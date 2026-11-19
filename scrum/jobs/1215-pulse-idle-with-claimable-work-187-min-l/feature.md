# Pulse idle with claimable work 187 min: pass holds to note_held

Pulse idle with claimable work 187 min (longest 51 min, onewitharts digest 127, 2026-11-19 04:24-08:04Z) while every pulse line had gates [] and guard null, sessions 0-1, CPU load at most 70%, and onewitharts held 19-34 claimable lines; meanwhile run-all children sat waiting with no reason (onewitharts 1524, 1525 under 1455-run-all; trevskills-scrum 1205 under 1191-run-all) and the shop Mac ran 1592-run-all children one at a time (job 1595 queued 4h58m, Queue gate `-`). Fix: in `skills/trevskills-scrum/serve.py`, have start_ready and auto_continue_tick pass the hold that skipped a ready job (a `runs_on: any` child left to the shop, finish_first, a running run-all, SWEEP_HELD) to note_held; have pulse_tick add that token to the project's gates so `skills/trevskills-scrum/board.py` write_pulse counts those minutes as gated and timing names the gate; when no hold applies, start the ready children. Tests in `tests/test_serve.py` and `tests/test_board.py`.

Lane: fast — ~77 added lines (serve.py, board.py write_pulse, two test files); related tests only
Complex: no
Hard stops: none
