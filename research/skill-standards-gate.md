# Skill standards doc + unattended merge of rule changes

Research 2026-10-21 (trevskills-research). Question: can changes to `SKILL.md` and `agents/scrum-*.md`
merge without Trevor's click when they comply with a written standard, and what should that standard say?

## Recommendation: rules doc with script-checked and judged rules, as a second bypass of the Merge agent-rules guard

Write `docs/skill-standards.md`: every rule has Why / Check / Fix and is tagged `script` or `judge`.
`B rules-check <id> --worktree --base` enforces the `script` rules (stdlib, deterministic) and a small
`scrum-review-rules` agent grades the `judge` rules with the existing `VERDICT: PASS|CHANGES` reviewer shape.
The Merge guard then merges a rules diff unattended when `digest-verify` passes (today's bypass) OR
`rules-check` exits 0 AND the rules review is PASS. Anything else becomes a `B ask` (Merge anyway / Send back),
per job 180. The doc, the checker, the reviewer agent and the guard bullets themselves stay human-only.

Confidence: medium. Every repo that automates this keeps the deterministic part in code and the judgment part
in a separate headless reviewer (skillsaw, graft, ccwriter lint); nobody found merges LLM-reviewed prompt
changes with no human at all, so the always-human set above is the safety margin.

## How the options compare

| | A. script + judge (pick) | B. script only | C. LLM reviewer only | D. fold into scrum-review-code |
|---|---|---|---|---|
| Who uses it | skillsaw gate+preflight, ccwriter rules.md, graft review.sh | skills-ref, skill-guard PR gate | graft review-prompt.md | nobody found |
| Fit | reuses digest-verify guard slot, reviewer shape, B sync, test_contracts | same, but cannot judge bloat/duplication | one new agent; guard still needed for fast lane | shortest diff, but fast-lane and cloud jobs never run reviewers |
| Effort | board.py cmd + agent + doc + guard wording + tests (~1 standard job, maybe bigboy 2 slices) | smaller | smallest | smallest |
| Main risk | reviewer rubber-stamps | misses "ideology" rules Trevor cares about | visible checker gets gamed; thresholds drift | sonnet reviewer, mixed concerns, no gate on fast lane |

## What to borrow

- Rules file with Why / Check / Fix and a script-or-judge tag per rule: ccwriter369-beep/claude-skill-skill-structure-lint `references/rules.md`.
- Deterministic in code, judgment to the LLM, strictly-better-or-reject gate: StevenACoffman/skillsaw `cmd/preflight/preflight.go`.
- Headless reviewer whose first line is the verdict, parsed by grep, missing verdict = request-changes, and an `exclusions.txt` of paths no unattended run may touch: FurbySoup/graft `ops/automation/review.sh`.
- Description overlap (Jaccard >= 0.6) between two skills/agents = duplicate trigger: erphq/skillcheck `src/checks.ts`.
- "Rule with no reason" regex and an instruction-count budget: Penloom-Studio/claude-md-lint `index.mjs`.
- Grader must criticise weak checks, not just grade: anthropics/skills skill-creator `agents/grader.md`.

## The standard (draft rule set, 14 rules)

Script-checked (block):
1. Frontmatter parses; skill has name+description, agent has name+description+model+tools with Read and no Agent. (already in test_contracts)
2. name matches `^[a-z0-9]+(-[a-z0-9]+)*$`, <= 64 chars, no "claude"/"anthropic".
3. description 1-1024 chars, no `<`/`>`, third person, opens with the trigger. Combined agent descriptions < 15k tokens.
4. Body budgets: a file already over 500 lines / 5k tokens may not grow; a new file stays under. (SKILL.md is 535 lines, ~24k tokens: over every published budget; see backlog note below.)
5. References one level deep; any over 100 lines starts with a contents list; no `@` links.
6. If a pinned phrase changed, `tests/test_contracts.py` changed in the same diff and the full contract suite passes in the worktree; every agent's `FIRST_LINE` intact.
7. The diff touches only files named in feature.md or spec.md `## Likely files` (job 180's rule).
8. Human-only set untouched: `docs/skill-standards.md`, `B rules-check` code, `agents/scrum-review-rules.md`, the Merge step 1 guard bullets, and the never-list at the top of SKILL.md. Any hit -> B ask, never unattended.

Judged (PASS needs the rule quoted per check):
9. No sentence repeats what CLAUDE.md, a rules file or another agent already says; point to it by name.
10. Every added instruction is checkable (observable action or predicate), not "be careful"/"properly".
11. Nothing explains what Claude already knows; no history or rationale where one line will do.
12. No nuance or exemption clauses; each exception is its own conditional on an observable predicate.
13. One term per concept, one default not a menu, no time-sensitive statements.
14. A must-hold-every-time rule is enforced by a test, guard or hook in the same diff, not prose alone.

Sources for the limits: platform.claude.com skill best practices (500 lines, 1024-char description, third person,
one level deep, TOC past 100 lines); code.claude.com skills (1536-char listing cut, first 5k tokens survive
compaction); sub-agents (15k-token description warning); memory (CLAUDE.md < 200 lines); agentskills.io spec
(5k-token body); superpowers writing-skills (triggers-only description, no `@` links, word budgets).

## Risks and how to handle them

- Reviewer rubber-stamps: PASS must quote the rule for every judged check; digest already reads review files, so
  the Digest step sees a reviewer that always passes. Keep the hard limits in `rules-check`, not in the LLM.
- Gaming the gate over many edits (arXiv 2609.00069 "harness tampering"): the human-only set (rule 8) is
  deterministic by path+section, so no unattended diff can loosen the guard, the checker or the standard.
- The first job that adds this is itself a rules change and stops for Trevor once. Expected.
- Budgets are rules of thumb, not measured; keep each threshold in the doc with its reason so a later digest
  proposal can move it.

## What I'd skip, and why

- skill-creator's `run_eval.py` trigger evals: reported 0% triggers under `claude -p` (anthropics/skills #556, #1169).
- Jaccard description overlap in v1: only 10 agents, the judged duplication rule covers it; add if it ever bites.
- PyYAML validators (quick_validate.py): not stdlib; frontmatter here is 4 flat keys, a regex does it.
- Codex second opinion: skipped, single-engine evaluation.

## Sources

- anthropics/skills skill-creator (2026-10-09) https://github.com/anthropics/skills/tree/dbd4588f9e/skills/skill-creator
- agentskills/agentskills skills-ref (2026-08-09, Apache-2.0) https://github.com/agentskills/agentskills/blob/69ef37e942/skills-ref/src/skills_ref/validator.py
- obra/superpowers writing-skills (2026-10-21, MIT) https://github.com/obra/superpowers/tree/2ce8aa15d0/skills/writing-skills
- ccwriter369-beep/claude-skill-skill-structure-lint (2026-10-02, MIT) https://github.com/ccwriter369-beep/claude-skill-skill-structure-lint
- erphq/skillcheck (2026-09-08, MIT) https://github.com/erphq/skillcheck
- vaibhavtupe/skill-guard (2026-08-06) https://github.com/vaibhavtupe/skill-guard
- Penloom-Studio/claude-md-lint (2026-07-02, MIT) https://github.com/Penloom-Studio/claude-md-lint
- StevenACoffman/skillsaw (2026-09-06, MIT) https://github.com/StevenACoffman/skillsaw
- FurbySoup/graft (2026-09-26, no license) https://github.com/FurbySoup/graft
- Docs: https://platform.claude.com/docs/en/agents-and-tools/agent-skills/best-practices , https://code.claude.com/docs/en/skills , https://code.claude.com/docs/en/sub-agents , https://code.claude.com/docs/en/memory , https://agentskills.io/specification
- Community: claude-code #34197 (2026-03), tianpan.co "Your CLAUDE.md Is Probably Too Long" (2026-02-14), Vercel "AGENTS.md outperforms skills" (2026-01), IFScale arXiv 2507.11538, ETH arXiv 2602.11988, arXiv 2609.00069 (harness tampering), anthropics/skills #556 #1169 #1487 #202, superpowers #743 #446 #895.

## Next step

Backlog one job (lands after job 180 merges, since it extends 180's agent-rules self-heal): the doc, `B rules-check`,
`scrum-review-rules`, the guard wording, the CLAUDE.md guard line, and contract tests. Separate backlog note: SKILL.md
is over every budget; split lanes into `trevskills-scrum/lanes/*.md` (the guard regex already anticipates that path).
