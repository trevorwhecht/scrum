#!/usr/bin/env python3
"""One Jev decision for the pipeline. Never fails the caller: any error prints the step's fallback.

usage: jev-gate.py <step> <job-dir>   (steps: model promote dupe approver reviewer-security reviewer-ui rank)
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
    "rank": ("How important is this ticket to the project", None, "none"),  # prints p<1-5> <kind>
}
LEVELS = ["trivial edit", "small contained change", "multi-file change with new logic", "cross-cutting or risky change"]
IMPORTANCE = ["Trivial (cosmetic or pedantic, nobody would notice if never done)",
              "Minor (small polish or tidy-up with little real effect)",
              "Moderate (a real improvement users or the developer would notice)",
              "High (fixes a real bug, risk, or meaningful gap)",
              "Critical (security, data loss, money, or broken core flow)"]
NECESSITY = ["Unnecessary (speculative, already covered, or reviewer nitpick)", "Optional (nice to have, safe to drop)",
             "Should do eventually (real but can wait indefinitely)", "Needed (will cause problems if not done)"]
PROGRESS = ("Doing this ticket moves the project meaningfully closer to completing its stated goal / current roadmap, "
            "rather than being side work")
KINDS = ["bug", "security", "feature", "ui-polish", "ux-a11y", "refactor-dedupe", "dead-code-lint", "tests", "docs-rules",
         "ops-manual"]
SIDE_KINDS = ("ui-polish", "ux-a11y", "dead-code-lint")  # one rank lower when they do little for the goal
USAGE = f"usage: jev-gate.py <{'|'.join(STEPS)}> <job-dir>"


def project_goal(root):
    """roadmap.md's first non-empty `Goal:` line, else project.md's `- Notes:` line; '' when neither has one."""
    for name, pattern in (("roadmap.md", r"^Goal:[ \t]*(.*)$"), ("project.md", r"^- Notes:[ \t]*(.*)$")):
        f = root / name
        for goal in re.findall(pattern, f.read_text(), re.M) if f.exists() else []:
            if goal.strip():
                return goal.strip()
    return ""


def rank_ticket(text, root, asked):
    """(question, raw answers, decision) for one backlog ticket: `p<N> <kind>`, or `none` with no ticket or goal."""
    q = STEPS["rank"][0]
    goal = project_goal(root)
    if not text.strip() or not goal:
        return "-", "-", "none"
    asked.append(q)
    a = jev.ask_many({"ticket": text.strip(), "goal": goal},
                     {"importance": {"type": "score", "instructions": q, "criteria": IMPORTANCE},
                      "necessity": {"type": "score", "instructions": "How necessary is this ticket", "criteria": NECESSITY},
                      "progress": {"type": "noul", "instructions": PROGRESS},
                      "kind": {"type": "choice", "instructions": "Which kind of work is this ticket", "criteria": KINDS}})
    v = {k: val for k, (val, _) in a.items()}
    n = round(v["importance"]) + 1
    if v["necessity"] < 1 or (v["progress"] < 0.5 and v["kind"] in SIDE_KINDS):
        n -= 1
    return q, {k: raw for k, (_, raw) in a.items()}, f"p{min(max(n, 1), 5)} {v['kind']}"


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
    if step == "rank":
        return rank_ticket(stdin, job.parent.parent, asked)
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
    print(run(step, lambda asked: decide(step, job, asked), job / "jev.log"))
    return 0


def run(step, fn, log_path):
    """Call fn(asked) -> (question, raw, decision), append the 6-field line to log_path and return the decision.
    Any error gives the step's fallback. board.py rank-backlog calls this too, so both log the same way."""
    start = time.monotonic()
    asked = []
    try:
        q, raw, decision = fn(asked)
        raw = raw if isinstance(raw, str) else json.dumps(raw, separators=(",", ":"))
    except Exception as e:  # the gate never fails the caller
        q, raw, decision = asked[0] if asked else "-", type(e).__name__, STEPS[step][2]
    key = os.environ.get("TYPESAFE_API_KEY", "").strip()
    safe = lambda s: re.sub(r"[\t\r\n]", " ", s.replace(key, "***") if key else s)
    decision = safe(decision)
    fields = [datetime.now().isoformat(timespec="seconds"), step, q, raw, decision, f"{time.monotonic() - start:.2f}"]
    try:
        with open(log_path, "a") as log:
            log.write("\t".join(safe(f) for f in fields) + "\n")
    except OSError:
        pass  # a missing job dir must not cost the caller its decision
    return decision


if __name__ == "__main__":
    sys.exit(main())
