# Ops lane

Non-code work Trevor asks for (a production data run, a blog post or other content) runs as a job of the `ops` lane. One lane, two kinds, each with its own file; this file is the shared flow. This lane has no worktree, branch, PR, Check gate, Review or Merge, and only Trevor's answer or approval ends a job.

**Kind files.** Read `$HOME/.claude/skills/trevskills-scrum/lanes/<kind>.md` for the job's kind and no other file of that pattern. One line per kind:
- `ops-data`: read `$HOME/.claude/skills/trevskills-scrum/lanes/ops-data.md`.
- `ops-content`: read `$HOME/.claude/skills/trevskills-scrum/lanes/ops-content.md`.
- While that file is missing the job stops with the **No kind** ask in step 1.

1. **Route.** A job whose `$F/jobs/$ID/feature.md` has a line `Kind: <kind>` runs this lane: the first line matching `^Kind: (ops-data|ops-content)\s*$`, anywhere in the file (a backlog item's first line included), which `board.ops_kind` reads (`Kind: knowledge` is a label and never routes here). Before anything else in New job, run `B set $ID lane=ops kind=<kind>` (with no valid kind, `B set $ID lane=ops` alone, then **No kind**), then follow this file and the kind's file. For every command on the job (new, resume, rework, approve) this lane replaces New job, the spec writer, the Check gate, Review and Merge: there is no worktree, branch or PR, and it never spawns a scrum agent or a stand-in for one. Ops jobs run only on the main Mac.
   - **No kind:** a job whose kind's file is missing, or whose feature.md has no valid `Kind:` line (`Kind: ops-movie` is not one), starts nothing. Write why to stop.md in the job folder, then run `B ask $ID 'blocked: this ops job does not name a kind that can be run yet, so nothing was started. Why is in the stop.md tab. Send the kind (ops-data or ops-content), or remove the job?' --a "Send back with a note=rework $ID \"Kind: <kind>\"" --b "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop.
   - A rework note with a `Kind: <kind>` line writes that line into feature.md in place of any old `Kind:` line, then this step runs again.
2. **Ledger.** Each kind keeps a per-job ledger in the job folder, named in its file and created on the first run. Append to it after every step; never rewrite an earlier line. Each of Trevor's notes goes into the ledger word for word, with the step it answers.
   - **Resume:** a resume, re-run, rework or approve reads the job ledger first on every resume and continues at its last unfinished step: it never redoes a step the ledger records as done.
3. **Stops.** Every block or question is a `B ask` with the title its kind's file names (`CONTENT_QUESTIONS`, `CONTENT_DRAFT` or `DATA_RUN`) or `BUILDER_BLOCKED`, never a silent stop. serve.py never auto-resumes an ops job: Trevor's answer runs the next command.
4. **Finish.** The final report gives the job id, the kind, the stage, what ran or was approved, or, for needs-human, the question and the next command (`approve <id>` or `rework <id> "<notes>"`). There is no PR URL. Then `B set $ID stage=done`.
