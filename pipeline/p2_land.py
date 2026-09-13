# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "scipy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "shapely",
#   "pyshp",
#   "requests",
# ]
# ///
"""P2 part 1: authoritative land/coastline + political borders.

Replaces the CGS-province-derived land notion (NOTES.md "P2 cleanup
contract"): the US Census cartographic boundary state polygons (1:500k)
become THE authority on what is California and what is US land; Natural
Earth 10m admin_0 countries supplies Mexico. Per project decisions the sea
stops at the Carquinez gate (config coastal_water_gate): polygon "water"
east of the gate (Suisun Bay, Delta channels) is forced to land at datum.

Outputs (all on the DEM grid, 4791 x 5632 @ 250 m, EPSG:3310):
  data/p2_land.npz        ca_mask, land_mask, border_lines (bool rasters)
  data/p2_borders.geojson state-state + US-Mexico border polylines,
                          EPSG:3310, clipped to the map rectangle
  out/p2_land_qa.png      hillshade + CA outline + borders + old-vs-new
                          coastline differences highlighted in red
"""

import io
import json
import sys
import zipfile
from pathlib import Path

import numpy as np
import requests
import shapefile  # pyshp
import shapely
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage
from shapely.geometry import box, mapping
from shapely.geometry import shape as shp_shape
from shapely.ops import transform as shp_transform

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

DATA, OUT, META = base.DATA, base.OUT, base.META

CENSUS_DIR = DATA / "census"
NE_DIR = DATA / "ne_countries"
NE_BORDERS_DIR = DATA / "ne_borders"  # cached by the P1.5 agent; read-only

CENSUS_URLS = [
    f"https://www2.census.gov/geo/tiger/GENZ{y}/shp/cb_{y}_us_state_500k.zip"
    for y in (2023, 2022, 2024)
]
NE_COUNTRIES_URL = ("https://naciscdn.org/naturalearth/10m/cultural/"
                    "ne_10m_admin_0_countries.zip")
NE_LINES_URL = ("https://naciscdn.org/naturalearth/10m/cultural/"
                "ne_10m_admin_0_boundary_lines_land.zip")

TO_LL = Transformer.from_crs(META["crs"], "EPSG:4326", always_xy=True)

# map rectangle (full DEM extent) in Albers meters
X0 = META["x_min"]
X1 = META["x_min"] + META["width"] * META["res"]
Y1 = META["y_max"]
Y0 = META["y_max"] - META["height"] * META["res"]
MAP_RECT = box(X0, Y0, X1, Y1)


# ---------------------------------------------------------------- data --

def ensure_shp(dir_, urls, stem):
    """Return a cached .shp matching stem in dir_, downloading and
    extracting the first reachable url if absent (data/ is gitignored)."""
    dir_.mkdir(parents=True, exist_ok=True)
    hit = sorted(p for p in dir_.glob("*.shp") if stem in p.name)
    if hit:
        return hit[0]
    last = None
    for url in urls:
        try:
            print(f"downloading {url}")
            r = requests.get(url, timeout=300,
                             headers={"User-Agent": "cali-map-pipeline"})
            if r.status_code != 200:
                print(f"  -> HTTP {r.status_code}, trying next vintage")
                continue
            zipfile.ZipFile(io.BytesIO(r.content)).extractall(dir_)
            hit = sorted(p for p in dir_.glob("*.shp") if stem in p.name)
            if hit:
                return hit[0]
        except Exception as e:  # noqa: BLE001 - report and try next URL
            last = e
            print(f"  -> {e}")
    raise RuntimeError(f"could not obtain {stem}: {last}")


def read_shp(path):
    """Yield (attributes-dict, shapely geometry in source lon/lat)."""
    rd = shapefile.Reader(str(path))
    fields = [f[0] for f in rd.fields[1:]]
    for sr in rd.iterShapeRecords():
        geom = shp_shape(sr.shape.__geo_interface__)
        if not geom.is_valid:
            geom = geom.buffer(0)
        yield dict(zip(fields, sr.record)), geom


def lonlat_work_bbox():
    """Lon/lat box covering the whole Albers map rectangle (the rectangle
    bulges beyond the source lon/lat box at corners, P0 finding)."""
    b = MAP_RECT.boundary.segmentize(10_000.0)
    xs, ys = np.asarray(b.coords).T
    lon, lat = TO_LL.transform(xs, ys)
    return box(lon.min() - 0.3, lat.min() - 0.3, lon.max() + 0.3, lat.max() + 0.3)


# ---------------------------------------------------------- rasterizing --

def rasterize_polys(geoms, densify_deg=0.005):
    """Boolean mask of the union of lon/lat polygons on the DEM grid
    (pattern of p1_regions.rasterize_provinces; vertices densified so
    long straight lon/lat edges follow their true Albers curve)."""
    h, w = base.grid_shape()
    img = Image.new("L", (w, h), 0)
    drw = ImageDraw.Draw(img)
    for g in geoms:
        g = g.segmentize(densify_deg)
        for p in (g.geoms if g.geom_type == "MultiPolygon" else [g]):
            for ring, fill in [(p.exterior, 1)] + [(r, 0) for r in p.interiors]:
                arr = np.asarray(ring.coords)
                px, py = base.px_of(arr[:, 0], arr[:, 1])
                drw.polygon(list(zip(px.tolist(), py.tolist())), fill=fill)
    return np.asarray(img, bool)


