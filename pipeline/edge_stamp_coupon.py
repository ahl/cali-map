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
#   "manifold3d",
# ]
# ///
"""Edge-stamp DEPTH LADDER (ahl 2026-09-15): a bar the same height as
the frame's outer wall, carrying the attribution text at several
depths, so "really subtle; like barely visible" gets decided from a
print rather than guessed.

The bar is [print].base_mm tall -- exactly the frame's wall at a water
edge -- so the text sits in the same z band, spans the same layers, and
is read at the same angle as it will be on the real thing.

TEXT ON BOTH FACES (ahl 2026-09-15), two rungs a side, which halves the
bar. Both faces are outer perimeters, so the slicer generates them the
same way; the back text is mirrored so it reads correctly from the back.
Each block is SELF-IDENTIFYING -- n notches in the top edge above rung n
-- so no orientation convention has to be remembered, and the notches
are Z cuts, which stay crisp no matter what the XY depths do.

What it answers, in the order that matters:
  1. is 2.0 mm cap LEGIBLE at all? At 0.2 mm layers that is ten layers
     per letter, and every diagonal is a staircase. If ten layers cannot
     render the text, the knob is cap_mm, not depth_mm -- no depth fixes
     it. All four rungs share the cap, so this comes out for free.
  2. which depths survive the slicer (a 0.45 mm stroke, 0.2 mm deep,
     against a ~0.42 mm perimeter -- Arachne may smooth the shallow ones
     away entirely).
  3. which one reads as "barely visible" to ahl, which is not
     computable.
A coupon is a mildly PESSIMISTIC test: its layers are quick, so it cools
less between them than the 225 x 250 frame does. If a depth reads here,
it reads there.

One solid bar rather than the frame's floor+water pair: those are two
bodies of the SAME filament overlapping by OVERLAP_MM, which the slicer
unions, so the printed wall is identical and the seam is not what is
being tested here.

Text, font and cap come from config [edge_stamp]; only the DEPTH varies.
Depths run shallow to deep, with an index notch marking the shallow end.

Output: out/edge_stamp/depth_ladder.stl
"""

import sys
from pathlib import Path

import numpy as np
import trimesh
from shapely import affinity

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compass_art as ca
import p4_bay_coupon as p4c

OUT_DIR = p4c.ROOT / "out" / "edge_stamp"
CFG = p4c._CFG_ALL.get("edge_stamp", {})

DEPTHS_MM = [0.10, 0.15, 0.20, 0.30]   # shallow -> deep
PER_FACE = 2          # rungs per face; the rest go on the back
BAR_D_MM = 8.0        # how deep the bar is (front to back)
PAD_MM = 5.0          # blank bar before/after each text block
NOTCH_MM = 1.0        # index notch: n of them above rung n
NOTCH_PITCH_MM = 2.0
NOTCH_INSET_MM = 2.0  # from its own face, so front/back marks do not mix
OVER = 0.4            # cut slack outside the face


def text_prisms(txt, ff, cap, depth, x0, wall_h, back=False):
    """Glyph prisms to subtract from one face of the bar, recessed
    `depth` into it. front = y 0 (cut runs -OVER..depth); back = y
    BAR_D_MM (cut runs BAR_D_MM-depth..+OVER), with the glyphs MIRRORED
    so the text reads correctly when you turn the bar around.
    Returns (prisms, width, height)."""
    g = ca._letter_poly(txt, ff, cap, ca.CHORD_TOL_MM)
    # merge glyphs that TOUCH (adjacent letters, "&" crossing itself):
    # left as separate parts they meet at an exact edge and the boolean
    # returns a non-manifold pinch there. A 2 um dilate unions them;
    # that is 0.004 mm on a 0.45 mm stroke, well under one nozzle.
    g = g.buffer(0.002)
    if back:
        g = affinity.scale(g, xfact=-1.0, yfact=1.0, origin="center")
    bx0, by0, bx1, by1 = g.bounds
    g = affinity.translate(g, -bx0, -by0)
    w, h = bx1 - bx0, by1 - by0
    v0 = (wall_h - h) / 2.0
    out = []
    for part in getattr(g, "geoms", [g]):
        m = trimesh.creation.extrude_polygon(part, depth + OVER,
                                             engine="triangle")
        # local (u, v, t) -> world (x, y=into the bar, z=up the wall)
        m.apply_transform(np.array([[1, 0, 0, 0], [0, 0, 1, 0],
                                    [0, 1, 0, 0], [0, 0, 0, 1]], float))
        m.apply_translation([x0, BAR_D_MM - depth if back else -OVER, v0])
        out.append(m)
    return out, w, h


