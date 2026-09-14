# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "shapely",
#   "pyproj",
#   "matplotlib",
#   "pillow",
#   "scipy",
# ]
# ///
"""P2: dimensioned 2D layout drawing of the FINAL PRODUCT, for ahl's
approval. Also the visual proposal for the coast-piece / ocean-split
composition question (NOTES.md D2, D13, G6, G11).

Composition drawn (six pieces tiling the D13 window rectangle exactly):
  1. COAST   = coast region land (data/p2_regions_smooth.geojson,
               region=coast, 3 parts: mainland + Angel I. + Treasure/
               Yerba Buena) UNION all ocean/bay water NORTH of the
               US-Mexico border line extended due WEST to the map edge
               (data/p2_borders.geojson, pair=US-Mexico), MINUS the
               islands piece's footprint (its cavity). Two-color plate:
               land tint above datum, paler water tint at datum (D2/G7).
  2-4. MOUNTAINS, VALLEY, DESERT = their p2_regions_smooth.geojson
               polygons as-is.
  5. ISLANDS = the "islands" feature polygon as-is (hull + 10 km, G11).
  6. FRAME   = everything else in the window: out-of-state land
               (OR/NV/AZ + Mexico incl. Baja) plus the ocean SOUTH of
               the extended Mexico line.

The D13 window = California's Census bbox (data/p2_land.npz ca_mask)
padded 40 km on N/E/S and 67.5 km of open Pacific on the W (same
padding p15_engraved.py uses), scaled so the window's total N-S extent
= config.toml [output].total_ns_mm (254 mm).

New geometry (coast-water, frame) is derived by rasterizing the four
already-vectorized region polygons + the islands polygon back onto the
DEM grid within the window, classifying every remaining pixel as
coast-water (sea, north of the Mexico-border latitude) or frame
(everything else remaining), and re-vectorizing with the same
corner-grid arc extraction p2_vectorize.py uses for the canonical
geometry (shared boundaries, no gaps by construction) -- then a light
Douglas-Peucker simplify for a clean print-quality line at this scale.

Outputs:
  out/p2_layout.png   dimensioned layout, legend/stats table, title.
"""

import json
import sys
import tomllib
from collections import defaultdict
from pathlib import Path

import numpy as np
import shapely
from PIL import Image, ImageDraw
from scipy import ndimage
from shapely.geometry import LineString, box
from shapely.geometry import shape as shp_shape

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

ROOT, DATA, OUT, META = base.ROOT, base.DATA, base.OUT, base.META
RES = META["res"]
X0, Y1 = META["x_min"], META["y_max"]

CFG_OUT = tomllib.loads((ROOT / "config.toml").read_text())["output"]
TOTAL_NS_MM = CFG_OUT["total_ns_mm"]

PAD_KM = 40.0        # D13 window margin N/E/S (matches p15_engraved.py)
WEST_PAD_KM = 67.5   # D13 window open-Pacific margin W

FRAME_COLOR = (0.78, 0.78, 0.78)
WATER_MIX = 0.78     # universal water tint = the coast land color
                     # lightened this far toward white (paler tint, same
                     # hue family) -- ONE color for every drop of water in
                     # the window, regardless of which piece owns it

REGION_NAMES = {base.MOUNTAINS: "mountains", base.VALLEY: "valley",
                base.DESERT: "desert", base.COAST: "coast"}


# ------------------------------------------------------------- geometry --

def load_regions():
    gj = json.loads((DATA / "p2_regions_smooth.geojson").read_text())
    out = {}
    for f in gj["features"]:
        p = f["properties"]
        key = p["region"]
        out[key] = shp_shape(f["geometry"])
    return out


def ca_window_bbox():
    """D13 window: Census CA bbox (data/p2_land.npz ca_mask) + PAD_KM on
    N/E/S + WEST_PAD_KM open Pacific on W. Returns (r0, r1, c0, c1) pixel
    slice bounds and (x0, x1, y0, y1) in Albers meters."""
    ca_mask = np.load(DATA / "p2_land.npz")["ca_mask"]
    rows = np.nonzero(ca_mask.any(axis=1))[0]
    cols = np.nonzero(ca_mask.any(axis=0))[0]
    pad = int(round(PAD_KM * 1000.0 / RES))
    wpad = int(round(WEST_PAD_KM * 1000.0 / RES))
    r0 = max(rows[0] - pad, 0)
    r1 = min(rows[-1] + 1 + pad, ca_mask.shape[0])
    c0 = max(cols[0] - wpad, 0)
    c1 = min(cols[-1] + 1 + pad, ca_mask.shape[1])
    x0, x1 = X0 + c0 * RES, X0 + c1 * RES
    y1, y0 = Y1 - r0 * RES, Y1 - r1 * RES
    ca_ns_mm_bounds = (rows[0], rows[-1])
    return (r0, r1, c0, c1), (x0, x1, y0, y1), ca_ns_mm_bounds


