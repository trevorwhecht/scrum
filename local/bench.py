#!/usr/bin/env python3
"""Benchmark local Ollama models on the three bounded tasks local routing is trusted with.

  python3 local/bench.py [--model M ...] [--runs N] [--task estimate|summary|edit]

One request at a time. Prints one JSON line per run, then a passed/total summary per model and task.
Exit 0 when every run passed, 1 when any failed, 2 when Ollama or a model is not ready.
"""
import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'skills' / 'trevskills-scrum'))
import route  # noqa: E402
from serve import ESTIMATE_PROMPT  # noqa: E402

POINTS = (1, 2, 3, 5, 8, 13)
TASKS = ('estimate', 'summary', 'edit')
ITEM = 'Add a --json flag to board.py status that prints the board as one JSON object instead of a table.'
EXCERPTS = {
    'jobs/a/feature.md': 'The dashboard shows a Resume button on a job card when the watchdog marks the job stalled. '
                         'Pressing it restarts the last agent with the same prompt.',
    'jobs/b/spec.md': 'board.py refuses stage=done unless the job PR is merged. '
                      'A refused move prints the PR state and exits 1.',
}
SUMMARY_PROMPT = ('Summarise the two job files below in 2 to 5 bullets. Each bullet starts with "- " and ends with the '
                  'bracketed path of the file it came from, e.g. [jobs/a/feature.md]. Use only facts in the files. '
                  'Reply with the bullets only.\n\n'
                  + '\n\n'.join(f'{path}:\n{text}' for path, text in EXCERPTS.items()))
CALC = 'def add(a, b):\n    return a - b\n'
TEST_CALC = 'import unittest\nfrom calc import add\n\n\nclass T(unittest.TestCase):\n' \
            '    def test_add(self):\n        self.assertEqual(add(2, 3), 5)\n'
EDIT_PROMPT = ('calc.py has a bug; test_calc.py asserts add(2, 3) == 5.\n\ncalc.py:\n' + CALC + '\ntest_calc.py:\n'
               + TEST_CALC + '\nFix calc.py. Reply with ONLY one JSON object: '
               '{"path": "calc.py", "content": "<full new file>"}')


def find_json(reply):
    """First JSON object in the reply (models often wrap it in prose or a code fence), or None."""
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{', reply):
        try:
            value, _ = decoder.raw_decode(reply, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def check_estimate(reply):
    data = find_json(reply)
    if data is None:
        return False, 'no JSON object'
    if data.get('points') not in POINTS or isinstance(data.get('points'), bool):
        return False, f'points {data.get("points")!r} not one of {POINTS}'
    if not isinstance(data.get('why'), str) or not data['why'].strip():
        return False, 'why is empty'
    return True, ''


def check_summary(reply, paths):
    bullets = [line for line in reply.splitlines() if line.startswith('- ')]
    if not 2 <= len(bullets) <= 5:
        return False, f'{len(bullets)} bullets, want 2-5'
    for bullet in bullets:
        cited = re.findall(r'\[([^\]]+)\]', bullet)
        if not cited:
            return False, f'uncited bullet: {bullet[:60]}'
        unknown = [c for c in cited if c not in paths]
        if unknown:
            return False, f'unknown path {unknown[0]}'
    return True, ''


def setup_edit(workdir):
    (workdir / 'calc.py').write_text(CALC)
    (workdir / 'test_calc.py').write_text(TEST_CALC)


def check_edit(reply, workdir):
    data = find_json(reply)
    if data is None:
        return False, 'no JSON object'
    if data.get('path') != 'calc.py':
        return False, f'path {data.get("path")!r} is not calc.py'
    if not isinstance(data.get('content'), str):
        return False, 'content is not a string'
    test = workdir / 'test_calc.py'
    before = test.read_bytes()
    (workdir / 'calc.py').write_text(data['content'])
    if test.read_bytes() != before:
        return False, 'test_calc.py changed'
    result = subprocess.run([sys.executable, '-m', 'unittest', 'test_calc'], cwd=workdir,
                            capture_output=True, text=True, timeout=60)
    if not test.is_file() or test.read_bytes() != before:
        return False, 'test_calc.py changed'
    return (True, '') if result.returncode == 0 else (False, 'test_calc failed')


def call(base, path, body=None, timeout=600):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base + path, data=data, headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as reply:
        return json.loads(reply.read())


def chat(base, model, prompt):
    return route.chat(model, prompt, base)


def ps_entry(base, model):
    try:
        models = call(base, '/api/ps', timeout=10).get('models', [])
    except (urllib.error.URLError, OSError, ValueError):
        return None
    for m in models:
        if model in (m.get('name'), m.get('model')):
            return {k: m.get(k) for k in ('size', 'size_vram', 'context_length')}
    return None


def run_task(base, model, task):
    """Return (pass, why) for one run of one task."""
    try:
        if task == 'estimate':
            return check_estimate(chat(base, model, ESTIMATE_PROMPT.format(text=ITEM)))
        if task == 'summary':
            return check_summary(chat(base, model, SUMMARY_PROMPT), tuple(EXCERPTS))
        with tempfile.TemporaryDirectory() as tmp:
            setup_edit(Path(tmp))
            return check_edit(chat(base, model, EDIT_PROMPT), Path(tmp))
    except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError, subprocess.TimeoutExpired) as e:
        return False, f'request failed: {e}'


def default_models():
    return list(dict.fromkeys(json.loads(Path(route.CONFIG).read_text())['models'].values()))


def main(argv=None):
    parser = argparse.ArgumentParser(description='Benchmark local Ollama models on the three routed tasks.')
    parser.add_argument('--model', action='append', help='model to benchmark (repeatable); default: routing.json models')
    parser.add_argument('--runs', type=int, default=3)
    parser.add_argument('--task', choices=TASKS, help='one task; default: all three')
    args = parser.parse_args(argv)
    models = list(dict.fromkeys(args.model or default_models()))
    tasks = [args.task] if args.task else list(TASKS)
    base = os.environ.get('SCRUM_OLLAMA_URL', 'http://127.0.0.1:11434').rstrip('/')
    for model in models:
        ready, cause = route._ollama_ready(model)
        if not ready:
            print(f'FAIL: {cause}', file=sys.stderr)
            return 2
    tally, failed = {}, False
    for model in models:  # strictly serial: one request in flight at a time
        for task in tasks:
            for run in range(1, args.runs + 1):
                start = time.monotonic()
                ok, why = run_task(base, model, task)
                line = {'model': model, 'task': task, 'run': run, 'pass': ok, 'why': why,
                        'duration_s': round(time.monotonic() - start, 1), 'ps': ps_entry(base, model)}
                print(json.dumps(line), flush=True)
                passed, total = tally.get((model, task), (0, 0))
                tally[(model, task)] = (passed + ok, total + 1)
                failed = failed or not ok
    for (model, task), (passed, total) in tally.items():
        print(f'{model} {task} {passed}/{total}')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
