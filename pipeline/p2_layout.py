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
approval (NOTES.md D2, D13, G6, G11).

Composition drawn (ahl's revised design, supersedes the six-piece coast/
islands/frame split): FOUR physical pieces tiling the D13 window.

  1. FRAME (one piece) = everything except the mountains/valley/desert
     cavities: every drop of ocean/bay water in the window (one
     continuous water tint, along the Oregon and Mexico coasts too),
     all non-CA land (Oregon/Nevada/Arizona/Mexico incl. Baja -- gray),
     the coastal-region land (data/p2_regions_smooth.geojson region=
     coast -- yellow), and the Channel Islands (also yellow) sitting on
     the water. No separate coast or islands piece, no ocean parting
     line -- it is all one printed part (3-color AMS multi-body: gray
     land / water tint / yellow coast+islands).
  2-4. MOUNTAINS, VALLEY, DESERT = their p2_regions_smooth.geojson
     polygons as-is, single color each -- removable pieces that drop
     into cavities in the frame. The cavity outlines (== the mutual
     boundaries among these three and the frame) are the only piece-
     parting lines, drawn bold black.

The D13 window = California's Census bbox (data/p2_land.npz ca_mask)
padded 40 km on N/E/S and 67.5 km of open Pacific on the W (same padding
p15_engraved.py uses), scaled so the window's total N-S extent =
config.toml [output].total_ns_mm (254 mm).

The frame's internal land/water coloring (which of its own territory
is gray vs. yellow vs. water) is derived by rasterizing the exact CA
region vectors + the islands hull back onto the DEM grid within the
window, classifying the remainder as land or water from data/p2_land.npz,
and re-vectorizing with the same corner-grid arc extraction
p2_vectorize.py uses for the canonical geometry -- then a light
Douglas-Peucker simplify for a clean print-quality line at this scale.
This is a cosmetic fill/outline distinction only; it does not create a
piece boundary.

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
                     # the window, regardless of where it sits


# ------------------------------------------------------------- geometry --

def load_regions():
    gj = json.loads((DATA / "p2_regions_smooth.geojson").read_text())
    out = {}
    for f in gj["features"]:
        out[f["properties"]["region"]] = shp_shape(f["geometry"])
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
# so it can vectorize the window-local land/water classification.)

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
    # without this, union_all/difference below produce degenerate slivers
    # of near-zero area at the shared-border vertices.
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

    shape_full = (META["height"], META["width"])
    islands_m = rasterize_mp(regions["islands"], shape_full)[r0:r1, c0:c1]

    land_mask = np.load(DATA / "p2_land.npz")["land_mask"][r0:r1, c0:c1]
    # data/p2_land.npz's land_mask is the RAW Census/NE land model; every
    # disconnected sub-printable speck it carries (coastal rocks,
    # skerries) was already dropped from the region polygons by
    # p2_vectorize.py's MIN_ISLAND_PX contract, so treating them as land
    # here would scatter tiny orphan islets through the water. Fold every
    # land component except the mainland and the Channel Islands back
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

    # --- the three removable cavities + the frame (pure complement) --
    win_rect = box(x0, y0, x1, y1)
    frame_piece = win_rect
    for g in (regions["mountains"], regions["valley"], regions["desert"]):
        frame_piece = shapely.difference(frame_piece, g, grid_size=1.0)
    if frame_piece.geom_type == "Polygon":
        frame_piece = shapely.MultiPolygon([frame_piece])
    frame_piece, dropped_n, dropped_km2 = keep_largest(frame_piece)
    if dropped_n:
        print(f"  frame: dropped {dropped_n} numerical sliver(s) "
             f"totaling {dropped_km2:.4f} km^2 (GEOS boolean-op noise)")

    # --- cosmetic fill/outline split of the frame: water vs. land -----
    # Vectorize the whole window's sea (ungated, unexcluded -- so it
    # already has a correctly-shaped hole for every land mass, including
    # the Channel Islands and out-of-state land), clean it against the
    # exact CA-mainland vectors the same way p2_vectorize builds shared
    # borders, and use it to split the frame into its water and land
    # sub-areas. This is a fill-color distinction only -- NOT a piece
    # boundary (ahl: no ocean/land parting line).
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

    island_land = regions["islands"].difference(water_all)
    if island_land.geom_type == "Polygon":
        island_land = shapely.MultiPolygon([island_land])
    frame_gray = frame_piece.difference(water_all) \
        .difference(regions["coast"]).difference(island_land)
    if frame_gray.geom_type == "Polygon":
        frame_gray = shapely.MultiPolygon([frame_gray])

    pieces = {
        "frame": frame_piece,
        "mountains": regions["mountains"],
        "valley": regions["valley"],
        "desert": regions["desert"],
        # cosmetic-only fill sub-areas of the frame (not pieces):
        "water_all": water_all,
        "coast_land": regions["coast"],
        "island_land": island_land,
        "frame_gray": frame_gray,
    }
    # pinhole-sized (few m^2) interior rings from the polygonize round trip
    # would otherwise render as a stray dot at print resolution
    pieces = {k: drop_tiny_holes(g) for k, g in pieces.items()}

    bbox = (x0, x1, y0, y1)
    return pieces, bbox, ca_rows


