# Playwright E2E skill and scrum-review-e2e agent
UI surface: no
Hard stops: secrets
Lane: standard

## Problem
The Check gate already runs the project's `E2E:` command when a diff touches `UI globs` (SKILL.md **Check gate** step 2, from the earlier E2E-hook job). But when that run fails, nobody works out why, and a UI change with no E2E spec covering it is never clicked through at all. Trevor wants a cheap, repeatable E2E check. It should replay saved Playwright specs first. It should write a new spec only for changed UI that no spec covers yet. It should sort failures into real bug, stale test or flake, using Jev for yes/no questions. The logic goes in one skill. Trevor can run it directly, and a scrum reviewer agent loads it.

## Scope
In:
- New skill `skills/trevskills-e2e/SKILL.md`, which holds the whole E2E flow. Trevor can run it as `/trevskills-e2e`.
- New agent `agents/scrum-review-e2e.md`. It loads that skill through its frontmatter and does not restate the flow. It writes `round-N/review-e2e.md`.
- `install.sh` links the new skill into `~/.claude/skills/trevskills-e2e`, the same way it links `trevskills-scrum`.
- `skills/trevskills-scrum/SKILL.md` wiring:
  - The Check gate's E2E run stays as it is.
  - The orchestrator spawns `scrum-review-e2e` under the conditions in criterion 5.
  - Its verdict feeds the round's verdict.
- `board.py sync` counts an optional `round-N/review-e2e.md` toward `verdict` and `invalid`. A missing file is never reported in `missing`.
- Contract and install tests, plus a README line.

Out:
- Dashboard changes: no fifth reviewer chip, and no change to the Pipelines chart or `REVIEWS` const.
- Adding `e2e` to `board.REVIEWERS` or to the board.json `reviews` dict.
- Writing an `E2E:` line into this repo's `scrum/project.md`.
- Installing Playwright, or running `npx playwright init-agents` for the user.
- Browser-MCP fallbacks.
- Carrying the e2e reviewer forward on incremental re-review rounds.

## Acceptance criteria
1. `skills/trevskills-e2e/SKILL.md` exists with frontmatter `name: trevskills-e2e` and a non-empty `description`. Its body documents each of these, in this order:
   1. **Finding the E2E command.** Use the `- E2E:` line of `scrum/project.md`. When that line is missing or `none`, fall back to `npm run test:e2e` if `package.json` has a `test:e2e` script. When there is neither, stop with the report line `E2E: no command`.
   2. **Mapping changed files to routes/pages.** With a base, use `git diff --name-only <BASE>...HEAD`. When run directly with no base, use all routes.
   3. **Replaying the saved suite first.** This needs no AI.
   4. **Covering changed UI with no spec.** Use Playwright's generator agent output (from `npx playwright init-agents --loop=claude`) when it is present in the repo. Otherwise drive the page once. Then save a spec that uses only `getByRole`, `getByLabel` or `data-testid` locators and asserts real page content, and re-run it until it passes.
   5. **On failure.** Read the trace/error-context and the page's `innerText`. Retry once before calling a failure a flake. Give a verdict of `real bug`, `stale test` or `flake`.
   6. **Jev for yes/no questions.** Try `~/.claude/scripts/jev-rank.py` first. Otherwise POST to `https://api.typesafe.ai/v1/systemone` with model `jev-latest`, no UL, and the question. The key comes from `TYPESAFE_API_KEY`, or else Keychain service `TypeSafe`, account `typesafe`. Any Jev error falls back to reading the output.
   7. **Token rules.** Never use a browser MCP when a saved spec can run. Read only the failing test's output. Take no screenshots unless a check needs one.
   8. **The report.** `Specs run:`, `Specs added:`, and `Failures:`, with one verdict per failure.

   (verify: new test `test_e2e_skill_contract` in `tests/test_contracts.py`. It asserts the frontmatter name, and that the body contains `E2E:`, `test:e2e`, `getByRole`, `getByLabel`, `data-testid`, `init-agents`, `innerText`, `jev-rank.py`, `jev-latest`, `TYPESAFE_API_KEY`, `real bug`, `stale test`, `flake`, `Specs run`, `Specs added`.)
2. **Assertion and key rules.** The skill says, on a line containing `never`, that an assertion is never weakened or deleted to make a test pass. It also says the Jev key is never printed, logged or written to any file. (verify: in `test_e2e_skill_contract`, assert that a line containing both `never` and `assertion` exists, and that a line containing both `never` and `key` exists.)
3. **The agent file.** `agents/scrum-review-e2e.md` exists with this frontmatter:
   - `name: scrum-review-e2e`
   - `model: sonnet`
   - `tools: Read, Grep, Glob, Bash, Edit, Write`
   - a `skills:` list containing `trevskills-e2e`

   Its body:
   - tells it to follow the `trevskills-e2e` skill;
   - limits its writes to the project's E2E/test directory and `JOB_DIR/round-N/review-e2e.md`;
   - says the review file's first line is `VERDICT: PASS` or `VERDICT: CHANGES`, with `VERDICT: CHANGES` whenever any failure's verdict is `real bug`;
   - mentions `prisma migrate` and `git merge` as forbidden.

   (verify: add `"scrum-review-e2e": "sonnet"` to `AGENTS` and `"scrum-review-e2e": "VERDICT: PASS"` to `FIRST_LINE` in `tests/test_contracts.py`. The existing `test_frontmatter`, `test_first_line_contracts_are_documented`, `test_every_agent_forbids_migrations_and_merges` and `test_skill_references_every_agent_and_board_command` then cover it. The new test `test_e2e_agent_loads_skill` asserts that `trevskills-e2e` is in the frontmatter `skills` list and that `review-e2e.md` is in the body.)
