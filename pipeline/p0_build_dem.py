# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "pyshp",
#   "requests",
#   "scipy",
# ]
# ///
"""P0: fetch source data and build the project heightfield.

Outputs (data/ is gitignored cache; out/ holds small committed artifacts):
  data/tiles/...                        terrarium DEM tiles (cache)
  data/dem_ca_albers_250m.npy           heightfield, float32 meters, EPSG:3310
  data/dem_meta.json                    grid georeferencing
  data/cgs_geomorphic_provinces.geojson CGS Note 36 provinces (for P1)
  data/ne_borders/                      Natural Earth border lines
  out/p0_map_area_relief.png            check-in: shaded relief + borders
"""

import io
import json
import math
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"

# ---- map area (WGS84 lon/lat) --------------------------------------------
# Matches "map area.jpg": S. Oregon to N. Baja, coast to just past Las Vegas,
# clipping corners of Idaho/Utah/Arizona.
LON_MIN, LON_MAX = -125.5, -113.0
LAT_MIN, LAT_MAX = 31.0, 43.5

ZOOM = 9            # terrarium zoom: ~230 m/px at these latitudes
RES = 250.0         # target heightfield resolution, meters (EPSG:3310)
CRS = "EPSG:3310"   # California Albers, meters

TILE_URL = "https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png"
CGS_URL = ("https://gis.conservation.ca.gov/server/rest/services/CGS/GeoGems/"
           "MapServer/2/query")
NE_URLS = [
    "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_1_states_provinces_lines.zip",
    "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_boundary_lines_land.zip",
]


# ---- web mercator tile math ----------------------------------------------
def lonlat_to_global_px(lon, lat, zoom):
    n = 256 * (2 ** zoom)
    x = (lon + 180.0) / 360.0 * n
    lat_r = np.radians(lat)
    y = (1.0 - np.arcsinh(np.tan(lat_r)) / math.pi) / 2.0 * n
    return x, y


