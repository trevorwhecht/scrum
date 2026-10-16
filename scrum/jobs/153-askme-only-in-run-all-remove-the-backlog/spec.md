# Askme only in Run all: drop the Backlog header Askme dropdown
UI surface: yes
Hard stops: none
Lane: standard

## Problem
The Backlog dialog header has an Askme dropdown (`#blAskme`, stored in localStorage `scrum.askme`). It only affects the per-item ▶ Run now button, which then opens an interactive Terminal per item. Trevor wants Askme to apply to a whole batch instead. Run now (▶) should always start the job headless. Run all should ask for an Askme level for that batch. When a level is picked, the one Run all Terminal session asks the questions for every item the triage left open, before any child job starts. It saves each item's answers to that child's `feature.md` under `## Q&A`, then runs the children as it does today.

## Scope
In:
- `skills/trevskills-scrum/dashboard.html`: remove the `#blAskme` select, its `#blAskmeLabel` label, its CSS selectors and the `scrum.askme` store get/set. The ▶ Run handler posts `{index}` only. Clicking Run all now shows an inline Askme picker (Off / 1 / 2 / 3) in place of the current armed "Run all?" confirm. Picking an option posts run-all with that level.
- `skills/trevskills-scrum/serve.py`: `POST /api/p/<project>/backlog/run-all` accepts an optional `askme` (1, 2, 3 or null/absent) with the same validation as `/backlog/run`. With a level it opens the Terminal with `/trevskills-scrum run-all askme <n>`.
- `skills/trevskills-scrum/SKILL.md`: document `run-all askme <1-3>` in the frontmatter description and the command list. Add an Askme step to **Run all** after `B runall-start` and before **BigBoy lane** step 2. Replace "Never ask questions here; there is no Askme step" with wording that allows only that step.
- Tests in `tests/test_serve.py` and `tests/test_contracts.py`, updated and added to match.

Out:
- The `/backlog/run` endpoint's `askme` parameter and the `start <id> askme <1-3>` / `askme [1-3] <feature>` CLI commands are left as they are (still documented and tested). Only the dashboard stops sending `askme` to `/backlog/run`.
- Remembering the last Run all Askme level across visits. The level is per batch.
- Asking questions inside child `start` sessions. Askme happens only in the Run all session.
- Any change to `board.py` (`runall-start`, `triage-*`, `ready`).

