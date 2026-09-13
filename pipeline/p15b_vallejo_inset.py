# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "scipy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "trimesh",
# ]
# ///
"""P1.5b: engraved WINDOW inset print (Carquinez / Vallejo / San Pablo Bay /
western Delta), same concept as p15_engraved.py but zoomed into the spot
where the four regions interact most intricately, at true 1:1,000,000.

Window (CA Albers EPSG:3310, km): a 120 x 120 km square centered on
(-185, +15), chosen so it contains San Pablo Bay, the Carquinez Strait
gate, the coast/valley/mountains triple junction around Suisun/Mt Diablo,
Vallejo/Benicia, and the western Sacramento-San Joaquin Delta.

  - real terrain, same DEM;
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

Outputs:
  out/p15b_vallejo_inset.stl  binary STL, watertight
  out/p15b_preview.png        top-down (grooves) + oblique 3D view
"""

import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import mesh_common as mc
import p15_engraved as p15  # reuse: build_source_rasters, resample,
                            # region_groove, render_preview, and the
                            # exact CA-wide z_scale computation

# ---- window definition (CA Albers, km) -------------------------------------
# Bay Area window (ahl 2026-09-13: cover the larger Bay Area, not just
# Vallejo): Santa Rosa / Sonoma coast down past San Jose, ocean to the
# western Delta.
WIN_CX_KM = -185.0
WIN_CY_KM = -5.0
WIN_SIDE_KM = 160.0

# ---- print parameters (mm unless noted) ------------------------------------
PRINT_MM = 160.0        # square print, side = WIN_SIDE_KM -> exactly 1:1e6
PX_MM = p15.PX_MM        # 0.2 mm/px heightfield, same as p15
BASE_MM = p15.BASE_MM    # 2.0 mm base; ocean/bay datum = top of base
GROOVE_DEPTH_MM = p15.GROOVE_DEPTH_MM  # 0.4 mm
GROOVE_W_PX = p15.GROOVE_W_PX          # 2 px -> 0.4 mm wide
MIN_FLOOR_MM = p15.MIN_FLOOR_MM        # 1.0 mm groove-floor protection

STL_NAME = "p15b_vallejo_inset.stl"
PNG_NAME = "p15b_preview.png"


def ca_wide_z_scale(reg_s, dem_s, sea_s):
    """Replicate p15_engraved.main()'s z_scale computation EXACTLY (same
    slab window, same resample, same CA-max-elevation definition), so this
    inset's relief matches the full-state print instead of being
    renormalized to the window's local max."""
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
    (WIN_CX_KM, WIN_CY_KM) in CA Albers meters."""
    half = WIN_SIDE_KM * 1000.0 / 2.0
    x0, x1 = WIN_CX_KM * 1000.0 - half, WIN_CX_KM * 1000.0 + half
    y0, y1 = WIN_CY_KM * 1000.0 - half, WIN_CY_KM * 1000.0 + half
    res = base.META["res"]
    col0 = int(round((x0 - base.META["x_min"]) / res))
    col1 = int(round((x1 - base.META["x_min"]) / res))
    row0 = int(round((base.META["y_max"] - y1) / res))  # north edge
    row1 = int(round((base.META["y_max"] - y0) / res))  # south edge
    return slice(row0, row1), slice(col0, col1), (x0, x1, y0, y1)


def main():
    reg_s, dem_s, sea_s, n_holes, n_or = p15.build_source_rasters()
    print(f"interior no-region holes filled inside CA: {n_holes} cells; "
          f"non-CA sea stacks dropped: {n_or}")

    z_scale, max_elev_ca = ca_wide_z_scale(reg_s, dem_s, sea_s)
    print(f"CA-wide max elevation: {max_elev_ca:.0f} m -> z_scale "
          f"{z_scale * 1000:.4f} mm/km ({p15.RELIEF_MM} mm at that peak, "
          "same value p15_engraved.py uses -- NOT renormalized to this "
          "window)")

    row_sl, col_sl, (x0, x1, y0, y1) = window_slice()
    reg_w = reg_s[row_sl, col_sl]
    dem_w = dem_s[row_sl, col_sl]
    sea_w = sea_s[row_sl, col_sl]
    h_src, w_src = dem_w.shape
    from pyproj import Transformer
    to_ll = Transformer.from_crs(base.META["crs"], "EPSG:4326", always_xy=True)
    lon0, lat0 = to_ll.transform(x0, y0)
    lon1, lat1 = to_ll.transform(x1, y1)
    print(f"window: Albers x [{x0/1000:.1f}, {x1/1000:.1f}] km, "
          f"y [{y0/1000:.1f}, {y1/1000:.1f}] km "
          f"(center {WIN_CX_KM:.0f}, {WIN_CY_KM:.0f}; side {WIN_SIDE_KM:.0f} km); "
          f"lon/lat [{lon0:.3f}, {lon1:.3f}] x [{lat0:.3f}, {lat1:.3f}]")
    print(f"source-grid window: {h_src} x {w_src} px @ 250 m")

    out_h = out_w = int(round(PRINT_MM / PX_MM))
    print(f"print grid {out_h} x {out_w} px @ {PX_MM} mm/px "
          f"-> {out_w * PX_MM:.1f} x {out_h * PX_MM:.1f} mm "
          f"(scale 1:{WIN_SIDE_KM * 1000 * 1000 / PRINT_MM:,.0f})")

    dem_p = p15.resample(np.where(sea_w, 0.0, dem_w), out_h, out_w, order=1)
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

    g_reg, border_mm = p15.region_groove(reg_p)
    groove = g_reg
    gt = top[groove] - GROOVE_DEPTH_MM
    n_clamp = int((gt < MIN_FLOOR_MM).sum())
    top[groove] = np.maximum(gt, MIN_FLOOR_MM)
    print(f"grooves: {int(groove.sum())} px lowered (region borders "
          f"{border_mm:.0f} mm total groove length); depth "
          f"{GROOVE_DEPTH_MM} mm, floor clamped at {MIN_FLOOR_MM} mm on "
          f"{n_clamp} px")

    # node heights: mean everywhere, min next to grooves so the 2-px slot
    # keeps its full 0.4 mm width and depth instead of averaging to a V
    mask = np.ones_like(sea_p)
    node_z = mc.node_heights(top, mask, "mean")
    node_min = mc.node_heights(top, mask, "min")
    gp = np.zeros((out_h + 2, out_w + 2), bool)
    gp[1:-1, 1:-1] = groove
    node_g = gp[:-1, :-1] | gp[:-1, 1:] | gp[1:, :-1] | gp[1:, 1:]
    node_z = np.where(node_g, node_min, node_z)

    mesh = mc.heightfield_to_mesh(top, mask, PX_MM, node_z=node_z,
                                  bottom="fan")
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
    p15.render_preview(top, sea_p, groove, reg_p, mesh, png)
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
