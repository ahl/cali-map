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
"""P1b: transplant the Coastal Region from the scanned curriculum map
("cali regions 2.png", the map ahl's region scheme comes from) onto our
DEM grid as a candidate Coast mask — an alternative to the elevation-
threshold candidates of p1_regions.py.

Steps:
  1. classify image pixels by color (reference colors sampled from the
     legend swatches); the largest connected component of the four
     region classes is the California silhouette (this automatically
     drops the legend box, UI chrome, scale bar); text-label holes are
     filled by nearest-class assignment.
  2. georeference: fit a 6-parameter affine transform image px -> EPSG:3310
     by maximizing IoU between the image silhouette and our CA mask
     (CGS provinces union) on a downsampled grid; init from centroid +
     second-moment (principal axes) matching, Nelder-Mead refinement.
     Landmark (extreme-point) init is the fallback if that stalls.
  3. warp the pink class onto the DEM grid; apply project precedence
     (Great Valley / Desert provinces win over coast); add a one-source-
     pixel shore ribbon (the scan is pink along its whole open coast, so
     this restores the strip where the scan's generalized coastline sits
     seaward of ours); light morphological smoothing (source is low-res
     => keep its smooth character); one mainland component; islands are
     always Coast.
  4. mountains = rest of CA; render QA + result.

Outputs:
  data/p1b_coast_mask.npy       boolean coast mask on the DEM grid
  out/p1b_coast_from_image.png  left: registration QA, right: 4-region map
"""

import json
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage, optimize

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"
IMG_PATH = ROOT / "cali regions 2.png"

CFG = tomllib.loads((ROOT / "config.toml").read_text())["regions"]
META = json.loads((DATA / "dem_meta.json").read_text())
TO_ALB = Transformer.from_crs("EPSG:4326", META["crs"], always_xy=True)

# region ids + palette, same as p1_regions.py
SEA, MOUNTAINS, VALLEY, DESERT, COAST = 0, 1, 2, 3, 4
COLORS = {
    MOUNTAINS: (0.85, 0.29, 0.75),  # magenta
    VALLEY: (0.36, 0.80, 0.36),     # green
    DESERT: (0.95, 0.60, 0.28),     # orange
    COAST: (0.98, 0.91, 0.28),      # yellow
}

# Legend swatch sample boxes in the scan (row0, row1, col0, col1), interior
# of each 21x13 swatch; order = legend order. Verified against the scan;
# classify_image() asserts each patch is near-uniform so a different scan
# fails loudly instead of silently misclassifying.
SWATCH_BOXES = {  # image class id: (r0, r1, c0, c1)
    MOUNTAINS: (88, 96, 265, 281),   # "Mountain Region"  blue-gray
    COAST: (108, 116, 265, 281),     # "Coastal Region"   pink/salmon
    DESERT: (128, 136, 265, 281),    # "Desert Region"    orange
    VALLEY: (148, 156, 265, 281),    # "Central Valley"   green
}
COLOR_TOL = 60  # max L1 RGB distance to a swatch color to claim a pixel


# ---------------------------------------------------------------- DEM side
# (grid helpers copied from p1_regions.py so this script is self-contained)

def grid_shape():
    return META["height"], META["width"]


def px_of(lon, lat):
    x, y = TO_ALB.transform(np.asarray(lon), np.asarray(lat))
    return ((x - META["x_min"]) / META["res"],
            (META["y_max"] - np.asarray(y)) / META["res"])


def rasterize_provinces():
    gj = json.loads((DATA / "cgs_geomorphic_provinces.geojson").read_text())
    names = sorted({f["properties"]["RANGE_NAME"] for f in gj["features"]})
    name_id = {n: i + 1 for i, n in enumerate(names)}
    h, w = grid_shape()
    img = Image.new("I", (w, h), 0)
    drw = ImageDraw.Draw(img)
    for f in gj["features"]:
        gid = name_id[f["properties"]["RANGE_NAME"]]
        geom = f["geometry"]
        polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                 else [geom["coordinates"]])
        for rings in polys:
            for i, ring in enumerate(rings):
                arr = np.asarray(ring)
                px, py = px_of(arr[:, 0], arr[:, 1])
                drw.polygon(list(zip(px.tolist(), py.tolist())),
                            fill=gid if i == 0 else 0)
    return np.asarray(img), name_id


