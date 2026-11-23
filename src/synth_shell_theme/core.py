"""Atomic configuration reader/writer, backups, layout controls, root/greeter sync, and JSON presets."""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import statistics
import subprocess
import tempfile
import time
from datetime import datetime
from pathlib import Path

from synth_shell_theme.patches import apply_runtime_patches, ensure_dual_separator_support, inspect_patches
from synth_shell_theme.paths import (
    get_backup_dir,
    get_config_dir,
    get_config_path,
    get_greeter_config_path,
    get_prompt_script_path,
    get_root_config_path,
)
from synth_shell_theme.separators import (
    ALL_PRESETS,
    format_separator_assignment,
    get_separator_key,
    parse_separator_value,
    resolve_separator_input,
)
from synth_shell_theme.themes import (
    DEFAULT_SEGMENT_COLORS,
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
    "STATUS",
    "DURATION",
    "AWS",
    "GCP",
    "DOCKER",
    "NODE",
    "SSH",
    "JOBS",
    "DIRENV",
    "SHLVL",
    "RUST",
    "GO",
    "BATTERY",
    "SUDO",
    "JJ",
    "CUSTOM",
)

VALID_FONT_EFFECTS: tuple[str, ...] = (
    "bold",
    "regular",
    "italic",
    "dim",
    "none",
)

GREETER_ALL_MONITORS: tuple[str, ...] = (
    "OS",
    "KERNEL",
    "CPU",
    "GPU",
    "SHELL",
    "DATE",
    "UPTIME",
    "USER",
    "LOCALIPV4",
    "EXTERNALIPV4",
    "SERVICES",
    "CPUTEMP",
    "SYSLOAD_MON%",
    "MEMORY_MON",
    "SWAP_MON",
    "HDDROOT_MON",
    "HDDHOME_MON",
    "PALETTE",
)

DEFAULT_GREETER_MONITORS: tuple[str, ...] = (
    "OS",
    "KERNEL",
    "CPU",
    "GPU",
    "SHELL",
    "DATE",
    "UPTIME",
    "LOCALIPV4",
    "SERVICES",
    "CPUTEMP",
    "SYSLOAD_MON%",
    "MEMORY_MON",
    "SWAP_MON",
    "HDDROOT_MON",
    "HDDHOME_MON",
    "PALETTE",
)

ASCII_SAFE_GIT_SYMBOLS: dict[str, str] = {
    "git_symbol_synced": "",
    "git_symbol_unpushed": " +",
    "git_symbol_unpulled": " -",
    "git_symbol_unpushedunpulled": " <>",
    "git_symbol_dirty": " *",
    "git_symbol_dirty_unpushed": " *+",
    "git_symbol_dirty_unpulled": " *-",
    "git_symbol_dirty_unpushedunpulled": " *<>",
    "git_symbol_stash": "#",
    "pwd_trunc_symbol": "...",
    "status_symbol": "! ",
}


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
    """Remove surrounding Bash quotes (`\"...\"`, `'...'`, or `$'...'`) and unescape double-quoted specials."""
    s = _strip_inline_comment(val)
    if s.startswith("$'") and s.endswith("'"):
        return s[2:-1]
    if len(s) >= 2 and s[0] == "'" and s[-1] == "'":
        return s[1:-1]
    if len(s) >= 2 and s[0] == '"' and s[-1] == '"':
        inner = s[1:-1]
        out: list[str] = []
        i = 0
        while i < len(inner):
            if inner[i] == "\\" and i + 1 < len(inner) and inner[i + 1] in ('\\', '"', "$", "`"):
                out.append(inner[i + 1])
                i += 2
            else:
                out.append(inner[i])
                i += 1
        return "".join(out)
    return s


def _escape_bash_dq(val: str) -> str:
    """Safely escape a string for a Bash double-quoted config assignment (`key=\"...\"`)."""
    clean = str(val).replace("\r", " ").replace("\n", " ")
    return (
        clean.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("$", "\\$")
        .replace("`", "\\`")
    )


