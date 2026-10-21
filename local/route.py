#!/usr/bin/env python3
"""Pick cloud, local Ollama or skip for one scrum role, and log what ran.

  route.py <role> [--job JOB_DIR] [--scrum DIR]   -> {"runner", "model", "why"}
  route.py record JOB_DIR <role> <runner> <model> <seconds> <outcome>
  route.py status [--scrum DIR]
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from zoneinfo import ZoneInfo

CONFIG = str(Path(__file__).resolve().parent / 'routing.json')
ALWAYS_CLOUD = frozenset({
    'scrum-approver', 'scrum-review-security', 'scrum-planner', 'scrum-tracker', 'scrum-debugger',
    'scrum-bigboy-reviewer', 'scrum-triager', 'scrum-digester', 'scrum-review-ui', 'scrum-review-ux'})
RUNNERS = ('cloud', 'local', 'skip')
TIMEOUT = 2
KEEP_ALIVE = '2m'  # idle scrum models free their ~4-7 GB after 2 minutes instead of Ollama's default 5
CLAUDE_LIMIT = 'hit your session limit'
RESET = re.compile(r'resets\s+(\d{1,2})(?::(\d{2}))?\s*([ap]m)\s*\(([^)]+)\)', re.I)


def _codex_installed():
    """Cloud sessions have no codex binary; Homebrew's bin is often missing from a headless PATH."""
    return shutil.which('codex', path=os.environ.get('PATH', '') + ':/opt/homebrew/bin') is not None


def _result(runner, why, model=None):
    return {'runner': runner, 'model': model if runner == 'local' else None, 'why': why}


