VERDICT: PASS
## Findings
No findings.

## Notes
- codex: skipped — codex not installed
- checkout_rel follows the clean_head pattern (same board._git and the same exceptions). The key change and both unpackings are consistent. Tests cover different subdirectories and the real git prefix.
- checkout_rel runs once per run line (a git call each), same cost class as clean_head; acceptable.
