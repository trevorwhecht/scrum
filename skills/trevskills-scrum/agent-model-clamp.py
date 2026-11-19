#!/usr/bin/env python3
"""PreToolUse hook (Agent|Task), wired into every headless scrum run by board.spawn's --settings JSON (NO_CACHE_TAX).

Job 1240: a scrum agent whose frontmatter pins `model: sonnet` or `model: haiku` (read from ~/.claude/agents, which
install.sh links to this repo's agents/) keeps that model when the orchestrator passes a pricier `model` override
(opus, fable, or a full id of a pricier family): the hook rewrites `model` to the frontmatter value. Every other call,
and any error, exits 0 with no output, so the hook never blocks a run. Builder, spec-writer, planner and approver pin
opus on purpose and are never touched."""
import json, re, sys
from pathlib import Path

RANK = {"haiku": 0, "sonnet": 1}  # any other model (opus, fable, inherit, an unknown id) ranks 2: pricier than both


def clamp(event):
    """The hook output for one PreToolUse event, or None to leave the call alone."""
    tool_input = event["tool_input"]
    kind, model = tool_input.get("subagent_type"), tool_input.get("model")
    if event.get("tool_name") not in ("Agent", "Task") or not isinstance(model, str) or not model \
            or not isinstance(kind, str) or not re.fullmatch(r"scrum-[a-z0-9-]+", kind):
        return None
    text = (Path.home() / ".claude" / "agents" / f"{kind}.md").read_text()
    pin = re.search(r"^model:\s*(\S+)\s*$", text.split("---", 2)[1], re.M) if text.startswith("---") else None
    pin = pin.group(1) if pin else None
    asked = next((r for family, r in RANK.items() if family in model.lower()), 2)
    if pin not in RANK or asked <= RANK[pin]:
        return None
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                   "updatedInput": {**tool_input, "model": pin}}}


def main():
    try:
        out = clamp(json.loads(sys.stdin.read()))
    except Exception:  # bad JSON, a missing agent file, an odd shape: fail open, never block a run
        return 0
    if out:
        print(json.dumps(out))
    return 0


if __name__ == "__main__":
    sys.exit(main())