def mexico_gate_y():
    """Northing (Albers meters) of the US-Mexico border's Pacific
    terminus -- the point the task's ocean split extends due west from."""
    gj = json.loads((DATA / "p2_borders.geojson").read_text())
    for f in gj["features"]:
        if f["properties"]["pair"] == "US-Mexico":
            g = shp_shape(f["geometry"])
            pts = list(g.coords)
            west = min(pts, key=lambda c: c[0])
            return west[1]
    raise RuntimeError("US-Mexico border not found")


def rasterize_mp(mp, shape_hw):
    """Boolean raster (FULL DEM grid) of a shapely (Multi)Polygon in
    EPSG:3310 meters (pattern of p1_regions.rasterize_provinces)."""
    h, w = shape_hw
    img = Image.new("L", (w, h), 0)
    drw = ImageDraw.Draw(img)
    polys = mp.geoms if hasattr(mp, "geoms") else [mp]
    for p in polys:
        for i, ring in enumerate([p.exterior, *p.interiors]):
            arr = np.asarray(ring.coords)
            px = (arr[:, 0] - X0) / RES
            py = (Y1 - arr[:, 1]) / RES
            drw.polygon(list(zip(px.tolist(), py.tolist())),
                       fill=1 if i == 0 else 0)
    return np.asarray(img, bool)


# -------------------------------------------- generic arc-node polygonizer --
# (same corner-grid method as p2_vectorize.extract_arcs, kept generic here
# so it can vectorize the window-local coast-water/frame classification.)

def extract_arcs(R):
    h, w = R.shape
    P = np.zeros((h + 2, w + 2), np.uint8)
    P[1:-1, 1:-1] = R
    H2, W2 = P.shape
    CW = W2 + 1

    hr, hc = np.nonzero(P[1:, :] != P[:-1, :])
    hr = hr + 1
    vr, vc = np.nonzero(P[:, 1:] != P[:, :-1])
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
    for n in adj:
        for nb in adj[n]:
            if (min(n, nb), max(n, nb)) not in visited:
                arcs.append(walk(n, nb))
    return arcs, CW


def _iter_lines(geom):
    """Flatten a shapely geometry (a boundary-intersection result can be a
    GeometryCollection with stray points) down to its LineString parts."""
    if geom.is_empty:
        return
    if geom.geom_type == "LineString":
        yield geom
    elif geom.geom_type in ("MultiLineString", "GeometryCollection"):
        for g in geom.geoms:
            yield from _iter_lines(g)


def arc_coords(path, CW, x0, y1):
    idx = np.asarray(path)
    r, c = idx // CW, idx % CW
    x = x0 + (c - 1) * RES
    y = y1 - (r - 1) * RES
    return np.column_stack([x, y])


def face_label(poly, W, x0, y1):
    minx, miny, maxx, maxy = poly.bounds
    c0 = max(int((minx - x0) / RES), 0)
    c1 = min(int(np.ceil((maxx - x0) / RES)) + 1, W.shape[1])
    r0 = max(int((y1 - maxy) / RES), 0)
    r1 = min(int(np.ceil((y1 - miny) / RES)) + 1, W.shape[0])
    if c1 > c0 and r1 > r0:
        rr, cc = np.meshgrid(np.arange(r0, r1), np.arange(c0, c1),
                             indexing="ij")
        xs = x0 + (cc.ravel() + 0.5) * RES
        ys = y1 - (rr.ravel() + 0.5) * RES
        inside = shapely.contains_xy(poly, xs, ys)
        if inside.any():
            vals = W[rr.ravel()[inside], cc.ravel()[inside]]
            return int(np.bincount(vals).argmax())
    p = poly.representative_point()
    r = int((y1 - p.y) / RES)
    c = int((p.x - x0) / RES)
    if 0 <= r < W.shape[0] and 0 <= c < W.shape[1]:
        return int(W[r, c])
    return 0


