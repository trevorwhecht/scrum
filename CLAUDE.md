# trevskills-scrum — repo facts

This repo IS the scrum. `install.sh` symlinks `skills/trevskills-scrum`, `skills/trevskills-e2e`, every
`agents/scrum-*.md` and `codex/AGENTS.md` into `~/.claude` / `~/.codex`, so the main checkout is live:
never leave it dirty, and land changes with `/trevskills-commitpush` or the pipeline.

- Test: `python3 tests/run_parallel.py` (stdlib only) is the full run: it deals the test ids into one shard per CPU and prints one line per shard. It took 160 s on 8 cores at a 1-minute load average of 4.2 (2026-10-27), inside the 600 s Bash timeout. The Go git-guard hook has its own tests: `cd skills/trevskills-scrum/gitguard && go test ./...` (`tests/test_gitguard.py` runs them when Go is installed).
- Edit check: `skills/trevskills-scrum/edit-check.py` is a PostToolUse hook (`Edit|Write|MultiEdit`, added to `~/.claude/settings.json` by `install.sh`). In a checkout holding `skills/trevskills-scrum/board.py` it compiles an edited `.py` and runs `ruff check --select F` on it when ruff is on PATH, and runs `tests.test_contracts` after an edit to `agents/*.md`, SKILL.md or `lanes/*.md`; a failure exits 2 with the error. Keep `ruff check --select F .` clean so the hook only names new findings.
- While working, run only the tests your change touches: `python3 -m unittest discover -s tests -p 'test_<name>.py' -k <part of the test names>` (e.g. `-k cmd_ready`); `python3 -m unittest tests.test_<name>` fails on modules that import a sibling (`import test_serve`).
- Never run `tests/test_board.py` or `tests/test_serve.py` whole as a focused or related-tests run: under load they took 1187 s and 1151 s (job 955), far longer than the whole `tests/run_parallel.py` run (59 s in job 964).
- Subprocess and timing tests with 5 s timeouts (`tests/test_board.py`, `tests/test_board_small_fixes.py`, `tests/test_buildlock.py`, `tests/test_jev.py`, `DigestTest` in `tests/test_serve.py`) and `RenderChromeTest` in `tests/test_render.py` ("Chrome failed to start") can fail in the full run under load; re-run a failing test alone before treating it as a real failure, and a pass alone ends the diagnosis.
- A load timeout that passes when re-run alone is not a review finding; at most one line under Notes.
- The dashboard browser tests (`require("playwright")`) skip when Playwright is missing, and the global npm root has none: run them with `NODE_PATH=/Users/trevorhecht/Developer/repos/onewitharts/node_modules`.
- `tests/test_contracts.py` pins exact agent and SKILL.md wording: `self.section(text, "## A", "## B")` slices a
  heading range and `assertIn(phrase, ...)` checks phrases. Before rewording an agent or SKILL.md line, grep the
  phrase there and change both in the same commit. `FIRST_LINE` pins each agent's first output line.
- `skills/trevskills-scrum/board.py` conventions: errors are `raise SystemExit("<message>")`; every board write is a
  tmp file + `os.replace` under the board lock; `SCRUM_*` env vars (`SCRUM_CODEX_SESSIONS`,
  `SCRUM_REGISTRY`, ...) override paths and URLs so tests stay hermetic.
