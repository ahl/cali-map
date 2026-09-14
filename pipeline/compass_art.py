"""D17 compass rose from ahl's Illustrator artwork (assets/compass.svg).

VECTOR end-to-end (2026-09-14 rework; the earlier pipeline rasterized
the SVG at 0.15 mm and meshed pixel cells -- every curve came out a
staircase and the slicer chased micro-segments).  Now:

  - the SVG's SHAPES are parsed directly (circles, polygons, and
    straight/bezier paths; curves flattened at CHORD_TOL_MM chord
    tolerance in print space) into shapely polygons, classified by each
    element's FILL color to its NEAREST reference color:

        dark blue (46, 49, 146)  -> "coast"  (CA-land filament body)
        gray     (193, 199, 210) -> "gray"   (gray body)
        black     (35, 31, 32)   -> "black"  (black body)
        teal      (39, 170, 225) + white/none -> water (no body)

    Paint order is respected exactly: walking the element list in
    REVERSE, each element's visible ink is its shape minus everything
    painted later, so the three ink classes come out DISJOINT with
    shared boundaries whose vertices agree between neighbors.

  - [compass].ink_min_stroke_mm is enforced per class with an exact
    buffer-opening test (erode by stroke/2, dilate back; a vanished
    chunk over the same 0.72 mm^2 tolerance version_stamp uses = a
    stroke thinner than the floor).  Under-floor classes are buffered
    out by the deficit, in black > coast > gray priority; growth is
    clipped against higher-priority ink so classes stay disjoint.
    Black (top priority, nothing can pinch it) is asserted to reach the
    floor; coast/gray are best-effort + reported (they can be boxed in
    by black at a sharp taper of the artwork).

  - N/E/S/W letters are VECTOR OUTLINES (matplotlib TextPath over the
    same Georgia Bold; DejaVu Serif Bold fallback), flattened at
    CHORD_TOL_MM, min-stroked to version_stamp.MIN_STROKE_MM by the
    same buffer test, then merged into the black class.  The letter
    outlines are asserted to keep a POSITIVE vector distance from the
    artwork ink (the cardinal tips reach ~1.36x the ring radius);
    [compass].letter_radius_frac is the knob if they don't.

  - MESHING is a single constrained Delaunay triangulation (`triangle`,
    'p' flags -- no Steiner points, like version_stamp's bottom
    rebuild) of the panel rectangle with every class boundary as a
    constraint segment; each triangle is classified water / coast /
    gray / black.  RosePanel serves both sides of the flush inlay from
    that ONE triangulation:

      RosePanel.build_bottom(...)   -- drop-in for
        version_stamp.stamped_bottom (p4_bay_coupon.solid_mesh
        dispatches on the method): the water body's TOP gets the panel
        rectangle rebuilt as water floor at datum + ink recesses at
        datum - depth, vertical walls along the smooth boundaries,
        stitched to the surrounding water-top CDT through the shared
        rectangle-corner ring (weld-exact, no T-junctions);
      RosePanel.ink_meshes(...)     -- one watertight extrusion per ink
        class between the recess floor and datum ("flush") or datum and
        datum + depth ("raised"), side walls built from the SAME
        triangulation vertices, so inlay walls are float-identical to
        the recess walls.

    Nodes where a class (or the recess) touches itself at a single
    point are split per triangle-fan, so every emitted surface is
    manifold even on pinched artwork.

Scale: the OUTER RING (largest circle in the SVG, outer stroke edge) =
[compass].diameter_mm; the cardinal tips and the letters extend beyond
it -- `tip_r_mm` / `size_mm` report the true footprint for placement.

Used by p4_bay_coupon.py (coupon placement) and p5_final.py (final
frame).  Deps for the importing script's uv header: numpy, shapely,
triangle, trimesh, matplotlib.
"""

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import triangle as tr
import trimesh
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import polylabel, unary_union
from shapely.prepared import prep

import version_stamp as vstamp

CHORD_TOL_MM = 0.02      # max chord deviation for flattened curves (print mm)
INK_RGB = {"coast": (46, 49, 146), "gray": (193, 199, 210),
           "black": (35, 31, 32)}
WATER_KEYS = [(39, 170, 225), (255, 255, 255)]
LETTERS = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
MARGIN_MM = 1.0          # ink -> panel-rectangle margin
_ORDER = ("black", "coast", "gray")   # overlap/dilation priority
_STROKE_TOL_MM2 = 0.72   # opening-loss tolerance (same as version_stamp)


# ---------------------------------------------------------------- SVG parse
def _ring_and_stroke(svg_path):
    """(center_units, ring outer radius units, stroke width units) —
    ring = largest circle; stroke from the CSS/style (max stroke-width)."""
    text = Path(svg_path).read_text()
    sws = [float(v) for v in re.findall(r"stroke-width:\s*([0-9.]+)", text)]
    sw = max(sws) if sws else 0.0
    root = ET.fromstring(text)
    circles = [el for el in root.iter() if el.tag.split("}")[-1] == "circle"]
    assert circles, "no circles in the artwork (need the ring for scale)"
    big = max(circles, key=lambda c: float(c.get("r")))
    return ((float(big.get("cx")), float(big.get("cy"))),
            float(big.get("r")) + sw / 2, sw)


