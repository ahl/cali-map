# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "scipy",
#   "shapely",
#   "scikit-image",
# ]
# ///
"""P1a: refine the chosen Coast region (300 m + 5 km band) into a smooth,
atlas-style puzzle-piece shape.

Rules (per ahl's review of out/p1_coast_candidates.png):
  1. Contiguity: inland blobs that only touch the strip through thin necks
     (Clear Lake basin, upper Russian River valleys, Eureka-area scraps)
     revert to Mountains.  NOTE the mainland strip itself is topologically
     TWO land components: SF Bay + Carquinez Strait + Delta channels reach
     the Great Valley province (verified: sea mask touches Valley), so no
     land path connects Marin to San Francisco without circling the whole
     Central Valley.  The two halves are joined by the piece's printed
     bay/ocean shelf (D2), exactly like the Channel Islands.
  2. The Coast/Mountains border is dramatically simplified -- flowing,
     children's-atlas curves.  Losing fine fidelity is OK.
  3. Borders that are NOT ours to smooth stay exact: the ocean coastline,
     the Coast/Valley and Coast/Desert borders (CGS province lines), and
     the state line.  Enforced by growing the mask into those fixed zones
     before vectorizing, then clipping the smoothed polygons back.
  4. SF Bay stays sea; Channel Islands stay Coast and keep their raster
     outline.  Delta islands (Great Valley province scraps in the sea
     mask) are dropped from Coast.
  5. Data patch: the CGS province polygons are coarser than the 250 m
     coastline and leave prov==0 hairline slivers along the shore and
     between adjacent provinces.  Slivers adjacent to the coast strip are
     claimed into it (they are CA land the polygons miss), gated to
     latitudes strictly inside CA so nothing bleeds past OR/MX borders.
     P2 replaces this with the Census state polygon.

Outputs:
  data/p1a_coast_mask.npy         final boolean Coast mask on the DEM grid
  data/p1a_coast_boundary.geojson simplified coast polygons, EPSG:3310
  out/p1a_coast_simplified.png    before/after check-in render
"""

import json
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy import ndimage
import shapely
from shapely.geometry import Polygon, mapping
from skimage import measure

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out"

CFG = tomllib.loads((ROOT / "config.toml").read_text())["regions"]
META = json.loads((DATA / "dem_meta.json").read_text())
TO_ALB = Transformer.from_crs("EPSG:4326", META["crs"], always_xy=True)
TO_LL = Transformer.from_crs(META["crs"], "EPSG:4326", always_xy=True)
RES = META["res"]

# ----------------------------------------------------------------------------
# Tuning parameters (candidates for promotion to config.toml [regions])
# ----------------------------------------------------------------------------
# Morphological opening radius (km), computed with sea/valley/desert/
# out-of-state as solid support: cuts the thin necks (river canyons) tying
# inland low-elevation blobs to the strip so the connectivity filter can
# drop them, and shaves ragged fringes.  Only the Coast/Mountains edge is
# eroded; the strip can never be eaten from the water/province side.
OPEN_KM = 3.0
# Morphological closing radius (km) after opening: fills notches where
# Mountains poke into the strip, keeping the band plump and continuous.
CLOSE_KM = 6.0
# Cap on distance from the sea (km): coast cells farther than this revert
# to Mountains before smoothing.  Shortens the Salinas Valley spur; also
# the outer limit of the "15-50 km wide band" spec.  0 disables.
MAX_SHORE_KM = 50.0
# Douglas-Peucker tolerance (km) for the Coast/Mountains boundary.
SIMPLIFY_KM = 3.0
# Chaikin corner-cutting iterations after simplification (flowing curves).
CHAIKIN_ITERS = 2
# Max segment length (km) fed into Chaikin; bounds corner-cutting
# deviation from the simplified line to ~SEGMENTIZE/4 worst case.
SEGMENTIZE_KM = 4.0
# How far (km) the mask is grown into fixed-border zones (sea, Valley,
# Desert, out-of-state) before vectorizing.  Must exceed worst-case
# simplify+Chaikin deviation so smoothing never bites into fixed borders;
# the growth is clipped back exactly afterwards.
GROW_KM = 6.0
# Mainland strip components smaller than this (km^2) are reassigned to
# Mountains; smaller polygon slivers from the vector clip are dropped too.
MIN_COMP_KM2 = 500.0
MIN_PART_KM2 = 25.0
# prov==0 sliver claiming: max distance from a CGS province cell (km) for
# a sliver to count as a data gap, and latitude window strictly inside CA.
CLAIM_NEAR_KM = 0.75
CLAIM_LAT = (32.545, 41.995)

