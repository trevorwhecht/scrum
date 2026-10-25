# Trevskills Scrum

`/trevskills-scrum <feature>` turns a feature request into a squash-merged PR. A spec writer, a builder, four parallel reviewers and an approver hand off through markdown files, and a one-file dashboard shows each job's progress.

```
feature → spec-writer → builder → check gate → security · ux · ui · code → approver
                           ▲          (tests/lint/build)   (wait for all;       │
                           │                               code runs codex too) │
                           └──────── CHANGES, round < 2 ◄───────────────────────┤
                                                    APPROVE → PR → CI → squash-merge
                                                    REWORK  → one more round (once)
                                                    ESCALATE → needs-human (hard stops only)
```

**Codex as a second model family, read-only only.** `scrum-review-code` runs `codex exec review` in the background once per round while it does its own review, confirms each finding, and tags the ones it keeps `(codex)`. Codex never edits, never spawns agents, and adds no step: if it fails, or hasn't finished 10 minutes after it started, the review notes `codex: skipped`, which never passes or fails the round. Both engines share one rubric, `codex/AGENTS.md`.

**Escalates only for:** DB schema/migrations, money, auth, secrets, a blocked builder, or infrastructure (no `gh`, or merge conflicts or CI still failing after 2 automatic fixes). The approver decides everything else. It runs on Opus, or on Sonnet when the round is all green (check PASS, every review PASS, no schema files, not a conflict round).

**E2E reviewer (optional).** When `scrum/project.md` has an `E2E:` line that isn't `none`, `scrum-review-e2e` replays the saved Playwright specs, covers changed UI that has none, and sorts failures into real bug, stale test or flake. It runs when the E2E check fails and when the diff touches `UI globs`; a `real bug` makes the round `CHANGES`.

**Skips the ux and ui reviewers** when no file in the diff matches `UI globs` in `scrum/project.md`; the orchestrator writes their review files as `VERDICT: PASS`. A missing or `none` line means all four run.

## Install (once)

```bash
brew install gh && gh auth login   # needed to open and merge PRs
./install.sh                       # links skills/trevskills-scrum, skills/trevskills-e2e and agents/* into ~/.claude
```

`install.sh` also links `codex/AGENTS.md` to `~/.codex/AGENTS.md` (or `$CODEX_HOME/AGENTS.md`), the review rules Codex reads. It refuses to replace a real file there.

## Use (in any repo, from its main checkout)

| Command | Does |
| --- | --- |
| `/trevskills-scrum <feature>` | runs a new job |
| `/trevskills-scrum lilguy "<feature>"` | makes the change in this checkout with no subagents, runs the checks, then lands it with commitpush |
| `/trevskills-scrum next` | runs the first `- [ ]` item in `scrum/backlog.md` |
| `/trevskills-scrum approve <id>` | merges a needs-human job |
| `/trevskills-scrum rework <id> "<feedback>"` | sends a job back to the builder with 2 more rounds |
| `/trevskills-scrum discuss <id> ["<note>"]` | talks a stopped job through with you first, then runs the approve or rework you agree on (dashboard: Discuss first) |
| `/trevskills-scrum cloud [N]` | runs up to N backlog items in cloud sessions (see Cloud lane) |
| `/trevskills-scrum` | shows the board |

## Dashboard

One dashboard shows every project. Each repo joins it automatically the first time `/trevskills-scrum` runs there, and its jobs and backlog stay in that repo's `scrum/` folder.

- **App:** run `./app/make-app.sh` once to build **Trevskills Scrum.app** in `~/Applications`, then drag it to your Dock. Clicking it starts the server if needed and opens the dashboard in its own window.
- **Or by hand:** `python3 ~/.claude/skills/trevskills-scrum/serve.py`, then open http://localhost:8765.

Each card carries a project tag, and the **All projects** menu filters to one project.

- Cards move across the stages, and each review round is one row of reviewer chips.
- A stuck (needs-human) card opens with **Approve & merge** and **Send back to builder**. Each click starts a background `claude -p` run, logged to `scrum/runs/`, and the card shows "● running" until it finishes.
- **Backlog** opens the queue:
  - **+** adds an item, and Sonnet estimates it in Fibonacci points (1 2 3 5 8 13, colour-coded). Change the points or text inline.
  - ↑/↓ reorders the queue; `/trevskills-scrum next` takes the top item.
  - ▶ starts a job now, and ✕ deletes an item. Both ask once on the button.