# ---------------------------------------------------------------- render --

def render(pieces, bbox, ca_rows):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import PathPatch, Rectangle
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

    mm_pieces = {k: to_mm(g) for k, g in pieces.items()}

    ca_r0, ca_r1 = ca_rows
    ca_y1 = Y1 - ca_r0 * RES
    ca_y0 = Y1 - (ca_r1 + 1) * RES
    ca_top_mm = (ca_y1 - y0) * scale
    ca_bot_mm = (ca_y0 - y0) * scale
    ca_ns_mm = ca_top_mm - ca_bot_mm

    COLORS = {
        "mountains": base.COLORS[base.MOUNTAINS],
        "valley": base.COLORS[base.VALLEY],
        "desert": base.COLORS[base.DESERT],
        "coast": base.COLORS[base.COAST],       # coast+islands yellow
        "frame": FRAME_COLOR,                   # non-CA land gray
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

    fig = plt.figure(figsize=(13.5, 15.5), dpi=200)
    gs = fig.add_gridspec(2, 1, height_ratios=[5.3, 1.0], hspace=0.10)
    ax = fig.add_subplot(gs[0])
    axt = fig.add_subplot(gs[1])
    axt.axis("off")

    bed = 256.0
    bx0 = (fp_w - bed) / 2.0
    by0 = (fp_h - bed) / 2.0
    ax.add_patch(Rectangle((bx0, by0), bed, bed, fill=False, linestyle="--",
                           edgecolor="#555555", linewidth=1.3, zorder=1))
    ax.text(bx0 + bed - 2, by0 + bed - 2, "256 mm print bed",
           ha="right", va="top", fontsize=9, color="#555555", style="italic")

    ax.add_patch(Rectangle((0, 0), fp_w, fp_h, fill=False,
                           edgecolor="black", linewidth=1.5, zorder=5))

    # Frame fill, cosmetic sub-areas only (no piece boundary among
    # them): water tint everywhere wet, gray on non-CA land, yellow on
    # the coastal-region land and the Channel Islands.
    draw_mp(ax, mm_pieces["water_all"], water_rgb, zorder=1)
    draw_mp(ax, mm_pieces["frame_gray"], COLORS["frame"], zorder=2)
    draw_mp(ax, mm_pieces["coast_land"], COLORS["coast"], zorder=3)
    draw_mp(ax, mm_pieces["island_land"], COLORS["coast"], zorder=3)
    # the three removable pieces, project palette
    draw_mp(ax, mm_pieces["mountains"], COLORS["mountains"], zorder=4)
    draw_mp(ax, mm_pieces["valley"], COLORS["valley"], zorder=4)
    draw_mp(ax, mm_pieces["desert"], COLORS["desert"], zorder=4)

    # thin hint line at every land/water transition within the frame
    # (coastlines proper -- not a piece boundary, just a legibility aid
    # now that water is a single flat color everywhere)
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

    # piece-parting lines: the ONLY ones are the three cavity outlines
    # (mountains/valley/desert boundaries, whether against each other or
    # against the frame) -- bold black, drawn on top of everything.
    for key in ("mountains", "valley", "desert"):
        draw_boundary(ax, mm_pieces[key], color="black", linewidth=1.1,
                     zorder=7)

    def dim_h(y, x_a, x_b, label):
        ax.annotate("", xy=(x_b, y), xytext=(x_a, y),
                   arrowprops=dict(arrowstyle="<->", color="black", lw=1.0),
                   zorder=8)
        ax.text((x_a + x_b) / 2, y + 2.5, label, ha="center", va="bottom",
               fontsize=10, zorder=8)

    def dim_v(x, y_a, y_b, label):
        ax.annotate("", xy=(x, y_b), xytext=(x, y_a),
                   arrowprops=dict(arrowstyle="<->", color="black", lw=1.0),
                   zorder=8)
        ax.text(x + 3, (y_a + y_b) / 2, label, ha="left", va="center",
               fontsize=10, rotation=90, zorder=8)

    dim_h(-14, 0, fp_w, f"{fp_w:.1f} mm")
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
    def stats(geom):
        parts = geom.geoms if hasattr(geom, "geoms") else [geom]
        parts = [p for p in parts if not p.is_empty]
        n = len(parts)
        area_cm2 = geom.area / 100.0
        minx, miny, maxx, maxy = geom.bounds
        return n, area_cm2, maxx - minx, maxy - miny

    rows = [
        ("Frame", *stats(mm_pieces["frame"]),
         "3-color AMS multi-body: gray land / water tint / yellow coast+islands",
         None),
        ("Mountains", *stats(mm_pieces["mountains"]),
         "single color (magenta)", "mountains"),
        ("Valley", *stats(mm_pieces["valley"]),
         "single color (green)", "valley"),
        ("Desert", *stats(mm_pieces["desert"]),
         "single color (orange)", "desert"),
    ]
    col_x = [0.005, 0.17, 0.25, 0.37, 0.46, 0.55, 1.0]
    col_labels = ["Piece", "Parts", "Area (cm²)", "W (mm)", "H (mm)", "Colors"]
    col_align = ["left", "center", "center", "center", "center", "left"]

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
        xc = col_x[j] if col_align[j] == "left" else (col_x[j] + col_x[j + 1]) / 2
        axt.text(xc, row_y(0), lab, ha=col_align[j], va="center",
                 fontsize=10.5, fontweight="bold")
    axt.plot([0, 1], [1 - row_h, 1 - row_h], color="black", linewidth=0.8)
    axt.plot([0, 1], [1, 1], color="black", linewidth=0.8)

    for i, (name, n, a, w, h, colors_txt, key) in enumerate(rows):
        y = row_y(i + 1)
        if key:
            axt.add_patch(Rectangle((0, 1 - (i + 2) * row_h), 1, row_h,
                                    facecolor=COLORS[key] + (0.35,),
                                    edgecolor="none", zorder=0))
        else:
            # frame: multi-color -- three small swatches instead of a
            # solid row tint
            sw_y = 1 - (i + 1.5) * row_h
            for k, col in enumerate((COLORS["frame"], water_rgb,
                                     COLORS["coast"])):
                axt.add_patch(Rectangle((col_x[0] - 0.003 + k * 0.02,
                                        sw_y - 0.10 * row_h),
                                        0.016, 0.20 * row_h,
                                        facecolor=col, edgecolor="#888888",
                                        linewidth=0.4, zorder=1))
        cells = [name, str(n), f"{a:,.1f}", f"{w:.1f}", f"{h:.1f}", colors_txt]
        for j, (val, align) in enumerate(zip(cells, col_align)):
            xc = col_x[j] if align == "left" else (col_x[j] + col_x[j + 1]) / 2
            xoff = 0.075 if (j == 0 and key is None) else 0
            axt.text(xc + xoff, y, val, ha=align, va="center", fontsize=10,
                     zorder=2)
        axt.plot([0, 1], [1 - (i + 2) * row_h, 1 - (i + 2) * row_h],
                 color="#bbbbbb", linewidth=0.6)
    for x in col_x:
        axt.plot([x, x], [0, 1], color="#bbbbbb", linewidth=0.6)
    axt.add_patch(Rectangle((0, 0), 1, 1, fill=False, edgecolor="black",
                            linewidth=0.8))
    axt.text(0.0, -0.06,
             "Mountains, Valley, and Desert are removable single-color "
             "pieces that drop into cavities in the Frame. Bold black "
             "lines are the only piece-parting lines (the cavity "
             "outlines); the thin gray coastline hint inside the "
             "Frame is a fill-color seam, not a piece boundary.",
             fontsize=8.5, ha="left", va="top", color="#333333", wrap=True)

    fig.savefig(OUT / "p2_layout.png", bbox_inches="tight")
    print(f"wrote {OUT / 'p2_layout.png'}")
    return rows


def main():
    pieces, bbox, ca_rows = build_layout()

    print("\n--- connectivity / composition checks ---")
    for name in ("frame", "mountains", "valley", "desert"):
        g = pieces[name]
        n = len(g.geoms) if hasattr(g, "geoms") else 1
        print(f"  {name:10s}: {n} part(s), area {g.area / 1e6:,.1f} km^2")

    names = ["frame", "mountains", "valley", "desert"]
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

    render(pieces, bbox, ca_rows)


if __name__ == "__main__":
    main()
