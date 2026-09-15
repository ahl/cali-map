"""Region-colour key: shared geometry LIBRARY (ahl 2026-09-14/15).

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

The plate carries five rows in ahl's order (Pacific Ocean, Coastal,
Mountain, Valley, Desert), each with

  - a BLIND circular pocket (recessed into the TOP face only, solid
    floor underneath -- ahl's choice over a through-hole) sized for a
    small colour-matched PLUG that prints alongside whichever job
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

LABELS = ["Pacific Ocean", "Coastal", "Mountain", "Valley", "Desert"]

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


# ---------------------------------------------------------------- layout
def layout(plate_w=None, plate_h=None, pocket_d=None):
    """Row geometry: plate size, pocket centers, and the label-recess
    rectangle (with each row's text baseline position inside it, LOCAL
    to the recess's own SW corner -- what render_label() draws).

    With no arguments the plate is sized to fit the text (the standalone
    coupon).  Pass plate_w/plate_h to lay the same five rows out inside
    a GIVEN rectangle instead -- that is the P5 path, where the key's
    footprint comes from config [key] and the rows have to fit it.  The
    row pitch then divides the available height evenly, and the caller's
    width sets how much room the label recess gets."""
    ff = ca._font_file(FONT)
    widths = {}
    for lab in LABELS:
        g = ca._letter_poly(lab, ff, CAP_MM, ca.CHORD_TOL_MM)
        widths[lab] = g.bounds[2] - g.bounds[0]
    text_w = max(widths.values())
    pocket_d = POCKET_D_MM if pocket_d is None else pocket_d

    if plate_h is None:
        plate_h = 2 * MARGIN_MM + 5 * pocket_d + 4 * ROW_GAP_MM
    if plate_w is None:
        plate_w = (MARGIN_MM + pocket_d + TEXT_GAP_MM + text_w
                   + TEXT_MARGIN_MM + MARGIN_MM)
    # rows fill the usable height evenly, whatever it is
    usable_h = plate_h - 2 * MARGIN_MM
    row_pitch = usable_h / len(LABELS)
    assert row_pitch >= pocket_d + 0.5, (
        f"key too short: {len(LABELS)} rows of dia {pocket_d:g} mm need "
        f"> {len(LABELS) * (pocket_d + 0.5) + 2 * MARGIN_MM:.1f} mm, "
        f"have {plate_h:.1f}")

    pocket_x = plate_w - MARGIN_MM - pocket_d / 2
    recess = {"x0": MARGIN_MM, "y0": MARGIN_MM,
             "x1": plate_w - MARGIN_MM - pocket_d - TEXT_GAP_MM,
             "y1": plate_h - MARGIN_MM}
    assert recess["x1"] - recess["x0"] > 10.0, (
        f"key too narrow: label recess only "
        f"{recess['x1'] - recess['x0']:.1f} mm wide")
    rows = []
    for i, lab in enumerate(LABELS):
        cy = plate_h - MARGIN_MM - row_pitch / 2 - i * row_pitch
        rows.append({"label": lab, "pocket_c": (pocket_x, cy),
                     "text_y_local": cy - recess["y0"]})
    return plate_w, plate_h, rows, recess


# ------------------------------------------------------------------ mesh
def build_plate(width, height, recesses, thickness, seg=48):
    """Rectangle `width` x `height` x `thickness`, with a BLIND recess
    (its own depth, recessed into the TOP face only -- bottom stays
    solid) for each entry in `recesses`: {"points": Nx2 CCW ring,
    "depth": float}. Returns a watertight trimesh.Trimesh."""
    corners = np.array([[0, 0], [width, 0], [width, height], [0, height]],
                       float)
    rings = [r["points"] for r in recesses]

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

    # bottom cap: same 4 corners, flat solid rectangle (no recesses go
    # all the way through), normal -z (reverse of the +z convention above)
    b0 = len(np.vstack(verts))
    verts.append(np.column_stack([corners, np.zeros(4)]))
    faces.append(b0 + np.array([[0, 2, 1], [0, 3, 2]]))

    # outer side walls: CCW rectangle boundary -> solid on the LEFT of
    # each directed edge -> outward wall = (a_lo,b_lo,b_hi),(a_lo,b_hi,a_hi)
    w0 = b0 + 4
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
        zf = thickness - depth
        n = len(ring)
        vbase = len(np.vstack(verts))
        # fan triangulate the floor from the ring's centroid (works for
        # any star-shaped-from-centroid outline -- true for a circle or
        # an axis-aligned rectangle, both used here)
        cx, cy = ring.mean(axis=0)
        verts.append(np.array([[cx, cy, zf]]))
        verts.append(np.column_stack([ring, np.full(n, zf)]))
        center_idx = vbase
        floor_idx = vbase + 1 + np.arange(n)
        fan = np.stack([np.full(n, center_idx), floor_idx,
                        np.roll(floor_idx, -1)], axis=1)
        faces.append(fan)

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
def render_label(recess, rows):
    """Print-at-100% PDF sized exactly to the label recess, text rows
    aligned to the same y-coordinates as the pockets."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    w = recess["x1"] - recess["x0"]
    h = recess["y1"] - recess["y0"]
    fig = plt.figure(figsize=(w / 25.4, h / 25.4), dpi=300)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(0, h)
    ax.set_aspect("equal")
    ax.axis("off")
    for r in rows:
        ax.text(1.0, r["text_y_local"], r["label"], fontfamily="Georgia",
                fontweight="bold", fontsize=CAP_MM * 3.4, va="center",
                ha="left")
    path = OUT_DIR / "key_insert.pdf"
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"-> {path} ({w:.1f} x {h:.1f} mm, print at 100%/actual size)")
