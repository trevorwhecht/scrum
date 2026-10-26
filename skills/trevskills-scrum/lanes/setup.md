# First-run setup (once per repo)

1. Run `mkdir -p "$F/jobs"`.
2. Add `scrum/` and `.claude/worktrees/` to `$(git rev-parse --git-common-dir)/info/exclude` unless they're already there.
3. If `$F/backlog.md` is missing, create it containing `# Backlog` plus one blank line.
4. Detect the project and write `$F/project.md`:
   - Read the repo `CLAUDE.md`/`AGENTS.md`, every `CLAUDE.md` in parent folders up to `$HOME`, and `.claude/rules/*.md` at each of those levels.
   - Then read `package.json` scripts and the lockfile, or `pyproject.toml`/`Makefile`/`go.mod`/`Cargo.toml`.
   - Prefer commands written explicitly in CLAUDE.md. Otherwise use package scripts (`test`, `lint`, `typecheck`, `build`). For TypeScript with no typecheck script, use `npx tsc --noEmit`. `Dev command:` is the command that starts the local dev server: an explicit one in CLAUDE.md first, then the `dev` package script, otherwise `none`. Write `none` when a command doesn't exist. Never invent a test runner.
   - `UI globs`: start from `*.tsx *.jsx *.css *.scss *.html *.vue *.svelte components/ app/`, keep only the entries the repo actually contains, and write `none` if the repo has no UI. Matching: `*.ext` matches any path ending in `.ext`, an entry ending in `/` matches any path containing that directory as a path component, and any other entry matches that exact path. Whatever the globs, a path with an `api/` path component directly under `app/`, or whose basename is `route.ts`, `route.js` or `route.tsx`, is never UI; a diff matching only such paths has no UI files.

```markdown
# Project profile (written by /trevskills-scrum; edit freely)
- Stack: <language / framework>
- Package manager: <npm|pnpm|yarn|pip|...>
- Install: <command>
- Test: <command|none>
- Typecheck: <command|none>
- Lint: <command|none>
- Build: <command|none>
- Dev command: <command|none>
- Has UI: <yes|no>
- UI globs: <space-separated globs|none>
- Conventions to read: <absolute paths of every CLAUDE.md / AGENTS.md / rules file found>
- Notes: <anything an agent must know, e.g. "tests need .env">
```

   `- Base branch: <branch>` is an optional line Trevor adds by hand to make every job target `<branch>` instead of `origin/HEAD` (see **New job** step 2). First-run setup never writes it.

   `- Orchestrator model: <model>` is an optional, hand-added line: the `--model` for headless orchestrator sessions, meaning only the headless `start` and `resume` sessions (BigBoy children started by **BigBoy lane** step 3, and the dashboard's Run now, reopen, Resume and Play). It defaults to `sonnet`. `inherit` (any case) passes no `--model`, so the session keeps its default model. A blank or malformed value (not `^[A-Za-z0-9._-]+$`) also gives `sonnet`. Interactive sessions, approve, rework, digest, research and agent `model:` pins ignore it. First-run setup never writes it.

   `- E2E: <command>` (optional, hand-added): an end-to-end test command the **Check gate** runs when the diff touches `UI globs`, and the BigBoy reviewer runs on main.

   `- Cloud environment: <id>` (optional, hand-added): the claude.ai/code environment the **Cloud lane** starts sessions in.

   `- Auto continue: <n>` (optional, hand-added): serve.py starts one headless run-all per idle opted-in project in dashboard rank order (the Rank dialog, stored as `projects.json` order; `n` orders nothing); only `board.machine_ok` and `MAX_SESSIONS` gate new work, and no new work while free RAM or disk is low. First-run setup does not write it.

   `- Test sign-in: <account> — credentials in <where>` is optional: the test account `scrum-review-ui` and `scrum-review-ux` sign in with to render signed-in pages. `<where>` is where the credentials live, such as an env var name or a file path; the line only points at them and never holds a password or token value. First-run setup writes it only when the repo's CLAUDE.md/AGENTS.md, rules files, README, seed script or e2e config already names a test account. Otherwise it writes no such line.

5. Tell the user this repo is now on the dashboard: open the **Trevskills Scrum** app, or run `python3 ~/.claude/skills/trevskills-scrum/serve.py` from anywhere, then go to http://localhost:8765. When `Has UI: yes` and step 4 wrote no `Test sign-in:` line, also ask the user to add one to `$F/project.md` so the ui and ux reviewers can render signed-in pages. This is a request in the message only: setup never waits for the answer. When `Has UI: no`, neither ask nor write it.
