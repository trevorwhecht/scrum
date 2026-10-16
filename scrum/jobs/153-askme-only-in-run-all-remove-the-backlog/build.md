STATUS: READY

## Summary
Askme moved from the per-item Run now to the whole Run all batch.
- dashboard.html: the `#blAskme` select, its `#blAskmeLabel` label, its CSS and the `scrum.askme` store get/set are gone. The ▶ Run handler posts `{index}`. The first click on Run all shows the `#blRunAllAskme` picker (Off/1/2/3) and turns the button into `Cancel`. A second click hides it. Picking a level posts `askme ? {askme} : {}` to `/backlog/run-all` and disables the picker and Run all while the call runs. `disarmRunAll()` hides the picker and re-enables its buttons, and still runs on dialog open, project change and every finished call.
- serve.py: `/backlog/run` and `/backlog/run-all` now share the askme check (`askme must be 1, 2, 3 or null`). Run all with a level opens `/trevskills-scrum run-all askme <n>`.
- SKILL.md: the frontmatter and command list now include `run-all askme <1-3>`. Run all has a new step 5 **Askme**, between `B runall-start` and BigBoy lane step 2, which asks for each child, writes `## Q&A` to `feature.md`, deletes a pre-written spec.md when there are answers, and handles skip/stop and level 2 as the default. The "there is no Askme step" sentence is gone. Old steps 5-6 are now 6-7.

## Acceptance criteria
1. No Askme dropdown; Run now posts `{index}`. Verified by `test_dashboard_run_now_has_no_askme`. RED: `AssertionError: 'id="blAskme"' unexpectedly found`. GREEN: OK. Also seen in headless Chromium: the ▶ Run double-click posted `{"index":0}` and `#blAskme` count was 0. PASS
2. Picker shows on the first click, the button reads Cancel, Cancel hides it, and no post is sent until a level is picked. Buttons are 44x44. Verified by `test_dashboard_run_all_askme_picker`: RED `AssertionError: unexpectedly None`, then GREEN OK. Also checked with a headless Chromium script at 1280 and 375 px wide. Picker hidden before the click. After the click: text `Cancel`, picker visible, 0 posts, each button 44x44. After Cancel: `Run all`, picker hidden, 0 posts. Reopening the dialog after a run shows it hidden. PASS
3. Off posts `{}`, and 1/2/3 post `{askme:n}` as a number. Verified by the same contract test asserting ``post(`${url}/run-all`, askme ? {askme} : {})``. In the browser: clicking `2` posted `{"askme":2}` and clicking `Off` posted `{}`. During the call Run all and all 4 picker buttons were disabled. On success the dialog closed. The POSTs were intercepted, so no real Terminal was opened. PASS
4. Run all with askme 3 opens the right argv, and `{}` or null give a plain `run-all`. Verified by `test_backlog_run_all_askme_opens_terminal`. RED: argv ended `'/trevskills-scrum run-all'` instead of `... askme 3`. GREEN: OK. `test_backlog_run_all_opens_terminal` still passes. PASS
5. Bad askme values return 400, no Terminal opens and backlog.md is unchanged. The 409 still applies. Verified by `test_backlog_run_all_rejects_bad_askme`. RED: got `(200, ...)` instead of 400. GREEN: OK. PASS
6. SKILL.md documents the batch Askme. Verified by the extended `test_skill_defines_run_all`. RED: `'there is no Askme step' unexpectedly found`. GREEN: OK. The `scrum-spec-writer` absence check still passes. PASS
7. Full suite: `python3 -m unittest discover -s tests -p 'test_*.py'` ran 669 tests, `OK (skipped=2)`, exit 0. PASS

Typecheck, lint and build are "none" in project.md.

## Rulings
- Ruling: askme is validated before the 409 empty-backlog check on run-all, the same order as `/backlog/run` — a bad request is rejected whatever the backlog holds — cost if wrong: a bad askme on an empty backlog gets 400 instead of 409.
- Ruling: the Askme step does not "record your terminal" on the Run-all parent — Run all never recorded one, and the hooks that read the tty mark a job `waiting`, which could disturb the parent's stage — cost if wrong: the dashboard won't show the Run all session as waiting on Trevor while it asks.
- Ruling: the picker buttons keep the spec's bare `<button type="button" data-askme>` markup and get the 13px/44px look from `#blRunAll,#blRunAllAskme button` — this reuses the existing Run all rule — cost if wrong: they look a little lighter than `.btn`.
- Ruling: at 375 px the armed header squeezes the project select down to its arrow until Cancel or a pick, with no horizontal overflow (scrollWidth 375) — this only happens during the one-step confirm — cost if wrong: the project can't be changed while armed without pressing Cancel first.
- Ruling: Askme is renumbered as Run all step 5, and old steps 5-6 become 6-7 — the step has to sit between runall-start and BigBoy step 2. No other file refers to Run all step numbers — cost if wrong: none found.
- Ruling: the `start <id> askme` bullet in SKILL.md still says the dashboard's Run now sends it, because the spec's Out list says to leave it — cost if wrong: that one sentence is slightly stale.

## Commits
- 9ce2fa4 Move Askme from Run now to a per-batch Run all picker
