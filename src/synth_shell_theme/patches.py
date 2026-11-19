"""Idempotent runtime patches and optional installer for upstream synth-shell scripts."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from synth_shell_theme.paths import (
    get_backup_dir,
    get_config_dir,
    get_config_path,
    get_prompt_script_path,
)

FAST_GET_KUBE = """getKube()
{
\t# synth-shell-theme: kube_fast (zero-subshell kubeconfig reader)
\tlocal cfg="${KUBECONFIG%%:*}"
\tcfg="${cfg:-$HOME/.kube/config}"
\t[[ -r "$cfg" ]] || return
\tlocal line ctx=""
\twhile IFS= read -r line; do
\t\tif [[ "$line" =~ ^current-context:[[:space:]]*(.*)$ ]]; then
\t\t\tctx="${BASH_REMATCH[1]}"
\t\t\tctx="${ctx%"${ctx##*[![:space:]]}"}"
\t\t\tctx="${ctx%\\"}" ; ctx="${ctx#\\"}"
\t\t\tctx="${ctx%\\'}" ; ctx="${ctx#\\'}"
\t\t\tbreak
\t\tfi
\tdone < "$cfg"
\t[[ -z "$ctx" ]] && return
\tif [[ "$ctx" =~ ^gke_[^_]+_[^_]+_(.+)$ ]]; then
\t\tctx="${BASH_REMATCH[1]#gke-}"
\tfi
\t(( ${#ctx} > 28 )) && ctx="${ctx:0:25}…"
\tprintf '☸ %s' "$ctx"
}"""

SINGLE_PASS_GIT = """    # synth-shell-theme: git_single_pass
    local status_out="$(git status --porcelain -b 2>/dev/null)"
    local is_dirty=false
    [[ "$status_out" =~ $'\\n' ]] && is_dirty=true
    local branch_line="${status_out%%$'\\n'*}"
    local is_ahead=false && [[ "$branch_line" == *"ahead"* ]] && is_ahead=true
    local is_behind=false && [[ "$branch_line" == *"behind"* ]] && is_behind=true"""

PATCHED_COLOR_CODES = """getColorCode()
{
\t# synth-shell-theme: color_256_parity
\tlocal COLOR=$1
\tif [ -z "$COLOR" ]; then
\t\techo 39
\t\treturn
\tfi
\tif [ "$COLOR" -eq "$COLOR" ] 2> /dev/null; then
\t\tif [ "$COLOR" -ge 0 -a "$COLOR" -lt 256 ]; then
\t\t\techo "38;5;$COLOR"
\t\telse
\t\t\techo 39
\t\tfi
\telse
\t\tcase $COLOR in
\t\t\tblack)        echo "38;5;0" ;;
\t\t\tred)          echo "38;5;1" ;;
\t\t\tgreen)        echo "38;5;2" ;;
\t\t\tyellow)       echo "38;5;3" ;;
\t\t\tblue)         echo "38;5;4" ;;
\t\t\tpurple|magenta|pink) echo "38;5;5" ;;
\t\t\tcyan)         echo "38;5;6" ;;
\t\t\tlight-gray)   echo "38;5;7" ;;
\t\t\tdark-gray)    echo "38;5;8" ;;
\t\t\tlight-red)    echo "38;5;9" ;;
\t\t\tlight-green)  echo "38;5;10" ;;
\t\t\tlight-yellow) echo "38;5;11" ;;
\t\t\tlight-blue)   echo "38;5;12" ;;
\t\t\tlight-purple|light-magenta) echo "38;5;13" ;;
\t\t\tlight-cyan)   echo "38;5;14" ;;
\t\t\twhite)        echo "38;5;15" ;;
\t\t\tnone|transparent|default) echo "39" ;;
\t\t\t*) echo "39" ;;
\t\tesac
\tfi
}
getBackgroundCode()
{
\tlocal COLOR=$1
\tif [ -z "$COLOR" ]; then
\t\techo 49
\t\treturn
\tfi
\tif [ "$COLOR" -eq "$COLOR" ] 2> /dev/null; then
\t\tif [ "$COLOR" -ge 0 -a "$COLOR" -lt 256 ]; then
\t\t\techo "48;5;$COLOR"
\t\telse
\t\t\techo 49
\t\tfi
\telse
\t\tcase $COLOR in
\t\t\tblack)        echo "48;5;0" ;;
\t\t\tred)          echo "48;5;1" ;;
\t\t\tgreen)        echo "48;5;2" ;;
\t\t\tyellow)       echo "48;5;3" ;;
\t\t\tblue)         echo "48;5;4" ;;
\t\t\tpurple|magenta|pink) echo "48;5;5" ;;
\t\t\tcyan)         echo "48;5;6" ;;
\t\t\tlight-gray)   echo "48;5;7" ;;
\t\t\tdark-gray)    echo "48;5;8" ;;
\t\t\tlight-red)    echo "48;5;9" ;;
\t\t\tlight-green)  echo "48;5;10" ;;
\t\t\tlight-yellow) echo "48;5;11" ;;
\t\t\tlight-blue)   echo "48;5;12" ;;
\t\t\tlight-purple|light-magenta) echo "48;5;13" ;;
\t\t\tlight-cyan)   echo "48;5;14" ;;
\t\t\twhite)        echo "48;5;15" ;;
\t\t\tnone|transparent|default) echo "49" ;;
\t\t\t*) echo "49" ;;
\t\tesac
\tfi
}"""

_GET_KUBE_RE = re.compile(
    r"^getKube\(\)\s*\{.*?\n\}",
    re.MULTILINE | re.DOTALL,
)

_OLD_GIT_RE = re.compile(
    r"^[ \t]*local is_dirty=false &&\\\n"
    r"[ \t]*\[\[ -n \"\$\(git status --porcelain\)\" \]\] &&\\\n"
    r"[ \t]*is_dirty=true\n"
    r"[ \t]*local is_ahead=false &&\\\n"
    r"[ \t]*\[\[ \"\$\(git status --porcelain -u no -b\)\" == \*\"ahead\"\* \]\] &&\\\n"
    r"[ \t]*is_ahead=true\n"
    r"[ \t]*local is_behind=false &&\\\n"
    r"[ \t]*\[\[ \"\$\(git status --porcelain -u no -b\)\" == \*\"behind\"\* \]\] &&\\\n"
    r"[ \t]*is_behind=true",
    re.MULTILINE,
)

_PRINT_SEG_HEAD_RE = re.compile(
    r"(printSegment\(\)\s*\{\s*(?:##[^\n]*\n\s*)*"
    r"local text=\$1\s+"
    r"local font_color=\$2\s+"
    r"local background_color=\$3\s+"
    r"local next_background_color=\$4[^\n]*\n"
    r"\tlocal font_effect=\$5)(?!\s+local sep_char=)",
    re.MULTILINE,
)

_COMBINE_TAIL_RE = re.compile(
    r"(\tlocal text_effect=\$\{colors_first\[2\]\}\n)"
    r"\tprintSegment \"\$text\" \"\$text_color\" \"\$bg_color\" \"\$next_bg_color\" \"\$text_effect\"(\s*\n\})",
    re.MULTILINE,
)

_COLOR_BLOCK_RE = re.compile(
    r"^getColorCode\(\)\s*\{.*?^\}\s*(?:##[^\n]*\n\s*)*^getBackgroundCode\(\)\s*\{.*?^\}",
    re.MULTILINE | re.DOTALL,
)


def _backup_script_once(script_path: Path, backup_dir: Path) -> None:
    """Create an initial `.orig.bak` backup of a shell script before first patching."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    orig_bak = backup_dir / f"{script_path.name}.orig.bak"
    if not orig_bak.exists():
        shutil.copy2(script_path, orig_bak)


