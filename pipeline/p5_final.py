# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "numpy",
#   "scipy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "trimesh",
#   "shapely",
#   "scikit-image",
#   "triangle",
#   "py-lib3mf",
#   "cairosvg",
# ]
# ///
"""P5: the FULL final product — frame + three removable pieces.

Extent = the D13 window (Census CA bbox + 40 km N/E/S + 67.5 km ocean W)
at [output].total_ns_mm N-S -> ~225 x 250 mm.  All physical knobs come
from config ([print] shared with the P4 coupon, [output].z_exaggeration,
[compass]) so post-test-print tuning is config-only; `make p5` rebuilds.

THE FRAME (out/p5/frame.3mf, 4-color Bambu multi-body):
  - tray per D16: continuous floor under everything, recess cavities for
    the three pieces, poke-holes ([print].poke_hole_d_mm; 2-3 per piece
    by cavity area) through the floor;
  - water (filament 2): floor + everything up to datum outside cavities,
    to the map edges (D15: no gray ring), MINUS the compass recesses;
  - coast (filament 1, yellow): coastal-region terrain incl. the Channel
    Islands (coast cells in the region raster, D15/G11);
  - gray (filament 3): ALL non-CA land (Census ca_mask is the authority)
    with full terrain (D15);
  - the D17 compass rose (ahl's artwork, assets/compass.svg) as RAISED
    relief on the water surface (datum -> datum + [compass].relief_mm):
    cairosvg rasterizes the artwork, compass_art.py color-keys it into
    three disjoint ink classes — dark blue -> the coast filament, gray
    -> the gray filament, black (outlines + pipeline-drawn N/E/S/W
    letters) -> the black body (filament 4).  Blue/gray rose ink merges
    into the EXISTING coast/gray bodies (same filament); the frame
    stays 4 bodies.  The water top under the rose stays flat.

PIECES (out/p5/{mountains,valley,desert}.stl): slab = base - floor,
terrain at the G2 normalized z-rule ([output].z_exaggeration x
horizontal scale), [print].clearance_per_side_mm per side, vertical
walls with optional [print].bottom_chamfer_mm 45-deg bottom chamfer.

Version stamps (version_stamp.py) debossed into all four bottoms.

Machinery is imported from p4_bay_coupon (kept runnable itself): region
cache, D13 scale, polygon extraction, solid meshing (incl. stamps +
chamfer), poke-holes, 3MF writer, preview helpers.

Outputs: out/p5/frame.3mf, out/p5/{mountains,valley,desert}.stl,
out/p5_preview.png (assembled / exploded / bottom-with-stamps / rose).
"""

import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy import ndimage
from shapely.geometry import MultiPolygon, box
from shapely.ops import polylabel

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import p4_bay_coupon as p4
import compass_art
import version_stamp as vstamp

# ------------------------------------------------------------------ params
PX_MM = p4.PX_MM             # print raster (0.05 mm/px; ~4500 x 5000 px)
NS_MM = p4.TOTAL_NS_MM
EXTRUDERS = {"coast": 1, "water": 2, "gray": 3, "black": 4}
POKE3_AREA_MM2 = 4000.0      # cavities above this get 3 poke-holes
STAMP_MARGIN = 0.8           # stamp rect -> piece wall margin

OUT = p4.OUT
OUT_DIR = OUT / "p5"
CFG = p4._CFG_ALL
COMPASS = CFG.get("compass", {"enabled": False})

PIECES = (("mountains", base.MOUNTAINS, "MTN"),
          ("valley", base.VALLEY, "VAL"),
          ("desert", base.DESERT, "DES"))


