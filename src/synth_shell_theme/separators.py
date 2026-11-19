"""Curated Powerline separator presets (48 styles) and 60+ Nerd Font character palette."""

from __future__ import annotations

import re

CATEGORIES: dict[str, list[tuple[str, str, str, str]]] = {
    "Powerline Solid (Hard Dividers)": [
        ("arrow", "\ue0b0", "\\uE0B0", "Classic Triangle Arrow (Powerline iconic)"),
        ("round", "\ue0b4", "\\uE0B4", "Rounded Bubble / Capsule (Modern pill)"),
        ("slant", "\ue0bc", "\\uE0BC", "Angled Slant Lower (Forward diagonal cut)"),
        ("slant-up", "\ue0be", "\\uE0BE", "Angled Slant Upper (Reverse diagonal cut)"),
        ("flame", "\ue0c0", "\\uE0C0", "Flame / Fire Spikes (Energetic serrated edge)"),
        ("pixel", "\ue0c4", "\\uE0C4", "8-Bit Stepped Pixel / Lego (Retro arcade)"),
        ("wave", "\ue0ca", "\\uE0CA", "Sine Wave / S-Curve (Fluid organic flow)"),
        ("hex", "\ue0cc", "\\uE0CC", "Hexagon / Honeycomb (Sci-fi cyber HUD)"),
        ("ice", "\ue0c8", "\\uE0C8", "Ice / Trapezoid Notch (Crystalline cut)"),
        ("sharp-slant", "\ue0d4", "\\uE0D4", "Sharp Slant Right (Crisp angular blade)"),
        ("trapezoid", "\ue0d2", "\\uE0D2", "Big Trapezoid Right (Bold wedge cut)"),
    ],
    "Powerline Thin (Soft Dividers)": [
        ("thin-arrow", "\ue0b1", "\\uE0B1", "Thin Outline Triangle (Minimalist soft divider)"),
        ("thin-round", "\ue0b5", "\\uE0B5", "Thin Outline Bubble (Subtle rounded pill)"),
        ("thin-flame", "\ue0c1", "\\uE0C1", "Thin Outline Flame (Delicate spike wireframe)"),
        ("thin-hex", "\ue0cd", "\\uE0CD", "Thin Outline Hexagon (Wireframe cyber mesh)"),
    ],
    "Geometric & Minimalist": [
        ("slash", "\u2571", "\\u2571", "Diagonal Line Slash (Architectural clean cut)"),
        ("backslash", "\u2572", "\\u2572", "Backslash Line Slash (Reverse angle cut)"),
        ("bar", "\u2502", "\\u2502", "Light Vertical Bar / Pipe (Nordic subtle separator)"),
        ("heavy-bar", "\u2503", "\\u2503", "Heavy Vertical Bar (Bold column divider)"),
        ("half-block", "\u258c", "\\u258C", "Left Half Solid Block (Staccato block divider)"),
        ("diamond", "\u25c6", "\\u25C6", "Solid Diamond (Geometric accent)"),
        ("bullet", "\u25cf", "\\u25CF", "Solid Bullet Circle (Centered dot spacer)"),
    ],
    "Chevrons & Terminal Arrows": [
        ("chevron", "\u00bb", "\\u00BB", "Double Angle Chevron (Fast-forward prompt)"),
        ("single-chevron", "\u203a", "\\u203A", "Single Angle Chevron (Compact breadcrumb)"),
        ("arrow-right", "\u2192", "\\u2192", "Clean Thin Right Arrow (Modern minimal pointer)"),
        ("heavy-arrow", "\u27a4", "\\u27A4", "Black Rightwards Arrowhead (Bold navigation dart)"),
        ("octicon-chevron", "\uf460", "\\uF460", "Octicon Chevron Right (GitHub Octicon glyph)"),
        ("fa-angle", "\uf105", "\\uF105", "FontAwesome Angle Right (UI breadcrumb angle)"),
    ],
    "Nerd Font Glyphs & Emblems": [
        ("star", "\u2605", "\\u2605", "Solid Star (Clean celestial emblem)"),
        ("rocket", "\uf135", "\\uF135", "FontAwesome Rocket (Fast launch emblem)"),
        ("lock", "\uf023", "\\uF023", "FontAwesome Lock (Security / prod context)"),
        ("git", "\ue725", "\\uE725", "Git Branch Icon"),
        ("terminal", "\ue271", "\\uE271", "Terminal Command Icon"),
    ],
    "Electricity, Sparks & High Voltage": [
        ("zap", "\u26a1", "\\u26A1", "Classic Zap Bolt (High-voltage electric energy)"),
        ("lightning", "\uf0e7", "\\uF0E7", "FontAwesome Solid Lightning Bolt"),
        ("thunder", "\u21af", "\\u21AF", "Zigzag Downward Thunder Discharge"),
        ("flash", "\U000f140b", "\\U000F140B", "Material Modern Sharp Lightning"),
        ("flash-wire", "\U000f140c", "\\U000F140C", "Material Wireframe Lightning"),
        ("sparkle", "\u2726", "\\u2726", "Four-Point Diamond Energy Sparkle"),
        ("starburst", "\u2727", "\\u2727", "Four-Point Hollow Starburst Flare"),
        ("burst", "\u2739", "\\u2739", "Twelve-Point Starburst Plasma Flare"),
        ("flare", "\u2738", "\\u2738", "Eight-Point Flare Explosion"),
        ("sparkles", "\u2728", "\\u2728", "Magic Twinkling Energy Sparks"),
        ("octo-flame", "\uf490", "\\uF490", "GitHub Octicon Energetic Fire Flame"),
        ("plasma-fire", "\U000f0238", "\\U000F0238", "Curved Hot Plasma Flame"),
        ("overdrive", "\U000f04c5", "\\U000F04C5", "Tachometer Needle in Red / Overdrive"),
        ("wave-pulse", "\u219d", "\\u219D", "Waveform Oscillator Energy Arrow"),
        ("squiggle", "\u21dd", "\\u21DD", "Pulse Wave Kinetic Squiggle Arrow"),
    ],
}

