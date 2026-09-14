"""Version stamps: text debossed into the flat bottom of printed parts.

3DBenchy-style iteration tags: every part carries "<build_tag> <date>
<details>" debossed DEPTH_MM (0.4 mm = two 0.2 mm layers) UP into its
bottom face (bottom at z = z_bottom, normally 0), MIRRORED in x so the
text reads correctly when the printed part is flipped over in hand.
Used by p4_bay_coupon.py; written to be imported unchanged by the P5
full-generation drivers.

No mesh booleans.  The text is rasterized (PIL + the DejaVu Sans Bold
that ships inside matplotlib) into a cell mask on a fine grid (PITCH_MM)
over a stamp rectangle, and the part's bottom face is REBUILT:

  - constrained Delaunay (`triangle`, "p" flags: no Steiner points) of
    the bottom polygon with the stamp rectangle as a hole.  Its input
    vertices are exactly the part's wall-bottom vertex chain (the
    boundary vertices of the top triangulation, Steiner points included)
    plus the rectangle's perimeter grid nodes, with those edges as
    constraint segments -- so every wall edge and every patch edge is
    matched exactly (no T-junctions);
  - a two-level heightfield patch over the rectangle: z = z_bottom
    outside glyphs, z_bottom + depth inside glyphs, with vertical
    micro-walls at every level change.  The glyph mask is made
    4-connected-clean with mesh_common.remove_diagonal_pinches and kept
    off the rectangle border by a MARGIN_MM margin, so the perimeter
    ring stays at z_bottom and stitches to the outer CDT.

The placement search (make_stamp) may ROTATE the whole stamp rectangle
(grid and all, rigidly) so narrow elongated pieces get their text laid
along their long axis; it also auto-splits the text into 2-3 balanced
lines and shrinks the cap height (never the stroke floor) until the
rectangle fits the allowed region.

All face blocks are welded on rounded-exact coordinates; the result
stays watertight (callers assert via trimesh).

Module deps (must be in the importing script's uv header): numpy, scipy,
shapely, triangle, pillow, matplotlib, trimesh (via mesh_common).
"""

import datetime
import itertools
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage
from shapely.geometry import Polygon, box
from shapely.ops import polylabel
from shapely.prepared import prep

import mesh_common

# ------------------------------------------------------------------ params
DEPTH_MM = 0.4        # deboss depth (2 layers at 0.2 mm)
PITCH_MM = 0.10       # glyph grid resolution (mm/cell)
MIN_STROKE_MM = 0.8   # every glyph stroke at least this wide (2 nozzles)
CAP_MM = 5.0          # target capital height
CAP_MIN_MM = 2.8      # smallest cap height the auto-fit may fall to
CAP_STEP = 0.88       # geometric cap shrink per fit attempt
MARGIN_MM = 0.7       # ink -> rectangle-edge margin
LINE_GAP_FRAC = 0.45  # inter-line gap as a fraction of cap height


@dataclass
class Stamp:
    """A placed, rasterized bottom stamp.

    mask is (ny, nx) bool on the PITCH grid in the stamp's LOCAL frame
    (row 0 = the baseline side, i.e. local -v), already x-mirrored:
    viewed from BELOW the part it reads correctly.  The stamp rectangle
    may be ROTATED by `angle` degrees about `center` (narrow pieces get
    their text laid along their long axis); `rect` is the placed
    (possibly rotated) rectangle polygon in part coordinates.
    """
    text: str
    lines: list
    cap_mm: float
    pitch: float
    depth: float
    mask: np.ndarray
    center: tuple        # (x, y) mm, part coords
    angle: float         # degrees CCW, normalized to (-90, 90]
    rect: Polygon
    dilated_px: int      # extra dilation applied to reach MIN_STROKE_MM
    min_stroke_mm: float # measured (opening test) lower bound

    @property
    def size_mm(self):
        ny, nx = self.mask.shape
        return (nx * self.pitch, ny * self.pitch)


def stamp_date():
    """Generation date, ISO format (the <YYYY-MM-DD> field)."""
    return datetime.date.today().isoformat()


# ------------------------------------------------------------- rasterizing
_FONT_CACHE = {}


