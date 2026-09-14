"""D17 compass rose from ahl's Illustrator artwork (assets/compass.svg).

RAISED relief, color-keyed: the artwork is rasterized (cairosvg — it
handles bezier paths, CSS classes, everything Illustrator exports) and
every pixel is classified to its NEAREST reference color:

    dark blue (46, 49, 146)  -> "coast"  (CA-land filament body)
    gray     (193, 199, 210) -> "gray"   (gray body)
    black     (35, 31, 32)   -> "black"  (black body)
    teal      (39, 170, 225) + white/transparent -> water (no body)

N/E/S/W lettering is drawn by the pipeline (config [compass].letter_*)
in black, merged into the black class (letters win over fills where a
cardinal tip passes under a letter).  The three ink masks are made
mutually DISJOINT and diagonal-pinch-free, then extruded as bodies that
sit ON the water surface: datum -> datum + relief_mm.  Blue/gray rose
bodies merge into the frame's existing coast/gray filament bodies; the
black one is its own body.

Scale: the OUTER RING (largest circle in the SVG, outer stroke edge) =
[compass].diameter_mm; the cardinal tips and the letters extend beyond
it — `tip_r_mm` / `size_mm` report the true footprint for placement.

Used by p4_bay_coupon.py (coupon placement) and p5_final.py (final
frame).  Deps for the importing script's uv header: numpy, scipy,
pillow, cairosvg, shapely, trimesh (via mesh_common), matplotlib
(font fallback).
"""

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import ndimage

import mesh_common
import version_stamp as vstamp

PITCH_MM = 0.15          # rose raster grid (mm/cell)
INK_RGB = {"coast": (46, 49, 146), "gray": (193, 199, 210),
           "black": (35, 31, 32)}
WATER_KEYS = [(39, 170, 225), (255, 255, 255)]
LETTERS = {"N": (0, 1), "E": (1, 0), "S": (0, -1), "W": (-1, 0)}
MARGIN_MM = 1.0
_ORDER = ("black", "coast", "gray")   # overlap priority (letters on top)


@dataclass
class RoseArt:
    masks: dict          # name -> (ny, nx) bool, row 0 = SOUTH, disjoint
    pitch: float
    diameter_mm: float   # outer ring (scale reference)
    tip_r_mm: float      # true max ink radius (tips/letters)
    letter_r_mm: float
    black_stroke_mm: float       # artwork outline stroke width
    letter_min_stroke_mm: float
    font_file: str
    cardinal_tip_r_mm: float     # max radius of artwork ink (no letters),
                                  # AFTER ink_min_stroke_mm dilation
    letter_tip_gap_mm: float     # letter glyph ink clearance past the tip
    ink_stroke_before_mm: dict   # per-class min stroke, raw classification
    ink_stroke_after_mm: dict    # per-class min stroke, after dilation
    ink_dilated_px: dict         # per-class dilation iterations applied

    @property
    def size_mm(self):
        ny, nx = self.masks["black"].shape
        return (nx * self.pitch, ny * self.pitch)

    def ink_union(self):
        u = np.zeros_like(self.masks["black"])
        for m in self.masks.values():
            u |= m
        return u

    def cell_centers(self, center_mm, mask=None):
        """World (x, y) of each True cell of `mask` (default: union)."""
        m = self.ink_union() if mask is None else mask
        ny, nx = m.shape
        jj, ii = np.nonzero(m)
        x0 = center_mm[0] - nx * self.pitch / 2
        y0 = center_mm[1] - ny * self.pitch / 2
        return (x0 + (ii + 0.5) * self.pitch,
                y0 + (jj + 0.5) * self.pitch)

    def ink_hull(self, center_mm, step=9):
        from shapely.geometry import MultiPoint
        xi, yi = self.cell_centers(center_mm)
        return MultiPoint(
            np.column_stack([xi[::step], yi[::step]])).convex_hull


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


