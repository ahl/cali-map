"""dem_hires.py: on-demand higher-resolution DEM fetch for inset prints.

The statewide heightfield (data/dem_ca_albers_250m.npy, P0) is built from
zoom-9 terrarium tiles at 250 m/px -- fine for the full-state print but too
coarse for a 1:1,000,000 zoomed-in inset (0.2mm/px there is ~200m ground,
close to the 230m/px the zoom-9 source tiles actually carry). This module
reuses P0's exact approach (pipeline/p0_build_dem.py: tile math, terrarium
decode, bilinear resample onto an Albers grid, 5x5 median despike >200m)
but parameterized by zoom, an arbitrary Albers (EPSG:3310) bounding box,
and output resolution, so an inset driver can fetch a small hi-res patch
on demand instead of slicing the coarse statewide array.

Tiles are cached under data/tiles/{zoom}/{x}/{y}.png -- same cache layout
P0 uses for its zoom-9 tiles, so a different zoom just lands in a sibling
subdirectory (no collision, no interference with P0's cache).

URL: https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png
"""

import math
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
MAX_TILES = 600  # safety cap; abort rather than download something huge

CRS = "EPSG:3310"  # California Albers, meters -- the only CRS this module
                    # supports for the output grid (matches P0/P1/P1.5)
TO_LL = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)


