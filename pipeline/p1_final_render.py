# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "pyproj", "matplotlib", "scipy"]
# ///
"""P1 final-state render: one full-state map straight from config.toml —
whatever the current knobs and rules produce. THE artifact to review when
asking "what does P1 currently say?".

Output: out/p1_final.png
"""

import sys
import tomllib
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

CFG = tomllib.loads((base.ROOT / "config.toml").read_text())["regions"]


def main():
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    prov, name_id = base.rasterize_provinces()
    sea = base.ocean_mask(dem)
    reg, _ = base.build_regions(
        dem, prov, name_id, CFG["coast_threshold_m"],
        band_km=CFG["coast_band_km"],
        shore_dist=ndimage.distance_transform_edt(~sea))
    pct = {nm: 100 * (reg == rid).sum() / (reg > 0).sum()
           for nm, rid in [("coast", base.COAST), ("mountains", base.MOUNTAINS),
                           ("valley", base.VALLEY), ("desert", base.DESERT)]}
    print("  ".join(f"{k} {v:.1f}%" for k, v in pct.items()))

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land, vert_exag=12,
                         dx=base.META["res"], dy=base.META["res"])
    x0k, x1k, y0k, y1k = -420, 560, -680, 470
    xm, ym = base.META["x_min"] / 1000, base.META["y_max"] / 1000
    res_k = base.META["res"] / 1000
    c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
    r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
    ss = 2

    sh = shade[r0:r1:ss, c0:c1:ss]
    rg = reg[r0:r1:ss, c0:c1:ss]
    se = sea[r0:r1:ss, c0:c1:ss]
    rgb = np.dstack([sh, sh, sh]) * 0.55 + 0.45
    for rid, col in base.COLORS.items():
        m = rg == rid
        for ch in range(3):
            rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.45 + col[ch] * 0.55
    rgb[se] = (0.70, 0.79, 0.87)

    fig, ax = plt.subplots(figsize=(13, 15), dpi=170)
    ax.imshow(rgb, extent=[x0k, x1k, y0k, y1k], interpolation="bilinear")
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_title(
        "P1 FINAL STATE (from config.toml): "
        f"coast = {CFG['coast_threshold_m']} m + {CFG['coast_band_km']} km "
        "band\nrules: valley absorb/enclosure/lowland, Carquinez gate, "
        "desert cap, contiguity  |  "
        + "  ".join(f"{k} {v:.0f}%" for k, v in pct.items()),
        fontsize=12)
    base.OUT.mkdir(exist_ok=True)
    fig.savefig(base.OUT / "p1_final.png", bbox_inches="tight")
    print(f"wrote {base.OUT / 'p1_final.png'}")


if __name__ == "__main__":
    main()