ALL_PRESETS: list[tuple[str, str, str, str]] = [
    item for items in CATEGORIES.values() for item in items
]

CHARACTER_PALETTE: dict[str, list[tuple[str, str, str]]] = {
    "Powerline & Dividers": [
        ("\ue0b0", "E0B0", "Triangle"),
        ("\ue0b1", "E0B1", "Thin Tri"),
        ("\ue0b4", "E0B4", "Bubble"),
        ("\ue0b5", "E0B5", "Thin Bub"),
        ("\ue0bc", "E0BC", "Slant Lo"),
        ("\ue0be", "E0BE", "Slant Up"),
        ("\ue0c0", "E0C0", "Flame"),
        ("\ue0c1", "E0C1", "Thin Flam"),
        ("\ue0c4", "E0C4", "Pixel"),
        ("\ue0c6", "E0C6", "Sm Pixel"),
        ("\ue0ca", "E0CA", "Wave"),
        ("\ue0cc", "E0CC", "Hexagon"),
        ("\ue0c8", "E0C8", "Ice Notch"),
        ("\ue0cd", "E0CD", "Thin Hex"),
        ("\ue0d4", "E0D4", "Sharp Slnt"),
        ("\ue0d2", "E0D2", "Trapezoid"),
    ],
    "Chevrons, Pointers & Arrows": [
        ("\u00bb", "00BB", "Dbl Chevr"),
        ("\u203a", "203A", "Sgl Chevr"),
        ("\u2192", "2192", "Thin Arrow"),
        ("\u279c", "279C", "Hvy Arrow"),
        ("\u27a4", "27A4", "Arrowhead"),
        ("\u25b6", "25B6", "Play Tri"),
        ("\u25b8", "25B8", "Sm Tri"),
        ("\u25ba", "25BA", "Point Tri"),
        ("\uf105", "F105", "FA Angle"),
        ("\uf054", "F054", "FA Chevr"),
        ("\uf061", "F061", "FA Arrow"),
        ("\uf0da", "F0DA", "FA Caret"),
        ("\uf460", "F460", "Oct Chevr"),
        ("\uf432", "F432", "Oct Tri"),
        ("\u00ab", "00AB", "Left Chevr"),
        ("\u25c0", "25C0", "Left Tri"),
    ],
    "Geometric & Block Dividers": [
        ("\u2571", "2571", "Diag Slash"),
        ("\u2572", "2572", "Backslash"),
        ("\u2502", "2502", "Vert Bar"),
        ("\u2503", "2503", "Heavy Bar"),
        ("\u258c", "258C", "Half Block"),
        ("\u2590", "2590", "R HalfBlk"),
        ("\u2588", "2588", "Full Block"),
        ("\u2591", "2591", "Light Shade"),
        ("\u25c6", "25C6", "Diamond"),
        ("\u25c7", "25C7", "White Diam"),
        ("\u25cf", "25CF", "Circle"),
        ("\u25cb", "25CB", "White Circ"),
    ],
    "Electricity, Sparks & Kinetic": [
        ("\u26a1", "26A1", "Zap Bolt"),
        ("\uf0e7", "F0E7", "FA Bolt"),
        ("\u21af", "21AF", "Thunder"),
        ("\U000f140b", "F140B", "MDI Flash"),
        ("\U000f140c", "F140C", "Wire Flash"),
        ("\u2726", "2726", "Sparkle"),
        ("\u2727", "2727", "Hollow Spark"),
        ("\u2728", "2728", "Sparkles"),
        ("\u2739", "2739", "12-Pt Burst"),
        ("\u2738", "2738", "8-Pt Flare"),
        ("\u2735", "2735", "Pinwheel"),
        ("\uf490", "F490", "Octo Flame"),
        ("\U000f0238", "F0238", "Plasma Fire"),
        ("\U000f04c5", "F04C5", "Overdrive"),
        ("\u219d", "219D", "Wave Zap"),
        ("\u21dd", "21DD", "Squiggle"),
    ],
    "Nerd Font Emblems & Icons": [
        ("\u2605", "2605", "Star"),
        ("\uf135", "F135", "Rocket"),
        ("\uf023", "F023", "Lock"),
        ("\ue725", "E725", "Git Branch"),
        ("\uf418", "F418", "Oct Branch"),
        ("\uf308", "F308", "Docker"),
        ("\U000f00fe", "F00FE", "Kubernetes"),
        ("\U000f0062", "F0062", "Terraform"),
        ("\ue271", "E271", "Terminal"),
        ("\u2665", "2665", "Heart"),
        ("\u2714", "2714", "Checkmark"),
        ("\uf017", "F017", "Clock"),
    ],
}


