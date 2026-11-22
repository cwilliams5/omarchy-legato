#!/usr/bin/env python3
"""A starter for a project's logo kit (name-and-brand skill, logo stage).

Copy it into the project as branding/build.py, then edit the marked parts:
the ICONS, the letters your wordmark needs, and OPTIONS (name, palette, which
icon, which letters). Run:

    python3 branding/build.py            # writes into the folder it lives in

Per option it writes: icon.svg / icon-color.svg, wordmark.svg /
wordmark-color.svg, and preview.png (a sheet: big icon, 64/32/24/16 px, the
wordmark on dark and light, the palette, the icon on a mock bar, the
one-color icon in several theme colors). It also prints a contrast report:
text on the background (wants 4.5:1) and the accent on dark and on white
(wants about 3:1 for a mark).

When Cody picks, mark that option "picked": True. That option then also gets
lockup-light.svg, lockup-dark.svg and tile.svg, and the repo's icon.svg one
folder up. As shipped nothing is picked, so a first run only writes inside
its own folder.

This copy builds Legato's kit: the picked mark (Slur, in legato/), the two
other Legato marks (alternatives/), and the Rubato marks drawn while choosing
between the names (alternatives/naming-comparisons/).

Options can set:
- "descender": True     room below the baseline for g, j, p, q, y
- "lockup_scale"        the wordmark's size beside the mark (default 64/86,
                        right for a square mark and an underlined wordmark)
- "lockup_dy"           its vertical offset (default 2)
- "accent_on_light"     a deeper accent for the light lockup, when the
                        accent fades on white

Letters are drawn as paths (no font needed): monoline lowercase on a 40-unit
x-height (baseline y=60) and capitals, covering
a c e g h i l m n o p r s t u w y and A C E G H I L M N O P R S T U W Y.
Add the letters your name needs in the same style: each returns (path data,
advance width) for a letter starting at x. Look at every preview before
showing it: overlaps, clipped descenders and misreadings only show up
rendered.
"""
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent  # the output folder: branding/

# ------------------------------------------------------------------ letters (EDIT: add yours)
# Monoline lowercase on a 40-unit x-height (baseline y=60, x-height y=20).
# Each returns (path data, advance width) for a letter starting at x.

def t(x):
    return (f"M{x+10} 6 V48 A12 12 0 0 0 {x+22} 60 M{x} 22 H{x+23}", 26)

def r(x):
    return (f"M{x} 22 V60 M{x} 38 A18 18 0 0 1 {x+18} 20 H{x+22}", 26)

def a(x):
    return (f"M{x+40} 40 A20 20 0 1 0 {x} 40 A20 20 0 1 0 {x+40} 40 Z M{x+40} 22 V60", 44)

def n(x):
    return (f"M{x} 22 V60 M{x} 38 A16 16 0 0 1 {x+32} 38 V60", 36)

def s(x):
    return (f"M{x+27} 25 C{x+24} 21 {x+19} 20 {x+14} 20 C{x+7} 20 {x+2} 24 {x+2} 30 "
            f"C{x+2} 36 {x+9} 38 {x+15} 40 C{x+21} 42 {x+28} 44 {x+28} 51 "
            f"C{x+28} 57 {x+22} 60 {x+14} 60 C{x+8} 60 {x+3} 58 {x+1} 54", 32)

def o(x):
    return (f"M{x+40} 40 A20 20 0 1 0 {x} 40 A20 20 0 1 0 {x+40} 40 Z", 44)

def o_window(x):
    # A rounded square with a mullion and transom: a window for an "o".
    return (f"M{x+6} 20 H{x+34} A6 6 0 0 1 {x+40} 26 V54 A6 6 0 0 1 {x+34} 60 H{x+6} "
            f"A6 6 0 0 1 {x} 54 V26 A6 6 0 0 1 {x+6} 20 Z M{x} 49 H{x+40}", 44)

def m(x):
    return (f"M{x} 22 V60 M{x} 36 A13 13 0 0 1 {x+26} 36 V60 M{x+26} 36 A13 13 0 0 1 {x+52} 36 V60", 52)

def word(letters, x=8, gap=10):
    parts = []
    for letter in letters:
        d, w = letter(x)
        parts.append(d)
        x += w + gap
    return " ".join(parts), x - gap

