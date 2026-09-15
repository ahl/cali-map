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
"""Key-pocket fit LADDER (ahl 2026-09-15): one strip of pockets at the
real key's diameter, and a matching row of plugs at a range of
diameters, so the right plug size is MEASURED in one print instead of
guessed one print at a time.

Why a ladder: the first attempt used +0.05 mm of designed interference
and came out far too tight -- ahl forced it in and deformed the plug.
That is the usual FDM small-hole story: a nominal 5 mm pocket prints
undersize (the inner perimeter's extrusion overlaps into the bore) while
the plug prints slightly oversize, so a few hundredths of *designed*
interference can be a few tenths in plastic. The size of that error is a
property of the printer and profile, not something to derive -- so
print the ladder, find the plug that seats firmly by hand without
force, and put that number in config.

The POCKET is a DESIGN dimension -- the key's row layout is built around
it -- so it is not a fit knob and stays at [key].pocket_d_mm. Only the
PLUGS vary, and [key].plug_d_mm is an absolute diameter rather than an
offset, so there is exactly one number to tune.

Orientation: the coupon has a small INDEX DIMPLE beside pocket #1, the
smallest plug. Plugs print in the same order, smallest first.

Outputs: out/key_coupon/{pocket_ladder.stl, plug_ladder.stl}
"""

import sys
from pathlib import Path

import numpy as np
import trimesh

sys.path.insert(0, str(Path(__file__).resolve().parent))
import key_panel as kp
import p4_bay_coupon as p4c

OUT_DIR = p4c.ROOT / "out" / "key_coupon"
KEY = p4c._CFG_ALL.get("key", {})

POCKET_D_MM = KEY.get("pocket_d_mm", 5.0)
POCKET_DEPTH_MM = KEY.get("pocket_depth_mm", 1.4)
PLATE_THICKNESS_MM = POCKET_DEPTH_MM + 1.2   # + solid floor under it
MARGIN_MM = 4.0
PITCH_MM = POCKET_D_MM + 5.0                 # pocket-to-pocket spacing
INDEX_D_MM = 1.6                             # orientation dimple

# The ladder of PLUG diameters to try. The pocket is fixed at the key's
# design size and is not a fit knob (ahl 2026-09-15: "just pick the
# pocket size and we'll try several plugs"), so these are absolute
# diameters -- the winner goes straight into [key].plug_d_mm, which the
# real P5 plug reads. Spanning below the pocket because a 5.05 mm plug
# was already far too tight: with print growth the usable range sits
# under nominal, and the plug is glued, so it need not grip on its own.
LADDER_D_MM = [4.70, 4.75, 4.80, 4.85, 4.90, 4.95, 5.00]

# from config, for the final (single-plug) geometry the key ships
INSERT_BUMP_MM = KEY.get("plug_proud_mm", 0.4)
INSERT_HEIGHT_MM = POCKET_DEPTH_MM + INSERT_BUMP_MM


def main():
    n = len(LADDER_D_MM)
    width = 2 * MARGIN_MM + (n - 1) * PITCH_MM + POCKET_D_MM
    height = 2 * MARGIN_MM + POCKET_D_MM
    cy = height / 2
    xs = [MARGIN_MM + POCKET_D_MM / 2 + i * PITCH_MM for i in range(n)]

    recesses = [{"points": kp.circle_ring(x, cy, POCKET_D_MM / 2),
                "depth": POCKET_DEPTH_MM} for x in xs]
    # index dimple beside pocket #1 (the smallest plug)
    recesses.append({"points": kp.circle_ring(
        MARGIN_MM + POCKET_D_MM / 2, MARGIN_MM / 2, INDEX_D_MM / 2),
        "depth": POCKET_DEPTH_MM})
    coupon = kp.build_plate(width, height, recesses, PLATE_THICKNESS_MM)
    assert coupon.is_watertight, "pocket ladder not watertight"
    if coupon.volume < 0:
        coupon.invert()

    plugs = []
    for i, d in enumerate(LADDER_D_MM):
        m = kp.insert_mesh(d, INSERT_HEIGHT_MM)
        m.apply_translation([xs[i], cy, 0.0])
        assert m.is_watertight
        plugs.append(m)
    ladder = trimesh.util.concatenate(plugs)

    print(f"key-pocket FIT LADDER: pockets all {POCKET_D_MM:g} mm dia x "
          f"{POCKET_DEPTH_MM:g} deep (the real key's size, from config "
          f"[key]); {n} plugs, {INSERT_HEIGHT_MM:g} mm tall, flat-topped")
    print(f"  plate {width:.1f} x {height:.1f} x {PLATE_THICKNESS_MM:g} mm; "
          f"index dimple marks plug #1")
    for i, d in enumerate(LADDER_D_MM, start=1):
        print(f"    #{i}  plug dia {d:5.2f} mm  "
              f"({d - POCKET_D_MM:+.2f} vs the {POCKET_D_MM:g} mm pocket)")
    print(f"  coupon watertight {coupon.is_watertight}, plugs watertight "
          f"{ladder.is_watertight}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, mesh in (("pocket_ladder", coupon), ("plug_ladder", ladder)):
        path = OUT_DIR / f"{name}.stl"
        mesh.export(path)
        print(f"-> {path}")
    print("\nprint both, press each plug into its own pocket, and pick the "
          "one that seats firmly BY HAND with no force (it is glued and "
          "permanent, so it does not need to grip on its own).\n"
          "then set [key].plug_d_mm to that diameter -- the real P5 plug "
          "(out/p5/key_plug.stl) reads the same knob.")


if __name__ == "__main__":
    main()