4. **Install.** `./install.sh` links `skills/trevskills-e2e` to `$CLAUDE_HOME/skills/trevskills-e2e`. Re-running it is still safe. It refuses to replace a real (non-symlink) directory at that path, and on refusal it links nothing. (verify: extend `test_install_links_skill_and_agents_and_is_rerunnable` to assert the new link resolves to the repo directory. Add `test_install_refuses_to_clobber_real_e2e_skill_dir`.)
5. **When the orchestrator spawns the agent.** These rules go in `skills/trevskills-scrum/SKILL.md`.
   - **Check gate.** Step 2 stays exactly as it is. In step 4, when `check.md` is `CHECK: FAIL` and the E2E command exited non-zero, the orchestrator first spawns `scrum-review-e2e` and waits for it. It then resumes the builder with a message that also names `JOB_DIR/round-N/review-e2e.md`.
   - **Review.** In step 3, the orchestrator also spawns `scrum-review-e2e`, in the same message as the other reviewers, when `project.md` has an `E2E:` line that isn't `none` and the diff touches `UI globs`.
   - **Never.** It never spawns `scrum-review-e2e` when there is no `E2E:` line or the line is `none`.

   (verify: new test `test_skill_wires_e2e_reviewer`. It asserts that `scrum-review-e2e` appears in both the `## Check gate` section and the `## Review (WAIT FOR ALL)` section, and that the existing `test_skill_e2e_hook` still passes.)
6. **Sync.** `board.py sync <id>` reads `round-N/review-e2e.md` when it exists:
   - `VERDICT: CHANGES` makes `verdict` `CHANGES` even when all four core reviews pass.
   - A file whose first word is neither `PASS` nor `CHANGES` puts `"e2e"` in `invalid`.
   - When the file is absent, `verdict`, `complete` and `missing` are exactly as they are today.

   `REVIEWERS` and board.json `reviews` are unchanged. (verify: new tests in `tests/test_board.py`: `test_sync_e2e_changes_overrides_pass`, `test_sync_e2e_absent_is_not_missing`, `test_sync_e2e_invalid`.)
7. **Missing review file.** When the orchestrator spawned `scrum-review-e2e` and `review-e2e.md` is still missing after one re-spawn, the orchestrator writes it as `VERDICT: CHANGES` plus `Reviewer produced no output.`, which is the same rule as for the other reviewers. The SKILL.md Review step 4 text covers this. (verify: `test_skill_wires_e2e_reviewer` asserts that the Review section mentions `review-e2e.md`.)
8. **Full suite and README.** `python3 -m unittest discover -s tests` passes. README's install line and agents line mention `trevskills-e2e` and `scrum-review-e2e`. (verify: run the command. Manual check: grep README.)

## Likely files
- `skills/trevskills-e2e/SKILL.md` (new): frontmatter `name: trevskills-e2e`, `description: ...`. Holds the full flow from criteria 1–2.
- `agents/scrum-review-e2e.md` (new): frontmatter `name`, `description`, `tools: Read, Grep, Glob, Bash, Edit, Write`, `model: sonnet`, `skills:` block with `  - trevskills-e2e`. Takes the standard 5 prompt lines (`JOB_DIR`, `WORKTREE`, `BASE`, `ROUND`, `PROJECT`).
- `skills/trevskills-scrum/SKILL.md`: Check gate step 4, Review steps 3–4, and the step 5 routing note on `review-e2e.md`.
- `skills/trevskills-scrum/board.py`: in `cmd_sync`, read `first_word(last_round_dir / "review-e2e.md", ("PASS", "CHANGES"))` and fold it into `verdict` and `invalid`. Add an `"e2e"` key to the returned dict with value `PASS` | `CHANGES` | `INVALID` | `None`.
- `install.sh`: `refuse_real` and `link` for `skills/trevskills-e2e`.
- `tests/test_contracts.py`, `tests/test_board.py`, `tests/test_install.py`
- `README.md`

## Assumptions
- **The prerequisite job.** "Job 109" is the earlier E2E-hook work. It is already on `origin/main`: commit c0b0014 added the `E2E:` line to First-run setup and Check gate step 2, plus `test_skill_e2e_hook`. So this job builds on that text and leaves Check gate step 2 as it is. (PR #109 is an unrelated Codex change.)
- **The truncated request.** feature.md is cut off at "spawn scrum-review-e2e only when that E2E run fails OR the diff touc…". I read the end as "...OR the diff touches `UI globs`". Both triggers also require an `E2E:` line that isn't `none`, because the Check gate only runs E2E then.
- **When an E2E failure spawns the agent.** A failure triggers it in Check gate step 4, so its triage reaches the builder. A UI diff triggers it in Review step 3.
- **Model.** The agent runs on `model: sonnet` to keep tokens low, like the other cheap reviewers.
- **No carry-forward.** On incremental re-review rounds, the e2e reviewer is never carried forward. It re-runs whenever the criterion 5 conditions hold. The clean-round and approver-model rules keep saying "all four"; a `review-e2e.md` that says `CHANGES` already makes the verdict `CHANGES`.
- **Jev without UL.** "noul" means the API request sends no UL parameter.
- **Keychain lookup.** The Keychain read is `security find-generic-password -s TypeSafe -a typesafe -w`, on macOS only. Cloud sessions use `TYPESAFE_API_KEY` or skip Jev.
- **Why the secrets hard stop.** The skill reads an API key from the environment or Keychain. That is a secrets touchpoint, though no secret is added to the repo.
- **"Project E2E/test directory".** This means the directory that holds the existing Playwright specs, taken from `testDir` in `playwright.config.*`. When there is no config, it is `e2e/`, or else `tests/`.
- **Direct runs.** `/trevskills-e2e` run directly with no base covers all routes, and writes its report to stdout only.
