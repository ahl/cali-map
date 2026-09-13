# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "scipy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "trimesh",
#   "shapely",
# ]
# ///
"""P1.5: engraved one-piece validation print (rectangular slab).

A rectangular terrain slab — California's bounding box padded ~40 km on
the north, east and south (the west edge is already Pacific) — 150 mm
north-south, printed as one watertight solid:

  - real terrain for CA and its neighbors (same DEM, one z scale);
  - ocean as a FLAT plane at datum height (top of the 2 mm base), so the
    Channel Islands are included, sitting on the ocean surface;
  - ENGRAVED as ~0.4 mm wide x 0.4 mm deep grooves, drawn from VECTOR
    geometry (not the raster) so curves are smooth instead of jaggy:
      * region-region borders inside California, from the canonical P2
        polygons (data/p2_regions_smooth.geojson) — the pairwise shared
        boundary between each pair of the 4 mainland region polygons;
      * political borders (state lines + US-Mexico), from
        data/p2_borders.geojson — the same exact Census/NE-derived lines
        P2's own vectorization uses, instead of reading the raw Natural
        Earth shapefiles directly;
    the coastline itself is NOT engraved (it was never a raster diff
    against another region OR a p2_borders.geojson line, so it's
    excluded from both sources by construction, no threshold needed).

Purpose: ahl eyeballs the region borders against real terrain in hand
before the puzzle is cut.

Mesh pitch is 0.12 mm/px (statewide DEM stays 250 m/zoom-9 — at this
slab's ~1:7.6M scale that's 0.033 mm, nowhere near the bottleneck; only
the per-inset drivers like p15b need their own hi-res DEM fetch). Falls
back to 0.15 mm/px if the predicted binary STL would exceed ~200 MB.

Outputs:
  out/p15_ca_engraved_150mm.stl  binary STL, watertight
  out/p15_preview.png            top-down + oblique 3D + groove-quality
                                 zoom crop
"""

import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import shape as shp_shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import mesh_common as mc

# ---- print parameters (mm unless noted) -----------------------------------
NS_MM = 150.0          # north-south extent of the slab
PX_MM = 0.12           # heightfield pixel size (statewide DEM stays 250 m;
                       # see module docstring)
PX_MM_FALLBACK = 0.15  # used instead of PX_MM if the predicted binary STL
                       # at PX_MM would exceed STL_SIZE_CAP_BYTES
STL_SIZE_CAP_BYTES = 200_000_000  # binary STL = 84 + 50*n_faces bytes
BASE_MM = 2.0          # base thickness; ocean datum plane = top of base
RELIEF_MM = 5.0        # z_scale default: highest CA peak = this above base
GROOVE_DEPTH_MM = 0.4  # groove depth
GROOVE_TARGET_MM = 0.4  # target groove WIDTH; actual px width is whatever
                        # integer count of px is closest at this PX_MM
MIN_FLOOR_MM = 1.0     # groove floor never goes below this (base protection)
PAD_KM = 40.0          # slab margin beyond CA's bbox on N, E, S (not W)

STL_NAME = "p15_ca_engraved_150mm.stl"
PNG_NAME = "p15_preview.png"
REGIONS_GEOJSON = base.DATA / "p2_regions_smooth.geojson"
BORDERS_GEOJSON = base.DATA / "p2_borders.geojson"
OCEAN_RGB = (0.73, 0.82, 0.90)


# ---- vector groove geometry (EPSG:3310 meters) -----------------------------

def load_region_polygons():
    """Mainland region polygons (mountains/valley/desert/coast), EPSG:3310
    meters, from the canonical P2 vector geometry -- the Chaikin-smoothed
    'preview flavor' (data/p2_regions_smooth.geojson), i.e. the same
    curve a human eye judges the border by. Excludes region_id 5 (the
    islands piece): it's a separate piece that never shares a mainland
    border with these four."""
    gj = json.loads(REGIONS_GEOJSON.read_text())
    return {f["properties"]["region_id"]: shp_shape(f["geometry"])
            for f in gj["features"] if f["properties"]["region_id"] != 5}