def _fetch_tags():
    """Return (body, error). body is the /api/tags reply when Ollama answered 200 in time."""
    base = os.environ.get('SCRUM_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    try:
        with urllib.request.urlopen(base + '/api/tags', timeout=TIMEOUT) as reply:
            if reply.status != 200:
                return None, f'Ollama down (HTTP {reply.status})'
            return reply.read(), None
    except urllib.error.HTTPError as e:
        e.close()
        return None, f'Ollama down (HTTP {e.code})'
    except TimeoutError:
        return None, 'Ollama down (timeout)'
    except (urllib.error.URLError, OSError) as e:
        if isinstance(getattr(e, 'reason', None), TimeoutError):
            return None, 'Ollama down (timeout)'
        return None, 'Ollama down (unreachable)'


def _ollama_ready(model):
    """Return (ready, cause) for running `model` on local Ollama."""
    if not model:
        return False, 'no local model configured'
    if 'cloud' in model.lower():
        return False, f'model {model} is cloud-tagged'
    body, error = _fetch_tags()
    if error:
        return False, error
    try:
        names = [m['name'] for m in json.loads(body)['models']]
    except (ValueError, KeyError, TypeError):
        return False, 'Ollama down (malformed /api/tags reply)'
    if model not in names:
        return False, f'model {model} missing from Ollama'
    size = next((m.get('size') for m in json.loads(body)['models'] if m['name'] == model), None)
    return memory_ok(model, size)


def _base(base=None):
    return (base or os.environ.get('SCRUM_OLLAMA_URL', 'http://127.0.0.1:11434')).rstrip('/')


def _get(path, base=None):
    with urllib.request.urlopen(_base(base) + path, timeout=TIMEOUT) as reply:
        return json.loads(reply.read())


def _post(path, body, timeout=TIMEOUT, base=None):
    request = urllib.request.Request(_base(base) + path, data=json.dumps(body).encode(),
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def loaded_models(base=None):
    """Names in Ollama's /api/ps, or [] when it can't be read."""
    try:
        return [m['name'] for m in _get('/api/ps', base).get('models') or []]
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, AttributeError):
        return []


def free_gb():
    """macOS's own free-memory figure (kern.memorystatus_level, % of RAM) in GB; None when unreadable."""
    try:
        level = int(subprocess.run(['sysctl', '-n', 'kern.memorystatus_level'], capture_output=True, text=True,
                                   timeout=5).stdout)
        total = int(subprocess.run(['sysctl', '-n', 'hw.memsize'], capture_output=True, text=True, timeout=5).stdout)
    except (OSError, ValueError, subprocess.SubprocessError):
        return None
    return level / 100 * total / 2**30


def memory_ok(model, size):
    """Local only when loading `model` still leaves `min_free_gb` for Trevor's apps (Illustrator etc). An already
    loaded model costs nothing more. Loaded size is ~1.4x the download size (KV cache at 32K)."""
    if model in loaded_models() or not size:
        return True, ''
    free, reserve = free_gb(), json.loads(Path(CONFIG).read_text())['thresholds'].get('min_free_gb', 3)
    need = size * 1.4 / 2**30 + reserve
    if free is not None and free < need:
        return False, f'low memory ({free:.1f} GB free, {model} needs {need:.1f} GB with the {reserve} GB reserve)'
    return True, ''


def chat(model, prompt, base=None, timeout=300, max_tokens=1024):
    """One /api/chat reply from local Ollama with thinking off. No num_ctx: the scrum- variant's own 32K applies,
    and a different value would make Ollama reload the model. Bounded tasks use this, never a Claude Code agent loop:
    a 4-7B model there fills 32K with tool output and auto-compacts until it gives up.
    Memory: other scrum- models are unloaded first (one model at a time), and the model unloads after KEEP_ALIVE idle."""
    for other in loaded_models(base):
        if other.startswith('scrum-') and other != model:
            try:
                _post('/api/generate', {'model': other, 'keep_alive': 0}, timeout=30, base=base)
            except (urllib.error.URLError, OSError, ValueError):
                pass
    # num_predict caps a runaway reply (a 7B once generated 6000+ tokens at 10 t/s); it does not reload the model
    body = {'model': model, 'stream': False, 'think': False, 'keep_alive': KEEP_ALIVE,
            'options': {'num_predict': max_tokens}, 'messages': [{'role': 'user', 'content': prompt}]}
    return _post('/api/chat', body, timeout=timeout, base=base)['message']['content']


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


def _board_job(scrum, job_id):
    try:
        jobs = json.loads(Path(scrum, 'board.json').read_text())['jobs']
        return next((j for j in jobs if j.get('id') == job_id), None)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return None


def _points(scrum, job_id):
    try:
        text = Path(scrum, 'backlog.md').read_text()
    except OSError:
        return None
    mark = re.compile(r'→ ' + re.escape(job_id) + r'(\s|$)')
    for line in text.splitlines():
        if mark.search(line):
            tag = re.search(r'\[(\d+)\]', line)
            return int(tag[1]) if tag else None
    return None


def _eligible(role, job, scrum, job_id, cfg):
    if role == 'scrum-builder':
        return bool(job) and job.get('lane') == 'fast'
    if role == 'scrum-spec-writer':
        points = _points(scrum, job_id) if job_id else None
        return points is not None and points <= cfg['thresholds']['spec_writer_max_points']
    return True


def _route_codex(model, thresholds, override):
    quota = codex_quota()
    over = [f'codex {name} at {quota[name]:g}% (limit {thresholds[key]})'
            for name, key in (('5h', 'codex_5h'), ('weekly', 'codex_weekly'))
            if quota[name] is not None and quota[name] >= thresholds[key]]
    if not over and override != 'local':
        return _result('cloud', 'codex quota below thresholds')
    reason = ' and '.join(over) or 'SCRUM_ROUTE=local'
    ready, cause = _ollama_ready(model)
    if ready:
        return _result('local', reason, model)
    if over:
        return _result('skip', f'{reason} and {cause}')
    return _result('cloud', f'{reason}, but {cause}')


def route(role, job_dir=None, scrum_dir=None):
    cfg = json.loads(Path(CONFIG).read_text())
    trust = cfg['roles'].get(role)
    override = os.environ.get('SCRUM_ROUTE', '')
    if role == 'codex-review' and not _codex_installed():
        return _result('skip', 'codex not installed')
    if role in ALWAYS_CLOUD or trust is None:
        return _result('cloud', f'{role} always runs on cloud')
    if override == 'cloud':
        return _result('cloud', 'SCRUM_ROUTE=cloud')
    if trust not in ('approved', 'trial'):
        return _result('cloud', f'{role} trust is {trust}')
    model = cfg['models'].get(role)
    if role == 'codex-review':
        return _route_codex(model, cfg['thresholds'], override)
    job_path = Path(job_dir).resolve() if job_dir else None
    scrum = job_path.parent.parent if job_path else scrum_dir
    job_id = job_path.name if job_path else None
    job = _board_job(scrum, job_id) if job_path else None
    eligible = _eligible(role, job, scrum, job_id, cfg)
    until = None if override == 'local' else claude_exhausted_until(scrum)
    if override == 'local':
        want, why = eligible, 'SCRUM_ROUTE=local'
    elif until:  # Claude is out: waive the lane/points rule and the trial condition (spec 6 test name)
        want, why = True, f'claude session limit until {until.isoformat()}'
    elif trust == 'approved':
        want, why = eligible, 'approved and eligible'
    else:
        child = bool(job and job.get('parent'))
        want, why = eligible or child, 'trial: BigBoy child' if child else 'trial: eligible'
    if not want:
        return _result('cloud', f'{role} not eligible for local ({trust})')
    ready, cause = _ollama_ready(model)
    if ready:
        return _result('local', why, model)
    return _result('cloud', f'{why}, but {cause}')


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
    return {'codex': codex_quota(), 'ollama': 'up' if _fetch_tags()[0] is not None else 'down',
            'claude_exhausted_until': until.isoformat() if until else None}


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
