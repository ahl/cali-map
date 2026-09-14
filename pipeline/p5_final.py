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
  - black (filament 4): the D17 compass rose as a FLUSH INLAY sunk
    [compass].inlay_depth_mm into the water datum surface.  The SVG
    (assets/compass_rose.svg) is parsed (polygons / stroked circles /
    serif letters), its BLACK-inked geometry rasterized to a mask at
    ROSE_PITCH_MM, and the same two-level-grid machinery that cuts the
    version stamps cuts the matching recesses into the water top (the
    water body is built z-mirrored so version_stamp.stamped_bottom can
    carve its TOP, then flipped back).  Black body = mask extrusion
    (mesh_common.heightfield_to_mesh), top flush at datum.

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
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import trimesh
from scipy import ndimage
from shapely.geometry import MultiPolygon, box
from shapely.ops import polylabel

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import p4_bay_coupon as p4
import mesh_common
import version_stamp as vstamp

# ------------------------------------------------------------------ params
PX_MM = p4.PX_MM             # print raster (0.05 mm/px; ~4500 x 5000 px)
ROSE_PITCH_MM = 0.15         # compass-rose inlay grid (SVG strokes are
                             # ~0.5 mm at 50 mm diameter -> 3+ cells)
DARK = "#231f20"             # the rose SVG's "black"
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


# ----------------------------------------------------------- compass rose
def _parse_svg(path):
    root = ET.parse(path).getroot()
    vb = [float(t) for t in root.get("viewBox").split()]
    els = []
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        g = el.get
        dark_f = g("fill", "none") == DARK
        dark_s = g("stroke", "none") == DARK
        sw = float(g("stroke-width", "0"))
        if tag == "circle":
            els.append(("circle", dict(
                cx=float(g("cx")), cy=float(g("cy")), r=float(g("r")),
                fill_dark=dark_f, stroke_dark=dark_s and sw > 0, sw=sw)))
        elif tag == "polygon":
            pts = [tuple(float(v) for v in p.split(","))
                   for p in g("points").split()]
            els.append(("polygon", dict(
                pts=pts, fill_dark=dark_f,
                stroke_dark=dark_s and sw > 0, sw=sw)))
        elif tag == "text":
            els.append(("text", dict(
                x=float(g("x")), y=float(g("y")),
                size=float(g("font-size", "16")), s=el.text or "",
                fill_dark=dark_f)))
    return vb, els


def _serif_bold(size_px):
    from PIL import ImageFont
    for p in ("/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
              "/Library/Fonts/Georgia Bold.ttf",
              "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"):
        if Path(p).exists():
            return ImageFont.truetype(p, size_px), Path(p).stem
    import matplotlib
    p = Path(matplotlib.get_data_path()) / "fonts/ttf/DejaVuSerif-Bold.ttf"
    return ImageFont.truetype(str(p), size_px), p.stem


def rasterize_rose(svg_path, diameter_mm, pitch):
    """Black-ink mask of the rose, row 0 = SOUTH, symmetric about the
    rose center (so placing the mask at [compass].center_mm keeps the
    center exact).  diameter_mm = printed outer edge of the outer ring.
    Returns (mask, mm_per_svg_unit, font_name)."""
    from PIL import Image, ImageDraw
    vb, els = _parse_svg(svg_path)
    r_out = max(a["r"] + a["sw"] / 2 for k, a in els
                if k == "circle" and a["stroke_dark"])
    kk = diameter_mm / (2.0 * r_out)      # mm per SVG unit
    f = kk / pitch                        # px per SVG unit
    pad = int(np.ceil((vstamp.MARGIN_MM + 1.0) / pitch))
    W = int(np.ceil(vb[2] * f)) + 2 * pad
    H = int(np.ceil(vb[3] * f)) + 2 * pad
    tx = lambda x: (x - vb[0]) * f + pad
    ty = lambda y: (y - vb[1]) * f + pad
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    font_name = None
    for kind, a in els:
        if kind == "circle":
            if a["fill_dark"]:
                d.ellipse([tx(a["cx"] - a["r"]), ty(a["cy"] - a["r"]),
                           tx(a["cx"] + a["r"]), ty(a["cy"] + a["r"])],
                          fill=255)
            if a["stroke_dark"]:
                ro = a["r"] + a["sw"] / 2      # SVG strokes are centered
                d.ellipse([tx(a["cx"] - ro), ty(a["cy"] - ro),
                           tx(a["cx"] + ro), ty(a["cy"] + ro)],
                          outline=255, width=max(1, round(a["sw"] * f)))
        elif kind == "polygon":
            pts = [(tx(x), ty(y)) for x, y in a["pts"]]
            if a["fill_dark"]:
                d.polygon(pts, fill=255)
            if a["stroke_dark"]:
                d.line(pts + pts[:1], fill=255, joint="curve",
                       width=max(1, round(a["sw"] * f)))
        elif kind == "text" and a["fill_dark"] and a["s"].strip():
            font, font_name = _serif_bold(max(6, round(a["size"] * f)))
            d.text((tx(a["x"]), ty(a["y"])), a["s"].strip(), fill=255,
                   font=font, anchor="mm")
    min_sw = min((a["sw"] for k, a in els
                  if k != "text" and a.get("stroke_dark")), default=0.0)
    m = np.asarray(img) > 127
    m = np.flipud(m)                       # row 0 = south
    # symmetric crop about the artwork center (viewBox center)
    ccol = (0.0 - vb[0]) * f + pad         # rose center in px
    crow = (H - 1) - ((0.0 - vb[1]) * f + pad)   # after flipud
    rows, cols = np.nonzero(m)
    mrg = int(np.ceil(vstamp.MARGIN_MM / pitch)) + 2
    half_c = int(np.ceil(max(ccol - cols.min(), cols.max() + 1 - ccol))) + mrg
    half_r = int(np.ceil(max(crow - rows.min(), rows.max() + 1 - crow))) + mrg
    half_c = min(half_c, int(ccol), W - int(ccol) - 1)
    half_r = min(half_r, int(crow), H - int(crow) - 1)
    m = m[int(crow) - half_r:int(crow) + half_r,
          int(ccol) - half_c:int(ccol) + half_c]
    m, _ = mesh_common.remove_diagonal_pinches(m)
    m[0, :] = m[-1, :] = False
    m[:, 0] = m[:, -1] = False
    return m, kk, font_name, min_sw * kk


