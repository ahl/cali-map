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
"""P1.5: engraved one-piece validation print (rectangular slab).

A rectangular terrain slab — California's bounding box padded ~40 km on
the north, east and south (the west edge is already Pacific) — 150 mm
north-south, printed as one watertight solid:

  - real terrain for CA and its neighbors (same DEM, one z scale);
  - ocean as a FLAT plane at datum height (top of the 2 mm base), so the
    Channel Islands are included, sitting on the ocean surface;
  - ENGRAVED as ~0.4 mm wide x 0.4 mm deep grooves:
      * the four-region borders inside California (region-region edges
        only, regenerated via p1_regions.build_regions — no stale .npy),
      * political borders (state lines + US-Mexico) from Natural Earth
        10m shapefiles in data/ne_borders/;
    the coastline itself is NOT engraved.

Purpose: ahl eyeballs the region borders against real terrain in hand
before the puzzle is cut.

Outputs:
  out/p15_ca_engraved_150mm.stl  binary STL, watertight
  out/p15_preview.png            top-down (grooves) + oblique 3D view
"""

import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import mesh_common as mc

# ---- print parameters (mm unless noted) -----------------------------------
NS_MM = 150.0          # north-south extent of the slab
PX_MM = 0.2            # heightfield pixel size
BASE_MM = 2.0          # base thickness; ocean datum plane = top of base
RELIEF_MM = 5.0        # z_scale default: highest CA peak = this above base
GROOVE_DEPTH_MM = 0.4  # 2 layers @ 0.2 mm
GROOVE_W_PX = 2        # total groove width in px (~0.4 mm)
MIN_FLOOR_MM = 1.0     # groove floor never goes below this (base protection)
PAD_KM = 40.0          # slab margin beyond CA's bbox on N, E, S (not W)

STL_NAME = "p15_ca_engraved_150mm.stl"
PNG_NAME = "p15_preview.png"
SHP_DIR = base.DATA / "ne_borders"
OCEAN_RGB = (0.73, 0.82, 0.90)


def read_shp_polylines(path):
    """Minimal ESRI shapefile reader: returns the parts of every PolyLine/
    PolyLineZ record as a list of (N, 2) lon/lat arrays. Geometry only —
    no .dbf attributes needed, we clip by the slab window instead."""
    buf = Path(path).read_bytes()
    parts_out = []
    pos = 100  # main file header
    while pos < len(buf):
        (clen,) = struct.unpack(">i", buf[pos + 4:pos + 8])
        rec = buf[pos + 8:pos + 8 + 2 * clen]
        pos += 8 + 2 * clen
        (stype,) = struct.unpack("<i", rec[:4])
        if stype in (3, 13, 23):  # PolyLine, Z, M
            nparts, npts = struct.unpack("<2i", rec[36:44])
            off = 44
            starts = np.frombuffer(rec, "<i4", nparts, off)
            off += 4 * nparts
            xy = np.frombuffer(rec, "<f8", 2 * npts, off).reshape(-1, 2)
            bounds = np.append(starts, npts)
            for a, b in zip(bounds[:-1], bounds[1:]):
                parts_out.append(xy[a:b])
    return parts_out


def build_source_rasters():
    """Regenerate regions on the 250 m grid; fill interior no-region holes
    inside CA (CGS gaps near Suisun) so region borders are continuous.
    Returns (reg, dem, sea, n_hole_cells) on the full source grid."""
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


def region_groove(reg):
    """Groove cells + border length (mm) for edges between two DIFFERENT
    land regions. Coastline / state line (reg==0 outside) excluded."""
    m = reg > 0
    dh = m[:, :-1] & m[:, 1:] & (reg[:, :-1] != reg[:, 1:])
    dv = m[:-1] & m[1:] & (reg[:-1] != reg[1:])
    g = np.zeros_like(m)
    g[:, :-1] |= dh
    g[:, 1:] |= dh
    g[:-1] |= dv
    g[1:] |= dv
    return g, (int(dh.sum()) + int(dv.sum())) * PX_MM


def political_groove(win_sl, out_h, out_w):
    """Rasterize Natural Earth state lines + international borders (clipped
    to the slab window) as GROOVE_W_PX-wide lines on the print grid.
    Returns (mask, approx_length_mm)."""
    r_sl, c_sl = win_sl
    h_src = r_sl.stop - r_sl.start
    w_src = c_sl.stop - c_sl.start
    lon0, lon1 = base.META["lon_range"]
    lat0, lat1 = base.META["lat_range"]
    img = Image.new("L", (out_w, out_h), 0)
    drw = ImageDraw.Draw(img)
    length_m = 0.0
    for shp in ("ne_10m_admin_1_states_provinces_lines.shp",
                "ne_10m_admin_0_boundary_lines_land.shp"):
        for part in read_shp_polylines(SHP_DIR / shp):
            if (part[:, 0].max() < lon0 - 1 or part[:, 0].min() > lon1 + 1 or
                    part[:, 1].max() < lat0 - 1 or part[:, 1].min() > lat1 + 1):
                continue
            sx, sy = base.px_of(part[:, 0], part[:, 1])  # source px
            px = (sx - c_sl.start) * out_w / w_src       # print px
            py = (sy - r_sl.start) * out_h / h_src
            inside = ((px > -2) & (px < out_w + 2) &
                      (py > -2) & (py < out_h + 2))
            if not inside.any():
                continue
            drw.line(list(zip(px.tolist(), py.tolist())),
                     fill=1, width=GROOVE_W_PX)
            seg = inside[:-1] & inside[1:]
            length_m += np.hypot(np.diff(px), np.diff(py))[seg].sum() * PX_MM
    return np.asarray(img, bool), length_m