def glyph_to_code(glyph: str) -> str:
    """Encode a Unicode character into a Bash/printf-compatible escape (`\\uXXXX` or `\\UXXXXXXXX`)."""
    if not glyph:
        return "\\uE0B0"
    if len(glyph) == 1:
        cp = ord(glyph)
        if cp > 0xFFFF:
            return f"\\U{cp:08X}"
        if cp > 127:
            return f"\\u{cp:04X}"
        return glyph
    return glyph


def parse_separator_value(raw_val: str) -> tuple[str, str]:
    """Parse a separator value from `synth-shell-prompt.config` into `(glyph, code_str)`."""
    s = raw_val.strip()
    if s.startswith("$'") and s.endswith("'"):
        s = s[2:-1]
    elif (s.startswith('"') and s.endswith('"')) or (s.startswith("'") and s.endswith("'")):
        s = s[1:-1]
    s = s.strip()

    m_hex = re.match(r"^\\([uU])([0-9a-fA-F]{4,8})$", s)
    if m_hex:
        try:
            cp = int(m_hex.group(2), 16)
            glyph = chr(cp)
            code = f"\\U{cp:08X}" if cp > 0xFFFF else f"\\u{cp:04X}"
            return glyph, code
        except ValueError:
            pass

    if len(s) == 1:
        return s, glyph_to_code(s)
    return s, s


