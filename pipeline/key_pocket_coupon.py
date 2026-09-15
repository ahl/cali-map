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
"""Key-pocket test coupon (ahl 2026-09-15): a tiny square carrying ONE
blind pocket, plus the plug that goes in it -- print both, press them
together, and decide the final plug dimensions before the real key
(D19, built into p5_final.py) commits to five filament colours.

Pocket geometry is taken from config [key] so the coupon always matches
the real key's pockets. Plug dimensions are the OPEN question this
coupon exists to answer, so they live here:

    plug diameter = pocket + INSERT_INTERFERENCE_MM   (press fit)
    plug height   = pocket depth + INSERT_BUMP_MM     (stands proud)

Outputs: out/key_coupon/{pocket_coupon.stl, plug.stl}
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import key_panel as kp
import p4_bay_coupon as p4c

OUT_DIR = p4c.ROOT / "out" / "key_coupon"
KEY = p4c._CFG_ALL.get("key", {})

POCKET_D_MM = KEY.get("pocket_d_mm", 7.0)
POCKET_DEPTH_MM = KEY.get("pocket_depth_mm", 1.4)
PLATE_THICKNESS_MM = POCKET_DEPTH_MM + 1.2   # + solid floor under it
MARGIN_MM = 5.0

# The knobs this coupon exists to settle. They live in config [key]
# (not here) so the coupon and the real P5 plugs cannot drift apart --
# see the comment there.
INSERT_INTERFERENCE_MM = KEY.get("plug_interference_mm", 0.05)
INSERT_BUMP_MM = KEY.get("plug_proud_mm", 0.4)
INSERT_D_MM = POCKET_D_MM + INSERT_INTERFERENCE_MM
INSERT_HEIGHT_MM = POCKET_DEPTH_MM + INSERT_BUMP_MM


def main():
    side = POCKET_D_MM + 2 * MARGIN_MM
    center = (side / 2, side / 2)
    recesses = [{"points": kp.circle_ring(*center, POCKET_D_MM / 2),
                "depth": POCKET_DEPTH_MM}]
    coupon = kp.build_plate(side, side, recesses, PLATE_THICKNESS_MM)
    assert coupon.is_watertight
    if coupon.volume < 0:
        coupon.invert()
    plug = kp.insert_mesh(INSERT_D_MM, INSERT_HEIGHT_MM)
    assert plug.is_watertight

    print(f"key pocket coupon: {side:.1f} x {side:.1f} x "
          f"{PLATE_THICKNESS_MM:g} mm, pocket dia {POCKET_D_MM:g} x "
          f"{POCKET_DEPTH_MM:g} deep (from config [key], so it matches "
          f"the real key)\n"
          f"  plug: dia {INSERT_D_MM:g} mm ({POCKET_D_MM:g} + "
          f"{INSERT_INTERFERENCE_MM:g} interference) x {INSERT_HEIGHT_MM:g} "
          f"mm tall, flat-topped ({POCKET_DEPTH_MM:g} seated + {INSERT_BUMP_MM:g} proud)\n"
          f"  watertight: coupon {coupon.is_watertight}, plug "
          f"{plug.is_watertight}")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for name, mesh in (("pocket_coupon", coupon), ("plug", plug)):
        path = OUT_DIR / f"{name}.stl"
        mesh.export(path)
        print(f"-> {path}")
    print("press the plug into the coupon: too loose or too tight, tune "
          "[key].plug_interference_mm / plug_proud_mm in config.toml -- "
          "that updates this coupon AND the real P5 plugs together.")


if __name__ == "__main__":
    main()