def _css_fills(text):
    """{class name: (r, g, b)} from the SVG's <style> CSS."""
    fills = {}
    for cls, body in re.findall(r"\.([\w-]+)\s*\{([^}]*)\}", text):
        m = re.search(r"fill:\s*([^;\s]+)", body)
        if m:
            fills[cls] = _parse_color(m.group(1))
    return fills


def _parse_color(s):
    s = s.strip()
    if s in ("none", "transparent"):
        return None
    if s.startswith("#"):
        h = s[1:]
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    m = re.match(r"rgb\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*\)", s)
    if m:
        return tuple(int(v) for v in m.groups())
    named = {"black": (0, 0, 0), "white": (255, 255, 255)}
    return named.get(s, (0, 0, 0))


def _elem_fill(el, css):
    """Resolved fill RGB of an element (None = unpainted)."""
    style = el.get("style", "")
    m = re.search(r"fill:\s*([^;]+)", style)
    if m:
        return _parse_color(m.group(1))
    if el.get("fill") is not None:
        return _parse_color(el.get("fill"))
    for cls in (el.get("class") or "").split():
        if cls in css:
            return css[cls]
    return (0, 0, 0)          # SVG default fill = black


def _classify_rgb(rgb):
    """Nearest reference color -> class name or 'water'."""
    if rgb is None:
        return "water"
    refs = [("water", c) for c in WATER_KEYS] + list(INK_RGB.items())
    d = [(sum((a - b) ** 2 for a, b in zip(rgb, ref)), name)
         for name, ref in refs]
    return min(d)[1]


def _bez(P, tol):
    """Uniformly flatten a quadratic/cubic bezier (control points P) so
    the chordal deviation stays under `tol`; returns sampled points
    including both endpoints."""
    P = np.asarray(P, float)
    chord0, chord1 = P[0], P[-1]
    d = chord1 - chord0
    L = np.hypot(*d)
    if L < 1e-12:
        dev = float(max(np.hypot(*(p - chord0)) for p in P[1:-1]))
    else:
        n = np.array([-d[1], d[0]]) / L
        dev = float(max(abs((p - chord0) @ n) for p in P[1:-1]))
    nseg = int(np.clip(np.ceil(np.sqrt(max(dev, 1e-12) / max(tol, 1e-9))) + 1,
                       2, 100))
    t = np.linspace(0.0, 1.0, nseg + 1)[:, None]
    if len(P) == 3:
        pts = (1 - t) ** 2 * P[0] + 2 * (1 - t) * t * P[1] + t ** 2 * P[2]
    else:
        pts = ((1 - t) ** 3 * P[0] + 3 * (1 - t) ** 2 * t * P[1]
               + 3 * (1 - t) * t ** 2 * P[2] + t ** 3 * P[3])
    return pts


def _parse_path(d, tol):
    """Flatten an SVG path `d` (M/L/H/V/C/S/Q/T/Z, abs + rel) to rings."""
    tok = re.findall(r"[MmLlHhVvCcSsQqTtZzAa]|-?\d*\.?\d+(?:e-?\d+)?", d)
    i, cur, start = 0, np.zeros(2), np.zeros(2)
    prev_ctrl, prev_cmd = None, ""
    rings, ring = [], []

    def num():
        nonlocal i
        v = float(tok[i])
        i += 1
        return v

    def pt(rel):
        return np.array([num(), num()]) + (cur if rel else 0.0)

    while i < len(tok):
        c = tok[i]
        if c.isalpha():
            i += 1
        else:
            c = prev_cmd if prev_cmd not in "Mm" else ("L" if prev_cmd == "M"
                                                      else "l")
        rel = c.islower()
        C = c.upper()
        if C == "A":
            raise ValueError("SVG arc segments not supported")
        if C == "M":
            if len(ring) >= 3:
                rings.append(np.asarray(ring))
            cur = pt(rel)
            start = cur.copy()
            ring = [cur.copy()]
        elif C == "L":
            cur = pt(rel)
            ring.append(cur.copy())
        elif C == "H":
            cur = np.array([num() + (cur[0] if rel else 0.0), cur[1]])
            ring.append(cur.copy())
        elif C == "V":
            cur = np.array([cur[0], num() + (cur[1] if rel else 0.0)])
            ring.append(cur.copy())
        elif C in "CSQT":
            if C == "C":
                p1, p2, p3 = pt(rel), pt(rel), pt(rel)
            elif C == "S":
                p1 = (2 * cur - prev_ctrl if prev_cmd.upper() in "CS"
                      and prev_ctrl is not None else cur.copy())
                p2, p3 = pt(rel), pt(rel)
            elif C == "Q":
                p1, p3 = pt(rel), pt(rel)
                p2 = None
            else:  # T
                p1 = (2 * cur - prev_ctrl if prev_cmd.upper() in "QT"
                      and prev_ctrl is not None else cur.copy())
                p2, p3 = None, pt(rel)
            if p2 is None:      # quadratic
                pts = _bez([cur, p1, p3], tol)
                prev_ctrl = p1
            else:
                pts = _bez([cur, p1, p2, p3], tol)
                prev_ctrl = p2
            ring.extend(p.copy() for p in pts[1:])
            cur = p3
        elif C == "Z":
            cur = start.copy()
            if len(ring) >= 3:
                rings.append(np.asarray(ring))
            ring = []
        prev_cmd = c
    if len(ring) >= 3:
        rings.append(np.asarray(ring))
    return rings


