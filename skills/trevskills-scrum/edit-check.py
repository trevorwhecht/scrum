#!/usr/bin/env python3
"""PostToolUse hook (Edit|Write|MultiEdit), wired into ~/.claude/settings.json by install.sh.

Only a file whose git root holds skills/trevskills-scrum/board.py (this repo, its job worktrees) is checked; any other
file exits 0 straight away with no subprocess, since the hook runs on every edit in every project.
*.py: compile, then `ruff check --select F` when ruff is on PATH. agents/*.md, SKILL.md, lanes/*.md: tests.test_contracts.
A failure exits 2 with the first 20 lines on stderr, which Claude sees; a pass prints nothing.
"""
import json, os, shutil, subprocess, sys, traceback

MARKER = os.path.join("skills", "trevskills-scrum", "board.py")
CONTRACT_DIRS = ("agents", os.path.join("skills", "trevskills-scrum", "lanes"))
SKILL_MD = os.path.join("skills", "trevskills-scrum", "SKILL.md")


def git_root(path):
    d = os.path.dirname(path)
    while not os.path.exists(os.path.join(d, ".git")):
        if os.path.dirname(d) == d:
            return None
        d = os.path.dirname(d)
    return d


def fail(text):
    print("\n".join(text.strip().splitlines()[:20])[:4000], file=sys.stderr)
    sys.exit(2)


def main():
    try:
        path = json.load(sys.stdin)["tool_input"]["file_path"]
        path = os.path.realpath(path)
    except Exception:
        return
    root = git_root(path)
    if root is None or not os.path.isfile(os.path.join(root, MARKER)) or not os.path.isfile(path):
        return
    rel = os.path.relpath(path, root)
    if path.endswith(".py"):
        try:
            with open(path, "rb") as f:
                compile(f.read(), path, "exec", dont_inherit=True)  # py_compile's check, without writing a .pyc
        except (SyntaxError, ValueError) as e:
            fail("".join(traceback.format_exception_only(type(e), e)))
        ruff = shutil.which("ruff")
        if ruff:
            r = subprocess.run([ruff, "check", "--select", "F", "--no-cache", "--output-format", "concise", "--", path],
                               capture_output=True, text=True)
            if r.returncode:
                fail(r.stdout + r.stderr)
    elif rel == SKILL_MD or (rel.endswith(".md") and os.path.dirname(rel) in CONTRACT_DIRS):
        r = subprocess.run([sys.executable, "-m", "unittest", "tests.test_contracts"], cwd=root, capture_output=True, text=True)
        if r.returncode:
            fail(r.stderr + r.stdout)


if __name__ == "__main__":
    main()