def fetch_tiles():
    x0f, y0f = lonlat_to_global_px(LON_MIN, LAT_MAX, ZOOM)
    x1f, y1f = lonlat_to_global_px(LON_MAX, LAT_MIN, ZOOM)
    tx0, ty0 = int(x0f // 256), int(y0f // 256)
    tx1, ty1 = int(x1f // 256), int(y1f // 256)
    tiles = [(x, y) for y in range(ty0, ty1 + 1) for x in range(tx0, tx1 + 1)]
    print(f"tiles: x {tx0}..{tx1}, y {ty0}..{ty1} -> {len(tiles)} tiles @ z{ZOOM}")

    tdir = DATA / "tiles" / str(ZOOM)
    sess = requests.Session()

    def get(xy):
        x, y = xy
        p = tdir / str(x) / f"{y}.png"
        if p.exists() and p.stat().st_size > 0:
            return 0
        p.parent.mkdir(parents=True, exist_ok=True)
        r = sess.get(TILE_URL.format(z=ZOOM, x=x, y=y), timeout=60)
        r.raise_for_status()
        p.write_bytes(r.content)
        return 1

    with ThreadPoolExecutor(max_workers=8) as ex:
        fetched = sum(ex.map(get, tiles))
    print(f"downloaded {fetched} new tiles ({len(tiles) - fetched} cached)")

    # mosaic (rows = y, cols = x), decode terrarium: elev = R*256+G+B/256-32768
    w, h = (tx1 - tx0 + 1) * 256, (ty1 - ty0 + 1) * 256
    mosaic = np.empty((h, w), dtype=np.float32)
    for x, y in tiles:
        rgb = np.asarray(
            Image.open(tdir / str(x) / f"{y}.png").convert("RGB"), dtype=np.float32
        )
        elev = rgb[:, :, 0] * 256.0 + rgb[:, :, 1] + rgb[:, :, 2] / 256.0 - 32768.0
        mosaic[(y - ty0) * 256:(y - ty0 + 1) * 256,
               (x - tx0) * 256:(x - tx0 + 1) * 256] = elev
    return mosaic, tx0 * 256, ty0 * 256  # mosaic + its global-pixel origin


def build_heightfield(mosaic, ox, oy):
    to_ll = Transformer.from_crs(CRS, "EPSG:4326", always_xy=True)
    to_alb = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)

    # target bounds: densified bbox edges -> albers extent
    e = np.linspace(0, 1, 200)
    edge_lon = np.concatenate([
        LON_MIN + (LON_MAX - LON_MIN) * e, np.full(200, LON_MAX),
        LON_MAX - (LON_MAX - LON_MIN) * e, np.full(200, LON_MIN)])
    edge_lat = np.concatenate([
        np.full(200, LAT_MAX), LAT_MAX - (LAT_MAX - LAT_MIN) * e,
        np.full(200, LAT_MIN), LAT_MIN + (LAT_MAX - LAT_MIN) * e])
    ax, ay = to_alb.transform(edge_lon, edge_lat)
    x_min, x_max = ax.min(), ax.max()
    y_min, y_max = ay.min(), ay.max()
    width = int(math.ceil((x_max - x_min) / RES))
    height = int(math.ceil((y_max - y_min) / RES))
    print(f"heightfield: {width} x {height} px @ {RES} m "
          f"({(x_max-x_min)/1000:.0f} x {(y_max-y_min)/1000:.0f} km)")

    dem = np.empty((height, width), dtype=np.float32)
    xs = x_min + (np.arange(width) + 0.5) * RES
    for r0 in range(0, height, 512):
        r1 = min(r0 + 512, height)
        ys = y_max - (np.arange(r0, r1) + 0.5) * RES
        gx, gy = np.meshgrid(xs, ys)
        lon, lat = to_ll.transform(gx, gy)
        px, py = lonlat_to_global_px(lon, lat, ZOOM)
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

    np.save(DATA / "dem_ca_albers_250m.npy", dem)
    meta = dict(crs=CRS, x_min=float(x_min), y_max=float(y_max), res=RES,
                width=width, height=height,
                lon_range=[LON_MIN, LON_MAX], lat_range=[LAT_MIN, LAT_MAX],
                source=f"AWS terrain tiles (terrarium) z{ZOOM}")
    (DATA / "dem_meta.json").write_text(json.dumps(meta, indent=2))
    return dem, meta


def fetch_cgs():
    out = DATA / "cgs_geomorphic_provinces.geojson"
    if not out.exists():
        r = requests.get(CGS_URL, params=dict(
            where="1=1", outFields="*", outSR=4326, f="geojson"), timeout=120)
        r.raise_for_status()
        out.write_bytes(r.content)
    gj = json.loads(out.read_text())
    names = sorted({f["properties"].get("RANGE_NAME", "?")
                    for f in gj["features"]})
    print(f"CGS provinces: {len(gj['features'])} features")
    for n in names:
        print(f"  - {n}")
    return gj


def fetch_ne_borders():
    bdir = DATA / "ne_borders"
    bdir.mkdir(parents=True, exist_ok=True)
    for url in NE_URLS:
        name = url.rsplit("/", 1)[-1].removesuffix(".zip")
        if any(bdir.glob(name + ".shp")):
            continue
        r = requests.get(url, timeout=120)
        r.raise_for_status()
        zipfile.ZipFile(io.BytesIO(r.content)).extractall(bdir)
        print(f"fetched {name}")
    return bdir


def ocean_mask(dem):
    """Cells at/below sea level connected to the open Pacific (keeps Death
    Valley and the Salton Trough, which are below sea level but inland)."""
    low = dem <= 0
    lab, _ = ndimage.label(low)
    seed = lab[dem.shape[0] // 2, 5]  # a point surely in the Pacific
    return lab == seed


def render_preview(dem, meta, bdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    import shapefile as shp

    to_alb = Transformer.from_crs("EPSG:4326", CRS, always_xy=True)
    sea = ocean_mask(dem)
    land = np.where(sea, 0.0, dem)

    ls = LightSource(azdeg=315, altdeg=45)
    rgb = ls.shade(land, cmap=plt.cm.gist_earth, blend_mode="soft",
                   vert_exag=15, dx=meta["res"], dy=meta["res"],
                   vmin=-100, vmax=4400)
    rgb[sea] = (0.55, 0.67, 0.80, 1.0)

    x_min, y_max, res = meta["x_min"], meta["y_max"], meta["res"]
    extent_km = [x_min / 1000, (x_min + meta["width"] * res) / 1000,
                 (y_max - meta["height"] * res) / 1000, y_max / 1000]

    fig, axp = plt.subplots(figsize=(11, 13), dpi=200)
    axp.imshow(rgb, extent=extent_km, interpolation="bilinear")

    for shpname, style in [
        ("ne_10m_admin_1_states_provinces_lines", dict(lw=0.7, color="k", alpha=0.7)),
        ("ne_10m_admin_0_boundary_lines_land", dict(lw=1.4, color="k", alpha=0.9)),
    ]:
        for rec in shp.Reader(str(bdir / shpname)).shapes():
            pts = np.asarray(rec.points)
            parts = list(rec.parts) + [len(pts)]
            for a, b in zip(parts, parts[1:]):
                seg = pts[a:b]
                if seg[:, 0].max() < LON_MIN - 1 or seg[:, 0].min() > LON_MAX + 1:
                    continue
                if seg[:, 1].max() < LAT_MIN - 1 or seg[:, 1].min() > LAT_MAX + 1:
                    continue
                sx, sy = to_alb.transform(seg[:, 0], seg[:, 1])
                axp.plot(np.asarray(sx) / 1000, np.asarray(sy) / 1000, **style)

    cities = [("San Francisco", -122.42, 37.77), ("Sacramento", -121.49, 38.58),
              ("Los Angeles", -118.24, 34.05), ("San Diego", -117.16, 32.72),
              ("Las Vegas", -115.14, 36.17), ("Reno", -119.81, 39.53),
              ("Medford", -122.87, 42.33), ("Ensenada", -116.62, 31.87)]
    for name, lo, la in cities:
        cx, cy = to_alb.transform(lo, la)
        axp.plot(cx / 1000, cy / 1000, "o", ms=4, mfc="w", mec="k", mew=0.8)
        axp.annotate(name, (cx / 1000, cy / 1000), textcoords="offset points",
                     xytext=(5, 4), fontsize=8,
                     path_effects=None, color="k")

    km_w = meta["width"] * res / 1000
    km_h = meta["height"] * res / 1000
    axp.set_title(
        f"P0 check-in: map area — {km_w:.0f} x {km_h:.0f} km, {CRS}\n"
        f"at 1000 mm tall: 1:{km_h*1e6/1000:,.0f}; "
        f"at 256 mm tall: 1:{km_h*1e6/256:,.0f}", fontsize=11)
    axp.set_xlabel("km (CA Albers)")
    axp.set_ylabel("km")
    axp.set_xlim(extent_km[0], extent_km[1])
    axp.set_ylim(extent_km[2], extent_km[3])
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p0_map_area_relief.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p0_map_area_relief.png'}")


def main():
    DATA.mkdir(exist_ok=True)
    mosaic, ox, oy = fetch_tiles()
    dem, meta = build_heightfield(mosaic, ox, oy)
    land = dem[~ocean_mask(dem)]
    print(f"elevation range on land: {land.min():.0f} .. {land.max():.0f} m")
    fetch_cgs()
    bdir = fetch_ne_borders()
    render_preview(dem, meta, bdir)


if __name__ == "__main__":
    main()
