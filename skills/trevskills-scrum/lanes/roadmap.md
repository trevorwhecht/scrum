# Roadmap lane

A roadmap strings bigboy and standard jobs into ordered phases in `$F/roadmap.md`, and chains each step into the next with no prompt. `roadmap.md` is the single source of truth and the resume doc. Only ever change it through `B` (`roadmap-link`, `roadmap-next`, `roadmap-insert`, `roadmap-stop`), except when drafting it below. Each step stops only where its job or bigboy already stops.

1. **Draft** (`/trevskills-scrum roadmap <brief>`; Setup and Prerequisites apply). If `$F/roadmap.md` already exists, say so, change nothing and stop. Otherwise draft it from the brief in this exact format, which `board.py` parses:
   ```
   ROADMAP: <name>
   Goal: <one line>

   ## Constraints
   - <rule every step must keep>

   ## P1 <phase title>
   - [ ] S1 <bigboy|standard>: <request>
   - [ ] S2 <bigboy|standard>: <request>
   ## P2 <phase title>
   - [ ] S1 <bigboy|standard>: <request>

   ## Log
   ```
   Show the draft to Trevor once. On his yes, write it to `$F/roadmap.md`, run `B roadmap-show`, and do **Starting a step** with its `next` (P1 S1). On anything else, write nothing and stop.
2. **Status** (bare `/trevskills-scrum roadmap`). Run `B roadmap-show`. If it prints `null`, say there is no roadmap. Otherwise print:
   ```
   <name>
   P<p>/<phases> <phase title> · S<s>/<steps in that phase>
   next: S<n> <request>      (or: next: none)
   blocker: <job> <reason>   (or: blocker: none)
   ```
   `p` and `s` come from `current`. It starts nothing.
3. **Starting a step** `<P> <S> <kind> <request>`, run in this session. The feature text is the request, a blank line, then every `- ` line under `## Constraints` in `roadmap.md`, copied verbatim. A `bigboy` step runs exactly as `/trevskills-scrum bigboy <feature text>`; a `standard` step runs **New job** with that feature text. Right after `B new` gives `$ID`, run `B roadmap-link <P> <S> $ID`.
4. **Stop rule.** Whenever this session sets a job `stage=needs-human`, or auto-aborts it (**Auto-abort instead of needs-human**), the step job is that job, or its `parent` for a BigBoy child. If `B roadmap-show` lists that id as a step's `job`, run `B roadmap-stop <that id> '<reason>'`, with the reason quoted under the **Untrusted reason text** rule. With no roadmap, or with the id in no step, skip the call: `board.py` exits non-zero for a job in no step.
5. **Resume.** Setup's **Roadmap resume** finishes a `running` step whose job is already `done` (`B roadmap-next`) and starts what it prints before the requested command.
6. **Roadmap done** (from Merge step 7 when `B roadmap-next $ID` prints `null`). Run `B roadmap-show`. A job in no roadmap, or a roadmap whose `current` is not `null` (a `running`, `stopped` or `todo` step is left), starts nothing. If it prints a roadmap that lists `$ID` as a step's `job` and whose `current` is `null`, and `grep -q '^- \[ \] ' "$F/backlog.md"` succeeds, start run-all detached from the main checkout with **BigBoy lane** step 3's start block, launching `run-all` instead of `start <child>`: `LOG` is `<timestamp>-run-all.log`, the prompt is `/trevskills-scrum run-all`, and there is no `B set <child> runlog=` line, because there is no job yet. Report `Run all started: runs/<LOG>`. An empty backlog starts nothing, and so does a missing `backlog.md`.
