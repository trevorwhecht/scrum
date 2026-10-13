# Triage router + lanes for trevskills-scrum (research, 2026-10-13)

## Recommendation: spec writer picks the lane; hard checks can promote it

The spec writer, which already reads the codebase and makes the one early-exit call (`OBSOLETE:`), adds a `Lane:` header line: `fast`, `standard`, `debug` or `epic`. Trevor can force a lane with a flag or backlog tag. Backlog points are a hint only, because ad-hoc jobs have none. Hard checks after the build can **promote** a fast job to standard but never demote one. This is the routing shape the closest prior art uses: BMAD-METHOD routes from a size estimate plus risk signals, with a user override. No well-known project puts a separate classifier agent in front of everything.

**Confidence:** medium-high. Each lane copies a proven pattern. Nobody has shipped exactly this four-lane combination, and the epic lane is the riskiest.

## The lanes

| Lane | Agents | Gate |
|---|---|---|
| **fast** | builder → check gate → 1 code reviewer (Sonnet) → merge | Promoted to standard if the diff is over ~100 lines or over 3 files, touches hard-stop paths, touches UI globs, or the check fails twice |
| **standard** | what runs today | unchanged |
| **debug** | debugger: reproduce with a failing test → localize → `assessment.md` (root cause, fix, allowed files) → compliance check against conventions → builder limited to those files → check gate re-runs the repro → code + security review → approver | 3 failed fixes → escalate, and question the design |
| **epic** | planner writes `tickets.md` (depth 2, acceptance criteria and dependencies per ticket) → **Trevor approves the plan** → tickets run one at a time as child jobs, each in its own lane → drift check against the frozen original goal between tickets → epic-level final review | A ticket too big gets re-split once, then goes to Trevor. No unbounded recursion |

**Fast lane merge policy:** one small PR per change, squash-merged after the check gate, the same as today but with fewer agents. Don't batch unrelated changes: it breaks one-click revert and `git bisect` (Google CL guidance, trunk-based development). Don't leave them unmerged: unmerged branches go stale and conflict. Pure typo or doc edits don't need the scrum at all.

## How the options compare

| | A: spec writer routes (pick) | B: separate triage agent | C: Trevor picks every time |
|---|---|---|---|
| Who uses it | BMAD-METHOD (54k stars), Task Master (28k) scoring | no major repo | spec-kit / superpowers (user runs the chosen command) |
| Fit with our code | one header line + `lane` field + a branch at New job step 3b | an extra agent per job, and it decides with less context | simplest, but a decision every time |
| Effort | medium | medium+ | low |
| Main risk | wrong lane | extra cost, decides blind | tedium, forgetting |

## What to borrow

- Size + risk routing with an override: BMAD `skills/bmad-build/customize.toml#L33-L44`, `docs/build/build-a-change.md#L96-L104`
- One goal per plan; multi-goal → "Split / Keep": BMAD `skills/bmad-build/workflow.md#L23-L31`
- Fixed-depth tickets with `after` dependencies, re-slice step, epic retrospective: BMAD `skills/bmad-ticket/references/slice.md`, `skills/bmad-retrospective`
- Re-plan future tickets when work drifts: Task Master `update-tasks` prompt
- Bug flow assess → human gate → fix (only listed files) → re-run repro: spec-kit `workflows/bugfix/workflow.yml`, `speckit.bug.fix.md#L85`, `speckit.bug.test.md#L84-L101`
- Reproduce-first prompt, re-run repro on submit: SWE-agent `config/default.yaml#L21-L54`
- 3 failed fixes → question the architecture: superpowers `skills/systematic-debugging/SKILL.md`
- Final whole-branch review against the spec (drift check): superpowers `skills/subagent-driven-development/SKILL.md`

## Risks and how to handle them

- **Wrong lane, e.g. "trivial" isn't:** base promotion on the real diff and check results, never the model's confidence. Log promotions; if they're common, tighten the spec writer.
- **Epic pieces don't fit together** ("two correct stories fail when combined", BMAD; Cognition, Jun 2025): tickets run in sequence, each child branches from the previous merge, and there's an epic-level integration review plus a human-approved plan.
- **Epic cost blow-up** (multi-agent runs use about 15× the tokens of a chat, Anthropic, Jun 2025): child tickets default to the fast lane where the hard checks allow, with a cap on ticket count (about 8).
- **Debug fix with no reproduction:** the debug lane may not report "fixed" unless the repro test failed before and passes after (spec-kit rule). If it can't reproduce, the job goes to Trevor.

## What I'd skip

- B, a separate triage agent: it costs an extra agent per job and decides with less context than the spec writer already has.
- Unbounded recursive decomposition: no project does it, and the reports describe drift and ignored plans.
- Batching trivial changes into one PR: it breaks clean reverts and bisect.

## Sources

- Repos: BMAD-METHOD (54.1k, 2026-10-12, custom); claude-task-master (28.2k, 2026-04-28, custom); obra/superpowers (298.5k, 2026-10-10, MIT); github/spec-kit (141.1k, 2026-10-13, MIT); SWE-agent (20.5k, 2026-10-12, MIT); Agentless (2.1k, 2024-12, MIT, stale); OpenHands software-agent-sdk (1.2k, 2026-10-13, MIT)
- Anthropic, Building effective agents (Dec 2024): https://www.anthropic.com/research/building-effective-agents
- Anthropic, multi-agent research system (Jun 2025): https://www.anthropic.com/engineering/multi-agent-research-system
- Cognition, Don't Build Multi-Agents (Jun 2025): https://cognition.ai/blog/dont-build-multi-agents ; follow-up (Apr 2026): https://cognition.com/blog/multi-agents-working
- MAST, Why Do Multi-Agent LLM Systems Fail? (NeurIPS 2025): https://arxiv.org/abs/2503.13657
- Agentless (FSE 2025): https://arxiv.org/abs/2407.01489 ; Issue2Test (ICSE 2026): https://arxiv.org/abs/2503.16320
- Trunk-based development, committing straight to trunk: https://trunkbaseddevelopment.com/committing-straight-to-the-trunk/
- DORA 2025, AI-assisted development: https://cloud.google.com/discover/how-test-driven-development-amplifies-ai-success
- Router/cascade practice (Nov 2025): https://tianpan.co/blog/2025-11-03-llm-routing-model-cascades

Evidence notes: almost no Reddit or HN discussion was found. Some primary pages could not be fetched and rest on summaries. No head-to-head study compares "reproduce first" with "just fix it".

## Measured cost: AI-Settings jobs 012–017 (2026-10-13)

Measured from session transcript `46bbc78b`, in input-token equivalents: cache reads count 0.1×, cache writes 1.25×, output 5×.

| Agent | Share of the 5 jobs' agent cost |
|---|---|
| builder | 54% (about 56 turns each; the actual work) |
| spec writer | 17% (about 17 turns of exploring) |
| 4 reviewers | 22% |
| approver | 7% |

- Total for the 5 jobs' agents: about **6.4M**.
- The **orchestrator session** that ran these jobs and about 5 others cost about **9M on its own**: 69M cache-read tokens, from one long session re-reading its growing context. That's more than all 5 jobs' agents combined.
- Fixed cost per job (spec writer + reviewers + approver): about 46% of a job, so splitting into 5 paid that overhead 5 times. Estimate: roughly 40–50% more than one or two bigger jobs. **Inference:** reviewers on one large diff read more, so the saving is not a full 4×.
