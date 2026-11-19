# Label digest-apply jobs started_by digest so Pulse skips them
UI surface: no
Hard stops: none
Human setup: none
Lane: fast
Complex: no

## Problem
`digest_apply` in serve.py creates its bookkeeping job with `board.cmd_new(scrum, title)`, so the job gets the default `started_by="hand"`. `write_pulse` then lists it under "Hand-started during cool down" as if Trevor started it (jobs 1183, 1186, 1187, 1188).

## Scope
In: add `"digest"` to `STARTED_BY` in board.py (this also lets `--by digest` pass the `new` CLI choices); `write_pulse` skips a `digest` job in the cool-down claim and Hand-started groups exactly where it skips `shop`; `digest_apply` passes `started_by="digest"` to its `board.cmd_new` call (this covers `digest_revert`, which goes through `digest_apply`). Tests in `tests/test_board.py` and `tests/test_serve.py`.
Out: the serve.py start gate (cool-down park list) is unchanged; the "Other starts while CPU load over 500%" group is unchanged; the other `cmd_new` calls (`weekly_ask`, `queue_digest_item`) are unchanged; relabelling jobs 1183-1188 already on boards.

## Acceptance criteria
1. `board.STARTED_BY` contains `"digest"`, and `board.cmd_new(root, title, started_by="digest")` stores `started_by: "digest"` on the job (verify: `tests/test_board.py` new test in the pulse test class beside `test_pulse_cool_down_skips_shop_claims`, or a cmd_new assertion there).
2. `write_pulse` during cool down, with a rise of jobs of which one is `started_by: "digest"`, one `hand` and one `runall`: the digest job appears in neither "Claims during cool down" nor "Hand-started during cool down" (verify: `tests/test_board.py` `test_pulse_cool_down_skips_digest_claims`, modelled on `test_pulse_cool_down_skips_shop_claims`).
3. A `hand` job and a `serve` job in the same rise are still counted as before (verify: the same test asserts the hand and serve counts and names).
4. `digest_apply` creates its job with `started_by == "digest"` on the board (verify: `tests/test_serve.py` assertion added to `test_digest_apply_pushes_and_fast_forwards`).
5. `digest_revert` of an applied repo proposal also creates a `started_by: "digest"` job (verify: assertion in the existing `DigestTest` revert test for a repo proposal; name it in the build).

## Likely files
- `skills/trevskills-scrum/board.py` (functions: write_pulse; the `STARTED_BY` constant)
- `skills/trevskills-scrum/serve.py` (functions: digest_apply)
- `tests/test_board.py` (`test_pulse_cool_down_skips_digest_claims`)
- `tests/test_serve.py` (`test_digest_apply_pushes_and_fast_forwards`, a `DigestTest` revert test)

## Assumptions
- Size: about 4 files, 40 lines
- Skipping is only in the cool-down claim and Hand-started groups; the `by_acc` per-account count still includes digest jobs, as shop jobs are today.
- No existing test asserts `started_by == "hand"` for digest_apply jobs; the build re-greps `STARTED_BY` and `started_by` in tests/ to confirm.
- The `write_pulse` docstring sentence naming "started_by shop skipped" gets "digest" added.