def notches(n, x_mid, back, wall_h):
    """n index notches in the TOP edge above a block, inset from that
    block's OWN face so front and back marks never mix. Z cuts, so they
    stay legible whatever the XY depths do."""
    y = BAR_D_MM - NOTCH_INSET_MM if back else NOTCH_INSET_MM
    x0 = x_mid - (n - 1) * NOTCH_PITCH_MM / 2.0
    out = []
    for i in range(n):
        b = trimesh.creation.box(
            extents=(NOTCH_MM, NOTCH_MM, 2 * NOTCH_MM))
        b.apply_translation([x0 + i * NOTCH_PITCH_MM, y, wall_h])
        out.append(b)
    return out


def main():
    txt = CFG.get("text", "AL&JL 2026 v1.0")
    cap = float(CFG.get("cap_mm", 2.0))
    want = CFG.get("font", "Tahoma Bold")
    ff = ca._font_file(want)
    got = Path(ff).stem
    wall_h = p4c.BASE_MM

    probe = ca._letter_poly(txt, ff, cap, ca.CHORD_TOL_MM)
    stroke = ca.measure_min_stroke_vec(probe)
    bx = probe.bounds
    tw, th = bx[2] - bx[0], bx[3] - bx[1]

    seg = tw + 2 * PAD_MM
    n_face = min(PER_FACE, len(DEPTHS_MM))
    cols = -(-len(DEPTHS_MM) // n_face)       # blocks along the bar
    length = seg * cols
    bar = trimesh.creation.box(extents=(length, BAR_D_MM, wall_h))
    bar.apply_translation([length / 2, BAR_D_MM / 2, wall_h / 2])

    cuts, plan = [], []
    for i, d in enumerate(DEPTHS_MM):
        back = i >= n_face
        col = i % n_face if not back else (i - n_face)
        x0 = col * seg + PAD_MM
        pr, _, _ = text_prisms(txt, ff, cap, d, x0, wall_h, back=back)
        cuts += pr
        cuts += notches(i + 1, x0 + tw / 2.0, back, wall_h)
        plan.append((i + 1, d, "back" if back else "front", col + 1))

    # UNION the cut prisms before subtracting. Concatenating leaves
    # glyphs that touch (adjacent letters, the "&" crossing itself)
    # meeting at an exact edge, which comes back from the boolean as a
    # non-manifold edge shared by 4 faces -- closed and printable, but
    # not strictly manifold.
    tool = trimesh.boolean.union(cuts)
    out = bar.difference(tool)
    assert out.is_watertight, "edge-stamp ladder is not watertight"

    print(f"edge-stamp DEPTH LADDER: bar {length:.1f} x {BAR_D_MM:g} x "
          f"{wall_h:g} mm, text on BOTH faces\n"
          f"  {wall_h:g} mm tall = the frame's outer wall at a water edge "
          f"([print].base_mm), so the text sits in the same z band and "
          f"spans the same layers\n"
          f"  text {txt!r}, cap {cap:g} mm, {tw:.1f} x {th:.1f} mm, "
          f"thinnest stroke {stroke:.2f} mm\n"
          f"  cap {cap:g} mm = {cap / 0.2:.0f} layers at 0.2 mm -- if the "
          f"text is illegible at EVERY depth, the knob is cap_mm\n"
          f"  font {want!r} -> {got!r}"
          + ("" if got.lower().startswith(want.split()[0].lower())
             else "   [!] NOT the font requested -- silent fallback")
          + "\n  rungs (n notches in the top edge above rung n):")
    for n, d, face, col in plan:
        print(f"    #{n}  {d:.2f} mm   {face:5s} face, block {col} "
              f"from the left   ({n} notch{'es' if n > 1 else ''})")
    print(f"  watertight {out.is_watertight}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "depth_ladder.stl"
    out.export(path)
    print(f"-> {path}")
    print("\nprint it, look along it in RAKING LIGHT, and pick the "
          "shallowest rung you can still read.\ncount the notches to "
          "identify it, then set [edge_stamp].depth_mm to that depth --\n"
          "the frame reads the same knob, so nothing else changes.")


if __name__ == "__main__":
    main()
