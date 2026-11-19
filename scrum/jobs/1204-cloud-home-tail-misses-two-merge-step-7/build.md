STATUS: READY
## Summary
Cloud-home tail paragraph in lanes/cloud.md now runs Merge step 7 Scrum map, then BigBoy chaining for a job with a parent, after Fast-forward main and before B digest-due, for a done job only. Pinned in test_skill_cloud_lane.
## Acceptance criteria
1. Scrum map after Fast-forward main, before digest-due — `python3 -m unittest tests.test_contracts` — PASS
2. BigBoy chaining order and parent condition — same command — PASS
3. Inside the `When the job is done` paragraph (test slices that line) — same command — PASS
4. Existing Step 7 cloud-session line untouched (not edited) — same command — PASS
## Rulings
- Ruling: wrote the test and the edit in one pass, no RED run — doc-only change with a pin test — cost: none.
- Ruling: no other test referenced `When the job is` (grep tests/ returned only the new test).
## Scrum map
- none
## Commits
- Cloud-home tail runs Merge step 7 Scrum map and BigBoy chaining for a done job
