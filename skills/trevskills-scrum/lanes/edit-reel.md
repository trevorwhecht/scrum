### edit-reel

Instagram print reels cut from a print day's phone clips and finished in Edits (Instagram's Mac app), per `motion/video/instaReels/pipeline-handoff.md` "Reel flow". Reels have no storyboard and no rough cut approval: the only card Trevor sees is the finished export.

**Headless computer use (measured 2026-11-23):** does not work: a `claude -p` child started with `--mcp-config <file> --strict-mcp-config` loaded no server (`"computer-use" is a reserved MCP server name and was not loaded`), so it had no `mcp__computer-use__` tools and took no screenshot. Step 6's driven path is off until this line says `works` and names its config file.

**Folder.** The job's feature.md also has a line starting `Reel project: `. `<name>` is the text after it and `<project>` is the same name; `<folder>` is `~/Developer/vid-img-editing/motion/video/instaReels/<name>`, and `<instaReels>` is its parent folder. The kind's rules file is `~/Developer/vid-img-editing/motion/notes/print-reels.md`; the Edits how-to is `motion/notes/video-edit.md` "What worked". Every script runs as `~/Developer/vid-img-editing/motion/.venv/bin/python <instaReels>/reel.py ...` (`<py>` below; plain `python3` has no Pillow). The song is the one a `Song: <title>` line in feature.md or a later note in the ledger names; its beats come only from Edits' own beat map, `~/Library/Containers/com.burbn.basel.mac/Data/Library/Caches/MCEBeatsCache/beats.json` (`<beats.json>` below), whose newest entry is the last song opened in Edits.
- **Bad folder:** when the line is missing, or `<name>` is empty or contains `/` or `..`, the job starts nothing. Write the line and why it was refused to stop.md in the job folder, then run `B ask $ID 'blocked: the reel project named in this job is missing or is not a plain folder name, so nothing was started. Why is in the stop.md tab. Send the right name, or remove the job?' --a "Send back with a note=rework $ID \"Reel project: <name>\"" --b "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop. A rework note naming a new `Reel project: ` line replaces the old line in feature.md, then this step runs again. `<folder>` itself is made by step 1 when it is missing.

**Ledger.** `$F/jobs/$ID/reel.md`, created on the first run:
```
# Reel ledger
Folder: <folder>
Song: <title> — first beat <k> at <mm:ss.ff>
## Steps
- <ISO time> r<R> <step>: done | <what it hit>
## Rounds
- r<R>: <folder>/selects/<hash>/ — check exit 0 | 1 (check-r<R>.txt) — review-N.md RECUT | PASS
## Reviews
- review-N.md: r<R> — RECUT | PASS
## Edits
- r<R>: project <Edits project name> — export <absolute path> — exported <ISO time> — Desktop copy <path> | none — Trevor: pending | notes | approved
## Trevor's notes
- <ISO time> (r<R>): <his note, word for word>
```
A round `r<R>` is one run of step 3, counted from 1, one more than the highest in the ledger. An `approve` means the newest exported round. A `rework` note goes into the ledger (step 8) and starts the next round at step 3.

1. **Clips.** `B set $ID stage=build`. Skip this step when `<folder>/footage/` already holds a `.mov` or `.mp4`. Otherwise check the phone with photos.py `pull` into a scratch folder: `W=$(mktemp -d)` then `uv run --with pymobiledevice3 --with pillow python ~/.claude/skills/trevskills-photo-scan-iphone/photos.py pull "$W"`.
   - A failure (no phone, locked, not trusted) copies nothing: write its last lines to stop.md in the job folder, then run `B ask $ID 'blocked: the phone is not reachable over USB, so no clips were copied. Please plug in and unlock your phone, then try again, or remove the job?' --a "Try again=resume $ID" --b "Send back with a note=rework $ID \"<what to change>\"" --c "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop. A resume retries this step from the top.
   - Success: `mkdir -p <folder>/footage`, then copy each video of the print day (feature.md's date, else today) from the phone into it under its own file name, read from the pulled `Photos.sqlite` (`ZASSET` rows with `ZKIND` 1 and that day's `ZDATECREATED`, at `/<ZDIRECTORY>/<ZFILENAME>`) through the `phone()` AFC connection photos.py opens, the way its `best_copy` reads a file, never re-encoding or renaming it. Then `trash "$W"`.
