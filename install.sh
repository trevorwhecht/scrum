#!/usr/bin/env bash
# Links the scrum into ~/.claude (and its review rules into ~/.codex) so /trevskills-scrum works in every repo. Safe to re-run; edits here go live instantly.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${CLAUDE_HOME:-$HOME/.claude}"
codex="${CODEX_HOME:-$HOME/.codex}"

refuse_real() {
  if [ -e "$1" ] && [ ! -L "$1" ]; then echo "refusing to replace real file: $1" >&2; exit 1; fi
}

link() {
  refuse_real "$2"
  ln -sfn "$1" "$2"
  echo "linked $2"
}

# Check everything first so a refusal leaves nothing half-installed.
for f in "$here"/agents/*.md; do refuse_real "$dest/agents/$(basename "$f")"; done
refuse_real "$codex/AGENTS.md"
mkdir -p "$dest/skills" "$dest/agents" "$codex"
link "$here/skills/trevskills-scrum" "$dest/skills/trevskills-scrum"
for f in "$here"/agents/*.md; do link "$f" "$dest/agents/$(basename "$f")"; done
link "$here/codex/AGENTS.md" "$codex/AGENTS.md"
echo "Done. In any repo: /trevskills-scrum <feature>"
