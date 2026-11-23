"""Idempotent runtime patches and optional installer for upstream synth-shell scripts (v1.2.0)."""

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
    get_greeter_script_path,
    get_prompt_script_path,
)

INTERACTIVE_GUARD_LINE = (
    '[[ "${BASH_SOURCE[0]}" != "${0}" && $- != *i* ]] && return  # synth-shell-theme: interactive_guard'
)

FAST_GET_KUBE = """getKube()
{
\t# synth-shell-theme: kube_fast v139 (zero-subshell kubeconfig context + namespace + prod warning + max_kube_char)
\tlocal cfg="${KUBECONFIG:-}"
\tcfg="${cfg%%:*}"
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
\tlocal ns=""
\tif [[ "${SSP_KUBE_SHOW_NAMESPACE:-true}" == "true" ]]; then
\t\tlocal _in_ctxs=0 _cur_name="" _cur_ns=""
\t\twhile IFS= read -r line; do
\t\t\tif [[ "$line" =~ ^contexts: ]]; then
\t\t\t\t_in_ctxs=1; continue
\t\t\telif (( _in_ctxs == 1 )) && [[ "$line" =~ ^[a-zA-Z0-9_-]+: ]]; then
\t\t\t\t[[ "$_cur_name" == "$ctx" && -n "$_cur_ns" ]] && ns="$_cur_ns"
\t\t\t\tbreak
\t\t\tfi
\t\t\t(( _in_ctxs == 0 )) && continue
\t\t\tif [[ "$line" =~ ^[[:space:]]*-[[:space:]]+ ]]; then
\t\t\t\tif [[ "$_cur_name" == "$ctx" && -n "$_cur_ns" ]]; then
\t\t\t\t\tns="$_cur_ns"; break
\t\t\t\tfi
\t\t\t\t_cur_name=""; _cur_ns=""
\t\t\tfi
\t\t\tif [[ "$line" =~ ^[[:space:]]*-?[[:space:]]*name:[[:space:]]*(.*)$ ]]; then
\t\t\t\t_cur_name="${BASH_REMATCH[1]}"
\t\t\t\t_cur_name="${_cur_name%"${_cur_name##*[![:space:]]}"}"
\t\t\t\t_cur_name="${_cur_name%\\"}" ; _cur_name="${_cur_name#\\"}"
\t\t\t\t_cur_name="${_cur_name%\\'}" ; _cur_name="${_cur_name#\\'}"
\t\t\telif [[ "$line" =~ ^[[:space:]]*namespace:[[:space:]]*(.*)$ ]]; then
\t\t\t\t_cur_ns="${BASH_REMATCH[1]}"
\t\t\t\t_cur_ns="${_cur_ns%"${_cur_ns##*[![:space:]]}"}"
\t\t\t\t_cur_ns="${_cur_ns%\\"}" ; _cur_ns="${_cur_ns#\\"}"
\t\t\t\t_cur_ns="${_cur_ns%\\'}" ; _cur_ns="${_cur_ns#\\'}"
\t\t\tfi
\t\tdone < "$cfg"
\t\t[[ -z "$ns" && "$_cur_name" == "$ctx" && -n "$_cur_ns" ]] && ns="$_cur_ns"
\tfi
\tlocal disp="$ctx"
\tif [[ "$disp" =~ ^gke_[^_]+_[^_]+_(.+)$ ]]; then
\t\tdisp="${BASH_REMATCH[1]#gke-}"
\tfi
\tif [[ -n "$ns" && "$ns" != "default" ]]; then
\t\tdisp="${disp} (${ns})"
\tfi
\tlocal max_k="${SSP_MAX_KUBE_CHAR:-28}"
\tif (( max_k > 3 && ${#disp} > max_k )); then
\t\tdisp="${disp:0:$((max_k - 1))}…"
\tfi
\tlocal _is_prod=0
\tif [[ "${SSP_KUBE_PROD_WARNING:-true}" == "true" ]]; then
\t\tlocal _pat="${SSP_KUBE_PROD_PATTERN:-prod|production|prd|live}"
\t\tlocal _had_nocase=0
\t\tshopt -q nocasematch && _had_nocase=1
\t\tshopt -s nocasematch
\t\t[[ "${ctx} ${ns}" =~ ($_pat) ]] && _is_prod=1
\t\t(( _had_nocase == 0 )) && shopt -u nocasematch
\tfi
\tif (( _is_prod == 1 )); then
\t\tprintf '🚨 ☸ %s' "$disp"
\telse
\t\tprintf '☸ %s' "$disp"
\tfi
}"""

SINGLE_PASS_GIT_V13 = """    # synth-shell-theme: git_single_pass v13 (WSL fast + timeout + async + counts + rebase/merge/worktree + max_git_char)
    local _git_flags="--porcelain -b"
    if [[ "${SSP_GIT_SKIP_UNTRACKED_ON_SLOW_FS:-true}" == "true" ]]; then
        if [[ "$PWD" == /mnt/[a-z]/* || "$PWD" == /mnt/[a-z] ]]; then
            _git_flags="--porcelain -b -u no"
        elif [[ "$(git config --bool bash.showUntrackedFiles 2>/dev/null)" == "false" ]]; then
            _git_flags="--porcelain -b -u no"
        fi
    fi
    local status_out=""
    local _git_timeout_ms="${SSP_GIT_TIMEOUT_MS:-0}"
    if [[ "${SSP_GIT_ASYNC_CACHE:-false}" == "true" ]]; then
        local _cache_dir="${XDG_RUNTIME_DIR:-/dev/shm}/synth-shell-git-cache"
        [[ -d "${XDG_RUNTIME_DIR:-/dev/shm}" && -w "${XDG_RUNTIME_DIR:-/dev/shm}" ]] || _cache_dir="/tmp/synth-shell-git-cache-${UID:-0}"
        mkdir -p "$_cache_dir" 2>/dev/null
        local _cache_key="${PWD//\\//_}"
        local _cache_file="${_cache_dir}/${_cache_key}.cache"
        if [[ -r "$_cache_file" ]]; then
            status_out="$(< "$_cache_file")"
            (
                local _fresh
                _fresh="$(git status $_git_flags 2>/dev/null)"
                printf '%s' "$_fresh" > "${_cache_file}.tmp.$$" && mv -f "${_cache_file}.tmp.$$" "$_cache_file"
            ) >/dev/null 2>&1 &
            disown 2>/dev/null || true
        else
            status_out="$(git status $_git_flags 2>/dev/null)"
            printf '%s' "$status_out" > "$_cache_file" 2>/dev/null
        fi
    elif (( _git_timeout_ms > 0 )) && command -v timeout >/dev/null 2>&1; then
        local _t_sec
        printf -v _t_sec '%d.%03d' $(( _git_timeout_ms / 1000 )) $(( _git_timeout_ms % 1000 ))
        status_out="$(timeout "${_t_sec}s" git status $_git_flags 2>/dev/null)"
    else
        status_out="$(git status $_git_flags 2>/dev/null)"
    fi
    local is_dirty=false
    [[ "$status_out" =~ $'\\n' ]] && is_dirty=true
    local branch_line="${status_out%%$'\\n'*}"
    local is_ahead=false is_behind=false _ahead_n="" _behind_n=""
    if [[ "$branch_line" =~ ahead[[:space:]]+([0-9]+) ]]; then
        is_ahead=true
        _ahead_n="${BASH_REMATCH[1]}"
    elif [[ "$branch_line" == *"ahead"* ]]; then
        is_ahead=true
    fi
    if [[ "$branch_line" =~ behind[[:space:]]+([0-9]+) ]]; then
        is_behind=true
        _behind_n="${BASH_REMATCH[1]}"
    elif [[ "$branch_line" == *"behind"* ]]; then
        is_behind=true
    fi
    local _max_g="${SSP_MAX_GIT_CHAR:-0}"
    if (( _max_g > 3 )) && [[ -n "${branch:-}" ]] && (( ${#branch} > _max_g )); then
        branch="${branch:0:$((_max_g - 1))}…"
    fi
    if [[ "${SSP_GIT_SHOW_COUNTS:-true}" == "true" ]]; then
        local _ab_counts=""
        [[ -n "$_ahead_n" ]] && _ab_counts+=" ↑${_ahead_n}"
        [[ -n "$_behind_n" ]] && _ab_counts+=" ↓${_behind_n}"
        [[ -n "$_ab_counts" ]] && branch="${branch}${_ab_counts}"
    fi
    if [[ "${SSP_GIT_SHOW_STATE:-true}" == "true" ]]; then
        local _gwalk="$PWD" _gdir="" _wt_name="" _gstep=0
        while [[ -n "$_gwalk" && $_gstep -lt 15 ]]; do
            if [[ -d "${_gwalk}/.git" ]]; then
                _gdir="${_gwalk}/.git"
                break
            elif [[ -f "${_gwalk}/.git" ]]; then
                local _gline=""
                IFS= read -r _gline < "${_gwalk}/.git"
                if [[ "$_gline" == gitdir:* ]]; then
                    _gdir="${_gline#gitdir:}"
                    _gdir="${_gdir#"${_gdir%%[![:space:]]*}"}"
                    [[ "$_gdir" != /* ]] && _gdir="${_gwalk}/${_gdir}"
                    if [[ "$_gdir" == */worktrees/* ]]; then
                        _wt_name="${_gdir##*/worktrees/}"
                        _wt_name="${_wt_name%%/*}"
                    fi
                fi
                break
            fi
            [[ "$_gwalk" == "/" ]] && break
            _gwalk="${_gwalk%/*}"
            [[ -z "$_gwalk" ]] && _gwalk="/"
            _gstep=$((_gstep + 1))
        done
        if [[ -n "$_gdir" ]]; then
            local _gstate=""
            if [[ -d "${_gdir}/rebase-merge" ]]; then
                local _rn="" _re=""
                [[ -r "${_gdir}/rebase-merge/msgnum" ]] && IFS= read -r _rn < "${_gdir}/rebase-merge/msgnum"
                [[ -r "${_gdir}/rebase-merge/end" ]] && IFS= read -r _re < "${_gdir}/rebase-merge/end"
                _gstate="REBASE${_rn:+ ${_rn}/${_re}}"
            elif [[ -d "${_gdir}/rebase-apply" ]]; then
                _gstate="REBASE"
            elif [[ -f "${_gdir}/MERGE_HEAD" ]]; then
                _gstate="MERGE"
            elif [[ -f "${_gdir}/CHERRY_PICK_HEAD" ]]; then
                _gstate="CHERRY"
            elif [[ -f "${_gdir}/BISECT_LOG" ]]; then
                _gstate="BISECT"
            fi
            [[ -n "$_wt_name" ]] && branch="${branch} ⎇${_wt_name}"
            [[ -n "$_gstate" ]] && branch="${branch} | ${_gstate}"
        fi
    fi"""

