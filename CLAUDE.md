# trevskills-scrum — repo facts

This repo IS the scrum. `install.sh` symlinks `skills/trevskills-scrum`, `skills/trevskills-e2e`, every
`agents/scrum-*.md` and `codex/AGENTS.md` into `~/.claude` / `~/.codex`, so the main checkout is live:
never leave it dirty, and land changes with `/trevskills-commitpush` or the pipeline.

- Test: `python3 -m unittest discover -s tests` (stdlib only). The full run takes 25-30 min under machine load, past the 600 s Bash timeout: run it with `run_in_background`, and run single modules (`python3 -m unittest tests.test_<name>`) while working.
- Subprocess and timing tests with 5 s timeouts (`tests/test_board_small_fixes.py`, `tests/test_buildlock.py`, `DigestTest` in `tests/test_serve.py`) can fail in the full run under load; re-run a failing test alone before treating it as a real failure.
- A load timeout that passes when re-run alone is not a review finding; at most one line under Notes.
- `tests/test_contracts.py` pins exact agent and SKILL.md wording: `self.section(text, "## A", "## B")` slices a
  heading range and `assertIn(phrase, ...)` checks phrases. Before rewording an agent or SKILL.md line, grep the
  phrase there and change both in the same commit. `FIRST_LINE` pins each agent's first output line.
- `skills/trevskills-scrum/board.py` conventions: errors are `raise SystemExit("<message>")`; every board write is a
  tmp file + `os.replace` under the board lock; `SCRUM_*` env vars (`SCRUM_CODEX_SESSIONS`,
  `SCRUM_REGISTRY`, ...) override paths and URLs so tests stay hermetic.
- SKILL.md: locate sections by heading (`grep -n '^## ' skills/trevskills-scrum/SKILL.md`), never by line number.
  Headings: Setup, Commands, New job, Run all, Fast lane, Debug lane, BigBoy lane, Roadmap lane, Lilguy lane,
  Cloud lane, Check gate, Review (WAIT FOR ALL), Approve, Migrate, Merge, Routing, Resuming the builder, Digest, Final report.
- SKILL.md must stay under 81,000 bytes (`test_skill_md_size_budget` in `tests/test_contracts.py`), target under 80,000; check `wc -c` before adding text. It is about 19,100 bytes (184 lines, about 4,800 tokens) now, just under rule 4's 5,000-token budget (`BODY_MAX_LINES, BODY_MAX_TOKENS = 500, 5000` in `board.py`), so growth can fail B rules-check. Put new text in `lanes/<lane>.md`.
- Lane bodies live in `skills/trevskills-scrum/lanes/<lane>.md` (runall, debug, bigboy, roadmap, lilguy, cloud); their SKILL.md section is one `Read ... when this lane runs.` line. New lane text goes in the lane file, not SKILL.md.
- Dashboard: `skills/trevskills-scrum/dashboard.html` is one file served by `serve.py` on :8765. The UI rules in
  `/Users/trevorhecht/Developer/repos/.claude/rules/ui-behaviour.md` apply to it; test at 390 px first.
- Dashboard: an async fetch or poll that writes into the viewer, a modal or a list returns early when its target changed while it waited (e.g. `if ($("viewer").dataset.key !== job.key) return;`).
- Routing: `local/routing.json` + `local/route.py`. Codex lives at `/opt/homebrew/bin/codex` only on Trevor's
  Mac; `route.py codex-review` returns `skip` wherever the binary is missing (cloud sessions).
- Agent, SKILL.md and lane edits merge like any other job, with no agent-rules stop (Trevor's choice, 2026-10-15).
  Batch rule edits; do not mix them into feature jobs.

## Scrum map
- `~/.claude/scrum-map.md` is the one-page reference for how the pipeline actually works (processes, Codex routing,
  lanes, pacing/caps, Focus, idle checklist). Any change to those (board.py, serve.py, continue.py, routing.json,
  LaunchAgents, lanes, agent models) updates the map in the same chat. It lives outside the repo, so editing
  it never dirties this checkout.
- A scrum job never edits the map (it is outside WORKTREE): the builder writes each map edit under build.md's
  `## Scrum map`, and Merge step 7 applies it to the map after the job is done. Specs need not restate this.

## Git
- The main checkout stays on `main` and is live in `~/.claude`; scrum jobs branch from `origin/main` and squash-merge
  their PRs into `main`.
- An edit made in this checkout from a chat is finished in that same chat: run the tests, then commit and push `main`
  (`/trevskills-commitpush`). Never end a chat with uncommitted edits here; every scrum Merge refuses to run while the
  checkout is dirty. Not finishing it now? Put it on the backlog (`board.py backlog-add`) and leave the files alone.
- Never `git reset`, `git rebase` or force-push.
