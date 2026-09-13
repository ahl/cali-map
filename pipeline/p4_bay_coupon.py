# /// script
# requires-python = ">=3.11,<3.14"
# dependencies = [
#   "numpy",
#   "scipy",
#   "pillow",
#   "pyproj",
#   "matplotlib",
#   "trimesh",
#   "shapely",
#   "scikit-image",
#   "triangle",
# ]
# ///
"""P4: Bay Area fit coupon (speculative, parallel with P1.5/P2).

The Bay Area is where Coast, Mountains and Valley interlock, so it is the
ideal puzzle-fit test. This script cuts a SQUARE WINDOW around the
Coast/Mountains/Valley triple junction near the Carquinez Strait and emits
one printable piece mesh per region present in the window, at FINAL-MODEL
scale, for two candidate final sizes. The user prints these to dial in the
PLA puzzle fit (snug but disassemblable, G3).

Regions are REGENERATED from p1_regions.build_regions with the current
config.toml (25 m threshold + 13 km band, all rules) — no stale .npy.

Geometry rules:
  - window faces: straight vertical cuts, NO clearance;
  - interior (piece/piece) borders: each piece shrunk by CLEARANCE_MM
    per side -> 2x that as the assembled gap;
  - Coast piece includes all sea/bay cells in the window as a flat shelf
    at datum height (D2);
  - flat bottom z=0, base BASE_MM thick, ocean surface = top of base,
    land top = base + elev * z-scale (Z_EXAG x true vertical scale).

Outputs:
  out/p4_bay_235mm/<region>.stl   binary STL, watertight
  out/p4_bay_420mm/<region>.stl
  out/p4_preview.png              assembled + junction zoom + exploded
"""

import hashlib
import json
import sys
import tempfile
from pathlib import Path

import numpy as np
import trimesh
import triangle as tr
from scipy import ndimage
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.ops import polylabel
from shapely import affinity
from skimage import measure

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base

# ------------------------------------------------------------------ params
# CA mainland N-S print extent per variant (mm) -> implied scale
VARIANTS = {"235mm": 235.0, "420mm": 420.0}
WINDOW_MM = 80.0          # square coupon window, print mm, both variants
# window center in CA Albers km, per variant (triple junction ~(-190, +5))
# 235mm: window reaches around the valley's north tip (y~302 km) so the
# western Coast Range mountains stay connected to the Sierra in-window and
# the real coast/mountains band border is part of the coupon; Carquinez
# triple junction sits near the south edge. 420mm: junction-centered.
CENTER_KM = {"235mm": (-165.0, 130.0), "420mm": (-170.0, 5.0)}
PX_MM = 0.05              # print-space raster resolution (mm/px)
CLEARANCE_MM = 0.15       # shrink per piece side; assembled gap = 2x this
PAD_MM = 3.0              # analysis pad beyond the window (edge-replicated)
BASE_MM = 2.0             # solid base under everything; ocean top = base
Z_EXAG = 2.5              # vertical exaggeration over true scale
MAX_TRI_AREA_MM2 = 0.08   # terrain triangulation density
MIN_FEATURE_MM = 1.0      # slivers narrower than this are dropped
SIMPLIFY_MM = 0.02        # polygon simplification tolerance
EDT_SMOOTH_PX = 0.8       # gaussian on the distance field (anti-jaggies)

CLEAR_PX = CLEARANCE_MM / PX_MM            # 3.0 px
PAD_PX = int(round(PAD_MM / PX_MM))        # 60 px
N_PX = int(round(WINDOW_MM / PX_MM))       # 1600 px

REGION_NAME = {base.MOUNTAINS: "mountains", base.VALLEY: "valley",
               base.DESERT: "desert", base.COAST: "coast"}
SEA_COLOR = (0.55, 0.68, 0.80)

ROOT = base.ROOT
OUT = ROOT / "out"


