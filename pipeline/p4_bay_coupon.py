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
#   "py-lib3mf",
# ]
# ///
"""P4 v2: Bay Area mini-frame coupon — a miniature of the final product.

One build at the FINAL product scale (config [output].total_ns_mm over the
D13 window; see p2_layout.py): a ~100 mm square Bay Area window plus an
~8 mm artificial gray rim (the non-CA-land stand-in) -> ~116 mm print.

The FRAME is a TRAY (one fixed part, 3-color Bambu 3MF per NOTES-3mf.md):
  - a continuous floor (FLOOR_MM) under the ENTIRE footprint, including
    under the removable pieces — cavities are recesses, not through-holes;
  - the RIM_MM band around the inner window is REAL GEOGRAPHY (ahl's
    correction): the map content simply continues ~36 km beyond the
    window on all sides. Band LAND = the gray body, real topography at
    the same G2 z-scale; band WATER = more water, flat at datum,
    continuous with the inner water out to the print edge (so gray
    appears only on sides where the band actually contains land);
  - water body (filament 2) = the floor everywhere + everything up to the
    water surface (BASE_MM above the bottom) outside the cavities: all
    sea/bay flat at datum, and the sub-datum volume under coast and gray
    land (D14: below datum prints in water color);
  - coast body (filament 1) = coastal-region land terrain (yellow) INSIDE
    the inner window, real topography from datum up, with a small
    LAND_MIN_MM visibility floor;
  - gray body (filament 3) = ALL land in the outer band regardless of its
    geographic region, same terrain treatment. The inner/outer boundary
    on land is purely a color boundary between bodies (coincident
    vertical walls, like the CA state line on the final product) — not a
    physical wall or groove;
  - CAVITIES for Mountains and Valley at their NOMINAL region outlines
    (pieces are cut at the inner-window edge; where a cavity edge lies on
    the window boundary its wall faces the gray band-land);
  - POKE-HOLES: two 8 mm circular through-holes in the floor under each
    removable piece (at deep-interior points) to push pieces out.

REMOVABLE PIECES (mountains.stl, valley.stl): slab = base - floor (they
rest ON the tray floor, so datum and terrain line up with the frame),
real terrain at the G2 z-scale (config [output].z_exaggeration x
horizontal scale — the normalized rule), VERTICAL walls with an optional
45-deg bottom chamfer ([print].bottom_chamfer_mm; 0 = off, slice with
elephant-foot compensation ON), clearance per side against the cavity
walls and against each other.

All physical print knobs (clearance, base, floor, chamfer, poke-hole
diameter, land-min) come from config [print], SHARED with the P5 final
build (p5_final.py) so coupon-validated tuning transfers 1:1.

VERSION STAMPS (version_stamp.py): every part's bottom layer carries a
mirrored debossed tag (0.4 mm deep) -- frame: "<tag> <date> <1:scale>
c<clearance>", pieces: "<tag> <date> MTN|VAL" -- so printed iterations
are identifiable in hand.  Tag = config [output].build_tag.  Gated by
[output].stamps_enabled (ahl 2026-09-14: currently FALSE -- the stamp
lettering is still wrong, so all parts get plain flat bottoms until
version_stamp.py is revisited).

Outputs:
  out/p4_mini/frame.3mf      4-5 bodies (coast, floor, water, gray, +
                             black if the compass rose is enabled) --
                             floor/water are two PARTS on one filament
                             (split so ironing can target the visible
                             water top without the hidden cavity floor)
                             filaments pre-assigned (Bambu)
  out/p4_mini/mountains.stl  binary STL, watertight
  out/p4_mini/valley.stl     binary STL, watertight
  out/p4_preview.png         assembled + exploded + cavity-edge zoom
                             + mirrored bottom view (version stamps)
(out/p4_bay_235mm and out/p4_bay_420mm are SUPERSEDED by this build.)
"""

import hashlib
import json
import sys
import tempfile
import tomllib
import uuid
import zipfile
from pathlib import Path

import numpy as np
import trimesh
import triangle as tr
from scipy import ndimage
from shapely.geometry import MultiPolygon, Point, Polygon, box
from shapely.ops import polylabel, unary_union
from shapely import affinity
from skimage import measure

sys.path.insert(0, str(Path(__file__).resolve().parent))
import p1_regions as base
import version_stamp as vstamp
import compass_art

# ------------------------------------------------------------------ params
WINDOW_MM = 100.0        # inner window (pieces + cavities), print mm
RIM_MM = 8.0             # real-geography band beyond the window (~36 km)
# Window center (CA Albers km): west/south of the Carquinez junction so
# the bay-wrapping Coast Range mountains are the DOMINANT mountains
# fragment (per ahl's sketch: SF Bay left-of-center, valley entering the
# NE) and the Sierra enters only as a minor east-edge strip.
CENTER_KM = (-190.0, -25.0)
PX_MM = 0.05             # print-space raster resolution (mm/px)
PAD_KM = 40.0            # D13 window pads (p2_layout.py)
WEST_PAD_KM = 67.5
MAX_TRI_AREA_MM2 = 0.08  # terrain triangulation density
MIN_FEATURE_MM = 1.0     # removable-piece slivers below this are dropped
MIN_COAST_PART_MM2 = 0.5  # coast-body crumbs below this are dropped
SIMPLIFY_MM = 0.02       # polygon simplification tolerance
EDT_SMOOTH_PX = 0.8      # gaussian on the distance field (anti-jaggies)
OVERLAP_MM = 0.05        # internal z-overlap of the water body's 2 solids

PAD_PX = 12
N_PX = int(round(WINDOW_MM / PX_MM))
RIM_PX = int(round(RIM_MM / PX_MM))
N_FP = N_PX + 2 * RIM_PX          # raster covers the full footprint

# Bambu filament slots (1-based; ahl maps AMS slots when slicing)
EXTRUDERS = {"coast": 1, "water": 2, "gray": 3, "black": 4}

REGION_NAME = {base.MOUNTAINS: "mountains", base.VALLEY: "valley",
               base.DESERT: "desert", base.COAST: "coast"}
WATER_RGB = (0.73, 0.82, 0.90)
GRAY_RGB = (0.80, 0.79, 0.76)

ROOT = base.ROOT
DATA = base.DATA
OUT = ROOT / "out"
OUT_DIR = OUT / "p4_mini"

_CFG_ALL = tomllib.loads((ROOT / "config.toml").read_text())
_OUTPUT_CFG = _CFG_ALL["output"]
TOTAL_NS_MM = _OUTPUT_CFG["total_ns_mm"]
BUILD_TAG = _OUTPUT_CFG.get("build_tag", "T0")
Z_EXAG = _OUTPUT_CFG["z_exaggeration"]   # G2 normalized rule
# Bottom version stamps (ahl 2026-09-14: disabled for now -- "the
# lettering on the bottom is still wrong; just remove it"): when false,
# every part gets a plain flat bottom and no version_stamp call is made.
STAMPS_ENABLED = _OUTPUT_CFG.get("stamps_enabled", True)

# Shared physical print knobs (config [print]): the coupon and the P5
# final build MUST read the same values so coupon-validated tuning
# transfers 1:1.
_PRINT_CFG = _CFG_ALL["print"]
CLEARANCE_MM = _PRINT_CFG["clearance_per_side_mm"]        # piece vs FRAME
CLEARANCE_PAIR_MM = _PRINT_CFG["clearance_pair_per_side_mm"]  # piece vs
                                           # piece shared borders
ENCLOSED_ZERO_CLEARANCE = _PRINT_CFG.get("enclosed_piece_zero_clearance",
                                         False)
# ahl 2026-09-14: the VALLEY is fully enclosed by the mountains in the
# real P5 layout (touches no frame -- only another removable piece), so
# under enclosed_piece_zero_clearance it contributes ZERO shrink on its
# own piece-facing walls; its neighbor's CLEARANCE_PAIR_MM does the
# WHOLE piece-piece gap. The coupon's valley DOES touch the window rim
# (frame) on some stretches, but that's already handled automatically:
# piece_polygon's d_frame field only ever counts an ACTUAL sibling piece
# as "other", so a valley/rim boundary is frame-facing (CLEARANCE_MM)
# regardless of this set -- only piece-pair stretches are affected.
# ahl 2026-09-15: a same-style change extending this to DESERT (so
# mountains is the sole clearance-contributor at both its piece-pair
# seams, for a mountains+desert snug-fit -- see NOTES.md) was tried and
# REVERTED as premature -- ahl wants to reason from the T1/T2 tolerance
# table first before touching desert's treatment. Revisit deliberately,
# not as a rider on the mountains-valley tuning work.
ZERO_CLEARANCE_PIECES = {"valley"}
BASE_MM = _PRINT_CFG["base_mm"]           # water surface above bottom
FLOOR_MM = _PRINT_CFG["floor_mm"]         # tray floor (D16)
CHAMFER_MM = _PRINT_CFG["bottom_chamfer_mm"]  # 45-deg piece bottom edge
POKE_D_MM = _PRINT_CFG["poke_hole_d_mm"]
RIB_INTERFERENCE_MM = _PRINT_CFG.get("rib_interference_mm", 0.0)
RIB_RADIUS_MM = _PRINT_CFG.get("rib_radius_mm", 0.4)
RIBS_PER_PIECE = _PRINT_CFG.get("ribs_per_piece", 4)
# config [print.ribs]: manual per-build-per-piece rib sites, keyed
# "p4_<piece>" / "p5_<piece>"; a missing/empty list = use the automatic
# placer for that piece (ahl 2026-09-15)
RIB_SITES_CFG = _PRINT_CFG.get("ribs", {})
LAND_MIN_MM = _PRINT_CFG["land_min_mm"]
COMPASS = _CFG_ALL.get("compass", {"enabled": False})
ROSE_STYLE = COMPASS.get("style", "raised")   # "flush" | "raised"
ROSE_DEPTH = COMPASS.get("depth_mm", COMPASS.get("relief_mm", 0.4))
PIECE_SLAB_MM = BASE_MM - FLOOR_MM   # piece base slab: rests on the floor
POKE_MARGIN_MM = 1.5     # extra margin between hole edge and cavity wall
CLEAR_PX = CLEARANCE_MM / PX_MM
CLEAR_PAIR_PX = CLEARANCE_PAIR_MM / PX_MM


def piece_pair_clear_px(name):
    """Piece-facing clearance CONTRIBUTED BY `name`'s own walls (pixels):
    a piece in ZERO_CLEARANCE_PIECES (when ENCLOSED_ZERO_CLEARANCE) is
    the exact nominal shape on every piece-facing stretch -- zero self-
    contribution, its neighbor's CLEAR_PAIR_PX does the entire gap.
    Every other piece (mountains, the only one NOT in the set)
    contributes the full CLEAR_PAIR_PX at every piece-pair seam it has."""
    if ENCLOSED_ZERO_CLEARANCE and name in ZERO_CLEARANCE_PIECES:
        return 0.0
    return CLEAR_PAIR_PX


def pair_gap_nominal_mm(name_a, name_b):
    """Expected TOTAL piece-piece gap at the name_a/name_b seam (mm):
    each side's own contribution (0 for the enclosed piece, else
    CLEARANCE_PAIR_MM), summed."""
    return (piece_pair_clear_px(name_a) + piece_pair_clear_px(name_b)) \
        * PX_MM


