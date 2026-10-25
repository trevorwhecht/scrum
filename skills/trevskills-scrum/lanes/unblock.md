# Unblock

Runs when a `B ask` run with `--kind` prints `{"unblock": true, "n": N}`. board.py decided the stop is eligible: the kind is one of `round-limit`, `check-fail`, `ci-fail`, `conflict`, `blocked` or `render`, the job has had fewer than 2 unblocks, and this kind was never unblocked on it before. The job was **not** parked: it keeps its stage and reason. Any other `--kind` call printed `{"unblock": false}` and parked as usual. `KIND` is the `--kind` value, `QUESTION` the question text, `N` the printed `n`; keep the original options too.

1. **Diagnose.** Spawn `scrum-unblocker` (see **Routing**) and wait for it. Prompt:
   ```
   JOB_DIR=$F/jobs/$ID
   WORKTREE=$WT
   BASE=$BASE
   PROJECT=$F/project.md
   KIND=<KIND>
   N=<N>
   QUESTION=<QUESTION>
   Diagnose this stop. Write only JOB_DIR/unblock-N.md.
   ```
   Then run `B unblock-log $ID`. It logs the verdict to questions.log and prints `{"verdict","blocker","kind","n"}`.
2. Act on `verdict`:
   - **REWORK:** run `B set $ID stage=build reason=`, resume the builder (see **Resuming the builder**) with `Read JOB_DIR/unblock-N.md and follow Instructions.` (N written out), then go to **Check gate**, the reviews and **Approve** as for any round. The new round counts toward the round limit, and REWORK never raises `limit`.
   - **RESPEC:** run `B set $ID stage=spec reason=`, spawn `scrum-spec-writer` (see **Routing**) with the **New job** step 3 prompt, `WORKTREE=$WT`, and the last line `Revise spec.md from the Instructions in JOB_DIR/unblock-N.md.` (N written out). Then run `B set $ID stage=build`, resume the builder with `spec.md was revised from JOB_DIR/unblock-N.md: rebuild against it, commit, update build.md.`, then go to **Check gate**. The round limit is not raised here either.
   - **ESCALATE or INVALID:** re-run the original `B ask` with the same question and the same `--kind`. The kind is now a repeat, so it prints `{"unblock": false}` and parks. For ESCALATE, use the `## For Trevor` lines of `unblock-N.md` as its options (`--a` the first line, `--b` the second, `--c` a third), each single-quoted with every `'` in it removed. For INVALID, or when `B ask` rejects a For Trevor option (non-zero exit), run it once more with the original options. Then run the side steps below, report and stop.
3. **Loop guard.** board.py owns it: at most 2 unblocks per job over its whole life, one per kind, never reset by a rework or resume. A stop of the same kind after a REWORK or RESPEC therefore parks at once.

**Side steps.** While the job is unblocked rather than parked, skip the needs-human side steps: **BigBoy lane** step 6 for a child, the **Roadmap lane** stop rule, and the **Cloud lane** needs-human report. They run only when a `B ask` actually parks the job (`{"unblock": false}`, or an ask without `--kind`).
