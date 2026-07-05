#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
dest="${1:-$repo_root/.backups/personal-config}"

log() {
  printf 'personal-config-backup: %s\n' "$*"
}

backup() {
  local src="$1"
  local rel="$2"
  shift 2
  if [[ -e "$src" ]]; then
    mkdir -p "$dest/$(dirname "$rel")"
    rsync -a --delete "$@" "$src" "$dest/$rel"
  else
    log "skip (missing): $src"
  fi
}

log "backing up to $dest"

backup "$HOME/.claude/CLAUDE.md" ".claude/CLAUDE.md"
backup "$HOME/.claude/settings.json" ".claude/settings.json"
backup "$HOME/.claude/hooks/" ".claude/hooks/"
backup "$HOME/.claude/engines/" ".claude/engines/"
backup "$HOME/.claude/scripts/" ".claude/scripts/" --exclude '__pycache__/'
backup "$HOME/.claude/commands/" ".claude/commands/"
backup "$HOME/.claude/skills/" ".claude/skills/" --exclude '.git/'
backup "$HOME/.codex/config.toml" ".codex/config.toml"
backup "$HOME/.codex/AGENTS.md" ".codex/AGENTS.md"
backup "$HOME/.codex/prompts/" ".codex/prompts/"
backup "$HOME/code/claude-auto/" "code/claude-auto/" --exclude '__pycache__/'
backup "$HOME/.config/fish/functions/claude-auto.fish" ".config/fish/functions/claude-auto.fish"
backup "$HOME/.config/fish/functions/cla.fish" ".config/fish/functions/cla.fish"

log "done"