# region ids / colors (identical to p1_regions.py)
SEA, MOUNTAINS, VALLEY, DESERT, COAST = 0, 1, 2, 3, 4
COLORS = {
    MOUNTAINS: (0.85, 0.29, 0.75),  # magenta
    VALLEY: (0.36, 0.80, 0.36),     # green
    DESERT: (0.95, 0.60, 0.28),     # orange
    COAST: (0.98, 0.91, 0.28),      # yellow
}


def km_px(km):
    return km * 1000.0 / RES


# ----------------------------------------------------------------------------
# Helpers copied from pipeline/p1_regions.py (kept self-contained on purpose)
# ----------------------------------------------------------------------------

def grid_shape():
    return META["height"], META["width"]


def px_of(lon, lat):
    x, y = TO_ALB.transform(np.asarray(lon), np.asarray(lat))
    return ((x - META["x_min"]) / RES,
            (META["y_max"] - np.asarray(y)) / RES)


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
    lab, n = ndimage.label(~sea & ~mainland)
    if n == 0:
        return np.zeros(sea.shape, bool)
    sizes = ndimage.sum_labels(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    keep = []
    for i in np.where(sizes >= 4)[0] + 1:
        cy, cx = ndimage.center_of_mass(lab == i)
        x = META["x_min"] + (cx + 0.5) * RES
        y = META["y_max"] - (cy + 0.5) * RES
        lon, lat = TO_LL.transform(x, y)
        if lat >= CFG["island_min_lat"] and lon < -117.0:
            keep.append(i)
    return np.isin(lab, keep)


def build_regions(dem, prov, name_id, coast_threshold_m, coast_from=None,
                  band_km=0.0, shore_dist=None):
    sea = ocean_mask(dem)
    ids = {n: i for n, i in name_id.items()}

    land_lab, _ = ndimage.label(~sea)
    mainland = land_lab == np.argmax(np.bincount(land_lab[~sea].ravel()))
    islands = ca_islands(sea, mainland)
    ca = ((prov > 0) & ~sea & mainland) | islands

    valley = np.isin(prov, [ids[n] for n in CFG["valley_provinces"]]) & ca
    desert = np.isin(prov, [ids[n] for n in CFG["desert_provinces"]]) & ca

    if coast_from is not None:
        coast = (coast_from & ca & ~valley & ~desert) | islands
    else:
        low = ca & mainland & (dem <= coast_threshold_m) & ~valley & ~desert
        lab, _ = ndimage.label(low)
        shore = ndimage.binary_dilation(sea, iterations=2)
        seeds = np.unique(lab[shore & low])
        coast = np.isin(lab, seeds[seeds > 0]) | islands
        if band_km > 0 and shore_dist is not None:
            band = (shore_dist <= band_km * 1000 / RES) & ca \
                   & mainland & ~valley & ~desert
            coast |= band

    r = int(round(CFG["smooth_radius_km"] * 1000 / RES))
    if r > 0:
        st = ndimage.iterate_structure(ndimage.generate_binary_structure(2, 1), r)
        coast_sm = ndimage.binary_closing(
            ndimage.binary_opening(coast & mainland, st), st) & ca & ~valley & ~desert
        coast = (coast_sm & mainland) | islands

    out = np.zeros(dem.shape, dtype=np.uint8)
    out[ca] = MOUNTAINS
    out[valley] = VALLEY
    out[desert] = DESERT
    out[coast] = COAST
    return out, sea


# ----------------------------------------------------------------------------
# New machinery
# ----------------------------------------------------------------------------

def erode(m, r_px):
    """Euclidean-disk erosion via distance transform (fast at large radii)."""
    return ndimage.distance_transform_edt(m) > r_px


def dilate(m, r_px):
    return ndimage.distance_transform_edt(~m) <= r_px


def open_supported(m, support, r_px):
    """Opening of m with `support` treated as solid mass: only the free
    (Coast/Mountains) edge erodes; capes, the shoreline ribbon, and cells
    pinned against fixed borders survive.  Never adds cells."""
    return dilate(erode(m | support, r_px), r_px) & m


def close_supported(m, support, r_px):
    """Closing of m with `support` solid; returns m plus fill cells."""
    return (erode(dilate(m | support, r_px), r_px) | m) & ~support


def keep_shore_connected(m, sea):
    lab, _ = ndimage.label(m)
    shore = ndimage.binary_dilation(sea, iterations=2)
    ids = np.unique(lab[shore & m])
    return np.isin(lab, ids[ids > 0])


def drop_small(m, min_km2):
    lab, n = ndimage.label(m)
    if n == 0:
        return m
    sizes = ndimage.sum_labels(np.ones_like(lab), lab, index=np.arange(1, n + 1))
    keep = np.where(sizes * (RES / 1000.0) ** 2 >= min_km2)[0] + 1
    return np.isin(lab, keep)


def mask_to_rings(mask):
    """Closed boundary rings of a boolean mask, in EPSG:3310 coords."""
    padded = np.pad(mask.astype(np.uint8), 1)
    rings = []
    for c in measure.find_contours(padded, 0.5):
        xs = META["x_min"] + (c[:, 1] - 1.0) * RES
        ys = META["y_max"] - (c[:, 0] - 1.0) * RES
        if len(xs) >= 4:
            rings.append(np.column_stack([xs, ys]))
    return rings


def rings_to_polygons(rings):
    """Assemble rings into shapely polygons (even-odd nesting)."""
    polys = sorted((Polygon(r) for r in rings), key=lambda p: -abs(p.area))
    polys = [p if p.is_valid else p.buffer(0) for p in polys]
    shells, holes = [], []
    for i, p in enumerate(polys):
        pt = p.representative_point()
        depth = sum(1 for q, _ in shells + holes if q.contains(pt))
        (shells if depth % 2 == 0 else holes).append((p, depth))
    out = []
    for p, d in shells:
        hole_rings = [h.exterior.coords for h, hd in holes
                      if hd == d + 1 and p.contains(h.representative_point())]
        out.append(Polygon(p.exterior.coords, hole_rings))
    return shapely.union_all([p if p.is_valid else p.buffer(0) for p in out])


def chaikin_ring(coords, iters):
    pts = np.asarray(coords)[:-1]
    for _ in range(iters):
        q = np.roll(pts, -1, axis=0)
        new = np.empty((2 * len(pts), 2))
        new[0::2] = 0.75 * pts + 0.25 * q
        new[1::2] = 0.25 * pts + 0.75 * q
        pts = new
    return np.vstack([pts, pts[:1]])


def smooth_polygon(poly, simplify_m, seg_m, chaikin_iters):
    poly = poly.simplify(simplify_m, preserve_topology=True)
    poly = shapely.segmentize(poly, seg_m)
    ext = chaikin_ring(np.asarray(poly.exterior.coords), chaikin_iters)
    ints = [chaikin_ring(np.asarray(r.coords), chaikin_iters)
            for r in poly.interiors if Polygon(r).area >= MIN_PART_KM2 * 1e6]
    out = Polygon(ext, ints)
    return out if out.is_valid else out.buffer(0)


def polygons_of(geom):
    if geom.is_empty:
        return []
    if geom.geom_type == "Polygon":
        return [geom]
    return [g for g in getattr(geom, "geoms", []) if g.geom_type == "Polygon"]


def rasterize_geom(geom):
    h, w = grid_shape()
    img = Image.new("L", (w, h), 0)
    drw = ImageDraw.Draw(img)
    for p in sorted(polygons_of(geom), key=lambda g: -g.area):
        def px(coords):
            a = np.asarray(coords)
            return list(zip(((a[:, 0] - META["x_min"]) / RES).tolist(),
                            ((META["y_max"] - a[:, 1]) / RES).tolist()))
        drw.polygon(px(p.exterior.coords), fill=1)
        for r in p.interiors:
            drw.polygon(px(r.coords), fill=0)
    return np.asarray(img).astype(bool)


def ring_count(geom):
    return sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors)
               for p in polygons_of(geom))


