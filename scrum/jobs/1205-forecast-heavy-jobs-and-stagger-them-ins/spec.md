# Forecast heavy jobs and stagger them
UI surface: no
Hard stops: none
Human setup: none
Lane: fast
Complex: no

## Problem
Digest 009 (messageManager) shows 5h03m of queued time behind vm_pressure, swap and cpu_load. messageManager has no Build, no UI and a pytest-only Test, yet its jobs size as heavy. All jobs wait for the same RAM and young-session gates, and heavy starts burst together and then stall each other. Light jobs should keep starting, and heavy starts should ramp one per `SESSION_RAMP_SECS`.

## Scope
In:
- `board.light_job(root, job)` is also true when `root/project.md` has a `- Build:` line whose value is `none` and a `- Has UI:` line whose value starts with `no`, whatever the lane. A new small helper reads those two lines with the existing `_project_list` pattern; a missing project.md or line is not light.
- `board.ram_room`: a non-light start counts as two young sessions toward `MAX_YOUNG_SESSIONS`, so the young cap for it is `(MAX_YOUNG_SESSIONS - young) // 2`. A light start keeps counting as one: `MAX_YOUNG_SESSIONS - young`. The free-RAM, swap, pressure and `MAX_SESSIONS` math is unchanged.
- `serve.py` spawn is unchanged (it already calls `board.ram_room(floor=0, light=board.light_job(...))`).
- Existing tests whose expectation flips (grep of `tests/` for `ram_room(` and `MAX_YOUNG_SESSIONS`): `tests/test_board_pacing.py` `test_ram_room_ramps_young_sessions` (0 young now gives 1, not 2) and `test_ready_ignores_usage_pacing_and_runall_cap` (the claim count at 40% becomes 1); `tests/test_board.py` `test_ram_room` (the `ram_room()` expectations that are 2), `test_ram_room_young_cap_holds_at_any_ram` and `test_ram_room_light_share` (the standard figures at young=1 and under the raised `MAX_YOUNG_SESSIONS`).
Out: weighting already-running young sessions by their own job's weight (ps does not say which are heavy); changing `SESSION_RAMP_SECS` or `MAX_YOUNG_SESSIONS`; a dashboard display.

## Acceptance criteria
1. `light_job` is True for a job on a standard lane when project.md has `- Build: none` and `- Has UI: no`, and False when Build is not `none`, when Has UI is `yes ...`, or when project.md or either line is missing. A fast lane stays light regardless. (verify: `tests/test_board.py` `test_light_job_project_profile`)
2. With free RAM high and no young sessions, `ram_room(floor=0)` for a non-light job is 1; with 1 young session it is 0; `ram_room(floor=0, light=True)` is 2 with none and 1 with one young session. (verify: `tests/test_board_pacing.py` `test_ram_room_ramps_young_sessions`, extended)
3. A heavy session started under the young window blocks a second heavy start until `SESSION_RAMP_SECS` has passed, while a light job still gets room beside it. (verify: `tests/test_board_pacing.py` `test_ram_room_ramps_young_sessions`, a case with ages `[5]`)
4. `serve.spawn` for a job in a project with `Build: none` and `Has UI: no` calls `ram_room(floor=0, light=True)`, and a standard job in a project with a build calls it with `light=False`. (verify: `tests/test_serve.py` `test_spawn_light_job_ram_gate`, a project-profile case)
5. The existing tests listed under Scope In are updated to the new figures. (verify: `python3 -m unittest tests.test_board tests.test_board_pacing tests.test_serve`)

## Likely files
- `skills/trevskills-scrum/board.py` (functions: light_job, ram_room, a new `_project_light(root)` helper)
- `tests/test_board.py`
- `tests/test_board_pacing.py`
- `tests/test_serve.py`

## Assumptions
Size: about 4 files, 60 lines
- "Two young sessions" means the new session's weight in the young cap; sessions already running count 1 each, because ps only shows the action and job id.
- `Has UI:` value is read as the first word, lowercased; `no` matches and `yes (...)` does not.
- This repo's own project.md has `Has UI: yes`, so it stays heavy.
- The `cmd_ready` claim batch in `board.py` (the `light` lane check near `light_room`) stays lane-based; it takes the `ram_room` result as is. If that check should also see the project profile, the builder reuses `light_job`. This is unverified.
