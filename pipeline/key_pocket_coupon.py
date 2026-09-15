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
"""Key-panel pocket test coupon (ahl 2026-09-15) -- a tiny square with
just ONE blind pocket, same size/depth as key_panel.py's real ones, to
test-fit insert_sample.stl's plug (interference + proud-bump height)
before committing to the full 5-row plate.

Output: out/key_panel/pocket_coupon.stl
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import key_panel as kp


def main():
    side = kp.POCKET_D_MM + 2 * kp.MARGIN_MM
    center = (side / 2, side / 2)
    recesses = [{"points": kp.circle_ring(*center, kp.POCKET_D_MM / 2),
                "depth": kp.POCKET_DEPTH_MM}]
    coupon = kp.build_plate(side, side, recesses, kp.PLATE_THICKNESS_MM)
    print(f"pocket coupon: {side:.1f} x {side:.1f} x "
          f"{kp.PLATE_THICKNESS_MM:g} mm, pocket dia {kp.POCKET_D_MM:g} "
          f"mm x {kp.POCKET_DEPTH_MM:g} mm deep (matches key_panel.py)\n"
          f"  watertight={coupon.is_watertight} volume={coupon.volume:.1f} "
          "mm^3")
    assert coupon.is_watertight
    if coupon.volume < 0:
        coupon.invert()

    kp.OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = kp.OUT_DIR / "pocket_coupon.stl"
    coupon.export(path)
    print(f"-> {path}")
    print("test with out/key_panel/insert_sample.stl (dia "
          f"{kp.INSERT_D_MM:g} mm x {kp.INSERT_HEIGHT_MM:g} mm) -- "
          "regenerate that via `uv run pipeline/key_panel.py` if stale")


if __name__ == "__main__":
    main()