def _rings_to_poly(rings):
    """Even-odd assembly of flattened rings into one shapely geometry."""
    polys = []
    for r in rings:
        if len(r) < 3:
            continue
        p = Polygon(r)
        if not p.is_valid:
            p = p.buffer(0)
        if not p.is_empty:
            polys.append(p)
    if not polys:
        return Polygon()
    polys.sort(key=lambda p: p.area, reverse=True)
    geom = polys[0]
    for p in polys[1:]:
        geom = geom.symmetric_difference(p)
    return geom


def _circle_segments(r_mm, tol_mm):
    """Segment count (multiple of 8, preserving dihedral symmetry) so the
    chord sagitta of an r_mm circle stays under tol_mm; returns
    (n, actual sagitta)."""
    n = int(np.ceil(np.pi / np.arccos(max(1.0 - tol_mm / r_mm, -1.0))))
    n = max(16, int(np.ceil(n / 8.0)) * 8)
    return n, r_mm * (1.0 - np.cos(np.pi / n))


def _svg_elements(svg_path, cu, cv, k, tol_mm):
    """Parse the SVG's shapes in PAINT ORDER.  Returns
    ([(shapely geom in LOCAL print mm -- rose center at origin, y up,
    class-or-'water')], max chord deviation of flattened circles)."""
    text = Path(svg_path).read_text()
    css = _css_fills(text)
    root = ET.fromstring(text)
    to_mm = lambda p: np.column_stack([(p[:, 0] - cu) * k,
                                       (cv - p[:, 1]) * k])
    elems, max_dev = [], 0.0
    for el in root.iter():
        tag = el.tag.split("}")[-1]
        if tag not in ("circle", "ellipse", "rect", "polygon", "polyline",
                       "path"):
            continue
        assert el.get("transform") is None, \
            f"<{tag} transform=...> not supported -- flatten in Illustrator"
        rgb = _elem_fill(el, css)
        cname = _classify_rgb(rgb)
        if tag == "circle" or tag == "ellipse":
            cx, cy = float(el.get("cx", 0)), float(el.get("cy", 0))
            rx = float(el.get("r") or el.get("rx"))
            ry = float(el.get("r") or el.get("ry"))
            r_mm = max(rx, ry) * k
            n, dev = _circle_segments(r_mm, tol_mm)
            max_dev = max(max_dev, dev)
            a = np.arange(n) * (2 * np.pi / n)
            lc = np.array([(cx - cu) * k, (cv - cy) * k])
            ring = np.column_stack([lc[0] + rx * k * np.cos(a),
                                    lc[1] + ry * k * np.sin(a)])
            geom = Polygon(ring)
        elif tag == "rect":
            x, y = float(el.get("x", 0)), float(el.get("y", 0))
            w, h = float(el.get("width")), float(el.get("height"))
            ring = to_mm(np.array([(x, y), (x + w, y), (x + w, y + h),
                                   (x, y + h)], float))
            geom = Polygon(ring)
        elif tag in ("polygon", "polyline"):
            nums = [float(v) for v in
                    re.findall(r"-?\d*\.?\d+(?:e-?\d+)?", el.get("points"))]
            pts = np.asarray(nums, float).reshape(-1, 2)
            if len(pts) < 3:
                continue
            geom = Polygon(to_mm(pts))
            if not geom.is_valid:
                geom = geom.buffer(0)
        else:  # path
            rings = [to_mm(r) for r in _parse_path(el.get("d"), tol_mm / k)]
            geom = _rings_to_poly(rings)
        if geom.is_empty:
            continue
        elems.append((geom, cname))
    return elems, max_dev


def _paint_resolve(elems):
    """Paint-order resolution: walk the element list in REVERSE; each
    element's visible ink = its shape minus everything painted later.
    Returns {class: disjoint shapely geometry} (may be empty)."""
    vis = {n: [] for n in _ORDER}
    occ = None
    for geom, cname in reversed(elems):
        vg = geom if occ is None else geom.difference(occ)
        if cname in vis and not vg.is_empty:
            vis[cname].append(vg)
        occ = geom if occ is None else occ.union(geom)
    return {n: (unary_union(vis[n]) if vis[n] else Polygon())
            for n in _ORDER}


# ------------------------------------------------------------ stroke width
def _poly_parts(g):
    return [p for p in getattr(g, "geoms", [g])
            if p.geom_type == "Polygon" and not p.is_empty]


def _open_ok(geom, half_mm, tol_mm2=_STROKE_TOL_MM2):
    """Vector morphological-opening test (exact counterpart of
    version_stamp._stroke_ok): erode by half_mm and dilate back; any
    sizeable vanished chunk = a stroke thinner than 2*half_mm (small
    losses are corner shaving)."""
    opened = geom.buffer(-half_mm).buffer(half_mm)
    missing = geom.difference(opened)
    if missing.is_empty:
        return True
    return max((p.area for p in _poly_parts(missing)), default=0.0) <= tol_mm2


