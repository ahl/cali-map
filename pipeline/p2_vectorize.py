# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "scipy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "shapely",
#   "scikit-image",
# ]
# ///
"""P2 part 2: vectorize the region raster into snapped shared-border
polygons — the durable representation all mesh generation uses (NOTES.md
"P1 output" section). Runs against the SIGNED-OFF P1 geometry: config
[overrides] (Vallejo corridor + p1_final marks) apply inside
p1_regions.build_regions automatically.

Steps:
  1. Regenerate the P1-final region raster (config.toml knobs).
  2. Override land/CA with the P2 authorities (data/p2_land.npz from
     p2_land.py): new land inside CA joins the nearest region; land
     outside CA is frame territory; polygon sea is sea. No-exclave rule +
     sub-printable speck drop (P2 cleanup contract; Farallones stay out).
  3. Pull the eight Channel Islands out of Coast: they form their own
     puzzle piece (config [islands] one_piece_hull) whose outline is the
     convex hull of all island land buffered by buffer_km of ocean.
     Harbor/bay islets (Terminal Island etc.) stay with mainland Coast.
  4. Extract the mainland boundary as a topological arc-node graph on
     pixel corners: every border polyline is stored ONCE and shared by
     the regions on both sides, so adjacent polygons reference
     geometrically identical vertices (what makes puzzle pieces mate).
  5. Douglas-Peucker each arc (500 m map tolerance), with a global
     cross-intersection check that backs off per-arc tolerance until the
     arrangement is clean (raw pixel arcs are provably non-crossing).
  6. Polygonize the arcs, label each face by majority vote of the raster
     cells inside it, dissolve faces per region. Do it twice: once with
     the DP arcs (canonical) and once with Chaikin-smoothed DP arcs
     (print-preview flavor), same topology guarantees both times.

Outputs:
  data/p2_regions.geojson         EPSG:3310, canonical (DP 500 m)
  data/p2_regions_smooth.geojson  EPSG:3310, Chaikin x2 preview flavor
  out/p2_regions_qa.png           smooth flavor over hillshade + Vallejo inset
"""

import hashlib
import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

import numpy as np
import shapely
from scipy import ndimage
from shapely.geometry import LineString, mapping
from shapely.strtree import STRtree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

DATA, OUT, META, CFG = base.DATA, base.OUT, base.META, base.CFG
ISL_CFG = tomllib.loads((base.ROOT / "config.toml").read_text())["islands"]
RES = META["res"]
X0, Y1 = META["x_min"], META["y_max"]
KM2 = (RES / 1000.0) ** 2

REGION_NAMES = {base.MOUNTAINS: "mountains", base.VALLEY: "valley",
                base.DESERT: "desert", base.COAST: "coast"}
ISLANDS_ID = 5
ISLANDS_COLOR = (0.35, 0.62, 0.85)

# the eight Channel Islands (as p1f_island_pieces.py); components within
# ISL_MATCH_KM of a listed point belong to the islands piece
CHANNEL_ISLANDS = {
    "San Miguel": (-120.37, 34.04), "Santa Rosa": (-120.05, 33.96),
    "Santa Cruz": (-119.72, 34.01), "Anacapa": (-119.37, 34.00),
    "San Nicolas": (-119.49, 33.24), "Santa Barbara": (-119.03, 33.48),
    "Santa Catalina": (-118.42, 33.39), "San Clemente": (-118.48, 32.90),
}
ISL_MATCH_KM = 18.0
# not on any piece (ahl): rasterized Census rocks exceed the speck
# threshold, so the Farallones need an explicit drop
FARALLONES = (-123.003, 37.699)
FARALLONES_KM = 8.0

SNAP_M = 50.0            # shared-border vertex snap grid
SIMPLIFY_M = 500.0       # Douglas-Peucker tolerance (map meters)
CHAIKIN_ITERS = 2        # smoothing for the preview flavor
MIN_ISLAND_PX = 8        # < 0.5 km^2 offshore specks dropped (P2 contract)


# ------------------------------------------------------------ raster fix --

