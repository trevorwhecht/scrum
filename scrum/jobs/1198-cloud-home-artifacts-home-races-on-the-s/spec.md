# Cloud-home Artifacts home fetches into a private ref, not the shared FETCH_HEAD
UI surface: no
Hard stops: none
Human setup: none
Lane: fast
Complex: no

## Problem
The **Artifacts home** step in `skills/trevskills-scrum/lanes/cloud.md` (Sync, Cloud-home tail) runs `git fetch origin scrum-artifacts/$ID` and then `git archive FETCH_HEAD scrum/jobs/$ID`. serve.py's cloud-sync loop spawns one headless `/trevskills-scrum cloud-home <id>` per id in `homes`; all run in the same main checkout, which has one `FETCH_HEAD`. A parallel fetch for another job can overwrite `FETCH_HEAD` between this job's fetch and its archive. Then the archive finds no `scrum/jobs/$ID`, the block takes the "empty artifacts branch" `else` path and runs `git push origin --delete scrum-artifacts/$ID`, deleting the job's real artifacts. This happened to onewitharts job 1501, which archived job 1502's commit.

## Scope
In:
- Rewrite the Artifacts home bash block and its lead-in in `lanes/cloud.md`. The block fetches into the job's own ref `refs/scrum-home/$ID` and archives that ref. It copies and deletes the remote branch only when the ref's commit subject is exactly `[scrum $ID] artifacts`, and it always drops the ref at the end.
- In `tests/test_contracts.py`, update `test_skill_cloud_artifacts_come_home`, whose phrases `"git fetch origin scrum-artifacts/$ID"` (in its phrase list and in both `assertLess` lines) and `"git archive FETCH_HEAD"` this change removes. Add one test that runs the block.

Out:
- The cloud-side **Artifacts** push block (it already commits with subject `[scrum $ID] artifacts`).
- serve.py and board.py.
- `--no-write-fetch-head` on the fetch.
- Recovering other branches deleted earlier.

## Acceptance criteria
1. In `lanes/cloud.md`, the **Artifacts home** fenced bash block is exactly this, indented as the current block is:
   ```bash
   cd "$REPO"; H="refs/scrum-home/$ID"
   if git fetch origin "+refs/heads/scrum-artifacts/${ID}:$H" 2>/dev/null; then
     T=$(mktemp -d)
     if [ "$(git log -1 --format=%s "$H")" != "[scrum $ID] artifacts" ]; then
       echo "artifacts: kept scrum-artifacts/$ID, its commit is not [scrum $ID] artifacts"
     elif git archive "$H" scrum/jobs/$ID 2>/dev/null | tar -x -C "$T" 2>/dev/null && [ -d "$T/scrum/jobs/$ID" ]; then
       rm -f "$T/scrum/jobs/$ID/feature.md" && mkdir -p "$F/jobs/$ID" &&
         cp -R "$T/scrum/jobs/$ID/." "$F/jobs/$ID/" && git push origin --delete scrum-artifacts/$ID
     else git push origin --delete scrum-artifacts/$ID  # an empty artifacts branch: nothing to copy
     fi
     rm -rf "$T"
   fi
   git update-ref -d "$H" 2>/dev/null
   ```
   The lead-in prose before it keeps every current guarantee: "missing branch", "never overwrites the local `feature.md`", "all but `feature.md`", "deleted only after the copy succeeds" and "never force". It adds that the step fetches into `refs/scrum-home/$ID`, never the shared `FETCH_HEAD`, because serve.py runs several cloud-home sessions at once in the same checkout and a parallel fetch overwrites `FETCH_HEAD` in between. It also adds that the branch is deleted only when the ref's commit subject is exactly `[scrum $ID] artifacts` (the **Artifacts** push's subject), that otherwise the block prints the `artifacts: kept ...` line and the final report quotes it, and that the ref is always dropped. (verify: `test_skill_cloud_artifacts_come_home` asserts in the Sync section: `git fetch origin "+refs/heads/scrum-artifacts/${ID}:$H"`, `refs/scrum-home/$ID`, `git archive "$H"`, `[scrum $ID] artifacts`, `artifacts: kept scrum-artifacts/$ID` and `git update-ref -d "$H"`. It asserts `"git archive FETCH_HEAD"` is not in the Sync section. Its two `assertLess` ordering lines use the new fetch phrase instead of `"git fetch origin scrum-artifacts/$ID"`. Its other phrases and `assertNotIn("--force", sync)` stay.)
