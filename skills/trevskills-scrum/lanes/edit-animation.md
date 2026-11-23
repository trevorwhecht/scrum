### edit-animation

Motion ads made with the saas-animation skill (`$HOME/.claude/skills/saas-animation/SKILL.md`; job 1340's Video lane). Trevor approves twice: the storyboard, and every cut.

1. **Folder.** The job's feature.md also has a line starting `Video folder: `. `<folder>` is the absolute path after it, with a leading `~` expanded; `<project>` is its last path part. The job ledger is `$F/jobs/$ID/video.md`. The kind's rules file is `<folder>/notes.md`, read with the saas-animation SKILL.md and its `references/style-rules.md`.
   - **Bad folder:** when the line is missing, or `<folder>` is missing or is not under `~/Developer/vid-img-editing/motion/video/`, start nothing. Write the path and why it was refused to stop.md in the job folder, then run `B ask $ID 'blocked: the video folder named in this job is missing or is not inside the motion video folder, so nothing was started. The path is in the stop.md tab. Send the right folder, or remove the job?' --a "Send back with a note=rework $ID \"Video folder: <the right folder>\"" --b "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop. A rework note naming a new `Video folder: ` line replaces the old line in feature.md, then this step runs again.
2. **Ledger.** `video.md`, created on the first run:
   ```
   # Video ledger
   Folder: <folder>
   Storyboard: pending | approved <ISO time>
   ## Versions
   - v<V>: <folder>/review/v<V>.html — <master file> — reviewer PASS | capped — Trevor: pending | notes | approved
   ## Reviews
   - review-N.md: v<V> — RECUT | PASS
   ## Trevor's notes
   - <ISO time> (storyboard | v<V>): <his note, word for word>
   ```
   Each of Trevor's notes is also copied word for word into `<folder>/notes.md` with its round, as saas-animation step 8 says. A resume never re-asks an approved storyboard and never reuses a version number: the next cut is one more than the highest `v<V>` in the ledger, whatever happened to the files. An `approve` means the storyboard while `Storyboard:` is pending, else the newest version. A `rework` note goes to the same one.
3. **Storyboard.** `B set $ID stage=spec`. Spawn `edit-builder` and wait for it, with this prompt:
   ```
   KIND: edit-animation. Step: storyboard. FOLDER: <folder>. JOB_DIR: <JOB_DIR> (job ledger video.md). Brief:
   <JOB_DIR>/feature.md. Follow $HOME/.claude/skills/saas-animation/SKILL.md workflow steps 1 to 3. Build a numbered
   storyboard from real captures and real assets in the folder: frames plus a page filled from the skill's
   templates/storyboard.html, saved in the folder. Screenshot that page at desktop and phone width and open both
   screenshots before you finish. Do not build, render, run Blender or make sound. Last line of your reply: the page
   path, or BLOCKED: <reason>.
   ```
   A `BLOCKED:` line takes the shared step 4 ask. Otherwise write the page path and both screenshot paths to stop.md in the job folder, then write `$F/jobs/$ID/preview.md` with one `- <absolute path>` line for each of the desktop and phone screenshots, replacing any older preview.md (the dashboard shows these files in the stop box, so Trevor can judge from his phone), `open` the page, delete any older `$F/jobs/$ID/view.md` (`rm -f`; a storyboard has no View button), and run `B ask $ID 'video storyboard: the numbered storyboard for this ad is ready, with frames checked at desktop and phone width. Its page is open on this Mac and its path is in the stop.md tab. Approve it, or send notes?' --a "Approve the storyboard=approve $ID" --b "Send back with a note=rework $ID \"<your notes on the storyboard>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop. A rework note re-runs this step with the note in the ledger. On approval write `Storyboard: approved <ISO time>` and go to step 4.
4. **Build.** `B set $ID stage=build`. Before every build round after the first, apply step 7. Spawn `edit-builder` and wait for it, with this prompt:
   ```
   KIND: edit-animation. Step: build. FOLDER: <folder>. JOB_DIR: <JOB_DIR> (job ledger video.md). Follow
   $HOME/.claude/skills/saas-animation/SKILL.md workflow steps 4 and 6. Build exactly the approved storyboard; apply
   every note in the ledger's "Trevor's notes" section and every must fix line in the newest review-N.md whose first
   line is RECUT. Build the page (or the Blender scene), then render the 4K master with scripts/render.mjs video. Add
   no sound. Last line of your reply: the page path and the master file path, or BLOCKED: <reason>.
   ```
   A `BLOCKED:` line takes the shared step 4 ask.
5. **Review.** `B set $ID stage=review`. Spawn a fresh `edit-reviewer`, never the session that built the cut, and wait for it, with this prompt:
   ```
   KIND: edit-animation. FOLDER: <folder>. JOB_DIR: <JOB_DIR> (job ledger video.md). N: <N>. Cut: v<V>, master
   <master file>. Make stills at 3 to 4 points per transition with scripts/render.mjs stills into
   <folder>/out/review-<N>/, then a contact sheet with scripts/contact_sheet.py, and look at it. Check every frame
   against references/style-rules.md, <folder>/notes.md, the approved storyboard and every note in the ledger. Write
   <JOB_DIR>/review-<N>.md.
   ```
   A `RECUT` sends its notes back to step 4 (same `v<V>`). After the third `RECUT` in a row on the same cut, make the version page (step 6) with the latest cut and the reviewer's notes on it, then ask with the capped question below.
6. **Version round.** Each passing cut becomes `v<V>` on a private local page, `<folder>/review/v<V>.html`: the clip in a `<video controls>` tag and its contact sheet, by relative path, plus (when capped) the reviewer's notes. Record it in the ledger, write the page path to stop.md in the job folder, write `$F/jobs/$ID/preview.md` with one `- <absolute path>` line each for the master clip, then its contact sheet, replacing any older preview.md (the dashboard shows these files in the stop box, so Trevor can watch the cut from his phone), run `open "<folder>/review/v<V>.html"`, write `$F/jobs/$ID/view.md` as one line `View: QuickTime Player <the master's absolute path>`, replacing any older view.md (the dashboard's View button runs `open -a` on it), and ask Trevor:
   - Passed: `B ask $ID 'video cut: a new cut of this ad passed review. Its page, with the clip and a contact sheet, is open on this Mac and its path is in the stop.md tab. Approve this cut, or send notes?' --a "Approve this cut=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this cut>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.
   - Capped: `B ask $ID 'video cut: the reviewer sent this cut of the ad back 3 times in a row, so the builder stopped trying. The cut and the reviewer notes are on its page, open on this Mac; its path is in the stop.md tab.' --a "Approve this cut anyway=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this cut>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.

   His notes start the next build round (step 4, version `v<V>` plus one), and only his approval ends the job: a reviewer `PASS` never does.
7. **One current version.** Follow `~/.claude/rules/one-current-version.md` when it exists; its steps, inline:
   - Before a new build round, zip the previous round's source (the page, its scripts and assets it changed) into `~/Developer/vid-img-editing/motion/video/Archivve/<project>-archive.zip` (`zip -r`, which adds to the archive), and move the old renders and stills to the Trash (`mv <file> ~/.Trash/`, never `rm`). The ledger keeps every version line.
   - On Trevor's approval, copy the final 4K master to `~/Desktop/videos/` (`mkdir -p` it first, never overwrite a file of the same name), record it in the ledger, then run `B set $ID stage=done`.
8. **Sound.** No sound is added and no ElevenLabs or Suno call is made unless Trevor asks for it: they use his paid credits. Sound is built only when Trevor asks, and only in a job whose folder ledger already records an approved picture (a later edit-animation job on the same folder; a picture approval ends this job).
