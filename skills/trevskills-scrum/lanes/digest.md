# Digest

Learns from finished jobs. It runs from the main checkout (Setup applies, but not the Prerequisites: it needs no remote and no `gh`), and it never pushes, merges or opens a PR. It never edits an agent, skill, rule or memory file itself. It never asks Trevor: step 4 applies, queues or skips every proposal, then trims the digested job folders.

Each registered project's questions.log holds stop lines: kind `ask`, `stall`, `machine`, `refused` or `bigboy`, each with `date`, `project`, `job`, `kind` and `reason`. A digest is also due once questions.log grows 15 lines since the last digest, so `B digest-start` can claim zero jobs. The reader writes a `## Stops` section from those lines, and a `backlog` proposal is queued by `--digest-auto` and reported under `applied`.

1. Run `B digest-start`. Under the board lock it claims every `done` job that's in no earlier digest and prints `{"id", "jobs"}`. If `id` is null, say there is nothing to digest and stop. Otherwise `D=$F/digests/<id>`; run `B pipeline-fit <id> > $D/pipeline-fit.json`.
2. Spawn `scrum-digest-reader` (see **Routing**) and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   JOBS_DIR=$F/jobs
   Write notes.md for this digest.
   ```
   If `$D/notes.md` is missing or its first line isn't exactly `DIGEST NOTES` (`head -1 "$D/notes.md"`), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digest reader produced no notes` and stop.
3. Spawn `scrum-digester` and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   PROJECT=$F/project.md
   Write proposals.json for this digest.
   ```
   If `python3 -m json.tool "$D/proposals.json"` fails, or the file has no `proposals` list (`python3 -c 'import json,sys; sys.exit(not isinstance(json.load(open(sys.argv[1])).get("proposals"), list))' "$D/proposals.json"` exits non-zero), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digester produced no valid proposals` and stop.
4. If the `proposals` list is empty, run `B digest-trim <id>`. Otherwise run `python3 ~/.claude/skills/trevskills-scrum/serve.py --digest-auto <id> --dir $F`. It prints `{"applied": [{"id", "target", "why"}], "queued": [{"id", "target", "why", "reason"}], "skipped": [{"id", "target", "reason"}], "job"}` and trims the digest. `applied` proposals are already edited (repo edits committed and pushed to origin under board job `job`, then main fast-forwarded; global files written in place after a backup); `queued` ones became backlog items; `skipped` ones were not applied and never will be. Report each applied proposal as `<pid> → <target>: <why>` and the commit's job id, then each queued proposal as `<pid> → <target> queued: <reason>`, then each skipped proposal as `<pid> → <target> skipped: <reason>`.
