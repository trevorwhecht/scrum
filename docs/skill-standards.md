# Skill standards

The standard a rules diff (`agents/scrum-*.md`, any `SKILL.md`, `skills/trevskills-scrum/lanes/*.md`) must meet to
merge without Trevor. Merge's Agent rules guard runs the gate in `skills/trevskills-scrum/lanes/rules-gate.md`:
the diff merges unattended when `B digest-verify` passes, or when `B rules-check` exits 0 and the
`scrum-review-rules` review is `VERDICT: PASS`. Anything else is a `B ask` (Merge anyway / Send back).

- `script` rules (1-8) are checked by `board.py rules-check` and block. Each failure prints as `rule N: ...`.
- `judge` rules (9-14) are graded by `agents/scrum-review-rules.md`. Its PASS quotes each rule and the evidence.
- Rules 2, 3 and 5 count only violations the diff adds: a violation already on the base does not block, so an old
  file can be edited before it is cleaned up. Rule 4 has its own growth test.
- Every threshold is a rule of thumb, not a measurement; each one keeps its reason so a digest proposal can move it.
  Tokens are estimated as characters / 4.

Source: `research/skill-standards-gate.md`.

## Human-only set

A diff touching any of these never merges unattended (rule 8): this doc's own `## Human-only set` section,
`B rules-check`'s code (the `# --- rules-check:` block in `board.py` and every board.py line naming rules-check),
`agents/scrum-review-rules.md`, `skills/trevskills-scrum/lanes/rules-gate.md`, the Merge step 1 guard bullets in
`SKILL.md` (from `1. **Preconditions:**` to step 2), and the never-list at the top of `SKILL.md` (from
`This skill is a sanctioned exception` to `## Setup`). Why: no unattended diff may loosen the gate, the checker
or the standard (harness tampering, arXiv 2609.00069).

## Script rules

### 1. Frontmatter parses `script`
- Why: a skill or agent with no name or description never loads or never triggers.
- Check: every changed `SKILL.md` and `agents/*.md` opens with `---` frontmatter holding `name:` and
  `description:`. The agent keys `model:` and `tools:` (with Read, without Agent) are pinned by
  `test_frontmatter` in `tests/test_contracts.py`, which rule 6 runs.
- Fix: add the missing keys.

### 2. Name format `script`
- Why: the skill spec rejects other names; `claude` and `anthropic` are reserved.
- Check: `name` matches `^[a-z0-9]+(-[a-z0-9]+)*$`, is 64 chars or less, and contains neither `claude` nor
  `anthropic`. 64: the skill spec's limit.
- Fix: rename to lowercase words joined by hyphens.

### 3. Description `script`
- Why: the description is the trigger; past 1,024 chars the listing cuts it, angle brackets break the listing,
  and first or second person reads as an instruction to the wrong party.
- Check: `description` is 1-1024 chars, has no `<` or `>`, and has no `I`, `you`, `your`, `we` or `our`.
  All `agents/scrum-*.md` descriptions together stay under 15,000 tokens (the sub-agents page warns past that).
  That the description opens with the trigger is graded by the rules reviewer under rule 11.
- Fix: rewrite it in third person, trigger first, under the limit.

### 4. Body budget `script`
- Why: long bodies lose instructions (IFScale), and only the first 5,000 tokens survive compaction.
- Check: a changed rules file over 500 lines or 5,000 tokens fails when it is new, or when it has more lines or
  characters than on the base. 500 lines: Claude skill best practices. 5,000 tokens: agentskills.io body limit.
  A file already over budget may shrink, never grow.
- Fix: move a section into a `lanes/*.md` reference, or cut text the same diff no longer needs.

### 5. References `script`
- Why: Claude reads a nested reference partly or not at all, a long reference without contents is skimmed, and an
  `@path` link loads the file into every context.
- Check: a `lanes/*.md` file names no other `lanes/*.md` file (references stay one level deep from SKILL.md); a
  `lanes/*.md` file over 100 lines has `Contents` in its first 10 lines (best practices: contents past 100 lines);
  no rules file has an `@dir/file.md` link.
- Fix: point from SKILL.md instead, add a contents list, or name the file in backticks.

### 6. Contract tests `script`
- Why: `tests/test_contracts.py` pins the wording the pipeline parses; a reworded pin silently breaks a step.
- Check: when the repo has `tests/test_contracts.py` (at the base or in the diff), `python3 -m unittest tests.test_contracts`
  passes in the worktree; and every `FIRST_LINE` pin on the base
  is still in `tests/test_contracts.py` with the same phrase.
- Fix: change the pinned phrase and its test in the same diff; never drop a `FIRST_LINE` pin.

### 7. In the ticket `script`
- Why: an unattended rules edit may change only what the ticket asked for (job 180's in-ticket rule).
- Check: every file the diff changes is named in the job's `feature.md` or in spec.md's `## Likely files`, as the
  repo-relative path verbatim; a `<dir>/*.md` mention covers every `.md` file directly in that directory. Known safe
  case moved-text: a `skills/trevskills-scrum/lanes/*.md` file Y also counts when the job's `decision.md` has the line
  `Rules case: moved-text — <Y> holds the <section> the ticket names in <X>`, X is a named `SKILL.md` or lane file
  (never `agents/scrum-*.md`), and X already contains Y's path at the merge-base.
- Fix: revert the extra file, or name it in the spec's `## Likely files`.

### 8. Human-only set untouched `script`
- Why: see **Human-only set** above.
- Check: the diff adds, edits or deletes no file in the set, and leaves each listed section byte-identical; a
  section whose start or end marker is gone counts as changed.
- Fix: none unattended; Trevor merges it with Merge anyway.

## Judged rules

### 9. No repeats `judge`
- Why: a rule said twice drifts into two rules.
- Check: no added sentence repeats what CLAUDE.md, a `rules/*.md` file or another agent already says.
- Fix: point to the existing rule by file name.

### 10. Checkable `judge`
- Why: an instruction no one can check is not followed.
- Check: every added instruction names an observable action or predicate; no "be careful", "properly",
  "as needed", "where appropriate".
- Fix: say what to run, read or write, and what result counts.

### 11. Nothing Claude already knows `judge`
- Why: every line costs context in every run.
- Check: no added text explains general knowledge, history or rationale where one line will do; a description
  opens with its trigger.
- Fix: delete it, or cut it to one line.

### 12. No nuance clauses `judge`
- Why: "usually", "unless it seems" and "in most cases" make the rule a judgement call each run.
- Check: each exception is its own conditional on an observable predicate.
- Fix: write `When <predicate>, <action>.` per exception.

### 13. One term, one default, no dates `judge`
- Why: two words for one thing read as two things; a menu has no default; "currently" goes stale.
- Check: one term per concept across the diff and the file it edits; one default, not a list of options; no
  time-sensitive statement ("now", "recently", "as of", a date).
- Fix: pick the term already used in the file; pick the default; state the rule without time.

### 14. Enforced, not prose `judge`
- Why: a must-hold-every-time rule written only as prose is skipped sometimes.
- Check: an added rule that must hold every run comes with a test, guard or hook in the same diff.
- Fix: add the test to `tests/test_contracts.py`, or the check to `board.py`.
