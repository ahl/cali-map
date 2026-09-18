# California Topo Puzzle Map — Design Log

## HANDOFF STATE (rewritten 2026-09-15 — READ FIRST)

**Everything is BUILT, CONVERGED (`make -n` clean) and WATERTIGHT.**
config.toml + overrides/ + assets/compass.svg are the complete inputs;
`make` (D12) regenerates exactly what is stale.

**The fit is SETTLED and print-validated.** ahl on the T3 coupon: *"the
T3 fit is great. I don't think I'd change it at all."* Marked LOCKED in
config with a banner; changing one means a fresh coupon print and a new
build_tag, not an edit.

| interface | gap | rib bite |
|---|---|---|
| piece <-> frame | **0.10 mm** (piece shrinks; cavity is nominal) | 0.05 mm |
| piece <-> piece | **0.20 mm** (0.10 each, symmetric) | 0.05 mm |

Crush ribs r0.4 mm, hand-placed. Poke holes 18 mm, hand-placed. The two
changes that made T3 work: the symmetric pair rule (no valley
exception), and specifying ribs as OVERLAP WITH THE MATING FACE, which
fixed pair ribs that were silently 0.04 mm short of touching anything.

**P5 IS BUILT, PRINTED AND ASSEMBLED (ahl 2026-09-17: "I printed it all
and it's fantastic").** Frame, mountains, valley, desert, key, five
plugs and the paper insert -- the whole object, complete. v1.0 is done.

Everything below describes a SHIPPED design, not a plan. The fit scheme,
the clearances, the rib placement, the key, the plug diameter and the
edge-stamp depth are all print-validated end to end; treat a change to
any of them as a new version with its own coupon print, not an edit.

**P5 outputs** (`make p5`): frame.3mf (5 parts: coast / floor / water /
gray / black rose — floor and water split so ironing can target the
visible water top only), mountains/valley/desert.stl, key.stl,
key_plug.stl, key_insert.pdf, p5_preview.png, p5_rib_markup.png.

**Hand placement is done for P5** (ahl's markup, extracted 2026-09-15):
ribs mountains 11 / valley 0 / desert 4; poke holes mountains 4 /
valley 2 / desert 3, each serving exactly ONE piece. (This USED to read
"mountains 5 ... one of them a mountains+valley seam hole" -- that
stopped being true when ahl's x/circle markup moved the second valley
hole off the seam to (106.8, 89.3). Moving it took a cut out of the
mountains piece, so mountains went 5 -> 4. The build's [poke] lines
report what each hole actually serves; trust those, not this.)
**Poke holes are cut into the FRAME FLOOR, not into the pieces**
(`floor_poly.interiors`; the build says "floor: one body, N
poke-holes") -- you push a piece up from underneath, and a hole through
the terrain would be visually wrong. So "serves mountains" means the
hole sits UNDER that piece; the count is service attribution, not
geometry. Confirmed from the exported STLs: valley and desert are
genus 0, and mountains' single ring is the valley seam, not a hole.
Consequence: moving a poke hole NEVER changes a piece.
VALLEY CARRIES NO RIBS ON PURPOSE — it touches no frame in P5 (nearest
approach 1.7 mm) and every mountains/valley rib was put on the
mountains side, which grips the joint either way since a rib bites the
mating face whichever piece carries it. Valley is therefore held
ENTIRELY by the mountains interface; if it ever feels loose, that is
the place to look.

**Recent fixes worth not re-breaking:**
- LAND AUTHORITY: bodies now follow p2_land's polygon `land_mask`, not
  the DEM `elev<=0` mask. Fixed 445 km^2 inside CA (SF Bay baylands)
  printing as WATER. Region BOUNDARIES still use the DEM mask by ahl's
  call, so this was a body-assignment fix only. See the dedicated
  section below.
- RING BUG: all rib machinery walked `.exterior` only, so marks on the
  mountains/valley seam (an INTERIOR ring — mountains holds the valley
  in a hole) snapped 17-24 mm away, and the automatic placer could
  never put a pair rib there at all. Sites are now
  `(ring_idx, arc_length, kind)`.
- **Edge stamp (attribution + version), added 2026-09-15, SETTLED by
  print 2026-09-16.** `AL & JL 2026 v1.0` DEBOSSED **0.2 mm** into the
  frame's south outer wall, Tahoma Bold at 2.0 mm cap, 24.6 x 2.1 mm.
  Both numbers are now MEASURED off the depth ladder, not guessed:
  ahl printed all four rungs and picked #3 ("the 3 dots looks good"),
  which also answers the question the ladder existed for -- 2.0 mm cap
  IS legible at 0.2 mm layers (ten layers a letter), so `cap_mm` does
  not need to grow and 0.15/0.10 are not needed to stay subtle.
  He also added SPACES around the ampersand: set tight as "AL&JL" the
  ampersand's lower bowl crowded the J and the pair read muddy in
  plastic. Note the 2 um glyph dilate below keeps touching letters
  MANIFOLD -- it does nothing for legibility, and at a 0.45 mm stroke
  there is no room for the eye to separate them. Kerning is a spacing
  problem, not a geometry one. ahl wanted it "really subtle; like
  barely visible" -- it should read as a shadow line in raking light.
  Config `[edge_stamp]`. Points worth keeping:
    * RECESSED, not raised: at this size a proud feature is under one
      nozzle width (prints mushy or not at all) and would be the first
      thing to chip on the outermost rim.
    * the band spans the floor/water seam at 1.2 mm on purpose -- the
      water body's exposed wall alone is only 1.85 mm, forcing a cap
      whose strokes fall under the nozzle. BOTH bodies get the same
      cut; same filament, so it reads as one surface.
    * the font must be BOLD and the lookup SILENTLY falls back to Times
      New Roman Bold for any name it cannot resolve (Helvetica, Futura,
      DejaVu all quietly became a serif). The build now prints the font
      FILE it actually used and flags a fallback. Installed and usable:
      Tahoma Bold and Verdana Bold (0.45 mm stroke), Georgia Bold
      (serif); Arial Bold and Trebuchet MS Bold are 0.35 mm, too thin.
    * glyphs are dilated 2 um before extruding so touching letters
      MERGE -- left touching they produce a non-manifold pinch edge in
      the boolean result.
  **`make edge_stamp_coupon`** -> out/edge_stamp/depth_ladder.stl: the
  text at 0.10/0.15/0.20/0.30 mm on a bar the same 3.0 mm height as the
  real wall. Text on BOTH faces, two rungs a side (ahl 2026-09-15), so
  the bar is 66 x 8 x 3 mm / 1.9 g -- both faces are outer perimeters,
  so the slicer treats them alike; the back text is mirrored. Each rung
  is self-identifying: **n notches in the top edge above rung n**, inset
  from its own face so front and back marks never mix. Notches are Z
  cuts, so they stay crisp whatever the XY depths do, and no orientation
  convention has to be remembered.
      #1 0.10 front-left   #2 0.15 front-right
      #3 0.20 back-left    #4 0.30 back-right
  Print it in the WATER TEAL (the stamp's actual filament -- it spans
  floor+water, and half of judging "barely visible" is color and
  finish) with the FRAME's profile, since Arachne is what may smooth a
  shallow recess away. Teal is loaded for the frame anyway, so it costs
  no swap. ahl names the rung he likes; `[edge_stamp].depth_mm` gets
  that number and the frame reads the same knob. 0.2 is a placeholder
  until then.
  What it answers, in order of how much each would hurt to find on the
  7-hour frame print:
    1. IS 2.0 mm CAP LEGIBLE AT ALL -- and that is not a depth question.
       At 0.2 mm layers a 2 mm letter is TEN layers, and every diagonal
       is a staircase. If ten layers cannot render it, the knob is
       `cap_mm` (the wall has room for ~2.4), and no depth fixes it.
       All four rungs share the cap, so this comes out for free.
    2. which depths survive the slicer (0.45 mm stroke, 0.2 mm deep,
       ~0.42 mm perimeter).
    3. which reads as "barely visible" to ahl -- not computable.
  A coupon is mildly PESSIMISTIC: its layers are quick, so it cools less
  between them than the 225 x 250 frame. If a depth reads here, it reads
  there. Skipping the print is defensible -- the fallback is 0.3, the
  rung most likely to survive any profile -- but that trades "barely
  visible" for "safely visible" and takes (1) on faith.
- The key is FINAL (ahl 2026-09-15 confirmed both: "the legend is in a
  good spot", "the size looks fine"): 68 x 66 mm over Nevada, top
  auto-scanned to sit flush with
  the terrain on its own boundary, permanent press fit, 5 mm swatch
  pockets each with a 2.5 mm poke hole, plug 4.90 mm (MEASURED off a
  fit ladder), 2D-printed insert with cut line and border.

**NEXT:** nothing, for v1.0. It is finished. The v2/v3 list lives in
README "Future work"; the first item anyone should weigh is the poke
hole under the key, because it is the only one the finished object
actively wants and it costs a frame reprint now.

Two things worth doing while the object and the slicer state still
exist, both unrecoverable later:
  1. TAG the commit that produced the printed artifact, so the "v1.0"
     debossed on the south wall resolves to an exact config, override
     set and pipeline.
  2. SAVE THE BAMBU PROJECT FILE. The eventual print guide should BE
     that file, not a prose settings list -- it carries the profile
     verbatim, including the per-part water-only ironing scope, which
     is genuinely fiddly to reproduce from instructions. Settings live
     in the slicer, not the repo, and the state is gone the moment
     something is tweaked for the next print.

**HOW THE P5 RISKS ACTUALLY RESOLVED** (all of these were live
warnings until 2026-09-16/17; kept because a v2 will face them again):
- **The brim risk was REAL and the checklist was WRONG.** ahl tried
  3 mm and it "actually printed PAST the edge", so he dropped to
  **2 mm, outer_only** (229.1 x 254.0). The computed 231.1 x 256.0 for
  3 mm is not a zero-margin fit, it is an overflow -- the usable bed is
  under its nominal 256. Lesson worth keeping: a computed fit to the
  NOMINAL bed is not a fit. Adhesion was never a problem at 2 mm, and
  the tray floor's full-footprint contact means brimless is viable too.
  Pieces, key and plugs printed BRIMLESS.
- **The 0.88 mm Bakersfield neck** (~2 extrusion widths) and the
  1.04 mm Petaluma one printed and survived handling — on CLASSIC
  walls and 10% gyroid, not the Arachne the checklist asks for. So they
  are not as fragile as feared, but they were never given the wall
  generator that suits them. Still D11, still unfixed, still reported by
  `thin_spots()` every build.
- **T3 was coupon-only** when the pieces were cut. It transferred: the
  same numbers produced a working fit at ten times the span, against a
  frame printed with four filaments and an ironing pass.
- **Piece shapes shifted after T3** (the land fix), so the printed
  coupon was not byte-identical to what shipped. Harmless, as predicted
  — the clearances are offsets applied to whatever shape results.
- **The paper insert** printed, cut and seated fine; the 2 mm border and
  cut line work in the hand.
- **IRONING WAS TRIED ON THE FINAL FRAME AND REJECTED.** ahl
  2026-09-17: "I tried ironing for the final print... but it didn't go
  great. I think on balance it's not worth it." The saved project ends
  up `ironing_type = "no ironing"` project-wide. So the pass that looked
  excellent on the small flat ROSE COUPON did not carry to a 225 x 250
  water surface -- a coupon result that did not generalise, which is
  the interesting part. v1.0 ships with no ironing anywhere and looks
  fantastic. (An earlier version of this entry claimed ironing was
  confirmed on the frame; that was inferred from the object looking
  good rather than from evidence, and it was wrong twice over -- it was
  not used, and when it was tried it did not work.)

**Open items parked deliberately:**
- **NO POKE HOLE UNDER THE KEY (ahl 2026-09-16, deferred to v2).** Each
  of the three pieces gets 18 mm holes through the frame FLOOR; the key
  got none -- the build says so every run ("press fit: ... no ribs, no
  poke-hole"), and nobody read it as a gap until the parts were in hand.
  Consequence: the key comes out only by prying, against the terrain and
  the recess edge. The case for having one is servicing the PAPER
  INSERT, which is the one consumable in the whole object.
  Design constraint when it is built: the key plate already has five
  2.5 mm poke holes through its own pocket floors, so a frame hole that
  lands under one of those ejects a PLUG instead of the key. It has to
  sit clear of all five. The machinery is the same `floor_poly.interiors`
  the pieces use.
  TIMING: the key recess lives in the FRAME, which PRINTED 2026-09-16
  without the hole. So this is now firmly v2 -- adding it costs a frame
  reprint, the most expensive print in the project. Decided by events,
  which is the normal way a window like this closes.
- D11 per-scale min-width pass NEVER RAN — and the necks are now
  LOCATED and measured, from the exported STLs, on the P5 pieces:
      mountains 0.88 mm  Bakersfield, valley's south tip (-119.49, 35.21)
      mountains 1.04 mm  Petaluma (-122.20, 38.90)  [the T2 spur]
      mountains 1.49 mm  Carquinez/Suisun (-122.24, 38.24)
      valley    1.12 / 1.19 mm at those same two seams
      desert    1.51 mm  Mono Lake (-119.42, 38.59)
  All of them sit on the mountains/valley seam except the desert one.
  The WORST is Bakersfield, not Petaluma. ahl 2026-09-15 is deliberately
  NOT reshaping them — T3 addressed the fit with tolerance + rib
  placement instead, and it worked. Still parked, but note the 0.88 mm
  one is on the print-once brown piece. `thin_spots()` reports necks
  every build (all rings, since 2026-09-15).
- Full-depth bodies (gray under pieces / land color to the floor):
  v1.0 SHIPPED WITHOUT IT and ahl did not call for it after seeing the
  finished object, so single-layer land over teal evidently reads fine.
  Left in the v2 list as an improvement, not a defect; spec sketched in
  the T1 session note.
- Ironing: validated on the ROSE COUPON only (2026-09-14, per-part "Top
  surfaces" on the WATER body, 20% flow at 20 mm/s, "looks fantastic").
  NOT used on the shipped frame -- see the settings-as-used section.
  So the two-top-surfaces question the coupon could not answer is STILL
  open, and the shipped object shows the pass is optional rather than
  required.
- Bottom version stamps: DISABLED (two failed styles), and v1.0 shipped
  with UNLABELLED pieces — ahl 2026-09-16: "I can write on the pieces;
  it will be fine." The edge stamp has since solved small-text rendering
  (font-fallback guard, glyph merge, a depth ladder), so the rendering
  objection no longer stands if a v2 wants them.
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
- ahl's markup loop, now used for THREE things — he draws on a render,
  the marks get extracted, nothing is hand-typed:
    * REGIONS: red=mountains / orange=coast / edge lines ->
      overrides/*.geojson, applied by build_regions. Canvas:
      `pipeline/region_markup.py` (contours + hillshade + current
      region lines, exactly georeferenced).
    * RIBS and POKE HOLES -> config [print.ribs] / [print.poke_holes].
      Canvas: out/p4_rib_markup.png, out/p5_rib_markup.png (one shared
      renderer). CURRENT sites are drawn Color-FREE (white fill, black
      edge, one shape per piece) so any saturated color is ahl's mark;
      he picks his own colors. Ribs SNAP to the nearest perimeter
      point; poke holes do NOT (an 18 mm circle either fits or it does
      not) and are validated instead.
  Every canvas carries an exact pixel->mm/Albers mapping, printed by
  the build and/or in a .json sidecar. AVOID orange for marks on P5: it
  is only L1 32 from the desert region fill.
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
| D1 | Four regions: Coast, Mountains, Central Valley, Desert | Per CA curriculum scheme. Borders SETTLED: derived in p1_regions from the DEM + a coastal band, with hand overrides in overrides/*.geojson. |
| D2 | Coast piece extends into the Pacific as flat ocean, two-color print | Keeps Channel Islands physically connected to one rigid piece |
| D3 | Frame printed gray or white | Signals "context, not subject" |
| D4 | Ocean = flat datum plane | No bathymetry |
| D5 | Linear (planimetric) scale; Z scaled independently | Terrain gets vertical exaggeration; sits on a fixed-height solid base |
| D6 | Print bed 256×256 mm; whole model ≤ 1000×1000 mm total | Either frame fits one bed, or frame is carved into tiles |
| D7 | Material: PLA. Fit: snug but disassemblable | SETTLED and print-validated: 0.10 mm piece<->frame, 0.20 mm piece<->piece, ribs biting 0.05 mm. See the T3 entry. |
| D8 | Version control: jj (colocated git), repo = this directory | |
| D19 | **Region KEY (ahl 2026-09-15):** a rectangular plate inset into the P5 frame over NEVADA, carrying a TITLE ("California Regions", 6 mm cap = the same size as the compass rose's N/E/S/W letters, word-wrapped to "California"/"Regions") then, after a gap, the five regions at a smaller 3 mm cap (labels are `key_panel.LABELS`; since 2026-09-16 they read **mountains / coast / valley / desert / water** — lower case, in ahl's order, and deliberately the SAME words the build uses for bodies, pieces, STLs and config keys, so the key, the filament slot and the code all say one name rather than synonyms), each with a 5 mm circular color-swatch plug beside it. Each pocket has a 2.5 mm POKE HOLE through its floor (1.25 mm ledge left for the plug): plugs are fitted BEFORE the key goes into the frame, so a plug in the wrong pocket gets pushed back out from underneath while the key is still loose. Nothing is drilled through the frame — ahl 2026-09-15: "people are going to assemble the key first... we don't need to be able to poke the plug out after the key is inserted". Title layout sets the size: the text column must fit "California" at 6 mm (44.6 mm), which drove the key to 66 x 66 mm (was 56 x 57 before the title). Title and labels share ONE rectangular recess with the pockets in a column to its right, so the paper insert is a plain rectangle with no holes to punch. Cut as a recess exactly like a piece cavity. **PERMANENT press fit** — no crush ribs, no poke-hole, `[key].interference_mm` (0.05 total) of squeeze, glue optional. Bottom sits on the tray floor at the same z as every piece; **top is flush with the tallest terrain ON ITS BOUNDARY** — the build walks the rectangle's perimeter every run and takes the max, so the plate finishes level with the ground it actually abuts and moving/resizing the key re-heights it automatically (there is no height knob; verified by moving the key and watching 6.24 -> 6.69 mm). "Adjacent" means on the boundary line, NOT merely nearby: an earlier band-sampling version picked up a peak standing off from the key and made it 1.2 mm too tall. Labels are 2D-PRINTED (`out/p5/key_insert.pdf`): the page is the recess plus 5 mm of spare paper on every side with a CUT LINE + corner crop marks at the exact recess size, and a 2 mm blank border inside that so type is not flush to the paper edge (ahl 2026-09-15). The border is taken out of the usable text column, which is why the key went 66 -> 68 mm wide — "California" at the 6 mm title cap is 44.6 mm and would not fit a bordered 48 mm column. Sits in a 0.2 mm recess — FDM text at this size fights the 0.4 mm nozzle. Config `[key]`: enabled, center_mm, width_mm, height_mm, adjacent_search_mm, interference_mm, pocket_*, label_recess_mm. Location picked by scanning for the largest clear gray non-CA land block. The swatch PLUG is a plain P5 output too (`out/p5/key_plug.stl`) — ONE flat-topped cylinder, printed five times in the five region colors, TOP ROW FIRST in `LABELS` order (the build prints that list, derived rather than hardcoded — an earlier hardcoded sentence went stale the moment the labels were reordered); ahl lays the real print out by hand in Bambu Studio, so the build does not pack plugs onto a plate or merge them into another part. Plug dimensions are SETTLED: `[key].plug_d_mm` = **4.90 mm**, measured off the `pipeline/key_pocket_coupon.py` ladder (-> `out/key_coupon/{pocket_ladder,plug_ladder}.stl`), which reads the pocket size from this same config so the coupon always matches the real key. There is exactly one fit knob — the pocket is a DESIGN dimension, not a tuning one. `plug_proud_mm` = **0.0**: the plug sits FLUSH, which is self-stopping (it is exactly `pocket_depth_mm` tall, so it bottoms out on the pocket-floor annulus and cannot go under-flush). ahl's original ask was a 0.4 mm "satisfying bump"; handling the printed parts changed it. The standalone key-panel build was REMOVED 2026-09-15 (ahl: "get rid of the stand-alone key stuff"); `key_panel.py` is now a pure library shared by p5_final and the coupon. | |
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
  P1.5 slab print and P4 coupon prints were held until regions
  finalized (both since printed);
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

## Plan (phases with check-ins) — HISTORICAL

All phases are complete as of 2026-09-17. Kept as the record of how the
project was sequenced; the live list is README "Future work".

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
  [DONE — printed; z_exaggeration 9.3 came off this slab] RECTANGULAR SLAB, 150 mm N-S
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
- **P3 — 3D prototype.** [SUPERSEDED — p15/p15b and then the P4 coupon
  did this work directly] Generate ONE
  real puzzle piece + matching frame corner at 2–3 vertical
  exaggerations; base height proposal (G2). Waterway multi-body deferred
  (D9: baseline = no waterways; 3MF packaging already validated).
  Mesh foundations exist (mesh_common.py, p15/p4 drivers).
  *Check-in: previews + STLs in slicer; pick exaggeration & base.*
- **P4 — Fit coupon.** [DONE — printed T1/T2/T3; T3 settled the fit] Bay
  Area window pieces at both candidate scales + 10 mm frame rim
  (out/p4_bay_235mm/, out/p4_bay_420mm/, incl. frame.stl; pieces carry
  edge clearance for the frame opening). Geometry-level fit verified to
  <0.01 mm of nominal. *Check-in: ahl prints and reports fit (G3/G4).*
- **P5 — Full generation.** [DONE] All pieces (4 regions +
  islands piece) + frame tiles + ocean datum; two-color islands piece
  (G7/G11); watertight verification on every mesh.
  *Check-in: full set + assembled render.*
- **P6 — Print & iterate.** [DONE 2026-09-17] Frame, all three pieces,
  key, five plugs and the paper insert printed and assembled. ahl: "I
  printed it all and it's fantastic."

**All phases are complete.** This plan is history; the live list is
README "Future work".

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

This is what we believe is RIGHT. What was actually on the machine for
a given print is recorded separately under "Settings AS USED" below --
they have already diverged once (P5 mountains ran Classic walls and 10%
infill), and the divergence is the interesting data, so do not quietly
reconcile the two.

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
- [ ] Ironing: **OFF for the frame -- tried on the final print and
      rejected** (ahl 2026-09-17: "I tried ironing for the final
      print... but it didn't go great. I think on balance it's not worth
      it"). It looked excellent on the small flat rose coupon and did
      not carry to a 225 x 250 water surface. v1.0 shipped with no
      ironing anywhere and the result is "fantastic", so this is
      optional at best. The rest of this item is kept as the recipe IF
      a v2 retries it.
      WAS: ON, per-part on the WATER body ONLY, ironing TYPE = "top
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
      just extra ironing time on hidden area. CONFIRMED on the real
      P5 frame 2026-09-16 -- this is the case the rose coupon could not
      test, and it came out well.

PIECES (mountains/valley/desert STLs — single color)
- [ ] Separate plate from the frame (don't ride the color changes)
- [ ] Top shell layers 5-6 (sloped terrain; avoid infill show-through)
- [ ] Orientation as imported (terrain up)

FINAL 225 x 250 FRAME ONLY
- [ ] Brim **2 mm, outer only** -- SETTLED BY PRINT (ahl 2026-09-17).
      The arithmetic: brim grows OUTWARD on every side, so on a 256 x 256
      bed the 225.1 x 250.0 frame becomes 229.1 x 254.0 at 2 mm,
      231.1 x **256.0** at 3 mm (exactly the bed edge) and 233.1 x 258.0
      at 4 mm. N-S is binding; rotating only swaps axes.
      **3 mm FAILED IN PRACTICE** -- ahl: "the 3 mm brim actually printed
      PAST the edge." So 256.0 is not merely zero-margin, it is over the
      real printable area. Do not treat a computed fit to the nominal bed
      as a fit. He dropped to 2 mm and reports adhesion was never a
      problem anyway -- the tray floor gives full-footprint contact, so
      brimless is also viable.

## Filament logistics (ahl 2026-09-14)

- GREEN (valley): plentiful — the valley is the designated tuning piece
  (cheap + reprintable), which the enclosed-zero-clearance design
  already exploits.
- BROWN (mountains) and YELLOW (desert): SCARCE — print those final
  pieces ONCE, from validated parameters. Do NOT burn them on coupons:
  test-print pieces in green/any plentiful color (fit doesn't care).
  The mountains piece is also the biggest filament consumer of the
  three.
- OUTCOME: the planned full-size DRESS REHEARSAL was SKIPPED. ahl went
  straight to the final brown mountains and it came out well, so the
  one-shot pieces cost one print each. Coupon pieces were WHITE, frame
  coupons in the real frame colors. Noted because the rehearsal was a
  standing recommendation in this file and the project shipped without
  it -- not a precedent so much as a reminder that by then the fit was
  already coupon-validated, which is what made skipping it reasonable.
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

  **SET ASIDE 2026-09-15** (ahl: "if I'm not happy with how it prints
  I'll consider vertical printing and maybe redesigning to remove the
  weak points"). Analyzis done then, so it need not be redone:

  *The resolution problem is real.* At 0.2 mm layers elevation
  quantises to **97.6 m per layer** (z rule 0.002049 mm/m), so the
  mountains piece renders ALL of California's relief in 42 layers.

  *But the three pieces are completely different problems.* Printed
  slope after the 9.3x exaggeration, and the share of each piece whose
  terracing would be wider than 0.5 mm:

      piece      median slope      >0.5 mm terrace @0.2   @0.1
      mountains  0.706  (35 deg)         29.6%           14.5%
      desert     0.319  (18 deg)         57.6%           35.2%
      valley     0.022  (1.3 deg)        96.8%           89.7%

  - mountains/desert have genuinely BIMODAL slope -- steep faces where
    0.2 mm is already invisible, gentle areas where it terraces. That is
    what ADAPTIVE layer height is for, and it beats a uniform fine layer
    (which pays everywhere for a third of the area). Safe on PIECES: the
    only critical flat z-levels are the bed-contact bottom and the datum
    plane at 1.8 mm, and a fraction-of-a-layer shift there just seats
    the piece a hair low, well inside the 0.10 mm clearance. NOT safe on
    the FRAME -- keep it fixed 0.2: the water datum at 3.0, the rose at
    exactly +0.4, the key pocket depths and the ironing pass all need
    flat surfaces landing exactly on layer boundaries, and it is the
    4-color print. (This is the reason behind the checklist's "NO
    adaptive layers" line; it stands for the frame.)
  - the VALLEY cannot be fixed by slicing at all: 1.3 deg median slope
    and only **1.28 mm of total relief (6 layers)** across 141 mm. Going
    to 0.1 mm moves terracing from 96.8% to 89.7% of its area. If it
    reads wrong the lever is [output].z_exaggeration, not layer height.
  - if a fixed layer height is preferred over adaptive, **0.1 mm is the
    only useful step down**: every critical z-dim must be a layer
    multiple, and 0.15 breaks the rose (0.4/0.15 = 2.67) and the plug's
    proud height, while 0.08 breaks the 1.8 mm slab. 0.1 divides slab
    1.8, datum 3.0, floor 1.2, rose 0.4, pocket 1.4, recess 0.2.

  *Why vertical is unattractive HERE specifically*, beyond the cautions
  already listed: the 0.88 mm neck (D11) would have its layer lines
  running ACROSS it, so the piece would hang together at its weakest
  point by inter-layer adhesion -- on the print-once brown filament.
  The perimeter IS the fit surface, so on edge the bed-contact edge
  takes elephant-foot squish on a fit face. Supports would land on the
  terrain being improved. Mountains on edge is 231.6 mm tall and ~10 mm
  thick (22:1, 1158 layers vs 51). And vertical would help the VALLEY
  most, where it is least viable: on edge that piece is 141 mm tall and
  3.08 mm thick, 46:1.

## Print sessions

- **T1 (2026-09-14, CLOSED):** ahl printing the mini-frame set
  (4-color frame.3mf w/ vector rose + mountains/valley pieces, plain
  bottoms). IRONING DEFERRED (revisit later; if wanted, the route is
  per-part "Top surfaces" on the WATER body — "topmost" mode would skip
  the water plane since terrain rises above it; note rose blue/gray ink
  merged into terrain bodies, so rose stays matte under per-part water
  ironing). Was awaiting: fit at 0.15 mm/side (G3), poke-hole/tray feel,
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
- **RING BUG, found by ahl's P5 markup and fixed (2026-09-15) --
  worth knowing because it was silent.** All the rib machinery walked
  `nominal.exterior` ONLY. A piece that ENCLOSES a sibling carries that
  seam on an INTERIOR ring: P5 mountains holds the valley in a hole. So
  four of ahl's marks, placed accurately (0.6-1.0 mm) on the
  mountains/valley seam, snapped **17-24 mm away** to the outer
  coastline -- and the automatic placer could never put a pair rib on
  that seam at all, only on the mountains/desert one, which is why its
  P5 picks looked reasonable while quietly missing half the problem.
  `thin_spots` had the same blind spot (it reported mountains as clean
  while `min_land_width` said 1.00 mm). Fixed: `_rings_of()` +
  `site_point()`, rib sites are now `(ring_idx, arc_length, kind)`, and
  `_local_widths` excludes by arc distance only WITHIN a ring -- two
  different rings have no arc relationship, and material between them
  is exactly the kind of neck worth finding. After the fix every mark
  snaps <= 1.71 mm and all four seam ribs bite the designed 0.05 mm.
- **Manual placement covers POKE HOLES too, on the same canvas (ahl
  2026-09-15: "can I also place the finger holes in this same pass?").**
  config `[print.poke_holes]`, keyed like the ribs; any piece with no
  list falls back to the automatic planner. Holes are drawn on the
  markup canvas at TRUE 18 mm size with a + center, so a hole and a rib
  can be judged against each other in one pass. Unlike a rib a hole does
  NOT snap -- an 18 mm circle either fits or it does not -- so
  `manual_poke_holes` VALIDATES instead of nudging: the whole circle
  must clear the cavity wall by POKE_MARGIN_MM, holes must be >= 20 mm
  apart, and every piece must end up with at least one. All three
  asserts were deliberately tripped to check the messages are
  actionable.
- **P5 rib markup canvas (`out/p5_rib_markup.png`).** P4 and P5 now
  share one renderer (`p4_bay_coupon.rib_markup_canvas`) so the two
  cannot drift. CURRENT sites are drawn Color-FREE -- white fill,
  black edge, one shape per piece (o mountains, s valley, ^ desert) --
  because ahl picks his own mark colors; that also sidesteps a real
  collision, since an orange mark is only L1 32 from the desert region
  fill (242,153,71) and a purple only 78 from mountains magenta. P5's
  rib sites are still the automatic placer's picks, unlike P4's.
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
- **T3 (2026-09-15): PRINTED — "the fit is great. I don't think I'd
  change it at all" (ahl). The clearances are LOCKED.** NOTE the P4
  geometry has shifted slightly SINCE that print (the land-authority
  fix moved the coast/water line around the Bay, and the ring fix
  changed nothing in P4 but is shared code). The fit NUMBERS still
  transfer — they are offsets — but a reprinted coupon would not be
  byte-identical to the one in ahl's hand. Frame 0.10 does
  not bind (it was 0.15 through T1+T2), the symmetric 0.20 pair gap is
  right, and the ribs — biting 0.05 mm into the mating face, hand-placed
  — retain properly. This is the end of the T1(loose) -> T2(too tight)
  -> T3(right) sequence; config.toml marks these LOCKED, and changing
  one means a fresh coupon print + build_tag, not an edit. Caveats
  carried forward at the time: no desert on the coupon, so three-piece
  wedging and the mountains<->desert seam were unproven, as was the full
  225 x 250 frame; 18 mm poke-hole ergonomics and 6 mm rose-letter
  legibility went uncommented. ALL CLEARED by the P5 prints
  (2026-09-16/17).
  Spec as built: `build_tag` = "T3"; `make p4 p5` converged, all bodies
  watertight.

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
  too-tight T3 would not isolate which; and the coupon has no desert, so
  three-piece wedging and mountains<->desert were untested until P5.
  DISCHARGED 2026-09-17 -- the full object assembled, desert included,
  with these exact numbers. Neither caveat ever had to be paid.
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
  measures the real distance to the as-cut neighbor (`neighbor_pieces`)
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
  judgment about the assembled object, not something a straightness/
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

## Settings AS USED (the record for a future print guide)

ahl 2026-09-15: *"make sure you record the print settings; if it all
goes well I'm going to want to document this for other people to
print."* So this section is what was ACTUALLY on the machine, per part,
kept separate from the checklist above -- the checklist is what we
believe is right, this is what produced the object. Where the two
disagree, say so; do not quietly reconcile them.

### P5 mountains (2026-09-15, brown, possibly FINAL)

Bambu Studio, stock profile, **one deliberate change: sparse infill
10% GYROID**. Everything else default. Notably NOT set, all of which
the checklist above asks for:

| setting | checklist wants | this print |
|---|---|---|
| wall generator | Arachne | **Classic** (the Bambu default) |
| top shell layers | 5-6 | default (~5) |
| sparse infill | 20-25% | **10%** |
| brim / mouse ears | (unspecified for pieces) | **none** |

Three things that makes this print a TEST of, each of which closes an
open item if it comes out clean:

1. **Classic walls across the 0.88 mm Bakersfield neck** (and 1.04
   Petaluma, 1.49 Carquinez). At the minimum itself Classic is fine --
   two 0.42 mm perimeters back to back. The exposure is the TAPER on
   either side, 0.88 -> 1.3 -> 1.8 mm, where Classic snaps to integer
   wall counts and leaves gaps that Arachne would fill with variable
   width. Those gaps land right next to the thinnest point, which is
   where stress concentrates when the piece is lifted by a poke hole.
   Arachne was scoped to the frame in the checklist (for the rose's
   0.45-0.8 mm features); that scoping was too narrow -- the pieces'
   necks are the other case for it.
2. **10% gyroid under ~5 top shell layers** on the VISIBLE face. Fine
   structurally (10 mm tall, mostly shell); the risk is pillowing or
   infill show-through on the flatter stretches. Desert has more flat
   area than mountains, so decide this before the desert piece.
3. **Bare first layer at the tips.** No brim and no ears. Measured
   footprint: 10,763 mm^2 of bed contact in ONE island, but erode it
   2 mm and it splits into three -- real necks and points. Worst tips,
   by material within a 4 mm radius (a straight edge is 50%, a 90-deg
   corner 25%):
       (180.9,  12.3) mm   13.6%   6.8 mm^2   <- worst
       (176.4,  39.0) mm   21.1%
       ( 46.0, 143.1) mm   22.2%
       ( 23.2, 240.8) mm   24.4%
       (159.8,   9.3) mm   25.7%
   Mountains is the WORST CASE of the three pieces for this -- tallest
   (10.3 mm), longest (231.6 mm), pointiest. Valley is 3.1 mm tall so
   it has almost no warping leverage; desert is blunter (2A/P 21.7 vs
   18.7). **If mountains comes off flat with nothing, valley and desert
   need nothing and the mouse-ear item closes permanently.**

A brim is the WRONG helper for these pieces regardless: the piece's
outer perimeter IS the fit face, at 0.10 mm/side with ribs biting 0.05,
and a brim welds to all 1,150 mm of it. Removal burr lands straight in
that 0.10 mm. Mouse ears touch it at five spots you can see and clean
deliberately. If ears are ever needed, the slicer route is uncertain
(brim ears are an Orca feature; Bambu's brim menu is
auto/outer/inner/both/none) -- the fallback is to build 0.2 mm discs
into the model at the coordinates above, which is slicer-independent.

**To inspect when it comes off the plate:** flex the Bakersfield neck;
sit it on something flat and press each corner (lift reads as rock, not
as a visible gap); look at the bottom face at the two SE tips for the
glossy-then-matte patch that means a tip lifted and re-bonded -- that
also means a thin first layer there, which is a FIT question at the
seam, separate from the neck question. Dry-fit before calling it final.

### P5 mountains + valley (2026-09-16): FIT CONFIRMED

ahl, having printed both: *"I printed the mountains and the valley and
they're fitting well enough."* This is the T2 failure case re-run at P5
scale -- T2 died on mountains + valley being too tight TOGETHER -- so
the T3 scheme (0.10 piece<->frame, 0.20 piece<->piece symmetric, ribs
specified as overlap with the mating face) now transfers from the P4
coupon to full size for that pair. Still untested: anything involving
the DESERT, the three-piece wedge, and the pieces against the real
frame, which does not exist yet.

Printed with the settings recorded above -- Classic walls and 10%
gyroid -- so those did not break the 0.88 mm Bakersfield neck badly
enough to matter for fit. Not the same as saying they are right; the
neck's strength in the hand is a separate judgment.

### P5 FRAME (2026-09-16): PRINTED, and it works

ahl: *"the mountains and valley and frame all printed and they're
great."* This retires the single largest risk in the project -- the
225 x 250 mm four-color frame had never been printed at any scale, and
everything validated before it came from the P4 coupon.

What that one sentence settles, all of which was open an hour ago:
  - the 3 mm brim at EXACTLY 256.0 mm did not clip the bed
  - a 225 x 250 footprint adheres and does not warp off
  - four-filament seams print acceptably at this size
  - the key recess prints
  - the per-part water-only ironing works on the real frame, not just
    the rose coupon (it had never been tried on a part with two
    top-facing regions at different Z)
  - the cavities print close enough to nominal that pieces fitted to
    them SEAT -- the clearance scheme puts all tolerance in the piece
    and assumes a nominal cavity, and that assumption had never been
    tested at ten times the coupon's span
  - the edge stamp at 0.2 mm survived Arachne on a real wall

Worth capturing while the object is in hand, because a print guide needs
it and memory fades: brim behavior at the bed edge, how the stamp reads
in raking light, ironing time, whether the key recess needed any
cleanup, and total print time.

### Desert, key, plugs (2026-09-17): PRINTED, assembled, done

ahl: *"I printed it all and it's fantastic."* Closes the last three
open geometric questions in one go -- the mountains<->desert seam (never
printed at ANY scale before this), the THREE-PIECE WEDGE (the pieces
pushing on each other, which only exists at P5), and the key: plugs
pressed flush into their pockets, paper insert, key pressed into the
frame at 0.025 mm/side.

So the full chain is validated: T3 clearances from a coupon -> a
225 x 250 four-color frame -> three pieces that wedge -> a press-fit
key with five press-fit plugs. Nothing in the fit scheme was changed
between the coupon and the final object.

### THE SHIPPED SETTINGS, read out of the saved Bambu project

`cali regions.3mf` (in the repo root, un-ignored on purpose -- see
.gitignore) is the authoritative record. Everything below is READ FROM
IT, not reconstructed, and it contradicts this file's own checklist in
five places. v1.0 is "fantastic" anyway, which makes the checklist
demonstrably more conservative than the object requires.

    layer_height                0.2      initial layer 0.2
    wall_generator              ARACHNE
    wall_loops                  2
    sparse_infill               10% GYROID       (checklist says 20-25%)
    top / bottom shells         5 / 3            (checklist says 5-6 top)
    elefant_foot_compensation   0.15     seam aligned
    ironing                     NONE             (checklist says water-only)
    brim                        frame: outer_only at 2 mm
                                everything else: none
                                                 (checklist says 3 mm)
    filaments (PLA), all 8 -- the frame's four plus the four the
    pieces and key are printed in:
       1 #0056B8 blue    CA land / coast     5 #00AE42 green   valley
       2 #A4DBE8 teal    water               6 #6F5034 brown   mountains
       3 #8E9089 gray    non-CA land         7 #FFFFFF white   key
       4 #000000 black   compass rose        8 #F4EE2A yellow  desert
    prime tower on;  5 plates;  10 key_plug copies (5 + 5 spares)

ARACHNE, and the checklist was right about it. The first saved copy of
this project said `classic` -- ahl 2026-09-17: *"I did use those for my
real print, but forgot to add them to this file"* -- and for one commit
this section wrongly concluded from that file that Classic had done the
job, including on the rose and the 0.88 mm neck. Re-saved and verified.
Keep the episode: the argument for shipping the project file AS the
print guide is that it carries the profile verbatim, and a save that
silently omits a setting turns the guide into a wrong answer rather than
a missing one. **Check it after every re-save:**
    python3 -c "import json,zipfile;print(json.load(zipfile.ZipFile('cali regions.3mf').open('Metadata/project_settings.config'))['wall_generator'])"

One of the differences deserves emphasis:
  - **No ironing, after trying it.** A whole design decision --
    splitting the frame's floor and water into separate 3MF parts so
    ironing could target the visible surface only -- was made to serve a
    pass that turned out not to be worth running. The split costs
    nothing and keeps the option open, so it was not wasted, but the
    sequence is worth remembering: a great result on a SMALL FLAT COUPON
    drove a design change, and the effect did not survive scaling to the
    real surface.

Where the checklist and this section disagree, THIS section is what
produced the object. Treat the checklist as the conservative starting
point for a v2, not as a description of v1.0.

### The eventual print guide

DONE: the distributable is NOT a prose list of settings -- it is the
**saved Bambu Studio project**, `cali regions.3mf`, committed alongside
v1.0. It carries the profile verbatim so someone else opens it and
everything is already set. It also caught two errors in this very file
(ironing and the brim) within minutes of being read, which is the
argument for the file over prose in one line. This section is the provenance behind that
file and the place to explain the non-obvious choices (why Arachne, why
no brim on the pieces, why ironing is water-only). Ask ahl to save the
project file at the point the print is judged good -- a reconstructed
settings list is a guess; the project file is the artifact.

## Land/sea authority — the coast-printed-as-water bug (FIXED 2026-09-15)

**Symptom (ahl, from the T1 frame print):** parts of the coastal region
printed as WATER (teal) instead of coast.

**Cause:** the project had TWO notions of sea and the mesh builds were
using the wrong one.
- `p1_regions.ocean_mask()` — every cell at or below 0 m that floods
  from the Pacific. Pure elevation, so genuinely-dry land lying at or
  below sea level reads as ocean.
- `p2_land.py` — Census state polygons + Natural Earth countries, which
  its own docstring calls "THE authority on what is California and what
  is US land".

p4/p5 had adopted p2_land's `ca_mask` but never its `land_mask`, so
bodies were still assigned off the DEM mask. **out/p2_land_qa.png is
literally a picture of this**: gray hillshade, blue sea, black Census CA
outline, brown political borders, and RED wherever the two definitions
disagree. The big red blobs are the SF Bay baylands.

**Measured:** 544 km^2 that the polygons call land the DEM called sea —
**445 km^2 of it inside California**, in 1182 patches. Largest: south
Bay/Alviso 112, Napa-Sonoma marsh 95, Petaluma marsh 25 + 23, Humboldt
Bay 12 km^2 — i.e. diked baylands and salt ponds, dry land sitting at or
below sea level. (808 km^2 goes the other way, a thin fringe where the
DEM reads above 0 outside the polygon coastline.)

**Fix — MINIMAL, by ahl's call** ("so we don't have to start back at
square 1 on the region boundaries"): `p4_bay_coupon.land_authority()`
loads p2_land's `land_mask`, and that drives BODY assignment only —
`coast_nom`, the gray land body, and the compass rose's on-land check.
The REGION rasters keep the DEM mask, so the coast band and the
coast/mountains line are untouched. The fuller fix (feeding the polygon
mask into `build_regions`' `shore_dist` so the band is measured from the
true shoreline) is deliberately NOT done.

**Second half of the fix — the reclaimed land needs a REGION, not just
land status (ahl spotted it in the P5 preview: "a new color (tan) that
I expect should be yellow").** `build_regions` never gave those cells a
region id, because the DEM called them sea, so they stayed at region 0.
`fill_and_contiguity`'s "no-region land -> nearest region" pass then
skipped them too, since it also tested against the DEM mask. With no
region they could not be coast, and fell through to whatever came next:
in P5 the gray body (tan), in P4 the water body (still teal -- which is
why ahl saw P4 as unchanged, despite the Bay being its whole window).
Fix: `fill_and_contiguity` takes the SAME water mask the bodies use, so
the reclaimed cells get their nearest region -- coast, around the Bay.
This only ADDS region to cells that were water; boundaries between
existing regions do not move. Fill grew 7.8 -> 29.4 mm^2 in P5 and to
213 mm^2 in the Bay-centerd P4 window, and the gray body went from 6
parts to 1.

**Side effects, all benign:** the polygon coastline is much smoother
than the DEM one, so the gray body dropped ~13% of its triangles
(949k -> 826k). Re-cutting coast out of gray AFTER the 0.05 mm
morphological opening was needed: the opening is a subset geometrically
but not in floating point, and on the more intricate polygon coastline
it left ~700 sub-micron slivers straddling the shared boundary, which
tripped the coast/gray disjointness assert. The two filament bodies are
now disjoint by construction rather than by an epsilon.

**Coast<->mountains boundary near SF Bay: REVIEWED AND ACCEPTED as-is
(ahl 2026-09-15, "let's not let perfect be the enemy of the good").**
After the land fix the coastal band still radiates 13.5 km from Bay
water, so the line cuts across the East Bay hills and the peninsula
ridge rather than following them. ahl looked at it on a contour canvas
and called it fine. The two alternatives were costed and NOT taken:
re-deriving the band from the polygon shoreline would have changed
1,891 km^2 statewide (691 km^2 near the Bay) with boundary shifts up to
11 km -- a global change for a local reason; a targeted override was the
cheaper option if it had been wanted.

**`pipeline/region_markup.py` — the tool for that, kept for next time.**
Renders any lon/lat window as a markup canvas: terrain CONTOURS (thin
every 100 m, heavy/labeled every 400 m, none over water) + hillshade +
the CURRENT region lines, exactly georeferenced. `out/region_markup.json`
carries the extent and the pixel->EPSG:3310 formula, so marks convert
without guesswork; they go to overrides/*.geojson and build_regions
applies them, moving one boundary without touching a global knob.
  uv run pipeline/region_markup.py [west south east north]

**Key swatch plug diameter: MEASURED, settled at 4.90 mm (ahl
2026-09-15).** First attempt used +0.05 mm of designed INTERFERENCE
(a 5.05 mm plug) and was far too tight -- ahl forced it in and deformed
the plug. That is the usual FDM small-hole behavior, not the number
being slightly off: a nominal 5 mm pocket prints UNDERSIZE (the inner
perimeter's extrusion overlaps into the bore) while the plug prints
slightly oversize, so a few hundredths of designed interference becomes
a few tenths in plastic. How much is a property of the printer and
profile, so it was measured rather than derived, with a fit LADDER
(`pipeline/key_pocket_coupon.py`): seven plugs against pockets at the
key's real diameter, one print, index dimple marking plug #1.

    4.70 / 4.75 / 4.80   fell out
    4.85 / 4.90          went in, solid
    4.95                 went in, took some effort
    5.00                 would not go in

Working band 4.85-4.95, so `[key].plug_d_mm` = **4.90**, its center --
0.05 mm of margin either side. The band edges are NOT safe picks: the
real key has five pockets, and pocket-to-pocket and print-to-print
variation eats that margin. Re-run the ladder if printer, filament or
profile changes; 0.15 mm is a narrow band.

ONE fit knob, not two (ahl: "just pick the pocket size and we'll try
several plugs"): `pocket_d_mm` is a DESIGN dimension -- the key's row
layout is built around it -- so it is never touched to chase fit, and
`plug_d_mm` is an absolute diameter rather than an offset from it. The
build asserts the two stay within 0.5 mm, so if the pocket ever moves
for layout reasons the plug value cannot silently orphan.
`plug_proud_mm` (0.4) is still an eyeball value, not measured.

## v1.0 REPRODUCIBILITY: verified from a clean worktree (2026-09-17)

`git worktree add --detach <path> v1.0` into an empty tree -- no
`data/`, and `out/` holding only the committed PNGs, since STL/3MF are
gitignored -- then `make`. Everything re-downloaded from the original
sources (198 MB: DEM tiles, CGS geomorphic provinces, both Natural Earth
boundary sets), every stage ran, and `make -n` came out clean.

**Every mesh is byte-identical to the shipped files**: mountains,
valley, desert, key, key_plug, the P4 coupon's frame pieces, and the
edge-stamp ladder. Two files differ, neither geometric:
  - `frame.3mf` -- two `p:UUID` attributes, regenerated per run. Every
    other zip entry, including the geometry payload, is identical.
  - `key_insert.pdf` -- 6 bytes, matplotlib's `CreationDate`.
So "the v1.0 on the south wall resolves to an exact object" is TESTED,
not aspirational. The upstream sources being live was the real risk and
it is the part most likely to rot; re-run this test before trusting the
tag years from now.

Two things the test incidentally proved: the pipeline is hermetic (it
needs nothing that exists only in ahl's working tree), and
`edge_stamp_coupon` is NOT part of `make all` -- it has to be asked for
by name. P4 writes to `out/p4_mini/`, not `out/p4/`.

**Dead files removed on the strength of it (ahl 2026-09-17).** The
clean build is what made dead distinguishable from live: anything the
build regenerates is live, anything it left untouched was a leftover.
  - `compass.svg` at the repo root -- an EXACT duplicate (same SHA256)
    of `assets/compass.svg`, which is what every consumer actually
    reads. Removed as a footgun more than as clutter: editing the wrong
    copy would have been silently ignored.
  - eight orphaned renders, ~11 MB, from stages since renamed or
    removed: p1_delta_zoom, p1_final_vallejo_inset, p1_marks_extract_qa,
    p1_marks_result_zooms, p1_override_extract_qa, p1c_low_thresholds,
    and rose_mesh_qa.png under both out/p5 and out/p4_mini. No script in
    pipeline/ produces any of them.
  - `compass rose.jpeg` (the rose reference photo).
KEPT, and do not mistake these for dead: **`p1 final marked.png`,
`p1 final vallejo marked.png`, `p1_coast_candidates marked.png`** fail
the same "no code references it" test but are the HAND-DRAWN SOURCES for
overrides/*.geojson. The geojson is the extracted result; these are the
only record of what was actually drawn. Losing them turns the overrides
into numbers nobody can check. Also kept: `cali regions.jpg`,
`mini frame.png` (print photos).
Note deleting committed files does not shrink `.git` (271 MB) -- this
was about removing traps, not reclaiming space.

## Observation log (noted, NOT to be acted on unless ahl says so)

**MAGNETS -- a v3 idea (ahl 2026-09-15: "maybe v3 we incorporate
magnets; it felt like too much for this time through").** Deliberately
NOT in v1. Recorded now because the constraints are cheapest to capture
while the geometry is fresh.

Why it was right to skip: magnets would have meant solving retention AND
the fit scheme in the same pass, with no way to tell which one was wrong
when a piece failed to seat. T1->T3 took three coupon prints to settle
fit alone.

What magnets would actually buy, and it is not "a bit more grip": they
DECOUPLE RETENTION FROM CLEARANCE. Every hard problem in this project --
crush ribs, the 0.10/0.20 split, the symmetric pair rule, the
overlap-with-the-mating-face rib spec, ribs as a wearing consumable --
exists only because retention is mechanical, so the piece has to be
simultaneously tight enough to hold and loose enough to insert. With
magnets doing retention you could open the clearance to ~0.3 mm, drop
ribs entirely, and have pieces fall in and snap. That is the design
argument for v3, not the novelty.

Constraints already known, from the CURRENT geometry:
  - the VALLEY piece is only 3.1 mm tall overall. That is the binding
    dimension for a piece-side pocket: a 2 mm-thick magnet leaves ~1 mm
    of floor, and the floor is what the magnet pulls against.
  - the frame's cavity floor is 1.2 mm thick (base 3.0, floor 1.2), so a
    frame-side magnet has nowhere to hide without thickening the floor
    locally -- which shows on the BOTTOM of the map unless the tray
    floor grows.
  - likely cheapest arrangement: magnet in the PIECE, steel disc (or a
    single steel sheet under the whole tray) in the frame. Avoids
    polarity entirely, which matters because a mis-polarised glued-in
    magnet is unrecoverable.
  - insertion means a slicer PAUSE at a known layer, so the build would
    need to emit the pause height along with the pocket -- a new kind of
    output this pipeline does not produce today.
  - poke holes (D18) could then go away, or stay as a convenience; the
    18 mm holes exist to break a friction fit.

None of this is designed. It is the set of things a v3 pass should not
have to rediscover.

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
