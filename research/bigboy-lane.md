# BigBoy lane: structure (Trevor's answers applied 2026-10-13)

Replaces the "epic" lane. For work too big for one job. Evidence is in `triage-lanes.md`.

## Flow

```
request
  └─ Askme (optional): questions with Trevor at level 1-3 (see Askme)
  └─ Spec writer says Lane: bigboy  (or Trevor forces it: /trevskills-scrum bigboy <feature>)
       └─ PLANNER writes plan.md; no plan approval, it proceeds on its own
            └─ orchestrator creates child jobs T1..Tn; all go to SPEC now
                 └─ each child: spec ──► waiting (until its dependencies have merged)
                      └─ build ─► check ─► review ─► (approver) ─► own PR, merged to main
                           └─ after each merge: TRACKER drift check ──► start the next ready ticket(s)
            └─ after the last merge: BIGBOY REVIEW of the whole goal against plan.md
```

## Askme (questions instead of plan approval)

- **Level:** Trevor sets 1-3; the agent decides how many questions to ask within it. 1 asks only what blocks the build, 2 asks moderately, 3 is thorough. Off by default.
- **Without askme:** agents keep the unattended rule: make the reasonable call and record it with its reasoning under Assumptions. That is acceptable.
- **Unclear answers:** if Trevor's answers are unclear, it asks follow-up or different questions before planning.
- **Where it runs:** interactively, like Discuss. Answers are saved to feature.md under `## Q&A`.

## plan.md (written by the planner, frozen once written)

    # <Goal>
    Goal: <one paragraph; never edited after it is written>
    Done when:
    1. <observable outcome for the whole feature> (verify: ...)
    ## Tickets
    | # | Title | Lane | Points | Depends on | Parallel | Why |
    | T1 | ...   | standard | 5 | - | - | foundation |
    | T2 | ...   | fast | 2 | T1 | yes, with T3 | disjoint files |
    | T3 | ...   | standard | 3 | T1 | yes, with T2 | disjoint files |
    | T4 | ...   | standard | 3 | T2, T3 | no | integrates both |
    ### T1: <title>
    Scope: in / out. Acceptance criteria. Likely files. Hard stops.

## Planner rules

- **Ticket count:** 2-4 tickets, at most 5. Each must be shippable and visible on its own, and none smaller than about 3 points; merge smaller ones. Tickets that would edit the same files are merged, or chained with a dependency.
- **Parallel:** no fixed cap. The planner decides case by case and gives its reasons in plan.md. Parallel is `yes` only when tickets touch disjoint files and neither needs the other's output. The orchestrator re-checks this from the specs' Likely files; any overlap makes them run one after the other. The digester reviews how parallel runs went (conflicts, cost, rework) and proposes rule changes.
- **Depth:** a ticket the spec writer flags as too big is split once by the planner. If it's still too big, it goes to Trevor (needs-human). No unlimited recursion.
- **Lanes:** every ticket gets its own lane (fast, standard or debug). Hard-stop tickets (schema, auth, money, secrets) are flagged in the plan. They still stop for Trevor's sign-off at merge, the same as any job.

## Waiting and scheduling

- **Specs up front:** all child specs are written as soon as the plan exists. A child sits in the `waiting` stage until every ticket it depends on has merged.
- **Spec refresh:** before a waiting child builds, a quick Sonnet check asks whether the merged dependencies changed any file in its Likely files. If so, the spec is refreshed before the build starts.
- **Fresh sessions and chaining:** each child runs as its own dashboard-started session. The run that merges a child calls `B ready <parent>` and starts the ready children. This is the automatic chaining that 022 lacked.

## Drift check (tracker, Sonnet, after each child merges)

Reads the frozen Goal and Done-when, the merged diffs so far, and the remaining tickets. Writes `track-<n>.md` with one of:
- `ON TRACK`: continue.
- `ADJUST`: rewrites remaining tickets that the merged work made wrong or redundant (scope must not grow). The changes are listed on the parent card.
- `OFF TRACK`, or any scope change: stops the parent and asks Trevor (questions, not a plan approval).

## Finish (BigBoy review, Opus, once)

Checks the merged result on main against the plan's Done-when, and runs the project's tests. It writes `bigboy-review.md`:
- `PASS`: the parent is done.
- `GAPS`: creates at most one fix ticket. If gaps remain after that, it goes to needs-human.

## Board / dashboard

- **Parent job:** `lane=bigboy`, `children=[...]`, `stage` is plan → running → review → done.
- **Child job:** `parent`, `depends_on`, `parallel`, and the new stage `waiting`.
- **Dashboard:** the parent card shows "T2/4 merged", with its children grouped under it.

## Cost guardrails

- At most 5 tickets.
- Parallelism is chosen per plan and tuned by the digester.
- Tracker and spec refresh run on Sonnet.
- One planner and one final review, on Opus.
