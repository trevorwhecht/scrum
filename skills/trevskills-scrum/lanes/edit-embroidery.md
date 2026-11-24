### edit-embroidery

Embroidery digitizing made with the digitize skill (`$HOME/.claude/skills/trevskills-digitize/SKILL.md`). Trevor approves every version. No MCP and no `--mcp-config`: the builder and reviewer use Bash only (Ink/Stitch headless plus Python), so `EDIT_MCP` has no entry for this kind.
1. **Folder.** The job's feature.md names the source art file and a design name. FOLDER is `~/Developer/vid-img-editing/digitizing/scripts/digitize-<name>/`; the builder makes it when it does not exist. The job ledger is `$F/jobs/$ID/embroidery.md`. The kind's rules files are the skill's SKILL.md and `~/Developer/vid-img-editing/digitizing/notes/embroidery-digitizing.md`, both read in full by every builder and reviewer.
   - **Bad folder:** when FOLDER is not under `~/Developer/vid-img-editing/digitizing/`, or feature.md names no source art file, or that file is missing on disk, start nothing. Write the path and why to stop.md in the job folder, then run the shared step 4 ask (`BUILDER_BLOCKED`) and stop.
2. **Ledger.** `embroidery.md`, created on the first run: `# Embroidery ledger`, then `## Versions` (`- v<V>: <file's absolute path> — reviewer PASS | capped — Trevor: pending | notes | approved`), `## Reviews` (`- review-N.md: v<V> — RECUT | PASS`) and `## Trevor's notes` (`- <ISO time> (v<V>): <his note, word for word>`). Each note is also copied word for word into `~/Developer/vid-img-editing/digitizing/notes/embroidery-digitizing.md`. The next version is one more than the highest `v<V>` in the ledger. An `approve` means the newest version.
3. **Build.** `B set $ID stage=build`. Spawn `edit-builder` and wait for it, with this prompt:
   ```
   KIND: edit-embroidery. Step: build. JOB_DIR: <JOB_DIR> (job ledger embroidery.md). FOLDER: <FOLDER>. Brief: <JOB_DIR>/feature.md. Follow
   $HOME/.claude/skills/trevskills-digitize/SKILL.md and ~/Developer/vid-img-editing/digitizing/notes/embroidery-digitizing.md. Make everything, the stitch
   files included, in FOLDER; put throwaway tools (Ink/Stitch, the venv) and renders in <FOLDER>/out/. The design is the art's own size unless feature.md says otherwise.
   Make the DST and its editable SVG (a PES only when feature.md or a note asks), and out/preview.png: the sewn thread drawn over the art with the size in inches on it. Apply every note in the ledger's "Trevor's notes" section and every
   must fix line in the newest review-N.md whose first line is RECUT. Last line of your reply: the DST's absolute
   path, or BLOCKED: <reason>.
   ```
   A `BLOCKED:` line takes the shared step 4 ask.
4. **Review.** `B set $ID stage=review`. Spawn a fresh `edit-reviewer`, never the session that built the version, and wait for it, with this prompt:
   ```
   KIND: edit-embroidery. JOB_DIR: <JOB_DIR> (job ledger embroidery.md). FOLDER: <FOLDER>. N: <N>. Version: v<V>, file <path>. Run
   `python -I ~/Developer/vid-img-editing/digitizing/scripts/audit.py <the DST>` yourself (RECUT unless it prints PASS; its size notes are not failures). Measure the DST's
   width and height against the source art (RECUT when either is over 2 percent off and feature.md names no other size). Draw your own render of the DST and look at it against the art.
   Check it against the brief, every note in the ledger and the rules in $HOME/.claude/skills/trevskills-digitize/SKILL.md and
   ~/Developer/vid-img-editing/digitizing/notes/embroidery-digitizing.md. Write <JOB_DIR>/review-<N>.md.
   ```
   A `RECUT` sends its notes back to step 3 (same `v<V>`). After the third `RECUT` in a row on the same cut, ask with the capped question below.
5. **Version round.** Each passing version is recorded in the ledger. The step right before the ask writes `$F/jobs/$ID/view.md` as one line `View: Preview <absolute path of out/preview.png>`, replacing any older view.md (the dashboard's View button runs `open -a` on it), and `$F/jobs/$ID/preview.md` with one `- <absolute path>` line, that same PNG, replacing any older preview.md (the dashboard shows it in the stop box). It also writes stop.md in the job folder: the size in inches, stitch count, trims, longest stitch, the audit result, and that no file is ready for a run before a test sew-out. Then ask Trevor:
   - Passed: `B ask $ID 'embroidery edit: a new version passed review. The preview is open from the View button and the numbers are in the stop.md tab. Approve it, or send notes?' --a "Approve this version=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this version>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.
   - Capped: `B ask $ID 'embroidery edit: the reviewer sent this version back 3 times in a row, so the builder stopped trying. The reviewer notes are in the stop.md tab.' --a "Approve this version anyway=approve $ID" --b "Send back with a note=rework $ID \"<your notes on this version>\"" --c "Remove this job=abort $ID --cascade" --title EDIT_APPROVE --recommend <key> '<why>'` and stop.

   His notes start the next build round (step 3, version `v<V>` plus one), and only his approval ends the job: a reviewer `PASS` never does.
6. **One current version.** Follow `~/.claude/rules/one-current-version.md` when it exists: on a new build round move the older versions to the Trash (`mv <file> ~/.Trash/`, never `rm`) and keep one current file; move `<FOLDER>/out/` to the Trash on approval. On Trevor's approval, before `B set $ID stage=done`: zip any file the delivery replaces into `~/Desktop/ArtFiles/Embroidery/Archivve/<Name>-<Garment>-archive.zip` (`zip -9 -m`), copy the DST and SVG (and the PES when asked) to `~/Desktop/ArtFiles/Embroidery/<Name>-<Garment>/`, check each copy with `cmp`, `ls` the folder and record it in the ledger. Nothing is written to the Desktop before approval. Then run `B set $ID stage=done`.
