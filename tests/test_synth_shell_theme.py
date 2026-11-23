"""Comprehensive unit and integration tests for synth-shell-theme (isolated via temp dirs)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.request
from pathlib import Path
from unittest import mock

# Ensure `src/` is importable before editable install
SRC_DIR = Path(__file__).resolve().parents[1] / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from synth_shell_theme import cli, core, ecosystem, patches, paths, separators, server, themes  # noqa: E402

MOCK_UPSTREAM_PROMPT_SH = """#!/usr/bin/env bash
getColorCode()
{
\tCOLOR=$1
\t## Check if color is a 256-color code
\tif [ $COLOR -eq $COLOR ] 2> /dev/null; then
\t\tif [ $COLOR -gt 0 -a $COLOR -lt 256 ]; then
\t\t\techo "38;5;$COLOR"
\t\telse
\t\t\techo 0
\t\tfi
\t## Or if color key-workd
\telse
\t\tBITCODE=$(get8bitCode $COLOR)
\t\tCOLORCODE=$(($BITCODE + 30))
\t\techo $COLORCODE
\tfi
}
##------------------------------------------------------------------------------
##
getBackgroundCode()
{
\tCOLOR=$1
\t## Check if color is a 256-color code
\tif [ $COLOR -eq $COLOR ] 2> /dev/null; then
\t\tif [ $COLOR -gt 0 -a $COLOR -lt 256 ]; then
\t\t\techo "48;5;$COLOR"
\t\telse
\t\t\techo 0
\t\tfi
\t## Or if color key-workd
\telse
\t\tBITCODE=$(get8bitCode $COLOR)
\t\tCOLORCODE=$(($BITCODE + 40))
\t\techo $COLORCODE
\tfi
}
getGitBranch()
{
    local is_dirty=false &&\\
                [[ -n "$(git status --porcelain)" ]] &&\\
                is_dirty=true
    local is_ahead=false &&\\
                [[ "$(git status --porcelain -u no -b)" == *"ahead"* ]] &&\\
                is_ahead=true
    local is_behind=false &&\\
                [[ "$(git status --porcelain -u no -b)" == *"behind"* ]] &&\\
                is_behind=true
    echo "$is_dirty"
}
getKube()
{
\ttype kubectl &>/dev/null && \\
\ttype yq &>/dev/null && \\
\techo -n "$(kubectl config view | yq '.contexts[].context.cluster |select(.contexts[].name == .current-context)' | head -n 1)"
}
printSegment()
{
\t## GET PARAMETERS
\tlocal text=$1
\tlocal font_color=$2
\tlocal background_color=$3
\tlocal next_background_color=$4 # needed for the separator, it participates in this and the next text segment
\tlocal font_effect=$5
\tlocal no_color="\\[$(getFormatCode -e reset)\\]"
\tlocal text_format="\\[$(getFormatCode -c $font_color -b $background_color -e $font_effect)\\]"
\tlocal separator_format="\\[$(getFormatCode -c $background_color -b $next_background_color)\\]"
\tprintf "${text_format}${segment_padding}${text}${segment_padding}${separator_padding_left}${separator_format}${separator_char}${separator_padding_right}${no_color}"
}
combine_elements()
{
\tlocal first=$1
\tlocal second=$2
\tlocal colors_first=($(get_colors_for_element $first))
\tlocal colors_second=($(get_colors_for_element $second))
\tlocal text="$first"
\tlocal text_color=${colors_first[0]}
\tlocal bg_color=${colors_first[1]}
\tlocal next_bg_color=${colors_second[1]}
\tlocal text_effect=${colors_first[2]}
\tprintSegment "$text" "$text_color" "$bg_color" "$next_bg_color" "$text_effect"
}
"""


class SynthShellThemeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="synth-shell-theme-test-")
        self.cfg_dir = Path(self._tmp.name)
        self._env_patch = mock.patch.dict(
            os.environ,
            {"SYNTH_SHELL_CONFIG_DIR": str(self.cfg_dir)},
            clear=False,
        )
        self._env_patch.start()

    def tearDown(self) -> None:
        self._env_patch.stop()
        self._tmp.cleanup()

    def test_paths_and_os_detection(self) -> None:
        with mock.patch.object(sys, "platform", "linux"):
            self.assertEqual(paths.detect_os(), "linux")
        with mock.patch.object(sys, "platform", "darwin"):
            self.assertEqual(paths.detect_os(), "macos")
        with mock.patch.object(sys, "platform", "win32"):
            self.assertEqual(paths.detect_os(), "windows")

        self.assertEqual(paths.get_config_dir(), self.cfg_dir)
        summary = paths.system_summary()
        self.assertEqual(summary["bundled_themes"], 64)
        self.assertFalse(summary["config_exists"])

    def test_load_all_64_themes_and_color_math(self) -> None:
        catalog = themes.load_themes()
        self.assertEqual(len(catalog), 64)
        for idx, t in enumerate(catalog, 1):
            self.assertEqual(t["id"], idx)
            self.assertTrue(str(t["name"]))
            self.assertTrue(str(t["slug"]))
            self.assertTrue(str(t["badge"]))
            self.assertTrue(str(t["description"]))
            web_obj = themes.serialize_theme_for_web(t, idx)
            self.assertEqual(len(web_obj["swatch"]), 3)
            self.assertTrue(str(web_obj["segments"]["host"]["bg"]).startswith("#"))

        self.assertEqual(themes.color_index("black"), 0)
        self.assertEqual(themes.color_index("white"), 15)
        self.assertEqual(themes.color_index("214"), 214)
        self.assertIsNone(themes.color_index("none"))
        self.assertEqual(themes.index_to_hex(0), "#000000")
        self.assertEqual(themes.index_to_hex(15), "#ffffff")
        self.assertEqual(themes.index_to_hex(232), "#080808")

        found, idx = themes.find_theme("tokyo-night", catalog)
        self.assertIsNotNone(found)
        self.assertEqual(idx, 12)
        self.assertEqual(found["name"], "Tokyo Night")

    def test_separators_parsing_and_presets(self) -> None:
        self.assertEqual(len(separators.ALL_PRESETS), 48)
        g1, c1 = separators.parse_separator_value('"\\uE0B4"')
        self.assertEqual((g1, c1), ("\ue0b4", "\\uE0B4"))
        g2, c2 = separators.parse_separator_value("$'\\uE0B0'")
        self.assertEqual((g2, c2), ("\ue0b0", "\\uE0B0"))

        rg, rc, rlabel = separators.resolve_separator_input("zap")
        self.assertEqual(rg, "\u26a1")
        self.assertEqual(rc, "\\u26A1")
        self.assertIn("zap", rlabel.lower())

        pg, pc, _ = separators.resolve_separator_input("F140B")
        self.assertEqual(pg, "\U000f140b")
        self.assertEqual(pc, "\\U000F140B")

    def test_runtime_patches_idempotent_and_valid_bash(self) -> None:
        prompt_sh = self.cfg_dir / "synth-shell-prompt.sh"
        alias_sh = self.cfg_dir / "alias.sh"
        prompt_sh.write_text(MOCK_UPSTREAM_PROMPT_SH, encoding="utf-8", newline="\n")
        alias_sh.write_text(MOCK_UPSTREAM_PROMPT_SH.split("getGitBranch()")[0], encoding="utf-8", newline="\n")

        before = patches.inspect_patches(self.cfg_dir)
        self.assertTrue(before["prompt_script_found"])
        self.assertFalse(before["all_applied"])

        res1 = patches.apply_runtime_patches(self.cfg_dir)
        self.assertTrue(res1["status"]["all_applied"])
        self.assertIn("kube_fast", res1["changes"])
        self.assertIn("git_single_pass", res1["changes"])
        self.assertIn("dual_separator", res1["changes"])
        self.assertIn("color_256_parity:synth-shell-prompt.sh", res1["changes"])
        self.assertIn("color_256_parity:alias.sh", res1["changes"])
        self.assertTrue((self.cfg_dir / "backups" / "synth-shell-prompt.sh.orig.bak").is_file())

        # Second invocation must be 100% idempotent
        res2 = patches.apply_runtime_patches(self.cfg_dir)
        self.assertEqual(res2["changes"], [])
        self.assertTrue(res2["status"]["all_applied"])

        self.assertNotIn("\r\n", prompt_sh.read_bytes().decode("utf-8"))
        if shutil.which("bash"):
            probe = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, check=False)
            if probe.returncode == 0:
                chk = subprocess.run(
                    ["bash", "-n"],
                    input=prompt_sh.read_text(encoding="utf-8"),
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(chk.returncode, 0, msg=chk.stderr)

    def test_apply_theme_separators_layout_backups_and_presets(self) -> None:
        catalog = themes.load_themes()
        cfg_path = self.cfg_dir / "synth-shell-prompt.config"
        cfg_path.write_text(
            'format="HOST PWD GIT"\n'
            'separator_char="\\uE0B4"\n'
            'max_pwd_char="42"\n'
            'font_color_host="white"\n'
            'background_host="1"\n'
            'font_color_input="199"\n'
            'background_input="none"\n',
            encoding="utf-8",
        )

        dracula, _ = themes.find_theme("dracula-punch", catalog)
        assert dracula is not None
        core.apply_theme(dracula, force_white=True, keep_input=True, config_dir=self.cfg_dir)

        state = core.read_current_state(catalog, self.cfg_dir)
        self.assertEqual(state["active_theme"], "Dracula Punch")
        self.assertEqual(state["format"], "HOST PWD GIT")
        self.assertEqual(state["max_pwd_char"], 42)
        self.assertEqual(state["colors"]["font_color_host"], "white")
        self.assertEqual(state["colors"]["font_color_input"], "199")

        # Apply dual separators
        core.apply_separators(internal=("\ue0bc", "\\uE0BC"), end=("\u26a1", "\\u26A1"), config_dir=self.cfg_dir)
        (int_g, _), end_t = core.detect_current_separators(self.cfg_dir)
        self.assertEqual(int_g, "\ue0bc")
        self.assertEqual(end_t, ("\u26a1", "\\u26A1"))

        # Export preset -> apply another theme -> import preset back
        preset_file = self.cfg_dir / "saved-preset.json"
        core.export_preset(preset_file, config_dir=self.cfg_dir)
        nord, _ = themes.find_theme("nord-ice", catalog)
        assert nord is not None
        core.apply_theme(nord, config_dir=self.cfg_dir)
        self.assertEqual(core.read_current_state(catalog, self.cfg_dir)["active_theme"], "Nord Ice")

        core.import_preset(preset_file, config_dir=self.cfg_dir)
        restored_state = core.read_current_state(catalog, self.cfg_dir)
        self.assertEqual(restored_state["active_theme"], "Dracula Punch")
        self.assertEqual(restored_state["end_separator"]["glyph"], "\u26a1")

        # Backups exist and restore works
        baks = core.list_backups(self.cfg_dir)
        self.assertGreaterEqual(len(baks), 2)
        self.assertIsNotNone(core.restore_backup(1, self.cfg_dir))

    def test_web_studio_http_endpoints(self) -> None:
        httpd = server.create_studio_server("127.0.0.1", 0, config_dir=self.cfg_dir)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/") as r_html:
                html_text = r_html.read().decode("utf-8")
                self.assertIn("Synth-Shell Theme Studio", html_text)

            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/bootstrap") as r_boot:
                boot = json.loads(r_boot.read().decode("utf-8"))
                self.assertEqual(len(boot["themes"]), 64)
                self.assertEqual(boot["separators"]["total_presets"], 48)

            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/apply",
                data=json.dumps(
                    {
                        "theme": "catppuccin-mocha",
                        "internal_separator": "round",
                        "end_separator": "rocket",
                        "format": ["HOST", "PWD", "GIT", "KUBE"],
                        "enable_command_on_new_line": False,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req) as r_apply:
                resp = json.loads(r_apply.read().decode("utf-8"))
                self.assertTrue(resp["ok"])
                self.assertEqual(resp["state"]["active_theme"], "Catppuccin Mocha")
                self.assertEqual(resp["state"]["end_separator"]["glyph"], "\uf135")
                self.assertFalse(resp["state"]["enable_command_on_new_line"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_cli_commands_and_separator_entrypoint(self) -> None:
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main(["--apply", "12", "--dual", "round", "arrow"])
        self.assertEqual(rc, 0)
        self.assertIn("Tokyo Night", buf.getvalue())

        buf_doc = io.StringIO()
        with contextlib.redirect_stdout(buf_doc):
            rc_doc = cli.main(["doctor", "--json"])
        self.assertEqual(rc_doc, 0)
        doc_json = json.loads(buf_doc.getvalue())
        self.assertEqual(doc_json["active_theme"], "Tokyo Night")
        self.assertEqual(doc_json["internal_separator"]["glyph"], "\ue0b4")
        self.assertEqual(doc_json["end_separator"]["glyph"], "\ue0b0")

        buf_sep = io.StringIO()
        with contextlib.redirect_stdout(buf_sep):
            rc_sep = cli.main_separator(["--palette"])
        self.assertEqual(rc_sep, 0)
        self.assertIn("Character Palette", buf_sep.getvalue())

    def test_v11_full_patches_and_bash_runtime_behavior(self) -> None:
        full_prompt = MOCK_UPSTREAM_PROMPT_SH.replace(
            '    echo "$is_dirty"',
            '    echo "${branch:-main}"',
        ) + """
