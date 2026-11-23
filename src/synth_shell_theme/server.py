"""Local HTTP Web Studio server for synth-shell-theme (zero external dependencies, v1.1.0)."""

from __future__ import annotations

import json
import socket
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from synth_shell_theme import __version__
from synth_shell_theme.core import (
    VALID_FONT_EFFECTS,
    VALID_FORMAT_TOKENS,
    apply_ascii_safe_mode,
    apply_layout_options,
    apply_separators,
    apply_theme,
    backup_config,
    benchmark_prompt,
    list_backups,
    read_current_state,
    read_greeter_state,
    restore_backup,
    sync_greeter_theme,
    sync_root_config,
    toggle_light_dark_theme,
)
from synth_shell_theme.ecosystem import sync_ecosystem
from synth_shell_theme.patches import apply_runtime_patches
from synth_shell_theme.paths import (
    detect_nerd_fonts,
    detect_terminal_capabilities,
    detect_utf8_locale,
    get_assets_dir,
    get_config_dir,
)
from synth_shell_theme.separators import resolve_separator_input, serialize_separators_for_web
from synth_shell_theme.themes import (
    BOLD,
    DIM,
    RESET,
    find_theme,
    load_themes,
    save_custom_theme,
    serialize_theme_for_web,
)


def build_bootstrap_payload(config_dir: Path | None = None) -> dict[str, object]:
    """Assemble full initial JSON state for the Web Studio frontend."""
    base = config_dir if config_dir is not None else get_config_dir()
    themes = load_themes(config_dir=base)
    serialized_themes = [serialize_theme_for_web(t, idx) for idx, t in enumerate(themes, 1)]
    nf = detect_nerd_fonts()
    return {
        "version": __version__,
        "themes": serialized_themes,
        "separators": serialize_separators_for_web(),
        "valid_segments": list(VALID_FORMAT_TOKENS),
        "valid_font_effects": list(VALID_FONT_EFFECTS),
        "state": read_current_state(themes, base),
        "greeter": read_greeter_state(base),
        "diagnostics": {
            "locale": detect_utf8_locale(),
            "nerd_fonts": nf,
            "terminal": detect_terminal_capabilities(nf),
        },
        "backups": list_backups(base),
    }


