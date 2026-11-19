STATUS: READY
## Summary
Added `checkout_rel(cwd)` to serve.py (git `rev-parse --show-prefix`, "" on failure or at root). The twin key in `stop_same_tests` is now (project, command, head, checkout_rel); the two later unpackings of the key were updated for the 4th element. Verified the committed diff against the spec; no fixes needed.

## Acceptance criteria
1. Twins grouped by (project, command, head, checkout-relative cwd); same command in different subdirectories is not a twin — verified by `cd tests && python3 -m unittest discover -s . -p 'test_serve_waste_reruns.py'` (test_different_subdirectories_not_twins) — PASS (21 tests OK)
2. Tests cover it — test_different_subdirectories_not_twins and test_checkout_rel_reads_git; also ran `test_serve_waste_hogs.py` — PASS (11 tests OK)

RED/GREEN: the implementation was committed before this run (1ae14a1); I did not observe a RED run. Not run: Typecheck/Lint (none for this Python repo; not run here).

## Rulings
- Ruling: checkout_rel returns "" when git fails — so a non-git cwd still groups as before — cost if wrong: two non-git runs in different subdirs would pair (they are already skipped when clean_head is None).

## Scrum map
- none

## Commits
- 1ae14a1 stop_same_tests: add checkout-relative cwd to the twin key
