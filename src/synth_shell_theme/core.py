"""Atomic configuration reader/writer, backups, layout controls, and JSON presets for synth-shell."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from datetime import datetime
from pathlib import Path

from synth_shell_theme.patches import apply_runtime_patches, ensure_dual_separator_support, inspect_patches
from synth_shell_theme.paths import get_backup_dir, get_config_dir, get_config_path
from synth_shell_theme.separators import (
    format_separator_assignment,
    get_separator_key,
    parse_separator_value,
    resolve_separator_input,
)
from synth_shell_theme.themes import (
    SEGMENT_KEYS,
    find_theme,
    is_color_key,
    load_themes,
    token_to_hex,
)

VALID_FORMAT_TOKENS: tuple[str, ...] = (
    "USER",
    "HOST",
    "PWD",
    "GIT",
    "PYENV",
    "TF",
    "KUBE",
    "CLOCK",
)


def _atomic_write(target: Path, content: str) -> None:
    """Write `content` atomically to `target`, preserving file permissions if it already exists."""
    target.parent.mkdir(parents=True, exist_ok=True)
    mode = target.stat().st_mode if target.exists() else None
    fd, tmp_name = tempfile.mkstemp(prefix=f".{target.name}.", dir=str(target.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(content)
        if mode is not None:
            try:
                os.chmod(tmp_path, mode)
            except OSError:
                pass
        os.replace(tmp_path, target)
    finally:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass


def _strip_inline_comment(val: str) -> str:
    """Strip unquoted `# ...` inline Bash comments from a config assignment RHS."""
    in_single = False
    in_double = False
    escaped = False
    for idx, ch in enumerate(val):
        if escaped:
            escaped = False
            continue
        if ch == "\\" and not in_single:
            escaped = True
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double:
            return val[:idx].strip()
    return val.strip()


def _unquote(val: str) -> str:
    """Remove surrounding Bash quotes (`\"...\"`, `'...'`, or `$'...'`)."""
    s = _strip_inline_comment(val)
    if s.startswith("$'") and s.endswith("'"):
        return s[2:-1]
    if len(s) >= 2 and s[0] == s[-1] and s[0] in ('"', "'"):
        return s[1:-1]
    return s


def backup_config(config_dir: Path | None = None) -> Path | None:
    """Create a timestamped backup of `synth-shell-prompt.config` in `backups/`."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    if not cfg.is_file():
        return None
    bdir = get_backup_dir(base)
    bdir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = bdir / f"synth-shell-prompt.config.{stamp}.bak"
    counter = 1
    while dest.exists():
        dest = bdir / f"synth-shell-prompt.config.{stamp}-{counter}.bak"
        counter += 1
    shutil.copy2(cfg, dest)

    # Keep at most 40 config backups so `backups/` stays tidy
    all_baks = sorted(bdir.glob("synth-shell-prompt.config.*.bak"))
    if len(all_baks) > 40:
        for old in all_baks[:-40]:
            try:
                old.unlink()
            except OSError:
                pass
    return dest