def inspect_patches(config_dir: Path | None = None) -> dict[str, bool]:
    """Check which of the 4 runtime enhancements are active in `synth-shell`."""
    base = config_dir if config_dir is not None else get_config_dir()
    prompt_sh = get_prompt_script_path(base)
    if not prompt_sh.is_file():
        return {
            "prompt_script_found": False,
            "kube_fast": False,
            "git_single_pass": False,
            "dual_separator": False,
            "color_256_parity": False,
            "all_applied": False,
        }

    content = prompt_sh.read_text(encoding="utf-8", errors="replace")
    m_kube = _GET_KUBE_RE.search(content)
    kube_body = m_kube.group(0) if m_kube else ""
    kube_fast = bool(kube_body) and ("yq" not in kube_body) and (
        "current-context:" in kube_body or "kubectl config current-context" in kube_body
    )
    git_single_pass = (
        "git status --porcelain -b 2>/dev/null" in content
        or '[[ -n "$(git status --porcelain)" ]]' not in content
    )
    dual_separator = (
        'local sep_char="${6:-$separator_char}"' in content
        and "separator_char_end" in content
    )

    color_files = [
        base / name
        for name in ("synth-shell-prompt.sh", "alias.sh", "better-ls.sh", "better-history.sh")
        if (base / name).is_file()
    ]
    color_256_parity = bool(color_files) and all(
        "COLORCODE=$(($BITCODE + 30))" not in f.read_text(encoding="utf-8", errors="replace")
        for f in color_files
    )

    return {
        "prompt_script_found": True,
        "kube_fast": kube_fast,
        "git_single_pass": git_single_pass,
        "dual_separator": dual_separator,
        "color_256_parity": color_256_parity,
        "all_applied": kube_fast and git_single_pass and dual_separator and color_256_parity,
    }