getEffectCode()
{
\tcase $1 in
\tdim)
\t\techo 2
\t\t;;
\t*)
\t\techo 0
\t\t;;
\tesac
}
getPyenv()
{
\techo "${VIRTUAL_ENV:-}"
}
get_colors_for_element()
{
\tcase $1 in
\t\t"USER") echo "${SSP_COLORS_USER[@]}" ;;
\t\t"INPUT") echo "${SSP_COLORS_INPUT[@]}" ;;
\tesac
}
prompt_command_hook()
{
\tPS1="$USER"
}
synth_shell_prompt()
{
\tSSP_ELEMENTS=($format "INPUT")
\tSSP_COLORS_USER=(white blue bold)
\tSSP_COLORS_HOST=(white 237 bold)
\tSSP_COLORS_PWD=(black 255 bold)
\tSSP_COLORS_GIT=(black 71 bold)
\tSSP_COLORS_PYENV=(white 63 bold)
\tSSP_COLORS_KUBE=(black 135 bold)
\tSSP_COLORS_TF=(black 228 bold)
\tSSP_COLORS_CLOCK=(white 240 bold)
\tSSP_COLORS_INPUT=(white none bold)
\tSSP_VERTICAL_PADDING=""
\tSSP_NEW_LINE_LINK_TOP=""
\tSSP_NEW_LINE_LINK_BOTTOM=""
\tSSP_PROMPT_COMM_SEP=""
\tSSP_BASH_SYMBOL=""
\tSSP_MAX_PWD_CHAR=35
\tSSP_PWD_TRUNC_SYMBOL="…"
\tSSP_CLOCK_FORMAT="%H:%M"
\tPROMPT_COMMAND=prompt_command_hook
}
"""
        mock_greeter = """#!/usr/bin/env bash
