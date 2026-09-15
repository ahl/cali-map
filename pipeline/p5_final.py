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
  - the D17 compass rose (ahl's artwork, assets/compass.svg):
    compass_art.py parses the SVG shapes VECTOR end-to-end (curves
    flattened at ~0.02 mm chord tolerance) into three disjoint ink
    classes — dark blue -> the coast filament, gray -> the gray
    filament, black (artwork + pipeline-drawn N/E/S/W letter outlines)
    -> the black body (filament 4).  Blue/gray rose ink merges into the
    EXISTING coast/gray bodies (same filament); the frame stays 4
    filaments, though water/floor export as two separate 3MF PARTS on
    filament 2 (so ironing can target the visible water top without
    the hidden cavity floor under the removable pieces -- see
    p4_bay_coupon.py).  [compass].style: "flush" = ink inlaid with tops
    level with the water surface, matching recesses carved into the top
    ([compass].depth_mm) from the SAME triangulation (walls exactly
    coincident); "raised" = ink stands proud on a flat water top.

PIECES (out/p5/{mountains,valley,desert}.stl): slab = base - floor,
terrain at the G2 normalized z-rule ([output].z_exaggeration x
horizontal scale), [print].clearance_per_side_mm per side against the
FRAME and [print].clearance_pair_per_side_mm per side against a sibling
piece (T1 finding: 0.15 mm/side is the frame friction fit, but doubles
to a loose 0.30 mm between two 0.15/side piece walls -- piece-piece
borders get the smaller pair clearance instead, blended in via
p4_bay_coupon.piece_polygon), vertical walls with optional
[print].bottom_chamfer_mm 45-deg bottom chamfer.

Version stamps (version_stamp.py) debossed into all four bottoms --
gated by [output].stamps_enabled (currently FALSE per ahl 2026-09-14:
plain flat bottoms until the stamp rendering is revisited).

Machinery is imported from p4_bay_coupon (kept runnable itself): region
cache, D13 scale, polygon extraction, solid meshing (incl. stamps +
chamfer), poke-holes, 3MF writer, preview helpers.

THE REGION KEY (D19, out/p5/key.stl + key_plug.stl + key_insert.pdf): a plate
that press-fits into its own rectangular recess in the frame over
Nevada, listing the five regions with a colour-swatch plug beside each.
Placement and size come from config [key]; the HEIGHT does not -- the
build walks the key's BOUNDARY and sets the top flush with the tallest
terrain it meets there, so moving or resizing the key re-heights it
automatically.  The bottom sits on the tray floor at the
same z as every piece.  Permanent press fit: no ribs, no poke-hole.
The swatch PLUG ships as a plain output too -- one flat-topped cylinder,
printed five times in the five region colours; ahl lays the real print
out by hand in Bambu Studio, so nothing here tries to pack it onto a
plate or merge it into another part.

Outputs: out/p5/frame.3mf, out/p5/{mountains,valley,desert}.stl,
out/p5/key.stl, out/p5/key_plug.stl, out/p5/key_insert.pdf,
out/p5_preview.png (assembled / exploded / bottom-with-stamps / rose).
"""

import sys
from pathlib import Path

import numpy as np
import trimesh
from scipy import ndimage
from shapely.geometry import MultiPolygon, Point, box
from shapely.ops import polylabel, unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import p4_bay_coupon as p4
import compass_art
import key_panel
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
KEY = CFG.get("key", {"enabled": False})


def key_rect():
    """The key's NOMINAL footprint (the frame recess) from config [key]."""
    cx, cy = KEY["center_mm"]
    w, h = KEY["width_mm"], KEY["height_mm"]
    return box(cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def key_top_relief_mm(rect, terrain_relief, step=0.1):
    """Max terrain relief (mm above datum) ON the key's BOUNDARY: walk
    the rectangle's perimeter at `step` spacing and take the tallest
    value found.

    ahl 2026-09-15, clarifying "flush with the highest peak adjacent to
    it": adjacent means the terrain the key's edge actually meets --
    each point along the boundary line -- NOT terrain merely nearby.
    (An earlier version sampled a band around the perimeter and so
    picked up peaks standing off from the key, making it taller than
    the terrain it touches.)  Re-scanned every build, so moving or
    resizing the key re-heights it and no height is configured by hand.
    `terrain_relief` is p4.make_terrain_fn with z_datum=0, i.e. it
    returns relief in mm."""
    ring = rect.exterior
    n = max(8, int(np.ceil(ring.length / step)))
    pts = np.array([[p.x, p.y] for p in
                    (ring.interpolate(d) for d in
                     np.linspace(0.0, ring.length, n, endpoint=False))])
    return float(terrain_relief(pts).max()), len(pts)

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
    # BODY assignment uses the POLYGON land authority; the REGION rasters
    # keep the DEM `seaw`, so region boundaries do not move. See
    # p4.land_authority() for the T1-print defect this fixes.
    wet = ~ndimage.map_coordinates(p4.land_authority().astype(np.uint8),
                                   [R, C], order=0,
                                   mode="nearest").astype(bool)
    del C, R

    notes = []
    # Census CA polygon is the land authority: regions live only on CA
    # land; every other land cell is the gray body (D15).
    spill = (regw > 0) & ~caw & ~wet
    if spill.any():
        notes.append(f"cleared {spill.sum() * PX_MM ** 2:.1f} mm^2 of "
                     "region spill outside the Census CA polygon -> gray")
    regw[~caw] = 0
    ca_land = caw & ~wet

    def to_albers_km(xm, ym):
        return ((GX0 + xm / (s * 1000.0)) / 1000.0,
                (GY0 + ym / (s * 1000.0)) / 1000.0)

    def where_km(comp):
        rr, cc = np.where(comp)
        ax0, ay0 = to_albers_km(cc.min() * PX_MM, NS_MM - rr.max() * PX_MM)
        ax1, ay1 = to_albers_km(cc.max() * PX_MM, NS_MM - rr.min() * PX_MM)
        return (f"Albers x [{ax0:.0f}, {ax1:.0f}] km, "
                f"y [{ay0:.0f}, {ay1:.0f}] km")

    regw = p4.fill_and_contiguity(regw, wet, notes, where_km,
                                  fill_mask=ca_land)

    # ---- polygons -------------------------------------------------------
    footprint = box(0.0, 0.0, EW_MM, NS_MM)
    geo = {}
    for name, rid, _ in PIECES:
        geo[f"{name}_nom"] = p4.mask_polygon(regw == rid, 0.0,
                                             clip=footprint)
    for name, rid, _ in PIECES:
        mask = regw == rid
        other_mask = np.zeros_like(mask)
        for oname, orid, _ in PIECES:
            if oname != name:
                other_mask |= (regw == orid)
        geo[f"{name}_piece"] = p4.clean_piece(
            p4.piece_polygon(mask, other_mask, p4.CLEAR_PX,
                             p4.piece_pair_clear_px(name),
                             clip=footprint), name, notes)
        assert geo[f"{name}_piece"].geom_type == "Polygon", \
            f"{name} piece is not one part"
    coast_nom = p4.mask_polygon((regw == base.COAST) & ~wet, 0.0,
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
    # the KEY is a recess in the frame exactly like a piece cavity, so
    # folding it into `cavities` here gets everything downstream for
    # free: it becomes a hole in the upper water solid (a recess down to
    # the tray floor), it is cut out of the gray body, and it is
    # excluded from the version-stamp's allowed area
    if KEY.get("enabled", False):
        geo["key_nom"] = key_rect()
        kx0, ky0, kx1, ky1 = geo["key_nom"].bounds
        assert footprint.contains(geo["key_nom"]), "key runs off the frame"
        assert not geo["key_nom"].intersects(cavities), \
            "key overlaps a piece cavity"
        # it is meant to sit on the gray non-CA land (Nevada): check the
        # rasters rather than trusting the configured coordinates
        kr0, kr1 = int((NS_MM - ky1) / PX_MM), int((NS_MM - ky0) / PX_MM)
        kc0, kc1 = int(kx0 / PX_MM), int(kx1 / PX_MM)
        f_ca = float(caw[kr0:kr1, kc0:kc1].mean())
        f_sea = float(wet[kr0:kr1, kc0:kc1].mean())
        print(f"\nkey (D19): {KEY['width_mm']:g} x {KEY['height_mm']:g} mm "
              f"at {tuple(KEY['center_mm'])}, x[{kx0:.1f},{kx1:.1f}] "
              f"y[{ky0:.1f},{ky1:.1f}]\n"
              f"  footing: {f_ca * 100:.1f}% California, {f_sea * 100:.1f}% "
              f"water (want 0/0 -- it belongs on gray non-CA land)")
        assert f_ca < 1e-6 and f_sea < 1e-6, \
            "key does not sit wholly on gray non-CA land"
        cavities = cavities.union(geo["key_nom"])
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
    land_nom = p4.mask_polygon(~wet, 0.0, clip=footprint)
    gray = land_nom.difference(cavities).difference(geo["coast_nom"])
    # the difference of near-coincident contours (land vs coast/cavity
    # along the CA border) leaves micro-filament slivers attached to the
    # main parts that explode the q25 triangulation (4.8M tris); a
    # 0.05 mm morphological OPENING removes every feature thinner than
    # 0.1 mm and never expands beyond the difference, so coast/gray
    # stay exactly disjoint (concave corners rounded < 0.05 mm)
    gray = gray.buffer(-0.05).buffer(0.05)
    # the opening is a subset GEOMETRICALLY but not in floating point:
    # it renders the shared coast/gray boundary with fresh vertices, and
    # on the polygon coastline (far more intricate than the old DEM one)
    # that left ~700 sub-micron slivers straddling the line. Re-cut coast
    # out AFTER the opening so the two filament bodies are disjoint by
    # construction rather than by an epsilon.
    gray = gray.difference(geo["coast_nom"])
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

    # ---- poke-holes: finger-sized (18 mm), THE disassembly mechanism
    # (ahl 2026-09-14), 2-3 per piece by cavity size, at least one
    # straddling each major piece-piece seam -- may span a seam (serves
    # both flanking pieces); must stay >= POKE_MARGIN_MM from the frame
    # cavity wall and fully under the removable-piece union -----------
    piece_nom = {name: geo[f"{name}_nom"] for name, _, _ in PIECES}
    target_n = {name: (3 if piece_nom[name].area > POKE3_AREA_MM2 else 2)
                for name in piece_nom}
    centers, holes = p4.plan_poke_holes(piece_nom, target_n)
    circles = []
    for pt in centers:
        circ = pt.buffer(p4.POKE_D_MM / 2, quad_segs=24)
        assert cavities.contains(circ), \
            "poke-hole not fully under removable pieces"
        wall_margin = p4.POKE_D_MM / 2 + p4.POKE_MARGIN_MM
        assert cavities.boundary.distance(pt) >= wall_margin - 1e-6, \
            "poke-hole closer than POKE_MARGIN_MM to the frame cavity wall"
        circles.append(circ)
        under = [n for n, pts in holes.items() if any(p is pt for p in pts)]
        ax, ay = to_albers_km(pt.x, pt.y)
        print(f"  poke-hole {'+'.join(under):24s} ({pt.x:.1f}, {pt.y:.1f}) "
              f"mm = Albers ({ax:.0f}, {ay:.0f}) km"
              + ("  [seam hole]" if len(under) > 1 else ""))
    print("  hole count: " + ", ".join(
        f"{name}: {len(holes[name])}" for name in piece_nom))
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
            COMPASS["letter_radius_frac"], COMPASS["ink_min_stroke_mm"])
        rose_c = tuple(COMPASS["center_mm"])
        # every ink cell (any class) must lie over open sea: the raised
        # bodies stand on the water datum surface
        xi, yi = rose.cell_centers(rose_c)
        rr = np.clip(np.round((NS_MM - yi) / PX_MM - 0.5).astype(int),
                     0, ny - 1)
        cc = np.clip(np.round(xi / PX_MM - 0.5).astype(int), 0, nx - 1)
        on_land = ~wet[rr, cc]
        assert not on_land.any(), (
            f"rose ink over land: {on_land.sum()} cells, first at "
            f"({xi[on_land][0] if on_land.any() else 0:.1f}, "
            f"{yi[on_land][0] if on_land.any() else 0:.1f}) mm")
        hull = rose.ink_hull(rose_c)
        d_coast = hull.distance(geo["coast_nom"])
        d_gray = hull.distance(geo["gray"])
        d_cav = hull.distance(cavities)
        w, h = rose.size_mm
        if p4.ROSE_STYLE == "flush":
            panel = vstamp.rect_poly(rose_c[0], rose_c[1], w, h, 0.0)
            assert panel.within(upper_water), \
                "flush rose panel overlaps a cavity"
        areas = {n: round(g.area, 1) for n, g in rose.polys.items()}
        print(f"\ncompass rose (D17, {p4.ROSE_STYLE} "
              f"{p4.ROSE_DEPTH:g} mm): ring dia "
              f"{COMPASS['diameter_mm']:g} mm at {rose_c}, "
              f"tips to r {rose.tip_r_mm:.1f} mm, box {w:.1f} x {h:.1f} "
              f"mm; ink areas (mm^2) {areas}\n"
              f"  black declared SVG stroke {rose.black_stroke_mm:.2f} mm "
              "(0 = no <stroke>, ink drawn as filled shapes); letters cap "
              f"{COMPASS['letter_cap_mm']:g} mm at r {rose.letter_r_mm:g}"
              f" mm, min stroke {rose.letter_min_stroke_mm:.2f} mm, "
              f"font {Path(rose.font_file).name}\n"
              f"  ink min stroke (target {COMPASS['ink_min_stroke_mm']:g} "
              "mm): " + ", ".join(
                  f"{n} {rose.ink_stroke_before_mm[n]:.2f}->"
                  f"{rose.ink_stroke_after_mm[n]:.2f} mm"
                  for n in rose.ink_stroke_after_mm) +
              f"\n  letter/tip gap {rose.letter_tip_gap_mm:+.3f} mm "
              f"(cardinal tips to r {rose.cardinal_tip_r_mm:.2f} mm)\n"
              f"  open-water check: all ink over sea; ink-hull margins "
              f"-- coast {d_coast:.1f} mm, gray {d_gray:.1f} mm, "
              f"cavities {d_cav:.1f} mm")
        assert rose.letter_min_stroke_mm >= 0.8 - 1e-6, \
            "letter strokes < 0.8"
        assert rose.letter_tip_gap_mm > 0, "letter ink touches cardinal tips"
        assert rose.ink_stroke_after_mm["black"] >= \
            COMPASS["ink_min_stroke_mm"] - 1e-6, "black ink stroke under floor"

    # ---- version stamps -------------------------------------------------
    stamps = {}
    if p4.STAMPS_ENABLED:
        date = vstamp.stamp_date()
        frame_text = (f"{p4.BUILD_TAG} {date} 1:{1 / s / 1e6:.2f}M "
                      f"c{p4.CLEARANCE_MM:g}")
        allowed_frame = footprint.buffer(-2.0).difference(
            cavities.buffer(1.5))
        for c in circles:
            allowed_frame = allowed_frame.difference(c.buffer(1.5))
        stamps["frame"] = vstamp.make_stamp(frame_text, allowed_frame)
        for name, _, abbr in PIECES:
            piece = geo[f"{name}_piece"]
            stamps[name] = vstamp.make_stamp(
                f"{p4.BUILD_TAG} {date} {abbr}",
                piece.buffer(-(STAMP_MARGIN + p4.CHAMFER_MM)),
                anchor=polylabel(piece, 0.05))
        print(f"\nversion stamps ({vstamp.DEPTH_MM:g} mm deboss, "
              "mirrored):")
        for name, st in stamps.items():
            host = floor_poly if name == "frame" else geo[f"{name}_piece"]
            assert st.rect.within(host)
            if name == "frame":
                extra = (f"; {st.rect.distance(cavities):.1f} mm to "
                         "cavities, "
                         f"{min(st.rect.distance(c) for c in circles):.1f}"
                         " mm to poke-holes")
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
    else:
        print("\nversion stamps DISABLED ([output].stamps_enabled = "
              "false) -- plain flat bottoms on every part")

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
                            quality=False, stamp=stamps.get("frame"))
    rose_panel = None
    if rose is not None:
        rose_panel = compass_art.RosePanel(rose, rose_c, p4.ROSE_DEPTH)
    m_upper = p4.water_upper_mesh(
        upper_water, rose_panel if p4.ROSE_STYLE == "flush" else None)
    # kept as two 3MF parts (not concatenated) so Bambu Studio can iron
    # just the visible open-water top and skip the cavity floor under
    # the removable pieces -- see p4_bay_coupon.py for the rationale
    ok &= p4.report_mesh("floor", m_floor)
    ok &= p4.report_mesh("water", m_upper)
    fs = stamps.get("frame")
    if fs is not None:
        zok, zlev = vstamp.verify_stamp_levels(m_floor, fs)
        ok &= zok
        print(f"    frame stamp z-levels {zlev} -> exact "
              f"{vstamp.DEPTH_MM:g}: {zok}")
    glyph_vol = (fs.mask.sum() * fs.pitch ** 2 * fs.depth
                 if fs is not None else 0.0)
    exp = floor_poly.area * p4.FLOOR_MM - glyph_vol
    dv = abs(m_floor.volume - exp) / exp
    ok &= dv < 2e-3
    print(f"    floor volume err {dv * 100:.3f}%")
    coast_mesh = p4.solid_mesh(geo["coast_nom"], terrain_coast, p4.BASE_MM)
    ok &= p4.report_mesh("coast(terrain)", coast_mesh)
    gray_mesh = p4.solid_mesh(geo["gray"], terrain_coast, p4.BASE_MM)
    ok &= p4.report_mesh("gray(terrain)", gray_mesh)
    black_mesh = None
    if rose is not None:
        rm = rose_panel.ink_meshes(p4.BASE_MM, style=p4.ROSE_STYLE)
        z0, z1 = ((p4.BASE_MM - p4.ROSE_DEPTH, p4.BASE_MM)
                  if p4.ROSE_STYLE == "flush"
                  else (p4.BASE_MM, p4.BASE_MM + p4.ROSE_DEPTH))
        for rname, rmesh in rm.items():
            bb = rmesh.bounds
            zok2 = (abs(bb[0][2] - z0) < 1e-6
                    and abs(bb[1][2] - z1) < 1e-6)
            ok &= zok2 and p4.report_mesh(f"rose {rname}", rmesh)
            print(f"    rose {rname} z {bb[0][2]:.2f}..{bb[1][2]:.2f} "
                  f"(want {z0:g}..{z1:g}, {p4.ROSE_STYLE}) OK: {zok2}")
        if p4.ROSE_STYLE == "flush":
            up_lv = sorted(set(np.round(m_upper.vertices[:, 2],
                                        5).tolist()))
            want = [round(v, 5) for v in
                    (p4.FLOOR_MM - p4.OVERLAP_MM,
                     p4.BASE_MM - p4.ROSE_DEPTH, p4.BASE_MM)]
            flush_ok = up_lv == want
            ok &= flush_ok
            print(f"    water-top recess z-levels {up_lv} == {want}: "
                  f"{flush_ok}")
        # blue/gray rose ink joins the matching filament bodies
        coast_mesh = trimesh.util.concatenate([coast_mesh, rm["coast"]])
        gray_mesh = trimesh.util.concatenate([gray_mesh, rm["gray"]])
        black_mesh = rm["black"]
    bodies = [("coast", coast_mesh, EXTRUDERS["coast"]),
              ("floor", m_floor, EXTRUDERS["water"]),
              ("water", m_upper, EXTRUDERS["water"]),
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
    ribbed_geo, rib_sites = {}, {}
    for name, _, _ in PIECES:
        piece = geo[f"{name}_piece"]
        sib_noms = [geo[f"{o}_nom"] for o, _, _ in PIECES if o != name]
        other_nom = unary_union(sib_noms) if sib_noms else None
        ribbed, sites = p4.add_crush_ribs(
            piece, geo[f"{name}_nom"], other_nom, p4.RIBS_PER_PIECE,
            p4.RIB_RADIUS_MM, p4.RIB_INTERFERENCE_MM,
            manual_points=p4.RIB_SITES_CFG.get(f"p5_{name}"),
            neighbor_pieces=[geo[f"{o}_piece"] for o, _, _ in PIECES
                             if o != name])
        ribbed_geo[name] = ribbed
        rib_sites[name] = sites
        mesh = p4.solid_mesh(ribbed, terrain_piece, 0.0,
                             stamp=stamps.get(name),
                             chamfer=p4.CHAMFER_MM)
        path = OUT_DIR / f"{name}.stl"
        mesh.export(path)
        piece_meshes[name] = mesh
        ok &= p4.report_mesh(name, mesh)
        szn = ""
        if name in stamps:
            zok, zlev = vstamp.verify_stamp_levels(mesh, stamps[name],
                                                   extra=(p4.CHAMFER_MM,))
            ok &= zok
            szn = f"stamp z {zlev} exact: {zok}; "
        gmin, fmin, fmed, nfar = p4.wall_gap_stats(piece, other_nom,
                                                   upper_water)
        ring = geo[f"{name}_nom"].exterior
        site_str = ", ".join(
            f"{kind}@({p.x:.1f},{p.y:.1f})"
            for (d, kind), p in zip(sites, [ring.interpolate(d)
                                            for d, _ in sites]))
        print(f"    {szn}min width "
              f"~{p4.min_land_width(piece):.2f} mm; gap vs frame: "
              f"global min {gmin:.3f} mm, away from any sibling seam "
              f"(n={nfar}) min {fmin:.3f} median {fmed:.3f} mm "
              f"(nom {p4.CLEARANCE_MM:g}); crush ribs: "
              f"{len(sites)} x r{p4.RIB_RADIUS_MM:g} mm crest "
              f"+{p4.RIB_INTERFERENCE_MM:g} mm into the mating face: {site_str}"
              f"  -> {path}")

    # ---- the region KEY: a plate that press-fits into its recess ------
    key_rows = key_recess = None
    if KEY.get("enabled", False):
        rect = geo["key_nom"]
        relief_fn = p4.make_terrain_fn(dem, s, GX0, GY0, z_per_m, 0.0)
        peak_mm, n_samp = key_top_relief_mm(rect, relief_fn)
        # Z BOOKKEEPING (ahl asked 2026-09-15 whether the key was sized
        # off the print plane rather than off where it actually sits):
        # key.stl is exported in PIECE-LOCAL z, bottom at 0, exactly like
        # mountains/valley/desert.stl -- that z=0 is the RECESS FLOOR,
        # which is the top of the tray floor, FLOOR_MM above the bed. So
        # the plate's own height must be measured from the recess floor,
        # not from the bed: slab (BASE_MM - FLOOR_MM) gets it up to the
        # water datum, then the adjacent relief on top of that. Asserted
        # against the terrain in global coords just below.
        top_local = p4.PIECE_SLAB_MM + peak_mm
        key_top_global = p4.FLOOR_MM + top_local
        peak_top_global = p4.BASE_MM + peak_mm
        assert abs(key_top_global - peak_top_global) < 1e-9, (
            f"key top {key_top_global:.4f} mm != adjacent terrain top "
            f"{peak_top_global:.4f} mm (both above the bed)")
        # PERMANENT press fit (ahl 2026-09-15): no ribs, no poke-hole --
        # the plate is grown by interference_mm total over the recess
        inter = KEY.get("interference_mm", 0.0)
        kx0, ky0, kx1, ky1 = rect.bounds
        pw = (kx1 - kx0) + inter
        ph = (ky1 - ky0) + inter
        pl_w, pl_h, key_rows, key_recess = key_panel.layout(
            pw, ph, pocket_d=KEY.get("pocket_d_mm", 5.0),
            title=KEY.get("title", key_panel.TITLE),
            title_cap=KEY.get("title_cap_mm", key_panel.TITLE_CAP_MM),
            title_gap=KEY.get("title_gap_mm", key_panel.TITLE_GAP_MM),
            label_cap=KEY.get("label_cap_mm", key_panel.CAP_MM),
            insert_border=KEY.get("insert_border_mm",
                                  key_panel.INSERT_BORDER_MM))
        recesses = [{"points": key_panel.circle_ring(
                        *r["pocket_c"], KEY.get("pocket_d_mm", 5.0) / 2),
                     "depth": KEY.get("pocket_depth_mm", 1.4)}
                    for r in key_rows]
        recesses.append({"points": key_panel.rect_ring(
                            key_recess["x0"], key_recess["y0"], key_recess["x1"], key_recess["y1"]),
                         "depth": KEY.get("label_recess_mm", 0.2)})
        key_mesh = key_panel.build_plate(pl_w, pl_h, recesses, top_local)
        key_mesh.apply_translation([kx0 - inter / 2, ky0 - inter / 2, 0.0])
        kpath = OUT_DIR / "key.stl"
        key_mesh.export(kpath)
        ok &= p4.report_mesh("key", key_mesh)
        print(f"    top scanned from terrain: tallest of {n_samp} points "
              f"walked along the key's BOUNDARY = {peak_mm:.2f} mm of "
              f"relief ({peak_mm / z_per_m:.0f} m)\n"
              f"    -> plate {pl_w:.2f} x {ph:.2f} x {top_local:.2f} mm "
              f"tall in the STL (z from 0, like every piece)\n"
              f"    z check: the STL's z=0 is the RECESS FLOOR, "
              f"{p4.FLOOR_MM:g} mm above the bed -- so seated, the key "
              f"spans {p4.FLOOR_MM:g}..{key_top_global:.2f} mm and its top "
              f"matches the tallest adjacent terrain at "
              f"{peak_top_global:.2f} mm (datum {p4.BASE_MM:g} + "
              f"{peak_mm:.2f}) exactly\n"
              f"    press fit: recess {kx1 - kx0:g} x {ky1 - ky0:g}, plate "
              f"+{inter:g} mm total ({inter / 2:g}/side) -- no ribs, no "
              f"poke-hole, glue optional\n"
              f"    {len(key_rows)} swatch pockets dia "
              f"{KEY.get('pocket_d_mm', 5.0):g} x "
              f"{KEY.get('pocket_depth_mm', 1.4):g} deep; label recess "
              f"{key_recess['x1'] - key_recess['x0']:.1f} x {key_recess['y1'] - key_recess['y0']:.1f}"
              f" x {KEY.get('label_recess_mm', 0.2):g} deep -> {kpath}")
        key_panel.OUT_DIR = OUT_DIR       # write the label next to key.stl
        key_panel.render_label(key_recess, key_rows,
                               bleed=KEY.get("insert_bleed_mm",
                                             key_panel.INSERT_BLEED_MM))
        # the swatch PLUG ships as a plain P5 output (ahl 2026-09-15:
        # "it can just live with the other p5 output; I'll build out a
        # bambu file to optimize printing everything by hand"). One
        # file, printed five times in the five region colours -- the
        # geometry is identical, only the filament differs, so there is
        # nothing to gain from five copies of the same cylinder.
        # the pocket is a DESIGN dimension (the row layout is built on
        # it), so fit is tuned on the plug alone and plug_d_mm is an
        # absolute diameter. Guard it against the pocket anyway, so a
        # future layout change to pocket_d_mm cannot silently leave this
        # value orphaned at the wrong size.
        pocket_d = KEY.get("pocket_d_mm", 5.0)
        plug_d = KEY.get("plug_d_mm", pocket_d - 0.15)
        assert abs(plug_d - pocket_d) < 0.5, (
            f"[key].plug_d_mm {plug_d:g} is {abs(plug_d - pocket_d):.2f} mm "
            f"off pocket_d_mm {pocket_d:g} -- re-fit it (see "
            "out/key_coupon/) rather than letting it drift")
        plug_h = KEY.get("pocket_depth_mm", 1.4) + \
            KEY.get("plug_proud_mm", 0.4)
        plug = key_panel.insert_mesh(plug_d, plug_h)
        assert plug.is_watertight
        ppath = OUT_DIR / "key_plug.stl"
        plug.export(ppath)
        ok &= p4.report_mesh("key plug", plug)
        print(f"    swatch plug dia {plug_d:g} x {plug_h:g} mm, flat-topped "
              f"({KEY.get('pocket_depth_mm', 1.4):g} seated + "
              f"{KEY.get('plug_proud_mm', 0.4):g} proud) -> {ppath}\n"
              "      print FIVE of it, one per region colour: Pacific "
              "Ocean = water, Coastal = coast, then the mountains, "
              "valley and desert piece colours.\n"
              "      dimensions are still PROVISIONAL -- [key].plug_d_mm "
              "/ plug_proud_mm, pending ahl's out/key_coupon/ fit "
              "ladder.")

    print("\npiece-piece seam gaps (only nominally-adjacent pairs):")
    pnames = [n for n, _, _ in PIECES]
    for i in range(len(pnames)):
        for j in range(i + 1, len(pnames)):
            a, b = pnames[i], pnames[j]
            if geo[f"{a}_nom"].distance(geo[f"{b}_nom"]) > 1e-6:
                continue                        # not a shared seam
            gap_ab = geo[f"{a}_piece"].distance(geo[f"{b}_piece"])
            nom_ab = p4.pair_gap_nominal_mm(a, b)
            rib_ab = ribbed_geo[a].distance(ribbed_geo[b])
            print(f"    {a}-{b}: {gap_ab:.3f} mm (nom {nom_ab:g}), "
                  f"{rib_ab:.3f} mm with ribs")
            # ribs are specified as OVERLAP with the mating face, so each
            # engaged pair rib should bite RIB_INTERFERENCE_MM -- P5
            # valley touches no frame at all, so these are its ONLY grip
            for x, y in ((a, b), (b, a)):
                edge = geo[f"{y}_piece"].boundary   # incl. holes
                for g in p4._parts(ribbed_geo[x].intersection(
                        geo[f"{y}_piece"]), min_area=1e-9):
                    depth = max(edge.distance(Point(c))
                                for c in g.exterior.coords)
                    pt = g.representative_point()
                    print(f"      {x} rib bites {y} {depth:.3f} mm deep at "
                          f"({pt.x:.1f}, {pt.y:.1f}) -- target "
                          f"{p4.RIB_INTERFERENCE_MM:g} mm")

    for n in notes:
        print(f"  note: {n}")

    mnom = geo["mountains_nom"].exterior
    rib_pt = mnom.interpolate(rib_sites["mountains"][0][0])
    rib_pts = []
    for name, _, _ in PIECES:
        ring = geo[f"{name}_nom"].exterior
        for d, kind in rib_sites[name]:
            p = ring.interpolate(d)
            rib_pts.append({"name": name, "kind": kind, "x": p.x, "y": p.y})
    render_preview(geo, s, holes, stamps, ribbed_geo, rib_pt, rose, rose_c,
                  EW_MM, rib_pts, key_rows, key_recess)
    print(f"\nall bodies/pieces watertight + checks: {ok}")
    if not ok:
        sys.exit(1)
    print("slicing (G4): vertical walls"
          + (f" with {p4.CHAMFER_MM:g} mm bottom chamfer"
             if p4.CHAMFER_MM > 0 else
             " -- enable elephant-foot compensation")
          + f"; filaments: {EXTRUDERS}")


# ----------------------------------------------------------------- preview
def render_preview(geo, s, holes, stamps, ribbed, rib_pt, rose, rose_c,
                   ew_mm, rib_pts, key_rows=None, key_recess=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.transforms import Affine2D
    from shapely import affinity

    ratio = ew_mm / NS_MM
    fig, axes = plt.subplots(1, 5, figsize=(5 * 7.0 * ratio + 3, 8.0),
                             dpi=170)

    # same per-piece explode offset draw_map uses, precomputed once so
    # the rib markers on the exploded panel track their piece exactly
    explode_off = {}
    for name, _, _ in PIECES:
        c = geo[f"{name}_piece"].centroid
        v = np.array([c.x - ew_mm / 2, c.y - NS_MM / 2])
        nv = np.linalg.norm(v)
        explode_off[name] = (v / nv * 45.0) if nv > 1e-6 else (0.0, 45.0)

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
                dx, dy = explode_off[name]
                g = affinity.translate(g, dx, dy)
                cc = g.centroid
                ax.annotate(name, (cc.x, cc.y), color="black", fontsize=9,
                            ha="center", weight="bold", zorder=6)
            p4.add_poly(ax, g, base.COLORS[rid], z=3)
        # the region KEY: its recess, and the plate sitting in it (shown
        # lifted out with the pieces in the exploded panel)
        if "key_nom" in geo:
            k = geo["key_nom"]
            if pieces_exploded:
                p4.add_poly(ax, k, tuple(c * 0.82 for c in p4.WATER_RGB),
                            z=2)
                k = affinity.translate(k, 0.0, 45.0)
            p4.add_poly(ax, k, (0.97, 0.97, 0.95), ec="black", lw=0.5, z=3)
            # draw the REAL key contents (ahl 2026-09-15) -- the title
            # and region names at their true sizes and positions, not a
            # placeholder label, so the preview shows what gets printed
            ox = geo["key_nom"].bounds[0]
            oy = geo["key_nom"].bounds[1] + (45.0 if pieces_exploded else 0.0)
            for r in key_rows or []:
                px, py = r["pocket_c"]
                ax.add_patch(plt.Circle(
                    (ox + px, oy + py), KEY.get("pocket_d_mm", 5.0) / 2,
                    facecolor="#b9b9b9", edgecolor="black", lw=0.3, zorder=4))
            if key_recess is not None:
                # glyphs as VECTOR OUTLINES in mm, the same way the
                # compass rose draws its letters -- a matplotlib
                # fontsize would have to be back-computed from the axes
                # extent and dpi at draw time, which is fragile; a
                # TextPath scaled to cap height is exact by construction
                ff = compass_art._font_file(key_panel.FONT)
                rx = ox + key_recess["x0"]
                ry = oy + key_recess["y0"]

                def _mm_text(txt, x, y, cap):
                    g = compass_art._letter_poly(txt, ff, cap,
                                                 compass_art.CHORD_TOL_MM)
                    x0, y0, x1, y1 = g.bounds
                    p4.add_poly(ax, affinity.translate(
                        g, x - x0, y - (y0 + y1) / 2), (0.1, 0.1, 0.1), z=5)

                for ln, ty in zip(key_recess["title_lines"],
                                  key_recess["title_y_local"]):
                    _mm_text(ln, rx, ry + ty, key_recess["title_cap"])
                for r in key_rows or []:
                    _mm_text(r["label"], rx, ry + r["text_y_local"],
                             key_recess["label_cap"])

    # crush-rib sites in RED -- "pair" (piece-piece) ribs as a triangle
    # (the ones implicated in the T2 too-tight finding), "frame" ribs as
    # a dot; `exploded` applies the SAME per-piece offset draw_map used
    def draw_ribs(ax, exploded=False):
        for r in rib_pts:
            x, y = r["x"], r["y"]
            if exploded:
                dx, dy = explode_off[r["name"]]
                x, y = x + dx, y + dy
            marker = "^" if r["kind"] == "pair" else "o"
            ax.plot(x, y, marker=marker, color="red",
                   markeredgecolor="white", markeredgewidth=0.4,
                   markersize=5, zorder=7)

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
    draw_ribs(ax)
    ax.set_xlim(-3, ew_mm + 3), ax.set_ylim(-3, NS_MM + 3)
    ax.set_title(f"assembled — 1:{1 / s / 1e6:.3f}M, {ew_mm:.0f} x "
                 f"{NS_MM:g} mm; dotted = poke-holes; red = crush ribs "
                 "(triangle = pair, dot = frame)", fontsize=10)

    # 2: exploded
    ax = axes[1]
    draw_map(ax, pieces_exploded=True)
    draw_rose(ax)
    draw_ribs(ax, exploded=True)
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
    ax.set_title(f"BOTTOM (mirrored) — {vstamp.DEPTH_MM:g} mm stamps"
                 if stamps else
                 "BOTTOM (mirrored) — plain bottoms (stamps disabled)",
                 fontsize=10)

    # 4: crush-rib close-up (14 mm) -- ribbed piece walls vs the NOMINAL
    # boundary (dashed) they protrude past by RIB_INTERFERENCE_MM
    ax = axes[3]
    ax.set_facecolor("#1c1c22")
    for name, rid, _ in PIECES:
        p4.add_poly(ax, ribbed[name], base.COLORS[rid], z=3)
        nx, ny = geo[f"{name}_nom"].exterior.xy
        ax.plot(nx, ny, color="white", lw=0.6, linestyle="--", zorder=6,
                alpha=0.7)
    ax.set_xlim(rib_pt.x - 7, rib_pt.x + 7)
    ax.set_ylim(rib_pt.y - 7, rib_pt.y + 7)
    ax.set_title(f"crush-rib close-up (14 mm): r{p4.RIB_RADIUS_MM:g} mm, "
                 f"+{p4.RIB_INTERFERENCE_MM:g} mm into the mating face (dashed = nominal), "
                 f"{p4.RIBS_PER_PIECE:d} ribs/piece", fontsize=9)

    # 5: rose close-up
    ax = axes[4]
    draw_map(ax)
    draw_rose(ax)
    if rose is not None:
        cx, cy = rose_c
        r = COMPASS["diameter_mm"] / 2
        ax.add_patch(plt.Circle((cx, cy), r, fill=False, lw=0.6,
                                edgecolor="#666", linestyle="--",
                                zorder=6))
        half = max(rose.size_mm) / 2 + 2   # tight: judge ink dilation
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        ax.set_title(f"rose close-up — ring dia {2 * r:g} mm, "
                     f"{p4.ROSE_STYLE} {p4.ROSE_DEPTH:g} mm (blue ink "
                     "-> coast filament, gray -> gray, black + letters "
                     "-> black)", fontsize=9)
    else:
        ax.set_title("compass disabled", fontsize=10)

    for ax in axes:
        ax.set_aspect("equal")
        ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle(
        f"P5 final — frame (4-color: coast/water/gray/black rose) + 3 "
        f"pieces; floor {p4.FLOOR_MM:g}, datum {p4.BASE_MM:g}, "
        f"clearance {p4.CLEARANCE_MM:g}/side frame, "
        f"{p4.CLEARANCE_PAIR_MM:g}/side piece-piece, chamfer "
        f"{p4.CHAMFER_MM:g}, z x{p4.Z_EXAG:g}", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "p5_preview.png", bbox_inches="tight",
                facecolor="white")
    print(f"wrote {OUT / 'p5_preview.png'}")


if __name__ == "__main__":
    main()
