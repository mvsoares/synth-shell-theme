"""Interactive Terminal UI (TUI) for browsing 64 themes and editing dual Powerline separators."""

from __future__ import annotations

import random
import shutil
import sys

from synth_shell_theme.core import (
    apply_separators,
    apply_theme,
    backup_config,
    detect_current_separators,
    detect_current_theme,
    list_backups,
    read_current_state,
    restore_backup,
)
from synth_shell_theme.paths import get_config_path
from synth_shell_theme.separators import (
    ALL_PRESETS,
    CATEGORIES,
    CHARACTER_PALETTE,
    find_preset,
    get_separator_key,
    resolve_separator_input,
)
from synth_shell_theme.themes import (
    BOLD,
    DIM,
    RESET,
    ansi_bg,
    build_card_lines,
    color_index,
    filter_themes,
    find_theme,
    load_themes,
    pad_to,
    render_prompt_line,
)

GUTTER = "   "


def _clear_screen(enabled: bool = True) -> None:
    if enabled and sys.stdout.isatty():
        sys.stdout.write("\033[H\033[2J")
        sys.stdout.flush()
    else:
        print()


def print_side_by_side(cards: list[list[str]], cols: int, col_width: int) -> None:
    """Print rendered theme cards arranged in a multi-column grid."""
    for row_start in range(0, len(cards), cols):
        row_cards = [list(c) for c in cards[row_start : row_start + cols]]
        max_lines = max(len(c) for c in row_cards)
        for c in row_cards:
            while len(c) < max_lines:
                c.append("")
        for line_idx in range(max_lines):
            parts = [pad_to(card[line_idx], col_width) for card in row_cards]
            print(GUTTER.join(parts))
        print()


def print_theme_list(themes: list[dict[str, object]], current_name: str | None) -> None:
    """Print compact numbered list of all 64 themes with 256-color swatches."""
    print()
    print(f"{BOLD}  Synth-Shell Prompt Theme Gallery ({len(themes)} themes){RESET}")
    print(f"  {DIM}Host · PWD · Git swatches (256-color){RESET}")
    print()
    for i, t in enumerate(themes, 1):
        name = str(t.get("name", "Unknown"))
        badge = str(t.get("badge", ""))
        h_bg = color_index(str(t.get("background_host", "0")))
        p_bg = color_index(str(t.get("background_pwd", "0")))
        g_bg = color_index(str(t.get("background_git", "0")))
        swatch = f"{ansi_bg(h_bg)}  {ansi_bg(p_bg)}  {ansi_bg(g_bg)}  {RESET}"
        badge_str = f" {DIM}[{badge}]{RESET}" if badge else ""
        active = f"  \033[33;1m← active{RESET}" if current_name and name == current_name else ""
        print(f"  {BOLD}#{i:02d}{RESET}  {swatch}  {name}{badge_str}{active}")
    print()


def print_character_palette_table() -> None:
    """Print visual cheat-sheet table of 60+ Nerd Font & Unicode separator glyphs."""
    print()
    print(f"  {BOLD}╔═════════════════════════════════════════════════════════════════════════════════════════╗{RESET}")
    print(f"  {BOLD}║              Nerd Font & Unicode Character Palette (60+ Glyphs)                         ║{RESET}")
    print(f"  {BOLD}╚═════════════════════════════════════════════════════════════════════════════════════════╝{RESET}")
    print()

    for title, items in CHARACTER_PALETTE.items():
        bar = "─" * max(4, 75 - len(title))
        print(f"  {BOLD}\033[36m── {title} ({len(items)} glyphs) {bar}{RESET}")
        for i in range(0, len(items), 4):
            row = items[i : i + 4]
            cells = [
                f" {BOLD}{ch}{RESET}  \033[33m\\u{hex_code:<5}\033[0m {DIM}{desc:<11}{RESET}"
                for ch, hex_code, desc in row
            ]
            print("  " + "  ".join(cells))
        print()

    print(
        f"  {DIM}Pick any character by its {BOLD}Hex Code{RESET}{DIM} (e.g. E0B4, F0E7), "
        f"{BOLD}Name{RESET}{DIM} (e.g. bubble, lightning), or paste a symbol.{RESET}"
    )
    print()


