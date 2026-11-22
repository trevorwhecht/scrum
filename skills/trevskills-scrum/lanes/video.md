# Video lane

Motion ads made with the saas-animation skill (`$HOME/.claude/skills/saas-animation/SKILL.md`). The video folder lives outside git, so this lane has no worktree, branch, PR, Check gate or Merge, and Trevor approves twice: the storyboard, and every cut.

1. **Route.** A job whose `$F/jobs/$ID/feature.md` has a line starting `Video folder: ` (anywhere in the file, a backlog item's first line included) runs this lane. `<folder>` is the absolute path after it, with a leading `~` expanded; `<project>` is its last path part. Before anything else in New job (lilguy fit, Askme, Base, spec writer), run `B set $ID lane=video`, then follow this file. For every command on the job (new, resume, rework, approve) this lane replaces New job, the spec writer, the Check gate, Review and Merge: it never makes a worktree, branch or PR, and never spawns a `scrum-*` agent. Video jobs run only on the main Mac (the shop Mac's `## Cannot run` list names `Video folder`).
   - **Bad folder:** when `<folder>` is missing, or is not under `~/Developer/vid-img-editing/motion/video/`, start nothing. Write the path and why it was refused to stop.md in the job folder, then run `B ask $ID 'blocked: the video folder named in this job is missing or is not inside the motion video folder, so nothing was started. The path is in the stop.md tab. Send the right folder, or remove the job?' --a "Send back with a note=rework $ID \"Video folder: <the right folder>\"" --b "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop. A rework note naming a new `Video folder: ` line replaces the old line in feature.md, then this step runs again.
2. **Ledger.** `$F/jobs/$ID/video.md` is the job's record, created on the first run:
   ```
   # Video ledger
   Folder: <folder>
   Storyboard: pending | approved <ISO time>
   ## Versions
   - v<N>: <folder>/review/v<N>.html — <master file> — reviewer PASS | capped — Trevor: pending | notes | approved
   ## Reviews
   - v<N> try <k>: VERDICT: PASS|FAIL — video-review-v<N>-<k>.md
   ## Trevor's notes
   - <ISO time> (storyboard | v<N>): <his note, word for word>
   ```
   Append to it after every step below; never rewrite an earlier line. Each of Trevor's notes is also copied word for word into `<folder>/notes.md` with its round, as saas-animation step 8 says.
   - **Resume after a stop:** a resume, re-run, rework or approve reads the ledger first and continues at its last unfinished step. It never re-asks an approved storyboard and never reuses a version number: the next cut is one more than the highest `v<N>` in the ledger, whatever happened to the files.
   - An `approve` means the storyboard while `Storyboard:` is pending, else the newest version. A `rework` note goes to the same one.
3. **Writer.** `B set $ID stage=spec`. Spawn a `general-purpose` Agent and wait for it, with this prompt:
   ```
   You are the storyboard writer for a motion ad. First read $HOME/.claude/skills/saas-animation/SKILL.md and follow
   its workflow steps 1 to 3. Video folder: <folder>. Job ledger: <JOB_DIR>/video.md. Brief: <JOB_DIR>/feature.md.
   Trevor's notes so far: the ledger's "Trevor's notes" section. Build a numbered storyboard from real captures and
   real assets in the folder: frames plus a page filled from the skill's templates/storyboard.html, saved in the
   folder. Screenshot that page at desktop and phone width and open both screenshots before you finish. Do not build,
   render, run Blender or make sound. Last line of your reply: the page path, or BLOCKED: <reason>.
   ```
   Then write the page path and both screenshot paths to stop.md in the job folder, `open` the page, and run `B ask $ID 'video storyboard: the numbered storyboard for this ad is ready, with frames checked at desktop and phone width. Its page is open on this Mac and its path is in the stop.md tab. Approve it, or send notes?' --a "Approve the storyboard=approve $ID" --b "Send back with a note=rework $ID \"<your notes on the storyboard>\"" --c "Remove this job=abort $ID --cascade" --title VIDEO_REVIEW --recommend <key> '<why>'` and stop. Notes are not approval: a rework note re-runs this step with the note in the ledger. On approval write `Storyboard: approved <ISO time>` and go to step 4.
4. **Builder.** `B set $ID stage=build`. Before every build round after the first, apply the one-current-version rule (step 7). Spawn a `general-purpose` Agent and wait for it, with this prompt:
   ```
   You are the builder for a motion ad. First read $HOME/.claude/skills/saas-animation/SKILL.md and follow its
   workflow steps 4 and 6. Video folder: <folder>. Job ledger: <JOB_DIR>/video.md. Build exactly the approved
   storyboard; apply every note in the ledger's "Trevor's notes" section and every note in the latest
   video-review-v<N>-<k>.md with VERDICT: FAIL. Build the page (or the Blender scene), then render the 4K master with
   scripts/render.mjs video. Add no sound. Last line of your reply: the page path and the master file path, or
   BLOCKED: <reason>.
   ```
   A `BLOCKED:` line: write its reason to stop.md in the job folder and run `B ask $ID 'blocked: the video builder could not go on. Its reason is in the stop.md tab. Send notes to try again, or remove the job?' --a "Send back with a note=rework $ID \"<what to change>\"" --b "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop.