2. **Log.** Run `<py> <instaReels>/reel.py log <folder>` (one GPU decode per new clip; its last line is `<n> clips scanned, <m> rows in footage-log.json, no rows yet: <clips | none>`). Spawn `edit-logger` agents in parallel, in batches of about 35 sheets (the `<clip> <s> s, <n> sheets` lines it printed), for the clips after `no rows yet:`, and wait for all of them, each with this prompt:
   ```
   KIND: edit-reel. Step: log. FOLDER: <folder>. Clips: <clip> <clip> ... Where <instaReels>/logger.md differs from
   your instructions it is newer (the spin stage, one word per ink): follow it. Write <folder>/log/rows/<clip stem>.json
   for each clip, row by row with the Write tool. Reply with one line per clip: <clip> <rows> rows, then DONE.
   ```
   Then rerun `reel.py log <folder>` until it exits 0 with `no rows yet: none`; clips still listed get a new batch. A `Bad rows` exit sends the lines it printed back to a new `edit-logger` for the clips it names, with those lines in its prompt, never to a script that fills rows. After 3 tries on the same clips, write the lines to stop.md and take the shared step 4 ask.
3. **Cut.** `B set $ID stage=build`, then start round `r<R>`. Before a recut overwrites `shots.json`, zip the old one into `~/Developer/vid-img-editing/motion/video/Archivve/<project>-archive.zip` as `r<R>-<date>/shots.json`, where `r<R>` is the round that wrote it (`r0` for one there before the job): `D=$(mktemp -d)`, `mkdir "$D/r<R>-<date>"`, `cp <folder>/shots.json "$D/r<R>-<date>/"`, `(cd "$D" && zip -9 -m <the archive> r<R>-<date>/shots.json)`, `trash "$D"`. Move the old `<folder>/rough.mov` and `<folder>/out/` sheets to the Trash (`trash <path>`, never `rm`). Nothing in `<folder>/selects/` is ever deleted, moved, renamed or overwritten, whatever round it is from: Edits projects link those files in place. Spawn `edit-builder` and wait for it, with this prompt:
   ```
   KIND: edit-reel. Step: cut. FOLDER: <folder>. JOB_DIR: <JOB_DIR> (job ledger reel.md). Round: r<R>. Rules:
   ~/Developer/vid-img-editing/motion/notes/print-reels.md, its "First cut" section first. Read every row of
   <folder>/footage-log.json, every note in the ledger's "Trevor's notes", every must fix and left out line of the
   newest review-N.md whose first line is RECUT, and <JOB_DIR>/check-r<R-1>.txt when the last round failed check.
   Song: <title>. Find its break and restart (video-edit.md "Finding a song's break") and count the beats back to
   <first beat>. Prove each stroke, lift and spin on a dense sheet before you use it:
   <py> <instaReels>/sheet.py <clip> <folder>/out/sheets/<name> 4 <in> <out>. Write <folder>/shots.json from
   footage-log.json in story order, "tripod": true only on still camera shots. Run
   <py> <instaReels>/reel.py cut <folder> <beats.json> <first beat>. A refusal: fix shots.json (shorter in/out or more
   beats) and run it again; never mark a moving shot tripod to pass. Join the files of the selects/<hash>/ folder it
   printed, in shot order, into <folder>/rough.mov with ffmpeg concat -c copy from a list file in <folder>/out/.
   Never delete, move, rename or overwrite anything in selects/. Never open Edits. Last line of your reply: the selects
   folder and the rough.mov path, or BLOCKED: <reason>.
   ```
   Record the round and the first beat in the ledger. A `BLOCKED:` line takes the shared step 4 ask, except a `reel.py cut` refusal, which goes to step 4's send back.
