"""Region-color key: shared geometry LIBRARY (ahl 2026-09-14/15).

This module builds nothing on its own.  The key is part of the final
assembly, so it is built by p5_final.py as D19 -- a plate press-fitted
into its own recess in the P5 frame over Nevada.  The standalone
key-panel build that used to live here is GONE (ahl 2026-09-15: "get rid
of the stand-alone key stuff"); what survives is the geometry these
callers share:

  p5_final.py           layout(), build_plate(), circle_ring(),
                        rect_ring(), render_label()  -> the real key
  key_pocket_coupon.py  build_plate(), circle_ring(), insert_mesh()
                        -> a one-pocket test coupon + its plug

The plate carries five rows in ahl's order (mountains, coast, valley,
desert, water), each with

  - a BLIND circular pocket (recessed into the TOP face only, solid
    floor underneath -- ahl's choice over a through-hole) sized for a
    small color-matched PLUG that prints alongside whichever job
    already uses that filament (water/coast from frame.3mf,
    mountain/valley/desert from their piece STLs). Plugs are permanent:
    a deliberate diameter INTERFERENCE for a snug press fit (glue
    optional), sized taller than the pocket so the plug sits proud once
    seated -- a felt bump, not flush;
  - a shallow (0.2 mm, one layer) rectangular recess across the text
    column -- ONE recess spanning all 5 rows -- sized for the printed
    KEY INSERT (key_insert.pdf, exact physical size) to sit in, so its
    edge doesn't catch and it sits close to flush with the pocket rims.
    The labels are 2D-printed because FDM text at this size fights the
    0.4 mm nozzle: at 3.5 mm cap height Georgia Bold crowded even after
    narrowing the glyphs.

Geometry: one CDT of the plate rectangle with the 5 pocket circles AND
the label rectangle as holes (constrained, exact boundary match -- same
recipe as compass_art.RosePanel/version_stamp.stamped_bottom) gives the
top face (thickness) and, reusing the identical boundary points, a
floor patch per recess (each at its OWN depth) plus the connecting
vertical walls. Outer side walls + a flat bottom close the plate. All
pieces share exact float coordinates and get merged with
version_stamp.weld (round-and-merge), the convention documented in
version_stamp.py's module docstring.
"""

import sys
from pathlib import Path

import numpy as np
import trimesh
import triangle as tr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compass_art as ca
import p4_bay_coupon as p4c
import version_stamp as vstamp

OUT_DIR = p4c.ROOT / "out" / "key_panel"   # overridden by each caller

# ahl 2026-09-16. Lower case, and in HIS order. These deliberately match
# the vocabulary the rest of the build uses for bodies and pieces
# (mountains / coast / valley / desert / water), so the label on the key
# is the same word as the filament slot, the STL and the config key --
# the reader and the assembler are looking at one name, not a synonym.
# The order here drives the ROW order and therefore which pocket gets
# which color plug; nothing else in the build depends on it.
LABELS = ["mountains", "coast", "valley", "desert", "water"]

# Layout knobs. Pocket/recess DEPTHS and the plug dimensions are NOT
# here: p5_final reads the real key's from config [key], and
# key_pocket_coupon owns the plug numbers it exists to test. Only what
# the 2D row layout needs lives in this module.
CAP_MM = 3.5               # label cap height (just sizes the layout --
                           # no FDM stroke-floor constraint, the labels
                           # are printed on a real printer)
FONT = "Georgia Bold"      # matches the compass rose
POCKET_D_MM = 7.0          # default swatch-pocket diameter (callers
                           # normally pass their own)
MARGIN_MM = 5.0            # plate edge -> content
ROW_GAP_MM = 3.0           # gap between pocket circles, row to row
TEXT_GAP_MM = 3.0          # pocket -> label-recess gap
TEXT_MARGIN_MM = 2.0       # extra clearance beyond the measured text box
TITLE = "California Regions"
TITLE_CAP_MM = 6.0         # ahl 2026-09-15: same size as the compass
                           # rose's N/E/S/W letters ([compass].
                           # letter_cap_mm). Wraps over as many lines as
                           # the text column needs.
