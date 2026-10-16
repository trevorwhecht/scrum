STATUS: READY

## Summary
The Review section of SKILL.md now has one more step 2 bullet, **Shared dev server**. It runs after the skips and the Jev gate. When ui or ux will be spawned, the diff matches `UI globs` and `Dev command:` is set and not `none`, the orchestrator does three things:
- starts the dev command once, on a free port that is never 3001, from `$WT`, with output going to `round-$N/dev.log`;
- probes `/` for a `200` and the first `/api/` path for a 2xx, giving up after 60 s;
- writes `round-$N/dev-url.txt`, holding either the URL or `unreachable: <why>`.

Step 3 passes `DEV_URL=<url>` to the ui/ux spawns and their re-spawns only. A new last bullet in step 4 stops the server (the PID, then `lsof -ti tcp:<port> -sTCP:LISTEN | xargs kill`) after WAIT FOR ALL and before step 5 routes.

In both scrum-review-ui.md and scrum-review-ux.md, **Render the real page** step 1 now uses `DEV_URL` when it is given. The reviewer never starts or stops that server. If `DEV_URL` is missing or does not answer, the reviewer starts its own server and says so in the `Rendered:` line. Two new contract tests cover this.

## Acceptance criteria
1. Start conditions (ui/ux spawned, UI globs match, Dev command not `none`), and otherwise nothing is started — verified by `test_skill_review_shares_one_dev_server` — PASS
2. Started once, in the background, from `$WT`, on a free port that is never 3001, with `PORT=<port> nohup ... >> .../round-$N/dev.log 2>&1 &` and the PID recorded — verified by `test_skill_review_shares_one_dev_server` — PASS
3. Probe: `/` must return 200 and the API path a 2xx, within 60 s; `no API path to probe`; `dev-url.txt` holds the URL or `unreachable: <why>` — verified by `test_skill_review_shares_one_dev_server` — PASS
4. `DEV_URL=<url>` goes to the ui/ux spawns and re-spawns only — verified by `test_skill_review_shares_one_dev_server` — PASS
5. Stop by PID plus `lsof ... -sTCP:LISTEN | xargs kill` after step 4 and before step 5, on every route — verified by `test_skill_review_shares_one_dev_server` (kill and -sTCP:LISTEN appear after the dev-url.txt text) — PASS
6. The agents use `DEV_URL` when it is given and start or stop no server for it; they start their own server only when `DEV_URL` is absent. The existing phrases are unchanged — verified by `test_ui_reviewers_use_dev_url`, `test_ui_reviewer_renders_page`, `test_ux_reviewer_renders_page` and `test_review_ux_ui_digest_rules` — PASS
7. If `DEV_URL` does not answer, the agent falls back to its own server and never writes `Rendered: no` for that reason alone — verified by `test_ui_reviewers_use_dev_url` — PASS
8. Full suite — `python3 -m unittest discover -s tests` → `Ran 668 tests ... OK (skipped=2)`, exit 0 — PASS

RED: `FAIL: test_skill_review_shares_one_dev_server ... AssertionError: 'Dev command:' not found` and `FAIL: test_ui_reviewers_use_dev_url ... AssertionError: 'DEV_URL' not found` (Ran 2 tests, FAILED (failures=2)).
GREEN: these 2 tests plus the renders_page and digest_rules tests → `OK`. Full suite → 668 tests OK, exit 0.

Typecheck, lint and build all show `none` in project.md, so there was nothing to run. Dev command is `none` and UI surface is `no`, so no browser walkthrough applies; the change is to Markdown instructions only.

## Rulings
- Ruling: the new text is a sub-bullet at the end of step 2 and the stop is a sub-bullet at the end of step 4, rather than new numbered steps — this keeps every existing "step 3", "step 4" and "step 5" reference (including resume's "as Review step 3") valid — cost if wrong: only a matter of layout.
- Ruling: dev.log is written to the absolute path `"$F/jobs/$ID/round-$N/dev.log"`, because the command first runs `cd "$WT"` — a relative `round-$N/dev.log` would land inside the worktree — cost if wrong: none; the test still matches `round-$N/dev.log`.
- Ruling: the API path comes from `grep -oE '/api/[A-Za-z0-9_./-]*' | head -1` over the diff, then over the served root page — this is a simple, concrete way to find "the first /api/ path" — cost if wrong: a dynamic segment such as `[id]` gets cut off, so the probe may hit a 404 and record `unreachable`. That is safe, because the reviewers then fall back to their own servers.
- Ruling: `no API path to probe` is recorded in `round-$N/dev.log` — the spec says "recorded" but names no file, and dev-url.txt must contain exactly the URL — cost if wrong: small.
- Ruling: a failed probe still writes `unreachable: <why>` into `round-$N/dev-url.txt` — this follows criterion 3's "On failure it writes" right after the dev-url.txt sentence — cost if wrong: small; nothing reads the file except step 3, and step 3 ignores `unreachable:`.

## Commits
- ad06002 Share one dev server per review round between the ui and ux reviewers