def measure_min_stroke_vec(geom, lo=0.05, hi=1.20, step=0.025):
    """Min stroke width (mm) by the exact buffer-opening test, swept like
    the raster version (largest passing radius).  Empty -> 0.0."""
    if geom.is_empty:
        return 0.0
    ok = 0.0
    for half in np.arange(lo, hi, step):
        if _open_ok(geom, half):
            ok = max(ok, half)
    return round(2 * ok, 6)


def _dilate_to_stroke(geom, floor_mm, claimed=None, s0=None, max_iter=6):
    """Buffer `geom` outward until its min stroke clears floor_mm; growth
    is clipped against `claimed` (higher-priority ink) so classes stay
    disjoint.  A step that gains no area means the class is boxed in --
    stop (best effort).  Returns (geom, total buffer mm, final stroke)."""
    s = measure_min_stroke_vec(geom) if s0 is None else s0
    dil = 0.0
    for _ in range(max_iter):
        if geom.is_empty or s >= floor_mm - 1e-9:
            break
        step = max((floor_mm - s) / 2, 0.02)
        g2 = geom.buffer(step)
        if claimed is not None and not claimed.is_empty:
            g2 = g2.difference(claimed)
        if g2.area <= geom.area + 1e-9:
            break
        geom, dil = g2, dil + step
        s = measure_min_stroke_vec(geom)
    return geom, dil, s


# ---------------------------------------------------------------- lettering
def _font_file(name):
    for p in (f"/System/Library/Fonts/Supplemental/{name}.ttf",
              f"/Library/Fonts/{name}.ttf",
              "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"):
        if Path(p).exists():
            return p
    import matplotlib
    return str(Path(matplotlib.get_data_path())
               / "fonts/ttf/DejaVuSerif-Bold.ttf")


def _flatten_mpl_path(tp, tol):
    """matplotlib Path -> flattened rings (beziers at `tol` chord dev)."""
    from matplotlib.path import Path as MPath
    verts, codes = tp.vertices, tp.codes
    if codes is None:
        return [np.asarray(verts)]
    rings, cur = [], []
    i = 0
    while i < len(codes):
        c = codes[i]
        if c == MPath.MOVETO:
            if len(cur) >= 3:
                rings.append(np.asarray(cur))
            cur = [verts[i]]
            i += 1
        elif c == MPath.LINETO:
            cur.append(verts[i])
            i += 1
        elif c == MPath.CURVE3:
            cur.extend(_bez([cur[-1], verts[i], verts[i + 1]], tol)[1:])
            i += 2
        elif c == MPath.CURVE4:
            cur.extend(_bez([cur[-1], verts[i], verts[i + 1],
                             verts[i + 2]], tol)[1:])
            i += 3
        elif c == MPath.CLOSEPOLY:
            if len(cur) >= 3:
                rings.append(np.asarray(cur))
            cur = []
            i += 1
        else:
            i += 1
    if len(cur) >= 3:
        rings.append(np.asarray(cur))
    return rings


def _letter_poly(ch, font_file, cap_mm, tol_mm):
    """Vector outline of `ch` scaled so the CAP height ('H') = cap_mm,
    origin at the glyph-bbox center (the anchor point)."""
    from matplotlib.font_manager import FontProperties
    from matplotlib.textpath import TextPath
    fp = FontProperties(fname=font_file)
    cap100 = TextPath((0, 0), "H", size=100.0, prop=fp).get_extents().height
    tp = TextPath((0, 0), ch, size=100.0 * cap_mm / cap100, prop=fp)
    geom = _rings_to_poly(_flatten_mpl_path(tp, tol_mm))
    minx, miny, maxx, maxy = geom.bounds
    return affinity.translate(geom, -(minx + maxx) / 2, -(miny + maxy) / 2)


# ------------------------------------------------------------------- rose
@dataclass
class RoseArt:
    polys: dict          # name -> shapely geometry, LOCAL mm (center at
                         # origin, y up), classes mutually DISJOINT
    diameter_mm: float   # outer ring (scale reference)
    tip_r_mm: float      # true max ink radius (tips/letters)
    letter_r_mm: float
    black_stroke_mm: float       # artwork outline stroke width (declared)
    letter_min_stroke_mm: float  # min over letters, final
    font_file: str
    cardinal_tip_r_mm: float     # max radius of artwork ink (no letters),
                                 # AFTER ink_min_stroke_mm dilation
    letter_tip_gap_mm: float     # letter outline -> artwork ink distance
    ink_stroke_before_mm: dict   # per-class min stroke, raw classification
    ink_stroke_after_mm: dict    # per-class min stroke, after dilation
    ink_dilated_mm: dict         # per-class buffer distance applied
    letter_strokes_mm: dict      # ch -> (before, after, buffer mm)
    chord_dev_mm: float          # max chord deviation of flattened curves
    half_mm: tuple               # panel half-extents (w/2, h/2)

    @property
    def size_mm(self):
        return (2 * self.half_mm[0], 2 * self.half_mm[1])

    def ink_union(self):
        return unary_union([g for g in self.polys.values()
                            if not g.is_empty])

    def cell_centers(self, center_mm, step=0.15):
        """World (x, y) sample points covering the ink (grid interior
        points + every boundary vertex) -- for raster overlap checks."""
        u = self.ink_union()
        minx, miny, maxx, maxy = u.bounds
        xs = np.arange(minx + step / 2, maxx, step)
        ys = np.arange(miny + step / 2, maxy, step)
        X, Y = np.meshgrid(xs, ys)
        X, Y = X.ravel(), Y.ravel()
        try:
            from shapely import contains_xy
            inside = contains_xy(u, X, Y)
        except ImportError:
            pu = prep(u)
            inside = np.fromiter((pu.contains(Point(x, y))
                                  for x, y in zip(X, Y)), bool, len(X))
        bx, by = [], []
        for p in _poly_parts(u):
            for ring in (p.exterior, *p.interiors):
                c = np.asarray(ring.coords)
                bx.append(c[:, 0])
                by.append(c[:, 1])
        xi = np.concatenate([X[inside]] + bx) + center_mm[0]
        yi = np.concatenate([Y[inside]] + by) + center_mm[1]
        return xi, yi

    def ink_hull(self, center_mm, step=None):
        return affinity.translate(self.ink_union().convex_hull,
                                  center_mm[0], center_mm[1])


