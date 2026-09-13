# /// script
# requires-python = ">=3.11"
# dependencies = ["numpy", "pillow", "pyproj", "matplotlib", "scipy"]
# ///
"""P1f: Channel Islands piece candidates (G11, ahl 2026-09-13).

2a TWO pieces: northern chain {San Miguel, Santa Rosa, Santa Cruz,
   Anacapa} + 10 km water; southern {San Nicolas, Santa Barbara,
   Santa Catalina, San Clemente} + 25 km water.
2b ONE piece: convex hull of all eight islands + 10 km.

Outputs: out/p1f_islands_two_pieces.png, out/p1f_islands_one_piece.png
"""

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
from scipy.spatial import ConvexHull

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

NORTH = {"San Miguel": (-120.37, 34.04), "Santa Rosa": (-120.05, 33.96),
         "Santa Cruz": (-119.72, 34.01), "Anacapa": (-119.37, 34.00)}
SOUTH = {"San Nicolas": (-119.49, 33.24), "Santa Barbara": (-119.03, 33.48),
         "Santa Catalina": (-118.42, 33.39), "San Clemente": (-118.48, 32.90)}
BUF_NORTH_KM, BUF_SOUTH_KM, BUF_HULL_KM = 10.0, 25.0, 10.0
MATCH_KM = 18.0   # island component belongs to a name if centroid within
X0, X1, Y0, Y1 = -170, 230, -680, -350  # view window, Albers km


def named_island_masks(sea, mainland):
    """{name: mask} for the eight Channel Islands, by centroid matching."""
    lab, n = ndimage.label(~sea & ~mainland)
    if n == 0:
        return {}
    sizes = ndimage.sum_labels(np.ones_like(lab), lab, np.arange(1, n + 1))
    targets = {}
    for nm, (lo, la) in (NORTH | SOUTH).items():
        px, py = base.px_of(lo, la)
        targets[nm] = (px, py)
    out = {}
    for i in np.where(sizes >= 4)[0] + 1:
        cy, cx = ndimage.center_of_mass(lab == i)
        for nm, (tx, ty) in targets.items():
            d_km = np.hypot(cx - tx, cy - ty) * base.META["res"] / 1000
            if d_km <= MATCH_KM:
                out.setdefault(nm, np.zeros(sea.shape, bool))
                out[nm] |= lab == i
    return out


def buffered(mask, km):
    return ndimage.distance_transform_edt(~mask) * base.META["res"] / 1000 <= km


def hull_mask(mask, shape):
    pts = np.argwhere(mask)  # (row, col)
    hull = ConvexHull(pts[:, ::-1])  # (x=col, y=row)
    poly = [tuple(p) for p in pts[:, ::-1][hull.vertices].astype(float)]
    img = Image.new("L", (shape[1], shape[0]), 0)
    ImageDraw.Draw(img).polygon(poly, fill=1)
    return np.asarray(img, bool)


def render(fname, title, shells, sea, dem, extras=()):
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
    rgb = np.dstack([shade] * 3) * 0.55 + 0.45
    rgb[se] = (0.70, 0.79, 0.87)

    fig, ax = plt.subplots(figsize=(13, 11.5), dpi=150)
    yc = base.COLORS[base.COAST]
    for shell, edge in shells:
        sh = shell[r0:r1, c0:c1]
        for ch in range(3):
            rgb[:, :, ch][sh] = rgb[:, :, ch][sh] * 0.55 + yc[ch] * 0.45
    ax.imshow(rgb, extent=ext)
    for shell, edge in shells:
        ax.contour(shell[r0:r1, c0:c1].astype(float), levels=[0.5],
                   extent=[X0, X1, Y1, Y0], colors=[edge], linewidths=2.0)
    for nm, (lo, la) in (NORTH | SOUTH).items():
        px, py = base.TO_ALB.transform(lo, la)
        ax.annotate(nm, (px / 1000, py / 1000), fontsize=8, ha="center",
                    xytext=(0, -11), textcoords="offset points")
    for txt in extras:
        ax.annotate(txt, (0.02, 0.02), xycoords="axes fraction", fontsize=10,
                    color="#333333")
    ax.set_xlim(X0, X1), ax.set_ylim(Y0, Y1)
    ax.set_xlabel("km (CA Albers)"), ax.set_ylabel("km")
    ax.set_title(title, fontsize=12)
    base.OUT.mkdir(exist_ok=True)
    fig.savefig(base.OUT / fname, bbox_inches="tight")
    print(f"wrote {base.OUT / fname}")


def main():
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    sea = base.ocean_mask(dem)
    land_lab, _ = ndimage.label(~sea)
    mainland = land_lab == np.argmax(np.bincount(land_lab[~sea].ravel()))
    isl = named_island_masks(sea, mainland)
    print("matched islands:", ", ".join(sorted(isl)))

    m_north = np.zeros(sea.shape, bool)
    for nm in NORTH:
        m_north |= isl[nm]
    m_south = np.zeros(sea.shape, bool)
    for nm in SOUTH:
        m_south |= isl[nm]

    # 2a: two pieces
    a_north = buffered(m_north, BUF_NORTH_KM)
    a_south = buffered(m_south, BUF_SOUTH_KM)
    ncomp_n = ndimage.label(a_north)[1]
    ncomp_s = ndimage.label(a_south)[1]
    area = lambda m: m.sum() * (base.META["res"] / 1000) ** 2
    print(f"2a north: {ncomp_n} component(s), {area(a_north):.0f} km2")
    print(f"2a south: {ncomp_s} component(s), {area(a_south):.0f} km2")
    if a_north.any() and a_south.any():
        d_ns = ndimage.distance_transform_edt(~a_north)[a_south].min() \
            * base.META["res"] / 1000
        print(f"2a min gap between pieces: {d_ns:.1f} km")
    render("p1f_islands_two_pieces.png",
           f"P1f-2a: TWO island pieces — north +{BUF_NORTH_KM:g} km, "
           f"south +{BUF_SOUTH_KM:g} km\n"
           f"(north: {ncomp_n} comp, south: {ncomp_s} comp)",
           [(a_north, "#c0392b"), (a_south, "#1e8449")], sea, dem)

    # 2b: one piece, convex hull of all eight + 10 km
    m_all = m_north | m_south
    h = hull_mask(m_all, sea.shape)
    b = buffered(h, BUF_HULL_KM)
    print(f"2b hull+{BUF_HULL_KM:g} km: {area(b):.0f} km2; "
          f"touches mainland: {(b & mainland).any()}")
    render("p1f_islands_one_piece.png",
           f"P1f-2b: ONE island piece — convex hull of all eight "
           f"+{BUF_HULL_KM:g} km\n(area {area(b):.0f} km2)",
           [(b, "#2471a3")], sea, dem)


if __name__ == "__main__":
    main()
