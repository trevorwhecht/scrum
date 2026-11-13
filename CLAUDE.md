# trevskills-scrum — repo facts

This repo IS the scrum. `install.sh` symlinks `skills/trevskills-scrum`, `skills/trevskills-e2e`, every
`agents/scrum-*.md` and `codex/AGENTS.md` into `~/.claude` / `~/.codex`, so the main checkout is live:
never leave it dirty, and land changes with `/trevskills-commitpush` or the pipeline.

- Test: `python3 tests/run_parallel.py` (stdlib only) is the full run: it deals the test ids into one shard per CPU and prints one line per shard. It took 160 s on 8 cores at a 1-minute load average of 4.2 (2026-10-27), inside the 600 s Bash timeout; run single modules (`python3 -m unittest tests.test_<name>`) while working. The Go git-guard hook has its own tests: `cd skills/trevskills-scrum/gitguard && go test ./...` (`tests/test_gitguard.py` runs them when Go is installed).
- Subprocess and timing tests with 5 s timeouts (`tests/test_board.py`, `tests/test_board_small_fixes.py`, `tests/test_buildlock.py`, `DigestTest` in `tests/test_serve.py`) can fail in the full run under load; re-run a failing test alone before treating it as a real failure.
- A load timeout that passes when re-run alone is not a review finding; at most one line under Notes.
- `tests/test_contracts.py` pins exact agent and SKILL.md wording: `self.section(text, "## A", "## B")` slices a
  heading range and `assertIn(phrase, ...)` checks phrases. Before rewording an agent or SKILL.md line, grep the
  phrase there and change both in the same commit. `FIRST_LINE` pins each agent's first output line.
- `skills/trevskills-scrum/board.py` conventions: errors are `raise SystemExit("<message>")`; every board write is a
  tmp file + `os.replace` under the board lock; `SCRUM_*` env vars (`SCRUM_CODEX_SESSIONS`,
  `SCRUM_REGISTRY`, ...) override paths and URLs so tests stay hermetic.
- A test module that reaches `serve.spawn`, a launch gate or auto-resume pins `SCRUM_PS=os.devnull`, `SCRUM_FREE_RAM`, `SCRUM_SWAP_PCT` and `SCRUM_CPU_LOAD_PCT` (as `tests/test_serve.py` does at import) and mocks `serve.run_terminal`, which raises under unittest.
- SKILL.md: locate sections by heading (`grep -n '^## ' skills/trevskills-scrum/SKILL.md`), never by line number.
  Headings: Setup, Commands, New job, Run all, Fast lane, Debug lane, BigBoy lane, Roadmap lane, Lilguy lane,
  Cloud lane, Check gate, Review (WAIT FOR ALL), Approve, Migrate, Merge, Routing, Resuming the builder, Digest, Final report.
- SKILL.md is capped by `test_skill_md_within_body_budget` in `tests/test_contracts.py`: 20,000 characters, 500 lines, 5,000 tokens (length // 4). It is about 19,300 characters now, so check `wc -c`/length before adding text and keep SKILL.md growth small. Put new text in `lanes/<lane>.md`.
- `test_no_unrequested_redesigns` in `tests/test_contracts.py` caps the length of `lanes/newjob.md` and of the approver, triager, spec-writer, review-ui and review-ux agents; `test_review_agents_base_render_before_additive` caps review-ui and review-ux lower. Read the live numbers in those tests, never from this file. A spec that adds text to one of them checks its length first and, when the edit would pass the cap, trims as much text from the same file, raises that cap only when no trim fits, says which under Assumptions, and lists `tests/test_contracts.py` under Likely files.
- A file near its cap is not a review finding.
- The Merge step 1 "Main checkout guard" and its three asks (Uncommitted changes, Wrong branch, Unpushed commits; titles incl. `WRONG_BRANCH`) live in SKILL.md under `## Merge`, step 1 Preconditions. Step 7 (Clean up) in `lanes/merge.md` has a "Fast-forward main" guard that repeats the same test; changing one means checking the other.
- Browser (Playwright) tests skip or need a ruling because the global npm root has no Playwright. Workaround: run from onewitharts with `NODE_PATH=/Users/trevorhecht/Developer/repos/onewitharts/node_modules`.
- Lane bodies live in `skills/trevskills-scrum/lanes/<file>.md` (runall, debug, bigboy, roadmap, lilguy, cloud, newjob, commands, digest, review, merge, setup, stops, unblock). SKILL.md holds only the section heading plus a `Read $HOME/.claude/skills/trevskills-scrum/lanes/<file>.md` pointer for every lane or section whose body moved. Tickets and specs name the `lanes/<file>.md`, not SKILL.md, when the live text sits there. New lane text goes in the lane file, not SKILL.md.
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