# Monoline capitals on a 40-unit cap height (y=20..60), for option 2.
def T(x):  return (f"M{x} 20 H{x+30} M{x+15} 20 V60", 30)
def R(x):  return (f"M{x} 60 V20 H{x+16} A10 10 0 0 1 {x+16} 40 H{x} M{x+14} 40 L{x+28} 60", 28)
def A(x):  return (f"M{x} 60 L{x+16} 20 L{x+32} 60 M{x+6} 46 H{x+26}", 32)
def N(x):  return (f"M{x} 60 V20 L{x+28} 60 V20", 28)
def S(x):  return (f"M{x+26} 26 C{x+23} 21 {x+18} 20 {x+13} 20 C{x+6} 20 {x+1} 24 {x+1} 30 "
                   f"C{x+1} 37 {x+8} 38 {x+14} 40 C{x+20} 42 {x+27} 44 {x+27} 51 "
                   f"C{x+27} 57 {x+21} 60 {x+13} 60 C{x+7} 60 {x+2} 58 {x} 54", 28)
def O(x):  return (f"M{x+40} 40 A20 20 0 1 0 {x} 40 A20 20 0 1 0 {x+40} 40 Z", 40)
def M(x):  return (f"M{x} 60 V20 L{x+18} 46 L{x+36} 20 V60", 36)

# Added for Locus and Rayleigh, in the same monoline style. Descenders (y, g)
# reach y=78, so options using them set "descender": True for a taller box.
def l(x):
    return (f"M{x} 4 V48 A12 12 0 0 0 {x+12} 60", 14)

def c(x):
    return (f"M{x+34.1} 25.9 A20 20 0 1 0 {x+34.1} 54.1", 38)

def u(x):
    return (f"M{x} 22 V42 A16 16 0 0 0 {x+32} 42 M{x+32} 22 V60", 36)

def y(x):
    return (f"M{x} 22 V40 A16 16 0 0 0 {x+32} 40 M{x+32} 22 V64 A14 14 0 0 1 {x+18} 78 H{x+8}", 36)

def e(x):
    return (f"M{x+1} 40 H{x+40} A20 20 0 1 0 {x+34.1} 54.1", 44)

def i(x):
    return (f"M{x+2} 22 V60 M{x+2} 7 V8", 4)

def g(x):
    return (f"M{x+40} 40 A20 20 0 1 0 {x} 40 A20 20 0 1 0 {x+40} 40 Z "
            f"M{x+40} 22 V64 A14 14 0 0 1 {x+26} 78 H{x+10}", 44)

def h(x):
    return (f"M{x} 4 V60 M{x} 38 A16 16 0 0 1 {x+32} 38 V60", 36)

def L(x):  return (f"M{x} 20 V60 H{x+24}", 24)
def C(x):  return (f"M{x+34.1} 25.9 A20 20 0 1 0 {x+34.1} 54.1", 36)
def U(x):  return (f"M{x} 20 V44 A14 14 0 0 0 {x+28} 44 V20", 28)
def Y(x):  return (f"M{x} 20 L{x+15} 40 L{x+30} 20 M{x+15} 40 V60", 30)
def E(x):  return (f"M{x+24} 20 H{x} V60 H{x+24} M{x} 40 H{x+20}", 24)
def I(x):  return (f"M{x+2} 20 V60", 4)
def G(x):  return (f"M{x+34.1} 25.9 A20 20 0 1 0 {x+40} 40 H{x+24}", 40)
def H(x):  return (f"M{x} 20 V60 M{x+28} 20 V60 M{x} 40 H{x+28}", 28)

def p(x):
    return (f"M{x} 22 V78 M{x} 40 A20 20 0 1 1 {x+40} 40 A20 20 0 1 1 {x} 40", 44)

def b(x):
    return (f"M{x} 4 V60 M{x} 40 A20 20 0 1 1 {x+40} 40 A20 20 0 1 1 {x} 40", 44)

def B(x):  return (f"M{x} 60 V20 H{x+14} A10 10 0 0 1 {x+14} 40 H{x} M{x+14} 40 H{x+16} A10 10 0 0 1 {x+16} 60 H{x}", 28)