def _max_r(geom):
    m = 0.0
    for p in _poly_parts(geom):
        for ring in (p.exterior, *p.interiors):
            c = np.asarray(ring.coords)
            m = max(m, float(np.hypot(c[:, 0], c[:, 1]).max()))
    return m


def load_rose(svg_path, diameter_mm, letter_font, letter_cap_mm,
              letter_radius_frac, ink_min_stroke_mm):
    (cu, cv), r_out_u, sw_u = _ring_and_stroke(svg_path)
    k = diameter_mm / (2.0 * r_out_u)     # mm per SVG unit
    elems, chord_dev = _svg_elements(svg_path, cu, cv, k, CHORD_TOL_MM)
    classes = _paint_resolve(elems)

    # ink_min_stroke_mm (D17): exact buffer-opening test per class; grow
    # under-floor classes by the deficit in black > coast > gray priority,
    # clipped against higher-priority ink (disjoint by construction).
    ink_stroke_before_mm = {n: measure_min_stroke_vec(classes[n])
                            for n in _ORDER}
    ink_dilated_mm, ink_stroke_after_mm = {}, {}
    claimed = None
    for n in _ORDER:
        g = classes[n]
        if (claimed is not None and not g.is_empty
                and g.intersection(claimed).area > 1e-12):
            g = g.difference(claimed)     # higher class grew over us
        g, d, s = _dilate_to_stroke(g, ink_min_stroke_mm, claimed,
                                    s0=ink_stroke_before_mm[n])
        classes[n], ink_dilated_mm[n], ink_stroke_after_mm[n] = g, d, s
        claimed = g if claimed is None else unary_union([claimed, g])
    print(f"  [compass] ink min stroke (target {ink_min_stroke_mm:g} mm): "
          + ", ".join(f"{n} {ink_stroke_before_mm[n]:.2f}->"
                      f"{ink_stroke_after_mm[n]:.2f} mm "
                      f"(+{ink_dilated_mm[n]:.2f} mm buffer)"
                      for n in _ORDER))
    assert ink_stroke_after_mm["black"] >= ink_min_stroke_mm - 1e-6, \
        (f"black ink stroke {ink_stroke_after_mm['black']:.2f} mm still "
         f"under {ink_min_stroke_mm:g} mm after {ink_dilated_mm['black']:.2f}"
         " mm of dilation")
    for n in ("coast", "gray"):
        if (not classes[n].is_empty
                and ink_stroke_after_mm[n] < ink_min_stroke_mm - 1e-6):
            print(f"  [compass] WARNING: {n} ink stroke "
                  f"{ink_stroke_after_mm[n]:.2f} mm still under "
                  f"{ink_min_stroke_mm:g} mm -- boxed in by black at its "
                  "narrowest taper; a geometric limit of the artwork at "
                  "this scale, not a dilation shortfall")

    artwork_ink = claimed
    cardinal_tip_r_mm = _max_r(artwork_ink)

    # pipeline lettering: vector outlines, min-stroked like the version
    # stamps (same 0.8 mm floor; N/E/S/W have no counters to close up)
    ff = _font_file(letter_font)
    letter_r_mm = letter_radius_frac * diameter_mm / 2
    letter_strokes_mm, lpolys = {}, []
    for ch, (ux, uy) in LETTERS.items():
        g = affinity.translate(
            _letter_poly(ch, ff, letter_cap_mm, CHORD_TOL_MM),
            ux * letter_r_mm, uy * letter_r_mm)
        s0 = measure_min_stroke_vec(g)
        g, d, s1 = _dilate_to_stroke(g, vstamp.MIN_STROKE_MM, s0=s0)
        letter_strokes_mm[ch] = (s0, s1, d)
        lpolys.append(g)
    letters = unary_union(lpolys)
    letter_stroke = min(s for _, s, _ in letter_strokes_mm.values())
    print("  [compass] letter min stroke (target "
          f"{vstamp.MIN_STROKE_MM:g} mm): "
          + ", ".join(f"{ch} {b:.2f}->{a:.2f} mm (+{d:.2f})"
                      for ch, (b, a, d) in letter_strokes_mm.items()))

    # D17 letter/tip clearance, now an exact vector distance between the
    # letter outlines and the artwork ink (which reaches ~1.36x the ring
    # radius at the cardinal tips)
    letter_tip_gap_mm = float(letters.distance(artwork_ink))
    letter_min_r_mm = float(Point(0, 0).distance(letters))
    print(f"  [compass] letter/tip gap: {letter_tip_gap_mm:+.3f} mm "
          f"(artwork ink to r {cardinal_tip_r_mm:.3f} mm, letter ink "
          f"from r {letter_min_r_mm:.3f} mm)")
    assert letter_tip_gap_mm > 0, (
        f"letter ink touches/overlaps the cardinal tips: gap "
        f"{letter_tip_gap_mm:.3f} mm -- increase "
        "[compass].letter_radius_frac to move the letters outward")

    classes["black"] = unary_union([classes["black"], letters])
    for n in ("coast", "gray"):
        if classes[n].intersection(letters).area > 1e-12:
            classes[n] = classes[n].difference(letters)

    for i, a in enumerate(_ORDER):
        for b in _ORDER[i + 1:]:
            ov = classes[a].intersection(classes[b]).area
            assert ov < 1e-6, f"{a}/{b} ink classes overlap ({ov:g} mm^2)"

    tip_r = max(_max_r(classes[n]) for n in _ORDER)
    xs, ys = [], []
    for n in _ORDER:
        for p in _poly_parts(classes[n]):
            x0, y0, x1, y1 = p.bounds
            xs += [abs(x0), abs(x1)]
            ys += [abs(y0), abs(y1)]
    half = (max(xs) + MARGIN_MM, max(ys) + MARGIN_MM)
    def _nverts(g):
        return sum(len(p.exterior.coords) - 1
                   + sum(len(r.coords) - 1 for r in p.interiors)
                   for p in _poly_parts(g))
    print(f"  [compass] vector artwork: chord dev <= {chord_dev:.4f} mm, "
          "boundary vertices "
          + ", ".join(f"{n} {_nverts(classes[n])}" for n in _ORDER))
    return RoseArt(polys=classes, diameter_mm=diameter_mm, tip_r_mm=tip_r,
                   letter_r_mm=letter_r_mm, black_stroke_mm=sw_u * k,
                   letter_min_stroke_mm=letter_stroke, font_file=ff,
                   cardinal_tip_r_mm=cardinal_tip_r_mm,
                   letter_tip_gap_mm=letter_tip_gap_mm,
                   ink_stroke_before_mm=ink_stroke_before_mm,
                   ink_stroke_after_mm=ink_stroke_after_mm,
                   ink_dilated_mm=ink_dilated_mm,
                   letter_strokes_mm=letter_strokes_mm,
                   chord_dev_mm=chord_dev, half_mm=half)