def apply_runtime_patches(
    config_dir: Path | None = None,
    tune_defaults: bool = False,
) -> dict[str, object]:
    """Idempotently apply all 4 runtime & performance patches to `synth-shell` scripts."""
    base = config_dir if config_dir is not None else get_config_dir()
    prompt_sh = get_prompt_script_path(base)
    bdir = get_backup_dir(base)
    changes: list[str] = []

    if prompt_sh.is_file():
        original = prompt_sh.read_text(encoding="utf-8", errors="replace")
        updated = original

        # 1. Fast zero-subshell kube context reader (no yq dependency)
        m_kube = _GET_KUBE_RE.search(updated)
        if m_kube and ("yq" in m_kube.group(0) or "kubectl config view" in m_kube.group(0) or "kubectl config current-context" in m_kube.group(0)):
            updated = _GET_KUBE_RE.sub(lambda _: FAST_GET_KUBE, updated, count=1)
            changes.append("kube_fast")

        # 2. Single-pass git status optimization (4x faster prompt)
        if _OLD_GIT_RE.search(updated):
            updated = _OLD_GIT_RE.sub(lambda _: SINGLE_PASS_GIT, updated, count=1)
            changes.append("git_single_pass")

        # 3. Dual separator support (`separator_char_end` before INPUT)
        if 'local sep_char="${6:-$separator_char}"' not in updated or "separator_char_end" not in updated:
            step1 = _PRINT_SEG_HEAD_RE.sub(
                r'\1\n\tlocal sep_char="${6:-$separator_char}"',
                updated,
                count=1,
            )
            step2 = step1.replace(
                "${separator_format}${separator_char}${separator_padding_right}",
                "${separator_format}${sep_char}${separator_padding_right}",
            )
            step3 = _COMBINE_TAIL_RE.sub(
                (
                    r"\1"
                    '\tlocal sep_char="$separator_char"\n'
                    '\tif [ "$second" = "INPUT" ] && [ -n "${separator_char_end:-}" ]; then\n'
                    '\t\tsep_char="$separator_char_end"\n'
                    "\tfi\n"
                    '\tprintSegment "$text" "$text_color" "$bg_color" "$next_bg_color" "$text_effect" "$sep_char"'
                    r"\2"
                ),
                step2,
                count=1,
            )
            if step3 != updated:
                updated = step3
                changes.append("dual_separator")

        if updated != original:
            _backup_script_once(prompt_sh, bdir)
            prompt_sh.write_text(updated, encoding="utf-8", newline="\n")

    # 4. 256-color & named-color parity across all synth-shell scripts
    for script_name in ("synth-shell-prompt.sh", "alias.sh", "better-ls.sh", "better-history.sh"):
        script_file = base / script_name
        if not script_file.is_file():
            continue
        txt = script_file.read_text(encoding="utf-8", errors="replace")
        if "COLORCODE=$(($BITCODE + 30))" in txt and _COLOR_BLOCK_RE.search(txt):
            new_txt = _COLOR_BLOCK_RE.sub(lambda _: PATCHED_COLOR_CODES, txt, count=1)
            if new_txt != txt:
                _backup_script_once(script_file, bdir)
                script_file.write_text(new_txt, encoding="utf-8", newline="\n")
                changes.append(f"color_256_parity:{script_name}")

    # Optional sensible prompt config defaults (`init --tune-defaults`)
    cfg_path = get_config_path(base)
    if tune_defaults and cfg_path.is_file():
        cfg_lines = cfg_path.read_text(encoding="utf-8", errors="replace").splitlines()
        out_lines: list[str] = []
        has_end_sep = False
        cfg_changed = False
        for line in cfg_lines:
            if line.startswith("max_pwd_char="):
                if line != 'max_pwd_char="35"':
                    cfg_changed = True
                out_lines.append('max_pwd_char="35"')
            elif line.startswith("enable_command_on_new_line="):
                if line != 'enable_command_on_new_line="true"':
                    cfg_changed = True
                out_lines.append('enable_command_on_new_line="true"')
            elif line.startswith("separator_char="):
                out_lines.append('separator_char="\\uE0B4"')
            elif line.startswith("separator_char_end="):
                has_end_sep = True
                out_lines.append(line)
            else:
                out_lines.append(line)
        if not has_end_sep:
            out_lines.append('separator_char_end="\\uE0B0"')
            cfg_changed = True
        if cfg_changed:
            stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            bdir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(cfg_path, bdir / f"synth-shell-prompt.config.{stamp}.bak")
            cfg_path.write_text("\n".join(out_lines) + "\n", encoding="utf-8", newline="\n")
            changes.append("tune_defaults")

    status = inspect_patches(base)
    return {
        "changes": changes,
        "status": status,
    }


