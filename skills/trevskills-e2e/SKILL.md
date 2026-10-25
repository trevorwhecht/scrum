---
name: trevskills-e2e
description: Cheap, repeatable Playwright E2E check. Replays the saved specs first, writes a new spec only for changed UI that no spec covers, and sorts each failure into real bug, stale test or flake (asking Jev yes/no questions). Run it as /trevskills-e2e, or let the scrum-review-e2e agent load it.
---

# /trevskills-e2e

One E2E pass over a repo: replay what is saved, cover only what is new, and explain every failure. **No human is watching** when an agent runs this, so never ask questions; make the reasonable call and say so in the report.

Inputs: the repo root (the current directory, or `WORKTREE` when an agent runs it), an optional `BASE` (e.g. `origin/main`) and an optional `PROJECT` (the project profile path an agent was given). Run every command from the repo root.

**The E2E/test directory** is `testDir` from `playwright.config.*` when there is one; otherwise `e2e/` when it exists, else `tests/`. New specs go there and nowhere else.

## 1. Find the E2E command

1. Read the `- E2E:` line of the `PROJECT` file when an agent supplied one. Only on a direct run with no `PROJECT`, read it from `scrum/project.md` (relative to the repo root). When the line is present and not `none`, that is the command.
2. When the line is missing or `none`, and `package.json` has a `test:e2e` script, the command is `npm run test:e2e`.
3. When there is neither, stop here. The whole report is the one line `E2E: no command`.

## 2. Map changed files to routes/pages

- **With a base:** list the changed files with `git diff --name-only <BASE>...HEAD`. Map each UI file to the route(s) or page(s) it renders: the file-system route for `app/`, `pages/` or `routes/` files; for a shared component or stylesheet, every route whose page imports it (`grep -rl` for the import). Files that render nothing (tests, docs, config) map to no route.
- **Run directly with no base:** the target is all routes.

Then find the saved specs that cover each target route: the spec files in the E2E/test directory whose `page.goto(...)` or test title names the route.

## 3. Replay the saved suite first

Replay needs no AI: run the E2E command as-is, once. With a base, run only the specs that cover the target routes when the runner accepts file arguments (e.g. `npx playwright test <spec files>`); otherwise run the whole command. Record each spec file run under `Specs run:`. Passing specs need no further reading.

## 4. Cover changed UI that has no spec

Only for a target route (or a new element on it) that no saved spec covers:

1. When the repo has Playwright's generator agent output (from `npx playwright init-agents --loop=claude`, e.g. `.claude/agents/playwright-test-generator.md` or a `specs/` plan folder), use it: follow that generator's instructions for this route.
2. Otherwise drive the page once yourself with Playwright (start the project's dev server on a free port when the config has no `webServer`) and note the roles, labels and test ids of the new elements.
3. Save one spec file for the route in the E2E/test directory. It uses only `getByRole`, `getByLabel` or `data-testid` (`getByTestId`) locators, never CSS or XPath selectors, and asserts real page content (visible text, a value, a count), never only that the page loaded. It never skips on missing data: it creates the record it needs in its own setup when the project's database notes allow dev writes, else it fails naming the missing record.
4. Run that spec alone. When it fails because the spec itself is wrong (a locator or expected value that does not match what step 2 observed), fix the spec and run it again. When the spec is correct and still fails, keep it saved and send it through section 5 (retry once, then classify); with no pass on the retry it is a `real bug`, and the never-weaken rule in section 5 applies to it. Record it under `Specs added:`.

Never install Playwright or run `init-agents` for the user; when Playwright is missing, report `Specs added: none (Playwright not installed)` and go on.

## 5. On failure

For each failing spec:

1. Read only its trace/error-context (`test-results/**/error-context.md`, or the trace's error) and the page's `innerText` at the failure (from the error context, or `await page.locator('body').innerText()` in a one-off run).
2. Retry that spec once. When it passes on the retry, its verdict is `flake`. Never call a failure a flake without that retry.
3. Otherwise decide:
   - `real bug`: the app does the wrong thing (the asserted content is wrong or missing because of the code).
   - `stale test`: the app is right and the spec's expectation is out of date (renamed label, moved route, intended copy change). Update the locator or the expected value to the new intended behaviour and re-run it.
   - `flake`: it passed on the retry, or the failure is timing/environment only.

An assertion is never weakened or deleted to make a test pass: a `stale test` fix changes what is asserted to the new correct value, never removes the check. When in doubt, the verdict is `real bug`.

## 6. Jev for yes/no questions

When a verdict is unclear, ask Jev a yes/no question, e.g. `This failure is caused by an intended UI change` (with the error and the diff stat as context).

1. When `~/.claude/scripts/jev-rank.py` exists, use it first (Bash timeout 90000):
   ```bash
   printf '%s' "<context>" | python3 ~/.claude/scripts/jev-rank.py "<question>" --top 1
   ```
   The score is the first tab-separated field; `>= 0.7` means yes.
2. Otherwise POST to `https://api.typesafe.ai/v1/systemone` with model `jev-latest` and one `noul` question, the way `jev-rank.py` does. Python reads the key from `TYPESAFE_API_KEY`, or else (macOS only) Keychain service `TypeSafe`, account `typesafe`, and sets the Authorization header itself. The script and the question travel in two single-quoted heredocs (script on fd 3, question on stdin: first line the question, the rest context), so neither the key nor the question touches a command line or a double-quoted shell string (paste it unindented so the `PY` and `JEV_Q_EOF` lines end the heredocs):

```bash
python3 /dev/fd/3 3<<'PY' <<'JEV_Q_EOF'
import json, os, subprocess, sys, urllib.request
question, _, context = sys.stdin.read().partition("\n")
key = os.environ.get("TYPESAFE_API_KEY") or subprocess.run(
    ["/usr/bin/security", "find-generic-password", "-s", "TypeSafe", "-a", "typesafe", "-w"],
    capture_output=True, text=True).stdout.strip()
if not key:
    sys.exit("jev: no TYPESAFE_API_KEY and no Keychain item TypeSafe/typesafe")
body = json.dumps({"model": "jev-latest", "state": {"context": context},
                   "questions": {"q": {"type": "noul", "instructions": question}}}).encode()
req = urllib.request.Request("https://api.typesafe.ai/v1/systemone", body,
                             {"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=60) as r:
    print(json.load(r)["answers"]["q"]["noul"])
PY
<question>
<context>
JEV_Q_EOF
```

   The printed score `>= 0.7` means yes.
3. Any Jev error (no script and no key, a non-zero exit, a timeout, an unparseable answer) falls back to reading the output yourself.

The Jev key is never placed in a shell variable, argv, a file or output (not the report, not a spec, not a review); only Python holds it, in memory, for the one request that sends it.

## 7. Token rules

- Never use a browser MCP when a saved spec can run; replay the spec instead.
- Read only the failing test's output, never the full log of a passing run.
- Take no screenshots unless a check needs one.

## 8. The report

    Specs run: <n> — <spec files>
    Specs added: <n> — <spec files>|none
    Failures: <n>|none
    - <spec>:<test name> — real bug|stale test|flake — <one-line reason>

One verdict per failure. A direct run writes the report to stdout only; an agent run puts it in its review file.
