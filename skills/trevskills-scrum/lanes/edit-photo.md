### edit-photo

Photo work made with the PhotoCraft skill (`$HOME/.claude/skills/trevskills-photocraft/SKILL.md`; job 1365). Trevor approves every version. The session loads the PhotoCraft MCP (`board.spawn` adds `--mcp-config`); the builder and reviewer inherit it.

1. **Folder.** The job's feature.md names the work file or folder. The job ledger is `$F/jobs/$ID/photo.md`. The kind's rules file is the skill's SKILL.md, read in full by every builder and reviewer.
   - **Bad folder:** when the work file or folder is missing or is not under `~/Developer/vid-img-editing/`, start nothing. Write the path and why to stop.md in the job folder, then run the shared step 4 ask (`BUILDER_BLOCKED`) and stop.
2. **Ledger.** `photo.md`, created on the first run: `# Photo ledger`, then `## Versions` (`- v<V>: <file's absolute path> — reviewer PASS | capped — Trevor: pending | notes | approved`), `## Reviews` (`- review-N.md: v<V> — RECUT | PASS`) and `## Trevor's notes` (`- <ISO time> (v<V>): <his note, word for word>`). Each note is also copied word for word into the skill's notes for the job. The next version is one more than the highest `v<V>` in the ledger. An `approve` means the newest version.
3. **Build.** `B set $ID stage=build`. Spawn `edit-builder` and wait for it, with this prompt:
   ```
   KIND: edit-photo. Step: build. JOB_DIR: <JOB_DIR> (job ledger photo.md). Brief: <JOB_DIR>/feature.md. Follow
   $HOME/.claude/skills/trevskills-photocraft/SKILL.md, with PhotoCraft launched with its control port as that skill says (`--control 7980`). Apply every note in the ledger's "Trevor's notes" section and every
   must fix line in the newest review-N.md whose first line is RECUT. Last line of your reply: the file's absolute
   path, or BLOCKED: <reason>.
   ```
   A `BLOCKED:` line takes the shared step 4 ask.
4. **Review.** `B set $ID stage=review`. Spawn a fresh `edit-reviewer`, never the session that built the version, and wait for it, with this prompt:
   ```
   KIND: edit-photo. JOB_DIR: <JOB_DIR> (job ledger photo.md). N: <N>. Version: v<V>, file <path>. Render the file with
   the PhotoCraft MCP and look at it. Check the render against the brief, every note in the ledger and the rules in
   $HOME/.claude/skills/trevskills-photocraft/SKILL.md. Write <JOB_DIR>/review-<N>.md.
   ```
   A `RECUT` sends its notes back to step 3 (same `v<V>`). After the third `RECUT` in a row on the same cut, ask with the capped question below.
5. **Version round.** Each passing version is recorded in the ledger and its path written to stop.md in the job folder. The step right before the ask writes `$F/jobs/$ID/view.md` as one line `View: PhotoCraft <the file's absolute path>`, replacing any older view.md (the dashboard's View button runs `open -a` on it). Then ask Trevor:
   - Passed: `B ask $ID 'photo edit: a new version passed review. Its file is open from the View button and its path is in the stop.md tab. Approve it, or send notes?' --a "Approve this version=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this version>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.
   - Capped: `B ask $ID 'photo edit: the reviewer sent this version back 3 times in a row, so the builder stopped trying. The reviewer notes are in the stop.md tab.' --a "Approve this version anyway=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this version>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.

   His notes start the next build round (step 3, version `v<V>` plus one), and only his approval ends the job: a reviewer `PASS` never does.
6. **One current version.** Follow `~/.claude/rules/one-current-version.md` when it exists: on a new build round move the older versions to the Trash (`mv <file> ~/.Trash/`, never `rm`) and keep one current file; on Trevor's approval run `B set $ID stage=done`.