def claim_slivers(m, prov, sea, mainland):
    """prov==0 hairline gaps (coastline slivers, inter-province cracks)
    adjacent to the coast strip, within CLAIM_NEAR_KM of a CGS province
    cell, at latitudes strictly inside CA.  These are CA land the coarse
    CGS polygons miss; claiming them keeps the strip from being cracked
    by data artifacts."""
    near_ca = ndimage.distance_transform_edt(~((prov > 0) & mainland)) \
        <= km_px(CLAIM_NEAR_KM)
    cand = (prov == 0) & mainland & ~sea & near_ca & dilate(m, km_px(1.0))
    rr, cc = np.where(cand)
    if rr.size == 0:
        return cand
    x = META["x_min"] + (cc + 0.5) * RES
    y = META["y_max"] - (rr + 0.5) * RES
    _, lat = TO_LL.transform(x, y)
    ok = (lat > CLAIM_LAT[0]) & (lat < CLAIM_LAT[1])
    out = np.zeros(m.shape, bool)
    out[rr[ok], cc[ok]] = True
    return out


def offshore_islands(sea, mainland, prov, vd_ids):
    """ca_islands minus Delta scraps: island components whose majority
    province is Valley/Desert are not Channel Islands."""
    isl = ca_islands(sea, mainland)
    lab, n = ndimage.label(isl)
    if n == 0:
        return isl
    frac = ndimage.mean(np.isin(prov, vd_ids).astype(float), lab,
                        index=np.arange(1, n + 1))
    keep = np.where(frac < 0.5)[0] + 1
    return np.isin(lab, keep)


