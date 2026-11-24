#!/usr/bin/env python3
"""Live check for job 1429's problem: the serve.py pulse (one pulse.log line a minute) never stops for more than
GAP_S seconds while the Mac is awake.

Reads board.pulse_path() lines from LIVE_CHECK_SINCE (epoch seconds; default now - 24 h) to that time + 24 h.
Exit 75 while less than 24 h has passed since LIVE_CHECK_SINCE (not yet). Exit 1, printing each gap, when two
consecutive pulse lines (the window's start and end count as lines, so a pulse that stops, starts late or never
writes is a gap) lie more than GAP_S apart and no `Sleep` entry of `pmset -g log` falls inside the gap.
Exit 0 otherwise. Read-only."""
import json, os, re, subprocess, sys, time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import board  # noqa: E402

WINDOW_S = 24 * 3600
GAP_S = 180
NOT_YET = 75
PMSET_TIMEOUT_S = 45  # the live check runner kills the whole run at 60 s
SLEEP_RE = re.compile(r"^(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d [+-]\d{4}) Sleep\s.*?(?:(\d+) secs)?\s*$")


def pmset_sleeps(since: float, until: float) -> list[tuple[int, int]]:
    """(start, seconds) of each `Sleep` entry in `pmset -g log` that overlaps since..until; [] when pmset fails."""
    try:
        out = subprocess.run(["pmset", "-g", "log"], capture_output=True, text=True, errors="replace",
                             timeout=PMSET_TIMEOUT_S, check=False).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    sleeps = []
    for line in out.splitlines():
        if m := SLEEP_RE.match(line):
            start = int(datetime.strptime(m[1], "%Y-%m-%d %H:%M:%S %z").timestamp())
            secs = int(m[2] or 0)
            if start <= until and start + secs >= since:
                sleeps.append((start, secs))
    return sleeps


def pulse_times(since: float, until: float) -> list[int] | None:
    """The sorted `t` of each pulse.log line within since..until; None when pulse.log is missing."""
    try:
        text = board.pulse_path().read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    times = []
    for line in text.splitlines():
        try:
            t = json.loads(line).get("t")
        except (ValueError, AttributeError):
            continue
        if board.is_num(t) and since <= t <= until:
            times.append(int(t))
    return sorted(times)


def main(now=None, read_sleeps=pmset_sleeps) -> int:
    now = time.time() if now is None else now
    since = int(os.environ.get("LIVE_CHECK_SINCE") or now - WINDOW_S)
    if now - since < WINDOW_S:
        print(f"not yet: {int(now - since)} s of {WINDOW_S} s since the merge")
        return NOT_YET
    until = since + WINDOW_S
    times = pulse_times(since, until)
    if times is None:
        print(f"no pulse log at {board.pulse_path()}")
        return 1
    edges = [since, *times, until]  # the window's edges are boundaries: a silence at either end, or all day, is a gap
    gaps = [(a, b) for a, b in zip(edges, edges[1:]) if b - a > GAP_S]
    sleeps = read_sleeps(since, until) if gaps else []
    awake = [(a, b) for a, b in gaps if not any(s < b and s + secs > a for s, secs in sleeps)]
    stamp = lambda t: datetime.fromtimestamp(t).strftime("%Y-%m-%d %H:%M:%S")  # noqa: E731
    for a, b in awake:
        print(f"gap {b - a} s while awake: {stamp(a)} to {stamp(b)}")
    if not awake:
        print(f"ok: {len(times)} pulse lines, {len(gaps)} gaps over {GAP_S} s, all during sleep")
    return 1 if awake else 0


if __name__ == "__main__":
    sys.exit(main())
