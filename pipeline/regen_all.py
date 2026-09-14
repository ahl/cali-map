# /// script
# requires-python = ">=3.11"
# dependencies = []
# ///
"""Regenerate the whole artifact chain from config.toml + overrides/.

THE automation contract (ahl, 2026-09-13): change any region aspect —
a config knob or a new markup override — then run this; everything
downstream rebuilds in dependency order.

  uv run pipeline/regen_all.py            # full chain
  uv run pipeline/regen_all.py p15 p4     # named stages only

Stages (in order):
  p1        statewide region render (out/p1_final.png)
  p2land    Census land authority (cached downloads)
  p2vec     region vectorization -> data/p2_regions*.geojson
  p15       statewide engraved slab STL
  p15b      Bay Area engraved inset STL (zoom-11 terrain)
  p4        Bay Area fit coupons (both scales + frames)
"""

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent

STAGES = [
    ("p1", "p1_final_render.py"),
    ("p2land", "p2_land.py"),
    ("p2vec", "p2_vectorize.py"),
    ("p15", "p15_engraved.py"),
    ("p15b", "p15b_vallejo_inset.py"),
    ("p4", "p4_bay_coupon.py"),
]


def main():
    want = set(sys.argv[1:])
    unknown = want - {n for n, _ in STAGES}
    if unknown:
        sys.exit(f"unknown stage(s): {sorted(unknown)}; "
                 f"valid: {[n for n, _ in STAGES]}")
    t00 = time.time()
    for name, script in STAGES:
        if want and name not in want:
            continue
        t0 = time.time()
        print(f"=== {name}: {script} ===", flush=True)
        r = subprocess.run(["uv", "run", str(HERE / script)])
        if r.returncode != 0:
            sys.exit(f"stage {name} FAILED (exit {r.returncode}); chain "
                     "stopped — downstream artifacts are now stale.")
        print(f"=== {name} ok ({time.time() - t0:.0f}s) ===", flush=True)
    print(f"ALL DONE in {(time.time() - t00) / 60:.1f} min")


if __name__ == "__main__":
    main()
