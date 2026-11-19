STATUS: READY
## Summary
Artifacts home block in lanes/cloud.md now fetches into refs/scrum-home/$ID, checks the commit subject is exactly `[scrum $ID] artifacts`, and always drops the ref. Lead-in prose extended. Tests updated and added.
## Acceptance criteria
1. Block text and lead-in as spec — verified by `python3 -m unittest tests.test_contracts -k cloud` (test_skill_cloud_artifacts_come_home) — PASS
2. Incident case keeps branch, prints kept line, no ref — test_cloud_artifacts_home_block_runs (bash and zsh, /bin/zsh present) — PASS
3. Good path — same test — PASS
4. Missing branch with stale ref — same test — PASS
5. Legacy branch deleted — same test — PASS
Full tests/test_contracts.py (339 tests): OK. Typecheck/Lint: none.
## Rulings
- Ruling: tests were written together with the edit in one pass, not red-first — small contract change; the new test asserts literal expectations — cost: none of note.
## Scrum map
- none
## Commits
- 604385c Artifacts home fetches into a private ref, not FETCH_HEAD
