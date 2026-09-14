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
| D12 | Automation contract: change a region aspect -> `uv run pipeline/regen_all.py` rebuilds the whole chain (p1 render, land, vectors, slabs, coupons) in dependency order | ahl 2026-09-13, after print validation |
| D13 | Slab/final-map aspect: ahl likes the P1.5 aspect (CA bbox + 40 km N/E/S) with MORE ocean west — WEST_PAD_KM = 50 added. Candidate template for the final frame crop (D10) | |
| D10 | Map area may be REDUCED in the final crop | ahl intentionally over-cropped the reference area. End-stage parameter; affects only the frame, never the pieces. Only reductions. |
| D11 | Physical scale decided at the END; possibly multiple scales | Geometry/borders in map meters; scale, Z-exaggeration, clearance applied at mesh export. Per-scale border min-width pass required (printable width is fixed in mm). |
| D9 | Waterways/lakes as second color on EACH piece — **OPTIONAL** | ahl may or may not print with these; keep it a build flag. Default output = solid single-color pieces; water variant = region body minus water inlays + water bodies in one 3MF (AMS + Bambu Studio confirmed). Prototyped P3, implemented P5, final call at the end. |

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

## P0 findings (2026-09-13)

- Heightfield built: ~4800 x 5650 px @ 250 m, EPSG:3310 (~1200 x 1410 km).
- **CGS layer has 13 features, not 11**: the classic provinces PLUS
  "Northern Coastline SubProvince" and "Southern Coastline SubProvince" —
  i.e., CGS itself demarcates a coastal strip. Evaluate in P1 alongside
  the elevation-threshold approach (could be the canonical Coast border,
  or a sanity check on our threshold choice).
- Terrarium DEM gotchas found & fixed in pipeline:
  - isolated garbage spikes (median-despike pass added);
  - Gulf of California is below sea level but not Pacific-connected
    within the frame → ocean mask = sea-level cells connected to Pacific
    OR touching map border;
  - genuine below-sea-level land kept as land: Death Valley, Salton
    Trough, Laguna Salada, subsided Sacramento Delta islands;
  - Albers rectangle bulges beyond the lon/lat box at corners → tile
    coverage must be computed from the projected rectangle.

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
  - **SETTLED 2026-09-13: coast = 25 m threshold + 13.5 km band**, with
    all rules (absorb, enclosure, lowland-valley, Carquinez gate,
    contiguity). ahl reviewed out/p1c_band_fine.png and picked 13.5.
  - P1 exploration history (all figures in out/): threshold sweeps
    150-450 m; band sweeps 5-12.5 km; low thresholds 50-200 m; agent
    explorations p1a (morphological simplify + polygon smoothing — came
    out over-trimmed at 3%) and p1b (curriculum-map transplant,
    registration IoU 0.971 — strong).
  - ahl's direction (2026-09-13): TWO live candidates —
    (1) p1d = RAW p1b image-derived coast strip + CGS valley/desert;
    (2) p1c family = very low threshold (<50 m) + 12.5 km band.
    Global rules (config.toml), all ahl-requested:
    - valley_absorb_km = 7.5 — coast near the Great Valley absorbed into
      valley (kills the Delta curl toward Sacramento); also absorbs
      Delta islets (island components near valley are valley, not Coast);
    - valley_fill_enclosed — non-valley mainland pockets cut off from the
      main landmass join the valley (Delta fringes, Sutter Buttes);
      connectivity-based, since water corridors defeat plain hole-fill;
    - band_source_min_width_km = 1.5 — shoreline band emanates only from
      open water (ocean/bays), not river-width Delta channels;
    - desert_north_limit_km = 100 — Desert north of Albers y=+100 km
      becomes Mountains (northern Basin & Range = Modoc country).
  - Agent finals (first p1a look was mid-iteration; finals are better):
    - p1a: 8.2% of CA, ONE mainland component, 20k->4k boundary vertices
      (open 3 km/close 6 km with sea+provinces as solid support, 50 km
      shore cap + 60 km geodesic cap, DP 3 km + Chaikin). Found CGS
      polygons miss the 250 m coastline (prov==0 slivers — patch with
      Census state polygon in P2). Contiguity via a real ~0.5-1 km
      Coast Ranges corridor east of Suisun.
    - p1b: IoU 0.971; per-report the scan is ~plate carrée (shear -0.01
      deg); forced-one-component variant used 218 km of shore corridors —
      p1d instead keeps shore-connected segments joined by the ocean
      shelf (D2), per ahl's preference for the raw strip.
  - **P2 cleanup contract** (applies to whichever coast wins): global
    no-exclave rule — every region's parts must connect to its piece
    (in-plane or via its printed shelf); sub-printable specks (Delta
    levee islets, coastal rocks) dropped at vectorization; per-scale
    min-width enforcement (D11).