def _iter_lines(geom):
    """Flatten a shapely geometry (possibly a GeometryCollection from a
    boundary intersection) down to its LineString parts; tangential
    single-point touches (Point/MultiPoint) are not grooves."""
    if geom.is_empty:
        return
    if geom.geom_type == "LineString":
        yield geom
    elif geom.geom_type in ("MultiLineString", "GeometryCollection"):
        for g in geom.geoms:
            yield from _iter_lines(g)


def region_border_lines():
    """Every pairwise shared boundary between the 4 mainland region
    polygons -- interior region-region borders ONLY. A pair's boundary
    intersection can only contain the stretch those two polygons
    actually share, so the coastline (only COAST's boundary touches open
    water) and the state-line/frame edges (none of the four polygons
    extends past CA) never appear here -- excluded by the geometry
    itself, no raster/threshold logic needed."""
    polys = load_region_polygons()
    ids = sorted(polys)
    lines = []
    for i in range(len(ids)):
        for j in range(i + 1, len(ids)):
            shared = polys[ids[i]].boundary.intersection(polys[ids[j]].boundary)
            lines.extend(_iter_lines(shared))
    return lines


def political_lines():
    """All state-line / international-border polylines in the map area,
    EPSG:3310 meters, from data/p2_borders.geojson -- the exact geometry
    P2's own region vectorization uses, instead of reading the raw
    Natural Earth shapefiles directly (so frame engraving and future
    piece edges share one source of truth)."""
    gj = json.loads(BORDERS_GEOJSON.read_text())
    return [shp_shape(f["geometry"]) for f in gj["features"]]


def rasterize_lines(lines, row_sl, col_sl, out_h, out_w, width_px):
    """Rasterize EPSG:3310-meter LineStrings onto a print grid as a
    GROOVE_W-px-wide boolean mask with round joints/caps. row_sl/col_sl =
    the window's slice on the 250 m source grid; out_h/out_w = the print
    grid covering that same window (may be a different resolution).
    Returns (mask, total_ground_length_km)."""
    img = Image.new("L", (out_w, out_h), 0)
    drw = ImageDraw.Draw(img)
    res = base.META["res"]
    x0, y1 = base.META["x_min"], base.META["y_max"]
    h_src = row_sl.stop - row_sl.start
    w_src = col_sl.stop - col_sl.start
    length_km = 0.0
    for ln in lines:
        xs, ys = np.asarray(ln.coords).T
        src_col = (xs - x0) / res
        src_row = (y1 - ys) / res
        px = (src_col - col_sl.start) * out_w / w_src
        py = (src_row - row_sl.start) * out_h / h_src
        inside = ((px > -width_px) & (px < out_w + width_px) &
                  (py > -width_px) & (py < out_h + width_px))
        if not inside.any():
            continue
        drw.line(list(zip(px.tolist(), py.tolist())), fill=1,
                 width=width_px, joint="curve")
        length_km += ln.length / 1000.0
    return np.asarray(img, bool), length_km


# ---- raster helpers (elevation / sea / region-fill, unchanged from before) -

