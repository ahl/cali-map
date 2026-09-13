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
"""P1: derive the four region masks and render coast-threshold candidates.

Regions (per NOTES.md G1 hybrid rule):
  valley    = CGS Great Valley
  desert    = CGS Mojave + Colorado Desert + Basin and Range
  coast     = shoreline-contiguous land <= threshold, minus valley/desert;
              offshore islands always belong to coast (D2)
  mountains = rest of California

Outputs:
  out/p1_coast_candidates.png  check-in: threshold candidates + CGS
                               coastline subprovinces for comparison
"""

import json
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"

_TOML = tomllib.loads((ROOT / "config.toml").read_text())
CFG = _TOML["regions"]
OVR = _TOML.get("overrides", {})
META = json.loads((DATA / "dem_meta.json").read_text())
TO_ALB = Transformer.from_crs("EPSG:4326", META["crs"], always_xy=True)

# region ids
SEA, MOUNTAINS, VALLEY, DESERT, COAST = 0, 1, 2, 3, 4
COLORS = {  # roughly matching the curriculum map ahl started from
    MOUNTAINS: (0.85, 0.29, 0.75),  # magenta
    VALLEY: (0.36, 0.80, 0.36),     # green
    DESERT: (0.95, 0.60, 0.28),     # orange
    COAST: (0.98, 0.91, 0.28),      # yellow
}


def grid_shape():
    return META["height"], META["width"]


def px_of(lon, lat):
    x, y = TO_ALB.transform(np.asarray(lon), np.asarray(lat))
    return ((x - META["x_min"]) / META["res"],
            (META["y_max"] - np.asarray(y)) / META["res"])


def rasterize_provinces():
    """Index raster of CGS provinces on the DEM grid: {RANGE_NAME: mask}
    built as one paletted image per distinct name set."""
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


def gate_barrier(shape):
    """Raster line across the Carquinez Strait (config coastal_water_gate),
    or None if unconfigured. Water/lowland beyond it is NOT sea."""
    gate = CFG.get("coastal_water_gate")
    if not gate:
        return None
    (lon0, lat0), (lon1, lat1) = gate
    h, w = shape
    img = Image.new("L", (w, h), 0)
    x0, y0 = px_of(lon0, lat0)
    x1, y1 = px_of(lon1, lat1)
    ImageDraw.Draw(img).line([(float(x0), float(y0)), (float(x1), float(y1))],
                             fill=1, width=5)
    return np.asarray(img, bool)


