"""Cross-platform path discovery, font/locale diagnostics, and terminal helpers for synth-shell-theme."""

from __future__ import annotations

import locale
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

_NERD_FONT_TOKENS = (
    "nerd",
    "powerline",
    "meslolgs",
    "caskaydia",
    "firacode",
    "jetbrainsmono",
    "hack nerd",
    "blexmono",
    "iosevka nf",
    "symbols nerd",
    " nf",
    " nfm",
    " nfp",
    " pl",
)


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


def get_root_config_path(config_dir: Path | None = None) -> Path:
    """Return the path to `synth-shell-prompt.root.config`."""
    base = config_dir if config_dir is not None else get_config_dir()
    return base / "synth-shell-prompt.root.config"


def get_prompt_script_path(config_dir: Path | None = None) -> Path:
    """Return the path to `synth-shell-prompt.sh`."""
    base = config_dir if config_dir is not None else get_config_dir()
    return base / "synth-shell-prompt.sh"


def get_greeter_config_path(config_dir: Path | None = None) -> Path:
    """Return the path to `synth-shell-greeter.config` (or legacy `status.config` if present)."""
    base = config_dir if config_dir is not None else get_config_dir()
    primary = base / "synth-shell-greeter.config"
    legacy = base / "status.config"
    if primary.is_file() or not legacy.is_file():
        return primary
    return legacy


def get_greeter_script_path(config_dir: Path | None = None) -> Path:
    """Return the path to `synth-shell-greeter.sh` (or legacy `status.sh` if present)."""
    base = config_dir if config_dir is not None else get_config_dir()
    primary = base / "synth-shell-greeter.sh"
    legacy = base / "status.sh"
    if primary.is_file() or not legacy.is_file():
        return primary
    return legacy


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


def get_user_themes_dir(config_dir: Path | None = None) -> Path:
    """Return the user custom themes directory (`~/.config/synth-shell/themes`)."""
    base = config_dir if config_dir is not None else get_config_dir()
    return base / "themes"


def get_assets_dir() -> Path:
    """Return the bundled `assets/` directory containing `studio.html`."""
    return get_package_dir() / "assets"


def detect_terminal_capabilities(nerd_fonts: dict[str, object] | None = None) -> dict[str, object]:
    """Inspect TERM, COLORTERM (24-bit TrueColor), TERM_PROGRAM (VS Code), tmux, and ble.sh."""
    term = os.environ.get("TERM", "")
    colorterm = os.environ.get("COLORTERM", "")
    term_program = os.environ.get("TERM_PROGRAM", "")
    in_tmux = bool(os.environ.get("TMUX"))
    truecolor = colorterm.lower() in ("truecolor", "24bit")
    term_256 = "256color" in term.lower() or "truecolor" in term.lower() or truecolor
    blesh_installed = bool(os.environ.get("BLE_VERSION")) or (Path.home() / ".local" / "share" / "blesh" / "ble.sh").is_file()

    nf = nerd_fonts if nerd_fonts is not None else detect_nerd_fonts()
    samples = list(nf.get("samples", [])) if isinstance(nf, dict) else []  # type: ignore[arg-type]
    rec_font = str(samples[0]) if samples else "CaskaydiaCove Nerd Font"

    return {
        "term": term or "unset",
        "colorterm": colorterm or "unset",
        "truecolor": truecolor,
        "term_256": term_256,
        "term_program": term_program or "unknown",
        "is_vscode": term_program.lower() == "vscode",
        "in_tmux": in_tmux,
        "blesh_detected": blesh_installed,
        "vscode_font_setting": f'"terminal.integrated.fontFamily": "{rec_font}"',
    }


def detect_utf8_locale() -> dict[str, object]:
    """Inspect active shell locale variables and encoding to determine UTF-8 readiness."""
    lc_all = os.environ.get("LC_ALL", "")
    lc_ctype = os.environ.get("LC_CTYPE", "")
    lang = os.environ.get("LANG", "")
    preferred = locale.getpreferredencoding(False) or ""

    effective = lc_all or lc_ctype or lang
    norm_eff = effective.lower().replace("-", "")
    norm_pref = preferred.lower().replace("-", "")

    if effective:
        is_utf8 = "utf8" in norm_eff
    else:
        is_utf8 = "utf8" in norm_pref

    return {
        "utf8": is_utf8,
        "encoding": preferred,
        "effective": effective or preferred or "unknown",
        "lang": lang,
        "lc_all": lc_all,
        "lc_ctype": lc_ctype,
    }


def _matches_nerd_font(name: str) -> bool:
    low = name.lower()
    return any(tok in low for tok in _NERD_FONT_TOKENS)