# -------------------------------------------------------------------- main
def main():
    dem = np.load(p4.DATA / "dem_ca_albers_250m.npy")
    reg, sea = p4.load_regions(dem)
    ca = np.load(p4.DATA / "p2_land.npz")["ca_mask"]
    s, (row_sl, col_sl), ns_m = p4.d13_scale()
    res = base.META["res"]
    GX0 = base.META["x_min"] + col_sl.start * res     # ground @ print x=0
    GY0 = base.META["y_max"] - row_sl.stop * res      # ground @ print y=0
    EW_MM = (col_sl.stop - col_sl.start) * res * s * 1000.0
    z_per_m = p4.g2_z_per_m(s)
    nx, ny = int(round(EW_MM / PX_MM)), int(round(NS_MM / PX_MM))
    print(f"P5 final build: 1:{1 / s / 1e6:.4f}M, {EW_MM:.1f} x {NS_MM:g} "
          f"mm, raster {nx} x {ny} px @ {PX_MM:g} mm "
          f"(~{nx * ny / 1e6:.0f} Mpx; ~"
          f"{nx * ny * (8 + 8 + 1 + 4) / 1e9:.1f} GB peak in EDT passes)\n"
          f"G2 z-scale: {p4.Z_EXAG:g}x (config) -> {z_per_m:.6f} mm/m; "
          f"CA max 4421 m would be {4421 * z_per_m:.2f} mm relief")

    # ---- print-space rasters -------------------------------------------
    x_mm = (np.arange(nx, dtype=np.float64) + 0.5) * PX_MM
    y_mm = NS_MM - (np.arange(ny, dtype=np.float64) + 0.5) * PX_MM
    cols1 = ((GX0 + x_mm / (s * 1000.0) - base.META["x_min"]) / res
             - 0.5).astype(np.float32)
    rows1 = ((base.META["y_max"] - (GY0 + y_mm / (s * 1000.0))) / res
             - 0.5).astype(np.float32)
    C, R = np.meshgrid(cols1, rows1)
    regw = ndimage.map_coordinates(reg, [R, C], order=0, mode="nearest")
    seaw = ndimage.map_coordinates(sea.astype(np.uint8), [R, C], order=0,
                                   mode="nearest").astype(bool)
    caw = ndimage.map_coordinates(ca.astype(np.uint8), [R, C], order=0,
                                  mode="nearest").astype(bool)
    del C, R

    notes = []
    # Census CA polygon is the land authority: regions live only on CA
    # land; every other land cell is the gray body (D15).
    spill = (regw > 0) & ~caw & ~seaw
    if spill.any():
        notes.append(f"cleared {spill.sum() * PX_MM ** 2:.1f} mm^2 of "
                     "region spill outside the Census CA polygon -> gray")
    regw[~caw] = 0
    ca_land = caw & ~seaw

    def to_albers_km(xm, ym):
        return ((GX0 + xm / (s * 1000.0)) / 1000.0,
                (GY0 + ym / (s * 1000.0)) / 1000.0)

    def where_km(comp):
        rr, cc = np.where(comp)
        ax0, ay0 = to_albers_km(cc.min() * PX_MM, NS_MM - rr.max() * PX_MM)
        ax1, ay1 = to_albers_km(cc.max() * PX_MM, NS_MM - rr.min() * PX_MM)
        return (f"Albers x [{ax0:.0f}, {ax1:.0f}] km, "
                f"y [{ay0:.0f}, {ay1:.0f}] km")

    regw = p4.fill_and_contiguity(regw, seaw, notes, where_km,
                                  fill_mask=ca_land)

    # ---- polygons -------------------------------------------------------
    footprint = box(0.0, 0.0, EW_MM, NS_MM)
    geo = {}
    for name, rid, _ in PIECES:
        mask = regw == rid
        geo[f"{name}_nom"] = p4.mask_polygon(mask, 0.0, clip=footprint)
        geo[f"{name}_piece"] = p4.clean_piece(
            p4.mask_polygon(mask, p4.CLEAR_PX, clip=footprint), name,
            notes)
        assert geo[f"{name}_piece"].geom_type == "Polygon", \
            f"{name} piece is not one part"
    coast_nom = p4.mask_polygon((regw == base.COAST) & ~seaw, 0.0,
                                clip=footprint)
    parts = p4._parts(coast_nom, p4.MIN_COAST_PART_MM2)
    n_all = len(list(getattr(coast_nom, "geoms", [coast_nom])))
    if n_all - len(parts):
        notes.append(f"coast body: dropped {n_all - len(parts)} crumb "
                     f"part(s) < {p4.MIN_COAST_PART_MM2} mm^2")
    geo["coast_nom"] = MultiPolygon(parts) if len(parts) > 1 else parts[0]
    print(f"  coast body: {len(parts)} parts (mainland + islands)")

    # cavity union contoured from the UNION raster mask: contouring the
    # three region outlines independently leaves hairline pinholes along
    # shared borders (sub-pixel contour wiggle) that would fragment the
    # water body; where cavities touch, the recess is one basin anyway
    cav_mask = np.isin(regw, [rid for _, rid, _ in PIECES])
    cavities = p4.mask_polygon(cav_mask, 0.0, clip=footprint)
    uw = footprint.difference(cavities)
    uparts = p4._parts(uw, 0.5)
    n_uw = len(list(getattr(uw, "geoms", [uw])))
    if n_uw - len(uparts):
        notes.append(f"water body: dropped {n_uw - len(uparts)} crumb "
                     "part(s) < 0.5 mm^2 along cavity borders")
    upper_water = (MultiPolygon(uparts) if len(uparts) > 1 else uparts[0])
    print(f"  upper water: {len(uparts)} part(s)")

    # gray = ALL land minus CA (cavities + coast) by exact polygon
    # difference, so the shared borders (CA state line at the Oregon and
    # Mexico coasts, cavity walls) are coincident by construction --
    # independently contoured coast/gray masks overlap by sub-pixel
    # wiggle along those lines
    land_nom = p4.mask_polygon(~seaw, 0.0, clip=footprint)
    gray = land_nom.difference(cavities).difference(geo["coast_nom"])
    # the difference of near-coincident contours (land vs coast/cavity
    # along the CA border) leaves micro-filament slivers attached to the
    # main parts that explode the q25 triangulation (4.8M tris); a
    # 0.05 mm morphological OPENING removes every feature thinner than
    # 0.1 mm and never expands beyond the difference, so coast/gray
    # stay exactly disjoint (concave corners rounded < 0.05 mm)
    gray = gray.buffer(-0.05).buffer(0.05)
    gall = list(getattr(gray, "geoms", [gray]))
    gparts = p4._parts(gray, p4.MIN_COAST_PART_MM2)
    if len(gall) - len(gparts):
        notes.append(f"gray body: dropped {len(gall) - len(gparts)} "
                     f"crumb part(s) < {p4.MIN_COAST_PART_MM2} mm^2")
    assert gparts, "no gray (non-CA) land?"
    geo["gray"] = MultiPolygon(gparts) if len(gparts) > 1 else gparts[0]
    print(f"  gray body: {len(gparts)} parts")
    geo["water_visible"] = upper_water.difference(
        geo["coast_nom"]).difference(geo["gray"])

    # ---- poke-holes (2-3 per piece by cavity size) ----------------------
    holes, circles = {}, []
    for name, _, _ in PIECES:
        nom = geo[f"{name}_nom"]
        n = 3 if nom.area > POKE3_AREA_MM2 else 2
        holes[name] = p4.poke_points(nom, n=n)
        for pt in holes[name]:
            circ = pt.buffer(p4.POKE_D_MM / 2, quad_segs=24)
            assert nom.contains(circ), f"poke-hole under a wall ({name})"
            circles.append(circ)
            ax, ay = to_albers_km(pt.x, pt.y)
            print(f"  poke-hole {name}: ({pt.x:.1f}, {pt.y:.1f}) mm = "
                  f"Albers ({ax:.0f}, {ay:.0f}) km")
    for i in range(len(circles)):
        for j in range(i + 1, len(circles)):
            assert circles[i].distance(circles[j]) > 1.0
    floor_poly = footprint
    for c in circles:
        floor_poly = floor_poly.difference(c)
    assert floor_poly.geom_type == "Polygon"
    print(f"  floor: one body, {len(floor_poly.interiors)} poke-holes")

    # ---- compass rose (ahl's artwork, raised relief) --------------------
    rose, rose_c = None, None
    if COMPASS.get("enabled", False):
        rose = compass_art.load_rose(
            base.ROOT / COMPASS["svg"], COMPASS["diameter_mm"],
            COMPASS["letter_font"], COMPASS["letter_cap_mm"],
            COMPASS["letter_radius_frac"])
        rose_c = tuple(COMPASS["center_mm"])
        # every ink cell (any class) must lie over open sea: the raised
        # bodies stand on the water datum surface
        xi, yi = rose.cell_centers(rose_c)
        rr = np.clip(np.round((NS_MM - yi) / PX_MM - 0.5).astype(int),
                     0, ny - 1)
        cc = np.clip(np.round(xi / PX_MM - 0.5).astype(int), 0, nx - 1)
        on_land = ~seaw[rr, cc]
        assert not on_land.any(), (
            f"rose ink over land: {on_land.sum()} cells, first at "
            f"({xi[on_land][0] if on_land.any() else 0:.1f}, "
            f"{yi[on_land][0] if on_land.any() else 0:.1f}) mm")
        hull = rose.ink_hull(rose_c)
        d_coast = hull.distance(geo["coast_nom"])
        d_gray = hull.distance(geo["gray"])
        d_cav = hull.distance(cavities)
        w, h = rose.size_mm
        cells = {n: int(m.sum()) for n, m in rose.masks.items()}
        stroke_flag = (" -- UNDER 0.42 mm nozzle width, FLAG"
                       if rose.black_stroke_mm < 0.42 else "")
        print(f"\ncompass rose (D17, raised {COMPASS['relief_mm']:g} mm):"
              f" ring dia {COMPASS['diameter_mm']:g} mm at {rose_c}, "
              f"tips to r {rose.tip_r_mm:.1f} mm, box {w:.1f} x {h:.1f} "
              f"mm; ink cells {cells}\n"
              f"  black artwork strokes {rose.black_stroke_mm:.2f} mm"
              f"{stroke_flag}; letters cap "
              f"{COMPASS['letter_cap_mm']:g} mm at r {rose.letter_r_mm:g}"
              f" mm, min stroke {rose.letter_min_stroke_mm:.2f} mm, "
              f"font {Path(rose.font_file).name}\n"
              f"  open-water check: all ink over sea; ink-hull margins "
              f"-- coast {d_coast:.1f} mm, gray {d_gray:.1f} mm, "
              f"cavities {d_cav:.1f} mm")
        assert rose.letter_min_stroke_mm >= 0.8 - 1e-6, \
            "letter strokes < 0.8"

    # ---- version stamps -------------------------------------------------
    date = vstamp.stamp_date()
    stamps = {}
    frame_text = (f"{p4.BUILD_TAG} {date} 1:{1 / s / 1e6:.2f}M "
                  f"c{p4.CLEARANCE_MM:g}")
    allowed_frame = footprint.buffer(-2.0).difference(cavities.buffer(1.5))
    for c in circles:
        allowed_frame = allowed_frame.difference(c.buffer(1.5))
    stamps["frame"] = vstamp.make_stamp(frame_text, allowed_frame)
    for name, _, abbr in PIECES:
        piece = geo[f"{name}_piece"]
        stamps[name] = vstamp.make_stamp(
            f"{p4.BUILD_TAG} {date} {abbr}",
            piece.buffer(-(STAMP_MARGIN + p4.CHAMFER_MM)),
            anchor=polylabel(piece, 0.05))
    print(f"\nversion stamps ({vstamp.DEPTH_MM:g} mm deboss, mirrored):")
    for name, st in stamps.items():
        host = floor_poly if name == "frame" else geo[f"{name}_piece"]
        assert st.rect.within(host)
        if name == "frame":
            extra = (f"; {st.rect.distance(cavities):.1f} mm to cavities,"
                     f" {min(st.rect.distance(c) for c in circles):.1f} "
                     "mm to poke-holes")
            assert st.rect.distance(cavities) > 1.0
            assert min(st.rect.distance(c) for c in circles) > 1.0
        else:
            extra = (f"; {st.rect.distance(host.boundary):.1f} mm to "
                     "piece wall")
        w, h = st.size_mm
        print(f"  {name:9s} '{st.text}' {len(st.lines)}L cap "
              f"{st.cap_mm:.1f} stroke>={st.min_stroke_mm:.2f} "
              f"(dil {st.dilated_px}): rect {w:.1f} x {h:.1f} mm at "
              f"({st.center[0]:.1f}, {st.center[1]:.1f}) "
              f"{st.angle:+.0f} deg{extra}")

    # ---- meshes ---------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    terrain_piece = p4.make_terrain_fn(dem, s, GX0, GY0, z_per_m,
                                       p4.PIECE_SLAB_MM)
    terrain_coast = p4.make_terrain_fn(dem, s, GX0, GY0, z_per_m,
                                       p4.BASE_MM, floor_mm=p4.LAND_MIN_MM)
    ok = True
    print("\nframe bodies (frame.3mf):")
    m_floor = p4.solid_mesh(floor_poly,
                            lambda v: np.full(len(v), p4.FLOOR_MM), 0.0,
                            quality=False, stamp=stamps["frame"])
    m_upper = p4.solid_mesh(upper_water,
                            lambda v: np.full(len(v), p4.BASE_MM),
                            p4.FLOOR_MM - p4.OVERLAP_MM, quality=False)
    water_mesh = trimesh.util.concatenate([m_floor, m_upper])
    ok &= p4.report_mesh("water(+floor)", water_mesh)
    zok, zlev = vstamp.verify_stamp_levels(water_mesh, stamps["frame"])
    ok &= zok
    fs = stamps["frame"]
    glyph_vol = fs.mask.sum() * fs.pitch ** 2 * fs.depth
    exp = floor_poly.area * p4.FLOOR_MM - glyph_vol
    dv = abs(m_floor.volume - exp) / exp
    ok &= dv < 2e-3
    print(f"    frame stamp z-levels {zlev} -> exact "
          f"{vstamp.DEPTH_MM:g}: {zok}; floor volume err {dv * 100:.3f}%")
    coast_mesh = p4.solid_mesh(geo["coast_nom"], terrain_coast, p4.BASE_MM)
    ok &= p4.report_mesh("coast(terrain)", coast_mesh)
    gray_mesh = p4.solid_mesh(geo["gray"], terrain_coast, p4.BASE_MM)
    ok &= p4.report_mesh("gray(terrain)", gray_mesh)
    black_mesh = None
    if rose is not None:
        rm = compass_art.relief_meshes(rose, rose_c, p4.BASE_MM,
                                       COMPASS["relief_mm"])
        z_top = p4.BASE_MM + COMPASS["relief_mm"]
        for rname, rmesh in rm.items():
            bb = rmesh.bounds
            raised = (abs(bb[0][2] - p4.BASE_MM) < 1e-6
                      and abs(bb[1][2] - z_top) < 1e-6)
            ok &= raised and p4.report_mesh(f"rose {rname}", rmesh)
            print(f"    rose {rname} z {bb[0][2]:.2f}..{bb[1][2]:.2f} "
                  f"(datum {p4.BASE_MM:g} + {COMPASS['relief_mm']:g}) "
                  f"raised OK: {raised}")
        # blue/gray rose ink joins the matching filament bodies
        coast_mesh = trimesh.util.concatenate([coast_mesh, rm["coast"]])
        gray_mesh = trimesh.util.concatenate([gray_mesh, rm["gray"]])
        black_mesh = rm["black"]
    bodies = [("coast", coast_mesh, EXTRUDERS["coast"]),
              ("water", water_mesh, EXTRUDERS["water"]),
              ("gray", gray_mesh, EXTRUDERS["gray"])]
    if black_mesh is not None:
        bodies.append(("black", black_mesh, EXTRUDERS["black"]))
    ok &= p4.report_mesh("coast body", coast_mesh)
    ok &= p4.report_mesh("gray body", gray_mesh)
    assert geo["coast_nom"].intersection(geo["gray"]).area < 1e-6

    frame_path = OUT_DIR / "frame.3mf"
    p4.write_bambu_3mf(frame_path, "p5_frame", bodies)
    print(f"  -> {frame_path} ({frame_path.stat().st_size / 1e6:.1f} MB) "
          f"[{p4.lint_3mf(frame_path)}]")

    print("\nremovable pieces:")
    piece_meshes = {}
    for name, _, _ in PIECES:
        piece = geo[f"{name}_piece"]
        mesh = p4.solid_mesh(piece, terrain_piece, 0.0,
                             stamp=stamps[name], chamfer=p4.CHAMFER_MM)
        path = OUT_DIR / f"{name}.stl"
        mesh.export(path)
        piece_meshes[name] = mesh
        ok &= p4.report_mesh(name, mesh)
        zok, zlev = vstamp.verify_stamp_levels(mesh, stamps[name],
                                               extra=(p4.CHAMFER_MM,))
        ok &= zok
        gap = piece.distance(upper_water)
        others = [geo[f"{o}_piece"] for o, _, _ in PIECES if o != name]
        gap_pp = min(piece.distance(o) for o in others)
        print(f"    stamp z {zlev} exact: {zok}; min width "
              f"~{p4.min_land_width(piece):.2f} mm; gap vs frame "
              f"{gap:.3f} (nom {p4.CLEARANCE_MM:g}); vs pieces "
              f"{gap_pp:.3f} (nom {2 * p4.CLEARANCE_MM:g})  -> {path}")

    for n in notes:
        print(f"  note: {n}")

    render_preview(geo, s, holes, stamps, rose, rose_c, EW_MM)
    print(f"\nall bodies/pieces watertight + checks: {ok}")
    if not ok:
        sys.exit(1)
    print("slicing (G4): vertical walls"
          + (f" with {p4.CHAMFER_MM:g} mm bottom chamfer"
             if p4.CHAMFER_MM > 0 else
             " -- enable elephant-foot compensation")
          + f"; filaments: {EXTRUDERS}")