def _active_preview_theme(themes: list[dict[str, object]] | None = None) -> dict[str, object]:
    """Return active colors from `synth-shell-prompt.config`, falling back to Tokyo Night."""
    catalog = themes if themes is not None else load_themes()
    state = read_current_state(catalog)
    colors = state.get("colors")
    if isinstance(colors, dict) and colors.get("background_host"):
        merged: dict[str, object] = {"name": state.get("active_theme") or "Active Prompt"}
        merged.update(colors)
        return merged
    tokyo, _ = find_theme("tokyo-night", catalog)
    return tokyo if tokyo else catalog[0]


def render_separator_sample(
    internal_sep: str,
    theme: dict[str, object],
    end_sep: str | None = None,
) -> str:
    """Render a 3-segment live sample prompt with `internal_sep` and `end_sep`."""
    return render_prompt_line(
        theme,
        [("host", "dev"), ("pwd", "~/workspace/app"), ("git", "main")],
        "git status",
        sep=internal_sep,
        sep_end=end_sep if end_sep else internal_sep,
    )


def print_separator_showcase(
    theme: dict[str, object] | None = None,
    current_glyph: str | None = None,
) -> None:
    """Print categorized showcase of all 48 Powerline & Nerd Font separator presets."""
    preview_theme = theme if theme is not None else _active_preview_theme()
    if current_glyph is None:
        (current_glyph, _), _ = detect_current_separators()

    print()
    print(f"{BOLD}  Synth-Shell Powerline Separator Gallery ({len(ALL_PRESETS)} presets){RESET}")
    print(f"  {DIM}Live sample previews rendered with your prompt colors:{RESET}")
    print()

    counter = 1
    for cat_name, items in CATEGORIES.items():
        print(f"  {BOLD}\033[36m── {cat_name} ──────────────────────────────────────{RESET}")
        print()
        for key, glyph, code, desc in items:
            active = f"  \033[33;1m← active{RESET}" if glyph == current_glyph else ""
            sample = render_separator_sample(glyph, preview_theme)
            print(f"    {BOLD}#{counter:02d}{RESET}  {glyph}  {BOLD}{key:<16}{RESET}  ({code})  {desc}{active}")
            print(f"         {sample}")
            print()
            counter += 1


def report_theme_applied(
    res: dict[str, object],
    force_white: bool = False,
    keep_input: bool = False,
) -> None:
    """Print user-friendly summary and reload instructions after applying a theme."""
    idx = res.get("theme_id")
    idx_str = f" (#{idx})" if idx else ""
    print()
    print(f"  Selected: {BOLD}{res.get('theme')}{RESET}{idx_str}")
    if force_white:
        print(f"  Mode:     {BOLD}High-Contrast White Text{RESET} (segment foregrounds forced to white)")
    if keep_input:
        print(f"  Input:    {BOLD}Preserved existing font_color_input{RESET}")
    if res.get("backup"):
        print(f"  Backup:   {res['backup']}")
    print(f"  Applied:  {res['config_path']}")
    print()
    print(f"  {BOLD}Theme applied!{RESET} Reload your current Bash session with:")
    print(f"    {BOLD}source ~/.config/synth-shell/synth-shell-prompt.sh{RESET}")
    print()


def report_separators_applied(res: dict[str, object], label: str = "") -> None:
    """Print user-friendly summary after applying internal/ending separators."""
    print()
    print(f"  {BOLD}Separators applied!{RESET}")
    if label:
        print(f"  Preset:   {BOLD}{label}{RESET}")
    internal = res.get("internal")
    if isinstance(internal, dict):
        print(f"  Internal: {BOLD}{internal['glyph']}{RESET}  ({internal['code']})")
    end = res.get("end")
    if isinstance(end, dict):
        print(f"  Ending:   {BOLD}{end['glyph']}{RESET}  ({end['code']})")
    if res.get("backup"):
        print(f"  Backup:   {res['backup']}")
    print(f"  Config:   {res['config_path']}")
    print()
    print(f"  Reload your current Bash session with:")
    print(f"    {BOLD}source ~/.config/synth-shell/synth-shell-prompt.sh{RESET}")
    print()