def build_final_raster():
    dem = np.load(DATA / "dem_ca_albers_250m.npy")
    prov, name_id = base.rasterize_provinces()
    sea0 = base.ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea0)
    reg, _ = base.build_regions(dem, prov, name_id, CFG["coast_threshold_m"],
                                band_km=CFG["coast_band_km"],
                                shore_dist=shore_dist)

    land = np.load(DATA / "p2_land.npz")
    ca_mask, land_mask = land["ca_mask"], land["land_mask"]
    sea = ~land_mask

    R = reg.copy()
    removed = (reg > 0) & ~ca_mask
    R[~ca_mask] = 0
    need = ca_mask & (R == 0)
    print("override deltas vs P1-final raster (1 cell = 0.0625 km^2):")
    for rid, nm in REGION_NAMES.items():
        n = (removed & (reg == rid)).sum()
        if n:
            print(f"  removed from {nm:9s} (outside Census CA): "
                  f"{n:6d} = {n * KM2:7.1f} km^2")
    print(f"  new CA land to fill (Census land the P1 raster called "
          f"sea/frame): {need.sum()} = {need.sum() * KM2:.1f} km^2")
    if need.any():
        _, (ir, ic) = ndimage.distance_transform_edt(R == 0,
                                                     return_indices=True)
        R[need] = R[ir[need], ic[need]]
        for rid, nm in REGION_NAMES.items():
            n = (need & (R == rid)).sum()
            if n:
                print(f"    -> joined {nm:9s}: {n:6d} = {n * KM2:7.1f} km^2")

    # no-exclave cleanup on the new land model, then drop offshore specks
    land_lab, _ = ndimage.label(land_mask)
    mainland = land_lab == np.argmax(np.bincount(land_lab[land_mask].ravel()))
    base.make_contiguous(R, mainland, sea)
    isl_lab, ni = ndimage.label((R > 0) & ~mainland)
    dropped = 0
    if ni:
        sizes = np.bincount(isl_lab.ravel())
        for i in range(1, ni + 1):
            if sizes[i] < MIN_ISLAND_PX:
                R[isl_lab == i] = 0
                dropped += 1
    print(f"  dropped {dropped} sub-printable offshore specks "
          f"(< {MIN_ISLAND_PX * KM2:.2f} km^2; Farallones stay out)")
    return R, dem, sea, mainland


def extract_channel_islands(R, mainland):
    """Remove the eight Channel Islands from the region raster (they are
    their own piece now, D2 revised) and return their land mask. Other
    off-mainland components (Terminal Island, bay islets) stay with their
    region — folded into the mainland Coast feature."""
    to_ll = base.Transformer.from_crs(META["crs"], "EPSG:4326",
                                      always_xy=True)
    targets = {}
    for nm, (lo, la) in CHANNEL_ISLANDS.items():
        px, py = base.px_of(lo, la)
        targets[nm] = (float(px), float(py))
    fx, fy = base.px_of(*FARALLONES)
    lab, n = ndimage.label((R > 0) & ~mainland)
    isl = np.zeros(R.shape, bool)
    matched = set()
    print("off-mainland components:")
    for i in range(1, n + 1):
        comp = lab == i
        cy, cx = ndimage.center_of_mass(comp)
        hit = None
        for nm, (tx, ty) in targets.items():
            if np.hypot(cx - tx, cy - ty) * RES / 1000 <= ISL_MATCH_KM:
                hit = nm
                break
        x = X0 + (cx + 0.5) * RES
        y = Y1 - (cy + 0.5) * RES
        lon, lat = to_ll.transform(x, y)
        if hit is None and \
                np.hypot(cx - fx, cy - fy) * RES / 1000 <= FARALLONES_KM:
            R[comp] = 0
            print(f"  {comp.sum() * KM2:7.1f} km^2 at ({lat:.2f}N, "
                  f"{abs(lon):.2f}W) -> DROPPED (Farallones, per ahl)")
            continue
        who = f"islands piece ({hit})" if hit else \
            f"stays {REGION_NAMES[int(np.bincount(R[comp]).argmax())]}"
        print(f"  {comp.sum() * KM2:7.1f} km^2 at ({lat:.2f}N, "
              f"{abs(lon):.2f}W) -> {who}")
        if hit:
            isl |= comp
            matched.add(hit)
    missing = set(CHANNEL_ISLANDS) - matched
    if missing:
        raise RuntimeError(f"Channel Islands not found in raster: {missing}")
    R[isl] = 0
    print(f"  islands piece land: {isl.sum() * KM2:.1f} km^2 "
          f"({len(matched)}/8 islands matched)")
    return isl