def w(x):
    return (f"M{x} 22 L{x+12} 60 L{x+24} 30 L{x+36} 60 L{x+48} 22", 48)

def P(x):  return (f"M{x} 60 V20 H{x+16} A10 10 0 0 1 {x+16} 40 H{x}", 28)
def W(x):  return (f"M{x} 20 L{x+10} 60 L{x+20} 30 L{x+30} 60 L{x+40} 20", 40)

# -------------------------------------------------------------------- icons
# 64x64, drawn to read at 16px. Lines in currentColor; the accent part in
# var(--accent, currentColor), so one-color use just works.

# EDIT: your marks. 64x64, readable at 16px; lines in currentColor, the
# accent part in var(--accent, currentColor).
ICONS = {
    # Legato 1: the legato slur over two noteheads, which doubles as headphones.
    "slur": """
  <path d="M4 42 C4 -2 60 -2 60 42 C55 9 9 9 4 42 Z" fill="var(--accent, currentColor)"/>
  <ellipse cx="11.5" cy="48" rx="10" ry="7.5" transform="rotate(-24 11.5 48)" fill="currentColor"/>
  <ellipse cx="52.5" cy="48" rx="10" ry="7.5" transform="rotate(-24 52.5 48)" fill="currentColor"/>""",
    # Legato 2: a script ell drawn as one unbroken stroke, looping round a play triangle.
    "ell": """
  <path d="M10 50 C20 44 30 38 38 30 C46 22 48 12 42 7 C36 2 28 6 26 16 C24 28 24 40 26 48 C28 58 40 60 52 50" fill="none" stroke="currentColor" stroke-width="5.5" stroke-linecap="round" stroke-linejoin="round"/>
  <path d="M31.5 12.5 L39.5 18 L31.5 23.5 Z" fill="var(--accent, currentColor)" stroke="var(--accent, currentColor)" stroke-width="2.2" stroke-linejoin="round"/>""",
    # Legato 3: the handoff itself, a phone tied to a screen by the slur.
    "handoff": """
  <rect x="5" y="30" width="15" height="26" rx="3.5" fill="none" stroke="currentColor" stroke-width="4"/>
  <rect x="27" y="26" width="32" height="22" rx="3.5" fill="none" stroke="currentColor" stroke-width="4"/>
  <path d="M38 55 H48 M43 48 V55" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
  <path d="M10 25 C14 3 44 1 49 21 C42 9 18 9 10 25 Z" fill="var(--accent, currentColor)"/>""",
    # Rubato 1: a metronome whose arm has swung off the beat.
    "metronome": """
  <path d="M11 57 L24 8 H40 L53 57 Z" fill="none" stroke="currentColor" stroke-width="5" stroke-linejoin="round"/>
  <path d="M32 50 L55 9" fill="none" stroke="var(--accent, currentColor)" stroke-width="5" stroke-linecap="round"/>
  <circle cx="32" cy="50" r="4" fill="var(--accent, currentColor)"/>
  <rect x="38.5" y="22.5" width="14" height="9" rx="2.5" transform="rotate(-60.7 45.5 27)" fill="var(--accent, currentColor)"/>""",
    # Rubato 2: a clock whose hands spell a lowercase r; the stolen minutes on its rim.
    "clockr": """
  <path d="M52.8 21 A24 24 0 1 1 32 9" fill="none" stroke="currentColor" stroke-width="4.5" stroke-linecap="round"/>
  <path d="M35.6 5.2 A28 28 0 0 1 54.1 16" fill="none" stroke="var(--accent, currentColor)" stroke-width="4.5" stroke-linecap="round"/>
  <path d="M32 33 V17 M32 33 L42 40" fill="none" stroke="currentColor" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/>""",
}

# ----------------------------------------------------------------- options

