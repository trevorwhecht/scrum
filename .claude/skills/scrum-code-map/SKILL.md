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
- `machine_ok(path, manual=False, claim=False)`: None when there is room, else the reason. Order: cool-down (`COOLING`, only when `claim` and not `manual`), free RAM, swap, free disk, CPU busy (skipped when `manual`; `MAX_CPU_BUSY_PCT`, the mean of the last 3 `top` samples the serve.py watchdog records via `record_cpu_sample`), session ceiling. Gates new claims, resumes and auto-continue starts only; cool-down holds only new work (claim=True: Run-all child claims, auto-continue, `/api/machine`), and `next` (no index), `runall-start`, `cloud-claim` and `roadmap-next` check `cooling_down()` themselves.
- `resume_blocker(root, job_id, live=())`: a `Blocker` (a str with `.ids`) when a sibling child holds overlapping files.
- `session_alive_fn()`: the live-session check; tests mock it.
- `cmd_ask(...)`: the only way a job becomes needs-human.
- `cmd_abort(...)` calls `abort_job(root, job, requeue, reason)`.
- `projects()`: registered repos that have a `scrum/` folder; `SCRUM_REGISTRY` overrides the registry path.

## serve.py (`skills/trevskills-scrum/serve.py`)
- `Handler.route(project, root, rest, body)`: the dashboard POST API (`/attachments`, `/manual-checks`, `/backlog`, job actions). When you add or remove a job action, check which branch an unmatched action reaches.
- `resume_refusal(project, root, job, manual=False)`: None or a `Refusal` (a str; `.blocker` set when a sibling blocks). It wraps the lilguy check, `board.machine_ok`, `heavy_refusal` (`board.usage_heavy_wait`: at `USAGE_HEAVY_PCT` used only light lanes start) and `board.resume_blocker`.
- `rework_job(project, root, job_id, feedback)`, `abort_job(project, root, job_id, requeue, cascade=False)`, `auto_resume(project, root, jobs)`.

## Tests
- `tests/test_board.py` covers board.py; `tests/test_serve.py` covers serve.py (`AutoResumeTest` covers `auto_resume`).
- Find a function's tests with `grep -n '<name>' tests/*.py`.

## dashboard.html (`skills/trevskills-scrum/dashboard.html`)
- One static file served by serve.py. Locate code by grepping element ids, CSS classes or function names, never line numbers.
- The UI rules in `/Users/trevorhecht/Developer/repos/.claude/rules/ui-behaviour.md` apply to it.

