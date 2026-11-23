"""Command-line interface for `synth-shell-theme` and `synth-shell-separator` (v1.1.0)."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from synth_shell_theme import __version__
from synth_shell_theme.core import (
    VALID_FONT_EFFECTS,
    apply_ascii_safe_mode,
    apply_layout_options,
    apply_separators,
    apply_theme,
    backup_config,
    benchmark_prompt,
    detect_current_separators,
    detect_current_theme,
    doctor_fix,
    export_preset,
    export_static_studio,
    generate_bash_completion,
    import_preset,
    list_backups,
    read_current_state,
    read_greeter_state,
    restore_backup,
    sync_greeter_theme,
    sync_root_config,
    toggle_light_dark_theme,
)
from synth_shell_theme.ecosystem import import_external_theme, sync_ecosystem
from synth_shell_theme.patches import (
    apply_runtime_patches,
    inspect_patches,
    install_upstream_synth_shell,
)
from synth_shell_theme.paths import get_prompt_script_path, setup_console, system_summary
from synth_shell_theme.separators import ALL_PRESETS, resolve_separator_input
from synth_shell_theme.themes import (
    BOLD,
    DIM,
    RESET,
    build_card_lines,
    filter_themes,
    find_theme,
    load_themes,
)
from synth_shell_theme.tui import (
    print_character_palette_table,
    print_separator_showcase,
    print_side_by_side,
    print_theme_list,
    report_separators_applied,
    report_theme_applied,
    run_separator_tui,
    run_theme_tui,
)


def _cmd_doctor(as_json: bool = False) -> int:
    summary = system_summary()
    patches = inspect_patches()
    state = read_current_state()
    greeter = read_greeter_state()
    report = {
        "version": __version__,
        "system": summary,
        "patches": patches,
        "active_theme": state["active_theme"],
        "active_theme_id": state["active_theme_id"],
        "internal_separator": state["internal_separator"],
        "end_separator": state["end_separator"],
        "greeter": greeter,
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    ok_tag = "\033[32;1mOK\033[0m"
    warn_tag = "\033[33;1mMISSING\033[0m"
    opt_tag = "\033[36;1mOPTIONAL\033[0m"

    loc = summary.get("locale", {})
    nf = summary.get("nerd_fonts", {})
    term = summary.get("terminal", {})
    loc_ok = bool(isinstance(loc, dict) and loc.get("utf8"))
    nf_ok = bool(isinstance(nf, dict) and nf.get("detected"))
    tc_ok = bool(isinstance(term, dict) and term.get("truecolor"))
    t256_ok = bool(isinstance(term, dict) and term.get("term_256"))

    print()
    print(f"  {BOLD}Synth-Shell Theme Doctor{RESET} (v{__version__})")
    print(f"  {DIM}{'─' * 62}{RESET}")
    print(f"  OS / Python:      {summary['os']} ({summary['python']})")
    custom_cnt = int(summary.get("custom_themes", 0) or 0)
    custom_note = f" + {custom_cnt} custom" if custom_cnt else ""
    print(f"  Bundled themes:   {summary['bundled_themes']} themes{custom_note} + {len(ALL_PRESETS)} separator presets")
    print(f"  Config file:      {summary['config_path']} [{ok_tag if summary['config_exists'] else warn_tag}]")
    print(f"  Root config:      {summary['root_config_path']} [{ok_tag if summary['root_config_exists'] else opt_tag}]")
    print(f"  Prompt script:    {summary['prompt_script_path']} [{ok_tag if summary['prompt_script_exists'] else warn_tag}]")
    print(f"  Greeter config:   {summary['greeter_config_path']} [{ok_tag if summary['greeter_config_exists'] else opt_tag}]")
    print(f"  Backups saved:    {summary['backup_count']} ({summary['backup_dir']})")
    print(f"  Active theme:     {state['active_theme'] or 'None detected'}")
    int_sep = state["internal_separator"]
    end_sep = state["end_separator"]
    print(
        f"  Separators:       internal={int_sep['glyph']} ({int_sep['code']})  "  # type: ignore[index]
        f"end={end_sep['glyph']} ({end_sep['code']})"  # type: ignore[index]
    )
    print(
        f"  UTF-8 Locale:     {loc.get('effective', 'unknown') if isinstance(loc, dict) else 'unknown'} "
        f"[{ok_tag if loc_ok else warn_tag}]"
    )
    if isinstance(term, dict):
        color_mode = "24-bit TrueColor" if tc_ok else ("256-color" if t256_ok else "basic")
        print(
            f"  Terminal / Color: TERM={term.get('term')}  COLORTERM={term.get('colorterm')}  "
            f"({color_mode}) [{ok_tag if t256_ok else warn_tag}]"
        )
        if term.get("blesh_detected"):
            print(f"  ble.sh detected:  yes (tip: enable transient prompt with `--transient`)")
        if term.get("is_vscode"):
            print(f"  VS Code font tip: {term.get('vscode_font_setting')}")
    if nf_ok and isinstance(nf, dict):
        samples = ", ".join(str(x) for x in list(nf.get("samples", []))[:3])  # type: ignore[arg-type]
        print(f"  Nerd/PL Fonts:    {nf.get('count', 0)} found ({samples}) [{ok_tag}]")
    else:
        print(f"  Nerd/PL Fonts:    none detected [{warn_tag}] (tip: run `synth-shell-theme --ascii-safe`)")

    print()
    print(f"  {BOLD}Runtime Patches & Optimizations:{RESET}")
    patch_labels = [
        ("kube_fast", "Zero-subshell Kubernetes reader + max_kube_char (no yq)"),
        ("git_single_pass", "Single-pass `git status --porcelain -b` (4x speedup)"),
        ("git_wsl_fast", "WSL2 /mnt/* fast-untracked + timeout + async cache + max_git_char"),
        ("git_ahead_behind_counts", "Exact Git ahead/behind counts (↑N ↓M) with zero extra forks"),
        ("git_advanced_state", "Git rebase/merge/cherry-pick/bisect & worktree detection"),
        ("zero_fork_render", "Zero-fork pure-Bash segment renderer (eliminates ~20 subshells)"),
        ("dual_separator", "Independent ending separator (`separator_char_end`)"),
        ("color_256_parity", "Full 0-255 & 16-named-color parity + italic/regular effects"),
        ("truecolor_24bit", "24-bit TrueColor (#RRGGBB) with automatic 256-color fallback"),
        ("v11_segments", "v1.1 segments (STATUS, DURATION, AWS, GCP, DOCKER, NODE, SSH, prefix, title)"),
        ("v12_segments", "v1.2 segments (JOBS, DIRENV, SHLVL/NIX, RUST, GO) + nounset safety"),
        ("v13_segments", "v1.3 BATTERY segment + Git state + RPROMPT top bar + OSC 133"),
        ("osc133_semantic", "OSC 133 semantic prompt markers (Ghostty/Kitty/WezTerm/WT/VS Code)"),
        ("right_prompt", "Right-aligned top bar (`right_format` + connector fill line)"),
        ("responsive_width", "Responsive compact layout on narrow tmux/VS Code splits (<90 cols)"),
        ("hook_chaining", "Safe PROMPT_COMMAND chaining + PS0 reset (direnv/zoxide/atuin/ble.sh safe)"),
        ("pyenv_enhanced", "Pure-Bash VIRTUAL_ENV_PROMPT / pyvenv.cfg / Conda + max_pyenv_char"),
        ("utf8_ps1_guard", "UTF-8 PS1 escape guard (fixes \\uE0B0 username bug under LC_ALL=C)"),
        ("interactive_guard", "Non-interactive shell safety guard (`scp`/`sftp`/`rsync` safe)"),
    ]
    for key, desc in patch_labels:
        badge = ok_tag if patches.get(key) else warn_tag
        print(f"    [{badge}] {desc}")
    if patches.get("greeter_script_found"):
        for key, desc in (
            ("greeter_amd_temp", "Greeter AMD k10temp/Tctl CPU sensor + LC_ALL=C fix"),
            ("greeter_zfs_arc", "Greeter ZFS ARC reclaimable memory accounting fix"),
        ):
            badge = ok_tag if patches.get(key) else warn_tag
            print(f"    [{badge}] {desc}")
    if not patches.get("all_applied") and summary["prompt_script_exists"]:
        print()
        print(f"  Tip: Run {BOLD}synth-shell-theme init{RESET} to apply missing runtime optimizations.")
    print()
    return 0


def _cmd_init(
    install_missing: bool = False,
    tune_defaults: bool = True,
    theme_choice: str | None = None,
    sync_root: bool = False,
    sync_greeter: bool = False,
    ascii_safe: bool = False,
) -> int:
    prompt_sh = get_prompt_script_path()
    if not prompt_sh.is_file() and install_missing:
        print("  Installing upstream synth-shell into ~/.config/synth-shell ...")
        if install_upstream_synth_shell():
            print("  \033[32;1m✓\033[0m Upstream synth-shell installed.")
        else:
            print("  \033[31;1m✗\033[0m Failed to install upstream synth-shell automatically.")
            return 1

    res = apply_runtime_patches(tune_defaults=tune_defaults)
    changes = list(res["changes"])  # type: ignore[arg-type]
    status = res["status"]

    selected_theme: dict[str, object] | None = None
    if theme_choice:
        themes = load_themes()
        found, _ = find_theme(theme_choice, themes)
        if not found:
            print(f"Error: Theme '{theme_choice}' not found.", file=sys.stderr)
            return 1
        apply_theme(found)
        selected_theme = found
        changes.append(f"theme:{found['name']}")

    if ascii_safe:
        apply_ascii_safe_mode()
        changes.append("ascii_safe")

    if sync_root:
        sync_root_config(theme=selected_theme)
        changes.append("sync_root")

    if sync_greeter:
        sync_greeter_theme(theme=selected_theme, hide_swap_if_unavailable=True)
        changes.append("sync_greeter")

    print()
    print(f"  {BOLD}Synth-Shell Runtime Initialization (v{__version__}){RESET}")
    if changes:
        for item in changes:
            print(f"    \033[32;1m✓\033[0m Applied: {item}")
    else:
        print("    \033[32;1m✓\033[0m All runtime patches and defaults already up to date.")
    if isinstance(status, dict) and not status.get("prompt_script_found"):
        print(
            f"    \033[33;1m!\033[0m {prompt_sh} not found yet "
            "(run `synth-shell-theme init --install` to install upstream synth-shell)."
        )
    print()
    return 0


def main_separator(argv: list[str] | None = None) -> int:
    """Dedicated CLI entry point for `synth-shell-separator` (and `synth-shell-theme sep`)."""
    setup_console()
    parser = argparse.ArgumentParser(
        prog="synth-shell-separator",
        description="Interactive Powerline & Nerd Font dual separator editor for synth-shell.",
    )
    parser.add_argument("-l", "--list", action="store_true", help="List all 48 separator presets with live prompt previews")
    parser.add_argument("-c", "--current", action="store_true", help="Show currently active internal and ending separators")
    parser.add_argument("-T", "--palette", action="store_true", help="Display visual cheat-sheet table of 60+ Nerd Font glyphs")
    parser.add_argument("-a", "--apply", metavar="SEP", help=f"Apply separator to both internal & ending positions (1-{len(ALL_PRESETS)}, name, hex, or glyph)")
    parser.add_argument("-d", "--dual", nargs=2, metavar=("INTERNAL", "ENDING"), help="Set independent internal and ending separators (e.g. --dual round arrow)")
    parser.add_argument("-i", "--internal", metavar="SEP", help="Set internal segment separator only")
    parser.add_argument("-e", "--end", metavar="SEP", help="Set final ending separator only")
    parser.add_argument("-u", "--custom", metavar="CHAR_OR_HEX", help="Apply custom Unicode hex (e.g. E0B4, U+F0E7) or glyph")
    parser.add_argument("-p", "--preview", metavar="SEP", help="Preview sample prompt with a separator without saving")
    parser.add_argument("--preview-dual", nargs=2, metavar=("INTERNAL", "ENDING"), help="Preview sample prompt with dual separators without saving")
    parser.add_argument("-r", "--random", action="store_true", help="Apply a random curated separator preset")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear terminal screen in interactive mode")

    args = parser.parse_args(argv)
    from synth_shell_theme.tui import _active_preview_theme, render_separator_sample

    theme = _active_preview_theme()
    (cur_int_glyph, cur_int_code), end_tuple = detect_current_separators()
    cur_end_glyph = end_tuple[0] if end_tuple else cur_int_glyph
    cur_end_code = end_tuple[1] if end_tuple else cur_int_code

    if args.current:
        end_desc = f" ({cur_end_code})" if end_tuple else " (same as internal)"
        print(f"Internal separator: {BOLD}{cur_int_glyph}{RESET} ({cur_int_code})")
        print(f"Ending separator:   {BOLD}{cur_end_glyph}{RESET}{end_desc}")
        print(f"Sample: {render_separator_sample(cur_int_glyph, theme, cur_end_glyph)}")
        return 0

    if args.palette:
        print_character_palette_table()
        return 0

    if args.list:
        print_separator_showcase(theme, cur_int_glyph)
        return 0

    if args.preview_dual:
        g1, c1, l1 = resolve_separator_input(args.preview_dual[0])
        g2, c2, l2 = resolve_separator_input(args.preview_dual[1])
        print()
        print(f"  Internal: {BOLD}{g1}{RESET} ({c1}) — {l1}")
        print(f"  Ending:   {BOLD}{g2}{RESET} ({c2}) — {l2}")
        print(f"  Preview:  {render_separator_sample(g1, theme, g2)}")
        print()
        return 0

    if args.preview:
        g, c, label = resolve_separator_input(args.preview)
        print()
        print(f"  Separator: {BOLD}{g}{RESET} ({c}) — {label}")
        print(f"  Preview:   {render_separator_sample(g, theme, g)}")
        print()
        return 0

    if args.dual:
        g1, c1, l1 = resolve_separator_input(args.dual[0])
        g2, c2, l2 = resolve_separator_input(args.dual[1])
        res = apply_separators(internal=(g1, c1), end=(g2, c2))
        report_separators_applied(res, label=f"{l1} + {l2}")
        return 0

    if args.internal:
        g, c, label = resolve_separator_input(args.internal)
        res = apply_separators(internal=(g, c))
        report_separators_applied(res, label=f"Internal: {label}")
        return 0

    if args.end:
        g, c, label = resolve_separator_input(args.end)
        res = apply_separators(end=(g, c))
        report_separators_applied(res, label=f"Ending: {label}")
        return 0

    if args.random:
        key, glyph, code, desc = random.choice(ALL_PRESETS)
        res = apply_separators(internal=(glyph, code), end=(glyph, code))
        report_separators_applied(res, label=f"{key} ({desc})")
        return 0

    target = args.custom or args.apply
    if target:
        g, c, label = resolve_separator_input(target)
        res = apply_separators(internal=(g, c), end=(g, c))
        report_separators_applied(res, label=label)
        return 0

    run_separator_tui(clear_screen=not args.no_clear)
    return 0


def main(argv: list[str] | None = None) -> int:
    """Primary CLI entry point for `synth-shell-theme`."""
    setup_console()
    raw_args = list(sys.argv[1:] if argv is None else argv)

    if raw_args:
        sub = raw_args[0].lower()
        rest = raw_args[1:]

        if sub in ("sep", "separator", "separators"):
            return main_separator(rest)

        if sub in ("web", "studio"):
            web_parser = argparse.ArgumentParser(
                prog="synth-shell-theme web",
                description="Launch the local interactive Synth-Shell Theme Web Studio.",
            )
            web_parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: 127.0.0.1)")
            web_parser.add_argument("-p", "--port", type=int, default=7778, help="Preferred port (default: 7778)")
            web_parser.add_argument("--no-browser", action="store_true", help="Do not automatically open web browser")
            w_args = web_parser.parse_args(rest)
            from synth_shell_theme.server import run_studio_server

            run_studio_server(host=w_args.host, port=w_args.port, open_browser=not w_args.no_browser)
            return 0

        if sub == "init":
            init_parser = argparse.ArgumentParser(
                prog="synth-shell-theme init",
                description="Apply idempotent runtime, speed, segment & safety patches to synth-shell.",
            )
            init_parser.add_argument("--install", action="store_true", help="Clone & install upstream synth-shell if missing")
            init_parser.add_argument("--no-tune", action="store_true", help="Do not update default max_pwd_char / 2-line config options")
            init_parser.add_argument("-a", "--apply", metavar="THEME", help="Also apply a theme by number or slug")
            init_parser.add_argument("--ascii-safe", action="store_true", help="Switch separators and Git symbols to ASCII-safe mode")
            init_parser.add_argument("--sync-root", action="store_true", help="Also generate/sync synth-shell-prompt.root.config")
            init_parser.add_argument("--sync-greeter", action="store_true", help="Also sync active palette to synth-shell-greeter.config")
            i_args = init_parser.parse_args(rest)
            return _cmd_init(
                install_missing=i_args.install,
                tune_defaults=not i_args.no_tune,
                theme_choice=i_args.apply,
                sync_root=i_args.sync_root,
                sync_greeter=i_args.sync_greeter,
                ascii_safe=i_args.ascii_safe,
            )

        if sub == "doctor":
            doc_parser = argparse.ArgumentParser(
                prog="synth-shell-theme doctor",
                description="Inspect synth-shell paths, locale, Nerd Fonts, terminal capabilities, backups & patches.",
            )
            doc_parser.add_argument("--json", action="store_true", help="Output diagnostics as JSON")
            doc_parser.add_argument("--fix", action="store_true", help="Auto-repair CRLF endings and apply all missing runtime patches")
            doc_parser.add_argument("--auto-ascii", action="store_true", help="With --fix, also switch to ASCII-safe if UTF-8/Nerd Fonts are missing")
            d_args = doc_parser.parse_args(rest)
            if d_args.fix:
                fres = doctor_fix(auto_ascii=d_args.auto_ascii)
                if not d_args.json:
                    actions = fres["actions"]
                    if actions:
                        print(f"\n  {BOLD}Doctor Auto-Fix Applied:{RESET}")
                        for act in actions:  # type: ignore[union-attr]
                            print(f"    \033[32;1m✓\033[0m {act}")
                    else:
                        print(f"\n  \033[32;1m✓\033[0m Everything is already healthy!")
            return _cmd_doctor(as_json=d_args.json)

        if sub in ("import-theme", "import-palette"):
            it_parser = argparse.ArgumentParser(
                prog="synth-shell-theme import-theme",
                description="Import external color palettes (Pywal, Base16 YAML, Ghostty, Kitty, Alacritty, Windows Terminal JSON).",
            )
            it_parser.add_argument("source", nargs="?", default=None, help="Path to palette file (omit when using --pywal)")
            it_parser.add_argument("--pywal", action="store_true", help="Import active colors from ~/.cache/wal/colors.json")
            it_parser.add_argument("--name", default=None, help="Custom name for the imported theme")
            it_parser.add_argument("--no-apply", action="store_true", help="Save to ~/.config/synth-shell/themes/ without applying immediately")
            it_args = it_parser.parse_args(rest)
            res_it = import_external_theme(
                source_path=Path(it_args.source) if it_args.source else None,
                from_pywal=it_args.pywal,
                custom_name=it_args.name,
                apply_now=not it_args.no_apply,
            )
            print(f"Imported {res_it['format']} theme '{res_it['theme']}' -> {res_it['saved_path']}")
            return 0

        if sub in ("export-web", "export-static"):
            ew_parser = argparse.ArgumentParser(
                prog="synth-shell-theme export-web",
                description="Export a standalone static HTML demo of the Web Studio (for GitHub Pages).",
            )
            ew_parser.add_argument("output", nargs="?", default="docs/index.html", help="Output HTML file (default: docs/index.html)")
            ew_args = ew_parser.parse_args(rest)
            out_html = export_static_studio(Path(ew_args.output))
            print(f"Exported standalone static Web Studio demo to {out_html}")
            return 0

        if sub in ("bench", "benchmark"):
            bench_parser = argparse.ArgumentParser(
                prog="synth-shell-theme bench",
                description="Benchmark live Bash prompt_command_hook rendering latency (p50 / p95 in ms).",
            )
            bench_parser.add_argument("-n", "--runs", type=int, default=15, help="Number of prompt iterations (default: 15)")
            bench_parser.add_argument("--json", action="store_true", help="Output benchmark metrics as JSON")
            b_args = bench_parser.parse_args(rest)
            bres = benchmark_prompt(iterations=b_args.runs)
            if b_args.json:
                print(json.dumps(bres, indent=2, ensure_ascii=False))
                return 0 if bres.get("ok") else 1
            if not bres.get("ok"):
                print(f"Benchmark error: {bres.get('error')}", file=sys.stderr)
                return 1
            print()
            print(f"  {BOLD}Synth-Shell Prompt Benchmark{RESET} ({bres['iterations']} runs in {bres['cwd']})")
            print(f"  {DIM}{'─' * 56}{RESET}")
            print(f"  Min:    \033[32;1m{bres['min_ms']} ms\033[0m")
            print(f"  Median: \033[36;1m{bres['p50_ms']} ms\033[0m (p50)")
            print(f"  p95:    \033[33;1m{bres['p95_ms']} ms\033[0m")
            print(f"  Max:    {bres['max_ms']} ms")
            print()
            return 0

        if sub in ("completion", "completions"):
            comp_parser = argparse.ArgumentParser(
                prog="synth-shell-theme completion",
                description="Output shell tab-completion script (currently supports: bash).",
            )
            comp_parser.add_argument("shell", nargs="?", default="bash", choices=("bash",), help="Target shell (default: bash)")
            comp_parser.parse_args(rest)
            print(generate_bash_completion())
            return 0

        if sub == "export":
            exp_parser = argparse.ArgumentParser(
                prog="synth-shell-theme export",
                description="Export active theme colors, separators, and layout options to a JSON file.",
            )
            exp_parser.add_argument("output", help="Destination JSON file path")
            e_args = exp_parser.parse_args(rest)
            out = export_preset(Path(e_args.output))
            print(f"Exported preset to {out}")
            return 0

        if sub == "import":
            imp_parser = argparse.ArgumentParser(
                prog="synth-shell-theme import",
                description="Import and apply a JSON preset file.",
            )
            imp_parser.add_argument("input", help="Source JSON preset file path")
            im_args = imp_parser.parse_args(rest)
            res = import_preset(Path(im_args.input))
            print(f"Imported preset from {res['imported_from']}")
            return 0

        if sub == "tui":
            raw_args = rest

    parser = argparse.ArgumentParser(
        prog="synth-shell-theme",
        description=(
            "Interactive 256-color Prompt Theme Picker (64 themes), Dual Powerline Separator Editor, "
            "Runtime Speed & Telemetry Optimizer, and Live Web Studio for synth-shell."
        ),
        epilog=(
            "Subcommands:\n"
            "  synth-shell-theme                Launch interactive 2-column TUI\n"
            "  synth-shell-theme web            Launch live browser-based Web Studio (port 7778)\n"
            "  synth-shell-theme sep            Launch interactive Dual Separator & 60+ Glyph Editor\n"
            "  synth-shell-theme init           Apply all v1.2 runtime, speed, TrueColor & hook-chaining patches\n"
            "  synth-shell-theme doctor         Check config, locale, Nerd Fonts, TERM, backups & patch health\n"
            "  synth-shell-theme bench          Measure live prompt_command_hook latency (p50 / p95 ms)\n"
            "  synth-shell-theme completion     Print Bash tab-completion script\n"
            "  synth-shell-theme export FILE    Export current setup as a portable JSON preset\n"
            "  synth-shell-theme import FILE    Import and apply a JSON preset"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-v", "--version", action="version", version=f"synth-shell-theme {__version__}")
    parser.add_argument("-l", "--list", action="store_true", help="List all 64 themes with 256-color swatches and exit")
    parser.add_argument("-c", "--current", action="store_true", help="Print currently active theme & separators and exit")
    parser.add_argument("-a", "--apply", metavar="THEME", help="Apply theme by number (1-64) or name/slug and exit")
    parser.add_argument("--force-white-text", action="store_true", help="Force segment text to white for maximum contrast")
    parser.add_argument("--keep-input", action="store_true", help="Preserve existing font_color_input when applying a theme")
    parser.add_argument("-S", "--separators", action="store_true", help="Showcase all 48 Powerline & Nerd Font separator presets")
    parser.add_argument("-T", "--palette", action="store_true", help="Display visual cheat-sheet table of 60+ Nerd Font glyphs")
    parser.add_argument("-t", "--separator", metavar="SEP", help="Apply separator style to both internal & ending positions")
    parser.add_argument("-d", "--dual", nargs=2, metavar=("INTERNAL", "ENDING"), help="Apply independent internal and ending separators")
    parser.add_argument("--internal", metavar="SEP", help="Set internal segment separator only")
    parser.add_argument("--end", metavar="SEP", help="Set final ending separator only")
    parser.add_argument("--format", metavar="SEGMENTS", help='Set left prompt segments (e.g. "HOST PWD GIT PYENV TF KUBE")')
    parser.add_argument("--right-format", default=None, metavar="SEGMENTS", help='Set right-aligned top bar segments (e.g. "STATUS DURATION KUBE CLOCK BATTERY", "" to clear)')
    parser.add_argument("--right-fill", default=None, metavar="CHAR", help='Connector character between left & right prompt bars (default: "─")')
    parser.add_argument("--osc133", dest="osc133", action="store_true", default=None, help="Enable OSC 133 semantic prompt markers (Ghostty/Kitty/WezTerm/WT/VS Code)")
    parser.add_argument("--no-osc133", dest="osc133", action="store_false", help="Disable OSC 133 semantic prompt markers")
    parser.add_argument("--git-state", dest="git_state", action="store_true", default=None, help="Show Git rebase/merge/cherry-pick/bisect & worktree state")
    parser.add_argument("--no-git-state", dest="git_state", action="store_false", help="Hide Git rebase/merge/worktree state")
    parser.add_argument("--battery-threshold", type=int, default=None, metavar="PCT", help="Only show BATTERY segment at or below PCT%% (default: 100)")
    parser.add_argument("--sync-ecosystem", action="store_true", help="Generate theme-env.sh (FZF_DEFAULT_OPTS + LS_COLORS) & tmux-theme.conf")
    parser.add_argument("--two-line", dest="two_line", action="store_true", default=None, help="Enable 2-line command prompt")
    parser.add_argument("--single-line", dest="two_line", action="store_false", help="Enable compact 1-line command prompt")
    parser.add_argument("--max-pwd", type=int, default=None, metavar="N", help="Max PWD display length (10-120)")
    parser.add_argument("--max-git", type=int, default=None, metavar="N", help="Max Git branch length (0=unlimited, or 4-80)")
    parser.add_argument("--max-pyenv", type=int, default=None, metavar="N", help="Max Python/Conda env name length (0=unlimited, or 4-60)")
    parser.add_argument("--max-kube", type=int, default=None, metavar="N", help="Max Kubernetes context length (0=unlimited, or 4-60)")
    parser.add_argument("--compact-width", type=int, default=None, metavar="COLS", help="Hide secondary segments when terminal width < COLS (default 90, 0=off)")
    parser.add_argument("--git-counts", dest="git_counts", action="store_true", default=None, help="Show exact Git ahead/behind counts (↑N ↓M)")
    parser.add_argument("--no-git-counts", dest="git_counts", action="store_false", help="Hide exact Git ahead/behind counts")
    parser.add_argument("--transient", dest="transient", action="store_true", default=None, help="Enable ble.sh transient prompt trimming when ble.sh is loaded")
    parser.add_argument("--no-transient", dest="transient", action="store_false", help="Disable ble.sh transient prompt trimming")
    parser.add_argument("--toggle-theme", action="store_true", help="Toggle between configured Light and Dark themes in 1 command")
    parser.add_argument("--light-theme", default=None, metavar="THEME", help="Preferred Light theme slug for --toggle-theme (default: catppuccin-latte)")
    parser.add_argument("--dark-theme", default=None, metavar="THEME", help="Preferred Dark theme slug for --toggle-theme (default: tokyo-night)")
    parser.add_argument("--prefix", default=None, metavar="TEXT", help='Leading prompt prefix icon/string (use "auto" for OS icon, "" to clear)')
    parser.add_argument("--text-effect", choices=VALID_FONT_EFFECTS, default=None, help="Global segment text effect (bold, regular, italic, dim, none)")
    parser.add_argument("--terminal-title", dest="terminal_title", action="store_true", default=None, help="Enable OSC-0 terminal tab/window title updates")
    parser.add_argument("--no-terminal-title", dest="terminal_title", action="store_false", help="Disable OSC-0 terminal title updates")
    parser.add_argument("--fast-git-wsl", dest="fast_git_wsl", action="store_true", default=None, help="Skip untracked files on WSL /mnt/* drives")
    parser.add_argument("--no-fast-git-wsl", dest="fast_git_wsl", action="store_false", help="Scan untracked files even on WSL /mnt/* drives")
    parser.add_argument("--git-timeout", type=int, default=None, metavar="MS", help="Git status timeout in ms (0=disabled, e.g. 500)")
    parser.add_argument("--async-git", dest="async_git", action="store_true", default=None, help="Enable asynchronous background Git status cache")
    parser.add_argument("--no-async-git", dest="async_git", action="store_false", help="Disable asynchronous Git status cache")
    parser.add_argument("--min-duration", type=int, default=None, metavar="MS", help="Minimum command runtime in ms to display DURATION segment (default 2000)")
    parser.add_argument("--ascii-safe", action="store_true", help="Use ASCII-safe separators & Git symbols (for SSH hosts without Nerd Fonts)")
    parser.add_argument("--sync-root", action="store_true", help="Generate/sync synth-shell-prompt.root.config from active theme")
    parser.add_argument("--sync-greeter", action="store_true", help="Sync active theme palette to synth-shell-greeter.config")
    parser.add_argument("--greeter-monitors", default=None, metavar="LIST", help='Set greeter monitors (e.g. "OS KERNEL CPU MEMORY_MON HDDROOT_MON")')
    parser.add_argument("--hide-swap", action="store_true", help="Hide SWAP_MON in greeter config when host has no swap")
    parser.add_argument("-r", "--random", action="store_true", help="Apply a random theme and exit")
    parser.add_argument("-s", "--search", metavar="TERM", help="Search themes by name, slug, or badge and exit")
    parser.add_argument("-w", "--web", action="store_true", help="Launch live interactive Web Studio in your browser")
    parser.add_argument("--port", type=int, default=7778, help="Port for --web server (default: 7778)")
    parser.add_argument("--no-browser", action="store_true", help="Do not open browser automatically with --web")
    parser.add_argument("-b", "--backup", action="store_true", help="Create a timestamped backup of synth-shell-prompt.config")
    parser.add_argument("--backups", action="store_true", help="List available configuration backups")
    parser.add_argument("-u", "--restore", nargs="?", const="1", metavar="ID_OR_NAME", help="Restore latest (or specified) backup")
    parser.add_argument("--no-clear", action="store_true", help="Do not clear screen between pages in TUI mode")

    args = parser.parse_args(raw_args)
    themes = load_themes()
    current_name, current_idx = detect_current_theme(themes)

    if args.backup:
        bak = backup_config()
        if bak:
            print(f"Backup created: {bak}")
            return 0
        print("No config file found to back up.", file=sys.stderr)
        return 1

    if args.backups:
        baks = list_backups()
        if not baks:
            print("No backups found.")
            return 0
        print(f"\n  {BOLD}Saved Configuration Backups ({len(baks)}):{RESET}")
        for b in baks:
            print(f"    #{b['id']:02d}  {b['modified']}  {b['name']}")
        print()
        return 0

    if args.restore is not None:
        restored = restore_backup(args.restore)
        if not restored:
            print(f"Error: Backup '{args.restore}' not found.", file=sys.stderr)
            return 1
        print(f"Restored configuration from: {restored}")
        return 0

    if args.current:
        (int_g, int_c), end_t = detect_current_separators()
        end_g, end_c = end_t if end_t else (int_g, int_c)
        if current_name:
            idx_str = f" (#{current_idx})" if current_idx else ""
            print(f"Current theme:      {BOLD}{current_name}{RESET}{idx_str}")
        else:
            print("Current theme:      none detected")
        print(f"Internal separator: {BOLD}{int_g}{RESET} ({int_c})")
        print(f"Ending separator:   {BOLD}{end_g}{RESET} ({end_c})")
        return 0

    if args.palette:
        print_character_palette_table()
        return 0

    if args.separators:
        print_separator_showcase()
        return 0

    if args.web:
        from synth_shell_theme.server import run_studio_server

        run_studio_server(port=args.port, open_browser=not args.no_browser)
        return 0

    if args.list:
        print_theme_list(themes, current_name)
        return 0

    if args.search:
        matches = filter_themes(args.search, themes)
        if not matches:
            print(f"No themes matching '{args.search}'.")
            return 0
        (sep_int, _), end_t = detect_current_separators()
        sep_end = end_t[0] if end_t else sep_int
        print()
        print(f"{BOLD}  Themes matching '{args.search}' ({len(matches)} matches):{RESET}")
        print()
        cards = [
            build_card_lines(t, orig_idx, current_name, sep=sep_int, sep_end=sep_end)
            for orig_idx, t in matches
        ]
        print_side_by_side(cards, 1, 74)
        return 0

    did_non_interactive = False
    chosen_theme: dict[str, object] | None = None

    if args.toggle_theme:
        res_tog = toggle_light_dark_theme(light_slug=args.light_theme, dark_slug=args.dark_theme)
        print(f"Toggled to {res_tog['mode']} theme: {BOLD}{res_tog['theme']}{RESET} ({res_tog['config_path']})")
        did_non_interactive = True
    elif args.random:
        pick_t = random.choice(themes)
        chosen_theme = pick_t
        res = apply_theme(pick_t, force_white=args.force_white_text, keep_input=args.keep_input)
        report_theme_applied(res, force_white=args.force_white_text, keep_input=args.keep_input)
        did_non_interactive = True
    elif args.apply:
        theme, _ = find_theme(args.apply, themes)
        if not theme:
            print(
                f"Error: Theme '{args.apply}' not found. Run `synth-shell-theme --list` to view all 64 themes.",
                file=sys.stderr,
            )
            return 1
        chosen_theme = theme
        res = apply_theme(theme, force_white=args.force_white_text, keep_input=args.keep_input)
        report_theme_applied(res, force_white=args.force_white_text, keep_input=args.keep_input)
        did_non_interactive = True

    if args.ascii_safe:
        res_ascii = apply_ascii_safe_mode()
        print(f"Applied ASCII-safe separators & Git symbols to {res_ascii['config_path']}")
        did_non_interactive = True
    elif args.dual:
        g1, c1, l1 = resolve_separator_input(args.dual[0])
        g2, c2, l2 = resolve_separator_input(args.dual[1])
        res_s = apply_separators(internal=(g1, c1), end=(g2, c2))
        report_separators_applied(res_s, label=f"{l1} + {l2}")
        did_non_interactive = True
    elif args.separator:
        g, c, label = resolve_separator_input(args.separator)
        res_s = apply_separators(internal=(g, c), end=(g, c))
        report_separators_applied(res_s, label=label)
        did_non_interactive = True
    else:
        if args.internal:
            g, c, label = resolve_separator_input(args.internal)
            res_s = apply_separators(internal=(g, c))
            report_separators_applied(res_s, label=f"Internal: {label}")
            did_non_interactive = True
        if args.end:
            g, c, label = resolve_separator_input(args.end)
            res_s = apply_separators(end=(g, c))
            report_separators_applied(res_s, label=f"Ending: {label}")
            did_non_interactive = True

    has_layout = any(
        x is not None
        for x in (
            args.format,
            args.right_format,
            args.right_fill,
            args.osc133,
            args.git_state,
            args.battery_threshold,
            args.two_line,
            args.max_pwd,
            args.max_git,
            args.max_pyenv,
            args.max_kube,
            args.compact_width,
            args.git_counts,
            args.transient,
            args.light_theme if not args.toggle_theme else None,
            args.dark_theme if not args.toggle_theme else None,
            args.prefix,
            args.text_effect,
            args.terminal_title,
            args.fast_git_wsl,
            args.git_timeout,
            args.async_git,
            args.min_duration,
        )
    )
    if has_layout:
        res_l = apply_layout_options(
            format_str=args.format,
            right_format_str=args.right_format,
            right_fill_char=args.right_fill,
            enable_osc133=args.osc133,
            git_show_state=args.git_state,
            battery_threshold=args.battery_threshold,
            new_line=args.two_line,
            max_pwd_char=args.max_pwd,
            max_git_char=args.max_git,
            max_pyenv_char=args.max_pyenv,
            max_kube_char=args.max_kube,
            compact_width=args.compact_width,
            git_show_counts=args.git_counts,
            transient_prompt=args.transient,
            light_theme=args.light_theme if not args.toggle_theme else None,
            dark_theme=args.dark_theme if not args.toggle_theme else None,
            prompt_prefix=args.prefix,
            font_effect=args.text_effect,
            enable_terminal_title=args.terminal_title,
            git_skip_untracked_on_slow_fs=args.fast_git_wsl,
            git_timeout_ms=args.git_timeout,
            git_async_cache=args.async_git,
            min_duration_ms=args.min_duration,
        )
        print(f"Updated layout & performance options in {res_l['config_path']}")
        did_non_interactive = True

    if args.sync_root:
        res_root = sync_root_config(theme=chosen_theme)
        print(f"Synced root prompt config ({res_root['theme']}) -> {res_root['root_config_path']}")
        did_non_interactive = True

    if args.sync_ecosystem:
        res_eco = sync_ecosystem(theme=chosen_theme)
        print(f"Synced ecosystem ({res_eco['theme']}) -> {res_eco['env_script']} & {res_eco['tmux_conf']}")
        did_non_interactive = True

    if args.sync_greeter or args.greeter_monitors is not None or args.hide_swap:
        mons = (
            [tok.strip() for tok in args.greeter_monitors.replace(",", " ").split() if tok.strip()]
            if args.greeter_monitors is not None
            else None
        )
        res_g = sync_greeter_theme(
            theme=chosen_theme,
            monitors=mons,
            hide_swap_if_unavailable=args.hide_swap,
        )
        print(f"Synced greeter config ({res_g['theme']}) -> {res_g['config_path']}")
        did_non_interactive = True

    if did_non_interactive:
        return 0

    run_theme_tui(
        themes,
        clear_screen_enabled=not args.no_clear,
        force_white=args.force_white_text,
        keep_input=args.keep_input,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
