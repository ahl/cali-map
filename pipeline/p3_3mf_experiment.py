# /// script
# requires-python = ">=3.11"
# dependencies = [
#   "numpy",
#   "trimesh",
#   "lxml",       # trimesh 3MF export requires lxml...
#   "networkx",   # ...and networkx (scene graph); plain trimesh dep set lacks both
# ]
# ///
"""P3 experiment: multi-body 3MF export candidates for Bambu Studio.

Two interlocked cubes (overlapping corner, absolute mm coordinates,
identity transforms) exported three ways to out/experiments/:

  cubes_trimesh_multiobject.3mf  (A) trimesh Scene export, one 3MF object
                                     per body. Bambu should offer "load as
                                     single object with multiple parts".
  cubes_components.3mf           (B) hand-rolled vanilla 3MF: one build
                                     item -> object of <components>, each
                                     component a mesh object.
  cubes_bambu.3mf                (C) hand-rolled Bambu-flavored 3MF:
                                     Application=BambuStudio metadata,
                                     production-extension UUIDs, and
                                     Metadata/model_settings.config with
                                     per-part extruder (water -> 2).

Human check (cannot run Bambu Studio here): open each in Bambu Studio,
confirm one object / two parts, relative position preserved, and for (C)
that part "water" arrives pre-assigned to filament 2.
"""

import uuid
import zipfile
from pathlib import Path

import numpy as np
import trimesh

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "experiments"
OUT.mkdir(parents=True, exist_ok=True)

# Two 20 mm cubes overlapping in a corner; absolute coordinates, mm.
region = trimesh.creation.box(extents=(20, 20, 20))
region.apply_translation((10, 10, 10))  # occupies [0,20]^3
water = trimesh.creation.box(extents=(20, 20, 20))
water.apply_translation((22, 22, 22))  # occupies [12,32]^3 -> interlocked

BODIES = [("region", region, 1), ("water", water, 2)]  # (name, mesh, extruder)

# ---------------------------------------------------------------- (A) trimesh
scene = trimesh.Scene({name: mesh for name, mesh, _ in BODIES})
scene.export(OUT / "cubes_trimesh_multiobject.3mf")

# ------------------------------------------------------- shared XML helpers
CORE = "http://schemas.microsoft.com/3dmanufacturing/core/2015/02"
PROD = "http://schemas.microsoft.com/3dmanufacturing/production/2015/06"

CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
 <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
 <Default Extension="model" ContentType="application/vnd.ms-package.3dmanufacturing-3dmodel+xml"/>
</Types>"""

RELS = """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
 <Relationship Target="/3D/3dmodel.model" Id="rel-1" Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/>
</Relationships>"""


def mesh_xml(mesh: trimesh.Trimesh) -> str:
    vs = "\n".join(
        f'     <vertex x="{x:.6f}" y="{y:.6f}" z="{z:.6f}"/>'
        for x, y, z in mesh.vertices
    )
    ts = "\n".join(
        f'     <triangle v1="{a}" v2="{b}" v3="{c}"/>' for a, b, c in mesh.faces
    )
    return (
        "   <mesh>\n    <vertices>\n" + vs + "\n    </vertices>\n"
        "    <triangles>\n" + ts + "\n    </triangles>\n   </mesh>"
    )


def write_3mf(path: Path, model_xml: str, extra: dict[str, str] | None = None):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", CONTENT_TYPES)
        z.writestr("_rels/.rels", RELS)
        z.writestr("3D/3dmodel.model", model_xml)
        for name, data in (extra or {}).items():
            z.writestr(name, data)


IDENT = "1 0 0 0 1 0 0 0 1 0 0 0"  # 3MF row-major 4x3

# ------------------------------------------------- (B) vanilla + components
objs = []
comps = []
for i, (name, mesh, _) in enumerate(BODIES, start=1):
    objs.append(f'  <object id="{i}" type="model" name="{name}">\n{mesh_xml(mesh)}\n  </object>')
    comps.append(f'    <component objectid="{i}" transform="{IDENT}"/>')
n_assy = len(BODIES) + 1
model_b = f"""<?xml version="1.0" encoding="UTF-8"?>
<model unit="millimeter" xml:lang="en-US" xmlns="{CORE}">
 <metadata name="Application">cali-map-pipeline</metadata>
 <resources>
{chr(10).join(objs)}
  <object id="{n_assy}" type="model" name="piece">
   <components>
{chr(10).join(comps)}
   </components>
  </object>
 </resources>
 <build>
  <item objectid="{n_assy}" transform="{IDENT}" printable="1"/>
 </build>
</model>"""
write_3mf(OUT / "cubes_components.3mf", model_b)

# ------------------------------------------------------- (C) Bambu-flavored
def u() -> str:
    return str(uuid.uuid4())

objs = []
comps = []
parts = []
for i, (name, mesh, extruder) in enumerate(BODIES, start=1):
    objs.append(f'  <object id="{i}" p:UUID="{u()}" type="model">\n{mesh_xml(mesh)}\n  </object>')
    comps.append(f'    <component p:UUID="{u()}" objectid="{i}" transform="{IDENT}"/>')
    parts.append(
        f'  <part id="{i}" subtype="normal_part">\n'
        f'   <metadata key="name" value="{name}"/>\n'
        f'   <metadata key="extruder" value="{extruder}"/>\n'
        f'   <metadata key="matrix" value="1 0 0 0 0 1 0 0 0 0 1 0 0 0 0 1"/>\n'
        f"  </part>"
    )
model_c = f"""<?xml version="1.0" encoding="UTF-8"?>
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
  <metadata key="name" value="piece"/>
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
write_3mf(
    OUT / "cubes_bambu.3mf",
    model_c,
    {"Metadata/model_settings.config": model_settings},
)

for f in sorted(OUT.glob("cubes_*.3mf")):
    print(f, f.stat().st_size, "bytes")
