VERDICT: PASS
## Findings
None.

## Notes
- codex: skipped — codex not installed (`command -v codex` printed nothing). Recorded once with `route.py record ... codex-review skip none 0 skipped`.
- I ran the criteria again myself: `python3 -m unittest discover -s tests -p 'test_board.py' -k resume_abort -k prod_check` ran 5 tests, OK. `-p 'test_contracts.py' -k not_resume_abort` ran 1 test, OK. check.md reports the full suite (3064 tests) OK.
- The `resume_abort_only` helper keeps `cmd_process_health`'s result unchanged. A non-dict option maps to `None`, which fails the `isinstance(c, str)` test, so it is not counted, exactly as the old inline `isinstance(o, dict) and ...` was. An empty list is still not counted.
- The CLI parses option commands with `partition("=")[2].strip()`, the same split `cmd_ask` uses (board.py ~6029). The exemptions are matched on the stripped question, the same text `cmd_ask` stores. Direct `cmd_ask` callers, such as serve.py:6158 (DIGEST Retry/Abort) and serve.py:6445 (Build it/Skip it), are not affected, as the spec's `Out:` requires.
- Ruling check: the option label is `File the fix as a follow-up` rather than the spec's `File a follow-up`. That is justified by `test_ask_labels_plain`. Adding the option to the `bigboy blocked` ask in commands.md is right: its question is `<its reason>`, which is not exempt, so the CLI would otherwise refuse it.
- The newjob.md size cap was raised from 26603 to 26740 to fit the three new options. The spec required those options, so this is acceptable.
- Minor taste: `test_ask_resume_abort_exempt_asks` only checks that the `reason` moved off `working`. Checking each ask's expected stage or reason would be stricter. Not blocking.
