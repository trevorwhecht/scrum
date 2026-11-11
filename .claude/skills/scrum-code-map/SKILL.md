---
name: scrum-code-map
description: Load before speccing or building a change to skills/trevskills-scrum/board.py, serve.py or dashboard.html. Names the functions and tests the scrum keeps re-tracing, so you start from them.
---

# Scrum code map

Find each name with `grep -n 'def <name>'`; never trust a line number. Every function below has a docstring: read it first.

## board.py (`skills/trevskills-scrum/board.py`)
- Subcommands are `cmd_<name>` functions (`cmd_ask`, `cmd_abort`, `cmd_hook`, `cmd_register`, `cmd_backlog_add`, ...).
- `cmd_hook(event, tty, pid=None)`: the `board.py hook` entry the SKILL.md frontmatter hooks call. `waiting_text(event)` picks the text; the job is matched by its recorded claude pid, else by tty.
- `pace_cap(...)` always returns None (job 282) and is kept only for continue.py; `usage_allowance(usage, now, live)` is the usage gate for automated claims.
- `machine_ok(path, manual=False, claim=False)`: None when there is room, else the reason. Order: cool-down (`COOLING`, only when `claim` and not `manual`), free RAM, swap, free disk, CPU busy (skipped when `manual`; `MAX_CPU_BUSY_PCT`, the mean of the last 3 `top` samples the serve.py watchdog records via `record_cpu_sample`), CPU load (skipped when `manual`; `MAX_CPU_LOAD_PCT`, the 5-minute load average over `os.cpu_count()`), session ceiling. Gates new claims, resumes and auto-continue starts only; cool-down holds every automatic start of new work (claim=True: Run-all and BigBoy child claims via `cmd_ready`, `wake_waiting`, auto-continue, `/api/machine`; `manual=True` from Setup done and Play lets Trevor's clicks through), `window_tick` skips the bad-window digest while `cooling_down()`, and `next` (no index), `runall-start`, `cloud-claim` and `roadmap-next` check `cooling_down()` themselves.
- `resume_blocker(root, job_id, live=())`: a `Blocker` (a str with `.ids`) when a sibling child holds overlapping files.
- `session_alive_fn()`: the live-session check for every claude process, Terminal and pre-restart sessions included; tests mock it.
- Watchdog state: `cmd_watchdog(root, alive=None)` flags a stall; `stalled(job)` reads both shapes (legacy needs-human reason `STALLED` = `stalled in `, new `STALL` = `stalled: ` with board `stalled` true); `RESUMABLE` lists the reason prefixes whose card offers Resume; `resume_first(jobs)` counts the paused and stalled jobs (no longer holding new claims since job 751; `cmd_ready` checks their Likely files); `parked_bigboy(k, by_id, live, root)` is a running BigBoy with no live child session.
- `cmd_ask(...)`: the only way a job becomes needs-human.
- `cmd_abort(...)` calls `abort_job(root, job, requeue, reason)`.
- `projects()`: registered repos that have a `scrum/` folder; `SCRUM_REGISTRY` overrides the registry path.
- Job-folder readers to reuse, never re-parse: `md_section(text, heading)`, `likely_files(spec_text)`, `job_files(d)`, `_round_text(folder, name)`; `.claude/` routing is `is_claude_path(path)` and `claude_split(root, job)`.

## serve.py (`skills/trevskills-scrum/serve.py`)
- `Handler.route(project, root, rest, body)`: the dashboard POST API (`/attachments`, `/manual-checks`, `/backlog`, job actions). When you add or remove a job action, check which branch an unmatched action reaches.
- `resume_refusal(project, root, job, manual=False)`: None or a `Refusal` (a str; `.blocker` set when a sibling blocks). It wraps the lilguy check, `board.machine_ok` and `board.resume_blocker`.
- Trevor's click carries `manual=True` through every launch hop: `resume_job`, `start_ready`, `spawn`, and a queued launch, which keeps it as `play_queued_manual` for `play_queue_tick`. A hop that drops it makes his click wait on the CPU gate. Grep every caller of the hop you change for `manual=`.
- `take_room()` spends one session of the watchdog tick's resume budget (`RESUME_ROOM`, None outside a tick); `spawn`'s own gate (`ram_room(floor=0)`, `MAX_LAUNCH_CPU_LOAD_PCT`) limits every launch.
- `rework_job(project, root, job_id, feedback)`, `abort_job(project, root, job_id, requeue, cascade=False)`, `auto_resume(project, root, jobs)`.
- `running(project, job_id)` only sees sessions serve.py started (its `RUNS` table); a liveness test also checks `board.session_alive_fn()`, as `parked_tree` does.
- `board_busy(project, root, jobs, by_id, alive)`: work in flight for auto-continue; it skips `finished_bigboy`, `parked_parent` and `parked_tree` parents.

## Tests
- `tests/test_board.py` covers board.py; `tests/test_serve.py` covers serve.py (`AutoResumeTest` covers `auto_resume`).
- Find a function's tests with `grep -n '<name>' tests/*.py`.

## dashboard.html (`skills/trevskills-scrum/dashboard.html`)
- One static file served by serve.py. Locate code by grepping element ids, CSS classes or function names, never line numbers.
- A new per-job field on a card: serve.py `board_with_activity` adds it (per-project data goes through `/api/projects`), dashboard.html `card`, `statusLine` or `tag` renders it, and a node-evaluated `tests/test_dashboard_<topic>.py` pins the render.
- The UI rules in `/Users/trevorhecht/Developer/repos/.claude/rules/ui-behaviour.md` apply to it.

