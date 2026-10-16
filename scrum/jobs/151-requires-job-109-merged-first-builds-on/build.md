STATUS: READY

## Summary
Added the `trevskills-e2e` skill (the whole E2E flow: find command, map changed files to routes, replay saved specs, cover uncovered changed UI, failure triage into real bug / stale test / flake, Jev yes/no questions, token rules, report) and the `scrum-review-e2e` agent (sonnet, loads the skill via `skills:` frontmatter, writes `round-N/review-e2e.md`). `install.sh` links the new skill with the same refuse-first pattern. `board.py sync` folds an optional `review-e2e.md` into `verdict`/`invalid` and returns a new `e2e` key; `REVIEWERS` and board.json `reviews` are unchanged. `trevskills-scrum/SKILL.md` wires the agent into Check gate step 4 (triage on E2E failure before resuming the builder) and Review steps 3–5. README mentions both.

## Acceptance criteria
1. Skill file with frontmatter and the 8 documented steps in order — verified by `tests.test_contracts.ContractTest.test_e2e_skill_contract` (also checks the 8 headings appear in order) — PASS
   RED: `ERROR: test_e2e_skill_contract ... FileNotFoundError: .../skills/trevskills-e2e/SKILL.md` / GREEN: `Ran 306 tests ... OK (skipped=2)` (board+install+contracts)
2. `never` + assertion line, `never` + key line — verified by `test_e2e_skill_contract` — PASS
3. Agent file frontmatter/body — verified by `test_frontmatter`, `test_first_line_contracts_are_documented`, `test_every_agent_forbids_migrations_and_merges`, `test_skill_references_every_agent_and_board_command`, `test_exactly_the_expected_agents_exist` (AGENTS/FIRST_LINE extended), and new `test_e2e_agent_loads_skill` — PASS
   RED: `ERROR: test_e2e_agent_loads_skill ... FileNotFoundError: .../agents/scrum-review-e2e.md`, `FAIL: test_exactly_the_expected_agents_exist` / GREEN: OK
4. Install links `trevskills-e2e`, rerunnable, refuses real dir and links nothing — verified by extended `test_install_links_skill_and_agents_and_is_rerunnable` and new `test_install_refuses_to_clobber_real_e2e_skill_dir` — PASS
   RED: both `FAIL` / GREEN: OK
5. Orchestrator spawn rules (Check gate step 4, Review step 3, never without `E2E:`) — verified by new `test_skill_wires_e2e_reviewer` plus unchanged `test_skill_e2e_hook` — PASS
   RED: `FAIL: test_skill_wires_e2e_reviewer` / GREEN: OK
6. Sync reads optional `review-e2e.md` — verified by `test_sync_e2e_changes_overrides_pass`, `test_sync_e2e_absent_is_not_missing`, `test_sync_e2e_invalid` — PASS
   RED: `FAIL: test_sync_e2e_changes_overrides_pass` (verdict PASS != CHANGES), `ERROR ... KeyError: 'e2e'` for the other two / GREEN: OK
7. Missing `review-e2e.md` after one re-spawn → orchestrator writes `VERDICT: CHANGES` + `Reviewer produced no output.` — new bullet in Review step 4; verified by `test_skill_wires_e2e_reviewer` (asserts `review-e2e.md` in the Review section) — PASS
8. Full suite and README — `python3 -m unittest discover -s tests` → `Ran 673 tests in 102.180s OK (skipped=2)`, exit 0 — PASS. `grep -n e2e README.md` shows `trevskills-e2e` on the install line and `scrum-review-e2e` on the Agents line.

Typecheck / Lint / Build: `none` in PROJECT. No UI globs (`*.html *.css`) touched, so no browser walkthrough needed.

## Rulings
- Ruling: `board.py sync` returns an extra `"e2e"` key (PASS|CHANGES|INVALID|None) — the spec's Likely files suggested it; no test compares the whole dict — cost if wrong: one extra JSON key in sync output.
- Ruling: an e2e review counts toward `verdict` only when the four core reviews are complete; with core reviews incomplete, verdict stays `None` as today — keeps absent/incomplete behaviour identical — cost if wrong: none observable, the orchestrator re-syncs after re-spawns.
- Ruling: in Check gate step 4, the e2e triage message is `Triage the failing E2E run. Write only your own review file.`; Review step 3 overwrites any triage file in the same round — avoids a stale check-gate verdict leaking into the review verdict — cost if wrong: one extra e2e run per round with a failed E2E check.
- Ruling: the orchestrator handles a missing `review-e2e.md` itself (not via `missing`), since sync never reports it — keeps criterion 6's "never in missing" while satisfying criterion 7.
- Ruling: the agent may commit its new/updated spec files in WORKTREE — it has Edit/Write limited to the E2E directory and the builder must see added specs — cost if wrong: reviewer commits on the job branch; drop the commit line.
- Ruling: Jev POST body is `{"model": "jev-latest", "question": ...}` with a Bearer header — spec names model and question but not the exact field names or auth header — cost if wrong: the POST fails and the skill falls back to reading the output, as specified.
- Ruling: `test_e2e_skill_contract` additionally asserts the 8 numbered headings appear in order — criterion 1 says "in this order" — cost if wrong: renaming a heading needs a test edit.

## Commits
- 98fab8d Add trevskills-e2e skill and scrum-review-e2e agent
