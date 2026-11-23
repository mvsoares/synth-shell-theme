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