def run_separator_tui(
    clear_screen: bool = True,
    return_on_apply: bool = True,
) -> str | None:
    """Interactive Dual Separator & 60+ Glyph Palette Editor."""
    status_msg = ""
    while True:
        theme = _active_preview_theme()
        (cur_int_glyph, cur_int_code), end_tuple = detect_current_separators()
        cur_end_glyph = end_tuple[0] if end_tuple else cur_int_glyph
        cur_end_code = end_tuple[1] if end_tuple else cur_int_code
        end_note = f" ({cur_end_code})" if end_tuple else " (same as internal)"

        _clear_screen(clear_screen)
        print(f"{BOLD}  Synth-Shell Powerline Separator Editor{RESET}  —  {len(ALL_PRESETS)} presets + dual separators")
        print(f"  Internal separator: \033[36;1m{cur_int_glyph}\033[0m ({cur_int_code})  [between segments]")
        print(f"  Ending separator:   \033[33;1m{cur_end_glyph}\033[0m{end_note}  [final cap before command]")
        print(f"  Live prompt:        {render_separator_sample(cur_int_glyph, theme, cur_end_glyph)}")
        print(f"  Config:             {get_config_path()}")
        print()

        counter = 1
        for cat_name, items in CATEGORIES.items():
            print(f"  \033[36m── {cat_name} ──{RESET}")
            for key, glyph, code, desc in items:
                active = f"  \033[33;1m← active{RESET}" if glyph == cur_int_glyph else ""
                sample = render_separator_sample(glyph, theme, cur_end_glyph if end_tuple else glyph)
                print(f"  {BOLD}#{counter:02d}{RESET}  {glyph}  {BOLD}{key:<16}{RESET}  {desc}{active}")
                print(f"       {sample}")
                counter += 1
            print()

        if status_msg:
            print(f"  {status_msg}")
            print()
            status_msg = ""

        nav = [
            f"[1-{len(ALL_PRESETS)}|name] apply both",
            "[m]ix dual",
            "[i]nternal only",
            "[e]nding only",
            "[c]ustom 60+ palette",
            "[p <sep>] preview",
            "[r]andom",
            "[q]uit",
        ]
        try:
            choice = input(f"  {' | '.join(nav)}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return None

        if not choice:
            continue
        cmd = choice.lower()

        if cmd in ("q", "quit", "exit"):
            return None
        if cmd in ("r", "random"):
            key, glyph, code, desc = random.choice(ALL_PRESETS)
            res = apply_separators(internal=(glyph, code), end=(glyph, code))
            msg = f"Separator set to {key} ({glyph})"
            if return_on_apply:
                report_separators_applied(res, label=f"{key} ({desc})")
                return msg
            status_msg = f"\033[32m{msg}\033[0m"
            continue

        if cmd in ("m", "mix", "dual"):
            print()
            print(f"  {BOLD}Step 1: Internal Separator{RESET} (between Host, PWD, Git, etc.)")
            try:
                raw_int = input(
                    f"  Pick INTERNAL [name, #id, hex, glyph] (Enter to keep '{cur_int_glyph}'): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            int_glyph, int_code, int_label = (
                resolve_separator_input(raw_int) if raw_int else (cur_int_glyph, cur_int_code, "Current")
            )

            print()
            print(f"  {BOLD}Step 2: Ending Separator{RESET} (final transition before typed command)")
            try:
                raw_end = input(
                    f"  Pick ENDING [e.g. arrow, zap, rocket, flame] (Enter to keep '{cur_end_glyph}'): "
                ).strip()
            except (EOFError, KeyboardInterrupt):
                continue
            end_glyph, end_code, end_label = (
                resolve_separator_input(raw_end) if raw_end else (cur_end_glyph, cur_end_code, "Current")
            )

            sample = render_separator_sample(int_glyph, theme, end_glyph)
            print()
            print("  Selected Dual Combination:")
            print(f"    Internal: {BOLD}{int_glyph}{RESET} ({int_code}) — {int_label}")
            print(f"    Ending:   {BOLD}{end_glyph}{RESET} ({end_code}) — {end_label}")
            print(f"    Preview:  {sample}")
            try:
                confirm = input("  Apply this dual separator combination? [Y/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                continue
            if confirm in ("", "y", "yes"):
                res = apply_separators(internal=(int_glyph, int_code), end=(end_glyph, end_code))
                msg = f"Dual separators set: {int_glyph} + {end_glyph}"
                if return_on_apply:
                    report_separators_applied(res, label=f"{int_label} + {end_label}")
                    return msg
                status_msg = f"\033[32m{msg}\033[0m"
            else:
                status_msg = "\033[33mDual separator selection cancelled.\033[0m"
            continue

        if cmd in ("i", "internal") or cmd.startswith("i ") or cmd.startswith("internal "):
            parts = choice.split(None, 1)
            raw = parts[1].strip() if len(parts) > 1 else ""
            if not raw:
                try:
                    raw = input("  Pick INTERNAL separator [name, #id, hex, glyph]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    continue
            if raw:
                g, c, label = resolve_separator_input(raw)
                res = apply_separators(internal=(g, c))
                msg = f"Internal separator set to {g} ({label})"
                if return_on_apply:
                    report_separators_applied(res, label=f"Internal: {label}")
                    return msg
                status_msg = f"\033[32m{msg}\033[0m"
            continue

        if cmd in ("e", "end", "last") or cmd.startswith("e ") or cmd.startswith("end "):
            parts = choice.split(None, 1)
            raw = parts[1].strip() if len(parts) > 1 else ""
            if not raw:
                try:
                    raw = input("  Pick ENDING separator [name, #id, hex, glyph]: ").strip()
                except (EOFError, KeyboardInterrupt):
                    continue
            if raw:
                g, c, label = resolve_separator_input(raw)
                res = apply_separators(end=(g, c))
                msg = f"Ending separator set to {g} ({label})"
                if return_on_apply:
                    report_separators_applied(res, label=f"Ending: {label}")
                    return msg
                status_msg = f"\033[32m{msg}\033[0m"
            continue

        if cmd in ("c", "custom", "palette", "table"):
            _clear_screen(clear_screen)
            print_character_palette_table()
            try:
                raw_char = input("  Pick character [name, hex, or glyph] (Enter to cancel): ").strip()
            except (EOFError, KeyboardInterrupt):
                continue
            if not raw_char:
                continue
            glyph, code, label = resolve_separator_input(raw_char)
            sample = render_separator_sample(glyph, theme, glyph)
            print()
            print(f"  Selected: {BOLD}{glyph}{RESET}  (Code: {code}, Label: {label})")
            print(f"  Preview:  {sample}")
            try:
                target = input("  Apply to [b]oth, [i]nternal only, [e]nding only, or [n]o? [B/i/e/n]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                continue
            if target in ("", "b", "both", "y", "yes"):
                res = apply_separators(internal=(glyph, code), end=(glyph, code))
            elif target in ("i", "internal"):
                res = apply_separators(internal=(glyph, code))
            elif target in ("e", "end", "ending"):
                res = apply_separators(end=(glyph, code))
            else:
                status_msg = "\033[33mCancelled.\033[0m"
                continue
            msg = f"Applied custom glyph {glyph} ({code})"
            if return_on_apply:
                report_separators_applied(res, label=label)
                return msg
            status_msg = f"\033[32m{msg}\033[0m"
            continue

        if cmd.startswith("p ") or cmd.startswith("preview "):
            raw_parts = choice.split()[1:]
            if len(raw_parts) >= 2:
                g1, _, _ = resolve_separator_input(raw_parts[0])
                g2, _, _ = resolve_separator_input(raw_parts[1])
                status_msg = f"Dual Preview ({g1} + {g2}): {render_separator_sample(g1, theme, g2)}"
            elif raw_parts:
                g, c, _ = resolve_separator_input(raw_parts[0])
                status_msg = f"Preview for \033[1m{g}\033[0m ({c}): {render_separator_sample(g, theme, g)}"
            continue

        preset = find_preset(choice)
        if preset:
            key, glyph, code, desc = preset
            res = apply_separators(internal=(glyph, code), end=(glyph, code))
            msg = f"Separator set to {key} ({glyph})"
            if return_on_apply:
                report_separators_applied(res, label=f"{key} ({desc})")
                return msg
            status_msg = f"\033[32m{msg}\033[0m"
            continue

        g, c, label = resolve_separator_input(choice)
        if label != "Custom" or len(choice) == 1:
            res = apply_separators(internal=(g, c), end=(g, c))
            msg = f"Separator set to {g} ({label})"
            if return_on_apply:
                report_separators_applied(res, label=label)
                return msg
            status_msg = f"\033[32m{msg}\033[0m"
            continue

        status_msg = (
            f"\033[31mUnknown choice: '{choice}'. Type 1-{len(ALL_PRESETS)}, "
            f"preset name, [m]ix dual, [c]ustom palette, or [q]uit.\033[0m"
        )


def run_theme_tui(
    themes: list[dict[str, object]] | None = None,
    clear_screen_enabled: bool = True,
    initial_filter: str = "",
    force_white: bool = False,
    keep_input: bool = False,
) -> None:
    """Unified interactive 2-column TUI for browsing 64 themes, editing dual separators, and launching Web Studio."""
    catalog = themes if themes is not None else load_themes()
    filter_query = initial_filter
    total_all = len(catalog)
    page = 0
    status_msg = ""

    while True:
        current_name, _ = detect_current_theme(catalog)
        (sep_int, _), end_tuple = detect_current_separators()
        sep_end = end_tuple[0] if end_tuple else sep_int

        filtered_items = (
            filter_themes(filter_query, catalog)
            if filter_query
            else [(i, t) for i, t in enumerate(catalog, 1)]
        )
        total = len(filtered_items)

        term_cols = shutil.get_terminal_size((120, 24)).columns
        col_width = 74
        num_cols = 2 if term_cols >= col_width * 2 + len(GUTTER) else 1
        if num_cols == 1:
            col_width = max(56, term_cols - 2)

        per_page = num_cols * 5
        total_pages = max(1, (total + per_page - 1) // per_page)
        if page >= total_pages:
            page = total_pages - 1

        _clear_screen(clear_screen_enabled)

        filter_badge = (
            f"  |  Filter: \033[36;1m'{filter_query}'\033[0m ({total} matches)"
            if filter_query
            else ""
        )
        sep_badge = f"  |  Sep: \033[36;1m{sep_int}\033[0m→\033[33;1m{sep_end}\033[0m ({get_separator_key(sep_int)})"
        fw_badge = "  |  \033[35;1m[White Text ON]\033[0m" if force_white else ""
        ki_badge = "  |  \033[32;1m[Keep Input ON]\033[0m" if keep_input else ""

        print(
            f"{BOLD}  Synth-Shell Theme Studio{RESET}  —  {total_all} themes"
            f"{filter_badge}{sep_badge}{fw_badge}{ki_badge}"
        )
        if current_name:
            print(f"  Active theme: \033[33;1m{current_name}\033[0m   |   Config: {get_config_path()}")
        else:
            print(f"  Config: {get_config_path()}")
        print()

        if total == 0:
            print(f"  No themes matching '{filter_query}'. Press [c] to clear filter.")
            print()
        else:
            start = page * per_page
            end = min(start + per_page, total)
            cards = [
                build_card_lines(
                    t,
                    orig_idx,
                    current_name,
                    sep=sep_int,
                    sep_end=sep_end,
                    force_white=force_white,
                )
                for orig_idx, t in filtered_items[start:end]
            ]
            print_side_by_side(cards, num_cols, col_width)

        if status_msg:
            print(f"  {status_msg}")
            print()
            status_msg = ""

        nav = []
        if filter_query:
            nav.append("[c]lear")
        if page > 0:
            nav.append("[p]rev")
        if (page + 1) < total_pages:
            nav.append("[n]ext")
        nav.extend(
            [
                f"[1-{total_all}|name] apply",
                "[s]eparators",
                "[/]search",
                "[f]white-text",
                "[w]eb studio",
                "[u]ndo",
                "[r]andom",
                "[q]uit",
            ]
        )

        page_info = f"  Page {page + 1}/{total_pages}" if total_pages > 1 else " "
        try:
            choice = input(f"{page_info}  {' | '.join(nav)}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled.")
            return

        cmd = choice.lower()
        if not cmd:
            continue
        if cmd in ("q", "quit", "exit"):
            print("  Bye.")
            return
        if cmd in ("n", "next"):
            if (page + 1) < total_pages:
                page += 1
            else:
                status_msg = "\033[33mAlready on last page.\033[0m"
        elif cmd in ("p", "prev", "back"):
            if page > 0:
                page -= 1
            else:
                status_msg = "\033[33mAlready on first page.\033[0m"
        elif cmd.startswith("g ") or cmd.startswith("page "):
            part = cmd.split()[-1]
            if part.isdigit() and 1 <= int(part) <= total_pages:
                page = int(part) - 1
            else:
                status_msg = f"\033[31mPage must be between 1 and {total_pages}.\033[0m"
        elif cmd in ("c", "clear", "all", "/clear"):
            filter_query = ""
            page = 0
        elif cmd == "f" or cmd == "white":
            force_white = not force_white
            state_lbl = "enabled" if force_white else "disabled"
            status_msg = f"\033[36mHigh-contrast white segment text {state_lbl}.\033[0m"
        elif cmd == "k" or cmd == "keep-input":
            keep_input = not keep_input
            state_lbl = "enabled" if keep_input else "disabled"
            status_msg = f"\033[36mKeep existing input color {state_lbl}.\033[0m"
        elif cmd in ("b", "backup"):
            bak = backup_config()
            status_msg = (
                f"\033[32mBackup saved: {bak}\033[0m"
                if bak
                else "\033[33mNo config file found to back up yet.\033[0m"
            )
        elif cmd in ("u", "undo", "restore"):
            baks = list_backups()
            if not baks:
                status_msg = "\033[33mNo backups found.\033[0m"
            else:
                restored = restore_backup(1)
                status_msg = (
                    f"\033[32mRestored backup: {restored.name}\033[0m"
                    if restored
                    else "\033[31mRestore failed.\033[0m"
                )
        elif cmd in ("/", "search") or cmd.startswith("/"):
            if cmd in ("/", "search"):
                try:
                    term = input("  Search themes (name, slug, or badge): ").strip()
                except (EOFError, KeyboardInterrupt):
                    continue
            else:
                term = choice[1:].strip()
            filter_query = term
            page = 0
        elif cmd in ("s", "t", "sep", "separator", "separators"):
            sep_res = run_separator_tui(clear_screen=clear_screen_enabled, return_on_apply=False)
            if sep_res:
                status_msg = f"\033[32m{sep_res}\033[0m"
        elif cmd in ("r", "random"):
            pick_t = random.choice(catalog)
            res = apply_theme(pick_t, force_white=force_white, keep_input=keep_input)
            report_theme_applied(res, force_white=force_white, keep_input=keep_input)
            return
        elif cmd in ("w", "web", "studio"):
            from synth_shell_theme.server import run_studio_server

            run_studio_server(open_browser=True)
            return
        elif cmd in ("?", "help"):
            status_msg = (
                f"{BOLD}Keys:{RESET} [n]ext, [p]rev, [g N] page, [s]eparator editor, "
                f"[/term] search, [f] white-text, [k] keep-input, [b]ackup, [u]ndo, [w]eb studio, [q]uit"
            )
        else:
            target_theme, _ = find_theme(choice, catalog)
            if target_theme:
                res = apply_theme(target_theme, force_white=force_white, keep_input=keep_input)
                report_theme_applied(res, force_white=force_white, keep_input=keep_input)
                return
            status_msg = (
                f"\033[31mTheme not found: '{choice}'. Enter 1-{total_all}, a theme name, or /search.\033[0m"
            )