# ------------------------------------------------------- region generation
def load_regions(dem):
    """Regenerate the region raster from config + p1_regions (cached in the
    system temp dir, keyed on the [regions] config, so iteration is fast;
    a cold run always regenerates from source)."""
    key = hashlib.md5((json.dumps(base.CFG, sort_keys=True)
                       + json.dumps(base.META, sort_keys=True)
                       + "p4v1").encode()).hexdigest()[:12]
    cache = Path(tempfile.gettempdir()) / f"p4_regions_{key}.npz"
    if cache.exists():
        z = np.load(cache)
        print(f"[regions] cache hit {cache}")
        return z["reg"], z["sea"].astype(bool)
    print("[regions] regenerating from p1_regions.build_regions ...")
    prov, name_id = base.rasterize_provinces()
    sea = base.ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea)
    reg, _ = base.build_regions(
        dem, prov, name_id, base.CFG["coast_threshold_m"],
        band_km=base.CFG["coast_band_km"], shore_dist=shore_dist)
    np.savez_compressed(cache, reg=reg, sea=sea)
    return reg, sea


def ns_extent_m(reg, sea):
    """CA mainland north-south extent in meters (islands excluded)."""
    lab, _ = ndimage.label(~sea)
    mainland = lab == np.argmax(np.bincount(lab[~sea].ravel()))
    rows = np.where(((reg > 0) & mainland).any(axis=1))[0]
    return (rows[-1] - rows[0] + 1) * base.META["res"]


# ------------------------------------------------------------ window build
def window_rasters(reg, sea, dem, s, cx, cy):
    """Resample region/sea/dem onto the window print grid (N_PX square,
    PX_MM/px). Nearest-neighbor for masks, bilinear for the DEM."""
    x_mm = (np.arange(N_PX) + 0.5) * PX_MM
    y_mm = WINDOW_MM - (np.arange(N_PX) + 0.5) * PX_MM
    gx = cx + (x_mm - WINDOW_MM / 2) / (s * 1000.0)   # ground meters
    gy = cy + (y_mm - WINDOW_MM / 2) / (s * 1000.0)
    cols = (gx - base.META["x_min"]) / base.META["res"] - 0.5
    rows = (base.META["y_max"] - gy) / base.META["res"] - 0.5
    C, R = np.meshgrid(cols, rows)
    regw = ndimage.map_coordinates(reg, [R, C], order=0, mode="nearest")
    seaw = ndimage.map_coordinates(sea.astype(np.uint8), [R, C],
                                   order=0, mode="nearest").astype(bool)
    demw = ndimage.map_coordinates(dem.astype(np.float32), [R, C],
                                   order=1, mode="nearest")
    return regw, seaw, demw


def fill_and_contiguity(regw, seaw, notes, s, cx, cy):
    def where_km(comp):
        rows, cols = np.where(comp)
        x0, x1 = cols.min() * PX_MM, cols.max() * PX_MM
        y1, y0 = (WINDOW_MM - rows.min() * PX_MM,
                  WINDOW_MM - rows.max() * PX_MM)
        f = lambda xm, ym: (
            (cx + (xm - WINDOW_MM / 2) / (s * 1000)) / 1000,
            (cy + (ym - WINDOW_MM / 2) / (s * 1000)) / 1000)
        (ax0, ay0), (ax1, ay1) = f(x0, y0), f(x1, y1)
        return (f"Albers x [{ax0:.0f}, {ax1:.0f}] km, "
                f"y [{ay0:.0f}, {ay1:.0f}] km")

    """(1) Land cells with no region (CGS gaps near Suisun) -> nearest
    region. (2) Every region = ONE in-window connected component; minor
    fragments are reassigned to the neighbor that borders them most
    (coast fragments touching sea are already shelf-connected, D2)."""
    unassigned = (regw == 0) & ~seaw
    if unassigned.any():
        _, (ri, ci) = ndimage.distance_transform_edt(
            regw == 0, return_indices=True)
        regw[unassigned] = regw[ri, ci][unassigned]
        notes.append(f"filled {unassigned.sum() * PX_MM**2:.1f} mm^2 of "
                     "no-region land holes by nearest region")
    for _ in range(4):
        changed = False
        for rid in (base.VALLEY, base.DESERT, base.MOUNTAINS, base.COAST):
            mask = (regw == rid) | (seaw if rid == base.COAST
                                    else np.zeros_like(seaw))
            lab, n = ndimage.label(mask)
            if n <= 1:
                continue
            sizes = np.bincount(lab.ravel())
            sizes[0] = 0
            main_id = sizes.argmax()
            for i in range(1, n + 1):
                if i == main_id:
                    continue
                comp = lab == i
                own = comp & (regw == rid)
                if not own.any():
                    continue          # a pure-sea fragment: nothing to move
                ring = ndimage.binary_dilation(comp) & ~comp
                vals = regw[ring]
                vals = vals[(vals != rid) & (vals != 0)]
                tgt = (np.bincount(vals).argmax() if len(vals)
                       else base.COAST)
                notes.append(
                    f"{REGION_NAME[rid]}: fragment "
                    f"{own.sum() * PX_MM**2:.1f} mm^2 -> {REGION_NAME[tgt]}"
                    f" ({where_km(own)})")
                regw[own] = tgt
                changed = True
        if not changed:
            break
    return regw


