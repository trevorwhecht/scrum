# Run all

Cleans the backlog, then runs every open item as a child job of one Run-all parent, in parallel where files don't overlap, with nobody watching. Setup and Prerequisites apply. Trevor stops it by interrupting or closing its Terminal window.

1. Run `B triage-start`. Under the board lock it claims `$F/triage/<id>/` and prints `{"id", "open"}`. If `id` is null, say the backlog is empty and stop.
2. Spawn `scrum-triager` with the Agent tool override `model: "sonnet"` (first spawn and the respawn below) and wait for it. Prompt:
   ```
   TRIAGE_DIR=$F/triage/<id>
   BACKLOG=$F/backlog.md
   PROJECT=$F/project.md
   Write plan.json for this triage.
   ```
   If `$F/triage/<id>/plan.json` is missing afterwards, spawn it once more.
3. Run `B triage-apply <id>`. It merges, retires, moves manual-only items to `$F/manual-checks.md`, estimates and adds dependencies (the plan's `depends` entries become `{needs …}` markers) under the board lock, skips stale entries, and writes `$F/triage/<id>/report.md` and `$F/triage/latest.md`. If it exits non-zero (including when plan.json is still missing), write `Triage <id> failed: <message>` to `$F/triage/latest.md`, with its error line as the message, and continue. A failed triage never blocks the run.
4. Run `B watchdog`; for each flagged id that has a `parent`, run **BigBoy lane** step 6 with `ID=<that id>`. Then run `B runall-start`. Under the board lock it makes a `lane=runall` parent with every open backlog item as a `waiting` child and prints `{"id", "children"}`. A child whose item needs another item claimed in the same run `depends_on` that sibling, so `B ready` holds it until the sibling is `done`; an item waiting on a job outside the run stays open and gets no child. If `id` is null, say the backlog is empty (or every open item waits) and stop. Otherwise `P` is that id.
5. **Askme** (only for `run-all askme <n>`; otherwise skip to step 6). Record no terminal here; Run all never does. For each child in `runall-start`'s `children`, in that order, run a question round with Trevor in this same session, exactly as New job step 1c does for one job: read `$F/jobs/<child>/feature.md` (and `$F/jobs/<child>/spec.md` when the item came with one), ask at that level's semantics from step 1c (level 1 only what blocks the build, level 2 a moderate number, level 3 thorough; a bad or missing level means level 2), with follow-ups when an answer is unclear. Say which item each round is about. Spawn no agent and edit no file except the children's `feature.md` and `spec.md` while asking. After each child's round, append its pairs to `$F/jobs/<child>/feature.md`, one pair per question asked, follow-ups included:
   ```
   ## Q&A
   - Q: <question>
     A: <Trevor's answer>
   ```
   A child with no questions gets no `## Q&A` section. When a child already had a pre-written `spec.md` and got at least one Q&A pair, delete that `spec.md`: the answers are Trevor's decisions, so its spec is rewritten from them in step 6 or in its own `start`. A child with no pairs keeps its `spec.md`. If Trevor says to skip or stop, write the pairs answered so far for the current child (and delete its `spec.md` if it got any), ask nothing for the remaining children, and carry on. This is the only place Run all asks questions; no child `start` session ever asks.
6. Run **BigBoy lane** step 2 for P's children.
7. Run **BigBoy lane** step 3 for `P`, then give the final report. Never ask questions here outside step 5.

Each child starts through `start <child>`, so **New job** step 3's Lilguy route (`B lilguy-fit`) routes a tiny child to the **Lilguy lane** the same way.

The final report lists the Run-all parent id, the children it created, which children started in this session, then what the triage merged, retired, moved to manual checks, estimated and added dependencies for (counts from `triage-apply`, `depends` included, or the failure line).