def _upsert_kv_lines(lines: list[str], updates: dict[str, str]) -> list[str]:
    """Update existing `key=...` lines in-place and append any missing keys cleanly."""
    new_lines: list[str] = []
    seen: set[str] = set()
    for line in lines:
        m = re.match(r"^(\w+)\s*=", line)
        key = m.group(1) if m else ""
        if key in updates:
            new_lines.append(f'{key}="{_escape_bash_dq(updates[key])}"')
            seen.add(key)
        else:
            new_lines.append(line)
    for key, val in updates.items():
        if key not in seen:
            new_lines.append(f'{key}="{_escape_bash_dq(val)}"')
    return new_lines


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
        m_hdr = re.match(r"^#\s*Theme(?:\s+\d+)?:\s*(.+)$", line)
        if m_hdr and header_title is None:
            header_title = m_hdr.group(1).strip()
            continue
        m_kv = re.match(r"^(font_color_\w+|background_\w+)\s*=\s*(.+)$", line)
        if m_kv:
            current[m_kv.group(1)] = _unquote(m_kv.group(2)).strip()

    if not current and not header_title:
        return None, None

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
    """Read complete active prompt configuration state (v1.0 + v1.1 fields)."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    catalog = themes if themes is not None else load_themes()

    (int_glyph, int_code), end_tuple = detect_current_separators(base)
    end_glyph = end_tuple[0] if end_tuple else int_glyph
    end_code = end_tuple[1] if end_tuple else int_code
    active_name, active_id = detect_current_theme(catalog, base)

    format_str = "HOST PWD GIT PYENV TF KUBE"
    right_format_str = ""
    right_fill_char = "─"
    enable_osc133 = True
    enable_osc7 = True
    enable_terminal_sanitize = True
    kube_show_namespace = True
    kube_prod_warning = True
    kube_prod_pattern = "prod|production|prd|live"
    git_dynamic_color = False
    ssh_host_color = False
    pwd_style = "default"
    notify_duration_sec = 0
    custom_segment_text = ""
    git_show_state = True
    battery_threshold = 100
    new_line = True
    vertical_padding = True
    max_pwd_char = 35
    max_git_char = 0
    max_pyenv_char = 0
    max_kube_char = 28
    compact_width = 90
    git_show_counts = True
    transient_prompt = False
    light_theme = "catppuccin-latte"
    dark_theme = "tokyo-night"
    prompt_prefix = ""
    font_effect = "bold"
    enable_terminal_title = True
    git_skip_untracked_on_slow_fs = True
    git_timeout_ms = 0
    git_async_cache = False
    min_duration_ms = 2000
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
            elif key == "right_format":
                right_format_str = " ".join(tok for tok in val.upper().split() if tok in VALID_FORMAT_TOKENS)
            elif key == "right_fill_char":
                right_fill_char = val or " "
            elif key == "enable_osc133":
                enable_osc133 = val.lower() in ("true", "1", "yes")
            elif key == "enable_osc7":
                enable_osc7 = val.lower() in ("true", "1", "yes")
            elif key == "enable_terminal_sanitize":
                enable_terminal_sanitize = val.lower() in ("true", "1", "yes")
            elif key == "kube_show_namespace":
                kube_show_namespace = val.lower() in ("true", "1", "yes")
            elif key == "kube_prod_warning":
                kube_prod_warning = val.lower() in ("true", "1", "yes")
            elif key == "kube_prod_pattern":
                kube_prod_pattern = val or "prod|production|prd|live"
            elif key == "git_dynamic_color":
                git_dynamic_color = val.lower() in ("true", "1", "yes")
            elif key == "ssh_host_color":
                ssh_host_color = val.lower() in ("true", "1", "yes")
            elif key == "pwd_style":
                pwd_style = val.lower() if val.lower() in ("default", "fish") else "default"
            elif key == "notify_duration_sec" and val.isdigit():
                notify_duration_sec = int(val)
            elif key == "custom_segment_text":
                custom_segment_text = val
            elif key == "git_show_state":
                git_show_state = val.lower() in ("true", "1", "yes")
            elif key == "battery_threshold" and val.isdigit():
                battery_threshold = int(val)
            elif key == "enable_command_on_new_line":
                new_line = val.lower() in ("true", "1", "yes")
            elif key == "enable_vertical_padding":
                vertical_padding = val.lower() in ("true", "1", "yes")
            elif key == "max_pwd_char" and val.isdigit():
                max_pwd_char = int(val)
            elif key == "max_git_char" and val.isdigit():
                max_git_char = int(val)
            elif key == "max_pyenv_char" and val.isdigit():
                max_pyenv_char = int(val)
            elif key == "max_kube_char" and val.isdigit():
                max_kube_char = int(val)
            elif key == "compact_width" and val.isdigit():
                compact_width = int(val)
            elif key == "git_show_counts":
                git_show_counts = val.lower() in ("true", "1", "yes")
            elif key == "transient_prompt":
                transient_prompt = val.lower() in ("true", "1", "yes")
            elif key == "synth_light_theme" and val:
                light_theme = val
            elif key == "synth_dark_theme" and val:
                dark_theme = val
            elif key == "prompt_prefix":
                prompt_prefix = val
            elif key == "font_effect_override" and val.lower() in VALID_FONT_EFFECTS:
                font_effect = val.lower()
            elif key == "enable_terminal_title":
                enable_terminal_title = val.lower() in ("true", "1", "yes")
            elif key == "git_skip_untracked_on_slow_fs":
                git_skip_untracked_on_slow_fs = val.lower() in ("true", "1", "yes")
            elif key == "git_timeout_ms" and val.isdigit():
                git_timeout_ms = int(val)
            elif key == "git_async_cache":
                git_async_cache = val.lower() in ("true", "1", "yes")
            elif key == "min_duration_ms" and val.isdigit():
                min_duration_ms = int(val)
            elif is_color_key(key):
                colors[key] = val

    segments_css: dict[str, dict[str, str | None]] = {}
    for seg in SEGMENT_KEYS:
        def_fg, def_bg = DEFAULT_SEGMENT_COLORS[seg]
        fg_tok = colors.get(f"font_color_{seg}", def_fg)
        bg_tok = colors.get(f"background_{seg}", def_bg)
        segments_css[seg] = {
            "fg": token_to_hex(fg_tok, "#ffffff"),
            "bg": token_to_hex(bg_tok, None),
            "fg_token": fg_tok,
            "bg_token": bg_tok,
        }

    return {
        "config_exists": cfg.is_file(),
        "config_path": str(cfg),
        "root_config_exists": get_root_config_path(base).is_file(),
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
        "right_format": right_format_str,
        "right_format_segments": right_format_str.split() if right_format_str else [],
        "right_fill_char": right_fill_char,
        "enable_osc133": enable_osc133,
        "enable_osc7": enable_osc7,
        "enable_terminal_sanitize": enable_terminal_sanitize,
        "kube_show_namespace": kube_show_namespace,
        "kube_prod_warning": kube_prod_warning,
        "kube_prod_pattern": kube_prod_pattern,
        "git_dynamic_color": git_dynamic_color,
        "ssh_host_color": ssh_host_color,
        "pwd_style": pwd_style,
        "notify_duration_sec": notify_duration_sec,
        "custom_segment_text": custom_segment_text,
        "git_show_state": git_show_state,
        "battery_threshold": battery_threshold,
        "enable_command_on_new_line": new_line,
        "enable_vertical_padding": vertical_padding,
        "max_pwd_char": max_pwd_char,
        "max_git_char": max_git_char,
        "max_pyenv_char": max_pyenv_char,
        "max_kube_char": max_kube_char,
        "compact_width": compact_width,
        "git_show_counts": git_show_counts,
        "transient_prompt": transient_prompt,
        "light_theme": light_theme,
        "dark_theme": dark_theme,
        "prompt_prefix": prompt_prefix,
        "font_effect": font_effect,
        "enable_terminal_title": enable_terminal_title,
        "git_skip_untracked_on_slow_fs": git_skip_untracked_on_slow_fs,
        "git_timeout_ms": git_timeout_ms,
        "git_async_cache": git_async_cache,
        "min_duration_ms": min_duration_ms,
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

    patch_state = inspect_patches(base)
    if patch_state["prompt_script_found"] and not patch_state["color_256_parity"]:
        apply_runtime_patches(base, tune_defaults=False)

    bak = backup_config(base) if (create_backup and cfg.is_file()) else None

    theme_id = int(theme.get("id", 0) or 0)
    theme_title = " ".join(str(theme.get("name") or theme.get("_name") or "Custom").replace("\r", " ").replace("\n", " ").split())
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
            safe_val = _escape_bash_dq(val)
            if "'" in line and '"' not in line:
                new_lines.append(f"{key}='{val.replace(chr(39), '')}'")
            else:
                new_lines.append(f'{key}="{safe_val}"')
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
            new_lines.append(f'{key}="{_escape_bash_dq(val)}"')

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
        themes = load_themes(config_dir=base)
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
    right_format_str: str | None = None,
    right_fill_char: str | None = None,
    enable_osc133: bool | None = None,
    enable_osc7: bool | None = None,
    enable_terminal_sanitize: bool | None = None,
    kube_show_namespace: bool | None = None,
    kube_prod_warning: bool | None = None,
    kube_prod_pattern: str | None = None,
    git_dynamic_color: bool | None = None,
    ssh_host_color: bool | None = None,
    pwd_style: str | None = None,
    notify_duration_sec: int | None = None,
    custom_segment_text: str | None = None,
    git_show_state: bool | None = None,
    battery_threshold: int | None = None,
    new_line: bool | None = None,
    vertical_padding: bool | None = None,
    max_pwd_char: int | None = None,
    max_git_char: int | None = None,
    max_pyenv_char: int | None = None,
    max_kube_char: int | None = None,
    compact_width: int | None = None,
    git_show_counts: bool | None = None,
    transient_prompt: bool | None = None,
    light_theme: str | None = None,
    dark_theme: str | None = None,
    prompt_prefix: str | None = None,
    font_effect: str | None = None,
    enable_terminal_title: bool | None = None,
    git_skip_untracked_on_slow_fs: bool | None = None,
    git_timeout_ms: int | None = None,
    git_async_cache: bool | None = None,
    min_duration_ms: int | None = None,
    create_backup: bool = True,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Update prompt layout, truncation, responsive width, prefix, text effect, titlebar, and Git/duration settings."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)

    if not cfg.is_file():
        themes = load_themes(config_dir=base)
        apply_theme(themes[1] if len(themes) > 1 else themes[0], create_backup=False, config_dir=base)

    updates: dict[str, str] = {}
    clean_format: str | None = None
    if format_str is not None:
        tokens = [t for t in format_str.upper().replace(",", " ").split() if t in VALID_FORMAT_TOKENS]
        if tokens:
            clean_format = " ".join(tokens)
            updates["format"] = clean_format

    clean_right_format: str | None = None
    if right_format_str is not None:
        rtokens = [t for t in right_format_str.upper().replace(",", " ").split() if t in VALID_FORMAT_TOKENS]
        clean_right_format = " ".join(rtokens)
        updates["right_format"] = clean_right_format
    if right_fill_char is not None:
        updates["right_fill_char"] = right_fill_char[:1] if right_fill_char else " "
    if enable_osc133 is not None:
        updates["enable_osc133"] = "true" if enable_osc133 else "false"
    if enable_osc7 is not None:
        updates["enable_osc7"] = "true" if enable_osc7 else "false"
    if enable_terminal_sanitize is not None:
        updates["enable_terminal_sanitize"] = "true" if enable_terminal_sanitize else "false"
    if kube_show_namespace is not None:
        updates["kube_show_namespace"] = "true" if kube_show_namespace else "false"
    if kube_prod_warning is not None:
        updates["kube_prod_warning"] = "true" if kube_prod_warning else "false"
    if kube_prod_pattern is not None and kube_prod_pattern.strip():
        updates["kube_prod_pattern"] = kube_prod_pattern.strip()
    if git_dynamic_color is not None:
        updates["git_dynamic_color"] = "true" if git_dynamic_color else "false"
    if ssh_host_color is not None:
        updates["ssh_host_color"] = "true" if ssh_host_color else "false"
    if pwd_style is not None:
        ps = pwd_style.strip().lower()
        updates["pwd_style"] = ps if ps in ("default", "fish") else "default"
    if notify_duration_sec is not None:
        updates["notify_duration_sec"] = str(max(0, min(3600, int(notify_duration_sec))))
    if custom_segment_text is not None:
        updates["custom_segment_text"] = custom_segment_text
    if git_show_state is not None:
        updates["git_show_state"] = "true" if git_show_state else "false"
    if battery_threshold is not None:
        battery_threshold = max(5, min(100, int(battery_threshold)))
        updates["battery_threshold"] = str(battery_threshold)

    if new_line is not None:
        updates["enable_command_on_new_line"] = "true" if new_line else "false"
    if vertical_padding is not None:
        updates["enable_vertical_padding"] = "true" if vertical_padding else "false"
    if max_pwd_char is not None:
        max_pwd_char = max(10, min(120, int(max_pwd_char)))
        updates["max_pwd_char"] = str(max_pwd_char)
    if max_git_char is not None:
        max_git_char = max(0, min(80, int(max_git_char)))
        updates["max_git_char"] = str(max_git_char)
    if max_pyenv_char is not None:
        max_pyenv_char = max(0, min(60, int(max_pyenv_char)))
        updates["max_pyenv_char"] = str(max_pyenv_char)
    if max_kube_char is not None:
        max_kube_char = max(0, min(60, int(max_kube_char)))
        updates["max_kube_char"] = str(max_kube_char)
    if compact_width is not None:
        compact_width = max(0, min(200, int(compact_width)))
        updates["compact_width"] = str(compact_width)
    if git_show_counts is not None:
        updates["git_show_counts"] = "true" if git_show_counts else "false"
    if transient_prompt is not None:
        updates["transient_prompt"] = "true" if transient_prompt else "false"
    if light_theme is not None and light_theme.strip():
        updates["synth_light_theme"] = light_theme.strip()
    if dark_theme is not None and dark_theme.strip():
        updates["synth_dark_theme"] = dark_theme.strip()
    if prompt_prefix is not None:
        updates["prompt_prefix"] = prompt_prefix
    if font_effect is not None:
        eff = font_effect.strip().lower()
        if eff not in VALID_FONT_EFFECTS:
            raise ValueError(f"Invalid font effect '{font_effect}'. Expected one of: {', '.join(VALID_FONT_EFFECTS)}")
        updates["font_effect_override"] = "" if eff == "bold" else ("none" if eff == "regular" else eff)
    if enable_terminal_title is not None:
        updates["enable_terminal_title"] = "true" if enable_terminal_title else "false"
    if git_skip_untracked_on_slow_fs is not None:
        updates["git_skip_untracked_on_slow_fs"] = "true" if git_skip_untracked_on_slow_fs else "false"
    if git_timeout_ms is not None:
        git_timeout_ms = max(0, min(10000, int(git_timeout_ms)))
        updates["git_timeout_ms"] = str(git_timeout_ms)
    if git_async_cache is not None:
        updates["git_async_cache"] = "true" if git_async_cache else "false"
    if min_duration_ms is not None:
        min_duration_ms = max(100, min(60000, int(min_duration_ms)))
        updates["min_duration_ms"] = str(min_duration_ms)

    bak = backup_config(base) if (create_backup and updates) else None
    if updates:
        lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
        new_lines = _upsert_kv_lines(lines, updates)
        _atomic_write(cfg, "\n".join(new_lines) + "\n")

    return {
        "format": clean_format,
        "right_format": clean_right_format,
        "right_fill_char": right_fill_char,
        "enable_osc133": enable_osc133,
        "enable_osc7": enable_osc7,
        "enable_terminal_sanitize": enable_terminal_sanitize,
        "kube_show_namespace": kube_show_namespace,
        "kube_prod_warning": kube_prod_warning,
        "kube_prod_pattern": kube_prod_pattern,
        "git_dynamic_color": git_dynamic_color,
        "ssh_host_color": ssh_host_color,
        "pwd_style": pwd_style,
        "notify_duration_sec": notify_duration_sec,
        "custom_segment_text": custom_segment_text,
        "git_show_state": git_show_state,
        "battery_threshold": battery_threshold,
        "enable_command_on_new_line": new_line,
        "enable_vertical_padding": vertical_padding,
        "max_pwd_char": max_pwd_char,
        "max_git_char": max_git_char,
        "max_pyenv_char": max_pyenv_char,
        "max_kube_char": max_kube_char,
        "compact_width": compact_width,
        "git_show_counts": git_show_counts,
        "transient_prompt": transient_prompt,
        "light_theme": light_theme,
        "dark_theme": dark_theme,
        "prompt_prefix": prompt_prefix,
        "font_effect": font_effect,
        "enable_terminal_title": enable_terminal_title,
        "git_skip_untracked_on_slow_fs": git_skip_untracked_on_slow_fs,
        "git_timeout_ms": git_timeout_ms,
        "git_async_cache": git_async_cache,
        "min_duration_ms": min_duration_ms,
        "backup": str(bak) if bak else None,
        "config_path": str(cfg),
    }


def apply_ascii_safe_mode(
    separator: str = ">",
    create_backup: bool = True,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Configure ASCII-safe separators and Git/truncation symbols for hosts without Nerd Fonts."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)

    if not cfg.is_file():
        themes = load_themes(config_dir=base)
        apply_theme(themes[1] if len(themes) > 1 else themes[0], create_backup=False, config_dir=base)

    bak = backup_config(base) if create_backup else None
    sep_clean = separator if separator in (">", "|", "/", "»") else ">"
    apply_separators(
        internal=(sep_clean, sep_clean),
        end=(sep_clean, sep_clean),
        create_backup=False,
        config_dir=base,
    )
    lines = cfg.read_text(encoding="utf-8", errors="replace").splitlines()
    new_lines = _upsert_kv_lines(lines, ASCII_SAFE_GIT_SYMBOLS)
    _atomic_write(cfg, "\n".join(new_lines) + "\n")
    return {
        "separator": sep_clean,
        "symbols_updated": len(ASCII_SAFE_GIT_SYMBOLS),
        "backup": str(bak) if bak else None,
        "config_path": str(cfg),
    }


def sync_root_config(
    theme: dict[str, object] | None = None,
    root_accent: str = "196",
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Generate/sync `synth-shell-prompt.root.config` matching active theme with a root warning accent."""
    base = config_dir if config_dir is not None else get_config_dir()
    root_cfg = get_root_config_path(base)
    catalog = load_themes(config_dir=base)
    state = read_current_state(catalog, base)

    if theme is None:
        active_id = state.get("active_theme_id")
        if isinstance(active_id, int) and 1 <= active_id <= len(catalog):
            theme = catalog[active_id - 1]
        else:
            tokyo, _ = find_theme("tokyo-night", catalog)
            theme = tokyo or catalog[0]

    theme_title = str(theme.get("name", "Active Theme"))
    int_code = str(state["internal_separator"]["code"])  # type: ignore[index]
    end_code = str(state["end_separator"]["code"])  # type: ignore[index]
    fmt = str(state.get("format") or "USER HOST PWD GIT")
    if "USER" not in fmt.split():
        fmt = f"USER {fmt}"

    lines = [
        f"# Root Prompt Sync — based on {theme_title} (synth-shell-theme)",
        f'format="{fmt}"',
        format_separator_assignment("separator_char", int_code),
        format_separator_assignment("separator_char_end", end_code),
        f'enable_vertical_padding="{"true" if state["enable_vertical_padding"] else "false"}"',
        f'enable_command_on_new_line="{"true" if state["enable_command_on_new_line"] else "false"}"',
        f'max_pwd_char="{state["max_pwd_char"]}"',
        "",
        "# High-visibility root warning accent on USER & HOST",
        'font_color_user="white"',
        f'background_user="{_escape_bash_dq(root_accent)}"',
        'texteffect_user="bold"',
        'font_color_host="white"',
        'background_host="52"',
        'texteffect_host="bold"',
        "",
        "# Remaining segments synced from active theme",
    ]
    for seg in SEGMENT_KEYS:
        if seg in ("user", "host", "input"):
            continue
        def_fg, def_bg = DEFAULT_SEGMENT_COLORS[seg]
        fg = str(theme.get(f"font_color_{seg}", def_fg))
        bg = str(theme.get(f"background_{seg}", def_bg))
        lines.append(f'font_color_{seg}="{_escape_bash_dq(fg)}"')
        lines.append(f'background_{seg}="{_escape_bash_dq(bg)}"')

    lines.extend(
        [
            f'font_color_input="{_escape_bash_dq(root_accent)}"',
            'background_input="none"',
            'texteffect_input="bold"',
        ]
    )
    _atomic_write(root_cfg, "\n".join(lines) + "\n")
    return {
        "theme": theme_title,
        "root_accent": root_accent,
        "root_config_path": str(root_cfg),
    }