def keep_largest(mp):
    """Drop every part of a MultiPolygon except the largest; returns
    (kept_MultiPolygon, n_dropped, dropped_area_km2)."""
    parts = list(mp.geoms) if hasattr(mp, "geoms") else [mp]
    parts = [p for p in parts if not p.is_empty and p.area > 0]
    if len(parts) <= 1:
        return shapely.MultiPolygon(parts), 0, 0.0
    parts.sort(key=lambda p: -p.area)
    dropped = parts[1:]
    return (shapely.MultiPolygon([parts[0]]), len(dropped),
            sum(p.area for p in dropped) / 1e6)


def drop_tiny_holes(mp, min_area_m2=1000.0):
    """Remove interior rings (holes) smaller than min_area_m2 -- a
    cosmetic cleanup for pinhole-sized polygonize artifacts (a few square
    meters) that would otherwise render as a stray dot (a visible
    outline stroke around a near-zero-area ring)."""
    parts = list(mp.geoms) if hasattr(mp, "geoms") else [mp]
    out = []
    for p in parts:
        holes = [r for r in p.interiors
                if shapely.Polygon(r).area >= min_area_m2]
        out.append(shapely.Polygon(p.exterior, holes))
    return shapely.MultiPolygon(out)


def vectorize_labels(W, x0, y1, labels):
    """W: window-local uint8 raster. Returns {label: MultiPolygon}."""
    arcs, CW = extract_arcs(W)
    lines = [LineString(arc_coords(a, CW, x0, y1)) for a in arcs
             if len(a) > 1]
    faces = list(shapely.polygonize(lines).geoms)
    out = {}
    for lab in labels:
        fs = [f for f in faces if face_label(f, W, x0, y1) == lab]
        if not fs:
            out[lab] = shapely.MultiPolygon()
            continue
        g = shapely.union_all(fs)
        g = g.simplify(500.0, preserve_topology=True)
        if g.geom_type == "Polygon":
            g = shapely.MultiPolygon([g])
        out[lab] = g
    return out


# ---------------------------------------------------------------- build --