def ocean_mask(dem):
    """Sea = at/below sea level AND reachable from the Pacific (or map
    border, for the Gulf of California) WITHOUT crossing the Carquinez
    gate. The Delta's subsided below-sea-level farmland and Suisun waters
    east of the gate are treated as LAND at datum height (their water
    depiction, if any, comes from the optional waterway color layer, D9)."""
    low = dem <= 0
    bar = gate_barrier(dem.shape)
    if bar is not None:
        low = low & ~bar
    lab, _ = ndimage.label(low)
    border = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    keep = set(border[border > 0].tolist())
    keep.add(int(lab[dem.shape[0] // 2, 5]))
    return np.isin(lab, list(keep))


def coastal_water(sea):
    """Sea cells that count as COASTAL: connected to the Pacific without
    passing the Carquinez gate. (With ocean_mask also gated this is
    nearly the whole sea; kept as a safety net.)"""
    bar = gate_barrier(sea.shape)
    if bar is None:
        return sea
    lab, _ = ndimage.label(sea & ~bar)
    return lab == lab[sea.shape[0] // 2, 5]  # Pacific-connected side


def ca_islands(sea, mainland):
    """US offshore islands (Channel Islands, Farallones): land components
    off the mainland whose centroid is north of island_min_lat. The CGS
    polygons don't cover them, so they're assigned by geometry."""
    to_ll = Transformer.from_crs(META["crs"], "EPSG:4326", always_xy=True)
    lab, n = ndimage.label(~sea & ~mainland)
    if n == 0:
        return np.zeros(sea.shape, bool)
    sizes = ndimage.sum_labels(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    keep = []
    for i in np.where(sizes >= 4)[0] + 1:  # >= 0.25 km^2; drops sea stacks
        cy, cx = ndimage.center_of_mass(lab == i)
        x = META["x_min"] + (cx + 0.5) * META["res"]
        y = META["y_max"] - (cy + 0.5) * META["res"]
        lon, lat = to_ll.transform(x, y)
        if lat >= CFG["island_min_lat"] and lon < -117.0:
            keep.append(i)
    return np.isin(lab, keep)


def build_regions(dem, prov, name_id, coast_threshold_m, coast_from=None,
                  band_km=0.0, shore_dist=None):
    """Region index raster. coast_from: None -> elevation rule; or a boolean
    mask (e.g., CGS coastline subprovinces) to use as coast directly.
    band_km > 0 additionally makes all mainland within that distance of the
    ocean Coast, regardless of elevation."""
    sea = ocean_mask(dem)
    ids = {n: i for n, i in name_id.items()}

    land_lab, _ = ndimage.label(~sea)
    mainland = land_lab == np.argmax(np.bincount(land_lab[~sea].ravel()))
    islands = ca_islands(sea, mainland)
    ca = ((prov > 0) & ~sea & mainland) | islands

    valley = np.isin(prov, [ids[n] for n in CFG["valley_provinces"]]) & ca
    desert = np.isin(prov, [ids[n] for n in CFG["desert_provinces"]]) & ca

    # northern Basin and Range counts as Mountains, not Desert
    lim = CFG.get("desert_north_limit_km")
    if lim is not None:
        r_cut = int((META["y_max"] - lim * 1000.0) / META["res"])
        if r_cut > 0:
            desert[:min(r_cut, desert.shape[0])] = False

    if coast_from is not None:
        coast = (coast_from & ca & ~valley & ~desert) | islands
    else:
        low = ca & mainland & (dem <= coast_threshold_m) & ~valley & ~desert
        bar = gate_barrier(dem.shape)
        if bar is not None:
            low = low & ~bar  # strait banks don't leak coast into the Delta
        lab, _ = ndimage.label(low)
        shore = ndimage.binary_dilation(sea, iterations=2)
        seeds = np.unique(lab[shore & low])
        coast = np.isin(lab, seeds[seeds > 0]) | islands
        if band_km > 0:
            # band emanates from OPEN COASTAL water only: morphologically
            # open the sea so river-width channels (Delta) don't generate
            # band, and cut at the Carquinez gate (Pacific + SF Bay + San
            # Pablo Bay count; Suisun/Delta don't)
            rw = CFG.get("band_source_min_width_km", 0) * 1000 / META["res"]
            open_sea = sea
            if rw > 0:
                core = ndimage.distance_transform_edt(sea) > rw
                open_sea = ndimage.distance_transform_edt(~core) <= rw
                open_sea &= sea
            open_sea &= coastal_water(sea)
            d = ndimage.distance_transform_edt(~open_sea)
            band = (d <= band_km * 1000 / META["res"]) & ca \
                   & mainland & ~valley & ~desert
            coast |= band

    # light smoothing so preview borders aren't 250 m-pixel fuzz
    r = int(round(CFG["smooth_radius_km"] * 1000 / META["res"]))
    if r > 0:
        st = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 1), r)
        coast_sm = ndimage.binary_closing(
            ndimage.binary_opening(coast & mainland, st), st) & ca & ~valley & ~desert
        coast = (coast_sm & mainland) | islands

    # the valley absorbs adjacent low coast cells (Delta): the band must
    # not curl around the Great Valley's western edge toward Sacramento
    ab = CFG.get("valley_absorb_km", 0)
    if ab and coast_from is None:
        near_valley = ndimage.distance_transform_edt(~valley) \
            <= ab * 1000 / META["res"]
        grabbed = coast & near_valley & mainland
        valley = valley | grabbed
        coast = coast & ~grabbed
        # Delta islets: island components near the valley are valley,
        # not Coast (the ocean-island rule is for the Channel Islands)
        isl_lab, ni = ndimage.label(coast & ~mainland)
        if ni:
            ids = np.unique(isl_lab[(isl_lab > 0) & near_valley])
            if len(ids):
                isl_grab = np.isin(isl_lab, ids)
                valley = valley | isl_grab
                coast = coast & ~isl_grab

    # land enclosed by the valley is valley (Delta islands/fringes, Sutter
    # Buttes). Connectivity-based: any non-valley mainland pocket that is
    # cut off from the main coast/mountains/desert landmass — including
    # pockets sealed by valley + water together — joins the valley.
    if CFG.get("valley_fill_enclosed"):
        nonval = ca & mainland & ~valley
        lab2, n2 = ndimage.label(nonval)
        if n2 > 1:
            sizes2 = np.bincount(lab2.ravel())
            sizes2[0] = 0
            pockets = nonval & (lab2 != sizes2.argmax())
            valley = valley | pockets
            coast = coast & ~valley
            desert = desert & ~valley

    out = np.zeros(dem.shape, dtype=np.uint8)
    out[ca] = MOUNTAINS
    out[valley] = VALLEY
    out[desert] = DESERT
    out[coast] = COAST
    # Lowland connected to the valley floor is valley (reclaims the Delta,
    # which CGS assigns to a Coastline SubProvince; the gate keeps it out
    # of Coast, which would otherwise leave it Mountains). Only Mountains
    # cells flip — Coast and Desert are never stolen.
    vlow = CFG.get("valley_lowland_m", 0)
    if vlow:
        lowv = ~sea & mainland & (dem <= vlow)
        barv = gate_barrier(dem.shape)
        if barv is not None:
            lowv = lowv & ~barv
        lv, _ = ndimage.label(lowv)
        vids = np.unique(lv[valley & lowv])
        sel = np.isin(lv, vids[vids > 0]) & (out == MOUNTAINS)
        out[sel] = VALLEY
        valley = valley | sel

    # No-region land enclosed by the map (CGS province gaps near Suisun,
    # and the Delta datum-land created by the ocean gate) -> nearest
    # region. Cured properly in P2 when the Census polygon defines land.
    gaps = ndimage.binary_fill_holes((out > 0) | sea) & (out == 0) & ~sea
    if gaps.any():
        # per-BLOB majority-of-border assignment (per-cell nearest painted
        # the reclaimed Delta as Mountains via the strait-side hills; its
        # perimeter is overwhelmingly Valley, which is the right answer)
        glab, gn = ndimage.label(gaps)
        gsl = ndimage.find_objects(glab)
        for i in range(1, gn + 1):
            sl = gsl[i - 1]
            sl = (slice(max(sl[0].start - 1, 0), min(sl[0].stop + 1, out.shape[0])),
                  slice(max(sl[1].start - 1, 0), min(sl[1].stop + 1, out.shape[1])))
            comp = glab[sl] == i
            ring = ndimage.binary_dilation(comp) & ~comp
            vals = out[sl][ring]
            vals = vals[vals != SEA]
            if not len(vals):
                continue
            # lowland gaps touching the valley ARE valley (the CGS Great
            # Valley polygon has a huge hole over the Delta; its perimeter
            # is majority-Mountains via the Diablo Range, so a plain
            # majority vote paints the Delta magenta — wrong)
            if (vals == VALLEY).any() and np.median(dem[sl][comp]) < 50.0:
                out[sl][comp] = VALLEY
            else:
                out[sl][comp] = np.bincount(vals).argmax()

    apply_mountain_edges(out, sea, mainland)

    if CFG.get("enforce_contiguous"):
        make_contiguous(out, mainland, sea)
    return out, sea


def apply_mountain_edges(out, sea, mainland):
    """Hand-drawn mountain corridors (ahl markups, config [overrides]):
    each Polygon feature in the override files marks an area whose coast
    and valley cells become Mountains — the polygon is built from ahl's
    drawn edge lines, so its boundary IS the new region border there.
    (LineString features in the same files are provenance only.)"""
    sources = [(fp, "mountains") for fp in OVR.get("mountain_edges", [])] \
        + [(fp, None) for fp in OVR.get("region_marks", [])]
    if not sources:
        return
    h, w = out.shape
    imgs = {"mountains": Image.new("L", (w, h), 0),
            "coast": Image.new("L", (w, h), 0)}
    n_poly = 0
    for fp, forced_target in sources:
        gj = json.loads((ROOT / fp).read_text())
        for f in gj["features"]:
            geom = f["geometry"]
            if geom["type"] not in ("Polygon", "MultiPolygon"):
                continue
            target = forced_target or f["properties"].get("target",
                                                          "mountains")
            drw = ImageDraw.Draw(imgs[target])
            polys = (geom["coordinates"] if geom["type"] == "MultiPolygon"
                     else [geom["coordinates"]])
            for rings in polys:
                for i, ring in enumerate(rings):
                    pts = [((x - META["x_min"]) / META["res"],
                            (META["y_max"] - y) / META["res"])
                           for x, y in ring]
                    drw.polygon(pts, fill=1 if i == 0 else 0)
                n_poly += 1
    if not n_poly:
        return
    zone_m = np.asarray(imgs["mountains"], bool)
    sel = zone_m & ((out == COAST) & mainland | (out == VALLEY))
    if sel.any():
        out[sel] = MOUNTAINS
    zone_c = np.asarray(imgs["coast"], bool)
    sel = zone_c & mainland & ~sea & np.isin(out, [MOUNTAINS, VALLEY])
    if sel.any():
        out[sel] = COAST


def make_contiguous(out, mainland, sea, passes=2):
    """Each region = one connected PIECE. For coast, the piece includes
    the printed ocean shelf (D2), so any coast fragment touching the sea
    is already connected — only LANDLOCKED coast fragments are reassigned.
    Other regions: minor fragments go to the neighboring region that
    borders them most (kills the stranded desert triangle at the north
    cap, mountain exclaves inside the coast band, etc.)."""
    for _ in range(passes):
        changed = 0
        for rid in (VALLEY, DESERT, COAST, MOUNTAINS):
            mask = out == rid
            if rid == COAST:
                mask = mask & mainland
            lab, n = ndimage.label(mask)
            if n <= 1:
                continue
            sizes = np.bincount(lab.ravel())
            sizes[0] = 0
            main_id = sizes.argmax()
            slices = ndimage.find_objects(lab)
            for i in range(1, n + 1):
                if i == main_id:
                    continue
                sl = slices[i - 1]
                if sl is None:
                    continue
                # work on the fragment's padded bounding box, not the
                # full 27M-cell grid (contiguity pass was minutes; now ms)
                sl = (slice(max(sl[0].start - 1, 0),
                            min(sl[0].stop + 1, out.shape[0])),
                      slice(max(sl[1].start - 1, 0),
                            min(sl[1].stop + 1, out.shape[1])))
                comp = lab[sl] == i
                ring = ndimage.binary_dilation(comp) & ~comp
                if rid == COAST and (ring & sea[sl]).any():
                    continue  # shelf-connected (D2)
                vals = out[sl][ring]
                vals = vals[(vals != rid) & (vals != SEA)]
                if len(vals):
                    out[sl][comp] = np.bincount(vals).argmax()
                    changed += 1
        if not changed:
            break


def render(dem, panels, sea):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land, vert_exag=12, dx=META["res"], dy=META["res"])

    # crop view to California + margin (Albers km)
    x0k, x1k, y0k, y1k = -420, 560, -660, 470
    xm, ym = META["x_min"] / 1000, META["y_max"] / 1000
    res_k = META["res"] / 1000
    c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
    r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
    ss = 3  # downsample for the figure

    fig, axes = plt.subplots(2, 2, figsize=(15, 18), dpi=140)
    for ax, (title, reg) in zip(axes.ravel(), panels):
        sh = shade[r0:r1:ss, c0:c1:ss]
        rg = reg[r0:r1:ss, c0:c1:ss]
        se = sea[r0:r1:ss, c0:c1:ss]
        rgb = np.dstack([sh, sh, sh]) * 0.55 + 0.45
        for rid, col in COLORS.items():
            m = rg == rid
            for ch in range(3):
                rgb[:, :, ch][m] = rgb[:, :, ch][m] * 0.45 + col[ch] * 0.55
        rgb[se] = (0.70, 0.79, 0.87)
        ax.imshow(rgb, extent=[x0k, x1k, y0k, y1k])
        ax.set_title(title, fontsize=13)
        ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle("P1 check-in: coast definition candidates "
                 "(yellow=Coast, magenta=Mountains, green=Valley, orange=Desert)",
                 fontsize=14, y=0.995)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p1_coast_candidates.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p1_coast_candidates.png'}")


def main():
    dem = np.load(DATA / "dem_ca_albers_250m.npy")
    prov, name_id = rasterize_provinces()
    sea = ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea)

    panels = []
    for t in CFG["coast_candidates_m"]:
        reg, _ = build_regions(dem, prov, name_id, t)
        pct = 100 * (reg == COAST).sum() / (reg > 0).sum()
        panels.append((f"elevation threshold {t} m  (coast = {pct:.0f}% of CA)", reg))
        print(f"threshold {t} m: coast {pct:.1f}% of CA area")

    t = CFG["coast_threshold_m"]
    b = CFG["coast_band_km"]
    reg, _ = build_regions(dem, prov, name_id, t, band_km=b,
                           shore_dist=shore_dist)
    pct = 100 * (reg == COAST).sum() / (reg > 0).sum()
    panels.append((f"{t} m + {b:.0f} km shoreline band  "
                   f"(coast = {pct:.0f}% of CA)", reg))
    print(f"threshold {t} m + band {b} km: coast {pct:.1f}% of CA area")

    render(dem, panels, sea)


if __name__ == "__main__":
    main()
