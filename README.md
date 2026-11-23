# ✦ Synth-Shell Theme Studio (`synth-shell-theme`)

[![CI](https://github.com/mvsoares/synth-shell-theme/actions/workflows/ci.yml/badge.svg)](https://github.com/mvsoares/synth-shell-theme/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/synth-shell-theme?color=3775A9&logo=pypi&logoColor=white)](https://pypi.org/project/synth-shell-theme/)
[![Release](https://img.shields.io/github/v/release/mvsoares/synth-shell-theme?color=8b5cf6)](https://github.com/mvsoares/synth-shell-theme/releases)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux%20%7C%20macOS%20%7C%20Windows-0ea5e9)](https://github.com/mvsoares/synth-shell-theme)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e)](https://github.com/mvsoares/synth-shell-theme/blob/main/LICENSE)

Interactive **256-color Prompt Theme Picker (64 themes)**, **Dual Powerline Separator Editor (48 presets + 60+ Nerd Font glyphs)**, **Runtime Speed Optimizer**, and **Live Web Studio** for [synth-shell](https://github.com/andresgongora/synth-shell).

Built with **100% Python `>= 3.10` standard library** — **zero external runtime dependencies**.

<p align="center">
  <img src="https://raw.githubusercontent.com/mvsoares/synth-shell-theme/main/docs/screenshots/hero-prompt-showcase.png" alt="Synth-Shell Theme Studio — Curated 256-Color Prompt Palettes and Dual Powerline Separators" width="100%" />
</p>

---

## Features

- **64 Curated 256-Color Prompt Themes**: From *Tokyo Night*, *Catppuccin Mocha/Latte/Frappé/Mauve*, *Dracula Punch*, *Rose Pine*, *Kanagawa*, *Everforest*, *Gruvbox*, and *Cyberpunk Edgerunners* to *Cloud Ops*, *GitHub Dark*, and *Minimal Mono*.
- **Side-by-Side Terminal UI (`synth-shell-theme`)**: 2-column 256-color live terminal preview rendering both 3-segment and 6-segment DevOps prompts (`host · pwd · git · pyenv · tf · kube`), live search (`/term`), high-contrast white-text mode (`[f]`), and 1-key undo (`[u]`).
- **Dual Powerline Separator Editor (`synth-shell-separator` or `synth-shell-theme sep`)**: Mix independent **internal** (`separator_char`) and **ending** (`separator_char_end`) glyphs across **48 curated presets** in 6 categories plus a **60+ Nerd Font Character Matrix**.
- **Live Browser Web Studio (`synth-shell-theme web`)**: Local HTTP studio (`http://127.0.0.1:7778`) with a sticky live prompt workbench, category badge filtering, 1-click theme & dual-separator application, segment order toggles (`USER HOST PWD GIT PYENV TF KUBE CLOCK`), and backup history.
- **4+ Idempotent Runtime, Speed & Safety Patches (`synth-shell-theme init`)**:
  1. **Zero-fork segment renderer (`zero_fork_render`)**: Eliminates ~15–25 subshell forks per `Enter` via pure-Bash color/format variable lookups.
  2. **Zero-subshell Kubernetes context (`kube_fast`)**: Reads `$KUBECONFIG` / `~/.kube/config` directly in pure Bash (<1 ms, removes `yq` dependency, shortens GKE context names, respects `max_kube_char`).
  3. **Single-pass Git + WSL2/Monorepo engine (`git_single_pass` / `git_wsl_fast`)**: Consolidates 3 `git status` calls into one, auto-skips untracked scans on WSL2 `/mnt/*`, supports `--git-timeout`, optional `--async-git` background cache (`/dev/shm`), and `--max-git` branch truncation.
  4. **Telemetry & Cloud segments (`v11_segments`)**: Zero-fork `STATUS` (non-zero exit code), `DURATION` (`PS0` + `$EPOCHREALTIME` timer), `AWS`, `GCP`, `DOCKER`, `NODE`, and `SSH`/`CONTAINER`, plus `prompt_prefix`, `font_effect` (`bold`/`regular`/`italic`/`dim`), and OSC-0 terminal tab titles.
  5. **Accurate Virtualenv & Conda (`pyenv_enhanced`)**: Pure-Bash `$VIRTUAL_ENV_PROMPT`, `pyvenv.cfg` `prompt`, `$CONDA_DEFAULT_ENV`, parent-dir naming for `.venv`, and `--max-pyenv` truncation.
  6. **Independent Ending Separator (`dual_separator`) & 256-Color Parity (`color_256_parity`)**: Supports `separator_char_end`, 0–255 & all 16 named colors, and `italic`/`regular` text styles.
  7. **Safe `PROMPT_COMMAND` Chaining & TrueColor 24-bit (`hook_chaining` / `truecolor_24bit`)**: Chains `PROMPT_COMMAND` (Bash 5.1+ arrays & strings) and moves color reset to `PS0` (no `trap DEBUG` hijacking — 100% compatible with `direnv`, `zoxide`, `atuin`, `ble.sh`, `mise`, and VS Code), supports exact `#RRGGBB` TrueColor with automatic 256-color fallback, responsive compact layout on narrow `tmux`/VS Code splits (`--compact-width`), exact Git `↑N ↓M` counts, `JOBS`/`DIRENV`/`SHLVL`/`RUST`/`GO` segments, and `set -u` safety.
  8. **Unicode `PS1` Guard (`utf8_ps1_guard`), Non-Interactive Safety (`interactive_guard`) & Greeter Fixes**: Prevents `\uE0B0` turning into `usernameE0B0` under `LC_ALL=C`, protects `scp`/`sftp`/`rsync`, adds `--ascii-safe`, `--sync-root`, `--sync-greeter`, plus AMD `k10temp`/`Tctl` CPU temp & ZFS ARC RAM fixes for `synth-shell-greeter`.
- **Safe Atomic Writes & Backups**: Preserves your custom layout, padding, and Git symbols when switching colors, with automatic timestamped backups in `~/.config/synth-shell/backups/` and portable JSON presets (`export` / `import`).

---

## Screenshots

### Interactive 2-Column Terminal Picker (`synth-shell-theme`)

Browse all 64 palettes side-by-side in your terminal with live 256-color swatches, 3-segment & 6-segment DevOps prompt previews, instant `/search`, and 1-key theme switching:

<p align="center">
  <img src="https://raw.githubusercontent.com/mvsoares/synth-shell-theme/main/docs/screenshots/tui-theme-picker.png" alt="Interactive 2-Column Terminal Theme Picker (synth-shell-theme)" width="100%" />
</p>

### Live Browser Web Studio (`synth-shell-theme web`)

Prefer a visual workbench? Launch the zero-dependency local Web Studio to preview themes, mix dual Powerline separators, reorder prompt segments, and manage runtime speed patches & backups in 1 click:

<p align="center">
  <img src="https://raw.githubusercontent.com/mvsoares/synth-shell-theme/main/docs/screenshots/web-studio-themes.png" alt="Synth-Shell Theme Web Studio — 64 Color Themes and Sticky Live Prompt Workbench" width="100%" />
</p>

<table>
  <tr>
    <td width="50%" align="center">
      <strong>Dual Separators &amp; 48 Curated Presets</strong><br /><br />
      <img src="https://raw.githubusercontent.com/mvsoares/synth-shell-theme/main/docs/screenshots/web-studio-separators.png" alt="Web Studio — Dual Powerline Separators Tab" width="100%" />
    </td>
    <td width="50%" align="center">
      <strong>Segment Toggles, Runtime Optimizer &amp; Backups</strong><br /><br />
      <img src="https://raw.githubusercontent.com/mvsoares/synth-shell-theme/main/docs/screenshots/web-studio-optimizer.png" alt="Web Studio — Layout, Segments and Runtime Optimizer Tab" width="100%" />
    </td>
  </tr>
</table>

### 60+ Nerd Font & Dual Separator Cheat-Sheet (`synth-shell-separator --palette`)

Mix any internal divider (e.g. rounded capsule, diagonal slant, wave, pixel) with an independent ending cap (e.g. classic arrow, lightning bolt, diamond sparkle):

<p align="center">
  <img src="https://raw.githubusercontent.com/mvsoares/synth-shell-theme/main/docs/screenshots/tui-separator-palette.png" alt="60+ Nerd Font Character Palette and Dual Separator Mix Examples" width="780" />
</p>

---

## Installation

### From PyPI (`pipx`, `uv`, or `pip`)

```bash
# Recommended: pipx
pipx install synth-shell-theme

# Or via uv (persistent tool install)
uv tool install synth-shell-theme

# Zero-install instant run with uvx
uvx synth-shell-theme

# Or via pip
pip install --user synth-shell-theme
```

### Local Clone / Editable Development Install

```bash
git clone https://github.com/mvsoares/synth-shell-theme.git
cd synth-shell-theme
pipx install -e . --force
```

Both `synth-shell-theme` (primary CLI) and `synth-shell-separator` (dedicated separator editor) are installed onto your `PATH`.

### Initialize Runtime Enhancements

After installing `synth-shell` (or use `--install` to install upstream `synth-shell` automatically), apply the 4 runtime speed & compatibility patches once:

```bash
synth-shell-theme init
# Or install upstream synth-shell + patch + apply Tokyo Night (#12):
synth-shell-theme init --install --apply tokyo-night
```

---

## Quick Start

### 1. Interactive Terminal Picker (TUI)

```bash
synth-shell-theme
```

Keyboard shortcuts inside the TUI:
- `1`–`64` or theme name/slug — Apply theme immediately
- `n` / `p` / `g <page>` — Next, previous, or jump to page
- `/query` — Filter themes by name, slug, or badge (`c` to clear)
- `s` — Open the interactive **Dual Separator & 60+ Glyph Editor**
- `f` — Toggle **High-Contrast White Text** (`--force-white-text`)
- `k` — Toggle **Keep Current Input Color** (`--keep-input`)
- `w` — Launch the **Live Web Studio** in your browser
- `b` / `u` — Save a manual backup or undo/restore the latest backup
- `r` — Apply a random theme

### 2. Live Browser Web Studio

```bash
synth-shell-theme web
# Custom port or headless mode:
synth-shell-theme web --port 7778 --no-browser
```

### 3. Direct CLI Commands

```bash
# List all 64 themes with 256-color Host/PWD/Git swatches
synth-shell-theme --list

# Apply a theme by number, name, or slug
synth-shell-theme --apply 12
synth-shell-theme --apply catppuccin-mocha
synth-shell-theme --apply dracula-punch --force-white-text --keep-input

# Dual Powerline & Nerd Font separators
synth-shell-theme --dual round arrow        # Rounded bubbles inside + classic triangle cap
synth-shell-theme --dual slant zap          # Cyberpunk slant inside + lightning bolt at end
synth-shell-separator --palette             # Print 60+ Nerd Font glyph cheat-sheet
synth-shell-separator                       # Launch dedicated interactive separator editor

# Prompt layout, truncation, prefix, text effect & telemetry segments
synth-shell-theme --format "HOST PWD GIT PYENV TF KUBE STATUS DURATION AWS" --two-line
synth-shell-theme --max-pwd 35 --max-git 22 --max-pyenv 18 --prefix auto --text-effect regular

# WSL2 / monorepo speed & ASCII-safe mode (SSH servers without Nerd Fonts)
synth-shell-theme --fast-git-wsl --git-timeout 400 --async-git
synth-shell-theme --ascii-safe

# Root prompt & synth-shell-greeter palette/monitor sync
synth-shell-theme --sync-root --sync-greeter --hide-swap

# Light / Dark toggle, live prompt benchmark & Bash tab-completion
synth-shell-theme --toggle-theme
synth-shell-theme bench --runs 20
eval "$(synth-shell-theme completion bash)"

# Health check (paths, UTF-8 locale, TERM/TrueColor, Nerd Fonts, patches), backups & presets
synth-shell-theme doctor
synth-shell-theme --restore
synth-shell-theme export my-prompt.json
synth-shell-theme import my-prompt.json
```

Reload your active Bash session after applying changes:

```bash
source ~/.config/synth-shell/synth-shell-prompt.sh
```

---

## Environment Variables

| Variable | Description |
| :--- | :--- |
| `SYNTH_SHELL_CONFIG_DIR` | Override configuration directory (defaults to `~/.config/synth-shell`). |

---

## Development & Testing

```bash
python3 -m unittest discover -s tests -v
```

---

## License

MIT License — see [LICENSE](https://github.com/mvsoares/synth-shell-theme/blob/main/LICENSE).
