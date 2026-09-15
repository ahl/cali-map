# California Topo Puzzle Map — Design Log

## HANDOFF STATE (written 2026-09-14 at a context reset — READ FIRST)

**Where things stand (updated 2026-09-15):** **T3** is BUILT, converged
(`make -n` clean), all bodies watertight, and CLEARED TO PRINT —
out/p4_mini/{frame.3mf,mountains.stl,valley.stl}; ahl is about to print
it. out/p5/ (frame.3mf + 3 piece STLs) is built from the SAME
parameters. Everything regenerates via `make` (D12); config.toml +
overrides/ + assets/compass.svg are the complete inputs.

**T3 = frame 0.10 / pair 0.20 (symmetric) / ribs 0.05 mm crush,
hand-placed.** Full spec + rationale in the T3 entry under "Print
sessions"; the two changes that matter most are the symmetric pair rule
(no more valley zero-clearance exception) and ribs now being specified
as OVERLAP WITH THE MATING FACE, which fixed pair ribs that were
silently 0.04 mm short of touching. **ahl: if T3 feels good, lock these
clearances in.**

**Awaiting from the T3 print:** overall fit/snugness at the new
clearances, rib retention when tipped with a from-scratch pair, whether
frame 0.10 binds (it was 0.15 through T1+T2 and "pretty locked in"),
18 mm finger-hole ergonomics, 6 mm letter "E" legibility. Each maps to
a config knob; iterate: bump [output].build_tag, adjust knobs,
`make p4`. Note T3 moved frame AND pair together, so a too-tight result
won't isolate which — and the coupon has no desert, so three-piece
wedging stays untested until P5.

**Then the endgame (P6):** full-size mountains DRESS REHEARSAL in a
plentiful color (decides flat-vs-VERTICAL printing — see Filament
logistics / vertical-printing notes) -> final prints: frame (4-color,
brim ~4 mm), valley green, desert yellow, mountains brown LAST (scarce
filament, print once).

**Open items parked deliberately:**
- D11 per-scale min-width pass NEVER RAN — and the "somewhere" is now
  LOCATED: the mountains spur at Petaluma/Sonoma just N of San Pablo
  Bay, 0.94 mm wide (P4 window (50.1, 76.6) = lon/lat -122.19, 38.86;
  `p4_bay_coupon.thin_spots()` reports it every build). T2's
  too-tight-together finding traces here. ahl 2026-09-15: deliberately
  NOT modifying the spur — he wants to keep the shape; T3 addresses it
  with tolerance + rib placement instead. Still parked.
- Full-depth bodies (gray under pieces / land color to the floor):
  revisit per ahl after judging translucency + teal cavity floors in
  prints; spec sketched in the T1 session note.
- Ironing: RESOLVED (ahl 2026-09-14, rose test coupon) — per-part "Top
  surfaces" ironing on the WATER body only, flow 20% at 20 mm/s: "looks
  fantastic." Roll into frame.3mf's water body for T2/P5 (checklist
  updated below).
- Bottom version stamps: DISABLED (two failed styles); revisit only via
  a dedicated small test print.
- Waterways (D9): deferred to the very end; data ready in
  data/p2_waterways.geojson; baseline = no waterways.
- US-Mexico line uses the NE polyline (consistent piece/frame geometry;
  ~800 m from Census truth — ahl accepted; Census switch is a small
  p2_land.py change if ever wanted).
- out/p4_bay_235mm/ and out/p4_bay_420mm/ are OBSOLETE early coupons.

**Working norms that are easy to lose:**
- Agents: never run jj/git/make; they run stage scripts directly; the
  coordinator commits after review and runs `make`/`make -n` to prove
  convergence. BATCH spec changes to in-flight agents (trickling five
  addenda serialized ~3 h once).
- Gap measurements: global minima at triple junctions are ARTIFACTS
  (two clearance regimes meeting at a point); judge fit by the
  seam-excluded medians the builds now print.
