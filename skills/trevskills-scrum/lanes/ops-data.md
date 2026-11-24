# Ops lane: data run

Read after `lanes/ops.md`, for `Kind: ops-data`. Dev runs first, then prod, every prod command gated by `B prod-ok`. The ledger is `$F/jobs/$ID/runs.md` (ops.md **Ledger**). The shape, schema refusal, record format and error-scan rules (`jev-gate.py prod-error` included) are those of merge.md's **Prod runs** sub-step (Prod check step 2); this file never restates them. Every run is from `$REPO`, which is the working dir (no worktree).

1. **Scripts.** Read the `Run: npm run <script>:prod` lines of `$F/jobs/$ID/feature.md`, each with an optional ` -- <args>`. For each line build five bullets in order, and write them to `runs.md` (created now):
   - dev dry run: `<script>` with `:prod` stripped, the args without `--apply` or `--prod`
   - dev apply: the same plus `--apply`
   - prod dry run: the `:prod` script, the original args without `--apply`
   - prod apply: the same plus `--apply`
   - closing prod dry run: the same as the prod dry run

   Nobody hand-writes the list. A fault is: no `Run:` line, a script or its dev twin that is not a key of `$REPO/package.json` `scripts` on main, or a schema, deploy or fixture script. Only a fault asks: `B ask $ID '<the Run line and the fault>' --a "Send back with a note=rework $ID \"<notes>\"" --b "Remove this job=abort $ID --cascade" --title DATA_RUN --recommend <key> '<why>'`, then stop. A clean job never asks Trevor to approve the dev runs, nor to go on to prod after a clean dev pass.
2. **Main.** Run merge.md's **Fast-forward main** guard and fast-forward. On failure, run `B ask $ID 'blocked: main could not be fast-forwarded, so no data run started.' --a "Send back with a note=rework $ID \"<notes>\"" --b "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop. Then run Prod check's `1. Deploy` wait (a project.md with no `- Deploy:` line means none); the prod bullets wait for it.
3. **Dev runs.** `B set $ID stage=build`. Overwrite `$F/jobs/$ID/prod.md` with `## Runs`. Run the dev dry run and dev apply bullets per script, recording each as **Prod runs** does (`- run: <bullet> exit <code>` plus the last 20 output lines indented 4 spaces), and append each result to `runs.md`.
4. **Result shown.** Write the tail of each dev run's output to `$F/jobs/$ID/dev-output.md`, so it shows in a dashboard tab. A failed dev run (non-zero exit or an error-word scan hit, as **Prod runs** scans) stops with `B ask $ID 'data run: <what failed, one plain clause under 25 words>; the output is in the dev-output.md tab of this job.' --a "Try again=resume $ID" --b "Stop tracking this job=abort $ID" --c "File the fix as a follow-up=followup $ID \"<the fix, one sentence, no double quotes>\"" --title PROD_CHECK_FAILED --recommend <key> '<why>'`; prod never starts.
5. **Prod runs.** `B set $ID stage=deploying`. Every prod bullet (dry run, apply, closing dry run) first passes `B prod-ok $ID '<bullet>'`; a non-zero exit runs nothing more and fails as `prod run refused: <its error>`. Record and scan each run as step 3 does. Never write a prod command outside the five-bullet list.
6. **Check.** The closing prod dry run's output must report nothing pending; otherwise the stop is `PROD_CHECK_FAILED` with `prod dry run still reports pending work`. Then finish through ops.md **Finish** (`B set $ID stage=done`).
7. **Resume.** Read `runs.md` first and continue at its last unfinished step. A restarted `prod.md` (missing, or reset by a later attempt) re-runs the dev pair before any prod bullet, because `prod-ok` counts only passing dev records in `prod.md`.
