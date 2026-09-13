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
"""P1.5: engraved one-piece validation print.

California as ONE contiguous solid, 150 mm north-south, with the four-
region borders engraved as narrow recesses in the top surface, so ahl can
eyeball the borders against real terrain before any puzzle cutting.

Regions are REGENERATED from config.toml + p1_regions.build_regions
(currently 25 m threshold + 13 km band, all rules incl. contiguity) —
no stale data/*.npy snapshots.

Outputs:
  out/p15_ca_engraved_150mm.stl  binary STL, watertight
  out/p15_preview.png            top-down (grooves) + oblique 3D view
"""

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import mesh_common as mc

# ---- print parameters (mm unless noted) -----------------------------------
NS_MM = 150.0          # north-south extent of the mainland
PX_MM = 0.2            # heightfield pixel size (one 0.4 mm nozzle ~ 2 px)
BASE_MM = 2.0          # flat base thickness under sea level (elev 0)
RELIEF_MM = 5.0        # top of the highest peak above the base
GROOVE_DEPTH_MM = 0.4  # 2 layers @ 0.2 mm
GROOVE_HALF_PX = 1     # cells within 1 px (0.2 mm) of a border are lowered
MIN_FLOOR_MM = 1.0     # groove floor never goes below this (base protection)

STL_NAME = "p15_ca_engraved_150mm.stl"
PNG_NAME = "p15_preview.png"


def build_source_raster():
    """Regenerate the region raster, keep the mainland only, fill interior
    no-region holes. Returns (reg, dem_filled, mask, stats) on the source
    250 m grid, cropped to the mainland bounding box."""
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    prov, name_id = base.rasterize_provinces()
    sea = base.ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea)
    reg, _ = base.build_regions(dem, prov, name_id,
                                base.CFG["coast_threshold_m"],
                                band_km=base.CFG["coast_band_km"],
                                shore_dist=shore_dist)

    ca = reg > 0
    mainland = mc.largest_component(ca, connectivity=1)
    dropped = ca & ~mainland
    _, n_drop_comp = ndimage.label(dropped)
    reg = np.where(mainland, reg, 0).astype(np.uint8)

    mask, holes = mc.fill_interior_holes(mainland)
    if holes.any():
        reg = np.where(holes, mc.fill_nearest(reg, mainland), reg)

    # elevation defined everywhere (nearest land value) so bilinear
    # resampling never blends in sea-floor bathymetry at the coast
    dem_filled = mc.fill_nearest(dem, mask)

    rows = np.nonzero(mask.any(axis=1))[0]
    cols = np.nonzero(mask.any(axis=0))[0]
    sl = (slice(rows[0], rows[-1] + 1), slice(cols[0], cols[-1] + 1))
    stats = {
        "dropped_cells": int(dropped.sum()),
        "dropped_components": int(n_drop_comp),
        "hole_cells_src": int(holes.sum()),
        "src_shape": (int(rows[-1] - rows[0] + 1), int(cols[-1] - cols[0] + 1)),
    }
    return reg[sl], dem_filled[sl], mask[sl], stats


def resample_to_print(reg, dem, mask, out_h):
    """Nearest-region / bilinear-elevation resample onto the print grid."""
    h, w = mask.shape
    out_w = int(round(w * out_h / h))
    rr = (np.arange(out_h) + 0.5) * h / out_h - 0.5
    cc = (np.arange(out_w) + 0.5) * w / out_w - 0.5
    grid = np.meshgrid(rr, cc, indexing="ij")
    dem_p = ndimage.map_coordinates(dem, grid, order=1)
    reg_p = ndimage.map_coordinates(reg, grid, order=0)
    reg_p[~ndimage.map_coordinates(mask.astype(np.uint8), grid, order=0)
          .astype(bool)] = 0
    return reg_p, dem_p


def engrave(reg, mask):
    """Groove mask + border length: cells adjacent to an edge between two
    DIFFERENT land regions (coastline excluded)."""
    dh = mask[:, :-1] & mask[:, 1:] & (reg[:, :-1] != reg[:, 1:])
    dv = mask[:-1] & mask[1:] & (reg[:-1] != reg[1:])
    groove = np.zeros_like(mask)
    groove[:, :-1] |= dh
    groove[:, 1:] |= dh
    groove[:-1] |= dv
    groove[1:] |= dv
    length_mm = (int(dh.sum()) + int(dv.sum())) * PX_MM
    return groove & mask, length_mm