2. The incident cannot recur. A run with `ID=1501` where origin's `scrum-artifacts/1501` holds a commit with subject `[scrum 1502] artifacts` and only `scrum/jobs/1502/` leaves origin's `refs/heads/scrum-artifacts/1501` in place. It creates no `$F/jobs/1501`, prints `artifacts: kept scrum-artifacts/1501, its commit is not [scrum 1501] artifacts`, and leaves no local `refs/scrum-home/1501`. (verify: new `test_cloud_artifacts_home_block_runs` in `tests/test_contracts.py`. It pulls the fenced block that follows `**Artifacts home.**` out of `lanes/cloud.md` and dedents it with `textwrap.dedent`. It runs the block with `subprocess.run([shell, "-c", block])` for `shell` in `("bash", "zsh")`, against a temp bare origin and a temp clone as `REPO`, with `F` set to a temp dir and `ID=1501`. A shell that is not installed is skipped, as `test_codex_block_is_shell_agnostic` does.)
3. The good path still works. When origin's `scrum-artifacts/1501` holds a commit with subject `[scrum 1501] artifacts` containing `scrum/jobs/1501/spec.md` and `scrum/jobs/1501/feature.md`, and `$F/jobs/1501/feature.md` already exists locally with the text `local`, the block copies `spec.md` into `$F/jobs/1501/`. It leaves the local `feature.md` reading `local`, deletes origin's `scrum-artifacts/1501` (`git ls-remote origin refs/heads/scrum-artifacts/1501` prints nothing) and leaves no local `refs/scrum-home/1501`. This holds under both bash and zsh. (verify: `test_cloud_artifacts_home_block_runs`.)
4. A missing branch, including one with state left over from an earlier run, is handled. With no `scrum-artifacts/1501` on origin and a stale local `refs/scrum-home/1501` pre-created by the test, the block exits 0 and prints nothing to stdout. It creates no `$F/jobs/1501` and removes the stale `refs/scrum-home/1501`. (verify: `test_cloud_artifacts_home_block_runs`.)
5. A legacy branch with no job folder but the right subject still takes the empty-branch path. When origin's `scrum-artifacts/1501` holds a commit with subject `[scrum 1501] artifacts` and no `scrum/jobs/1501/`, the block deletes the branch and copies nothing. (verify: `test_cloud_artifacts_home_block_runs`.)

## Likely files
- `skills/trevskills-scrum/lanes/cloud.md`: the Sync section's **Artifacts home** bullet (lead-in prose and fenced block).
- `tests/test_contracts.py`: update `test_skill_cloud_artifacts_come_home` and add `test_cloud_artifacts_home_block_runs`.

## Assumptions
- Exact match of the subject with `[scrum $ID] artifacts` (a substring check would let job 150 match `[scrum 1501] artifacts`).
- When the subject does not match, the block skips the copy too; the branch stays on origin for a human.
- The `+` in the fetch refspec force-updates only the local private ref. "never force" is about the remote branch.
- `git fetch` with an explicit refspec still writes `FETCH_HEAD`; harmless, nothing reads it.
- Two cloud-home sessions for the same id never run at once (serve.py checks `running`).
- `git update-ref -d` on a missing ref exits 0.
- The block must run the same in bash and zsh.

## Diverged
- The block writes `git fetch origin "+refs/heads/scrum-artifacts/${ID}:$H"` with `H="refs/scrum-home/$ID"` rather than `...:refs/scrum-home/$ID` because zsh reads `$ID:r` as a modifier.