def islands_piece_polygon(isl_mask):
    """One-piece hull outline (config [islands] one_piece_hull): convex
    hull of all island land, buffered by buffer_km of ocean. Vertices
    snapped to the same 50 m grid as the shared borders."""
    assert ISL_CFG["mode"] == "one_piece_hull", ISL_CFG["mode"]
    edge = isl_mask ^ ndimage.binary_erosion(isl_mask)
    rr, cc = np.nonzero(edge)
    corners = []
    for dr in (0, 1):
        for dc in (0, 1):
            corners.append(np.column_stack([X0 + (cc + dc) * RES,
                                            Y1 - (rr + dr) * RES]))
    pts = shapely.multipoints(np.concatenate(corners))
    hull = shapely.convex_hull(pts)
    piece = hull.buffer(ISL_CFG["buffer_km"] * 1000.0, quad_segs=16)
    coords = np.round(np.asarray(piece.exterior.coords) / SNAP_M) * SNAP_M
    piece = shapely.Polygon(coords)
    if not piece.is_valid:
        piece = piece.buffer(0)
    return shapely.MultiPolygon([piece])


# ------------------------------------------------- arc-node vectorization --

def extract_arcs(R):
    """Boundary arcs on pixel corners: maximal chains of boundary edges
    between junction nodes (>=3 incident edges), plus pure cycles. Every
    arc is shared verbatim by the areas on both sides. Returns
    (paths, is_cycle flags, corner-grid stride)."""
    h, w = R.shape
    P = np.zeros((h + 2, w + 2), np.uint8)
    P[1:-1, 1:-1] = R
    H2, W2 = P.shape
    CW = W2 + 1  # corner grid stride

    hr, hc = np.nonzero(P[1:, :] != P[:-1, :])   # horiz edge below corner row
    hr = hr + 1
    vr, vc = np.nonzero(P[:, 1:] != P[:, :-1])   # vert edge right of corner col
    vc = vc + 1

    adj = defaultdict(list)
    for a, b in zip((hr * CW + hc).tolist(), (hr * CW + hc + 1).tolist()):
        adj[a].append(b)
        adj[b].append(a)
    for a, b in zip((vr * CW + vc).tolist(), (vr * CW + vc + CW).tolist()):
        adj[a].append(b)
        adj[b].append(a)

    junctions = {n for n, nb in adj.items() if len(nb) != 2}
    visited = set()

    def walk(start, nxt):
        path = [start, nxt]
        visited.add((min(start, nxt), max(start, nxt)))
        prev, cur = start, nxt
        while cur not in junctions and cur != start:
            nb = adj[cur]
            step = nb[0] if nb[0] != prev else nb[1]
            visited.add((min(cur, step), max(cur, step)))
            path.append(step)
            prev, cur = cur, step
        return path

    arcs, cyc = [], []
    for j in junctions:
        for nb in adj[j]:
            if (min(j, nb), max(j, nb)) in visited:
                continue
            arcs.append(walk(j, nb))
            cyc.append(False)
    for n in adj:  # leftover pure cycles (islands, holes)
        for nb in adj[n]:
            if (min(n, nb), max(n, nb)) not in visited:
                arcs.append(walk(n, nb))
                cyc.append(True)
    n_edges = len(hr) + len(vr)
    assert len(visited) == n_edges, (len(visited), n_edges)
    return arcs, cyc, CW


def arc_coords(path, CW):
    """Corner-node chain -> snapped EPSG:3310 coordinates."""
    idx = np.asarray(path)
    r, c = idx // CW, idx % CW
    x = X0 + (c - 1) * RES
    y = Y1 - (r - 1) * RES
    x = np.round(x / SNAP_M) * SNAP_M
    y = np.round(y / SNAP_M) * SNAP_M
    return np.column_stack([x, y])


def check_arrangement(lines):
    """Indices of arcs that self-intersect or cross another arc anywhere
    but a shared endpoint."""
    tree = STRtree(lines)
    bad = set()

    def endpoints(g):
        cc = g.coords
        return {(cc[0][0], cc[0][1]), (cc[-1][0], cc[-1][1])}

    for i, g in enumerate(lines):
        if not g.is_simple:
            bad.add(i)
        for j in tree.query(g):
            j = int(j)
            if j <= i:
                continue
            inter = g.intersection(lines[j])
            if inter.is_empty:
                continue
            pts = ([inter] if inter.geom_type == "Point"
                   else list(inter.geoms)
                   if inter.geom_type == "MultiPoint" else None)
            shared = endpoints(g) & endpoints(lines[j])
            if pts is None or any((p.x, p.y) not in shared for p in pts):
                bad.add(i)
                bad.add(j)
    return bad