TITLE_GAP_MM = 4.0         # space between the title block and the list
TITLE_LINE_FRAC = 1.35     # title line height / cap
INSERT_BORDER_MM = 2.0     # blank margin inside the cut line on the
                           # printed insert, so type is not flush to the
                           # paper edge (ahl 2026-09-15)
INSERT_BLEED_MM = 5.0      # extra paper OUTSIDE the cut line, to hold
                           # while trimming


# ---------------------------------------------------------------- layout
def _wrap(text, ff, cap_mm, max_w):
    """Greedy word-wrap `text` so every line fits `max_w` at `cap_mm`."""
    def w(t):
        b = ca._letter_poly(t, ff, cap_mm, ca.CHORD_TOL_MM).bounds
        return b[2] - b[0]
    lines, cur = [], ""
    for word in text.split():
        trial = f"{cur} {word}".strip()
        if cur and w(trial) > max_w:
            lines.append(cur)
            cur = word
        else:
            cur = trial
    if cur:
        lines.append(cur)
    over = [ln for ln in lines if w(ln) > max_w]
    assert not over, (f"key too narrow for the title at {cap_mm:g} mm cap: "
                      f"{over[0]!r} needs {w(over[0]):.1f} mm, have "
                      f"{max_w:.1f}")
    return lines, [w(ln) for ln in lines]


def layout(plate_w, plate_h, pocket_d=None, title=TITLE,
           title_cap=TITLE_CAP_MM, title_gap=TITLE_GAP_MM,
           label_cap=CAP_MM, insert_border=INSERT_BORDER_MM):
    """Lay the key out inside a GIVEN plate rectangle (ahl 2026-09-15:
    the key's footprint comes from config [key], the contents fit it).

    Down the plate: a TITLE at `title_cap` -- ahl asked for the same size
    as the compass rose's N/E/S/W letters -- word-wrapped over as many
    lines as it needs, then `title_gap` of space, then the five region
    rows at the smaller `label_cap`, each with a swatch pocket beside it.

    Across the plate: a right-hand column of pockets, and everything
    printed (title AND labels) inside ONE rectangular recess to its left,
    so the paper insert is a plain rectangle with no holes to punch.
    That makes the recess width, not the plate width, the constraint on
    the title -- the assert in _wrap fires if the key is too narrow.

    Returns (plate_w, plate_h, rows, recess).  `recess` carries the
    title lines and their y positions, all LOCAL to the recess's own SW
    corner, which is the frame render_label() draws in."""
    ff = ca._font_file(FONT)
    pocket_d = POCKET_D_MM if pocket_d is None else pocket_d

    recess = {"x0": MARGIN_MM, "y0": MARGIN_MM,
             "x1": plate_w - MARGIN_MM - pocket_d - TEXT_GAP_MM,
             "y1": plate_h - MARGIN_MM}
    # the printed insert keeps a blank BORDER inside the cut line, so
    # the lettering is not jammed against the paper edge (ahl
    # 2026-09-15). That border comes out of the usable text area, so the
    # type has to fit rec_w - 2*border, not rec_w.
    rec_w = recess["x1"] - recess["x0"] - 2 * insert_border
    rec_h = recess["y1"] - recess["y0"] - 2 * insert_border
    assert rec_w > 10.0, (f"key too narrow: text column only {rec_w:.1f} mm "
                          f"(plate {plate_w:.1f} - margins - {pocket_d:g} mm "
                          f"pocket column - {2 * insert_border:g} mm insert "
                          "border)")

    title_lines, _ = _wrap(title, ff, title_cap, rec_w)
    line_h = title_cap * TITLE_LINE_FRAC
    title_h = len(title_lines) * line_h

    # rows share whatever height is left under the title block
    rows_h = rec_h - title_h - title_gap
    row_pitch = rows_h / len(LABELS)
    assert row_pitch >= pocket_d + 0.5, (
        f"key too short: after a {len(title_lines)}-line title "
        f"({title_h:.1f} mm) + {title_gap:g} mm gap, {len(LABELS)} rows of "
        f"dia {pocket_d:g} mm need {len(LABELS) * (pocket_d + 0.5):.1f} mm "
        f"but only {rows_h:.1f} mm is left (plate {plate_h:.1f})")
    lab_w = max(ca._letter_poly(l, ff, label_cap, ca.CHORD_TOL_MM).bounds[2]
                - ca._letter_poly(l, ff, label_cap, ca.CHORD_TOL_MM).bounds[0]
                for l in LABELS)
    assert lab_w <= rec_w, (f"region labels need {lab_w:.1f} mm at "
                            f"{label_cap:g} mm cap, text column is "
                            f"{rec_w:.1f} mm")

    # positions below are LOCAL to the recess (the frame render_label
    # draws in), so the border offset is folded in here once
    recess["title_lines"] = title_lines
    recess["title_cap"] = title_cap
    recess["label_cap"] = label_cap
    recess["border"] = insert_border
    recess["text_x_local"] = insert_border
    recess["title_y_local"] = [insert_border + rec_h - (i + 0.5) * line_h
                               for i in range(len(title_lines))]

    pocket_x = plate_w - MARGIN_MM - pocket_d / 2
    rows_top = recess["y0"] + insert_border + rows_h
    rows = []
    for i, lab in enumerate(LABELS):
        cy = rows_top - (i + 0.5) * row_pitch
        rows.append({"label": lab, "pocket_c": (pocket_x, cy),
                     "text_y_local": cy - recess["y0"]})
    return plate_w, plate_h, rows, recess


