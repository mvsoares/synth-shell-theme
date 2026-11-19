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
        prompt_sh.write_text(MOCK_UPSTREAM_PROMPT_SH, encoding="utf-8")
        alias_sh.write_text(MOCK_UPSTREAM_PROMPT_SH.split("getGitBranch()")[0], encoding="utf-8")

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

        if shutil.which("bash"):
            chk = subprocess.run(["bash", "-n", str(prompt_sh)], capture_output=True, text=True, check=False)
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


if __name__ == "__main__":
    unittest.main()
