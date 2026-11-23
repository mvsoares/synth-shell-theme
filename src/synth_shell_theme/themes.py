"""Theme catalog, 256-color/RGB palette math, and ANSI terminal rendering for synth-shell-theme."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

from synth_shell_theme.paths import get_themes_dir, get_user_themes_dir

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"

NAMED_COLORS: dict[str, int] = {
    "black": 0,
    "red": 1,
    "green": 2,
    "yellow": 3,
    "blue": 4,
    "purple": 5,
    "magenta": 5,
    "pink": 5,
    "cyan": 6,
    "light-gray": 7,
    "dark-gray": 8,
    "light-red": 9,
    "light-green": 10,
    "light-yellow": 11,
    "light-blue": 12,
    "light-purple": 13,
    "light-magenta": 13,
    "light-cyan": 14,
    "white": 15,
}

# Crisp dark-terminal 16 ANSI base colors matching xterm / modern terminal emulators
ANSI_16_HEX: tuple[str, ...] = (
    "#000000",  # 0 black
    "#cc3333",  # 1 red
    "#2eb85c",  # 2 green
    "#d9a300",  # 3 yellow
    "#3377dd",  # 4 blue
    "#9944cc",  # 5 purple
    "#1fb2c2",  # 6 cyan
    "#d0d0d0",  # 7 light-gray
    "#585858",  # 8 dark-gray
    "#ff5f5f",  # 9 light-red
    "#5fd787",  # 10 light-green
    "#ffd75f",  # 11 light-yellow
    "#5fafff",  # 12 light-blue
    "#d787ff",  # 13 light-purple
    "#5fffff",  # 14 light-cyan
    "#ffffff",  # 15 white
)

_CUBE_STEPS: tuple[int, ...] = (0, 95, 135, 175, 215, 255)
_ANSI_RE = re.compile(r"\033\[[0-9;]*m")

SEGMENT_KEYS: tuple[str, ...] = (
    "user",
    "host",
    "pwd",
    "git",
    "pyenv",
    "tf",
    "kube",
    "clock",
    "status",
    "duration",
    "aws",
    "gcp",
    "docker",
    "node",
    "ssh",
    "jobs",
    "direnv",
    "shlvl",
    "rust",
    "go",
    "input",
)

DEFAULT_SEGMENT_COLORS: dict[str, tuple[str, str]] = {
    "user": ("white", "blue"),
    "host": ("white", "237"),
    "pwd": ("black", "255"),
    "git": ("black", "71"),
    "pyenv": ("white", "63"),
    "tf": ("black", "228"),
    "kube": ("black", "135"),
    "clock": ("white", "240"),
    "status": ("white", "196"),
    "duration": ("black", "220"),
    "aws": ("black", "208"),
    "gcp": ("white", "33"),
    "docker": ("white", "39"),
    "node": ("black", "76"),
    "ssh": ("white", "125"),
    "jobs": ("black", "214"),
    "direnv": ("black", "114"),
    "shlvl": ("white", "99"),
    "rust": ("white", "166"),
    "go": ("black", "81"),
    "input": ("white", "none"),
}

_HEX_COLOR_RE = re.compile(r"^#([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


def normalize_hex_color(token: str | int | None) -> str | None:
    """Return normalized `#rrggbb` lowercase hex string if `token` is a hex color, else None."""
    if not isinstance(token, str):
        return None
    clean = token.strip().strip('"').strip("'")
    m = _HEX_COLOR_RE.match(clean)
    if not m:
        return None
    raw = m.group(1).lower()
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    return f"#{raw}"


def hex_to_nearest_256(hex_color: str) -> int:
    """Map a `#rrggbb` TrueColor hex string to the nearest xterm-256 index (16..255)."""
    norm = normalize_hex_color(hex_color)
    if not norm:
        return 15
    r = int(norm[1:3], 16)
    g = int(norm[3:5], 16)
    b = int(norm[5:7], 16)

    best_idx = 16
    best_dist = 10**9
    for idx in range(16, 256):
        hx = index_to_hex(idx)
        if not hx:
            continue
        cr = int(hx[1:3], 16)
        cg = int(hx[3:5], 16)
        cb = int(hx[5:7], 16)
        dist = (r - cr) ** 2 + (g - cg) ** 2 + (b - cb) ** 2
        if dist < best_dist:
            best_dist = dist
            best_idx = idx
    return best_idx


def color_index(token: str | int | None) -> int | None:
    """Resolve a synth-shell color token (0-255, named color, or #rrggbb) to an xterm-256 index."""
    if token is None:
        return None
    if isinstance(token, int):
        return token if 0 <= token <= 255 else None
    clean = str(token).strip().strip('"').strip("'").lower()
    if clean in ("none", "transparent", "default", ""):
        return None
    hx = normalize_hex_color(clean)
    if hx:
        return hex_to_nearest_256(hx)
    if clean in NAMED_COLORS:
        return NAMED_COLORS[clean]
    try:
        num = int(clean)
        if 0 <= num <= 255:
            return num
    except ValueError:
        pass
    return None


def index_to_hex(idx: int | None) -> str | None:
    """Convert an xterm-256 color index (0..255) into a `#rrggbb` CSS hex color."""
    if idx is None or not (0 <= idx <= 255):
        return None
    if idx < 16:
        return ANSI_16_HEX[idx]
    if idx < 232:
        offset = idx - 16
        r = _CUBE_STEPS[(offset // 36) % 6]
        g = _CUBE_STEPS[(offset // 6) % 6]
        b = _CUBE_STEPS[offset % 6]
        return f"#{r:02x}{g:02x}{b:02x}"
    gray = 8 + 10 * (idx - 232)
    return f"#{gray:02x}{gray:02x}{gray:02x}"


def token_to_hex(token: str | int | None, fallback: str | None = None) -> str | None:
    """Resolve any synth-shell color token (including #rrggbb TrueColor) directly to `#rrggbb`."""
    hx = normalize_hex_color(token)
    if hx:
        return hx
    idx = color_index(token)
    if idx is None:
        return fallback
    return index_to_hex(idx) or fallback


def ansi_fg(idx: int | None) -> str:
    """Return 256-color ANSI foreground escape sequence."""
    return f"\033[38;5;{idx}m" if idx is not None else ""


def ansi_bg(idx: int | None) -> str:
    """Return 256-color ANSI background escape sequence."""
    return f"\033[48;5;{idx}m" if idx is not None else ""


def visible_len(text: str) -> int:
    """Calculate printable display column width after stripping ANSI escape sequences."""
    plain = _ANSI_RE.sub("", text)
    width = 0
    for ch in plain:
        cat = unicodedata.east_asian_width(ch)
        width += 2 if cat in ("W", "F") else 1
    return width


def pad_to(text: str, width: int) -> str:
    """Pad `text` with trailing spaces to reach `width` visible columns."""
    diff = width - visible_len(text)
    return text + (" " * max(diff, 0))


def is_color_key(key: str) -> bool:
    """Return True if `key` is a prompt segment color variable (`font_color_*` or `background_*`)."""
    return (key.startswith("font_color_") or key.startswith("background_")) and not key.startswith("_")


def parse_theme(path: Path) -> dict[str, object]:
    """Parse a bundled or custom `.conf` theme file into a structured dictionary."""
    stem = path.stem
    m_id = re.match(r"^(\d+)[-_]?(.*)$", stem)
    theme_id = int(m_id.group(1)) if m_id else 0
    slug = (m_id.group(2) if m_id and m_id.group(2) else stem).lower()

    data: dict[str, object] = {
        "id": theme_id,
        "slug": slug,
        "name": slug.replace("-", " ").title(),
        "badge": "Theme",
        "description": "",
        "swatch256": [],
        "_name": "",
        "_path": path,
    }

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m_title = re.match(r"^#\s*Theme\s+\d+:\s*(.+)$", line)
        if m_title:
            title = m_title.group(1).strip()
            data["name"] = title
            data["_name"] = title
            continue
        m_swatch = re.match(r"^#\s*swatch256:\s*(.+)$", line)
        if m_swatch:
            swatches = [int(tok) for tok in m_swatch.group(1).split() if tok.isdigit()]
            data["swatch256"] = swatches
            continue
        m_badge = re.match(r"^#\s*badge:\s*(.+)$", line)
        if m_badge:
            data["badge"] = m_badge.group(1).strip()
            continue
        m_desc = re.match(r"^#\s*description:\s*(.+)$", line)
        if m_desc:
            data["description"] = m_desc.group(1).strip()
            continue
        if line.startswith("#"):
            continue
        m_kv = re.match(r"^(\w+)\s*=\s*\$?['\"]?([^'\"]*)['\"]?\s*$", line)
        if m_kv:
            data[m_kv.group(1)] = m_kv.group(2).strip()

    if not data["_name"]:
        data["_name"] = data["name"]
    return data


def load_themes(
    themes_dir: Path | None = None,
    include_user_themes: bool = True,
    config_dir: Path | None = None,
) -> list[dict[str, object]]:
    """Load all bundled `.conf` themes plus any user-created custom themes in `~/.config/synth-shell/themes/`."""
    directory = themes_dir if themes_dir is not None else get_themes_dir()
    if not directory.is_dir():
        raise FileNotFoundError(f"Themes directory not found: {directory}")
    files = sorted(directory.glob("*.conf"))
    if not files:
        raise FileNotFoundError(f"No .conf theme files found in: {directory}")
    themes = [parse_theme(f) for f in files]
    for idx, t in enumerate(themes, 1):
        t["custom"] = False
        if not t.get("id"):
            t["id"] = idx

    if include_user_themes and themes_dir is None:
        user_dir = get_user_themes_dir(config_dir)
        if user_dir.is_dir():
            for uf in sorted(user_dir.glob("*.conf")):
                ut = parse_theme(uf)
                ut["custom"] = True
                ut["id"] = len(themes) + 1
                themes.append(ut)

    return themes


def save_custom_theme(
    name: str,
    colors: dict[str, str],
    description: str = "",
    badge: str = "Custom",
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Save a custom theme (supporting 256-color and #RRGGBB TrueColor) into `~/.config/synth-shell/themes/`."""
    clean_name = name.strip()
    if not clean_name:
        raise ValueError("Theme name cannot be empty.")
    slug = re.sub(r"[^a-z0-9]+", "-", clean_name.lower()).strip("-") or "custom-theme"
    user_dir = get_user_themes_dir(config_dir)
    user_dir.mkdir(parents=True, exist_ok=True)
    dest = user_dir / f"{slug}.conf"

    h_idx = color_index(colors.get("background_host", "237")) or 237
    p_idx = color_index(colors.get("background_pwd", "255")) or 255
    g_idx = color_index(colors.get("background_git", "71")) or 71

    lines = [
        f"# Theme 0: {clean_name}",
        f"# swatch256: {h_idx} {p_idx} {g_idx}",
        f"# badge: {badge.strip() or 'Custom'}",
        f"# description: {description.strip() or 'Custom user theme created in Synth-Shell Theme Studio.'}",
        'format="HOST PWD GIT PYENV TF KUBE"',
        'separator_char="\\uE0B4"',
        'separator_char_end="\\uE0B0"',
        'enable_vertical_padding="true"',
        'enable_command_on_new_line="true"',
        "",
    ]
    for seg in SEGMENT_KEYS:
        def_fg, def_bg = DEFAULT_SEGMENT_COLORS[seg]
        fg_k = f"font_color_{seg}"
        bg_k = f"background_{seg}"
        fg_val = str(colors.get(fg_k, def_fg)).strip() or def_fg
        bg_val = str(colors.get(bg_k, def_bg)).strip() or def_bg
        if fg_k in colors or seg in ("host", "pwd", "git", "pyenv", "tf", "kube", "input"):
            lines.append(f'{fg_k}="{fg_val}"')
        if bg_k in colors or seg in ("host", "pwd", "git", "pyenv", "tf", "kube", "input"):
            lines.append(f'{bg_k}="{bg_val}"')

    dest.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    parsed = parse_theme(dest)
    parsed["custom"] = True
    return parsed


def find_theme(
    query: str | int,
    themes: list[dict[str, object]],
) -> tuple[dict[str, object] | None, int | None]:
    """Find a theme by 1-based index, slug, or name. Returns `(theme, 1-based-index)`."""
    if isinstance(query, int) or (isinstance(query, str) and query.strip().isdigit()):
        idx = int(str(query).strip())
        if 1 <= idx <= len(themes):
            return themes[idx - 1], idx
        return None, None

    q = str(query).strip().lower().replace("-", " ").replace("_", " ")
    if not q:
        return None, None

    # 1. Exact name match
    for i, t in enumerate(themes, 1):
        t_name = str(t.get("name", "")).lower().replace("-", " ").replace("_", " ")
        if t_name == q:
            return t, i

    # 2. Exact slug / stem match
    for i, t in enumerate(themes, 1):
        slug = str(t.get("slug", "")).lower().replace("-", " ").replace("_", " ")
        stem = Path(t["_path"]).stem.lower().replace("-", " ").replace("_", " ")  # type: ignore[arg-type]
        if q in (slug, stem):
            return t, i

    # 3. Unique substring match
    matches: list[tuple[dict[str, object], int]] = []
    raw_q = str(query).strip().lower()
    for i, t in enumerate(themes, 1):
        t_name = str(t.get("name", "")).lower()
        slug = str(t.get("slug", "")).lower()
        if raw_q in t_name or raw_q in slug or q in t_name.replace("-", " "):
            matches.append((t, i))
    if len(matches) == 1:
        return matches[0]

    return None, None


def filter_themes(
    query: str,
    themes: list[dict[str, object]],
    badge: str = "",
) -> list[tuple[int, dict[str, object]]]:
    """Return `(1-based-index, theme)` pairs matching `query` and optional `badge`."""
    q = query.strip().lower()
    b = badge.strip().lower()
    results: list[tuple[int, dict[str, object]]] = []
    for i, t in enumerate(themes, 1):
        if b and str(t.get("badge", "")).lower() != b:
            continue
        if not q:
            results.append((i, t))
            continue
        haystack = " ".join(
            [
                str(t.get("name", "")),
                str(t.get("slug", "")),
                str(t.get("badge", "")),
                str(t.get("description", "")),
                f"#{i:02d}",
            ]
        ).lower()
        if q in haystack:
            results.append((i, t))
    return results


def render_segment(text: str, fg: int | None, bg: int | None) -> str:
    """Render a single padded segment in 256-color ANSI."""
    parts: list[str] = []
    if bg is not None:
        parts.append(ansi_bg(bg))
    if fg is not None:
        parts.append(ansi_fg(fg))
    parts.append(BOLD)
    parts.append(f" {text} ")
    return "".join(parts)


def render_separator(prev_bg: int | None, next_bg: int | None, sep: str) -> str:
    """Render a Powerline transition glyph between `prev_bg` and `next_bg`."""
    parts: list[str] = []
    if prev_bg is not None:
        parts.append(ansi_fg(prev_bg))
    if next_bg is not None:
        parts.append(ansi_bg(next_bg))
    else:
        parts.append(RESET)
        if prev_bg is not None:
            parts.append(ansi_fg(prev_bg))
    parts.append(sep)
    return "".join(parts)


def render_prompt_line(
    theme: dict[str, object],
    segments: list[tuple[str, str]],
    command: str,
    sep: str = "\ue0b4",
    sep_end: str | None = "\ue0b0",
    force_white: bool = False,
) -> str:
    """Render a complete sample prompt line with dual separator and input command preview."""
    out: list[str] = []
    final_sep = sep_end if sep_end else sep
    for i, (key, text) in enumerate(segments):
        fg_token = "white" if force_white else str(theme.get(f"font_color_{key}", "white"))
        fg = color_index(fg_token)
        bg = color_index(str(theme.get(f"background_{key}", "0")))
        out.append(render_segment(text, fg, bg))
        if i + 1 < len(segments):
            next_key = segments[i + 1][0]
            next_bg = color_index(str(theme.get(f"background_{next_key}", "0")))
            out.append(render_separator(bg, next_bg, sep))
        else:
            out.append(render_separator(bg, None, final_sep))

    input_fg = color_index(str(theme.get("font_color_input", "white")))
    out.append(RESET)
    if input_fg is not None:
        out.append(ansi_fg(input_fg))
    out.append(BOLD)
    out.append(f" {command}")
    out.append(RESET)
    return "".join(out)


def build_card_lines(
    theme: dict[str, object],
    index: int,
    current_name: str | None,
    sep: str = "\ue0b4",
    sep_end: str | None = "\ue0b0",
    force_white: bool = False,
) -> list[str]:
    """Build a 3-line terminal preview card for a theme."""
    name = str(theme.get("name", "Unknown"))
    badge = str(theme.get("badge", ""))
    tag = f"  \033[33;1m← active{RESET}" if current_name and name == current_name else ""
    badge_str = f" {DIM}[{badge}]{RESET}" if badge else ""

    h_bg = color_index(str(theme.get("background_host", "0")))
    p_bg = color_index(str(theme.get("background_pwd", "0")))
    g_bg = color_index(str(theme.get("background_git", "0")))
    swatch = f" {ansi_bg(h_bg)}  {ansi_bg(p_bg)}  {ansi_bg(g_bg)}  {RESET}"

    num_label = f"{BOLD}{DIM}#{index:02d}{RESET}"
    return [
        f"{num_label} {BOLD}{name}{RESET}{badge_str}{swatch}{tag}",
        render_prompt_line(
            theme,
            [("host", "dev"), ("pwd", "~/workspace/app"), ("git", "main")],
            "git status",
            sep=sep,
            sep_end=sep_end,
            force_white=force_white,
        ),
        render_prompt_line(
            theme,
            [
                ("host", "dev"),
                ("pwd", "~/api"),
                ("git", "feat ◔"),
                ("pyenv", ".venv"),
                ("tf", "prod"),
                ("kube", "☸ gke"),
            ],
            "kubectl get pods",
            sep=sep,
            sep_end=sep_end,
            force_white=force_white,
        ),
    ]


def serialize_theme_for_web(theme: dict[str, object], index: int) -> dict[str, object]:
    """Serialize a parsed theme with precomputed `#rrggbb` CSS hex colors for Web Studio."""
    segments_css: dict[str, dict[str, str | None]] = {}
    raw_colors: dict[str, str] = {}

    for seg in SEGMENT_KEYS:
        def_fg, def_bg = DEFAULT_SEGMENT_COLORS[seg]
        fg_tok = str(theme.get(f"font_color_{seg}", def_fg))
        bg_tok = str(theme.get(f"background_{seg}", def_bg))
        raw_colors[f"font_color_{seg}"] = fg_tok
        raw_colors[f"background_{seg}"] = bg_tok
        segments_css[seg] = {
            "fg": token_to_hex(fg_tok, "#ffffff"),
            "bg": token_to_hex(bg_tok, None),
            "fg_token": fg_tok,
            "bg_token": bg_tok,
        }

    return {
        "id": index,
        "slug": str(theme.get("slug", "")),
        "name": str(theme.get("name", "")),
        "badge": str(theme.get("badge", "Theme")),
        "description": str(theme.get("description", "")),
        "swatch": [
            segments_css["host"]["bg"] or "#333333",
            segments_css["pwd"]["bg"] or "#666666",
            segments_css["git"]["bg"] or "#444444",
        ],
        "segments": segments_css,
        "raw_colors": raw_colors,
    }