OPTIONS = [
    {
        "slug": "legato",
        "name": "Legato",
        "picked": True,
        "accent_on_light": "#D94F7C",
        # Lockup: letters sized to the mark, baseline on the noteheads' feet,
        # the g hanging below; no second slur under the word.
        "lockup_plain": True,
        "lockup_scale": 0.78,
        "lockup_dy": 9.2,
        "lockup_height": 74,
        "icon": "slur",
        "letters": [l, e, g, a, t, o],
        "stroke": 7,
        "descender": True,
        "underline": True,
        "under_style": "slur",
        "palette": [("Ink", "#1B1F2A", "background"), ("Rose", "#F2789F", "accent"),
                    ("Gold", "#F4C26B", "highlight"), ("Ivory", "#F5EFE6", "text")],
    },
    {
        "slug": "alternatives/ell",
        "name": "Legato: Ell",
        "icon": "ell",
        "letters": [L, E, G, A, T, O],
        "stroke": 4.5,
        "gap": 15,
        "underline": False,
        "palette": [("Deep teal", "#10282B", "background"), ("Aqua", "#4FD1C5", "accent"),
                    ("Amber", "#F6AD55", "highlight"), ("Foam", "#E6FFFA", "text")],
    },
    {
        "slug": "alternatives/handoff",
        "name": "Legato: Handoff",
        "icon": "handoff",
        "letters": [l, e, g, a, t, o],
        "stroke": 9,
        "descender": True,
        "underline": False,
        "palette": [("Night", "#191A3A", "background"), ("Periwinkle", "#8B9CFF", "accent"),
                    ("Butter", "#FFD166", "highlight"), ("Cloud", "#F0F2FF", "text")],
    },
    {
        "slug": "alternatives/naming-comparisons/rubato-metronome",
        "name": "Rubato: Metronome",
        "icon": "metronome",
        "letters": [R, U, B, A, T, O],
        "stroke": 4.5,
        "gap": 15,
        "underline": False,
        "palette": [("Walnut", "#2A1D16", "background"), ("Brass", "#E0A458", "accent"),
                    ("Cinnabar", "#C0544B", "highlight"), ("Parchment", "#F3E9DC", "text")],
    },
    {
        "slug": "alternatives/naming-comparisons/rubato-stolen-time",
        "name": "Rubato: Stolen time",
        "icon": "clockr",
        "letters": [r, u, b, a, t, o],
        "stroke": 7,
        "underline": True,
        "palette": [("Graphite", "#1A1A1D", "background"), ("Mint", "#3DDC97", "accent"),
                    ("Coral", "#FF6B6B", "highlight"), ("Chalk", "#F4F4F5", "text")],
    },
]


def icon_svg(body, size=64, color=None, accent=None):
    style = ""
    if color or accent:
        style = f' style="color:{color or "currentColor"};--accent:{accent or color or "currentColor"}"'
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="{size}" height="{size}"{style}>'
            f'{resolve_accent(body, accent or color)}\n</svg>\n')


def resolve_accent(body, accent):
    # rsvg doesn't do CSS variables; spell the accent out when one is given.
    return body.replace("var(--accent, currentColor)", accent or "currentColor")


def wordmark(option):
    gap = option.get("gap", 10)
    d, width = word(option["letters"], gap=gap)
    stroke = option["stroke"]
    under = ""
    height = 84 if option.get("descender") else 72
    if option["underline"] and option.get("under_style") == "slur":
        # A legato slur under the word: a crescent, thick in the middle.
        top = height + 2
        under = (f'<path d="M8 {top} C{8 + width * 0.25:.1f} {top + 22} {width * 0.75:.1f} {top + 22} {width} {top} '
                 f'C{width * 0.75:.1f} {top + 12} {8 + width * 0.25:.1f} {top + 12} 8 {top} Z" fill="ACCENT"/>')
        height += 22
    elif option["underline"]:
        under = f'<path d="M8 {height + 4} H{width}" stroke="ACCENT" stroke-width="{stroke + 1}" stroke-linecap="round"/>'
        height += 14
    return d, width + 8, height, stroke, under


def wordmark_svg(option, color="currentColor", accent="currentColor"):
    d, width, height, stroke, under = wordmark(option)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width * 2}" height="{height * 2}">'
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round"/>'
            f'{under.replace("ACCENT", accent)}</svg>\n')