# -------------------------------------------------- polygon extraction
def mask_polygon(mask, erode_px):
    """Sub-pixel polygon of `mask` shrunk inward by erode_px pixels.

    Method: Euclidean distance transform of the (edge-replicated-padded)
    mask, lightly gaussian-smoothed, contoured at level erode_px + 0.5
    (EDT measures to outside pixel CENTERS, 0.5 px beyond the nominal
    pixel-edge border, hence the +0.5). Marching squares interpolates the
    crossing linearly -> boundary accuracy ~= +/-0.5 px (0.025 mm) before
    the SIMPLIFY_MM simplification. Padding is edge-replicated so window
    faces see no erosion; the clip to the window box makes them straight.
    """
    padded = np.pad(mask, PAD_PX, mode="edge")
    padded[0, :] = padded[-1, :] = False
    padded[:, 0] = padded[:, -1] = False
    field = ndimage.distance_transform_edt(padded)
    if EDT_SMOOTH_PX > 0:
        field = ndimage.gaussian_filter(field, EDT_SMOOTH_PX)
    rings = []
    for lp in measure.find_contours(field, erode_px + 0.5):
        if len(lp) < 4:
            continue
        xs = (lp[:, 1] - PAD_PX + 0.5) * PX_MM
        ys = WINDOW_MM - (lp[:, 0] - PAD_PX + 0.5) * PX_MM
        ring = Polygon(np.column_stack([xs, ys]))
        if not ring.is_valid:
            ring = ring.buffer(0)
        if ring.is_empty or ring.area < 0.02:
            continue
        rings.append(ring)
    if not rings:
        return None
    rings.sort(key=lambda r: r.area, reverse=True)
    geom = rings[0]
    for r in rings[1:]:                        # even-odd nesting
        geom = geom.symmetric_difference(r)
    geom = geom.intersection(box(0, 0, WINDOW_MM, WINDOW_MM))
    geom = geom.simplify(SIMPLIFY_MM, preserve_topology=True)
    parts = [g for g in getattr(geom, "geoms", [geom])
             if g.geom_type == "Polygon" and g.area > 1e-6]
    if not parts:
        return None
    return MultiPolygon(parts) if len(parts) > 1 else parts[0]


def clean_piece(poly, name, notes):
    """Drop sub-printable slivers; enforce one connected component."""
    parts = list(getattr(poly, "geoms", [poly]))
    kept = []
    for p in parts:
        if p.buffer(-MIN_FEATURE_MM / 2).is_empty:
            notes.append(f"{name}: dropped sliver {p.area:.2f} mm^2 "
                         f"(everywhere < {MIN_FEATURE_MM} mm wide)")
        else:
            kept.append(p)
    if not kept:
        return None
    if len(kept) > 1:
        kept.sort(key=lambda p: p.area, reverse=True)
        lost = sum(p.area for p in kept[1:])
        notes.append(f"{name}: NOT one component after clearance cut; "
                     f"kept largest, dropped {len(kept) - 1} parts "
                     f"({lost:.1f} mm^2 total) -- REVIEW")
    return kept[0]


def min_land_width(poly, step=0.05, cap=2.0):
    """Approximate narrowest local feature width: sweep morphological
    opening (buffer -d then +d). The removed residual counts as a REAL
    feature of width ~2d only if it is a coherent chunk — inscribed
    radius > 0.35 d (corner rounding gives ~0.29 d, boundary wiggle much
    less) and area > 0.25 mm^2. A split of the piece at depth d also
    means a ~2d-wide neck. Returns mm (cap means 'wider than cap')."""
    base_parts = len(list(getattr(poly, "geoms", [poly])))
    d = step
    while d <= cap / 2 + 1e-9:
        shrunk = poly.buffer(-d)
        if shrunk.is_empty:
            return 2 * d
        if len(list(getattr(shrunk, "geoms", [shrunk]))) > base_parts:
            return 2 * d
        residual = poly.difference(shrunk.buffer(d))
        for g in getattr(residual, "geoms", [residual]):
            if g.geom_type != "Polygon" or g.area < 0.25:
                continue
            try:
                pole = polylabel(g, 0.01)
                if pole.distance(g.boundary) > 0.35 * d:
                    return 2 * d
            except Exception:
                pass
        d += step
    return cap