def _font(size_px):
    f = _FONT_CACHE.get(size_px)
    if f is not None:
        return f
    from PIL import ImageFont
    try:
        import matplotlib
        p = (Path(matplotlib.get_data_path()) / "fonts" / "ttf"
             / "DejaVuSans-Bold.ttf")
        f = ImageFont.truetype(str(p), size_px)
    except Exception:                              # noqa: BLE001
        f = ImageFont.load_default(size_px)
    _FONT_CACHE[size_px] = f
    return f


def render_mask(lines, cap_mm, pitch=PITCH_MM, mirror=True):
    """Rasterize text lines to a bool cell mask, row 0 = south (y up),
    x-mirrored by default (reads correctly from below)."""
    from PIL import Image, ImageDraw
    probe = _font(64)
    pb = probe.getbbox("H")
    size = max(10, int(round(cap_mm / pitch * 64.0 / (pb[3] - pb[1]))))
    font = _font(size)
    draw0 = ImageDraw.Draw(Image.new("L", (4, 4)))
    sp = int(round(LINE_GAP_FRAC * cap_mm / pitch))
    txt = "\n".join(lines)
    bb = draw0.multiline_textbbox((0, 0), txt, font=font, spacing=sp,
                                  align="center")
    mpx = max(2, int(round(MARGIN_MM / pitch)))
    img = Image.new("L", (int(np.ceil(bb[2] - bb[0])) + 2 * mpx,
                          int(np.ceil(bb[3] - bb[1])) + 2 * mpx), 0)
    ImageDraw.Draw(img).multiline_text((mpx - bb[0], mpx - bb[1]), txt,
                                       fill=255, font=font, spacing=sp,
                                       align="center")
    m = np.asarray(img) > 127
    m = np.flipud(m)               # PIL row 0 = top -> our row 0 = south
    if mirror:
        m = m[:, ::-1]
    return m


# ------------------------------------------------------------ stroke width
def _disk(r_px):
    r = int(np.ceil(r_px))
    yy, xx = np.mgrid[-r:r + 1, -r:r + 1]
    return (xx * xx + yy * yy) <= r_px * r_px + 1e-9


def _stroke_ok(mask, half_mm, pitch):
    """Morphological-opening test: opening with a disk of radius half_mm
    must not delete any sizeable connected chunk of ink (a vanished chunk
    = a stroke thinner than 2*half_mm; small losses are corner shaving)."""
    opened = ndimage.binary_opening(mask, structure=_disk(half_mm / pitch))
    missing = mask & ~opened
    if not missing.any():
        return True
    lab, n = ndimage.label(missing)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    return sizes.max() <= 0.72 / (pitch * pitch)   # 0.72 mm^2 tolerance


def measure_min_stroke(mask, pitch):
    """Lower bound on the narrowest stroke (mm) via the opening test."""
    ok = 0.0
    for half in np.arange(0.30, 0.71, 0.05):
        if _stroke_ok(mask, half, pitch):
            ok = half
        else:
            break
    return 2 * ok


def _ensure_stroke(mask, pitch, min_stroke):
    dil = 0
    while not _stroke_ok(mask, min_stroke / 2, pitch) and dil < 4:
        mask = ndimage.binary_dilation(mask, structure=_disk(1.0))
        dil += 1
    return mask, dil, _stroke_ok(mask, min_stroke / 2, pitch)


# --------------------------------------------------------------- placement
def _layouts(text, max_lines=3):
    """[[text]] then balanced 2-line, 3-line word splits."""
    words = text.split()
    outs = [[text]]
    for n in range(2, min(max_lines, len(words)) + 1):
        best, bw = None, None
        for cuts in itertools.combinations(range(1, len(words)), n - 1):
            idx = (0,) + cuts + (len(words),)
            lines = [" ".join(words[a:b]) for a, b in zip(idx, idx[1:])]
            w = max(len(ln) for ln in lines)
            if bw is None or w < bw:
                best, bw = lines, w
        if best:
            outs.append(best)
    return outs


def _norm_angle(a):
    """Fold to (-90, 90] so stamped text is never fully upside down."""
    return ((a + 90.0) % 180.0) - 90.0