def simplify_arcs(raw):
    """DP-simplify every arc, then back off tolerance on any arc involved
    in a cross- or self-intersection until the arrangement is clean.
    Raw pixel arcs only meet at shared endpoints, so tol=0 always passes."""
    ladder = [SIMPLIFY_M, SIMPLIFY_M / 2, SIMPLIFY_M / 4, 0.0]
    tol_i = [0] * len(raw)
    lines = [LineString(a).simplify(ladder[0], preserve_topology=True)
             for a in raw]
    for _ in range(len(ladder)):
        bad = check_arrangement(lines)
        if not bad:
            return lines, tol_i
        for i in bad:
            if tol_i[i] < len(ladder) - 1:
                tol_i[i] += 1
                lines[i] = LineString(raw[i]).simplify(
                    ladder[tol_i[i]], preserve_topology=True)
        print(f"  simplification back-off on {len(bad)} arcs")
    return lines, tol_i


def chaikin(coords, iters, cyclic):
    """Corner-cutting smoothing. Open arcs keep both endpoints fixed
    (junction nodes stay shared); pure cycles smooth cyclically."""
    c = np.asarray(coords, float)
    if cyclic:
        ring = c[:-1]
        for _ in range(iters):
            q = np.roll(ring, -1, axis=0)
            new = np.empty((2 * len(ring), 2))
            new[0::2] = 0.75 * ring + 0.25 * q
            new[1::2] = 0.25 * ring + 0.75 * q
            ring = new
        return np.vstack([ring, ring[:1]])
    for _ in range(iters):
        p, q = c[:-1], c[1:]
        mid = np.empty((2 * len(p), 2))
        mid[0::2] = 0.75 * p + 0.25 * q
        mid[1::2] = 0.25 * p + 0.75 * q
        c = np.vstack([c[:1], mid, c[-1:]])
    return c


def smooth_arcs(dp_lines, cycles):
    """Chaikin the DP arcs; any arc that breaks the arrangement reverts
    to its DP form (endpoints never move, so borders stay shared)."""
    sm = [LineString(chaikin(np.asarray(g.coords), CHAIKIN_ITERS, cyc))
          for g, cyc in zip(dp_lines, cycles)]
    reverted = 0
    for _ in range(4):
        bad = check_arrangement(sm)
        if not bad:
            break
        for i in bad:
            if sm[i] is not dp_lines[i]:
                sm[i] = dp_lines[i]
                reverted += 1
    if reverted:
        print(f"  chaikin: reverted {reverted} arcs to DP form")
    return sm


def face_label(poly, R):
    """Region id of a polygonized face = majority vote of the raster
    cells whose centers fall inside it (immune to boundary shift from
    simplification; representative_point fallback for slivers)."""
    minx, miny, maxx, maxy = poly.bounds
    c0 = max(int((minx - X0) / RES), 0)
    c1 = min(int(np.ceil((maxx - X0) / RES)) + 1, R.shape[1])
    r0 = max(int((Y1 - maxy) / RES), 0)
    r1 = min(int(np.ceil((Y1 - miny) / RES)) + 1, R.shape[0])
    if c1 > c0 and r1 > r0:
        stride = max(1, int(np.sqrt(max((r1 - r0) * (c1 - c0), 1) / 4000.0)))
        rr, cc = np.meshgrid(np.arange(r0, r1, stride),
                             np.arange(c0, c1, stride), indexing="ij")
        xs = X0 + (cc.ravel() + 0.5) * RES
        ys = Y1 - (rr.ravel() + 0.5) * RES
        inside = shapely.contains_xy(poly, xs, ys)
        if inside.any():
            vals = R[rr.ravel()[inside], cc.ravel()[inside]]
            return int(np.bincount(vals).argmax())
    p = poly.representative_point()
    r = int((Y1 - p.y) / RES)
    c = int((p.x - X0) / RES)
    if 0 <= r < R.shape[0] and 0 <= c < R.shape[1]:
        return int(R[r, c])
    return 0


