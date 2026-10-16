STATUS: READY
## Summary
Both UX and UI reviewers now have a third render outcome, `Rendered: blocked — <env reason>`, for renders the environment stopped. It is non-blocking: the verdict is PASS unless another finding blocks, and the review adds a `Manual smoke:` bullet under Out of scope. `Rendered: no` + `VERDICT: CHANGES` stays the outcome for render failures the diff causes. A review with `Rendered: blocked` means the round is never clean (SKILL.md Review step 5). The approver ESCALATEs with `Hard stop: blocked — UI not rendered (environment)` and does not REWORK when the only render evidence is blocked.

Tests were written first. RED: `python3 -m unittest tests.test_contracts`, which gave `FAILED (failures=3, skipped=2)` (test_approver_requires_rendered_ui, test_reviewers_rendered_blocked_non_blocking, test_skill_clean_round_skips_approver, all failing on missing `Rendered: blocked` text). GREEN: `Ran 145 tests ... OK`.

## Acceptance criteria
1. Both reviewers define `Rendered: blocked — <env reason>` as non-blocking, with PASS and a `Manual smoke:` bullet — verified by test_reviewers_rendered_blocked_non_blocking — PASS
2. `Rendered: no` and CHANGES are kept for diff-caused failures. The wording is now "Never PASS a UI diff you did not render unless it is Rendered: blocked" — verified by assert_reviewer_renders (ux/ui) and test_reviewers_rendered_blocked_non_blocking — PASS
3. In UX the harness fallback comes first ("Only when the harness above also could not render the new element"). The harness sentence is unchanged byte-for-byte — verified by test_review_ux_ui_digest_rules, plus a new index-order assertion — PASS
4. The template `Rendered:` alternative line now lists `Rendered: blocked — <env reason>` in both files — verified by test_reviewers_rendered_blocked_non_blocking — PASS
5. SKILL.md Review step 5 has a new clean-round bullet that excludes `Rendered: blocked` — verified by test_skill_clean_round_skips_approver (extended) — PASS
6. The approver's **UI must be rendered.** rule has an exception that ESCALATEs with `UI not rendered (environment)` and routes manual smoke to `## Manual checks` — verified by test_approver_requires_rendered_ui (extended) — PASS
7. Full suite: `python3 -m unittest discover -s tests` gave `Ran 667 tests ... OK (skipped=2)` — PASS. The project has no typecheck, lint or build commands.

## Rulings
- Ruling: in the reviewer prose, the Manual smoke bullet is described as going to "the output's `Out of scope` section" rather than written as the literal `## Out of scope` — the existing test_reviewers_document_out_of_scope requires the first `## Out of scope` to come after `## Notes` (in the template) — cost if wrong: none, since the meaning is the same.
- Ruling: the approver exception also says a `Rendered: blocked` line never counts as `Rendered: yes`, which is the spec's assumption made explicit — cost if wrong: one extra sentence.

## Commits
- 709be8e Make environment-blocked renders non-blocking and route them to the approver
