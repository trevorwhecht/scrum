STATUS: READY
## Summary
- `board.py` `cmd_process_health` skips a questions.log line whose `date` (per `_epoch`) is at or before the previous digest's Since: the birth time, else mtime, of the folder `_trevor_previous` returns, as `cmd_digest_trevor` computes it. No previous digest means no cutoff; a dateless line still counts.
- `board.py` `park(..., auto=False)` sets `entry["auto"] = True` when asked (shared branch with `is_guard_ask`); `claude_batch` parks the new Terminal batch with `auto=True`.
- `board.py` `cmd_answer(..., auto=False)` adds `"auto": true` to the pick line when true.
- `serve.py` `answer_job(..., auto=False)` passes `auto=True` to `board.cmd_answer` only when set (Trevor's clicks call it without the keyword, so `test_answer_passes_note`'s exact call asserts still hold); `terminal_batch_tick` calls it with `auto=True`.

## Acceptance criteria
1. Old line of a listed job counts 0 for stops_per_job, resume_abort_stops, unreadable_asks; a line dated after counts 1 — verified by `python3 -m unittest discover -s tests -p 'test_board.py' -k test_process_health_skips_lines_before` (`test_process_health_skips_lines_before_previous_since`) — RED: `[(1.0, ['101-alpha']), ...] != [(0, []), ...] : dated before 001's birth time`; GREEN: `Ran 1 test ... OK` — PASS
2. No previous digest and a dateless line both still count — verified by the same test's first and fourth cases, plus `python3 -m unittest discover -s tests -p 'test_board.py' -k health -k digest` (51 tests OK) and `-k ProcessHealth -k ClaudeBatch -k answer -k Ask -k guard` (55 tests OK) — PASS
3. `claude_batch` ask line has `"auto": true` and process-health counts no stop — verified by `python3 -m unittest discover -s tests -p 'test_board.py' -k test_claude_batch_ask_is_auto` — RED: `('002-terminal-batch-project-claude-edits', 'ask', None) != (..., 'ask', True)`; GREEN: OK — PASS
4. `cmd_answer(auto=True)` pick line has `"auto": true`; without it no `auto` key — verified by `python3 -m unittest discover -s tests -p 'test_board.py' -k test_answer_auto_flag` — RED: `TypeError: cmd_answer() got an unexpected keyword argument 'auto'`; GREEN: OK — PASS
5. `terminal_batch_tick` logs the `Run it in a Terminal window` pick with `"auto": true` — verified by `python3 -m unittest discover -s tests -p 'test_serve.py' -k test_terminal_batch_tick_pick_is_auto` — RED: `[('Run it in a Terminal window', None)] != [('Run it in a Terminal window', True)]`; GREEN: OK; plus `-k answer -k terminal_batch -k batch` (22 tests OK) — PASS

Related runs: `python3 -m unittest discover -s tests -p 'test_contracts.py'` (338 OK), `-p 'test_processes.py'` (25 OK), `ruff check --select F` on board.py and serve.py (clean). Typecheck and Lint are `none` in PROJECT. Whole test_board.py/test_serve.py not run (CLAUDE.md forbids it as a focused run).

## Rulings
- Ruling: the Since cutoff sits at the top of the questions.log loop, so it also windows `auto_stalls` — the spec says "skip a questions.log line" in `cmd_process_health`, and auto_stalls has the same re-count bug — cost if wrong: auto_stalls drops lines a later digest would otherwise re-show.
- Ruling: the digest's `## Stops` section (agents/scrum-digest-reader.md:114-123) is left unchanged even though it has no `auto` skip — it deliberately counts auto stall and machine lines (its cause list names "swap used", "stalled in build"), so an `auto` skip there would drop those; `## Repeated questions` already skips `auto` lines and the Terminal batch ask (agents/scrum-digest-reader.md:101). CLAUDE.md also says rule edits batch separately from feature jobs — cost if wrong: the Terminal batch ask still appears as a row in the digest's Stops table.
- Ruling: `answer_job` adds `auto` to `cmd_answer`'s kwargs only when true — keeps `test_answer_passes_note`'s `assert_called_once_with(..., note=...)` (tests/test_serve.py:3150) exact for Trevor's clicks — cost if wrong: none.
- Ruling: local in `cmd_process_health` is named `earlier`, not `prev`, because `prev` is reassigned later in the same function (`prev_id, prev = _previous_health(...)`) — cost if wrong: none.

## Scrum map
- none

## Commits
- f73c191 Process health skips questions.log lines before the previous digest's Since
- ecbb052 Mark the Terminal batch ask auto; cmd_answer takes auto
- f72974e terminal_batch_tick logs its pick auto
