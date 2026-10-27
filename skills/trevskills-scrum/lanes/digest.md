# Digest

Learns from finished jobs. It runs from the main checkout (Setup applies, but not the Prerequisites: it needs no remote and no `gh`), and it never pushes, merges or opens a PR. It never edits an agent, skill, rule or memory file itself. It never asks Trevor: step 4 applies, queues or skips every proposal, then trims the digested job folders.

Each registered project's questions.log holds stop lines: kind `ask`, `stall`, `machine`, `refused` or `bigboy`, each with `date`, `project`, `job`, `kind` and `reason`. A digest is also due once questions.log grows 15 lines since the last digest, so `B digest-start` can claim zero jobs. The reader writes a `## Stops` section from those lines, and a `backlog` proposal is queued by `--digest-auto` and reported under `applied`.

1. Run `B digest-start`. Under the board lock it claims every `done` job that's in no earlier digest, and every usage-window scorecard no earlier digest lists, and prints `{"id", "jobs", "windows"}`. If `id` is null, say there is nothing to digest and stop. Otherwise `D=$F/digests/<id>`; run `B pipeline-fit <id> > $D/pipeline-fit.json`. `$D/windows.json` (the claimed usage-window scorecards) already sits in DIGEST_DIR beside `pipeline-fit.json` for the reader.
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

## Weekly

The cross-project weekly digest. serve.py's watchdog (`weekly_tick`) claims it in the last 2 days of the 7-day usage window, only while Fable has room, and starts `/trevskills-scrum weekly-digest <NNN>` headless in the trevskills-scrum project. It reads that week's done jobs from every registered project. It runs from the main checkout like **Digest**, and never edits a file, pushes, merges or opens a PR. Every proposal goes to Trevor as a question on its target repo's board; none is applied here. It never runs steps 1, 2 or 4 above, so no per-project digest is started, trimmed or applied.

1. `W=<weekly_dir>/<NNN>`, where `<weekly_dir>` is `$HOME/.claude/trevskills-scrum/weekly` (board.py `weekly_dir()`, beside `projects.json`). If `$W/jobs.txt` is missing, say there is no such weekly digest and stop.
2. Spawn `scrum-digester` with Agent override `model: "claude-fable-5-1"` and wait for it. Prompt:
   ```
   WEEKLY_DIR=$W
   Write proposals.json for this weekly digest.
   ```
   If the Agent tool rejects that model, write `$W/error.md` containing the one line `fable unavailable` and stop. Never respawn it without the override. Check `$W/proposals.json` exactly as step 3 above checks `$D/proposals.json`: on a failure, spawn it once more with the same override; if it still fails, write `$W/error.md` containing the one line `digester produced no valid proposals` and stop.
3. Run `python3 ~/.claude/skills/trevskills-scrum/serve.py --weekly-ask <NNN>`. It prints `{"asked": [{"id", "project", "job"}], "skipped": [{"id", "reason"}]}`. Each `asked` proposal is now a needs-human job on its project's board with **Build it** and **Skip it**; each `skipped` one never will be. Report each asked proposal as `<pid> → <project> <job>`, then each skipped proposal as `<pid> skipped: <reason>`.