def parse_custom_char(input_str: str) -> tuple[str, str]:
    """Parse user input (`E0B4`, `\\uE0B4`, `U+E0B4`, `0xE0B4`, or literal glyph) into `(glyph, code_str)`."""
    s = input_str.strip().strip('"').strip("'")
    hex_match = re.match(r"^(?:\\u|\\U|u\+|0x)?([0-9a-fA-F]{4,8})$", s, re.IGNORECASE)
    if hex_match:
        cp = int(hex_match.group(1), 16)
        if 0 < cp <= 0x10FFFF:
            glyph = chr(cp)
            code = f"\\U{cp:08X}" if cp > 0xFFFF else f"\\u{cp:04X}"
            return glyph, code
    if len(s) == 1:
        return s, glyph_to_code(s)
    return s, s


def find_preset(query: str | int) -> tuple[str, str, str, str] | None:
    """Find a curated preset separator by 1-based index, key slug, or glyph."""
    q = str(query).strip().lower()
    if not q:
        return None
    if q.isdigit():
        idx = int(q)
        if 1 <= idx <= len(ALL_PRESETS):
            return ALL_PRESETS[idx - 1]
        return None
    for key, glyph, code, desc in ALL_PRESETS:
        if q in (key, key.replace("-", ""), glyph.lower(), desc.lower()):
            return key, glyph, code, desc
    for key, glyph, code, desc in ALL_PRESETS:
        if q in key or q in desc.lower():
            return key, glyph, code, desc
    return None


def find_palette_char(query: str) -> tuple[str, str, str] | None:
    """Find a character in the 60+ glyph palette by hex code, short label, or glyph."""
    q = query.strip().lower()
    if not q:
        return None
    for items in CHARACTER_PALETTE.values():
        for glyph, hex_code, desc in items:
            code = f"\\U{int(hex_code, 16):08X}" if len(hex_code) > 4 else f"\\u{hex_code.upper()}"
            if q in (
                glyph.lower(),
                hex_code.lower(),
                desc.lower(),
                desc.lower().replace(" ", ""),
                code.lower(),
                f"u+{hex_code.lower()}",
                f"0x{hex_code.lower()}",
            ):
                return glyph, code, desc
    return None


def get_separator_key(glyph: str) -> str:
    """Return the preset key matching `glyph`, or `'custom'`."""
    for key, g, _, _ in ALL_PRESETS:
        if g == glyph:
            return key
    return "custom"


def resolve_separator_input(user_input: str) -> tuple[str, str, str]:
    """Resolve any preset index/name, palette label, hex code, or literal glyph into `(glyph, code_str, label)`."""
    preset = find_preset(user_input)
    if preset:
        return preset[1], preset[2], f"{preset[0]} ({preset[3]})"
    pal = find_palette_char(user_input)
    if pal:
        return pal[0], pal[1], pal[2]
    glyph, code = parse_custom_char(user_input)
    return glyph, code, "Custom"


def format_separator_assignment(var_name: str, code_str: str) -> str:
    """Format a safe Bash config line (`separator_char="\\uE0B4"`)."""
    if re.match(r"^\\[uU][0-9A-Fa-f]{4,8}$", code_str):
        return f'{var_name}="{code_str}"'
    escaped = code_str.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$").replace("`", "\\`")
    return f'{var_name}="{escaped}"'


def serialize_separators_for_web() -> dict[str, object]:
    """Serialize all separator presets and palette glyphs for Web Studio."""
    categories_out: list[dict[str, object]] = []
    idx_counter = 1
    for cat_name, items in CATEGORIES.items():
        cat_items = []
        for key, glyph, code, desc in items:
            cat_items.append(
                {
                    "id": idx_counter,
                    "key": key,
                    "glyph": glyph,
                    "code": code,
                    "description": desc,
                }
            )
            idx_counter += 1
        categories_out.append({"name": cat_name, "items": cat_items})

    palette_out = [
        {
            "group": group_name,
            "items": [
                {
                    "glyph": glyph,
                    "hex": hex_code,
                    "code": f"\\U{int(hex_code, 16):08X}" if len(hex_code) > 4 else f"\\u{hex_code.upper()}",
                    "label": label,
                }
                for glyph, hex_code, label in items
            ],
        }
        for group_name, items in CHARACTER_PALETTE.items()
    ]

    return {
        "total_presets": len(ALL_PRESETS),
        "categories": categories_out,
        "palette": palette_out,
    }