def ocean_mask(dem):
    low = dem <= 0
    lab, _ = ndimage.label(low)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    keep = set(border[border > 0].tolist())
    keep.add(int(lab[dem.shape[0] // 2, 5]))
    return np.isin(lab, list(keep))


def ca_islands(sea, mainland):
    """US offshore islands (Channel Islands, Farallones) — always Coast."""
    to_ll = Transformer.from_crs(META["crs"], "EPSG:4326", always_xy=True)
    lab, n = ndimage.label(~sea & ~mainland)
    if n == 0:
        return np.zeros(sea.shape, bool)
    sizes = ndimage.sum_labels(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    keep = []
    for i in np.where(sizes >= 4)[0] + 1:
        cy, cx = ndimage.center_of_mass(lab == i)
        x = META["x_min"] + (cx + 0.5) * META["res"]
        y = META["y_max"] - (cy + 0.5) * META["res"]
        lon, lat = to_ll.transform(x, y)
        if lat >= CFG["island_min_lat"] and lon < -117.0:
            keep.append(i)
    return np.isin(lab, keep)


# --------------------------------------------------------------- image side

def classify_image():
    """Color-classify the scan. Returns (cls, sil): cls is 0 outside
    California / MOUNTAINS..COAST inside, sil = CA silhouette (bool)."""
    rgb = np.asarray(Image.open(IMG_PATH).convert("RGB")).astype(np.int32)

    refs = {}
    for rid, (r0, r1, c0, c1) in SWATCH_BOXES.items():
        patch = rgb[r0:r1, c0:c1].reshape(-1, 3)
        assert patch.std(axis=0).max() < 8, \
            f"legend swatch for class {rid} not uniform — wrong scan?"
        refs[rid] = np.median(patch, axis=0)

    ids = np.array(list(refs))
    dist = np.stack([np.abs(rgb - refs[i]).sum(axis=2) for i in ids])
    cls = ids[dist.argmin(axis=0)].astype(np.uint8)
    cls[dist.min(axis=0) > COLOR_TOL] = 0  # tan bg, ocean, chrome, text

    # California = largest connected component of the class union. This
    # drops the legend swatches, scale bar, UI buttons and the pink island
    # dots (islands get re-added from our own geometry later).
    lab, _ = ndimage.label(cls > 0)
    sizes = np.bincount(lab.ravel())
    sizes[0] = 0
    sil = ndimage.binary_fill_holes(lab == sizes.argmax())

    # fill text-label holes (and the filled SF Bay) with the nearest class
    _, (ir, ic) = ndimage.distance_transform_edt(cls == 0, return_indices=True)
    cls = np.where(sil, cls[ir, ic], 0).astype(np.uint8)
    return cls, sil


# ------------------------------------------------------------- registration
# Model: (x, y)_albers = A @ (u, w) + t   with u = image col, w = -row
# (row flipped so both frames are right-handed and A is near-diagonal).

def sqrtm_spd(m):
    vals, vecs = np.linalg.eigh(m)
    return (vecs * np.sqrt(vals)) @ vecs.T


def pts_of_mask(mask, flip_rows):
    r, c = np.nonzero(mask)
    return np.stack([c, -r] if flip_rows else [c, r]).astype(float)


def moment_init(P, Q):
    """Affine matching centroid + covariance (symmetric / minimal-rotation
    solution — both maps are roughly north-up, so this is the right branch)."""
    A0 = sqrtm_spd(np.cov(Q)) @ np.linalg.inv(sqrtm_spd(np.cov(P)))
    t0 = Q.mean(axis=1) - A0 @ P.mean(axis=1)
    return A0, t0


def landmark_init(sil, ca, ds):
    """Fallback: match extreme points (N, S, W tips + SE corner) of the two
    silhouettes with a least-squares affine."""
    def extremes(pts):
        x, y = pts
        return np.array([pts[:, np.argmax(y)], pts[:, np.argmin(y)],
                         pts[:, np.argmin(x)], pts[:, np.argmax(x - y)]])

    P = extremes(pts_of_mask(sil, True))
    r, c = np.nonzero(ca)
    Q = np.stack([META["x_min"] + (c * ds + 0.5) * META["res"],
                  META["y_max"] - (r * ds + 0.5) * META["res"]]).astype(float)
    Q = extremes(Q)
    M = np.hstack([P, np.ones((4, 1))])
    sol, *_ = np.linalg.lstsq(M, Q, rcond=None)
    return sol[:2].T, sol[2]


def warp_classes(cls, A, t, xs, ys):
    """Sample the image class raster at albers coords (xs, ys) [meshgrid-
    broadcastable]; returns class ids, 0 outside."""
    Ainv = np.linalg.inv(A)
    dx, dy = xs - t[0], ys - t[1]
    u = Ainv[0, 0] * dx + Ainv[0, 1] * dy
    w = Ainv[1, 0] * dx + Ainv[1, 1] * dy
    return ndimage.map_coordinates(cls, [-w, u], order=0, cval=0)


def fit_transform(cls, sil, ca_ds, ds):
    """Maximize IoU(warped silhouette, our CA mask) over a 6-param affine."""
    r, c = np.nonzero(ca_ds)
    Q = np.stack([META["x_min"] + (c * ds + 0.5) * META["res"],
                  META["y_max"] - (r * ds + 0.5) * META["res"]]).astype(float)
    A0, t0 = moment_init(pts_of_mask(sil, True), Q)

    h, w = ca_ds.shape
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float64)
    xs = META["x_min"] + (xs * ds + 0.5) * META["res"]
    ys = META["y_max"] - (ys * ds + 0.5) * META["res"]
    sil8 = sil.astype(np.uint8)
    n_ca = ca_ds.sum()

    def unpack(p, A_base, t_base):
        M = np.array([[1 + p[0], p[2]], [p[3], 1 + p[1]]])
        return A_base @ M, t_base + 1e5 * np.asarray(p[4:6])

    def neg_iou(p, A_base, t_base):
        A, t = unpack(p, A_base, t_base)
        wrp = warp_classes(sil8, A, t, xs, ys) > 0
        inter = (wrp & ca_ds).sum()
        return -inter / (n_ca + wrp.sum() - inter)

    def solve(A_base, t_base):
        p = np.zeros(6)
        for step in (0.04, 0.01):  # restart with a tighter simplex
            simplex = np.vstack([p, p + step * np.eye(6)])
            res = optimize.minimize(
                neg_iou, p, args=(A_base, t_base), method="Nelder-Mead",
                options=dict(initial_simplex=simplex, maxiter=4000,
                             xatol=1e-5, fatol=1e-6))
            p = res.x
        return unpack(p, A_base, t_base), -res.fun

    (A, t), iou = solve(A0, t0)
    if iou < 0.85:  # moment init landed in a bad basin -> landmark fallback
        print(f"moment-init fit weak (IoU {iou:.3f}); trying landmark init")
        A1, t1 = landmark_init(sil, ca_ds, ds)
        (A2, t2), iou2 = solve(A1, t1)
        if iou2 > iou:
            (A, t), iou = (A2, t2), iou2
    return A, t, iou


# ------------------------------------------------------------------ regions

# Euclidean-disk morphology via distance transforms: isotropic (a diamond
# element erodes diagonal bands ~1.4x deeper, which severed the SoCal
# shore strip) and much faster than a 17x17 footprint at this grid size.

def disk_erode(mask, r_px):
    return ndimage.distance_transform_edt(mask) > r_px


def disk_dilate(mask, r_px):
    return ndimage.distance_transform_edt(~mask) <= r_px


def disk_open(mask, r_px):
    return disk_dilate(disk_erode(mask, r_px), r_px)


def disk_close(mask, r_px):
    return disk_erode(disk_dilate(mask, r_px), r_px)


def build_coast(cls_map, ca, sea, mainland, islands, valley, desert, px_m):
    """Pink class on the map grid -> cleaned Coast mask + component count.

    px_m = source-map pixel size in meters (from the fitted affine). The
    scan's pink strip hugs the ENTIRE open coastline (verified: virtually
    every shoreline-adjacent classified pixel is pink), but its generalized
    coastline wanders a few km off ours, so the warped strip pinches to
    zero where the scan's coast sits seaward of the real one. Adding a
    one-source-pixel shore ribbon restores exactly what the scan asserts
    at its own resolution ("the shore is pink") and reconnects the strip.
    """
    allowed = ca & mainland & ~valley & ~desert
    shore_dist = ndimage.distance_transform_edt(~sea) * META["res"]
    coast = ((cls_map == COAST) | (shore_dist <= px_m)) & allowed

    # light smoothing (project-standard radius) — the scan is inherently
    # smooth at map scale, this only cleans warp jaggies. Smooth the union
    # with the sea so the ocean side is supported (never eroded): only the
    # inland border is cleaned, and shoreline connectivity is preserved.
    r = CFG["smooth_radius_km"] * 1000 / META["res"]
    if r > 0:
        u = disk_close(disk_open(coast | sea, r), r)
        coast = u & allowed & ~sea

    # one mainland component: keep the largest, drop scan-noise blobs
    lab, n = ndimage.label(coast)
    if n > 1:
        sizes = np.bincount(lab.ravel())
        sizes[0] = 0
        print(f"dropping {n - 1} stray coast blob(s) "
              f"({(sizes.sum() - sizes.max()) * META['res'] ** 2 / 1e6:.0f} km2)")
        coast = lab == sizes.argmax()
    n_after = ndimage.label(coast)[1]

    return coast | islands, n_after


# ------------------------------------------------------------------- render

def render(dem, sea, ca_all, cls_map, reg, iou, coast_pct, ncomp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land, vert_exag=12, dx=META["res"], dy=META["res"])

    # crop view to California + margin (Albers km) — same window as p1
    x0k, x1k, y0k, y1k = -420, 560, -660, 470
    xm, ym = META["x_min"] / 1000, META["y_max"] / 1000
    res_k = META["res"] / 1000
    c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
    r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
    ss = 3

    sh = shade[r0:r1:ss, c0:c1:ss]
    se = sea[r0:r1:ss, c0:c1:ss]
    base = np.dstack([sh, sh, sh]) * 0.55 + 0.45

    fig, axes = plt.subplots(1, 2, figsize=(15, 9.6), dpi=140)

    # left: registration QA — raw warped image classes + our CA outline
    rgb = base.copy()
    cm = cls_map[r0:r1:ss, c0:c1:ss]
    for rid, col in COLORS.items():
        m = cm == rid
        for ch in range(3):
            rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.45 + col[ch] * 0.55
    rgb[se] = (0.70, 0.79, 0.87)
    axes[0].imshow(rgb, extent=[x0k, x1k, y0k, y1k])
    ext = ca_all[r0:r1:ss, c0:c1:ss].astype(float)
    axes[0].contour(ext, levels=[0.5], colors="black", linewidths=0.7,
                    extent=[x0k, x1k, y1k, y0k])
    axes[0].set_title(f"registration QA: warped image classes vs our CA "
                      f"outline (black)\nsilhouette IoU = {iou:.3f}",
                      fontsize=13)

    # right: final regions with the image-derived coast
    rgb = base.copy()
    rg = reg[r0:r1:ss, c0:c1:ss]
    for rid, col in COLORS.items():
        m = rg == rid
        for ch in range(3):
            rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.45 + col[ch] * 0.55
    rgb[se] = (0.70, 0.79, 0.87)
    axes[1].imshow(rgb, extent=[x0k, x1k, y0k, y1k])
    axes[1].set_title(f"image-derived coast  (coast = {coast_pct:.0f}% of CA, "
                      f"{ncomp} mainland component)", fontsize=13)

    for ax in axes:
        ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle("P1b: Coast transplanted from the curriculum map "
                 "(yellow=Coast, magenta=Mountains, green=Valley, "
                 "orange=Desert)", fontsize=14, y=0.99)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p1b_coast_from_image.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p1b_coast_from_image.png'}")


# --------------------------------------------------------------------- main

def main():
    dem = np.load(DATA / "dem_ca_albers_250m.npy")
    prov, name_id = rasterize_provinces()
    sea = ocean_mask(dem)

    land_lab, _ = ndimage.label(~sea)
    mainland = land_lab == np.argmax(np.bincount(land_lab[~sea].ravel()))
    islands = ca_islands(sea, mainland)
    ca_main = (prov > 0) & ~sea & mainland     # mainland CA (fit target)
    ca = ca_main | islands                     # full CA
    valley = np.isin(prov, [name_id[n] for n in CFG["valley_provinces"]]) & ca
    desert = np.isin(prov, [name_id[n] for n in CFG["desert_provinces"]]) & ca

    cls, sil = classify_image()
    print(f"image classified: silhouette {sil.sum()} px, "
          f"pink {(cls == COAST).sum()} px")

    ds = 8  # fit on a 2 km grid
    A, t, iou = fit_transform(cls, sil, ca_main[::ds, ::ds], ds)
    sx, sy = np.hypot(*A[:, 0]), np.hypot(*A[:, 1])
    rot = np.degrees(np.arctan2(A[1, 0], A[0, 0]))
    print(f"registration IoU = {iou:.4f}")
    print(f"affine: A = {A.round(2).tolist()}, t = {t.round(0).tolist()}")
    print(f"  scale {sx / 1000:.3f} / {sy / 1000:.3f} km per image px, "
          f"rotation {rot:.2f} deg, "
          f"shear (col-axis angle mismatch) "
          f"{90 - np.degrees(np.arccos(A[:, 0] @ A[:, 1] / (sx * sy))):.2f} deg")

    # warp the full class raster onto the DEM grid (row chunks: memory)
    h, w = grid_shape()
    cls_map = np.zeros((h, w), np.uint8)
    cols = META["x_min"] + (np.arange(w) + 0.5) * META["res"]
    for r0 in range(0, h, 512):
        r1 = min(r0 + 512, h)
        ys = META["y_max"] - (np.arange(r0, r1) + 0.5)[:, None] * META["res"]
        cls_map[r0:r1] = warp_classes(cls, A, t, cols[None, :], ys)

    px_m = np.sqrt(abs(np.linalg.det(A)))  # source-map pixel size, meters
    coast, ncomp = build_coast(cls_map, ca, sea, mainland, islands,
                               valley, desert, px_m)
    np.save(DATA / "p1b_coast_mask.npy", coast)
    print(f"wrote {DATA / 'p1b_coast_mask.npy'}")

    reg = np.zeros(dem.shape, dtype=np.uint8)
    reg[ca] = MOUNTAINS
    reg[valley] = VALLEY
    reg[desert] = DESERT
    reg[coast] = COAST

    coast_pct = 100 * (reg == COAST).sum() / (reg > 0).sum()
    print(f"coast = {coast_pct:.1f}% of CA; mainland components: {ncomp} "
          f"{'(OK)' if ncomp == 1 else '(PROBLEM: must be 1)'}")

    render(dem, sea, ca, cls_map, reg, iou, coast_pct, ncomp)


if __name__ == "__main__":
    main()
