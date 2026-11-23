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

from synth_shell_theme import cli, core, patches, paths, separators, server, themes  # noqa: E402

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
        full_prompt = MOCK_UPSTREAM_PROMPT_SH + """
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
                    '_SSP_CMD_START_MS=$(( ${EPOCHREALTIME/./} / 1000 - 4250 )); SSP_MIN_DURATION_MS=2000; '
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
                self.assertEqual(len(boot["valid_segments"]), 20)
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
        full_prompt = MOCK_UPSTREAM_PROMPT_SH + """
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
shortenPath() { echo "$1"; }
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


if __name__ == "__main__":
    unittest.main()