printInfoCPUTemp()
{
\techo "old temp"
}
printMonitorRAM()
{
\techo "old ram"
}
"""
        prompt_sh = self.cfg_dir / "synth-shell-prompt.sh"
        greeter_sh = self.cfg_dir / "synth-shell-greeter.sh"
        prompt_sh.write_text(full_prompt, encoding="utf-8", newline="\n")
        greeter_sh.write_text(mock_greeter, encoding="utf-8", newline="\n")

        res1 = patches.apply_runtime_patches(self.cfg_dir)
        st1 = res1["status"]
        self.assertTrue(st1["all_applied"], msg=f"Status: {st1}")
        for key in (
            "kube_fast",
            "git_single_pass",
            "git_wsl_fast",
            "zero_fork_render",
            "v11_segments",
            "pyenv_enhanced",
            "utf8_ps1_guard",
            "interactive_guard",
            "greeter_amd_temp",
            "greeter_zfs_arc",
        ):
            self.assertTrue(st1[key], msg=f"Expected {key} to be True")

        # Strict idempotency check
        res2 = patches.apply_runtime_patches(self.cfg_dir)
        self.assertEqual(res2["changes"], [])
        self.assertTrue(res2["status"]["all_applied"])

        if shutil.which("bash"):
            probe = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, check=False)
            if probe.returncode == 0:
                for pfile in (prompt_sh, greeter_sh):
                    chk = subprocess.run(
                        ["bash", "-n"],
                        input=pfile.read_text(encoding="utf-8"),
                        capture_output=True,
                        text=True,
                        check=False,
                    )
                    self.assertEqual(chk.returncode, 0, msg=f"{pfile.name}: {chk.stderr}")

                # Non-interactive source must exit cleanly with zero stdout (`scp`/`sftp` safety)
                ni = subprocess.run(
                    ["bash", "-c", f'source "{prompt_sh}"'],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(ni.returncode, 0)
                self.assertEqual(ni.stdout, "")

                # Test UTF-8 PS1 escape guard under LC_ALL=C vs UTF-8, getPyenv, and v1.1 segments
                stripped = "\n".join(
                    ln for ln in prompt_sh.read_text(encoding="utf-8").splitlines()
                    if "interactive_guard" not in ln
                )
                runner = self.cfg_dir / "test_helpers.sh"
                runner.write_text(stripped + "\n", encoding="utf-8", newline="\n")

                # 1. Under LC_ALL=C, \uE0B0 must degrade cleanly to '>' (never literal \uE0B0)
                c_env = dict(os.environ)
                c_env["LC_ALL"] = "C"
                c_env["LANG"] = "C"
                c_res = subprocess.run(
                    ["bash", "-c", f'source "{runner}"; _ssp_resolve_sep "\\uE0B0"; printf "%s" "$_SSP_SEP"'],
                    env=c_env,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(c_res.stdout, ">")

                # 2. Pure-Bash getPyenv (`VIRTUAL_ENV_PROMPT`, `pyvenv.cfg`, truncation) + AWS/DOCKER/SSH/DURATION
                ve_dir = self.cfg_dir / "my-proj" / ".venv"
                ve_dir.mkdir(parents=True, exist_ok=True)
                (ve_dir / "pyvenv.cfg").write_text("prompt = custom-venv-superlong\n", encoding="utf-8", newline="\n")
                seg_cmd = (
                    f'source "{runner}"; '
                    f'VIRTUAL_ENV="{ve_dir}" SSP_MAX_PYENV_CHAR=10 getPyenv; echo ""; '
                    'VIRTUAL_ENV_PROMPT="(api-prod)" getPyenv; echo ""; '
                    'AWS_PROFILE=prod-admin getAws; echo ""; '
                    'DOCKER_CONTEXT=remote-gpu getDocker; echo ""; '
                    'SSH_CONNECTION="1 2 3 4" getSsh; echo ""; '
                    'if [[ -n "${EPOCHREALTIME:-}" ]]; then _SSP_CMD_START_MS=$(( ${EPOCHREALTIME/./} / 1000 - 4250 )); else SECONDS=10; _SSP_CMD_START_MS=5750; fi; '
                    'SSP_MIN_DURATION_MS=2000; '
                    '_ssp_format_duration_var; echo "$_SSP_DUR"'
                )
                seg_res = subprocess.run(["bash", "-c", seg_cmd], capture_output=True, text=True, check=False)
                out_lines = seg_res.stdout.splitlines()
                self.assertEqual(out_lines[0], "custom-ve…")
                self.assertEqual(out_lines[1], "api-prod")
                self.assertEqual(out_lines[2], "☁ prod-admin")
                self.assertEqual(out_lines[3], "🐳 remote-gpu")
                self.assertEqual(out_lines[4], "⇄ ssh")
                self.assertRegex(out_lines[5], r"^⏱ 4\.[23]s$")

    def test_v11_layout_ascii_safe_root_greeter_and_web_endpoints(self) -> None:
        # Apply Tokyo Night + v1.1 CLI options (truncation, prefix, effect, WSL fast-git, root & greeter sync)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = cli.main([
                "--apply", "tokyo-night",
                "--format", "HOST PWD GIT PYENV KUBE STATUS DURATION AWS",
                "--max-git", "22",
                "--max-pyenv", "16",
                "--max-kube", "20",
                "--prefix", "auto",
                "--text-effect", "italic",
                "--no-terminal-title",
                "--git-timeout", "400",
                "--async-git",
                "--min-duration", "1500",
                "--sync-root",
                "--sync-greeter",
                "--greeter-monitors", "OS KERNEL CPU MEMORY_MON HDDROOT_MON",
            ])
        self.assertEqual(rc, 0)

        state = core.read_current_state(config_dir=self.cfg_dir)
        self.assertEqual(state["active_theme"], "Tokyo Night")
        self.assertEqual(state["max_git_char"], 22)
        self.assertEqual(state["max_pyenv_char"], 16)
        self.assertEqual(state["max_kube_char"], 20)
        self.assertEqual(state["prompt_prefix"], "auto")
        self.assertEqual(state["font_effect"], "italic")
        self.assertFalse(state["enable_terminal_title"])
        self.assertEqual(state["git_timeout_ms"], 400)
        self.assertTrue(state["git_async_cache"])
        self.assertEqual(state["min_duration_ms"], 1500)
        self.assertIn("STATUS", state["format_segments"])
        self.assertIn("DURATION", state["format_segments"])
        self.assertIn("AWS", state["format_segments"])

        root_cfg = self.cfg_dir / "synth-shell-prompt.root.config"
        greeter_cfg = self.cfg_dir / "synth-shell-greeter.config"
        self.assertTrue(root_cfg.is_file())
        self.assertTrue(greeter_cfg.is_file())
        self.assertIn('background_user="196"', root_cfg.read_text(encoding="utf-8"))
        g_state = core.read_greeter_state(self.cfg_dir)
        self.assertEqual(g_state["monitors"], ["OS", "KERNEL", "CPU", "MEMORY_MON", "HDDROOT_MON"])

        # Export v2 preset and re-import after switching to ASCII-safe mode
        preset_v2 = self.cfg_dir / "v2-preset.json"
        core.export_preset(preset_v2, self.cfg_dir)
        core.apply_ascii_safe_mode(config_dir=self.cfg_dir)
        ascii_state = core.read_current_state(config_dir=self.cfg_dir)
        self.assertEqual(ascii_state["internal_separator"]["glyph"], ">")
        self.assertIn('git_symbol_dirty=" *"', (self.cfg_dir / "synth-shell-prompt.config").read_text(encoding="utf-8"))

        core.import_preset(preset_v2, self.cfg_dir)
        reimported = core.read_current_state(config_dir=self.cfg_dir)
        self.assertEqual(reimported["max_git_char"], 22)
        self.assertEqual(reimported["prompt_prefix"], "auto")
        self.assertTrue(reimported["git_async_cache"])

        # Doctor JSON includes locale, nerd_fonts, and greeter diagnostics
        buf_doc = io.StringIO()
        with contextlib.redirect_stdout(buf_doc):
            rc_doc = cli.main(["doctor", "--json"])
        self.assertEqual(rc_doc, 0)
        doc = json.loads(buf_doc.getvalue())
        self.assertIn("locale", doc["system"])
        self.assertIn("nerd_fonts", doc["system"])
        self.assertIn("greeter", doc)

        # Web Studio v1.1 HTTP endpoints
        httpd = server.create_studio_server("127.0.0.1", 0, config_dir=self.cfg_dir)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/bootstrap") as r_b:
                boot = json.loads(r_b.read().decode("utf-8"))
                self.assertEqual(len(boot["valid_segments"]), 24)
                self.assertIn("diagnostics", boot)
                self.assertIn("greeter", boot)

            for ep, payload in (
                ("/api/ascii-safe", {"separator": ">"}),
                ("/api/sync-root", {"root_accent": "196"}),
                ("/api/greeter", {"monitors": ["OS", "CPU", "MEMORY_MON"], "hide_swap_if_unavailable": True}),
            ):
                req = urllib.request.Request(
                    f"http://127.0.0.1:{port}{ep}",
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(req) as resp:
                    body = json.loads(resp.read().decode("utf-8"))
                    self.assertTrue(body["ok"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_v12_truecolor_hooks_segments_custom_themes_bench_and_completion(self) -> None:
        # 1. TrueColor #RRGGBB parsing & nearest-256 fallback math
        self.assertEqual(themes.normalize_hex_color("#7AA2F7"), "#7aa2f7")
        self.assertEqual(themes.normalize_hex_color("#0f8"), "#00ff88")
        self.assertEqual(themes.token_to_hex("#7aa2f7"), "#7aa2f7")
        self.assertIsInstance(themes.color_index("#7aa2f7"), int)

        # 2. Save custom TrueColor theme & verify load_themes discovers it
        saved = themes.save_custom_theme(
            name="Midnight Hex Test",
            colors={
                "font_color_host": "#ffffff",
                "background_host": "#1a1b26",
                "font_color_pwd": "#000000",
                "background_pwd": "#7aa2f7",
                "font_color_git": "#000000",
                "background_git": "#9ece6a",
                "font_color_input": "#bb9af7",
                "background_input": "none",
            },
            config_dir=self.cfg_dir,
        )
        self.assertTrue(saved["custom"])
        all_themes = themes.load_themes(config_dir=self.cfg_dir)
        self.assertEqual(len(all_themes), 65)
        found_custom, _ = themes.find_theme("midnight-hex-test", all_themes)
        self.assertIsNotNone(found_custom)

        # 3. Light/Dark toggle CLI & state persistence
        core.apply_theme(themes.find_theme("tokyo-night", all_themes)[0], config_dir=self.cfg_dir)  # type: ignore[arg-type]
        tog1 = core.toggle_light_dark_theme(config_dir=self.cfg_dir)
        self.assertEqual(tog1["mode"], "light")
        self.assertEqual(tog1["theme"], "Catppuccin Latte")
        tog2 = core.toggle_light_dark_theme(config_dir=self.cfg_dir)
        self.assertEqual(tog2["mode"], "dark")
        self.assertEqual(tog2["theme"], "Tokyo Night")

        # 4. Bash completion script syntax & contents
        comp_buf = io.StringIO()
        with contextlib.redirect_stdout(comp_buf):
            rc_comp = cli.main(["completion", "bash"])
        self.assertEqual(rc_comp, 0)
        comp_script = comp_buf.getvalue()
        self.assertIn("complete -F _synth_shell_theme_complete", comp_script)
        self.assertIn("tokyo-night", comp_script)

        # 5. Full v1.2 runtime patches: TrueColor, hook_chaining (no DEBUG trap), v12 segments, nounset, bench
        full_prompt = MOCK_UPSTREAM_PROMPT_SH.replace(
            '    echo "$is_dirty"',
            '    echo "${branch:-main}"',
        ) + """
