# BigBoy lane v2: structure (Trevor's answers applied 2026-10-13)

Replaces the "epic" lane. For work too big for one job. Evidence is in `triage-lanes.md`.

## Flow

```
request (spec writer says Lane: bigboy, or /trevskills-scrum bigboy <feature>)
  └─ PLANNER (Opus) writes plan.md: frozen goal, 2-5 tickets, dependencies, parallel + why
       └─ children created at once; each gets its spec right away (parallel, cheap)
            └─ child waits until every dependency has merged (and any Human setup is done)
                 └─ build ─► check ─► review ─► its own PR, merged to main (in its own lane)
                      └─ after each merge: TRACKER (Sonnet) checks the goal ─► starts ready children
  └─ after the last merge: BIGBOY REVIEW (Opus) checks the whole goal on main
```

## Rules

**Planner**
- **Ticket count:** 2-5 tickets. Each is a vertical slice that is **safe to be live on its own**.
- **Exposure ticket last:** the ticket that shows the feature to users (nav link, button, route) depends on all the others. Main can then take each merge without users seeing half a feature, with no integration branch and no feature flags.
- **Parallel:** chosen case by case with a reason (disjoint files, and neither needs the other's output). The orchestrator re-checks it from the specs' Likely files; any overlap means one after the other. There is no fixed cap; the digester tunes the rule from results.
- **Bigger than 5 tickets:** the planner writes Phase 1 (up to 5 tickets) and records Phase 2 as one backlog item that depends on this BigBoy. That is the only recursion, one level at a time.
- **Human setup:** a ticket needing manual setup gets a `Human setup:` line. It waits, highlighted on the dashboard, until Trevor clicks Setup done. Tickets that don't depend on it keep going.
- **Hard stops** (schema, auth, money, secrets) are flagged per ticket. They stop for Trevor at merge, as any job does.
- **No plan approval.** If the request is unclear, the planner records its reasoning under Assumptions and Diverged, like every agent. Askme, when used, runs before the planner.

**Scheduling**
- **Board fields:**
  - Parent: `lane=bigboy`, `children`, `stage` (plan, running, review, done).
  - Child: `parent`, `depends_on`, `parallel`, and stage `waiting` until it's ready.
- **`B ready <parent>`** lists children whose dependencies have all merged. The run that merges a child starts each ready child as its own fresh session (`claude -p "/trevskills-scrum start <child>"`, detached, the same way the dashboard does). This is automatic chaining, with no watcher.
- **`B next` and Run all skip** BigBoy parents and waiting children, so they're never double-started.
- **Spec refresh:** when a waiting child becomes ready, a Sonnet check compares the merged dependency diffs with its spec's Likely files. Only on overlap does the spec writer refresh the spec.
- **A child that ends needs-human or aborted** blocks only the children that depend on it. Independent tickets continue.

**Tracker (Sonnet, after each child merges)**
Reads the frozen Goal and Done-when, the merged diffs so far, and the remaining tickets. Writes `track-<n>.md` with one of:
- `ON TRACK`: continue.
- `ADJUST`: rewrites remaining unbuilt tickets (scope must not grow), and records the change as Diverged on the parent.
- `OFF TRACK`: stops the parent as needs-human, with a clear reason and next step.

**BigBoy review (Opus, once, after the last merge)**
Checks Done-when on main, and runs the full test suite.
- `PASS`: the parent is done.
- `GAPS`: at most one fix ticket, run as a normal child. Remaining gaps go to needs-human.

**Dashboard**
- **Parent card:** "T2/4 merged", a lane chip `bigboy`, and its children listed under it with their dependency arrows.
- **plan.md** opens like any job file. A Diverged badge appears if the tracker adjusted the plan.

## Cost guardrails

- **Model split:** one planner and one final review on Opus. The tracker, spec refresh, and children's fast lanes use Sonnet where allowed.
- **Fresh sessions:** each child runs in its own session, never one long session.
- **Measured afterwards:** the digester reports per-BigBoy cost and how parallel runs went, and proposes rule changes.

## What I changed from v1, and why

1. **Exposure ticket last** (new). Without it, merging each ticket to main shows users a half-built feature. The alternatives cost more: an integration branch gives one huge final PR plus drift; feature flags add code.
2. **Phase 2 instead of "split once, then needs-human".** Over 5 tickets now continues automatically, one bounded level at a time.
3. **Chaining from inside the merge step**, with no external watcher. Run all and `B next` skip BigBoy children.
4. **Human setup** waits per ticket and doesn't block independent tickets. This reuses the Human setup job.
5. **A failed child blocks only its dependents**, not the whole BigBoy.
6. **Spec refresh only on file overlap**, so it costs nothing when nothing changed.
7. **No plan approval;** assumptions and Diverged give the trail. This is your answer #3.
