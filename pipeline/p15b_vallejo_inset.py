# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "scipy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "trimesh",
#   "requests",
#   "shapely",
# ]
# ///
"""P1.5b: engraved WINDOW inset print (Carquinez / Vallejo / San Pablo Bay /
western Delta), same concept as p15_engraved.py but zoomed into the spot
where the four regions interact most intricately, at true 1:1,000,000.

Window (CA Albers EPSG:3310, km): a 160 x 160 km square centered on
(-185, -5), chosen so it contains San Pablo Bay, the Carquinez Strait
gate, the coast/valley/mountains triple junction around Suisun/Mt Diablo,
Vallejo/Benicia, and the western Sacramento-San Joaquin Delta.

  - HI-RES terrain: unlike p15_engraved.py (which slices the statewide
    250 m/zoom-9 heightfield), this driver fetches its OWN zoom-11
    terrarium tiles for just this window via dem_hires.py and resamples
    them straight onto the print grid (~120 m ground cells at 0.12 mm/px,
    1:1e6) -- the statewide DEM is too coarse (250 m -> 0.25 mm at this
    scale) to look good zoomed in this far;
  - region raster (250 m) still drives elevation/land-sea for the window;
  - GROOVES ARE VECTOR-DRAWN (same fix as p15_engraved.py): region-region
    borders come from p15_engraved.region_border_lines() (pairwise shared
    boundaries between the 4 mainland polygons in
    data/p2_regions_smooth.geojson), rasterized onto THIS window's print
    grid via p15_engraved.rasterize_lines() -- no more inheriting the
    250 m raster's staircase steps;
  - ocean/bay as a FLAT plane at datum height (top of the 2 mm base);
  - land z uses the SAME z_scale as p15_engraved.py (5 mm at CALIFORNIA's
    max elevation, computed the same way p15 computes it) -- NOT
    renormalized to this window's local max, so relief here matches the
    eventual full-state print;
  - ENGRAVED as ~0.4 mm wide x 0.4 mm deep grooves on region-region
    borders ONLY (no political borders in this window; no coastline
    engraving -- same rule as p15);
  - vertical walls on all four window edges (this is a cut window, not
    the coastline), flat bottom, watertight.
  - if the 0.12 mm/px mesh's predicted binary STL would exceed ~200 MB,
    falls back to 0.15 mm/px and says so.

Outputs:
  out/p15b_vallejo_inset.stl  binary STL, watertight
  out/p15b_preview.png        top-down (grooves) + oblique 3D view
  out/p15b_res_compare.png    OLD (250 m/zoom-9) vs NEW (zoom-11) oblique
                              shaded relief over the same ~25x25 km patch
                              around Mt Tamalpais
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import mesh_common as mc
import p15_engraved as p15  # reuse: build_source_rasters, resample,
                            # region_border_lines, rasterize_lines,
                            # render_preview, and the exact CA-wide
                            # z_scale computation
import dem_hires

# ---- window definition (CA Albers, km) -------------------------------------
# Bay Area window (ahl 2026-09-13: cover the larger Bay Area, not just
# Vallejo): Santa Rosa / Sonoma coast down past San Jose, ocean to the
# western Delta.
WIN_CX_KM = -185.0
WIN_CY_KM = -5.0
WIN_SIDE_KM = 160.0

# ---- print parameters (mm unless noted) ------------------------------------
PRINT_MM = 160.0        # square print, side = WIN_SIDE_KM -> exactly 1:1e6
DEM_ZOOM = 11            # terrarium zoom for THIS driver's own hi-res DEM
                         # fetch (dem_hires.py) -- p0/p15 use zoom 9/250 m,
                         # too coarse for a 1:1e6 zoomed-in inset
PX_MM = 0.12             # heightfield px size for THIS driver, set
                         # independently of p15's own statewide PX_MM;
                         # ~120 m ground cells at zoom 11 (0.12 mm * 1000
                         # m/mm-at-1:1e6)
PX_MM_FALLBACK = 0.15    # used instead of PX_MM if the predicted binary
                         # STL at PX_MM would exceed STL_SIZE_CAP_BYTES
STL_SIZE_CAP_BYTES = 200_000_000  # binary STL = 84 + 50*n_faces bytes

BASE_MM = p15.BASE_MM              # 2.0 mm base; ocean/bay datum = top of base
GROOVE_DEPTH_MM = p15.GROOVE_DEPTH_MM  # 0.4 mm
GROOVE_TARGET_MM = p15.GROOVE_TARGET_MM  # 0.4 mm target groove width
MIN_FLOOR_MM = p15.MIN_FLOOR_MM        # 1.0 mm groove-floor protection

STL_NAME = "p15b_vallejo_inset.stl"
PNG_NAME = "p15b_preview.png"
COMPARE_PNG_NAME = "p15b_res_compare.png"

# ---- resolution-comparison patch (ahl asked to see the DEM upgrade) --------
COMPARE_LON, COMPARE_LAT = -122.5965, 37.9235  # Mt Tamalpais summit
COMPARE_SIDE_KM = 25.0


def ca_wide_z_scale(reg_s, dem_s, sea_s):
    """Replicate p15_engraved.main()'s z_scale computation EXACTLY (same
    slab window, same resample, same CA-max-elevation definition), so this
    inset's relief matches the full-state print instead of being
    renormalized to the window's local max. Uses p15's OWN PX_MM (the
    statewide slab resolution) regardless of this driver's PX_MM."""
    win = p15.slab_window(reg_s > 0)
    reg_w, dem_w, sea_w = reg_s[win], dem_s[win], sea_s[win]
    h_src, w_src = dem_w.shape
    out_h = int(round(p15.NS_MM / p15.PX_MM))
    out_w = int(round(w_src * out_h / h_src))
    dem_p = p15.resample(np.where(sea_w, 0.0, dem_w), out_h, out_w, order=1)
    reg_p = p15.resample(reg_w, out_h, out_w, order=0)
    sea_p = p15.resample(sea_w.astype(np.uint8), out_h, out_w,
                         order=0).astype(bool)
    reg_p[sea_p] = 0
    max_elev_ca = float(dem_p[reg_p > 0].max())
    return p15.RELIEF_MM / max_elev_ca, max_elev_ca


