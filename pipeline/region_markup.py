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
"""Region MARKUP canvas: terrain contours + the CURRENT region lines,
georeferenced exactly, for ahl to draw a new boundary on.

Feeds the established markup loop (see NOTES "ahl's markup loop"): he
draws on the render, the marks get extracted to overrides/*.geojson in
EPSG:3310, and p1_regions.build_regions applies them -- so a boundary
can be moved surgically, without re-deriving the whole state's regions
from a global knob.

The point of this particular canvas (ahl 2026-09-15, deciding whether to
move the coast<->mountains line near SF Bay) is that you cannot judge a
region boundary without seeing the LANDFORM under it: the coastal band
rule puts a line 13.5 km inland from the water regardless of terrain, so
whether that line is in the right place depends on where the ridges
actually are. Hence contours under the region lines, in one image.

The mm<->ground mapping is EXACT and printed by the build: the axes fill
the figure edge to edge (no tight-bbox crop) over the window's EPSG:3310
extent, so a mark at pixel (px, py) in a W x H image is

    x_albers = X0 + px * (X1 - X0) / W
    y_albers = Y1 - py * (Y1 - Y0) / H

Usage:  uv run pipeline/region_markup.py [west south east north]
        (lon/lat degrees; defaults to the SF Bay window)
Output: out/region_markup.png  + a .json sidecar with the exact extent
"""

import json
import sys
from pathlib import Path

import numpy as np
from pyproj import Transformer
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import p4_bay_coupon as p4

DEFAULT_LL = (-123.15, 37.05, -121.35, 38.65)   # SF Bay + Coast Ranges
PX_PER_KM = 26.0          # render resolution
MINOR_M = 100             # thin contour interval (m)
MAJOR_M = 400             # heavy, labelled contour interval (m)
HILLSHADE = 0.45          # how strongly relief shades the fills (0 = off)

REGION_FILL = {base.COAST: (0.99, 0.95, 0.62),
               base.MOUNTAINS: (0.95, 0.72, 0.92),
               base.VALLEY: (0.72, 0.92, 0.72),
               base.DESERT: (0.98, 0.86, 0.68)}
REGION_LINE = {base.COAST: "#b8960b", base.MOUNTAINS: "#8e1f7d",
               base.VALLEY: "#1d7a1d", base.DESERT: "#a2651b"}
REGION_NAME = {base.COAST: "coast", base.MOUNTAINS: "mountains",
               base.VALLEY: "valley", base.DESERT: "desert"}


