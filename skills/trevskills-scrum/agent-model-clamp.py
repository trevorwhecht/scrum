#!/usr/bin/env python3
"""PreToolUse hook (Agent|Task), wired into every headless scrum run by board.spawn's --settings JSON (NO_CACHE_TAX).

Job 1240: a scrum agent whose frontmatter pins `model: sonnet` or `model: haiku` (read from ~/.claude/agents, which
install.sh links to this repo's agents/) keeps that model when the orchestrator passes a pricier `model` override
(opus, fable, or a full id of a pricier family): the hook rewrites `model` to the frontmatter value. Every other call,
and any error, exits 0 with no output, so the hook never blocks a run. Builder, spec-writer, planner and approver pin
opus on purpose and are never touched.

Job 1438: a `scrum-builder` call with no `model` (the orchestrator skipped New job step 3's builder Model decision, so
the builder ran on Opus) gets `model: sonnet` when the JOB_DIR named in its prompt says so: jev.log's last `model` line
decides sonnet, or, with no such line, feature.md's (else spec.md's) `Complex:` header is `no` (board.header_value, no
Jev call). That second case appends a `model` line to jev.log. Any error leaves the call alone."""
import datetime, json, os, re, sys
from pathlib import Path

RANK = {"haiku": 0, "sonnet": 1}  # any other model (opus, fable, inherit, an unknown id) ranks 2: pricier than both


def builder_model(tool_input):
    """The updatedInput for a model-less scrum-builder call whose job says sonnet, else None."""
    m = re.search(r"JOB_DIR\s*[=:]\s*[`'\"]?(/[^\s`'\"),;]+)", tool_input.get("prompt") or "")
    job = Path(m.group(1)) if m else None
    if job is None or not job.is_dir():
        return None
    log = job / "jev.log"
    last = None
    if log.is_file():
        for line in log.read_text(errors="replace").splitlines():
            f = line.split("\t")
            if len(f) >= 5 and f[1] == "model":
                last = f[4].strip()
    if last is None:
        sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))
        import board
        if (board.header_value(job / "feature.md", "Complex", ("yes", "no"))
                or board.header_value(job / "spec.md", "Complex", ("yes", "no"))) != "no":
            return None
        with open(log, "a") as out:
            out.write("\t".join((datetime.datetime.now().isoformat(timespec="seconds"), "model", "-",
                                 "Complex: no (agent-model-clamp)", "sonnet", "0.00")) + "\n")
        last = "sonnet"
    return {**tool_input, "model": "sonnet"} if last == "sonnet" else None


def clamp(event):
    """The hook output for one PreToolUse event, or None to leave the call alone."""
    tool_input = event["tool_input"]
    kind, model = tool_input.get("subagent_type"), tool_input.get("model")
    if event.get("tool_name") in ("Agent", "Task") and kind == "scrum-builder" and not model:
        new = builder_model(tool_input)
        return new and {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "allow",
                                               "updatedInput": new}}
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
