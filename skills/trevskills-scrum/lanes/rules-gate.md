# Rules gate

Run by **Merge** step 1's **Agent rules guard** (and its step 6 re-run) when the diff changes a rules file, `docs/skill-standards.md` or `board.py`, `$F/jobs/$ID/human-approval.md` doesn't exist, and `B digest-verify` exited non-zero. The standard is `docs/skill-standards.md` in `$WT`: `B rules-check` enforces its script rules 1-8 and `scrum-review-rules` grades its judged rules 9-14. The diff merges without a human only when both pass. This file, the standard, `B rules-check`'s code, `agents/scrum-review-rules.md`, the Merge step 1 guard bullets and the never-list at the top of SKILL.md are human-only: rule 8 fails any diff that touches them.

1. **Script rules.** Run `B rules-check $ID --worktree "$WT" --base "$BASE"` with Bash timeout 600000. It prints `{"ok", "files", "failures"}`. When it exits non-zero, `<why>` is its first `failures` entry; go to step 4. When it exits 0 and `files` is empty (only `board.py` outside the rules-check code changed), there is nothing for rules 9-14 to grade: continue Merge without a human.
2. **Judged rules.** Run `HEAD=$(git -C "$WT" rev-parse HEAD)`. When `$F/jobs/$ID/rules-review.md` exists and its second line is `Reviewed: $HEAD`, reuse it. Otherwise spawn `scrum-review-rules` and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   WORKTREE=$WT
   BASE=$BASE
   HEAD=$HEAD
   PROJECT=$F/project.md
   Grade the rules diff against docs/skill-standards.md rules 9-14. Write JOB_DIR/rules-review.md.
   ```
3. **Verdict.** When the first line of `$F/jobs/$ID/rules-review.md` is `VERDICT: PASS` and its second line is `Reviewed: $HEAD`, continue Merge without a human. Anything else (`VERDICT: CHANGES`, a missing or unreadable file, another HEAD) counts as CHANGES: `<why>` is `rules review CHANGES`; go to step 4.
4. **Ask.** Write the matching files to `$F/jobs/$ID/stop.md`, run `B ask $ID 'Hard stop: agent rules — this change edits scrum rules files, listed in stop.md; <why>' --a "Merge anyway=approve $ID" --b 'Send back with a note=rework <id> "<why>: read rules-review.md, then fix it so B rules-check exits 0 and the rules review is PASS"' --recommend <key> '<why>'` and stop. Remove every `'`, `"` and backtick from `<why>` first. When `<why>` starts with `rule 7:`, `<key>` is `b`.
