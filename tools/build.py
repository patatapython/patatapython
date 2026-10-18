"""Build the profile README and its images from tools/profile.toml.

Usage: python3 tools/build.py

Writes README.md and assets/*.svg. Needs Pillow to crop the screenshots in media/. Every image has a light and a dark version,
served with <picture> so it follows the theme the visitor uses on GitHub.

GitHub renders README images through its image proxy: no external fonts, no
scripts. So the SVGs use the system font stack and plain CSS animations, and
the text is wrapped by hand in profile.toml. This script refuses to write
anything if a line would overflow its card, or if a text breaks one of the
profile's content rules.
"""

from __future__ import annotations

import base64
import io
import re
import sys
import tomllib
from html import escape
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
MONO = "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace"

# Colours follow GitHub's own light and dark palettes so the images sit flush.
THEMES = {
    "light": {
        "canvas": "#ffffff", "card": "#f6f8fa", "border": "#d0d7de", "text": "#1f2328",
        "muted": "#59636e", "grid": "#eaeef2", "belt": "#8c959f", "accent": "#bc4c00",
        "production": "#1a7f37", "pilot": "#9a6700", "thesis": "#0969da", "opensource": "#8250df",
    },
    "dark": {
        "canvas": "#0d1117", "card": "#161b22", "border": "#30363d", "text": "#e6edf3",
        "muted": "#9198a1", "grid": "#161b22", "belt": "#6e7681", "accent": "#f0883e",
        "production": "#3fb950", "pilot": "#d29922", "thesis": "#58a6ff", "opensource": "#bc8cff",
    },
}

# Content rules of the profile (same as LinkedIn and Manfred).
FORBIDDEN = ["OCR", "Generative AI", "YOLOv11", "paying customers", "three months of",
             "faces", "load test", "www.oxalis", "Realtime", "real-time sync", "€", "—"]
FORBIDDEN_PATTERNS = [r"\b\d+\+?\s*tests\b", r"\bcoverage\b", r"\bpayments?\b"]
FORBIDDEN_IN = {"pollo": ["real-time", "Supabase"]}

IMG_W, IMG_H = 420, 190
CARD_W, CARD_H = 420, 214 + IMG_H
CARD_PAD = 14  # transparent margin inside the image: GitHub strips CSS, so the gap lives here
MAX_BODY_CHARS = 54   # 13px sans in a 380px text column
MAX_TITLE_CHARS = 32
MAX_STACK_CHARS = 54


def check_text(where: str, text: str, card_id: str | None = None) -> list[str]:
    errors = [f"{where}: forbidden '{w}'" for w in FORBIDDEN if w.lower() in text.lower()]
    errors += [f"{where}: forbidden pattern {p}" for p in FORBIDDEN_PATTERNS
               if re.search(p, text, re.IGNORECASE)]
    for w in FORBIDDEN_IN.get(card_id or "", []):
        if w.lower() in text.lower():
            errors.append(f"{where}: forbidden for this project '{w}'")
    return errors


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    person = data["person"]
    for key in ("name", "role", "tagline", "private_note"):
        errors += check_text(f"person.{key}", person[key])
    for i, para in enumerate(person["intro"] + person["how_i_work"]):
        errors += check_text(f"person text {i}", para)
    for section in data["section"]:
        errors += check_text(f"section {section['title']}", section.get("footer", ""))
        for card in section["card"]:
            cid = card["id"]
            if not card.get("shot") or not (ROOT / card["shot"]).is_file():
                errors.append(f"{cid}: screenshot missing ({card.get('shot')})")
            if card["kind"] not in THEMES["light"]:
                errors.append(f"{cid}: unknown kind {card['kind']}")
            if len(card["title"]) > MAX_TITLE_CHARS:
                errors.append(f"{cid}: title longer than {MAX_TITLE_CHARS} chars")
            if len(card["body"]) > 4:
                errors.append(f"{cid}: more than 4 body lines")
            for n, line in enumerate(card["body"], 1):
                if len(line) > MAX_BODY_CHARS:
                    errors.append(f"{cid}: body line {n} has {len(line)} chars (max {MAX_BODY_CHARS})")
            if len(card["stack"]) > MAX_STACK_CHARS:
                errors.append(f"{cid}: stack line longer than {MAX_STACK_CHARS} chars")
            whole = " ".join([card["label"], card["title"], *card["body"], card["stack"]])
            errors += check_text(cid, whole, cid)
    return errors


