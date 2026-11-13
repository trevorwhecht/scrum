#!/usr/bin/env bash
# Links the scrum into ~/.claude (and its review rules into ~/.codex) so /trevskills-scrum works in every repo. Safe to re-run; edits here go live instantly.
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
dest="${CLAUDE_HOME:-$HOME/.claude}"
codex="${CODEX_HOME:-$HOME/.codex}"

# A linked worktree is throwaway: linking from it would repoint the live ~/.claude symlinks at it. CLAUDE_HOME set is a sandbox.
if [ -z "${CLAUDE_HOME:-}" ] && [ "$(git -C "$here" rev-parse --git-dir 2>/dev/null)" != "$(git -C "$here" rev-parse --git-common-dir 2>/dev/null)" ]; then
  echo "refusing to install from a git worktree ($here); run it from the main checkout" >&2
  exit 1
fi

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
# The git-guard hook is a Go binary (job 812). No go, or a failed build: say so and carry on; the hook's `|| true`
# makes a missing binary a silent pass.
if command -v go >/dev/null 2>&1; then
  (cd "$here/skills/trevskills-scrum/gitguard" && go build -o "$here/skills/trevskills-scrum/gitguard/gitguard") \
    || echo "warning: go build failed; git-guard binary not built" >&2
else
  echo "go not found; git-guard binary not built (install Go and re-run ./install.sh)"
fi
# Register board.py as the status line (it feeds usage.json to `ready`'s pacing), only when none is set, and the
# git-guard PreToolUse hook (refuses a chat's git commit on main in a scrum repo), only when no git-guard hook exists.
# An old `board.py git-guard` hook entry is rewritten in place to the Go binary.
python3 - "$dest" <<'PY'
import json, os, shlex, sys
dest = sys.argv[1]
path = os.path.join(dest, "settings.json")
board = "python3 " + shlex.quote(f"{dest}/skills/trevskills-scrum/board.py")
guard = shlex.quote(f"{dest}/skills/trevskills-scrum/gitguard/gitguard") + " || true"
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
    else:
        for entry in pre:
            for hook in (entry.get("hooks") if isinstance(entry, dict) else None) or []:
                cmd = hook.get("command") if isinstance(hook, dict) else None
                if isinstance(cmd, str) and "board.py" in cmd and "git-guard" in cmd:
                    hook["command"] = guard
                    changed.append("Go git-guard hook (was board.py git-guard)")
        if "git-guard" not in json.dumps(pre) and "gitguard" not in json.dumps(pre):
            pre.append({"matcher": "Bash", "hooks": [{"type": "command", "command": guard, "timeout": 5}]})
            changed.append("git-guard PreToolUse hook")
if changed:
    with open(path + ".tmp", "w") as f:
        json.dump(settings, f, indent=2)
        f.write("\n")
    os.replace(path + ".tmp", path)
    print(f"set {' and '.join(changed)} in {path}")
PY
echo "Done. In any repo: /trevskills-scrum <feature>"
