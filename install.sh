#!/usr/bin/env bash
# Links the scrum into ~/.claude so /trevskills-scrum works in every repo. Safe to re-run; edits here go live instantly.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${CLAUDE_HOME:-$HOME/.claude}"
mkdir -p "$dest/skills" "$dest/agents"

link() {
  if [ -e "$2" ] && [ ! -L "$2" ]; then echo "refusing to replace real file: $2" >&2; exit 1; fi
  ln -sfn "$1" "$2"
  echo "linked $2"
}

# Check everything first so a refusal leaves nothing half-installed.
for f in "$here"/agents/*.md; do
  t="$dest/agents/$(basename "$f")"
  if [ -e "$t" ] && [ ! -L "$t" ]; then echo "refusing to replace real file: $t" >&2; exit 1; fi
done
link "$here/skills/trevskills-scrum" "$dest/skills/trevskills-scrum"
for f in "$here"/agents/*.md; do link "$f" "$dest/agents/$(basename "$f")"; done
echo "Done. In any repo: /trevskills-scrum <feature>"