def ensure_dual_separator_support(config_dir: Path | None = None) -> bool:
    """Ensure `synth-shell-prompt.sh` supports `separator_char_end` before writing dual separators."""
    status = inspect_patches(config_dir)
    if not status["prompt_script_found"]:
        return False
    if status["dual_separator"]:
        return True
    res = apply_runtime_patches(config_dir=config_dir, tune_defaults=False)
    new_status = res["status"]
    return bool(isinstance(new_status, dict) and new_status.get("dual_separator"))


def install_upstream_synth_shell() -> bool:
    """Clone and run upstream `andresgongora/synth-shell` user installer non-interactively."""
    if shutil.which("git") is None or shutil.which("bash") is None:
        return False
    with tempfile.TemporaryDirectory(prefix="synth-shell-install-") as tmp:
        clone_cmd = [
            "git",
            "clone",
            "--recursive",
            "--depth=1",
            "https://github.com/andresgongora/synth-shell.git",
            tmp,
        ]
        res_clone = subprocess.run(clone_cmd, capture_output=True, text=True, check=False)
        if res_clone.returncode != 0:
            return False
        setup_sh = Path(tmp) / "setup.sh"
        if not setup_sh.is_file():
            return False
        setup_sh.chmod(0o755)
        # Answers: i=install, u=user, n=skip greeter, y=prompt, y=better-ls, y=alias, y=better-history
        res_setup = subprocess.run(
            ["bash", str(setup_sh)],
            input="iunyyyy",
            capture_output=True,
            text=True,
            check=False,
        )
        return res_setup.returncode == 0
