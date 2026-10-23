# Roadmap lane: design

A roadmap strings bigboys and standard jobs into ordered phases, chains them without a human, and shows where it is on the board. It exists because the onewitharts cleanup (2026-10-14/15) ran 3 bigboys by hand from a memory file: the board had no idea of phases, each handoff waited 40 min to 1h20 on someone noticing, and a cleared orchestrator could not tell where it had left off.

## Decisions (from Trevor, 2026-10-15)

1. **A step is one bigboy or one standard job.** Both count, numbered within their phase. A phase can grow (8 steps becoming 10); when it does, `roadmap.md` is updated in the same moment.
2. **`scrum/roadmap.md` is the single source of truth** and the resume doc. A fresh orchestrator reads it and knows the phase, the step, what is next and what blocks it. Nothing about the roadmap lives only in memory.
3. **Auto-chain.** When a step finishes, the next one starts with no prompt. It stops only where a bigboy or job already stops today (FAIL, GAPS twice, ESCALATE, OFF TRACK, needs-human).
4. **Board display.**
   - A banner above the columns per project with a roadmap: `onewitharts roadmap · P1/2 Split giant files · S2/10`, then `next: S3 <title> · blocker: <none | job id + reason>`.
   - Cards of roadmap jobs get one meta line `P1/2 · S2/10`: above `T3/5 merged` on a bigboy card, in front of `T2 of <parent>` on a child card (`P1/2 · S2/10 · T2 of 017-...`), alone on a standard step card.
   - The lane chip is unchanged. Jobs outside a roadmap look exactly as today.

## Retro decisions (onewitharts cleanup roadmap, 2026-10-21)

- **An environment-blocked render is never a stop.** When every review and the check pass and the only gap is a reviewer's `Rendered: blocked`, the job merges with a manual check; the chain keeps moving. S2 lost 12h10m of 14h54m to two such stops (047, 048).
- **No silent stall.** Every stall of a roadmap job or its child writes a `## Log` line and marks the step `[!]`, including a watchdog flag or an exited session that serve.py handles. 051 sat 5h32m with no log line.

## roadmap.md

One per project at `scrum/roadmap.md` (gitignored like the rest of `scrum/`). Plain markdown a human can edit:

```
ROADMAP: onewitharts cleanup
Goal: clean up mixed v0/Cursor/Claude patterns, make it faster, ready to clone into billmeez.

## Constraints
- Zero behaviour change in splits.
- `calculateBlankCostFromSizes` stays the single blank-cost function.

## P1 Split giant files
- [x] S1 bigboy 011-split-quote-builder-content-tsx-13-5k-li: Split quote-builder-content.tsx, part 1
- [~] S2 bigboy 017-quote-builder-bigboy-2-move-state-and-ef: Quote builder part 2, state and effects into hooks
- [ ] S3 bigboy: Quote builder part 3, <request>
- [ ] S4 standard: Split garmentDesigner
## P2 Speed
- [ ] S1 standard: Profile and fix the order-progress endpoint (~3.3s)

## Log
- 2026-10-15 09:12 P1 S1 done: BIGBOY PASS
```

- Status box: `[ ]` todo, `[~]` running, `[x]` done, `[!]` stopped (needs a human).
- After the kind comes the job id once the step has a job, then `:` and the request. A todo step's request is the full feature text the step starts with.
- `## Constraints` lines are appended to every step's `feature.md` when it starts, so they are never re-typed by hand.
- `## Log` gets one line per step state change, newest last.

## board.py

All three run under the board lock and change `roadmap.md` only.

- `roadmap-show` prints `{name, phases: [{n, title, steps: [{n, kind, job, status, request}]}], current: {p, s}, next: {p, s, kind, request} | null, blocker: {job, reason} | null}`, or `null` when there is no roadmap. `blocker` is the current step's job (or its needs-human child) when that job is `needs-human`.
- `roadmap-link <P> <S> <job>` writes the job id into the step and marks it `[~]`.
- `roadmap-next <job>` marks the step holding `<job>` `[x]` and logs it, then prints the next todo step (same shape as `next` above) or `null`. A job not in the roadmap prints `null` and changes nothing, so the hook is safe to call for every finished job.
- `roadmap-insert <P> <after S> <kind> <request>` adds a step and renumbers the rest of that phase.
- `roadmap-stop <job> <reason>` marks the step `[!]` and logs the reason. It is cleared back to `[~]` by `roadmap-link` when the job is resumed.

## SKILL.md: Roadmap lane

- **`/trevskills-scrum roadmap <brief>`**: this session drafts `roadmap.md` from the brief (phases, steps, constraints), shows it to Trevor once, and on his yes starts P1 S1.
- **Bare `/trevskills-scrum roadmap`**: prints `roadmap-show` as a status block.
- **Starting a step**: a `bigboy` step runs the BigBoy lane with the step's request plus the constraints; a `standard` step runs New job. Then `B roadmap-link`.
- **Hooks** (each one line in the existing steps):
  - BigBoy step 7, `BIGBOY: PASS`: if plan.md has `## Phase 2` and the parent is in a roadmap, `B roadmap-insert` it as the next step of the same phase instead of `backlog-add`. Then `B roadmap-next $P` and start what it prints.
  - Merge step 7, a job with no parent: `B roadmap-next $ID` and start what it prints.
  - Every place a roadmap job, or a child of one, goes `needs-human`: `B roadmap-stop`.
- **Resume**: Setup reads `roadmap-show`; a `[~]` step whose job is done (the hook was missed) is finished with `roadmap-next` before anything else.

## serve.py and dashboard.html

- `GET api/p/<project>/roadmap` returns `roadmap-show` (reusing the board.py parser, not a second one), fetched in `poll()` alongside digests.
- The dashboard maps job id to `(p, s)` from the roadmap: a step's own job, or any job whose `parent` is that job. That one lookup feeds the card meta line and the banner. No board.json change.

## Testing

- `tests/test_board.py`: parse, link, next (including the not-in-roadmap no-op), insert renumbering, stop and resume, and a malformed file reported with its line number.
- `tests/test_serve.py`: the roadmap endpoint for a project with and without `roadmap.md`.
- `tests/test_contracts.py`: SKILL.md documents the lane and both hooks.

## Rollout

Seed `onewitharts/scrum/roadmap.md` from the memory file and the board (P1 S1 = 011 done, S2 = 017 running, S3 = quote-builder part 3, then OrdersView, account page and the 5 standard splits; P2 = speed and tax), and point the memory file at it.

## Out of scope (separate backlog items from the retrospective)

- A known-noise list so reviewers stop re-flagging overridden findings (`.env.example` was flagged in 6 jobs).
- A fixture or staging DB so money screens get a real browser check (unverified in 012-016, 018, 019).
- Batching auth hard-stop approvals into one click.
