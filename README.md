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

Dashboard: `cd scrum && python3 -m http.server 8765`, then open http://localhost:8765/dashboard.html

The first run writes `scrum/project.md` (stack, test/lint/build commands, convention files). Edit it if detection got something wrong. To run several jobs at once, open several Claude sessions; each job gets its own worktree.

## Change the scrum

- Agents: `agents/scrum-*.md`. A repo can override one with its own `.claude/agents/<same name>.md`.
- The loop: `skills/trevskills-scrum/SKILL.md`
- Tests: `python3 -m unittest discover -s tests -v`
