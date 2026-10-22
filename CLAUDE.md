# trevskills-scrum — repo facts

This repo IS the scrum. `install.sh` symlinks `skills/trevskills-scrum`, `skills/trevskills-e2e`, every
`agents/scrum-*.md` and `codex/AGENTS.md` into `~/.claude` / `~/.codex`, so the main checkout is live:
never leave it dirty, and land changes with `/trevskills-commitpush` or the pipeline.

- Test: `python3 -m unittest discover -s tests` (stdlib only, ~725 tests, ~90 s).
- `tests/test_contracts.py` pins exact agent and SKILL.md wording: `self.section(text, "## A", "## B")` slices a
  heading range and `assertIn(phrase, ...)` checks phrases. Before rewording an agent or SKILL.md line, grep the
  phrase there and change both in the same commit. `FIRST_LINE` pins each agent's first output line.
- `skills/trevskills-scrum/board.py` conventions: errors are `raise SystemExit("<message>")`; every board write is a
  tmp file + `os.replace` under the board lock; `SCRUM_*` env vars (`SCRUM_OLLAMA_URL`, `SCRUM_CODEX_SESSIONS`,
  `SCRUM_ROUTE`, ...) override paths and URLs so tests stay hermetic.
- SKILL.md: locate sections by heading (`grep -n '^## ' skills/trevskills-scrum/SKILL.md`), never by line number.
  Headings: Setup, Commands, New job, Run all, Fast lane, Debug lane, BigBoy lane, Roadmap lane, Lilguy lane,
  Cloud lane, Check gate, Review (WAIT FOR ALL), Approve, Merge, Routing, Resuming the builder, Digest, Final report.
- Dashboard: `skills/trevskills-scrum/dashboard.html` is one file served by `serve.py` on :8765. The UI rules in
  `/Users/trevorhecht/Developer/repos/.claude/rules/ui-behaviour.md` apply to it; test at 390 px first.
- Local routing: `local/routing.json` + `local/route.py`. Codex lives at `/opt/homebrew/bin/codex` only on Trevor's
  Mac; `route.py codex-review` returns `skip` wherever the binary is missing (cloud sessions).
- A diff that touches `agents/scrum-*.md` or `SKILL.md` always stops at the Merge agent-rules guard for Trevor unless
  it is exactly an approved digest proposal. Batch rule edits; do not mix them into feature jobs.