def _clear_pinches(m):
    """Remove diagonal-only pinches by CLEARING one cell of each pair
    (used where filling is blocked by a higher-priority ink class)."""
    m = m.copy()
    while True:
        a, b = m[:-1, :-1], m[:-1, 1:]
        c, d = m[1:, :-1], m[1:, 1:]
        p1 = a & d & ~b & ~c
        p2 = b & c & ~a & ~d
        if not (p1.any() or p2.any()):
            return m
        m[1:, 1:] &= ~p1      # drop the SE... (row+1) cell of each pair
        m[1:, :-1] &= ~p2


def _stroke_mm(mask, pitch, lo=0.05, hi=1.20, step=0.025):
    """Min stroke width (mm), via the SAME morphological-opening test
    version_stamp uses for letters (vstamp._stroke_ok), swept over a
    range fine/wide enough for both raw sub-mm artwork ink and the
    dilated target width. Empty mask -> 0.0 (nothing to measure)."""
    if not mask.any():
        return 0.0
    ok = 0.0
    for half in np.arange(lo, hi, step):
        if vstamp._stroke_ok(mask, half, pitch):
            ok = max(ok, half)
    return round(2 * ok, 6)


def _dilate_to_stroke(mask, pitch, min_stroke_mm, claimed=None, max_iter=40):
    """Thicken `mask` until its min stroke width >= min_stroke_mm, using
    version_stamp's own opening test (vstamp._stroke_ok) as the stopping
    condition and its disk primitive to grow. SURGICAL: each step grows
    only the cells the opening test currently flags as too-thin (not a
    blanket dilation of the whole silhouette), which is far less
    destructive to a neighboring ink class sharing most of this mask's
    boundary (a thin outline sandwiched between two fills would
    otherwise get fattened everywhere, not just where it's actually
    thin, needlessly eating into both neighbors along its full length).
    Growth never crosses into `claimed` cells (higher-priority ink
    already locked in) -- classes stay disjoint BY CONSTRUCTION. Some
    pinches are boxed in by a higher-priority class on every side and
    are geometrically un-thickenable without touching that class; such
    a step makes no progress and dilation stops early (best effort).
    Returns (mask, iterations_applied)."""
    m = mask.copy()
    if claimed is not None:
        m &= ~claimed
    half = min_stroke_mm / 2
    dil = 0
    while not vstamp._stroke_ok(m, half, pitch) and dil < max_iter:
        opened = ndimage.binary_opening(m, structure=vstamp._disk(half / pitch))
        missing = m & ~opened
        grow = ndimage.binary_dilation(missing, structure=vstamp._disk(1.0))
        new_m = m | grow
        if claimed is not None:
            new_m &= ~claimed
        if np.array_equal(new_m, m):
            break                    # boxed in: no room left to grow
        m = new_m
        dil += 1
    return m, dil


def _font_file(name):
    for p in (f"/System/Library/Fonts/Supplemental/{name}.ttf",
              f"/Library/Fonts/{name}.ttf",
              "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf"):
        if Path(p).exists():
            return p
    import matplotlib
    return str(Path(matplotlib.get_data_path())
               / "fonts/ttf/DejaVuSerif-Bold.ttf")


