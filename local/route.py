#!/usr/bin/env python3
"""Decide whether the code reviewer's Codex step runs on cloud or is skipped, and log what ran.

codex-review answers skip when the codex binary is missing or either Codex quota window (5h, weekly) is at or past
its threshold in routing.json, and cloud otherwise. Every other role answers cloud.

  route.py <role> [--job JOB_DIR] [--scrum DIR]   -> {"runner", "model", "why"}
  route.py record JOB_DIR <role> <runner> <model> <seconds> <outcome>   appends one JSON line to JOB_DIR/routing.log
  route.py status [--scrum DIR]   -> {"codex": {"5h", "weekly"}, "claude_exhausted_until"}
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import sys
import time
from zoneinfo import ZoneInfo

CONFIG = str(Path(__file__).resolve().parent / 'routing.json')
RUNNERS = ('cloud', 'skip')
CLAUDE_LIMIT = 'hit your session limit'
RESET = re.compile(r'resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*\(([^)]+)\)', re.I)


def _codex_installed():
    """Cloud sessions have no codex binary; Homebrew's bin is often missing from a headless PATH."""
    return shutil.which('codex', path=os.environ.get('PATH', '') + ':/opt/homebrew/bin') is not None


def codex_quota():
    """Used percent of the 5h and weekly Codex windows, from the newest rollout file."""
    quota = {'5h': None, 'weekly': None}
    root = Path(os.environ.get('SCRUM_CODEX_SESSIONS') or Path.home() / '.codex' / 'sessions')
    files = list(root.glob('**/rollout-*.jsonl'))
    if not files:
        return quota
    newest = max(files, key=lambda p: p.stat().st_mtime)
    limits = None
    for line in reversed(newest.read_text(errors='replace').splitlines()):
        if 'rate_limits' not in line:
            continue
        try:
            limits = json.loads(line)['payload']['rate_limits']
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(limits, dict):
            break
    if not isinstance(limits, dict):
        return quota
    for key, window in (('5h', 'primary'), ('weekly', 'secondary')):
        data = limits.get(window)
        if not isinstance(data, dict):
            continue
        resets = data.get('resets_at')
        if isinstance(resets, (int, float)) and resets < time.time():
            continue
        if isinstance(data.get('used_percent'), (int, float)):
            quota[key] = data['used_percent']
    return quota


def claude_exhausted_until(scrum):
    """The latest future reset printed by a Claude session-limit line in scrum/runs, or None."""
    if not scrum:
        return None
    now, best = time.time(), None
    for log in Path(scrum, 'runs').glob('*.log'):
        stat = log.stat()
        if now - stat.st_mtime > 86400:
            continue
        with open(log, 'rb') as f:
            f.seek(max(0, stat.st_size - 1024))
            lines = [x for x in f.read().decode(errors='replace').splitlines() if x.strip()]
        if not lines or CLAUDE_LIMIT not in lines[-1]:
            continue
        found = RESET.search(lines[-1])
        if not found or not 1 <= int(found[1]) <= 12 or int(found[2] or 0) > 59:
            continue
        try:
            zone = ZoneInfo(found[4].strip())
        except (KeyError, ValueError):  # ZoneInfoNotFoundError is a KeyError
            continue
        hour = int(found[1]) % 12 + (12 if found[3].lower() == 'pm' else 0)
        start = datetime.fromtimestamp(stat.st_mtime, zone)
        reset = start.replace(hour=hour, minute=int(found[2] or 0), second=0, microsecond=0)
        if reset <= start:  # wall-clock next day in that zone
            reset = (start + timedelta(days=1)).replace(hour=hour, minute=int(found[2] or 0), second=0,
                                                        microsecond=0)
        if reset.timestamp() > now and (best is None or reset > best):
            best = reset
    return best


def _route_codex(thresholds):
    quota = codex_quota()
    over = [f'codex {name} at {quota[name]:g}% (limit {thresholds[key]})'
            for name, key in (('5h', 'codex_5h'), ('weekly', 'codex_weekly'))
            if quota[name] is not None and quota[name] >= thresholds[key]]
    if over:
        return {'runner': 'skip', 'model': None, 'why': ' and '.join(over)}
    return {'runner': 'cloud', 'model': None, 'why': 'codex quota below thresholds'}


def route(role, job_dir=None, scrum_dir=None):
    """job_dir and scrum_dir are accepted and ignored so existing call sites keep working."""
    if role != 'codex-review':
        return {'runner': 'cloud', 'model': None, 'why': f'{role} always runs on cloud'}
    if not _codex_installed():
        return {'runner': 'skip', 'model': None, 'why': 'codex not installed'}
    return _route_codex(json.loads(Path(CONFIG).read_text())['thresholds'])


def record(job_dir, role, runner, model, seconds, outcome):
    if runner not in RUNNERS:
        raise ValueError(f'runner must be one of {"|".join(RUNNERS)}, got {runner!r}')
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        raise ValueError(f'seconds must be a number, got {seconds!r}') from None
    if not Path(job_dir).is_dir():
        raise ValueError(f'no such JOB_DIR: {job_dir}')
    line = {'ts': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'role': role, 'runner': runner,
            'model': model, 'duration_s': seconds, 'outcome': outcome}
    with open(Path(job_dir) / 'routing.log', 'a') as f:
        f.write(json.dumps(line) + '\n')


def status(scrum_dir=None):
    until = claude_exhausted_until(scrum_dir)
    return {'codex': codex_quota(), 'claude_exhausted_until': until.isoformat() if until else None}


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ['record']:
        if len(argv) != 7:
            print('Usage: route.py record JOB_DIR <role> <runner> <model> <seconds> <outcome>', file=sys.stderr)
            return 2
        try:
            record(*argv[1:])
        except ValueError as e:
            print(f'route.py record: {e}', file=sys.stderr)
            return 2
        return 0
    parser = argparse.ArgumentParser(prog='route.py')
    parser.add_argument('role')
    parser.add_argument('--job')
    parser.add_argument('--scrum')
    args = parser.parse_args(argv)
    if args.role == 'status':
        print(json.dumps(status(args.scrum)))
    else:
        print(json.dumps(route(args.role, args.job, args.scrum)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
