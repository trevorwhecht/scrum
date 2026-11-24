STATUS: READY
## Summary
`board.shop_excluded` now lets a lilguy job go to the shop once one of its gates in `current-gates.json` has a `held` value over its limit. The limit is `SHOP_LILGUY_MEM_HELD_SECS` = 1800 for a `swap` or `vm_pressure` gate that queue-gates.txt names, and `SHOP_LILGUY_HELD_SECS` = 7200 for any other gate. The `held` values are the ones job 1485's note_current_gate writes. `play_queued` and `updatedAt` no longer count. The Pool and Runs on lines in `lanes/shop.md` and the `shop_tick` docstring in serve.py now say this. The cases in `tests/test_board_runs_on.py` (next to the 7200 pin) were rewritten around held seconds, and a 1800 pin was added.

## Acceptance criteria
1. A lilguy job whose queue-gates.txt names swap or vm_pressure goes to the shop after 30 min (cases: vm_pressure 31 min and swap 31 min are released; 29 min and 29 min 50 s are kept). Verified by `python3 -m unittest tests.test_board_runs_on -k test_shop_excluded_lilguy_held_over_2h`. RED: `FAIL ... [board lane, vm_pressure 31 min]`, `[swap 31 min]` and others, plus `AttributeError` on `SHOP_LILGUY_MEM_HELD_SECS`. GREEN: `Ran 20 tests ... OK` (whole file). PASS
2. Other gates keep 7200 (cpu_load at 2 h 1 min is released, at 1 h 59 min kept; a memory gate named but only cpu_load held 1 h is kept). Same command, PASS
3. The hold counts from current-gates.json held seconds, not play_queued or updatedAt. Cases: play_queued and updatedAt just now with held 31 min is released; play_queued 3 h old or updatedAt 3 h old with no current-gates.json is kept; malformed JSON, a list, the old bare-epoch shape, and a held that is a string, `true`, negative or missing are all kept. A cmd_ready subTest leaves a lilguy child held 31 min (play_queued now) to the shop and claims one held 10 min (play_queued 3 h old). Same command, PASS
4. The Pool line in `lanes/shop.md` is updated. `python3 -m unittest tests.test_shop` gives OK, and `tests.test_contracts` gives OK. PASS
5. Other tests for the changed sources (each run in this session, and each passed):
   - `tests.test_serve_shop`, `test_hand_queue`, `test_watchdog_idle_claimable_repro`, `test_backlog`, `test_board_pacing`, `test_finish_first` and `test_parked_bigboy_repro`
   - `test_serve_waste_reruns`, run from `tests/`
   - `tests.test_board -k shop`, `tests.test_board -k ready` and `tests.test_serve -k shop`

   PASS
- Typecheck: none. Lint: none (PROJECT).

## Rulings
- Ruling: each gate in current-gates.json is checked against its own limit. The 1800 limit applies only to a swap or vm_pressure gate that queue-gates.txt also names; every other gate uses 7200. A job goes when any one gate passes its limit. Why: under the literal reading, a brief vm_pressure hit plus 31 min of cpu_load would release the job, which is not a memory hold. Test case "memory gate named, cpu_load 1 h" covers this. Cost if wrong: such a job stays home until 2 h.
- Ruling: the per-gate `held` values are not added together. Why: gates are often hit on the same tick (note_queue_gate stamps several), so a sum would double-count time. Cost if wrong: a job held by alternating gates waits longer.
- Ruling: a non-empty queue-gates.txt is still required, as in job 1246. Why: the spec keeps the "queue-gates.txt names" condition. Cost: none (both files are written together by note_queue_gate, board.py:7222).
- Ruling: the old play_queued/updatedAt kept cases ("malformed play_queued wins...", and so on) were replaced with malformed current-gates.json cases. Why: the spec removes those fields from the rule.
- Ruling: the "held over 2 h" text in the shop.md **Runs on** line and in the serve.py `shop_tick` docstring was also updated. Why: both describe the same rule. `grep -rn "held over 2 h" skills tests` now finds only the test docstring at tests/test_board_runs_on.py:324, which states the 2 h rule alongside the new 30 min one.

## Scrum map
- none

## Commits
- 53919de2 Send a memory-held lilguy job to the shop after 30 min of current-gates held time
