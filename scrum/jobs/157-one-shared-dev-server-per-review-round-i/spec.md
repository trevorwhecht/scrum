# One shared dev server per review round
UI surface: no
Hard stops: none
Lane: standard

## Problem
In a full review round, `scrum-review-ui` and `scrum-review-ux` each start their own dev server from the worktree (agents/scrum-review-ui.md and agents/scrum-review-ux.md, **Render the real page** step 1). That means two cold starts per round, two chances to collide on ports, and two chances to fail differently. The orchestrator should start the project's `Dev command` once per round, check that it actually serves, record the result, give the URL to both UI reviewers, and stop it when they are done.

## Scope
In:
- `skills/trevskills-scrum/SKILL.md`, **Review (WAIT FOR ALL)**: a new instruction placed after step 2's skip decisions and before the step 3 spawn. It starts the shared server, probes it, writes `round-$N/dev-url.txt` and passes `DEV_URL=<url>` to the ui/ux spawns. A matching instruction stops the server once step 4's WAIT FOR ALL (re-spawns included) has finished, before step 5 routes.
- `agents/scrum-review-ui.md` and `agents/scrum-review-ux.md`, **Render the real page** step 1: if the prompt has `DEV_URL=<url>`, render that URL and start no server. Otherwise start a fresh server as they do today.
- `tests/test_contracts.py`: new contract assertions.

Out:
- The Fast lane (it spawns no ui/ux reviewer), the builder's own dev server (agents/scrum-builder.md), and the Approve/Merge `Restart:` flow.
- Reusing one server across rounds, or between the builder and the reviewers.
- Any change to board.py, serve.py or the dashboard (dev-url.txt is not shown anywhere new).
- Changing this repo's own `Dev command: none` in project.md.

## Acceptance criteria
1. The **Review** section of SKILL.md says the orchestrator starts the shared server only when all of these hold: at least one of `scrum-review-ui` / `scrum-review-ux` will be spawned in step 3 (step 2 wrote neither a skip file nor a carried-forward file for it); at least one file in `git -C "$WT" diff --name-only "$BASE"...HEAD` matches `UI globs`; and `project.md`'s `Dev command:` is present and not `none`. When any of these fails, it starts nothing, writes no `dev-url.txt` and passes no `DEV_URL`. (verify: `test_skill_review_shares_one_dev_server` in tests/test_contracts.py asserts the Review section (`self.section(text, "## Review (WAIT FOR ALL)", "## Approve")`) contains `Dev command:`, `UI globs` and `not \`none\``)
2. The Review section says the server is started exactly once per round, in the background, from `$WT`, on a free port that is never 3001. It is started as `PORT=<port> nohup <Dev command> >> round-$N/dev.log 2>&1 &`, and its PID is recorded. (verify: the same test asserts the section contains `round-$N/dev.log`, `free port` and `3001`)
3. The Review section says the probe counts as reachable only when both of these succeed within 60 seconds of the start: (a) `curl -s -o /dev/null -w '%{http_code}' http://localhost:<port>/` returns `200`; (b) one GET to a data API path returns a 2xx status. The API path is the first `/api/...` path the diff references, otherwise the first `/api/...` path the served root page references. When neither has an `/api/` path, (b) is skipped and recorded as `no API path to probe`. On success it writes `round-$N/dev-url.txt` containing exactly `http://localhost:<port>`. On failure it writes `unreachable: <why>` (for example `unreachable: / returned 500` or `unreachable: no response within 60s`), stops the server, and passes no `DEV_URL`. (verify: the same test asserts the section contains `round-$N/dev-url.txt`, `unreachable: <why>`, `200` and `/api/`)
4. The Review section's step 3 says that when `dev-url.txt` holds a URL, the `scrum-review-ui` and `scrum-review-ux` spawns (and any step 4 re-spawn of them) get the extra prompt line `DEV_URL=<url>`, and no other reviewer gets it. The **resume** `review` path spawns "as Review step 3", so it inherits this rule through that reference and needs no separate text. (verify: the same test asserts the section contains `DEV_URL=<url>`)
5. The Review section says that after step 4's WAIT FOR ALL, re-spawns included, and before step 5 routes, the orchestrator stops the server it started (by the recorded PID, plus `lsof -ti tcp:<port> -sTCP:LISTEN | xargs kill` for any child still listening). It stops the server on every route out of step 4. (verify: the same test asserts the section contains `kill` and `-sTCP:LISTEN` after the `dev-url.txt` text)
6. Both agents/scrum-review-ui.md and agents/scrum-review-ux.md say in **Render the real page** step 1: when the prompt has `DEV_URL=<url>`, open that URL, start no server and never stop that server. Only when `DEV_URL` is absent do they start a fresh server from WORKTREE on a spare port, as today. All phrases that `assert_reviewer_renders` and `test_review_ux_ui_digest_rules` require stay unchanged, including `serve.py --port <free port>` and `Stop the server and Chrome you started`. (verify: new `test_ui_reviewers_use_dev_url` in tests/test_contracts.py asserts each file contains `DEV_URL` and `DEV_URL` is absent; existing `test_ui_reviewer_renders_page` / `test_ux_reviewer_renders_page` still pass)
7. Edge case, shared server dies mid-round: both agents say that if `DEV_URL` does not answer when they open it, they start their own fresh server as in the no-`DEV_URL` path, and say so in their `Rendered:` line. They never write `Rendered: no` only because `DEV_URL` was down. (verify: `test_ui_reviewers_use_dev_url` asserts each file contains `does not answer`)
8. The full suite passes. (verify: `python3 -m unittest discover -s tests`)

## Likely files
- `skills/trevskills-scrum/SKILL.md`: **Review (WAIT FOR ALL)**, new text between step 2 and step 3, a `DEV_URL=<url>` line in step 3, and a stop instruction at the end of step 4.
- `agents/scrum-review-ui.md`: **Render the real page** step 1.
- `agents/scrum-review-ux.md`: **Render the real page** step 1.
- `tests/test_contracts.py`: new `test_skill_review_shares_one_dev_server(self)` and `test_ui_reviewers_use_dev_url(self)` in `ContractTest`.

## Assumptions
- "when the diff matches UI globs" also requires that ui or ux is actually spawned this round. On an incremental round where both are carried forward, or when the skip files stand, no server is started.
- `DEV_URL` is passed only when the probe succeeded. With `unreachable: <why>`, the agents get no `DEV_URL` and fall back to starting their own server, which matches "start their own server only when it is absent".
- "Kills it after WAIT FOR ALL" means after all of step 4, re-spawns included, because the re-spawned ui/ux reviewers also need the server.
- The port is passed as the `PORT` environment variable. Most dev servers (Next, Vite via config, Express conventions) read it. The `<port>` the probe uses is the one the orchestrator chose. If the server listens elsewhere, the probe fails and the round records `unreachable`, which is safe.
- "One data API call" is a GET to an `/api/` path, picked as in criterion 3, with a 2xx response. Projects with no `/api/` path skip that half of the probe instead of failing.
- 60 seconds is the probe deadline (poll every 2 s).
- Server output goes to `round-$N/dev.log` in the job dir so that an `unreachable` reason can be checked. board.py and the dashboard need no change for it.
- In this repo `Dev command: none`, so on this repo's own jobs nothing changes at runtime. The UI agents keep starting serve.py themselves.
- dev-url.txt and dev.log are not review files, so the orchestrator-edit exception list (the "never edits code or review files" line) needs no change.
