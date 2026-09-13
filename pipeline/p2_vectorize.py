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
"P1 output" section).

Steps:
  1. Regenerate the P1 region raster (config.toml knobs, deterministic).
  2. Override land/CA with the P2 authorities (data/p2_land.npz from
     p2_land.py): new land inside CA joins the nearest region; land
     outside CA is frame territory; polygon sea is sea. No-exclave rule +
     sub-printable speck drop (P2 cleanup contract).
  3. Extract the boundary as a topological arc-node graph on pixel
     corners: every border polyline is stored ONCE and shared by the
     regions on both sides, so adjacent polygons reference geometrically
     identical vertices (what makes puzzle pieces mate).
  4. Douglas-Peucker each arc (500 m map tolerance), with a global
     cross-intersection check that backs off per-arc tolerance until the
     arrangement is clean (raw pixel arcs are provably non-crossing).
  5. Polygonize the arcs, label each face by majority vote of the raster
     cells inside it, dissolve faces per region.

Outputs:
  data/p2_regions.geojson  EPSG:3310 MultiPolygon per region
  out/p2_regions_qa.png    filled polygons over hillshade
"""

import json
import sys
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
RES = META["res"]
X0, Y1 = META["x_min"], META["y_max"]
KM2 = (RES / 1000.0) ** 2

REGION_NAMES = {base.MOUNTAINS: "mountains", base.VALLEY: "valley",
                base.DESERT: "desert", base.COAST: "coast"}

SNAP_M = 50.0            # shared-border vertex snap grid
SIMPLIFY_M = 500.0       # Douglas-Peucker tolerance (map meters)
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
    print("override deltas vs P1 raster (cells; 1 cell = 0.0625 km^2):")
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
          f"(< {MIN_ISLAND_PX * KM2:.2f} km^2)")
    for rid, nm in REGION_NAMES.items():
        print(f"  final {nm:9s}: {(R == rid).sum() * KM2:9.1f} km^2")
    return R, dem, sea


# ------------------------------------------------- arc-node vectorization --

def extract_arcs(R):
    """Boundary arcs on pixel corners: maximal chains of boundary edges
    between junction nodes (>=3 incident edges), plus pure cycles. Every
    arc is shared verbatim by the areas on both sides."""
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

    arcs = []
    for j in junctions:
        for nb in adj[j]:
            if (min(j, nb), max(j, nb)) in visited:
                continue
            arcs.append(walk(j, nb))
    for n in adj:  # leftover pure cycles (islands, holes)
        for nb in adj[n]:
            if (min(n, nb), max(n, nb)) not in visited:
                arcs.append(walk(n, nb))
    n_edges = len(hr) + len(vr)
    assert len(visited) == n_edges, (len(visited), n_edges)
    return arcs, CW


def arc_coords(path, CW):
    """Corner-node chain -> snapped EPSG:3310 coordinates."""
    idx = np.asarray(path)
    r, c = idx // CW, idx % CW
    x = X0 + (c - 1) * RES
    y = Y1 - (r - 1) * RES
    x = np.round(x / SNAP_M) * SNAP_M
    y = np.round(y / SNAP_M) * SNAP_M
    return np.column_stack([x, y])


def simplify_arcs(raw):
    """DP-simplify every arc, then back off tolerance on any arc involved
    in a cross- or self-intersection until the arrangement is clean.
    Raw pixel arcs only meet at shared endpoints, so tol=0 always passes."""
    ladder = [SIMPLIFY_M, SIMPLIFY_M / 2, SIMPLIFY_M / 4, 0.0]
    tol_i = [0] * len(raw)
    lines = [LineString(a).simplify(ladder[0], preserve_topology=True)
             for a in raw]

    def endpoints(g):
        cc = g.coords
        return {(cc[0][0], cc[0][1]), (cc[-1][0], cc[-1][1])}

    for _ in range(len(ladder)):
        tree = STRtree(lines)
        bad = set()
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
        if not bad:
            return lines, tol_i
        for i in bad:
            if tol_i[i] < len(ladder) - 1:
                tol_i[i] += 1
                lines[i] = LineString(raw[i]).simplify(
                    ladder[tol_i[i]], preserve_topology=True)
        print(f"  simplification back-off on {len(bad)} arcs")
    return lines, tol_i


def face_label(poly, R, prepared_cache={}):
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


# ----------------------------------------------------------------- main --

def main():
    R, dem, sea = build_final_raster()

    print("\nextracting boundary arcs...")
    paths, CW = extract_arcs(R)
    raw = [arc_coords(p, CW) for p in paths]
    n_raw = sum(len(a) for a in raw)
    print(f"  {len(raw)} arcs, {n_raw} raw vertices")

    lines, tol_i = simplify_arcs(raw)
    n_simp = sum(len(g.coords) for g in lines)
    n_backed = sum(1 for t in tol_i if t > 0)
    print(f"  simplified to {n_simp} vertices (DP {SIMPLIFY_M:.0f} m; "
          f"{n_backed} arcs needed reduced tolerance)")

    faces = list(shapely.polygonize(lines).geoms)
    labels = [face_label(f, R) for f in faces]
    print(f"  {len(faces)} faces "
          f"({sum(1 for l in labels if l == 0)} sea/frame, dropped)")

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

    # ---- topology / area checks -----------------------------------------
    print("\nchecks:")
    max_olap = 0.0
    rids = sorted(regions)
    for i, a in enumerate(rids):
        for b in rids[i + 1:]:
            olap = regions[a].intersection(regions[b]).area
            max_olap = max(max_olap, olap)
    print(f"  max pairwise overlap: {max_olap:.6f} m^2")
    union = shapely.union_all(list(regions.values()))
    sum_areas = sum(g.area for g in regions.values())
    gap_proxy = sum_areas - union.area  # >0 would mean double-counted area
    print(f"  sum(region areas) - area(union): {gap_proxy:.6f} m^2")
    raster_area = (R > 0).sum() * RES * RES
    print(f"  union(regions) vs raster CA: {union.area / 1e6:,.1f} vs "
          f"{raster_area / 1e6:,.1f} km^2 "
          f"({100 * (union.area - raster_area) / raster_area:+.4f}%)")
    for rid, nm in REGION_NAMES.items():
        ra = (R == rid).sum() * RES * RES
        pa = regions[rid].area
        parts = len(regions[rid].geoms)
        nv = sum(len(p.exterior.coords) + sum(len(r.coords) for r in p.interiors)
                 for p in regions[rid].geoms)
        print(f"  {nm:9s}: {parts:2d} part(s), {nv:5d} vertices, "
              f"area vs raster {100 * (pa - ra) / ra:+.4f}%")

    # ---- outputs ----------------------------------------------------------
    feats = [{"type": "Feature",
              "properties": {"region": REGION_NAMES[rid], "region_id": rid},
              "geometry": mapping(regions[rid])}
             for rid in sorted(regions)]
    gj = {"type": "FeatureCollection",
          "crs": {"type": "name",
                  "properties": {"name": "urn:ogc:def:crs:EPSG::3310"}},
          "features": feats}
    (DATA / "p2_regions.geojson").write_text(json.dumps(gj))
    print(f"\nwrote {DATA / 'p2_regions.geojson'}")

    render_qa(dem, sea, regions)


def render_qa(dem, sea, regions):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.colors import LightSource
    from matplotlib.patches import PathPatch
    from matplotlib.path import Path as MplPath

    ls = LightSource(azdeg=315, altdeg=45)
    land_z = np.clip(np.where(sea, 0, dem), 0, None)
    shade = ls.hillshade(land_z, vert_exag=12, dx=RES, dy=RES)

    x0k, x1k, y0k, y1k = -420, 560, -660, 470  # CA view crop (as p1)
    xm, ym = X0 / 1000, Y1 / 1000
    res_k = RES / 1000
    c0, c1 = int((x0k - xm) / res_k), int((x1k - xm) / res_k)
    r0, r1 = int((ym - y1k) / res_k), int((ym - y0k) / res_k)
    ss = 3
    sh = shade[r0:r1:ss, c0:c1:ss]
    rgb = np.dstack([sh, sh, sh]) * 0.55 + 0.45
    rgb[sea[r0:r1:ss, c0:c1:ss]] = (0.70, 0.79, 0.87)

    fig, ax = plt.subplots(figsize=(10, 12), dpi=150)
    ax.imshow(rgb, extent=[x0k, x1k, y0k, y1k])
    for rid, g in regions.items():
        col = base.COLORS[rid]
        verts, codes = [], []
        for p in g.geoms:
            for ring in [p.exterior, *p.interiors]:
                arr = np.asarray(ring.coords) / 1000.0
                verts.append(arr)
                codes.append([MplPath.MOVETO]
                             + [MplPath.LINETO] * (len(arr) - 1))
        path = MplPath(np.concatenate(verts), np.concatenate(codes))
        ax.add_patch(PathPatch(path, facecolor=col + (0.5,),
                               edgecolor="black", linewidth=0.6))
    ax.set_xlim(x0k, x1k), ax.set_ylim(y0k, y1k)
    ax.set_xticks([]), ax.set_yticks([])
    ax.set_title("P2 vectorized regions (shared snapped borders, DP 500 m)\n"
                 "yellow=Coast, magenta=Mountains, green=Valley, orange=Desert",
                 fontsize=12)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p2_regions_qa.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p2_regions_qa.png'}")


if __name__ == "__main__":
    main()