def t(x: float, y: float, text: str, size: int, fill: str, weight: int = 400,
      family: str = FONT, extra: str = "") -> str:
    return (f'<text x="{x}" y="{y}" font-family="{family}" font-size="{size}" '
            f'font-weight="{weight}" fill="{fill}" {extra}>{escape(text)}</text>')


def header_svg(person: dict, c: dict) -> str:
    """Name over a production line: boxes go through a gate and come out as nodes."""
    w, h = 1200, 270
    belt_y = 232
    gate_x = 820
    items, statics = [], []
    n, dur = 7, 14.0
    travel = w + 160
    gate_pct = (gate_x + 8 + 80) / travel * 100  # where an item centre crosses the gate
    for i in range(n):
        delay = -dur * i / n
        items.append(
            f'<g class="item" style="animation-delay:{delay:.2f}s">'
            f'<rect class="box" x="-22" y="{belt_y - 30}" width="28" height="22" rx="3" '
            f'fill="none" stroke="{c["belt"]}" stroke-width="2"/>'
            f'<line class="box" x1="-22" y1="{belt_y - 19}" x2="6" y2="{belt_y - 19}" '
            f'stroke="{c["belt"]}" stroke-width="1.5"/>'
            f'<circle class="node" cx="-8" cy="{belt_y - 19}" r="9" fill="{c["accent"]}" fill-opacity="0.18" '
            f'stroke="{c["accent"]}" stroke-width="2"/>'
            f'<circle class="node" cx="-8" cy="{belt_y - 19}" r="3" fill="{c["accent"]}"/>'
            f'</g>')
        sx = 90 + i * 160
        shape = (f'<rect x="{sx}" y="{belt_y - 30}" width="28" height="22" rx="3" fill="none" '
                 f'stroke="{c["belt"]}" stroke-width="2"/>' if sx + 14 < gate_x else
                 f'<circle cx="{sx + 14}" cy="{belt_y - 19}" r="9" fill="{c["accent"]}" '
                 f'fill-opacity="0.18" stroke="{c["accent"]}" stroke-width="2"/>')
        statics.append(shape)
    rollers = "".join(
        f'<circle cx="{x}" cy="{belt_y + 6}" r="4" fill="none" stroke="{c["belt"]}" stroke-width="1.5"/>'
        for x in range(30, w, 60))
    grid = "".join(f'<line x1="{x}" y1="0" x2="{x}" y2="{h}" stroke="{c["grid"]}" stroke-width="1"/>'
                   for x in range(0, w + 1, 40))
    grid += "".join(f'<line x1="0" y1="{y}" x2="{w}" y2="{y}" stroke="{c["grid"]}" stroke-width="1"/>'
                    for y in range(0, h + 1, 40))
    gate = (f'<rect x="{gate_x - 28}" y="{belt_y - 74}" width="56" height="76" rx="6" '
            f'fill="{c["accent"]}" fill-opacity="0.07"/>'
            f'<path d="M{gate_x - 28} {belt_y + 2} V{belt_y - 62} Q{gate_x - 28} {belt_y - 74} {gate_x - 16} {belt_y - 74} '
            f'H{gate_x + 16} Q{gate_x + 28} {belt_y - 74} {gate_x + 28} {belt_y - 62} V{belt_y + 2}" '
            f'fill="none" stroke="{c["accent"]}" stroke-width="3" stroke-linecap="round"/>'
            f'<line class="scan" x1="{gate_x - 22}" y1="{belt_y - 64}" x2="{gate_x + 22}" '
            f'y2="{belt_y - 64}" stroke="{c["accent"]}" stroke-width="2.5" stroke-linecap="round"/>'
            f'<circle cx="{gate_x}" cy="{belt_y - 84}" r="3.5" fill="{c["accent"]}"/>')
    style = f"""
    .item {{ animation: run {dur}s linear infinite; }}
    .item .box {{ animation: box {dur}s linear infinite; animation-delay: inherit; }}
    .item .node {{ animation: node {dur}s linear infinite; animation-delay: inherit; }}
    .scan {{ animation: scan 1.6s ease-in-out infinite alternate; }}
    .static {{ display: none; }}
    @keyframes run {{ from {{ transform: translateX(-80px); }} to {{ transform: translateX({w + 80}px); }} }}
    @keyframes box {{ 0%, {gate_pct - 0.5:.1f}% {{ opacity: 1; }} {gate_pct:.1f}%, 100% {{ opacity: 0; }} }}
    @keyframes node {{ 0%, {gate_pct - 0.5:.1f}% {{ opacity: 0; }} {gate_pct:.1f}%, 100% {{ opacity: 1; }} }}
    @keyframes scan {{ from {{ transform: translateY(0); }} to {{ transform: translateY(52px); }} }}
    @media (prefers-reduced-motion: reduce) {{
      .item, .scan {{ animation: none; display: none; }}
      .static {{ display: inline; }}
    }}"""
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{escape(person['name'])}, {escape(person['role'])}">
  <title>{escape(person['name'])}: {escape(person['role'])}</title>
  <style>{style}
  </style>
  <rect width="{w}" height="{h}" fill="{c['canvas']}"/>
  {grid}
  {t(60, 92, person['name'], 52, c['text'], 700)}
  {t(62, 136, person['role'], 26, c['accent'], 600)}
  {t(62, 172, person['tagline'], 18, c['muted'])}
  <line x1="0" y1="{belt_y}" x2="{w}" y2="{belt_y}" stroke="{c['belt']}" stroke-width="2.5"/>
  <line x1="0" y1="{belt_y + 12}" x2="{w}" y2="{belt_y + 12}" stroke="{c['belt']}" stroke-width="1" stroke-opacity="0.5"/>
  {rollers}
  {"".join(items)}
  <g class="static">{"".join(statics)}</g>
  {gate}