def sheet_svg(option):
    """A 1200x760 preview: icon big, icon small sizes, wordmark on dark and
    light, the palette, the icon as a start button on a bar, and the
    one-color icon in several theme colors."""
    pal = {role: hexv for _, hexv, role in option["palette"]}
    bg, accent, hi, text = pal["background"], pal["accent"], pal["highlight"], pal["text"]
    body = ICONS[option["icon"]]
    d, ww, wh, stroke, under = wordmark(option)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="760" viewBox="0 0 1200 760" '
           f'font-family="JetBrainsMono Nerd Font, Liberation Mono, monospace">',
           f'<rect width="1200" height="760" fill="{bg}"/>']
    # Big icon
    out.append(f'<g transform="translate(60 60) scale(5)" style="color:{text}">{resolve_accent(body, accent)}</g>')
    # Small sizes
    x = 420
    for size in (64, 32, 24, 16):
        out.append(f'<g transform="translate({x} {60 + (64 - size)}) scale({size / 64})" style="color:{text}">{resolve_accent(body, accent)}</g>')
        out.append(f'<text x="{x}" y="150" fill="{text}" opacity="0.6" font-size="13">{size}px</text>')
        x += size + 40
    # Wordmark on dark
    scale = 560 / ww
    out.append(f'<g transform="translate(420 190) scale({scale:.3f})">'
               f'<path d="{d}" fill="none" stroke="{text}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round"/>'
               f'{under.replace("ACCENT", accent)}</g>')
    # Light panel with wordmark and icon in background color
    out.append(f'<rect x="60" y="420" width="520" height="150" rx="14" fill="{text}"/>')
    out.append(f'<g transform="translate(90 455) scale(1.25)" style="color:{bg}">{resolve_accent(body, accent)}</g>')
    s2 = min(340 / ww, 100 / wh)  # tall wordmarks (descender plus slur) fit the panel
    out.append(f'<g transform="translate(200 {470 - 10 * s2:.1f}) scale({s2:.3f})">'
               f'<path d="{d}" fill="none" stroke="{bg}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round"/>'
               f'{under.replace("ACCENT", accent)}</g>')
    # Palette
    x = 620
    for name, hexv, role in option["palette"]:
        out.append(f'<rect x="{x}" y="420" width="120" height="96" rx="12" fill="{hexv}" stroke="{text}" stroke-opacity="0.25"/>')
        out.append(f'<text x="{x}" y="540" fill="{text}" font-size="15">{name}</text>')
        out.append(f'<text x="{x}" y="560" fill="{text}" opacity="0.7" font-size="13">{hexv}</text>')
        out.append(f'<text x="{x}" y="578" fill="{text}" opacity="0.5" font-size="13">{role}</text>')
        x += 135
    # A bar with the icon as the start button
    out.append(f'<rect x="0" y="690" width="1200" height="70" fill="#000" opacity="0.35"/>')
    out.append(f'<g transform="translate(24 703) scale(0.69)" style="color:{text}">{resolve_accent(body, accent)}</g>')
    for i, w in enumerate((210, 210, 210)):
        bx = 300 + i * 220
        out.append(f'<rect x="{bx}" y="702" width="{w}" height="46" rx="8" fill="{text}" opacity="{0.16 if i == 1 else 0.06}"/>')
        out.append(f'<rect x="{bx + 14}" y="716" width="18" height="18" rx="4" fill="{text}" opacity="0.5"/>')
        out.append(f'<rect x="{bx + 44}" y="721" width="{w - 70}" height="8" rx="4" fill="{text}" opacity="0.45"/>')
    out.append(f'<rect x="{300 + 220 + 20}" y="744" width="170" height="4" rx="2" fill="{accent}"/>')
    # One-color icon following theme colors
    x = 60
    out.append(f'<text x="60" y="618" fill="{text}" opacity="0.6" font-size="13">one color, following themes:</text>')
    for color in ("#F8F8F2", "#A6E3A1", "#7AA2F7", "#EBDBB2", "#F5C2E7", "#E0DEF4", "#1E1E2E"):
        out.append(f'<rect x="{x}" y="630" width="48" height="48" rx="8" fill="{"#E6E6E6" if color == "#1E1E2E" else "#16161E"}"/>')
        out.append(f'<g transform="translate({x + 8} 638) scale(0.5)" style="color:{color}">{resolve_accent(body, color)}</g>')
        x += 58
    out.append(f'<text x="1140" y="660" text-anchor="end" fill="{text}" font-size="34" opacity="0.9">{option["name"]}</text>')
    out.append('</svg>\n')
    return "\n".join(out)