def build_layout():
    regions = load_regions()
    # snap to a 1 m precision grid: adjacent p2_regions_smooth.geojson
    # polygons share exact vertices, and GEOS boolean ops on touching-but-
    # not-overlapping polygons are floating-point-robustness-sensitive --
    # without this, union_all/difference below produce ~300 degenerate
    # slivers of near-zero area at the shared-border vertices.
    regions = {k: shapely.set_precision(g, 1.0) for k, g in regions.items()}
    # p2_vectorize.py's own overlap check (coast vs islands) only runs on
    # the canonical DP flavor, not this smooth/Chaikin preview flavor;
    # the smooth coast polygon has a ~0.013 km^2 sliver overlap with the
    # islands hull near the mainland (found while building this figure --
    # worth a look upstream, but harmless here: clip it defensively).
    coast_islands_overlap = regions["coast"].intersection(regions["islands"]).area
    if coast_islands_overlap > 0:
        print(f"  note: p2_regions_smooth.geojson coast/islands overlap "
             f"{coast_islands_overlap / 1e6:.4f} km^2 (smooth-flavor "
             f"artifact, not present in the canonical DP flavor) -- "
             f"clipped for this drawing")
        regions["coast"] = regions["coast"].difference(regions["islands"])
    (r0, r1, c0, c1), (x0, x1, y0, y1), ca_rows = ca_window_bbox()
    gate_y = mexico_gate_y()

    shape_full = (META["height"], META["width"])
    islands_m = rasterize_mp(regions["islands"], shape_full)[r0:r1, c0:c1]

    land_mask = np.load(DATA / "p2_land.npz")["land_mask"][r0:r1, c0:c1]
    # data/p2_land.npz's land_mask is the RAW Census/NE land model; every
    # disconnected sub-printable speck it carries (coastal rocks,
    # skerries) was already dropped from the 5 piece polygons by
    # p2_vectorize.py's MIN_ISLAND_PX contract, so treating them as land
    # here would either open a hole in coast-water (north of the gate) or
    # scatter tiny orphan islets through frame (everywhere else). Fold
    # every land component except the mainland and the islands piece back
    # into sea, matching the signed-off geometry's model of the world.
    land_lab, n_land = ndimage.label(land_mask)
    if n_land > 1:
        sizes = np.bincount(land_lab.ravel())
        sizes[0] = 0
        mainland_id = sizes.argmax()
        stray = (land_lab != mainland_id) & (land_lab != 0) & ~islands_m
        if stray.any():
            print(f"  folding {stray.sum()} px ({stray.sum() * (RES/1000)**2:.2f} "
                 f"km^2) of disconnected sub-printable land specks into sea "
                 f"(consistent with p2_vectorize.py's MIN_ISLAND_PX contract)")
            land_mask = land_mask & ~stray
    sea = ~land_mask

    rows_abs = np.arange(r0, r1)
    row_of_gate = (Y1 - gate_y) / RES
    north_of_gate = (rows_abs <= row_of_gate)[:, None]

    coast_water_mask = sea & north_of_gate & ~islands_m

    W = np.zeros((r1 - r0, c1 - c0), np.uint8)
    W[coast_water_mask] = 1
    coast_water = vectorize_labels(W, x0, y1, [1])[1]

    # Guarantee an exact, gap-free/overlap-free partition: the raster ->
    # vector round trip (rasterize 5 smooth polygons, classify the rest,
    # re-vectorize with a cosmetic DP simplify) can drift by up to the
    # simplify tolerance where coast-water's new boundary meets an
    # already-exact region polygon. Subtract the exact polygons back out
    # of coast-water, then define FRAME as the pure geometric complement
    # of "everything else" in the window -- not its own raster/vectorize
    # pass -- so frame can never gap or overlap its neighbors.
    coast_water = shapely.set_precision(coast_water, 1.0)
    exact = shapely.union_all([regions["mountains"], regions["valley"],
                              regions["desert"], regions["coast"],
                              regions["islands"]], grid_size=1.0)
    coast_water = shapely.difference(coast_water, exact, grid_size=1.0)
    # GEOS difference() isn't perfectly robust against the islands piece's
    # smooth buffered-hull curve specifically -- a hairline (~0.01 km^2,
    # spread over a handful of sub-hectare patches) sliver survives even
    # with a precision grid. Clear it unconditionally with a 15 m buffer
    # (0.0000034 mm on paper at this scale -- sub-pixel, invisible; the
    # thin moat this opens between islands and coast-water defaults to
    # frame territory, also invisible at print scale).
    coast_water = coast_water.difference(regions["islands"].buffer(15.0))
    if coast_water.geom_type == "Polygon":
        coast_water = shapely.MultiPolygon([coast_water])

    # sequential differencing (rather than one difference against a
    # unioned MultiPolygon) is the numerically robust way to carve frame
    # out of the window rectangle here.
    win_rect = box(x0, y0, x1, y1)
    frame = win_rect
    for g in (regions["mountains"], regions["valley"], regions["desert"],
              regions["coast"], regions["islands"], coast_water):
        frame = shapely.difference(frame, g, grid_size=1.0)
    if frame.geom_type == "Polygon":
        frame = shapely.MultiPolygon([frame])

    # data/p2_land.npz's land_mask is the RAW Census/NE land model, but
    # p2_regions_smooth.geojson already dropped every sub-printable
    # offshore speck (coastal rocks, skerries -- NOTES.md P2 cleanup
    # contract, MIN_ISLAND_PX ~0.5 km^2 in p2_vectorize.py) from the 5
    # pieces. Those dropped specks are still LAND in land_mask, so they
    # fall out of this script's "frame = everything else" difference as
    # dozens of sub-km^2 rock islets scattered inside coast-water -- kept
    # consistent with the signed-off pipeline by dropping them here too
    # (report the dropped count/area rather than silently discarding).
    frame, dropped_n, dropped_km2 = keep_largest(frame)
    if dropped_n:
        print(f"  frame: dropped {dropped_n} sub-printable speck(s) "
             f"totaling {dropped_km2:.2f} km^2 (consistent with "
             f"p2_vectorize.py's MIN_ISLAND_PX contract)")

    coast_full = shapely.union_all([regions["coast"], coast_water])
    if coast_full.geom_type == "Polygon":
        coast_full = shapely.MultiPolygon([coast_full])

    # ahl's correction: ocean is ONE continuous water color regardless of
    # which piece owns it (frame's southern water and islands' shelf are
    # not gray/blue -- they're the same tint as coast-water). Vectorize
    # the whole window's sea (ungated, unexcluded -- so it already has a
    # correctly-shaped hole for every land mass, including the islands'
    # own land and out-of-state land) and clean it against the four exact
    # CA-mainland vectors the same way coast-water was cleaned above.
    W_all = np.zeros((r1 - r0, c1 - c0), np.uint8)
    W_all[sea] = 1
    water_all = vectorize_labels(W_all, x0, y1, [1])[1]
    water_all = shapely.set_precision(water_all, 1.0)
    exact_ca_land = shapely.union_all(
        [regions["mountains"], regions["valley"], regions["desert"],
         regions["coast"]], grid_size=1.0)
    water_all = shapely.difference(water_all, exact_ca_land, grid_size=1.0)
    if water_all.geom_type == "Polygon":
        water_all = shapely.MultiPolygon([water_all])

    # frame's and the islands piece's own land sub-areas, for the
    # region-palette/gray fill -- everything else in each piece is water,
    # painted with the single universal tint.
    frame_land = frame.difference(water_all)
    island_land = regions["islands"].difference(water_all)
    if frame_land.geom_type == "Polygon":
        frame_land = shapely.MultiPolygon([frame_land])
    if island_land.geom_type == "Polygon":
        island_land = shapely.MultiPolygon([island_land])

    pieces = {
        "coast_land": regions["coast"],
        "coast_water": coast_water,
        "coast": coast_full,
        "mountains": regions["mountains"],
        "valley": regions["valley"],
        "desert": regions["desert"],
        "islands": regions["islands"],
        "island_land": island_land,
        "frame": frame,
        "frame_land": frame_land,
        "water_all": water_all,
    }
    # pinhole-sized (few m^2) interior rings from the polygonize round trip
    # would otherwise render as a stray dot at print resolution
    pieces = {k: drop_tiny_holes(g) for k, g in pieces.items()}

    # piece-parting lines (drawn distinctly from same-piece land/water
    # seams): for every pair of the 6 physical pieces, the shared boundary
    # is solid where it touches ANY land (a real, informative edge -- an
    # interior CA border, a state line, or a piece boundary that follows
    # an actual coastline) and dashed where it runs entirely through open
    # water with land on neither side (the coast/frame ocean-split gate
    # line; the islands piece's outline, wholly inside coast-water).
    land_all = shapely.union_all(
        [regions["mountains"], regions["valley"], regions["desert"],
         regions["coast"], pieces["island_land"], pieces["frame_land"]])
    piece_polys = {"mountains": regions["mountains"],
                  "valley": regions["valley"], "desert": regions["desert"],
                  "coast": pieces["coast"], "islands": regions["islands"],
                  "frame": pieces["frame"]}
    names = list(piece_polys)
    land_lines, water_lines = [], []
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            shared = piece_polys[names[i]].boundary.intersection(
                piece_polys[names[j]].boundary)
            for ln in _iter_lines(shared):
                if ln.length < 1.0:
                    continue
                if ln.buffer(30.0).intersects(land_all):
                    land_lines.append(ln)
                else:
                    water_lines.append(ln)
    pieces["_parting_land_lines"] = land_lines
    pieces["_parting_water_lines"] = water_lines

    bbox = (x0, x1, y0, y1)
    return pieces, bbox, ca_rows, gate_y