4. **Check.** Run `<py> <instaReels>/reel.py check <folder>` and save its whole output to `$F/jobs/$ID/check-r<R>.txt`. Exit 1, or a `reel.py cut` refusal from step 3, goes back to the builder with its lines (step 3, next round): no reviewer is spawned until check exits 0. After 3 rounds in a row that fail check or cut, write the last lines to stop.md and take the shared step 4 ask.
5. **Review.** `B set $ID stage=review`. Spawn a fresh `edit-reviewer`, never the session that built the cut, and wait for it, with this prompt:
   ```
   KIND: edit-reel. FOLDER: <folder>. JOB_DIR: <JOB_DIR> (job ledger reel.md). N: <N>. Round: r<R>. Make sheets of all
   of <folder>/rough.mov at 4 fps into <folder>/out/review-<N>/ (<py> <instaReels>/sheet.py <folder>/rough.mov
   <folder>/out/review-<N>/rough 4) and open every one; make denser sheets (15 to 30 fps) of any stitch, stroke start
   or stroke end you doubt. Read <folder>/shots.json, every row of <folder>/footage-log.json (every clip, not only the
   ones in the cut), ~/Developer/vid-img-editing/motion/notes/print-reels.md, the saved check output
   <JOB_DIR>/check-r<R>.txt and every earlier <JOB_DIR>/review-*.md. A check line, and check passing, is a floor: judge
   every shot by eye against every rule, the ones check cannot measure first: a sped moving camera, his hand mid stroke
   in each colour's pull, how long each colour's real pulls run, any shot with ink and nobody printing, the first shot
   that shows the finished print, a lift after every colour, and the end. Under left out, give for each colour at
   least one real pull from the log, from more than one angle. Write <JOB_DIR>/review-<N>.md.
   ```
   Record it in the ledger. A `RECUT` sends its notes back to step 3 (next round). A `PASS` goes to step 6; so does the third `RECUT` in a row, carrying the reviewer's notes to Trevor's card.
