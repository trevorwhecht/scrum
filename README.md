# Trevskills Scrum

`/trevskills-scrum <feature>` turns a feature request into a squash-merged PR. A spec writer, a builder, four parallel reviewers and an approver hand off through markdown files, and a one-file dashboard shows each job's progress.

```
feature → spec-writer → builder → check gate → security · ux · ui · code → approver
                           ▲          (tests/lint/build)   (wait for all 4)    │
                           └──────── CHANGES, round < 2 ◄──────────────────────┤
                                                    APPROVE → PR → CI → squash-merge
                                                    REWORK  → one more round (once)
                                                    ESCALATE → needs-human (hard stops only)
```

**Escalates only for:** DB schema/migrations, money, auth, secrets, a blocked builder, or infrastructure (no `gh`, or merge conflicts or CI still failing after 2 automatic fixes). The Opus approver decides everything else.

## Install (once)

```bash
brew install gh && gh auth login   # needed to open and merge PRs
./install.sh                       # links skills/trevskills-scrum and agents/* into ~/.claude
```

## Use (in any repo, from its main checkout)

| Command | Does |
| --- | --- |
| `/trevskills-scrum <feature>` | runs a new job |
| `/trevskills-scrum next` | runs the first `- [ ]` item in `scrum/backlog.md` |
| `/trevskills-scrum approve <id>` | merges a needs-human job |
| `/trevskills-scrum rework <id> "<feedback>"` | sends a job back to the builder with 2 more rounds |
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

The server listens on localhost only and refuses requests from other websites.

The first run writes `scrum/project.md` (stack, test/lint/build commands, convention files). Edit it if detection got something wrong. To run several jobs at once, open several Claude sessions; each job gets its own worktree.

## Change the scrum

- Agents: `agents/scrum-*.md`. A repo can override one with its own `.claude/agents/<same name>.md`.
- The loop: `skills/trevskills-scrum/SKILL.md`
- Tests: `python3 -m unittest discover -s tests -v`