# ---------------------------------------------------------------- render --

def render(pieces, bbox, ca_rows, gate_y):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Rectangle, FancyArrowPatch
    from matplotlib.path import Path as MplPath

    x0, x1, y0, y1 = bbox
    scale = TOTAL_NS_MM / (y1 - y0)   # mm per Albers meter
    fp_w = (x1 - x0) * scale
    fp_h = (y1 - y0) * scale
    scale_denom = (1.0 / scale) * 1000.0  # ground mm per 1 mm paper

    def to_mm(geom):
        if geom.is_empty:
            return geom

        def f(coords):
            c = np.asarray(coords)
            return np.column_stack([(c[:, 0] - x0) * scale,
                                    (c[:, 1] - y0) * scale])
        return shapely.transform(geom, f)

    mm_pieces = {k: to_mm(g) for k, g in pieces.items() if not k.startswith("_")}

    ca_r0, ca_r1 = ca_rows
    ca_y1 = Y1 - ca_r0 * RES
    ca_y0 = Y1 - (ca_r1 + 1) * RES
    ca_top_mm = (ca_y1 - y0) * scale
    ca_bot_mm = (ca_y0 - y0) * scale
    ca_ns_mm = ca_top_mm - ca_bot_mm

    gate_mm = (gate_y - y0) * scale

    COLORS = {
        "mountains": base.COLORS[base.MOUNTAINS],
        "valley": base.COLORS[base.VALLEY],
        "desert": base.COLORS[base.DESERT],
        "coast": base.COLORS[base.COAST],
        "coast_land": base.COLORS[base.COAST],
        "islands": base.COLORS[base.COAST],  # islands land = coast-yellow
        "frame": FRAME_COLOR,
    }
    coast_rgb = base.COLORS[base.COAST]
    water_rgb = tuple(c + (1.0 - c) * WATER_MIX for c in coast_rgb)

    def draw_mp(ax, mp, color, lw=0.0, edgecolor="none", zorder=2):
        if mp.is_empty:
            return
        polys = mp.geoms if hasattr(mp, "geoms") else [mp]
        verts, codes = [], []
        for p in polys:
            for ring in [p.exterior, *p.interiors]:
                arr = np.asarray(ring.coords)
                verts.append(arr)
                codes.append([MplPath.MOVETO] + [MplPath.LINETO] * (len(arr) - 1))
        path = MplPath(np.concatenate(verts), np.concatenate(codes))
        ax.add_patch(PathPatch(path, facecolor=color, edgecolor=edgecolor,
                               linewidth=lw, zorder=zorder))

    def draw_boundary(ax, mp, **kw):
        if mp.is_empty:
            return
        polys = mp.geoms if hasattr(mp, "geoms") else [mp]
        for p in polys:
            for ring in [p.exterior, *p.interiors]:
                arr = np.asarray(ring.coords)
                ax.plot(arr[:, 0], arr[:, 1], **kw)

    def plot_line(ax, ln, **kw):
        arr = np.asarray(ln.coords)
        mmx = (arr[:, 0] - x0) * scale
        mmy = (arr[:, 1] - y0) * scale
        ax.plot(mmx, mmy, **kw)

    fig = plt.figure(figsize=(13.5, 15.5), dpi=200)
    gs = fig.add_gridspec(2, 1, height_ratios=[5.3, 1.15], hspace=0.10)
    ax = fig.add_subplot(gs[0])
    axt = fig.add_subplot(gs[1])
    axt.axis("off")

    margin = 22.0
    bed = 256.0
    bx0 = (fp_w - bed) / 2.0
    by0 = (fp_h - bed) / 2.0
    ax.add_patch(Rectangle((bx0, by0), bed, bed, fill=False, linestyle="--",
                           edgecolor="#555555", linewidth=1.3, zorder=1))
    ax.text(bx0 + bed - 2, by0 + bed - 2, "256 mm print bed",
           ha="right", va="top", fontsize=9, color="#555555", style="italic")

    ax.add_patch(Rectangle((0, 0), fp_w, fp_h, fill=False,
                           edgecolor="black", linewidth=1.5, zorder=5))

    # Fill order: ONE continuous water tint for every drop of water in the
    # window first (ahl's correction), then non-CA land (frame) gray, then
    # the CA region palette on top, then the islands' own land patch in
    # the same yellow as the coast piece's land.
    draw_mp(ax, mm_pieces["water_all"], water_rgb, zorder=1)
    draw_mp(ax, mm_pieces["frame_land"], COLORS["frame"], zorder=2)
    draw_mp(ax, mm_pieces["mountains"], COLORS["mountains"], zorder=3)
    draw_mp(ax, mm_pieces["valley"], COLORS["valley"], zorder=3)
    draw_mp(ax, mm_pieces["desert"], COLORS["desert"], zorder=3)
    draw_mp(ax, mm_pieces["coast_land"], COLORS["coast_land"], zorder=3)
    draw_mp(ax, mm_pieces["island_land"], COLORS["islands"], zorder=4)

    # thin hint line at every land/water transition (coastlines proper --
    # not piece boundaries, just a legibility aid now that water is a
    # single flat color everywhere)
    draw_boundary(ax, mm_pieces["water_all"], color="#8a8a8a",
                 linewidth=0.35, zorder=5)

    # political borders (thin lines on the frame, for context)
    gj = json.loads((DATA / "p2_borders.geojson").read_text())
    win = box(x0, y0, x1, y1)
    for f in gj["features"]:
        g = shp_shape(f["geometry"]).intersection(win)
        if g.is_empty:
            continue
        parts = g.geoms if hasattr(g, "geoms") else [g]
        for ln in parts:
            if ln.geom_type != "LineString":
                continue
            arr = np.asarray(ln.coords)
            mmx = (arr[:, 0] - x0) * scale
            mmy = (arr[:, 1] - y0) * scale
            ax.plot(mmx, mmy, color="#333333", linewidth=0.55, zorder=6)

    # piece-parting lines: solid where the seam touches land anywhere
    # along its length (a real, informative edge -- interior CA borders,
    # state lines, or a piece boundary that follows an actual coastline);
    # dashed where the seam runs entirely through open water with land on
    # neither side (the coast/frame ocean-split gate line; the islands
    # piece's outline, which sits wholly inside coast-water).
    for ln in pieces["_parting_land_lines"]:
        plot_line(ax, ln, color="black", linewidth=0.9, zorder=7)
    for ln in pieces["_parting_water_lines"]:
        plot_line(ax, ln, color="black", linewidth=0.9,
                 linestyle=(0, (5, 3)), zorder=7)

    ax.text(2, gate_mm + 2, "coast/frame ocean-split boundary (dashed --\n"
           "follows the US-Mexico line extended west)",
           fontsize=7.5, color="#444444", va="bottom", zorder=7)

    def dim_h(y, x_a, x_b, label, off=8):
        ax.annotate("", xy=(x_b, y), xytext=(x_a, y),
                   arrowprops=dict(arrowstyle="<->", color="black", lw=1.0),
                   zorder=7)
        ax.text((x_a + x_b) / 2, y + 2.5, label, ha="center", va="bottom",
               fontsize=10, zorder=7)

    def dim_v(x, y_a, y_b, label, off=8):
        ax.annotate("", xy=(x, y_b), xytext=(x, y_a),
                   arrowprops=dict(arrowstyle="<->", color="black", lw=1.0),
                   zorder=7)
        ax.text(x + 3, (y_a + y_b) / 2, label, ha="left", va="center",
               fontsize=10, rotation=90, zorder=7)

    dim_h(-14, 0, fp_w, f"{fp_w:.1f} mm", off=0)
    dim_v(fp_w + 14, 0, fp_h, f"{fp_h:.1f} mm")
    dim_v(-30, ca_bot_mm, ca_top_mm, f"CA N-S {ca_ns_mm:.1f} mm")

    ax.set_xlim(min(bx0, -40) - 6, max(bx0 + bed, fp_w + 22) + 6)
    ax.set_ylim(min(by0, -14) - 6, max(by0 + bed, fp_h + 8) + 6)
    ax.set_aspect("equal")
    ax.set_xlabel("mm")
    ax.set_ylabel("mm")
    ax.set_title(
        "California topo puzzle -- P2 final-product layout proposal\n"
        f"scale 1:{scale_denom:,.0f}   (254 mm = 10 in)   "
        f"footprint {fp_w:.1f} x {fp_h:.1f} mm",
        fontsize=13)

    # --- legend / stats table -------------------------------------------
    def stats(name, geom):
        parts = geom.geoms if hasattr(geom, "geoms") else [geom]
        parts = [p for p in parts if not p.is_empty]
        n = len(parts)
        area_cm2 = geom.area / 100.0
        minx, miny, maxx, maxy = geom.bounds
        return name, n, area_cm2, maxx - minx, maxy - miny

    rows = [
        stats("Coast (land+water)", mm_pieces["coast"]),
        stats("  └ land", mm_pieces["coast_land"]),
        stats("  └ water", mm_pieces["coast_water"]),
        stats("Mountains", mm_pieces["mountains"]),
        stats("Valley", mm_pieces["valley"]),
        stats("Desert", mm_pieces["desert"]),
        stats("Islands", mm_pieces["islands"]),
        stats("Frame", mm_pieces["frame"]),
    ]
    swatches = ["coast", None, None, "mountains", "valley", "desert",
                "islands", "frame"]
    col_x = [0.005, 0.34, 0.45, 0.66, 0.83, 1.0]
    col_labels = ["Piece", "Parts", "Area (cm²)", "W (mm)", "H (mm)"]
    col_align = ["left", "center", "center", "center", "center"]

    axt.set_xlim(0, 1)
    axt.set_ylim(0, 1)
    axt.axis("off")
    axt.set_title("Piece inventory (bboxes are axis-aligned; parts counted "
                 "with shapely)", fontsize=10.5, pad=6)

    n_rows = len(rows) + 1  # + header
    row_h = 1.0 / n_rows

    def row_y(i):
        return 1.0 - (i + 0.5) * row_h

    for j, lab in enumerate(col_labels):
        xc = (col_x[j] + col_x[j + 1]) / 2 if col_align[j] != "left" else col_x[j]
        axt.text(xc, row_y(0), lab, ha=col_align[j], va="center",
                 fontsize=10.5, fontweight="bold")
    axt.plot([0, 1], [1 - row_h, 1 - row_h], color="black", linewidth=0.8)
    axt.plot([0, 1], [1, 1], color="black", linewidth=0.8)

    for i, ((n, p, a, w, h), key) in enumerate(zip(rows, swatches)):
        y = row_y(i + 1)
        if key:
            col = COLORS.get(key, water_rgb if key == "coast_water" else (1, 1, 1))
            axt.add_patch(Rectangle((0, 1 - (i + 2) * row_h), 1, row_h,
                                    facecolor=col + (0.35,), edgecolor="none",
                                    zorder=0))
        cells = [n, str(p), f"{a:,.1f}", f"{w:.1f}", f"{h:.1f}"]
        for j, (val, align) in enumerate(zip(cells, col_align)):
            xc = (col_x[j] + col_x[j + 1]) / 2 if align != "left" else col_x[j]
            axt.text(xc, y, val, ha=align, va="center", fontsize=10)
        axt.plot([0, 1], [1 - (i + 2) * row_h, 1 - (i + 2) * row_h],
                 color="#bbbbbb", linewidth=0.6)
    for x in col_x:
        axt.plot([x, x], [0, 1], color="#bbbbbb", linewidth=0.6)
    axt.add_patch(Rectangle((0, 0), 1, 1, fill=False, edgecolor="black",
                            linewidth=0.8))
    axt.text(0.0, -0.05,
             "Coast, Islands, and Frame are each two-color prints (layer-"
             "swap at the datum): the universal water tint below/at 2 mm, "
             "region color (coast/islands: yellow; frame: gray) above.  "
             "Solid piece-parting lines run through land; dashed "
             "piece-parting lines run entirely through open water.",
             fontsize=8.5, ha="left", va="top", color="#333333", wrap=True)

    fig.savefig(OUT / "p2_layout.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p2_layout.png'}")
    return rows