</svg>
"""


def shot_data_uri(card: dict) -> str:
    """Crop the card's screenshot to the image band and return it as a JPEG data URI.

    GitHub shows README images through a proxy that blocks anything an SVG tries to
    load, so the screenshot has to travel inside the SVG. Rendered at 2x for sharp
    text on high-density screens.
    """
    from PIL import Image  # only the build needs Pillow, the README does not

    tw, th = IMG_W * 2, IMG_H * 2
    img = Image.open(ROOT / card["shot"]).convert("RGB")
    w, h = img.size
    if card.get("fit") == "contain":
        bg = Image.new("RGB", (tw, th), img.getpixel((2, 2)))
        img.thumbnail((tw, th), Image.LANCZOS)
        bg.paste(img, ((tw - img.width) // 2, (th - img.height) // 2))
        img = bg
    else:
        aspect = tw / th
        zoom = card.get("zoom", 1.0)
        cw = min(w, h * aspect) / zoom
        ch = cw / aspect
        fx, fy = card.get("focus", [0.5, 0.5])
        left = min(max(fx * w - cw / 2, 0), w - cw)
        top = min(max(fy * h - ch / 2, 0), h - ch)
        img = img.crop((round(left), round(top), round(left + cw), round(top + ch)))
        img = img.resize((tw, th), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=84, optimize=True, progressive=True)
    return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def card_svg(card: dict, c: dict, shot: str) -> str:
    kind = c[card["kind"]]
    y0 = IMG_H  # everything below the screenshot band
    lines = "".join(t(22, y0 + 100 + 19 * i, line, 13, c["muted"]) for i, line in enumerate(card["body"]))
    arrow = t(CARD_W - 34, y0 + 36, "↗", 18, c["muted"]) if card.get("url") else ""
    label_w = 16 + 7.1 * len(card["label"])
    pw, ph = CARD_W + 2 * CARD_PAD, CARD_H + 2 * CARD_PAD
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {pw} {ph}" width="{pw}" height="{ph}" role="img" aria-label="{escape(card['title'])}">
  <title>{escape(card['title'])}</title>
  <g transform="translate({CARD_PAD} {CARD_PAD})">
  <defs><clipPath id="top"><path d="M1 {IMG_H} V11 Q1 1 11 1 H{CARD_W - 11} Q{CARD_W - 1} 1 {CARD_W - 1} 11 V{IMG_H} Z"/></clipPath></defs>
  <rect x="1" y="1" width="{CARD_W - 2}" height="{CARD_H - 2}" rx="10" fill="{c['card']}" stroke="{c['border']}" stroke-width="1.5"/>
  <image href="{shot}" x="1" y="1" width="{CARD_W - 2}" height="{IMG_H - 1}" preserveAspectRatio="xMidYMid slice" clip-path="url(#top)"/>
  <rect x="1" y="{IMG_H - 2}" width="{CARD_W - 2}" height="4" fill="{kind}"/>
  <rect x="20" y="{y0 + 18}" width="{label_w:.0f}" height="22" rx="11" fill="{kind}" fill-opacity="0.14"/>
  {t(27, y0 + 33, card['label'], 11, kind, 600, MONO, 'letter-spacing="0.4"')}
  {arrow}
  {t(22, y0 + 74, card['title'], 20, c['text'], 700)}
  {lines}
  <line x1="22" y1="{CARD_H - 40}" x2="{CARD_W - 22}" y2="{CARD_H - 40}" stroke="{c['border']}" stroke-width="1"/>
  {t(22, CARD_H - 16, card['stack'], 12, c['text'], 500, MONO)}
  </g>
</svg>
"""


