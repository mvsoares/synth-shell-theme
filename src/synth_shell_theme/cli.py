"""Command-line interface for `synth-shell-theme` and `synth-shell-separator`."""

from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

from synth_shell_theme import __version__
from synth_shell_theme.core import (
    apply_layout_options,
    apply_separators,
    apply_theme,
    backup_config,
    detect_current_separators,
    detect_current_theme,
    export_preset,
    import_preset,
    list_backups,
    read_current_state,
    restore_backup,
)
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
    report = {
        "version": __version__,
        "system": summary,
        "patches": patches,
        "active_theme": state["active_theme"],
        "active_theme_id": state["active_theme_id"],
        "internal_separator": state["internal_separator"],
        "end_separator": state["end_separator"],
    }
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0

    ok_tag = "\033[32;1mOK\033[0m"
    warn_tag = "\033[33;1mMISSING\033[0m"

    print()
    print(f"  {BOLD}Synth-Shell Theme Doctor{RESET} (v{__version__})")
    print(f"  {DIM}{'─' * 58}{RESET}")
    print(f"  OS / Python:      {summary['os']} ({summary['python']})")
    print(f"  Bundled themes:   {summary['bundled_themes']} themes + {len(ALL_PRESETS)} separator presets")
    print(f"  Config file:      {summary['config_path']} [{ok_tag if summary['config_exists'] else warn_tag}]")
    print(f"  Prompt script:    {summary['prompt_script_path']} [{ok_tag if summary['prompt_script_exists'] else warn_tag}]")
    print(f"  Backups saved:    {summary['backup_count']} ({summary['backup_dir']})")
    print(f"  Active theme:     {state['active_theme'] or 'None detected'}")
    int_sep = state["internal_separator"]
    end_sep = state["end_separator"]
    print(
        f"  Separators:       internal={int_sep['glyph']} ({int_sep['code']})  "  # type: ignore[index]
        f"end={end_sep['glyph']} ({end_sep['code']})"  # type: ignore[index]
    )
    print()
    print(f"  {BOLD}Runtime Patches & Optimizations:{RESET}")
    patch_labels = [
        ("kube_fast", "Zero-subshell Kubernetes context reader (no yq needed)"),
        ("git_single_pass", "Single-pass `git status --porcelain -b` (4x speedup)"),
        ("dual_separator", "Independent ending separator (`separator_char_end`)"),
        ("color_256_parity", "Full 0-255 & 16-named-color parity across scripts"),
    ]
    for key, desc in patch_labels:
        badge = ok_tag if patches.get(key) else warn_tag
        print(f"    [{badge}] {desc}")
    if not patches.get("all_applied") and summary["prompt_script_exists"]:
        print()
        print(f"  Tip: Run {BOLD}synth-shell-theme init{RESET} to apply missing runtime optimizations.")
    print()
    return 0


def _cmd_init(install_missing: bool = False, tune_defaults: bool = True, theme_choice: str | None = None) -> int:
    prompt_sh = get_prompt_script_path()
    if not prompt_sh.is_file() and install_missing:
        print("  Installing upstream synth-shell into ~/.config/synth-shell ...")
        if install_upstream_synth_shell():
            print("  \033[32;1m✓\033[0m Upstream synth-shell installed.")
        else:
            print("  \033[31;1m✗\033[0m Failed to install upstream synth-shell automatically.")
            return 1

    res = apply_runtime_patches(tune_defaults=tune_defaults)
    changes = res["changes"]
    status = res["status"]

    if theme_choice:
        themes = load_themes()
        found, _ = find_theme(theme_choice, themes)
        if not found:
            print(f"Error: Theme '{theme_choice}' not found.", file=sys.stderr)
            return 1
        apply_theme(found)

    print()
    print(f"  {BOLD}Synth-Shell Runtime Initialization{RESET}")
    if changes:
        for item in changes:  # type: ignore[union-attr]
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

    # Subcommand routing (`web`/`studio`, `sep`/`separators`, `init`, `doctor`, `export`, `import`, `tui`)
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
                description="Apply idempotent runtime & performance patches to synth-shell.",
            )
            init_parser.add_argument("--install", action="store_true", help="Clone & install upstream synth-shell if missing")
            init_parser.add_argument("--no-tune", action="store_true", help="Do not update default max_pwd_char / 2-line config options")
            init_parser.add_argument("-a", "--apply", metavar="THEME", help="Also apply a theme by number or slug")
            i_args = init_parser.parse_args(rest)
            return _cmd_init(install_missing=i_args.install, tune_defaults=not i_args.no_tune, theme_choice=i_args.apply)

        if sub == "doctor":
            doc_parser = argparse.ArgumentParser(
                prog="synth-shell-theme doctor",
                description="Inspect synth-shell paths, active theme, backups, and runtime patches.",
            )
            doc_parser.add_argument("--json", action="store_true", help="Output diagnostics as JSON")
            d_args = doc_parser.parse_args(rest)
            return _cmd_doctor(as_json=d_args.json)

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
            "and Live Web Studio for synth-shell."
        ),
        epilog=(
            "Subcommands:\n"
            "  synth-shell-theme                Launch interactive 2-column TUI\n"
            "  synth-shell-theme web            Launch live browser-based Web Studio (port 7778)\n"
            "  synth-shell-theme sep            Launch interactive Dual Separator & 60+ Glyph Editor\n"
            "  synth-shell-theme init           Apply 4 runtime & speed patches to synth-shell\n"
            "  synth-shell-theme doctor         Check config, backups, and runtime patch health\n"
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
    parser.add_argument("--format", metavar="SEGMENTS", help='Set prompt segment order (e.g. "HOST PWD GIT PYENV TF KUBE")')
    parser.add_argument("--two-line", dest="two_line", action="store_true", default=None, help="Enable 2-line command prompt")
    parser.add_argument("--single-line", dest="two_line", action="store_false", help="Enable compact 1-line command prompt")
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

    if args.random:
        pick_t = random.choice(themes)
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
        res = apply_theme(theme, force_white=args.force_white_text, keep_input=args.keep_input)
        report_theme_applied(res, force_white=args.force_white_text, keep_input=args.keep_input)
        did_non_interactive = True

    if args.dual:
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

    if args.format is not None or args.two_line is not None:
        res_l = apply_layout_options(format_str=args.format, new_line=args.two_line)
        print(f"Updated layout options in {res_l['config_path']}")
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