# ------------------------------------------------------------------ meshes
def triangulate(poly):
    """Conforming constrained Delaunay of a shapely Polygon (holes ok),
    quality + max-area refined (Shewchuk Triangle)."""
    pts, segs, holes = [], [], []

    def add_ring(coords):
        c = np.asarray(coords)[:-1]
        keep = np.ones(len(c), bool)
        keep[1:] = np.linalg.norm(np.diff(c, axis=0), axis=1) > 1e-9
        c = c[keep]
        i0 = len(pts)
        pts.extend(c.tolist())
        segs.extend([[i0 + k, i0 + (k + 1) % len(c)] for k in range(len(c))])

    add_ring(poly.exterior.coords)
    for h in poly.interiors:
        add_ring(h.coords)
        rp = Polygon(h).representative_point()
        holes.append([rp.x, rp.y])
    A = {"vertices": np.asarray(pts, float),
         "segments": np.asarray(segs, np.int32)}
    if holes:
        A["holes"] = np.asarray(holes, float)
    B = tr.triangulate(A, f"pq25a{MAX_TRI_AREA_MM2:.6f}")
    return B["vertices"], B["triangles"]


def solid_mesh(poly, height_fn):
    """Watertight solid: terrain top via height_fn, flat bottom at z=0,
    vertical walls along the triangulation boundary."""
    bodies = []
    for part in getattr(poly, "geoms", [poly]):
        v2, f = triangulate(part)
        # enforce CCW tops
        a = v2[f[:, 0]]
        cross = ((v2[f[:, 1]] - a)[:, 0] * (v2[f[:, 2]] - a)[:, 1]
                 - (v2[f[:, 1]] - a)[:, 1] * (v2[f[:, 2]] - a)[:, 0])
        f[cross < 0] = f[cross < 0][:, ::-1]
        nv = len(v2)
        ztop = height_fn(v2)
        verts = np.vstack([np.column_stack([v2, ztop]),
                           np.column_stack([v2, np.zeros(nv)])])
        edges = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        und = np.sort(edges, axis=1)
        _, inv, cnt = np.unique(und, axis=0, return_inverse=True,
                                return_counts=True)
        be = edges[cnt[inv] == 1]           # directed boundary edges (CCW)
        walls = np.vstack([
            np.column_stack([be[:, 0], be[:, 0] + nv, be[:, 1] + nv]),
            np.column_stack([be[:, 0], be[:, 1] + nv, be[:, 1]])])
        faces = np.vstack([f, f[:, ::-1] + nv, walls])
        bodies.append(trimesh.Trimesh(vertices=verts, faces=faces,
                                      process=False))
    return trimesh.util.concatenate(bodies) if len(bodies) > 1 else bodies[0]


def make_height_fn(dem, s, cx, cy):
    """(x_mm, y_mm) in window coords -> top z (mm). Sea (elev <= 0) sits at
    the datum = top of base; land rises at Z_EXAG x true vertical scale.
    Below-sea-level land (Delta islands) is clamped to the datum."""
    z_per_m = s * 1000.0 * Z_EXAG   # print mm per ground meter of elevation

    def h(xy):
        gx = cx + (xy[:, 0] - WINDOW_MM / 2) / (s * 1000.0)
        gy = cy + (xy[:, 1] - WINDOW_MM / 2) / (s * 1000.0)
        cols = (gx - base.META["x_min"]) / base.META["res"] - 0.5
        rows = (base.META["y_max"] - gy) / base.META["res"] - 0.5
        e = ndimage.map_coordinates(dem.astype(np.float32), [rows, cols],
                                    order=1, mode="nearest")
        return BASE_MM + np.maximum(e, 0.0) * z_per_m
    return h, z_per_m


# ----------------------------------------------------------------- variant
def triple_junction_mm(regw):
    """In-window centroid (mm) of cells where Coast, Valley and Mountains
    all meet within a 2-px dilation. None if absent."""
    d = lambda m: ndimage.binary_dilation(m, iterations=2)
    tj = (d(regw == base.COAST) & d(regw == base.VALLEY)
          & d(regw == base.MOUNTAINS))
    if not tj.any():
        return None
    r, c = ndimage.center_of_mass(tj)
    return ((c + 0.5) * PX_MM, WINDOW_MM - (r + 0.5) * PX_MM)


