#!/usr/bin/env python3
"""The scrum's one way to talk to the shop MacBook Pro: every remote command goes through `ssh shopmac`.

usage: shop.py probe   (print the cached probe as one JSON line; exit 0 whether the shop Mac is up or down)

run() never raises: a timeout comes back as exit 124, ssh that cannot start as 127, and ssh's own failure as 255.
probe() is one cached round trip that prints nothing when the shop Mac sleeps. See lanes/shop.md.
"""
import argparse, json, subprocess, sys, time

ALIAS = "shopmac"
SSH_OPTS = ("-o", "BatchMode=yes", "-o", "ConnectTimeout=5")  # after the alias: they win over ~/.ssh/config
PATH_PREFIX = 'export PATH="$HOME/.local/bin:$PATH"; '  # node, gh and claude live there; a non-interactive shell lacks it
PROBE_CMD = "sysctl -n vm.loadavg hw.ncpu; command -v node gh claude; true"  # `true`: a missing tool is not a down Mac
PROBE_TIMEOUT = 10
UP_TTL = 60
DOWN_TTL = 300  # 5 of serve.py's one-minute watchdog ticks per probe of a sleeping shop Mac
TOOLS = ("node", "gh", "claude")

# ponytail: module global with no lock; add one when a second thread calls probe(). Callers treat the dict as read-only.
_cache = None  # (time.monotonic() of the probe, its result)


def run(cmd: str, timeout: float, input: str | bytes | None = None) -> subprocess.CompletedProcess:
    """Run `cmd` on the shop Mac. Secrets go in `input` (stdin), never in `cmd`. stdout and stderr come back as str."""
    argv = ["ssh", ALIAS, *SSH_OPTS, PATH_PREFIX + cmd]
    feed = {"stdin": subprocess.DEVNULL} if input is None else {
        "input": input.encode("utf-8") if isinstance(input, str) else input}
    try:
        r = subprocess.run(argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout, **feed)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(argv, 124, "", f"ssh {ALIAS} timed out after {timeout} s")
    except OSError as e:
        return subprocess.CompletedProcess(argv, 127, "", f"ssh {ALIAS} could not start: {e}")
    return subprocess.CompletedProcess(argv, r.returncode, r.stdout.decode("utf-8", "replace"),
                                       r.stderr.decode("utf-8", "replace"))


def probe() -> dict:
    """{"up", "load", "tools"} from one cached round trip; `load` is the 1-minute load as a percent of all cores
    (board.cpu_load_pct's unit) or None when unreadable. Down (any non-zero exit) is silent and never raises."""
    global _cache
    now = time.monotonic()
    if _cache and now - _cache[0] < (UP_TTL if _cache[1]["up"] else DOWN_TTL):
        return _cache[1]
    r = run(PROBE_CMD, PROBE_TIMEOUT)
    lines = r.stdout.splitlines() if r.returncode == 0 else []
    try:
        load = round(float(lines[0].strip("{} ").split()[0]) / int(lines[1]) * 100, 1)
    except (IndexError, ValueError, ZeroDivisionError):
        load = None
    tools = {t: any(line.rsplit("/", 1)[-1] == t for line in lines) for t in TOOLS}
    _cache = (now, {"up": r.returncode == 0, "load": load, "tools": tools})
    return _cache[1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="shop.py", description="Talk to the shop Mac over ssh shopmac.")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("probe", help="print the probe as one JSON line")
    parser.parse_args(argv)
    print(json.dumps(probe()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