getEffectCode()
{
\tcase $1 in
\tdim)
\t\techo 2
\t\t;;
\t*)
\t\techo 0
\t\t;;
\tesac
}
getPyenv() { echo ""; }
getTerraform() { echo ""; }
shortenPath() { echo "~/repo"; }
get_colors_for_element() { echo "white blue bold"; }
prompt_command_hook() { PS1="$USER"; }
synth_shell_prompt()
{
\tformat="HOST PWD GIT KUBE AWS JOBS DIRENV SHLVL RUST GO"
\tSSP_ELEMENTS=($format "INPUT")
\tSSP_COLORS_USER=(white blue bold)
\tSSP_COLORS_HOST=(white 237 bold)
\tSSP_COLORS_PWD=(black 255 bold)
\tSSP_COLORS_GIT=(black 71 bold)
\tSSP_COLORS_PYENV=(white 63 bold)
\tSSP_COLORS_KUBE=(black 135 bold)
\tSSP_COLORS_TF=(black 228 bold)
\tSSP_COLORS_CLOCK=(white 240 bold)
\tSSP_COLORS_INPUT=(white none bold)
\tSSP_VERTICAL_PADDING=""
\tSSP_NEW_LINE_LINK_TOP=""
\tSSP_NEW_LINE_LINK_BOTTOM=""
\tSSP_PROMPT_COMM_SEP=""
\tSSP_BASH_SYMBOL=""
\tSSP_MAX_PWD_CHAR=35
\tSSP_PWD_TRUNC_SYMBOL="…"
\tSSP_CLOCK_FORMAT="%H:%M"
\tnone="$(tput sgr0)"
\ttrap 'echo -ne "${none}"' DEBUG
\tPROMPT_COMMAND=prompt_command_hook
}
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
\texit
elif [ -n "$( echo $- | grep i )" ]; then
\tsynth_shell_prompt
fi
"""
        prompt_sh = self.cfg_dir / "synth-shell-prompt.sh"
        prompt_sh.write_text(full_prompt, encoding="utf-8", newline="\n")
        res_p = patches.apply_runtime_patches(self.cfg_dir)
        st = res_p["status"]
        for k in ("truecolor_24bit", "git_ahead_behind_counts", "v12_segments", "responsive_width", "hook_chaining", "all_applied"):
            self.assertTrue(st[k], msg=f"Expected {k}=True, got {st}")
        self.assertEqual(patches.apply_runtime_patches(self.cfg_dir)["changes"], [])

        if shutil.which("bash"):
            probe = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, check=False)
            if probe.returncode == 0:
                chk_comp = subprocess.run(["bash", "-n"], input=comp_script, capture_output=True, text=True, check=False)
                self.assertEqual(chk_comp.returncode, 0, msg=chk_comp.stderr)

                stripped = "\n".join(
                    ln for ln in prompt_sh.read_text(encoding="utf-8").splitlines()
                    if "interactive_guard" not in ln
                ).replace('elif [ -n "$( echo $- | grep i )" ]; then', "elif true; then")
                runner = self.cfg_dir / "v12_runner.sh"
                runner.write_text(stripped + "\n", encoding="utf-8", newline="\n")

                # Verify TrueColor 24-bit vs 256 fallback, PROMPT_COMMAND chaining, v12 segments & set -u safety
                proj = self.cfg_dir / "rustgo"
                proj.mkdir(exist_ok=True)
                (proj / "Cargo.toml").write_text('rust-version = "1.82"\n', encoding="utf-8", newline="\n")
                (proj / "go.mod").write_text("module example\n\ngo 1.23.1\n", encoding="utf-8", newline="\n")

                cmd = (
                    f'PROMPT_COMMAND="existing_hook"; source "{runner}"; '
                    'echo "PC=$PROMPT_COMMAND"; '
                    'COLORTERM=truecolor _ssp_color_var "#7aa2f7"; echo "TC=$_SSP_C"; '
                    'COLORTERM="" _ssp_color_var "#7aa2f7"; echo "FB=$_SSP_C"; '
                    f'cd "{proj}"; '
                    'DIRENV_DIR="-/tmp/myapp" getDirenv; echo ""; '
                    'IN_NIX_SHELL=pure getShlvl; echo ""; '
                    'getRust; echo ""; '
                    'getGo; echo ""; '
                    'set -u; COLUMNS=70 prompt_command_hook; echo "NOUNSET_OK"'
                )
                r_bash = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=False)
                self.assertEqual(r_bash.returncode, 0, msg=r_bash.stderr)
                lines = r_bash.stdout.splitlines()
                self.assertEqual(lines[0], "PC=prompt_command_hook;existing_hook")
                self.assertEqual(lines[1], "TC=38;2;122;162;247")
                self.assertEqual(lines[2], "FB=38;5;110")
                self.assertEqual(lines[3], "⚡ myapp")
                self.assertEqual(lines[4], "❄ nix")
                self.assertEqual(lines[5], "🦀 1.82")
                self.assertEqual(lines[6], "🐹 1.23.1")
                self.assertEqual(lines[7], "NOUNSET_OK")

                # Live prompt benchmark via CLI & API
                bres = core.benchmark_prompt(iterations=5, config_dir=self.cfg_dir)
                self.assertTrue(bres["ok"], msg=str(bres))
                self.assertEqual(bres["iterations"], 5)

        # 6. Web Studio v1.2 HTTP endpoints (`/api/custom-theme`, `/api/toggle-theme`, `/api/bench`)
        httpd = server.create_studio_server("127.0.0.1", 0, config_dir=self.cfg_dir)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            req_ct = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/custom-theme",
                data=json.dumps({
                    "name": "Studio Neon Hex",
                    "colors": {"background_host": "#282a36", "background_pwd": "#bd93f9", "background_git": "#50fa7b"},
                    "apply": True,
                }).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_ct) as r_ct:
                body_ct = json.loads(r_ct.read().decode("utf-8"))
                self.assertTrue(body_ct["ok"])
                self.assertEqual(body_ct["saved_theme"], "Studio Neon Hex")

            req_tog = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/toggle-theme",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_tog) as r_tog:
                self.assertTrue(json.loads(r_tog.read().decode("utf-8"))["ok"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_v13_rprompt_osc133_git_state_ecosystem_import_doctor_fix_and_static_demo(self) -> None:
        # 1. Ecosystem sync (fzf + LS_COLORS + tmux)
        catalog = themes.load_themes(config_dir=self.cfg_dir)
        tokyo, _ = themes.find_theme("tokyo-night", catalog)
        assert tokyo is not None
        core.apply_theme(tokyo, config_dir=self.cfg_dir)
        eco_res = ecosystem.sync_ecosystem(config_dir=self.cfg_dir)
        self.assertEqual(eco_res["theme"], "Tokyo Night")
        env_sh = Path(eco_res["env_script"]).read_text(encoding="utf-8")
        tmux_conf = Path(eco_res["tmux_conf"]).read_text(encoding="utf-8")
        self.assertIn("FZF_DEFAULT_OPTS", env_sh)
        self.assertIn("LS_COLORS", env_sh)
        self.assertIn("status-style", tmux_conf)

        # 2. Import external themes (Pywal, Base16 YAML, Ghostty, Kitty, Alacritty, Windows Terminal JSON)
        imp_dir = self.cfg_dir / "external_palettes"
        imp_dir.mkdir(exist_ok=True)

        pywal_file = imp_dir / "colors.json"
        pywal_file.write_text(
            json.dumps({
                "special": {"background": "#10121a", "foreground": "#d8dee9"},
                "colors": {
                    "color0": "#1b1e2b", "color1": "#f07178", "color2": "#c3e88d",
                    "color3": "#ffcb6b", "color4": "#82aaff", "color5": "#c792ea",
                    "color6": "#89ddff", "color7": "#d8dee9", "color8": "#676e95",
                },
            }),
            encoding="utf-8",
            newline="\n",
        )
        r_pywal = ecosystem.import_external_theme(pywal_file, custom_name="Pywal Test", config_dir=self.cfg_dir, apply_now=False)
        self.assertEqual(r_pywal["format"], "pywal")
        self.assertEqual(r_pywal["slug"], "pywal-test")

        b16_file = imp_dir / "nord.yaml"
        b16_file.write_text(
            'scheme: "Base16 Nord"\nbase00: "2E3440"\nbase01: "3B4252"\nbase02: "434C5E"\n'
            'base03: "4C566A"\nbase05: "E5E9F0"\nbase08: "BF616A"\nbase0A: "EBCB8B"\n'
            'base0B: "A3BE8C"\nbase0C: "88C0D0"\nbase0D: "81A1C1"\nbase0E: "B48EAD"\n',
            encoding="utf-8",
            newline="\n",
        )
        r_b16 = ecosystem.import_external_theme(b16_file, config_dir=self.cfg_dir, apply_now=False)
        self.assertEqual(r_b16["format"], "base16")

        ghostty_file = imp_dir / "ghostty.conf"
        ghostty_file.write_text(
            "background = #1e1e2e\nforeground = #cdd6f4\n"
            "palette = 0=#45475a\npalette = 1=#f38ba8\npalette = 2=#a6e3a1\n"
            "palette = 3=#f9e2af\npalette = 4=#89b4fa\npalette = 5=#cba6f7\npalette = 6=#94e2d5\n",
            encoding="utf-8",
            newline="\n",
        )
        r_gh = ecosystem.import_external_theme(ghostty_file, custom_name="Ghostty Mocha", config_dir=self.cfg_dir, apply_now=False)
        self.assertEqual(r_gh["format"], "terminal-conf")

        kitty_file = imp_dir / "kitty.conf"
        kitty_file.write_text(
            "background #282a36\nforeground #f8f8f2\n"
            "color0 #21222c\ncolor1 #ff5555\ncolor2 #50fa7b\ncolor3 #f1fa8c\n"
            "color4 #bd93f9\ncolor5 #ff79c6\ncolor6 #8be9fd\n",
            encoding="utf-8",
            newline="\n",
        )
        r_ki = ecosystem.import_external_theme(kitty_file, custom_name="Kitty Drac", config_dir=self.cfg_dir, apply_now=False)
        self.assertEqual(r_ki["format"], "terminal-conf")

        alac_file = imp_dir / "alacritty.toml"
        alac_file.write_text(
            '[colors.primary]\nbackground = "#1a1b26"\nforeground = "#c0caf5"\n'
            '[colors.normal]\nblack = "#15161e"\nred = "#f7768e"\ngreen = "#9ece6a"\n'
            'yellow = "#e0af68"\nblue = "#7aa2f7"\nmagenta = "#bb9af7"\ncyan = "#7dcfff"\n',
            encoding="utf-8",
            newline="\n",
        )
        r_al = ecosystem.import_external_theme(alac_file, custom_name="Alacritty TN", config_dir=self.cfg_dir, apply_now=False)
        self.assertEqual(r_al["format"], "terminal-conf")

        wt_file = imp_dir / "wt.json"
        wt_file.write_text(
            json.dumps({
                "name": "WT OneHalf",
                "background": "#282c34", "foreground": "#dcdfe4",
                "black": "#282c34", "red": "#e06c75", "green": "#98c379",
                "yellow": "#e5c07b", "blue": "#61afef", "purple": "#c678dd", "cyan": "#56b6c2",
            }),
            encoding="utf-8",
            newline="\n",
        )
        r_wt = ecosystem.import_external_theme(wt_file, config_dir=self.cfg_dir, apply_now=True)
        self.assertEqual(r_wt["format"], "windows-terminal")
        self.assertEqual(core.read_current_state(config_dir=self.cfg_dir)["active_theme"], "WT OneHalf")

        # 3. Layout v1.3 options (RPROMPT, OSC 133, Git state, Battery)
        core.apply_layout_options(
            format_str="HOST PWD GIT",
            right_format_str="CLOCK BATTERY DURATION",
            right_fill_char="─",
            enable_osc133=True,
            git_show_state=True,
            battery_threshold=90,
            new_line=True,
            config_dir=self.cfg_dir,
        )
        st_cfg = core.read_current_state(config_dir=self.cfg_dir)
        self.assertEqual(st_cfg["right_format"], "CLOCK BATTERY DURATION")
        self.assertEqual(st_cfg["right_fill_char"], "─")
        self.assertTrue(st_cfg["enable_osc133"])
        self.assertTrue(st_cfg["git_show_state"])
        self.assertEqual(st_cfg["battery_threshold"], 90)

        # 4. Runtime patches v1.3 + real Bash verification (OSC 133, RPROMPT, Git rebase/worktree, doctor --fix CRLF)
        full_prompt = MOCK_UPSTREAM_PROMPT_SH.replace(
            '    echo "$is_dirty"',
            '    echo "${branch:-main}"',
        ) + """