def build_variant(tag, target_mm, reg, sea, dem, extent_m):
    s = target_mm / (extent_m * 1000.0)          # print mm / ground mm
    cx, cy = (v * 1000.0 for v in CENTER_KM[tag])
    ground_km = WINDOW_MM / s / 1e6
    notes = []
    print(f"\n=== variant {tag}: scale 1:{1/s/1e6:.2f}M "
          f"(CA N-S {extent_m/1000:.0f} km -> {target_mm:.0f} mm), "
          f"window {ground_km:.0f} km sq @ Albers "
          f"({cx/1000:.0f}, {cy/1000:.0f}) km ===")

    regw, seaw, demw = window_rasters(reg, sea, dem, s, cx, cy)
    regw = fill_and_contiguity(regw, seaw, notes, s, cx, cy)
    hfn, z_per_m = make_height_fn(dem, s, cx, cy)
    land = ~seaw
    max_e = float(demw[land].max()) if land.any() else 0.0
    print(f"  z-scale {z_per_m:.5f} mm/m ({Z_EXAG:g}x true); max elev in "
          f"window {max_e:.0f} m -> land top {BASE_MM + max_e*z_per_m:.2f} mm"
          f" (base {BASE_MM:g} mm)")

    out_dir = OUT / f"p4_bay_{tag}"
    out_dir.mkdir(parents=True, exist_ok=True)
    pieces, stats = {}, {}
    for rid in (base.COAST, base.MOUNTAINS, base.VALLEY, base.DESERT):
        name = REGION_NAME[rid]
        mask = (regw == rid) | (seaw if rid == base.COAST
                                else np.zeros_like(seaw))
        area = mask.sum() * PX_MM ** 2
        if area < 4.0:
            if area > 0:
                notes.append(f"{name}: only {area:.1f} mm^2 in window; "
                             "skipped")
            continue
        poly = mask_polygon(mask, CLEAR_PX)
        poly = clean_piece(poly, name, notes) if poly else None
        if poly is None:
            notes.append(f"{name}: nothing printable left; skipped")
            continue
        mesh = solid_mesh(poly, hfn)
        path = out_dir / f"{name}.stl"
        mesh.export(path)                       # binary STL
        sea_poly = mask_polygon(seaw, 0.0) if rid == base.COAST else None
        land_poly = (poly.difference(sea_poly.buffer(0.02))
                     if sea_poly is not None else poly)
        mlw = (min_land_width(land_poly)
               if not land_poly.is_empty else float("nan"))
        bb = mesh.bounds
        stats[name] = dict(
            tris=len(mesh.faces), watertight=mesh.is_watertight,
            volume=float(mesh.volume), bbox=bb, min_land_w=mlw,
            area=poly.area)
        pieces[name] = (poly, sea_poly)
        print(f"  {name:9s} {len(mesh.faces):7d} tris  "
              f"watertight={mesh.is_watertight}  "
              f"bbox {bb[1][0]-bb[0][0]:.1f} x {bb[1][1]-bb[0][1]:.1f} x "
              f"{bb[1][2]:.2f} mm  min land width ~{mlw:.2f} mm  -> {path}")
        if not mesh.is_watertight:
            print(f"  !! {name} NOT WATERTIGHT")
    for n in notes:
        print(f"  note: {n}")
    return dict(tag=tag, s=s, cx=cx, cy=cy, ground_km=ground_km,
                pieces=pieces, stats=stats, notes=notes,
                tj=triple_junction_mm(regw), max_elev=max_e,
                z_per_m=z_per_m)


# ----------------------------------------------------------------- preview
def add_poly(ax, geom, color, ec="none", lw=0.0, alpha=1.0, z=1):
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    for p in getattr(geom, "geoms", [geom]):
        if p.geom_type != "Polygon" or p.is_empty:
            continue
        verts, codes = [], []
        for ring in [p.exterior, *p.interiors]:
            pts = np.asarray(ring.coords)
            verts.append(pts)
            codes += ([MPath.MOVETO] + [MPath.LINETO] * (len(pts) - 2)
                      + [MPath.CLOSEPOLY])
        ax.add_patch(PathPatch(MPath(np.vstack(verts), codes),
                               facecolor=color, edgecolor=ec, lw=lw,
                               alpha=alpha, zorder=z))


