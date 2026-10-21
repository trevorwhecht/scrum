# scrum-unblocker: diagnose a stop before it reaches Trevor

Agreed with Trevor 2026-10-21. Builds on job 180 (every stop becomes `B ask`) and on research/skill-standards-gate.md.

## Why
Many needs-human stops are not decisions only Trevor can make: the pipeline knows what is wrong but not what to do.
Job 179 stopped on "SKILL.md 95938 bytes, over the 95000 budget"; three read-only commands showed most of the job's
+1,000 bytes copied text already in BigBoy lane step 3, so the fix was "send back: reuse it", not "raise the budget".

## What it is
`agents/scrum-unblocker.md`. model: opus. Tools: Read, Grep, Glob, Bash (read-only git, the project's test command),
Write (only `JOB_DIR/unblock-N.md`). It never edits code; the builder stays the only code writer.

## Where it hooks in (agreed changes)
- **No new `B block` command and no new stage.** It hooks into `B ask`, the one choke point every stop goes through
  after job 180. `B ask` takes a `--kind <kind>`; board.py decides eligibility from an allowlist of kinds plus the
  job's `unblocks` counter (max 2). Eligible: the orchestrator spawns the unblocker before the ask is shown, and the
  job stays in the stage it stopped in, so watchdog and "stalled in <stage>" resume keep working.
- Eligible kinds: round limit hit with CHANGES still wanted, check/CI fix loop exhausted, conflict or semantic
  conflict with main, a test failure the diff explains, approver `blocked` (e.g. UI not rendered).
- Never eligible (code decides, not a model): schema/migration and `migrate stopped`, the agent-rules guard (that is
  the standards gate's job), gh missing or signed out, credentials or human setup, approver `Hard stop:` ESCALATE,
  prod data or secrets.
- **Loop guard compares the kind, not the text**: a second unblock of the same kind on the same job escalates at
  once. Unblock rounds count toward the job's round limit.
- Its detail lives in `skills/trevskills-scrum/lanes/unblock.md`; SKILL.md gets a one-line pointer only.

## Output: JOB_DIR/unblock-N.md
    VERDICT: REWORK | RESPEC | ESCALATE
    <one line: the blocker in plain words>
    ## Evidence            <command> -> <the number or line that shows it>
    ## Options considered  <option>: rejected because <reason>  (always weigh "raise the limit" when it applies)
    ## Instructions        numbered; last line "Done when: <exact check>"  (REWORK -> builder, RESPEC -> spec writer)
    ## For Trevor          ESCALATE only: recommended button + paste-ready text

## Rules
- Measure before recommending: every claim has a command and its output behind it.
- Fix the cause, never loosen the check, unless the evidence shows the check itself is wrong, and say why.
- Look for duplication first (global Code Reuse rule).
- Stay inside the spec; a fix that changes what the ticket delivers is RESPEC.

## What the orchestrator does
- REWORK: resume scrum-builder with "Read JOB_DIR/unblock-N.md and follow Instructions", then check -> reviews -> approve.
- RESPEC: spawn scrum-spec-writer to revise spec.md from Instructions, then rebuild.
- ESCALATE: the `B ask` is shown with the For Trevor block as its bound buttons, so it is one click.

## Learning loop
Append `<id> <kind> <verdict> <blocker>` to questions.log so the digest sees repeat blockers.

## Tests
Agent file pins model: opus, no Edit, no Agent; `B ask --kind <hard stop>` never unblocks; an eligible kind unblocks
until `unblocks` hits 2 or the kind repeats; SKILL.md mentions lanes/unblock.md.
