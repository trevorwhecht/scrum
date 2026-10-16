# Environment-blocked renders stop costing a rework round
UI surface: no
Hard stops: none
Lane: standard

## Problem
`agents/scrum-review-ux.md` and `agents/scrum-review-ui.md` (paragraph after render step 5) say that whenever the reviewer "could not render or exercise the page" it writes `Rendered: no — <reason>` and returns `VERDICT: CHANGES` with a `[blocking]` finding at confidence 100. That covers failures caused by the environment as well, such as the dev server not starting or the DB being unreachable. The builder can't fix those, so the job burns a rework round. Environment-blocked renders should not block. They should still never count toward a **clean round**, so the approver always rules on them.

## Scope
In:
- Both reviewer agents: add a third render outcome, `Rendered: blocked — <env reason>`. Use it only when the environment, not the diff, prevented rendering. It gives `VERDICT: PASS` (unless other blocking findings exist) and adds a manual-smoke bullet under `## Out of scope`.
- Both reviewers keep `Rendered: no — <reason>` + `VERDICT: CHANGES` `[blocking]` for renders that fail because of the diff.
- `skills/trevskills-scrum/SKILL.md` **Review** step 5: add a clean-round condition that excludes any round where a review contains `Rendered: blocked`.
- `agents/scrum-approver.md` **UI must be rendered.** rule: when the only render evidence is `Rendered: blocked`, ESCALATE instead of using REWORK.
- `tests/test_contracts.py`: assertions for all of the above.

Out:
- Automatically detecting environment failures, or retrying the render.
- Any change to `board.py`/dashboard parsing of review files.
- Changing the `Rendered: yes` formats or the UX harness fallback.

## Acceptance criteria
1. `agents/scrum-review-ux.md` and `agents/scrum-review-ui.md` each define `Rendered: blocked — <env reason>` for this case: the server or DB could not be reached or started, and the cause is not a defect in the diff. In that case the reviewer writes `VERDICT: PASS` (unless another finding is `[blocking]` with confidence ≥ 80) and one `## Out of scope` bullet that begins `Manual smoke:` and names the page and the new element to check. Each file contains the exact phrase `Rendered: blocked — <env reason>` and states that it is non-blocking. (verify: new `test_reviewers_rendered_blocked_non_blocking` in `tests/test_contracts.py` asserts, for both files, `"Rendered: blocked — <env reason>"`, `"Manual smoke:"` and `"non-blocking"` are present)
2. In both reviewers, `Rendered: no — <reason>` stays the outcome when the page failed to render, or the new element (or expected change) was not visible, for a reason inside the diff. It is still `VERDICT: CHANGES` with a `[blocking]` finding (confidence 100). `Never PASS a UI diff you did not render` is reworded so it allows the blocked case. The new wording keeps the substring `Never PASS a UI diff you did not render` and adds `unless it is Rendered: blocked`. (verify: existing `assert_reviewer_renders` still passes; the new test asserts `"Rendered: no"` and `"VERDICT: CHANGES"` remain in both files)
3. In `scrum-review-ux.md` the existing throwaway-harness fallback comes first. `Rendered: blocked` is allowed only when the harness also could not render the element. The existing harness sentence stays byte-for-byte, so `test_review_ux_ui_digest_rules` passes unchanged. (verify: `python3 -m unittest tests.test_contracts`)
4. Both output templates list `Rendered: blocked — <env reason>` as an alternative `Rendered:` line, next to the existing `Rendered: no — <reason>` alternative. (verify: new test asserts the template line containing `Rendered: no — <reason>` also contains `Rendered: blocked — <env reason>` in both files)
5. `skills/trevskills-scrum/SKILL.md` **Review** step 5's clean-round list gets one more bullet: no `round-1/review-*.md` contains a line starting `Rendered: blocked`. As a result, such a round always goes to **Approve**. (verify: new assertion in `test_skill_clean_round_skips_approver` that the `## Review (WAIT FOR ALL)` section contains `Rendered: blocked`, and that it appears between `A clean round is one where every one of these holds` and `**Approve**`)
6. In `agents/scrum-approver.md`, the **UI must be rendered.** rule stays the same when no review has a qualifying `Rendered: yes`, with one exception. If at least one latest-round review has `Rendered: blocked` and none has `Rendered: no`, the approver does not REWORK. It ESCALATEs with `Hard stop: blocked — UI not rendered (environment)` and lists the manual smoke under `## Manual checks`. (verify: `test_approver_requires_rendered_ui` extended to assert `Rendered: blocked` and `UI not rendered (environment)` appear in the `**UI must be rendered.**` line)
7. The full suite passes. (verify: `python3 -m unittest discover -s tests`)

## Likely files
- `agents/scrum-review-ux.md`: paragraph after render step 5, output template, possibly the Rules list
- `agents/scrum-review-ui.md`: same places
- `skills/trevskills-scrum/SKILL.md`: **Review** step 5 clean-round bullet list
- `agents/scrum-approver.md`: `**UI must be rendered.**` line
- `tests/test_contracts.py`: new `test_reviewers_rendered_blocked_non_blocking(self)`; extend `test_skill_clean_round_skips_approver` and `test_approver_requires_rendered_ui`

## Assumptions
- "Environment-blocked" means the reviewer could not start the fresh server from WORKTREE, Chrome could not launch, or a required DB or session backend was unreachable, and the cause is not a crash introduced by the diff. A server that fails to start because of a traceback in changed files counts as `Rendered: no` (blocking).
- The manual-smoke line lives in `## Out of scope` as feature.md says. The approver's existing **Manual checks** rule routes it to `## Manual checks` rather than to `## Follow-ups`.
- Without criterion 6, the approver's current rule would REWORK a job whose only render evidence is `Rendered: blocked`. That is exactly the rework round this feature removes. "The approver still rules" is therefore read as: the approver decides, and on an environment block its decision is ESCALATE to a human (a manual smoke), not REWORK. The UI-render guard is not loosened into an APPROVE.
- A `Rendered: blocked` review never counts as a `Rendered: yes` for the approver.
- Change size is about 5 files and under 100 lines, but 5 files exceeds the fast-lane limit, so the lane is `standard`. The touched files are Markdown and a Python test, none of which matches the UI globs, so `UI surface: no`.
