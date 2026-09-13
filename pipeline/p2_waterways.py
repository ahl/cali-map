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
"""P2 waterways: prepare the OPTIONAL second-color hydro layer (D9, G10).

Source: USGS Small-Scale (National Atlas) 1:1,000,000 hydrography.
  streams:      streaml010g  (polylines, Strahler stream order)
  waterbodies:  wtrbdyp010g  (polygons, Feature + Area_sq_mi)

Filter (NOTES G10):
  streams      Strahler >= 4 (sentinels -999/-998 dropped) PLUS named
               exceptions (Owens River, Salinas River) at any order;
  waterbodies  Feature in (Lake, Reservoir) with Area_sq_mi >= 1.5.
Clip by GEOMETRY to the map lon/lat box (dem_meta.json) — NOT by the
State attribute, so Tahoe, Mead, Havasu, Pyramid survive.

Outputs:
  data/p2_waterways.geojson       EPSG:3310; feature classes "stream"
                                  (name, strahler) and "waterbody"
                                  (name, area_sq_mi)
  out/p2_waterways_preview.png    hillshade + blue hydro, labeled — for
                                  ahl to pick which waterways print
"""

import json
import sys
import tarfile
from pathlib import Path

import numpy as np
import requests
import shapefile
from pyproj import Transformer
from shapely.geometry import box, mapping, shape
from shapely.ops import transform as shp_transform

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
HYDRO = DATA / "hydro"
OUT = ROOT / "out"

META = json.loads((DATA / "dem_meta.json").read_text())

SOURCES = {
    "streaml010g": ("https://prd-tnm.s3.amazonaws.com/StagedProducts/"
                    "Small-scale/data/Hydrography/"
                    "streaml010g.shp_nt00885.tar.gz"),
    "wtrbdyp010g": ("https://prd-tnm.s3.amazonaws.com/StagedProducts/"
                    "Small-scale/data/Hydrography/"
                    "wtrbdyp010g.shp_nt00886.tar.gz"),
}

STRAHLER_MIN = 4
STREAM_NAME_EXCEPTIONS = {"Owens River", "Salinas River"}
WATERBODY_FEATURES = {"Lake", "Reservoir"}
AREA_MIN_SQMI = 1.5

# Source shapefiles are NAD83 geographic; NAD83<->WGS84 is far below one
# DEM cell at this scale.
TO_ALB = Transformer.from_crs("EPSG:4269", META["crs"], always_xy=True)