- A test that reaches `board.finish_first` (an automatic `cmd_next` claim, `cmd_ready`) sets `SCRUM_REGISTRY` to a temp `projects.json` in setUp, as `tests/test_backlog.py` does, so a job waiting on a real board cannot fail it.
- A test module that reaches `serve.spawn`, a launch gate or auto-resume pins `SCRUM_PS=os.devnull`, `SCRUM_FREE_RAM`, `SCRUM_SWAP_PCT` and `SCRUM_CPU_LOAD_PCT` (as `tests/test_serve.py` does at import) and mocks `serve.run_terminal`, which raises under unittest.
- Accounts: board.py `ACCOUNTS` lists main (`~/.claude`) then owa (`~/.claude-owa`), both reserve `(None, 90)` (7d 90%, no 5h value), applied to the backup only: the primary (`primary_account`, the soonest future 7d reset) is never held; each has its own `usage.json` and limit marker (`limit_path`, `note_limit`, `limited_until`), `pick_account` chooses one, and serve.py `LIMIT_RE`/`limit_reset` decide a limit exit. Tests set `SCRUM_ACCOUNTS` or `SCRUM_USAGE` to temp paths; `limit_path` refuses real account dirs under unittest.
- A test module that reaches `serve.spawn`, a launch gate or auto-resume pins `SCRUM_PS=os.devnull`, `SCRUM_FREE_RAM`, `SCRUM_SWAP_PCT`, `SCRUM_VM_PRESSURE=1` and `SCRUM_CPU_LOAD_PCT` (as `tests/test_serve.py` does at import) and mocks `serve.run_terminal`, which raises under unittest.
- SKILL.md: locate sections by heading (`grep -n '^## ' skills/trevskills-scrum/SKILL.md`), never by line number.
  Headings: Setup, Commands, New job, Run all, Fast lane, Debug lane, BigBoy lane, Roadmap lane, Lilguy lane,
  Cloud lane, Check gate, Review (WAIT FOR ALL), Approve, Migrate, Merge, Routing, Resuming the builder, Digest, Final report.
- SKILL.md is capped by `test_skill_md_within_body_budget` in `tests/test_contracts.py`: 20,000 characters, 500 lines, 5,000 tokens (length // 4). It is about 19,300 characters now, so check `wc -c`/length before adding text and keep SKILL.md growth small. Put new text in `lanes/<lane>.md`.
- `test_no_unrequested_redesigns` in `tests/test_contracts.py` caps the length of `lanes/newjob.md` and of the approver, triager, spec-writer, review-ui and review-ux agents; `test_review_agents_base_render_before_additive` caps review-ui and review-ux lower. Read the live numbers in those tests, never from this file. A spec that adds text to one of them checks its length first and, when the edit would pass the cap, trims as much text from the same file, raises that cap only when no trim fits, says which under Assumptions, and lists `tests/test_contracts.py` under Likely files.
- A file near its cap is not a review finding.
- The Merge step 1 "Main checkout guard" and its three asks (Uncommitted changes, Wrong branch, Unpushed commits; titles incl. `WRONG_BRANCH`) live in SKILL.md under `## Merge`, step 1 Preconditions. Step 7 (Clean up) in `lanes/merge.md` has a "Fast-forward main" guard that repeats the same test; changing one means checking the other.
- Browser (Playwright) tests skip or need a ruling because the global npm root has no Playwright. Workaround: run from onewitharts with `NODE_PATH=/Users/trevorhecht/Developer/repos/onewitharts/node_modules`.
- Lane bodies live in `skills/trevskills-scrum/lanes/<file>.md` (runall, debug, bigboy, roadmap, lilguy, cloud, newjob, commands, digest, review, merge, setup, stops, unblock). SKILL.md holds only the section heading plus a `Read $HOME/.claude/skills/trevskills-scrum/lanes/<file>.md` pointer for every lane or section whose body moved. Tickets and specs name the `lanes/<file>.md`, not SKILL.md, when the live text sits there. New lane text goes in the lane file, not SKILL.md.
- `lanes/shop.md` documents `shop.py` and serve.py `shop_tick` step by step, so a change to either updates it in the same diff: Likely files lists `skills/trevskills-scrum/lanes/shop.md` with `skills/trevskills-scrum/shop.py` and `tests/test_shop.py` (setup steps) or serve.py `shop_tick` and `tests/test_serve_shop.py` (dispatch).
- Facts about the shop Mac's tools (no Homebrew; its `~/.local/bin/python3` is uv-managed and refuses `pip install`) come from `skills/trevskills-scrum/shop/machine-notes-shopmac.md`: read it before writing any spec Assumption about the shop Mac, never guess.
- **Merge** step 1 (Preconditions: the schema guard and the main checkout guard with its asks) and the start of step 2 stay in SKILL.md `## Merge`; the rest of Merge, **Migrate** and **Resuming the builder** live in `lanes/merge.md`.
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
