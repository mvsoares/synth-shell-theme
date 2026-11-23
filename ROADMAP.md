# 🗺️ Synth-Shell Theme Studio — Community Roadmap

This roadmap captures **unimplemented enhancements, runtime patches, and UX ideas** gathered from upstream GitHub issues & pull requests ([`synth-shell`](https://github.com/andresgongora/synth-shell), [`synth-shell-prompt`](https://github.com/andresgongora/synth-shell-prompt), [`synth-shell-greeter`](https://github.com/andresgongora/synth-shell-greeter)), Reddit (`r/bash`, `r/linux`, `r/unixporn`), AskUbuntu, and community forks/blogs (*Clustered Pi*, *mcgillij.dev*).

---

## Already Solved in `v1.0.0` (Baseline)

For reference, the following community requests are **already implemented** in `synth-shell-theme`:
- **64 256-color themes + live 2-column TUI & Browser Web Studio** ([synth-shell#227](https://github.com/andresgongora/synth-shell/issues/227), [synth-shell-prompt#9](https://github.com/andresgongora/synth-shell-prompt/issues/9))
- **Single-pass `git status` (`git_single_pass` — 4× faster Git prompt)** ([synth-shell-prompt#35](https://github.com/andresgongora/synth-shell-prompt/issues/35), [#36](https://github.com/andresgongora/synth-shell-prompt/issues/36))
- **Zero-subshell Kubernetes context reader (`kube_fast` — removes `yq` dependency)** ([synth-shell-prompt#28](https://github.com/andresgongora/synth-shell-prompt/pull/28))
- **Independent internal & ending Powerline separators (`dual_separator` + 48 presets + 60+ Nerd Font glyphs)**
- **Full 0–255 & 16 named-color parity across prompt, `alias.sh`, `better-ls.sh`, and `better-history.sh` (`color_256_parity`)**
- **2-line prompt toggle, segment ordering (`format`), and `max_pwd_char` controls** ([synth-shell#221](https://github.com/andresgongora/synth-shell/issues/221), [#226](https://github.com/andresgongora/synth-shell/issues/226), [synth-shell-prompt#29](https://github.com/andresgongora/synth-shell-prompt/issues/29), [#31](https://github.com/andresgongora/synth-shell-prompt/issues/31))
- **Unattended upstream `synth-shell` installation (`synth-shell-theme init --install`)** ([synth-shell#198](https://github.com/andresgongora/synth-shell/issues/198))

---

## Implemented in `v1.1.0` (All 5 Phases Complete)

All 16 community enhancements across Phases 1–5 have been implemented in **`v1.1.0`**:

### Phase 1 — Zero-Fork Prompt Speed & WSL2 / Large-Repo Engine ✅

1. **[x] Zero-Subshell Segment Renderer (`zero_fork_render` patch)**
   - **Community context:** [synth-shell-prompt#35](https://github.com/andresgongora/synth-shell-prompt/issues/35), [#36](https://github.com/andresgongora/synth-shell-prompt/issues/36); Reddit `r/bash` comparisons against Starship.
   - **Problem:** `printSegment()` and `getFormatCode()` still invoke `$(getColorCode ...)`, `$(getBackgroundCode ...)`, and `$(getEffectCode ...)` via command substitution on every segment, spawning ~15–25 subshells per `Enter` keystroke (especially costly on WSL2 and Raspberry Pi).
   - **Plan:** Add an idempotent patch in `patches.py` converting color/format lookup helpers to pure-Bash variable return (`REPLY` / `printf -v`) with zero process forks during prompt assembly.

2. **[x] WSL2 `/mnt/*` & Monorepo Fast-Git Mode (`git_fast_untracked` + Timeout Guard)**
   - **Community context:** [synth-shell-prompt#35](https://github.com/andresgongora/synth-shell-prompt/issues/35) (*"Synth shell is a bit slow in Windows WSL"*), [#36](https://github.com/andresgongora/synth-shell-prompt/issues/36).
   - **Problem:** Crossing the Linux↔NTFS boundary on `/mnt/c/...` in WSL2 or scanning untracked files in huge monorepos makes `git status` take 300–800 ms.
   - **Plan:**
     - Add `git_skip_untracked_on_slow_fs="true"` (auto-adds `--untracked-files=no` on `/mnt/[a-z]/*` or when `bash.showUntrackedFiles=false`).
     - Support an optional `git_timeout_ms` guard so stalled NFS/SSHFS mounts never freeze interactive input.

3. **[x] Optional Asynchronous Background Git Refresh**
   - **Community context:** Frequent Powerlevel10k / Starship comparison on `r/linux` and `r/unixporn`.
   - **Plan:** Cache last-known Git status per repo directory in `/dev/shm` (`$XDG_RUNTIME_DIR`) so `PS1` renders in `<2 ms` immediately while a background job refreshes dirty/ahead/behind state for the next prompt.

---

### Phase 2 — Execution Telemetry & Cloud / DevOps Segments ✅

4. **[x] Last Command Exit Code Segment (`STATUS`)**
   - **Community context:** Top feature users miss when choosing `synth-shell` over Starship/P10k.
   - **Plan:** Capture `$?` at the very top of `prompt_command_hook`. When non-zero, render a high-contrast error segment (e.g., `✗ 1` or `✗ SIGINT`), hidden automatically when `$? == 0`. Add `font_color_status` / `background_status` defaults across all 64 themes.

5. **[x] Command Execution Duration Segment (`DURATION`)**
   - **Community context:** Requested across `r/bash` and DevOps dotfiles forks.
   - **Plan:** Use Bash `PS0` (Bash `>= 4.4`) + `$EPOCHREALTIME` / `$SECONDS` (zero subshells) to measure command runtime and display a segment (e.g., `⏱ 4.2s` or `⏱ 1m 18s`) whenever execution exceeds `min_duration_sec` (default `2`).

6. **[x] Additional Zero-Fork Dev & Cloud Context Segments (`AWS`, `GCP`, `DOCKER`, `NODE`, `SSH`)**
   - **Community context:** *mcgillij.dev* synth-shell mods, [synth-shell-prompt#16](https://github.com/andresgongora/synth-shell-prompt/issues/16), [#28](https://github.com/andresgongora/synth-shell-prompt/pull/28).
   - **Plan:**
     - `AWS`: Pure-Bash read of `$AWS_PROFILE` / `$AWS_VAULT`.
     - `GCP`: Pure-Bash read of `$CLOUDSDK_ACTIVE_CONFIG_NAME` or `~/.config/gcloud/active_config` + project file.
     - `DOCKER`: Pure-Bash read of `$DOCKER_CONTEXT` or `~/.docker/config.json` (`currentContext` when non-default).
     - `NODE`: Zero-fork version extraction from `$NVM_BIN` / `$FNM_MULTISHELL_PATH` when inside a directory with `package.json`.
     - `SSH` / `CONTAINER`: Automatic context badge when `$SSH_CONNECTION` is set or inside Docker (`/.dockerenv`), Podman (`/run/.containerenv`), or Distrobox.

---

### Phase 3 — Segment Truncation, Virtualenv Fidelity, Prefix Icons & Tab Titles ✅

7. **[x] Per-Segment Length Limits (`max_git_char`, `max_pyenv_char`, `max_kube_char`)**
   - **Community context:** [synth-shell#242](https://github.com/andresgongora/synth-shell/issues/242) (*"How to limit the python environment length in the prompt?"*).
   - **Problem:** Upstream only truncates `PWD` (`max_pwd_char`), leaving long Jira Git branches (`feature/JIRA-4821-refactor-auth-middleware`) and Poetry virtualenv hashes (`service-api-9f8a7b6c-py3.12`) unclipped.
   - **Plan:** Add configurable max-length keys with clean `…` truncation in `patches.py`, CLI flags (`--max-git`, `--max-pyenv`), and sliders in Web Studio.

8. **[x] Accurate Python Virtualenv & Conda Prompt Names (`$VIRTUAL_ENV_PROMPT` / `pyvenv.cfg`)**
   - **Community context:** [synth-shell-prompt#27](https://github.com/andresgongora/synth-shell-prompt/pull/27), [#15](https://github.com/andresgongora/synth-shell-prompt/issues/15), [#16](https://github.com/andresgongora/synth-shell-prompt/issues/16).
   - **Problem:** `python -m venv .venv --prompt my-api` sets `$VIRTUAL_ENV_PROMPT` (and `prompt = my-api` in `pyvenv.cfg`), while `synth-shell` only runs `basename "$VIRTUAL_ENV"`, showing `.venv` for every project.
   - **Plan:** Prefer `${VIRTUAL_ENV_PROMPT}` (stripped of parens), then `pyvenv.cfg` `prompt`, then `$CONDA_DEFAULT_ENV`, falling back to `basename "$VIRTUAL_ENV"` (or parent folder name when `basename == ".venv"`).

9. **[x] Custom Leading Prompt Prefix / Distro Emblem (`prompt_prefix`)**
   - **Community context:** [synth-shell-prompt#37](https://github.com/andresgongora/synth-shell-prompt/issues/37) (*"Allow adding characters to the beginning of the prompt"*).
   - **Plan:** Support an optional leading symbol/OS icon (e.g., ``, ``, ``, ``, `❯`, or auto-detected `/etc/os-release` Nerd Font distro logo) rendered right before the first segment.

10. **[x] Configurable Segment Text Effects (`font_effect`: `bold`, `regular`, `italic`, `dim`)**
    - **Community context:** [synth-shell-prompt#39](https://github.com/andresgongora/synth-shell-prompt/issues/39) (*"Allow other texteffect or enhance documentation"*).
    - **Plan:** Allow overriding the hardcoded `bold` segment text style globally (`--text-effect regular|bold|italic`) and per-segment in `.conf` presets and Web Studio.

11. **[x] Terminal Window / Tab Title Restoration (`enable_terminal_title`)**
    - **Community context:** [synth-shell#142](https://github.com/andresgongora/synth-shell/issues/142) (*"Host and path missing from terminal's title bar"*).
    - **Problem:** Overwriting `PS1` removes Ubuntu/GNOME/Terminator/Windows Terminal OSC-0 sequences (`\e]0;user@host: dir\a`), leaving terminal tabs titled `"bash"`.
    - **Plan:** Emit `\[\e]0;\u@\h: \w\a\]` at the start of `PS1` when `enable_terminal_title="true"` (enabled by default).

---

### Phase 4 — Unicode, Nerd Font, Locale & Non-Interactive Shell Hardening ✅

12. **[x] UTF-8 `PS1` Escape Guard (`utf8_ps1_guard` patch)**
    - **Community context:** [synth-shell-prompt#40](https://github.com/andresgongora/synth-shell-prompt/issues/40) (*`separator_char in Unicode shows up as "username+bytes"`*).
    - **Problem:** Under `LC_ALL=C` / `POSIX` locales or older Bash (`< 4.2`, e.g., macOS `/bin/bash`), `printf '\uE0B0'` outputs literal `\uE0B0`, and Bash's `PS1` parser then expands `\u` into the **current username** (`rmetrichE0B0`).
    - **Plan:** Pre-decode Unicode escapes into raw UTF-8 bytes when the active locale is UTF-8, and automatically fall back to ASCII `>` when `locale charmap` is not `UTF-8` or `\u` remains unexpanded.

13. **[x] Nerd Font & Locale Diagnostics in `doctor` + `--ascii-safe` Mode**
    - **Community context:** [synth-shell#248](https://github.com/andresgongora/synth-shell/issues/248), [synth-shell-prompt#21](https://github.com/andresgongora/synth-shell-prompt/issues/21), [#23](https://github.com/andresgongora/synth-shell-prompt/issues/23), [#26](https://github.com/andresgongora/synth-shell-prompt/issues/26), [#34](https://github.com/andresgongora/synth-shell-prompt/issues/34), AskUbuntu.
    - **Plan:**
      - Extend `synth-shell-theme doctor` to inspect `LANG`/`LC_CTYPE` UTF-8 support and scan system/user font directories (`fc-list` on Linux, `~/Library/Fonts` on macOS, Windows `Fonts`) for installed Powerline/Nerd Fonts.
      - Add `synth-shell-theme --ascii-safe` to switch both separators (`»` / `>` / `|`) and Git status symbols (`*`, `+`, `-`, `^` instead of `◔`, `⇡`, `⇣`) in one command for headless SSH hosts or unpatched terminals.

14. **[x] Non-Interactive Shell Safety Guard (`interactive_guard` patch)**
    - **Community context:** [synth-shell#177](https://github.com/andresgongora/synth-shell/issues/177), [#232](https://github.com/andresgongora/synth-shell/issues/232).
    - **Problem:** Sourcing `synth-shell` scripts in non-interactive shells emits ANSI sequences on stdout and breaks `scp`, `sftp`, `rsync`, and VS Code Remote SSH.
    - **Plan:** Ensure `[[ $- != *i* ]] && return` is present at the top of installed `synth-shell` startup scripts during `synth-shell-theme init`.

---

### Phase 5 — `synth-shell-greeter` Studio & `root` Prompt Sync ✅

15. **[x] Root Prompt Theme Sync (`--sync-root` & Web Studio Toggle)**
    - **Community context:** [synth-shell#222](https://github.com/andresgongora/synth-shell/issues/222) (*"When is synth-shell-prompt.root.config used?"*).
    - **Plan:** Add `--sync-root` to write a matching `synth-shell-prompt.root.config` (preserving the chosen theme's palette while highlighting `USER`/`HOST` with a distinct root warning accent) and document/automate `/root/.config/synth-shell` linking.

16. **[x] Greeter Palette Sync & Monitor Customizer (`synth-shell-greeter`)**
    - **Community context:** [synth-shell#272](https://github.com/andresgongora/synth-shell/issues/272) (*"setup.sh: ask which monitors the greeter shows"*), [synth-shell#269](https://github.com/andresgongora/synth-shell/issues/269), [synth-shell-greeter#10](https://github.com/andresgongora/synth-shell-greeter/issues/10), [#12](https://github.com/andresgongora/synth-shell-greeter/issues/12), [#45](https://github.com/andresgongora/synth-shell-greeter/issues/45), [#48](https://github.com/andresgongora/synth-shell-greeter/issues/48).
    - **Plan:**
      - Add `--sync-greeter` (and a Web Studio **Greeter** tab) to synchronize the active prompt theme's 256-color accents to `synth-shell-greeter`'s ASCII logo and usage bars.
      - Provide 1-click toggles for which system rows `status.sh` prints (e.g., hiding `SWAP: N/A` on cloud VMs) plus optional runtime fixes for AMD `k10temp`/`Tctl` CPU sensors and ZFS ARC memory accounting.

---

## Implemented in `v1.2.0` (Modern Shell Interop, TrueColor & Studio Expansion) ✅

17. **[x] Safe `PROMPT_COMMAND` Chaining & Removal of `trap DEBUG` (`hook_chaining`)** — Preserves `direnv`, `zoxide`, `atuin`, `ble.sh`, `mise`, and VS Code Shell Integration (`OSC 633`) by chaining `PROMPT_COMMAND` (Bash 5.1+ array & legacy string) and moving input color reset (`\e[0m`) into `PS0`.
18. **[x] 24-Bit TrueColor (`#RRGGBB`) with Automatic 256-Color Fallback (`truecolor_24bit`)** — Native `38;2;R;G;B` / `48;2;R;G;B` in pure Bash when `COLORTERM=truecolor|24bit` with zero-fork nearest-256 fallback.
19. **[x] Responsive Compact Width (`--compact-width`, default `90` cols)** — Automatically hides secondary segments and shortens `PWD` in narrow `tmux` / VS Code split panes.
20. **[x] Exact Git Ahead/Behind Counters (`↑N ↓M`)** — Zero-fork extraction from `git status --porcelain -b` (`--git-counts` / `--no-git-counts`).
21. **[x] New Zero-Fork Context Segments (`JOBS`, `DIRENV`, `SHLVL`/`NIX`, `RUST`, `GO`) & `set -u` (`nounset`) Safety** — Full 20-segment catalog safe under strict `set -u` shells.
22. **[x] Optional `ble.sh` Transient Prompt Integration (`--transient`)** — Enables `bleopt prompt_ps1_transient=trim` automatically when `ble.sh` is loaded.
23. **[x] Live Prompt Benchmark (`synth-shell-theme bench` + Web Studio button)** — Measures real `prompt_command_hook` latency (`min` / `p50` / `p95` / `max` ms).
24. **[x] Custom TrueColor Theme Creator in Web Studio (`~/.config/synth-shell/themes/`)** — Pick `#RRGGBB` colors per segment, save custom `.conf` themes, and browse them alongside the 64 bundled palettes.
25. **[x] 1-Click Light / Dark Theme Toggle (`--toggle-theme`, `--light-theme`, `--dark-theme`)** — Instant day/night switching in CLI and Web Studio.
26. **[x] Bash Tab-Completion (`synth-shell-theme completion bash`) & VS Code / `TERM` / `COLORTERM` Diagnostics in `doctor`**.

---

## Implemented in `v1.3.0` (Modern Terminals, Unified Color Ecosystem & Interactive Studio) ✅

27. **[x] Right-Aligned Top Prompt Bar (`RPROMPT` — `--right-format`, `--right-fill`)** — Pure-Bash right-aligned top prompt segments (e.g. `CLOCK BATTERY DURATION`) with customizable connecting fill bar (`─`, `·`, ` `) and automatic column-width calculation in 2-line mode.
28. **[x] OSC 133 Semantic Prompt Integration (`--osc133` / `osc133_semantic`)** — Native `OSC 133;A/B/C/D;<exit>` sequences for Ghostty, Kitty, WezTerm, Windows Terminal, iTerm2, and VS Code (jump between prompts, select command output, visual command markers).
29. **[x] Advanced Git State & Worktree Detection (`git_advanced_state`)** — Zero-fork pure-Bash `.git` inspection showing `REBASE 2/5`, `MERGE`, `CHERRY`, `BISECT`, and `git worktree` badges (`⎇name`).
30. **[x] Zero-Fork `BATTERY` Segment (`v13_segments`)** — Pure-Bash `/sys/class/power_supply/BAT*/capacity` & `status` reader (with `--battery-threshold` auto-hide when charged).
31. **[x] Unified Color Ecosystem (`--sync-ecosystem`)** — Generates matching `~/.config/synth-shell/theme-env.sh` (`FZF_DEFAULT_OPTS` + `LS_COLORS`) and `~/.config/synth-shell/tmux-theme.conf` from the active prompt theme.
32. **[x] External Theme Importer (`import-theme`)** — Direct 1-command import from **Pywal** (`--pywal`), **Base16 YAML**, **Ghostty**, **Kitty**, **Alacritty**, and **Windows Terminal JSON** palettes into `~/.config/synth-shell/themes/`.
33. **[x] Interactive Drag-and-Drop Segments, Inline Color Editor & Shareable CLI in Web Studio** — Drag pills to reorder Left & Right prompt bars, click any Live Workbench segment to tweak its FG/BG hex inline, and copy a reproducible 1-line CLI command.
34. **[x] Static Browser Demo Export (`export-web docs/index.html`) & Auto-Healing `doctor --fix`** — Zero-backend static HTML showcase ready for GitHub Pages, plus 1-command CRLF→LF repair and patch auto-remediation (`synth-shell-theme doctor --fix`).
35. **[x] Automatic Terminal Mode Sanitizer (`terminal_sanitize` — `v1.3.2`)** — Zero-fork TTY-guarded reset (`\e[?1000l\e[?1002l\e[?1003l\e[?1006l\e[?1015l\e[?1004l`) on prompt return that automatically clears leaked SGR/X10/urxvt mouse tracking (`35;col;rowM`) and focus reporting left behind by dropped SSH/TUI sessions while preserving Readline bracketed paste (`?2004h`) and `ble.sh`.

---

## Implemented in `v1.3.9` (Smart DevOps Safety, Modern Terminal Superpowers & SSH/Starship/WezTerm Ecosystem) ✅

36. **[x] Kubernetes Namespace + Automatic Production Red Warning (`kube_namespace_prod`)** — Pure-Bash kubeconfig parser extracts both `current-context` and matching `namespace` (`☸ ctx (ns)`), highlighting production contexts/namespaces (`--kube-prod-pattern`) in vibrant red with `🚨`.
37. **[x] Dynamic Git Colors (`--git-dynamic-color`) & Deterministic SSH Host Coloring (`--ssh-host-color`)** — Automatically colors `GIT` amber when dirty and red during `REBASE`/`MERGE`, and hashes SSH hostnames (with automatic red `prod` / amber `stg` rules) to distinguish remote terminals at a glance.
38. **[x] New Context Segments (`SUDO`, `JJ` Jujutsu VCS, `CUSTOM`) — 24 Total Segments** — Cached `sudo` credential indicator, zero-fork Jujutsu (`.jj`) repository detection, and user-defined `CUSTOM` badge (`--custom-badge` or `$SYNTH_CUSTOM_BADGE`).
39. **[x] OSC 7 CWD Reporting (`--osc7`) & Long-Command Desktop Notifications (`--notify-sec` OSC 9/99)** — Pure-Bash URL-encoded OSC 7 so WezTerm/Ghostty/Kitty/Windows Terminal open new tabs & splits in the active directory, plus native desktop notifications when slow builds/deploys finish.
40. **[x] Fish-Style Path Shortening (`--pwd-style fish`) & OS Auto Light/Dark Theme (`--auto-theme`)** — Pure-Bash `~/p/synth-shell-theme` abbreviation and automatic OS color-scheme detection (Linux GNOME/KDE, macOS `defaults`, Windows Registry).
41. **[x] 1-Command SSH Remote Deploy (`ssh-install user@host`), `wezterm-theme.lua` Ecosystem Sync & `export-starship`** — Deploy patched prompt + config over SSH with zero Python/Git on the remote host, generate `wezterm-theme.lua` alongside `theme-env.sh` & `tmux-theme.conf`, and export any of the 64 themes + dual separators to `starship.toml`.
