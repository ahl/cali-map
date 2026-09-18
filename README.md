# California Topo Puzzle Map

A 3D-printable, to-scale topographic map of California as a region
puzzle: four land regions — Coast, Mountains, Central Valley, Desert —
set into a frame of the surrounding geography.

**Coast is part of the frame.** The three removable pieces are
**mountains, valley, desert**. Scale 1:4.54M, 225 × 250 mm, terrain at
9.3× vertical exaggeration.

## Build

```sh
make            # rebuild whatever is stale
make -n         # show what would rebuild
make p5         # one stage
```

Everything derives from `config.toml` + `overrides/*.geojson` +
`assets/compass.svg`. Every stage depends on those, so a knob change can
never be silently ignored.

## The final product — `make p5` → `out/p5/`

| file | what |
|---|---|
| `frame.3mf` | the tray. 4 filaments, 5 parts (coast / floor / water / gray / black rose) |
| `mountains.stl` `valley.stl` `desert.stl` | the removable pieces |
| `key.stl` `key_plug.stl` `key_insert.pdf` | region key over Nevada: plate, ×5 colour swatch plugs, printed label |

Also `out/p5_preview.png` (assembled / exploded / bottom / rose) and
`out/p5_rib_markup.png` (markup canvas, below).

## Other targets

- `make p4` — Bay Area coupon at final scale: a small frame + 2 pieces
  for testing fit before committing to the real thing.
- `make rose_coupon` — just the compass-rose corner.
- `uv run pipeline/key_pocket_coupon.py` — swatch-plug fit ladder.
- `uv run pipeline/region_markup.py [W S E N]` — region markup canvas.
- `p0`/`p1`/`p2` are upstream data stages; `p15`/`p15b` are older
  single-piece experiments.

## Print settings

Short form; `NOTES.md` has the checklist and the reasoning.

**Both** — 0.2 mm layers, first layer 0.2 mm (every z dimension in the
model is a multiple of 0.2, so **no adaptive layers**). Elephant-foot
compensation 0.15 mm. Seam aligned. Infill 20–25% grid/gyroid.

| | frame (`frame.3mf`) | pieces (`*.stl`) |
|---|---|---|
| plate | its own — 4 filaments, 5 parts | separate, so they don't ride the colour changes |
| wall generator | **Arachne** — the rose has 0.45–0.8 mm features | default |
| ironing | **off** — tried on the final frame and rejected; great on a small coupon, didn't carry to a 225 × 250 water surface | off |
| top shell layers | default | **5–6** — sloped terrain shows infill through fewer |
| brim | **2 mm, outer only** → 229.1 × 254.0 mm. 3 mm printed *past* the bed edge in practice; 4 mm overflows by 2 mm | none |
| also | prime tower on, flush into objects' infill; raise the black→teal and black→blue flush volumes; move the object as a whole, never its parts | orientation as imported, terrain up; no supports |

Frame filament slots: 1 CA-land blue, 2 water teal, 3 gray, 4 black —
recheck after every re-import.

**Use Arachne**, the variable-width wall generator. Classic offsets
perimeters by a fixed width, so where a region isn't a whole number of
walls it leaves a gap or drops a wall, switching abruptly. Arachne
varies width along the medial axis and fills exactly. Three features
here are sub-2-wall: the pieces' 0.88–1.5 mm necks (the taper either
side of a neck is where Classic leaves voids, right where the piece is
weakest), the rose's 0.45–0.8 mm features, and the edge stamp's 0.45 mm
strokes. v1.0 was printed with it.

Plugs ride along with a print that already has their filament — mountain
with the mountains piece, valley with valley, desert with desert, ocean
and coastal with the frame — so they never need a print of their own.
Print a few spares: the fit band is 0.15 mm wide and the press fit is
permanent.

Brown (mountains) and yellow (desert) are scarce: print those once, from
validated parameters. Test in green or white — fit doesn't care.

## Markup loop

Region boundaries, crush ribs and poke holes are all placed by hand:
the build renders a canvas, you draw on it, the marks are extracted
back into `config.toml` (ribs, poke holes) or `overrides/*.geojson`
(regions). Each canvas carries an exact pixel→mm mapping. Current sites
are drawn colour-free, so any saturated colour on the page is a mark.

## Conventions

- Piece STLs have `z = 0` at the **recess floor**, not the build plate —
  that is 1.2 mm up in the assembled object. Each piece prints flat on
  its own.
- Clearances are LOCKED (see NOTES): piece↔frame 0.10 mm, piece↔piece
  0.20 mm, crush ribs biting 0.05 mm into the mating face.
- `make -n` clean and every body watertight is the bar for "done".

## Versioning

**v1.0 is the object stamped `AL & JL 2026 v1.0`** on the frame's south
wall. Nothing else here is a product version: `[output].build_tag` (T3)
tracks the *fit* generation — clearances and ribs — and P4/P5/P6 are
pipeline stages. Tag the commit that produced a print you keep, so the
number on the edge resolves to an exact config and pipeline.

## Future work

Nothing below is designed or scheduled; NOTES has the detail and the
reasoning for each. Split by whether it changes how pieces are *held*.

**v2 — same mechanism**

- **Waterways** (D9) — rivers on the terrain. Data already downloaded
  (`data/p2_waterways.geojson`); baseline is none.
- **Full-depth bodies** — land colour down to the floor, gray under the
  removable pieces. Fixes the edge cross-section and the teal cavity
  floors. Decide after judging translucency in a real print.
- **Thin necks** (D11) — 0.88 mm at Bakersfield, 1.04 Petaluma, 1.49
  Carquinez. Located and measured, never reshaped; T3 addressed fit with
  tolerance and rib placement instead, and it worked.
- **Vertical printing / adaptive layers** — 0.2 mm layers quantise
  terrain at ~98 m. Vertical gets far better relief at the cost of
  supports and inter-layer adhesion on the necks above.
- **Piece labels** — bottom version stamps exist but are disabled (bad
  rendering, 2026-09-14). The edge stamp solved small-text rendering, so
  this is a small revisit. Without it, pieces from different generations
  are indistinguishable by anything but feel.
- **Poke hole under the key** — the three pieces each get 18 mm holes
  through the frame floor; the key got none, so it can only come out by
  prying. Wanted for servicing the paper insert. Must miss the five
  2.5 mm pocket holes in the key plate, or poking ejects a plug instead
  of the key.
- **Region boundaries** — e.g. coast↔mountains near SF Bay. Not wrong,
  just arguable; `pipeline/region_markup.py` makes it a surgical edit.
- **US–Mexico line** — uses the NE polyline, ~800 m from Census truth.
  Accepted; switching is a small `p2_land.py` change.

**v3 — magnets**

Replaces friction with magnetic retention, which **decouples retention
from clearance**. Ribs, the 0.10/0.20 split, the symmetric pair rule and
the poke holes all exist only because a piece must be tight enough to
hold and loose enough to insert at once. Invalidates most of the fit
work, which is why it is its own version rather than an increment.

## License

Code (`pipeline/`, Makefile, config, overrides) is **MIT**. The design
and artwork — compass rose, key layout, the physical map, and the meshes
the pipeline produces — are **CC BY-SA 4.0**: print it, sell prints,
remix it, provided you credit AL & JL and share design derivatives
alike. No source data ships here (`data/` is fetched at build time) and
all of it is public domain; see `LICENSE`.

## See also

`NOTES.md` — design log: decisions and why, print-session findings,
the print-settings checklist, open risks. Read its HANDOFF STATE first.