def render_preview(top, mask, groove, reg, mesh_full, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    fig = plt.figure(figsize=(16, 10), dpi=130)

    # -- panel 1: top-down, grooves visible ---------------------------------
    ax = fig.add_subplot(1, 2, 1)
    ls = LightSource(azdeg=315, altdeg=45)
    z = np.where(mask, top, np.nan)
    shade = ls.hillshade(np.where(mask, top, 0.0), vert_exag=3,
                         dx=PX_MM, dy=PX_MM)
    rgb = np.dstack([shade] * 3) * 0.6 + 0.4
    for rid, col in base.COLORS.items():
        m = mask & (reg == rid)
        for ch in range(3):
            rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.72 + col[ch] * 0.28
    rgb[~mask] = (1.0, 1.0, 1.0)
    rgb[groove] = (0.05, 0.05, 0.05)
    h, w = mask.shape
    ax.imshow(rgb, extent=[0, w * PX_MM, 0, h * PX_MM])
    ax.set_title(f"top-down  ({w * PX_MM:.1f} x {h * PX_MM:.1f} mm, "
                 "grooves black)")
    ax.set_xlabel("mm (E-W)")
    ax.set_ylabel("mm (S-N)")

    # -- panel 2: oblique 3D on a decimated copy ----------------------------
    ds = 3
    mask_d, _ = mc.remove_diagonal_pinches(mask[::ds, ::ds])
    mesh_d = mc.heightfield_to_mesh(top[::ds, ::ds], mask_d, PX_MM * ds)
    v, f = mesh_d.vertices, mesh_d.faces
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    ax2.plot_trisurf(v[:, 0], v[:, 1], f, v[:, 2], cmap="gist_earth",
                     linewidth=0, antialiased=False,
                     vmin=-2.0, vmax=float(np.nanmax(z)))
    ext = mesh_full.extents
    ax2.set_box_aspect((ext[0], ext[1], ext[2] * 4))
    ax2.view_init(elev=38, azim=-115)
    ax2.set_title(f"oblique (z shown 4x; actual max thickness "
                  f"{ext[2]:.1f} mm)")
    ax2.set_xlabel("mm E")
    ax2.set_ylabel("mm N")

    fig.tight_layout()
    base.OUT.mkdir(exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
    plt.close(fig)


def main():
    reg_s, dem_s, mask_s, st = build_source_raster()
    print(f"source crop: {st['src_shape'][0]} x {st['src_shape'][1]} px @ 250 m")
    print(f"dropped offshore/disconnected: {st['dropped_components']} "
          f"components, {st['dropped_cells']} cells "
          f"({st['dropped_cells'] * 0.0625:.0f} km^2)")
    print(f"interior no-region holes filled (source): {st['hole_cells_src']} cells")

    ns_ground_m = st["src_shape"][0] * base.META["res"]
    scale_den = ns_ground_m * 1000.0 / NS_MM
    out_h = int(round(NS_MM / PX_MM))
    reg_p, dem_p = resample_to_print(reg_s, dem_s, mask_s, out_h)

    # print-grid mask cleanup: one 4-connected piece, no voids, no pinches
    mask_p = reg_p > 0
    kept = mc.largest_component(mask_p)
    n_speck = int((mask_p & ~kept).sum())
    mask_p = kept
    mask_p, holes_p = mc.fill_interior_holes(mask_p)
    mask_p, n_pinch = mc.remove_diagonal_pinches(mask_p)
    need = mask_p & (reg_p == 0)
    if need.any():
        reg_p = np.where(need, mc.fill_nearest(reg_p, reg_p > 0), reg_p)
    reg_p[~mask_p] = 0
    print(f"print grid {mask_p.shape[0]} x {mask_p.shape[1]} px @ {PX_MM} mm: "
          f"dropped {n_speck} resample specks, filled {int(holes_p.sum())} "
          f"hole px + {n_pinch} pinch px")

    rows = np.nonzero(mask_p.any(axis=1))[0]
    cols = np.nonzero(mask_p.any(axis=0))[0]
    ns_mm = (rows[-1] - rows[0] + 1) * PX_MM
    ew_mm = (cols[-1] - cols[0] + 1) * PX_MM

    max_elev = float(dem_p[mask_p].max())
    z_scale = RELIEF_MM / max_elev              # mm per meter of elevation
    horiz = 1000.0 / scale_den                  # mm per meter of ground
    print(f"scale 1:{scale_den:,.0f}  ({ns_mm:.1f} mm N-S x {ew_mm:.1f} mm "
          f"E-W); max elev {max_elev:.0f} m -> {RELIEF_MM} mm relief; "
          f"vertical exaggeration {z_scale / horiz:.1f}x")

    top = BASE_MM + dem_p * z_scale
    groove, border_mm = engrave(reg_p, mask_p)
    gt = top[groove] - GROOVE_DEPTH_MM
    n_clamp = int((gt < MIN_FLOOR_MM).sum())
    top[groove] = np.maximum(gt, MIN_FLOOR_MM)
    print(f"grooves: {int(groove.sum())} px lowered, border length "
          f"{border_mm:.0f} mm, depth {GROOVE_DEPTH_MM} mm, "
          f"floor clamped at {MIN_FLOOR_MM} mm on {n_clamp} px")

    # node heights: mean everywhere, min next to grooves so the 2-px slot
    # keeps its full 0.4 mm width and depth instead of averaging to a V
    node_z = mc.node_heights(top, mask_p, "mean")
    node_min = mc.node_heights(top, mask_p, "min")
    h, w = mask_p.shape
    gp = np.zeros((h + 2, w + 2), bool)
    gp[1:-1, 1:-1] = groove
    node_g = gp[:-1, :-1] | gp[:-1, 1:] | gp[1:, :-1] | gp[1:, 1:]
    node_z = np.where(node_g, node_min, node_z)

    mesh = mc.heightfield_to_mesh(top, mask_p, PX_MM, node_z=node_z)
    print(f"mesh: {len(mesh.faces):,} triangles, {len(mesh.vertices):,} "
          f"vertices")
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
    render_preview(top, mask_p, groove, reg_p, mesh, png)
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
