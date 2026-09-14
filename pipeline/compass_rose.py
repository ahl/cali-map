# /// script
# requires-python = ">=3.11"
# dependencies = ["cairosvg"]
# ///
"""Compass rose vector generator (D17): 8-point nautical rose per ahl's
concept ("compass rose.jpeg", reduced from 16 to 8 points).

Emits assets/compass_rose.svg — the EDITABLE design source (view/tweak in
any vector editor; or adjust the parameters below and re-run). A PNG
preview is written next to it for quick viewing.

Print mapping (4-color frame, D17): black = outlines + letters + dark
point-halves; light point-halves and all fills = water color (the rose
sits in the Pacific, bottom-left of the frame).

Geometry is in abstract units (outer ring radius = 100); physical size is
chosen at frame-placement time.
"""

from pathlib import Path
import math

OUT_SVG = Path(__file__).resolve().parent.parent / "assets" / "compass_rose.svg"

# ---- parameters (all editable) --------------------------------------------
RING_R_OUT = 100.0   # outer ring, outside radius
RING_R_IN = 92.0     # outer ring, inside radius
CARD_TIP = 88.0      # cardinal (N/E/S/W) point tip radius
INTER_TIP = 60.0     # intercardinal (NE/SE/SW/NW) point tip radius
SHOULDER_R = 22.0    # radius of each point's base "shoulders"
SHOULDER_HALF_DEG = 22.5  # angular half-offset of shoulders from the point
CENTER_R = 13.0      # center circle radius
LETTER_R = 126.0     # letter anchor radius (outside the ring)
LETTER_SIZE = 30.0   # font size for N/E/S/W
STROKE = 2.0         # black outline width
BLACK = "#231f20"    # near-black (matches printed black nicely on screen)
WATER = "#bad1e6"    # water tint (screen stand-in for the water filament)
FONT = "Georgia, 'Times New Roman', serif"


def pt(r, deg):
    a = math.radians(deg - 90)          # 0 deg = North, clockwise
    return (r * math.sin(math.radians(deg)), -r * math.cos(math.radians(deg)))


def poly(points, fill):
    d = " ".join(f"{x:.2f},{y:.2f}" for x, y in points)
    return (f'<polygon points="{d}" fill="{fill}" stroke="{BLACK}" '
            f'stroke-width="{STROKE}" stroke-linejoin="miter"/>')


def point_halves(deg, tip_r):
    """One rose point as two half-polygons: clockwise half dark, counter-
    clockwise half light (classic alternating shading)."""
    tip = pt(tip_r, deg)
    sh_l = pt(SHOULDER_R, deg - SHOULDER_HALF_DEG)
    sh_r = pt(SHOULDER_R, deg + SHOULDER_HALF_DEG)
    dark = poly([tip, (0.0, 0.0), sh_r], BLACK)
    light = poly([tip, (0.0, 0.0), sh_l], WATER)
    return light + dark      # dark drawn last within the point


def build():
    e = []
    # outer ring: two concentric circles (band left in water color)
    for r in (RING_R_OUT, RING_R_IN):
        e.append(f'<circle cx="0" cy="0" r="{r}" fill="none" '
                 f'stroke="{BLACK}" stroke-width="{STROKE}"/>')
    # intercardinal points first (under the cardinals), then cardinals
    for deg in (45, 135, 225, 315):
        e.append(point_halves(deg, INTER_TIP))
    for deg in (0, 90, 180, 270):
        e.append(point_halves(deg, CARD_TIP))
    # center circle over the star bases
    e.append(f'<circle cx="0" cy="0" r="{CENTER_R}" fill="{WATER}" '
             f'stroke="{BLACK}" stroke-width="{STROKE}"/>')
    # cardinal letters
    for label, deg in (("N", 0), ("E", 90), ("S", 180), ("W", 270)):
        x, y = pt(LETTER_R, deg)
        e.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{FONT}" '
                 f'font-size="{LETTER_SIZE}" font-weight="bold" '
                 f'fill="{BLACK}" text-anchor="middle" '
                 f'dominant-baseline="central">{label}</text>')
    m = LETTER_R + LETTER_SIZE
    return (f'<svg xmlns="http://www.w3.org/2000/svg" '
            f'viewBox="{-m:.0f} {-m:.0f} {2*m:.0f} {2*m:.0f}">'
            + "".join(e) + "</svg>")


def main():
    OUT_SVG.parent.mkdir(exist_ok=True)
    svg = build()
    OUT_SVG.write_text(svg)
    print(f"wrote {OUT_SVG}")
    import cairosvg
    png = OUT_SVG.with_suffix(".png")
    cairosvg.svg2png(bytestring=svg.encode(), write_to=str(png),
                     output_width=800, background_color="#dfe9f2")
    print(f"wrote {png} (preview)")


if __name__ == "__main__":
    main()