# ------------------------------------------------------- region generation
def load_regions(dem):
    """Regenerate the region raster from config + overrides + p1_regions
    (cached in the system temp dir; the key hashes config [regions] AND
    [overrides] AND the override geojson contents, so any knob or markup
    change forces regeneration)."""
    h = hashlib.md5()
    h.update(json.dumps(base.CFG, sort_keys=True).encode())
    h.update(json.dumps(base.OVR, sort_keys=True).encode())
    for group in ("mountain_edges", "region_marks"):
        for fp in base.OVR.get(group, []):
            h.update((ROOT / fp).read_bytes())
    h.update(json.dumps(base.META, sort_keys=True).encode())
    h.update(b"p4v3")
    cache = Path(tempfile.gettempdir()) / f"p4_regions_{h.hexdigest()[:12]}.npz"
    if cache.exists():
        z = np.load(cache)
        print(f"[regions] cache hit {cache}")
        return z["reg"], z["sea"].astype(bool)
    print("[regions] regenerating from p1_regions.build_regions "
          "(config + overrides) ...")
    prov, name_id = base.rasterize_provinces()
    sea = base.ocean_mask(dem)
    shore_dist = ndimage.distance_transform_edt(~sea)
    reg, _ = base.build_regions(
        dem, prov, name_id, base.CFG["coast_threshold_m"],
        band_km=base.CFG["coast_band_km"], shore_dist=shore_dist)
    np.savez_compressed(cache, reg=reg, sea=sea)
    return reg, sea


# ------------------------------------------------- scale + z (D13 + G2)
def d13_scale():
    """Final-product scale from p2_layout.py's derivation: the D13 window
    (Census CA bbox from data/p2_land.npz + 40 km N/E/S + 67.5 km ocean W)
    printed at [output].total_ns_mm N-S. Returns (s_mm_per_m, window
    slices on the source grid)."""
    ca_mask = np.load(DATA / "p2_land.npz")["ca_mask"]
    rows = np.nonzero(ca_mask.any(axis=1))[0]
    cols = np.nonzero(ca_mask.any(axis=0))[0]
    res = base.META["res"]
    pad = int(round(PAD_KM * 1000.0 / res))
    wpad = int(round(WEST_PAD_KM * 1000.0 / res))
    r0 = max(rows[0] - pad, 0)
    r1 = min(rows[-1] + 1 + pad, ca_mask.shape[0])
    c0 = max(cols[0] - wpad, 0)
    c1 = min(cols[-1] + 1 + pad, ca_mask.shape[1])
    ns_m = (r1 - r0) * res
    # s is UNITLESS: print mm per ground mm
    return TOTAL_NS_MM / (ns_m * 1000.0), (slice(r0, r1), slice(c0, c1)), ns_m


def g2_z_per_m(s):
    """G2 normalized rule (config [output].z_exaggeration): print z per
    meter of true elevation = z_exaggeration x horizontal scale.  s is
    the unitless print-mm-per-ground-mm scale; 1 m ground = 1000 mm."""
    return Z_EXAG * s * 1000.0


# ------------------------------------------------------------ window build
def window_rasters(reg, sea, dem, s, cx, cy):
    """Rasters over the FULL footprint (window + band), print grid."""
    x_mm = (np.arange(N_FP) + 0.5) * PX_MM - RIM_MM
    y_mm = WINDOW_MM + RIM_MM - (np.arange(N_FP) + 0.5) * PX_MM
    gx = cx + (x_mm - WINDOW_MM / 2) / (s * 1000.0)
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


def fill_and_contiguity(regw, seaw, notes, where_km, fill_mask=None):
    """(1) no-region land -> nearest region; (2) mountains/valley/desert =
    one component each (minor fragments -> most-bordering neighbor);
    coast fragments are fine (they anchor to the frame).  where_km(comp)
    -> human-readable location string (caller-supplied: the print->Albers
    mapping differs between the coupon and P5).  fill_mask limits step
    (1) to those cells (P5: only CA land gets a region; other land is
    the gray body)."""
    unassigned = (regw == 0) & ~seaw
    if fill_mask is not None:
        unassigned &= fill_mask
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
                    continue
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
def mask_polygon(mask, erode_px, origin_mm=0.0, clip=None):
    """Sub-pixel polygon of `mask` shrunk inward by erode_px pixels (0 =
    nominal outline). EDT of the zero-padded mask, gaussian-smoothed,
    contoured at erode_px + 0.5 (the +0.5 corrects EDT's measure-to-pixel-
    centers offset); accuracy ~+/-0.5 px (0.025 mm) before SIMPLIFY_MM.
    origin_mm: mm coordinate of the mask's lower-left corner (0 for
    window-indexed masks, -RIM_MM for footprint-indexed). clip: shapely
    box to intersect with (default = the inner window)."""
    if clip is None:
        clip = box(0, 0, WINDOW_MM, WINDOW_MM)
    span = mask.shape[0] * PX_MM
    padded = np.pad(mask, PAD_PX, mode="constant", constant_values=False)
    field = ndimage.distance_transform_edt(padded)
    if EDT_SMOOTH_PX > 0:
        field = ndimage.gaussian_filter(field, EDT_SMOOTH_PX)
    rings = []
    for lp in measure.find_contours(field, erode_px + 0.5):
        if len(lp) < 4:
            continue
        xs = (lp[:, 1] - PAD_PX + 0.5) * PX_MM + origin_mm
        ys = span + origin_mm - (lp[:, 0] - PAD_PX + 0.5) * PX_MM
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
    geom = geom.intersection(clip)
    geom = geom.simplify(SIMPLIFY_MM, preserve_topology=True)
    parts = [g for g in getattr(geom, "geoms", [geom])
             if g.geom_type == "Polygon" and g.area > 1e-6]
    if not parts:
        return None
    return MultiPolygon(parts) if len(parts) > 1 else parts[0]


def piece_polygon(mask, other_mask, c_frame_px, c_pair_px, clip=None):
    """Sub-pixel polygon of a removable PIECE, generalizing mask_polygon
    to two clearances: shrink by c_frame_px pixels along stretches facing
    the FRAME (anything that is not another removable piece -- coast,
    gray land, water, window/rim edge) and by c_pair_px pixels along
    stretches facing `other_mask` (the union of SIBLING removable-piece
    masks). T1 print finding: 0.15 mm/side vs the frame is the calibrated
    friction fit, but the same 0.15/side between two pieces doubles to a
    loose 0.30 mm total gap -- piece-piece borders get their own
    (smaller) [print].clearance_pair_per_side_mm instead (and the
    a piece in ZERO_CLEARANCE_PIECES may use 0 on its own piece-facing
    walls entirely -- see ENCLOSED_ZERO_CLEARANCE).

    Two-STAGE construction (an earlier one-shot version that combined a
    single continuous field via min(d_frame - c_frame_px, d_other -
    c_pair_px) and contoured its own zero crossing had a real bug: the
    field could dip NEGATIVE at pixels hugging the piece's own true edge
    whenever an offset was small (e.g. c_pair_px=0 for the enclosed
    piece), which collides with the fixed 0.0 assigned to background --
    mask_polygon's single-EDT field is never negative, so its 0-vs-
    positive floor is unambiguous, but ours could invert it, and it
    measurably corrupted the extracted contour: verified the valley
    piece grew ~28 mm^2 INTO the mountains' own nominal territory in the
    coupon. Fixed by never touching the continuous EDT arithmetic at
    all -- instead THRESHOLD each obstacle type into a plain binary
    raster (the same sub-pixel convention mask_polygon uses: keep a
    piece pixel only if its EDT distance to that obstacle is >=
    offset + 0.5), AND the two thresholded survivorships together, then
    hand the resulting (already correctly eroded) raster to the
    existing, proven mask_polygon(., 0.0) for the final sub-pixel
    contour/smooth/simplify pass -- so background is a plain False and
    interior is a plain non-negative EDT field again, exactly
    mask_polygon's own invariant.
      d_frame = EDT(mask | other_mask) -- distance to the nearest FRAME
                pixel, computed with siblings folded into the foreground
                so a nearby sibling never shortens it (the frame
                threshold "sees past" siblings to the real frame
                territory beyond);
      d_other = EDT(~other_mask)       -- distance to the nearest
                sibling pixel (0 on the siblings themselves).
    A pixel survives (stays in the effective mask) iff d_frame >=
    c_frame_px + 0.5 AND d_other >= c_pair_px + 0.5 -- an AND of two
    independent erosions, the discrete equivalent of the min() blend:
    where a stretch borders ONLY the frame, d_other is always large so
    only the frame threshold ever removes pixels there (behaves exactly
    like mask_polygon(mask, c_frame_px)); where a stretch borders ONLY a
    sibling, d_frame is large (it sees past the sibling) so only the
    pair threshold matters. At a piece-piece-frame triple point the two
    erosions blend through the AND with no seam/discontinuity. At
    c_frame_px == c_pair_px == 0 no pixel is ever removed (both
    thresholds are >= 0.5, and the closest a piece pixel can be to any
    non-piece pixel is exactly 1.0), so this is identical to
    mask_polygon(mask, 0.0, clip=clip). Pixels are PADDED by PAD_PX with
    False before either EDT (matching mask_polygon's own convention) so
    a piece touching the raw raster's own edge (e.g. the P4 coupon's
    window boundary, which is rasterized as its own bounded array with
    no cells beyond it) still sees genuine frame background just past
    that edge -- computing the EDT on the unpadded array would treat
    'off the edge' as simply not existing rather than as frame, so a
    piece flush with the array edge would wrongly get NO frame
    clearance there (verified: the coupon's south window edge, where
    both mountains and valley touch y=0, measured an exact 0.000 mm
    frame gap before this padding was added)."""
    pad = lambda a: np.pad(a, PAD_PX, mode="constant", constant_values=False)
    unpad = lambda a: a[PAD_PX:-PAD_PX, PAD_PX:-PAD_PX]
    eff = mask
    if c_frame_px > 0:
        frame_bg = ~(pad(mask) | pad(other_mask))
        d_frame = ndimage.distance_transform_edt(~frame_bg)
        eff = eff & unpad(d_frame >= c_frame_px + 0.5)
    if c_pair_px > 0:
        d_other = ndimage.distance_transform_edt(~pad(other_mask))
        eff = eff & unpad(d_other >= c_pair_px + 0.5)
    return mask_polygon(eff, 0.0, clip=clip)


def clean_piece(poly, name, notes):
    """Removable pieces: drop sub-printable slivers; one component."""
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


def _outward_normal(poly, p, tangent):
    """Unit normal at boundary point `p` of `poly`, pointing OUT of the
    polygon (tangent need not be unit or a particular orientation --
    tested with a tiny probe and flipped if it lands inside)."""
    tl = np.hypot(tangent[0], tangent[1])
    if tl < 1e-9:
        return (1.0, 0.0)
    tx, ty = tangent[0] / tl, tangent[1] / tl
    nx, ny = -ty, tx
    if poly.contains(Point(p.x + 0.01 * nx, p.y + 0.01 * ny)):
        nx, ny = -nx, -ny
    return (nx, ny)


def _ring_curvature(ring, length, d, window_mm=1.0):
    """Local turning angle (radians) of `ring` at arc-length `d`, between
    the chords approaching and leaving `d` over +/- window_mm -- a cheap
    straightness proxy (0 = dead straight, larger = sharper corner)."""
    p0 = ring.interpolate((d - window_mm) % length)
    p1 = ring.interpolate(d % length)
    p2 = ring.interpolate((d + window_mm) % length)
    v1 = np.array([p1.x - p0.x, p1.y - p0.y])
    v2 = np.array([p2.x - p1.x, p2.y - p1.y])
    n1, n2 = np.hypot(*v1), np.hypot(*v2)
    if n1 < 1e-9 or n2 < 1e-9:
        return 0.0
    cosang = float(np.clip(np.dot(v1, v2) / (n1 * n2), -1.0, 1.0))
    return abs(np.arccos(cosang))


MIN_RIB_WIDTH_MM = _PRINT_CFG.get("min_rib_width_mm", 1.5)
                          # ahl 2026-09-15: candidates where the piece's
                          # LOCAL width drops below this are never
                          # eligible for a crush rib (frame OR pair) --
                          # protects thin necks (e.g. the mountains spur
                          # just N of the SF Bay, ~0.8 mm, D11) from
                          # extra local interference, without touching
                          # the boundary geometry itself. Between the
                          # ~0.8 mm neck and the ~1.5-2.0 mm the piece
                          # otherwise measures.
