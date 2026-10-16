# Ask Claude button in every job modal
UI surface: yes
Hard stops: none
Lane: standard

## Problem
Once a job's session has died, there is no quick way to ask questions about that job. Trevor has to open a terminal, cd into the worktree, start `claude`, and type out every artifact path by hand. The job modal should have a button that opens a new interactive Claude session in the job's worktree, with a prompt that already points at all of the job's artifacts.

## Scope
In:
- A new endpoint `POST /api/p/<project>/jobs/<id>/ask` in `serve.py`. It builds the prompt and opens a new interactive `claude` session. It uses Ghostty when `/Applications/Ghostty.app` exists and a new Terminal.app window otherwise.
- An **Ask Claude** button in the job modal's actions for every job, whatever its stage. It shows a pending state, then the message or error, the same way **Open terminal** does.
- One README line in the Dashboard section.

Out:
- Restricting the new session's tools or permissions (for example a read-only mode).
- iTerm support.
- Reusing or resuming the job's old session.
- Embedding file contents in the prompt. The prompt carries paths only.
- A button on the board cards. The button lives only in the modal.

## Acceptance criteria
1. With `/Applications/Ghostty.app` present, `POST /api/p/repo/jobs/<id>/ask` returns 200 with `{"id": <id>, "message": "Claude opened in Ghostty."}`. It runs exactly one command: `["open", "-na", "Ghostty", "--args", f"--working-directory={cwd}", "-e", "env", "CLAUDE_NOTIFIER_DISABLE=1", serve.CLAUDE, prompt]`. (verify: `test_ask_opens_ghostty_in_worktree` in `tests/test_serve.py`, with `os.path.isdir` patched to report the Ghostty app and `subprocess.run` mocked)
2. Without Ghostty, the same request runs `osa_new_window(cwd, "env", "CLAUDE_NOTIFIER_DISABLE=1", serve.CLAUDE, prompt)`. That gives argv `[:2] == ["osascript", "-e"]`, `argv[3] == str(cwd)`, `argv[4:7] == ["env", "CLAUDE_NOTIFIER_DISABLE=1", CLAUDE]` and `len(argv) == 8`. The response message is `"Claude opened in a new Terminal window."`. (verify: `test_ask_falls_back_to_terminal`)
3. `cwd` is the job's `worktree` from board.json when that is an existing directory. Otherwise, for example when the worktree is null or was removed after merge, `cwd` is the repo root (`root.parent`). The request still succeeds in both cases. (verify: `test_ask_uses_repo_root_when_worktree_missing`, using a job with `worktree=/nonexistent/path` and one with no worktree)
4. The prompt names the job id. It then lists, as absolute paths, each of these files that exists at click time, in this order:
   - `jobs/<id>/feature.md`
   - `jobs/<id>/spec.md`
   - `jobs/<id>/build.md`
   - every `jobs/<id>/round-<N>/*.md`, rounds in ascending numeric order and files sorted by name within a round (this covers `check.md`, every `review-<role>.md` and `decision.md`)
   - `jobs/<id>/decision.md`

   It ends by pointing at `<scrum dir>/board.json` and the entry whose `"id"` is `<id>`. A file that doesn't exist is left out, and the prompt never names it. (verify: `test_ask_prompt_lists_existing_artifacts`, which creates feature.md, round-1/check.md, round-1/review-code.md, round-2/check.md and decision.md, then asserts the order and the absence of spec.md and build.md)
5. An unknown job returns 404 `{"error": "no such job"}`, and a malformed id returns 400. Neither starts a subprocess. (verify: `test_ask_rejects_unknown_and_bad_id`)
6. If the launcher fails (non-zero exit or an OSError), the endpoint returns 500 with the launcher's last stderr line, as `run_terminal` already does, and the modal shows it in a `role="alert"` span next to the button. (verify: `test_ask_launcher_failure_returns_500`, plus a manual check in the dashboard on a Mac with Ghostty renamed away)
7. `renderActions` includes the **Ask Claude** form (`<form data-act="ask">`) in all three branches: run alive, not needs-human (including done and aborted), and needs-human. While the request is pending the button is disabled. Afterwards the server's message shows in a `role="status"` span, and the state survives a polling re-render. (verify: `test_ask_button_in_every_modal_branch` in `tests/test_dashboard_job_modal.py`, a static check that `askForm(job)` appears in each `el.innerHTML =` assignment in `renderActions` and that the submit handler routes `act === "ask"`; plus a manual click in the dashboard)
8. A request from a foreign Origin is refused, as for the other job endpoints. (verify: `test_ask_rejects_foreign_origin`, mirroring `test_terminal_rejects_foreign_origin`)

## Likely files
- `skills/trevskills-scrum/serve.py`:
  - Add `ask` to the job-action alternation in the POST route regex (`/jobs/[^/]+/(?:approve|...|resume|ask)`).
  - Add `def ask_prompt(root: Path, job_id: str) -> str`, which builds the prompt from criterion 4.
  - Add `def ask_claude(project: str, root: Path, job_id: str) -> tuple[int, dict]`, which loads the job, picks `cwd`, and calls `run_terminal([(cmd, message)])` with the Ghostty or Terminal command.
  - In `Handler.route`, dispatch `if action == "ask": return ask_claude(project, root, job_id)` before the needs-human gate, next to `terminal`.
  - Prompt text: `Answer my questions about scrum job <id>. Its session has ended. Read these first:\n<path per line>\nIts board entry is the object with "id": "<id>" in <scrum dir>/board.json. Don't change any file unless I ask.`
- `skills/trevskills-scrum/dashboard.html`:
  - Add `const askState = {}`, `function askForm(job)`, `askClaude(key)` and a redraw helper, modelled on `termState`, `termForm`, `openTerminal` and `redrawTerm`.
  - Add `askForm(job)` to each branch of `renderActions`.
  - In the actions submit handler, add `if (act === "ask") return askClaude(key);`.
  - The button gets a `data-agent-hint` explaining that it opens a new Claude session in the job's worktree, preloaded with the job's files.
- `tests/test_serve.py`: criteria 1–6 and 8.
- `tests/test_dashboard_job_modal.py`: criterion 7.
- `README.md`: one bullet in the Dashboard section.

## Assumptions
- "Every job modal" means every stage, including done, aborted, BigBoy parents and cloud jobs. A job without a worktree falls back to the repo's main checkout, so the button always works.
- I took "Ghostty missing" to mean `/Applications/Ghostty.app` is not a directory, the same check `open_terminal` already uses.
- `--working-directory=` sets Ghostty's cwd, because `open -na Ghostty --args -e ...` takes no cd. The prompt reaches the session only as an argv item, never as shell text.
- "Every round's check/review files" covers everything in `round-<N>/` (`check.md`, `review-*.md`, the per-round `decision.md`), which is simpler than filtering by name. The top-level `decision.md` is listed after the rounds.
- The board.json entry is pointed at by path and id, not pasted into the prompt, which keeps the argv short and the data current.
- The session gets `CLAUDE_NOTIFIER_DISABLE=1`, like every other dashboard-opened interactive session (`test_terminal_sessions_silence_notifier`).
- The prompt asks the session not to change files unless Trevor asks. No tool restriction is enforced.
- The new session is not recorded as the job's tty or term, and it is not added to `RUNS`, so the board and the watchdog ignore it.