def assemble(lines, R, flavor):
    """Polygonize arcs, label faces from the raster, dissolve per region,
    run the topology/area checks. Returns {region_id: MultiPolygon}."""
    faces = list(shapely.polygonize(lines).geoms)
    labels = [face_label(f, R) for f in faces]
    regions = {}
    for rid in REGION_NAMES:
        fs = [f for f, l in zip(faces, labels) if l == rid]
        if not fs:
            raise RuntimeError(f"no faces for region {REGION_NAMES[rid]}")
        g = shapely.union_all(fs)
        if g.geom_type == "Polygon":
            g = shapely.MultiPolygon([g])
        if not g.is_valid:
            raise RuntimeError(f"invalid geometry for {REGION_NAMES[rid]}")
        regions[rid] = g

    print(f"[{flavor}] {len(faces)} faces "
          f"({sum(1 for l in labels if l == 0)} sea/frame, dropped); checks:")
    max_olap = 0.0
    rids = sorted(regions)
    for i, a in enumerate(rids):
        for b in rids[i + 1:]:
            olap = regions[a].intersection(regions[b]).area
            max_olap = max(max_olap, olap)
    union = shapely.union_all(list(regions.values()))
    gap_proxy = sum(g.area for g in regions.values()) - union.area
    raster_area = (R > 0).sum() * RES * RES
    print(f"  max pairwise overlap {max_olap:.6f} m^2; "
          f"sum(areas)-area(union) {gap_proxy:.6f} m^2")
    print(f"  union(regions) vs raster CA-mainland: {union.area / 1e6:,.1f}"
          f" vs {raster_area / 1e6:,.1f} km^2 "
          f"({100 * (union.area - raster_area) / raster_area:+.4f}%)")
    for rid, nm in REGION_NAMES.items():
        ra = (R == rid).sum() * RES * RES
        pa = regions[rid].area
        nv = sum(len(p.exterior.coords)
                 + sum(len(r.coords) for r in p.interiors)
                 for p in regions[rid].geoms)
        print(f"  {nm:9s}: {len(regions[rid].geoms):2d} part(s), "
              f"{nv:5d} vertices, area vs raster {100 * (pa - ra) / ra:+.4f}%")
    vc = regions[base.VALLEY].boundary.intersection(
        regions[base.COAST].boundary)
    print(f"  valley-coast contact: {vc.length / 1000:.3f} km"
          f"{'' if vc.length else '  (Vallejo corridor holds)'}")
    return regions


def write_geojson(path, regions, islands_mp):
    feats = [{"type": "Feature",
              "properties": {"region": REGION_NAMES[rid], "region_id": rid},
              "geometry": mapping(regions[rid])}
             for rid in sorted(regions)]
    feats.append({"type": "Feature",
                  "properties": {"region": "islands",
                                 "region_id": ISLANDS_ID,
                                 "kind": "piece_outline_hull_buffer",
                                 "buffer_km": ISL_CFG["buffer_km"]},
                  "geometry": mapping(islands_mp)})
    gj = {"type": "FeatureCollection",
          "crs": {"type": "name",
                  "properties": {"name": "urn:ogc:def:crs:EPSG::3310"}},
          "features": feats}
    path.write_text(json.dumps(gj))
    print(f"wrote {path}")


# ----------------------------------------------------------------- main --

def main():
    prev = DATA / "p2_regions.geojson"
    prev_areas = {}
    if prev.exists():
        old = json.loads(prev.read_text())
        for f in old["features"]:
            g = shapely.geometry.shape(f["geometry"])
            prev_areas[f["properties"]["region"]] = g.area / 1e6

    R, dem, sea, mainland = build_final_raster()
    isl_mask = extract_channel_islands(R, mainland)
    print(f"region raster sha256: "
          f"{hashlib.sha256(R.tobytes()).hexdigest()[:16]}")
    for rid, nm in REGION_NAMES.items():
        a = (R == rid).sum() * KM2
        d = f" ({a - prev_areas[nm]:+,.1f} vs previous geojson)" \
            if nm in prev_areas else ""
        print(f"  final {nm:9s}: {a:9.1f} km^2{d}")

    islands_mp = islands_piece_polygon(isl_mask)
    print(f"islands piece: hull+{ISL_CFG['buffer_km']:g} km buffer, "
          f"{islands_mp.area / 1e6:,.0f} km^2, "
          f"{len(islands_mp.geoms[0].exterior.coords)} vertices")

    print("\nextracting boundary arcs...")
    paths, cycles, CW = extract_arcs(R)
    raw = [arc_coords(p, CW) for p in paths]
    print(f"  {len(raw)} arcs, {sum(len(a) for a in raw)} raw vertices")

    dp_lines, tol_i = simplify_arcs(raw)
    n_backed = sum(1 for t in tol_i if t > 0)
    print(f"  DP {SIMPLIFY_M:.0f} m -> {sum(len(g.coords) for g in dp_lines)}"
          f" vertices ({n_backed} arcs needed reduced tolerance)")
    sm_lines = smooth_arcs(dp_lines, cycles)
    print(f"  chaikin x{CHAIKIN_ITERS} -> "
          f"{sum(len(g.coords) for g in sm_lines)} vertices")

    print()
    regions_dp = assemble(dp_lines, R, "canonical DP")
    for rid, g in regions_dp.items():  # islands piece may touch nothing
        olap = g.intersection(islands_mp).area
        if olap:
            raise RuntimeError(f"islands piece overlaps {REGION_NAMES[rid]}"
                               f" by {olap:.1f} m^2")
    gap = regions_dp[base.COAST].distance(islands_mp)
    print(f"  islands piece: overlaps NO mainland region; "
          f"min gap to coast piece {gap / 1000:.1f} km")
    print()
    regions_sm = assemble(sm_lines, R, "smooth preview")

    write_geojson(DATA / "p2_regions.geojson", regions_dp, islands_mp)
    write_geojson(DATA / "p2_regions_smooth.geojson", regions_sm, islands_mp)

    render_qa(dem, sea, regions_sm, islands_mp)