def make_rose_stamp():
    """Stamp object for the compass recesses in the water top (mask NOT
    x-mirrored: the rose is carved into the TOP surface, read from
    above), plus the matching black inlay body parameters."""
    svg = base.ROOT / COMPASS["svg"]
    mask, kk, font_name, min_stroke = rasterize_rose(
        svg, COMPASS["diameter_mm"], ROSE_PITCH_MM)
    ny, nx = mask.shape
    w, h = nx * ROSE_PITCH_MM, ny * ROSE_PITCH_MM
    cx, cy = COMPASS["center_mm"]
    rose = vstamp.Stamp(
        text="compass rose (D17)", lines=[], cap_mm=0.0,
        pitch=ROSE_PITCH_MM, depth=COMPASS["inlay_depth_mm"], mask=mask,
        center=(cx, cy), angle=0.0,
        rect=vstamp.rect_poly(cx, cy, w, h, 0.0), dilated_px=0,
        min_stroke_mm=min_stroke)
    return rose, kk, font_name


def black_inlay_mesh(rose):
    """The black body: extrusion of the ink mask, top FLUSH at datum."""
    hf = np.flipud(rose.mask)             # heightfield rows: 0 = north
    top = np.full(hf.shape, rose.depth, np.float64)
    mesh = mesh_common.heightfield_to_mesh(top, hf, rose.pitch)
    ny, nx = rose.mask.shape
    mesh.apply_translation([rose.center[0] - nx * rose.pitch / 2,
                            rose.center[1] - ny * rose.pitch / 2,
                            p4.BASE_MM - rose.depth])
    return mesh