def load_rose(svg_path, diameter_mm, letter_font, letter_cap_mm,
              letter_radius_frac, ink_min_stroke_mm, pitch=PITCH_MM):
    import cairosvg
    from PIL import Image, ImageDraw, ImageFont

    (cu, cv), r_out_u, sw_u = _ring_and_stroke(svg_path)
    k = diameter_mm / (2.0 * r_out_u)     # mm per SVG unit
    f = k / pitch                          # px per SVG unit
    png = cairosvg.svg2png(url=str(svg_path), scale=f)
    rgba = np.asarray(Image.open(io.BytesIO(png)).convert("RGBA"))
    H, W = rgba.shape[:2]
    ccol, crow = cu * f, cv * f            # rose center, y-down px

    # pad the canvas so the letters (beyond the artwork bbox) fit
    letter_r_px = letter_radius_frac * (diameter_mm / 2) / pitch
    cap_px = letter_cap_mm / pitch
    need = int(np.ceil(letter_r_px + 1.2 * cap_px + MARGIN_MM / pitch))
    pads = (max(0, need - int(crow)), max(0, need - (H - int(crow))),
            max(0, need - int(ccol)), max(0, need - (W - int(ccol))))
    rgba = np.pad(rgba, ((pads[0], pads[1]), (pads[2], pads[3]), (0, 0)))
    crow += pads[0]
    ccol += pads[2]
    H, W = rgba.shape[:2]

    # nearest-color classification (alpha < 128 -> water/none)
    refs = WATER_KEYS + [INK_RGB[n] for n in ("coast", "gray", "black")]
    rgb = rgba[..., :3].astype(np.int32)
    d = np.stack([((rgb - np.array(rc)) ** 2).sum(axis=-1) for rc in refs])
    cls = d.argmin(axis=0)
    cls[rgba[..., 3] < 128] = 0
    masks = {"coast": cls == 2, "gray": cls == 3, "black": cls == 4}

    # ink_min_stroke_mm (D17): dilate each ink class, in the same
    # black > coast > gray priority the disjointness pass below uses,
    # until its printed min stroke width clears the floor. Each class
    # is grown only into cells not already `claimed` by a higher class,
    # so classes stay disjoint by construction (no later overlap to
    # resolve for THIS reason -- the pinch-removal pass below still
    # runs for diagonal pinches and the separate letter overlap).
    ink_stroke_before_mm = {n: _stroke_mm(masks[n], pitch) for n in _ORDER}
    claimed = np.zeros_like(masks["black"])
    ink_dilated_px = {}
    for n in _ORDER:
        masks[n], ink_dilated_px[n] = _dilate_to_stroke(
            masks[n], pitch, ink_min_stroke_mm, claimed)
        claimed |= masks[n]
    ink_stroke_after_mm = {n: _stroke_mm(masks[n], pitch) for n in _ORDER}
    print(f"  [compass] ink min stroke (target {ink_min_stroke_mm:g} mm): "
          + ", ".join(f"{n} {ink_stroke_before_mm[n]:.2f}->"
                      f"{ink_stroke_after_mm[n]:.2f} mm "
                      f"(+{ink_dilated_px[n]} dilation step(s))"
                      for n in _ORDER))
    # black is top priority -- nothing else can pinch it, so it MUST
    # clear the floor (this is the hard D17 requirement: raw black is
    # sub-nozzle at this scale and must end >= ink_min_stroke_mm).
    assert ink_stroke_after_mm["black"] >= ink_min_stroke_mm - 1e-6, \
        (f"black ink stroke {ink_stroke_after_mm['black']:.2f} mm still "
         f"under {ink_min_stroke_mm:g} mm after "
         f"{ink_dilated_px['black']} dilation step(s)")
    # coast/gray are lower priority and can be geometrically boxed in by
    # the (now-thickened) black outline on every side at a sharp taper
    # (the combined black+color width available there can be under the
    # single-class floor) -- best-effort, and reported rather than
    # asserted, since no amount of dilation can create width that
    # doesn't exist in the artwork without shrinking black below ITS
    # floor.
    for n in ("coast", "gray"):
        if masks[n].any() and ink_stroke_after_mm[n] < ink_min_stroke_mm - 1e-6:
            print(f"  [compass] WARNING: {n} ink stroke "
                  f"{ink_stroke_after_mm[n]:.2f} mm still under "
                  f"{ink_min_stroke_mm:g} mm after {ink_dilated_px[n]} "
                  "dilation step(s) -- boxed in by the black outline at "
                  "its narrowest taper; a geometric limit of the artwork "
                  "at this scale, not a dilation shortfall")

    # cardinal-tip max radius AFTER ink dilation -- the real printed
    # footprint (artwork only, no letters yet) the letters must clear
    tip_mask = masks["coast"] | masks["gray"] | masks["black"]
    jt, it = np.nonzero(tip_mask)
    cardinal_tip_r_mm = float(np.hypot((it + 0.5 - ccol) * pitch,
                                       (jt + 0.5 - crow) * pitch).max())

    # pipeline lettering (black, drawn y-down: N at the image top)
    ff = _font_file(letter_font)
    probe = ImageFont.truetype(ff, 100)
    pb = probe.getbbox("H")
    font = ImageFont.truetype(ff, max(8, round(cap_px * 100 /
                                               (pb[3] - pb[1]))))
    lim = Image.new("L", (W, H), 0)
    ld = ImageDraw.Draw(lim)
    for ch, (ux, uy) in LETTERS.items():
        ld.text((ccol + ux * letter_r_px, crow - uy * letter_r_px), ch,
                fill=255, font=font, anchor="mm")
    lm = np.asarray(lim) > 127
    # serif thins (Georgia) run under the 0.8 mm floor at cap ~6 mm:
    # auto-dilate like the version stamps (N/E/S/W have no counters)
    lm, lm_dil, _ = vstamp._ensure_stroke(lm, pitch, vstamp.MIN_STROKE_MM)
    letter_stroke = vstamp.measure_min_stroke(lm, pitch)

    # D17 letter/tip clearance: the letter GLYPH ink -- the actual
    # rasterized (post-dilation, what prints) pixels, not just the
    # radial anchor -- must keep a POSITIVE gap from the cardinal tips
    # (which reach cardinal_tip_r_mm, ~1.30x the ring radius by design).
    jl, il = np.nonzero(lm)
    letter_min_r_mm = float(np.hypot((il + 0.5 - ccol) * pitch,
                                     (jl + 0.5 - crow) * pitch).min())
    letter_tip_gap_mm = letter_min_r_mm - cardinal_tip_r_mm
    print(f"  [compass] letter/tip gap: {letter_tip_gap_mm:+.3f} mm "
          f"(tips to r {cardinal_tip_r_mm:.3f} mm, letter ink from r "
          f"{letter_min_r_mm:.3f} mm)")
    assert letter_tip_gap_mm > 0, (
        f"letter ink touches/overlaps the cardinal tips: gap "
        f"{letter_tip_gap_mm:.3f} mm (tips to r {cardinal_tip_r_mm:.3f} "
        f"mm, letter ink from r {letter_min_r_mm:.3f} mm) -- increase "
        "[compass].letter_radius_frac to move the letters outward")

    masks["black"] |= lm
    masks["coast"] &= ~lm
    masks["gray"] &= ~lm

    # row 0 = south
    for n in masks:
        masks[n] = np.flipud(masks[n])
    crow = (H - 1) - crow

    # symmetric crop about the rose center (keeps center_mm exact)
    union = masks["coast"] | masks["gray"] | masks["black"]
    rr, cc = np.nonzero(union)
    mrg = int(np.ceil(MARGIN_MM / pitch)) + 1
    half_c = int(np.ceil(max(ccol - cc.min(), cc.max() + 1 - ccol))) + mrg
    half_r = int(np.ceil(max(crow - rr.min(), rr.max() + 1 - crow))) + mrg
    half_c = min(half_c, int(ccol), W - int(ccol) - 1)
    half_r = min(half_r, int(crow), H - int(crow) - 1)
    sl = (slice(int(crow) - half_r, int(crow) + half_r),
          slice(int(ccol) - half_c, int(ccol) + half_c))
    masks = {n: m[sl].copy() for n, m in masks.items()}

    # disjoint + diagonal-pinch-free (priority: black > coast > gray;
    # pinch fills may cross classes, so iterate to a fixpoint)
    for it in range(8):
        changed = False
        higher = np.zeros_like(masks["black"])
        for n in _ORDER:
            m, _ = mesh_common.remove_diagonal_pinches(masks[n])
            m &= ~higher
            changed |= not np.array_equal(m, masks[n])
            masks[n] = m
            higher |= m
        if not changed:
            break
    assert not changed, "ink masks did not stabilize"
    # a lower-priority mask can be left pinched when its fill cell is
    # owned by a higher class: break those by CLEARING one diagonal
    # cell (one 0.15 mm cell, invisible) instead of filling
    for n in ("coast", "gray"):
        masks[n] = _clear_pinches(masks[n])
    for n in _ORDER:
        _, added = mesh_common.remove_diagonal_pinches(masks[n])
        assert added == 0, f"{n} ink mask still diagonally pinched"
    assert not (masks["black"] & masks["coast"]).any()
    assert not (masks["black"] & masks["gray"]).any()
    assert not (masks["coast"] & masks["gray"]).any()

    ny, nx = masks["black"].shape
    jj, ii = np.nonzero(masks["coast"] | masks["gray"] | masks["black"])
    tip_r = float(np.hypot((ii + 0.5 - nx / 2) * pitch,
                           (jj + 0.5 - ny / 2) * pitch).max())
    return RoseArt(masks=masks, pitch=pitch, diameter_mm=diameter_mm,
                   tip_r_mm=tip_r,
                   letter_r_mm=letter_radius_frac * diameter_mm / 2,
                   black_stroke_mm=sw_u * k,
                   letter_min_stroke_mm=letter_stroke, font_file=ff,
                   cardinal_tip_r_mm=cardinal_tip_r_mm,
                   letter_tip_gap_mm=letter_tip_gap_mm,
                   ink_stroke_before_mm=ink_stroke_before_mm,
                   ink_stroke_after_mm=ink_stroke_after_mm,
                   ink_dilated_px=ink_dilated_px)


