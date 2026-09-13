# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "pyproj", "matplotlib", "scipy"]
# ///
"""P1e: Channel Islands shelf study — distance contours around the islands.

Draws the union buffer outlines at 10/20/30/40 km around the Channel
Islands (buffers merge where islands' rings intersect) over the SoCal
coast, to pick the Coast piece's ocean-shelf outline (D2 / gap G11).

Output: out/p1e_island_buffers.png
"""

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

RINGS_KM = [10, 20, 30, 40]
# view window, Albers km: all eight Channel Islands + SoCal shore
X0, X1, Y0, Y1 = -170, 230, -660, -350


def main():
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    sea = base.ocean_mask(dem)
    land_lab, _ = ndimage.label(~sea)
    mainland = land_lab == np.argmax(np.bincount(land_lab[~sea].ravel()))
    islands = base.ca_islands(sea, mainland)

    dist_km = ndimage.distance_transform_edt(~islands) * base.META["res"] / 1000

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    xm, ym = base.META["x_min"] / 1000, base.META["y_max"] / 1000
    res_k = base.META["res"] / 1000
    c0, c1 = int((X0 - xm) / res_k), int((X1 - xm) / res_k)
    r0, r1 = int((ym - Y1) / res_k), int((ym - Y0) / res_k)
    ext = [X0, X1, Y0, Y1]

    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land[r0:r1, c0:c1], vert_exag=12,
                         dx=base.META["res"], dy=base.META["res"])
    se = sea[r0:r1, c0:c1]
    isl = islands[r0:r1, c0:c1]
    d = dist_km[r0:r1, c0:c1]

    rgb = np.dstack([shade] * 3) * 0.55 + 0.45
    rgb[se] = (0.70, 0.79, 0.87)
    yc = base.COLORS[base.COAST]
    for ch in range(3):
        rgb[:, :, ch][isl] = rgb[:, :, ch][isl] * 0.35 + yc[ch] * 0.65

    fig, ax = plt.subplots(figsize=(13, 11.5), dpi=150)
    ax.imshow(rgb, extent=ext)
    cs = ax.contour(d, levels=RINGS_KM, extent=[X0, X1, Y1, Y0],
                    colors=["#c0392b", "#8e44ad", "#2471a3", "#1e8449"],
                    linewidths=1.6)
    ax.clabel(cs, fmt=lambda v: f"{v:.0f} km", fontsize=10, inline=True)

    names = [("San Miguel", -120.37, 34.04), ("Santa Rosa", -120.05, 33.96),
             ("Santa Cruz", -119.72, 34.01), ("Anacapa", -119.37, 34.00),
             ("Santa Barbara", -119.03, 33.48), ("San Nicolas", -119.49, 33.24),
             ("Santa Catalina", -118.42, 33.39), ("San Clemente", -118.48, 32.90)]
    for nm, lo, la in names:
        px, py = base.TO_ALB.transform(lo, la)
        ax.annotate(nm, (px / 1000, py / 1000), fontsize=8, ha="center",
                    xytext=(0, -11), textcoords="offset points")

    ax.set_xlim(X0, X1)
    ax.set_ylim(Y0, Y1)
    ax.set_xlabel("km (CA Albers)")
    ax.set_ylabel("km")
    ax.set_title("P1e: Channel Islands — union distance rings at "
                 f"{RINGS_KM} km\n(candidate ocean-shelf outlines for the "
                 "Coast piece, D2/G11)", fontsize=12)
    base.OUT.mkdir(exist_ok=True)
    fig.savefig(base.OUT / "p1e_island_buffers.png", bbox_inches="tight")
    print(f"wrote {base.OUT / 'p1e_island_buffers.png'}")


if __name__ == "__main__":
    main()
