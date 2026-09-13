# 3MF export for multi-body pieces (Bambu Studio, AMS) — findings 2026-09-13

## Recommendation

Write **one 3MF per puzzle piece, hand-rolled Bambu-flavored** (it's a tiny zip; ~60
lines of Python, no extra deps beyond `zipfile`): one `<object>` of `<components>`
(one mesh object per body: terrain + each water inlay), all coordinates baked in mm
(identity transforms), plus `Metadata/model_settings.config` declaring the parts:

```xml
<object id="3">
  <metadata key="name" value="piece"/>  <metadata key="extruder" value="1"/>
  <part id="1" subtype="normal_part"> <metadata key="name" value="region"/>  <metadata key="extruder" value="1"/> </part>
  <part id="2" subtype="normal_part"> <metadata key="name" value="water"/>   <metadata key="extruder" value="2"/> </part>
</object>
```

and `<metadata name="Application">BambuStudio-…</metadata>` in `3D/3dmodel.model` so
Bambu Studio treats it as a native project: the piece arrives as **one object with
named parts**, exact relative positions preserved, water bodies **pre-assigned to
filament 2** (user just maps AMS slots). This is the same structure Bambu Studio
writes itself (Printago teardown; the `bambu-3mf-export` project does exactly this
and confirms it opens "as a real project"). Per-part `extruder` is 1-based; use
`subtype="negative_part"` later if we ever want boolean-subtract parts.

## Fallback (community-verified, zero custom XML)

Plain **vanilla multi-object 3MF via `trimesh.Scene({...}).export("x.3mf")`** — one
named object per body, shared coordinate frame. Bambu Studio shows "not from Bambu
Lab, load geometry only", then (for multiple objects) asks **"load these as a single
object with multiple parts?" → Yes** gives one object whose parts keep their exact
relative positions; user then right-clicks each part to assign filament. One dialog
click + manual color per part, but no format risk. (Multi-STL baseline is strictly
worse: same dialogs but N files and no single-file provenance — keep only as escape
hatch; STLs do carry absolute coords, so relative position survives the combine.)

## Python tooling notes

- **trimesh** 3MF export: supports `Scene` with multiple named geometries (dict key →
  `name` attr), hardcodes `unit="millimeter"`, does **no axis conversion** (3MF is
  Z-up like our meshes — good), writes build items with transforms. Pitfall: needs
  `lxml` **and `networkx`** at export time (soft deps — add both to PEP 723 blocks).
  It cannot emit the single-object/components grouping or Bambu metadata.
- **lib3mf**: pip name is **`py-lib3mf`** (official 3MF Consortium bindings,
  `from py_lib3mf import Lib3MF`; v2.3.1 verified locally). Fine as a validator/reader
  but no help for Bambu sidecars (it drops/ignores `Metadata/*.config`), so it buys
  nothing over the hand-rolled writer. Used here to lint our outputs: all three
  candidates parse with only cosmetic warnings (non-spec `printable`/Bambu metadata).
- Bake geometry in absolute mm coordinates, identity transforms — sidesteps all
  transform/precision issues and makes "parts stay put" trivially true.

## Layer-swap two-color mode (coastal piece)

Confirmed supported, needs **nothing special in our file**: user slices, moves the
layer slider to the target layer, right-clicks the "+" → **"Change Filament"**
(AMS required) or "Add Custom G-code" (M600-style). Caveats: "Change Filament" on the
slider is only enabled when the plate is otherwise single-color — so ship the coastal
piece as a plain one-body mesh for this mode; alternative is the **height range
modifier** (right-click object → per-range filament). We should just print the target
transition Z (and layer number at 0.2 mm) in the pipeline output/README.

## Human check (I can't run Bambu Studio)

Open **`/Users/ahl/src/cali-map/out/experiments/cubes_bambu.3mf`** in Bambu Studio:
expect ONE object "piece", two parts ("region" [0,20]³, "water" [12,32]³ interlocked,
positions preserved), water pre-assigned filament 2, no "not from Bambu Lab" prompt.
If it degrades to geometry-only/separate objects, fall back to
`out/experiments/cubes_trimesh_multiobject.3mf` (answer Yes to the combine dialog) and
tell the generator (`pipeline/p3_3mf_experiment.py`) which path won.

## Sources

- https://printago.io/blog/3mf-file-format (Bambu 3MF internals, model_settings.config, extruder keys)
- https://github.com/m-esm/bambu-3mf-export (hand-assembled Bambu 3MF from Python, per-part settings)
- https://forum.bambulab.com/t/importing-multiple-objects-from-fusion-360-to-bambu-studio/62826 ("single object with multiple parts" dialog)
- https://forum.bambulab.com/t/change-filament-at-layer-height/7954 and https://forum.bambulab.com/t/change-filament-at-layer-is-disabled-while-printing-multicolor-prints/55470
- https://github.com/mikedh/trimesh/blob/main/trimesh/exchange/threemf.py (export: names, mm, no axis flip)
- https://github.com/3MFConsortium/lib3mf_python / https://pypi.org/project/py-lib3mf/
- https://wiki.bambulab.com/en/software/bambu-studio/3mf-compatibility
