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

The POCKETS stay at the key's real diameter ([key].pocket_d_mm); only
the PLUGS vary, since the pocket is what the key is committed to.

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

# The ladder: plug diameter = POCKET_D_MM + step. NEGATIVE is clearance.
# Centred on clearance, not interference, because +0.05 was already too
# tight -- the true zero is somewhere below 0 once print growth is
# accounted for. The winner goes into config [key].plug_interference_mm,
# which both this coupon and the real P5 plug read.
LADDER_MM = [-0.30, -0.25, -0.20, -0.15, -0.10, -0.05, 0.00]

# from config, for the final (single-plug) geometry the key ships
INSERT_BUMP_MM = KEY.get("plug_proud_mm", 0.4)
INSERT_HEIGHT_MM = POCKET_DEPTH_MM + INSERT_BUMP_MM


def main():
    n = len(LADDER_MM)
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
    for i, step in enumerate(LADDER_MM):
        m = kp.insert_mesh(POCKET_D_MM + step, INSERT_HEIGHT_MM)
        m.apply_translation([xs[i], cy, 0.0])
        assert m.is_watertight
        plugs.append(m)
    ladder = trimesh.util.concatenate(plugs)

    print(f"key-pocket FIT LADDER: pockets all {POCKET_D_MM:g} mm dia x "
          f"{POCKET_DEPTH_MM:g} deep (the real key's size, from config "
          f"[key]); {n} plugs, {INSERT_HEIGHT_MM:g} mm tall, flat-topped")
    print(f"  plate {width:.1f} x {height:.1f} x {PLATE_THICKNESS_MM:g} mm; "
          f"index dimple marks plug #1")
    for i, step in enumerate(LADDER_MM, start=1):
        print(f"    #{i}  plug dia {POCKET_D_MM + step:5.2f} mm  "
              f"({step:+.2f} vs pocket)")
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
          "then set [key].plug_interference_mm to that step -- the real "
          "P5 plug (out/p5/key_plug.stl) reads the same knob.")


if __name__ == "__main__":
    main()
