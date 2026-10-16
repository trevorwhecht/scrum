STATUS: READY

## Summary
Added `POST /api/p/<project>/jobs/<id>/ask` to `serve.py`. `ask_prompt` builds the prompt from paths only. `ask_claude` loads the job and picks the worktree, or `root.parent` when the worktree is missing. It then opens `env CLAUDE_NOTIFIER_DISABLE=1 claude <prompt>` in Ghostty (`open -na Ghostty --args --working-directory=<cwd> -e ...`) when `/Applications/Ghostty.app` is a directory, and in a new Terminal.app window (`osa_new_window`) otherwise. Both go through `run_terminal`. The route is dispatched next to `terminal`, before the needs-human gate. `dashboard.html` gets `askState`/`askForm`/`redrawAsk`/`askClaude`, modelled on the Open terminal code. `askForm(job)` is in all three `renderActions` branches, the submit handler routes `act === "ask"`, and `open()` clears a stale non-pending ask state the same way it does for termState. There is one README bullet in the Dashboard section.

## Acceptance criteria
1. Ghostty: 200 + exact `open -na Ghostty ...` argv — verified by `test_ask_opens_ghostty_in_worktree` — PASS
2. Terminal fallback argv shape + message — verified by `test_ask_falls_back_to_terminal` — PASS
3. cwd = worktree if it is a directory, else repo root (`/nonexistent/path` and no worktree, both launchers) — verified by `test_ask_uses_repo_root_when_worktree_missing` — PASS
4. Prompt lists the existing artifacts in order, omits missing spec.md/build.md, sorts rounds numerically (the test adds `round-10` to prove 2 < 10), ends with board.json + id — verified by `test_ask_prompt_lists_existing_artifacts` (full literal prompt string) — PASS
5. Unknown job 404 `{"error": "no such job"}`, bad ids 400, no subprocess — verified by `test_ask_rejects_unknown_and_bad_id` — PASS
6. Launcher failure: 500 with the last stderr line, and an OSError gives 500 — verified by `test_ask_launcher_failure_returns_500`. The modal `role="alert"` was checked live in headless Chromium against a real serve.py with a stub `osascript` that exits 1. The alert read "execution error: Terminal got an error: not allowed (-1743)". — PASS. (The Mac/Ghostty-renamed manual check could not be run on this Linux box. The Linux run exercises the same Terminal-fallback path.)
7. `askForm(job)` is in every `el.innerHTML =` branch, the submit handler routes ask, and the pending/status/alert rendering is correct — verified by `test_ask_button_in_every_modal_branch` (static check + node render of askForm). A live headless-Chromium click on a done job against `serve.py --port 8791` showed the button disabled while pending, then `role="status"` "Claude opened in a new Terminal window.", which was still present after 6 s of polling re-renders. The stub osascript received argv `[script, <repo>, env, CLAUDE_NOTIFIER_DISABLE=1, <claude>, <prompt>]`. — PASS
8. Foreign Origin/Host refused with 403 and no subprocess — verified by `test_ask_rejects_foreign_origin` — PASS

RED: before implementation, `python3 -m unittest tests.test_serve -k test_ask` gave `FAILED (failures=5, errors=1)` (route returned 404). `tests.test_dashboard_job_modal -k test_ask` gave `FAILED (failures=1)` (`'askForm(job)' not found in ...`). The origin test passed before implementation, because the origin guard runs before routing.
GREEN: `Ran 7 tests ... OK` and `Ran 6 tests ... OK`.

Full suite: `python3 -m unittest discover -s tests` returned exit 0, `Ran 674 tests ... OK (skipped=2)` — PASS. Typecheck/lint/build: none in PROJECT.

## Rulings
- Ruling: the prompt and cwd use `root` as given, with no `.resolve()` — the registry already stores resolved repo paths. Tests compare against `os.path.realpath(self.root)` so they also pass on macOS, where /var resolves to /private/var — cost if wrong: a non-canonical path in the prompt, which is harmless.
- Ruling: rounds match only `round-<digits>` directories and sort numerically. Files within a round are sorted by name and limited to `*.md` — follows the spec — cost if wrong: a stray non-md file isn't listed.
- Ruling: `..%2F..%2Fx` returns 400 (the id check), and the test asserts this — matches criterion 5.
- Ruling: the Ask Claude button sits after Open terminal in every branch. Updated the expected button list in `tests/test_dashboard_mobile_390_browser.py` (the new button measures 44px tall on the 390px viewport) — cost if wrong: cosmetic ordering.

## Commits
- 15759de Add Ask Claude button to every job modal
- (round 1: no code change; render evidence only)