getEffectCode() { echo 0; }
getPyenv() { echo ""; }
getTerraform() { echo ""; }
shortenPath() { echo "~/repo"; }
get_colors_for_element() { echo "white blue bold"; }
prompt_command_hook() { PS1="$USER"; }
synth_shell_prompt()
{
\tformat="HOST PWD GIT"
\tSSP_ELEMENTS=($format "INPUT")
\tSSP_COLORS_USER=(white blue bold)
\tSSP_COLORS_HOST=(white 237 bold)
\tSSP_COLORS_PWD=(black 255 bold)
\tSSP_COLORS_GIT=(black 71 bold)
\tSSP_COLORS_PYENV=(white 63 bold)
\tSSP_COLORS_KUBE=(black 135 bold)
\tSSP_COLORS_TF=(black 228 bold)
\tSSP_COLORS_CLOCK=(white 240 bold)
\tSSP_COLORS_INPUT=(white none bold)
\tSSP_VERTICAL_PADDING=""
\tSSP_NEW_LINE_LINK_TOP="┌"
\tSSP_NEW_LINE_LINK_BOTTOM="└"
\tSSP_PROMPT_COMM_SEP=""
\tSSP_BASH_SYMBOL=""
\tSSP_MAX_PWD_CHAR=35
\tSSP_PWD_TRUNC_SYMBOL="…"
\tSSP_CLOCK_FORMAT="%H:%M"
\tnone="$(tput sgr0)"
\ttrap 'echo -ne "${none}"' DEBUG
\tPROMPT_COMMAND=prompt_command_hook
}
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
\texit
elif [ -n "$( echo $- | grep i )" ]; then
\tsynth_shell_prompt
fi
"""
        prompt_sh = self.cfg_dir / "synth-shell-prompt.sh"
        # Inject CRLF intentionally to verify `doctor --fix` normalizes it and applies patches
        prompt_sh.write_bytes(full_prompt.replace("\n", "\r\n").encode("utf-8"))
        fix_res = core.doctor_fix(config_dir=self.cfg_dir)
        self.assertIn("normalized_lf:synth-shell-prompt.sh", fix_res["actions"])
        self.assertNotIn(b"\r\n", prompt_sh.read_bytes())
        for k in ("git_advanced_state", "v13_segments", "osc133_semantic", "terminal_sanitize", "right_prompt", "all_applied"):
            self.assertTrue(fix_res["patches"][k], msg=f"Expected {k}=True, got {fix_res['patches']}")
        self.assertEqual(patches.apply_runtime_patches(self.cfg_dir)["changes"], [])

        if shutil.which("bash"):
            probe = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, check=False)
            if probe.returncode == 0:
                chk_sh = subprocess.run(["bash", "-n", str(prompt_sh)], capture_output=True, text=True, check=False)
                self.assertEqual(chk_sh.returncode, 0, msg=chk_sh.stderr)
                chk_env = subprocess.run(["bash", "-n", eco_res["env_script"]], capture_output=True, text=True, check=False)
                self.assertEqual(chk_env.returncode, 0, msg=chk_env.stderr)

                stripped = "\n".join(
                    ln for ln in prompt_sh.read_text(encoding="utf-8").splitlines()
                    if "interactive_guard" not in ln
                ).replace('elif [ -n "$( echo $- | grep i )" ]; then', "elif true; then")
                runner = self.cfg_dir / "v13_runner.sh"
                runner.write_text(stripped + "\n", encoding="utf-8", newline="\n")

                # Mock git repo with rebase-merge to verify pure-Bash state detection
                repo = self.cfg_dir / "fake_git_repo"
                repo.mkdir(exist_ok=True)
                subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.email", "t@t.dev"], cwd=repo, check=True)
                subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
                (repo / "a.txt").write_text("hi\n", encoding="utf-8", newline="\n")
                subprocess.run(["git", "add", "a.txt"], cwd=repo, check=True)
                subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=repo, check=True)
                rebase_dir = repo / ".git" / "rebase-merge"
                rebase_dir.mkdir(exist_ok=True)
                (rebase_dir / "msgnum").write_text("2\n", encoding="utf-8", newline="\n")
                (rebase_dir / "end").write_text("5\n", encoding="utf-8", newline="\n")

                cmd = (
                    f'source "{runner}"; '
                    'SSP_ENABLE_OSC133="true"; SSP_RIGHT_ELEMENTS=(CLOCK); SSP_RIGHT_FILL_CHAR="─"; '
                    'SSP_PROMPT_COMM_SEP=$\'\\n\'; SSP_NEW_LINE_LINK_TOP="┌"; SSP_NEW_LINE_LINK_BOTTOM="└"; COLUMNS=200; '
                    f'cd "{repo}"; '
                    'GS="$(getGitBranch)"; echo "GIT=$GS"; '
                    'prompt_command_hook; prompt_command_hook; '
                    '[[ "$PS1" == *"133;A"* && "$PS1" == *"133;B"* && "$PS1" == *"133;D;"* ]] && echo "OSC133_OK"; '
                    r'''if (( BASH_VERSINFO[0] > 4 || (BASH_VERSINFO[0] == 4 && BASH_VERSINFO[1] >= 4) )); then eval 'exp="${PS1@P}"'; clean="${exp//$'\x1b]'/}"; [[ "$clean" != *']'* ]] && echo "NO_STRAY_BRACKET_OK"; else [[ "$PS1" != *'\e\\]'* ]] && echo "NO_STRAY_BRACKET_OK"; fi; '''
                    '[[ "$PS1" == *"───"* ]] && echo "RPROMPT_OK"; '
                    '[[ "$PS0" == *"133;C"* ]] && echo "PS0_C_OK"; '
                    'SAN_OUT="$(SSP_FORCE_SANITIZE=1 prompt_command_hook)"; '
                    '[[ "$SAN_OUT" == *"?1000l"* && "$SAN_OUT" == *"?1003l"* && "$SAN_OUT" == *"?1006l"* && "$SAN_OUT" == *"?1004l"* ]] && echo "SANITIZE_OK"; '
                    'SAN_OFF="$(SSP_FORCE_SANITIZE=1 SSP_TERMINAL_SANITIZE=false prompt_command_hook)"; '
                    '[[ -z "$SAN_OFF" ]] && echo "SANITIZE_OFF_OK"'
                )
                r_bash = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=False)
                self.assertEqual(r_bash.returncode, 0, msg=r_bash.stderr)
                out = r_bash.stdout
                self.assertIn("REBASE 2/5", out)
                self.assertIn("OSC133_OK", out)
                self.assertIn("NO_STRAY_BRACKET_OK", out)
                self.assertIn("RPROMPT_OK", out)
                self.assertIn("PS0_C_OK", out)
                self.assertIn("SANITIZE_OK", out)
                self.assertIn("SANITIZE_OFF_OK", out)

        # 5. Export static browser demo (GitHub Pages bundle)
        static_html = self.cfg_dir / "demo" / "index.html"
        exp_path = core.export_static_studio(static_html, config_dir=self.cfg_dir)
        self.assertEqual(exp_path, static_html)
        html_content = static_html.read_text(encoding="utf-8")
        self.assertIn("window.__SYNTH_STATIC_BOOTSTRAP__", html_content)
        self.assertIn("Tokyo Night", html_content)

        # 6. Web Studio HTTP `/api/sync-ecosystem` + 21 valid segments
        httpd = server.create_studio_server("127.0.0.1", 0, config_dir=self.cfg_dir)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/bootstrap") as r_boot:
                boot = json.loads(r_boot.read().decode("utf-8"))
                self.assertEqual(len(boot["valid_segments"]), 24)
                self.assertIn("BATTERY", boot["valid_segments"])

            req_eco = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/sync-ecosystem",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_eco) as r_eco:
                body_eco = json.loads(r_eco.read().decode("utf-8"))
                self.assertTrue(body_eco["ok"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_v139_smart_devops_osc7_notify_fish_jj_wezterm_starship_ssh_and_autotheme(self) -> None:
        # 1. Ecosystem sync includes wezterm-theme.lua + export-starship + ssh-install --dry-run
        catalog = themes.load_themes(config_dir=self.cfg_dir)
        tokyo, _ = themes.find_theme("tokyo-night", catalog)
        assert tokyo is not None
        core.apply_theme(tokyo, config_dir=self.cfg_dir)

        eco = ecosystem.sync_ecosystem(config_dir=self.cfg_dir)
        wez_lua = Path(eco["wezterm_lua"]).read_text(encoding="utf-8")
        self.assertIn("tab_bar", wez_lua)
        self.assertIn("active_tab", wez_lua)

        starship_out = self.cfg_dir / "starship.toml"
        res_st = ecosystem.export_starship_toml(starship_out, config_dir=self.cfg_dir)
        self.assertEqual(res_st["theme"], "Tokyo Night")
        st_toml = starship_out.read_text(encoding="utf-8")
        self.assertIn("starship.rs/config-schema.json", st_toml)
        self.assertIn("[kubernetes]", st_toml)

        # 2. OS Auto Light/Dark theme detection
        with mock.patch("synth_shell_theme.paths.detect_system_color_scheme", return_value="light"):
            r_light = core.apply_auto_system_theme(config_dir=self.cfg_dir)
            self.assertEqual(r_light["detected_scheme"], "light")
            self.assertEqual(r_light["theme"], "Catppuccin Latte")
        with mock.patch("synth_shell_theme.paths.detect_system_color_scheme", return_value="dark"):
            r_dark = core.apply_auto_system_theme(config_dir=self.cfg_dir)
            self.assertEqual(r_dark["detected_scheme"], "dark")
            self.assertEqual(r_dark["theme"], "Tokyo Night")

        # 3. Layout options & preset persistence for v1.3.9 fields
        core.apply_layout_options(
            enable_osc7=True,
            kube_show_namespace=True,
            kube_prod_warning=True,
            kube_prod_pattern="prod|live",
            git_dynamic_color=True,
            ssh_host_color=True,
            pwd_style="fish",
            notify_duration_sec=30,
            custom_segment_text="EU-WEST",
            config_dir=self.cfg_dir,
        )
        cur = core.read_current_state(config_dir=self.cfg_dir)
        self.assertTrue(cur["enable_osc7"])
        self.assertTrue(cur["kube_show_namespace"])
        self.assertTrue(cur["kube_prod_warning"])
        self.assertTrue(cur["git_dynamic_color"])
        self.assertTrue(cur["ssh_host_color"])
        self.assertEqual(cur["pwd_style"], "fish")
        self.assertEqual(cur["notify_duration_sec"], 30)
        self.assertEqual(cur["custom_segment_text"], "EU-WEST")

        # 4. Patch prompt script & test ssh-install --dry-run + real Bash runtime behavior
        full_prompt = MOCK_UPSTREAM_PROMPT_SH.replace(
            '    echo "$is_dirty"',
            '    echo "${branch:-main}"',
        ) + """