PATCHED_COLOR_CODES = """getColorCode()
{
\t# synth-shell-theme: color_256_parity truecolor_24bit
\tlocal COLOR="${1:-}"
\tif [ -z "$COLOR" ]; then
\t\techo 39
\t\treturn
\tfi
\tif [[ "$COLOR" =~ ^#([0-9a-fA-F]{6})$ ]]; then
\t\tlocal h="${BASH_REMATCH[1]}"
\t\tlocal r=$((16#${h:0:2})) g=$((16#${h:2:2})) b=$((16#${h:4:2}))
\t\tif [[ "${COLORTERM:-}" == "truecolor" || "${COLORTERM:-}" == "24bit" ]]; then
\t\t\techo "38;2;${r};${g};${b}"
\t\telse
\t\t\techo "38;5;$(( 16 + 36*(r*5/255) + 6*(g*5/255) + (b*5/255) ))"
\t\tfi
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
\tlocal COLOR="${1:-}"
\tif [ -z "$COLOR" ]; then
\t\techo 49
\t\treturn
\tfi
\tif [[ "$COLOR" =~ ^#([0-9a-fA-F]{6})$ ]]; then
\t\tlocal h="${BASH_REMATCH[1]}"
\t\tlocal r=$((16#${h:0:2})) g=$((16#${h:2:2})) b=$((16#${h:4:2}))
\t\tif [[ "${COLORTERM:-}" == "truecolor" || "${COLORTERM:-}" == "24bit" ]]; then
\t\t\techo "48;2;${r};${g};${b}"
\t\telse
\t\t\techo "48;5;$(( 16 + 36*(r*5/255) + 6*(g*5/255) + (b*5/255) ))"
\t\tfi
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

ZERO_FORK_V12_HELPERS = """# synth-shell-theme: zero_fork_render
# synth-shell-theme: utf8_ps1_guard
# synth-shell-theme: truecolor_24bit
_ssp_color_var()
{
\tlocal c="${1:-}"
\tif [[ -z "$c" ]]; then _SSP_C="39"; return; fi
\tif [[ "$c" =~ ^#([0-9a-fA-F]{6})$ ]]; then
\t\tlocal h="${BASH_REMATCH[1]}"
\t\tlocal r=$((16#${h:0:2})) g=$((16#${h:2:2})) b=$((16#${h:4:2}))
\t\tif [[ "${COLORTERM:-}" == "truecolor" || "${COLORTERM:-}" == "24bit" ]]; then
\t\t\t_SSP_C="38;2;${r};${g};${b}"
\t\telse
\t\t\t_SSP_C="38;5;$(( 16 + 36*(r*5/255) + 6*(g*5/255) + (b*5/255) ))"
\t\tfi
\t\treturn
\tfi
\tif [[ "$c" =~ ^[0-9]+$ ]] && (( c >= 0 && c < 256 )); then
\t\t_SSP_C="38;5;$c"
\telse
\t\tcase "$c" in
\t\t\tblack) _SSP_C="38;5;0" ;; red) _SSP_C="38;5;1" ;;
\t\t\tgreen) _SSP_C="38;5;2" ;; yellow) _SSP_C="38;5;3" ;;
\t\t\tblue) _SSP_C="38;5;4" ;; purple|magenta|pink) _SSP_C="38;5;5" ;;
\t\t\tcyan) _SSP_C="38;5;6" ;; light-gray) _SSP_C="38;5;7" ;;
\t\t\tdark-gray) _SSP_C="38;5;8" ;; light-red) _SSP_C="38;5;9" ;;
\t\t\tlight-green) _SSP_C="38;5;10" ;; light-yellow) _SSP_C="38;5;11" ;;
\t\t\tlight-blue) _SSP_C="38;5;12" ;; light-purple|light-magenta) _SSP_C="38;5;13" ;;
\t\t\tlight-cyan) _SSP_C="38;5;14" ;; white) _SSP_C="38;5;15" ;;
\t\t\t*) _SSP_C="39" ;;
\t\tesac
\tfi
}
_ssp_bg_var()
{
\tlocal c="${1:-}"
\tif [[ -z "$c" ]]; then _SSP_B="49"; return; fi
\tif [[ "$c" =~ ^#([0-9a-fA-F]{6})$ ]]; then
\t\tlocal h="${BASH_REMATCH[1]}"
\t\tlocal r=$((16#${h:0:2})) g=$((16#${h:2:2})) b=$((16#${h:4:2}))
\t\tif [[ "${COLORTERM:-}" == "truecolor" || "${COLORTERM:-}" == "24bit" ]]; then
\t\t\t_SSP_B="48;2;${r};${g};${b}"
\t\telse
\t\t\t_SSP_B="48;5;$(( 16 + 36*(r*5/255) + 6*(g*5/255) + (b*5/255) ))"
\t\tfi
\t\treturn
\tfi
\tif [[ "$c" =~ ^[0-9]+$ ]] && (( c >= 0 && c < 256 )); then
\t\t_SSP_B="48;5;$c"
\telse
\t\tcase "$c" in
\t\t\tblack) _SSP_B="48;5;0" ;; red) _SSP_B="48;5;1" ;;
\t\t\tgreen) _SSP_B="48;5;2" ;; yellow) _SSP_B="48;5;3" ;;
\t\t\tblue) _SSP_B="48;5;4" ;; purple|magenta|pink) _SSP_B="48;5;5" ;;
\t\t\tcyan) _SSP_B="48;5;6" ;; light-gray) _SSP_B="48;5;7" ;;
\t\t\tdark-gray) _SSP_B="48;5;8" ;; light-red) _SSP_B="48;5;9" ;;
\t\t\tlight-green) _SSP_B="48;5;10" ;; light-yellow) _SSP_B="48;5;11" ;;
\t\t\tlight-blue) _SSP_B="48;5;12" ;; light-purple|light-magenta) _SSP_B="48;5;13" ;;
\t\t\tlight-cyan) _SSP_B="48;5;14" ;; white) _SSP_B="48;5;15" ;;
\t\t\t*) _SSP_B="49" ;;
\t\tesac
\tfi
}
_ssp_effect_var()
{
\tcase "${1:-}" in
\t\tbold|bright) _SSP_E="1" ;;
\t\tdim) _SSP_E="2" ;;
\t\titalic) _SSP_E="3" ;;
\t\tunderline) _SSP_E="4" ;;
\t\tblink) _SSP_E="5" ;;
\t\treverse) _SSP_E="7" ;;
\t\thidden) _SSP_E="8" ;;
\t\tstrikeout) _SSP_E="9" ;;
\t\t*) _SSP_E="0" ;;
\tesac
}
_ssp_fmt_var()
{
\tlocal fg="${1:-}" bg="${2:-}" eff="${3:-}"
\t_ssp_color_var "$fg"
\t_ssp_bg_var "$bg"
\tif [[ -n "$eff" ]]; then
\t\t_ssp_effect_var "$eff"
\t\t_SSP_FMT="\\[\\e[0;${_SSP_C};${_SSP_B};${_SSP_E}m\\]"
\telse
\t\t_SSP_FMT="\\[\\e[0;${_SSP_C};${_SSP_B}m\\]"
\tfi
}
_ssp_resolve_sep()
{
\tlocal raw="${1:-}"
\tif [[ -z "$raw" ]]; then
\t\t_SSP_SEP=">"
\t\treturn
\tfi
\tlocal loc="${LC_ALL:-${LC_CTYPE:-${LANG:-}}}"
\tif [[ "$raw" == *'\\u'* || "$raw" == *'\\U'* ]]; then
\t\tcase "$loc" in
\t\t\t*[Uu][Tt][Ff]-8*|*[Uu][Tt][Ff]8*) ;;
\t\t\t*)
\t\t\t\t_SSP_SEP=">"
\t\t\t\treturn
\t\t\t\t;;
\t\tesac
\t\tlocal decoded=""
\t\tprintf -v decoded '%b' "$raw"
\t\tif [[ "$decoded" == *'\\u'* || "$decoded" == *'\\U'* || -z "$decoded" ]]; then
\t\t\t_SSP_SEP=">"
\t\telse
\t\t\t_SSP_SEP="$decoded"
\t\tfi
\telse
\t\t_SSP_SEP="$raw"
\tfi
}
_ssp_print_segment_var()
{
\tlocal text="${1:-}"
\tlocal font_color="${2:-white}"
\tlocal background_color="${3:-none}"
\tlocal next_background_color="${4:-none}"
\tlocal font_effect="${SSP_FONT_EFFECT_OVERRIDE:-${5:-bold}}"
\tlocal sep_char="${6:-${separator_char:-}}"
\t_ssp_resolve_sep "$sep_char"
\tsep_char="$_SSP_SEP"
\tlocal no_color='\\[\\e[0;0m\\]'
\t_ssp_fmt_var "$font_color" "$background_color" "$font_effect"
\tlocal text_format="$_SSP_FMT"
\t_ssp_fmt_var "$background_color" "$next_background_color" ""
\tlocal separator_format="$_SSP_FMT"
\t_SSP_SEG_OUT="${text_format}${segment_padding:- }${text}${segment_padding:- }${separator_padding_left:-}${separator_format}${sep_char}${separator_padding_right:-}${no_color}"
}"""

PATCHED_PRINT_SEGMENT = """printSegment()
{
\tlocal text="${1:-}"
\tlocal font_color="${2:-white}"
\tlocal background_color="${3:-none}"
\tlocal next_background_color="${4:-none}"
\tlocal font_effect="${5:-bold}"
\tlocal sep_char="${6:-${separator_char:-}}"
\t_ssp_print_segment_var "$text" "$font_color" "$background_color" "$next_background_color" "$font_effect" "$sep_char"
\tprintf '%s' "$_SSP_SEG_OUT"
}"""

ENHANCED_GET_PYENV = """getPyenv()
{
\t# synth-shell-theme: pyenv_enhanced (pure-Bash VIRTUAL_ENV_PROMPT + pyvenv.cfg + conda + max_pyenv_char)
\tlocal pyenv=""
\tif [[ -n "${VIRTUAL_ENV_PROMPT:-}" ]]; then
\t\tpyenv="${VIRTUAL_ENV_PROMPT}"
\t\tpyenv="${pyenv#(}" ; pyenv="${pyenv%)}"
\t\tpyenv="${pyenv#"${pyenv%%[![:space:]]*}"}"
\t\tpyenv="${pyenv%"${pyenv##*[![:space:]]}"}"
\telif [[ -n "${VIRTUAL_ENV:-}" && -r "${VIRTUAL_ENV}/pyvenv.cfg" ]]; then
\t\tlocal _line
\t\twhile IFS= read -r _line; do
\t\t\tif [[ "$_line" =~ ^prompt[[:space:]]*=[[:space:]]*(.*)$ ]]; then
\t\t\t\tpyenv="${BASH_REMATCH[1]}"
\t\t\t\tpyenv="${pyenv%"${pyenv##*[![:space:]]}"}"
\t\t\t\tpyenv="${pyenv%\\"}" ; pyenv="${pyenv#\\"}"
\t\t\t\tpyenv="${pyenv%\\'}" ; pyenv="${pyenv#\\'}"
\t\t\t\tbreak
\t\t\tfi
\t\tdone < "${VIRTUAL_ENV}/pyvenv.cfg"
\tfi
\tif [[ -z "$pyenv" && -n "${CONDA_DEFAULT_ENV:-}" ]]; then
\t\tpyenv="${CONDA_DEFAULT_ENV}"
\telif [[ -z "$pyenv" && -n "${VIRTUAL_ENV:-}" ]]; then
\t\tlocal _ve="${VIRTUAL_ENV%/}"
\t\tpyenv="${_ve##*/}"
\t\tif [[ "$pyenv" == ".venv" || "$pyenv" == "venv" ]]; then
\t\t\tlocal _parent="${_ve%/*}"
\t\t\t[[ -n "$_parent" && "$_parent" != "$_ve" ]] && pyenv="${_parent##*/}"
\t\tfi
\tfi
\t[[ -z "$pyenv" ]] && return
\tlocal _max_p="${SSP_MAX_PYENV_CHAR:-0}"
\tif (( _max_p > 3 && ${#pyenv} > _max_p )); then
\t\tpyenv="${pyenv:0:$((_max_p - 1))}…"
\tfi
\tprintf '%s' "$pyenv"
}"""

V12_SEGMENTS_BLOCK = """# synth-shell-theme: v11_segments
# synth-shell-theme: v12_segments
# synth-shell-theme: v13_segments
# synth-shell-theme: responsive_width
# synth-shell-theme: osc133_semantic
# synth-shell-theme: osc7_cwd
# synth-shell-theme: v139_smart_features
# synth-shell-theme: right_prompt
_ssp_has_element()
{
\tlocal target="$1" item
\tfor item in "${SSP_ELEMENTS[@]}" "${SSP_RIGHT_ELEMENTS[@]}"; do
\t\t[[ "$item" == "$target" ]] && return 0
\tdone
\treturn 1
}
_ssp_auto_os_icon()
{
\tif [[ "${OSTYPE:-}" == darwin* ]]; then
\t\t_SSP_PREFIX=" "
\t\treturn
\tfi
\tlocal os_id=""
\tif [[ -r /etc/os-release ]]; then
\t\tlocal _line
\t\twhile IFS= read -r _line; do
\t\t\tif [[ "$_line" == ID=* ]]; then
\t\t\t\tos_id="${_line#ID=}"
\t\t\t\tos_id="${os_id%\\"}" ; os_id="${os_id#\\"}"
\t\t\t\tbreak
\t\t\tfi
\t\tdone < /etc/os-release
\tfi
\tcase "$os_id" in
\t\t[Uu]buntu) _SSP_PREFIX=" " ;;
\t\t[Dd]ebian) _SSP_PREFIX=" " ;;
\t\t[Aa]rch|[Ee]ndeavouros|[Mm]anjaro) _SSP_PREFIX=" " ;;
\t\t[Ff]edora) _SSP_PREFIX=" " ;;
\t\t[Nn]ixos) _SSP_PREFIX=" " ;;
\t\t[Aa]lpine) _SSP_PREFIX=" " ;;
\t\t*) _SSP_PREFIX=" " ;;
\tesac
}
getAws()
{
\tlocal prof="${AWS_PROFILE:-${AWS_VAULT:-${AWS_DEFAULT_PROFILE:-}}}"
\t[[ -z "$prof" ]] && return
\tprintf '☁ %s' "$prof"
}
getGcp()
{
\tlocal proj="${CLOUDSDK_CORE_PROJECT:-${GOOGLE_CLOUD_PROJECT:-}}"
\tif [[ -z "$proj" ]]; then
\t\tlocal gdir="${CLOUDSDK_CONFIG:-$HOME/.config/gcloud}"
\t\tif [[ -r "${gdir}/active_config" ]]; then
\t\t\tlocal active_cfg=""
\t\t\tIFS= read -r active_cfg < "${gdir}/active_config"
\t\t\tlocal cfg_file="${gdir}/configurations/config_${active_cfg}"
\t\t\tif [[ -r "$cfg_file" ]]; then
\t\t\t\tlocal _line
\t\t\t\twhile IFS= read -r _line; do
\t\t\t\t\tif [[ "$_line" =~ ^project[[:space:]]*=[[:space:]]*(.*)$ ]]; then
\t\t\t\t\t\tproj="${BASH_REMATCH[1]}"
\t\t\t\t\t\tproj="${proj%"${proj##*[![:space:]]}"}"
\t\t\t\t\t\tbreak
\t\t\t\t\tfi
\t\t\t\tdone < "$cfg_file"
\t\t\tfi
\t\tfi
\tfi
\t[[ -z "$proj" ]] && return
\tprintf 'GCP:%s' "$proj"
}
getDocker()
{
\tlocal ctx="${DOCKER_CONTEXT:-}"
\tif [[ -z "$ctx" && -r "$HOME/.docker/config.json" ]]; then
\t\tlocal _line
\t\twhile IFS= read -r _line; do
\t\t\tif [[ "$_line" =~ \\"currentContext\\"[[:space:]]*:[[:space:]]*\\"([^\\"]+)\\" ]]; then
\t\t\t\tctx="${BASH_REMATCH[1]}"
\t\t\t\tbreak
\t\t\tfi
\t\tdone < "$HOME/.docker/config.json"
\tfi
\t[[ -z "$ctx" || "$ctx" == "default" ]] && return
\tprintf '🐳 %s' "$ctx"
}
getNode()
{
\t[[ -f package.json ]] || return
\tlocal ver=""
\tif [[ -n "${NVM_BIN:-}" && "$NVM_BIN" =~ /(v[0-9]+\\.[0-9]+\\.[0-9]+)/ ]]; then
\t\tver="${BASH_REMATCH[1]}"
\telif [[ -n "${FNM_MULTISHELL_PATH:-}" && "$FNM_MULTISHELL_PATH" =~ /(v[0-9]+\\.[0-9]+\\.[0-9]+) ]]; then
\t\tver="${BASH_REMATCH[1]}"
\telif [[ -r .nvmrc ]]; then
\t\tIFS= read -r ver < .nvmrc
\t\tver="${ver%"${ver##*[![:space:]]}"}"
\tfi
\t[[ -z "$ver" ]] && return
\tprintf '⬢ %s' "$ver"
}
getSsh()
{
\tif [[ -n "${SSH_CONNECTION:-}" || -n "${SSH_TTY:-}" ]]; then
\t\tprintf '⇄ ssh'
\telif [[ -f /.dockerenv ]]; then
\t\tprintf '🐳 ctr'
\telif [[ -f /run/.containerenv ]]; then
\t\tprintf '📦 pod'
\telif [[ -n "${CONTAINER_ID:-}" ]]; then
\t\tprintf '📦 %s' "$CONTAINER_ID"
\tfi
}
getJobs()
{
\tlocal _jlines _jcount=0 _jl
\t_jlines="$(jobs -p 2>/dev/null)"
\t[[ -z "$_jlines" ]] && return
\twhile IFS= read -r _jl; do
\t\t[[ -n "$_jl" ]] && _jcount=$((_jcount + 1))
\tdone <<< "$_jlines"
\t(( _jcount > 0 )) && printf '⚙ %d' "$_jcount"
}
getDirenv()
{
\tlocal dd="${DIRENV_DIR:-}"
\t[[ -z "$dd" ]] && return
\tdd="${dd#-}"
\tdd="${dd%/}"
\tprintf '⚡ %s' "${dd##*/}"
}
getShlvl()
{
\tif [[ -n "${IN_NIX_SHELL:-}" ]]; then
\t\tprintf '❄ nix'
\telif (( ${SHLVL:-1} > 1 )); then
\t\tprintf '↳ L%d' "$SHLVL"
\tfi
}
getRust()
{
\t[[ -f Cargo.toml ]] || return
\tlocal ver="${RUSTUP_TOOLCHAIN:-}"
\tif [[ -z "$ver" && -r rust-toolchain.toml ]]; then
\t\tlocal _line
\t\twhile IFS= read -r _line; do
\t\t\tif [[ "$_line" =~ channel[[:space:]]*=[[:space:]]*\\"([^\\"]+)\\" ]]; then
\t\t\t\tver="${BASH_REMATCH[1]}"
\t\t\t\tbreak
\t\t\tfi
\t\tdone < rust-toolchain.toml
\tfi
\tif [[ -z "$ver" && -r Cargo.toml ]]; then
\t\tlocal _line
\t\twhile IFS= read -r _line; do
\t\t\tif [[ "$_line" =~ ^rust-version[[:space:]]*=[[:space:]]*\\"([^\\"]+)\\" ]]; then
\t\t\t\tver="${BASH_REMATCH[1]}"
\t\t\t\tbreak
\t\t\tfi
\t\tdone < Cargo.toml
\tfi
\tprintf '🦀 %s' "${ver:-rs}"
}
getGo()
{
\t[[ -f go.mod ]] || return
\tlocal ver="" _line
\twhile IFS= read -r _line; do
\t\tif [[ "$_line" =~ ^go[[:space:]]+([0-9]+\\.[0-9]+(\\.[0-9]+)?) ]]; then
\t\t\tver="${BASH_REMATCH[1]}"
\t\t\tbreak
\t\tfi
\tdone < go.mod
\t[[ -z "$ver" ]] && return
\tprintf '🐹 %s' "$ver"
}
getBattery()
{
\tlocal bat_dir="" cap="" st=""
\tlocal d
\tfor d in /sys/class/power_supply/BAT* /sys/class/power_supply/macsmc-battery; do
\t\tif [[ -r "${d}/capacity" ]]; then
\t\t\tbat_dir="$d"
\t\t\tbreak
\t\tfi
\tdone
\t[[ -z "$bat_dir" ]] && return
\tIFS= read -r cap < "${bat_dir}/capacity"
\t[[ -r "${bat_dir}/status" ]] && IFS= read -r st < "${bat_dir}/status"
\t[[ ! "$cap" =~ ^[0-9]+$ ]] && return
\tlocal thresh="${SSP_BATTERY_THRESHOLD:-100}"
\t(( cap > thresh )) && return
\tlocal icon="🔋"
\tif [[ "$st" == "Charging" ]]; then
\t\ticon="⚡"
\telif (( cap <= 20 )); then
\t\ticon="🪫"
\tfi
\tprintf '%s %d%%' "$icon" "$cap"
}
getSudo()
{
\tcommand -v sudo >/dev/null 2>&1 || return
\tsudo -n true 2>/dev/null && printf '%s' "${SSP_SUDO_SYMBOL:-🔓 sudo}"
}
getJj()
{
\tlocal _w="$PWD" _st=0 _found=0
\twhile [[ -n "$_w" && $_st -lt 15 ]]; do
\t\tif [[ -d "${_w}/.jj" ]]; then _found=1; break; fi
\t\t[[ "$_w" == "/" ]] && break
\t\t_w="${_w%/*}"
\t\t[[ -z "$_w" ]] && _w="/"
\t\t_st=$((_st + 1))
\tdone
\t(( _found == 0 )) && return
\tlocal _jj_out=""
\tif command -v jj >/dev/null 2>&1; then
\t\t_jj_out="$(jj log -r @ --no-graph --ignore-working-copy -T 'change_id.shortest(4) ++ if(bookmarks, " " ++ bookmarks, "")' 2>/dev/null)"
\tfi
\tprintf '🥋 %s' "${_jj_out:-jj}"
}
getCustom()
{
\tlocal _val="${SYNTH_CUSTOM_BADGE:-${SSP_CUSTOM_TEXT:-}}"
\t[[ -z "$_val" ]] && return
\tprintf '%s' "$_val"
}
_ssp_shorten_path_fish()
{
\tlocal p="${1:-$PWD}"
\tif [[ "$p" == "$HOME" ]]; then _SSP_FISH_PATH="~"; return; fi
\tif [[ "$p" == "$HOME"/* ]]; then p="~${p#"$HOME"}"; fi
\tlocal IFS='/' _parts=() _out="" _idx=0 _last=0
\tread -r -a _parts <<< "$p"
\t_last=$(( ${#_parts[@]} - 1 ))
\twhile (( _idx <= _last )); do
\t\tlocal _seg="${_parts[$_idx]}"
\t\tif (( _idx == _last )); then
\t\t\t_out+="${_seg}"
\t\telif [[ -z "$_seg" ]]; then
\t\t\t_out+="/"
\t\telif [[ "$_seg" == "~" ]]; then
\t\t\t_out+="~/"
\t\telif [[ "$_seg" == .* && ${#_seg} -gt 1 ]]; then
\t\t\t_out+="${_seg:0:2}/"
\t\telse
\t\t\t_out+="${_seg:0:1}/"
\t\tfi
\t\t_idx=$(( _idx + 1 ))
\tdone
\t_SSP_FISH_PATH="${_out:-/}"
}
_ssp_osc7_emit()
{
\tlocal _raw="$PWD" _enc="" _i=0 _len=${#PWD} _ch="" _hex=""
\twhile (( _i < _len )); do
\t\t_ch="${_raw:_i:1}"
\t\tcase "$_ch" in
\t\t\t[a-zA-Z0-9._~/-]) _enc+="$_ch" ;;
\t\t\t*) printf -v _hex '%%%02X' "'$_ch" 2>/dev/null && _enc+="$_hex" || _enc+="$_ch" ;;
\t\tesac
\t\t_i=$(( _i + 1 ))
\tdone
\tprintf '\\e]7;file://%s%s\\a' "${HOSTNAME:-localhost}" "$_enc"
}
_ssp_host_color_var()
{
\t_SSP_SSH_HOST_FG=""
\t_SSP_SSH_HOST_BG=""
\t[[ "${SSP_SSH_HOST_COLOR:-false}" != "true" ]] && return
\t[[ -z "${SSH_CONNECTION:-}" && -z "${SSP_FORCE_SSH_COLOR:-}" ]] && return
\tlocal hn="${HOSTNAME:-localhost}"
\tlocal _had_nc=0
\tshopt -q nocasematch && _had_nc=1
\tshopt -s nocasematch
\tif [[ "$hn" =~ (prod|production|prd|live) ]]; then
\t\t_SSP_SSH_HOST_FG="white"; _SSP_SSH_HOST_BG="196"
\telif [[ "$hn" =~ (stg|stag|staging|uat|qa) ]]; then
\t\t_SSP_SSH_HOST_FG="black"; _SSP_SSH_HOST_BG="214"
\tfi
\t(( _had_nc == 0 )) && shopt -u nocasematch
\t[[ -n "$_SSP_SSH_HOST_BG" ]] && return
\tlocal _pal=(33 37 68 71 98 130 135 166 172 203 39 63)
\tlocal _h=0 _i=0 _c="" _n=0 _hlen=${#hn}
\twhile (( _i < _hlen )); do
\t\t_c="${hn:_i:1}"
\t\tprintf -v _n '%d' "'$_c" 2>/dev/null || _n=7
\t\t_h=$(( (_h * 31 + _n) % 12 ))
\t\t_i=$(( _i + 1 ))
\tdone
\t_SSP_SSH_HOST_FG="white"
\t_SSP_SSH_HOST_BG="${_pal[$_h]}"
}
_ssp_format_duration_var()
{
\t_SSP_DUR=""
\t_SSP_LAST_ELAPSED_MS=0
\tlocal start_ms="${_SSP_CMD_START_MS:-0}"
\t(( start_ms <= 0 )) && return
\tlocal now_ms=0
\tif [[ -n "${EPOCHREALTIME:-}" ]]; then
\t\tnow_ms=$(( ${EPOCHREALTIME/./} / 1000 ))
\telse
\t\tnow_ms=$(( SECONDS * 1000 ))
\tfi
\tlocal elapsed=$(( now_ms - start_ms ))
\t_SSP_LAST_ELAPSED_MS=$elapsed
\tlocal min_ms="${SSP_MIN_DURATION_MS:-2000}"
\t(( elapsed < min_ms )) && return
\tif (( elapsed >= 60000 )); then
\t\tprintf -v _SSP_DUR '⏱ %dm %ds' $(( elapsed / 60000 )) $(( (elapsed % 60000) / 1000 ))
\telse
\t\tprintf -v _SSP_DUR '⏱ %d.%ds' $(( elapsed / 1000 )) $(( (elapsed % 1000) / 100 ))
\tfi
}"""

V12_COLORS_FOR_ELEMENT = """get_colors_for_element()
{
\tcase "${1:-}" in
\t\t"USER")     echo "${SSP_COLORS_USER[@]}" ;;
\t\t"HOST")     echo "${SSP_COLORS_HOST[@]}" ;;
\t\t"PWD")      echo "${SSP_COLORS_PWD[@]}" ;;
\t\t"GIT")      echo "${SSP_COLORS_GIT[@]}" ;;
\t\t"PYENV")    echo "${SSP_COLORS_PYENV[@]}" ;;
\t\t"KUBE")     echo "${SSP_COLORS_KUBE[@]}" ;;
\t\t"TF")       echo "${SSP_COLORS_TF[@]}" ;;
\t\t"CLOCK")    echo "${SSP_COLORS_CLOCK[@]}" ;;
\t\t"STATUS")   echo "${SSP_COLORS_STATUS[@]}" ;;
\t\t"DURATION") echo "${SSP_COLORS_DURATION[@]}" ;;
\t\t"AWS")      echo "${SSP_COLORS_AWS[@]}" ;;
\t\t"GCP")      echo "${SSP_COLORS_GCP[@]}" ;;
\t\t"DOCKER")   echo "${SSP_COLORS_DOCKER[@]}" ;;
\t\t"NODE")     echo "${SSP_COLORS_NODE[@]}" ;;
\t\t"SSH")      echo "${SSP_COLORS_SSH[@]}" ;;
\t\t"JOBS")     echo "${SSP_COLORS_JOBS[@]}" ;;
\t\t"DIRENV")   echo "${SSP_COLORS_DIRENV[@]}" ;;
\t\t"SHLVL")    echo "${SSP_COLORS_SHLVL[@]}" ;;
\t\t"RUST")     echo "${SSP_COLORS_RUST[@]}" ;;
\t\t"GO")       echo "${SSP_COLORS_GO[@]}" ;;
\t\t"BATTERY")  echo "${SSP_COLORS_BATTERY[@]}" ;;
\t\t"SUDO")     echo "${SSP_COLORS_SUDO[@]}" ;;
\t\t"JJ")       echo "${SSP_COLORS_JJ[@]}" ;;
\t\t"CUSTOM")   echo "${SSP_COLORS_CUSTOM[@]}" ;;
\t\t"INPUT")    echo "${SSP_COLORS_INPUT[@]}" ;;
\t\t*) ;;
\tesac
}
_ssp_colors_var()
{
\tcase "${1:-}" in
\t\t"USER")     _SSP_EL_C=("${SSP_COLORS_USER[@]}") ;;
\t\t"HOST")     _SSP_EL_C=("${SSP_COLORS_HOST[@]}") ;;
\t\t"PWD")      _SSP_EL_C=("${SSP_COLORS_PWD[@]}") ;;
\t\t"GIT")      _SSP_EL_C=("${SSP_COLORS_GIT[@]}") ;;
\t\t"PYENV")    _SSP_EL_C=("${SSP_COLORS_PYENV[@]}") ;;
\t\t"KUBE")     _SSP_EL_C=("${SSP_COLORS_KUBE[@]}") ;;
\t\t"TF")       _SSP_EL_C=("${SSP_COLORS_TF[@]}") ;;
\t\t"CLOCK")    _SSP_EL_C=("${SSP_COLORS_CLOCK[@]}") ;;
\t\t"STATUS")   _SSP_EL_C=("${SSP_COLORS_STATUS[@]}") ;;
\t\t"DURATION") _SSP_EL_C=("${SSP_COLORS_DURATION[@]}") ;;
\t\t"AWS")      _SSP_EL_C=("${SSP_COLORS_AWS[@]}") ;;
\t\t"GCP")      _SSP_EL_C=("${SSP_COLORS_GCP[@]}") ;;
\t\t"DOCKER")   _SSP_EL_C=("${SSP_COLORS_DOCKER[@]}") ;;
\t\t"NODE")     _SSP_EL_C=("${SSP_COLORS_NODE[@]}") ;;
\t\t"SSH")      _SSP_EL_C=("${SSP_COLORS_SSH[@]}") ;;
\t\t"JOBS")     _SSP_EL_C=("${SSP_COLORS_JOBS[@]}") ;;
\t\t"DIRENV")   _SSP_EL_C=("${SSP_COLORS_DIRENV[@]}") ;;
\t\t"SHLVL")    _SSP_EL_C=("${SSP_COLORS_SHLVL[@]}") ;;
\t\t"RUST")     _SSP_EL_C=("${SSP_COLORS_RUST[@]}") ;;
\t\t"GO")       _SSP_EL_C=("${SSP_COLORS_GO[@]}") ;;
\t\t"BATTERY")  _SSP_EL_C=("${SSP_COLORS_BATTERY[@]}") ;;
\t\t"SUDO")     _SSP_EL_C=("${SSP_COLORS_SUDO[@]}") ;;
\t\t"JJ")       _SSP_EL_C=("${SSP_COLORS_JJ[@]}") ;;
\t\t"CUSTOM")   _SSP_EL_C=("${SSP_COLORS_CUSTOM[@]}") ;;
\t\t"INPUT")    _SSP_EL_C=("${SSP_COLORS_INPUT[@]}") ;;
\t\t*)          _SSP_EL_C=(white none bold) ;;
\tesac
}"""

V12_COMBINE_ELEMENTS = """_ssp_text_for_el()
{
\tcase "${1:-}" in
\t\t"USER")     _SSP_EL_TXT="${user:-}" ;;
\t\t"HOST")     _SSP_EL_TXT="${host:-}" ;;
\t\t"PWD")      _SSP_EL_TXT="${path:-}" ;;
\t\t"GIT")      _SSP_EL_TXT="${git_branch:-}" ;;
\t\t"PYENV")    _SSP_EL_TXT="${pyenv:-}" ;;
\t\t"KUBE")     _SSP_EL_TXT="${kube:-}" ;;
\t\t"TF")       _SSP_EL_TXT="${tf:-}" ;;
\t\t"CLOCK")    _SSP_EL_TXT="${clock:-}" ;;
\t\t"STATUS")   _SSP_EL_TXT="${status_seg:-}" ;;
\t\t"DURATION") _SSP_EL_TXT="${duration_seg:-}" ;;
\t\t"AWS")      _SSP_EL_TXT="${aws_seg:-}" ;;
\t\t"GCP")      _SSP_EL_TXT="${gcp_seg:-}" ;;
\t\t"DOCKER")   _SSP_EL_TXT="${docker_seg:-}" ;;
\t\t"NODE")     _SSP_EL_TXT="${node_seg:-}" ;;
\t\t"SSH")      _SSP_EL_TXT="${ssh_seg:-}" ;;
\t\t"JOBS")     _SSP_EL_TXT="${jobs_seg:-}" ;;
\t\t"DIRENV")   _SSP_EL_TXT="${direnv_seg:-}" ;;
\t\t"SHLVL")    _SSP_EL_TXT="${shlvl_seg:-}" ;;
\t\t"RUST")     _SSP_EL_TXT="${rust_seg:-}" ;;
\t\t"GO")       _SSP_EL_TXT="${go_seg:-}" ;;
\t\t"BATTERY")  _SSP_EL_TXT="${battery_seg:-}" ;;
\t\t"SUDO")     _SSP_EL_TXT="${sudo_seg:-}" ;;
\t\t"JJ")       _SSP_EL_TXT="${jj_seg:-}" ;;
\t\t"CUSTOM")   _SSP_EL_TXT="${custom_seg:-}" ;;
\t\t"INPUT")    _SSP_EL_TXT="" ;;
\t\t*)          _SSP_EL_TXT="" ;;
\tesac
}
_ssp_dyn_colors_var()
{
\t_ssp_colors_var "$1"
\tif [[ "$1" == "KUBE" && "${kube:-}" == *"🚨"* ]]; then
\t\t_SSP_EL_C=(white 196 "${_SSP_EL_C[2]:-bold}")
\telif [[ "$1" == "HOST" && -n "${_SSP_SSH_HOST_BG:-}" ]]; then
\t\t_SSP_EL_C=("${_SSP_SSH_HOST_FG:-white}" "${_SSP_SSH_HOST_BG}" "${_SSP_EL_C[2]:-bold}")
\telif [[ "$1" == "GIT" && "${SSP_GIT_DYNAMIC_COLOR:-false}" == "true" ]]; then
\t\tif [[ "${git_branch:-}" == *"| REBASE"* || "${git_branch:-}" == *"| MERGE"* || "${git_branch:-}" == *"| CHERRY"* || "${git_branch:-}" == *"| BISECT"* ]]; then
\t\t\t_SSP_EL_C=(white 196 "${_SSP_EL_C[2]:-bold}")
\t\telif [[ ( -n "${SSP_GIT_DIRTY:-}" && "${git_branch:-}" == *"${SSP_GIT_DIRTY}"* ) || "${git_branch:-}" == *"◔"* || "${git_branch:-}" == *"*"* ]]; then
\t\t\t_SSP_EL_C=(black 214 "${_SSP_EL_C[2]:-bold}")
\t\tfi
\tfi
}
_ssp_combine_var()
{
\tlocal first="${1:-}"
\tlocal second="${2:-}"
\t_ssp_dyn_colors_var "$first"
\tlocal text_color="${_SSP_EL_C[0]:-white}"
\tlocal bg_color="${_SSP_EL_C[1]:-none}"
\tlocal text_effect="${_SSP_EL_C[2]:-bold}"
\t_ssp_dyn_colors_var "$second"
\tlocal next_bg_color="${_SSP_EL_C[1]:-none}"
\t_ssp_text_for_el "$first"
\tlocal text="$_SSP_EL_TXT"
\tlocal sep_char="${separator_char:-}"
\tif [ "$second" = "INPUT" ] && [ -n "${separator_char_end:-}" ]; then
\t\tsep_char="$separator_char_end"
\tfi
\t_ssp_print_segment_var "$text" "$text_color" "$bg_color" "$next_bg_color" "$text_effect" "$sep_char"
}
combine_elements()
{
\t_ssp_combine_var "${1:-}" "${2:-}"
\tprintf '%s' "$_SSP_SEG_OUT"
}"""

V12_PROMPT_COMMAND_HOOK = """prompt_command_hook()
{
\tlocal last_exit=$?
\tlocal _ssp_had_u=0
\t[[ $- == *u* ]] && { _ssp_had_u=1; set +u; }
\t# synth-shell-theme: terminal_sanitize (auto-clear leaked SSH/TUI mouse tracking & focus reporting)
\tif [[ "${SSP_TERMINAL_SANITIZE:-true}" == "true" && -z "${BLE_VERSION:-}" ]] && [[ -t 1 || "${SSP_FORCE_SANITIZE:-}" == "1" ]]; then
\t\tprintf '\\e[?1000l\\e[?1002l\\e[?1003l\\e[?1006l\\e[?1015l\\e[?1004l'
\tfi
\tif [[ "${SSP_ENABLE_OSC7:-true}" == "true" ]] && [[ -t 1 || "${SSP_FORCE_OSC7:-}" == "1" ]]; then
\t\t_ssp_osc7_emit
\tfi
\t_ssp_host_color_var
\tlocal elements=("${SSP_ELEMENTS[@]}")
\tlocal right_elements=("${SSP_RIGHT_ELEMENTS[@]}")
\tlocal user="${USER:-}"
\tlocal host="${HOSTNAME:-}"
\tlocal _is_compact=0
\tlocal _cw="${SSP_COMPACT_WIDTH:-90}"
\tif (( _cw > 0 && ${COLUMNS:-120} > 0 && ${COLUMNS:-120} < _cw )); then
\t\t_is_compact=1
\tfi
\tlocal _eff_pwd_max="${SSP_MAX_PWD_CHAR:-35}"
\tif (( _is_compact == 1 && _eff_pwd_max > 18 )); then
\t\t_eff_pwd_max=18
\tfi
\tlocal path="" git_branch="" pyenv="" kube="" tf="" clock=""
\tlocal status_seg="" duration_seg="" aws_seg="" gcp_seg="" docker_seg="" node_seg="" ssh_seg=""
\tlocal jobs_seg="" direnv_seg="" shlvl_seg="" rust_seg="" go_seg="" battery_seg=""
\tlocal sudo_seg="" jj_seg="" custom_seg=""

\tif _ssp_has_element "PWD"; then
\t\tif [[ "${SSP_PWD_STYLE:-default}" == "fish" ]]; then
\t\t\t_ssp_shorten_path_fish "$PWD"
\t\t\tpath="$_SSP_FISH_PATH"
\t\telse
\t\t\tpath="$(shortenPath "$PWD" "$_eff_pwd_max" "${SSP_PWD_TRUNC_SYMBOL:-…}")"
\t\tfi
\tfi
\t_ssp_has_element "GIT" && git_branch="$(getGitBranch)"
\t_ssp_has_element "JJ" && jj_seg="$(getJj)"
\t_ssp_has_element "PYENV" && pyenv="$(getPyenv)"
\tif (( _is_compact == 0 )); then
\t\t_ssp_has_element "KUBE" && kube="$(getKube)"
\t\t_ssp_has_element "TF" && tf="$(getTerraform)"
\t\tif _ssp_has_element "CLOCK"; then
\t\t\tprintf -v clock "%(${SSP_CLOCK_FORMAT:-%H:%M})T" -1 2>/dev/null || clock="$(date +"${SSP_CLOCK_FORMAT:-%H:%M}")"
\t\tfi
\t\t_ssp_has_element "AWS" && aws_seg="$(getAws)"
\t\t_ssp_has_element "GCP" && gcp_seg="$(getGcp)"
\t\t_ssp_has_element "DOCKER" && docker_seg="$(getDocker)"
\t\t_ssp_has_element "NODE" && node_seg="$(getNode)"
\t\t_ssp_has_element "RUST" && rust_seg="$(getRust)"
\t\t_ssp_has_element "GO" && go_seg="$(getGo)"
\t\t_ssp_has_element "BATTERY" && battery_seg="$(getBattery)"
\tfi
\tif _ssp_has_element "STATUS" && (( last_exit != 0 )); then
\t\tstatus_seg="${SSP_STATUS_SYMBOL:-✗ }${last_exit}"
\tfi
\t_SSP_LAST_ELAPSED_MS=0
\tif _ssp_has_element "DURATION" || (( ${SSP_NOTIFY_DURATION_SEC:-0} > 0 )); then
\t\t_ssp_format_duration_var
\t\t_ssp_has_element "DURATION" && duration_seg="$_SSP_DUR"
\tfi
\tif (( ${SSP_NOTIFY_DURATION_SEC:-0} > 0 && _SSP_LAST_ELAPSED_MS >= SSP_NOTIFY_DURATION_SEC * 1000 )) && [[ -t 1 || "${SSP_FORCE_NOTIFY:-}" == "1" ]]; then
\t\tlocal _n_msg=""
\t\tif (( last_exit == 0 )); then
\t\t\tprintf -v _n_msg 'synth-shell: ✓ Command finished (%d.%ds)' $(( _SSP_LAST_ELAPSED_MS / 1000 )) $(( (_SSP_LAST_ELAPSED_MS % 1000) / 100 ))
\t\telse
\t\t\tprintf -v _n_msg 'synth-shell: ✗ Command failed (exit %d, %d.%ds)' "$last_exit" $(( _SSP_LAST_ELAPSED_MS / 1000 )) $(( (_SSP_LAST_ELAPSED_MS % 1000) / 100 ))
\t\tfi
\t\tcase "${TERM:-}" in
\t\t\t*kitty*) printf '\\e]99;i=1:d=0;%s\\a' "$_n_msg" ;;
\t\t\t*)       printf '\\e]9;%s\\a' "$_n_msg" ;;
\t\tesac
\tfi
\t_SSP_CMD_START_MS=0
\t_ssp_has_element "SSH" && ssh_seg="$(getSsh)"
\t_ssp_has_element "JOBS" && jobs_seg="$(getJobs)"
\t_ssp_has_element "DIRENV" && direnv_seg="$(getDirenv)"
\t_ssp_has_element "SHLVL" && shlvl_seg="$(getShlvl)"
\t_ssp_has_element "SUDO" && sudo_seg="$(getSudo)"
\t_ssp_has_element "CUSTOM" && custom_seg="$(getCustom)"

\tlocal filtered=() _el
\tfor _el in "${elements[@]}"; do
\t\t_ssp_text_for_el "$_el"
\t\tif [[ "$_el" == "INPUT" || -n "$_SSP_EL_TXT" ]]; then
\t\t\tfiltered+=("$_el")
\t\tfi
\tdone
\telements=("${filtered[@]}")

\tlocal r_filtered=()
\tif (( _is_compact == 0 && ${#right_elements[@]} > 0 )) && [[ -n "${SSP_PROMPT_COMM_SEP:-}" ]]; then
\t\tfor _el in "${right_elements[@]}"; do
\t\t\t_ssp_text_for_el "$_el"
\t\t\t[[ -n "$_SSP_EL_TXT" ]] && r_filtered+=("$_el")
\t\tdone
\tfi

\tlocal titlebar=""
\tif [[ "${SSP_ENABLE_TERMINAL_TITLE:-true}" == "true" ]]; then
\t\tcase "${TERM:-}" in
\t\t\txterm*|rxvt*|screen*|tmux*|alacritty*|kitty*|foot*|wezterm*|ghostty*)
\t\t\t\tSSP_PWD="$path"
\t\t\t\ttitlebar="\\[\\e]0;\\u@\\h: \\w\\a\\]"
\t\t\t\t;;
\t\tesac
\tfi

\tlocal osc_pre="" osc_post=""
\tif [[ "${SSP_ENABLE_OSC133:-true}" == "true" ]]; then
\t\tif (( ${_SSP_HAS_RUN:-0} == 1 )); then
\t\t\tosc_pre="\\[\\e]133;D;${last_exit}\\a\\]\\[\\e]133;A\\a\\]"
\t\telse
\t\t\tosc_pre="\\[\\e]133;A\\a\\]"
\t\tfi
\t\tosc_post="\\[\\e]133;B\\a\\]"
\t\t_SSP_HAS_RUN=1
\tfi

\tPS1="${osc_pre}${titlebar}${SSP_VERTICAL_PADDING:-}${SSP_NEW_LINE_LINK_TOP:-}${SSP_PROMPT_PREFIX:-}"
\tlocal _top_s="${SSP_NEW_LINE_LINK_TOP:-}" _pre_s="${SSP_PROMPT_PREFIX:-}" _pad_s="${segment_padding:- }"
\tlocal left_vis=$(( ${#_top_s} + ${#_pre_s} ))
\tlocal pad_w=$(( ${#_pad_s} * 2 + 1 ))
\tlocal idx=0 total="${#elements[@]}"
\twhile (( idx + 1 < total )); do
\t\t_ssp_text_for_el "${elements[$idx]}"
\t\tleft_vis=$(( left_vis + ${#_SSP_EL_TXT} + pad_w ))
\t\t_ssp_combine_var "${elements[$idx]}" "${elements[$((idx + 1))]}"
\t\tPS1+="$_SSP_SEG_OUT"
\t\tidx=$((idx + 1))
\tdone

\tif (( ${#r_filtered[@]} > 0 )); then
\t\tlocal right_str="" right_vis=0 r_idx=0 r_tot="${#r_filtered[@]}"
\t\twhile (( r_idx < r_tot )); do
\t\t\tlocal r_cur="${r_filtered[$r_idx]}"
\t\t\tlocal r_nxt="INPUT"
\t\t\t(( r_idx + 1 < r_tot )) && r_nxt="${r_filtered[$((r_idx + 1))]}"
\t\t\t_ssp_text_for_el "$r_cur"
\t\t\tright_vis=$(( right_vis + ${#_SSP_EL_TXT} + pad_w ))
\t\t\t_ssp_combine_var "$r_cur" "$r_nxt"
\t\t\tright_str+="$_SSP_SEG_OUT"
\t\t\tr_idx=$((r_idx + 1))
\t\tdone
\t\tlocal fill_len=$(( ${COLUMNS:-120} - left_vis - right_vis - 2 ))
\t\tif (( fill_len >= 2 )); then
\t\t\tlocal fill_ch="${SSP_RIGHT_FILL_CHAR:-─}"
\t\t\tlocal fill_spaces=""
\t\t\tprintf -v fill_spaces '%*s' "$fill_len" ""
\t\t\tlocal fill_line="${fill_spaces// /$fill_ch}"
\t\t\tPS1+=" \\[\\e[0;38;5;239m\\]${fill_line}\\[\\e[0;0m\\] ${right_str}"
\t\tfi
\tfi

\t_ssp_colors_var "${elements[$idx]}"
\tlocal input_color="${_SSP_EL_C[0]:-white}"
\tlocal input_bg="${_SSP_EL_C[1]:-none}"
\tlocal input_effect="${_SSP_EL_C[2]:-bold}"
\t_ssp_fmt_var "$input_color" "$input_bg" "$input_effect"
\tlocal input_format="$_SSP_FMT"
\tlocal command_start_symbol="${input_format}${SSP_BASH_SYMBOL:-}"
\tPS1="${PS1}${SSP_PROMPT_COMM_SEP:-}${SSP_NEW_LINE_LINK_BOTTOM:-}${command_start_symbol} ${input_format}${osc_post}"
\tif (( _ssp_had_u )); then set -u; fi
}"""

V12_INIT_AND_CHAINING = """\t# synth-shell-theme: v11_init
\t# synth-shell-theme: v12_init
\t# synth-shell-theme: v13_init
\t# synth-shell-theme: v139_init
\t# synth-shell-theme: hook_chaining
\tSSP_RIGHT_ELEMENTS=(${right_format:-})
\tSSP_RIGHT_FILL_CHAR="${right_fill_char:-─}"
\tSSP_ENABLE_OSC133=${enable_osc133:-true}
\tSSP_ENABLE_OSC7=${enable_osc7:-true}
\tSSP_TERMINAL_SANITIZE=${enable_terminal_sanitize:-true}
\tSSP_KUBE_SHOW_NAMESPACE=${kube_show_namespace:-true}
\tSSP_KUBE_PROD_WARNING=${kube_prod_warning:-true}
\tSSP_KUBE_PROD_PATTERN="${kube_prod_pattern:-prod|production|prd|live}"
\tSSP_GIT_DYNAMIC_COLOR=${git_dynamic_color:-false}
\tSSP_SSH_HOST_COLOR=${ssh_host_color:-false}
\tSSP_PWD_STYLE="${pwd_style:-default}"
\tSSP_NOTIFY_DURATION_SEC=${notify_duration_sec:-0}
\tSSP_CUSTOM_TEXT="${custom_segment_text:-}"
\tSSP_SUDO_SYMBOL="${sudo_symbol:-🔓 sudo}"
\tSSP_GIT_SHOW_STATE=${git_show_state:-true}
\tSSP_BATTERY_THRESHOLD=${battery_threshold:-100}
\tSSP_COLORS_STATUS=(${font_color_status:-white} ${background_status:-196} ${texteffect_status:-bold})
\tSSP_COLORS_DURATION=(${font_color_duration:-black} ${background_duration:-220} ${texteffect_duration:-bold})
\tSSP_COLORS_AWS=(${font_color_aws:-black} ${background_aws:-208} ${texteffect_aws:-bold})
\tSSP_COLORS_GCP=(${font_color_gcp:-white} ${background_gcp:-33} ${texteffect_gcp:-bold})
\tSSP_COLORS_DOCKER=(${font_color_docker:-white} ${background_docker:-39} ${texteffect_docker:-bold})
\tSSP_COLORS_NODE=(${font_color_node:-black} ${background_node:-76} ${texteffect_node:-bold})
\tSSP_COLORS_SSH=(${font_color_ssh:-white} ${background_ssh:-125} ${texteffect_ssh:-bold})
\tSSP_COLORS_JOBS=(${font_color_jobs:-black} ${background_jobs:-214} ${texteffect_jobs:-bold})
\tSSP_COLORS_DIRENV=(${font_color_direnv:-black} ${background_direnv:-114} ${texteffect_direnv:-bold})
\tSSP_COLORS_SHLVL=(${font_color_shlvl:-white} ${background_shlvl:-99} ${texteffect_shlvl:-bold})
\tSSP_COLORS_RUST=(${font_color_rust:-white} ${background_rust:-166} ${texteffect_rust:-bold})
\tSSP_COLORS_GO=(${font_color_go:-black} ${background_go:-81} ${texteffect_go:-bold})
\tSSP_COLORS_BATTERY=(${font_color_battery:-black} ${background_battery:-114} ${texteffect_battery:-bold})
\tSSP_COLORS_SUDO=(${font_color_sudo:-white} ${background_sudo:-196} ${texteffect_sudo:-bold})
\tSSP_COLORS_JJ=(${font_color_jj:-black} ${background_jj:-214} ${texteffect_jj:-bold})
\tSSP_COLORS_CUSTOM=(${font_color_custom:-black} ${background_custom:-219} ${texteffect_custom:-bold})
\tSSP_MAX_GIT_CHAR=${max_git_char:-0}
\tSSP_MAX_PYENV_CHAR=${max_pyenv_char:-0}
\tSSP_MAX_KUBE_CHAR=${max_kube_char:-28}
\tSSP_COMPACT_WIDTH=${compact_width:-90}
\tSSP_GIT_SHOW_COUNTS=${git_show_counts:-true}
\tSSP_GIT_SKIP_UNTRACKED_ON_SLOW_FS=${git_skip_untracked_on_slow_fs:-true}
\tSSP_GIT_TIMEOUT_MS=${git_timeout_ms:-0}
\tSSP_GIT_ASYNC_CACHE=${git_async_cache:-false}
\tSSP_MIN_DURATION_MS=${min_duration_ms:-2000}
\tSSP_ENABLE_TERMINAL_TITLE=${enable_terminal_title:-true}
\tSSP_FONT_EFFECT_OVERRIDE="${font_effect_override:-}"
\tSSP_STATUS_SYMBOL="${status_symbol:-✗ }"
\tSSP_TRANSIENT_PROMPT=${transient_prompt:-false}
\tif [[ "${prompt_prefix:-}" == "auto" ]]; then
\t\t_ssp_auto_os_icon
\t\tSSP_PROMPT_PREFIX="$_SSP_PREFIX"
\telse
\t\tSSP_PROMPT_PREFIX="${prompt_prefix:-}"
\tfi
\t_ssp_resolve_sep "${separator_char:-\\uE0B0}"
\tseparator_char="$_SSP_SEP"
\tif [[ -n "${separator_char_end:-}" ]]; then
\t\t_ssp_resolve_sep "${separator_char_end}"
\t\tseparator_char_end="$_SSP_SEP"
\tfi
\t_SSP_EMPTY=""
\t_SSP_CMD_START_MS=0
\t_SSP_HAS_RUN=0
\tlocal _ps0_osc=""
\t[[ "${SSP_ENABLE_OSC133}" == "true" ]] && _ps0_osc=$'\\e]133;C\\a'
\tif [[ -n "${EPOCHREALTIME:-}" ]]; then
\t\tPS0="${_ps0_osc}"$'\\e[0m''${_SSP_EMPTY:0:((_SSP_CMD_START_MS=${EPOCHREALTIME/./}/1000, 0))}'
\telse
\t\tPS0="${_ps0_osc}"$'\\e[0m''${_SSP_EMPTY:0:((_SSP_CMD_START_MS=SECONDS*1000, 0))}'
\tfi
\tif [[ "${SSP_TRANSIENT_PROMPT}" == "true" && -n "${BLE_VERSION:-}" ]] && command -v bleopt >/dev/null 2>&1; then
\t\tbleopt prompt_ps1_transient=trim 2>/dev/null || true
\tfi
\tif declare -p PROMPT_COMMAND 2>/dev/null | grep -q 'declare -a'; then
\t\tlocal _ssp_pc_has=0 _ssp_pc_item
\t\tfor _ssp_pc_item in "${PROMPT_COMMAND[@]}"; do
\t\t\t[[ "$_ssp_pc_item" == "prompt_command_hook" ]] && _ssp_pc_has=1 && break
\t\tdone
\t\t(( _ssp_pc_has == 0 )) && PROMPT_COMMAND=(prompt_command_hook "${PROMPT_COMMAND[@]}")
\telse
\t\tcase ";${PROMPT_COMMAND:-};" in
\t\t\t*";prompt_command_hook;"*) ;;
\t\t\t";;") PROMPT_COMMAND="prompt_command_hook" ;;
\t\t\t*) PROMPT_COMMAND="prompt_command_hook;${PROMPT_COMMAND}" ;;
\t\tesac
\tfi"""

PATCHED_GREETER_AMD_TEMP = """printInfoCPUTemp()
{
\t# synth-shell-theme: greeter_amd_temp (LC_ALL=C + AMD k10temp/Tctl/Tdie support)
\tif command -v sensors >/dev/null 2>&1; then
\t\tlocal temp_line
\t\ttemp_line="$(LC_ALL=C sensors 2>/dev/null | grep -E '^(Core 0|Package id 0|Tctl|Tdie|CPU|temp1):' | head -n 1 | sed 's/^.*:[ \\t]*//g;s/[\\(\\),]//g')"
\t\tif [[ -z "$temp_line" ]]; then
\t\t\tprintInfoLine "CPU temp" "unavailable"
\t\t\treturn
\t\tfi
\t\tlocal current=""
\t\tif [[ "$temp_line" =~ \\+?([0-9]+(\\.[0-9]+)?) ]]; then
\t\t\tcurrent="${BASH_REMATCH[1]}"
\t\tfi
\t\tif [[ -z "$current" ]]; then
\t\t\tprintInfoLine "CPU temp" "unavailable"
\t\t\treturn
\t\tfi
\t\tlocal high=75 max=90
\t\t[[ "$temp_line" =~ high[[:space:]]*=[[:space:]]*\\+?([0-9]+(\\.[0-9]+)?) ]] && high="${BASH_REMATCH[1]}"
\t\t[[ "$temp_line" =~ crit[[:space:]]*=[[:space:]]*\\+?([0-9]+(\\.[0-9]+)?) ]] && max="${BASH_REMATCH[1]}"
\t\tlocal cur_int="${current%%.*}" high_int="${high%%.*}" max_int="${max%%.*}"
\t\tlocal state="nominal"
\t\tif (( cur_int >= max_int )); then
\t\t\tstate="error"
\t\telif (( cur_int >= high_int )); then
\t\t\tstate="critical"
\t\tfi
\t\tprintInfoLine "CPU temp" "${current}°C" "$state"
\telse
\t\tprintInfoLine "CPU temp" "lm-sensors not installed"
\tfi
}"""

PATCHED_GREETER_ZFS_RAM = """printMonitorRAM()
{
\t# synth-shell-theme: greeter_zfs_arc (accounts for reclaimable ZFS ARC memory)
\tassert_is_set $bar_ram_units
\tassert_is_set $bar_ram_crit_percent
\tlocal format=$1
\tlocal label="Memory"
\tlocal units="GB" option="--giga" div=1073741824
\tcase "$bar_ram_units" in
\t\t"MB") units="MB"; option="--mega"; div=1048576 ;;
\t\t"TB") units="TB"; option="--tera"; div=1099511627776 ;;
\t\t"PB") units="PB"; option="--peta"; div=1125899906842624 ;;
\tesac
\tlocal mem_info
\tmem_info=$('free' "$option" | head -n 2 | tail -n 1)
\tlocal current_value
\tcurrent_value=$(echo "$mem_info" | awk '{mem=($2-$7)} END {printf mem}')
\tlocal max
\tmax=$(echo "$mem_info" | awk '{mem=($2)} END {printf mem}')
\tif [[ -r /proc/spl/kstat/zfs/arcstats ]]; then
\t\tlocal arc_size=0 arc_cmin=0 _k _t _v
\t\twhile read -r _k _t _v; do
\t\t\t[[ "$_k" == "size" ]] && arc_size="$_v"
\t\t\t[[ "$_k" == "c_min" ]] && arc_cmin="$_v"
\t\tdone < /proc/spl/kstat/zfs/arcstats
\t\tif (( arc_size > arc_cmin )); then
\t\t\tlocal reclaim=$(( (arc_size - arc_cmin) / div ))
\t\t\tif (( current_value > reclaim )); then
\t\t\t\tcurrent_value=$(( current_value - reclaim ))
\t\t\tfi
\t\tfi
\tfi
\tlocal crit_percent=$bar_ram_crit_percent
\tprintResourceMonitor "$label" "$current_value" "$max" "$units" "$format" "$crit_percent"
}"""

def _fn_re(name: str) -> re.Pattern[str]:
    return re.compile(rf"^{name}\(\)\s*\{{(?:[^\n]*\}}|.*?\n\}})", re.MULTILINE | re.DOTALL)


_GET_KUBE_RE = _fn_re("getKube")
_GET_PYENV_RE = _fn_re("getPyenv")
_PRINT_SEG_FULL_RE = _fn_re("printSegment")
_ZERO_FORK_BLOCK_RE = re.compile(
    r"^# synth-shell-theme: zero_fork_render\n.*?^_ssp_print_segment_var\(\)\s*\{.*?\n\}",
    re.MULTILINE | re.DOTALL,
)
_V11_SEGS_BLOCK_RE = re.compile(
    r"^# synth-shell-theme: v11_segments\n.*?^_ssp_colors_var\(\)\s*\{.*?\n\}",
    re.MULTILINE | re.DOTALL,
)
_GET_COLORS_RE = _fn_re("get_colors_for_element")
_COMBINE_V11_RE = re.compile(
    r"^(?:_ssp_text_for_el\(\)\s*\{.*?\n\}\n)?_ssp_combine_var\(\)\s*\{.*?\n\}\ncombine_elements\(\)\s*\{.*?\n\}",
    re.MULTILINE | re.DOTALL,
)
_COMBINE_FULL_RE = _fn_re("combine_elements")
_PROMPT_HOOK_RE = _fn_re("prompt_command_hook")
_GET_EFFECT_RE = _fn_re("getEffectCode")
_V11_INIT_AND_PC_RE = re.compile(
    r"^\t# synth-shell-theme: v11_init\n.*?(?:\tPROMPT_COMMAND=prompt_command_hook|\t\tesac\n\tfi)",
    re.MULTILINE | re.DOTALL,
)
_V12_GIT_RE = re.compile(
    r"^[ \t]*# synth-shell-theme: git_single_pass v12[^\n]*\n.*?"
    r"[ \t]*\[\[ -n \"\$_ab_counts\" \]\] && branch=\"\$\{branch\}\$\{_ab_counts\}\"\n[ \t]*fi",
    re.MULTILINE | re.DOTALL,
)
_DEBUG_TRAP_RE = re.compile(
    r"^[ \t]*none=\"\$\(tput sgr0\)\"\n[ \t]*trap 'echo -ne \"\$\{none\}\"' DEBUG\n",
    re.MULTILINE,
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

_V10_GIT_RE = re.compile(
    r"^[ \t]*# synth-shell-theme: git_single_pass\n"
    r"[ \t]*local status_out=\"\$\(git status --porcelain -b 2>/dev/null\)\"\n"
    r"[ \t]*local is_dirty=false\n"
    r"[ \t]*\[\[ \"\$status_out\" =~ \$'\\n' \]\] && is_dirty=true\n"
    r"[ \t]*local branch_line=\"\$\{status_out%%\$'\\n'\*\}\"\n"
    r"[ \t]*local is_ahead=false && \[\[ \"\$branch_line\" == \*\"ahead\"\* \]\] && is_ahead=true\n"
    r"[ \t]*local is_behind=false && \[\[ \"\$branch_line\" == \*\"behind\"\* \]\] && is_behind=true",
    re.MULTILINE,
)

_V11_GIT_RE = re.compile(
    r"^[ \t]*# synth-shell-theme: git_single_pass v11[^\n]*\n.*?"
    r"[ \t]*branch=\"\$\{branch:0:\$\(\(_max_g - 1\)\)\}…\"\n[ \t]*fi",
    re.MULTILINE | re.DOTALL,
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

_GREETER_TEMP_RE = re.compile(r"^printInfoCPUTemp\(\)\s*\{.*?\n\}", re.MULTILINE | re.DOTALL)
_GREETER_RAM_RE = re.compile(r"^printMonitorRAM\(\)\s*\{.*?\n\}", re.MULTILINE | re.DOTALL)


def _backup_script_once(script_path: Path, backup_dir: Path) -> None:
    """Create an initial `.orig.bak` backup of a shell script before first patching."""
    backup_dir.mkdir(parents=True, exist_ok=True)
    orig_bak = backup_dir / f"{script_path.name}.orig.bak"
    if not orig_bak.exists():
        shutil.copy2(script_path, orig_bak)


def _inject_interactive_guard(text: str) -> str:
    """Prepend `interactive_guard` after the shebang line if not already present."""
    if "synth-shell-theme: interactive_guard" in text or "[[ $- != *i* ]] && return" in text:
        return text
    lines = text.splitlines()
    if lines and lines[0].startswith("#!"):
        lines.insert(1, INTERACTIVE_GUARD_LINE)
    else:
        lines.insert(0, INTERACTIVE_GUARD_LINE)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def inspect_patches(config_dir: Path | None = None) -> dict[str, bool]:
    """Check which runtime enhancements (v1.0 + v1.1 + v1.2) are active in `synth-shell`."""
    base = config_dir if config_dir is not None else get_config_dir()
    prompt_sh = get_prompt_script_path(base)
    greeter_sh = get_greeter_script_path(base)
    greeter_found = greeter_sh.is_file()

    greeter_amd_temp = False
    greeter_zfs_arc = False
    if greeter_found:
        g_txt = greeter_sh.read_text(encoding="utf-8", errors="replace")
        greeter_amd_temp = "synth-shell-theme: greeter_amd_temp" in g_txt or not _GREETER_TEMP_RE.search(g_txt)
        greeter_zfs_arc = "synth-shell-theme: greeter_zfs_arc" in g_txt or not _GREETER_RAM_RE.search(g_txt)

    if not prompt_sh.is_file():
        return {
            "prompt_script_found": False,
            "kube_fast": False,
            "kube_namespace_prod": False,
            "git_single_pass": False,
            "git_wsl_fast": False,
            "git_ahead_behind_counts": False,
            "git_advanced_state": False,
            "dual_separator": False,
            "color_256_parity": False,
            "truecolor_24bit": False,
            "zero_fork_render": False,
            "v11_segments": False,
            "v12_segments": False,
            "v13_segments": False,
            "osc133_semantic": False,
            "osc7_cwd": False,
            "v139_smart_features": False,
            "terminal_sanitize": False,
            "right_prompt": False,
            "responsive_width": False,
            "hook_chaining": False,
            "pyenv_enhanced": False,
            "utf8_ps1_guard": False,
            "interactive_guard": False,
            "greeter_script_found": greeter_found,
            "greeter_amd_temp": greeter_amd_temp,
            "greeter_zfs_arc": greeter_zfs_arc,
            "all_applied": False,
        }

    content = prompt_sh.read_text(encoding="utf-8", errors="replace")
    m_kube = _GET_KUBE_RE.search(content)
    kube_body = m_kube.group(0) if m_kube else ""
    kube_fast = bool(kube_body) and ("yq" not in kube_body) and (
        "SSP_MAX_KUBE_CHAR" in kube_body or "current-context:" in kube_body
    )
    kube_namespace_prod = (
        ("kube_fast v139" in kube_body) if bool(kube_body) else True
    )
    git_single_pass = (
        "synth-shell-theme: git_single_pass" in content
        or '[[ -n "$(git status --porcelain)" ]]' not in content
    )
    git_wsl_fast = (
        "synth-shell-theme: git_single_pass v13" in content
        or "synth-shell-theme: git_single_pass v12" in content
        or "synth-shell-theme: git_single_pass v11" in content
        or not (_OLD_GIT_RE.search(content) or _V10_GIT_RE.search(content))
    )
    git_ahead_behind_counts = (
        "synth-shell-theme: git_single_pass v13" in content
        or "synth-shell-theme: git_single_pass v12" in content
        or not (_OLD_GIT_RE.search(content) or _V10_GIT_RE.search(content) or _V11_GIT_RE.search(content))
    )
    git_advanced_state = (
        "synth-shell-theme: git_single_pass v13" in content
        or not (_OLD_GIT_RE.search(content) or _V10_GIT_RE.search(content) or _V11_GIT_RE.search(content) or _V12_GIT_RE.search(content))
    )
    dual_separator = (
        'local sep_char="${6:-${separator_char:-}}"' in content
        or 'local sep_char="${6:-$separator_char}"' in content
    ) and "separator_char_end" in content
    zero_fork_render = "synth-shell-theme: zero_fork_render" in content
    utf8_ps1_guard = "synth-shell-theme: utf8_ps1_guard" in content and "${loc,,}" not in content
    truecolor_24bit = "synth-shell-theme: truecolor_24bit" in content

    has_full_hook = "prompt_command_hook()" in content
    v11_segments = (
        ("synth-shell-theme: v11_segments" in content and "synth-shell-theme: v11_init" in content)
        if has_full_hook
        else True
    )
    v12_segments = (
        ("synth-shell-theme: v12_segments" in content and "synth-shell-theme: v12_init" in content)
        if has_full_hook
        else True
    )
    v13_segments = (
        ("synth-shell-theme: v13_segments" in content and "synth-shell-theme: v13_init" in content)
        if has_full_hook
        else True
    )
    osc133_semantic = (
        ("synth-shell-theme: osc133_semantic" in content and "133;A\\e\\\\" not in content and "133;C\\e\\\\" not in content)
        if has_full_hook
        else True
    )
    osc7_cwd = ("synth-shell-theme: osc7_cwd" in content) if has_full_hook else True
    v139_smart_features = (
        ("synth-shell-theme: v139_smart_features" in content and "synth-shell-theme: v139_init" in content)
        if has_full_hook
        else True
    )
    terminal_sanitize = ("synth-shell-theme: terminal_sanitize" in content) if has_full_hook else True
    right_prompt = ("synth-shell-theme: right_prompt" in content) if has_full_hook else True
    responsive_width = ("synth-shell-theme: responsive_width" in content) if has_full_hook else True
    hook_chaining = (
        ("synth-shell-theme: hook_chaining" in content and "trap 'echo -ne \"${none}\"' DEBUG" not in content)
        if has_full_hook
        else True
    )
    has_pyenv_fn = "getPyenv()" in content
    pyenv_enhanced = ("synth-shell-theme: pyenv_enhanced" in content) if has_pyenv_fn else True

    managed_scripts = [
        base / name
        for name in ("synth-shell-prompt.sh", "alias.sh", "better-ls.sh", "better-history.sh")
        if (base / name).is_file()
    ]
    if greeter_found and greeter_sh not in managed_scripts:
        managed_scripts.append(greeter_sh)

    color_files = [
        base / name
        for name in ("synth-shell-prompt.sh", "alias.sh", "better-ls.sh", "better-history.sh")
        if (base / name).is_file()
    ]
    color_256_parity = bool(color_files) and all(
        "COLORCODE=$(($BITCODE + 30))" not in f.read_text(encoding="utf-8", errors="replace")
        for f in color_files
    )
    interactive_guard = bool(managed_scripts) and all(
        (
            "synth-shell-theme: interactive_guard" in f.read_text(encoding="utf-8", errors="replace")
            or "[[ $- != *i* ]] && return" in f.read_text(encoding="utf-8", errors="replace")
        )
        for f in managed_scripts
    )

    all_ok = (
        kube_fast
        and kube_namespace_prod
        and git_single_pass
        and git_wsl_fast
        and git_ahead_behind_counts
        and git_advanced_state
        and dual_separator
        and color_256_parity
        and truecolor_24bit
        and zero_fork_render
        and v11_segments
        and v12_segments
        and v13_segments
        and osc133_semantic
        and osc7_cwd
        and v139_smart_features
        and terminal_sanitize
        and right_prompt
        and responsive_width
        and hook_chaining
        and pyenv_enhanced
        and utf8_ps1_guard
        and interactive_guard
        and (not greeter_found or (greeter_amd_temp and greeter_zfs_arc))
    )

    return {
        "prompt_script_found": True,
        "kube_fast": kube_fast,
        "kube_namespace_prod": kube_namespace_prod,
        "git_single_pass": git_single_pass,
        "git_wsl_fast": git_wsl_fast,
        "git_ahead_behind_counts": git_ahead_behind_counts,
        "git_advanced_state": git_advanced_state,
        "dual_separator": dual_separator,
        "color_256_parity": color_256_parity,
        "truecolor_24bit": truecolor_24bit,
        "zero_fork_render": zero_fork_render,
        "v11_segments": v11_segments,
        "v12_segments": v12_segments,
        "v13_segments": v13_segments,
        "osc133_semantic": osc133_semantic,
        "osc7_cwd": osc7_cwd,
        "v139_smart_features": v139_smart_features,
        "terminal_sanitize": terminal_sanitize,
        "right_prompt": right_prompt,
        "responsive_width": responsive_width,
        "hook_chaining": hook_chaining,
        "pyenv_enhanced": pyenv_enhanced,
        "utf8_ps1_guard": utf8_ps1_guard,
        "interactive_guard": interactive_guard,
        "greeter_script_found": greeter_found,
        "greeter_amd_temp": greeter_amd_temp,
        "greeter_zfs_arc": greeter_zfs_arc,
        "all_applied": all_ok,
    }


def apply_runtime_patches(
    config_dir: Path | None = None,
    tune_defaults: bool = False,
) -> dict[str, object]:
    """Idempotently apply all v1.0 + v1.1 + v1.2 runtime, speed, TrueColor, hook-chaining & safety patches."""
    base = config_dir if config_dir is not None else get_config_dir()
    prompt_sh = get_prompt_script_path(base)
    greeter_sh = get_greeter_script_path(base)
    bdir = get_backup_dir(base)
    changes: list[str] = []

    if prompt_sh.is_file():
        original = prompt_sh.read_text(encoding="utf-8", errors="replace")
        updated = original

        # 1. Fast zero-subshell kube context + namespace + prod warning reader (v139)
        m_kube = _GET_KUBE_RE.search(updated)
        if m_kube and ("kube_fast v139" not in m_kube.group(0)):
            updated = _GET_KUBE_RE.sub(lambda _: FAST_GET_KUBE, updated, count=1)
            changes.append("kube_fast")
            changes.append("kube_namespace_prod")

        # 2. Single-pass git status + WSL2 fast-untracked + timeout + async + counts + rebase/merge/worktree
        if _OLD_GIT_RE.search(updated):
            updated = _OLD_GIT_RE.sub(lambda _: SINGLE_PASS_GIT_V13, updated, count=1)
            changes.append("git_single_pass")
            changes.append("git_ahead_behind_counts")
            changes.append("git_advanced_state")
        elif _V10_GIT_RE.search(updated):
            updated = _V10_GIT_RE.sub(lambda _: SINGLE_PASS_GIT_V13, updated, count=1)
            changes.append("git_wsl_fast")
            changes.append("git_ahead_behind_counts")
            changes.append("git_advanced_state")
        elif _V11_GIT_RE.search(updated):
            updated = _V11_GIT_RE.sub(lambda _: SINGLE_PASS_GIT_V13, updated, count=1)
            changes.append("git_ahead_behind_counts")
            changes.append("git_advanced_state")
        elif _V12_GIT_RE.search(updated):
            updated = _V12_GIT_RE.sub(lambda _: SINGLE_PASS_GIT_V13, updated, count=1)
            changes.append("git_advanced_state")

        # 3. Zero-fork segment renderer + UTF-8 PS1 escape guard + TrueColor 24-bit (#RRGGBB)
        if "synth-shell-theme: truecolor_24bit" not in updated or "${loc,,}" in updated:
            if _ZERO_FORK_BLOCK_RE.search(updated):
                updated = _ZERO_FORK_BLOCK_RE.sub(lambda _: ZERO_FORK_V12_HELPERS, updated, count=1)
                if _PRINT_SEG_FULL_RE.search(updated):
                    updated = _PRINT_SEG_FULL_RE.sub(lambda _: PATCHED_PRINT_SEGMENT, updated, count=1)
                changes.append("truecolor_24bit")
            elif _PRINT_SEG_FULL_RE.search(updated):
                updated = _PRINT_SEG_FULL_RE.sub(
                    lambda _: f"{ZERO_FORK_V12_HELPERS}\n{PATCHED_PRINT_SEGMENT}",
                    updated,
                    count=1,
                )
                changes.append("zero_fork_render")
                changes.append("utf8_ps1_guard")
                changes.append("truecolor_24bit")

        # Ensure `dual_separator` is wired in `combine_elements` even on minimal scripts
        if "separator_char_end" not in updated:
            step_comb = _COMBINE_TAIL_RE.sub(
                (
                    r"\1"
                    '\tlocal sep_char="$separator_char"\n'
                    '\tif [ "$second" = "INPUT" ] && [ -n "${separator_char_end:-}" ]; then\n'
                    '\t\tsep_char="$separator_char_end"\n'
                    "\tfi\n"
                    '\tprintSegment "$text" "$text_color" "$bg_color" "$next_bg_color" "$text_effect" "$sep_char"'
                    r"\2"
                ),
                updated,
                count=1,
            )
            if step_comb != updated:
                updated = step_comb
                changes.append("dual_separator")

        # 4. Enhanced pure-Bash getPyenv (`VIRTUAL_ENV_PROMPT`, `pyvenv.cfg`, Conda, `max_pyenv_char`)
        m_py = _GET_PYENV_RE.search(updated)
        if m_py and "synth-shell-theme: pyenv_enhanced" not in m_py.group(0):
            updated = _GET_PYENV_RE.sub(lambda _: ENHANCED_GET_PYENV, updated, count=1)
            changes.append("pyenv_enhanced")

        # 5. Italic & regular text effect support in `getEffectCode()`
        m_eff = _GET_EFFECT_RE.search(updated)
        if m_eff and "italic)" not in m_eff.group(0):
            eff_patched = m_eff.group(0).replace(
                "\tdim)\n\t\techo 2\n\t\t;;",
                "\tdim)\n\t\techo 2\n\t\t;;\n\titalic)\n\t\techo 3\n\t\t;;\n\tregular)\n\t\techo 0\n\t\t;;",
            )
            if eff_patched != m_eff.group(0):
                updated = updated[: m_eff.start()] + eff_patched + updated[m_eff.end() :]
                changes.append("font_effects")

        # 6. Phase 2, 3, v1.2 & v1.3 segments + RPROMPT + OSC 133 + safe PROMPT_COMMAND chaining
        if "prompt_command_hook()" in updated and (
            "synth-shell-theme: v13_segments" not in updated
            or "synth-shell-theme: v13_init" not in updated
            or "synth-shell-theme: v139_smart_features" not in updated
            or "synth-shell-theme: v139_init" not in updated
            or "synth-shell-theme: osc133_semantic" not in updated
            or "synth-shell-theme: osc7_cwd" not in updated
            or "synth-shell-theme: terminal_sanitize" not in updated
            or "synth-shell-theme: right_prompt" not in updated
            or "133;A\\e\\\\" in updated
            or "133;C\\e\\\\" in updated
            or "${os_id,,}" in updated
            or "_ssp_had_u" not in updated
        ):
            had_dual = "separator_char_end" in updated
            if _V11_SEGS_BLOCK_RE.search(updated):
                updated = _V11_SEGS_BLOCK_RE.sub(
                    lambda _: f"{V12_SEGMENTS_BLOCK}\n{V12_COLORS_FOR_ELEMENT}",
                    updated,
                    count=1,
                )
            elif _GET_COLORS_RE.search(updated):
                updated = _GET_COLORS_RE.sub(
                    lambda _: f"{V12_SEGMENTS_BLOCK}\n{V12_COLORS_FOR_ELEMENT}",
                    updated,
                    count=1,
                )

            if _COMBINE_V11_RE.search(updated):
                updated = _COMBINE_V11_RE.sub(lambda _: V12_COMBINE_ELEMENTS, updated, count=1)
            elif _COMBINE_FULL_RE.search(updated):
                updated = _COMBINE_FULL_RE.sub(lambda _: V12_COMBINE_ELEMENTS, updated, count=1)

            if _PROMPT_HOOK_RE.search(updated):
                updated = _PROMPT_HOOK_RE.sub(lambda _: V12_PROMPT_COMMAND_HOOK, updated, count=1)

            # Remove destructive DEBUG trap (replaced by PS0 reset)
            updated = _DEBUG_TRAP_RE.sub("", updated, count=1)

            if "synth-shell-theme: v139_init" not in updated or "133;C\\e\\\\" in updated or "SSP_TERMINAL_SANITIZE" not in updated:
                if _V11_INIT_AND_PC_RE.search(updated):
                    updated = _V11_INIT_AND_PC_RE.sub(lambda _: V12_INIT_AND_CHAINING, updated, count=1)
                elif "\tPROMPT_COMMAND=prompt_command_hook" in updated:
                    updated = updated.replace("\tPROMPT_COMMAND=prompt_command_hook", V12_INIT_AND_CHAINING, 1)

            changes.append("v13_segments")
            changes.append("v139_smart_features")
            changes.append("osc133_semantic")
            changes.append("osc7_cwd")
            changes.append("terminal_sanitize")
            changes.append("right_prompt")
            if "hook_chaining" not in changes:
                changes.append("hook_chaining")
            if not had_dual and "dual_separator" not in changes:
                changes.append("dual_separator")

        if updated != original:
            _backup_script_once(prompt_sh, bdir)
            prompt_sh.write_text(updated, encoding="utf-8", newline="\n")

    # 7. 256-color + TrueColor parity & non-interactive shell guard across all synth-shell scripts
    script_names = ["synth-shell-prompt.sh", "alias.sh", "better-ls.sh", "better-history.sh"]
    if greeter_sh.is_file() and greeter_sh.name not in script_names:
        script_names.append(greeter_sh.name)

    for script_name in script_names:
        script_file = base / script_name
        if not script_file.is_file():
            continue
        txt = script_file.read_text(encoding="utf-8", errors="replace")
        new_txt = txt
        needs_color_upgrade = (
            "COLORCODE=$(($BITCODE + 30))" in new_txt
            or ("synth-shell-theme: color_256_parity" in new_txt and "truecolor_24bit" not in new_txt)
        )
        if needs_color_upgrade and _COLOR_BLOCK_RE.search(new_txt):
            replaced = _COLOR_BLOCK_RE.sub(lambda _: PATCHED_COLOR_CODES, new_txt, count=1)
            if replaced != new_txt:
                new_txt = replaced
                changes.append(f"color_256_parity:{script_name}")

        guarded = _inject_interactive_guard(new_txt)
        if guarded != new_txt:
            new_txt = guarded
            changes.append(f"interactive_guard:{script_name}")

        if new_txt != txt:
            _backup_script_once(script_file, bdir)
            script_file.write_text(new_txt, encoding="utf-8", newline="\n")

    # 8. Optional Greeter runtime fixes (AMD k10temp/Tctl CPU temp + ZFS ARC memory accounting)
    if greeter_sh.is_file():
        g_orig = greeter_sh.read_text(encoding="utf-8", errors="replace")
        g_new = g_orig
        m_gt = _GREETER_TEMP_RE.search(g_new)
        if m_gt and "synth-shell-theme: greeter_amd_temp" not in m_gt.group(0):
            g_new = _GREETER_TEMP_RE.sub(lambda _: PATCHED_GREETER_AMD_TEMP, g_new, count=1)
            changes.append("greeter_amd_temp")
        m_gr = _GREETER_RAM_RE.search(g_new)
        if m_gr and "synth-shell-theme: greeter_zfs_arc" not in m_gr.group(0):
            g_new = _GREETER_RAM_RE.sub(lambda _: PATCHED_GREETER_ZFS_RAM, g_new, count=1)
            changes.append("greeter_zfs_arc")
        if g_new != g_orig:
            _backup_script_once(greeter_sh, bdir)
            greeter_sh.write_text(g_new, encoding="utf-8", newline="\n")

    # Optional sensible prompt config defaults (`init` without `--no-tune`)
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