- A card whose job has a `routing.log` shows one tag per routed step, such as `builder cloud` or `codex-review skip`; hover for the model, seconds and outcome. The header shows Claude and Codex 5h and weekly use, refreshed every minute.
- **Pipelines** shows each pipeline's chart with each agent's model, in tabs: All (the orchestrator fanning out to all four), Fast, Standard, Debug, BigBoy and Maintenance. Click an agent for its prompt, tools and skills; **+** adds an installed skill to its frontmatter (live on the next spawn, and an uncommitted change in this checkout).

The server listens on localhost only and refuses requests from other websites.

The first run writes `scrum/project.md` (stack, test/lint/build commands, convention files). Edit it if detection got something wrong. To run several jobs at once, open several Claude sessions; each job gets its own worktree.

## Change the scrum

- Agents: `agents/scrum-*.md` (including `scrum-review-e2e`, which loads the `trevskills-e2e` skill). A repo can override one with its own `.claude/agents/<same name>.md`.
- E2E flow: `skills/trevskills-e2e/SKILL.md`, also runnable directly as `/trevskills-e2e`
- The loop: `skills/trevskills-scrum/SKILL.md`
- Review rules shared by Claude and Codex: `codex/AGENTS.md`
- Tests: `python3 -m unittest discover -s tests -v`

## Cloud lane

`/trevskills-scrum cloud [N]` runs up to N (default 4) backlog items in Claude Code cloud sessions (claude.ai/code), paid by cloud-session credit instead of the weekly plan. Each session first reruns `cloud/setup.sh` to refresh the skill, since the environment caches an old copy, verifies its skill copy (`~/scrum` HEAD matches origin main and `lanes/cloud.md` has the Artifacts step, else it stops as needs-human), reads SKILL.md from disk instead of the skill text loaded at session start, then runs the normal pipeline and squash-merges its own `[scrum <id>]` PR, or labels it `scrum:needs-human` with a comment saying why. `/trevskills-scrum cloud-sync` (also run by `cloud` and bare `/trevskills-scrum`) moves those results onto the board. Its PR lookup and board update are plain Python, `board.py cloud-sync` (one GitHub REST call, no LLM), and the dashboard server runs that every 10 minutes while any job is in stage `cloud`, so a merged or stopped cloud job lands without a session. Each cloud job also pushes its folder to a `scrum-artifacts/<id>` branch that `cloud-sync` fetches into the local board (follow-ups go to the backlog) and then deletes. When the poll moves a job with such a branch, or one stopped on a schema or agent-rules hard stop, the server starts a headless `/trevskills-scrum cloud-home <id>` for just that work. Before each batch the orchestrator reads the credit at https://claude.ai/settings/usage through Claude in Chrome and refuses under $25; the value is cached for 24 h in `~/.claude/trevskills-scrum/cloud-credit.json`, and a batch skips the read and the question while that value is under 24 h old and above $25 plus $5 per job dispatched since. The rules are in `skills/trevskills-scrum/lanes/cloud.md`.

Set up the cloud environment once:

1. At claude.ai/code, open the environment menu and add an environment named `scrum`, with network access **Trusted**.
2. Setup script: `curl -fsSL https://raw.githubusercontent.com/trevorwhecht/scrum/main/cloud/setup.sh | bash` (or paste [cloud/setup.sh](cloud/setup.sh)). It clones this repo to `~/scrum` and runs `install.sh`, so the session loads the same skill and agents through symlinks, never a copy; it also installs Playwright and Chromium for the dashboard browser tests. Add the project's own setup after it, such as `service postgresql start` when its tests need Postgres.
3. Environment variables: whatever the project's tests need from `.env` (cloud sessions have no `.env`).
4. Copy the environment's id (`env_...`). If the settings page doesn't show it, ask any cloud session to run its `list_environments` tool. Add `- Cloud environment: env_...` to the project's `scrum/project.md`. Without that line, `claude --cloud` uses your default environment.

## Routing

Every agent runs on cloud Claude. `local/route.py codex-review` answers `skip` when Codex is not installed or its 5h or weekly quota is at its threshold, and `cloud` otherwise; every step is logged to `routing.log`. See [local/README.md](local/README.md).