def rect_poly(cx, cy, w_mm, h_mm, angle):
    """The stamp rectangle: w x h, rotated `angle` deg CCW about its
    center (cx, cy)."""
    ca, sa = np.cos(np.radians(angle)), np.sin(np.radians(angle))
    return Polygon([(cx + ca * du - sa * dv, cy + sa * du + ca * dv)
                    for du, dv in ((-w_mm / 2, -h_mm / 2),
                                   (w_mm / 2, -h_mm / 2),
                                   (w_mm / 2, h_mm / 2),
                                   (-w_mm / 2, h_mm / 2))])


def _principal_angle(geom):
    """Orientation (deg) of the long axis of geom's min rotated rect."""
    with np.errstate(divide="ignore", invalid="ignore"):
        mrr = geom.minimum_rotated_rectangle
    if mrr.geom_type != "Polygon":
        return 0.0
    c = np.asarray(mrr.exterior.coords)[:4]
    e = np.diff(np.vstack([c, c[:1]]), axis=0)
    v = e[np.argmax(np.hypot(e[:, 0], e[:, 1]))]
    return _norm_angle(np.degrees(np.arctan2(v[1], v[0])))


def _place(w_mm, h_mm, allowed, anchor, step=2.0):
    """w x h rectangle fully inside `allowed`, as close to `anchor` as
    the search grid finds (anchor tried first).  Tries horizontal, then
    the region's principal axis, then a fan of other angles.  Returns
    (center, angle, rect_polygon) or None."""
    if allowed.is_empty:
        return None
    parts = list(getattr(allowed, "geoms", [allowed]))
    pa = _principal_angle(max(parts, key=lambda p: p.area))
    angles, seen = [], set()
    for a in (0.0, pa, pa + 90.0, 90.0, 30.0, -30.0, 45.0, -45.0,
              60.0, -60.0, 15.0, -15.0, 75.0, -75.0):
        a = _norm_angle(a)
        k = round(a)
        if k not in seen:
            seen.add(k)
            angles.append(a)
    pallowed = prep(allowed)
    x0, y0, x1, y1 = allowed.bounds
    xs = np.arange(x0, x1 + 1e-9, step)
    ys = np.arange(y0, y1 + 1e-9, step)
    cands = [(anchor.x, anchor.y)]
    cands += sorted(((x, y) for x in xs for y in ys),
                    key=lambda c: (c[0] - anchor.x) ** 2
                    + (c[1] - anchor.y) ** 2)
    from shapely.geometry import Point
    for cx, cy in cands:
        if not pallowed.contains(Point(cx, cy)):
            continue
        for a in angles:
            r = rect_poly(cx, cy, w_mm, h_mm, a)
            if pallowed.contains(r):
                return (cx, cy), a, r
    return None


def make_stamp(text, allowed, anchor=None, cap_mm=CAP_MM,
               cap_min_mm=CAP_MIN_MM, pitch=PITCH_MM, depth=DEPTH_MM,
               min_stroke=MIN_STROKE_MM, grid_step=2.0):
    """Fit `text` somewhere inside the `allowed` region (a shapely
    (Multi)Polygon already carrying all margins/exclusions), preferring
    cap_mm cap height / one line / horizontal, then multi-line, then
    vertical, then geometrically smaller caps down to cap_min_mm.
    anchor = preferred center (default: pole of inaccessibility of the
    largest allowed part).  Raises RuntimeError if nothing fits."""
    if allowed.is_empty:
        raise RuntimeError(f"stamp {text!r}: allowed region is empty")
    if anchor is None:
        big = max(getattr(allowed, "geoms", [allowed]), key=lambda p: p.area)
        anchor = polylabel(big, 0.1)
    caps = []
    c = cap_mm
    while c >= cap_min_mm - 1e-9:
        caps.append(c)
        c *= CAP_STEP
    for cap in caps:
        for lines in _layouts(text):
            m = render_mask(lines, cap, pitch)
            m, dil, ok = _ensure_stroke(m, pitch, min_stroke)
            if not ok:
                continue
            m, _ = mesh_common.remove_diagonal_pinches(m)
            m[0, :] = m[-1, :] = False           # keep the border ring
            m[:, 0] = m[:, -1] = False           # strictly at z_bottom
            ny, nx = m.shape
            hit = _place(nx * pitch, ny * pitch, allowed, anchor,
                         grid_step)
            if hit is None:
                continue
            center, angle, rect = hit
            return Stamp(text=text, lines=lines, cap_mm=cap, pitch=pitch,
                         depth=depth, mask=m, center=center, angle=angle,
                         rect=rect, dilated_px=dil,
                         min_stroke_mm=measure_min_stroke(m, pitch))
    raise RuntimeError(f"stamp {text!r} does not fit (caps tried down to "
                       f"{caps[-1]:.2f} mm)")