def list_backups(config_dir: Path | None = None) -> list[dict[str, object]]:
    """Return available config backups sorted newest-first."""
    base = config_dir if config_dir is not None else get_config_dir()
    bdir = get_backup_dir(base)
    if not bdir.is_dir():
        return []
    files = sorted(
        bdir.glob("synth-shell-prompt.config.*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    out: list[dict[str, object]] = []
    for idx, f in enumerate(files, 1):
        stat = f.stat()
        out.append(
            {
                "id": idx,
                "name": f.name,
                "path": str(f),
                "size": stat.st_size,
                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            }
        )
    return out


def restore_backup(
    target: int | str | None = None,
    config_dir: Path | None = None,
) -> Path | None:
    """Restore a backup by 1-based index (default `1` = latest) or filename."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    bdir = get_backup_dir(base)
    if not bdir.is_dir():
        return None
    files = sorted(
        bdir.glob("synth-shell-prompt.config.*.bak"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    if not files:
        return None

    chosen: Path | None = None
    if target is None or target == "" or target == 1 or target == "1":
        chosen = files[0]
    elif isinstance(target, int) or (isinstance(target, str) and target.strip().isdigit()):
        idx = int(str(target).strip())
        if 1 <= idx <= len(files):
            chosen = files[idx - 1]
    else:
        t_str = str(target).strip()
        for f in files:
            if f.name == t_str or str(f) == t_str:
                chosen = f
                break

    if chosen is None or not chosen.is_file():
        return None

    content = chosen.read_text(encoding="utf-8", errors="replace")
    _atomic_write(cfg, content)
    return chosen


def detect_current_separators(
    config_dir: Path | None = None,
) -> tuple[tuple[str, str], tuple[str, str] | None]:
    """Return `((internal_glyph, internal_code), (end_glyph, end_code) | None)` from live config."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    internal_res = ("\ue0b4", "\\uE0B4")
    end_res: tuple[str, str] | None = None
    if not cfg.is_file():
        return internal_res, end_res

    for raw_line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.strip()
        m_main = re.match(r"^separator_char\s*=\s*(.+)$", line)
        if m_main:
            rhs = _strip_inline_comment(m_main.group(1))
            parsed = parse_separator_value(rhs)
            if parsed[0]:
                internal_res = parsed
            continue
        m_end = re.match(r"^separator_char_end\s*=\s*(.+)$", line)
        if m_end:
            rhs = _strip_inline_comment(m_end.group(1))
            parsed = parse_separator_value(rhs)
            if parsed[0]:
                end_res = parsed
            continue

    return internal_res, end_res


def detect_current_theme(
    themes: list[dict[str, object]],
    config_dir: Path | None = None,
) -> tuple[str | None, int | None]:
    """Detect the currently active theme name and 1-based index from `synth-shell-prompt.config`."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    if not cfg.is_file():
        return None, None

    lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    current: dict[str, str] = {}
    header_title: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        m_hdr = re.match(r"^#\s*Theme\s+\d+:\s*(.+)$", line)
        if m_hdr and header_title is None:
            header_title = m_hdr.group(1).strip()
            continue
        m_kv = re.match(r"^(font_color_\w+|background_\w+)\s*=\s*(.+)$", line)
        if m_kv:
            current[m_kv.group(1)] = _unquote(m_kv.group(2)).strip()

    if not current and not header_title:
        return None, None

    # 1. Exact color score across core prompt segments
    color_keys = [
        "font_color_host",
        "background_host",
        "font_color_pwd",
        "background_pwd",
        "font_color_git",
        "background_git",
        "font_color_input",
        "background_input",
    ]
    best_score = 0
    best_match: tuple[str | None, int | None] = (None, None)
    for idx, t in enumerate(themes, 1):
        score = sum(
            1
            for k in color_keys
            if str(t.get(k, "")).lower() == current.get(k, "").lower()
        )
        if score > best_score:
            best_score = score
            best_match = (str(t.get("name", "")), idx)

    if best_score >= 6:
        return best_match

    # 2. If `--force-white-text` was used, background keys + header title match cleanly
    bg_keys = [
        "background_host",
        "background_pwd",
        "background_git",
        "background_pyenv",
        "background_tf",
        "background_kube",
    ]
    for idx, t in enumerate(themes, 1):
        bg_matches = sum(
            1
            for k in bg_keys
            if k in current and str(t.get(k, "")).lower() == current.get(k, "").lower()
        )
        if bg_matches >= 5:
            return str(t.get("name", "")), idx

    if header_title:
        found_t, found_idx = find_theme(header_title, themes)
        if found_t and found_idx:
            return str(found_t.get("name", "")), found_idx

    return None, None


def read_current_state(
    themes: list[dict[str, object]] | None = None,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Read complete active prompt configuration state."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    catalog = themes if themes is not None else load_themes()

    (int_glyph, int_code), end_tuple = detect_current_separators(base)
    end_glyph = end_tuple[0] if end_tuple else int_glyph
    end_code = end_tuple[1] if end_tuple else int_code
    active_name, active_id = detect_current_theme(catalog, base)

    format_str = "HOST PWD GIT PYENV TF KUBE"
    new_line = True
    vertical_padding = True
    max_pwd_char = 35
    colors: dict[str, str] = {}

    if cfg.is_file():
        for raw_line in cfg.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            m_kv = re.match(r"^(\w+)\s*=\s*(.+)$", line)
            if not m_kv:
                continue
            key = m_kv.group(1)
            val = _unquote(m_kv.group(2))
            if key == "format":
                format_str = " ".join(tok for tok in val.upper().split() if tok in VALID_FORMAT_TOKENS) or format_str
            elif key == "enable_command_on_new_line":
                new_line = val.lower() in ("true", "1", "yes")
            elif key == "enable_vertical_padding":
                vertical_padding = val.lower() in ("true", "1", "yes")
            elif key == "max_pwd_char" and val.isdigit():
                max_pwd_char = int(val)
            elif is_color_key(key):
                colors[key] = val

    segments_css: dict[str, dict[str, str | None]] = {}
    for seg in SEGMENT_KEYS:
        fg_tok = colors.get(f"font_color_{seg}", "white")
        bg_tok = colors.get(f"background_{seg}", "none" if seg == "input" else "237")
        segments_css[seg] = {
            "fg": token_to_hex(fg_tok, "#ffffff"),
            "bg": token_to_hex(bg_tok, None),
            "fg_token": fg_tok,
            "bg_token": bg_tok,
        }

    return {
        "config_exists": cfg.is_file(),
        "config_path": str(cfg),
        "active_theme": active_name,
        "active_theme_id": active_id,
        "internal_separator": {
            "glyph": int_glyph,
            "code": int_code,
            "key": get_separator_key(int_glyph),
        },
        "end_separator": {
            "glyph": end_glyph,
            "code": end_code,
            "key": get_separator_key(end_glyph),
            "explicit": end_tuple is not None,
        },
        "format": format_str,
        "format_segments": format_str.split(),
        "enable_command_on_new_line": new_line,
        "enable_vertical_padding": vertical_padding,
        "max_pwd_char": max_pwd_char,
        "colors": colors,
        "segments_css": segments_css,
        "patches": inspect_patches(base),
    }


def apply_theme(
    theme: dict[str, object],
    force_white: bool = False,
    keep_input: bool = False,
    create_backup: bool = True,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Apply `theme` colors to `synth-shell-prompt.config` while preserving layout & separator settings."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)

    # Ensure 256-color parity patch is active if synth-shell is installed
    patch_state = inspect_patches(base)
    if patch_state["prompt_script_found"] and not patch_state["color_256_parity"]:
        apply_runtime_patches(base, tune_defaults=False)

    bak = backup_config(base) if (create_backup and cfg.is_file()) else None

    theme_id = int(theme.get("id", 0) or 0)
    theme_title = str(theme.get("name") or theme.get("_name") or "Custom")
    header_comment = (
        f"# Theme {theme_id}: {theme_title}" if theme_id else f"# Theme: {theme_title}"
    )
    swatches = theme.get("swatch256")
    swatch_comment = (
        f"# swatch256: {' '.join(str(x) for x in swatches)}"
        if isinstance(swatches, list) and swatches
        else ""
    )

    theme_keys = {k for k in theme if is_color_key(k)}

    if not cfg.is_file():
        src_path = theme.get("_path")
        if isinstance(src_path, Path) and src_path.is_file():
            raw_lines = src_path.read_text(encoding="utf-8").splitlines()
        else:
            raw_lines = [
                header_comment,
                'format="HOST PWD GIT PYENV TF KUBE"',
                'separator_char="\\uE0B4"',
                'separator_char_end="\\uE0B0"',
                'enable_vertical_padding="true"',
                'enable_command_on_new_line="true"',
                'max_pwd_char="35"',
                "",
            ] + [f'{k}="{theme[k]}"' for k in sorted(theme_keys)]

        fresh_lines: list[str] = []
        for line in raw_lines:
            m = re.match(r"^(\w+)\s*=", line)
            if m and m.group(1) in theme_keys:
                key = m.group(1)
                val = str(theme[key])
                if force_white and key.startswith("font_color_") and key != "font_color_input":
                    val = "white"
                fresh_lines.append(f'{key}="{val}"')
            else:
                fresh_lines.append(line)
        _atomic_write(cfg, "\n".join(fresh_lines) + "\n")
        return {
            "theme": theme_title,
            "theme_id": theme_id,
            "backup": str(bak) if bak else None,
            "config_path": str(cfg),
        }

    lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines: list[str] = []
    updated: set[str] = set()
    first_comment_updated = False
    swatch_comment_updated = False

    for line in lines:
        if line.startswith("# Theme") and not first_comment_updated:
            new_lines.append(header_comment)
            first_comment_updated = True
            continue
        if line.startswith("# swatch256:") and not swatch_comment_updated:
            new_lines.append(swatch_comment or line)
            swatch_comment_updated = True
            continue

        m = re.match(r"^(\w+)\s*=", line)
        if m and m.group(1) in theme_keys:
            key = m.group(1)
            if keep_input and key == "font_color_input":
                new_lines.append(line)
                updated.add(key)
                continue
            val = str(theme[key])
            if force_white and key.startswith("font_color_") and key != "font_color_input":
                val = "white"
            if "'" in line and '"' not in line:
                new_lines.append(f"{key}='{val}'")
            else:
                new_lines.append(f'{key}="{val}"')
            updated.add(key)
        else:
            new_lines.append(line)

    if not first_comment_updated:
        prefix = [header_comment]
        if swatch_comment and not swatch_comment_updated:
            prefix.append(swatch_comment)
        new_lines = prefix + new_lines

    missing = theme_keys - updated
    if missing:
        new_lines.append("")
        for key in sorted(missing):
            if keep_input and key == "font_color_input":
                continue
            val = str(theme[key])
            if force_white and key.startswith("font_color_") and key != "font_color_input":
                val = "white"
            new_lines.append(f'{key}="{val}"')

    _atomic_write(cfg, "\n".join(new_lines) + "\n")
    return {
        "theme": theme_title,
        "theme_id": theme_id,
        "backup": str(bak) if bak else None,
        "config_path": str(cfg),
    }


def apply_separators(
    internal: tuple[str, str] | None = None,
    end: tuple[str, str] | None = None,
    create_backup: bool = True,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Write internal (`separator_char`) and/or ending (`separator_char_end`) glyphs atomically."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)

    ensure_dual_separator_support(base)

    if not cfg.is_file():
        themes = load_themes()
        apply_theme(themes[1] if len(themes) > 1 else themes[0], create_backup=False, config_dir=base)

    bak = backup_config(base) if create_backup else None
    lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines: list[str] = []
    found_main = False
    found_end = False

    for line in lines:
        if re.match(r"^separator_char\s*=", line):
            if internal is not None:
                new_lines.append(format_separator_assignment("separator_char", internal[1]))
            else:
                new_lines.append(line)
            found_main = True
        elif re.match(r"^separator_char_end\s*=", line):
            if end is not None:
                new_lines.append(format_separator_assignment("separator_char_end", end[1]))
            else:
                new_lines.append(line)
            found_end = True
        else:
            new_lines.append(line)

    if not found_main and internal is not None:
        new_lines.append(format_separator_assignment("separator_char", internal[1]))
    if not found_end and end is not None:
        new_lines.append(format_separator_assignment("separator_char_end", end[1]))

    _atomic_write(cfg, "\n".join(new_lines) + "\n")
    return {
        "internal": {"glyph": internal[0], "code": internal[1]} if internal else None,
        "end": {"glyph": end[0], "code": end[1]} if end else None,
        "backup": str(bak) if bak else None,
        "config_path": str(cfg),
    }


def apply_layout_options(
    format_str: str | None = None,
    new_line: bool | None = None,
    vertical_padding: bool | None = None,
    max_pwd_char: int | None = None,
    create_backup: bool = True,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Update non-color prompt layout settings (`format`, 2-line prompt, vertical padding, `max_pwd_char`)."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)

    if not cfg.is_file():
        themes = load_themes()
        apply_theme(themes[1] if len(themes) > 1 else themes[0], create_backup=False, config_dir=base)

    clean_format: str | None = None
    if format_str is not None:
        tokens = [t for t in format_str.upper().replace(",", " ").split() if t in VALID_FORMAT_TOKENS]
        if tokens:
            clean_format = " ".join(tokens)

    if max_pwd_char is not None:
        max_pwd_char = max(10, min(120, int(max_pwd_char)))

    bak = backup_config(base) if create_backup else None
    lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines: list[str] = []
    seen: set[str] = set()

    for line in lines:
        m = re.match(r"^(\w+)\s*=", line)
        key = m.group(1) if m else ""
        if key == "format" and clean_format is not None:
            new_lines.append(f'format="{clean_format}"')
            seen.add("format")
        elif key == "enable_command_on_new_line" and new_line is not None:
            new_lines.append(f'enable_command_on_new_line="{"true" if new_line else "false"}"')
            seen.add("enable_command_on_new_line")
        elif key == "enable_vertical_padding" and vertical_padding is not None:
            new_lines.append(f'enable_vertical_padding="{"true" if vertical_padding else "false"}"')
            seen.add("enable_vertical_padding")
        elif key == "max_pwd_char" and max_pwd_char is not None:
            new_lines.append(f'max_pwd_char="{max_pwd_char}"')
            seen.add("max_pwd_char")
        else:
            new_lines.append(line)

    if clean_format is not None and "format" not in seen:
        new_lines.append(f'format="{clean_format}"')
    if new_line is not None and "enable_command_on_new_line" not in seen:
        new_lines.append(f'enable_command_on_new_line="{"true" if new_line else "false"}"')
    if vertical_padding is not None and "enable_vertical_padding" not in seen:
        new_lines.append(f'enable_vertical_padding="{"true" if vertical_padding else "false"}"')
    if max_pwd_char is not None and "max_pwd_char" not in seen:
        new_lines.append(f'max_pwd_char="{max_pwd_char}"')

    _atomic_write(cfg, "\n".join(new_lines) + "\n")
    return {
        "format": clean_format,
        "enable_command_on_new_line": new_line,
        "enable_vertical_padding": vertical_padding,
        "max_pwd_char": max_pwd_char,
        "backup": str(bak) if bak else None,
        "config_path": str(cfg),
    }


def export_preset(dest_path: Path, config_dir: Path | None = None) -> Path:
    """Export active colors, dual separators, and layout options into a portable JSON preset."""
    state = read_current_state(config_dir=config_dir)
    payload = {
        "schema": "synth-shell-theme-preset/v1",
        "active_theme": state["active_theme"],
        "active_theme_id": state["active_theme_id"],
        "internal_separator": state["internal_separator"],
        "end_separator": state["end_separator"],
        "format": state["format"],
        "enable_command_on_new_line": state["enable_command_on_new_line"],
        "enable_vertical_padding": state["enable_vertical_padding"],
        "max_pwd_char": state["max_pwd_char"],
        "colors": state["colors"],
    }
    dest = Path(dest_path).expanduser()
    _atomic_write(dest, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return dest


def import_preset(src_path: Path, config_dir: Path | None = None) -> dict[str, object]:
    """Import and apply a JSON preset file created by `export_preset`."""
    base = config_dir if config_dir is not None else get_config_dir()
    src = Path(src_path).expanduser()
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("Invalid preset JSON: expected a JSON object.")

    bak = backup_config(base)
    colors = data.get("colors", {})
    if isinstance(colors, dict) and colors:
        pseudo_theme: dict[str, object] = {
            "id": data.get("active_theme_id") or 0,
            "name": data.get("active_theme") or src.stem,
            "_name": data.get("active_theme") or src.stem,
        }
        for k, v in colors.items():
            if is_color_key(str(k)):
                pseudo_theme[str(k)] = str(v)
        apply_theme(pseudo_theme, create_backup=False, config_dir=base)
    elif data.get("active_theme"):
        themes = load_themes()
        found, _ = find_theme(str(data["active_theme"]), themes)
        if found:
            apply_theme(found, create_backup=False, config_dir=base)

    int_sep = data.get("internal_separator")
    end_sep = data.get("end_separator")
    int_tuple: tuple[str, str] | None = None
    end_tuple: tuple[str, str] | None = None
    if isinstance(int_sep, dict) and int_sep.get("code"):
        g, c, _ = resolve_separator_input(str(int_sep["code"]))
        int_tuple = (g, c)
    if isinstance(end_sep, dict) and end_sep.get("code"):
        g, c, _ = resolve_separator_input(str(end_sep["code"]))
        end_tuple = (g, c)
    if int_tuple or end_tuple:
        apply_separators(internal=int_tuple, end=end_tuple, create_backup=False, config_dir=base)

    apply_layout_options(
        format_str=str(data["format"]) if "format" in data else None,
        new_line=bool(data["enable_command_on_new_line"]) if "enable_command_on_new_line" in data else None,
        vertical_padding=bool(data["enable_vertical_padding"]) if "enable_vertical_padding" in data else None,
        max_pwd_char=int(data["max_pwd_char"]) if "max_pwd_char" in data else None,
        create_backup=False,
        config_dir=base,
    )
    return {
        "imported_from": str(src),
        "backup": str(bak) if bak else None,
        "state": read_current_state(config_dir=base),
    }
