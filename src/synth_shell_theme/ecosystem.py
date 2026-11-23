"""Ecosystem color sync (fzf, LS_COLORS, tmux) & external palette importer (Pywal, Base16, Ghostty, Kitty, Alacritty, WT)."""

from __future__ import annotations

import json
import re
from pathlib import Path

from synth_shell_theme.paths import get_config_dir
from synth_shell_theme.themes import (
    color_index,
    find_theme,
    load_themes,
    normalize_hex_color,
    save_custom_theme,
    token_to_hex,
)


def _contrast_fg(hex_bg: str) -> str:
    """Return `#000000` or `#ffffff` based on perceptual luminance of `hex_bg`."""
    norm = normalize_hex_color(hex_bg) or "#222222"
    r = int(norm[1:3], 16)
    g = int(norm[3:5], 16)
    b = int(norm[5:7], 16)
    lum = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if lum >= 140 else "white"


def sync_ecosystem(
    theme: dict[str, object] | None = None,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Generate `theme-env.sh` (`FZF_DEFAULT_OPTS` + `LS_COLORS`) and `tmux-theme.conf` matching active theme."""
    from synth_shell_theme.core import _atomic_write, read_current_state

    base = config_dir if config_dir is not None else get_config_dir()
    catalog = load_themes(config_dir=base)
    state = read_current_state(catalog, base)

    if theme is None:
        active_id = state.get("active_theme_id")
        if isinstance(active_id, int) and 1 <= active_id <= len(catalog):
            theme = catalog[active_id - 1]
        else:
            tokyo, _ = find_theme("tokyo-night", catalog)
            theme = tokyo or catalog[0]

    theme_name = str(theme.get("name", "Active Theme"))
    host_bg = token_to_hex(str(theme.get("background_host", "237")), "#3b4261") or "#3b4261"
    pwd_bg = token_to_hex(str(theme.get("background_pwd", "255")), "#7aa2f7") or "#7aa2f7"
    git_bg = token_to_hex(str(theme.get("background_git", "71")), "#9ece6a") or "#9ece6a"
    pyenv_bg = token_to_hex(str(theme.get("background_pyenv", "63")), "#bb9af7") or "#bb9af7"
    tf_bg = token_to_hex(str(theme.get("background_tf", "228")), "#e0af68") or "#e0af68"
    kube_bg = token_to_hex(str(theme.get("background_kube", "135")), "#7dcfff") or "#7dcfff"
    input_fg = token_to_hex(str(theme.get("font_color_input", "white")), "#eef2f8") or "#eef2f8"

    # 256-color indices for LS_COLORS compatibility across all terminals
    i_dir = color_index(pwd_bg) or 75
    i_exec = color_index(git_bg) or 114
    i_link = color_index(kube_bg) or 117
    i_arch = color_index(tf_bg) or 214
    i_code = color_index(pyenv_bg) or 141

    fzf_colors = (
        f"bg+:{host_bg},fg+:{input_fg},"
        f"hl:{tf_bg},hl+:{git_bg},"
        f"info:{kube_bg},prompt:{pwd_bg},"
        f"pointer:{pyenv_bg},marker:{git_bg},"
        f"spinner:{tf_bg},header:{pwd_bg},border:{host_bg}"
    )

    ls_colors = (
        f"di=1;38;5;{i_dir}:"
        f"ln=1;38;5;{i_link}:"
        f"ex=1;38;5;{i_exec}:"
        f"*.py=38;5;{i_code}:*.sh=38;5;{i_exec}:*.json=38;5;{i_arch}:"
        f"*.yaml=38;5;{i_arch}:*.yml=38;5;{i_arch}:*.md=38;5;{i_link}:"
        f"*.tar=38;5;{i_arch}:*.gz=38;5;{i_arch}:*.zip=38;5;{i_arch}"
    )

    env_path = base / "theme-env.sh"
    env_content = (
        f"# Synth-Shell Ecosystem Theme Env — synced with {theme_name}\n"
        f"# Add to ~/.bashrc: source ~/.config/synth-shell/theme-env.sh\n"
        f'export FZF_DEFAULT_OPTS="${{FZF_DEFAULT_OPTS:+${{FZF_DEFAULT_OPTS}} }}--color={fzf_colors}"\n'
        f'export LS_COLORS="{ls_colors}"\n'
    )
    _atomic_write(env_path, env_content)

    tmux_path = base / "tmux-theme.conf"
    tmux_fg_host = "#000000" if _contrast_fg(host_bg) == "black" else "#ffffff"
    tmux_fg_pwd = "#000000" if _contrast_fg(pwd_bg) == "black" else "#ffffff"
    tmux_content = (
        f"# Synth-Shell tmux Theme — synced with {theme_name}\n"
        f"# Add to ~/.tmux.conf: source-file ~/.config/synth-shell/tmux-theme.conf\n"
        f'set -g status-style "bg=#12161f,fg={input_fg}"\n'
        f'set -g status-left "#[bg={host_bg},fg={tmux_fg_host},bold] #S #[bg=#12161f,fg={host_bg}] "\n'
        f'set -g status-right "#[fg={git_bg}]#[bg={git_bg},fg=#000000,bold] %H:%M "\n'
        f'setw -g window-status-current-style "bg={pwd_bg},fg={tmux_fg_pwd},bold"\n'
        f'setw -g window-status-current-format " #I:#W "\n'
        f'set -g pane-active-border-style "fg={pwd_bg}"\n'
        f'set -g pane-border-style "fg={host_bg}"\n'
    )
    _atomic_write(tmux_path, tmux_content)

    return {
        "theme": theme_name,
        "env_script": str(env_path),
        "tmux_conf": str(tmux_path),
        "fzf_colors": fzf_colors,
        "ls_colors": ls_colors,
    }


def _extract_palette_from_pywal(path: Path) -> tuple[str, dict[str, str]]:
    """Parse Pywal `~/.cache/wal/colors.json` or `colors.sh` into a 16-color map."""
    text = path.read_text(encoding="utf-8", errors="replace")
    colors: dict[str, str] = {}
    name = "Pywal Wallpaper"
    if path.suffix.lower() == ".json" or text.lstrip().startswith("{"):
        data = json.loads(text)
        wp = data.get("wallpaper")
        if isinstance(wp, str) and wp.strip():
            name = f"Pywal ({Path(wp).stem})"
        cmap = data.get("colors", {})
        if isinstance(cmap, dict):
            for k, v in cmap.items():
                hx = normalize_hex_color(str(v))
                if hx:
                    colors[k.lower()] = hx
        special = data.get("special", {})
        if isinstance(special, dict):
            for k in ("background", "foreground"):
                hx = normalize_hex_color(str(special.get(k, "")))
                if hx:
                    colors[k] = hx
    else:
        for m in re.finditer(r"^(color\d+|background|foreground)\s*=\s*['\"]?(#[0-9a-fA-F]{6})['\"]?", text, re.MULTILINE):
            colors[m.group(1).lower()] = m.group(2).lower()
    return name, colors


def _extract_palette_from_base16(text: str, stem: str) -> tuple[str, dict[str, str]]:
    """Parse Base16 YAML (`base00:` .. `base0F:`) without external YAML dependencies."""
    name = stem.replace("-", " ").replace("_", " ").title()
    m_scheme = re.search(r'^scheme\s*:\s*["\']?([^"\'\n]+)["\']?', text, re.MULTILINE)
    if m_scheme:
        name = m_scheme.group(1).strip()

    b: dict[str, str] = {}
    for m in re.finditer(r'^(base0[0-9A-Fa-f])\s*:\s*["\']?#?([0-9a-fA-F]{6})["\']?', text, re.MULTILINE):
        b[m.group(1).lower()] = f"#{m.group(2).lower()}"

    if not b:
        return name, {}

    # Standard Base16 semantic mapping
    return name, {
        "background": b.get("base00", "#1a1b26"),
        "foreground": b.get("base05", "#c0caf5"),
        "color0": b.get("base01", b.get("base00", "#24283b")),
        "color1": b.get("base08", "#f7768e"),
        "color2": b.get("base0b", "#9ece6a"),
        "color3": b.get("base0a", "#e0af68"),
        "color4": b.get("base0d", "#7aa2f7"),
        "color5": b.get("base0e", "#bb9af7"),
        "color6": b.get("base0c", "#7dcfff"),
        "color7": b.get("base05", "#c0caf5"),
        "color8": b.get("base02", "#414868"),
    }


def _extract_palette_from_windows_terminal(text: str, stem: str) -> tuple[str, dict[str, str]]:
    data = json.loads(text)
    if isinstance(data, dict) and isinstance(data.get("schemes"), list) and data["schemes"]:
        data = data["schemes"][0]
    if not isinstance(data, dict):
        return stem, {}
    name = str(data.get("name") or stem.replace("-", " ").title())
    key_map = {
        "background": "background",
        "foreground": "foreground",
        "black": "color0",
        "red": "color1",
        "green": "color2",
        "yellow": "color3",
        "blue": "color4",
        "purple": "color5",
        "cyan": "color6",
        "white": "color7",
        "brightBlack": "color8",
        "brightBlue": "color12",
    }
    colors: dict[str, str] = {}
    for src_k, dst_k in key_map.items():
        hx = normalize_hex_color(str(data.get(src_k, "")))
        if hx:
            colors[dst_k] = hx
    return name, colors


def _extract_palette_from_terminal_conf(text: str, stem: str) -> tuple[str, dict[str, str]]:
    """Parse Ghostty (`palette = N=#hex`), Kitty (`colorN #hex`), and Alacritty TOML/YAML color configs."""
    name = stem.replace("-", " ").replace("_", " ").title()
    colors: dict[str, str] = {}

    # Ghostty: palette = 4=#7aa2f7
    for m in re.finditer(r"^\s*palette\s*=\s*(\d+)\s*=\s*(#[0-9a-fA-F]{6})", text, re.MULTILINE):
        colors[f"color{m.group(1)}"] = m.group(2).lower()

    # Kitty: color4 #7aa2f7 / background #1a1b26
    for m in re.finditer(r"^\s*(color\d+|background|foreground)\s*[=:]?\s*['\"]?(#[0-9a-fA-F]{6})['\"]?", text, re.MULTILINE):
        colors[m.group(1).lower()] = m.group(2).lower()

    # Alacritty TOML/YAML named keys: blue = "#7aa2f7" or blue: '0x7aa2f7'
    name_map = {
        "black": "color0",
        "red": "color1",
        "green": "color2",
        "yellow": "color3",
        "blue": "color4",
        "magenta": "color5",
        "cyan": "color6",
        "white": "color7",
    }
    for key_name, dst in name_map.items():
        if dst in colors:
            continue
        m = re.search(rf"^\s*{key_name}\s*[=:]\s*['\"]?(?:#|0x)([0-9a-fA-F]{{6}})['\"]?", text, re.MULTILINE)
        if m:
            colors[dst] = f"#{m.group(1).lower()}"

    return name, colors


def import_external_theme(
    source_path: Path | None = None,
    *,
    from_pywal: bool = False,
    custom_name: str | None = None,
    apply_now: bool = True,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Import a palette from Pywal, Base16 YAML, Ghostty, Kitty, Alacritty, or Windows Terminal JSON."""
    from synth_shell_theme.core import apply_theme

    base = config_dir if config_dir is not None else get_config_dir()
    if from_pywal:
        candidates = [
            source_path if source_path is not None else Path.home() / ".cache" / "wal" / "colors.json",
            Path.home() / ".cache" / "wal" / "colors.sh",
        ]
        target = next((p for p in candidates if p.is_file()), None)
        if target is None:
            raise FileNotFoundError("Pywal cache not found (~/.cache/wal/colors.json or colors.sh).")
        inferred_name, pal = _extract_palette_from_pywal(target)
        src_fmt = "pywal"
    else:
        if source_path is None or not Path(source_path).expanduser().is_file():
            raise FileNotFoundError(f"Palette file not found: {source_path}")
        target = Path(source_path).expanduser()
        text = target.read_text(encoding="utf-8", errors="replace")
        stem = target.stem
        if re.search(r"^base0[0-9a-fA-F]\s*:", text, re.MULTILINE):
            inferred_name, pal = _extract_palette_from_base16(text, stem)
            src_fmt = "base16"
        elif target.suffix.lower() == ".json" or text.lstrip().startswith("{"):
            try:
                parsed_json = json.loads(text)
            except json.JSONDecodeError:
                parsed_json = {}
            if isinstance(parsed_json, dict) and "colors" in parsed_json and "special" in parsed_json:
                inferred_name, pal = _extract_palette_from_pywal(target)
                src_fmt = "pywal"
            else:
                inferred_name, pal = _extract_palette_from_windows_terminal(text, stem)
                src_fmt = "windows-terminal"
        else:
            inferred_name, pal = _extract_palette_from_terminal_conf(text, stem)
            src_fmt = "terminal-conf"

    if len(pal) < 3:
        raise ValueError(f"Could not extract enough colors from {target} (detected format: {src_fmt}).")

    host_bg = pal.get("color8") or pal.get("color0") or pal.get("background") or "#2a2e3f"
    pwd_bg = pal.get("color4") or pal.get("color12") or "#7aa2f7"
    git_bg = pal.get("color2") or "#9ece6a"
    pyenv_bg = pal.get("color5") or "#bb9af7"
    tf_bg = pal.get("color3") or "#e0af68"
    kube_bg = pal.get("color6") or "#7dcfff"
    status_bg = pal.get("color1") or "#f7768e"
    input_fg = pal.get("foreground") or pal.get("color7") or "#eef2f8"

    segment_colors = {
        "font_color_user": _contrast_fg(pwd_bg),
        "background_user": pwd_bg,
        "font_color_host": _contrast_fg(host_bg),
        "background_host": host_bg,
        "font_color_pwd": _contrast_fg(pwd_bg),
        "background_pwd": pwd_bg,
        "font_color_git": _contrast_fg(git_bg),
        "background_git": git_bg,
        "font_color_pyenv": _contrast_fg(pyenv_bg),
        "background_pyenv": pyenv_bg,
        "font_color_tf": _contrast_fg(tf_bg),
        "background_tf": tf_bg,
        "font_color_kube": _contrast_fg(kube_bg),
        "background_kube": kube_bg,
        "font_color_status": _contrast_fg(status_bg),
        "background_status": status_bg,
        "font_color_input": input_fg,
        "background_input": "none",
    }

    final_name = (custom_name or inferred_name).strip()
    saved = save_custom_theme(
        name=final_name,
        colors=segment_colors,
        description=f"Imported from {src_fmt} ({target.name}).",
        badge=src_fmt.capitalize(),
        config_dir=base,
    )
    if apply_now:
        apply_theme(saved, config_dir=base)

    return {
        "format": src_fmt,
        "source": str(target),
        "theme": saved["name"],
        "slug": saved["slug"],
        "saved_path": str(saved["_path"]),
        "applied": apply_now,
    }
