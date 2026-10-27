---
name: scrum-digest-flow
description: Load before speccing or building a change to the digest flow (serve.py digest_* functions, lanes/digest.md, agents/scrum-digester.md, the dashboard Digest dialog, DigestTest). Names the lifecycle and helpers the scrum keeps re-deriving.
---

# Digest flow

Find each name with `grep -n '<name>'`; never trust a line number. Every serve.py function below has a docstring: read it first.

## Files
- `skills/trevskills-scrum/lanes/digest.md`: the orchestrator steps (digest-start, reader, digester, `serve.py --digest-auto`).
- `agents/scrum-digest-reader.md` writes `scrum/digests/<NNN>/notes.md`; `agents/scrum-digester.md` writes `proposals.json`.
- `skills/trevskills-scrum/serve.py`: everything after the `# --- Digest:` comment.
- `skills/trevskills-scrum/board.py`: `cmd_digest_due`, `cmd_digest_start`, `cmd_digest_trim`, `cmd_digest_verify` (the Merge agent rules guard uses verify).

## Proposal shape
- `proposals.json` is agent-written and untrusted.
- `valid_proposal(p)`: keys `PROPOSAL_KEYS` (id, target, why, old, new), all strings, `old != new`, id matches `PROPOSAL_ID_RE`.
- `kind` is `edit` (default) or `skill`; a skill has empty `old` and frontmatter, at most `SKILL_MAX_LINES` lines.
- `status` is one of `PROPOSAL_STATUSES`; a missing status reads as `pending`. An optional `reason` string is kept.

## Lifecycle
- The digester writes every proposal as `pending`.
- `digest_auto(root, digest_id)` (the `--digest-auto` CLI) moves every pending one to applied, queued or skipped, then the digest is trimmed:
  - skill: `digest_queue_skill` queues a backlog item (`queued`, reason `new skill`), or `skipped` when the target is not creatable or exists.
  - settings or hooks target (`digest_denied`): `skipped`.
  - target inside a registered repo (`repo_of`): grouped per repo into `digest_apply`.
  - any other target: `digest_write_global` (only an editable AI-Settings item, backed up by `ai_backup`, written in place).
- `digest_apply(root, digest_id, props, title, feature, mark_applied)`:
  - refuses the whole repo when `digest_apply_ready` gives a reason (not a checkout, detached HEAD, dirty outside scrum/, no tests/test_contracts.py);
  - fetches origin and queues everything when the fetch fails (`fetch failed: ...`) or local `<branch>` is ahead of origin;
  - applies in a temporary detached worktree at `origin/<branch>`, so the main checkout is never written: per proposal, old text must occur once there, write, run `tests.test_contracts` (`digest_contract_ok(wt)`), restore the bytes on failure;
  - commits the passing ones in the worktree under one lilguy board job, `[scrum <job>] <title>`, and pushes it to `origin/<branch>`; a commit or push failure queues them all and asks;
  - then fast-forwards the main checkout after the Merge guard (on `<branch>`, no tracked changes); when that fails the edits stay applied and the job is done with `merged, not live: <why>`;
  - always removes the temporary worktree.
- In `digest_auto`, an `old text found N times` result is `skipped`; any other unapplied repo edit becomes a backlog item via `digest_queue_repo_edit` (`queued`).
- Backlog items carry a pre-written spec from `digest_item_spec`; `queue_digest_item` writes the spec before the backlog line.
- `digest_skill_check` re-checks a queued skill before its backlog job creates the file.

## Statuses and the lock
- `DIGEST_LOCK` is one `threading.Lock` in serve.py.
- `digest_set_statuses(root, digest_id, updates, from_status="pending")` changes only entries still at `from_status`, writes tmp + `os.replace`, and trims once nothing is pending. The caller holds `DIGEST_LOCK`.
- `digest_mark_applied` takes the lock and sets pending to applied.
- `digest_revert(root, digest_id, pid)`: only an `applied` proposal; swaps old and new and re-applies through `digest_apply` (repo, `mark_applied=False`, its own `Revert digest` job) or `digest_write_global`; then sets `reverted` from `applied` under the lock.
- Any read-modify-write you add re-checks the live status under `DIGEST_LOCK` right before writing.

## Weekly
- The cross-project weekly digest lives in `board.weekly_dir()` (`~/.claude/trevskills-scrum/weekly/<NNN>/`, beside `projects.json`; `SCRUM_REGISTRY` moves both). It never touches a project's `scrum/digests/`.
- `board.cmd_weekly_start(resets_at, now)` claims, under `registry_lock()`, every registered project's done jobs updated in the 7d window that no earlier `weekly/*/jobs.txt` lists; it writes `window` (the integer `resets_at`) even when none qualify. `board.weekly_ran(resets_at)` reads those markers.
- serve.py `weekly_tick()` (watchdog, after `window_tick()`) runs it in the last `board.WEEKLY_LATE_SECS` of the window, only when `board.fable_ok`, once per window, and spawns `/trevskills-scrum weekly-digest <NNN>` in `research_home()`'s project.
- `lanes/digest.md` `## Weekly` runs `scrum-digester` (**Weekly mode**, `WEEKLY_DIR`) on `board.FABLE_MODEL` with no Opus fallback, then `serve.py --weekly-ask <NNN>`.
- serve.py `weekly_ask(digest_id)` parks one needs-human job (`cmd_new(unique=True)`, `digest_item_spec(f"weekly-{NNN}", ...)`, `cmd_ask` with Build it / Skip it) per pending repo edit and marks it `queued`; anything else is `skipped`. `weekly_set_status` re-reads under `DIGEST_LOCK`. No target file is written.
- `lanes/commands.md` resume sends a `Weekly digest ` reason to **New job** step 2.
- Tests: `tests/test_board.py` `WeeklyStartTest`, `tests/test_serve.py` `WeeklyTest`.

## HTTP (serve.py `Handler.route`)
- `GET /api/p/<project>/digests` lists digests (`digests()`).
- `POST /api/p/<project>/digest` starts one (`digest_now`; 409 when running or nothing new).
- `POST /api/p/<project>/digests/<id>/<pid>` with `{"decision": "revert"}` calls `digest_revert`.

## Tests
- `tests/test_serve.py` `DigestTest` runs on the `AiSettingsTest` fake home; the registered project is `reg`.
- Its helpers: `done_job`, `digest(proposals, digest_id, jobs)`, `prop(pid, target, old, new, **extra)`, `revert(pid)`, `statuses()`, `rule(text)` (a global rules file).
- `board.merge_refusal` is mocked in its setUp so fixture jobs can go done.
- `tests/test_contracts.py` pins wording in lanes/digest.md and the digester agent: grep the phrase before rewording.