def main():
    pieces, bbox, ca_rows, gate_y = build_layout()

    print("\n--- connectivity / composition checks ---")
    for name in ("coast", "mountains", "valley", "desert", "islands", "frame"):
        g = pieces[name]
        n = len(g.geoms) if hasattr(g, "geoms") else 1
        print(f"  {name:10s}: {n} part(s), area {g.area / 1e6:,.1f} km^2")

    # islands cavity: the islands piece must sit entirely north of the
    # coast/frame ocean-split gate line (it's carved OUT of coast_water
    # by construction, so it never overlaps coast_water -- the real
    # check is that it doesn't spill onto CA mainland or south of the
    # gate, i.e. it only ever displaces open ocean).
    isl = pieces["islands"]
    isl_miny = isl.bounds[1]
    print(f"  islands piece min-y {isl_miny / 1000:.1f} km vs gate "
         f"{gate_y / 1000:.1f} km "
         f"({'north of gate, OK' if isl_miny >= gate_y else 'SOUTH OF GATE - CHECK'})")

    # no overlaps between pieces
    names = ["coast", "mountains", "valley", "desert", "islands", "frame"]
    max_olap = 0.0
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            olap = pieces[a].intersection(pieces[b]).area
            if olap > 1.0:
                print(f"  overlap {a} x {b}: {olap / 1e6:.4f} km^2")
            max_olap = max(max_olap, olap)
    print(f"  max pairwise overlap: {max_olap:.1f} m^2")

    x0, x1, y0, y1 = bbox
    union = shapely.union_all([pieces[n] for n in names])
    win = box(x0, y0, x1, y1)
    gap = win.area - union.area
    print(f"  window area {win.area / 1e6:,.1f} km^2, union of pieces "
         f"{union.area / 1e6:,.1f} km^2, gap {gap / 1e6:.2f} km^2 "
         f"({100 * gap / win.area:.4f}%)")

    render(pieces, bbox, ca_rows, gate_y)


if __name__ == "__main__":
    main()