- **G2 — Vertical exaggeration: RESOLVED 2026-09-13 (print-validated).**
  ahl printed the P1.5 slab and called the vertical scale "very
  pleasing" — the rule is **relief = 5 mm at CA's max elevation on a
  150 mm N-S print**, i.e. **~9.3x vertical exaggeration** (equivalently
  Whitney relief ≈ N-S extent / 30). Keep the exaggeration FACTOR
  constant across print sizes (relief grows proportionally with the
  model). Base thickness 2.0 mm validated on the same print. P3 may
  still bracket ±20% for the final build, but this is the default.
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
- **G11 — RESOLVED 2026-09-13: Channel Islands = ONE separate piece**,
  convex hull of all eight + 10 km ocean (out/p1f_islands_one_piece.png;
  config [islands]). Two-color print (ocean/land); own cavity in the
  frame. D2 revised: the mainland Coast piece no longer carries islands
  or an ocean shelf — the islands piece owns its ocean. Farallones
  SKIPPED. Terminal Island artifact -> mainland (P2). Bay islands stay
  inside the coast band. (Sizes: piece is 49x36 mm @235 final,
  88x64 mm @420.)
- **Decisions from ahl's 2026-09-13 review round**: waterways DEFERRED —
  baseline build assumes NO waterways (D9 stays optional, revisit at
  end); 3MF Bambu packaging VALIDATED in Bambu Studio (no print needed);
  P1.5 slab print and P4 coupon prints ON HOLD until regions finalized;
  NEW deliverable P1.5b — an engraved INSET print (coupon-style window)
  of the Carquinez/Vallejo area, where the regions interact messily;
  raster-jaggy borders (delta zoom) to be cured by vector smoothing in
  the per-scale pass, with specific spots escalated to ahl if automation
  isn't enough.
- **G8 — Map projection**: need one that keeps "to scale" honest across
  ~11° of latitude (likely a local transverse Mercator or CA Albers,
  EPSG:3310). CA Albers is equal-area and the state standard — probable
  choice.
- **G9 — Multi-material capability**: RESOLVED 2026-09-13 — printer has an
  AMS; slicer is Bambu Studio. True second-color waterways via multi-body
  3MF, colors assigned per body in Bambu Studio.
- **G10 — Waterway selection & width**: SOURCE RESOLVED 2026-09-13
  (researched, URLs verified): primary = **USGS Small-Scale (National
  Atlas) 1:1,000,000 hydrography** — already generalized to ~our print
  scale, public domain, Strahler stream-order attribute for filtering:
  - streams: `prd-tnm.s3.amazonaws.com/StagedProducts/Small-scale/data/Hydrography/streaml010g.shp_nt00885.tar.gz` (240 MB)
  - waterbodies: `.../wtrbdyp010g.shp_nt00886.tar.gz` (35 MB)
  - filter: streams Strahler >= 4–5 (drop -999/-998 sentinels), plus
    hand-picked iconic names (Owens, Salinas); waterbodies
    Feature in (Lake, Reservoir) and Area >= ~1.5 sq mi; clip by
    geometry, NOT State attr (keeps Tahoe, Mead, Havasu).
  Backup: Natural Earth 10m rivers/lakes + North America supplements
  (naciscdn.org, ~2 MB each; merged-set scalerank quirks).
  Avoid NHDPlus HR / 3DHP (too detailed; NHD frozen since 2024).
  Gotchas: SF Bay is "ocean" in every dataset — take it from our own
  coastline/DEM mask; Delta = main stems only; Colorado River is a
  centerline (buffer >= ~650 m ground width, union with Havasu/Mead
  polygons). Remaining: tune Strahler threshold + width function (P3/P5).

## Plan (phases with check-ins)

Each phase ends with a check-in deliverable; nothing downstream starts
until its inputs are signed off. Every phase is a jj commit.

- **P0 — Data & pipeline skeleton.** [DONE 2026-09-13] Fetch DEM tiles,
  CGS provinces, state borders; reproject to CA Albers (EPSG:3310);
  heightfield built. Extent approved (final crop may REDUCE it, D10).
- **P1 — Region boundaries.** [CLOSED — PRINT-VALIDATED 2026-09-13: ahl
  printed the statewide slab; "regions look excellent"; no
  mountain-as-valley errors; some mountains-as-coastal accepted as fine;
  Bay Area imperfections accepted for our purposes] 25 m +
  13.5 km band + all rules + ahl's markup overrides (Vallejo mountain
  corridor; p1_final red->mountains / orange->coast marks — overrides/
  *.geojson, applied by build_regions [overrides]). Definitive artifact:
  out/p1_final.png. Markup->extract->apply is a standing loop for any
  future tweak (red=mountains, orange=coast on any render).
- **P1.5 — Engraved one-piece validation print (ahl, 2026-09-13).**
  [BUILT, print on hold until P1 signs off] RECTANGULAR SLAB, 150 mm N-S
  — California plus ~40 km beyond the state line (N/E/S), Pacific as
  flat datum (Channel Islands on it) — engraved recesses (<0.5 mm wide,
  1-2 layers deep at 0.2 mm layer height) for BOTH the four-region
  borders AND political borders (state lines + US-Mexico). First topo
  print + early read on vertical exaggeration (built at 9.3x). Purpose
  per ahl: EYEBALL piece boundaries against real terrain in hand.
  Artifacts: out/p15_ca_engraved_150mm.stl, out/p15_preview.png.
  - **P1.5b — Vallejo inset** [BUILT]: 120x120 mm @1:1M engraved slab of
    the Carquinez junction (out/p15b_vallejo_inset.stl, p15b_preview.png)
    — for eyeballing the messiest region interactions.