def water_upper_mesh(upper_water, rose):
    """Upper water solid (floor top .. datum) with the rose recesses cut
    into its TOP: built z-mirrored so the stamp machinery (which carves
    bottoms) applies, then flipped back."""
    zb = p4.FLOOR_MM - p4.OVERLAP_MM
    if rose is None:
        return p4.solid_mesh(upper_water,
                             lambda v: np.full(len(v), p4.BASE_MM), zb,
                             quality=False)
    m = p4.solid_mesh(upper_water, lambda v: np.full(len(v), -zb),
                      -p4.BASE_MM, quality=False, stamp=rose)
    return trimesh.Trimesh(vertices=m.vertices * [1.0, 1.0, -1.0],
                           faces=m.faces[:, ::-1], process=False)


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

    # ---- compass rose ---------------------------------------------------
    rose = None
    if COMPASS.get("enabled", False):
        from shapely.geometry import MultiPoint
        rose, kk, font_name = make_rose_stamp()
        w, h = rose.size_mm
        # exact no-land-contact test: every INK cell must lie over open
        # sea (the rect's empty corners may span water next to land, but
        # nothing black may touch land)
        jj, ii = np.nonzero(rose.mask)
        xi = rose.center[0] - w / 2 + (ii + 0.5) * rose.pitch
        yi = rose.center[1] - h / 2 + (jj + 0.5) * rose.pitch
        rr = np.clip(np.round((NS_MM - yi) / PX_MM - 0.5).astype(int),
                     0, ny - 1)
        cc = np.clip(np.round(xi / PX_MM - 0.5).astype(int), 0, nx - 1)
        on_land = ~seaw[rr, cc]
        assert rose.rect.within(upper_water), \
            "rose rectangle overlaps a piece cavity"
        assert not on_land.any(), (
            f"rose ink over land: {on_land.sum()} cells, first at "
            f"({xi[on_land][0] if on_land.any() else 0:.1f}, "
            f"{yi[on_land][0] if on_land.any() else 0:.1f}) mm")
        hull = MultiPoint(
            np.column_stack([xi[::7], yi[::7]])).convex_hull
        d_coast = hull.distance(geo["coast_nom"])
        d_gray = hull.distance(geo["gray"])
        d_cav = hull.distance(cavities)
        print(f"\ncompass rose (D17): ring dia {COMPASS['diameter_mm']:g} "
              f"mm at {tuple(COMPASS['center_mm'])}, artwork+letters "
              f"{w:.1f} x {h:.1f} mm, inlay {rose.depth:g} mm, "
              f"min ink stroke ~{rose.min_stroke_mm:.2f} mm, "
              f"letters font {font_name}\n"
              f"  open-water check: all ink over sea; ink-hull margins "
              f"-- coast {d_coast:.1f} mm, gray {d_gray:.1f} mm, "
              f"cavities {d_cav:.1f} mm")

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
    m_upper = water_upper_mesh(upper_water, rose)
    ok &= p4.report_mesh("water upper", m_upper)
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
    if rose is not None:
        up_lv = sorted(set(np.round(m_upper.vertices[:, 2], 5).tolist()))
        want = [round(v, 5) for v in (p4.FLOOR_MM - p4.OVERLAP_MM,
                                      p4.BASE_MM - rose.depth, p4.BASE_MM)]
        flush_ok = up_lv == want
        ok &= flush_ok
        print(f"    rose recess z-levels {up_lv} == {want}: {flush_ok}")
    coast_mesh = p4.solid_mesh(geo["coast_nom"], terrain_coast, p4.BASE_MM)
    ok &= p4.report_mesh("coast", coast_mesh)
    gray_mesh = p4.solid_mesh(geo["gray"], terrain_coast, p4.BASE_MM)
    ok &= p4.report_mesh("gray", gray_mesh)
    bodies = [("coast", coast_mesh, EXTRUDERS["coast"]),
              ("water", water_mesh, EXTRUDERS["water"]),
              ("gray", gray_mesh, EXTRUDERS["gray"])]
    if rose is not None:
        black_mesh = black_inlay_mesh(rose)
        ok &= p4.report_mesh("black(rose)", black_mesh)
        bb = black_mesh.bounds
        flush = (abs(bb[1][2] - p4.BASE_MM) < 1e-6
                 and abs(bb[0][2] - (p4.BASE_MM - rose.depth)) < 1e-6)
        ok &= flush
        print(f"    black inlay z {bb[0][2]:.3f}..{bb[1][2]:.3f} "
              f"(datum {p4.BASE_MM:g}) -> flush: {flush}")
        bodies.append(("black", black_mesh, EXTRUDERS["black"]))
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

    render_preview(geo, s, holes, stamps, rose, EW_MM)
    print(f"\nall bodies/pieces watertight + checks: {ok}")
    if not ok:
        sys.exit(1)
    print("slicing (G4): vertical walls"
          + (f" with {p4.CHAMFER_MM:g} mm bottom chamfer"
             if p4.CHAMFER_MM > 0 else
             " -- enable elephant-foot compensation")
          + f"; filaments: {EXTRUDERS}")


# ----------------------------------------------------------------- preview
def render_preview(geo, s, holes, stamps, rose, ew_mm):
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

    def draw_rose(ax):
        if rose is None:
            return
        w, h = rose.size_mm
        rgba = np.zeros(rose.mask.shape + (4,))
        rgba[rose.mask] = (0.1, 0.1, 0.1, 1.0)
        ax.imshow(rgba, extent=(rose.center[0] - w / 2,
                                rose.center[0] + w / 2,
                                rose.center[1] - h / 2,
                                rose.center[1] + h / 2),
                  origin="lower", interpolation="nearest", zorder=5)

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
        cx, cy = rose.center
        r = COMPASS["diameter_mm"] / 2
        ax.add_patch(plt.Circle((cx, cy), r, fill=False, lw=0.6,
                                edgecolor="#666", linestyle="--",
                                zorder=6))
        half = max(rose.size_mm) / 2 + 6
        ax.set_xlim(cx - half, cx + half)
        ax.set_ylim(cy - half, cy + half)
        ax.set_title(f"rose close-up — ring dia {2 * r:g} mm, inlay "
                     f"{rose.depth:g} mm flush", fontsize=10)
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