# ----------------------------------------------------------------------------

def refine_coast(reg, sea, prov, name_id, shore_dist):
    land_lab, _ = ndimage.label(~sea)
    mainland = land_lab == np.argmax(np.bincount(land_lab[~sea].ravel()))
    vd_ids = [name_id[n] for n in
              CFG["valley_provinces"] + CFG["desert_provinces"]]
    valley = np.isin(prov, [name_id[n] for n in CFG["valley_provinces"]])
    desert = np.isin(prov, [name_id[n] for n in CFG["desert_provinces"]])
    islands = offshore_islands(sea, mainland, prov, vd_ids)

    m0 = (reg == COAST) & mainland
    claim = claim_slivers(m0, prov, sea, mainland)
    ca_main = (((prov > 0) & ~valley & ~desert) | claim) & mainland & ~sea
    allowed = ca_main                              # where mainland Coast may live
    fixed = ~allowed                               # borders we must not move
    open_support = fixed                           # water/provinces/state pin the strip
    close_support = sea                            # closing may only span water gaps

    m = m0 | claim
    # 1) contiguity: only shoreline-connected coast
    m = keep_shore_connected(m, sea)
    # 2) cut necks, drop what disconnects
    m = open_supported(m, open_support, km_px(OPEN_KM))
    m = keep_shore_connected(m, sea)
    # 3) band-width cap: shorten deep inland spurs (Salinas)
    if MAX_SHORE_KM > 0:
        m &= shore_dist <= km_px(MAX_SHORE_KM)
        m = keep_shore_connected(m, sea)
    # 4) fill notches + interior mountain enclaves
    m = close_supported(m, close_support, km_px(CLOSE_KM)) & allowed
    m = ndimage.binary_fill_holes(m | sea) & ~sea & allowed
    m = keep_shore_connected(m, sea)
    m = drop_small(m, MIN_COMP_KM2)

    # 5) grow into fixed zones so smoothing can't nibble exact borders
    grown = m | (dilate(m, km_px(GROW_KM)) & fixed)

    # 6) vectorize -> simplify -> Chaikin
    rings = mask_to_rings(grown)
    raw_vertices = sum(len(r) for r in rings)
    raw_geom = rings_to_polygons(rings)
    parts = [p for p in polygons_of(raw_geom) if p.area >= MIN_PART_KM2 * 1e6]
    smooth = shapely.union_all([
        smooth_polygon(p, SIMPLIFY_KM * 1000, SEGMENTIZE_KM * 1000,
                       CHAIKIN_ITERS) for p in parts])
    smooth_vertices = ring_count(smooth)

    # 7) clip smoothed shape back to the allowed zone in vector space, so
    #    mask and geojson agree; fixed borders come back exact.
    allowed_geom = rings_to_polygons(mask_to_rings(allowed))
    final_vec = shapely.union_all([
        p for p in polygons_of(smooth.intersection(allowed_geom))
        if p.area >= MIN_PART_KM2 * 1e6])

    final_main = rasterize_geom(final_vec) & allowed
    final_main = keep_shore_connected(final_main, sea)
    final_main = drop_small(final_main, MIN_COMP_KM2)

    return final_main, islands, claim, final_vec, raw_vertices, smooth_vertices


