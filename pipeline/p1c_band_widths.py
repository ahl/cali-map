# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "scipy",
# ]
# ///
"""P1c: compare shoreline band widths (300 m threshold + N km band).

Reuses the region machinery from p1_regions.py; only the band width varies.
Output: out/p1c_band_widths.png
"""

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

# (threshold_m, band_km) per panel; output filename for the figure
PANELS_SPEC = [(25, 12), (25, 13), (25, 14), (25, 15)]
OUT_NAME = "p1c_band_fine.png"
FIG_TITLE = ("P1c: fine band sweep at 25 m threshold, "
             "all rules incl. contiguity")


def main():
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    prov, name_id = base.rasterize_provinces()
    sea = base.ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea)

    panels = []
    for t, b in PANELS_SPEC:
        reg, _ = base.build_regions(dem, prov, name_id, t,
                                    band_km=b, shore_dist=shore_dist)
        pct = 100 * (reg == base.COAST).sum() / (reg > 0).sum()
        panels.append((f"{t} m + {b:g} km shoreline band  "
                       f"(coast = {pct:.0f}% of CA)", reg))
        print(f"threshold {t} m, band {b:g} km: coast {pct:.1f}% of CA area")

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land, vert_exag=12,
                         dx=base.META["res"], dy=base.META["res"])
    x0k, x1k, y0k, y1k = -420, 560, -660, 470
    xm, ym = base.META["x_min"] / 1000, base.META["y_max"] / 1000
    res_k = base.META["res"] / 1000
    c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
    r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
    ss = 3

    fig, axes = plt.subplots(2, 2, figsize=(15, 18), dpi=140)
    for ax, (title, reg) in zip(axes.ravel(), panels):
        sh = shade[r0:r1:ss, c0:c1:ss]
        rg = reg[r0:r1:ss, c0:c1:ss]
        se = sea[r0:r1:ss, c0:c1:ss]
        rgb = np.dstack([sh, sh, sh]) * 0.55 + 0.45
        for rid, col in base.COLORS.items():
            m = rg == rid
            for ch in range(3):
                rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.45 + col[ch] * 0.55
        rgb[se] = (0.70, 0.79, 0.87)
        ax.imshow(rgb, extent=[x0k, x1k, y0k, y1k])
        ax.set_title(title, fontsize=13)
        ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle(FIG_TITLE, fontsize=14, y=0.995)
    fig.tight_layout()
    base.OUT.mkdir(exist_ok=True)
    fig.savefig(base.OUT / OUT_NAME, bbox_inches="tight")
    print(f"wrote {base.OUT / OUT_NAME}")


if __name__ == "__main__":
    main()