def main():
    ll = ([float(v) for v in sys.argv[1:5]] if len(sys.argv) >= 5
          else list(DEFAULT_LL))
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    reg, _ = p4.load_regions(dem)
    land = p4.land_authority()
    res = base.META["res"]

    tr = Transformer.from_crs("EPSG:4326", "EPSG:3310", always_xy=True)
    x0, y0 = tr.transform(ll[0], ll[1])
    x1, y1 = tr.transform(ll[2], ll[3])
    c0 = int((x0 - base.META["x_min"]) / res)
    c1 = int((x1 - base.META["x_min"]) / res)
    r0 = int((base.META["y_max"] - y1) / res)
    r1 = int((base.META["y_max"] - y0) / res)
    sl = (slice(r0, r1), slice(c0, c1))
    R, L, D = reg[sl], land[sl], dem[sl].astype(float)

    # exact extent of the cropped raster, in EPSG:3310 metres
    X0 = base.META["x_min"] + c0 * res
    X1 = base.META["x_min"] + c1 * res
    Y1 = base.META["y_max"] - r0 * res
    Y0 = base.META["y_max"] - r1 * res
    w_km, h_km = (X1 - X0) / 1000.0, (Y1 - Y0) / 1000.0

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    W = int(round(w_km * PX_PER_KM))
    H = int(round(h_km * PX_PER_KM))
    fig = plt.figure(figsize=(W / 100.0, H / 100.0), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(X0, X1)
    ax.set_ylim(Y0, Y1)
    ax.set_aspect("equal")
    ax.axis("off")
    ext = (X0, X1, Y0, Y1)

    # --- pale region fills, so the contours stay readable on top
    rgb = np.zeros(R.shape + (3,))
    rgb[...] = (0.80, 0.88, 0.95)                 # water
    for rid, col in REGION_FILL.items():
        rgb[(R == rid) & L] = col
    rgb[(R == 0) & L] = (0.86, 0.86, 0.84)        # land, region assigned
                                                  # later by nearest-fill
    # HILLSHADE the fills: the question this canvas answers is "is the
    # boundary on the right landform", and flat colour + sparse contours
    # is not enough to see a ridge. Standard NW-lit shaded relief.
    if HILLSHADE > 0:
        zf = 4.0
        dy, dx = np.gradient(ndimage.gaussian_filter(D, 1.0), res, res)
        slope = np.arctan(zf * np.hypot(dx, dy))
        aspect = np.arctan2(-dx, dy)
        az, alt = np.radians(315.0), np.radians(45.0)
        sh = (np.sin(alt) * np.cos(slope)
              + np.cos(alt) * np.sin(slope) * np.cos(az - aspect))
        sh = np.clip(sh, 0, 1)
        # shade DOWNWARD only: factor runs (1-HILLSHADE)..1, so a lit
        # slope keeps the flat region colour and a shadowed one darkens.
        # (Blending upward as well blew the pale fills out to white and
        # lost the colour identity the canvas depends on.) Water is left
        # unshaded so the shoreline stays a clean edge.
        fac = np.where(L, (1 - HILLSHADE) + HILLSHADE * sh, 1.0)
        rgb = np.clip(rgb * fac[..., None], 0, 1)
    ax.imshow(rgb, extent=ext, origin="upper", interpolation="nearest")

    # --- terrain contours
    Xc = np.linspace(X0 + res / 2, X1 - res / 2, R.shape[1])
    Yc = np.linspace(Y1 - res / 2, Y0 + res / 2, R.shape[0])
    Dm = np.where(L, D, np.nan)                   # no contours over water
    Ds = ndimage.gaussian_filter(np.nan_to_num(Dm, nan=0.0), 1.0)
    Ds = np.where(L, Ds, np.nan)
    hi = int(np.nanmax(Ds) // MINOR_M + 1) * MINOR_M
    ax.contour(Xc, Yc, Ds, levels=np.arange(MINOR_M, hi, MINOR_M),
               colors="#33291f", linewidths=0.55, alpha=0.9)
    cs = ax.contour(Xc, Yc, Ds, levels=np.arange(MAJOR_M, hi, MAJOR_M),
                    colors="#241c14", linewidths=1.3)
    ax.clabel(cs, fmt="%d m", fontsize=9, inline=True)

    # --- CURRENT region boundaries, one bold line per region
    for rid, col in REGION_LINE.items():
        m = ((R == rid) & L).astype(float)
        if m.sum() == 0:
            continue
        ax.contour(Xc, Yc, ndimage.gaussian_filter(m, 0.6), levels=[0.5],
                   colors=col, linewidths=2.2)
    # shoreline
    ax.contour(Xc, Yc, L.astype(float), levels=[0.5], colors="#1f5fa8",
               linewidths=1.4)

    # --- 10 km grid, labelled in EPSG:3310 km
    for gx in np.arange(np.ceil(X0 / 10000) * 10000, X1, 10000):
        ax.axvline(gx, color="#000000", lw=0.4, alpha=0.25)
        ax.annotate(f"{gx/1000:.0f}", (gx, Y0), fontsize=6, color="#222",
                    ha="center", va="bottom")
    for gy in np.arange(np.ceil(Y0 / 10000) * 10000, Y1, 10000):
        ax.axhline(gy, color="#000000", lw=0.4, alpha=0.25)
        ax.annotate(f"{gy/1000:.0f}", (X0, gy), fontsize=6, color="#222",
                    ha="left", va="center")

    out = p4.OUT / "region_markup.png"
    fig.savefig(out, dpi=100, facecolor="white")
    plt.close(fig)

    meta = {"crs": "EPSG:3310", "x0": X0, "x1": X1, "y0": Y0, "y1": Y1,
            "width_px": W, "height_px": H, "lonlat_window": ll,
            "px_to_albers": "x = x0 + px*(x1-x0)/W ; y = y1 - py*(y1-y0)/H"}
    (p4.OUT / "region_markup.json").write_text(json.dumps(meta, indent=2))

    km2 = (res / 1000.0) ** 2
    print(f"region markup canvas -> {out}")
    print(f"  window lon/lat {ll}, EPSG:3310 x[{X0:.0f},{X1:.0f}] "
          f"y[{Y0:.0f},{Y1:.0f}] m  ({w_km:.0f} x {h_km:.0f} km)")
    print(f"  {W} x {H} px at {PX_PER_KM:g} px/km -- extent + the exact "
          f"pixel->Albers formula are in {p4.OUT / 'region_markup.json'}")
    print(f"  contours: thin every {MINOR_M} m, heavy/labelled every "
          f"{MAJOR_M} m, none over water")
    print("  region lines (current):")
    for rid, col in REGION_LINE.items():
        a = ((R == rid) & L).sum() * km2
        if a:
            print(f"    {REGION_NAME[rid]:10s} {col}  {a:7,.0f} km^2")
    unl = ((R == 0) & L).sum() * km2
    if unl:
        print(f"    (gray fill: {unl:,.0f} km^2 of land with no region yet "
              "-- the build assigns it to the nearest region, so it is NOT "
              "a hole)")
    print("\n  mark a new boundary on it and hand it back; marks get "
          "extracted to overrides/*.geojson (EPSG:3310) and applied by "
          "build_regions -- no global knob is touched.")


if __name__ == "__main__":
    main()
