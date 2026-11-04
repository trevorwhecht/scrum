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
refuse_real "$dest/skills/trevskills-scrum"
refuse_real "$dest/skills/trevskills-e2e"
refuse_real "$codex/AGENTS.md"
mkdir -p "$dest/skills" "$dest/agents" "$codex"
link "$here/skills/trevskills-scrum" "$dest/skills/trevskills-scrum"
link "$here/skills/trevskills-e2e" "$dest/skills/trevskills-e2e"
for f in "$here"/agents/*.md; do link "$f" "$dest/agents/$(basename "$f")"; done
link "$here/codex/AGENTS.md" "$codex/AGENTS.md"
# jev-rank.py: a real file there predates this repo's copy, so keep it and carry on rather than refuse.
mkdir -p "$dest/scripts"
jev_rank="$dest/scripts/jev-rank.py"
if [ -e "$jev_rank" ] && [ ! -L "$jev_rank" ]; then
  echo "kept real file $jev_rank; jev-rank.py not linked"
else
  link "$here/skills/trevskills-scrum/jev-rank.py" "$jev_rank"
fi
# Register board.py as the status line (it feeds usage.json to `ready`'s pacing), only when none is set, and its
# git-guard PreToolUse hook (refuses a chat's git commit on main in a scrum repo), only when no git-guard hook exists.
python3 - "$dest" <<'PY'
import json, os, shlex, sys
dest = sys.argv[1]
path = os.path.join(dest, "settings.json")
board = "python3 " + shlex.quote(f"{dest}/skills/trevskills-scrum/board.py")
try:
    with open(path) as f:
        settings = json.load(f)
except FileNotFoundError:
    settings = {}
except (OSError, ValueError) as e:
    settings = None
    print(f"warning: {path} is not readable JSON ({e}); statusLine and git-guard hook not set, add them by hand", file=sys.stderr)
if settings is not None and not isinstance(settings, dict):
    settings = None
    print(f"warning: {path} is not a JSON object; statusLine and git-guard hook not set, add them by hand", file=sys.stderr)
changed = []
if settings is not None and "statusLine" not in settings:
    settings["statusLine"] = {"type": "command", "refreshInterval": 60, "command": f"{board} statusline"}
    changed.append("statusLine")
if settings is not None:
    hooks = settings.setdefault("hooks", {})
    pre = hooks.setdefault("PreToolUse", []) if isinstance(hooks, dict) else None
    if not isinstance(pre, list):
        print(f"warning: {path} hooks.PreToolUse is not a list; git-guard hook not set, add it by hand", file=sys.stderr)
    elif "git-guard" not in json.dumps(pre):
        pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": f"{board} git-guard", "timeout": 5}]})
        changed.append("git-guard PreToolUse hook")
if changed:
    with open(path + ".tmp", "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(path + ".tmp", path)
    print(f"set {' and '.join(changed)} in {path}")
PY
echo "Done. In any repo: /trevskills-scrum <feature>"
