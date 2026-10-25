# Routing for Trevskills Scrum

Every scrum agent runs on cloud Claude. `local/route.py` only decides whether the code reviewer's
Codex step runs or is skipped, and logs what ran.

## How routing decides

`python3 local/route.py <role> [--job JOB_DIR] [--scrum DIR]` prints `{"runner", "model", "why"}`:

- **`codex-review`** answers `skip` when the `codex` binary is not installed (`PATH` plus
  `/opt/homebrew/bin`), or when the newest `~/.codex/sessions/**/rollout-*.jsonl` reports the
  5h window at `codex_5h` (85) % used or more, or the weekly window at `codex_weekly` (90) % or
  more. Otherwise it answers `cloud`.
- **Every other role** answers `cloud`.

## Logging

`python3 local/route.py record JOB_DIR <role> <cloud|skip> <model> <seconds> <outcome>` appends one
JSON line (`ts`, `role`, `runner`, `model`, `duration_s`, `outcome`) to `JOB_DIR/routing.log`. Any
other runner exits 2. The digest reader logs to `scrum/routing.log`. The dashboard shows one tag per
line on the job's card.

## Status

`python3 local/route.py status [--scrum DIR]` prints the Codex quota (`codex`: `5h`, `weekly`) and
`claude_exhausted_until`, the latest future reset from a Claude session-limit line in `scrum/runs/`.
The dashboard header shows it (`GET /api/routing-status`).

## routing.json

`routing.json` holds only `thresholds`: `codex_5h` and `codex_weekly`, in percent used.

`.agents/skills/trevskills-scrum` is the committed symlink that lets Codex discover the scrum
skill from this repo.