def window_slice():
    """Source-grid (250 m) slice for the WIN_SIDE_KM square centered at
    (WIN_CX_KM, WIN_CY_KM) in CA Albers meters. Also returns the exact
    Albers bbox in meters -- used both to slice the 250 m region raster
    AND as the bbox handed to dem_hires for the hi-res DEM fetch."""
    half = WIN_SIDE_KM * 1000.0 / 2.0
    x0, x1 = WIN_CX_KM * 1000.0 - half, WIN_CX_KM * 1000.0 + half
    y0, y1 = WIN_CY_KM * 1000.0 - half, WIN_CY_KM * 1000.0 + half
    res = base.META["res"]
    col0 = int(round((x0 - base.META["x_min"]) / res))
    col1 = int(round((x1 - base.META["x_min"]) / res))
    row0 = int(round((base.META["y_max"] - y1) / res))  # north edge
    row1 = int(round((base.META["y_max"] - y0) / res))  # south edge
    return slice(row0, row1), slice(col0, col1), (x0, x1, y0, y1)


def build_print_grid(reg_s, dem_s, sea_s, z_scale, px_mm, lines_region):
    """Everything from the window bbox down to the finished mesh, at
    heightfield resolution px_mm. Fetches this window's OWN hi-res DEM
    via dem_hires (does not slice the statewide 250 m array). Grooves are
    vector-drawn from lines_region (p15_engraved.region_border_lines()),
    clipped to this window by rasterize_lines(). Returns (mesh, top,
    sea_p, groove, reg_p, stats)."""
    row_sl, col_sl, (x0, x1, y0, y1) = window_slice()
    reg_w = reg_s[row_sl, col_sl]
    sea_w = sea_s[row_sl, col_sl]
    from pyproj import Transformer
    to_ll = Transformer.from_crs(base.META["crs"], "EPSG:4326", always_xy=True)
    lon0, lat0 = to_ll.transform(x0, y0)
    lon1, lat1 = to_ll.transform(x1, y1)
    print(f"window: Albers x [{x0/1000:.1f}, {x1/1000:.1f}] km, "
          f"y [{y0/1000:.1f}, {y1/1000:.1f}] km "
          f"(center {WIN_CX_KM:.0f}, {WIN_CY_KM:.0f}; side {WIN_SIDE_KM:.0f} km); "
          f"lon/lat [{lon0:.3f}, {lon1:.3f}] x [{lat0:.3f}, {lat1:.3f}]")

    out_h = out_w = int(round(PRINT_MM / px_mm))
    out_res_m = (x1 - x0) / out_w
    print(f"print grid {out_h} x {out_w} px @ {px_mm} mm/px "
          f"-> {out_w * px_mm:.1f} x {out_h * px_mm:.1f} mm "
          f"(scale 1:{WIN_SIDE_KM * 1000 * 1000 / PRINT_MM:,.0f}); "
          f"ground cell {out_res_m:.1f} m (zoom {DEM_ZOOM})")

    dem_p, dem_meta, n_tiles = dem_hires.fetch_hires_dem(
        x0, x1, y0, y1, DEM_ZOOM, out_res_m)
    if dem_p.shape != (out_h, out_w):
        # rounding can land a row/col off the exact print grid; resample
        # rather than crop so the mesh always matches out_h x out_w
        dem_p = p15.resample(dem_p, out_h, out_w, order=1)

    reg_p = p15.resample(reg_w, out_h, out_w, order=0)
    sea_p = p15.resample(sea_w.astype(np.uint8), out_h, out_w,
                         order=0).astype(bool)
    reg_p[sea_p] = 0

    max_elev_win = float(dem_p[~sea_p].max()) if (~sea_p).any() else 0.0
    print(f"window max elevation: {max_elev_win:.0f} m -> "
          f"{max_elev_win * z_scale:.2f} mm of relief in this print "
          f"(base {BASE_MM} mm; total thickness up to "
          f"{BASE_MM + max_elev_win * z_scale:.2f} mm)")

    top = np.where(sea_p, BASE_MM, BASE_MM + dem_p * z_scale)

    width_px = max(1, round(GROOVE_TARGET_MM / px_mm))
    groove, border_km = p15.rasterize_lines(lines_region, row_sl, col_sl,
                                            out_h, out_w, width_px)
    gt = top[groove] - GROOVE_DEPTH_MM
    n_clamp = int((gt < MIN_FLOOR_MM).sum())
    top[groove] = np.maximum(gt, MIN_FLOOR_MM)
    print(f"grooves (vector-drawn): {int(groove.sum())} px lowered "
          f"(region borders {border_km:.1f} km ground length; width "
          f"{width_px} px = {width_px * px_mm:.2f} mm vs {GROOVE_TARGET_MM} "
          f"mm target); depth {GROOVE_DEPTH_MM} mm, floor clamped at "
          f"{MIN_FLOOR_MM} mm on {n_clamp} px")

    # node heights: mean everywhere, min next to grooves so the groove
    # keeps its full width and depth instead of averaging to a V
    mask = np.ones_like(sea_p)
    node_z = mc.node_heights(top, mask, "mean")
    node_min = mc.node_heights(top, mask, "min")
    gp = np.zeros((out_h + 2, out_w + 2), bool)
    gp[1:-1, 1:-1] = groove
    node_g = gp[:-1, :-1] | gp[:-1, 1:] | gp[1:, :-1] | gp[1:, 1:]
    node_z = np.where(node_g, node_min, node_z)

    mesh = mc.heightfield_to_mesh(top, mask, px_mm, node_z=node_z,
                                  bottom="fan")
    stats = dict(out_h=out_h, out_w=out_w, out_res_m=out_res_m,
                 n_tiles=n_tiles, max_elev_win=max_elev_win,
                 border_km=border_km, width_px=width_px)
    return mesh, top, sea_p, groove, reg_p, stats