# ------------------------------------------------------------ mesh surgery
def stamped_bottom(part, v2, boundary_edges, stamp, z_bottom=0.0):
    """Bottom face of `part` (shapely Polygon) with the stamp debossed.

    v2 (n,2): the part's top-triangulation vertices; boundary_edges
    (m,2): its boundary (wall) edges as index pairs into v2.  Returns
    (verts (N,3), faces (M,3)): the outer CDT (rect = hole) at z_bottom
    plus the two-level glyph patch, all faces wound outward (-z is
    outside; the part's solid is above).  Face indices are local to the
    returned verts; the caller offsets, concatenates with top + walls,
    and welds (weld())."""
    import triangle as tr
    ny, nx = stamp.mask.shape
    g = stamp.pitch
    W, H = nx * g, ny * g
    U, V = np.meshgrid(np.arange(nx + 1) * g, np.arange(ny + 1) * g)
    ca = np.cos(np.radians(stamp.angle))
    sa = np.sin(np.radians(stamp.angle))
    cx0, cy0 = stamp.center
    X = cx0 + ca * (U - W / 2) - sa * (V - H / 2)
    Y = cy0 + sa * (U - W / 2) + ca * (V - H / 2)

    # rectangle perimeter ring taken from the SAME X/Y arrays the patch
    # grid uses -> bitwise-identical coordinates, welds exactly
    ring = np.vstack([
        np.column_stack([X[0, :], Y[0, :]]),              # S edge, W->E
        np.column_stack([X[1:-1, -1], Y[1:-1, -1]]),      # E edge, S->N
        np.column_stack([X[-1, ::-1], Y[-1, ::-1]]),      # N edge, E->W
        np.column_stack([X[-2:0:-1, 0], Y[-2:0:-1, 0]]),  # W edge, N->S
    ])

    # ---- outer CDT: part bottom with the rect (and part holes) removed
    bidx = np.unique(boundary_edges)
    remap = np.full(len(v2), -1, np.int64)
    remap[bidx] = np.arange(len(bidx))
    pts = np.vstack([v2[bidx], ring])
    ring_ids = len(bidx) + np.arange(len(ring))
    segs = np.vstack([remap[boundary_edges],
                      np.column_stack([ring_ids, np.roll(ring_ids, -1)])])
    holes = [[cx0, cy0]]
    for h in part.interiors:
        p = polylabel(Polygon(h), 0.05)
        holes.append([p.x, p.y])
    B = tr.triangulate({"vertices": pts.astype(float),
                        "segments": segs.astype(np.int32),
                        "holes": np.asarray(holes, float)}, "p")
    bv, bf = B["vertices"], B["triangles"].astype(np.int64)
    assert len(bv) == len(pts), "triangle added Steiner points on 'p' run"
    a = bv[bf[:, 0]]
    cross = ((bv[bf[:, 1]] - a)[:, 0] * (bv[bf[:, 2]] - a)[:, 1]
             - (bv[bf[:, 1]] - a)[:, 1] * (bv[bf[:, 2]] - a)[:, 0])
    bf[cross > 0] = bf[cross > 0][:, ::-1]        # CW from +z: normal -z
    verts = [np.column_stack([bv, np.full(len(bv), float(z_bottom))])]
    faces = [bf]
    off = len(bv)

    # ---- two-level glyph patch over the rect
    glyph = stamp.mask
    assert not (glyph[0, :].any() or glyph[-1, :].any()
                or glyph[:, 0].any() or glyph[:, -1].any()), \
        "glyphs touch the stamp-rect border"
    floor_cells = ~glyph

    def node_used(cells):
        u = np.zeros((ny + 1, nx + 1), bool)
        u[:-1, :-1] |= cells
        u[:-1, 1:] |= cells
        u[1:, :-1] |= cells
        u[1:, 1:] |= cells
        return u

    uf, uc = node_used(floor_cells), node_used(glyph)
    FN = np.full((ny + 1, nx + 1), -1, np.int64)  # floor-level node ids
    CN = np.full((ny + 1, nx + 1), -1, np.int64)  # ceiling-level node ids
    FN[uf] = off + np.arange(int(uf.sum()))
    CN[uc] = off + uf.sum() + np.arange(int(uc.sum()))
    zd = float(z_bottom) + stamp.depth
    verts.append(np.column_stack([X[uf], Y[uf],
                                  np.full(int(uf.sum()), float(z_bottom))]))
    verts.append(np.column_stack([X[uc], Y[uc], np.full(int(uc.sum()), zd)]))

    def cell_quads(cells, N):                     # normal -z (CW from +z)
        j, i = np.nonzero(cells)
        SW, SE = N[j, i], N[j, i + 1]
        NE, NW = N[j + 1, i + 1], N[j + 1, i]
        return np.vstack([np.stack([SW, NE, SE], 1),
                          np.stack([SW, NW, NE], 1)])

    faces.append(cell_quads(floor_cells, FN))
    faces.append(cell_quads(glyph, CN))

    # cavity walls wherever a glyph cell borders a floor cell; outward
    # normal points from the solid (floor side) INTO the glyph cavity
    wj, wi = np.nonzero(glyph)
    sel = floor_cells[wj + 1, wi]                 # floor to the north
    j, i = wj[sel], wi[sel]
    W0, E0 = FN[j + 1, i], FN[j + 1, i + 1]
    Wd, Ed = CN[j + 1, i], CN[j + 1, i + 1]
    faces += [np.stack([W0, E0, Ed], 1), np.stack([W0, Ed, Wd], 1)]  # -y
    sel = floor_cells[wj - 1, wi]                 # floor to the south
    j, i = wj[sel], wi[sel]
    W0, E0 = FN[j, i], FN[j, i + 1]
    Wd, Ed = CN[j, i], CN[j, i + 1]
    faces += [np.stack([E0, W0, Wd], 1), np.stack([E0, Wd, Ed], 1)]  # +y
    sel = floor_cells[wj, wi + 1]                 # floor to the east
    j, i = wj[sel], wi[sel]
    S0, N0 = FN[j, i + 1], FN[j + 1, i + 1]
    Sd, Nd = CN[j, i + 1], CN[j + 1, i + 1]
    faces += [np.stack([N0, S0, Sd], 1), np.stack([N0, Sd, Nd], 1)]  # -x
    sel = floor_cells[wj, wi - 1]                 # floor to the west
    j, i = wj[sel], wi[sel]
    S0, N0 = FN[j, i], FN[j + 1, i]
    Sd, Nd = CN[j, i], CN[j + 1, i]
    faces += [np.stack([S0, N0, Nd], 1), np.stack([S0, Nd, Sd], 1)]  # +x

    V = np.vstack(verts)
    F = np.vstack([f for f in faces if len(f)])
    assert F.min() >= 0 and F.max() < len(V)
    return V, F


def weld(verts, faces, decimals=6):
    """Merge vertices with identical (rounded) coordinates; remap faces."""
    key = np.round(verts, decimals)
    _, first, inv = np.unique(key, axis=0, return_index=True,
                              return_inverse=True)
    return verts[first], inv[faces]


# ------------------------------------------------------------ verification
def verify_stamp_levels(mesh, stamp, z_bottom=0.0, extra=()):
    """All vertices below z_bottom + depth must sit EXACTLY at z_bottom,
    z_bottom + depth, or a declared extra level (e.g. a bottom-chamfer
    ring); the depth level must actually be present.  Returns
    (ok, levels_found)."""
    z = mesh.vertices[:, 2]
    low = z[z < z_bottom + stamp.depth + 1e-5]
    levels = sorted(set(np.round(low - z_bottom, 5).tolist()))
    want = {0.0, round(stamp.depth, 5)}
    want |= {round(e, 5) for e in extra
             if 0 < e < stamp.depth + 1e-5}
    return set(levels) == want, levels