5. **Reviewer.** `B set $ID stage=review`. Spawn a new `general-purpose` Agent, never the session that built the cut, and wait for it, with this prompt:
   ```
   You are the reviewer for a motion ad; you did not build it. First read $HOME/.claude/skills/saas-animation/SKILL.md
   and its references/style-rules.md. Video folder: <folder>. Job ledger: <JOB_DIR>/video.md. Make stills at 3 to 4
   points per transition with scripts/render.mjs stills into a new folder (out/v<N>-<k>/), then a contact sheet with
   scripts/contact_sheet.py, and look at it. Check every frame against references/style-rules.md, the approved
   storyboard and every note in the ledger. Write <JOB_DIR>/video-review-v<N>-<k>.md: first line VERDICT: PASS or
   VERDICT: FAIL, then the contact sheet path, then one numbered note per problem with its shot number. Edit nothing
   else.
   ```
   `<N>` is this cut's version number and `<k>` counts the reviewer's tries on it, from 1. A `VERDICT: FAIL` sends its notes back to the builder (step 4, same `<N>`, next `<k>`). A missing file or first line counts as a FAIL.
   - **Reviewer cap:** after 3 reviewer FAILs in a row on the same cut, the job stops trying: make the version page (step 6) with the latest cut and the reviewer's notes on it, then ask with the cap question below instead of the cut question.
6. **Version round.** Each passing cut becomes `v<N>` on a private local page, `<folder>/review/v<N>.html`: the clip in a `<video controls>` tag and its contact sheet, by relative path, plus (when capped) the reviewer's notes. Record it in the ledger, write the page path to stop.md in the job folder, run `open "<folder>/review/v<N>.html"`, and ask Trevor:
   - Passed: `B ask $ID 'video cut: a new cut of this ad passed review. Its page, with the clip and a contact sheet, is open on this Mac and its path is in the stop.md tab. Approve this cut, or send notes?' --a "Approve this cut=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this cut>\"" --c "Remove this job=abort $ID --cascade" --title VIDEO_REVIEW --recommend <key> '<why>'` and stop.
   - Capped: `B ask $ID 'video cut: the reviewer failed this cut of the ad 3 times in a row, so the builder stopped trying. The cut and the reviewer notes are on its page, open on this Mac; its path is in the stop.md tab.' --a "Approve this cut anyway=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this cut>\"" --c "Remove this job=abort $ID --cascade" --title VIDEO_REVIEW --recommend <key> '<why>'` and stop.

   His notes start the next build round (step 4, version `<N>+1`, `<k>` from 1), and only his approval ends the job: a reviewer PASS never does.
7. **One current version.** Follow `~/.claude/rules/one-current-version.md` when it exists; its steps, inline:
   - Before a new build round, zip the previous round's source (the page, its scripts and assets it changed) into `~/Developer/vid-img-editing/motion/video/Archivve/<project>-archive.zip` (`zip -r`, which adds to the archive), and move the old renders and stills to the Trash (`mv <file> ~/.Trash/`, never `rm`). The ledger keeps every version line.
   - On Trevor's approval, copy the final 4K master to `~/Desktop/videos/` (`mkdir -p` it first, never overwrite a file of the same name), record it in the ledger, then run `B set $ID stage=done`.
8. **Sound.** No sound is added and no ElevenLabs or Suno call is made unless Trevor asks for it: they use his paid credits. Sound is built only when Trevor asks, and only in a job whose folder ledger already records an approved picture (a later video job on the same folder; a picture approval ends this job).
9. **Finish.** The final report gives the job id, the stage, the version Trevor approved, the master's path on the Desktop, or, for needs-human, the question and the next command (`approve <id>` or `rework <id> "<notes>"`). There is no PR URL.