def lockup_svg(option, text, accent):
    """The icon and the wordmark side by side, for the README's header."""
    body = resolve_accent(ICONS[option["icon"]], accent)
    d, ww, wh, stroke, under = wordmark(option)
    if option.get("lockup_plain"):
        under = ""  # the mark already carries the slur; one is enough beside it
    height = option.get("lockup_height", 64)  # taller when a descender hangs below the mark
    # The wordmark's height matched to the mark's. The starter's default (64/86)
    # suits a square mark beside an underlined wordmark; Locus's arc is 32
    # units tall, so its ascenders (y 4 to 60) are scaled to match and the
    # baseline sits on the arc's feet.
    scale = option.get("lockup_scale", 64 / 86)
    dy = option.get("lockup_dy", 2)
    width = 64 + 18 + ww * scale
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:.0f} {height}" width="{width * 3:.0f}" height="{height * 3}">'
            f'<g style="color:{text}">{body}</g>'
            f'<g transform="translate(82 {dy:.2f}) scale({scale:.4f})">'
            f'<path d="{d}" fill="none" stroke="{text}" stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round"/>'
            f'{under.replace("ACCENT", accent)}</g></svg>\n')


def tile_svg(option, background, text, accent):
    """The icon on a rounded tile: an app icon that reads on any background."""
    body = resolve_accent(ICONS[option["icon"]], accent)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" width="256" height="256">'
            f'<rect width="64" height="64" rx="14" fill="{background}"/>'
            f'<g transform="translate(9 9) scale(0.72)" style="color:{text}">{body}</g></svg>\n')


def luminance(hexv):
    def channel(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    h = hexv.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast(a, b):
    la, lb = sorted((luminance(a), luminance(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def contrast_report(option):
    """Prints the contrasts that matter; flags the ones too low."""
    pal = {role: hexv for _, hexv, role in option["palette"]}
    checks = [
        ("text on background", pal["text"], pal["background"], 4.5),
        ("accent on background", pal["accent"], pal["background"], 3.0),
        ("accent on white (light lockup)", option.get("accent_on_light", pal["accent"]), "#FFFFFF", 3.0),
        ("background ink on white (light lockup)", pal["background"], "#FFFFFF", 4.5),
    ]
    for label, fg, bg, want in checks:
        ratio = contrast(fg, bg)
        flag = "" if ratio >= want else f"   <-- below {want}:1"
        print(f"    {label:40s} {ratio:5.2f}:1{flag}")


def main():
    for option in OPTIONS:
        folder = HERE / option["slug"]
        folder.mkdir(parents=True, exist_ok=True)
        body = ICONS[option["icon"]]
        pal = {role: hexv for _, hexv, role in option["palette"]}
        (folder / "icon.svg").write_text(icon_svg(body))
        (folder / "icon-color.svg").write_text(icon_svg(body, color=pal["text"], accent=pal["accent"]))
        (folder / "wordmark.svg").write_text(wordmark_svg(option))
        (folder / "wordmark-color.svg").write_text(wordmark_svg(option, color=pal["text"], accent=pal["accent"]))
        if option.get("picked"):
            (folder / "lockup-dark.svg").write_text(lockup_svg(option, pal["text"], pal["accent"]))
            # A deeper accent where it sits on white, so the mark's point keeps 3:1.
            (folder / "lockup-light.svg").write_text(lockup_svg(option, pal["background"], option.get("accent_on_light", pal["accent"])))
            (folder / "tile.svg").write_text(tile_svg(option, pal["background"], pal["text"], pal["accent"]))
            # The repo's own icon (marketplace listings, the README).
            (HERE.parent / "icon.svg").write_text(tile_svg(option, pal["background"], pal["text"], pal["accent"]))
        sheet = folder / "preview.svg"
        sheet.write_text(sheet_svg(option))
        subprocess.run(["rsvg-convert", "-w", "1200", "-o", str(folder / "preview.png"), str(sheet)], check=True)
        sheet.unlink()
        print("built", option["slug"])
        contrast_report(option)


if __name__ == "__main__":
    main()
