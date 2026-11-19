"""Local HTTP Web Studio server for synth-shell-theme (zero external dependencies)."""

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
    VALID_FORMAT_TOKENS,
    apply_layout_options,
    apply_separators,
    apply_theme,
    backup_config,
    list_backups,
    read_current_state,
    restore_backup,
)
from synth_shell_theme.patches import apply_runtime_patches
from synth_shell_theme.paths import get_assets_dir, get_config_dir
from synth_shell_theme.separators import resolve_separator_input, serialize_separators_for_web
from synth_shell_theme.themes import BOLD, DIM, RESET, find_theme, load_themes, serialize_theme_for_web


def build_bootstrap_payload(config_dir: Path | None = None) -> dict[str, object]:
    """Assemble full initial JSON state for the Web Studio frontend."""
    base = config_dir if config_dir is not None else get_config_dir()
    themes = load_themes()
    serialized_themes = [serialize_theme_for_web(t, idx) for idx, t in enumerate(themes, 1)]
    return {
        "version": __version__,
        "themes": serialized_themes,
        "separators": serialize_separators_for_web(),
        "valid_segments": list(VALID_FORMAT_TOKENS),
        "state": read_current_state(themes, base),
        "backups": list_backups(base),
    }


def handle_apply_payload(
    payload: dict[str, object],
    config_dir: Path | None = None,
) -> dict[str, object]:
    """Apply theme, dual separators, and/or layout options atomically from a JSON payload."""
    base = config_dir if config_dir is not None else get_config_dir()
    themes = load_themes()
    bak = backup_config(base)
    applied: list[str] = []

    if "theme" in payload and payload["theme"] not in (None, ""):
        query = payload["theme"]
        theme, _ = find_theme(query, themes)  # type: ignore[arg-type]
        if not theme:
            raise ValueError(f"Theme not found: {query}")
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

    has_layout = any(
        k in payload
        for k in ("format", "enable_command_on_new_line", "enable_vertical_padding", "max_pwd_char")
    )
    if has_layout:
        fmt_raw = payload.get("format")
        if isinstance(fmt_raw, list):
            fmt_str: str | None = " ".join(str(x) for x in fmt_raw)
        elif isinstance(fmt_raw, str):
            fmt_str = fmt_raw
        else:
            fmt_str = None

        new_line = (
            bool(payload["enable_command_on_new_line"])
            if "enable_command_on_new_line" in payload
            else None
        )
        v_pad = (
            bool(payload["enable_vertical_padding"])
            if "enable_vertical_padding" in payload
            else None
        )
        max_pwd = int(payload["max_pwd_char"]) if "max_pwd_char" in payload else None  # type: ignore[arg-type]

        apply_layout_options(
            format_str=fmt_str,
            new_line=new_line,
            vertical_padding=v_pad,
            max_pwd_char=max_pwd,
            create_backup=False,
            config_dir=base,
        )
        applied.append("Layout options updated")

    return {
        "ok": True,
        "applied": applied,
        "backup": str(bak) if bak else None,
        "state": read_current_state(themes, base),
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
            return  # Keep terminal quiet while browsing

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
                            "backups": list_backups(config_dir),
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