def build_source_rasters():
    """Regenerate regions on the 250 m grid; fill interior no-region holes
    inside CA (CGS gaps near Suisun) so land/sea + region-id lookups stay
    complete. Returns (reg, dem, sea, n_hole_cells) on the full source
    grid. (Grooves no longer come from this raster -- see
    region_border_lines/political_lines above -- but the raster still
    drives elevation, land/sea, and the CA-max-elevation z_scale.)"""
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    prov, name_id = base.rasterize_provinces()
    sea = base.ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea)
    reg, _ = base.build_regions(dem, prov, name_id,
                                base.CFG["coast_threshold_m"],
                                band_km=base.CFG["coast_band_km"],
                                shore_dist=shore_dist)
    mainland = mc.largest_component(reg > 0)
    _, holes = mc.fill_interior_holes(mainland)
    if holes.any():
        reg = np.where(holes, mc.fill_nearest(reg, mainland), reg)

    # the interim island rule (p1_regions.ca_islands: lat >= 32.6) also
    # grabs Oregon sea stacks up at ~43 N, which would stretch the slab
    # window ~180 km north; drop island components north of the 42 N
    # state line (they are not California)
    from pyproj import Transformer
    to_ll = Transformer.from_crs(base.META["crs"], "EPSG:4326",
                                 always_xy=True)
    lab, n = ndimage.label((reg > 0) & ~mainland)
    n_or = 0
    for i in range(1, n + 1):
        cy, cx = ndimage.center_of_mass(lab == i)
        y = base.META["y_max"] - (cy + 0.5) * base.META["res"]
        x = base.META["x_min"] + (cx + 0.5) * base.META["res"]
        if to_ll.transform(x, y)[1] > 42.0:
            reg[lab == i] = 0
            n_or += 1
    return reg, dem, sea, int(holes.sum()), n_or


def slab_window(ca):
    """Source-grid slice for the slab: CA bbox + PAD_KM on N, E, S."""
    pad = int(round(PAD_KM * 1000.0 / base.META["res"]))
    rows = np.nonzero(ca.any(axis=1))[0]
    cols = np.nonzero(ca.any(axis=0))[0]
    r0 = max(rows[0] - pad, 0)
    r1 = min(rows[-1] + 1 + pad, ca.shape[0])
    c0 = cols[0]                                   # west: already Pacific
    c1 = min(cols[-1] + 1 + pad, ca.shape[1])
    return slice(r0, r1), slice(c0, c1)


def resample(arr, out_h, out_w, order):
    h, w = arr.shape
    rr = (np.arange(out_h) + 0.5) * h / out_h - 0.5
    cc = (np.arange(out_w) + 0.5) * w / out_w - 0.5
    return ndimage.map_coordinates(arr, np.meshgrid(rr, cc, indexing="ij"),
                                   order=order)


# ---- build + preview -------------------------------------------------------

def build(px_mm, reg_s, dem_s, sea_s, win, lines_region, lines_political):
    """Everything from the (already-sliced) slab window down to the
    finished mesh, at heightfield resolution px_mm. Returns (mesh, top,
    sea_p, groove, reg_p, stats)."""
    row_sl, col_sl = win
    reg_w, dem_w, sea_w = reg_s[win], dem_s[win], sea_s[win]
    h_src, w_src = dem_w.shape

    ns_ground_m = h_src * base.META["res"]
    scale_den = ns_ground_m * 1000.0 / NS_MM
    out_h = int(round(NS_MM / px_mm))
    out_w = int(round(w_src * out_h / h_src))

    # sea floor must not bleed into coastal land during bilinear resampling
    dem_p = resample(np.where(sea_w, 0.0, dem_w), out_h, out_w, order=1)
    reg_p = resample(reg_w, out_h, out_w, order=0)
    sea_p = resample(sea_w.astype(np.uint8), out_h, out_w, order=0).astype(bool)
    reg_p[sea_p] = 0
    print(f"print grid {out_h} x {out_w} px @ {px_mm} mm/px")

    ca_rows = np.nonzero((reg_p > 0).any(axis=1))[0]
    max_elev_ca = float(dem_p[reg_p > 0].max())
    max_elev_win = float(dem_p[~sea_p].max())
    z_scale = RELIEF_MM / max_elev_ca            # mm per meter of elevation
    horiz = 1000.0 / scale_den                   # mm per meter of ground
    print(f"scale 1:{scale_den:,.0f}; slab {out_w * px_mm:.1f} mm E-W x "
          f"{NS_MM:.0f} mm N-S; CA spans {len(ca_rows) * px_mm:.1f} mm N-S")
    print(f"max elev: CA {max_elev_ca:.0f} m -> {RELIEF_MM} mm relief "
          f"(window max {max_elev_win:.0f} m -> "
          f"{max_elev_win * z_scale:.2f} mm); "
          f"vertical exaggeration {z_scale / horiz:.1f}x")

    top = np.where(sea_p, BASE_MM, BASE_MM + dem_p * z_scale)

    width_px = max(1, round(GROOVE_TARGET_MM / px_mm))
    g_reg, border_km = rasterize_lines(lines_region, row_sl, col_sl,
                                       out_h, out_w, width_px)
    g_pol, pol_km = rasterize_lines(lines_political, row_sl, col_sl,
                                    out_h, out_w, width_px)
    groove = g_reg | g_pol
    gt = top[groove] - GROOVE_DEPTH_MM
    n_clamp = int((gt < MIN_FLOOR_MM).sum())
    top[groove] = np.maximum(gt, MIN_FLOOR_MM)
    print(f"grooves (vector-drawn): {int(groove.sum())} px lowered "
          f"(region borders {border_km:.1f} km, political {pol_km:.1f} km "
          f"ground length; width {width_px} px = {width_px * px_mm:.2f} mm "
          f"vs {GROOVE_TARGET_MM} mm target); depth {GROOVE_DEPTH_MM} mm, "
          f"floor clamped at {MIN_FLOOR_MM} mm on {n_clamp} px")

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
    stats = dict(out_h=out_h, out_w=out_w, scale_den=scale_den,
                 border_km=border_km, pol_km=pol_km, width_px=width_px)
    return mesh, top, sea_p, groove, reg_p, stats


