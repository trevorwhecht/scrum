#!/usr/bin/env python3
"""Run a command while holding the machine-wide build lock, so only one project Build runs at a time.

usage: buildlock.py '<Build string>'   (run through sh -c)
       buildlock.py <cmd> [args...]    (run as argv, no shell)
       buildlock.py --project <file>   (run the `- Build:` line of <file> through sh -c; exit 2 when it is missing or none)

SCRUM_BUILD_LOCK overrides the lock file; SCRUM_BUILD_LOCK_TIMEOUT the wait in seconds (default 1800).
While board.py's cool-down flag is on, waiters go in board.lock_rank order (nearest the finish line first), then by
arrival; the waiting marker holds `<cwd>\n<rank>`.
Exits with the command's exit code, 124 on a lock timeout, 127 when the command is not found.
"""
import fcntl, math, os, re, subprocess, sys, time
from pathlib import Path

DEFAULT_TIMEOUT = 1800.0


def lock_path() -> Path:
    return Path(os.environ.get("SCRUM_BUILD_LOCK") or Path.home() / ".claude" / "trevskills-scrum" / "build.lock")


def waiting_dir(lock: Path) -> Path:
    """Where a waiting buildlock.py leaves `<pid>` holding its cwd; serve.py reads it."""
    return lock.with_name(lock.name + ".waiting")


def timeout_s() -> float:
    try:
        value = float(os.environ.get("SCRUM_BUILD_LOCK_TIMEOUT", ""))
    except ValueError:
        return DEFAULT_TIMEOUT
    return value if math.isfinite(value) and value >= 0 else DEFAULT_TIMEOUT


def board_module():
    """board.py, imported lazily from this file's folder; None when the import fails (the build still runs)."""
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import board
        return board
    except (Exception, SystemExit):
        return None


def marker_rank(m: Path) -> int:
    """A waiting marker's second line as its rank; 0 when it has none or it is not a number."""
    try:
        return int(m.read_text().split("\n")[1].strip())
    except (OSError, ValueError, IndexError):
        return 0


def outranked(board, marker: Path, rank: int) -> bool:
    """While board.cooling_down(), True when another live waiter's marker beside `marker` goes first: a higher rank,
    or the same rank with an older mtime (then a lower pid). Outside cool down, or on any error, False."""
    try:
        if not board or not board.cooling_down():
            return False
        mine = (marker.stat().st_mtime, int(marker.name))
        for m in marker.parent.iterdir():
            if m.name == marker.name:
                continue
            try:
                pid = int(m.name)
                try:
                    os.kill(pid, 0)
                except PermissionError:
                    pass  # alive, owned by another user
                theirs, at = marker_rank(m), (m.stat().st_mtime, pid)
            except (OSError, ValueError):
                continue  # a dead pid or a vanished marker never blocks
            if theirs > rank or (theirs == rank and at < mine):
                return True
    except Exception:
        pass
    return False


def build_from(path: str) -> str | None:
    try:
        text = Path(path).read_text()
    except (OSError, UnicodeDecodeError):
        return None
    m = re.search(r"^- Build:[ \t]*(.*)$", text, re.M)
    value = m.group(1).strip() if m else ""
    return None if value.lower() in ("", "none") else value


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: buildlock.py '<command string>' | <cmd> [args...] | --project <file>", file=sys.stderr)
        return 2
    if argv[0] == "--project":
        if len(argv) != 2:
            print("buildlock: --project needs a path to project.md", file=sys.stderr)
            return 2
        value = build_from(argv[1])  # read before taking the lock, so a bad path never waits
        if value is None:
            print(f"buildlock: no runnable '- Build:' line in {argv[1]}", file=sys.stderr)
            return 2
        argv = [value]
    path = lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a") as f:  # only a live flock holds the lock, so a leftover file never blocks
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"buildlock: waiting for the build lock ({path})", file=sys.stderr, flush=True)
            limit = timeout_s()
            deadline = time.monotonic() + limit
            marker = waiting_dir(path) / str(os.getpid())  # the dashboard reads this to show the Check is queued
            board, rank = board_module(), 0
            try:
                rank = int(board.lock_rank(os.getcwd())) if board else 0
            except (Exception, SystemExit):
                rank = 0  # the rank only orders cool-down waiters; never fail the build over it
            try:
                marker.parent.mkdir(parents=True, exist_ok=True)
                marker.write_text(f"{os.getcwd()}\n{rank}")
            except OSError:
                pass  # the marker is only a hint; never fail the build over it
            try:
                while True:  # flock has no timeout, so poll LOCK_NB
                    time.sleep(0.5)
                    try:
                        if outranked(board, marker, rank):
                            raise BlockingIOError  # cool down: a job nearer the finish line goes first
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            print(f"buildlock: timed out after {limit:g} s waiting for the build lock ({path})",
                                  file=sys.stderr)
                            return 124
            finally:
                try:
                    marker.unlink(missing_ok=True)
                except OSError:
                    pass  # the marker is only a hint; never let cleanup replace the build's exit code
        cmd = ["sh", "-c", argv[0]] if len(argv) == 1 else argv
        try:
            # the child inherits the lock fd, so the lock outlives a SIGKILLed wrapper until the build exits
            # ponytail: a build that daemonizes a long-lived grandchild keeps the lock until that grandchild exits
            return subprocess.call(cmd, pass_fds=(f.fileno(),))
        except (FileNotFoundError, PermissionError):
            return 127


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