def render_res_compare(dem_s, sea_s, px_mm, out_path):
    """Side-by-side: the OLD statewide 250 m/zoom-9 grid vs THIS driver's
    NEW zoom-11 fetch, over the same ~25x25 km patch around Mt Tamalpais,
    oblique shaded relief, so ahl can see what the DEM upgrade buys."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    cx, cy = base.TO_ALB.transform(COMPARE_LON, COMPARE_LAT)
    half = COMPARE_SIDE_KM * 1000.0 / 2.0
    x0, x1, y0, y1 = cx - half, cx + half, cy - half, cy + half

    res = base.META["res"]
    col0 = int(round((x0 - base.META["x_min"]) / res))
    col1 = int(round((x1 - base.META["x_min"]) / res))
    row0 = int(round((base.META["y_max"] - y1) / res))
    row1 = int(round((base.META["y_max"] - y0) / res))
    dem_old = dem_s[row0:row1, col0:col1]
    sea_old = sea_s[row0:row1, col0:col1]
    dem_old = np.where(sea_old, 0.0, dem_old).astype(np.float64)

    out_res_m = px_mm * 1000.0
    dem_new, meta_new, n_tiles = dem_hires.fetch_hires_dem(
        x0, x1, y0, y1, DEM_ZOOM, out_res_m)
    dem_new = dem_new.astype(np.float64)
    print(f"res-compare: fetched {n_tiles} tiles @ zoom {DEM_ZOOM} for the "
          f"{COMPARE_SIDE_KM:.0f} km comparison patch around Mt Tamalpais")

    vexag = 8.0  # visual-only exaggeration for this comparison figure
                  # (independent of the print's own z_scale)
    zmax_native = max(dem_old.max(), dem_new.max())

    fig = plt.figure(figsize=(13, 6.6), dpi=170)
    for i, (dem, cell_m, label, zoom) in enumerate([
            (dem_old, res, "OLD", 9),
            (dem_new, out_res_m, "NEW", DEM_ZOOM)]):
        h, w = dem.shape
        xs = np.arange(w) * cell_m / 1000.0
        ys = np.arange(h)[::-1] * cell_m / 1000.0
        X, Y = np.meshgrid(xs, ys)
        ax = fig.add_subplot(1, 2, i + 1, projection="3d")
        ax.plot_surface(X, Y, dem * vexag, cmap="gist_earth", rstride=1,
                        cstride=1, linewidth=0, antialiased=True,
                        vmin=0, vmax=zmax_native * vexag)
        # deliberately NOT true-proportioned (set_box_aspect would flatten
        # a 25 km run x ~800 m peak to a barely-visible sliver) -- let
        # matplotlib's default per-axis auto-scaling do the exaggeration,
        # shared zlim across both panels for a fair side-by-side
        ax.set_zlim(0, zmax_native * vexag)
        ax.view_init(elev=38, azim=-115)
        ax.set_title(f"{label}: {cell_m:.0f} m/px (zoom {zoom})\n"
                     f"{w} x {h} px over {COMPARE_SIDE_KM:.0f} km")
        ax.set_xlabel("km E")
        ax.set_ylabel("km N")
        ax.set_zticks([])
    fig.suptitle("Mt Tamalpais, same 25 x 25 km patch, z shown "
                 f"{vexag:.0f}x -- statewide 250 m DEM vs this inset's "
                 "own zoom-11 fetch")
    fig.tight_layout()
    base.OUT.mkdir(exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main():
    reg_s, dem_s, sea_s, n_holes, n_or = p15.build_source_rasters()
    print(f"interior no-region holes filled inside CA: {n_holes} cells; "
          f"non-CA sea stacks dropped: {n_or}")

    z_scale, max_elev_ca = ca_wide_z_scale(reg_s, dem_s, sea_s)
    print(f"CA-wide max elevation: {max_elev_ca:.0f} m -> z_scale "
          f"{z_scale * 1000:.4f} mm/km ({p15.RELIEF_MM} mm at that peak, "
          "same value p15_engraved.py uses -- NOT renormalized to this "
          "window)")

    lines_region = p15.region_border_lines()
    print(f"vector groove source: {len(lines_region)} region-border line "
          f"parts (data/p2_regions_smooth.geojson), clipped to this window")

    px_mm = PX_MM
    mesh, top, sea_p, groove, reg_p, stats = build_print_grid(
        reg_s, dem_s, sea_s, z_scale, px_mm, lines_region)

    predicted_bytes = 84 + 50 * len(mesh.faces)
    print(f"mesh @ {px_mm} mm/px: {len(mesh.faces):,} triangles -> "
          f"predicted binary STL {predicted_bytes / 1e6:.1f} MB")
    if predicted_bytes > STL_SIZE_CAP_BYTES:
        print(f"predicted STL exceeds the {STL_SIZE_CAP_BYTES / 1e6:.0f} MB "
              f"cap at {px_mm} mm/px -- falling back to "
              f"{PX_MM_FALLBACK} mm/px")
        px_mm = PX_MM_FALLBACK
        mesh, top, sea_p, groove, reg_p, stats = build_print_grid(
            reg_s, dem_s, sea_s, z_scale, px_mm, lines_region)

    print(f"mesh: {len(mesh.faces):,} triangles, "
          f"{len(mesh.vertices):,} vertices")
    print(f"watertight={mesh.is_watertight}  "
          f"winding_consistent={mesh.is_winding_consistent}  "
          f"euler={mesh.euler_number}")
    ext = mesh.extents
    print(f"bounding box: {ext[0]:.2f} x {ext[1]:.2f} x {ext[2]:.2f} mm "
          f"(E-W x N-S x thickness)")
    print(f"volume: {mesh.volume / 1000.0:.1f} cm^3")
    print(f"hi-res DEM: {stats['n_tiles']} tiles @ zoom {DEM_ZOOM}; "
          f"effective ground resolution {stats['out_res_m']:.1f} m/px; "
          f"grid {stats['out_h']} x {stats['out_w']} px")
    print(f"groove: {stats['border_km']:.1f} km ground length, "
          f"{stats['width_px']} px wide")

    base.OUT.mkdir(exist_ok=True)
    stl = base.OUT / STL_NAME
    mesh.export(stl)  # .stl -> binary by default in trimesh
    print(f"wrote {stl} ({stl.stat().st_size / 1e6:.1f} MB)")

    png = base.OUT / PNG_NAME
    p15.render_preview(top, sea_p, groove, reg_p, mesh, png, px_mm)
    print(f"wrote {png}")

    cmp_png = base.OUT / COMPARE_PNG_NAME
    render_res_compare(dem_s, sea_s, px_mm, cmp_png)
    print(f"wrote {cmp_png}")


if __name__ == "__main__":
    main()