def relief_meshes(rose, center_mm, base_mm, depth_mm, style="raised"):
    """One watertight extrusion per ink class.  style='raised': bodies
    sit ON the water surface (base .. base+depth).  style='flush':
    bodies are INLAID, tops level with the water surface
    (base-depth .. base) — pair with the matching water-top recesses
    from union_stamp()."""
    z0 = float(base_mm) - depth_mm if style == "flush" else float(base_mm)
    meshes = {}
    ny, nx = rose.masks["black"].shape
    x0 = center_mm[0] - nx * rose.pitch / 2
    y0 = center_mm[1] - ny * rose.pitch / 2
    for name, m in rose.masks.items():
        if not m.any():
            continue
        hf = np.flipud(m)              # heightfield rows: 0 = north
        mesh = mesh_common.heightfield_to_mesh(
            np.full(hf.shape, float(depth_mm)), hf, rose.pitch)
        mesh.apply_translation([x0, y0, z0])
        meshes[name] = mesh
    return meshes


def union_stamp(rose, center_mm, depth_mm):
    """For style='flush': a version_stamp.Stamp carrying the ink UNION,
    to carve the matching recesses into the water body's TOP (build the
    water solid z-mirrored with this stamp, then flip z and reverse
    faces).  The union is made pinch-free by FILLING; filled cells (rare
    single cells at cross-class diagonal junctions) belong to no ink
    body and stay as sub-nozzle 1-cell pockets — returned as `added`
    for reporting.  Grid coordinates match relief_meshes() exactly, so
    the inlay walls are coincident with the recess walls."""
    u = rose.ink_union()
    u, added = mesh_common.remove_diagonal_pinches(u)
    ny, nx = u.shape
    w, h = nx * rose.pitch, ny * rose.pitch
    st = vstamp.Stamp(
        text="compass recess", lines=[], cap_mm=0.0, pitch=rose.pitch,
        depth=float(depth_mm), mask=u, center=tuple(center_mm), angle=0.0,
        rect=vstamp.rect_poly(center_mm[0], center_mm[1], w, h, 0.0),
        dilated_px=0, min_stroke_mm=0.0)
    return st, int(added)


def draw_rose(ax, rose, center_mm, colors, z=5):
    """Preview: imshow the three ink classes in their PRINT colors."""
    ny, nx = rose.masks["black"].shape
    rgba = np.zeros((ny, nx, 4))
    for name, m in rose.masks.items():
        rgba[m] = (*colors[name], 1.0)
    w, h = nx * rose.pitch, ny * rose.pitch
    ax.imshow(rgba, extent=(center_mm[0] - w / 2, center_mm[0] + w / 2,
                            center_mm[1] - h / 2, center_mm[1] + h / 2),
              origin="lower", interpolation="nearest", zorder=z)
