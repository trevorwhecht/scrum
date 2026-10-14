import importlib.util
import json
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROUTE_PY = Path(__file__).resolve().parents[1] / 'local/route.py'
spec = importlib.util.spec_from_file_location('local_route', ROUTE_PY)
route_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_mod)

ALL_MODELS = ['qwen3.5:4b', 'qwen2.5-coder:7b']


class FakeOllama(BaseHTTPRequestHandler):
    status = 200
    body = b''
    delay = 0

    def do_GET(self):
        time.sleep(type(self).delay)
        self.send_response(type(self).status)
        self.end_headers()
        self.wfile.write(type(self).body)

    def log_message(self, *args):
        pass


def tags(*names):
    return json.dumps({'models': [{'name': n} for n in names]}).encode()


class RouteTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.scrum = self.root / 'scrum'
        (self.scrum / 'runs').mkdir(parents=True)
        self.sessions = self.root / 'sessions'
        self.sessions.mkdir()
        self.jobs = []
        self.backlog = ''
        handler = type('Handler', (FakeOllama,), {'body': tags(*ALL_MODELS)})
        self.handler = handler
        server = HTTPServer(('127.0.0.1', 0), handler)
        threading.Thread(target=server.serve_forever, args=(0.05,), daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.up_url = 'http://127.0.0.1:%d' % server.server_address[1]
        env = patch.dict(os.environ, {'SCRUM_OLLAMA_URL': self.up_url,
                                      'SCRUM_CODEX_SESSIONS': str(self.sessions)})
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop('SCRUM_ROUTE', None)

    def job(self, job_id, lane='standard', parent=None, points=None):
        self.jobs.append({'id': job_id, 'lane': lane, 'parent': parent})
        (self.scrum / 'board.json').write_text(json.dumps({'jobs': self.jobs}))
        tag = f'[{points}] ' if points is not None else ''
        self.backlog += f'- [ ] {tag}Do the thing → {job_id}\n'
        (self.scrum / 'backlog.md').write_text(self.backlog)
        path = self.scrum / 'jobs' / job_id
        path.mkdir(parents=True)
        return str(path)

    def ollama_down(self):
        sock = socket.socket()
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
        sock.close()
        os.environ['SCRUM_OLLAMA_URL'] = 'http://127.0.0.1:%d' % port

    def rollout(self, primary=None, secondary=None):
        future = int(time.time()) + 3600
        limits = {'primary': {'used_percent': primary, 'window_minutes': 300, 'resets_at': future},
                  'secondary': {'used_percent': secondary, 'window_minutes': 10080, 'resets_at': future}}
        folder = self.sessions / '2026' / '10' / '14'
        folder.mkdir(parents=True, exist_ok=True)
        lines = [{'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': limits}},
                 {'type': 'event_msg', 'payload': {'type': 'agent_message', 'message': 'hi'}}]
        (folder / 'rollout-1.jsonl').write_text('\n'.join(json.dumps(x) for x in lines) + '\n')
        return folder / 'rollout-1.jsonl'

    def claude_limit(self, mtime_ago, reset_offset):
        """Write a session-limit log changed `mtime_ago` seconds ago whose printed
        reset is the LA wall-clock time `reset_offset` seconds from now."""
        zone = ZoneInfo('America/Los_Angeles')
        at = datetime.now(zone) + timedelta(seconds=reset_offset)
        clock = f"{at.hour % 12 or 12}:{at.minute:02d}{'pm' if at.hour >= 12 else 'am'}"
        log = self.scrum / 'runs' / 'x.log'
        log.write_text(f"working...\nYou've hit your session limit · resets {clock} (America/Los_Angeles)\n\n")
        stamp = time.time() - mtime_ago
        os.utime(log, (stamp, stamp))

    def config(self, **roles):
        data = json.loads(Path(route_mod.CONFIG).read_text())
        data['roles'].update(roles)
        path = self.root / 'routing.json'
        path.write_text(json.dumps(data))
        p = patch.object(route_mod, 'CONFIG', str(path))
        p.start()
        self.addCleanup(p.stop)

    def runner(self, role, job=None, scrum=None):
        return route_mod.route(role, job, scrum)['runner']

    # 1
    def test_routing_json_shape(self):
        data = json.loads((ROUTE_PY.parent / 'routing.json').read_text())
        self.assertEqual(set(data), {'roles', 'models', 'thresholds'})
        self.assertEqual(data['roles'], {'estimator': 'approved', 'scrum-digest-reader': 'approved',
                                         'codex-review': 'approved', 'scrum-spec-writer': 'trial',
                                         'scrum-builder': 'trial'})
        self.assertEqual(data['models'], {'estimator': 'qwen3.5:4b', 'scrum-digest-reader': 'qwen3.5:4b',
                                          'scrum-spec-writer': 'qwen2.5-coder:7b',
                                          'scrum-builder': 'qwen2.5-coder:7b', 'codex-review': 'qwen2.5-coder:7b'})
        self.assertEqual(data['thresholds'], {'codex_5h': 85, 'codex_weekly': 90, 'spec_writer_max_points': 2})

    # 2
    def test_always_cloud_roles(self):
        job = self.job('001-x', lane='fast')
        self.claude_limit(60, 3600)
        os.environ['SCRUM_ROUTE'] = 'local'
        for role in ('scrum-approver', 'scrum-review-security', 'scrum-planner', 'scrum-tracker',
                     'scrum-debugger', 'scrum-bigboy-reviewer', 'scrum-triager', 'scrum-digester',
                     'scrum-review-ui', 'scrum-review-ux'):
            result = route_mod.route(role, job)
            self.assertEqual((result['runner'], result['model']), ('cloud', None), role)

    def test_unknown_role_cloud(self):
        os.environ['SCRUM_ROUTE'] = 'local'
        result = route_mod.route('scrum-made-up', None, str(self.scrum))
        self.assertEqual(result['runner'], 'cloud')
        self.assertIsNone(result['model'])

    def test_cli_prints_json(self):
        job = self.job('002-x')
        out = subprocess.run([sys.executable, str(ROUTE_PY), 'estimator', '--job', job],
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual(set(data), {'runner', 'model', 'why'})
        self.assertEqual(data['runner'], 'local')
        self.assertEqual(data['model'], 'qwen3.5:4b')
        self.assertIsInstance(data['why'], str)

    # 3
    def test_trust_off_cloud(self):
        self.config(estimator='off')
        self.assertEqual(self.runner('estimator'), 'cloud')

    def test_builder_fast_lane_local(self):
        result = route_mod.route('scrum-builder', self.job('003-x', lane='fast'))
        self.assertEqual((result['runner'], result['model']), ('local', 'qwen2.5-coder:7b'))

    def test_builder_standard_lane_cloud(self):
        self.assertEqual(self.runner('scrum-builder', self.job('004-x', lane='standard')), 'cloud')

    def test_builder_bigboy_child_trial_local(self):
        self.assertEqual(self.runner('scrum-builder', self.job('005-x', parent='084-parent')), 'local')

    def test_builder_no_job_cloud(self):
        self.assertEqual(self.runner('scrum-builder'), 'cloud')

    def test_spec_writer_points_le_threshold_local(self):
        self.job('006-a', points=5)
        self.assertEqual(self.runner('scrum-spec-writer', self.job('006-x', points=2)), 'local')
        self.assertEqual(self.runner('scrum-spec-writer', self.job('006-y', points=3)), 'cloud')

    def test_spec_writer_unpointed_cloud(self):
        self.assertEqual(self.runner('scrum-spec-writer', self.job('007-x')), 'cloud')
        self.assertEqual(self.runner('scrum-spec-writer'), 'cloud')

    def test_approved_estimator_local(self):
        result = route_mod.route('estimator')
        self.assertEqual((result['runner'], result['model']), ('local', 'qwen3.5:4b'))

    # 4
    def test_ollama_down_cloud(self):
        self.ollama_down()
        result = route_mod.route('estimator')
        self.assertEqual(result['runner'], 'cloud')
        self.assertIn('unreachable', result['why'])

    def test_ollama_bad_replies_cloud(self):
        self.handler.status = 500
        self.assertIn('HTTP 500', route_mod.route('estimator')['why'])
        self.handler.status = 200
        self.handler.body = b'not json'
        result = route_mod.route('estimator')
        self.assertEqual(result['runner'], 'cloud')
        self.assertIn('malformed', result['why'])

    def test_ollama_timeout_cloud(self):
        self.handler.delay = 0.5
        with patch.object(route_mod, 'TIMEOUT', 0.1):
            result = route_mod.route('estimator')
        self.assertEqual(result['runner'], 'cloud')
        self.assertIn('timeout', result['why'])

    def test_model_missing_from_tags_cloud(self):
        self.handler.body = tags('qwen2.5-coder:7b')
        result = route_mod.route('estimator')
        self.assertEqual(result['runner'], 'cloud')
        self.assertIn('qwen3.5:4b', result['why'])
        self.assertIn('missing', result['why'])

    def test_cloud_tagged_model_refused(self):
        data = json.loads(Path(route_mod.CONFIG).read_text())
        data['models']['estimator'] = 'gpt-oss:120b-CLOUD'
        path = self.root / 'cloudy.json'
        path.write_text(json.dumps(data))
        self.handler.body = tags('gpt-oss:120b-CLOUD')
        with patch.object(route_mod, 'CONFIG', str(path)):
            result = route_mod.route('estimator')
            self.rollout(primary=99)
            data['models']['codex-review'] = 'x:cloud'
            path.write_text(json.dumps(data))
            codex = route_mod.route('codex-review')
        self.assertEqual((result['runner'], result['model']), ('cloud', None))
        self.assertIn('cloud-tagged', result['why'])
        self.assertEqual(codex['runner'], 'skip')
        self.assertIn('cloud-tagged', codex['why'])

    # 5
    def test_codex_5h_90_local(self):
        self.rollout(primary=90.0, secondary=10.0)
        result = route_mod.route('codex-review')
        self.assertEqual((result['runner'], result['model']), ('local', 'qwen2.5-coder:7b'))

    def test_codex_weekly_95_local(self):
        self.rollout(primary=10.0, secondary=95.0)
        self.assertEqual(self.runner('codex-review'), 'local')

    def test_codex_below_thresholds_cloud(self):
        self.rollout(primary=84.0, secondary=89.0)
        self.assertEqual(self.runner('codex-review'), 'cloud')

    def test_codex_over_and_ollama_down_skip(self):
        self.rollout(primary=90.0, secondary=10.0)
        self.ollama_down()
        self.assertEqual(route_mod.route('codex-review'), {
            'runner': 'skip', 'model': None,
            'why': 'codex 5h at 90% (limit 85) and Ollama down (unreachable)'})

    def test_codex_expired_resets_at_ignored_cloud(self):
        path = self.rollout(primary=99.0, secondary=99.0)
        past = int(time.time()) - 60
        line = {'payload': {'rate_limits': {'primary': {'used_percent': 99.0, 'resets_at': past},
                                            'secondary': {'used_percent': 99.0, 'resets_at': past}}}}
        newer = path.parent / 'rollout-2.jsonl'
        newer.write_text(json.dumps(line) + '\n')
        os.utime(path, (time.time() - 100, time.time() - 100))
        self.assertEqual(self.runner('codex-review'), 'cloud')
        self.assertEqual(route_mod.status()['codex'], {'5h': None, 'weekly': None})

    def test_codex_no_sessions_cloud(self):
        self.assertEqual(self.runner('codex-review'), 'cloud')
        os.environ['SCRUM_CODEX_SESSIONS'] = str(self.root / 'missing')
        self.assertEqual(self.runner('codex-review'), 'cloud')

    # 6
    def test_claude_exhausted_trial_builder_standard_lane_local(self):
        job = self.job('008-x', lane='standard')
        self.claude_limit(60, 3600)
        result = route_mod.route('scrum-builder', job)
        self.assertEqual(result['runner'], 'local')
        self.assertIn('claude session limit until ', result['why'])
        self.assertEqual(self.runner('scrum-spec-writer', job), 'local')
        self.assertEqual(self.runner('codex-review', job), 'cloud')

    def test_claude_exhausted_expired_reset_ignored(self):
        job = self.job('009-x', lane='standard')
        self.claude_limit(3 * 3600, -2 * 3600)
        self.assertEqual(self.runner('scrum-builder', job), 'cloud')
        self.assertIsNone(route_mod.status(str(self.scrum))['claude_exhausted_until'])

    def test_claude_exhausted_unparseable_reset_ignored(self):
        job = self.job('010-x', lane='standard')
        (self.scrum / 'runs' / 'y.log').write_text("You've hit your session limit · resets soon\n")
        self.assertEqual(self.runner('scrum-builder', job), 'cloud')

    def test_claude_exhausted_off_role_stays_cloud(self):
        self.config(**{'scrum-builder': 'off'})
        job = self.job('011-x', lane='fast')
        self.claude_limit(60, 3600)
        self.assertEqual(self.runner('scrum-builder', job), 'cloud')

    # 7
    def test_override_cloud(self):
        os.environ['SCRUM_ROUTE'] = 'cloud'
        self.rollout(primary=99.0)
        self.assertEqual(self.runner('codex-review'), 'cloud')
        self.assertEqual(self.runner('estimator'), 'cloud')
        self.assertEqual(self.runner('scrum-builder', self.job('012-x', lane='fast')), 'cloud')

    def test_override_local_trial_ineligible_still_needs_eligibility(self):
        os.environ['SCRUM_ROUTE'] = 'local'
        self.assertEqual(self.runner('scrum-builder', self.job('013-x', lane='standard')), 'cloud')
        self.assertEqual(self.runner('scrum-builder', self.job('013-y', lane='fast')), 'local')
        self.assertEqual(self.runner('codex-review'), 'local')

    def test_override_local_ollama_down_cloud(self):
        os.environ['SCRUM_ROUTE'] = 'local'
        self.ollama_down()
        self.assertEqual(self.runner('estimator'), 'cloud')
        self.assertEqual(self.runner('codex-review'), 'cloud')
        self.rollout(primary=99.0)
        self.assertEqual(self.runner('codex-review'), 'skip')

    # 8
    def test_record_appends_jsonl(self):
        job = self.job('014-x')
        self.assertEqual(route_mod.main(['record', job, 'codex-review', 'local', 'qwen2.5-coder:7b', '12.5', 'ok']), 0)
        self.assertEqual(route_mod.main(['record', job, 'codex-review', 'skip', 'none', '0', 'skipped']), 0)
        lines = [json.loads(x) for x in Path(job, 'routing.log').read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        first = dict(lines[0])
        ts = first.pop('ts')
        self.assertEqual(datetime.fromisoformat(ts).utcoffset(), timedelta(0))
        self.assertEqual(first, {'role': 'codex-review', 'runner': 'local', 'model': 'qwen2.5-coder:7b',
                                 'duration_s': 12.5, 'outcome': 'ok'})
        self.assertEqual(lines[1]['duration_s'], 0.0)
        self.assertEqual(lines[1]['runner'], 'skip')

    def test_record_rejects_bad_runner(self):
        job = self.job('015-x')
        for args in (['record', job, 'codex-review', 'gpu', 'm', '1', 'ok'],
                     ['record', job, 'codex-review', 'cloud', 'm', 'fast', 'ok'],
                     ['record', str(self.root / 'nope'), 'codex-review', 'cloud', 'm', '1', 'ok']):
            out = subprocess.run([sys.executable, str(ROUTE_PY), *args], capture_output=True, text=True)
            self.assertEqual(out.returncode, 2, args)
            self.assertTrue(out.stderr.strip(), args)
        self.assertFalse(Path(job, 'routing.log').exists())

    # 9
    def test_status_shape(self):
        self.rollout(primary=27.0, secondary=8.0)
        self.handler.body = tags()
        self.assertEqual(route_mod.status(), {'codex': {'5h': 27.0, 'weekly': 8.0}, 'ollama': 'up',
                                              'claude_exhausted_until': None})
        self.claude_limit(60, 3600)
        self.assertIsNotNone(route_mod.status(str(self.scrum))['claude_exhausted_until'])
        self.ollama_down()
        self.assertEqual(route_mod.status()['ollama'], 'down')


if __name__ == '__main__':
    unittest.main()
