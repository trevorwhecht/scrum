#!/usr/bin/env python3
"""One Jev decision for the pipeline. Never fails the caller: any error prints the step's fallback.

usage: jev-gate.py <step> <job-dir>   (steps: model promote dupe approver reviewer-security reviewer-ui)
stdout is one line, the decision. Every run appends to <job-dir>/jev.log:
timestamp, step, question, raw answer, decision, elapsed seconds (tab-separated).
"""
import json, os, re, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.realpath(__file__)))  # works through the skill symlink
import board, jev  # noqa: E402

# step -> (question, cutoff, fallback)
STEPS = {
    "model": ("How hard is this feature to implement", 1.5, "opus"),  # score index 0-3 = difficulty 1-4
    "promote": (None, None, "opus"),
    "dupe": ("Item {i} is the same task as the query", 0.8, "add"),
    "approver": ("This diff changes payment, pricing, billing, authentication, session, role or permission logic",
                 0.3, "opus"),
    "reviewer-security": ("This diff needs a security review", 0.7, "skip"),
    "reviewer-ui": ("This diff needs a UI review", 0.7, "skip"),
}
LEVELS = ["trivial edit", "small contained change", "multi-file change with new logic", "cross-cutting or risky change"]
USAGE = f"usage: jev-gate.py <{'|'.join(STEPS)}> <job-dir>"


def decide(step, job, asked):
    """(question, raw answer, decision); question and raw are '-' when no Jev call was made.
    asked gets the question appended just before each Jev call, so main() can tell if one started."""
    q, cut, _ = STEPS[step]
    if step == "model":
        f = job / "feature.md"
        text = f.read_text() if f.exists() else ""
        if not text.strip():
            return "-", "-", "opus"
        asked.append(q)
        v, raw = jev.score(text, q, LEVELS)
        return q, raw, "sonnet" if v < cut else "opus"
    stdin = sys.stdin.read().strip()
    if step == "promote":
        return "-", stdin or "-", "opus"
    if step == "dupe":
        items = [i["text"] for i in board.read_backlog(job.parent.parent)[1] if not i["done"]]
        if not items or not stdin:
            return "-", "-", "add"
        asked.append(q)
        scores = jev.rank(stdin, items, q)
        top = max(range(len(items)), key=scores.__getitem__)
        return q, scores, f"dupe {items[top]}" if scores[top] >= cut else "add"
    asked.append(q)
    v, raw = jev.noul(stdin, q)
    if step == "approver":
        return q, raw, "sonnet" if v < cut else "opus"
    return q, raw, "add" if v >= cut else "skip"


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2 or argv[0] not in STEPS:
        print(USAGE, file=sys.stderr)
        return 2
    step, job = argv[0], Path(argv[1])
    start = time.monotonic()
    asked = []
    try:
        q, raw, decision = decide(step, job, asked)
        raw = raw if isinstance(raw, str) else json.dumps(raw, separators=(",", ":"))
    except Exception as e:  # the gate never fails the caller
        q, raw, decision = asked[0] if asked else "-", type(e).__name__, STEPS[step][2]
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    safe = lambda s: re.sub(r"[\t\r\n]", " ", s.replace(key, "***") if key else s)
    decision = safe(decision)
    fields = [datetime.now().isoformat(timespec="seconds"), step, q, raw, decision, f"{time.monotonic() - start:.2f}"]
    try:
        with open(job / "jev.log", "a") as log:
            log.write("\t".join(safe(f) for f in fields) + "\n")
    except OSError:
        pass  # a missing job dir must not cost the caller its decision
    print(decision)
    return 0


if __name__ == "__main__":
    sys.exit(main())