# ------------------------------------------------------------------ mesh
def build_plate(width, height, recesses, thickness, seg=48):
    """Rectangle `width` x `height` x `thickness` with a recess per entry
    in `recesses`: {"points": Nx2 CCW ring, "depth": float,
    "through": Nx2 CCW ring or None}.

    A recess is BLIND (solid floor under it) unless it carries a
    "through" ring, in which case that ring is punched all the way out
    of the bottom: the recess floor becomes an ANNULUS and the hole gets
    its own wall down to z=0.  The swatch pockets use this as a POKE
    HOLE -- ahl 2026-09-15, so a plug pressed into the wrong pocket can
    be pushed back out from underneath while the key is still loose.
    (Only while loose: the key is press-fit permanently into the frame,
    and by ahl's call it does not need to be recoverable after that, so
    nothing is drilled through the frame.)

    Returns a watertight trimesh.Trimesh."""
    corners = np.array([[0, 0], [width, 0], [width, height], [0, height]],
                       float)
    rings = [r["points"] for r in recesses]
    thru = [r.get("through") for r in recesses]

    pts = np.vstack([corners] + rings) if rings else corners
    segs = [(i, (i + 1) % 4) for i in range(4)]
    off = 4
    for ring in rings:
        n = len(ring)
        segs += [(off + i, off + (i + 1) % n) for i in range(n)]
        off += n
    holes = (np.asarray([r["points"].mean(axis=0) for r in recesses], float)
            if recesses else np.zeros((0, 2)))
    B = tr.triangulate({"vertices": pts, "segments": np.asarray(segs, np.int32),
                        "holes": holes}, "p")
    tv, tf = B["vertices"], B["triangles"].astype(np.int64)
    assert len(tv) == len(pts), "triangle added Steiner points on 'p' run"
    a = tv[tf[:, 0]]
    cross = ((tv[tf[:, 1]] - a)[:, 0] * (tv[tf[:, 2]] - a)[:, 1]
             - (tv[tf[:, 1]] - a)[:, 1] * (tv[tf[:, 2]] - a)[:, 0])
    tf[cross < 0] = tf[cross < 0][:, ::-1]        # CCW from +z (top patch)

    verts = [np.column_stack([tv, np.full(len(tv), thickness)])]
    faces = [tf]

    # bottom cap, normal -z. Solid rectangle unless some recess punches
    # through, in which case those rings are holes in it too.
    tr_rings = [t for t in thru if t is not None]
    b0 = len(np.vstack(verts))
    if not tr_rings:
        verts.append(np.column_stack([corners, np.zeros(4)]))
        faces.append(b0 + np.array([[0, 2, 1], [0, 3, 2]]))
        n_bot = 4
    else:
        bpts = np.vstack([corners] + tr_rings)
        bsegs = [(i, (i + 1) % 4) for i in range(4)]
        o = 4
        for ring in tr_rings:
            k = len(ring)
            bsegs += [(o + i, o + (i + 1) % k) for i in range(k)]
            o += k
        Bb = tr.triangulate(
            {"vertices": bpts, "segments": np.asarray(bsegs, np.int32),
             "holes": np.asarray([r.mean(axis=0) for r in tr_rings], float)},
            "p")
        bv, bf = Bb["vertices"], Bb["triangles"].astype(np.int64)
        assert len(bv) == len(bpts), "triangle added Steiner points (bottom)"
        a = bv[bf[:, 0]]
        cr = ((bv[bf[:, 1]] - a)[:, 0] * (bv[bf[:, 2]] - a)[:, 1]
              - (bv[bf[:, 1]] - a)[:, 1] * (bv[bf[:, 2]] - a)[:, 0])
        bf[cr > 0] = bf[cr > 0][:, ::-1]          # CW from +z -> normal -z
        verts.append(np.column_stack([bv, np.zeros(len(bv))]))
        faces.append(b0 + bf)
        n_bot = len(bv)

    # outer side walls: CCW rectangle boundary -> solid on the LEFT of
    # each directed edge -> outward wall = (a_lo,b_lo,b_hi),(a_lo,b_hi,a_hi)
    w0 = b0 + n_bot
    verts.append(np.column_stack([corners, np.zeros(4)]))       # lo, z=0
    verts.append(np.column_stack([corners, np.full(4, thickness)]))  # hi
    lo = w0 + np.arange(4)
    hi = w0 + 4 + np.arange(4)
    wall = []
    for i in range(4):
        a_lo, b_lo = lo[i], lo[(i + 1) % 4]
        a_hi, b_hi = hi[i], hi[(i + 1) % 4]
        wall += [(a_lo, b_lo, b_hi), (a_lo, b_hi, a_hi)]
    faces.append(np.asarray(wall, np.int64))

    # recess floors (normal +z, into the cavity from below) + recess
    # walls (normal toward the recess interior)
    off = 4
    for r in recesses:
        ring, depth = r["points"], r["depth"]
        hole = r.get("through")
        zf = thickness - depth
        n = len(ring)
        vbase = len(np.vstack(verts))
        if hole is None:
            # fan triangulate the floor from the ring's centroid (works
            # for any star-shaped-from-centroid outline -- true for a
            # circle or an axis-aligned rectangle, both used here)
            cx, cy = ring.mean(axis=0)
            verts.append(np.array([[cx, cy, zf]]))
            verts.append(np.column_stack([ring, np.full(n, zf)]))
            center_idx = vbase
            floor_idx = vbase + 1 + np.arange(n)
            faces.append(np.stack([np.full(n, center_idx), floor_idx,
                                   np.roll(floor_idx, -1)], axis=1))
        else:
            # floor is an ANNULUS (poke hole through the middle), then
            # the hole's own wall straight down to z=0
            assert len(hole) == n, ("through-ring must match the recess "
                                    "ring's segment count so the annulus "
                                    "strips cleanly")
            verts.append(np.column_stack([ring, np.full(n, zf)]))
            verts.append(np.column_stack([hole, np.full(n, zf)]))
            verts.append(np.column_stack([hole, np.zeros(n)]))
            floor_idx = vbase + np.arange(n)          # outer, at zf
            in_hi = vbase + n + np.arange(n)          # hole rim, at zf
            in_lo = vbase + 2 * n + np.arange(n)      # hole rim, at z=0
            o2, i2 = np.roll(floor_idx, -1), np.roll(in_hi, -1)
            faces.append(np.concatenate([
                np.stack([floor_idx, o2, in_hi], axis=1),
                np.stack([o2, i2, in_hi], axis=1)]))   # annulus, normal +z
            l2 = np.roll(in_lo, -1)
            faces.append(np.concatenate([
                np.stack([in_lo, i2, l2], axis=1),
                np.stack([in_lo, in_hi, i2], axis=1)]))  # hole wall, inward

        top_idx = off + np.arange(n)   # this recess's rim in the top patch
        rwall = []
        for i in range(n):
            a, b = top_idx[i], top_idx[(i + 1) % n]           # top (thickness)
            fa, fb = floor_idx[i], floor_idx[(i + 1) % n]      # floor (zf)
            # ring is CCW -> cavity on the LEFT of a->b -> outward
            # (into cavity) normal is the MIRROR of the solid-on-left
            # rule: swap a/b
            rwall += [(fb, fa, a), (fb, a, b)]
        faces.append(np.asarray(rwall, np.int64))
        off += n

    V = np.vstack(verts)
    F = np.vstack([f for f in faces if len(f)])
    V, F = vstamp.weld(V, F)
    m = trimesh.Trimesh(vertices=V, faces=F, process=False)
    return m