def lonlat_to_global_px(lon, lat, zoom):
    """Web-Mercator global pixel coords at a given zoom (same formula as
    p0_build_dem.py)."""
    n = 256 * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    lat_r = np.radians(lat)
    y = (1.0 - np.arcsinh(np.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def _bbox_ll_coverage(x_min, x_max, y_min, y_max, pad_deg=0.02):
    """lon/lat bounds covering an Albers bbox. Albers rectangles are not
    lon/lat rectangles, so densify the edges and take the envelope (same
    trick as p0_build_dem.rect_ll_coverage, just starting from a bbox
    instead of a lon/lat box)."""
    e = np.linspace(0, 1, 200)
    bx = np.concatenate([
        x_min + (x_max - x_min) * e, np.full_like(e, x_max),
        x_max - (x_max - x_min) * e, np.full_like(e, x_min)])
    by = np.concatenate([
        np.full_like(e, y_max), y_max - (y_max - y_min) * e,
        np.full_like(e, y_min), y_min + (y_max - y_min) * e])
    lon, lat = TO_LL.transform(bx, by)
    return (lon.min() - pad_deg, lon.max() + pad_deg,
            lat.min() - pad_deg, lat.max() + pad_deg)


def _fetch_tiles(lon0, lon1, lat0, lat1, zoom):
    """Download (or reuse cached) terrarium tiles covering the lon/lat
    box, and mosaic them into one decoded-elevation array. Returns
    (mosaic, ox, oy, n_tiles) where (ox, oy) is the mosaic's origin in
    zoom-`zoom` global pixel coords."""
    x0f, y0f = lonlat_to_global_px(lon0, lat1, zoom)
    x1f, y1f = lonlat_to_global_px(lon1, lat0, zoom)
    tx0, ty0 = int(x0f // 256), int(y0f // 256)
    tx1, ty1 = int(x1f // 256), int(y1f // 256)
    tiles = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    print(f"dem_hires: tiles x {tx0}..{tx1}, y {ty0}..{ty1} "
          f"-> {len(tiles)} tiles @ z{zoom}")
    if len(tiles) > MAX_TILES:
        raise RuntimeError(
            f"dem_hires: {len(tiles)} tiles requested at zoom {zoom} "
            f"exceeds safety cap of {MAX_TILES} -- aborting before "
            "downloading anything; shrink the bbox or lower zoom")

    tdir = DATA / "tiles" / str(zoom)
    sess = requests.Session()

    def get(xy):
        x, y = xy
        p = tdir / str(x) / f"{y}.png"
        if p.exists() and p.stat().st_size > 0:
            return 0
        p.parent.mkdir(parents=True, exist_ok=True)
        r = sess.get(TILE_URL.format(z=zoom, x=x, y=y), timeout=60)
        r.raise_for_status()
        p.write_bytes(r.content)
        return 1

    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = sum(ex.map(get, tiles))
    print(f"dem_hires: downloaded {fetched} new tiles "
          f"({len(tiles) - fetched} cached)")

    w, h = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    mosaic = np.empty((h, w), dtype=np.float32)
    for x, y in tiles:
        rgb = np.asarray(
            Image.open(tdir / str(x) / f"{y}.png").convert("RGB"),
            dtype=np.float32)
        elev = rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0
        mosaic[(y - ty0) * 256:(y - ty0 + 1) * 256,
               (x - tx0) * 256:(x - tx0 + 1) * 256] = elev
    return mosaic, tx0 * 256, ty0 * 256, len(tiles)


def _resample_to_albers(mosaic, ox, oy, x_min, x_max, y_min, y_max,
                         out_res_m, zoom):
    """Bilinear-resample the tile mosaic onto an Albers grid, row 0 =
    north (matches dem_ca_albers_250m.npy's convention), then despike."""
    width = int(round((x_max - x_min) / out_res_m))
    height = int(round((y_max - y_min) / out_res_m))
    xs = x_min + (np.arange(width) + 0.5) * out_res_m
    dem = np.empty((height, width), dtype=np.float32)
    for r0 in range(0, height, 512):
        r1 = min(r0 + 512, height)
        ys = y_max - (np.arange(r0, r1) + 0.5) * out_res_m
        gx, gy = np.meshgrid(xs, ys)
        lon, lat = TO_LL.transform(gx, gy)
        px, py = lonlat_to_global_px(lon, lat, zoom)
        px, py = px - ox, py - oy
        x0 = np.clip(np.floor(px - 0.5).astype(int), 0, mosaic.shape[1] - 2)
        y0 = np.clip(np.floor(py - 0.5).astype(int), 0, mosaic.shape[0] - 2)
        fx = np.clip(px - 0.5 - x0, 0, 1)
        fy = np.clip(py - 0.5 - y0, 0, 1)
        dem[r0:r1] = (
            mosaic[y0, x0] * (1 - fx) * (1 - fy)
            + mosaic[y0, x0 + 1] * fx * (1 - fy)
            + mosaic[y0 + 1, x0] * (1 - fx) * fy
            + mosaic[y0 + 1, x0 + 1] * fx * fy
        )
    med = ndimage.median_filter(dem, size=5)
    spikes = np.abs(dem - med) > 200.0
    n_spikes = int(spikes.sum())
    if n_spikes:
        dem[spikes] = med[spikes]
    return dem, width, height, n_spikes


def fetch_hires_dem(x_min, x_max, y_min, y_max, zoom, out_res_m):
    """Fetch AWS terrarium tiles at `zoom` covering the Albers (EPSG:3310)
    bbox [x_min, x_max] x [y_min, y_max] (meters), and resample onto an
    Albers grid at `out_res_m` meters/px, row 0 = north.

    Returns (dem, meta, n_tiles):
      dem   float32 (H, W) array, meters, row 0 = north (matches P0).
      meta  dict(crs, x_min, y_max, res, width, height, zoom).
      n_tiles  number of tiles the bbox required (for reporting).

    Raises RuntimeError before downloading anything if the bbox would
    need more than MAX_TILES tiles at this zoom.
    """
    lon0, lon1, lat0, lat1 = _bbox_ll_coverage(x_min, x_max, y_min, y_max)
    mosaic, ox, oy, n_tiles = _fetch_tiles(lon0, lon1, lat0, lat1, zoom)
    dem, width, height, n_spikes = _resample_to_albers(
        mosaic, ox, oy, x_min, x_max, y_min, y_max, out_res_m, zoom)
    print(f"dem_hires: heightfield {width} x {height} px @ {out_res_m:.1f} m "
          f"(despiked {n_spikes} cells)")
    meta = dict(crs=CRS, x_min=float(x_min), y_max=float(y_max),
                res=float(out_res_m), width=width, height=height, zoom=zoom)
    return dem, meta, n_tiles