def render_preview(top, sea, groove, reg, mesh_full, out_path, px_mm):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    fig = plt.figure(figsize=(24, 9.5), dpi=130)
    h, w = top.shape

    # -- panel 1: top-down, grooves visible ---------------------------------
    ax = fig.add_subplot(1, 3, 1)
    ls = LightSource(azdeg=315, altdeg=45)
    shade = ls.hillshade(top, vert_exag=3, dx=px_mm, dy=px_mm)
    rgb = np.dstack([shade] * 3) * 0.6 + 0.4
    for rid, col in base.COLORS.items():
        m = reg == rid
        for ch in range(3):
            rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.72 + col[ch] * 0.28
    rgb[sea] = OCEAN_RGB
    rgb[groove] = (0.05, 0.05, 0.05)
    ax.imshow(rgb, extent=[0, w * px_mm, 0, h * px_mm])
    ax.set_title(f"top-down  ({w * px_mm:.1f} x {h * px_mm:.1f} mm slab, "
                 "grooves black)")
    ax.set_xlabel("mm (E-W)")
    ax.set_ylabel("mm (S-N)")

    # -- panel 2: oblique 3D on a decimated copy ----------------------------
    ds = 3
    mesh_d = mc.heightfield_to_mesh(top[::ds, ::ds],
                                    np.ones_like(top[::ds, ::ds], bool),
                                    px_mm * ds, bottom="fan")
    v, f = mesh_d.vertices, mesh_d.faces
    # drop the bottom fan: its slab-sized z=0 triangles defeat matplotlib's
    # painter-algorithm depth sort and get drawn over the terrain
    f = f[~(v[f][:, :, 2] < 1e-9).all(axis=1)]
    ax2 = fig.add_subplot(1, 3, 2, projection="3d")
    ax2.plot_trisurf(v[:, 0], v[:, 1], f, v[:, 2], cmap="gist_earth",
                     linewidth=0, antialiased=False,
                     vmin=BASE_MM - 1.5, vmax=float(top.max()))
    ext = mesh_full.extents
    ax2.set_box_aspect((ext[0], ext[1], ext[2] * 4))
    ax2.view_init(elev=40, azim=-110)
    ax2.set_title(f"oblique (z shown 4x; real thickness {ext[2]:.1f} mm max)")
    ax2.set_xlabel("mm E")
    ax2.set_ylabel("mm N")

    # -- panel 3: groove-quality zoom crop -----------------------------------
    # crop centered on the median groove pixel (typically near a
    # region-junction, and always ON a groove) so curve smoothness is
    # visible at native pixel resolution
    ax3 = fig.add_subplot(1, 3, 3)
    gy, gx = np.nonzero(groove)
    cy0, cx0 = (int(np.median(gy)), int(np.median(gx))) if gy.size else (h // 2, w // 2)
    half_px = int(round(15.0 / px_mm))  # ~30x30 mm crop
    r0, r1 = max(cy0 - half_px, 0), min(cy0 + half_px, h)
    c0, c1 = max(cx0 - half_px, 0), min(cx0 + half_px, w)
    ax3.imshow(rgb[r0:r1, c0:c1],
              extent=[c0 * px_mm, c1 * px_mm, (h - r1) * px_mm, (h - r0) * px_mm])
    ax3.set_title(f"groove-quality crop ({(c1 - c0) * px_mm:.0f} x "
                 f"{(r1 - r0) * px_mm:.0f} mm @ {px_mm} mm/px)")
    ax3.set_xlabel("mm (E-W)")
    ax3.set_ylabel("mm (S-N)")

    fig.tight_layout()
    base.OUT.mkdir(exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main():
    reg_s, dem_s, sea_s, n_holes, n_or = build_source_rasters()
    print(f"interior no-region holes filled inside CA: {n_holes} cells "
          f"({n_holes * 0.0625:.1f} km^2); non-CA sea stacks (>42 N) "
          f"dropped from the region raster: {n_or}")

    win = slab_window(reg_s > 0)

    lines_region = region_border_lines()
    lines_political = political_lines()
    print(f"vector groove sources: {len(lines_region)} region-border line "
          f"parts (data/p2_regions_smooth.geojson), "
          f"{len(lines_political)} political line parts "
          f"(data/p2_borders.geojson)")

    px_mm = PX_MM
    mesh, top, sea_p, groove, reg_p, stats = build(
        px_mm, reg_s, dem_s, sea_s, win, lines_region, lines_political)

    predicted_bytes = 84 + 50 * len(mesh.faces)
    print(f"mesh @ {px_mm} mm/px: {len(mesh.faces):,} triangles -> "
          f"predicted binary STL {predicted_bytes / 1e6:.1f} MB")
    if predicted_bytes > STL_SIZE_CAP_BYTES:
        print(f"predicted STL exceeds the {STL_SIZE_CAP_BYTES / 1e6:.0f} MB "
              f"cap at {px_mm} mm/px -- falling back to "
              f"{PX_MM_FALLBACK} mm/px")
        px_mm = PX_MM_FALLBACK
        mesh, top, sea_p, groove, reg_p, stats = build(
            px_mm, reg_s, dem_s, sea_s, win, lines_region, lines_political)

    print(f"mesh: {len(mesh.faces):,} triangles, "
          f"{len(mesh.vertices):,} vertices")
    print(f"watertight={mesh.is_watertight}  "
          f"winding_consistent={mesh.is_winding_consistent}  "
          f"euler={mesh.euler_number}")
    ext = mesh.extents
    print(f"bounding box: {ext[0]:.2f} x {ext[1]:.2f} x {ext[2]:.2f} mm "
          f"(E-W x N-S x thickness)")
    print(f"volume: {mesh.volume / 1000.0:.1f} cm^3")

    base.OUT.mkdir(exist_ok=True)
    stl = base.OUT / STL_NAME
    mesh.export(stl)  # .stl -> binary by default in trimesh
    print(f"wrote {stl} ({stl.stat().st_size / 1e6:.1f} MB)")

    png = base.OUT / PNG_NAME
    render_preview(top, sea_p, groove, reg_p, mesh, png, px_mm)
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