def rasterize_lines(geoms_alb, width=2):
    """Boolean raster of EPSG:3310 polylines (engraving/QA mask)."""
    h, w = base.grid_shape()
    img = Image.new("L", (w, h), 0)
    drw = ImageDraw.Draw(img)
    for g in geoms_alb:
        parts = g.geoms if g.geom_type.startswith("Multi") else [g]
        for ln in parts:
            if ln.geom_type != "LineString":
                continue
            arr = np.asarray(ln.coords)
            px = (arr[:, 0] - META["x_min"]) / META["res"]
            py = (META["y_max"] - arr[:, 1]) / META["res"]
            drw.line(list(zip(px.tolist(), py.tolist())), fill=1, width=width)
    return np.asarray(img, bool)


# -------------------------------------------------------------- borders --

def only_lines(geom):
    """1-D parts of a geometry (intersection results carry stray points)."""
    parts = geom.geoms if hasattr(geom, "geoms") else [geom]
    lines = [g for g in parts if g.geom_type == "LineString" and len(g.coords) > 1]
    return shapely.line_merge(shapely.union_all(lines)) if lines else None


def state_state_borders(states):
    """Shared border polylines between Census state polygons (they share
    vertices exactly, so boundary intersection is clean 1-D geometry)."""
    out = []
    names = sorted(states)
    for i, a in enumerate(names):
        for b_ in names[i + 1:]:
            if not states[a].intersects(states[b_]):
                continue
            seg = only_lines(states[a].boundary.intersection(states[b_].boundary))
            if seg is not None and not seg.is_empty:
                out.append((f"{a}-{b_}", "state", seg))
    return out


def us_mexico_border(bbox_ll):
    """US-Mexico border polyline from NE 10m admin_0_boundary_lines_land
    (the canonical border-LINE product; reuses the P1.5 cache when present)."""
    shp = NE_BORDERS_DIR / "ne_10m_admin_0_boundary_lines_land.shp"
    if not shp.exists():
        shp = ensure_shp(NE_DIR, [NE_LINES_URL], "boundary_lines_land")
    segs = []
    for _, geom in read_shp(shp):
        clip = geom.intersection(bbox_ll)
        seg = None if clip.is_empty else only_lines(clip)
        if seg is not None and not seg.is_empty:
            segs.append(seg)
    if not segs:
        raise RuntimeError("no international border found in the map area")
    return shapely.line_merge(shapely.union_all(segs))


# ----------------------------------------------------------------- main --