6. **Edits build.** `B set $ID stage=build`. It starts straight after a `PASS` (or the third `RECUT` in a row), with no storyboard and no rough cut approval. Every round is a new Edits project (File, New Project): never empty, reuse or delete an Edits project, never open an older one, and keep every round's export until Trevor approves one. The method is `motion/notes/video-edit.md` "What worked": the song started exactly on `<first beat>`, the numbered selects imported as separate clips (never rough.mov), then export. Edits takes Trevor's only mouse and keyboard, so nothing here clicks or types until he says he has stepped away. Never an idle timer: a quiet Mac is never a go.
   - First write the exact Edits steps for doing it himself to stop.md in the job folder:
     ```
     Edits, reel <project> round r<R>. Never press "Share to Instagram"; Trevor posts.
     1. File > New Project. Never open, empty or delete an older project.
     2. Cmd+I, Cmd+Shift+G, paste <folder>/selects/<hash>/, Cmd+A, import. Select every clip in Media, then "Add <count>".
     3. Audio > search "<title>" > click its row > "+". Drag the song right, drag its left edge out to the song's start,
        park the playhead on <mm:ss.ff> (ff in 60ths; arrow keys step 1/60 s), press Q, drag the song back to 0. The
        timecode readout then shows the song's length minus <mm:ss.ff>.
     4. Playhead at the video's end, select the song, press W.
     5. Export (no dialog; it saves to ~/Movies/Edits/Exports/). Then answer the card.
     ```
   - Then `touch $F/jobs/$ID/edits-asked`. The driven path is off (the **Headless computer use** line says `does not work`), so ask: `B ask $ID 'reel ready for Edits: the cut passed its checks, and the Edits steps are in the stop.md tab. Build and export it in Edits, then tap I exported it, or send notes?' --a "I exported it=resume $ID" --b "Send back with a note=rework $ID \"<your notes on the cut>\"" --c "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop.
   - On that resume, take the newest `~/Movies/Edits/Exports/*.mp4` newer than the marker (`find ~/Movies/Edits/Exports -maxdepth 1 -name '*.mp4' -newer $F/jobs/$ID/edits-asked`): record its absolute path, its modified time and its project name (the file name before its date) on the round's Edits line, and go to step 7. With no new export, ask the same question again: never a silent stop.
   - When the **Headless computer use** line says `works`, the ask instead says `B ask $ID 'reel ready for Edits: building it takes your mouse and keyboard, so step away from this Mac first. The steps to build it yourself are in the stop.md tab. Go once you have stepped away?' --a "I have stepped away, go=resume $ID" --b "Send back with a note=rework $ID \"<your notes on the cut>\"" --c "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'`, and on that resume a new export (as above) means he built it himself: go to step 7. Otherwise read `~/.claude/computer-use.lock` (`{"sessionId", "pid", "acquiredAt"}`): when its `pid` is alive (`kill -0 <pid>`), write the holder (pid, session id, `ps -o lstart=,command= -p <pid>`) and "type /exit in that chat" to stop.md and run `B ask $ID 'blocked: another Claude chat holds the mouse and keyboard, so Edits was not started. Which chat, and how to free it, is in the stop.md tab. Free it, then try again, or send notes?' --a "Try again=resume $ID" --b "Send back with a note=rework $ID \"<your notes on the cut>\"" --c "Remove this job=abort $ID --cascade" --title BUILDER_BLOCKED --recommend <key> '<why>'` and stop; that resume asks the stepped-away question again. Never remove the lock or close that chat. With no live holder, drive Edits from Bash with a child session, `claude -p --mcp-config <the config file the Headless line names> --strict-mcp-config --permission-mode dontAsk --allowedTools 'mcp__computer-use__*,Bash(ioreg:*)' '<the stop.md steps>'`, whose prompt also says: before each action sit still a few seconds and read `ioreg -c IOHIDSystem | awk '/HIDIdleTime/ {print $NF/1e9; exit}'`; under about 2 s HIDIdleTime means someone is at the Mac, so stop at once and reply `STOPPED: someone at the Mac`. A `STOPPED` reply asks the stepped-away question again; an export goes to step 7.
7. **Final approval.** Run `ffmpeg -i "<export>" -vf blackdetect=d=0.01:pix_th=0.10 -an -f null -` on the round's export: any `black_start` line sends it back to step 6 (a new Edits project, the black spans in stop.md), since Edits plays stale cached lengths as black. Compare a frame from the middle of each shot in the export with the same time in rough.mov; a shot that differs goes back to step 6 too. Draft the caption the way trevskills-email `captions.md` says (`~/.claude/skills/trevskills-email/captions.md`: long, the process and the ink, his wording) into `<folder>/caption.md`, replacing any older one. Write the export path, its Edits project name and the caption path to stop.md in the job folder (when capped, the latest review's notes too), write `$F/jobs/$ID/view.md` as one line `View: Edits`, replacing any older view.md (Edits takes no file; the dashboard's View button brings it forward), and ask Trevor:
   - Passed: `B ask $ID 'reel final: the finished reel is exported from Edits with no black frames, and a caption draft is ready. View opens Edits on this Mac; the export path is in the stop.md tab. Approve it, or send notes?' --a "Approve the reel=approve $ID" --b "Send back with a note=rework $ID \"<your notes on the reel>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.
   - Capped: `B ask $ID 'reel final: the reviewer sent this cut back 3 times, so it was built in Edits as it stands. Its notes, the export and the caption are in the stop.md tab. Approve it anyway, or send notes?' --a "Approve the reel anyway=approve $ID" --b "Send back with a note=rework $ID \"<your notes on the reel>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.

   On approve: `mkdir -p ~/Desktop/videos`, move that reel's previous Desktop copy (`~/Desktop/videos/<project>.mp4`) to the Trash with `trash`, `cp -c "<export>" ~/Desktop/videos/<project>.mp4`, run `ls -R ~/Desktop/videos`, record the copy on the round's Edits line, move this job's older exports of the reel (earlier rounds' Edits lines) to the Trash, then run `B set $ID stage=done`. Until then every round's export, project and Desktop copy stay as they are; Edits projects and `selects/` are never touched. Never press Share (`Share to Instagram`): Trevor posts the reel himself.
8. **His notes.** Each of Trevor's notes (a rework note, or a note with his approval) goes word for word, with its date and round, under the matching heading of `~/Developer/vid-img-editing/motion/notes/print-reels.md` and into the ledger's "Trevor's notes", the same day. When it can be measured (a length, a speed, an order, a count), spawn `edit-builder` with `KIND: edit-reel. Step: rule. FOLDER: <folder>. JOB_DIR: <JOB_DIR>. Note: <his note>. Add it to reel.py check as a measured rule, with a case in test_reel.py, then run <py> <instaReels>/test_reel.py until it passes. Last line: the rule's check line, or BLOCKED: <reason>.` and wait for it. Then a rework note starts the next round at step 3.
