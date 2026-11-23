### edit-reel

Instagram print reels cut from a print day's phone clips and finished in Edits (Instagram's Mac app), per `motion/video/instaReels/pipeline-handoff.md` "Reel flow". Reels have no storyboard and no rough cut approval: the only card Trevor sees is the finished export.

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

1. **Clips.** 
2. **Log.** 
3. **Cut.** 
4. **Check.** 
5. **Review.** 
6. **Edits build.** 
7. **Final approval.** 
8. **His notes.** 