## Acceptance criteria
1. The Backlog dialog header no longer has an Askme dropdown. `dashboard.html` contains no `id="blAskme"`, no `blAskmeLabel` and no `"scrum.askme"`. The ▶ Run handler posts exactly `{index}` to `/backlog/run` (the source contains `post(\`${url}/run\`, {index})`), so Run now always starts headless and gets a 202. (verify: update `test_dashboard_has_askme_select` in `tests/test_contracts.py` into `test_dashboard_run_now_has_no_askme`, which asserts those strings are absent and the `{index}` post is present)
2. The first click on an enabled Run all button does not post anything. It shows a picker `<div id="blRunAllAskme" role="group" aria-label="Askme for this run">` with four buttons labelled `Off`, `1`, `2`, `3`, each at least 44x44 px. The Run all button's text becomes `Cancel`. Clicking the Run all button again hides the picker and restores `Run all` without posting. The picker is hidden on every dialog open, every project change and every finished call, everywhere `disarmRunAll()` runs today. (verify: contract test `test_dashboard_run_all_askme_picker` asserts the `blRunAllAskme` group with the four buttons and a `data-agent-hint`. Manual: open the Backlog, click Run all, check the picker shows, click Cancel, check it hides)
3. Clicking `Off` in the picker posts `{}` to `/backlog/run-all`. Clicking `1`, `2` or `3` posts `{askme: <n>}` as a number. While the call runs, all picker buttons and Run all are disabled. On success the dialog closes as it does today. (verify: contract test asserts the source contains `post(\`${url}/run-all\`, askme ? {askme} : {})` or an equivalent single expression named in the test. Manual: click `2` and check the Terminal window opens)
4. `POST /backlog/run-all` with `{"askme": 3}` returns 200 `{"message": "Run all opened in a new Terminal window."}`. Its osascript argv ends with `["env", "CLAUDE_NOTIFIER_DISABLE=1", CLAUDE, "/trevskills-scrum run-all askme 3"]`. With `{}` or `{"askme": null}` the argv still ends with `"/trevskills-scrum run-all"`. In all cases backlog.md is unchanged. (verify: `test_backlog_run_all_askme_opens_terminal` in `tests/test_serve.py`. The existing `test_backlog_run_all_opens_terminal` keeps passing)
5. `POST /backlog/run-all` with `askme` set to any of `0`, `4`, `"x"`, `"2"`, `true` or `2.0` returns 400 `askme must be 1, 2, 3 or null`. No Terminal opens (`subprocess.run` not called) and backlog.md is unchanged. The 409 `backlog is empty` check still applies when every item is done. (verify: `test_backlog_run_all_rejects_bad_askme` in `tests/test_serve.py`)
6. SKILL.md documents the batch Askme:
   - The frontmatter description and the command list name `run-all askme <1-3>`.
   - `## Run all` has an **Askme** step placed after `B runall-start` and before `**BigBoy lane** step 2`. It runs only for `run-all askme <n>`. It asks the questions in this same session for each child from `runall-start`'s `children`, in order, at the level semantics New job step 1c defines. It appends each child's pairs as `## Q&A` / `- Q: ` / `  A: ` to `$F/jobs/<child>/feature.md`.
   - When a child already had a pre-written `spec.md` and got at least one Q&A pair, the step deletes that `spec.md` so its spec is rewritten from the answers.
   - When Trevor says skip or stop, the answers given so far are written and the remaining children get no questions.
   - A bad or missing level means level 2.
   - The sentence "Never ask questions here; there is no Askme step" is gone.

   (verify: extend `test_skill_defines_run_all` in `tests/test_contracts.py` to assert `run-all askme`, `## Q&A` and `spec.md` inside the Run all section, and that the Askme step's index is between `B runall-start` and `**BigBoy lane** step 2`. The existing assertion that `scrum-spec-writer` is not in that section keeps passing)
7. The full suite passes. (verify: `python3 -m unittest discover -s tests -p 'test_*.py'`)

## Likely files
- `skills/trevskills-scrum/dashboard.html`: remove the `#blAskme` select, label and CSS (lines ~71, 92, 204, 741-742, 758-759). Add `<div id="blRunAllAskme" role="group" aria-label="Askme for this run" hidden>` holding four `<button type="button" data-askme="">Off</button>`, `data-askme="1"`, `"2"` and `"3"` buttons next to `#blRunAll`. Rework the `#blRunAll` click handler and `disarmRunAll()` so the picker shows and hides.
- `skills/trevskills-scrum/serve.py`: the `rest == "/backlog/run-all"` branch (~line 1960) validates `askme` like `/backlog/run` and appends ` askme <n>` to the command.
- `skills/trevskills-scrum/SKILL.md`: frontmatter description, the `run-all` command bullet (~line 144), and `## Run all` steps 4-6.
- `tests/test_serve.py`: new `test_backlog_run_all_askme_opens_terminal` and `test_backlog_run_all_rejects_bad_askme`. The `run_all` helper takes a body argument (default `{}`).
- `tests/test_contracts.py`: `test_dashboard_has_askme_select` (replaced), `test_dashboard_has_run_all_and_last_triage` (its `"Run all?"` phrase changes to the picker markers), `test_skill_defines_run_all` (extended).

## Assumptions
- The questions are asked after `B runall-start`, not before. Each child's job directory and `feature.md` exist only then. The children stay `waiting` and nothing starts until **BigBoy lane** step 3, so asking first is safe. "Triaged items" means the children `runall-start` created.
- The picker replaces the current two-click "Run all?" confirm. Picking a level is the confirmation, and the armed Run all button reads `Cancel`.
- `take_spec` can move a pre-written backlog spec into a child before Trevor answers. Spec rules say Q&A answers are Trevor's decisions, so a child that gets answers has its stale `spec.md` deleted. BigBoy lane step 2 (or the child's own `start`) then writes a fresh spec that includes the answers. Children with no answers keep their pre-written spec.
- Level semantics (1 only blockers, 2 moderate, 3 thorough) are the same as New job step 1c and apply to each item separately.
- The server keeps accepting `askme` on `/backlog/run` for CLI/API compatibility. Only the dashboard stops sending it.
- The level is not stored in localStorage. Every Run all picks again.