def fetch(name: str) -> Path:
    """Download + extract one source into data/hydro/ (cached)."""
    HYDRO.mkdir(parents=True, exist_ok=True)
    shp = HYDRO / f"{name}.shp"
    if shp.exists():
        return shp
    url = SOURCES[name]
    tgz = HYDRO / url.rsplit("/", 1)[-1]
    if not tgz.exists():
        print(f"downloading {url} ...")
        with requests.get(url, stream=True, timeout=600) as r:
            r.raise_for_status()
            part = tgz.with_suffix(".part")
            with open(part, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
            part.rename(tgz)
    print(f"extracting {tgz.name} ...")
    with tarfile.open(tgz) as tf:
        tf.extractall(HYDRO, filter="data")
    if not shp.exists():  # tarball may nest a directory
        found = next(HYDRO.rglob(f"{name}.shp"))
        for part in found.parent.glob(f"{name}.*"):
            part.rename(HYDRO / part.name)
    return shp


def clip_box():
    lon0, lon1 = META["lon_range"]
    lat0, lat1 = META["lat_range"]
    return box(lon0, lat0, lon1, lat1)


def load_streams(bbox):
    """Filtered, clipped, reprojected streams.
    Returns (features, stats) where each feature is
    (shapely geom in EPSG:3310, name, strahler)."""
    shp = fetch("streaml010g")
    rd = shapefile.Reader(str(shp), encoding="latin-1")
    fields = [f[0] for f in rd.fields[1:]]
    print(f"streams: {rd.numRecords} records, fields: {fields}")

    kept, n_pass, n_exc, feats_seen = [], 0, 0, {}
    for sr in rd.iterShapeRecords(fields=["Strahler", "Name", "Feature"]):
        rec = sr.record
        strahler = rec["Strahler"]
        name = (rec["Name"] or "").strip()
        feat = (rec["Feature"] or "").strip()
        by_order = strahler is not None and strahler >= STRAHLER_MIN
        by_name = name in STREAM_NAME_EXCEPTIONS
        if not (by_order or by_name):
            continue
        geom = shape(sr.shape.__geo_interface__)
        if not geom.intersects(bbox):
            continue
        geom = geom.intersection(bbox)
        if geom.is_empty:
            continue
        feats_seen[feat] = feats_seen.get(feat, 0) + 1
        n_pass += by_order
        n_exc += (by_name and not by_order)
        kept.append((shp_transform(TO_ALB.transform, geom), name,
                     int(strahler) if strahler is not None else -999))
    print(f"streams kept: {len(kept)} "
          f"({n_pass} by Strahler>={STRAHLER_MIN}, "
          f"{n_exc} by name exception); Feature values: {feats_seen}")
    total_km = sum(g.length for g, _, _ in kept) / 1000
    print(f"total stream length kept: {total_km:.0f} km")
    return kept, {"total": rd.numRecords, "kept": len(kept),
                  "by_order": n_pass, "by_name": n_exc,
                  "length_km": round(total_km)}


def load_waterbodies(bbox):
    """Filtered, clipped, reprojected waterbodies.
    Each feature: (geom EPSG:3310, name, area_sq_mi)."""
    shp = fetch("wtrbdyp010g")
    rd = shapefile.Reader(str(shp), encoding="latin-1")
    fields = [f[0] for f in rd.fields[1:]]
    print(f"waterbodies: {rd.numRecords} records, fields: {fields}")

    kept = []
    for sr in rd.iterShapeRecords(fields=["Feature", "Name", "Area_sq_mi"]):
        rec = sr.record
        feat = (rec["Feature"] or "").strip()
        if feat not in WATERBODY_FEATURES:
            continue
        area = rec["Area_sq_mi"] or 0.0
        if area < AREA_MIN_SQMI:
            continue
        geom = shape(sr.shape.__geo_interface__)
        if not geom.intersects(bbox):
            continue
        geom = geom.intersection(bbox)
        if geom.is_empty:
            continue
        name = (rec["Name"] or "").strip()
        kept.append((shp_transform(TO_ALB.transform, geom), name,
                     float(area)))
    print(f"waterbodies kept: {len(kept)} "
          f"(Feature in {sorted(WATERBODY_FEATURES)}, "
          f"area >= {AREA_MIN_SQMI} sq mi, clipped by geometry)")
    return kept, {"total": rd.numRecords, "kept": len(kept)}


def save_geojson(streams, waterbodies):
    feats = []
    for geom, name, strahler in streams:
        feats.append({"type": "Feature",
                      "properties": {"class": "stream", "name": name,
                                     "strahler": strahler},
                      "geometry": mapping(geom)})
    for geom, name, area in waterbodies:
        feats.append({"type": "Feature",
                      "properties": {"class": "waterbody", "name": name,
                                     "area_sq_mi": round(area, 2)},
                      "geometry": mapping(geom)})
    gj = {"type": "FeatureCollection",
          "crs": {"type": "name",
                  "properties": {"name": "urn:ogc:def:crs:EPSG::3310"}},
          "features": feats}
    out = DATA / "p2_waterways.geojson"
    out.write_text(json.dumps(gj))
    print(f"wrote {out} ({len(feats)} features)")


# ---------------------------------------------------------------- preview

# Waterbodies to label: iconic first (always labeled if present), then
# largest-by-area fills up to the cap.
ICONIC_LAKES = ["Lake Tahoe", "Salton Sea", "Shasta Lake", "Mono Lake",
                "Clear Lake", "Goose Lake", "Lake Mead", "Lake Havasu",
                "Pyramid Lake", "Lake Almanor", "Trinity Lake",
                "Lake Oroville", "San Luis Reservoir", "Walker Lake",
                "Honey Lake"]
ICONIC_RIVERS = ["Sacramento River", "San Joaquin River", "Colorado River",
                 "Klamath River", "Owens River", "Salinas River",
                 "Eel River", "Feather River", "Kern River",
                 "Russian River", "Pit River", "Trinity River"]
N_LAKE_LABELS = 15


# label nudges (points) to break known collisions
LABEL_OFFSET = {"Lake Almanor": (-14, 10, "right"),
                "Honey Lake": (8, -3, "left"),
                "Shasta Lake": (5, 6, "left")}


def stream_lw(strahler):
    """Line width scaled by Strahler order (named exceptions -> thinnest)."""
    if strahler < STRAHLER_MIN:
        return 1.0
    return 1.3 + 0.6 * (strahler - STRAHLER_MIN)  # 4->1.3, 5->1.9, 6->2.5


def render_preview(streams, waterbodies):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    dem = np.load(DATA / "dem_ca_albers_250m.npy")
    sea = base.ocean_mask(dem)
    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land, vert_exag=12,
                         dx=META["res"], dy=META["res"])

    xm, ym = META["x_min"] / 1000, META["y_max"] / 1000
    res_k = META["res"] / 1000
    x1k = xm + META["width"] * res_k
    y0k = ym - META["height"] * res_k
    ss = 2
    sh = shade[::ss, ::ss]
    se = sea[::ss, ::ss]
    rgb = np.dstack([sh, sh, sh]) * 0.62 + 0.38
    rgb[se] = (0.80, 0.87, 0.92)

    fig, ax = plt.subplots(figsize=(13, 15.3), dpi=150)
    ax.imshow(rgb, extent=[xm, x1k, y0k, ym], zorder=1)

    WATER = "#1560bd"
    for geom, _, _ in waterbodies:
        polys = getattr(geom, "geoms", [geom])
        for p in polys:
            if p.geom_type != "Polygon":
                continue
            xs, ys = np.asarray(p.exterior.coords).T
            ax.fill(xs / 1000, ys / 1000, color=WATER, lw=0, zorder=3)
    for geom, name, strahler in streams:
        lines = getattr(geom, "geoms", [geom])
        for ln in lines:
            if ln.geom_type != "LineString":
                continue
            xs, ys = np.asarray(ln.coords).T
            ax.plot(xs / 1000, ys / 1000, color=WATER,
                    lw=stream_lw(strahler), solid_capstyle="round",
                    zorder=4)

    # --- labels: lakes ---
    by_name = {}
    for geom, name, area in waterbodies:
        if name:
            g0, a0 = by_name.get(name, (None, 0.0))
            by_name[name] = (geom if area >= a0 else g0, max(area, a0))
    ordered = [n for n in ICONIC_LAKES if n in by_name]
    for n, _ in sorted(by_name.items(), key=lambda kv: -kv[1][1]):
        if n not in ordered:
            ordered.append(n)
    for name in ordered[:N_LAKE_LABELS]:
        geom, area = by_name[name]
        pt = geom.representative_point()
        dx, dy, ha = LABEL_OFFSET.get(name, (4, 4, "left"))
        ax.annotate(name, (pt.x / 1000, pt.y / 1000),
                    xytext=(dx, dy), textcoords="offset points",
                    fontsize=7.5, color="#0a3d7a", fontweight="bold",
                    ha=ha, zorder=6,
                    path_effects=_halo())

    # --- labels: rivers, at the midpoint of each river's longest arc ---
    river_arcs = {}
    for geom, name, strahler in streams:
        if name in ICONIC_RIVERS:
            for ln in getattr(geom, "geoms", [geom]):
                best = river_arcs.get(name)
                if best is None or ln.length > best.length:
                    river_arcs[name] = ln
    for name, ln in river_arcs.items():
        pt = ln.interpolate(0.5, normalized=True)
        ax.annotate(name, (pt.x / 1000, pt.y / 1000),
                    xytext=(4, -9), textcoords="offset points",
                    fontsize=7.5, color="#0a3d7a", style="italic",
                    zorder=6, path_effects=_halo())

    ax.set_xlim(xm, x1k)
    ax.set_ylim(y0k, ym)
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_title("P2 waterways candidates — streams Strahler>=4 "
                 "(+Owens, Salinas), lakes/reservoirs >=1.5 sq mi\n"
                 "line width ~ Strahler order; for selecting the printed "
                 "cut (D9 optional second color)", fontsize=11)
    OUT.mkdir(exist_ok=True)
    fig.tight_layout()
    fig.savefig(OUT / "p2_waterways_preview.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p2_waterways_preview.png'}")


def _halo():
    import matplotlib.patheffects as pe
    return [pe.withStroke(linewidth=2.2, foreground="white", alpha=0.9)]


def main():
    bbox = clip_box()
    streams, s_stats = load_streams(bbox)
    waterbodies, w_stats = load_waterbodies(bbox)
    save_geojson(streams, waterbodies)
    render_preview(streams, waterbodies)
    print("\nsummary:")
    print(f"  streams:     {s_stats['total']} total -> {s_stats['kept']} "
          f"kept ({s_stats['by_order']} by order, {s_stats['by_name']} "
          f"by name), {s_stats['length_km']} km")
    print(f"  waterbodies: {w_stats['total']} total -> "
          f"{w_stats['kept']} kept")


if __name__ == "__main__":
    main()