# ----------------------------------------------------------------- preview
def render_preview(geo, s, holes, stamps, rose, rose_c, ew_mm):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.transforms import Affine2D
    from shapely import affinity

    ratio = ew_mm / NS_MM
    fig, axes = plt.subplots(1, 4, figsize=(4 * 7.0 * ratio + 3, 8.0),
                             dpi=170)

    def draw_map(ax, pieces_exploded=False):
        ax.set_facecolor("#1c1c22")
        p4.add_poly(ax, geo["water_visible"], p4.WATER_RGB)
        p4.add_poly(ax, geo["gray"], p4.GRAY_RGB, z=2)
        p4.add_poly(ax, geo["coast_nom"], base.COLORS[base.COAST], z=2)
        for name, rid, _ in PIECES:
            g = geo[f"{name}_piece"]
            if pieces_exploded:
                cav = geo[f"{name}_nom"]
                for pt in holes[name]:
                    cav = cav.difference(
                        pt.buffer(p4.POKE_D_MM / 2, quad_segs=24))
                p4.add_poly(ax, cav,
                            tuple(c * 0.82 for c in p4.WATER_RGB), z=2)
                c = g.centroid
                v = np.array([c.x - ew_mm / 2, c.y - NS_MM / 2])
                nv = np.linalg.norm(v)
                dx, dy = (v / nv * 45.0) if nv > 1e-6 else (0, 45.0)
                g = affinity.translate(g, dx, dy)
                cc = g.centroid
                ax.annotate(name, (cc.x, cc.y), color="black", fontsize=9,
                            ha="center", weight="bold", zorder=6)
            p4.add_poly(ax, g, base.COLORS[rid], z=3)

    rose_colors = {"coast": tuple(base.COLORS[base.COAST])[:3],
                   "gray": p4.GRAY_RGB, "black": (0.12, 0.11, 0.11)}

    def draw_rose(ax):
        if rose is not None:
            compass_art.draw_rose(ax, rose, rose_c, rose_colors)

    # 1: assembled
    ax = axes[0]
    draw_map(ax)
    draw_rose(ax)
    for pts in holes.values():
        for pt in pts:
            ax.add_patch(plt.Circle((pt.x, pt.y), p4.POKE_D_MM / 2,
                                    fill=False, edgecolor="black",
                                    linestyle=":", lw=0.8, zorder=5))
    ax.set_xlim(-3, ew_mm + 3), ax.set_ylim(-3, NS_MM + 3)
    ax.set_title(f"assembled — 1:{1 / s / 1e6:.3f}M, {ew_mm:.0f} x "
                 f"{NS_MM:g} mm; dotted = poke-holes", fontsize=10)

    # 2: exploded
    ax = axes[1]
    draw_map(ax, pieces_exploded=True)
    draw_rose(ax)
    ax.set_xlim(-52, ew_mm + 52), ax.set_ylim(-52, NS_MM + 52)
    ax.set_title("exploded (+45 mm) — cavity floors show poke-holes",
                 fontsize=10)

    # 3: bottom view (mirrored) with the version stamps
    ax = axes[2]
    draw_map(ax)
    for pts in holes.values():
        for pt in pts:
            ax.add_patch(plt.Circle((pt.x, pt.y), p4.POKE_D_MM / 2,
                                    facecolor="#1c1c22",
                                    edgecolor="black", lw=0.5, zorder=5))
    for st in stamps.values():
        w, h = st.size_mm
        rgba = np.zeros(st.mask.shape + (4,))
        rgba[st.mask] = (0.05, 0.05, 0.05, 1.0)
        im = ax.imshow(rgba, extent=(-w / 2, w / 2, -h / 2, h / 2),
                       origin="lower", interpolation="nearest", zorder=6)
        im.set_transform(Affine2D().rotate_deg(st.angle)
                         .translate(*st.center) + ax.transData)
        xr, yr = st.rect.exterior.xy
        ax.plot(xr, yr, color="black", lw=0.5, linestyle=":", zorder=6)
    ax.set_xlim(ew_mm + 3, -3), ax.set_ylim(-3, NS_MM + 3)   # mirrored
    ax.set_title(f"BOTTOM (mirrored) — {vstamp.DEPTH_MM:g} mm stamps",
                 fontsize=10)

    # 4: rose close-up
    ax = axes[3]
    draw_map(ax)
    draw_rose(ax)
    if rose is not None:
        cx, cy = rose_c
        r = COMPASS["diameter_mm"] / 2
        ax.add_patch(plt.Circle((cx, cy), r, fill=False, lw=0.6,
                                edgecolor="#666", linestyle="--",
                                zorder=6))
        half = max(rose.size_mm) / 2 + 6
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        ax.set_title(f"rose close-up — ring dia {2 * r:g} mm, raised "
                     f"{COMPASS['relief_mm']:g} mm (blue ink -> coast "
                     "filament, gray -> gray, black + letters -> black)",
                     fontsize=9)
    else:
        ax.set_title("compass disabled", fontsize=10)

    for ax in axes:
        ax.set_aspect("equal")
        ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle(
        f"P5 final — frame (4-color: coast/water/gray/black rose) + 3 "
        f"pieces; floor {p4.FLOOR_MM:g}, datum {p4.BASE_MM:g}, "
        f"clearance {p4.CLEARANCE_MM:g}/side, chamfer "
        f"{p4.CHAMFER_MM:g}, z x{p4.Z_EXAG:g}", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "p5_preview.png", bbox_inches="tight",
                facecolor="white")
    print(f"wrote {OUT / 'p5_preview.png'}")


if __name__ == "__main__":
    main()