def render_preview(results):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rid_of = {v: k for k, v in REGION_NAME.items()}
    fig, axes = plt.subplots(2, 3, figsize=(16.5, 11.5), dpi=200)
    for row, res in enumerate(results):
        tj = res["tj"] or (WINDOW_MM / 2, WINDOW_MM / 2)
        for col, ax in enumerate(axes[row]):
            ax.set_facecolor("#1c1c22")
            explode = col == 2
            for name, (poly, sea_poly) in res["pieces"].items():
                color = base.COLORS[rid_of[name]]
                g, sg = poly, sea_poly
                if explode:
                    c = poly.centroid
                    v = np.array([c.x - WINDOW_MM / 2, c.y - WINDOW_MM / 2])
                    n = np.linalg.norm(v)
                    dx, dy = (v / n * 7.0) if n > 1e-6 else (0, 7.0)
                    g = affinity.translate(g, dx, dy)
                    if sg is not None:
                        sg = affinity.translate(sg, dx, dy)
                add_poly(ax, g, color)
                if sg is not None:
                    add_poly(ax, g.intersection(sg), SEA_COLOR, z=2)
                if explode:
                    c = g.centroid
                    ax.annotate(name, (c.x, c.y), color="black", fontsize=9,
                                ha="center", weight="bold", zorder=5)
            if col == 0:
                ax.set_xlim(-2, WINDOW_MM + 2)
                ax.set_ylim(-2, WINDOW_MM + 2)
                ax.set_title(
                    f"{res['tag']}  (1:{1/res['s']/1e6:.2f}M)  assembled — "
                    f"{res['ground_km']:.0f} km window @ "
                    f"({res['cx']/1e3:.0f}, {res['cy']/1e3:.0f}) km Albers",
                    fontsize=10)
                ax.plot(*tj, "w+", ms=8, zorder=6)
            elif col == 1:
                ax.set_xlim(tj[0] - 6, tj[0] + 6)
                ax.set_ylim(tj[1] - 6, tj[1] + 6)
                ax.set_title(f"triple junction zoom (12 mm) — gaps = "
                             f"2 x {CLEARANCE_MM:g} mm", fontsize=10)
            else:
                ax.set_xlim(-14, WINDOW_MM + 14)
                ax.set_ylim(-14, WINDOW_MM + 14)
                ax.set_title("exploded (+7 mm)", fontsize=10)
            ax.set_aspect("equal")
            ax.set_xticks([]), ax.set_yticks([])
    fig.suptitle(
        "P4 Bay Area fit coupon — clearance "
        f"{CLEARANCE_MM:g} mm/side, base {BASE_MM:g} mm, "
        f"Z = {Z_EXAG:g}x true scale  "
        "(magenta=Mountains, green=Valley, yellow=Coast, blue=shelf)",
        fontsize=12)
    fig.tight_layout()
    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / "p4_preview.png", bbox_inches="tight",
                facecolor="white")
    print(f"\nwrote {OUT / 'p4_preview.png'}")


def main():
    dem = np.load(base.DATA / "dem_ca_albers_250m.npy")
    reg, sea = load_regions(dem)
    extent_m = ns_extent_m(reg, sea)
    print(f"CA mainland N-S extent: {extent_m/1000:.1f} km")
    results = [build_variant(tag, mm, reg, sea, dem, extent_m)
               for tag, mm in VARIANTS.items()]
    render_preview(results)
    print(f"\nclearance method: sub-pixel EDT contour on a {PX_MM} mm/px "
          f"raster, offset {CLEAR_PX:g} px = {CLEARANCE_MM:g} mm/side "
          f"(assembled gap {2*CLEARANCE_MM:g} mm). Accuracy: half-pixel "
          "center offset corrected analytically (level = px + 0.5); "
          "gaussian smoothing acts on a unit-gradient field (no bias on "
          "straight borders); residual local error = contour "
          f"interpolation (~+/-{PX_MM/2:g} mm) + simplify tolerance "
          f"({SIMPLIFY_MM:g} mm) => border position within ~+/-0.045 mm "
          "worst case, typically +/-0.02 mm. Window faces: no clearance.")


if __name__ == "__main__":
    main()