## Round 1 response
- review-code: PASS, no findings.
- review-security: PASS (skipped by orchestrator).
- review-ui: PASS, no findings.
- review-ux finding 1 [blocking] "UI diff not rendered": fixed with render evidence and no code change — the reviewer's environment had no browser on PATH, but nothing in the code was wrong. Chromium is in this environment at `/opt/pw-browsers` (`PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers`), and the Node `playwright` module is under `NODE_PATH=/usr/local/lib/node_modules_global`, with `node` at `/opt/node22/bin/node`. Two ways to render it:
  1. Existing browser test at 390 px. From the worktree, `python3 -m unittest -v tests.test_dashboard_mobile_390_browser` gave `Ran 4 tests ... OK`, with none skipped. `test_viewer_action_buttons_44px` opens a needs-human job's modal at 390x844 in headless Chromium and asserts the action buttons are exactly `["Approve & merge", "Discuss first", "Send back to builder", "Open terminal", "Ask Claude", "Abort job"]`, each 44 px tall. `test_viewer_tabs_desktop_unchanged` covers 1280 px.
  2. Full walkthrough of the button states at 390 and 1440 px. Save the script below as `/tmp/ask-walk.sh` and run `bash /tmp/ask-walk.sh <WORKTREE>` (screenshots go to `$OUT`, default `/tmp`). It starts the real `serve.py` on port 8792 with a throwaway registry and a done job, with a stub `osascript` on PATH because Linux has none. It clicks Ask Claude and then re-clicks with the stub set to fail. Run in round 1 (exit 0):
     `{"width":390,"visible":true,"height":44,"pending":true,"status":"Claude opened in a new Terminal window.","statusAfterPoll":"Claude opened in a new Terminal window.","alert":"execution error: Terminal got an error: not allowed (-1743)","overflow":false}`
     `{"width":1440,"visible":true,"height":44,"pending":true,"status":"Claude opened in a new Terminal window.","statusAfterPoll":"Claude opened in a new Terminal window.","alert":"execution error: Terminal got an error: not allowed (-1743)","overflow":false}`
     The 390 px screenshot shows Reopen, then Ask Claude below it, with the red alert line under the button and no horizontal overflow.

```bash
#!/usr/bin/env bash
# Usage: ask-walk.sh <worktree>. Renders the Ask Claude button at 390 and 1440 px against a real serve.py (port 8792),
# with a stub osascript on PATH (Linux has none), and prints visible/height/pending/status/alert/overflow per width.
set -e
WT=$1; T=$(mktemp -d); mkdir -p $T/bin $T/repo/scrum/jobs
printf '#!/bin/sh\necho "$@" >> %s/osa.log\n[ -e %s/fail ] && { echo "execution error: Terminal got an error: not allowed (-1743)" >&2; exit 1; }\nexit 0\n' $T $T > $T/bin/osascript
chmod +x $T/bin/osascript
export SCRUM_REGISTRY=$T/projects.json SCRUM_MUTE=1 SCRUM_CLAUDE=/usr/bin/true PATH=$T/bin:$PATH
python3 -c "import sys; sys.path.insert(0, '$WT/skills/trevskills-scrum'); import board, json; from pathlib import Path
board.cmd_register('$T/repo'); r = Path('$T/repo/scrum'); i = board.cmd_new(r, 'Done one')
p = r / 'board.json'; d = json.loads(p.read_text()); d['jobs'][0]['stage'] = 'done'; p.write_text(json.dumps(d))"
python3 $WT/skills/trevskills-scrum/serve.py --port 8792 > $T/serve.log 2>&1 & SRV=$!
trap "kill $SRV; rm -rf $T" EXIT
for _ in $(seq 50); do curl -s -o /dev/null localhost:8792/ && break; sleep 0.1; done
cat > $T/drive.js <<'JS'
const {chromium} = require("playwright"), fs = require("fs");
(async () => {
  const b = await chromium.launch();
  for (const width of [390, 1440]) {
    try { fs.unlinkSync(process.env.FAIL); } catch {}
    const page = await b.newPage({viewport: {width, height: 900}}), sel = '#actions form[data-act="ask"]';
    await page.goto("http://127.0.0.1:8792/");
    await page.click(".card[data-key]");
    await page.waitForSelector(sel + " button");
    const r = await page.$eval(sel + " button", e => { const b = e.getBoundingClientRect(); return {visible: b.width > 0 && b.height > 0, height: b.height}; });
    await page.route("**/ask", async x => { await new Promise(s => setTimeout(s, 800)); x.continue(); });
    await page.click(sel + " button"); await page.waitForTimeout(150);
    const pending = await page.$eval(sel + " button", e => e.disabled);
    const status = await (await page.waitForSelector(sel + ' [role="status"]')).textContent();
    await page.waitForTimeout(6000);
    const statusAfterPoll = await page.$eval(sel + ' [role="status"]', e => e.textContent).catch(() => null);
    fs.writeFileSync(process.env.FAIL, "");
    await page.click(sel + " button");
    const alert = await (await page.waitForSelector(sel + ' [role="alert"]')).textContent();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > innerWidth);
    await page.screenshot({path: `${process.env.OUT}/ask-${width}.png`});
    console.log(JSON.stringify({width, ...r, pending, status, statusAfterPoll, alert, overflow}));
    await page.close();
  }
  await b.close();
})().catch(e => { console.log(e.stack); process.exit(1); });
JS
FAIL=$T/fail OUT=${OUT:-/tmp} node $T/drive.js
```