def circle_ring(cx, cy, r, seg=48):
    ang = np.arange(seg) * (2 * np.pi / seg)
    return np.column_stack([cx + r * np.cos(ang), cy + r * np.sin(ang)])


def rect_ring(x0, y0, x1, y1):
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float)


def insert_mesh(diameter, height, seg=48):
    """A plain cylinder plug: `diameter` (a deliberate interference fit
    -- see INSERT_INTERFERENCE_MM) x `height` (taller than the pocket
    it presses into, so it sits proud once seated -- see
    INSERT_BUMP_MM)."""
    m = trimesh.creation.cylinder(radius=diameter / 2, height=height,
                                  sections=seg)
    m.apply_translation([0, 0, height / 2])   # base at z=0
    return m


# ------------------------------------------------------------- 2D label
def render_label(recess, rows, bleed=INSERT_BLEED_MM):
    """The printed KEY INSERT.

    The page is the recess plus `bleed` of spare paper on every side, so
    there is something to hold while trimming, with a CUT LINE drawn at
    the exact recess size -- cut on the line and the piece drops into the
    recess.  Inside that, layout() has already reserved a blank border
    (recess["border"]) so the lettering is not flush to the paper edge
    (ahl 2026-09-15: "I don't like that the left edge is right up
    against the lettering").

    2D-printed rather than moulded in plastic because FDM text at this
    size fights a 0.4 mm nozzle -- at 3.5 mm cap Georgia Bold crowded
    even after narrowing the glyphs."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    w = recess["x1"] - recess["x0"]
    h = recess["y1"] - recess["y0"]
    pw, ph = w + 2 * bleed, h + 2 * bleed
    fig = plt.figure(figsize=(pw / 25.4, ph / 25.4), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, pw)
    ax.set_ylim(0, ph)
    ax.set_aspect("equal")
    ax.axis("off")

    # CUT LINE at the true recess size
    ax.add_patch(Rectangle((bleed, bleed), w, h, fill=False,
                           edgecolor="#9a9a9a", linewidth=0.4))
    for x, y, dx, dy in ((bleed, bleed, -1, 0), (bleed, bleed, 0, -1),
                         (bleed + w, bleed, 1, 0), (bleed + w, bleed, 0, -1),
                         (bleed, bleed + h, -1, 0), (bleed, bleed + h, 0, 1),
                         (bleed + w, bleed + h, 1, 0),
                         (bleed + w, bleed + h, 0, 1)):
        ax.plot([x, x + dx * bleed * 0.55], [y, y + dy * bleed * 0.55],
                color="#9a9a9a", lw=0.4)

    # matplotlib sizes text in POINTS by em, Georgia's cap is ~0.7 em
    pt = lambda cap_mm: cap_mm / 0.7 * 72.0 / 25.4
    tx = bleed + recess.get("text_x_local", 0.0)
    for ln, y in zip(recess["title_lines"], recess["title_y_local"]):
        ax.text(tx, bleed + y, ln, fontfamily="Georgia", fontweight="bold",
                fontsize=pt(recess["title_cap"]), va="center", ha="left")
    for r in rows:
        ax.text(tx, bleed + r["text_y_local"], r["label"],
                fontfamily="Georgia", fontweight="bold",
                fontsize=pt(recess["label_cap"]), va="center", ha="left")
    path = OUT_DIR / "key_insert.pdf"
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"-> {path}: page {pw:.1f} x {ph:.1f} mm, CUT LINE at "
          f"{w:.1f} x {h:.1f} mm (the recess), {recess.get('border', 0):g} mm "
          f"blank border inside it; print at 100%/actual size\n"
          f"      title {'/'.join(recess['title_lines'])} at "
          f"{recess['title_cap']:g} mm cap, labels at "
          f"{recess['label_cap']:g} mm")