def detect_nerd_fonts() -> dict[str, object]:
    """Scan local font registry/directories for installed Nerd Font or Powerline fonts."""
    matches: list[str] = []
    seen: set[str] = set()
    os_name = detect_os()

    def _add(font_name: str) -> None:
        clean = font_name.strip()
        if not clean:
            return
        key = clean.lower()
        if key not in seen and _matches_nerd_font(clean):
            seen.add(key)
            matches.append(clean)

    fc_list = shutil.which("fc-list")
    if fc_list:
        try:
            proc = subprocess.run(
                [fc_list, ":", "family"],
                capture_output=True,
                text=True,
                timeout=2.5,
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    for fam in line.split(","):
                        _add(fam)
        except Exception:
            pass

    if not matches:
        font_dirs: list[Path] = []
        if os_name == "macos":
            font_dirs = [Path.home() / "Library" / "Fonts", Path("/Library/Fonts")]
        elif os_name == "windows":
            local_app = os.environ.get("LOCALAPPDATA", "")
            if local_app:
                font_dirs.append(Path(local_app) / "Microsoft" / "Windows" / "Fonts")
            font_dirs.append(Path("C:/Windows/Fonts"))
        else:
            font_dirs = [
                Path.home() / ".local" / "share" / "fonts",
                Path.home() / ".fonts",
                Path("/usr/local/share/fonts"),
                Path("/usr/share/fonts"),
            ]

        for fdir in font_dirs:
            if not fdir.is_dir():
                continue
            try:
                for root, _dirs, files in os.walk(fdir):
                    for fname in files:
                        if fname.lower().endswith((".ttf", ".otf", ".ttc")):
                            _add(Path(fname).stem)
                            if len(matches) >= 30:
                                break
                    if len(matches) >= 30:
                        break
            except OSError:
                continue

    matches.sort()
    return {
        "detected": bool(matches),
        "count": len(matches),
        "samples": matches[:6],
    }


def detect_system_color_scheme() -> str:
    """Detect OS dark/light preference (`'dark'` or `'light'`, defaulting to `'dark'`)."""
    os_name = detect_os()
    if os_name == "macos":
        try:
            r = subprocess.run(
                ["defaults", "read", "-g", "AppleInterfaceStyle"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            return "dark" if r.returncode == 0 and "dark" in r.stdout.lower() else "light"
        except (OSError, subprocess.SubprocessError):
            return "dark"
    if os_name == "windows":
        try:
            import winreg  # type: ignore[import-not-found]

            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
            )
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            winreg.CloseKey(key)
            return "light" if int(val) == 1 else "dark"
        except Exception:
            return "dark"
    # Linux: GNOME gsettings -> KDE kdeglobals fallback
    if shutil.which("gsettings"):
        try:
            r = subprocess.run(
                ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
                capture_output=True,
                text=True,
                timeout=1.5,
                check=False,
            )
            out = r.stdout.strip().lower()
            if "light" in out:
                return "light"
            if "dark" in out:
                return "dark"
        except (OSError, subprocess.SubprocessError):
            pass
    kde_cfg = Path.home() / ".config" / "kdeglobals"
    if kde_cfg.is_file():
        try:
            txt = kde_cfg.read_text(encoding="utf-8", errors="replace").lower()
            if "breezelight" in txt or "colorscheme=light" in txt:
                return "light"
        except OSError:
            pass
    return "dark"


def system_summary(config_dir: Path | None = None) -> dict[str, object]:
    """Return environment and installation diagnostics for `synth-shell-theme doctor`."""
    base = config_dir if config_dir is not None else get_config_dir()
    cfg = get_config_path(base)
    root_cfg = get_root_config_path(base)
    prompt_sh = get_prompt_script_path(base)
    greeter_cfg = get_greeter_config_path(base)
    greeter_sh = get_greeter_script_path(base)
    bdir = get_backup_dir(base)
    backups = sorted(bdir.glob("synth-shell-prompt.config.*.bak")) if bdir.is_dir() else []

    nf = detect_nerd_fonts()
    return {
        "os": detect_os(),
        "platform": platform.platform(),
        "python": sys.version.split()[0],
        "config_dir": str(base),
        "config_path": str(cfg),
        "config_exists": cfg.is_file(),
        "root_config_path": str(root_cfg),
        "root_config_exists": root_cfg.is_file(),
        "prompt_script_path": str(prompt_sh),
        "prompt_script_exists": prompt_sh.is_file(),
        "greeter_config_path": str(greeter_cfg),
        "greeter_config_exists": greeter_cfg.is_file(),
        "greeter_script_path": str(greeter_sh),
        "greeter_script_exists": greeter_sh.is_file(),
        "backup_dir": str(bdir),
        "backup_count": len(backups),
        "bash_found": shutil.which("bash") is not None,
        "git_found": shutil.which("git") is not None,
        "themes_dir": str(get_themes_dir()),
        "user_themes_dir": str(get_user_themes_dir(base)),
        "bundled_themes": len(list(get_themes_dir().glob("*.conf"))),
        "custom_themes": len(list(get_user_themes_dir(base).glob("*.conf"))) if get_user_themes_dir(base).is_dir() else 0,
        "locale": detect_utf8_locale(),
        "nerd_fonts": nf,
        "terminal": detect_terminal_capabilities(nf),
        "system_theme": detect_system_color_scheme(),
    }
