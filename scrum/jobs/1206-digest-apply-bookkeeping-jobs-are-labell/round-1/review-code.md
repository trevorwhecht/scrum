VERDICT: PASS
## Findings
## Notes
- codex: skipped — codex not installed (`command -v codex` printed nothing; no router call made, skip recorded in routing.log).
- All 5 acceptance criteria are implemented and backed by tests that went from RED to GREEN, as build.md records. check.md shows the full suite passing (3067 tests, exit 0).
- A side effect the spec accepts: digest_apply jobs used to be `hand`, and `write_pulse` skips hand jobs before the `by_acc` per-account count (the `if hand: continue` in board.py). Now they are `digest`, so they add to `by_acc`. The spec's `## Assumptions` chooses this ("the `by_acc` per-account count still includes digest jobs"), so it is not a finding.
- The "Other starts while CPU load over 500%" check: a digest job used to land in the `hand` group and now lands in `other`. The spec keeps that group's logic unchanged, and build.md's first Ruling records this. Taste only.
- serve.py:333 start gate (`started_by in ("serve", "runall", "shop")`): `digest` is not in that tuple, and neither was the old `hand`, so gate behaviour does not change, as the spec's `Out:` requires.
- The separate `digest` flag (rather than folding digest into `shop`) is right: `shop` also gates the CPU-over-500% group, which the spec keeps unchanged.