def toolbox_svg(tools: list[str], c: dict) -> tuple[str, list[str]]:
    w, gap, chip_h, row_gap = 840, 10, 34, 12
    x, y, chips, errors = 0.0, 0.0, [], []
    for tool in tools:
        cw = 26 + 8.2 * len(tool)
        if x + cw > w:
            x, y = 0.0, y + chip_h + row_gap
        chips.append(
            f'<rect x="{x + 1:.0f}" y="{y + 1:.0f}" width="{cw:.0f}" height="{chip_h}" rx="17" '
            f'fill="{c["card"]}" stroke="{c["border"]}" stroke-width="1.5"/>'
            + t(x + 14, y + 23, tool, 14, c["text"], 500, MONO))
        x += cw + gap
    h = int(y + chip_h + 3)
    if h > 3 * (chip_h + row_gap):
        errors.append("toolbox: more than three rows")
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w + 2} {h}" width="{w + 2}" '
           f'height="{h}" role="img" aria-label="Toolbox: {escape(", ".join(tools))}">'
           f'<title>Toolbox</title>{"".join(chips)}</svg>\n')
    return svg, errors


def picture(name: str, alt: str, width: int, url: str | None = None) -> str:
    img = (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">'
           f'<img src="assets/{name}-light.svg" alt="{escape(alt)}" width="{width}"></picture>')
    return f'<a href="{url}">{img}</a>' if url else img


def card_alt(card: dict) -> str:
    return f"{card['title']} ({card['label'].lower()}): {' '.join(card['body'])} Stack: {card['stack']}."


def readme(data: dict) -> str:
    p = data["person"]
    out = [
        "<!-- Generated by tools/build.py from tools/profile.toml. Edit those, not this file. -->",
        "",
        '<p align="center">',
        picture("header", f"{p['name']}, {p['role']}. {p['tagline']}", 1200),
        "</p>",
        "",
        *[f"{para}\n" for para in p["intro"]],
    ]
    for section in data["section"]:
        out += [f"### {section['title']}", "", '<p align="center">']
        out += [picture(f"card-{card['id']}", card_alt(card), 400, card.get("url"))
                for card in section["card"]]
        out += ["</p>", ""]
        if section.get("footer"):
            out += [section["footer"], ""]
    out += ["### How I work", "", *[f"- {item}" for item in p["how_i_work"]], ""]
    out += ["### Toolbox", "", '<p align="center">',
            picture("toolbox", "Toolbox: " + ", ".join(p["toolbox"]), 842), "</p>", ""]
    out += ["### About what you can't see here", "", p["private_note"], ""]
    out += ["---", "",
            f'<p align="center"><a href="{p["linkedin"]}">LinkedIn</a> · '
            f'<a href="{p["website"]}">epitrixconsulting.com</a></p>', ""]
    return "\n".join(out)


def main() -> int:
    data = tomllib.loads((ROOT / "tools" / "profile.toml").read_text(encoding="utf-8"))
    errors = validate(data)
    outputs: dict[Path, str] = {}
    if errors:
        print("Nothing written:", *sorted(set(errors)), sep="\n  ", file=sys.stderr)
        return 1
    shots = {card["id"]: shot_data_uri(card) for section in data["section"] for card in section["card"]}
    for theme, colours in THEMES.items():
        outputs[ASSETS / f"header-{theme}.svg"] = header_svg(data["person"], colours)
        for section in data["section"]:
            for card in section["card"]:
                outputs[ASSETS / f"card-{card['id']}-{theme}.svg"] = card_svg(card, colours, shots[card["id"]])
        svg, tb_errors = toolbox_svg(data["person"]["toolbox"], colours)
        outputs[ASSETS / f"toolbox-{theme}.svg"] = svg
        errors += tb_errors
    if errors:
        print("Nothing written:", *sorted(set(errors)), sep="\n  ", file=sys.stderr)
        return 1
    ASSETS.mkdir(exist_ok=True)
    for path in ASSETS.glob("*.svg"):
        if path not in outputs:
            path.unlink()
    for path, content in outputs.items():
        path.write_text(content, encoding="utf-8")
    (ROOT / "README.md").write_text(readme(data), encoding="utf-8")
    print(f"Wrote README.md and {len(outputs)} images.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
