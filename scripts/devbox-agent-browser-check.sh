#!/usr/bin/env bash
set -euo pipefail

readonly expected_version="0.32.4"
readonly dashboard_port="4848"
pass=0
fail=0

check() {
  local label="$1"
  shift
  if "$@"; then
    printf 'PASS: %s\n' "$label"
    pass=$((pass + 1))
  else
    printf 'FAIL: %s\n' "$label" >&2
    fail=$((fail + 1))
  fi
}

check_version() {
  [[ "$(/usr/bin/agent-browser --version)" == "agent-browser $expected_version" ]]
}

check_doctor() {
  /usr/local/bin/agent-browser doctor --json | jq -e \
    '.success == true and ([.checks[] | select(.status == "fail")] | length) == 0' \
    >/dev/null
}

check_apparmor_loaded() {
  sudo aa-status --json | jq -e \
    '.profiles["agent-browser-chrome"] == "unconfined"' >/dev/null
}

chrome_pids() {
  local proc exe
  for proc in /proc/[0-9]*; do
    exe="$(readlink "$proc/exe" 2>/dev/null || true)"
    if [[ "$exe" == "$HOME"/.agent-browser/browsers/chrome-*/chrome ]]; then
      printf '%s\n' "${proc##*/}"
    fi
  done
}

check_chrome_sandbox() (
  local session pid cmdline renderer_count=0
  session="ab-sandbox-$(printf '%s' "$(git rev-parse --show-toplevel)" | sha256sum | cut -c1-12)"
  trap '/usr/local/bin/agent-browser --session "$session" close >/dev/null 2>&1 || true' EXIT
  /usr/local/bin/agent-browser --session "$session" \
    --allowed-domains example.com open https://example.com >/dev/null

  while IFS= read -r pid; do
    cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline")"
    [[ "$cmdline" != *"--no-sandbox"* ]] || return 1
    if [[ "$cmdline" == *"--type=renderer"* ]]; then
      grep -Eq '^Seccomp:[[:space:]]+2$' "/proc/$pid/status" || return 1
      renderer_count=$((renderer_count + 1))
    fi
  done < <(chrome_pids)
  [[ "$renderer_count" -gt 0 ]]
)

skill_front_matter_is_valid() {
  local skill_link="$1" skill_file front_matter
  [[ -L "$skill_link" ]] || return 1
  skill_file="$(readlink -f "$skill_link")/SKILL.md"
  [[ -f "$skill_file" ]] || return 1
  front_matter="$(awk 'NR == 1 && $0 == "---" { inside=1; next } inside && $0 == "---" { exit } inside { print }' "$skill_file")"
  [[ -n "$front_matter" ]] || return 1
  printf '%s\n' "$front_matter" | yq eval -e \
    '.name == "agent-browser" and (.description | type == "!!str")' - >/dev/null
}

check_skills() {
  /usr/local/bin/agent-browser skills get core >/dev/null
  skill_front_matter_is_valid "$HOME/.claude/skills/agent-browser"
  skill_front_matter_is_valid "$HOME/.codex/skills/agent-browser"
}

check_claude_mcp() {
  local current status
  current="$(jq -c '.mcpServers["agent-browser"] // null' "$HOME/.claude.json")"
  jq -e \
    '.type == "stdio"
     and .command == "/usr/local/bin/agent-browser"
     and .args == ["mcp", "--tools", "core"]' \
    <<<"$current" >/dev/null || return 1
  status="$(claude mcp get agent-browser)"
  grep -Fq 'Scope: User config' <<<"$status"
  grep -Fq 'Status: ✔ Connected' <<<"$status"
}

check_codex_mcp() {
  codex mcp get agent-browser --json | jq -e \
    '.enabled == true
     and .transport.type == "stdio"
     and .transport.command == "/usr/local/bin/agent-browser"
     and .transport.args == ["mcp", "--tools", "core"]
     and .transport.env == null
     and .transport.env_vars == []
     and .transport.cwd == null' >/dev/null
}

check_session_lifecycle() (
  local root session cache_dir
  root="$(git rev-parse --show-toplevel)"
  session="ab-check-$(printf '%s' "$root" | sha256sum | cut -c1-12)"
  cache_dir="$root/.cache/agent-browser-check"
  mkdir -p "$cache_dir"
  trap '/usr/local/bin/agent-browser --session "$session" close >/dev/null 2>&1 || true' EXIT

  /usr/local/bin/agent-browser --session "$session" \
    --allowed-domains example.com open https://example.com >/dev/null
  /usr/local/bin/agent-browser --session "$session" snapshot \
    >"$cache_dir/snapshot.txt"
  /usr/local/bin/agent-browser --session "$session" screenshot \
    "$cache_dir/screenshot.png" >/dev/null
  [[ -s "$cache_dir/snapshot.txt" && -s "$cache_dir/screenshot.png" ]]
)

check_dashboard_loopback() (
  trap '/usr/local/bin/agent-browser dashboard stop >/dev/null 2>&1 || true' EXIT
  /usr/local/bin/agent-browser dashboard stop >/dev/null 2>&1 || true
  /usr/local/bin/agent-browser dashboard start --port "$dashboard_port" >/dev/null
  ss -ltn "sport = :$dashboard_port" | grep -q "127.0.0.1:$dashboard_port"
  if ss -ltn "sport = :$dashboard_port" | grep -Eq "(0\.0\.0\.0|\[::\]):$dashboard_port"; then
    return 1
  fi
  curl --fail --silent --show-error "http://127.0.0.1:$dashboard_port" >/dev/null
)

printf '%s\n' 'agent-browser integration check'
check "exact version $expected_version" check_version
check 'doctor reports no failures' check_doctor
check 'AppArmor profile is loaded' check_apparmor_loaded
check 'Chrome sandbox and renderer seccomp are enabled' check_chrome_sandbox
check 'core skill and both skill links are valid' check_skills
check 'MCP initialization and paginated tool listing' \
  python3 "$(dirname "$0")/devbox-agent-browser-mcp-check.py"
check 'Claude user MCP registration is exact and connected' check_claude_mcp
check 'Codex MCP registration is exact' check_codex_mcp
check 'worktree-scoped browser session writes artifacts and closes' \
  check_session_lifecycle
check 'dashboard is loopback-only and answers HTTP' check_dashboard_loopback

printf 'agent-browser check: %d passed, %d failed\n' "$pass" "$fail"
[[ "$fail" -eq 0 ]]
