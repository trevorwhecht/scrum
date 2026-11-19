STATUS: READY
## Summary
`board.STARTED_BY` gains `"digest"` (so `new --by digest` passes the CLI choices too). `write_pulse` now skips a `started_by: digest` job in the "Claims during cool down" and "Hand-started during cool down" groups, at the same check that skips `shop`. Its docstring and the `STARTED_BY` comment say so. `serve.py digest_apply` creates its bookkeeping job with `started_by="digest"`. That covers `digest_revert`, which calls `digest_apply`. Per the spec, these stay as they were: the "Other starts while CPU load over 500%" group, the `by_acc` per-account count, the serve.py start gate, and the other `cmd_new` calls.

## Acceptance criteria
1. `board.STARTED_BY` contains "digest", and `cmd_new(..., started_by="digest")` stores it. Verified by `tests/test_board.py` `test_pulse_cool_down_skips_digest_claims` (its first asserts), run with `python3 -m unittest discover -s tests -p 'test_board.py' -k test_pulse_cool_down_skips`. RED: `AssertionError: 'digest' not found in ('serve', 'runall', 'wake', 'hand', 'shop')`. GREEN: `Ran 3 tests ... OK`. PASS
2. A digest job in a cool-down rise is in neither the Claims group nor the Hand-started group. Verified by `test_pulse_cool_down_skips_digest_claims`, which asserts `Claims during cool down: 1 — app 13\nHand-started during cool down: 1 — app 12\n`. Same command, same RED (the test stops at the STARTED_BY assert first), then GREEN OK. PASS
3. The hand and serve jobs in the same rise still count. Verified by the same assertion: hand 12 is in Hand-started and serve 13 is in Claims. Same command. PASS
4. `digest_apply` creates its job with `started_by == "digest"`. Verified by a new assertion in `tests/test_serve.py` `test_digest_apply_pushes_and_fast_forwards`, run with `python3 -m unittest discover -s tests -p 'test_serve.py' -k test_digest_apply_pushes_and_fast_forwards -k test_digest_revert_repo_edit_commits_under_lilguy_job`. RED: `AssertionError: 'hand' != 'digest'`. GREEN: `Ran 2 tests ... OK`. PASS
5. `digest_revert` of a repo proposal creates a `started_by: "digest"` job. Verified by a new assertion in `DigestTest.test_digest_revert_repo_edit_commits_under_lilguy_job`. Same command: RED `'hand' != 'digest'`, then GREEN OK. PASS

Related runs, all with the exit code read:
- `python3 -m unittest discover -s tests -p 'test_board.py' -k pulse`: 28 tests, OK.
- `python3 -m unittest discover -s tests -p 'test_serve.py' -k digest`: 64 tests, OK.
- `python3 -m unittest discover -s tests -p 'test_board.py' -k started_by -k cmd_new -k by_`: 14 tests, OK.
- `ruff check --select F` on the 4 changed files: clean.
- Typecheck and Lint are `none` in PROJECT, so neither was run.

## Rulings
- Ruling: I used a separate `digest` flag in `write_pulse` instead of folding digest into the existing `shop` variable. Why: `shop` also gates the "Other starts while CPU load over 500%" group (`skills/trevskills-scrum/board.py`, the `and not shop` on the cpu_load>500 check), and the spec keeps that group unchanged. Cost if wrong: a digest job created while the CPU is hot still shows as an "other" start.
- Ruling: I checked that no test asserted `started_by == "hand"` for a digest job. `grep -rn "started_by.*hand\|STARTED_BY" tests/ | grep -i digest` finds only the new lines. Cost if wrong: none.

## Scrum map
- none

## Commits
- 63cf868 Label digest-apply jobs started_by digest so Pulse skips them
