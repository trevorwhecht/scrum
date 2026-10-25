# Digest

Learns from finished jobs. It runs from the main checkout (Setup applies, but not the Prerequisites: it needs no remote and no `gh`), and it never pushes, merges or opens a PR. It never edits an agent, skill, rule or memory file itself. Step 4 handles the edit proposals the digester marked obvious: serve.py applies each one whose old text occurs exactly once and whose repo's contract tests still pass, and commits them locally under one `lilguy` board job; any it can't apply becomes a repo backlog item. Trevor approves or rejects every other proposal from its needs-human card on the board or in the dashboard's **Digest** dialog. The last decision trims the digested job folders.

1. Run `B digest-start`. Under the board lock it claims every `done` job that's in no earlier digest and prints `{"id", "jobs"}`. If `id` is null, say there is nothing to digest and stop. Otherwise `D=$F/digests/<id>`.
2. Spawn `scrum-digest-reader` (see **Routing**) and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   JOBS_DIR=$F/jobs
   Write notes.md for this digest.
   ```
   If `$D/notes.md` is missing or its first line isn't exactly `DIGEST NOTES` (`head -1 "$D/notes.md"`), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digest reader produced no notes` and stop.
3. Set `R=$(cd "$(realpath ~/.claude/skills/trevskills-scrum)/../.." && pwd)`, then spawn `scrum-digester` and wait for it. Prompt:
   ```
   DIGEST_DIR=$D
   PROJECT=$F/project.md
   ROUTING=$R/local/routing.json
   Write proposals.json for this digest.
   ```
   If `python3 -m json.tool "$D/proposals.json"` fails, or the file has no `proposals` list (`python3 -c 'import json,sys; sys.exit(not isinstance(json.load(open(sys.argv[1])).get("proposals"), list))' "$D/proposals.json"` exits non-zero), spawn it once more. If it still fails, write `$D/error.md` containing the one line `digester produced no valid proposals` and stop.
4. If the `proposals` list is empty, run `B digest-trim <id>`. Otherwise run `python3 ~/.claude/skills/trevskills-scrum/serve.py --digest-auto <id> --dir $F`. It prints `{"applied": [{"id", "target", "obvious_reason"}], "queued": [{"id", "target", "obvious_reason", "reason"}], "human": [{"id", "reason"}], "job"}`. `applied` proposals are already edited and committed (not pushed) under board job `job`; `queued` ones became backlog items. Report each applied proposal as `<pid> → <target>: <obvious_reason>` and the commit's job id, then each queued proposal as `<pid> → <target> queued: <reason>`, then the number of `human` proposals left for Trevor on the board.
