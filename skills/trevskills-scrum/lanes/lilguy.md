# Lilguy lane

The orchestrator spawns no subagents (no spec writer, builder, reviewer or approver) and makes the change itself, in the job's own `scrum/<id>` worktree, and lands it through the normal **Merge** squash PR. A job enters this lane in one of two ways:
- **New job** step 3's **Lilguy route** sends a tiny job here when `B lilguy-fit $ID` prints `fit: true`: a job with no `parent` or a `runall` parent (so **Run all** children too), outside a Cloud lane session, that is 1 point on the backlog or that Jev rates trivial with confidence, and whose feature.md has no hard-stop word. A pre-written spec.md does not stop the route; this lane ignores it.
- `/trevskills-scrum lilguy <feature text>` runs **New job** steps 1, 1b and 2 (job, feature.md, base), then step 1 below. It never runs `B lilguy-fit $ID`, because Trevor picked the lane himself.

1. **Worktree.** Run `B set $ID lane=lilguy`, then **New job** step 4. If `.claude/worktrees/scrum-$ID` already exists (a resume), reuse it as `$WT` instead.
2. **Build.** Run `B set $ID stage=build`. Read `$F/project.md` and every convention file it lists, make the change in `$WT` and commit it on `scrum/<id>`.
3. **Check.** Run `B set $ID stage=check`. In `$WT`, run the **Check gate** step 2 commands and its `.env` check, and write `$F/jobs/$ID/check.md` in the **Check gate** step 3 format (no `round-N/`; `round` and `limit` stay unset). A `.env` hit is a check failure. Schema files are not stopped here: **Merge**'s schema guard (**Migrate**) handles them.
4. **Route.** On a check failure, fix, commit and re-run step 3. On the 3rd failure, run `B route-check $ID --check-fails 3`. After a pass, run `B route-check $ID`. A non-null `promote` promotes the job (below); it triggers on a 3rd check failure, a binary file, more than 30 added lines, more than 3 files with added lines, or a rules file not named in feature.md. Exception: when the trigger is a line or file count and the diff is mostly deletions, you may keep the job here and append `Kept in lilguy lane: <trigger>` to `$F/jobs/$ID/promoted.md`. A `null` `promote` goes on to step 5.
5. **Merge.** Land through **Merge**. Wherever Merge resumes the builder, make the fix yourself. Merge's **Conflicts** step returns to step 3 here, not to the **Check gate**. The PR uses Merge's no-Merge-summary fallback, with bullets summarising the change, and the body line `Lilguy lane: orchestrator build + check gate, no reviewers. Job files: scrum/jobs/$ID/`. With no decision.md, `Restart:` counts as `none`.

**Promotion.** Run `B set $ID lane=fast` and append `Promoted to fast: <trigger>` to `$F/jobs/$ID/promoted.md`. Keep the worktree and its commits. Then run **New job** step 3 with `WORKTREE=$WT` (its `B lilguy-fit` now says `already on fast lane`), then 3b and 3c, except that `Lane: bigboy` and `Lane: debug` count as `standard`. Skip step 4 and go on at step 5, so the builder continues from the existing commits. From there the **Fast lane** promotions to standard apply.

**Resume.** A lilguy job with a worktree flagged `stalled` re-runs this lane: step 2 for `build`, step 3 for `check`, **Merge** from step 1 for `merging`.

6. End with the **Final report** (job id, stage, PR URL, and for needs-human the reason).
