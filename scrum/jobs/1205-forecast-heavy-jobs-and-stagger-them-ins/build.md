STATUS: READY
## Summary
`board.light_job` is also true when project.md has `- Build: none` and a `- Has UI:` first word `no` (new `_project_light`). `ram_room` caps a non-light start at `(MAX_YOUNG_SESSIONS - young) // 2`; a light start keeps `MAX_YOUNG_SESSIONS - young`. serve.py unchanged.
## Acceptance criteria
1. light_job profile — `python3 -m unittest tests.test_board` `test_light_job_project_profile` — PASS
2. ram_room figures 1/0 heavy, 2/1 light — `tests.test_board_pacing` `test_ram_room_ramps_young_sessions` — PASS
3. Heavy at ages [5] blocks a second heavy, light still gets room (the `young=1` case: 0 heavy, 1 light) — same test — PASS
4. serve.spawn passes light by project profile — `tests.test_serve` `test_spawn_light_job_project_profile` — PASS
5. Updated tests — `python3 -m unittest tests.test_board tests.test_board_pacing tests.test_serve` (test_serve passed in the full run; board and pacing re-run after final edits: 948 OK) — PASS
## Rulings
- Ruling: about 20 more tests than the spec listed flipped (claims of 2 per cmd_ready/serve batch become 1). Where the test is about something else (overlap, cooling, drain), I added `@mock.patch.object(board, "MAX_YOUNG_SESSIONS", 4)` so a heavy batch is still 2 and the expectations stay unchanged; tests that used `board.MAX_SESSIONS` as the lifted cap now use `2 * board.MAX_SESSIONS` — the heavy cap would otherwise be halved; ReadyUsageTest expectations use `MAX_YOUNG_SESSIONS // 2`. — keeps each test's intent — cost if wrong: none for runtime.
- Ruling: `cmd_ready` claim batch left as is (takes the ram_room result); lane-only light check near light_room unchanged per spec assumption.
- Ruling: `Has UI` value read as first word lowercased, trailing punctuation stripped (`No (scripts only)` is light).
## Scrum map
- none
## Commits
- "Stagger heavy starts: heavy counts two young sessions, no-build no-UI projects are light"

## Round 1 response (Check gate)
- Fixed `tests/test_swap_stale_repro.py` `test_stale_swap_does_not_block`, `tests/test_finish_first.py` (`test_queue_wait_in_another_project_holds_child_claims`, `test_trevor_click_claims_past_the_hold`) and `tests/test_serve_launch_gate_repro.py` `test_resolving_n_needs_human_jobs_starts_at_most_ram_room` by patching `MAX_YOUNG_SESSIONS` to 4 (a heavy start counts 2 young); expectations unchanged. Grepped tests/ for `ram_room(` / `MAX_YOUNG_SESSIONS`: other users (`test_serve_launch_cpu_gate.py`) pass.
- `python3 tests/run_parallel.py`: exit 0, 3066 tests, all 8 shards OK.
