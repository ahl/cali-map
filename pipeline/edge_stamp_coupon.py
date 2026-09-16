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
BAR_D_MM = 8.0        # how deep the bar is (front to back)
PAD_MM = 5.0          # blank bar before/after each text block
NOTCH_MM = 1.2        # index notch at the shallow end
OVER = 0.4            # cut slack outside the face


def text_prisms(txt, ff, cap, depth, x0, wall_h):
    """Glyph prisms to subtract from the bar's front face (y = 0),
    recessed `depth` into it. Returns (prisms, width, height)."""
    g = ca._letter_poly(txt, ff, cap, ca.CHORD_TOL_MM)
    # merge glyphs that TOUCH (adjacent letters, "&" crossing itself):
    # left as separate parts they meet at an exact edge and the boolean
    # returns a non-manifold pinch there. A 2 um dilate unions them;
    # that is 0.004 mm on a 0.45 mm stroke, well under one nozzle.
    g = g.buffer(0.002)
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
        m.apply_translation([x0, -OVER, v0])
        out.append(m)
    return out, w, h


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
    length = seg * len(DEPTHS_MM)
    bar = trimesh.creation.box(extents=(length, BAR_D_MM, wall_h))
    bar.apply_translation([length / 2, BAR_D_MM / 2, wall_h / 2])

    cuts = []
    for i, d in enumerate(DEPTHS_MM):
        pr, _, _ = text_prisms(txt, ff, cap, d, i * seg + PAD_MM, wall_h)
        cuts += pr
    # index notch at the shallow end, on the TOP face so it cannot be
    # mistaken for part of the lettering
    n = trimesh.creation.box(extents=(NOTCH_MM, BAR_D_MM + 1, NOTCH_MM))
    n.apply_translation([PAD_MM / 2, BAR_D_MM / 2, wall_h])
    cuts.append(n)

    # UNION the cut prisms before subtracting. Concatenating leaves
    # glyphs that touch (adjacent letters, the "&" crossing itself)
    # meeting at an exact edge, which comes back from the boolean as a
    # non-manifold edge shared by 4 faces -- closed and printable, but
    # not strictly manifold.
    tool = trimesh.boolean.union(cuts)
    out = bar.difference(tool)
    assert out.is_watertight, "edge-stamp ladder is not watertight"

    print(f"edge-stamp DEPTH LADDER: bar {length:.1f} x {BAR_D_MM:g} x "
          f"{wall_h:g} mm\n"
          f"  {wall_h:g} mm tall = the frame's outer wall at a water edge "
          f"([print].base_mm), so the text sits in the same z band and "
          f"spans the same layers\n"
          f"  text {txt!r}, cap {cap:g} mm, {tw:.1f} x {th:.1f} mm, "
          f"thinnest stroke {stroke:.2f} mm\n"
          f"  font {want!r} -> {got!r}"
          + ("" if got.lower().startswith(want.split()[0].lower())
             else "   [!] NOT the font requested -- silent fallback")
          + "\n  depths, shallow end first (notch marks it):")
    for i, d in enumerate(DEPTHS_MM, start=1):
        print(f"    #{i}  {d:.2f} mm")
    print(f"  watertight {out.is_watertight}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "depth_ladder.stl"
    out.export(path)
    print(f"-> {path}")
    print("\nprint it, look along it in raking light, and pick the "
          "shallowest one you can still read.\nthen set "
          "[edge_stamp].depth_mm to that -- the frame reads the same knob.")


if __name__ == "__main__":
    main()
