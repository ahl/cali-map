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
"""Rose-only test coupon (ahl 2026-09-14) -- isolates the compass rose
corner that already exists on both frame prints (P4 mini + P5 final) so
a raised-ink design tweak can be test-printed without reprinting the
whole frame.

The rose sits entirely over open water (p4_bay_coupon.main asserts this
-- ink-hull margins to coast/gray/cavities are all checked positive), so
"the corner that contains the compass rose" is just a flat water-color
disk at the water surface height (config [print].base_mm) with the ink
bodies (coast/gray/black) raised [compass].depth_mm on top -- exactly
the geometry p4_bay_coupon/p5_final emit for that corner, reusing the
SAME compass_art.RosePanel + p4_bay_coupon 3MF writer so the print
matches the real thing.

Uses [compass].diameter_mm (the FULL final-size rose, not the smaller
coupon_diameter_mm) since that's what ships on both real prints.

Output: out/rose_coupon/rose_coupon.3mf (multi-body Bambu 3MF: water +
coast + gray + black, filaments per p4_bay_coupon.EXTRUDERS)
"""

import sys
from pathlib import Path

import numpy as np
import trimesh
from shapely.geometry import Point
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import compass_art
import p4_bay_coupon as p4c

OUT_DIR = p4c.ROOT / "out" / "rose_coupon"
DIAMETER_MM = 60.0   # ahl 2026-09-14: was auto-sized off the letters'
                      # bounding-box diagonal (81.3 mm) -- way bigger
                      # than the ink actually needs, since the letters
                      # sit on-axis (a "+" footprint) and don't reach
                      # the bbox corners; true max ink radius is
                      # ~26 mm, so 60 mm still leaves ~4 mm clear.


def ink_max_radius_mm(rose):
    """True max radial extent of all ink (rose + letters, which
    load_rose already merges into rose.polys['black']) -- the tight
    circumscribing-circle radius, not the loose bbox diagonal."""
    ink = unary_union([g for g in rose.polys.values() if not g.is_empty])
    r = 0.0
    for p in getattr(ink, "geoms", [ink]):
        for ring in (p.exterior, *p.interiors):
            c = np.asarray(ring.coords)
            r = max(r, float(np.hypot(c[:, 0], c[:, 1]).max()))
    return r


def main():
    cfg = p4c.COMPASS
    style = cfg.get("style", "raised")
    depth = cfg.get("depth_mm", 0.4)
    assert style == "raised", (
        f"this coupon exists to test the RAISED style; config [compass]."
        f"style is {style!r} -- update config or this script's assert")

    rose = compass_art.load_rose(
        p4c.ROOT / cfg["svg"], cfg["diameter_mm"], cfg["letter_font"],
        cfg["letter_cap_mm"], cfg["letter_radius_frac"],
        cfg["ink_min_stroke_mm"])
    w, h = rose.size_mm
    radius = DIAMETER_MM / 2
    ink_r = ink_max_radius_mm(rose)
    assert ink_r < radius, (
        f"ink reaches r {ink_r:.2f} mm, past the {DIAMETER_MM:g} mm "
        f"coupon's r {radius:.1f} mm -- raise DIAMETER_MM")
    center = (radius, radius)

    disk_poly = Point(center).buffer(radius, quad_segs=96)
    disk = trimesh.creation.extrude_polygon(disk_poly, p4c.BASE_MM,
                                            engine="triangle")

    panel = compass_art.RosePanel(rose, center, depth)
    ink = panel.ink_meshes(p4c.BASE_MM, style=style)

    print(f"rose test coupon: disk dia {2 * radius:.1f} mm, height "
          f"{p4c.BASE_MM:g} mm (= config [print].base_mm, the water "
          f"surface height on both real frames)\n"
          f"  rose ring dia {cfg['diameter_mm']:g} mm (FULL final size) "
          f"at coupon center, letters bbox {w:.1f} x {h:.1f} mm, true "
          f"ink max radius {ink_r:.2f} mm ({radius - ink_r:.2f} mm clear "
          f"to the coupon edge), ink {style} +{depth:g} mm")
    ok = disk.is_watertight
    print(f"  water disk: watertight {disk.is_watertight}, volume "
          f"{disk.volume:.1f} mm^3")
    for name in ("coast", "gray", "black"):
        m = ink.get(name)
        if m is None:
            continue
        ok &= m.is_watertight
        print(f"  ink {name}: watertight {m.is_watertight}, volume "
              f"{m.volume:.2f} mm^3, z {m.bounds[0][2]:.2f}.."
              f"{m.bounds[1][2]:.2f} mm")
    assert ok, "not all bodies watertight"

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bodies = [("water", disk, p4c.EXTRUDERS["water"])]
    for name in ("coast", "gray", "black"):
        if name in ink:
            bodies.append((name, ink[name], p4c.EXTRUDERS[name]))
    path = OUT_DIR / "rose_coupon.3mf"
    p4c.write_bambu_3mf(path, "rose_coupon", bodies)
    print(f"-> {path} ({path.stat().st_size / 1e3:.0f} KB)  "
          f"[{p4c.lint_3mf(path)}]")

    render_preview(disk_poly, radius, rose, center)


def render_preview(disk_poly, radius, rose, center):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    import p1_regions as base

    fig, ax = plt.subplots(figsize=(6, 6), dpi=200)
    ax.set_facecolor("#1c1c22")
    p4c.add_poly(ax, disk_poly, p4c.WATER_RGB)
    rose_colors = {"coast": tuple(base.COLORS[base.COAST])[:3],
                   "gray": p4c.GRAY_RGB, "black": (0.12, 0.11, 0.11)}
    compass_art.draw_rose(ax, rose, center, rose_colors)
    ax.set_xlim(0, 2 * radius)
    ax.set_ylim(0, 2 * radius)
    ax.set_aspect("equal")
    ax.axis("off")
    path = OUT_DIR / "preview.png"
    fig.savefig(path, bbox_inches="tight", facecolor=fig.get_facecolor())
    plt.close(fig)
    print(f"-> {path}")


if __name__ == "__main__":
    main()