def main():
    bbox_ll = lonlat_work_bbox()
    to_alb = lambda g: shp_transform(base.TO_ALB.transform, g)  # noqa: E731

    # --- source polygons -------------------------------------------------
    census_shp = ensure_shp(CENSUS_DIR, CENSUS_URLS, "us_state_500k")
    states = {}
    for att, geom in read_shp(census_shp):
        if geom.intersects(bbox_ll):
            states[att["NAME"]] = geom
    print(f"census states in map area: {sorted(states)}")

    ne_shp = ensure_shp(NE_DIR, [NE_COUNTRIES_URL], "admin_0_countries")
    mexico = None
    for att, geom in read_shp(ne_shp):
        if att.get("ADMIN") == "Mexico" or att.get("ADM0_A3") == "MEX":
            mexico = geom.intersection(bbox_ll)
            break
    if mexico is None or mexico.is_empty:
        raise RuntimeError("Mexico not found in NE admin_0 countries")

    # --- border polylines (vector, EPSG:3310, clipped to map rect) -------
    borders = state_state_borders(states)
    borders.append(("US-Mexico", "international", us_mexico_border(bbox_ll)))
    feats = []
    border_geoms_alb = []
    for pair, kind, geom in borders:
        g = to_alb(geom.segmentize(0.004)).intersection(MAP_RECT)
        if g.is_empty:
            continue
        g = only_lines(g)
        if g is None or g.is_empty:
            continue
        border_geoms_alb.append(g)
        feats.append({"type": "Feature",
                      "properties": {"pair": pair, "kind": kind},
                      "geometry": mapping(g)})
    gj = {"type": "FeatureCollection",
          "crs": {"type": "name",
                  "properties": {"name": "urn:ogc:def:crs:EPSG::3310"}},
          "features": feats}
    (DATA / "p2_borders.geojson").write_text(json.dumps(gj))
    print(f"wrote {DATA / 'p2_borders.geojson'} "
          f"({[f['properties']['pair'] for f in feats]})")

    # --- rasters ----------------------------------------------------------
    ca_poly = rasterize_polys([states["California"]])
    us_poly = rasterize_polys(states.values())
    mex_poly = rasterize_polys([mexico])
    border_ras = rasterize_lines(border_geoms_alb, width=2)

    # polygon land; borders (always on land) dilated in so any Census-vs-NE
    # digitization crack along the US-Mexico line can't read as a sea inlet
    land_poly = us_poly | mex_poly
    land_poly |= ndimage.binary_dilation(border_ras, iterations=2)

    # sea = polygon water reachable from the Pacific or the map border
    # (Gulf of California) WITHOUT crossing the Carquinez gate; everything
    # else (Suisun, Delta channels, any enclosed water) is land at datum.
    water = ~land_poly
    bar = base.gate_barrier(water.shape)
    if bar is not None:
        water &= ~bar
    lab, _ = ndimage.label(water)
    edge = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    keep = set(edge[edge > 0].tolist())
    keep.add(int(lab[water.shape[0] // 2, 5]))  # Pacific seed (as p1)
    keep.discard(0)
    sea = np.isin(lab, list(keep))
    land_mask = ~sea

    # CA gets the forced land whose nearest polygon-land is California
    # (Suisun Bay / Delta datum-land is enclosed by CA on all sides)
    forced = land_mask & ~land_poly
    if forced.any():
        _, (ir, ic) = ndimage.distance_transform_edt(~land_poly,
                                                     return_indices=True)
        ca_mask = ca_poly | (forced & ca_poly[ir, ic])
    else:
        ca_mask = ca_poly
    ca_mask &= land_mask

    np.savez_compressed(DATA / "p2_land.npz", ca_mask=ca_mask,
                        land_mask=land_mask, border_lines=border_ras)
    print(f"wrote {DATA / 'p2_land.npz'}")
    km2 = (META["res"] / 1000.0) ** 2
    print(f"ca_mask: {ca_mask.sum()} px = {ca_mask.sum() * km2:,.0f} km^2 "
          f"(CA is ~423,970 km^2 incl. inland water)")
    print(f"forced land east of Carquinez gate / enclosed water: "
          f"{forced.sum()} px = {forced.sum() * km2:,.0f} km^2")

    # --- agreement vs the DEM-derived ocean mask --------------------------
    dem = np.load(DATA / "dem_ca_albers_250m.npy")
    old_sea = base.ocean_mask(dem)
    diff = old_sea ^ sea
    n = diff.size
    print(f"\nold (elevation) vs new (polygon) coastline: "
          f"{diff.sum()} cells changed = {100 * diff.sum() / n:.3f}% of grid")
    print(f"  sea -> land: {(old_sea & ~sea).sum()} px "
          f"({(old_sea & ~sea).sum() * km2:,.0f} km^2)")
    print(f"  land -> sea: {(~old_sea & sea).sum()} px "
          f"({(~old_sea & sea).sum() * km2:,.0f} km^2)")
    lab_d, nd = ndimage.label(diff)
    if nd:
        sizes = np.bincount(lab_d.ravel())
        sizes[0] = 0
        order = np.argsort(sizes)[::-1][:10]
        print("  largest disagreement patches:")
        for i in order:
            if sizes[i] == 0:
                break
            cy, cx = ndimage.center_of_mass(lab_d == i)
            x = META["x_min"] + (cx + 0.5) * META["res"]
            y = META["y_max"] - (cy + 0.5) * META["res"]
            lon, lat = TO_LL.transform(x, y)
            kind = "sea->land" if old_sea[lab_d == i].any() else "land->sea"
            print(f"    {sizes[i] * km2:8.1f} km^2  {kind:9s}  "
                  f"({lat:.3f}N, {abs(lon):.3f}W)")

    render_qa(dem, sea, old_sea, ca_mask, border_ras)


def render_qa(dem, sea, old_sea, ca_mask, border_ras):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    ls = LightSource(azdeg=315, altdeg=45)
    land_z = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land_z, vert_exag=12, dx=META["res"], dy=META["res"])

    ss = 3
    thick = lambda m: ndimage.maximum_filter(m, size=ss)[::ss, ::ss]  # noqa: E731
    sh = shade[::ss, ::ss]
    rgb = np.dstack([sh, sh, sh]) * 0.6 + 0.4
    rgb[sea[::ss, ::ss]] = (0.72, 0.80, 0.88)                     # new sea
    diff = thick(old_sea ^ sea)
    rgb[diff] = (0.90, 0.08, 0.08)                                # changes
    ca_edge = ca_mask ^ ndimage.binary_erosion(ca_mask)
    rgb[thick(ca_edge)] = (0.0, 0.0, 0.0)                         # CA outline
    rgb[thick(border_ras)] = (0.35, 0.18, 0.05)                   # borders

    h, w = rgb.shape[:2]
    fig, ax = plt.subplots(figsize=(w / 150, h / 150), dpi=150)
    ax.imshow(rgb)
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_title("P2 land authority QA - black: Census CA outline; "
                 "brown: political borders;\nred: old (DEM) vs new (polygon) "
                 "coastline differences; blue: sea (stops at Carquinez gate)",
                 fontsize=11)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p2_land_qa.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p2_land_qa.png'}")


if __name__ == "__main__":
    main()
