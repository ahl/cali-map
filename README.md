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

## See also

`NOTES.md` — design log: decisions and why, print-session findings,
the print-settings checklist, open risks. Read its HANDOFF STATE first.