def render(dem, panels, sea):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource

    ls = LightSource(azdeg=315, altdeg=45)
    land = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land, vert_exag=12, dx=RES, dy=RES)

    x0k, x1k, y0k, y1k = -420, 560, -660, 470
    xm, ym = META["x_min"] / 1000, META["y_max"] / 1000
    res_k = RES / 1000
    c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
    r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
    ss = 3

    fig, axes = plt.subplots(1, 2, figsize=(16, 10.5), dpi=140)
    for ax, (title, reg) in zip(axes.ravel(), panels):
        sh = shade[r0:r1:ss, c0:c1:ss]
        rg = reg[r0:r1:ss, c0:c1:ss]
        se = sea[r0:r1:ss, c0:c1:ss]
        rgb = np.dstack([sh, sh, sh]) * 0.55 + 0.45
        for rid, col in COLORS.items():
            mm = rg == rid
            for ch in range(3):
                rgb[:, :, ch][mm] = rgb[:, :, ch][mm] * 0.45 + col[ch] * 0.55
        rgb[se] = (0.70, 0.79, 0.87)
        ax.imshow(rgb, extent=[x0k, x1k, y0k, y1k])
        ax.set_title(title, fontsize=13)
        ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle("P1a: coast piece simplification "
                 "(yellow=Coast, magenta=Mountains, green=Valley, orange=Desert)",
                 fontsize=14, y=0.99)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p1a_coast_simplified.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p1a_coast_simplified.png'}")


def main():
    dem = np.load(DATA / "dem_ca_albers_250m.npy")
    prov, name_id = rasterize_provinces()
    sea = ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea)

    t, b = CFG["coast_threshold_m"], CFG["coast_band_km"]
    reg, _ = build_regions(dem, prov, name_id, t, band_km=b,
                           shore_dist=shore_dist)
    ca_px = (reg > 0).sum()
    pct0 = 100 * (reg == COAST).sum() / ca_px

    final_main, islands, claim, final_vec, raw_v, smooth_v = \
        refine_coast(reg, sea, prov, name_id, shore_dist)
    final = final_main | islands

    # safety checks
    assert not (final & sea).any(), "coast bleeds into sea"
    assert not (final & np.isin(reg, [VALLEY, DESERT])).any(), \
        "coast overlaps valley/desert"
    assert not (final & ~((reg > 0) | claim)).any(), "coast outside CA"
    _, n_main = ndimage.label(final_main)
    _, n_piece = ndimage.label(final_main | sea)
    pct1 = 100 * final.sum() / ca_px

    # region raster for the "after" panel (delta islands revert to Valley)
    vd = np.isin(prov, [name_id[n] for n in CFG["valley_provinces"]])
    dd = np.isin(prov, [name_id[n] for n in CFG["desert_provinces"]])
    reg2 = np.zeros_like(reg)
    reg2[reg > 0] = MOUNTAINS
    reg2[(reg > 0) & vd] = VALLEY
    reg2[(reg > 0) & dd] = DESERT
    reg2[final] = COAST

    np.save(DATA / "p1a_coast_mask.npy", final)
    print(f"wrote {DATA / 'p1a_coast_mask.npy'}")

    feats = []
    for p in polygons_of(final_vec):
        feats.append({"type": "Feature",
                      "properties": {"part": "mainland"},
                      "geometry": mapping(shapely.set_precision(p, 0.1))})
    for p in polygons_of(rings_to_polygons(mask_to_rings(islands))):
        feats.append({"type": "Feature",
                      "properties": {"part": "island"},
                      "geometry": mapping(shapely.set_precision(p, 0.1))})
    gj = {"type": "FeatureCollection",
          "crs": {"type": "name",
                  "properties": {"name": "urn:ogc:def:crs:EPSG::3310"}},
          "features": feats}
    (DATA / "p1a_coast_boundary.geojson").write_text(json.dumps(gj))
    print(f"wrote {DATA / 'p1a_coast_boundary.geojson'}")

    print(f"coast before: {pct0:.1f}% of CA;  after: {pct1:.1f}% of CA")
    print(f"mainland land components: {n_main} "
          "(2 expected: bay/delta water splits north from south)")
    print(f"components incl. printed water shelf: {n_piece} (must be 1)")
    print(f"boundary vertices: raw {raw_v} -> simplified+smoothed {smooth_v}")
    md = shore_dist[final_main].max() * RES / 1000
    print(f"max distance from sea inside coast: {md:.0f} km")

    panels = [
        (f"current: {t} m + {b:.0f} km band  ({pct0:.0f}% of CA)", reg),
        (f"simplified: open {OPEN_KM:.0f} km / close {CLOSE_KM:.0f} km / "
         f"cap {MAX_SHORE_KM:.0f} km / DP {SIMPLIFY_KM:.0f} km + Chaikin  "
         f"({pct1:.0f}% of CA)", reg2),
    ]
    render(dem, panels, sea)


if __name__ == "__main__":
    main()
