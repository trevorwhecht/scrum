#!/usr/bin/env python3
"""Background Ollama worker: free local work for every dashboard project, never paid usage.

  worker.py            one tick (launchd runs it every 10 minutes; see local/worker-install.sh)
  worker.py --status   print what a tick would do now, and do nothing

A tick does nothing unless the router would run the task locally (Ollama up, trust on, and the memory gate:
the model plus `min_free_gb` must fit in free memory). While Trevor is active it does one task; once the Mac
has been idle IDLE_AFTER seconds it keeps going for up to IDLE_BUDGET seconds. Tasks, in order:
  1. estimate unpointed open backlog items (estimator role, local only);
  2. write insight notes for done jobs before the digest trims them (insights role).
One line per tick goes to ~/.claude/trevskills-scrum/worker.log.
"""
from datetime import datetime
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'skills' / 'trevskills-scrum'))
import board  # noqa: E402
import insights  # noqa: E402
import route  # noqa: E402

STATE = Path(os.environ.get('SCRUM_WORKER_DIR') or Path.home() / '.claude' / 'trevskills-scrum')
IDLE_AFTER, IDLE_BUDGET = 600, 540  # idle 10 min -> work up to 9 min, so ticks 10 min apart never overlap


def idle_seconds():
    """Seconds since the last keyboard/mouse input (macOS HIDIdleTime); 0 when unreadable (treated as active)."""
    try:
        out = subprocess.run(['ioreg', '-c', 'IOHIDSystem'], capture_output=True, text=True, timeout=10).stdout
        return int(next(line for line in out.splitlines() if 'HIDIdleTime' in line).split('=')[-1]) // 10**9
    except (OSError, ValueError, StopIteration, subprocess.SubprocessError):
        return 0


def tasks():
    """(role, project, run) for every task waiting, in priority order. Lazy: each check reads files only."""
    import serve  # noqa: E402  (heavy; only a tick that has work imports it)
    for name, repo in board.projects().items():
        root = repo / 'scrum'
        for item in board.backlog_items(root):
            if not item['done'] and item['points'] is None:
                yield 'estimator', name, lambda root=root, text=item['text']: serve.estimate(root, text, local_only=True)
    for name, repo in board.projects().items():
        root = repo / 'scrum'
        for job in insights.pending(root):
            yield 'insights', name, lambda root=root, job=job: insights.write(root, job, route_model('insights'))


def route_model(role):
    pick = route.route(role)
    return pick['model'] if pick['runner'] == 'local' else None


def tick(dry=False):
    STATE.mkdir(parents=True, exist_ok=True)
    with open(STATE / 'worker.lock', 'w') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            return 'skip: another tick is running'
        idle = idle_seconds()
        deadline = time.monotonic() + (IDLE_BUDGET if idle >= IDLE_AFTER else 0)
        done, stop = [], ''
        for role, project, run in tasks():
            pick = route.route(role)
            if pick['runner'] != 'local':
                stop = f'{role}: {pick["why"]}'
                break
            busy = [m for m in route.loaded_models() if m.startswith('scrum-') and m != pick['model']]
            if busy:  # a scrum job (or another run) is using local: yield instead of evicting its model
                stop = f'{busy[0]} in use'
                break
            if dry:
                return f'would run {role} for {project} (idle {idle}s)'
            run()
            done.append(f'{role}@{project}')
            if time.monotonic() >= deadline:
                break
        if dry:
            return f'nothing to do ({stop or "no tasks"})'
        return f'idle {idle}s · ran {len(done)}: {", ".join(done) or "-"}' + (f' · stopped: {stop}' if stop else '')


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    line = tick(dry=argv[:1] == ['--status'])
    print(line)
    if argv[:1] != ['--status']:
        with open(STATE / 'worker.log', 'a') as log:
            log.write(f'{datetime.now().isoformat(timespec="seconds")} {line}\n')


if __name__ == '__main__':
    main()