- **P2 — Layout & scale.** [VECTORIZATION DONE on signed-off geometry
  2026-09-13] data/p2_regions.geojson (canonical, DP 500 m) +
  data/p2_regions_smooth.geojson (Chaikin x2 preview flavor) — both with
  ZERO gaps/overlaps, shared borders bit-identical; valley-coast contact
  0.000 km statewide (min separation 7.2 km); islands piece = 5th
  feature (hull+10 km, 19,264 km², 84 vertices, 9 km clear of coast
  piece); coast = 3 parts (mainland + Angel Isl + Treasure/Yerba Buena);
  Farallones dropped by name. QA: out/p2_regions_qa.png (with Vallejo
  vector inset). Remaining in P2: physical size decision (scale-at-end,
  D11), frame tiling plan (G5), per-scale min-width/tolerance passes,
  dimensioned layout drawing.
- **P3 — 3D prototype.** [NOT STARTED; foundations ready] Generate ONE
  real puzzle piece + matching frame corner at 2–3 vertical
  exaggerations; base height proposal (G2). Waterway multi-body deferred
  (D9: baseline = no waterways; 3MF packaging already validated).
  Mesh foundations exist (mesh_common.py, p15/p4 drivers).
  *Check-in: previews + STLs in slicer; pick exaggeration & base.*
- **P4 — Fit coupon.** [BUILT, print on hold until P1 signs off] Bay
  Area window pieces at both candidate scales + 10 mm frame rim
  (out/p4_bay_235mm/, out/p4_bay_420mm/, incl. frame.stl; pieces carry
  edge clearance for the frame opening). Geometry-level fit verified to
  <0.01 mm of nominal. *Check-in: ahl prints and reports fit (G3/G4).*
- **P5 — Full generation.** [NOT STARTED] All pieces (4 regions +
  islands piece) + frame tiles + ocean datum; two-color islands piece
  (G7/G11); watertight verification on every mesh.
  *Check-in: full set + assembled render.*
- **P6 — Print & iterate.** [NOT STARTED] Slice, print, adjust.

## Viewing workflow

- 2D check-ins: pipeline emits shaded-relief/overlay PNGs, sent into the
  conversation directly.
- 3D check-ins: STLs imported to Blender (MCP bridge) → viewport
  screenshots; user can also Quick Look STLs in Finder or open in slicer.

## P1 output: how boundaries are represented

- Source of truth = **config.toml [regions] + pipeline/p1_regions.py**,
  which deterministically regenerate the region layout from the DEM +
  CGS provinces. Nothing hand-drawn; every rule is a named config knob.
- Working representation = **region index raster**: uint8 grid aligned
  to the DEM (4791 x 5632 @ 250 m, EPSG:3310); values 0=sea, 1=Mountains,
  2=Valley, 3=Desert, 4=Coast. Candidate snapshots in data/*.npy
  (p1d_regions.npy etc.); p1a also produced vector polygons
  (data/p1a_coast_boundary.geojson, EPSG:3310).
- P2 converts the WINNING raster to the durable form: **vector polygons
  in Albers meters with shared borders snapped** — adjacent regions
  reference the identical polyline, which is what guarantees puzzle
  pieces mate. Those polygons + the DEM drive all mesh generation
  (P1.5 engraving grooves = the same border polylines).
- Known raster-stage flaw, cured in P2: CGS province polygons miss the
  250 m shoreline in places (prov==0 hairline cracks) — this is what
  invisibly fragments the coast band; the Census state polygon becomes
  the land authority in P2.

## DEM resolution strategy (2026-09-13, after ahl noticed inset softness)

- Global heightfield: zoom-9 terrarium, 250 m — sufficient wherever
  250 m <= ~0.12 mm in print (all full-map scales: 1:7.5M slab 0.03 mm,
  420 mm build 0.10 mm).
- 1:1M INSETS are data-limited at 250 m (0.25 mm): use zoom-11 (~60 m)
  window fetches via pipeline/dem_hires.py + finer heightfield
  (~0.12 mm/px). Grooves/regions stay on the 250 m raster (borders don't
  need hi-res).
- Slicer never smooths; nozzle physics low-passes anything < ~0.2 mm.
  Deliberate border smoothing lives in the P2 vector stage.

## Toolchain

- **Mesh generation**: Python via `uv` (rasterio/shapely/pyproj/trimesh) —
  DEM → heightfield → region-masked watertight STL per piece. (System
  python3.14 has only numpy; uv manages the rest per-script.)
- **Inspection/preview**: Blender (installed, MCP bridge available).
- OpenSCAD (installed) not suited for DEM-scale meshes; not planned.
