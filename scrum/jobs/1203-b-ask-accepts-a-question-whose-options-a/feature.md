# B ask accepts a question whose options are all resume/abort

`B ask` accepts a question whose options are all `resume`/`abort` commands though `skills/trevskills-scrum/lanes/stops.md` says it is refused (1x, onewitharts job 1091, 2026-11-15 phase-order ask, digest 124 resume_abort_stops): in `skills/trevskills-scrum/board.py` main's `ask` branch, refuse with `ask refused: add a followup <id> "<fix>" option, or run B wait-on <id> <blocker> instead of asking` when every option's command starts `resume ` or `abort ` (the same test cmd_process_health uses), after checking that every `B ask` in `skills/trevskills-scrum/SKILL.md` and `skills/trevskills-scrum/lanes/*.md` keeps another option; test in `tests/test_board.py`.

## Pre-written spec

# Refuse a `B ask` whose options are all resume/abort
UI surface: no
Hard stops: none
Human setup: none
Lane: fast
Complex: no

## Problem
`lanes/stops.md` ("Never only resume or abort") says an ask whose options are all `resume`/`abort` is refused, but `board.py main`'s `ask` branch accepts it. Job 1091 parked such a stop, and `cmd_process_health` counted it under `resume_abort_stops` (digest 124).

## Scope
In:
- In `board.py`, one helper (e.g. `resume_abort_only(options)`: non-empty and every command starts `resume ` or `abort `), used by `cmd_process_health` (replacing its inline test) and by main's `ask` branch.
- Main's `ask` branch (the CLI, next to the `unreadable_question` check) refuses with exactly `ask refused: add a followup <id> "<fix>" option, or run B wait-on <id> <blocker> instead of asking`. It does not refuse asks that process_health already ignores as automatic: `is_guard_ask(question)`, `QUEUE_ASK_RE.match`, `CI_BILLING_RE.search`, `AGENT_TYPES_RE.search`. These stay on `Carry on=resume` / `Remove this job=abort` (SKILL.md Merge guards, `check.lock` queue waits, merge.md CI billing, unblock.md E2E queue).
- Audit first: scan every `B ask` in `skills/trevskills-scrum/SKILL.md`, `agents/scrum-unblocker.md` and `lanes/*.md` whose options are all `resume`/`abort` and which is not one of those exempt asks. Each gets a `--c 'File a follow-up=followup $ID "<fix>"'` option. A scan of the current text finds `lanes/newjob.md` (malformed Base branch ask; local database down ask) and `lanes/merge.md` step 5 (conflict after 2 tries, `--kind conflict`). Re-run the scan; it also must check asks split over lines. Update the `--recommend` key if needed.
- Existing tests that flip: `test_ask_accepts_prod_check_title` and `test_ask_followup_option` (first call in `test_ask_accepts_prod_check_title` only: CLI with `Try again=resume` + `abort`, no `--c`); grep `tests/` for any other CLI `board.main([... "ask" ...])` with only resume/abort options and for lane-text phrases pinned in `tests/test_contracts.py`, and fix them.
Out: `cmd_ask` direct calls (not the CLI) stay unrefused (`test_cmd_ask_direct_not_limited`, `test_ask_accepts_each_command_form`); no change to process_health counting.

## Acceptance criteria
1. `board.main(["ask", id, "Q?", "--a", "Go=resume <id>", "--b", "Stop=abort <id>", "--title", "MERGE_CONFLICT"])` raises SystemExit with the exact message above and leaves the job's stage unchanged with no `question`. (verify: `test_ask_refuses_resume_abort_only` in tests/test_board.py)
2. The same ask with a third `--c 'File a follow-up=followup <id> "fix it"'`, or with an `approve`/`rework` option, parks. (verify: `test_ask_accepts_resume_abort_with_other_option`)
3. The exempt asks (a guard ask `Unpushed commits in repo: x`, `waiting on the E2E queue` in check, a billing ask) with only resume/abort options are not refused. (verify: `test_ask_resume_abort_exempt_asks`)
4. `cmd_process_health` uses the same helper and its `resume_abort_stops` result is unchanged. (verify: existing process_health tests in tests/test_board.py pass)
5. Every non-exempt `B ask` in SKILL.md, the unblocker agent and `lanes/*.md` keeps a non-resume/abort option. (verify: `test_ask_lines_not_resume_abort_only` in tests/test_contracts.py, scanning those files and skipping the exempt asks by their text)

## Likely files
- `skills/trevskills-scrum/board.py` (functions: `cmd_process_health`, `main`, new `resume_abort_only`)
- `skills/trevskills-scrum/lanes/newjob.md`
- `skills/trevskills-scrum/lanes/merge.md`
- `tests/test_board.py`
- `tests/test_contracts.py`

## Assumptions
- Size: about 5 files, 60 lines
- The exempt list mirrors what process_health already treats as non-stops; the CLI has no stage, so the queue exemption matches on question text only.
- Other lane files (`unblock.md`, `commands.md`, SKILL.md guards) are exempt asks or prose; the scan in Scope decides, not this list.
