# gitguard

The user-level PreToolUse hook that refuses a chat's Bash `git commit` on `main`/`master` in a registered repo's main
checkout (job 607), ported from `board.py git-guard` to a stdlib-only Go binary (job 812). Same rules: scrum-launched
sessions (`CLAUDE_NOTIFIER_DISABLE`) and sessions owning an ACTIVE job (pid, else tty) are exempt; any error means no
output and exit 0.

- Build: `./install.sh` runs `go build -o gitguard` here and registers `<path>/gitguard || true` in
  `~/.claude/settings.json` (rewriting an old `board.py ... git-guard` entry). No Go: the hook is a silent pass.
- Test: `cd skills/trevskills-scrum/gitguard && go test ./...` (`tests/test_gitguard.py` runs it when Go is installed).
- `board.py git-guard` is now a silent exit-0 no-op, kept for settings.json files not yet migrated.

## Go trial: result

Measured 2026-11-13 on Trevor's Mac (Apple Silicon, go1.27.4), 5 runs each. Events: `git status` (non-commit) and
`git commit -m x` in a registered repo's main checkout on `main` (deny), with `SCRUM_REGISTRY` pointing at a one-repo
registry.

`/usr/bin/time -p sh -c '<cmd> < event.json >/dev/null'` (10 ms resolution, includes `sh` start-up):

| Hook | git status | commit on main |
|---|---|---|
| Python `python3 board.py git-guard` (BASE) | 0.18 0.18 0.19 0.19 0.18 s | 0.23 0.23 0.23 0.23 0.23 s |
| Go `gitguard` | 0.01 0.01 0.01 0.01 0.01 s | 0.07 0.05 0.05 0.05 0.06 s |

`time.perf_counter()` around `subprocess.run(argv, input=event)` (ms):

| Hook | git status | median | commit on main | median |
|---|---|---|---|---|
| Python (BASE) | 192.4 178.7 181.4 179.5 181.2 | 181.2 ms | 221.1 224.9 219.1 217.9 216.5 | 219.1 ms |
| Go | 5.8 5.1 4.7 4.8 4.7 | 4.8 ms | 39.3 39.9 40.7 39.7 39.6 | 39.7 ms |

The non-commit path is about 38x faster and under 10 ms; the commit path is spent in the `ps` ancestor walks and two
`git` calls, which the port keeps.