# ----------------------------------------------------------------- meshing
def _fan_slots(tris, sel, edge_map):
    """Per-corner vertex slots over the triangle subset `sel` ((T,) bool).
    Corners at one node normally share a slot; where the subset touches
    itself at a single node (a pinch), each triangle FAN around the node
    (connectivity via shared subset edges) gets its OWN slot, so emitted
    surfaces stay manifold.  Returns (slot (T,3), node ids (n_slots,))."""
    parent = {}

    def find(x):
        r = x
        while parent[r] != r:
            r = parent[r]
        while parent[x] != r:
            parent[x], x = r, parent[x]
        return r

    sel_idx = np.nonzero(sel)[0]
    corner_of = {}
    for t in sel_idx:
        for c in range(3):
            parent[(t, c)] = (t, c)
            corner_of[(t, int(tris[t, c]))] = c
    for (u, v), lst in edge_map.items():
        ts = [t for t, _ in lst if sel[t]]
        if len(ts) == 2:
            t1, t2 = ts
            for node in (u, v):
                a = find((t1, corner_of[(t1, node)]))
                b = find((t2, corner_of[(t2, node)]))
                if a != b:
                    parent[a] = b
    slot = np.full(tris.shape, -1, np.int64)
    nodes, root_slot = [], {}
    for t in sel_idx:
        for c in range(3):
            r = find((t, c))
            s = root_slot.get(r)
            if s is None:
                s = len(nodes)
                root_slot[r] = s
                nodes.append(int(tris[t, c]))
            slot[t, c] = s
    return slot, np.asarray(nodes, np.int64)