def render_preview(top, sea, groove, reg, mesh_full, out_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    fig = plt.figure(figsize=(17, 10), dpi=130)
    h, w = top.shape

    # -- panel 1: top-down, grooves visible ---------------------------------
    ax = fig.add_subplot(1, 2, 1)
    ls = LightSource(azdeg=315, altdeg=45)
    shade = ls.hillshade(top, vert_exag=3, dx=PX_MM, dy=PX_MM)
    rgb = np.dstack([shade] * 3) * 0.6 + 0.4
    for rid, col in base.COLORS.items():
        m = reg == rid
        for ch in range(3):
            rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.72 + col[ch] * 0.28
    rgb[sea] = OCEAN_RGB
    rgb[groove] = (0.05, 0.05, 0.05)
    ax.imshow(rgb, extent=[0, w * PX_MM, 0, h * PX_MM])
    ax.set_title(f"top-down  ({w * PX_MM:.1f} x {h * PX_MM:.1f} mm slab, "
                 "grooves black)")
    ax.set_xlabel("mm (E-W)")
    ax.set_ylabel("mm (S-N)")

    # -- panel 2: oblique 3D on a decimated copy ----------------------------
    ds = 3
    mesh_d = mc.heightfield_to_mesh(top[::ds, ::ds],
                                    np.ones_like(top[::ds, ::ds], bool),
                                    PX_MM * ds, bottom="fan")
    v, f = mesh_d.vertices, mesh_d.faces
    # drop the bottom fan: its slab-sized z=0 triangles defeat matplotlib's
    # painter-algorithm depth sort and get drawn over the terrain
    f = f[~(v[f][:, :, 2] < 1e-9).all(axis=1)]
    ax2 = fig.add_subplot(1, 2, 2, projection="3d")
    ax2.plot_trisurf(v[:, 0], v[:, 1], f, v[:, 2], cmap="gist_earth",
                     linewidth=0, antialiased=False,
                     vmin=BASE_MM - 1.5, vmax=float(top.max()))
    ext = mesh_full.extents
    ax2.set_box_aspect((ext[0], ext[1], ext[2] * 4))
    ax2.view_init(elev=40, azim=-110)
    ax2.set_title(f"oblique (z shown 4x; real thickness {ext[2]:.1f} mm max)")
    ax2.set_xlabel("mm E")
    ax2.set_ylabel("mm N")

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
    reg_w, dem_w, sea_w = reg_s[win], dem_s[win], sea_s[win]
    h_src, w_src = dem_w.shape
    print(f"slab window: {h_src} x {w_src} px @ 250 m "
          f"({h_src * 0.25:.0f} x {w_src * 0.25:.0f} km)")

    ns_ground_m = h_src * base.META["res"]
    scale_den = ns_ground_m * 1000.0 / NS_MM
    out_h = int(round(NS_MM / PX_MM))
    out_w = int(round(w_src * out_h / h_src))

    # sea floor must not bleed into coastal land during bilinear resampling
    dem_p = resample(np.where(sea_w, 0.0, dem_w), out_h, out_w, order=1)
    reg_p = resample(reg_w, out_h, out_w, order=0)
    sea_p = resample(sea_w.astype(np.uint8), out_h, out_w, order=0).astype(bool)
    reg_p[sea_p] = 0
    print(f"print grid {out_h} x {out_w} px @ {PX_MM} mm/px")

    ca_rows = np.nonzero((reg_p > 0).any(axis=1))[0]
    max_elev_ca = float(dem_p[reg_p > 0].max())
    max_elev_win = float(dem_p[~sea_p].max())
    z_scale = RELIEF_MM / max_elev_ca            # mm per meter of elevation
    horiz = 1000.0 / scale_den                   # mm per meter of ground
    print(f"scale 1:{scale_den:,.0f}; slab {out_w * PX_MM:.1f} mm E-W x "
          f"{NS_MM:.0f} mm N-S; CA spans {len(ca_rows) * PX_MM:.1f} mm N-S")
    print(f"max elev: CA {max_elev_ca:.0f} m -> {RELIEF_MM} mm relief "
          f"(window max {max_elev_win:.0f} m -> "
          f"{max_elev_win * z_scale:.2f} mm); "
          f"vertical exaggeration {z_scale / horiz:.1f}x")

    top = np.where(sea_p, BASE_MM, BASE_MM + dem_p * z_scale)

    g_reg, border_mm = region_groove(reg_p)
    g_pol, pol_mm = political_groove(win, out_h, out_w)
    groove = g_reg | g_pol
    gt = top[groove] - GROOVE_DEPTH_MM
    n_clamp = int((gt < MIN_FLOOR_MM).sum())
    top[groove] = np.maximum(gt, MIN_FLOOR_MM)
    print(f"grooves: {int(groove.sum())} px lowered "
          f"(region borders {border_mm:.0f} mm, political ~{pol_mm:.0f} mm); "
          f"depth {GROOVE_DEPTH_MM} mm, floor clamped at {MIN_FLOOR_MM} mm "
          f"on {n_clamp} px")

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
    render_preview(top, sea_p, groove, reg_p, mesh, png)
    print(f"wrote {png}")


if __name__ == "__main__":
    main()