NECK_ARC_EXCLUDE_MM = 3.0  # when probing local width at a candidate,
                          # ignore other candidates within this arc
                          # distance (else every point trivially reads
                          # ~0 mm to its own immediate neighbors)


def _local_widths(ds, coords, length, exclude_mm=NECK_ARC_EXCLUDE_MM):
    """Cheap local-thickness proxy per candidate: min Euclidean distance
    to another candidate at least `exclude_mm` away in ARC length. A
    thin neck's far side is close in SPACE but far in arc length, so it
    reads as a small value; a normal straight run does not."""
    dxy = coords[:, None, :] - coords[None, :, :]
    eucl = np.hypot(dxy[..., 0], dxy[..., 1])
    darc = np.abs(ds[:, None] - ds[None, :])
    darc = np.minimum(darc, length - darc)
    eucl = np.where(darc < exclude_mm, np.inf, eucl)
    return eucl.min(axis=1)


def thin_spots(nominal, threshold_mm=MIN_RIB_WIDTH_MM, sample_step_mm=1.0):
    """Debug helper (ahl 2026-09-15, verifying MIN_RIB_WIDTH_MM against
    the visually-identified spur): (x, y, width) for each LOCAL-MINIMUM
    run of candidates under threshold_mm -- adjacent thin candidates
    (a real neck shows up as a RUN, not an isolated sample) collapsed to
    their single narrowest point."""
    ring = nominal.exterior
    length = ring.length
    ds = np.arange(0.0, length, sample_step_mm)
    pts = [ring.interpolate(d) for d in ds]
    coords = np.array([[p.x, p.y] for p in pts])
    widths = _local_widths(ds, coords, length)
    thin = widths < threshold_mm
    spots = []
    i, n = 0, len(thin)
    while i < n:
        if thin[i]:
            j = i
            while j + 1 < n and thin[j + 1]:
                j += 1
            k = i + int(np.argmin(widths[i:j + 1]))
            spots.append((coords[k, 0], coords[k, 1], float(widths[k])))
            i = j + 1
        else:
            i += 1
    return spots