def _system_has_swap() -> bool:
    """Return True if Linux `/proc/swaps` reports at least one active swap device."""
    swaps = Path("/proc/swaps")
    if not swaps.is_file():
        return True
    try:
        lines = [ln for ln in swaps.read_text(encoding="utf-8", errors="replace").splitlines() if ln.strip()]
        return len(lines) > 1
    except OSError:
        return True


def read_greeter_state(config_dir: Path | None = None) -> dict[str, object]:
    """Read current `synth-shell-greeter.config` monitors and format accents."""
    base = config_dir if config_dir is not None else get_config_dir()
    gcfg = get_greeter_config_path(base)
    monitors = list(DEFAULT_GREETER_MONITORS)
    formats: dict[str, str] = {}

    if gcfg.is_file():
        text = gcfg.read_text(encoding="utf-8", errors="replace")
        m_pi = re.search(r'print_info\s*=\s*"([^"]*)"', text, re.DOTALL)
        if m_pi:
            parsed = [tok.strip() for tok in m_pi.group(1).split() if tok.strip()]
            if parsed:
                monitors = parsed
        for key in ("format_info", "format_highlight", "format_crit", "format_deco", "format_ok", "format_error", "format_logo"):
            m_f = re.search(rf'^{key}\s*=\s*"([^"]*)"', text, re.MULTILINE)
            if m_f:
                formats[key] = " ".join(m_f.group(1).split())

    return {
        "config_exists": gcfg.is_file(),
        "config_path": str(gcfg),
        "monitors": monitors,
        "available_monitors": list(GREETER_ALL_MONITORS),
        "formats": formats,
        "has_swap": _system_has_swap(),
    }