class RosePanel:
    """One constrained Delaunay triangulation of the rose panel, shared
    by the water body's flush recesses (build_bottom) and the ink inlay
    bodies (ink_meshes) so their walls are float-identical."""

    def __init__(self, rose, center_mm, depth_mm):
        self.rose = rose
        self.center = (float(center_mm[0]), float(center_mm[1]))
        self.depth = float(depth_mm)
        w, h = rose.size_mm
        self.rect = vstamp.rect_poly(self.center[0], self.center[1],
                                     w, h, 0.0)
        self._build()

    def _build(self):
        cx, cy = self.center
        rose = self.rose
        world = {n: affinity.translate(rose.polys[n], cx, cy)
                 for n in _ORDER if not rose.polys[n].is_empty}
        self.class_names = [n for n in _ORDER if n in world]

        pool, pts = {}, []

        def vid(x, y):
            key = (round(x, 7), round(y, 7))
            i = pool.get(key)
            if i is None:
                i = len(pts)
                pool[key] = i
                pts.append((x, y))
            return i

        # NODE the class boundaries into one consistent planar linework
        # (unary_union splits lines at every crossing/T-junction and
        # dissolves shared portions) -- classes produced by shapely
        # differences can carry vertices on a neighbor's edge interior,
        # which `triangle` rejects as inconsistent segments otherwise.
        noded = unary_union([g.boundary for g in world.values()])
        segs = set()
        for ln in getattr(noded, "geoms", [noded]):
            ids = []
            for x, y in np.asarray(ln.coords):
                i = vid(x, y)
                if not ids or ids[-1] != i:
                    ids.append(i)
            for a, b in zip(ids, ids[1:]):
                if a != b:
                    segs.add((a, b) if a < b else (b, a))
        ring = np.asarray(self.rect.exterior.coords)[:-1]
        rids = [vid(x, y) for x, y in ring]
        for a, b in zip(rids, rids[1:] + rids[:1]):
            segs.add((a, b) if a < b else (b, a))

        pts = np.asarray(pts, float)
        ink_all = unary_union(list(world.values()))
        assert self.rect.exterior.distance(ink_all) > 0.25, \
            "rose ink too close to the panel border"
        B = tr.triangulate({"vertices": pts,
                            "segments": np.asarray(sorted(segs), np.int32)},
                           "p")
        bv = B["vertices"]
        assert len(bv) == len(pts), "triangle added Steiner points on 'p' run"
        tris = B["triangles"].astype(np.int64)
        a = bv[tris[:, 0]]
        cross = ((bv[tris[:, 1]] - a)[:, 0] * (bv[tris[:, 2]] - a)[:, 1]
                 - (bv[tris[:, 1]] - a)[:, 1] * (bv[tris[:, 2]] - a)[:, 0])
        tris[cross < 0] = tris[cross < 0][:, ::-1]      # all CCW from +z

        cent = bv[tris].mean(axis=1)
        tcls = np.zeros(len(tris), np.int8)
        preps = {n: prep(world[n]) for n in self.class_names}
        for i in range(len(tris)):
            p = Point(cent[i, 0], cent[i, 1])
            for ci, n in enumerate(self.class_names, start=1):
                if preps[n].contains(p):
                    tcls[i] = ci
                    break
        # classification sanity: triangle area per class == polygon area
        tri_area = 0.5 * np.abs(cross)
        for ci, n in enumerate(self.class_names, start=1):
            got = float(tri_area[tcls == ci].sum())
            assert abs(got - world[n].area) < 1e-3, \
                (f"panel CDT mis-classification: {n} triangles "
                 f"{got:.4f} mm^2 vs polygons {world[n].area:.4f} mm^2")

        edge_map = {}
        for t in range(len(tris)):
            p0, p1, p2 = tris[t]
            for u, v in ((p0, p1), (p1, p2), (p2, p0)):
                key = (u, v) if u < v else (v, u)
                edge_map.setdefault(key, []).append((t, (u, v)))
        for key, lst in edge_map.items():
            if len(lst) == 1:                # panel-rect border edge
                assert tcls[lst[0][0]] == 0, "ink touches the panel border"
        self.bv, self.tris, self.tcls, self.edge_map = bv, tris, tcls, edge_map

    def _neighbor(self, t, a, b):
        key = (a, b) if a < b else (b, a)
        lst = self.edge_map[key]
        others = [o for o, _ in lst if o != t]
        return others[0] if others else -1

    # -- water body side -------------------------------------------------
    def build_bottom(self, part, v2, boundary_edges, z_bottom):
        """Bottom face of `part` (shapely Polygon) with the rose panel
        patch replacing the panel rectangle -- same contract as
        version_stamp.stamped_bottom (p4_bay_coupon.solid_mesh dispatches
        on this method; the water body is built z-MIRRORED, so this
        'bottom' becomes the water TOP): outer 'p' CDT of the part with
        the rect as a hole (constraints = the part's wall-vertex chain +
        the rect's corner ring, both matched exactly -- no T-junctions),
        plus the two-level panel patch: water floor at z_bottom, ink
        recess ceilings at z_bottom + depth, vertical walls along the
        smooth class boundaries."""
        cx, cy = self.center
        ring = np.asarray(self.rect.exterior.coords)[:-1]
        bidx = np.unique(boundary_edges)
        remap = np.full(len(v2), -1, np.int64)
        remap[bidx] = np.arange(len(bidx))
        pts = np.vstack([v2[bidx], ring])
        ring_ids = len(bidx) + np.arange(len(ring))
        segs = np.vstack([remap[boundary_edges],
                          np.column_stack([ring_ids,
                                           np.roll(ring_ids, -1)])])
        holes = [[cx, cy]]
        for h in part.interiors:
            p = polylabel(Polygon(h), 0.05)
            holes.append([p.x, p.y])
        B = tr.triangulate({"vertices": pts.astype(float),
                            "segments": segs.astype(np.int32),
                            "holes": np.asarray(holes, float)}, "p")
        ov, of = B["vertices"], B["triangles"].astype(np.int64)
        assert len(ov) == len(pts), "triangle added Steiner points on 'p' run"
        a = ov[of[:, 0]]
        cross = ((ov[of[:, 1]] - a)[:, 0] * (ov[of[:, 2]] - a)[:, 1]
                 - (ov[of[:, 1]] - a)[:, 1] * (ov[of[:, 2]] - a)[:, 0])
        of[cross > 0] = of[cross > 0][:, ::-1]      # CW from +z: normal -z
        verts = [np.column_stack([ov, np.full(len(ov), float(z_bottom))])]
        faces = [of]
        off = len(ov)

        zf = float(z_bottom)
        zc = zf + self.depth
        water = self.tcls == 0
        ink = ~water
        fslot, fnode = _fan_slots(self.tris, water, self.edge_map)
        cslot, cnode = _fan_slots(self.tris, ink, self.edge_map)
        F0, C0 = off, off + len(fnode)
        verts.append(np.column_stack([self.bv[fnode],
                                      np.full(len(fnode), zf)]))
        verts.append(np.column_stack([self.bv[cnode],
                                      np.full(len(cnode), zc)]))
        faces.append(F0 + fslot[water][:, ::-1])    # floor, normal -z
        faces.append(C0 + cslot[ink][:, ::-1])      # recess ceiling, -z

        walls = []
        cof = {}                                    # (t, node) -> corner
        for t in np.nonzero(water)[0]:
            for c in range(3):
                cof[(t, int(self.tris[t, c]))] = c
        for t in np.nonzero(ink)[0]:
            for ca, cb in ((0, 1), (1, 2), (2, 0)):
                a, b = int(self.tris[t, ca]), int(self.tris[t, cb])
                tw = self._neighbor(t, a, b)
                if tw < 0 or self.tcls[tw] != 0:
                    continue
                fa = F0 + fslot[tw, cof[(tw, a)]]
                fb = F0 + fslot[tw, cof[(tw, b)]]
                ka = C0 + cslot[t, ca]
                kb = C0 + cslot[t, cb]
                # directed edge a->b has the ink on its LEFT; the wall's
                # outward normal points from the solid INTO the recess
                walls += [(fb, fa, ka), (fb, ka, kb)]
        faces.append(np.asarray(walls, np.int64))

        V = np.vstack(verts)
        F = np.vstack([f for f in faces if len(f)])
        assert F.min() >= 0 and F.max() < len(V)
        return V, F

    # -- ink body side ---------------------------------------------------
    def ink_meshes(self, base_mm, style="raised"):
        """One watertight extrusion per ink class.  style='flush': inlaid,
        tops level with the water surface (base-depth .. base), side
        walls float-identical to the recess walls from build_bottom.
        style='raised': bodies sit ON the water top (base .. base+depth)."""
        z0, z1 = ((float(base_mm) - self.depth, float(base_mm))
                  if style == "flush"
                  else (float(base_mm), float(base_mm) + self.depth))
        out = {}
        for ci, name in enumerate(self.class_names, start=1):
            sel = self.tcls == ci
            if not sel.any():
                continue
            slot, node = _fan_slots(self.tris, sel, self.edge_map)
            n = len(node)
            verts = np.vstack([
                np.column_stack([self.bv[node], np.full(n, z1)]),   # top
                np.column_stack([self.bv[node], np.full(n, z0)])])  # bottom
            faces = [slot[sel],                     # top, normal +z (CCW)
                     slot[sel][:, ::-1] + n]        # bottom, normal -z
            walls = []
            for t in np.nonzero(sel)[0]:
                for ca, cb in ((0, 1), (1, 2), (2, 0)):
                    a, b = int(self.tris[t, ca]), int(self.tris[t, cb])
                    to = self._neighbor(t, a, b)
                    if to >= 0 and self.tcls[to] == ci:
                        continue                    # interior edge
                    at, bt = slot[t, ca], slot[t, cb]
                    # class interior LEFT of a->b; outward normal RIGHT
                    walls += [(at + n, bt + n, bt), (at + n, bt, at)]
            faces.append(np.asarray(walls, np.int64))
            F = np.vstack([np.asarray(f, np.int64) for f in faces
                           if len(f)])
            m = trimesh.Trimesh(vertices=verts, faces=F, process=False)
            if m.volume < 0:
                m.invert()
            out[name] = m
        return out


def relief_meshes(rose, center_mm, base_mm, depth_mm, style="raised",
                  panel=None):
    """One watertight extrusion per ink class (see RosePanel.ink_meshes).
    Pass the RosePanel used for the water recesses to share its
    triangulation; building a fresh one is deterministic and yields
    identical coordinates."""
    if panel is None:
        panel = RosePanel(rose, center_mm, depth_mm)
    return panel.ink_meshes(base_mm, style)


# ------------------------------------------------------------------ preview
def draw_rose(ax, rose, center_mm, colors, z=5):
    """Preview: the three ink classes as vector patches in PRINT colors."""
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MPath
    for name, g in rose.polys.items():
        if g.is_empty:
            continue
        gg = affinity.translate(g, center_mm[0], center_mm[1])
        verts, codes = [], []
        for p in _poly_parts(gg):
            for ring in (p.exterior, *p.interiors):
                c = np.asarray(ring.coords)
                verts.append(c)
                codes += ([MPath.MOVETO] + [MPath.LINETO] * (len(c) - 2)
                          + [MPath.CLOSEPOLY])
        if not verts:
            continue
        ax.add_patch(PathPatch(MPath(np.vstack(verts), codes),
                               facecolor=colors[name], edgecolor="none",
                               zorder=z))