def choose_rib_sites(nominal, other_nominal, n_total, sample_step_mm=1.0,
                     avoid_points=(), avoid_dist_mm=15.0):
    """Picks `n_total` rib sites (arc-length positions on `nominal`'s
    exterior ring), simply: straightest stretches first, spread around
    the perimeter by arc-length max-min (ahl 2026-09-15: ribs matter
    most on big FLAT stretches -- a curvy stretch already gets some
    mechanical interlock from its own shape and needs a rib less -- so
    NO forced frame/pair quota and no directional-coverage requirement,
    just follow the straightness wherever it actually is). Candidates
    under MIN_RIB_WIDTH_MM local width (a thin neck should never carry a
    rib's extra interference) or within `avoid_dist_mm` of an
    `avoid_points` entry (e.g. a SIBLING piece's already-chosen pair-rib
    site, so two pieces' ribs don't cluster on their shared boundary)
    are excluded first, falling back to the unfiltered pool if an
    exclusion would leave nothing at all.

    `other_nominal`: union of sibling nominal footprints, or None/empty
    if this piece has no siblings -- used only to LABEL each chosen site
    "frame" or "pair" for reporting/preview, it does not affect which
    sites get picked. Returns a list of (arc_length_d, kind), sorted by
    arc length."""
    ring = nominal.exterior
    length = ring.length
    ds = np.arange(0.0, length, sample_step_mm)
    pts = [ring.interpolate(d) for d in ds]
    has_pair = other_nominal is not None and not other_nominal.is_empty
    ob = other_nominal.boundary if has_pair else None
    is_pair = np.array([has_pair and ob.distance(p) < 0.02 for p in pts])
    curv = np.array([_ring_curvature(ring, length, d) for d in ds])
    coords = np.array([[p.x, p.y] for p in pts])
    widths = _local_widths(ds, coords, length)
    ok = widths >= MIN_RIB_WIDTH_MM
    if (~ok).any():
        wmin = int(np.argmin(widths))
        print(f"    [ribs] excluding {(~ok).sum()} of {len(ds)} candidate "
              f"site(s) under {MIN_RIB_WIDTH_MM:g} mm local width (min "
              f"{widths[wmin]:.2f} mm @ ({coords[wmin, 0]:.1f}, "
              f"{coords[wmin, 1]:.1f}))")

    if avoid_points:
        near = np.zeros(len(ds), bool)
        for ax, ay in avoid_points:
            near |= np.hypot(coords[:, 0] - ax, coords[:, 1] - ay) \
                < avoid_dist_mm
        if (ok & ~near).any():
            ok &= ~near
        else:
            print("    [ribs] avoid_points would exclude everything left -- "
                  "ignoring this time")

    idx = sorted(np.nonzero(ok)[0].tolist(), key=lambda i: curv[i])
    idx = idx[:max(n_total, (len(idx) + 1) // 2)]     # straighter half
    chosen = [idx[0]] if idx else []
    pool = idx[1:]
    while len(chosen) < n_total and pool:
        def arc_gap(i):
            return min(min(abs(ds[i] - ds[c]), length - abs(ds[i] - ds[c]))
                       for c in chosen)
        best = max(pool, key=arc_gap)
        chosen.append(best)
        pool.remove(best)

    # floor of one pair rib (ahl 2026-09-15): pure straightness can
    # legitimately pick zero -- a curvy shared boundary self-interlocks
    # and may lose every slot to straighter frame stretches -- but some
    # grip against the sibling piece is still wanted, so swap the
    # straightest available pair candidate in for the single WEAKEST
    # (least straight) chosen site if none made the cut on their own
    if has_pair and chosen and not any(is_pair[i] for i in chosen):
        pair_ok = np.nonzero(ok & is_pair)[0]
        if len(pair_ok):
            best_pair = int(min(pair_ok, key=lambda i: curv[i]))
            worst = max(chosen, key=lambda i: curv[i])
            chosen[chosen.index(worst)] = best_pair

    sites = [(ds[i], "pair" if is_pair[i] else "frame") for i in chosen]
    sites.sort(key=lambda t: t[0])
    return sites


def manual_rib_sites(nominal, other_nominal, points, label=""):
    """MANUAL rib placement (ahl 2026-09-15 -- replaces the automatic
    heuristic, which kept producing surprises; there are only ~4 ribs per
    piece and ahl has better judgement about the assembled object than
    any straightness/spread proxy).  `points`: approximate (x, y) in
    print mm, read off the preview -- each SNAPS to the nearest point on
    `nominal`'s exterior, so eyeballed coordinates are fine.  Reports the
    snap distance (a big one = a typo or a stale coordinate) and warns if
    a site lands on a thin neck, but never overrides ahl's choice.
    Returns choose_rib_sites' (arc_length_d, kind) list."""
    ring = nominal.exterior
    has_pair = other_nominal is not None and not other_nominal.is_empty
    ob = other_nominal.boundary if has_pair else None
    necks = thin_spots(nominal)
    sites = []
    for x, y in points:
        want = Point(float(x), float(y))
        d = ring.project(want)
        p = ring.interpolate(d)
        kind = "pair" if (has_pair and ob.distance(p) < 0.02) else "frame"
        snap = want.distance(p)
        warn = ""
        if snap > 2.0:
            warn += f"  [!] snapped {snap:.1f} mm -- check this coordinate"
        for nx, ny, w in necks:
            if np.hypot(p.x - nx, p.y - ny) < 5.0:
                warn += (f"  [!] {np.hypot(p.x - nx, p.y - ny):.1f} mm from a "
                         f"{w:.2f} mm neck")
                break
        print(f"    [ribs] {label}manual ({x:g}, {y:g}) -> {kind}@"
              f"({p.x:.1f}, {p.y:.1f}), snap {snap:.2f} mm{warn}")
        sites.append((d, kind))
    sites.sort(key=lambda t: t[0])
    return sites


def add_crush_ribs(piece, nominal, other_nominal, n_ribs, radius_mm,
                   interference_mm, avoid_points=(), manual_points=None):
    """Retention crush-ribs (ahl 2026-09-14: pieces must stay seated when
    the tray is tipped; release is via the finger poke-holes, not a
    snug piece fit) -- vertical half-cylinder ribs standing proud of
    `piece`'s (the clearance-cut piece) own wall, at sites on `nominal`
    (the pre-clearance region outline): `manual_points` when given (ahl's
    hand-picked (x, y) list from config [print.ribs] -- the normal path),
    else n_ribs sites from the automatic choose_rib_sites heuristic.

    Crest placement is independent of which clearance applied locally:
    the offset wall sits `clearance_local` inside nominal; a rib
    protruding (clearance_local + interference_mm) from THAT wall lands
    at nominal + interference_mm, always -- so every rib is simply a
    disk of radius `radius_mm` centered (interference_mm - radius_mm)
    outward from a nominal-boundary sample point (i.e. INSET into the
    piece by radius_mm - interference_mm when radius_mm > interference_mm,
    the normal case) and unioned onto `piece`: only the cap beyond
    piece's own wall becomes new material, a radius_mm-curvature bump
    whose crest reaches exactly interference_mm past nominal (0 = no
    ribs). `interference_mm` may be 0 for an enclosed piece's OWN walls
    -- see ENCLOSED_ZERO_CLEARANCE -- ahl's call was to keep ribs on
    every piece regardless (the valley still gets ribs against its
    enclosing neighbor), so this is called uniformly per piece.

    Returns (ribbed_piece, sites) where sites is choose_rib_sites' list
    of (arc_length_d, kind), for reporting/preview."""
    if interference_mm <= 0 or radius_mm <= 0 or n_ribs <= 0:
        return piece, []
    ring = nominal.exterior
    length = ring.length
    eps = min(0.3, length * 0.01)
    if manual_points:
        sites = manual_rib_sites(nominal, other_nominal, manual_points)
    else:
        sites = choose_rib_sites(nominal, other_nominal, n_ribs,
                                 avoid_points=avoid_points)
    bumps = []
    for d, _kind in sites:
        p = ring.interpolate(d)
        p0 = ring.interpolate((d - eps) % length)
        p1 = ring.interpolate((d + eps) % length)
        nx, ny = _outward_normal(nominal, p, (p1.x - p0.x, p1.y - p0.y))
        k = interference_mm - radius_mm
        bumps.append(Point(p.x + k * nx, p.y + k * ny)
                    .buffer(radius_mm, quad_segs=16))
    ribbed = unary_union([piece] + bumps).buffer(0)
    parts = [g for g in getattr(ribbed, "geoms", [ribbed])
             if g.geom_type == "Polygon"]
    parts.sort(key=lambda g: g.area, reverse=True)
    return parts[0], sites


def _parts(geom, min_area=0.5):
    return [p for p in getattr(geom, "geoms", [geom])
            if p.geom_type == "Polygon" and p.area >= min_area]


def min_land_width(poly, step=0.05, cap=2.0):
    """Narrowest ELONGATED feature width via morphological opening; corner
    tips and boundary wiggle excluded (see P4 v1 report)."""
    keep = _parts(poly)
    if not keep:
        return float("nan")
    poly = MultiPolygon(keep) if len(keep) > 1 else keep[0]
    base_n = len(keep)
    d = step
    while d <= cap / 2 + 1e-9:
        shrunk = poly.buffer(-d)
        if shrunk.is_empty:
            return 2 * d
        opened = shrunk.buffer(d)
        if len(_parts(opened)) > base_n:
            return 2 * d
        residual = poly.difference(opened)
        for g in getattr(residual, "geoms", [residual]):
            if g.geom_type != "Polygon" or g.area < 0.25:
                continue
            try:
                r = polylabel(g, 0.01).distance(g.boundary)
            except Exception:
                continue
            if r > 0.3 * d and g.area > 3 * np.pi * r * r:
                return 2 * d
        d += step
    return cap


def wall_gap_stats(piece, transition_nom, reference, n=400,
                   near_tol=0.5):
    """Sample `piece`'s (clearance-cut) boundary and measure distance to
    `reference` (upper_water for the frame gap; another piece for a pair
    gap), split into samples NEAR a clearance-type transition (within
    near_tol mm of `transition_nom` -- e.g. a sibling piece's nominal
    footprint, when measuring the FRAME gap) and the rest (the general
    wall). ahl 2026-09-14 T2-vs-T1 verification: where two different
    per-stretch offsets meet (frame-facing vs piece-facing clearance on
    the SAME piece), the AND-of-two-independent-erosions can legitimately
    pinch toward zero at that single corner -- the same class of
    singularity any offset-curve construction has at a reflex vertex,
    confirmed by isolating it: mountains' and valley's global-minimum
    frame gap each sat within 0.06 mm of the OTHER piece's nominal
    boundary, while every sample >= near_tol mm from it measured within
    a few hundredths of a mm of nominal (0.13-0.15 mm here for a 0.15 mm
    target). Reporting the raw global minimum ALONE is misleadingly
    pessimistic for a piece with mixed interfaces -- report both.
    Returns (global_min, far_min, far_median, n_far); if `transition_nom`
    is None/empty or every/no sample is 'near', far_* falls back to all
    samples."""
    ring = piece.exterior
    length = ring.length
    pts = [ring.interpolate(t) for t in np.linspace(0, length, n,
                                                     endpoint=False)]
    global_min = float(piece.distance(reference))
    near = None
    if transition_nom is not None and not transition_nom.is_empty:
        near = np.array([transition_nom.distance(p) < near_tol
                         for p in pts])
    d = np.array([p.distance(reference) for p in pts])
    far_d = d[~near] if (near is not None and near.any()
                        and not near.all()) else d
    return global_min, float(far_d.min()), float(np.median(far_d)), \
        len(far_d)


# ------------------------------------------------------------------ meshes
def triangulate(poly, flags):
    """Constrained Delaunay of a shapely Polygon (holes ok)."""
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
        rp = polylabel(Polygon(h), 0.05)
        holes.append([rp.x, rp.y])
    A = {"vertices": np.asarray(pts, float),
         "segments": np.asarray(segs, np.int32)}
    if holes:
        A["holes"] = np.asarray(holes, float)
    B = tr.triangulate(A, flags)
    return B["vertices"], B["triangles"]


def _cdt_down(pts, segs, holes):
    """'p'-flag CDT of a PSLG (no Steiner points, asserted), faces
    flipped to wind CW seen from +z (downward-facing surfaces)."""
    A = {"vertices": np.asarray(pts, float),
         "segments": np.asarray(segs, np.int32)}
    if holes:
        A["holes"] = np.asarray(holes, float)
    B = tr.triangulate(A, "p")
    bv, bf = B["vertices"], B["triangles"].astype(np.int64)
    assert len(bv) == len(pts), "Steiner point appeared on a 'p' CDT"
    a = bv[bf[:, 0]]
    cross = ((bv[bf[:, 1]] - a)[:, 0] * (bv[bf[:, 2]] - a)[:, 1]
             - (bv[bf[:, 1]] - a)[:, 1] * (bv[bf[:, 2]] - a)[:, 0])
    bf[cross > 0] = bf[cross > 0][:, ::-1]
    return bf


def _bottom_patch(part, v2, be, stamp, z_bottom):
    """Rebuild a part bottom around a stamp: version stamps go through
    version_stamp.stamped_bottom (raster glyph grid); the vector compass
    panel (compass_art.RosePanel) carries its own CDT builder and is
    dispatched on its build_bottom method."""
    build = getattr(stamp, "build_bottom", None)
    if build is not None:
        return build(part, v2, be, z_bottom)
    return vstamp.stamped_bottom(part, v2, be, stamp, z_bottom)


def solid_mesh(poly, top_fn, z_bottom=0.0, quality=True, stamp=None,
               chamfer=0.0):
    """Watertight solid over a (Multi)Polygon: top from top_fn(xy)->z,
    flat bottom at z_bottom, vertical walls. quality=False -> boundary-
    only CDT (flat prisms need no interior refinement). stamp: optional
    version_stamp.Stamp (or compass_art.RosePanel) debossed into the
    bottom of the part containing its rectangle (see _bottom_patch).
    chamfer > 0: G4 45-degree bottom edge chamfer -- walls stay vertical
    down to z_bottom + chamfer, then slope inward to the bottom outline
    inset by `chamfer` (elephant-foot relief; [print].bottom_chamfer_mm)."""
    flags = f"pq25a{MAX_TRI_AREA_MM2:.6f}" if quality else "p"
    bodies = []
    stamped = False
    for part in getattr(poly, "geoms", [poly]):
        v2, f = triangulate(part, flags)
        a = v2[f[:, 0]]
        cross = ((v2[f[:, 1]] - a)[:, 0] * (v2[f[:, 2]] - a)[:, 1]
                 - (v2[f[:, 1]] - a)[:, 1] * (v2[f[:, 2]] - a)[:, 0])
        f[cross < 0] = f[cross < 0][:, ::-1]
        nv = len(v2)
        ztop = top_fn(v2)
        edges = np.vstack([f[:, [0, 1]], f[:, [1, 2]], f[:, [2, 0]]])
        und = np.sort(edges, axis=1)
        _, inv, cnt = np.unique(und, axis=0, return_inverse=True,
                                return_counts=True)
        be = edges[cnt[inv] == 1]
        inset = None
        if chamfer > 1e-9:
            cand = part.buffer(-chamfer)
            if (cand.geom_type == "Polygon" and not cand.is_empty
                    and not part.interiors and not cand.interiors):
                inset = cand
            else:
                print("  !! chamfer skipped for one part (inset is not a "
                      "simple polygon) -- vertical wall to the plate there")
        if inset is not None:
            # vertical wall to z_bottom+chamfer, 45-deg annulus to the
            # inset outline at z_bottom, then the (optionally stamped)
            # inset bottom; all boundary chains shared exactly, welded
            bidx = np.unique(be)
            n_b = len(bidx)
            bmap = np.full(nv, -1, np.int64)
            bmap[bidx] = nv + np.arange(n_b)
            z_ch = float(z_bottom) + chamfer
            P, Q = be[:, 0], be[:, 1]
            walls = np.vstack([np.stack([P, bmap[P], bmap[Q]], 1),
                               np.stack([P, bmap[Q], Q], 1)])
            ir = np.asarray(inset.exterior.coords)[:-1]
            keep = np.ones(len(ir), bool)
            keep[1:] = np.linalg.norm(np.diff(ir, axis=0), axis=1) > 1e-9
            ir = ir[keep]
            remap = np.full(nv, -1, np.int64)
            remap[bidx] = np.arange(n_b)
            iids = n_b + np.arange(len(ir))
            iseg = np.column_stack([iids, np.roll(iids, -1)])
            hp = polylabel(inset, 0.05)
            ann_f = _cdt_down(np.vstack([v2[bidx], ir]),
                              np.vstack([remap[be], iseg]), [[hp.x, hp.y]])
            ann_verts = np.column_stack([
                np.vstack([v2[bidx], ir]),
                np.concatenate([np.full(n_b, z_ch),
                                np.full(len(ir), float(z_bottom))])])
            iseg0 = np.column_stack([np.arange(len(ir)),
                                     np.roll(np.arange(len(ir)), -1)])
            if stamp is not None and inset.contains(stamp.rect):
                stamped = True
                bverts, bfaces = _bottom_patch(inset, ir, iseg0,
                                               stamp, z_bottom)
            else:
                bfaces = _cdt_down(ir, iseg0, None)
                bverts = np.column_stack(
                    [ir, np.full(len(ir), float(z_bottom))])
            blocks = [np.column_stack([v2, ztop]),
                      np.column_stack([v2[bidx], np.full(n_b, z_ch)]),
                      ann_verts, bverts]
            offs = np.cumsum([0] + [len(b) for b in blocks])
            faces = np.vstack([f, walls, ann_f + offs[2],
                               bfaces + offs[3]])
            verts, faces = vstamp.weld(np.vstack(blocks), faces)
            mesh = trimesh.Trimesh(vertices=verts, faces=faces,
                                   process=False)
            if mesh.volume < 0:
                mesh.invert()
            bodies.append(mesh)
            continue
        if stamp is not None and part.contains(stamp.rect):
            # bottom rebuilt with the deboss; walls end on the same
            # boundary vertex chain the CDT reuses, then weld
            stamped = True
            bidx = np.unique(be)
            bmap = np.full(nv, -1, np.int64)
            bmap[bidx] = nv + np.arange(len(bidx))
            verts = np.vstack([
                np.column_stack([v2, ztop]),
                np.column_stack([v2[bidx],
                                 np.full(len(bidx), float(z_bottom))])])
            P, Q = be[:, 0], be[:, 1]
            walls = np.vstack([np.stack([P, bmap[P], bmap[Q]], 1),
                               np.stack([P, bmap[Q], Q], 1)])
            bverts, bfaces = _bottom_patch(part, v2, be, stamp, z_bottom)
            faces = np.vstack([f, walls, bfaces + len(verts)])
            verts, faces = vstamp.weld(np.vstack([verts, bverts]), faces)
            mesh = trimesh.Trimesh(vertices=verts, faces=faces,
                                   process=False)
            if mesh.volume < 0:
                mesh.invert()
            bodies.append(mesh)
            continue
        verts = np.vstack([np.column_stack([v2, ztop]),
                           np.column_stack([v2, np.full(nv, z_bottom)])])
        walls = np.vstack([
            np.column_stack([be[:, 0], be[:, 0] + nv, be[:, 1] + nv]),
            np.column_stack([be[:, 0], be[:, 1] + nv, be[:, 1]])])
        faces = np.vstack([f, f[:, ::-1] + nv, walls])
        bodies.append(trimesh.Trimesh(vertices=verts, faces=faces,
                                      process=False))
    assert stamp is None or stamped, "stamp rect not inside any part"
    return trimesh.util.concatenate(bodies) if len(bodies) > 1 else bodies[0]


def water_upper_mesh(upper_water_poly, rose_panel=None):
    """Upper water solid (floor top .. datum).  With rose_panel (a
    compass_art.RosePanel; flush compass style) its TOP carries the
    matching vector ink recesses: the solid is built z-MIRRORED so the
    bottom-rebuild machinery carves the top, then flipped back (z
    negated, faces reversed)."""
    zb = FLOOR_MM - OVERLAP_MM
    if rose_panel is None:
        return solid_mesh(upper_water_poly,
                          lambda v: np.full(len(v), BASE_MM), zb,
                          quality=False)
    m = solid_mesh(upper_water_poly, lambda v: np.full(len(v), -zb),
                   -BASE_MM, quality=False, stamp=rose_panel)
    return trimesh.Trimesh(vertices=m.vertices * [1.0, 1.0, -1.0],
                           faces=m.faces[:, ::-1], process=False)


def make_terrain_fn(dem, s, gx0, gy0, z_per_m, z_datum, floor_mm=0.0):
    """(x_mm, y_mm) print coords -> top z: z_datum + relief (clamped to
    sea level; floor_mm = minimum height above datum, for the coast).
    (gx0, gy0) = ground (Albers m) coordinates of print (0, 0)."""
    def h(xy):
        gx = gx0 + xy[:, 0] / (s * 1000.0)
        gy = gy0 + xy[:, 1] / (s * 1000.0)
        cols = (gx - base.META["x_min"]) / base.META["res"] - 0.5
        rows = (base.META["y_max"] - gy) / base.META["res"] - 0.5
        e = ndimage.map_coordinates(dem.astype(np.float32), [rows, cols],
                                    order=1, mode="nearest")
        return z_datum + np.maximum(np.maximum(e, 0.0) * z_per_m, floor_mm)
    return h


# ------------------------------------------------------------- poke holes
def poke_points(nom_poly, n=2):
    """n deep-interior points for the floor poke-holes: pole of
    inaccessibility of the shrunk-by-(radius+margin) cavity, then
    greedily the admissible points farthest from those already chosen
    (max-min distance)."""
    margin = POKE_D_MM / 2 + POKE_MARGIN_MM
    allowed = nom_poly.buffer(-margin)
    while allowed.is_empty and margin > POKE_D_MM / 2:
        margin -= 0.5
        allowed = nom_poly.buffer(-margin)
    parts = sorted(getattr(allowed, "geoms", [allowed]),
                   key=lambda p: p.area, reverse=True)
    chosen = [polylabel(parts[0], 0.05)]
    cands = []
    for part in parts:
        x0, y0, x1, y1 = part.bounds
        for x in np.arange(x0, x1, 1.5):
            for y in np.arange(y0, y1, 1.5):
                pt = Point(x, y)
                if part.contains(pt):
                    cands.append(pt)
    while len(chosen) < n and cands:
        best = max(cands, key=lambda p: min(p.distance(c) for c in chosen))
        if min(best.distance(c) for c in chosen) < POKE_D_MM + 2.0:
            break                    # too crowded for another hole
        chosen.append(best)
    return chosen


def _all_rings(poly):
    """Every LinearRing of a (Multi)Polygon: each part's exterior AND
    its interiors (holes) -- a piece fully enclosed by another (the
    valley inside the mountains, in P5) shows up as an INTERIOR ring of
    the enclosing piece's polygon, not its exterior, so any perimeter
    walk that only checks .exterior misses that whole interface."""
    rings = []
    for part in getattr(poly, "geoms", [poly]):
        rings.append(part.exterior)
        rings.extend(part.interiors)
    return rings


def _best_seam_run(ring, nom_b, cav_union, allowed, min_len_mm,
                   touch_tol_mm, step_mm):
    """Longest circularly-contiguous run of `ring` samples lying within
    touch_tol_mm of nom_b, and the point within a qualifying run (>=
    min_len_mm) that clears `allowed` and sits farthest from
    cav_union's own boundary. Returns (point_or_None, run_len_mm)."""
    length = ring.length
    n = max(int(length / step_mm), 8)
    ds = np.linspace(0.0, length, n, endpoint=False)
    pts = [ring.interpolate(d) for d in ds]
    close = np.array([nom_b.distance(p) < touch_tol_mm for p in pts])
    if not close.any():
        return None, 0.0
    idx = np.nonzero(close)[0]
    runs, start, prev = [], idx[0], idx[0]
    for i in idx[1:]:
        if i == prev + 1:
            prev = i
            continue
        runs.append((start, prev))
        start = prev = i
    runs.append((start, prev))
    if len(runs) > 1 and runs[0][0] == 0 and runs[-1][1] == n - 1:
        s1, e1 = runs.pop()
        s0, e0 = runs.pop(0)
        runs.append((s1, e0 + n))               # wraps around index 0
    step_actual = length / n
    s, e = max(runs, key=lambda r: r[1] - r[0])
    run_len = (e - s) * step_actual
    if run_len < min_len_mm:
        return None, run_len
    run_pts = [pts[i % n] for i in range(s, e + 1)]
    outer = cav_union.boundary
    cands = [p for p in run_pts if allowed.contains(p)]
    if not cands:
        return None, run_len
    return max(cands, key=lambda p: outer.distance(p)), run_len


def seam_hole(nom_a, nom_b, cav_union, allowed, min_len_mm=None,
             touch_tol_mm=0.05, step_mm=0.5):
    """A poke-hole CENTER straddling the shared border of two adjacent
    NOMINAL (pre-clearance) piece footprints -- ahl 2026-09-14: poke-
    holes are now the disassembly mechanism and finger-sized, and one
    hole spanning a piece-piece seam undermines both pieces at once.
    Nominal footprints are exactly contiguous (no clearance cut yet), so
    `cav_union` (their union) has NO boundary along the seam itself --
    only its outer edge is a real frame wall -- meaning a hole centered
    on the seam is legitimately entirely 'under removable pieces' even
    though its circle crosses two different piece rasters.

    Finding the seam by exact geometric intersection of the two rings
    (nom_a.exterior.intersection(nom_b.exterior)) does NOT work in this
    pipeline: each region's outline is contoured INDEPENDENTLY from its
    own raster/EDT field (see mask_polygon), so two touching regions'
    rings approximate the same physical edge but are not bit-identical
    -- verified their exact intersection is empty even where they
    plainly border each other over a long run. Instead, walk EVERY ring
    of BOTH polygons (_all_rings -- critical for an ENCLOSED piece like
    P5's valley: the mountains/valley border lives on mountains' own
    INTERIOR ring, the hole valley sits in, not its exterior; verified
    mountains_nom carries exactly one such 380 mm hole there), sampling
    every step_mm and marking points within touch_tol_mm of the other
    polygon (a proximity test against the whole polygon, not exact
    coincidence -- the same style of check choose_rib_sites uses for
    pair-vs-frame classification); find the longest circularly-
    contiguous marked run on any ring, keep it if its arc length is >=
    min_len_mm (default: 1.5x the hole diameter, so the full circle
    plausibly fits along it) and some point in it clears `allowed`
    (cav_union already buffered in by the wall margin -- hole radius +
    POKE_MARGIN_MM), scored by distance to cav_union's OWN boundary (so
    the seam itself costs nothing). Returns None if no ring on either
    side qualifies."""
    if min_len_mm is None:
        min_len_mm = 1.5 * POKE_D_MM
    best_pt, best_len = None, -1.0
    for ring, other in ((r, nom_b) for r in _all_rings(nom_a)):
        pt, run_len = _best_seam_run(ring, other, cav_union, allowed,
                                     min_len_mm, touch_tol_mm, step_mm)
        if pt is not None and run_len > best_len:
            best_pt, best_len = pt, run_len
    for ring, other in ((r, nom_a) for r in _all_rings(nom_b)):
        pt, run_len = _best_seam_run(ring, other, cav_union, allowed,
                                     min_len_mm, touch_tol_mm, step_mm)
        if pt is not None and run_len > best_len:
            best_pt, best_len = pt, run_len
    return best_pt


def plan_poke_holes(nom, target_n, seam_min_len_mm=None):
    """Plans finger-sized poke-hole CENTERS (config [print].poke_hole_d_mm
    = 18 mm, ahl 2026-09-14: THE disassembly mechanism) through the frame
    floor under the union of all removable pieces.  `nom`: {name:
    nominal piece polygon}.  One SHARED hole per adjacent pair of pieces
    whose common border is long enough (seam_hole) -- serves both
    flanking pieces at once; then per-piece deep-interior holes
    (poke_points, unchanged) top each piece up to target_n[name] holes
    credited to it, with at least 1 own hole even when seam holes
    already reach the target (a piece must never depend SOLELY on a
    hole centered mostly under its neighbor).  Every center clears the
    cavity-union boundary (the real frame cavity wall) by >= hole_radius
    + POKE_MARGIN_MM and every other hole by >= poke_hole_d_mm + 2 mm.
    Returns (centers, credit) -- credit[name] is the sublist of centers
    whose circle overlaps that piece's own nominal footprint (a seam
    hole appears in both flanking pieces' lists)."""
    names = list(nom)
    cav_union = unary_union(list(nom.values()))
    margin = POKE_D_MM / 2 + POKE_MARGIN_MM
    allowed = cav_union.buffer(-margin)
    centers, credit = [], {n: [] for n in names}

    def add(pt):
        if pt is None or any(pt.distance(c) < POKE_D_MM + 2.0
                             for c in centers):
            return False
        centers.append(pt)
        for n in names:
            if nom[n].distance(pt) < 1e-6:
                credit[n].append(pt)
        return True

    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            a, b = names[i], names[j]
            add(seam_hole(nom[a], nom[b], cav_union, allowed,
                         seam_min_len_mm))

    for n in names:
        want = max(target_n.get(n, 2), 1)
        if len(credit[n]) >= want and credit[n]:
            continue                            # target met via seam(s)
        need = max(want - len(credit[n]), 1)    # never zero own holes
        for pt in poke_points(nom[n], n=need + len(credit[n])):
            if len(credit[n]) >= want:
                break
            add(pt)
    return centers, credit


# --------------------------------------------------------------- 3MF writer
CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"
IDENT = "1 0 0 0 1 0 0 0 1 0 0 0"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""


def _mesh_xml(mesh):
    vs = "\n".join(f'     <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>'
                   for x, y, z in mesh.vertices)
    ts = "\n".join(f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>'
                   for a, b, c in mesh.faces)
    return ("   <mesh>\n    <vertices>\n" + vs + "\n    </vertices>\n"
            "    <triangles>\n" + ts + "\n    </triangles>\n   </mesh>")


def write_bambu_3mf(path, object_name, bodies):
    """Hand-rolled Bambu-flavored multi-body 3MF, exactly the validated
    cubes_bambu.3mf layout from p3_3mf_experiment.py: one components
    object, production-extension UUIDs, Application=BambuStudio, and
    Metadata/model_settings.config assigning per-part extruders.
    bodies = [(name, trimesh, extruder_1based)]."""
    u = lambda: str(uuid.uuid4())
    objs, comps, parts = [], [], []
    for i, (name, mesh, extruder) in enumerate(bodies, start=1):
        objs.append(f'  <object id="{i}" p:UUID="{u()}" type="model">\n'
                    f"{_mesh_xml(mesh)}\n  </object>")
        comps.append(f'    <component p:UUID="{u()}" objectid="{i}" '
                     f'transform="{IDENT}"/>')
        parts.append(
            f'  <part id="{i}" subtype="normal_part">\n'
            f'   <metadata key="name" value="{name}"/>\n'
            f'   <metadata key="extruder" value="{extruder}"/>\n'
            f'   <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
            f"  </part>")
    n_assy = len(bodies) + 1
    model = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}" xmlns:p="{PROD}" requiredextensions="p">
 <metadata name="Application">BambuStudio-02.01.01.52</metadata>
 <metadata name="BambuStudio:3mfVersion">1</metadata>
 <resources>
{chr(10).join(objs)}
  <object id="{n_assy}" p:UUID="{u()}" type="model">
   <components>
{chr(10).join(comps)}
   </components>
  </object>
 </resources>
 <build p:UUID="{u()}">
  <item objectid="{n_assy}" p:UUID="{u()}" transform="{IDENT}" printable="1"/>
 </build>
</model>"""
    model_settings = f"""<?xml version="1.0" encoding="UTF-8"?>
<config>
 <object id="{n_assy}">
  <metadata key="name" value="{object_name}"/>
  <metadata key="extruder" value="1"/>
{chr(10).join(parts)}
 </object>
 <plate>
  <metadata key="plater_id" value="1"/>
  <metadata key="plater_name" value=""/>
  <metadata key="locked" value="false"/>
  <model_instance>
   <metadata key="object_id" value="{n_assy}"/>
   <metadata key="instance_id" value="0"/>
   <metadata key="identify_id" value="100"/>
  </model_instance>
 </plate>
 <assemble>
  <assemble_item object_id="{n_assy}" instance_id="0" transform="{IDENT}" offset="0 0 0"/>
 </assemble>
</config>"""
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model)
        z.writestr("Metadata/model_settings.config", model_settings)


def lint_3mf(path):
    """Parse with py-lib3mf (validator only, per NOTES-3mf.md)."""
    try:
        from py_lib3mf import Lib3MF
        wrapper = Lib3MF.Wrapper()
        model = wrapper.CreateModel()
        reader = model.QueryReader("3mf")
        reader.ReadFromFile(str(path))
        n = 0
        it = model.GetMeshObjects()
        while it.MoveNext():
            n += 1
        return f"py-lib3mf parse OK ({n} mesh objects)"
    except Exception as e:                       # noqa: BLE001
        return f"py-lib3mf lint skipped/failed: {e}"


# ----------------------------------------------------------------- preview
def add_poly(ax, geom, color, ec="none", lw=0.0, alpha=1.0, z=1):
    from matplotlib.path import Path as MPath
    from matplotlib.patches import PathPatch
    if geom is None or geom.is_empty:
        return
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


def render_preview(geo, s, tj, holes, stamps, ribbed, rib_pt, rose=None,
                   rose_c=None, rib_pts=None):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    water_vis = geo["water_visible"]
    cav_floor = {n: geo[f"{n}_nom"] for n in ("mountains", "valley")}
    n_panels = 6 if rose is not None else 5
    fig, axes = plt.subplots(1, n_panels,
                             figsize=(6.4 * n_panels, 7.2), dpi=200)
    rose_colors = {"coast": tuple(base.COLORS[base.COAST])[:3],
                   "gray": GRAY_RGB, "black": (0.12, 0.11, 0.11)}

    # same per-piece explode offset the loop below uses, precomputed
    # once so the rib markers on the exploded panel track their piece
    explode_off = {}
    for name in ("mountains", "valley"):
        c = geo[f"{name}_piece"].centroid
        v = np.array([c.x - WINDOW_MM / 2, c.y - WINDOW_MM / 2])
        nv = np.linalg.norm(v)
        explode_off[name] = (v / nv * 26.0) if nv > 1e-6 else (0.0, 26.0)

    def draw_ribs(ax, exploded=False):
        for r in (rib_pts or []):
            x, y = r["x"], r["y"]
            if exploded:
                dx, dy = explode_off[r["name"]]
                x, y = x + dx, y + dy
            marker = "^" if r["kind"] == "pair" else "o"
            ax.plot(x, y, marker=marker, color="red",
                   markeredgecolor="white", markeredgewidth=0.4,
                   markersize=5, zorder=7)

    for col, ax in enumerate(axes[:3]):
        ax.set_facecolor("#1c1c22")
        explode = col == 1
        add_poly(ax, water_vis, WATER_RGB)
        add_poly(ax, geo["gray"], GRAY_RGB, z=2)
        add_poly(ax, geo["coast_nom"], base.COLORS[base.COAST], z=2)
        for name in ("mountains", "valley"):
            rid = {v: k for k, v in REGION_NAME.items()}[name]
            g = geo[f"{name}_piece"]
            if explode:
                # cavity floor (water-color) with its poke-holes
                floor = cav_floor[name]
                for pt in holes[name]:
                    floor = floor.difference(
                        pt.buffer(POKE_D_MM / 2, quad_segs=24))
                add_poly(ax, floor, tuple(c * 0.82 for c in WATER_RGB), z=2)
                c = g.centroid
                v = np.array([c.x - WINDOW_MM / 2, c.y - WINDOW_MM / 2])
                nv = np.linalg.norm(v)
                dx, dy = explode_off[name]
                g = affinity.translate(g, dx, dy)
                cc = g.centroid
                ax.annotate(name, (cc.x, cc.y), color="black", fontsize=10,
                            ha="center", weight="bold", zorder=6)
            add_poly(ax, g, base.COLORS[rid], z=3)
        if col in (0, 1) and rose is not None:
            compass_art.draw_rose(ax, rose, rose_c, rose_colors)
        if col in (0, 1):
            draw_ribs(ax, exploded=(col == 1))
        if col == 0:
            for name in ("mountains", "valley"):
                for pt in holes[name]:
                    ax.add_patch(plt.Circle(
                        (pt.x, pt.y), POKE_D_MM / 2, fill=False,
                        edgecolor="black", linestyle=":", lw=0.9, zorder=5))
            ax.plot(*tj, "k+", ms=8, zorder=6)
            ax.set_xlim(-RIM_MM - 2, WINDOW_MM + RIM_MM + 2)
            ax.set_ylim(-RIM_MM - 2, WINDOW_MM + RIM_MM + 2)
            ax.set_title(
                f"assembled — 1:{1 / s / 1e6:.3f}M, window "
                f"{WINDOW_MM / s / 1e6:.0f} km @ ({CENTER_KM[0]:.0f}, "
                f"{CENTER_KM[1]:.0f}) km Albers; band = real geography "
                "(gray = band land); dotted = poke-holes; red = crush "
                "ribs (triangle = pair, dot = frame)", fontsize=10)
        elif col == 1:
            ax.set_xlim(-RIM_MM - 30, WINDOW_MM + RIM_MM + 30)
            ax.set_ylim(-RIM_MM - 30, WINDOW_MM + RIM_MM + 30)
            ax.set_title("exploded (+26 mm) — cavity floors show "
                         "poke-holes", fontsize=10)
        else:
            ax.set_xlim(tj[0] - 6, tj[0] + 6)
            ax.set_ylim(tj[1] - 6, tj[1] + 6)
            ax.set_title(f"cavity-edge zoom (12 mm): piece vs frame "
                         f"{CLEARANCE_MM:g} mm, piece vs piece "
                         f"{2 * CLEARANCE_PAIR_MM:g} mm", fontsize=10)
        ax.set_aspect("equal")
        ax.set_xticks([]), ax.set_yticks([])

    # panel 4: crush-rib close-up (12 mm) -- ribbed piece walls vs the
    # NOMINAL boundary (dashed) they protrude past by RIB_INTERFERENCE_MM
    ax = axes[3]
    ax.set_facecolor("#1c1c22")
    for name in ("mountains", "valley"):
        rid = {v: k for k, v in REGION_NAME.items()}[name]
        add_poly(ax, ribbed[name], base.COLORS[rid], z=3)
        nx, ny = geo[f"{name}_nom"].exterior.xy
        ax.plot(nx, ny, color="white", lw=0.6, linestyle="--", zorder=6,
                alpha=0.7)
    ax.set_xlim(rib_pt.x - 6, rib_pt.x + 6)
    ax.set_ylim(rib_pt.y - 6, rib_pt.y + 6)
    ax.set_title(f"crush-rib close-up (12 mm): r{RIB_RADIUS_MM:g} mm, "
                 f"+{RIB_INTERFERENCE_MM:g} mm past nominal (dashed), "
                 f"{RIBS_PER_PIECE:d} ribs/piece", fontsize=9)
    ax.set_aspect("equal")
    ax.set_xticks([]), ax.set_yticks([])

    # panel 5: BOTTOM view, mirrored (x flipped) so the debossed version
    # stamps read the way they do on the flipped printed parts
    ax = axes[4]
    ax.set_facecolor("#1c1c22")
    add_poly(ax, water_vis, WATER_RGB)
    add_poly(ax, geo["gray"], GRAY_RGB, z=2)
    add_poly(ax, geo["coast_nom"], base.COLORS[base.COAST], z=2)
    for name in ("mountains", "valley"):
        rid = {v: k for k, v in REGION_NAME.items()}[name]
        add_poly(ax, geo[f"{name}_piece"], base.COLORS[rid], z=3)
    for pts in holes.values():
        for pt in pts:
            ax.add_patch(plt.Circle((pt.x, pt.y), POKE_D_MM / 2,
                                    facecolor="#1c1c22",
                                    edgecolor="black", lw=0.6, zorder=5))
    from matplotlib.transforms import Affine2D
    for st in stamps.values():
        w, h = st.size_mm
        rgba = np.zeros(st.mask.shape + (4,))
        rgba[st.mask] = (0.05, 0.05, 0.05, 1.0)
        im = ax.imshow(rgba, extent=(-w / 2, w / 2, -h / 2, h / 2),
                       origin="lower", interpolation="nearest", zorder=6)
        im.set_transform(Affine2D().rotate_deg(st.angle)
                         .translate(*st.center) + ax.transData)
        xr, yr = st.rect.exterior.xy
        ax.plot(xr, yr, color="black", lw=0.5, linestyle=":", zorder=6)
    ax.set_xlim(WINDOW_MM + RIM_MM + 2, -RIM_MM - 2)   # mirrored view
    ax.set_ylim(-RIM_MM - 2, WINDOW_MM + RIM_MM + 2)
    ax.set_title("BOTTOM view (mirrored) — version stamps, "
                 f"{vstamp.DEPTH_MM:g} mm deboss into the bottom layer"
                 if stamps else
                 "BOTTOM view (mirrored) — plain bottoms "
                 "(version stamps disabled)", fontsize=10)
    ax.set_aspect("equal")
    ax.set_xticks([]), ax.set_yticks([])

    if rose is not None:
        # panel 6: rose close-up (raised multi-color relief + letters)
        ax = axes[5]
        ax.set_facecolor("#1c1c22")
        add_poly(ax, water_vis, WATER_RGB)
        add_poly(ax, geo["gray"], GRAY_RGB, z=2)
        add_poly(ax, geo["coast_nom"], base.COLORS[base.COAST], z=2)
        compass_art.draw_rose(ax, rose, rose_c, rose_colors)
        r = COMPASS["coupon_diameter_mm"] / 2
        ax.add_patch(plt.Circle(rose_c, r, fill=False, lw=0.6,
                                edgecolor="#666", linestyle="--",
                                zorder=6))
        half = max(rose.size_mm) / 2 + 2   # tight: judge ink dilation
        ax.set_xlim(rose_c[0] - half, rose_c[0] + half)
        ax.set_ylim(rose_c[1] - half, rose_c[1] + half)
        ax.set_title(f"rose close-up — ring dia {2 * r:g} mm, "
                     f"{ROSE_STYLE} {ROSE_DEPTH:g} mm (blue -> coast "
                     "filament, gray, black + letters)", fontsize=9)
        ax.set_aspect("equal")
        ax.set_xticks([]), ax.set_yticks([])

    fig.suptitle(
        "P4 v2 mini-frame — miniature of the final product  "
        f"(tray frame: floor {FLOOR_MM:g} mm, water surface {BASE_MM:g} mm,"
        f" band land = gray body w/ terrain; pieces {PIECE_SLAB_MM:g} mm "
        "slab + G2 terrain)", fontsize=12)
    fig.tight_layout()
    fig.savefig(OUT / "p4_preview.png", bbox_inches="tight",
                facecolor="white")
    print(f"wrote {OUT / 'p4_preview.png'}")


def triple_junction_mm(regw):
    d = lambda m: ndimage.binary_dilation(m, iterations=2)
    tj = (d(regw == base.COAST) & d(regw == base.VALLEY)
          & d(regw == base.MOUNTAINS))
    if not tj.any():
        return (WINDOW_MM / 2, WINDOW_MM / 2)
    r, c = ndimage.center_of_mass(tj)
    return ((c + 0.5) * PX_MM, WINDOW_MM - (r + 0.5) * PX_MM)


# -------------------------------------------------------------------- main
def report_mesh(name, mesh):
    bb = mesh.bounds
    print(f"  {name:14s} {len(mesh.faces):7d} tris  "
          f"watertight={mesh.is_watertight}  "
          f"bbox {bb[1][0] - bb[0][0]:.1f} x {bb[1][1] - bb[0][1]:.1f} mm, "
          f"z {bb[0][2]:.2f}..{bb[1][2]:.2f} mm")
    if not mesh.is_watertight:
        print(f"  !! {name} NOT WATERTIGHT")
    return mesh.is_watertight


def main():
    dem = np.load(DATA / "dem_ca_albers_250m.npy")
    reg, sea = load_regions(dem)
    s, d13_win, d13_ns_m = d13_scale()
    z_per_m = g2_z_per_m(s)   # config [output].z_exaggeration (G2 norm.)
    print(f"final-product scale: 1:{1 / s / 1e6:.4f}M "
          f"({TOTAL_NS_MM:g} mm over the {d13_ns_m / 1000:.1f} km D13 "
          f"window)\nG2 z-scale: {Z_EXAG:g}x vertical exaggeration "
          f"(config) -> {z_per_m:.6f} mm per m of elevation")

    cx, cy = CENTER_KM[0] * 1000.0, CENTER_KM[1] * 1000.0
    ground_km = WINDOW_MM / s / 1e6
    print(f"window: {WINDOW_MM:g} mm = {ground_km:.0f} km square @ Albers "
          f"({CENTER_KM[0]:.0f}, {CENTER_KM[1]:.0f}) km; real-geography "
          f"band {RIM_MM:g} mm (~{RIM_MM / s / 1e6:.0f} km) -> total "
          f"{WINDOW_MM + 2 * RIM_MM:g} mm square")

    notes = []
    # full-footprint rasters; window views drive pieces/cavities/coast
    regw_fp, seaw_fp, demw_fp = window_rasters(reg, sea, dem, s, cx, cy)
    win_sl = (slice(RIM_PX, -RIM_PX), slice(RIM_PX, -RIM_PX))
    regw = regw_fp[win_sl].copy()
    seaw = seaw_fp[win_sl].copy()
    demw = demw_fp[win_sl]
    if (regw == base.DESERT).any():
        # desert is out of scope for the mini (no desert piece/cavity);
        # leaving it unowned would punch a void in the frame — fold it
        # into the nearest other region instead
        area = (regw == base.DESERT).sum() * PX_MM ** 2
        des = regw == base.DESERT
        regw[des] = 0
        _, (ri, ci) = ndimage.distance_transform_edt(
            regw == 0, return_indices=True)
        regw[des] = regw[ri, ci][des]
        notes.append(f"desert fringe {area:.1f} mm^2 folded into nearest "
                     "region (no desert piece in the mini)")

    def where_km(comp):
        rows, cols = np.where(comp)
        f = lambda xm, ym: (
            (cx + (xm - WINDOW_MM / 2) / (s * 1000)) / 1000,
            (cy + (ym - WINDOW_MM / 2) / (s * 1000)) / 1000)
        (ax0, ay0) = f(cols.min() * PX_MM, WINDOW_MM - rows.max() * PX_MM)
        (ax1, ay1) = f(cols.max() * PX_MM, WINDOW_MM - rows.min() * PX_MM)
        return (f"Albers x [{ax0:.0f}, {ax1:.0f}] km, "
                f"y [{ay0:.0f}, {ay1:.0f}] km")

    regw = fill_and_contiguity(regw, seaw, notes, where_km)

    max_e_win = float(demw[~seaw].max())
    print(f"max elev in window {max_e_win:.0f} m -> terrain top "
          f"{BASE_MM + max_e_win * z_per_m:.2f} mm above print bottom "
          f"(footprint incl. band: {float(demw_fp[~seaw_fp].max()):.0f} m)")

    # ---- polygons -------------------------------------------------------
    geo = {}
    piece_ids = {"mountains": base.MOUNTAINS, "valley": base.VALLEY}
    for name, rid in piece_ids.items():
        geo[f"{name}_nom"] = mask_polygon(regw == rid, 0.0)
    for name, rid in piece_ids.items():
        mask = regw == rid
        other_mask = np.zeros_like(mask)
        for oname, orid in piece_ids.items():
            if oname != name:
                other_mask |= (regw == orid)
        piece = clean_piece(
            piece_polygon(mask, other_mask, CLEAR_PX,
                         piece_pair_clear_px(name)),
            name, notes)
        geo[f"{name}_piece"] = piece
    coast_nom = mask_polygon((regw == base.COAST) & ~seaw, 0.0)
    parts = _parts(coast_nom, MIN_COAST_PART_MM2)
    dropped = (len(list(getattr(coast_nom, "geoms", [coast_nom])))
               - len(parts))
    if dropped:
        notes.append(f"coast body: dropped {dropped} crumb part(s) "
                     f"< {MIN_COAST_PART_MM2} mm^2")
    geo["coast_nom"] = (MultiPolygon(parts) if len(parts) > 1 else parts[0])

    footprint = box(-RIM_MM, -RIM_MM, WINDOW_MM + RIM_MM,
                    WINDOW_MM + RIM_MM)
    window_box = box(0, 0, WINDOW_MM, WINDOW_MM)

    # gray body: ALL land in the outer band, regardless of region --
    # real geography continuing past the window to the print edge
    land_fp = mask_polygon(~seaw_fp, 0.0, origin_mm=-RIM_MM, clip=footprint)
    gray = land_fp.difference(window_box) if land_fp is not None else None
    gparts = _parts(gray, MIN_COAST_PART_MM2) if gray is not None else []
    n_crumb = (len(list(getattr(gray, "geoms", [gray]))) - len(gparts)
               if gray is not None else 0)
    if n_crumb:
        notes.append(f"gray body: dropped {n_crumb} band-land crumb "
                     f"part(s) < {MIN_COAST_PART_MM2} mm^2")
    assert gparts, "no land in the band at all?"
    geo["gray"] = MultiPolygon(gparts) if len(gparts) > 1 else gparts[0]
    assert geo["gray"].intersection(window_box).area < 1e-6

    cavities = geo["mountains_nom"].union(geo["valley_nom"])
    upper_water = footprint.difference(cavities)
    geo["water_visible"] = footprint.difference(cavities).difference(
        geo["coast_nom"]).difference(geo["gray"])

    # which footprint edges actually show gray (check vs ahl's sketch)
    sides = {"west": box(-RIM_MM, -RIM_MM, 0, WINDOW_MM + RIM_MM),
             "east": box(WINDOW_MM, -RIM_MM, WINDOW_MM + RIM_MM,
                         WINDOW_MM + RIM_MM),
             "north": box(-RIM_MM, WINDOW_MM, WINDOW_MM + RIM_MM,
                          WINDOW_MM + RIM_MM),
             "south": box(-RIM_MM, -RIM_MM, WINDOW_MM + RIM_MM, 0)}
    print("  gray band land per side:")
    for sname, sbox in sides.items():
        a = geo["gray"].intersection(sbox).area
        pct = 100 * a / sbox.area
        print(f"    {sname:5s}: {a:7.1f} mm^2 ({pct:4.1f}% of that band)"
              + ("  [no gray]" if a < 1.0 else ""))

    # ---- poke-holes: finger-sized (18 mm), THE disassembly mechanism
    # (ahl 2026-09-14) -- may straddle a piece-piece seam (serves both
    # flanking pieces); must stay >= POKE_MARGIN_MM from the frame
    # cavity wall and fully under the removable-piece union -----------
    piece_nom = {n: geo[f"{n}_nom"] for n in ("mountains", "valley")}
    wall_margin = POKE_D_MM / 2 + POKE_MARGIN_MM
    target_n = {n: 2 for n in piece_nom}   # ~1-2 holes credited per piece
    centers, holes = plan_poke_holes(piece_nom, target_n)
    circles = []
    for pt in centers:
        circ = pt.buffer(POKE_D_MM / 2, quad_segs=24)
        assert cavities.contains(circ), \
            "poke-hole not fully under removable pieces"
        assert cavities.boundary.distance(pt) >= wall_margin - 1e-6, \
            "poke-hole closer than POKE_MARGIN_MM to the frame cavity wall"
        circles.append(circ)
        under = [n for n, pts in holes.items() if any(p is pt for p in pts)]
        gx = cx + (pt.x - WINDOW_MM / 2) / (s * 1000.0)
        gy = cy + (pt.y - WINDOW_MM / 2) / (s * 1000.0)
        print(f"  poke-hole {'+'.join(under):18s} window ({pt.x:.1f}, "
              f"{pt.y:.1f}) mm = Albers ({gx / 1000:.1f}, {gy / 1000:.1f})"
              f" km" + ("  [seam hole]" if len(under) > 1 else ""))
    for i in range(len(circles)):
        for j in range(i + 1, len(circles)):
            assert circles[i].distance(circles[j]) > 1.0
    floor_poly = footprint
    for c in circles:
        floor_poly = floor_poly.difference(c)
    assert floor_poly.geom_type == "Polygon", "floor not one connected body"
    print(f"  floor: one connected body, {len(floor_poly.interiors)} "
          f"poke-holes ({len(centers)} total, dia {POKE_D_MM:g} mm) -- "
          + ", ".join(f"{n}: {len(holes[n])} hole(s)" for n in piece_nom))

    # ---- compass rose (ahl's artwork, raised relief; coupon placement) --
    rose, rose_c = None, None
    if COMPASS.get("enabled", False):
        rose = compass_art.load_rose(
            ROOT / COMPASS["svg"], COMPASS["coupon_diameter_mm"],
            COMPASS["letter_font"], COMPASS["letter_cap_mm"],
            COMPASS["letter_radius_frac"], COMPASS["ink_min_stroke_mm"])
        rose_c = tuple(COMPASS["coupon_center_mm"])
        xi, yi = rose.cell_centers(rose_c)
        assert (xi.min() > -RIM_MM + 0.5 and yi.min() > -RIM_MM + 0.5
                and xi.max() < WINDOW_MM + RIM_MM - 0.5
                and yi.max() < WINDOW_MM + RIM_MM - 0.5), \
            "rose ink runs off the coupon footprint"
        rr = np.clip(np.round((WINDOW_MM + RIM_MM - yi) / PX_MM
                              - 0.5).astype(int), 0, N_FP - 1)
        cc = np.clip(np.round((xi + RIM_MM) / PX_MM - 0.5).astype(int),
                     0, N_FP - 1)
        on_land = ~seaw_fp[rr, cc]
        assert not on_land.any(), (
            f"rose ink over land: {on_land.sum()} cells, first at "
            f"({xi[on_land][0] if on_land.any() else 0:.1f}, "
            f"{yi[on_land][0] if on_land.any() else 0:.1f}) mm")
        hull = rose.ink_hull(rose_c)
        d_coast = hull.distance(geo["coast_nom"])
        d_gray = hull.distance(geo["gray"])
        d_cav = hull.distance(cavities)
        w, h = rose.size_mm
        if ROSE_STYLE == "flush":
            # the water-top recess panel spans the whole ink box; it
            # must not cross a cavity (holes in the upper water solid)
            panel = vstamp.rect_poly(rose_c[0], rose_c[1], w, h, 0.0)
            assert panel.within(upper_water), \
                "flush rose panel overlaps a cavity"
        print(f"\ncompass rose (D17, {ROSE_STYLE} {ROSE_DEPTH:g} mm): "
              f"ring dia {COMPASS['coupon_diameter_mm']:g} mm at "
              f"{rose_c}, tips to r {rose.tip_r_mm:.1f} mm, box "
              f"{w:.1f} x {h:.1f} mm\n"
              f"  black declared SVG stroke {rose.black_stroke_mm:.2f} mm "
              "(0 = no <stroke>, ink drawn as filled shapes); letter min "
              f"stroke {rose.letter_min_stroke_mm:.2f} mm\n"
              f"  ink min stroke (target {COMPASS['ink_min_stroke_mm']:g} "
              "mm): " + ", ".join(
                  f"{n} {rose.ink_stroke_before_mm[n]:.2f}->"
                  f"{rose.ink_stroke_after_mm[n]:.2f} mm"
                  for n in rose.ink_stroke_after_mm) +
              f"\n  letter/tip gap {rose.letter_tip_gap_mm:+.3f} mm "
              f"(cardinal tips to r {rose.cardinal_tip_r_mm:.2f} mm)\n"
              f"  open-water check: all ink over sea; ink-hull margins "
              f"-- coast {d_coast:.1f} mm, gray {d_gray:.1f} mm, "
              f"cavities {d_cav:.1f} mm")
        assert rose.letter_min_stroke_mm >= 0.8 - 1e-6, \
            "letter strokes < 0.8"
        assert rose.letter_tip_gap_mm > 0, "letter ink touches cardinal tips"
        assert rose.ink_stroke_after_mm["black"] >= \
            COMPASS["ink_min_stroke_mm"] - 1e-6, "black ink stroke under floor"

    # ---- version stamps (0.4 mm bottom deboss, mirrored) ----------------
    stamps = {}
    if STAMPS_ENABLED:
        date = vstamp.stamp_date()
        stamp_texts = {
            "frame": (f"{BUILD_TAG} {date} 1:{1 / s / 1e6:.2f}M "
                      f"c{CLEARANCE_MM:g}"),
            "mountains": f"{BUILD_TAG} {date} MTN",
            "valley": f"{BUILD_TAG} {date} VAL",
        }
        # frame: floor-only clear area -- away from cavity outlines and
        # poke-holes, off the footprint edge
        allowed_frame = footprint.buffer(-2.0).difference(
            cavities.buffer(1.5))
        for c in circles:
            allowed_frame = allowed_frame.difference(c.buffer(1.5))
        stamps["frame"] = vstamp.make_stamp(stamp_texts["frame"],
                                            allowed_frame)
        for name in ("mountains", "valley"):
            piece = geo[f"{name}_piece"]
            stamps[name] = vstamp.make_stamp(
                stamp_texts[name], piece.buffer(-(0.8 + CHAMFER_MM)),
                anchor=polylabel(piece, 0.05))
        print(f"\nversion stamps ({vstamp.DEPTH_MM:g} mm deboss, mirrored, "
              "into each bottom layer):")
        for name, st in stamps.items():
            host = floor_poly if name == "frame" else geo[f"{name}_piece"]
            assert st.rect.within(host), f"stamp {name} outside its bottom"
            if name == "frame":
                d_cav = st.rect.distance(cavities)
                d_poke = min(st.rect.distance(c) for c in circles)
                assert d_cav > 1.0 and d_poke > 1.0
                extra = (f"; {d_cav:.1f} mm to cavities, {d_poke:.1f} mm to "
                         "poke-holes")
            else:
                extra = (f"; {st.rect.distance(host.boundary):.1f} mm to "
                         "piece wall")
            w, h = st.size_mm
            print(f"  {name:9s} '{st.text}' as {len(st.lines)} line(s), cap "
                  f"{st.cap_mm:.1f} mm, min stroke >= {st.min_stroke_mm:.2f} "
                  f"mm (dil {st.dilated_px} px)\n"
                  f"            rect {w:.1f} x {h:.1f} mm at "
                  f"({st.center[0]:.1f}, {st.center[1]:.1f}), rotated "
                  f"{st.angle:+.0f} deg{extra}")
    else:
        print("\nversion stamps DISABLED ([output].stamps_enabled = false) "
              "-- plain flat bottoms on every part")

    # ---- meshes ---------------------------------------------------------
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    gx0 = cx - (WINDOW_MM / 2) / (s * 1000.0)   # ground coords of print
    gy0 = cy - (WINDOW_MM / 2) / (s * 1000.0)   # (0, 0) (window origin)
    terrain_piece = make_terrain_fn(dem, s, gx0, gy0, z_per_m,
                                    PIECE_SLAB_MM)
    terrain_coast = make_terrain_fn(dem, s, gx0, gy0, z_per_m, BASE_MM,
                                    floor_mm=LAND_MIN_MM)

    ok = True
    print("\nframe bodies (frame.3mf):")
    m_floor = solid_mesh(floor_poly, lambda v: np.full(len(v), FLOOR_MM),
                         0.0, quality=False, stamp=stamps.get("frame"))
    rose_panel = None
    if rose is not None:
        rose_panel = compass_art.RosePanel(rose, rose_c, ROSE_DEPTH)
    m_upper = water_upper_mesh(
        upper_water, rose_panel if ROSE_STYLE == "flush" else None)
    # kept as two 3MF parts (not concatenated) so Bambu Studio can iron
    # just the visible open-water top and skip the cavity floor under
    # the removable pieces (ahl 2026-09-14, rose coupon ironing test:
    # "Top surfaces" irons every locally-exposed top face, and a fused
    # water body has one at FLOOR_MM under the cavities as well as the
    # one at BASE_MM that's actually visible)
    ok &= report_mesh("floor", m_floor)
    ok &= report_mesh("water", m_upper)
    fs = stamps.get("frame")
    if fs is not None:
        zok, zlev = vstamp.verify_stamp_levels(m_floor, fs)
        ok &= zok
        print(f"    stamp z-levels {zlev} mm -> depth exactly "
              f"{vstamp.DEPTH_MM:g}: {zok} (floor left above stamp: "
              f"{FLOOR_MM - vstamp.DEPTH_MM:g} mm)")
    # independent volume check on the uniform-thickness floor
    glyph_vol = (fs.mask.sum() * fs.pitch ** 2 * fs.depth
                 if fs is not None else 0.0)
    exp_vol = floor_poly.area * FLOOR_MM - glyph_vol
    dv = abs(m_floor.volume - exp_vol) / exp_vol
    ok &= dv < 2e-3
    print(f"    floor volume {m_floor.volume:.1f} mm^3 vs expected "
          f"{exp_vol:.1f} (glyph void {glyph_vol:.1f} mm^3, err "
          f"{dv * 100:.3f}%)")
    coast_mesh = solid_mesh(geo["coast_nom"], terrain_coast, BASE_MM)
    ok &= report_mesh("coast", coast_mesh)
    gray_mesh = solid_mesh(geo["gray"], terrain_coast, BASE_MM)
    ok &= report_mesh("gray", gray_mesh)
    gray_max = gray_mesh.bounds[1][2]
    print(f"    gray terrain top {gray_max:.2f} mm "
          f"(~{(gray_max - BASE_MM) / z_per_m:.0f} m)")

    # inter-body overlap sanity (z-disjoint by construction; lateral
    # check: coast is inside the window, gray strictly outside — they
    # meet only along the window-edge line, a pure color boundary)
    assert geo["coast_nom"].intersection(geo["gray"]).area < 1e-6

    black_mesh = None
    if rose is not None:
        rm = rose_panel.ink_meshes(BASE_MM, style=ROSE_STYLE)
        z0, z1 = ((BASE_MM - ROSE_DEPTH, BASE_MM)
                  if ROSE_STYLE == "flush"
                  else (BASE_MM, BASE_MM + ROSE_DEPTH))
        for rname, rmesh in rm.items():
            bb = rmesh.bounds
            zok2 = (abs(bb[0][2] - z0) < 1e-6 and abs(bb[1][2] - z1) < 1e-6)
            ok &= zok2 and report_mesh(f"rose {rname}", rmesh)
            print(f"    rose {rname} z {bb[0][2]:.2f}..{bb[1][2]:.2f} "
                  f"(want {z0:g}..{z1:g}, {ROSE_STYLE}) OK: {zok2}")
        if ROSE_STYLE == "flush":
            up_lv = sorted(set(np.round(m_upper.vertices[:, 2],
                                        5).tolist()))
            want = [round(v, 5) for v in (FLOOR_MM - OVERLAP_MM,
                                          BASE_MM - ROSE_DEPTH, BASE_MM)]
            flush_ok = up_lv == want
            ok &= flush_ok
            print(f"    water-top recess z-levels {up_lv} == {want}: "
                  f"{flush_ok}")
        coast_mesh = trimesh.util.concatenate([coast_mesh, rm["coast"]])
        gray_mesh = trimesh.util.concatenate([gray_mesh, rm["gray"]])
        black_mesh = rm["black"]
        ok &= report_mesh("coast body", coast_mesh)
        ok &= report_mesh("gray body", gray_mesh)

    bodies = [("coast", coast_mesh, EXTRUDERS["coast"]),
              ("floor", m_floor, EXTRUDERS["water"]),
              ("water", m_upper, EXTRUDERS["water"]),
              ("gray", gray_mesh, EXTRUDERS["gray"])]
    if black_mesh is not None:
        bodies.append(("black", black_mesh, EXTRUDERS["black"]))
    frame_path = OUT_DIR / "frame.3mf"
    write_bambu_3mf(frame_path, "p4_mini_frame", bodies)
    print(f"  -> {frame_path} ({frame_path.stat().st_size / 1e6:.1f} MB)  "
          f"[{lint_3mf(frame_path)}]")
    with zipfile.ZipFile(frame_path) as z:
        names = set(z.namelist())
    expect = {"[Content_Types].xml", "_rels/.rels", "3D/3dmodel.model",
              "Metadata/model_settings.config"}
    print(f"  3MF layout matches cubes_bambu.3mf: {names == expect}")

    print("\nremovable pieces:")
    ribbed_geo, rib_sites = {}, {}
    pair_pts_so_far = []   # ahl 2026-09-15: mountains picks first, so
                          # valley's call can avoid clustering its own
                          # pair rib near mountains' already-chosen one
    for name in ("mountains", "valley"):
        piece = geo[f"{name}_piece"]
        other_name = "valley" if name == "mountains" else "mountains"
        ribbed, sites = add_crush_ribs(
            piece, geo[f"{name}_nom"], geo[f"{other_name}_nom"],
            RIBS_PER_PIECE, RIB_RADIUS_MM, RIB_INTERFERENCE_MM,
            avoid_points=pair_pts_so_far,
            manual_points=RIB_SITES_CFG.get(f"p4_{name}"))
        ribbed_geo[name] = ribbed
        rib_sites[name] = sites
        ring = geo[f"{name}_nom"].exterior
        pair_pts_so_far += [(ring.interpolate(d).x, ring.interpolate(d).y)
                            for d, kind in sites if kind == "pair"]
        mesh = solid_mesh(ribbed, terrain_piece, 0.0,
                          stamp=stamps.get(name), chamfer=CHAMFER_MM)
        path = OUT_DIR / f"{name}.stl"
        mesh.export(path)
        ok &= report_mesh(name, mesh)
        if name in stamps:
            zok, zlev = vstamp.verify_stamp_levels(mesh, stamps[name],
                                                   extra=(CHAMFER_MM,))
            ok &= zok
            print(f"    stamp z-levels {zlev} mm -> depth exactly "
                  f"{vstamp.DEPTH_MM:g}: {zok}")
        mlw = min_land_width(piece)
        other = geo[f"{other_name}_piece"]
        gap_piece = piece.distance(other)
        nom_pp = pair_gap_nominal_mm(name, other_name)
        gmin, fmin, fmed, nfar = wall_gap_stats(
            piece, geo[f"{other_name}_nom"], upper_water)
        ring = geo[f"{name}_nom"].exterior
        site_pts = [ring.interpolate(d) for d, _ in sites]
        site_str = ", ".join(
            f"{kind}@({p.x:.1f},{p.y:.1f})"
            for (d, kind), p in zip(sites, site_pts))
        print(f"    min width ~{mlw:.2f} mm; gap vs frame: global min "
              f"{gmin:.3f} mm, away from the {other_name} seam (n={nfar}) "
              f"min {fmin:.3f} median {fmed:.3f} mm (nominal "
              f"{CLEARANCE_MM:g}); vs other piece {gap_piece:.3f} mm "
              f"(nominal {nom_pp:g})\n"
              f"    crush ribs: {len(sites)} x r{RIB_RADIUS_MM:g} mm "
              f"crest +{RIB_INTERFERENCE_MM:g} mm past nominal: "
              f"{site_str}  -> {path}")

    for n in notes:
        print(f"  note: {n}")

    tj = triple_junction_mm(regw)
    mnom = geo["mountains_nom"].exterior
    rib_pt = mnom.interpolate(rib_sites["mountains"][0][0])
    rib_pts = []
    for name in ("mountains", "valley"):
        ring = geo[f"{name}_nom"].exterior
        for d, kind in rib_sites[name]:
            p = ring.interpolate(d)
            rib_pts.append({"name": name, "kind": kind, "x": p.x, "y": p.y})
    print("\nthin-neck check (debug, MIN_RIB_WIDTH_MM = "
          f"{MIN_RIB_WIDTH_MM:g} mm):")
    for name in ("mountains", "valley"):
        for x, y, w in thin_spots(geo[f"{name}_nom"]):
            print(f"    {name:9s} ({x:.1f}, {y:.1f}) width {w:.2f} mm")
    render_preview(geo, s, tj, holes, stamps, ribbed_geo, rib_pt, rose,
                  rose_c, rib_pts)
    print(f"\nall bodies/pieces watertight: {ok}")
    print("canonical Makefile output for this stage: out/p4_mini/frame.3mf "
          "(replaces out/p4_bay_420mm/frame.stl; old p4_bay_* dirs are "
          "superseded)")
    print("slicing note (G4): walls are VERTICAL, no draft -- enable "
          "elephant-foot compensation.")


if __name__ == "__main__":
    main()
