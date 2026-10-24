#!/usr/bin/env python3
"""Run a command while holding the machine-wide build lock, so only one project Build runs at a time.

usage: buildlock.py '<Build string>'   (run through sh -c)
       buildlock.py <cmd> [args...]    (run as argv, no shell)

SCRUM_BUILD_LOCK overrides the lock file; SCRUM_BUILD_LOCK_TIMEOUT the wait in seconds (default 1800).
Exits with the command's exit code, 124 on a lock timeout, 127 when the command is not found.
"""
import fcntl, math, os, subprocess, sys, time
from pathlib import Path

DEFAULT_TIMEOUT = 1800.0


def lock_path() -> Path:
    return Path(os.environ.get("SCRUM_BUILD_LOCK") or Path.home() / ".claude" / "trevskills-scrum" / "build.lock")


def timeout_s() -> float:
    try:
        value = float(os.environ.get("SCRUM_BUILD_LOCK_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if math.isfinite(value) and value >= 0 else DEFAULT_TIMEOUT


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: buildlock.py '<command string>' | <cmd> [args...]", file=sys.stderr)
        return 2
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:  # only a live flock holds the lock, so a leftover file never blocks
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"buildlock: waiting for the build lock ({path})", file=sys.stderr, flush=True)
            limit = timeout_s()
            deadline = time.monotonic() + limit
            while True:  # flock has no timeout, so poll LOCK_NB
                time.sleep(0.5)
                try:
                    fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except BlockingIOError:
                    if time.monotonic() >= deadline:
                        print(f"buildlock: timed out after {limit:g} s waiting for the build lock ({path})",
                              file=sys.stderr)
                        return 124
        cmd = ["sh", "-c", argv[0]] if len(argv) == 1 else argv
        try:
            return subprocess.call(cmd)
        except (FileNotFoundError, PermissionError):
            return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