def render_qa(dem, sea, regions, islands_mp):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    ls = LightSource(azdeg=315, altdeg=45)
    land_z = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land_z, vert_exag=12, dx=RES, dy=RES)
    xm, ym = X0 / 1000, Y1 / 1000
    res_k = RES / 1000

    def backdrop(ax, x0k, x1k, y0k, y1k, ss):
        c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
        r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
        sh = shade[r0:r1:ss, c0:c1:ss]
        rgb = np.dstack([sh, sh, sh]) * 0.55 + 0.45
        rgb[sea[r0:r1:ss, c0:c1:ss]] = (0.70, 0.79, 0.87)
        ax.imshow(rgb, extent=[x0k, x1k, y0k, y1k])

    def draw(ax, geoms_cols, lw):
        for g, col in geoms_cols:
            verts, codes = [], []
            for p in g.geoms:
                for ring in [p.exterior, *p.interiors]:
                    arr = np.asarray(ring.coords) / 1000.0
                    verts.append(arr)
                    codes.append([MplPath.MOVETO]
                                 + [MplPath.LINETO] * (len(arr) - 1))
            path = MplPath(np.concatenate(verts), np.concatenate(codes))
            ax.add_patch(PathPatch(path, facecolor=col + (0.5,),
                                   edgecolor="black", linewidth=lw))

    geoms_cols = [(g, base.COLORS[rid]) for rid, g in regions.items()]
    geoms_cols.append((islands_mp, ISLANDS_COLOR))

    fig, (ax1, ax2) = plt.subplots(
        1, 2, figsize=(17, 12), dpi=150, width_ratios=[2.05, 1])
    backdrop(ax1, -420, 560, -660, 470, 3)
    draw(ax1, geoms_cols, 0.6)
    ax1.set_xlim(-420, 560), ax1.set_ylim(-660, 470)
    ax1.set_title("P2 regions, smooth flavor (DP 500 m + Chaikin x2)\n"
                  "yellow=Coast, magenta=Mountains, green=Valley, "
                  "orange=Desert, blue=Islands piece", fontsize=12)

    backdrop(ax2, -260, -120, -80, 95, 1)
    draw(ax2, geoms_cols, 1.2)
    try:  # ahl's hand-drawn corridor edges, for eyeballing the cut
        ovr = json.loads((base.ROOT /
                          "overrides/vallejo_mountain_edges.geojson")
                         .read_text())
        for f in ovr["features"]:
            if f["geometry"]["type"] == "LineString":
                arr = np.asarray(f["geometry"]["coordinates"]) / 1000.0
                ax2.plot(arr[:, 0], arr[:, 1], "--", color="#222222",
                         linewidth=1.0)
    except FileNotFoundError:
        pass
    ax2.set_xlim(-260, -120), ax2.set_ylim(-80, 95)
    ax2.set_title("Vallejo corridor inset\n(dashed = ahl's override edges)",
                  fontsize=12)
    for ax in (ax1, ax2):
        ax.set_xticks([]), ax.set_yticks([])

    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p2_regions_qa.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p2_regions_qa.png'}")


if __name__ == "__main__":
    main()
