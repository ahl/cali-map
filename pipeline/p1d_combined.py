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
"""P1d: ahl's picked combination (2026-09-13):
  - Coast  = RAW warped pink strip from the curriculum map (p1b's left
             panel), i.e. no opening/closing beyond a pinhole-close —
             only clipped by CA land and by valley/desert precedence
  - Valley = CGS Great Valley, Desert = CGS desert provinces, with the
             desert_north_limit_km rule (northern Basin & Range ->
             Mountains)
  - Mountains = rest of CA

Outputs:
  data/p1d_coast_mask.npy   boolean coast mask
  data/p1d_regions.npy      uint8 region raster (SEA/MOUNTAINS/... ids)
  out/p1d_combined.png      single-panel render
"""

import sys
from pathlib import Path

import numpy as np
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1b_coast_from_image as b

# only cosmetic hole-sealing on the raw strip (warp jaggies), in km
PINHOLE_CLOSE_KM = 1.0


def main():
    dem = np.load(b.DATA / "dem_ca_albers_250m.npy")
    prov, name_id = b.rasterize_provinces()
    sea = b.ocean_mask(dem)

    land_lab, _ = ndimage.label(~sea)
    mainland = land_lab == np.argmax(np.bincount(land_lab[~sea].ravel()))
    islands = b.ca_islands(sea, mainland)
    ca_main = (prov > 0) & ~sea & mainland
    ca = ca_main | islands
    valley = np.isin(prov, [name_id[n] for n in b.CFG["valley_provinces"]]) & ca
    desert = np.isin(prov, [name_id[n] for n in b.CFG["desert_provinces"]]) & ca

    # northern Basin and Range counts as Mountains, not Desert
    lim = b.CFG.get("desert_north_limit_km")
    if lim is not None:
        r_cut = int((b.META["y_max"] - lim * 1000.0) / b.META["res"])
        if r_cut > 0:
            desert[:min(r_cut, desert.shape[0])] = False

    cls, sil = b.classify_image()
    ds = 8
    A, t, iou = b.fit_transform(cls, sil, ca_main[::ds, ::ds], ds)
    print(f"registration IoU = {iou:.4f}")

    h, w = b.grid_shape()
    cls_map = np.zeros((h, w), np.uint8)
    cols = b.META["x_min"] + (np.arange(w) + 0.5) * b.META["res"]
    for r0 in range(0, h, 512):
        r1 = min(r0 + 512, h)
        ys = b.META["y_max"] - (np.arange(r0, r1) + 0.5)[:, None] * b.META["res"]
        cls_map[r0:r1] = b.warp_classes(cls, A, t, cols[None, :], ys)

    # RAW coast: warped pink + one-source-pixel shore ribbon, clipped only
    # by precedence and CA land; tiny closing seals warp pinholes.
    px_m = np.sqrt(abs(np.linalg.det(A)))
    shore_dist = ndimage.distance_transform_edt(~sea) * b.META["res"]
    allowed = ca & mainland & ~valley & ~desert
    coast = ((cls_map == b.COAST) | (shore_dist <= px_m)) & allowed
    r = PINHOLE_CLOSE_KM * 1000 / b.META["res"]
    coast = b.disk_close(coast | sea, r) & allowed & ~sea

    # the physical piece connects through the printed ocean shelf (D2), so
    # keep every component touching the shore; drop only inland strays
    lab, n = ndimage.label(coast)
    near_shore = ndimage.binary_dilation(sea, iterations=2)
    keep = np.unique(lab[near_shore & coast])
    keep = keep[keep > 0]
    dropped = coast.sum() - np.isin(lab, keep).sum()
    if dropped:
        print(f"dropping {n - len(keep)} inland stray blob(s), "
              f"{dropped * b.META['res']**2 / 1e6:.0f} km2")
    coast = np.isin(lab, keep)
    ncomp = len(keep)
    print(f"{ncomp} shore-connected components (join via ocean shelf)")
    coast = coast | islands

    np.save(b.DATA / "p1d_coast_mask.npy", coast)

    reg = np.zeros(dem.shape, dtype=np.uint8)
    reg[ca] = b.MOUNTAINS
    reg[valley] = b.VALLEY
    reg[desert] = b.DESERT
    reg[coast] = b.COAST
    np.save(b.DATA / "p1d_regions.npy", reg)

    pct = 100 * (reg == b.COAST).sum() / (reg > 0).sum()
    print(f"coast = {pct:.1f}% of CA; mainland components: {ncomp}")

    # single-panel render, project style
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land, vert_exag=12, dx=b.META["res"], dy=b.META["res"])
    x0k, x1k, y0k, y1k = -420, 560, -660, 470
    xm, ym = b.META["x_min"] / 1000, b.META["y_max"] / 1000
    res_k = b.META["res"] / 1000
    c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
    r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
    ss = 3
    sh = shade[r0:r1:ss, c0:c1:ss]
    se = sea[r0:r1:ss, c0:c1:ss]
    rg = reg[r0:r1:ss, c0:c1:ss]
    rgb = np.dstack([sh, sh, sh]) * 0.55 + 0.45
    for rid, col in b.COLORS.items():
        m = rg == rid
        for ch in range(3):
            rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.45 + col[ch] * 0.55
    rgb[se] = (0.70, 0.79, 0.87)

    fig, ax = plt.subplots(figsize=(10.5, 13), dpi=150)
    ax.imshow(rgb, extent=[x0k, x1k, y0k, y1k])
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_title("P1d: curriculum-map coast (raw) + CGS valley/desert, "
                 f"desert capped at +{lim:g} km\n"
                 f"coast = {pct:.0f}% of CA, {ncomp} mainland component, "
                 f"registration IoU {iou:.3f}", fontsize=12)
    b.OUT.mkdir(exist_ok=True)
    fig.savefig(b.OUT / "p1d_combined.png", bbox_inches="tight")
    print(f"wrote {b.OUT / 'p1d_combined.png'}")


if __name__ == "__main__":
    main()
