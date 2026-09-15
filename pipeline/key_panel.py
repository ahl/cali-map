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
"""Region-color key panel (ahl 2026-09-14/15) -- a rectangular plate
that sits in its own cavity in the P5 frame (placement TBD, "somewhere
over Nevada"; per ahl this step is JUST the standalone piece -- the
frame cavity subtraction is a follow-on step).

v2 (ahl 2026-09-15): 3D-printed raised text at 3.5 mm cap crowded even
after narrowing the glyphs (fighting a 0.4 mm nozzle's resolution, not
a font problem) -- ahl's call: print the labels on a real 2D printer
instead. So the plate is now SINGLE-COLOR (white, no black text pass):
five rows in ahl's order (Pacific Ocean, Coastal, Mountain, Valley,
Desert), each with

  - a BLIND circular pocket (recessed into the TOP face only, solid
    floor underneath -- ahl's choice over a through-hole) sized for a
    small color-matched insert PLUG that prints alongside whichever
    job already uses that filament (water/coast from frame.3mf,
    mountain/valley/desert from their piece STLs). Plugs are permanent
    (ahl 2026-09-15): a deliberate diameter INTERFERENCE for a snug
    press fit (glue optional, not required), sized taller than the
    pocket so the plug sits proud once seated -- a felt bump, not
    flush;
  - a shallow (0.2 mm, one layer) rectangular recess across the text
    column -- ONE recess spanning all 5 rows -- sized for a printed
    label (key_label.pdf, exact physical size) to sit in, so its edge
    doesn't catch and it sits close to flush with the pocket rims.

Geometry: one CDT of the plate rectangle with the 5 pocket circles AND
the label rectangle as holes (constrained, exact boundary match -- same
recipe as compass_art.RosePanel/version_stamp.stamped_bottom) gives the
top face (thickness) and, reusing the identical boundary points, a
floor patch per recess (each at its OWN depth) plus the connecting
vertical walls. Outer side walls + a flat bottom close the plate. All
pieces share exact float coordinates and get merged with
version_stamp.weld (round-and-merge), the convention documented in
version_stamp.py's module docstring.

Output:
  out/key_panel/key_panel.stl      single-color plate (white), watertight
  out/key_panel/insert_sample.stl  one sample plug, for a test-fit print
  out/key_panel/key_label.pdf      print-at-100% label for the recess
  out/key_panel/preview.png
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

OUT_DIR = p4c.ROOT / "out" / "key_panel"

LABELS = ["Pacific Ocean", "Coastal", "Mountain", "Valley", "Desert"]

CAP_MM = 3.5               # label cap height (just sizes the layout --
                           # no FDM stroke-floor constraint now, it's a
                           # real printer)
FONT = "Georgia Bold"      # matches the compass rose

POCKET_D_MM = 7.0          # swatch-insert hole diameter
POCKET_DEPTH_MM = 1.4      # blind pocket depth (7 layers)
FLOOR_UNDER_POCKET_MM = 1.2    # solid material left under a pocket floor
PLATE_THICKNESS_MM = POCKET_DEPTH_MM + FLOOR_UNDER_POCKET_MM  # 2.6
# ahl 2026-09-15: plugs are PERMANENT (snug friction fit + maybe glue,
# never removed) -- the opposite goal from the piece/frame clearance
# (CLEARANCE_MM, meant to come apart by hand), so this is a small
# INTERFERENCE like the crush ribs (RIB_INTERFERENCE_MM = 0.05 total),
# not a clearance. Tune after the first test fit, same as the ribs were.
INSERT_INTERFERENCE_MM = 0.05    # insert dia = pocket dia + this (total)
INSERT_D_MM = POCKET_D_MM + INSERT_INTERFERENCE_MM
INSERT_BUMP_MM = 0.4             # proud of the plate top once seated --
                                 # a felt "bump", matches the rose's
                                 # validated raised height
INSERT_HEIGHT_MM = POCKET_DEPTH_MM + INSERT_BUMP_MM

LABEL_RECESS_MM = 0.2      # one layer -- just enough for the label's
                           # paper/vinyl thickness to sit near-flush

MARGIN_MM = 5.0             # plate edge -> content
ROW_GAP_MM = 3.0            # gap between pocket circles, row to row
TEXT_GAP_MM = 3.0           # pocket -> label-recess gap
TEXT_MARGIN_MM = 2.0        # extra clearance beyond the measured text box

ROSE_EXTRUDERS = {"coast": 1, "water": 2}   # frame.3mf filaments that
                           # own the Pacific/Coastal swatches
PIECE_NAME = {"Mountain": "mountains", "Valley": "valley",
              "Desert": "desert"}            # -> piece STL that owns it


# ---------------------------------------------------------------- layout
def layout():
    """Row geometry: plate size, pocket centers, and the label-recess
    rectangle (with each row's text baseline position inside it, LOCAL
    to the recess's own SW corner -- what render_label() draws)."""
    ff = ca._font_file(FONT)
    widths = {}
    for lab in LABELS:
        g = ca._letter_poly(lab, ff, CAP_MM, ca.CHORD_TOL_MM)
        widths[lab] = g.bounds[2] - g.bounds[0]
    text_w = max(widths.values())

    row_pitch = POCKET_D_MM + ROW_GAP_MM
    plate_h = 2 * MARGIN_MM + 5 * POCKET_D_MM + 4 * ROW_GAP_MM
    plate_w = (MARGIN_MM + POCKET_D_MM + TEXT_GAP_MM + text_w
              + TEXT_MARGIN_MM + MARGIN_MM)

    pocket_x = plate_w - MARGIN_MM - POCKET_D_MM / 2
    recess = {"x0": MARGIN_MM, "y0": MARGIN_MM,
             "x1": plate_w - MARGIN_MM - POCKET_D_MM - TEXT_GAP_MM,
             "y1": plate_h - MARGIN_MM}
    rows = []
    for i, lab in enumerate(LABELS):
        cy = plate_h - MARGIN_MM - POCKET_D_MM / 2 - i * row_pitch
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


def main():
    plate_w, plate_h, rows, recess = layout()
    print(f"key panel: {plate_w:.1f} x {plate_h:.1f} x "
          f"{PLATE_THICKNESS_MM:g} mm, {len(rows)} rows, pocket dia "
          f"{POCKET_D_MM:g} mm\n"
          f"  insert plugs: dia {INSERT_D_MM:g} mm ({POCKET_D_MM:g} + "
          f"{INSERT_INTERFERENCE_MM:g} mm interference -- press fit, "
          "permanent, glue optional) x height "
          f"{INSERT_HEIGHT_MM:g} mm ({POCKET_DEPTH_MM:g} mm seated + "
          f"{INSERT_BUMP_MM:g} mm proud bump)\n"
          f"  label recess: {recess['x1'] - recess['x0']:.1f} x "
          f"{recess['y1'] - recess['y0']:.1f} mm, {LABEL_RECESS_MM:g} mm "
          "deep -- print out/key_panel/key_label.pdf at 100% and trim "
          "to fit")

    recesses = [{"points": circle_ring(*r["pocket_c"], POCKET_D_MM / 2),
                "depth": POCKET_DEPTH_MM} for r in rows]
    recesses.append({"points": rect_ring(recess["x0"], recess["y0"],
                                         recess["x1"], recess["y1"]),
                     "depth": LABEL_RECESS_MM})
    plate = build_plate(plate_w, plate_h, recesses, PLATE_THICKNESS_MM)
    print(f"  plate: watertight={plate.is_watertight} "
          f"volume={plate.volume:.1f} mm^3")
    assert plate.is_watertight
    if plate.volume < 0:
        plate.invert()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    stl_path = OUT_DIR / "key_panel.stl"
    plate.export(stl_path)
    print(f"-> {stl_path}")

    insert = insert_mesh(INSERT_D_MM, INSERT_HEIGHT_MM)
    assert insert.is_watertight
    insert_path = OUT_DIR / "insert_sample.stl"
    insert.export(insert_path)
    print(f"-> {insert_path} (one sample plug, print-and-test-fit before "
          "committing to 5 filament colors)")

    render_label(recess, rows)
    render_preview(plate_w, plate_h, rows, recess)
    print("\nnext (not done here): 5 plugs (dia "
          f"{INSERT_D_MM:g} mm x {INSERT_HEIGHT_MM:g} mm, same shape as "
          "insert_sample.stl) added to whichever print already carries "
          "each filament -- Pacific Ocean/Coastal to frame.3mf "
          f"(extruders {ROSE_EXTRUDERS}), Mountain/Valley/Desert to their "
          f"piece STLs ({PIECE_NAME}); then cut this plate's footprint as "
          "a cavity into the P5 frame, placement TBD over Nevada.")


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
    path = OUT_DIR / "key_label.pdf"
    fig.savefig(path, facecolor="white")
    plt.close(fig)
    print(f"-> {path} ({w:.1f} x {h:.1f} mm, print at 100%/actual size)")


# ------------------------------------------------------------------ preview
def render_preview(plate_w, plate_h, rows, recess):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(plate_w / 20, plate_h / 20), dpi=200)
    ax.set_facecolor("#dcdcdc")
    ax.add_patch(plt.Rectangle((0, 0), plate_w, plate_h,
                               facecolor="#f4f4f0", edgecolor="black",
                               lw=0.5, zorder=1))
    ax.add_patch(plt.Rectangle((recess["x0"], recess["y0"]),
                               recess["x1"] - recess["x0"],
                               recess["y1"] - recess["y0"],
                               facecolor="#e8e8e2", edgecolor="#999999",
                               lw=0.4, ls=":", zorder=2))
    for r in rows:
        ax.add_patch(plt.Circle(r["pocket_c"], POCKET_D_MM / 2,
                                facecolor="#bdbdbd", edgecolor="black",
                                lw=0.4, zorder=3))
        ax.text(recess["x0"] + 1.0, recess["y0"] + r["text_y_local"],
               r["label"], fontfamily="Georgia", fontweight="bold",
               fontsize=CAP_MM * 3.4, va="center", ha="left", zorder=4)
    ax.set_xlim(0, plate_w)
    ax.set_ylim(0, plate_h)
    ax.set_aspect("equal")
    ax.axis("off")
    path = OUT_DIR / "preview.png"
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"-> {path}")


if __name__ == "__main__":
    main()