getEffectCode() { echo 0; }
getPyenv() { echo ""; }
getTerraform() { echo ""; }
shortenPath() { echo "~/repo"; }
get_colors_for_element() { echo "white blue bold"; }
prompt_command_hook() { PS1="$USER"; }
synth_shell_prompt()
{
\tformat="HOST PWD GIT KUBE JJ CUSTOM"
\tSSP_ELEMENTS=($format "INPUT")
\tSSP_COLORS_USER=(white blue bold)
\tSSP_COLORS_HOST=(white 237 bold)
\tSSP_COLORS_PWD=(black 255 bold)
\tSSP_COLORS_GIT=(black 71 bold)
\tSSP_COLORS_PYENV=(white 63 bold)
\tSSP_COLORS_KUBE=(black 135 bold)
\tSSP_COLORS_TF=(black 228 bold)
\tSSP_COLORS_CLOCK=(white 240 bold)
\tSSP_COLORS_INPUT=(white none bold)
\tSSP_VERTICAL_PADDING=""
\tSSP_NEW_LINE_LINK_TOP=""
\tSSP_NEW_LINE_LINK_BOTTOM=""
\tSSP_PROMPT_COMM_SEP=""
\tSSP_BASH_SYMBOL=""
\tSSP_MAX_PWD_CHAR=35
\tSSP_PWD_TRUNC_SYMBOL="…"
\tSSP_CLOCK_FORMAT="%H:%M"
\tnone="$(tput sgr0)"
\ttrap 'echo -ne "${none}"' DEBUG
\tPROMPT_COMMAND=prompt_command_hook
}
if [ "${BASH_SOURCE[0]}" == "${0}" ]; then
\texit
elif [ -n "$( echo $- | grep i )" ]; then
\tsynth_shell_prompt
fi
"""
        prompt_sh = self.cfg_dir / "synth-shell-prompt.sh"
        prompt_sh.write_text(full_prompt, encoding="utf-8", newline="\n")
        pr = patches.apply_runtime_patches(self.cfg_dir)
        for k in ("kube_namespace_prod", "osc7_cwd", "v139_smart_features", "all_applied"):
            self.assertTrue(pr["status"][k], msg=f"Expected {k}=True, got {pr['status']}")
        self.assertEqual(patches.apply_runtime_patches(self.cfg_dir)["changes"], [])

        ssh_dry = ecosystem.ssh_install_remote("dev@prod-01", ascii_safe=True, dry_run=True, config_dir=self.cfg_dir)
        self.assertTrue(ssh_dry["ok"])
        self.assertTrue(ssh_dry["dry_run"])
        self.assertGreater(int(ssh_dry["script_bytes"]), 1000)  # type: ignore[arg-type]

        if shutil.which("bash"):
            probe = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, check=False)
            if probe.returncode == 0:
                chk_sh = subprocess.run(["bash", "-n", str(prompt_sh)], capture_output=True, text=True, check=False)
                self.assertEqual(chk_sh.returncode, 0, msg=chk_sh.stderr)

                stripped = "\n".join(
                    ln for ln in prompt_sh.read_text(encoding="utf-8").splitlines()
                    if "interactive_guard" not in ln
                ).replace('elif [ -n "$( echo $- | grep i )" ]; then', "elif true; then")
                runner = self.cfg_dir / "v139_runner.sh"
                runner.write_text(stripped + "\n", encoding="utf-8", newline="\n")

                # Mock kubeconfig with prod context + custom namespace
                kcfg = self.cfg_dir / "kubeconfig"
                kcfg.write_text(
                    "apiVersion: v1\n"
                    "current-context: gke_myproj_us-east1_prod-cluster\n"
                    "contexts:\n"
                    "- name: dev-cluster\n"
                    "  context:\n"
                    "    namespace: dev\n"
                    "- name: gke_myproj_us-east1_prod-cluster\n"
                    "  context:\n"
                    "    namespace: payments\n",
                    encoding="utf-8",
                    newline="\n",
                )
                jj_dir = self.cfg_dir / "my folder" / "jjproj"
                (jj_dir / ".jj").mkdir(parents=True, exist_ok=True)

                cmd = (
                    f'source "{runner}"; '
                    f'KUBECONFIG="{kcfg}" getKube; echo ""; '
                    '_ssp_shorten_path_fish "/etc/systemd/system"; echo "FISH=$_SSP_FISH_PATH"; '
                    f'cd "{jj_dir}"; '
                    'OSC7_OUT="$(_ssp_osc7_emit)"; [[ "$OSC7_OUT" == *"]7;file://"* && "$OSC7_OUT" == *"my%20folder"* ]] && echo "OSC7_OK"; '
                    'SSP_SSH_HOST_COLOR=true SSP_FORCE_SSH_COLOR=1 HOSTNAME=api-prod-01 _ssp_host_color_var; echo "HOST_PROD=$_SSP_SSH_HOST_BG"; '
                    'SSP_SSH_HOST_COLOR=true SSP_FORCE_SSH_COLOR=1 HOSTNAME=api-staging-02 _ssp_host_color_var; echo "HOST_STG=$_SSP_SSH_HOST_BG"; '
                    'SSP_SSH_HOST_COLOR=true SSP_FORCE_SSH_COLOR=1 HOSTNAME=worker-42 _ssp_host_color_var; [[ -n "$_SSP_SSH_HOST_BG" ]] && echo "HOST_HASH_OK"; '
                    'SSP_GIT_DYNAMIC_COLOR=true git_branch="main ◔" _ssp_dyn_colors_var GIT; echo "GIT_DIRTY=${_SSP_EL_C[1]}"; '
                    'SSP_GIT_DYNAMIC_COLOR=true git_branch="main | REBASE 1/3" _ssp_dyn_colors_var GIT; echo "GIT_REBASE=${_SSP_EL_C[1]}"; '
                    'kube="🚨 ☸ prod-cluster (payments)" _ssp_dyn_colors_var KUBE; echo "KUBE_PROD_BG=${_SSP_EL_C[1]}"; '
                    'JJ_OUT="$(getJj)"; [[ "$JJ_OUT" == *"🥋"* ]] && echo "JJ_OK"; '
                    'SYNTH_CUSTOM_BADGE="VPN:BR" getCustom; echo ""; '
                    'SSP_NOTIFY_DURATION_SEC=5 SSP_FORCE_NOTIFY=1; '
                    'if [[ -n "${EPOCHREALTIME:-}" ]]; then _SSP_CMD_START_MS=$(( ${EPOCHREALTIME/[.,]/} / 1000 - 7500 )); else SECONDS=20; _SSP_CMD_START_MS=12500; fi; '
                    'NOTIF_OUT="$(prompt_command_hook)"; [[ "$NOTIF_OUT" == *"]9;synth-shell:"* || "$NOTIF_OUT" == *"]99;"* ]] && echo "NOTIFY_OK"'
                )
                r_bash = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, check=False)
                self.assertEqual(r_bash.returncode, 0, msg=r_bash.stderr)
                out = r_bash.stdout
                self.assertIn("🚨 ☸ prod-cluster (payments)", out)
                self.assertIn("FISH=/e/s/system", out)
                self.assertIn("OSC7_OK", out)
                self.assertIn("HOST_PROD=196", out)
                self.assertIn("HOST_STG=214", out)
                self.assertIn("HOST_HASH_OK", out)
                self.assertIn("GIT_DIRTY=214", out)
                self.assertIn("GIT_REBASE=196", out)
                self.assertIn("KUBE_PROD_BG=196", out)
                self.assertIn("JJ_OK", out)
                self.assertIn("VPN:BR", out)
                self.assertIn("NOTIFY_OK", out)

        # 5. Web Studio HTTP endpoints `/api/export-starship` & `/api/auto-theme`
        httpd = server.create_studio_server("127.0.0.1", 0, config_dir=self.cfg_dir)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            req_st = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/export-starship",
                data=json.dumps({"output": str(self.cfg_dir / "web-starship.toml")}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_st) as r_s:
                self.assertTrue(json.loads(r_s.read().decode("utf-8"))["ok"])

            req_at = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/auto-theme",
                data=b"{}",
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req_at) as r_a:
                self.assertTrue(json.loads(r_a.read().decode("utf-8"))["ok"])
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_v140_security_locale_custom_themes_and_fixes(self) -> None:
        import urllib.error

        # 1. Shell-injection escaping in _escape_bash_dq / _unquote & save_custom_theme
        core.apply_layout_options(
            prompt_prefix="$ $(touch /tmp/should-not-run) `id`\nnewline",
            custom_segment_text='100$ "quoted"',
            config_dir=self.cfg_dir,
        )
        cfg_txt = (self.cfg_dir / "synth-shell-prompt.config").read_text(encoding="utf-8")
        self.assertIn(r'prompt_prefix="\$ \$(touch /tmp/should-not-run) \`id\` newline"', cfg_txt)
        self.assertIn(r'custom_segment_text="100\$ \"quoted\""', cfg_txt)
        st_esc = core.read_current_state(config_dir=self.cfg_dir)
        self.assertEqual(st_esc["prompt_prefix"], "$ $(touch /tmp/should-not-run) `id` newline")
        self.assertEqual(st_esc["custom_segment_text"], '100$ "quoted"')

        # save_custom_theme rejects unsafe color tokens & strips newlines in headers
        saved_custom = themes.save_custom_theme(
            name="Safe Custom\nInjected",
            colors={
                "background_host": "#112233",
                "font_color_host": "$(whoami)",
                "background_pwd": "#eeeeee",
                "font_color_pwd": "black",
            },
            config_dir=self.cfg_dir,
        )
        custom_txt = Path(saved_custom["_path"]).read_text(encoding="utf-8")  # type: ignore[arg-type]
        self.assertNotIn("$(whoami)", custom_txt)
        self.assertIn("# Theme 0: Safe Custom Injected", custom_txt)

        # Custom theme applied via handle_apply_payload(config_dir=...) & detected by header
        res_apply = server.handle_apply_payload({"theme": "safe-custom-injected"}, config_dir=self.cfg_dir)
        self.assertTrue(res_apply["ok"])
        self.assertEqual(res_apply["state"]["active_theme"], "Safe Custom Injected")

        # 2. export_preset includes v1.2+ fields (compact_width, git_show_counts, transient_prompt, light/dark)
        core.apply_layout_options(
            compact_width=77,
            git_show_counts=False,
            transient_prompt=True,
            light_theme="catppuccin-latte",
            dark_theme="dracula-punch",
            config_dir=self.cfg_dir,
        )
        preset_p = self.cfg_dir / "v140-preset.json"
        core.export_preset(preset_p, config_dir=self.cfg_dir)
        exported = json.loads(preset_p.read_text(encoding="utf-8"))
        self.assertEqual(exported["compact_width"], 77)
        self.assertFalse(exported["git_show_counts"])
        self.assertTrue(exported["transient_prompt"])
        self.assertEqual(exported["dark_theme"], "dracula-punch")

        # 3. sync_root_config covers all 24 segments
        root_res = core.sync_root_config(config_dir=self.cfg_dir)
        root_txt = Path(root_res["root_config_path"]).read_text(encoding="utf-8")  # type: ignore[arg-type]
        for seg in ("jobs", "direnv", "shlvl", "rust", "go", "battery", "sudo", "jj", "custom"):
            self.assertIn(f"background_{seg}=", root_txt)

        # 4. export_starship_toml has no stray space before internal separator
        st_out = self.cfg_dir / "clean-starship.toml"
        ecosystem.export_starship_toml(st_out, config_dir=self.cfg_dir)
        st_txt = st_out.read_text(encoding="utf-8")
        self.assertNotIn("[ \ue0b4]", st_txt)
        self.assertIn("[\ue0b4](fg:", st_txt)

        # 5. ssh_install_remote --ascii-safe replaces all ASCII_SAFE_GIT_SYMBOLS & uses pure-Bash hook
        prompt_sh = self.cfg_dir / "synth-shell-prompt.sh"
        prompt_sh.write_text(MOCK_UPSTREAM_PROMPT_SH, encoding="utf-8", newline="\n")
        patches.apply_runtime_patches(self.cfg_dir)
        dry_ssh = ecosystem.ssh_install_remote("dev@example.com", ascii_safe=True, dry_run=True, config_dir=self.cfg_dir)
        self.assertTrue(dry_ssh["ok"])

        # 6. Web Studio CSRF / Origin / Content-Type / path-traversal guards
        httpd = server.create_studio_server("127.0.0.1", 0, config_dir=self.cfg_dir)
        port = httpd.server_address[1]
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            # Reject text/plain CSRF POST
            req_plain = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/apply",
                data=b'{"theme": 1}',
                headers={"Content-Type": "text/plain"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx_plain:
                urllib.request.urlopen(req_plain)
            self.assertEqual(ctx_plain.exception.code, 403)

            # Reject evil Origin header
            req_origin = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/apply",
                data=b'{"theme": 1}',
                headers={"Content-Type": "application/json", "Origin": "https://evil.example.com"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx_origin:
                urllib.request.urlopen(req_origin)
            self.assertEqual(ctx_origin.exception.code, 403)

            # Reject arbitrary file write outside config_dir in /api/export-starship
            req_trav = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/export-starship",
                data=json.dumps({"output": str(Path.home() / ".bashrc")}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with self.assertRaises(urllib.error.HTTPError) as ctx_trav:
                urllib.request.urlopen(req_trav)
            self.assertEqual(ctx_trav.exception.code, 400)
        finally:
            httpd.shutdown()
            httpd.server_close()

        # 7. Bash runtime verification: decimal-comma EPOCHREALTIME + emoji width helper
        if shutil.which("bash"):
            probe = subprocess.run(["bash", "-c", "true"], capture_output=True, text=True, check=False)
            if probe.returncode == 0:
                full_sh = self.cfg_dir / "full_v140.sh"
                full_sh.write_text(
                    MOCK_UPSTREAM_PROMPT_SH
                    + "\ngetPyenv()\n{\n\techo ''\n}\n"
                    + "get_colors_for_element()\n{\n\techo 'white blue bold'\n}\n"
                    + "prompt_command_hook()\n{\n\tPS1='x'\n}\n"
                    + "synth_shell_prompt()\n{\n\tPROMPT_COMMAND=prompt_command_hook\n}\n",
                    encoding="utf-8",
                    newline="\n",
                )
                # Copy into synth-shell-prompt.sh and patch
                prompt_sh.write_text(full_sh.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
                res_p = patches.apply_runtime_patches(self.cfg_dir)
                self.assertTrue(res_p["status"]["all_applied"])
                # Verify idempotency
                res_p2 = patches.apply_runtime_patches(self.cfg_dir)
                self.assertEqual(res_p2["changes"], [])

                runner_cmd = (
                    f'eval "$(sed \'/interactive_guard/d\' "{prompt_sh}")"; '
                    '_SSP_VIS_A=""; _ssp_vis_width_var "abc"; echo "VW_ASCII=$_SSP_VW"; '
                    '_ssp_vis_width_var "🚨 prod"; echo "VW_EMOJI=$_SSP_VW"; '
                    'EPOCHREALTIME="1795467919,500000" _SSP_CMD_START_MS=1795467915000 SSP_MIN_DURATION_MS=1000 _ssp_format_duration_var; '
                    'echo "DUR_COMMA=$_SSP_DUR"'
                )
                r_b = subprocess.run(["bash", "-c", runner_cmd], capture_output=True, text=True, check=False)
                self.assertEqual(r_b.returncode, 0, msg=r_b.stderr)
                self.assertIn("VW_ASCII=3", r_b.stdout)
                self.assertIn("VW_EMOJI=7", r_b.stdout)
                self.assertIn("DUR_COMMA=⏱ 4.5s", r_b.stdout)


if __name__ == "__main__":
    unittest.main()
