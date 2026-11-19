"""Cross-platform path discovery and terminal environment helpers for synth-shell-theme."""

from __future__ import annotations

import os
import platform
import shutil
import sys
from pathlib import Path


def detect_os() -> str:
    """Return normalized OS identifier ('linux', 'macos', or 'windows')."""
    plat = sys.platform.lower()
    if plat.startswith("win"):
        return "windows"
    if plat == "darwin":
        return "macos"
    return "linux"


def setup_console() -> None:
    """Configure UTF-8 console output and enable ANSI VT100 sequences on Windows if needed."""
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:
                pass

    if sys.platform.startswith("win"):
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
            handle = kernel32.GetStdHandle(-11)  # STD_OUTPUT_HANDLE
            mode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                kernel32.SetConsoleMode(handle, mode.value | 0x0004)
        except Exception:
            pass


def get_config_dir() -> Path:
    """Return the synth-shell configuration directory (overridable via SYNTH_SHELL_CONFIG_DIR)."""
    override = os.environ.get("SYNTH_SHELL_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "synth-shell"


def get_config_path(config_dir: Path | None = None) -> Path:
    """Return the path to `synth-shell-prompt.config`."""
    base = config_dir if config_dir is not None else get_config_dir()
    return base / "synth-shell-prompt.config"


def get_prompt_script_path(config_dir: Path | None = None) -> Path:
    """Return the path to `synth-shell-prompt.sh`."""
    base = config_dir if config_dir is not None else get_config_dir()
    return base / "synth-shell-prompt.sh"


def get_backup_dir(config_dir: Path | None = None) -> Path:
    """Return the directory used for timestamped configuration backups."""
    base = config_dir if config_dir is not None else get_config_dir()
    return base / "backups"


def get_package_dir() -> Path:
    """Return the installed package root directory."""
    return Path(__file__).resolve().parent


def get_themes_dir() -> Path:
    """Return the bundled `themes/` directory containing the 64 `.conf` files."""
    return get_package_dir() / "themes"


def get_assets_dir() -> Path:
    """Return the bundled `assets/` directory containing `studio.html`."""
    return get_package_dir() / "assets"


def system_summary(config_dir: Path | None = None) -> dict[str, object]:
    """Return environment and installation diagnostics for `synth-shell-theme doctor`."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    prompt_sh = get_prompt_script_path(base)
    bdir = get_backup_dir(base)
    backups = sorted(bdir.glob("synth-shell-prompt.config.*.bak")) if bdir.is_dir() else []

    return {
        "os": detect_os(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "config_dir": str(base),
        "config_path": str(cfg),
        "config_exists": cfg.is_file(),
        "prompt_script_path": str(prompt_sh),
        "prompt_script_exists": prompt_sh.is_file(),
        "backup_dir": str(bdir),
        "backup_count": len(backups),
        "bash_found": shutil.which("bash") is not None,
        "git_found": shutil.which("git") is not None,
        "themes_dir": str(get_themes_dir()),
        "bundled_themes": len(list(get_themes_dir().glob("*.conf"))),
    }