- ahl's markup loop: he draws on any render (red=mountains,
  orange=coast, or edge lines), the marks get extracted into
  overrides/*.geojson, and build_regions applies them — see [overrides].
- Machine quirks: ahl's shell aliases cp/rm to interactive (use
  /bin/cp, /bin/rm in scripts/background commands); stock make 3.81
  (no grouped targets — ride-alongs use @touch recipes); jj snapshot
  size limit set to 8 MB repo-level; STL/3MF/data/ are gitignored.

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
| D19 | **Region KEY (ahl 2026-09-15):** a rectangular plate inset into the P5 frame over NEVADA, listing the five regions (Pacific Ocean, Coastal, Mountain, Valley, Desert) each with a circular colour-swatch plug beside it. Cut as a recess exactly like a piece cavity. **PERMANENT press fit** — no crush ribs, no poke-hole, `[key].interference_mm` (0.05 total) of squeeze, glue optional. Bottom sits on the tray floor at the same z as every piece; **top is flush with the tallest terrain ON ITS BOUNDARY** — the build walks the rectangle's perimeter every run and takes the max, so the plate finishes level with the ground it actually abuts and moving/resizing the key re-heights it automatically (there is no height knob; verified by moving the key and watching 6.24 -> 6.69 mm). "Adjacent" means on the boundary line, NOT merely nearby: an earlier band-sampling version picked up a peak standing off from the key and made it 1.2 mm too tall. Labels are 2D-PRINTED (`out/p5/key_insert.pdf`, sized to a 0.2 mm recess) — FDM text at this size fights the 0.4 mm nozzle. Config `[key]`: enabled, center_mm, width_mm, height_mm, adjacent_search_mm, interference_mm, pocket_*, label_recess_mm. Location picked by scanning for the largest clear gray non-CA land block. Plug dimensions deliberately NOT yet fixed — decide from `pipeline/key_pocket_coupon.py` (-> `out/key_coupon/{pocket_coupon,plug}.stl`), which reads the pocket size from this same config so the coupon always matches the real key. The standalone key-panel build was REMOVED 2026-09-15 (ahl: "get rid of the stand-alone key stuff"); `key_panel.py` is now a pure library shared by p5_final and the coupon. | |
| D18 | **Retention & disassembly (ahl 2026-09-14, from T1):** pieces stay seated through handling (T1: mountains fell out when tipped); the FINGER POKE-HOLES (18 mm, may span piece-piece seams) are THE disassembly mechanism. Retention via crush ribs on piece walls (rib_* knobs; ~0.05 mm interference, tune from T2 print). Clearances split by interface: 0.15 total everywhere (frame 0.15 single-side kept from T1's good fit; piece-pair 0.075/side, was 0.30 total = loose valley). | |
| D17 | **Compass rose (ahl 2026-09-14):** 8-point nautical rose (4 cardinal + 4 intercardinal, split-shaded points, center circle, outer ring, N/E/S/W serif letters) in the bottom-left Pacific of the Frame. Concept: "compass rose.jpeg". Design source: assets/compass_rose.svg (parametric generator pipeline/compass_rose.py — edit SVG directly or params). **Makes the Frame a 4-COLOR print** (adds black for rose outlines + lettering). Physical size + emboss method decided at placement. | |
| D16 | **The Frame is a TRAY (ahl 2026-09-13):** a continuous floor (FLOOR_MM = 1.2, 6 layers) runs under the whole footprint; cavities are recesses, not through-holes — pieces rest ON the Frame. Poke-holes (2x 8 mm circles in the floor per piece, at interior points) allow pushing pieces out from below. Pieces carry BASE_MM - FLOOR_MM of slab so all datums/tops align. Water/base height: 3.0 mm proposed for final rigidity (ahl deciding 2.0-3.0); G2 relief rides on top (total max ~11.5 mm at 3.0). | |
| D15 | **PIECE PLAN REVISED (ahl 2026-09-13, supersedes D2/G11 piece-hood):** the model = the **FRAME** + THREE removable pieces (Mountains, Valley, Desert). **"Frame" (ahl's term, confirmed) = non-California land (gray) + water (Pacific + SF Bay, one continuous color) + the California coastal region (yellow), with the Channel Islands as yellow islands on the water** — one 3-color AMS multi-body print. Coast is not removable. Multi-body 3MF path already validated (NOTES-3mf.md). **Explicit (ahl 2026-09-14): the gray non-CA land carries FULL TERRAIN (gray = recolor, not flattening), and water runs to the map edge with no gray ring — the P4 mini-frame rehearses both.** | |
| D14 | **Color spec (ahl 2026-09-13):** the ocean is ONE continuous water color across the whole map — it continues along the Oregon and Mexico coasts, regardless of piece ownership; all non-California land = frame gray; CA regions = their piece colors. Frame and coast pieces are each two-color prints via a filament swap at datum z (water at/below 2 mm, gray/region color above). Piece parting lines through open water are physically real but color-invisible. | |
| D12 | Automation contract: **`make`** rebuilds exactly the stale artifacts. Every stage target depends on config.toml + overrides/*.geojson + its script + upstream artifacts, so markup/knob changes can never be silently ignored (the P4 stale-cache bug class). Stages: p0 p1 p2 p15 p15b p4; `make -n` previews. | ahl 2026-09-13 |
| D13 | **Final-map aspect = the P1.5 slab at 135 x 150** (CA bbox + 40 km N/E/S + 67.5 km ocean west; 0.9 aspect). ahl 2026-09-13: "we're going to use that aspect ratio for the final map" | |
| D10 | Map area may be REDUCED in the final crop | ahl intentionally over-cropped the reference area. End-stage parameter; affects only the frame, never the pieces. Only reductions. |
| D11 | Physical scale decided at the END; possibly multiple scales | Geometry/borders in map meters; scale, Z-exaggeration, clearance applied at mesh export. Per-scale border min-width pass required (printable width is fixed in mm). |
| D9 | Waterways/lakes as second color on EACH piece — **OPTIONAL** | ahl may or may not print with these; keep it a build flag. Default output = solid single-color pieces; water variant = region body minus water inlays + water bodies in one 3MF (AMS + Bambu Studio confirmed). Prototyped P3, implemented P5, final call at the end. |

## Data provenance (complete download inventory)

Everything below is public domain (US Gov) or Natural Earth public
domain; no attribution required for the printed object. All caches live
under data/ (gitignored, regenerable). Fetched 2026-09-13/14.

1. **Elevation**: AWS Terrain Tiles ("terrarium" encoding, Mapzen/
   Nextzen dataset on AWS Open Data), anonymous:
   `https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png`
   - zoom 9 (~250 m) statewide mosaic -> data/dem_ca_albers_250m.npy
     (pipeline/p0_build_dem.py; 550 tiles)
   - zoom 11 (~120 m) Bay Area window fetches (pipeline/dem_hires.py;
     ~150 tiles) for the 1:1M inset
2. **Region basis**: California Geological Survey Note 36 geomorphic
   provinces, via the CA Dept of Conservation ArcGIS server:
   `https://gis.conservation.ca.gov/server/rest/services/CGS/GeoGems/MapServer/2/query`
   (f=geojson) -> data/cgs_geomorphic_provinces.geojson (13 features
   incl. Coastline SubProvinces)
3. **Political boundaries / land authority**:
   - US Census cartographic boundary states 1:500k (2023):
     `https://www2.census.gov/geo/tiger/GENZ2023/shp/cb_2023_us_state_500k.zip`
     -> data/census/ (CA polygon = THE land/CA authority; state lines)
   - Natural Earth 10m (naciscdn.org/naturalearth/10m/):
     `cultural/ne_10m_admin_1_states_provinces_lines.zip`,
     `cultural/ne_10m_admin_0_boundary_lines_land.zip` (US-Mexico line),
     `cultural/ne_10m_admin_0_countries.zip` (Mexico land)
     -> data/ne_borders/, data/ne_countries/
4. **Hydrography** (deferred waterways option, G10): USGS National
   Atlas / Small-Scale 1:1,000,000:
   `https://prd-tnm.s3.amazonaws.com/StagedProducts/Small-scale/data/Hydrography/streaml010g.shp_nt00885.tar.gz`
   `https://prd-tnm.s3.amazonaws.com/StagedProducts/Small-scale/data/Hydrography/wtrbdyp010g.shp_nt00886.tar.gz`
   -> data/hydro/, filtered to data/p2_waterways.geojson
5. **ahl-authored inputs** (tracked in jj, NOT downloads): overrides/
   *.geojson (extracted from his markups; marked source images at repo
   root), assets/compass.svg + compass.ai (his artwork).

## Original source-vetting notes (2026-09-13)

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
- **G2 — Vertical exaggeration: RESOLVED; NORMALIZED 2026-09-14.**
  Canonical rule: **z = true height x 9.3 x horizontal scale** (config
  [output].z_exaggeration) — constant, grid-independent. 9.3 is the
  factor ahl print-validated on the P1.5 slab ("very pleasing").
  Supersedes the "5 mm at CA max per 150 mm" formulation whose CA-max
  sample varied with grid resolution (caused 9.3-vs-8.8 bookkeeping
  drift between builds; the mini-frame coupon shipped ~5% shallower —
  fine for fit testing, not rebuilt). P5 and all future builds use the
  config value; the older drivers' internal rule is superseded and gets
  switched over next time each is touched.
- **G3 — Clearances**: PLA-on-PLA puzzle fit; likely ~0.15–0.25 mm/side,
  calibrate with a test coupon before committing to full prints.
- **G4 — Wall geometry**: vertical vs. slightly drafted piece walls
  (draft eases insertion/removal). Deferred.
- **G5 — Frame tiling**: if > 256 mm, how to split the frame (straight
  seams vs. following state borders) and join tiles (dovetails? pins?).
- **G6 — Overall scale: RESOLVED 2026-09-13.** Final product = 254 mm
  total N-S (10 inches; config [output].total_ns_mm), scale 1:4.469M,
  footprint 228.6 x 254.0 mm, CA ~236 mm N-S. Single-plate frame fits
  the 256 mm bed with ~2 mm margin (CONFIRMED by ahl: he has printed
  full edge-to-edge 256 mm parts on this machine; no fit test needed). 420 mm variant SET ASIDE. Frame tiling (G5) likely
  moot at this size.
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
  - **P1.5b — Bay Area inset** [SKIPPED per ahl 2026-09-13 — not needed;
    the statewide slab print validated the regions. Artifacts remain in
    out/ and regenerate with the chain; also spawned dem_hires.py.]
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

## Print settings checklist (check before EVERY print)

ALL PARTS
- [ ] Layer height 0.2 mm, first layer 0.2 mm (all model z-dims are
      0.2 multiples — NO adaptive layers)
- [ ] Elephant-foot compensation ON (0.15 mm)
- [ ] Seam position: Aligned

FRAME (frame.3mf — 4-color)
- [ ] Wall generator: ARACHNE (NOT the Classic default — needed for the
      rose's 0.45-0.8 mm features)
- [ ] Filament slots: 1 = CA-land blue, 2 = water teal, 3 = gray,
      4 = black (re-check after every re-import)
- [ ] Prime tower ON; "flush into objects' infill" ON
- [ ] Flush volumes: raise black->teal and black->blue above default
- [ ] Infill 20-25% (grid/gyroid)
- [ ] Do NOT move the frame's parts individually (aligned in absolute
      coords; move the object as a whole only)
- [ ] Ironing: ON, per-part on the WATER body ONLY, ironing TYPE = "top
      layers"/"top surfaces" (irons every locally-exposed upward face).
      NOT "topmost surface(s) only" -- ahl found that mode irons
      nothing on the water part, because it restricts to the single
      highest Z, which the raised ink shadows (both options are
      correctly per-part-scoped; this is about Z-filtering within the
      part, not global vs. per-part). Flow 20% at 20 mm/s. Validated on
      the rose test coupon 2026-09-14 -- CAVEAT (ahl 2026-09-14): unlike
      the coupon's single flat disk, the real frame's "water" part is
      m_floor + m_upper concatenated (p4_bay_coupon.main), so it has
      TWO disjoint top-facing regions at different Z: the open-water
      surface (BASE_MM, what we want ironed) AND the cavity floor under
      mountains/valley/desert (FLOOR_MM, hidden once pieces are seated).
      "Top surfaces" irons BOTH (it has no Z filter) -- expected
      harmless (no dimension-critical spec depends on cavity-floor
      finish; extra smoothness there may even help pieces sit flatter),
      just extra ironing time on hidden area. Not yet print-tested on
      the full frame -- confirm at T2/P5.

PIECES (mountains/valley/desert STLs — single color)
- [ ] Separate plate from the frame (don't ride the color changes)
- [ ] Top shell layers 5-6 (sloped terrain; avoid infill show-through)
- [ ] Orientation as imported (terrain up)

FINAL 225 x 250 FRAME ONLY
- [ ] Brim ~4 mm (the 250 mm N-S size reserved bed room for it)

## Filament logistics (ahl 2026-09-14)

- GREEN (valley): plentiful — the valley is the designated tuning piece
  (cheap + reprintable), which the enclosed-zero-clearance design
  already exploits.
- BROWN (mountains) and YELLOW (desert): SCARCE — print those final
  pieces ONCE, from validated parameters. Do NOT burn them on coupons:
  test-print pieces in green/any plentiful color (fit doesn't care).
  The mountains piece is also the biggest filament consumer of the
  three; if a reprint risk appears, order more brown before P6.
- ahl's plan: coupon pieces in WHITE (T1 done so); frame coupons in the
  REAL frame colors (validates the actual 4-color result). The final
  mountains gets a full-size DRESS REHEARSAL in a plentiful color
  before the one-shot brown print.
- **VERTICAL PRINTING of pieces (open, decide at the rehearsal):** ahl
  previously printed a similar-size CA topo vertically (brim + some
  supports) with much better terrain resolution (slope becomes a side
  wall: XY resolution instead of 0.2 mm z-terracing). Cautions agreed:
  plate-contact edge is a fit surface (EF squish); texture mismatch with
  the flat-printed frame terrain is ACCEPTED (frame = context, lower
  res OK); ribs/overhang handling could be messy. If a flat plate edge
  is needed, split the valley at its NATURAL seam — Sacramento Valley /
  San Joaquin Valley at the Delta — so the cut reads as geography (and
  could become a real fifth piece). Rehearsal print decides; flat
  printing may be good enough.

## Print sessions

- **T1 (2026-09-14, in progress):** ahl printing the mini-frame set
  (4-color frame.3mf w/ vector rose + mountains/valley pieces, plain
  bottoms). IRONING DEFERRED (revisit later; if wanted, the route is
  per-part "Top surfaces" on the WATER body — "topmost" mode would skip
  the water plane since terrain rises above it; note rose blue/gray ink
  merged into terrain bodies, so rose stays matte under per-part water
  ironing). Awaiting: fit at 0.15 mm/side (G3), poke-hole/tray feel,
  4-color seam quality, rose crispness, AND the "bodies own their full
  depth" decision (deferred by ahl until seen in plastic): judge how
  single-layer coast/gray land reads over the teal sub-surface — if the
  teal ghosts through or the teal cavity floors look wrong, T2 switches
  to full-depth bodies (land color to the floor, GRAY under the
  removable pieces; also fixes the edge cross-section and kills the
  translucency issue; costs a little purge in the floor layers).

- **T2 (2026-09-15): mountains+valley TOO TIGHT together in the T1
  frame** — ahl printed T2 mountains + T2 valley (ribs + the tightened
  0.08 mm total pair clearance) and they don't both fit into the T1
  frame at once. Mixing generations works: ONE T1 piece + ONE T2 piece
  fits fine either way, and T2 valley + T1 mountain in particular is
  "especially nice and snug" — stays seated through handling, only
  releases via the poke holes (D18's exact target behavior).
  ROOT CAUSE per ahl: TOPOGRAPHICAL, not rib interference — a narrow
  mountains SPUR just north of the SF Bay pinches the mountains/valley
  boundary to a fragile width. Located precisely (a `thin_spots()`
  debug pass, agreed on independently by BOTH pieces' outlines):
  **P4 window (50.1, 76.6) = lon/lat (-122.19, 38.86), Petaluma /
  Sonoma just N of San Pablo Bay, 0.94 mm wide** — the same feature D11
  flagged and never fixed ("a ~0.8 mm neck somewhere; printable but
  fragile"). CORRECTION to an earlier claim in this log: the pair ribs
  were NOT on the spur. `pair@(84.9, 14.9)` converts to lon/lat
  (-120.35, 36.36) — near Fresno, ~65 mm away; that claim came from
  misreading a pixel-cropped preview, and coordinate conversion
  disproved it. So no rib was ever loading the neck; the tightness there
  is just the uniform pair clearance landing on an already-thin spot.
  ahl's call: do NOT modify the spur geometry (D11 pass stays deferred)
  — fix it with tolerance + rib placement only. See the T3 spec below.
- **Rib-site visualization added (ahl 2026-09-15):** both
  `p4_bay_coupon.render_preview` and `p5_final.render_preview` now mark
  every crush-rib site in red on the assembled + exploded panels
  (triangle = piece-pair rib, dot = frame rib) — added specifically to
  investigate this finding; keep it, it's generally useful for judging
  rib placement.
- **T1/T2 tolerance table + ahl's read (2026-09-15).** Frame clearance
  was 0.15 for BOTH T1 and T2 (never changed); only the pair number
  moved. Physical pairings, by what each piece actually printed at:
  T1<->T1 pair 0.30 (loose); T2<->T2 pair 0.08 (too tight together);
  T2 valley + T1 mountain 0.15 ("especially nice and snug" — but that
  mountain had NO ribs); T1 valley + T2 mountain 0.23 (too loose).
  ahl's conclusions: the T1-frame/T2-mountain snugness is the RIBS
  doing their job; the 0.15 mixed pairing is snug in a way that worries
  him — it loads the fragile SF Bay spur (D11) and might crack it; the
  spur is NOT to be modified (no geometry changes this pass); and
  remember all pieces push on each other to fill the frame, so an
  over-tight local joint carries the whole system's contact pressure.
  Blind alleys along the way, all reverted: a blanket
  `clearance_pair_per_side_mm` walk-back (0.10, then 0.16) and extending
  zero-clearance to desert — both premature, both undone before the T3
  decisions below. Desert's zero-clearance (for the mountains+desert
  snug-fit goal) stays parked as its own future decision.
- **T3 spec — FINAL, built and cleared to print (ahl 2026-09-15).**
  `build_tag` = "T3"; `make p4 p5` converged, all bodies watertight.

  | interface | gap | contributors | rib bite |
  |---|---|---|---|
  | piece <-> frame | **0.10 mm** | piece only (cavity at nominal) | 0.05 mm |
  | piece <-> piece | **0.20 mm** | both pieces, 0.10 each | 0.05 mm |

  Changes from T2: `clearance_per_side_mm` 0.15 -> 0.10 (lean on ribs at
  a tighter base fit); `clearance_pair_per_side_mm` 0.08 -> 0.10 with
  `enclosed_piece_zero_clearance` -> **false**, dropping the valley
  exception for a symmetric rule (under the enclosed rule 100% of the
  pair gap, and so 100% of the relief at the Petaluma spur, came off
  mountains alone; symmetric spreads it). Ribs r0.4 mm, 0.05 mm crush,
  hand-placed: P4 mountains 4 (3 frame + 1 pair), P4 valley 6
  (5 frame + 1 pair), P5 valley all-pair (it touches no frame).
  Caveats accepted going in: frame and pair both moved at once, so a
  too-tight T3 won't isolate which; and the coupon has no desert, so
  the three-piece wedging (and mountains<->desert) is untested until P5.
  ahl: if T3 feels good, lock these clearances in.
- **Ribs are specified as OVERLAP WITH THE MATING FACE, not as an offset
  from nominal (ahl 2026-09-15) — and this caught a real defect.** The
  old rule put every crest at nominal + interference, which is only
  correct against a FRAME wall (cavity cut at nominal). A sibling piece
  is clearance-cut too, so its face has retreated `clearance_neighbor`
  past nominal and the rib fell short by exactly that much. Measured on
  T3-as-first-built: pair ribs sat **0.040 mm short of touching** —
  the mountains/valley seam had ZERO rib retention and would have
  printed that way unnoticed. (It also retro-explains T2 "too tight
  together": there valley took ZERO clearance, so its wall sat on the
  shared line and mountains' pair rib drove a hard 0.05 mm into solid
  valley material on top of only 0.08 mm of gap. Asymmetric, too —
  valley's own pair rib was 0.03 mm short and inert.) Now each rib
  measures the real distance to the as-cut neighbour (`neighbor_pieces`)
  and lands its crest that far plus the interference, so the knob means
  "how deep do I crush into whatever I press against" at both interface
  types and self-corrects when any clearance changes. Frame ribs are
  unchanged. Verified: P4 0.053/0.050 mm bites, P5 all seven engaged
  pair ribs 0.050-0.054 mm against a 0.05 target; seam gap 0.17 -> 0.000
  with ribs. Both builds print a per-rib bite report every run — if a
  future clearance change ever switches ribs off again, it will say so.
- **Crush-rib placement is now MANUAL (ahl 2026-09-15).** The automatic
  placer got four rewrites in one session and produced a surprise every
  time — a whole side skipped, two ribs on one spur, every slot going to
  one interface type, zero pair ribs — because good placement is a
  judgement about the assembled object, not something a straightness/
  spread proxy captures, and there are only ~4 ribs per piece. New
  contract: config **`[print.ribs]`**, one hand-picked (x, y) list per
  build+piece (`p4_mountains`, `p5_desert`, ...). Coordinates are
  approximate — read them straight off the red rib markers in
  out/p4_preview.png / out/p5_preview.png and each SNAPS to the nearest
  point on that piece's nominal outline. The build prints every snap
  distance, flags >2 mm as a likely typo, and warns (but obeys) if a
  site lands within 5 mm of a thin neck. Delete a list to fall back to
  the automatic placer for that piece. Seeded with exactly what the
  placer last chose, verified a no-op on both builds (all snaps
  <0.05 mm). `choose_rib_sites` survives as that fallback, simplified
  to ahl's actual rule — ribs matter most on big FLAT stretches, since
  a curvy stretch already self-interlocks — plus a floor of one pair
  rib, with `ribs_per_piece`/`min_rib_width_mm` applying only to it.

## Observation log (noted, NOT to be acted on unless ahl says so)

- **PLA translucency at thin land (ahl 2026-09-14):** near-datum coastal
  land sits ~1 layer (LAND_MIN_MM = 0.2) above the water body; PLA is
  slightly translucent, so the water color may ghost through. OK for the
  mini-frame print. Known remedies if ever wanted: raise LAND_MIN_MM to
  2-3 layers, or give land bodies downward depth (color the top N mm of
  the slab in the land filament instead of starting at datum).

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