def sync_greeter_theme(
    theme: dict[str, object] | None = None,
    monitors: list[str] | None = None,
    hide_swap_if_unavailable: bool = False,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Sync active prompt theme colors and/or monitor visibility into `synth-shell-greeter.config`."""
    base = config_dir if config_dir is not None else get_config_dir()
    gcfg = get_greeter_config_path(base)
    catalog = load_themes(config_dir=base)
    state = read_current_state(catalog, base)

    if theme is None:
        active_id = state.get("active_theme_id")
        if isinstance(active_id, int) and 1 <= active_id <= len(catalog):
            theme = catalog[active_id - 1]
        else:
            tokyo, _ = find_theme("tokyo-night", catalog)
            theme = tokyo or catalog[0]

    theme_title = str(theme.get("name", "Active Theme"))
    accent_primary = str(theme.get("background_host") or "blue")
    accent_ok = str(theme.get("background_git") or "green")
    accent_deco = str(theme.get("font_color_input") or theme.get("background_pwd") or "white")
    accent_crit = str(theme.get("background_tf") or "208")

    fmt_updates = {
        "format_info": "-c white",
        "format_highlight": f"-c {accent_primary} -e bold",
        "format_crit": f"-c {accent_crit} -e bold",
        "format_deco": f"-c {accent_deco} -e bold",
        "format_ok": f"-c {accent_ok} -e bold",
        "format_error": "-c 196 -e bold",
        "format_logo": f"-c {accent_primary} -e bold",
    }

    current_greeter = read_greeter_state(base)
    final_monitors = list(monitors) if monitors is not None else list(current_greeter["monitors"])  # type: ignore[arg-type]
    if hide_swap_if_unavailable and not _system_has_swap():
        final_monitors = [m for m in final_monitors if not m.startswith("SWAP_MON")]

    print_info_block = 'print_info="\n' + "\n".join(f"\t{m}" for m in final_monitors) + '\n"'

    if gcfg.is_file():
        bdir = get_backup_dir(base)
        bdir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        shutil.copy2(gcfg, bdir / f"{gcfg.name}.{stamp}.bak")
        text = gcfg.read_text(encoding="utf-8", errors="replace")
        if re.search(r'print_info\s*=\s*"[^"]*"', text, re.DOTALL):
            text = re.sub(r'print_info\s*=\s*"[^"]*"', lambda _: print_info_block, text, count=1, flags=re.DOTALL)
        else:
            text = text.rstrip() + "\n\n" + print_info_block + "\n"
        lines = _upsert_kv_lines(text.splitlines(), fmt_updates)
        _atomic_write(gcfg, "\n".join(lines) + "\n")
    else:
        header = [
            f"# Synth-Shell Greeter Config — synced with {theme_title} (synth-shell-theme)",
            "",
            print_info_block,
            "",
        ]
        for k, v in fmt_updates.items():
            header.append(f'{k}="{v}"')
        _atomic_write(gcfg, "\n".join(header) + "\n")

    return {
        "theme": theme_title,
        "config_path": str(gcfg),
        "monitors": final_monitors,
        "formats": fmt_updates,
    }


def export_preset(dest_path: Path, config_dir: Path | None = None) -> Path:
    """Export active colors, dual separators, layout, truncation, and speed options into a JSON preset."""
    state = read_current_state(config_dir=config_dir)
    payload = {
        "schema": "synth-shell-theme-preset/v2",
        "active_theme": state["active_theme"],
        "active_theme_id": state["active_theme_id"],
        "internal_separator": state["internal_separator"],
        "end_separator": state["end_separator"],
        "format": state["format"],
        "right_format": state["right_format"],
        "right_fill_char": state["right_fill_char"],
        "enable_osc133": state["enable_osc133"],
        "enable_osc7": state["enable_osc7"],
        "enable_terminal_sanitize": state["enable_terminal_sanitize"],
        "kube_show_namespace": state["kube_show_namespace"],
        "kube_prod_warning": state["kube_prod_warning"],
        "kube_prod_pattern": state["kube_prod_pattern"],
        "git_dynamic_color": state["git_dynamic_color"],
        "ssh_host_color": state["ssh_host_color"],
        "pwd_style": state["pwd_style"],
        "notify_duration_sec": state["notify_duration_sec"],
        "custom_segment_text": state["custom_segment_text"],
        "git_show_state": state["git_show_state"],
        "battery_threshold": state["battery_threshold"],
        "enable_command_on_new_line": state["enable_command_on_new_line"],
        "enable_vertical_padding": state["enable_vertical_padding"],
        "max_pwd_char": state["max_pwd_char"],
        "max_git_char": state["max_git_char"],
        "max_pyenv_char": state["max_pyenv_char"],
        "max_kube_char": state["max_kube_char"],
        "compact_width": state["compact_width"],
        "git_show_counts": state["git_show_counts"],
        "transient_prompt": state["transient_prompt"],
        "light_theme": state["light_theme"],
        "dark_theme": state["dark_theme"],
        "prompt_prefix": state["prompt_prefix"],
        "font_effect": state["font_effect"],
        "enable_terminal_title": state["enable_terminal_title"],
        "git_skip_untracked_on_slow_fs": state["git_skip_untracked_on_slow_fs"],
        "git_timeout_ms": state["git_timeout_ms"],
        "git_async_cache": state["git_async_cache"],
        "min_duration_ms": state["min_duration_ms"],
        "colors": state["colors"],
    }
    dest = Path(dest_path).expanduser()
    _atomic_write(dest, json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    return dest


def import_preset(src_path: Path, config_dir: Path | None = None) -> dict[str, object]:
    """Import and apply a JSON preset file (supports both v1 and v2 schemas)."""
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
        themes = load_themes(config_dir=base)
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
        right_format_str=str(data["right_format"]) if "right_format" in data else None,
        right_fill_char=str(data["right_fill_char"]) if "right_fill_char" in data else None,
        enable_osc133=bool(data["enable_osc133"]) if "enable_osc133" in data else None,
        enable_osc7=bool(data["enable_osc7"]) if "enable_osc7" in data else None,
        enable_terminal_sanitize=bool(data["enable_terminal_sanitize"]) if "enable_terminal_sanitize" in data else None,
        kube_show_namespace=bool(data["kube_show_namespace"]) if "kube_show_namespace" in data else None,
        kube_prod_warning=bool(data["kube_prod_warning"]) if "kube_prod_warning" in data else None,
        kube_prod_pattern=str(data["kube_prod_pattern"]) if "kube_prod_pattern" in data else None,
        git_dynamic_color=bool(data["git_dynamic_color"]) if "git_dynamic_color" in data else None,
        ssh_host_color=bool(data["ssh_host_color"]) if "ssh_host_color" in data else None,
        pwd_style=str(data["pwd_style"]) if "pwd_style" in data else None,
        notify_duration_sec=int(data["notify_duration_sec"]) if "notify_duration_sec" in data else None,
        custom_segment_text=str(data["custom_segment_text"]) if "custom_segment_text" in data else None,
        git_show_state=bool(data["git_show_state"]) if "git_show_state" in data else None,
        battery_threshold=int(data["battery_threshold"]) if "battery_threshold" in data else None,
        new_line=bool(data["enable_command_on_new_line"]) if "enable_command_on_new_line" in data else None,
        vertical_padding=bool(data["enable_vertical_padding"]) if "enable_vertical_padding" in data else None,
        max_pwd_char=int(data["max_pwd_char"]) if "max_pwd_char" in data else None,
        max_git_char=int(data["max_git_char"]) if "max_git_char" in data else None,
        max_pyenv_char=int(data["max_pyenv_char"]) if "max_pyenv_char" in data else None,
        max_kube_char=int(data["max_kube_char"]) if "max_kube_char" in data else None,
        compact_width=int(data["compact_width"]) if "compact_width" in data else None,
        git_show_counts=bool(data["git_show_counts"]) if "git_show_counts" in data else None,
        transient_prompt=bool(data["transient_prompt"]) if "transient_prompt" in data else None,
        light_theme=str(data["light_theme"]) if "light_theme" in data else None,
        dark_theme=str(data["dark_theme"]) if "dark_theme" in data else None,
        prompt_prefix=str(data["prompt_prefix"]) if "prompt_prefix" in data else None,
        font_effect=str(data["font_effect"]) if "font_effect" in data else None,
        enable_terminal_title=bool(data["enable_terminal_title"]) if "enable_terminal_title" in data else None,
        git_skip_untracked_on_slow_fs=(
            bool(data["git_skip_untracked_on_slow_fs"]) if "git_skip_untracked_on_slow_fs" in data else None
        ),
        git_timeout_ms=int(data["git_timeout_ms"]) if "git_timeout_ms" in data else None,
        git_async_cache=bool(data["git_async_cache"]) if "git_async_cache" in data else None,
        min_duration_ms=int(data["min_duration_ms"]) if "min_duration_ms" in data else None,
        create_backup=False,
        config_dir=base,
    )
    return {
        "imported_from": str(src),
        "backup": str(bak) if bak else None,
        "state": read_current_state(config_dir=base),
    }


def toggle_light_dark_theme(
    light_slug: str | None = None,
    dark_slug: str | None = None,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Toggle between the configured Light and Dark theme pair in 1 command."""
    base = config_dir if config_dir is not None else get_config_dir()
    catalog = load_themes(config_dir=base)
    state = read_current_state(catalog, base)

    light_choice = (light_slug or str(state.get("light_theme") or "catppuccin-latte")).strip()
    dark_choice = (dark_slug or str(state.get("dark_theme") or "tokyo-night")).strip()

    light_t, _ = find_theme(light_choice, catalog)
    dark_t, _ = find_theme(dark_choice, catalog)
    if not light_t:
        raise ValueError(f"Light theme not found: {light_choice}")
    if not dark_t:
        raise ValueError(f"Dark theme not found: {dark_choice}")

    active_name = str(state.get("active_theme") or "").lower()
    is_currently_light = (
        active_name == str(light_t.get("name", "")).lower()
        or "latte" in active_name
        or "light" in active_name
    )
    target_theme = dark_t if is_currently_light else light_t
    target_mode = "dark" if is_currently_light else "light"

    res = apply_theme(target_theme, config_dir=base)
    apply_layout_options(
        light_theme=str(light_t.get("slug") or light_choice),
        dark_theme=str(dark_t.get("slug") or dark_choice),
        create_backup=False,
        config_dir=base,
    )
    return {
        "mode": target_mode,
        "theme": res["theme"],
        "theme_id": res["theme_id"],
        "light_theme": str(light_t.get("name")),
        "dark_theme": str(dark_t.get("name")),
        "backup": res["backup"],
        "config_path": res["config_path"],
    }


def apply_auto_system_theme(
    light_theme: str | None = None,
    dark_theme: str | None = None,
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Detect OS dark/light preference and apply the corresponding configured theme."""
    from synth_shell_theme.paths import detect_system_color_scheme

    base = config_dir if config_dir is not None else get_config_dir()
    catalog = load_themes(config_dir=base)
    state = read_current_state(catalog, base)

    scheme = detect_system_color_scheme()
    light_choice = light_theme or str(state.get("light_theme") or "catppuccin-latte")
    dark_choice = dark_theme or str(state.get("dark_theme") or "tokyo-night")
    target_slug = light_choice if scheme == "light" else dark_choice
    found, _ = find_theme(target_slug, catalog)
    target_theme = found or catalog[0]

    res = apply_theme(target_theme, config_dir=base)
    return {
        "detected_scheme": scheme,
        "theme": res["theme"],
        "theme_id": res["theme_id"],
        "backup": res["backup"],
        "config_path": res["config_path"],
    }


def benchmark_prompt(
    iterations: int = 15,
    config_dir: Path | None = None,
    cwd: Path | None = None,
) -> dict[str, object]:
    """Measure live Bash `prompt_command_hook` latency (min, p50, p95, max in ms)."""
    base = config_dir if config_dir is not None else get_config_dir()
    prompt_sh = get_prompt_script_path(base)
    runs = max(3, min(100, int(iterations)))

    if not prompt_sh.is_file():
        return {
            "ok": False,
            "error": f"Prompt script not found: {prompt_sh}",
            "iterations": 0,
            "patches": inspect_patches(base),
        }

    if shutil.which("bash") is None:
        return {
            "ok": False,
            "error": "Bash executable not found on PATH.",
            "iterations": 0,
            "patches": inspect_patches(base),
        }

    probe = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, check=False)
    if probe.returncode != 0:
        return {
            "ok": False,
            "error": "Bash is unavailable on this host.",
            "iterations": 0,
            "patches": inspect_patches(base),
        }

    raw_script = prompt_sh.read_text(encoding="utf-8", errors="replace")
    stripped = "\n".join(
        ln for ln in raw_script.splitlines() if "synth-shell-theme: interactive_guard" not in ln
    )
    # Replace the interactive source check at the bottom so benchmark can invoke synth_shell_prompt() cleanly
    stripped = re.sub(
        r'elif \[ -n "\$\( echo \$- \| grep i \)" \]; then',
        "elif true; then",
        stripped,
    )

    with tempfile.TemporaryDirectory(prefix="synth-shell-bench-") as tmp:
        bench_sh = Path(tmp) / "bench_prompt.sh"
        bench_sh.write_text(stripped + "\n", encoding="utf-8", newline="\n")
        driver = (
            f"source {shlex.quote(str(bench_sh))} >/dev/null 2>&1; "
            'declare -F prompt_command_hook >/dev/null 2>&1 || exit 2; '
            "prompt_command_hook; "  # warm-up
            f"for ((i=0; i<{runs}; i++)); do "
            't0="${EPOCHREALTIME:-}"; '
            "prompt_command_hook; "
            't1="${EPOCHREALTIME:-}"; '
            'if [[ -n "$t0" && -n "$t1" ]]; then '
            'echo "$(( (${t1/[.,]/} - ${t0/[.,]/}) ))"; '
            "else echo 0; fi; "
            "done"
        )
        bench_env = dict(os.environ)
        bench_env["LC_NUMERIC"] = "C"
        if not bench_env.get("TERM") or bench_env.get("TERM") == "dumb":
            bench_env["TERM"] = "xterm-256color"
        t_wall0 = time.perf_counter()
        proc = subprocess.run(
            ["bash", "-c", driver],
            cwd=str(cwd) if cwd else None,
            env=bench_env,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
        t_wall_ms = (time.perf_counter() - t_wall0) * 1000.0

    if proc.returncode != 0:
        return {
            "ok": False,
            "error": (proc.stderr or "Failed to execute prompt_command_hook").strip(),
            "iterations": 0,
            "patches": inspect_patches(base),
        }

    samples_ms: list[float] = []
    for ln in proc.stdout.splitlines():
        s = ln.strip()
        if s.isdigit() and int(s) > 0:
            samples_ms.append(int(s) / 1000.0)

    if not samples_ms:
        per_run = round(t_wall_ms / runs, 2)
        samples_ms = [per_run] * runs

    samples_ms.sort()
    p50 = round(statistics.median(samples_ms), 2)
    p95_idx = min(len(samples_ms) - 1, int(round(0.95 * (len(samples_ms) - 1))))
    p95 = round(samples_ms[p95_idx], 2)

    return {
        "ok": True,
        "iterations": len(samples_ms),
        "min_ms": round(samples_ms[0], 2),
        "p50_ms": p50,
        "p95_ms": p95,
        "max_ms": round(samples_ms[-1], 2),
        "cwd": str(cwd or Path.cwd()),
        "patches": inspect_patches(base),
    }


def generate_bash_completion(config_dir: Path | None = None) -> str:
    """Generate a self-contained Bash tab-completion script for `synth-shell-theme` & `synth-shell-separator`."""
    themes = load_themes(config_dir=config_dir)
    theme_slugs = " ".join(str(t.get("slug", "")) for t in themes if t.get("slug"))
    sep_keys = " ".join(key for key, *_ in ALL_PRESETS)
    seg_tokens = " ".join(VALID_FORMAT_TOKENS)
    effects = " ".join(VALID_FONT_EFFECTS)

    return f"""# Bash completion for synth-shell-theme & synth-shell-separator
# Activate with: eval "$(synth-shell-theme completion bash)"
_synth_shell_theme_complete()
{{
    local cur prev words cword
    cur="${{COMP_WORDS[COMP_CWORD]}}"
    prev="${{COMP_WORDS[COMP_CWORD-1]}}"

    local subcmds="tui web studio sep init doctor bench export import import-theme export-web export-starship ssh-install completion"
    local opts="--version --list --current --apply --force-white-text --keep-input --separators --palette --separator --dual --internal --end --format --right-format --right-fill --osc133 --no-osc133 --osc7 --no-osc7 --terminal-sanitize --no-terminal-sanitize --kube-ns --no-kube-ns --kube-prod-warn --no-kube-prod-warn --kube-prod-pattern --git-dynamic-color --no-git-dynamic-color --ssh-host-color --no-ssh-host-color --pwd-style --notify-sec --custom-badge --git-state --no-git-state --battery-threshold --two-line --single-line --max-pwd --max-git --max-pyenv --max-kube --compact-width --prefix --text-effect --terminal-title --no-terminal-title --fast-git-wsl --no-fast-git-wsl --git-timeout --async-git --no-async-git --git-counts --no-git-counts --min-duration --transient --no-transient --ascii-safe --toggle-theme --auto-theme --light-theme --dark-theme --sync-root --sync-greeter --sync-ecosystem --greeter-monitors --hide-swap --random --search --web --port --no-browser --backup --backups --restore --no-clear"
    local themes="{theme_slugs}"
    local seps="{sep_keys}"
    local segs="{seg_tokens}"
    local effects="{effects}"

    case "$prev" in
        -a|--apply|--light-theme|--dark-theme)
            COMPREPLY=( $(compgen -W "$themes" -- "$cur") )
            return 0
            ;;
        -t|--separator|-i|--internal|-e|--end|-d|--dual)
            COMPREPLY=( $(compgen -W "$seps" -- "$cur") )
            return 0
            ;;
        --text-effect)
            COMPREPLY=( $(compgen -W "$effects" -- "$cur") )
            return 0
            ;;
        --format)
            COMPREPLY=( $(compgen -W "$segs" -- "$cur") )
            return 0
            ;;
        completion)
            COMPREPLY=( $(compgen -W "bash" -- "$cur") )
            return 0
            ;;
    esac

    if [[ "$COMP_CWORD" -eq 1 && "$cur" != -* ]]; then
        COMPREPLY=( $(compgen -W "$subcmds" -- "$cur") )
        return 0
    fi
    COMPREPLY=( $(compgen -W "$opts" -- "$cur") )
}}
complete -F _synth_shell_theme_complete synth-shell-theme synth-shell-separator
"""


def doctor_fix(
    config_dir: Path | None = None,
    auto_ascii: bool = False,
) -> dict[str, object]:
    """Auto-repair common synth-shell issues: apply pending patches, fix CRLF line endings, optional ASCII fallback."""
    from synth_shell_theme.paths import detect_nerd_fonts, detect_utf8_locale

    base = config_dir if config_dir is not None else get_config_dir()
    actions: list[str] = []

    # 1. Normalize CRLF -> LF on managed shell scripts and configs
    for fname in (
        "synth-shell-prompt.sh",
        "synth-shell-prompt.config",
        "synth-shell-prompt.root.config",
        "alias.sh",
        "better-ls.sh",
        "better-history.sh",
        "synth-shell-greeter.sh",
        "synth-shell-greeter.config",
    ):
        fpath = base / fname
        if not fpath.is_file():
            continue
        raw = fpath.read_bytes()
        if b"\r\n" in raw:
            fpath.write_bytes(raw.replace(b"\r\n", b"\n"))
            actions.append(f"normalized_lf:{fname}")

    # 2. Apply all missing runtime patches
    patch_res = apply_runtime_patches(config_dir=base, tune_defaults=False)
    for ch in patch_res["changes"]:  # type: ignore[union-attr]
        actions.append(f"patch:{ch}")

    # 3. Optional ASCII-safe fallback if locale is not UTF-8 or no Nerd Fonts detected
    loc = detect_utf8_locale()
    nf = detect_nerd_fonts()
    if auto_ascii and (not loc.get("utf8") or not nf.get("detected")):
        apply_ascii_safe_mode(config_dir=base)
        actions.append("applied:ascii_safe_fallback")

    return {
        "actions": actions,
        "patches": patch_res["status"],
        "locale_utf8": bool(loc.get("utf8")),
        "nerd_fonts_detected": bool(nf.get("detected")),
    }


def export_static_studio(dest_path: Path, config_dir: Path | None = None) -> Path:
    """Build a standalone static HTML demo of the Web Studio (ideal for GitHub Pages)."""
    from synth_shell_theme import __version__
    from synth_shell_theme.paths import get_assets_dir
    from synth_shell_theme.separators import serialize_separators_for_web
    from synth_shell_theme.themes import serialize_theme_for_web

    studio_src = (get_assets_dir() / "studio.html").read_text(encoding="utf-8")
    catalog = load_themes(include_user_themes=False)
    serialized = [serialize_theme_for_web(t, idx) for idx, t in enumerate(catalog, 1)]
    static_boot = {
        "static_demo": True,
        "version": __version__,
        "themes": serialized,
        "separators": serialize_separators_for_web(),
        "valid_segments": list(VALID_FORMAT_TOKENS),
        "valid_font_effects": list(VALID_FONT_EFFECTS),
        "state": {
            "active_theme": "Tokyo Night",
            "active_theme_id": 12,
            "internal_separator": {"glyph": "\ue0b4", "code": "\\uE0B4", "key": "round"},
            "end_separator": {"glyph": "\ue0b0", "code": "\\uE0B0", "key": "arrow", "explicit": True},
            "format": "HOST PWD GIT PYENV TF",
            "format_segments": ["HOST", "PWD", "GIT", "PYENV", "TF"],
            "right_format": "KUBE DURATION CLOCK",
            "right_format_segments": ["KUBE", "DURATION", "CLOCK"],
            "right_fill_char": "─",
            "enable_osc133": True,
            "enable_osc7": True,
            "enable_terminal_sanitize": True,
            "kube_show_namespace": True,
            "kube_prod_warning": True,
            "kube_prod_pattern": "prod|production|prd|live",
            "git_dynamic_color": False,
            "ssh_host_color": False,
            "pwd_style": "default",
            "notify_duration_sec": 0,
            "custom_segment_text": "",
            "git_show_state": True,
            "battery_threshold": 100,
            "enable_command_on_new_line": True,
            "enable_vertical_padding": True,
            "max_pwd_char": 35,
            "max_git_char": 0,
            "max_pyenv_char": 0,
            "max_kube_char": 28,
            "compact_width": 90,
            "git_show_counts": True,
            "transient_prompt": False,
            "prompt_prefix": "",
            "font_effect": "bold",
            "enable_terminal_title": True,
            "git_skip_untracked_on_slow_fs": True,
            "git_timeout_ms": 0,
            "git_async_cache": False,
            "min_duration_ms": 2000,
            "root_config_exists": True,
            "patches": {
                "kube_fast": True,
                "kube_namespace_prod": True,
                "git_single_pass": True,
                "git_wsl_fast": True,
                "git_ahead_behind_counts": True,
                "git_advanced_state": True,
                "dual_separator": True,
                "color_256_parity": True,
                "truecolor_24bit": True,
                "zero_fork_render": True,
                "v11_segments": True,
                "v12_segments": True,
                "v13_segments": True,
                "osc133_semantic": True,
                "osc7_cwd": True,
                "v139_smart_features": True,
                "terminal_sanitize": True,
                "right_prompt": True,
                "responsive_width": True,
                "hook_chaining": True,
                "pyenv_enhanced": True,
                "utf8_ps1_guard": True,
                "interactive_guard": True,
            },
        },
        "greeter": {
            "config_exists": True,
            "monitors": list(DEFAULT_GREETER_MONITORS),
            "available_monitors": list(GREETER_ALL_MONITORS),
            "has_swap": True,
        },
        "diagnostics": {
            "locale": {"utf8": True, "effective": "en_US.UTF-8"},
            "nerd_fonts": {"detected": True, "count": 4, "samples": ["JetBrainsMono Nerd Font", "FiraCode Nerd Font"]},
            "terminal": {"term": "xterm-256color", "colorterm": "truecolor", "truecolor": True, "term_256": True},
        },
        "backups": [],
    }
    boot_json = json.dumps(static_boot, ensure_ascii=False).replace("</", "<\\/")
    inject = f"<script>window.__SYNTH_STATIC_BOOTSTRAP__ = {boot_json};</script>\n</head>"
    out_html = studio_src.replace("</head>", inject, 1)
    dest = Path(dest_path).expanduser()
    _atomic_write(dest, out_html)
    return dest
