# Shop Mac

## Transport and probe

`skills/trevskills-scrum/shop.py` is the scrum's only way to talk to the shop MacBook Pro (mid 2015, macOS 12). It is stdlib only; serve.py and board.py import it the way serve.py imports `buildlock.py`.

- **Every call starts `ssh shopmac`.** The alias and its key live in `~/.ssh/config`. Options go after the alias (`ssh shopmac -o BatchMode=yes -o ConnectTimeout=5 ...`), where they win over the config file. Never use another remote-exec form.
- **PATH.** A non-interactive ssh shell has only `/usr/bin:/bin:/usr/sbin:/sbin`, so every remote command is prefixed with `export PATH="$HOME/.local/bin:$PATH";` (node, gh and claude live there; git is `/usr/bin/git`).
- **Secrets go through `input`.** `run(cmd, timeout, input=None)` sends `input` on stdin (a `str` as UTF-8, `bytes` unchanged) and never puts it in argv. With no `input`, ssh reads `/dev/null`, never the caller's stdin. stdout and stderr are captured, so ssh's own messages never reach the caller's terminal or log.
- **Failed results, never exceptions.** `run` has a hard subprocess timeout and returns a `CompletedProcess` with `str` output: `124` when the timeout hits, `127` when ssh cannot start, and ssh's own `255` when the connection fails. Output that is not UTF-8 is decoded with replacement.
- **Probe.** `probe()` makes one round trip (`sysctl -n vm.loadavg hw.ncpu; command -v node gh claude; true`, 10 s timeout) and returns `{"up": bool, "load": float | None, "tools": {"node": bool, "gh": bool, "claude": bool}}`. `load` is the 1-minute load as a percent of all cores, `board.cpu_load_pct`'s unit; it is None when the output does not parse. A missing tool never reads as down. The result is cached in-process: an up result for 60 s, a down result for 300 s, so a sleeping shop Mac costs at most one probe of 10 s or less per 5 one-minute watchdog ticks.
- **Down is silent.** When the shop Mac sleeps or is unreachable (exit `255`, `124` or `127`), `probe()` returns `up: false` and prints nothing and raises nothing. Callers skip it quietly: Trevor may be out of town.
- **CLI.** `python3 shop.py probe` prints the probe as one JSON line and exits 0 whether the shop Mac is up or down. Later tickets add their own subcommands and sections here.
