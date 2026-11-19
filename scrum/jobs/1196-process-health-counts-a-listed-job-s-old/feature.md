# Process health: window old ask lines, mark terminal batch asks auto
Lane: fast — pre-written spec, ~80 added lines
Complex: no

See spec.md (the pre-written spec).

## Pre-written spec
# Process health: window old ask lines, mark terminal batch asks auto
UI surface: no
Hard stops: none
Human setup: none
Lane: fast
Complex: no

## Problem
`cmd_process_health` reads all of `questions.log` for every listed job, so a job listed in an earlier digest keeps counting its old ask lines (`unreadable_asks`, `resume_abort_stops`, `stops_per_job`) in a later digest. Separately, the Terminal batch (`project .claude edits`) parks an ask that `serve.py` `terminal_batch_tick` answers itself, yet both its ask line and its pick count as Trevor stops.

## Scope
In:
- `board.py` `cmd_process_health`: skip a questions.log line whose `date` is at or before the previous digest's Since (the window `cmd_digest_trevor` uses: the birth time, else mtime, of the folder `_trevor_previous` returns). With no previous digest there is no cutoff. A line with no parseable `date` (per `_epoch`) still counts, so existing tests that write dateless lines keep passing.
- `board.py` `claude_batch`: the `park(...)` call that creates the batch also marks the ask line `"auto": true`. Do this by a new optional `park(..., auto=False)` argument that sets `entry["auto"] = True` (same as the existing `is_guard_ask` branch); no change to other callers.
- `board.py` `cmd_answer` gets `auto=False`; when true the pick line carries `"auto": true`. `serve.py` `answer_job` gets a pass-through `auto=False`, and `terminal_batch_tick` calls it with `auto=True`.
- Tests: `tests/test_board.py` (old line of a listed job counts 0; a dated line after Since still counts; no previous digest counts all; `claude_batch` ask line has `auto` true and process-health skips it; `cmd_answer(auto=True)` line has `auto` true), `tests/test_serve.py` (`terminal_batch_tick` logs the pick with `auto` true).
Out: Trevor's own clicks stay non-auto; other metrics' windows; the digest's Stops and Repeated questions sections need no code change if they already skip `auto` lines (Assumption below).

## Acceptance criteria
1. A listed job with an `unreadable_asks`-qualifying ask line dated before the previous digest folder's birth time counts 0 in `cmd_process_health` for `stops_per_job`, `resume_abort_stops` and `unreadable_asks`; the same line dated after counts 1. (verify: `tests/test_board.py` `test_process_health_skips_lines_before_previous_since`)
2. With no previous digest, and for a line with no `date`, every line still counts. (verify: same test, second and third case; existing `test_process_health_*` tests still pass)
3. `claude_batch` creating a new batch writes the ask line to questions.log with `"auto": true`, and `cmd_process_health` counts no stop for it. (verify: `tests/test_board.py` `test_claude_batch_ask_is_auto`)
4. `board.cmd_answer(root, id, key, auto=True)` writes the pick line with `"auto": true`; without it the line has no `auto` key. (verify: `tests/test_board.py` `test_answer_auto_flag`)
5. `terminal_batch_tick` opening a parked batch logs the `Run it in a Terminal window` pick with `"auto": true`. (verify: `tests/test_serve.py` `test_terminal_batch_tick_pick_is_auto`)

## Likely files
- `skills/trevskills-scrum/board.py` (functions: cmd_process_health, park, claude_batch, cmd_answer)
- `skills/trevskills-scrum/serve.py` (functions: answer_job, terminal_batch_tick)
- `tests/test_board.py`
- `tests/test_serve.py`

## Assumptions
- Size: about 4 files, 80 lines
- The cutoff is the previous digest folder's `st_birthtime` (else `st_mtime`), the same value `cmd_digest_trevor` calls `since`, found with `_trevor_previous`; the cutoff is exclusive (`date` must be after it).
- Dateless lines count: keeps existing tests and old log lines working.
- The digest's Stops and Repeated questions skip `auto` lines already (unverified; if a reader there does not, the build adds the same `auto` skip).
- Existing tests that write questions.log lines with no `date` are unaffected; no existing test expectation flips.