def handle_apply_payload(
    payload: dict[str, object],
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Apply theme, dual separators, layout, truncation, speed, and sync options atomically."""
    base = config_dir if config_dir is not None else get_config_dir()
    themes = load_themes()
    bak = backup_config(base)
    applied: list[str] = []
    chosen_theme: dict[str, object] | None = None

    if "theme" in payload and payload["theme"] not in (None, ""):
        query = payload["theme"]
        theme, _ = find_theme(query, themes)  # type: ignore[arg-type]
        if not theme:
            raise ValueError(f"Theme not found: {query}")
        chosen_theme = theme
        force_white = bool(payload.get("force_white", False))
        keep_input = bool(payload.get("keep_input", False))
        res_t = apply_theme(
            theme,
            force_white=force_white,
            keep_input=keep_input,
            create_backup=False,
            config_dir=base,
        )
        applied.append(f"Theme: {res_t['theme']}")

    if payload.get("ascii_safe"):
        apply_ascii_safe_mode(create_backup=False, config_dir=base)
        applied.append("ASCII-Safe Mode")
    else:
        int_raw = payload.get("internal_separator")
        end_raw = payload.get("end_separator")
        int_tuple: tuple[str, str] | None = None
        end_tuple: tuple[str, str] | None = None
        if isinstance(int_raw, str) and int_raw.strip():
            g, c, _ = resolve_separator_input(int_raw.strip())
            int_tuple = (g, c)
        if isinstance(end_raw, str) and end_raw.strip():
            g, c, _ = resolve_separator_input(end_raw.strip())
            end_tuple = (g, c)
        if int_tuple is not None or end_tuple is not None:
            apply_separators(
                internal=int_tuple,
                end=end_tuple,
                create_backup=False,
                config_dir=base,
            )
            applied.append("Separators updated")

    layout_keys = (
        "format",
        "right_format",
        "right_fill_char",
        "enable_osc133",
        "git_show_state",
        "battery_threshold",
        "enable_command_on_new_line",
        "enable_vertical_padding",
        "max_pwd_char",
        "max_git_char",
        "max_pyenv_char",
        "max_kube_char",
        "compact_width",
        "git_show_counts",
        "transient_prompt",
        "light_theme",
        "dark_theme",
        "prompt_prefix",
        "font_effect",
        "enable_terminal_title",
        "git_skip_untracked_on_slow_fs",
        "git_timeout_ms",
        "git_async_cache",
        "min_duration_ms",
    )
    if any(k in payload for k in layout_keys):
        fmt_raw = payload.get("format")
        if isinstance(fmt_raw, list):
            fmt_str: str | None = " ".join(str(x) for x in fmt_raw)
        elif isinstance(fmt_raw, str):
            fmt_str = fmt_raw
        else:
            fmt_str = None

        rfmt_raw = payload.get("right_format")
        if isinstance(rfmt_raw, list):
            rfmt_str: str | None = " ".join(str(x) for x in rfmt_raw)
        elif isinstance(rfmt_raw, str):
            rfmt_str = rfmt_raw
        else:
            rfmt_str = None

        apply_layout_options(
            format_str=fmt_str,
            right_format_str=rfmt_str,
            right_fill_char=str(payload["right_fill_char"]) if "right_fill_char" in payload else None,
            enable_osc133=bool(payload["enable_osc133"]) if "enable_osc133" in payload else None,
            git_show_state=bool(payload["git_show_state"]) if "git_show_state" in payload else None,
            battery_threshold=int(payload["battery_threshold"]) if "battery_threshold" in payload else None,  # type: ignore[arg-type]
            new_line=bool(payload["enable_command_on_new_line"]) if "enable_command_on_new_line" in payload else None,
            vertical_padding=bool(payload["enable_vertical_padding"]) if "enable_vertical_padding" in payload else None,
            max_pwd_char=int(payload["max_pwd_char"]) if "max_pwd_char" in payload else None,  # type: ignore[arg-type]
            max_git_char=int(payload["max_git_char"]) if "max_git_char" in payload else None,  # type: ignore[arg-type]
            max_pyenv_char=int(payload["max_pyenv_char"]) if "max_pyenv_char" in payload else None,  # type: ignore[arg-type]
            max_kube_char=int(payload["max_kube_char"]) if "max_kube_char" in payload else None,  # type: ignore[arg-type]
            compact_width=int(payload["compact_width"]) if "compact_width" in payload else None,  # type: ignore[arg-type]
            git_show_counts=bool(payload["git_show_counts"]) if "git_show_counts" in payload else None,
            transient_prompt=bool(payload["transient_prompt"]) if "transient_prompt" in payload else None,
            light_theme=str(payload["light_theme"]) if "light_theme" in payload else None,
            dark_theme=str(payload["dark_theme"]) if "dark_theme" in payload else None,
            prompt_prefix=str(payload["prompt_prefix"]) if "prompt_prefix" in payload else None,
            font_effect=str(payload["font_effect"]) if "font_effect" in payload else None,
            enable_terminal_title=bool(payload["enable_terminal_title"]) if "enable_terminal_title" in payload else None,
            git_skip_untracked_on_slow_fs=(
                bool(payload["git_skip_untracked_on_slow_fs"]) if "git_skip_untracked_on_slow_fs" in payload else None
            ),
            git_timeout_ms=int(payload["git_timeout_ms"]) if "git_timeout_ms" in payload else None,  # type: ignore[arg-type]
            git_async_cache=bool(payload["git_async_cache"]) if "git_async_cache" in payload else None,
            min_duration_ms=int(payload["min_duration_ms"]) if "min_duration_ms" in payload else None,  # type: ignore[arg-type]
            create_backup=False,
            config_dir=base,
        )
        applied.append("Layout & performance options updated")

    if payload.get("sync_root"):
        sync_root_config(theme=chosen_theme, config_dir=base)
        applied.append("Root config synced")

    if payload.get("sync_greeter"):
        sync_greeter_theme(theme=chosen_theme, config_dir=base)
        applied.append("Greeter palette synced")

    return {
        "ok": True,
        "applied": applied,
        "backup": str(bak) if bak else None,
        "state": read_current_state(themes, base),
        "greeter": read_greeter_state(base),
        "backups": list_backups(base),
    }


def create_studio_server(
    host: str = "127.0.0.1",
    port: int = 7778,
    config_dir: Path | None = None,
) -> ThreadingHTTPServer:
    """Create a configured `ThreadingHTTPServer` serving the Synth-Shell Web Studio."""
    studio_html_path = get_assets_dir() / "studio.html"

    class StudioHandler(BaseHTTPRequestHandler):
        def log_message(self, fmt: str, *args: object) -> None:
            return

        def _send_json(self, data: dict[str, object], status: int = HTTPStatus.OK) -> None:
            body = json.dumps(data, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _read_json_body(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0") or "0")
            if length <= 0:
                return {}
            raw = self.rfile.read(length).decode("utf-8", errors="replace")
            parsed = json.loads(raw) if raw.strip() else {}
            if not isinstance(parsed, dict):
                raise ValueError("Expected a JSON object body.")
            return parsed

        def do_GET(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            if route in ("/", "/index.html"):
                if not studio_html_path.is_file():
                    self._send_json({"ok": False, "error": "studio.html asset missing"}, HTTPStatus.NOT_FOUND)
                    return
                html_bytes = studio_html_path.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html_bytes)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(html_bytes)
                return

            if route == "/api/bootstrap":
                self._send_json(build_bootstrap_payload(config_dir))
                return

            if route == "/api/health":
                self._send_json({"ok": True, "version": __version__})
                return

            self._send_json({"ok": False, "error": f"Unknown endpoint: {route}"}, HTTPStatus.NOT_FOUND)

        def do_POST(self) -> None:  # noqa: N802
            route = urlparse(self.path).path
            try:
                body = self._read_json_body()
                if route == "/api/apply":
                    result = handle_apply_payload(body, config_dir)
                    self._send_json(result)
                    return
                if route == "/api/patches":
                    tune = bool(body.get("tune_defaults", False))
                    patch_res = apply_runtime_patches(config_dir=config_dir, tune_defaults=tune)
                    themes = load_themes()
                    self._send_json(
                        {
                            "ok": True,
                            "changes": patch_res["changes"],
                            "state": read_current_state(themes, config_dir),
                            "greeter": read_greeter_state(config_dir),
                            "backups": list_backups(config_dir),
                        }
                    )
                    return
                if route == "/api/ascii-safe":
                    sep = str(body.get("separator", ">"))
                    res_a = apply_ascii_safe_mode(separator=sep, config_dir=config_dir)
                    themes = load_themes()
                    self._send_json(
                        {
                            "ok": True,
                            "result": res_a,
                            "state": read_current_state(themes, config_dir),
                            "backups": list_backups(config_dir),
                        }
                    )
                    return
                if route == "/api/sync-root":
                    accent = str(body.get("root_accent", "196"))
                    res_r = sync_root_config(root_accent=accent, config_dir=config_dir)
                    themes = load_themes()
                    self._send_json(
                        {
                            "ok": True,
                            "result": res_r,
                            "state": read_current_state(themes, config_dir),
                            "backups": list_backups(config_dir),
                        }
                    )
                    return
                if route == "/api/greeter":
                    mons_raw = body.get("monitors")
                    mons = [str(x) for x in mons_raw] if isinstance(mons_raw, list) else None
                    hide_swap = bool(body.get("hide_swap_if_unavailable", False))
                    res_g = sync_greeter_theme(
                        monitors=mons,
                        hide_swap_if_unavailable=hide_swap,
                        config_dir=config_dir,
                    )
                    themes = load_themes(config_dir=config_dir)
                    self._send_json(
                        {
                            "ok": True,
                            "result": res_g,
                            "state": read_current_state(themes, config_dir),
                            "greeter": read_greeter_state(config_dir),
                            "backups": list_backups(config_dir),
                        }
                    )
                    return
                if route == "/api/custom-theme":
                    name = str(body.get("name", "")).strip()
                    colors_raw = body.get("colors", {})
                    if not isinstance(colors_raw, dict):
                        raise ValueError("Expected 'colors' object.")
                    clean_colors = {str(k): str(v) for k, v in colors_raw.items()}
                    saved = save_custom_theme(
                        name=name,
                        colors=clean_colors,
                        description=str(body.get("description", "")),
                        badge=str(body.get("badge", "Custom")),
                        config_dir=config_dir,
                    )
                    if body.get("apply", True):
                        apply_theme(saved, config_dir=config_dir)
                    themes = load_themes(config_dir=config_dir)
                    serialized_themes = [serialize_theme_for_web(t, idx) for idx, t in enumerate(themes, 1)]
                    self._send_json(
                        {
                            "ok": True,
                            "saved_theme": saved["name"],
                            "themes": serialized_themes,
                            "state": read_current_state(themes, config_dir),
                            "backups": list_backups(config_dir),
                        }
                    )
                    return
                if route == "/api/toggle-theme":
                    res_t = toggle_light_dark_theme(
                        light_slug=str(body["light_theme"]) if body.get("light_theme") else None,
                        dark_slug=str(body["dark_theme"]) if body.get("dark_theme") else None,
                        config_dir=config_dir,
                    )
                    themes = load_themes(config_dir=config_dir)
                    self._send_json(
                        {
                            "ok": True,
                            "result": res_t,
                            "state": read_current_state(themes, config_dir),
                            "backups": list_backups(config_dir),
                        }
                    )
                    return
                if route == "/api/bench":
                    runs = int(body.get("iterations", 12))  # type: ignore[arg-type]
                    self._send_json(benchmark_prompt(iterations=runs, config_dir=config_dir))
                    return
                if route == "/api/sync-ecosystem":
                    res_e = sync_ecosystem(config_dir=config_dir)
                    themes = load_themes(config_dir=config_dir)
                    self._send_json(
                        {
                            "ok": True,
                            "result": res_e,
                            "state": read_current_state(themes, config_dir),
                        }
                    )
                    return
                if route == "/api/restore":
                    target = body.get("target", 1)
                    restored = restore_backup(target, config_dir=config_dir)  # type: ignore[arg-type]
                    if not restored:
                        self._send_json({"ok": False, "error": "Backup not found."}, HTTPStatus.NOT_FOUND)
                        return
                    themes = load_themes()
                    self._send_json(
                        {
                            "ok": True,
                            "restored": restored.name,
                            "state": read_current_state(themes, config_dir),
                            "backups": list_backups(config_dir),
                        }
                    )
                    return
                self._send_json({"ok": False, "error": f"Unknown endpoint: {route}"}, HTTPStatus.NOT_FOUND)
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)

    return ThreadingHTTPServer((host, port), StudioHandler)


def _find_available_port(host: str, preferred_port: int, attempts: int = 15) -> int:
    for candidate in range(preferred_port, preferred_port + attempts):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return candidate
            except OSError:
                continue
    return 0


def run_studio_server(
    host: str = "127.0.0.1",
    port: int = 7778,
    open_browser: bool = True,
    config_dir: Path | None = None,
) -> None:
    """Start the local Web Studio server and open it in the user's browser."""
    actual_port = _find_available_port(host, port)
    server = create_studio_server(host=host, port=actual_port, config_dir=config_dir)
    bound_port = server.server_address[1]
    url = f"http://{host}:{bound_port}"

    print()
    print(f"  {BOLD}Synth-Shell Theme Web Studio{RESET} v{__version__}")
    print(f"  Live URL:  \033[36;1m{url}\033[0m")
    print(f"  {DIM}Press Ctrl+C to stop the server.{RESET}")
    print()

    if open_browser:
        try:
            webbrowser.open(url)
        except Exception:
            pass

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n  Stopping Web Studio server. Bye!")
    finally:
        server.server_close()
