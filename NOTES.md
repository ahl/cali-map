# California Topo Puzzle Map — Design Log

A 3D-printable, to-scale topographic map of California as a region-puzzle
set into a frame of the surrounding geography.

## Concept

- **Puzzle pieces**: California split into its four classic land regions —
  Coast, Mountains, Central Valley, Desert. Each is a separate printed part
  with real terrain relief; together they assemble into California.
- **Frame**: surrounding topo map (S. Oregon, Nevada, W. Arizona, N. Baja/
  Sonora, corners of Idaho & Utah) with a California-shaped cavity.
  Printed gray/white — present, but visually "not the subject."
- **Ocean**: Pacific included, rendered as a flat datum plane (no bathymetry).

## Decisions

| # | Decision | Notes |
|---|----------|-------|
| D1 | Four regions: Coast, Mountains, Central Valley, Desert | Per CA curriculum scheme; exact borders TBD from canonical source (see G1) |
| D2 | Coast piece extends into the Pacific as flat ocean, two-color print | Keeps Channel Islands physically connected to one rigid piece |
| D3 | Frame printed gray or white | Signals "context, not subject" |
| D4 | Ocean = flat datum plane | No bathymetry |
| D5 | Linear (planimetric) scale; Z scaled independently | Terrain gets vertical exaggeration; sits on a fixed-height solid base |
| D6 | Print bed 256×256 mm; whole model ≤ 1000×1000 mm total | Either frame fits one bed, or frame is carved into tiles |
| D7 | Material: PLA. Fit: snug but disassemblable | Clearance values TBD (see G3) |
| D8 | Version control: jj (colocated git), repo = this directory | |
| D9 | Waterways/lakes as second color on EACH piece | Requires multi-material (rivers span Z — layer swap won't work), so pieces export as multi-body 3MF (region body + water bodies). Designed in from start; prototyped P3; implemented P5. Fallback if no AMS: recessed engraving (paintable). |

## Data sources (verified accessible 2026-09-13)

- **Region boundaries (candidate canonical source)**: California Geological
  Survey *Note 36* geomorphic provinces — 11 provinces as GIS polygons,
  queryable as GeoJSON from the state ArcGIS server:
  `https://gis.conservation.ca.gov/server/rest/services/CGS/GeoGems/MapServer/2`
  (verified: layer metadata returns; polygon feature layer, EPSG:3857).
  Backup: EPA Level III ecoregions (epa.gov shapefile downloads).
- **Elevation (DEM)**: AWS Terrain Tiles (Mapzen "terrarium" PNG tiles),
  anonymous access, global incl. Mexico:
  `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
  (verified: tile fetch returns 200). At ~1:1,000,000 print scale, even a
  0.4 mm nozzle only resolves ~400 m ground distance, so tile zoom ~8–10
  is plenty.
- **State/national boundaries & coastline**: Natural Earth (10m) or US
  Census TIGER. Needed for the CA outline (piece/frame parting line is the
  state border) and for engraved/reference borders on the frame.

## Gaps / open questions

- **G1 — Region borders**: hybrid approach agreed 2026-09-13:
  - *Central Valley* = CGS Great Valley province
  - *Desert* = CGS Mojave Desert + Colorado Desert + Basin and Range
    (desert is a rainfall concept — elevation can't draw this line)
  - *Coast* = **elevation-derived**: land contiguous with the shoreline
    below a threshold (~150–400 m, tunable), MINUS Great Valley (the
    valley is near sea level and connects to the ocean via the Delta /
    Carquinez Strait — must be excluded explicitly). Morphological
    smoothing + minimum-width enforcement so the piece is printable.
  - *Mountains* = everything else.
  - **Remaining decision**: pick the coast elevation threshold from
    side-by-side rendered candidates (Phase 1 check-in).
- **G2 — Vertical exaggeration factor**: TBD (typical 3–8× at this scale).
  Also: base thickness value.
- **G3 — Clearances**: PLA-on-PLA puzzle fit; likely ~0.15–0.25 mm/side,
  calibrate with a test coupon before committing to full prints.
- **G4 — Wall geometry**: vertical vs. slightly drafted piece walls
  (draft eases insertion/removal). Deferred.
- **G5 — Frame tiling**: if > 256 mm, how to split the frame (straight
  seams vs. following state borders) and join tiles (dovetails? pins?).
- **G6 — Overall scale**: pick once map-area extent is fixed in km.
- **G7 — Two-color strategy for the coast piece**: layer-swap at the ocean
  datum Z (easy, works on any printer) vs. multi-material. Layer-swap
  favors ocean-below/land-above color split.
- **G8 — Map projection**: need one that keeps "to scale" honest across
  ~11° of latitude (likely a local transverse Mercator or CA Albers,
  EPSG:3310). CA Albers is equal-area and the state standard — probable
  choice.
- **G9 — Multi-material capability**: RESOLVED 2026-09-13 — printer has an
  AMS; slicer is Bambu Studio. True second-color waterways via multi-body
  3MF, colors assigned per body in Bambu Studio.
- **G10 — Waterway selection & width**: which rivers/lakes make the cut
  (NHD is exhaustive; Natural Earth has just the majors), and how much to
  exaggerate river width (true width is sub-nozzle at this scale;
  ~0.8–1.0 mm printed minimum).

## Plan (phases with check-ins)

Each phase ends with a check-in deliverable; nothing downstream starts
until its inputs are signed off. Every phase is a jj commit.

- **P0 — Data & pipeline skeleton.** Fetch DEM tiles for the map area,
  CGS provinces, state borders; reproject everything to CA Albers
  (EPSG:3310); build the mosaicked heightfield.
  *Check-in: shaded-relief PNG of the full map area → confirm extent/crop
  (settles G6 scale too).*
- **P1 — Region boundaries.** Implement the hybrid G1 rule; render 3–4
  coast-threshold candidates as colored overlays on the relief.
  *Check-in: pick the threshold; sign off all four region borders.*
- **P2 — Layout & scale.** Fix overall physical size, frame tiling plan
  (G5), minimum piece widths, projection sanity.
  *Check-in: dimensioned 2D layout drawing.*
- **P3 — 3D prototype.** Generate STL for ONE piece + matching frame
  corner at 2–3 vertical exaggerations; base height proposal (G2).
  Include a waterway body on the prototype piece to validate the
  multi-body 3MF approach (D9).
  *Check-in: Blender screenshots + STLs to open in slicer; pick
  exaggeration & base.*
- **P4 — Fit coupon.** Small test print: one small real boundary segment
  as plug + socket at 2–3 clearances (G3), plus wall draft experiment
  (G4). *Check-in: user prints and reports fit.*
- **P5 — Full generation.** All four pieces + frame tiles + ocean datum;
  two-color coast piece split at ocean Z (G7); watertight/manifold
  verification on every STL.
  *Check-in: full set of STLs + assembled render.*
- **P6 — Print & iterate.** Slice, print, adjust from reality.

## Viewing workflow

- 2D check-ins: pipeline emits shaded-relief/overlay PNGs, sent into the
  conversation directly.
- 3D check-ins: STLs imported to Blender (MCP bridge) → viewport
  screenshots; user can also Quick Look STLs in Finder or open in slicer.

## Toolchain

- **Mesh generation**: Python via `uv` (rasterio/shapely/pyproj/trimesh) —
  DEM → heightfield → region-masked watertight STL per piece. (System
  python3.14 has only numpy; uv manages the rest per-script.)
- **Inspection/preview**: Blender (installed, MCP bridge available).
- OpenSCAD (installed) not suited for DEM-scale meshes; not planned.
