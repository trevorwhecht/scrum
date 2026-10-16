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

**Skips the ux and ui reviewers** when no file in the diff matches `UI globs` in `scrum/project.md`; the orchestrator writes their review files as `VERDICT: PASS`. A missing or `none` line means all four run.

## Install (once)

```bash
brew install gh && gh auth login   # needed to open and merge PRs
./install.sh                       # links skills/trevskills-scrum and agents/* into ~/.claude
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
- A card whose job has a `routing.log` shows one tag per routed step, such as `builder local` or `builder cloud`; hover for the model, seconds and outcome. The header shows `Codex 5h 42% · wk 61% · Ollama up`, refreshed every minute.
- **Pipelines** shows each pipeline's chart with each agent's model, in tabs: All (the orchestrator fanning out to all four), Fast, Standard, Debug, BigBoy and Maintenance. Click an agent for its prompt, tools and skills; **+** adds an installed skill to its frontmatter (live on the next spawn, and an uncommitted change in this checkout).

The server listens on localhost only and refuses requests from other websites.

The first run writes `scrum/project.md` (stack, test/lint/build commands, convention files). Edit it if detection got something wrong. To run several jobs at once, open several Claude sessions; each job gets its own worktree.

## Change the scrum

- Agents: `agents/scrum-*.md`. A repo can override one with its own `.claude/agents/<same name>.md`.
- The loop: `skills/trevskills-scrum/SKILL.md`
- Review rules shared by Claude and Codex: `codex/AGENTS.md`
- Tests: `python3 -m unittest discover -s tests -v`

## Cloud lane

`/trevskills-scrum cloud [N]` runs up to N (default 4) backlog items in Claude Code cloud sessions (claude.ai/code), paid by cloud-session credit instead of the weekly plan. Each session runs the normal pipeline and squash-merges its own `[scrum <id>]` PR, or labels it `scrum:needs-human` with a comment saying why. `/trevskills-scrum cloud-sync` (also run by `cloud` and bare `/trevskills-scrum`) moves those results onto the board. Each cloud job also pushes its folder to a `scrum-artifacts/<id>` branch that `cloud-sync` fetches into the local board (follow-ups go to the backlog) and then deletes. Before each batch the orchestrator reads the credit at https://claude.ai/settings/usage through Claude in Chrome and refuses under $25. The rules are in SKILL.md **Cloud lane**.

Set up the cloud environment once:

1. At claude.ai/code, open the environment menu and add an environment named `scrum`, with network access **Trusted**.
2. Setup script: `curl -fsSL https://raw.githubusercontent.com/trevorwhecht/scrum/main/cloud/setup.sh | bash` (or paste [cloud/setup.sh](cloud/setup.sh)). It clones this repo to `~/scrum` and runs `install.sh`, so the session loads the same skill and agents through symlinks, never a copy. Add the project's own setup after it, such as `service postgresql start` when its tests need Postgres.
3. Environment variables: whatever the project's tests need from `.env` (cloud sessions have no `.env`).
4. Copy the environment's id (`env_...`). If the settings page doesn't show it, ask any cloud session to run its `list_environments` tool. Add `- Cloud environment: env_...` to the project's `scrum/project.md`. Without that line, `claude --cloud` uses your default environment.

## Local routing

`local/route.py` picks cloud or local Ollama for each routed step; the full rules are in [local/README.md](local/README.md#how-routing-decides).

- **Eligible roles:** the estimator, digest reader and Codex review always; the builder only on a `fast`-lane job; the spec writer only for a backlog item of 2 points or less (`spec_writer_max_points`). Reviewers, the approver, planner, tracker, debugger, triager and digester always run on cloud.
- **Trust** per role in `local/routing.json`: `off` (cloud), `trial` (local when eligible or a BigBoy child), `approved` (local when eligible).
- **Ollama health check:** local only when Ollama's `/api/tags` answers within 2 s and lists the role's model (`scrum-qwen2.5-coder:7b` or `scrum-qwen3.5:4b`, the 32K variants from local/README.md).
- **Claude session limit:** while a recent `scrum/runs/` log shows Claude's session limit, trial and approved roles go local until it resets.
- **Codex quota:** the Codex review moves to local once the 5h window reaches 85 % used or the weekly one 90 % (`codex_5h`, `codex_weekly`), and is skipped when Ollama is down.
- **Background worker:** `local/worker-install.sh` runs `local/worker.py` every 10 minutes: local backlog estimates and insight notes for the digest, only when memory allows, more while the Mac is idle. See [local/README.md](local/README.md#background-worker).
- **`SCRUM_ROUTE=cloud`** forces every routed step to cloud; **`SCRUM_ROUTE=local`** forces local for eligible steps when Ollama is up.
- **One cloud retry:** a local run with no valid artifact is retried once on cloud, never again and never back to local. Every attempt is logged to `routing.log`.

For the opt-in local launcher and setup, see [local/README.md](local/README.md).
