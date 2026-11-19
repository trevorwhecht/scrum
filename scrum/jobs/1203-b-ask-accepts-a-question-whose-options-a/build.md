STATUS: READY
## Summary
- `board.py` now has one helper, `resume_abort_only(commands)`. It is true when the list is non-empty and every command starts with `resume ` or `abort `. `cmd_process_health` uses it in place of its inline test.
- The CLI `ask` branch of `main` runs a new check right after the `unreadable_question` check. When every `--a/--b/--c` command is resume or abort, it refuses with exactly `ask refused: add a followup <id> "<fix>" option, or run B wait-on <id> <blocker> instead of asking`. It does not refuse an ask whose question matches `is_guard_ask`, `QUEUE_ASK_RE.match`, `CI_BILLING_RE.search` or `AGENT_TYPES_RE.search`. Direct `cmd_ask` calls are not affected.
- Audit: I scanned every `` `B ask ...` `` code span in SKILL.md, lanes/*.md and agents/*.md, including spans that run over more than one line. Four non-exempt asks offered only resume and abort, and each now has `--c "File the fix as a follow-up=followup $ID \"<fix>\""` (the commands.md one uses `<id>`):
  - `lanes/newjob.md` step 2: the malformed Base branch line ask
  - `lanes/newjob.md` step 2: the Base branch not found on origin ask
  - `lanes/newjob.md` Check gate step 2: the local database down ask
  - `lanes/merge.md` step 5: the merge conflict after 2 tries ask
  - `lanes/commands.md` resume: the `bigboy blocked` ask
- The exempt asks keep only resume and abort: SKILL.md Wrong branch and Unpushed commits, merge.md CI billing, newjob.md and unblock.md `waiting on the E2E queue`.

## Acceptance criteria
1. A CLI ask offering only resume and abort raises SystemExit with the exact message. The job's stage stays unchanged, it gets no `question`, and no questions.log line is written. Verified by `test_ask_refuses_resume_abort_only`, run with `python3 -m unittest discover -s tests -p 'test_board.py' -k resume_abort -k prod_check_title`.
   - RED: `AssertionError: SystemExit not raised`
   - GREEN: `Ran 5 tests ... OK`
   - Result: PASS
2. The same ask parks when it also offers a followup, approve or rework option. Verified by `test_ask_accepts_resume_abort_with_other_option`, same command.
   - This test passed before the change too, because it guards against refusing too much.
   - Result: PASS
3. The exempt asks (guard `Unpushed commits in repo: x`, `waiting on the E2E queue` in check, CI billing) are not refused. Verified by `test_ask_resume_abort_exempt_asks`, same command.
   - It passed before the change (it guards against refusing too much) and still passes after it.
   - Result: PASS
4. `cmd_process_health` uses the helper and its result is unchanged. Verified with `python3 -m unittest discover -s tests -p 'test_board.py' -k ProcessHealthTest -k process_health -k resume_abort -k test_ask_ -k unreadable -k followup -k ask_cli -k billing -k queue`, which ran 93 tests: OK. PASS
5. Every non-exempt `B ask` keeps an option that is not resume or abort. Verified by `test_ask_lines_not_resume_abort_only` in tests/test_contracts.py.
   - RED, with the lane edits stashed: `FAILED (failures=1)`, first on `commands: B ask <id> '<its reason>' --a "Carry on=resume <id>" ...`
   - GREEN: `python3 -m unittest discover -s tests -p 'test_contracts.py'` ran 340 tests: OK.
   - Result: PASS

Other focused runs, each `python3 -m unittest discover -s tests -p '<file>'`, all OK:
- test_backlog
- test_edit_check
- test_merge_migrate_prod_status
- test_jev_model_gaps
- test_shop_merged_pr_spelling
- test_shop
- test_verify_follows_redirect

These are the test files that mention the changed lane files or functions. `ruff check --select F` on the changed .py files reports no findings. The project lists Typecheck and Lint as `none`.

## Rulings
- Ruling: The option label is `File the fix as a follow-up`, not the spec's `File a follow-up`. — `test_ask_labels_plain` (tests/test_contracts.py) requires that label for every `followup` command, and merge.md's prod check ask already uses it. — If wrong: only the label text changes.
- Ruling: The lane options use the short placeholder `\"<fix>\"`. — It keeps newjob.md small. — If wrong: the asker writes one sentence in its place.
- Ruling: The audit also fixed the `bigboy blocked` ask in `lanes/commands.md`. — The spec says the re-run scan decides which asks change, and this ask is not exempt (its question is `<its reason>`). — If wrong: it can be reverted, but the CLI would then refuse that ask.
- Ruling: Raised the newjob.md cap in `test_no_unrequested_redesigns` from 26603 to 26740 (now 26737 characters).
  - Before the edit the file was 26589, 14 under the cap. The three new options add about 168 characters.
  - I trimmed what I could: the two Base branch asks now share one closing sentence, "Either ask stops before the spec writer; otherwise `DEFAULT=$BB`", which saves about 23.
  - The other candidate sentences are pinned by tests or carry rules.
  - If wrong: someone trims about 140 more characters later.
- Ruling: Test edits:
  - `test_merge_conflicts_ask_after_two` and `test_resume_reentry_per_reason` pin the exact ask text, so both now include the new `--c` option.
  - `test_ask_accepts_prod_check_title` gains a `--c` followup option.
  - `test_ask_followup_option` already had `--c`, so it is unchanged.
- Ruling: The CLI matches exemptions on the stripped question, because `cmd_ask` stores the question stripped. The queue exemption matches on question text only, because the CLI has no stage (as the spec assumes).
- Ruling: The contract test reuses the existing `ask_spans()` helper (tests/test_contracts.py), which scans every agents/*.md file. That is a superset of the spec's "unblocker agent". The helper's regex `` `(B ask [^`]+)` `` crosses line breaks, so it reads asks that run over more than one line.

## Scrum map
- none

## Commits
- 8d71526 Refuse a CLI ask whose options are all resume/abort
- 80572c2 Give every non-exempt resume/abort-only lane ask a follow-up option
