import importlib.util
import json
from datetime import datetime, timedelta
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo

ROUTE_PY = Path(__file__).resolve().parents[1] / 'local/route.py'
spec = importlib.util.spec_from_file_location('local_route', ROUTE_PY)
route_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_mod)
LIVE_CONFIG = route_mod.CONFIG
RESETS = 4102444800  # 2100-01-01 UTC, always in the future
NO_QUOTA = {'5h': None, 'weekly': None, '5h_resets_at': None, 'weekly_resets_at': None}


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
        env = patch.dict(os.environ, {'SCRUM_CODEX_SESSIONS': str(self.sessions),
                                      'SCRUM_CODEX_CONFIG': str(self.root / 'codex-config.toml')})
        env.start()
        self.addCleanup(env.stop)
        codex = patch.object(route_mod, '_codex_installed', lambda: True)
        codex.start()
        self.addCleanup(codex.stop)

    def job(self, job_id, lane='standard'):
        self.jobs.append({'id': job_id, 'lane': lane})
        (self.scrum / 'board.json').write_text(json.dumps({'jobs': self.jobs}))
        path = self.scrum / 'jobs' / job_id
        path.mkdir(parents=True)
        return str(path)

    def rollout(self, primary=None, secondary=None, future=RESETS):
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

    def runner(self, role, job=None, scrum=None):
        return route_mod.route(role, job, scrum)['runner']

    def test_routing_json_shape(self):
        self.assertEqual(json.loads(Path(LIVE_CONFIG).read_text()), {'thresholds': {'codex_5h': 85, 'codex_weekly': 90}})

    def test_no_local_model_left(self):
        text = ROUTE_PY.read_text()
        self.assertNotIn('oll' + 'ama', text.lower())
        for word in ('urllib.request', 'chat(', 'loaded' + '_models', 'KEEP_ALIVE', 'SCRUM_ROUTE'):
            self.assertNotIn(word, text)

    def test_codex_review_without_tomllib_falls_through(self):
        (self.root / 'codex-config.toml').write_text('openai_base_url = "http://127.0.0.1:11434/v1"\n')
        with patch.object(route_mod, 'tomllib', None):
            self.assertIsNone(route_mod._codex_local_base_url())
            self.assertEqual(route_mod.route('codex-review'),
                             {'runner': 'cloud', 'model': None, 'why': 'codex quota below thresholds'})

    def test_codex_review_config_check_edge_cases(self):
        config = self.root / 'codex-config.toml'
        low = {'runner': 'cloud', 'model': None, 'why': 'codex quota below thresholds'}
        for url in ('http://localhost:11434/v1', 'http://[::1]:11434/v1'):
            config.write_text(f'openai_base_url = "{url}"\n')
            self.assertEqual(route_mod.route('codex-review'), {
                'runner': 'skip', 'model': None, 'why': f'codex config points at a local server ({url})'}, url)
        cases = {'no key': 'model = "gpt-6.1-sol"\n',
                 'remote': 'openai_base_url = "https://api.openai.com/v1"\n',
                 'invalid toml': 'openai_base_url = "http://127.0.0.1:11434\n[[[',
                 'table only': '[profiles.x]\nopenai_base_url = "http://127.0.0.1:11434/v1"\n'}
        for name, body in cases.items():
            config.write_text(body)
            self.assertEqual(route_mod.route('codex-review'), low, name)
        config.unlink()
        self.assertEqual(route_mod.route('codex-review'), low, 'missing file')
        config.write_text('openai_base_url = "http://127.0.0.1:11434/v1"\n')
        with patch.object(route_mod, '_codex_installed', lambda: False):
            self.assertEqual(route_mod.route('codex-review'),
                             {'runner': 'skip', 'model': None, 'why': 'codex not installed'})

    def test_other_roles_cloud(self):
        fast = self.job('001-x', lane='fast')
        self.claude_limit(60, 3600)
        self.rollout(primary=99.0, secondary=99.0)
        for role, job, scrum in (('estimator', None, None), ('scrum-builder', fast, None),
                                 ('scrum-spec-writer', fast, None), ('scrum-digest-reader', None, str(self.scrum)),
                                 ('scrum-approver', fast, None), ('scrum-made-up', None, str(self.scrum))):
            result = route_mod.route(role, job, scrum)
            self.assertEqual((result['runner'], result['model']), ('cloud', None), role)

    def test_cli_prints_json(self):
        job = self.job('002-x')
        out = subprocess.run([sys.executable, str(ROUTE_PY), 'estimator', '--job', job],
                             capture_output=True, text=True, env=dict(os.environ))
        self.assertEqual(out.returncode, 0, out.stderr)
        data = json.loads(out.stdout)
        self.assertEqual(set(data), {'runner', 'model', 'why'})
        self.assertEqual((data['runner'], data['model']), ('cloud', None))
        self.assertIsInstance(data['why'], str)

    def test_codex_missing_binary_skips(self):
        with patch.object(route_mod, '_codex_installed', lambda: False):
            for quota in ((None, None), (10.0, 10.0), (99.0, 99.0)):
                self.rollout(*quota)
                self.assertEqual(route_mod.route('codex-review'),
                                 {'runner': 'skip', 'model': None, 'why': 'codex not installed'})

    def test_codex_5h_over_skip(self):
        self.rollout(primary=90.0, secondary=10.0)
        self.assertEqual(route_mod.route('codex-review'),
                         {'runner': 'skip', 'model': None, 'why': 'codex 5h at 90% (limit 85)'})

    def test_codex_weekly_over_skip(self):
        self.rollout(primary=10.0, secondary=95.0)
        self.assertEqual(route_mod.route('codex-review'),
                         {'runner': 'skip', 'model': None, 'why': 'codex weekly at 95% (limit 90)'})

    def test_codex_both_over_skip(self):
        self.rollout(primary=85.0, secondary=90.0)
        self.assertEqual(route_mod.route('codex-review'), {
            'runner': 'skip', 'model': None, 'why': 'codex 5h at 85% (limit 85) and codex weekly at 90% (limit 90)'})

    def test_codex_below_thresholds_cloud(self):
        self.rollout(primary=84.0, secondary=89.0)
        self.assertEqual(route_mod.route('codex-review'),
                         {'runner': 'cloud', 'model': None, 'why': 'codex quota below thresholds'})

    def test_codex_expired_resets_at_ignored_cloud(self):
        path = self.rollout(primary=99.0, secondary=99.0)
        past = int(time.time()) - 60
        line = {'payload': {'rate_limits': {'primary': {'used_percent': 99.0, 'resets_at': past},
                                            'secondary': {'used_percent': 99.0, 'resets_at': past}}}}
        newer = path.parent / 'rollout-2.jsonl'
        newer.write_text(json.dumps(line) + '\n')
        os.utime(path, (time.time() - 100, time.time() - 100))
        self.assertEqual(self.runner('codex-review'), 'cloud')
        self.assertEqual(route_mod.status()['codex'], NO_QUOTA)

    def test_codex_no_sessions_cloud(self):
        self.assertEqual(self.runner('codex-review'), 'cloud')
        os.environ['SCRUM_CODEX_SESSIONS'] = str(self.root / 'missing')
        self.assertEqual(route_mod.route('codex-review'),
                         {'runner': 'cloud', 'model': None, 'why': 'codex quota below thresholds'})

    def bare_rollout(self, name, mtime):
        """A rollout file with no rate_limits line, like the second file of a `codex exec review`."""
        path = self.sessions / '2026' / '10' / '14' / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({'type': 'event_msg', 'payload': {'type': 'task_complete'}}) + '\n')
        os.utime(path, (mtime, mtime))
        return path

    def test_codex_quota_skips_newest_file_without_rate_limits(self):
        now = time.time()
        older = self.rollout(primary=14, secondary=1)
        os.utime(older, (now - 1, now - 1))
        self.bare_rollout('rollout-2.jsonl', now)
        self.assertEqual(route_mod.status()['codex'],
                         {'5h': 14, 'weekly': 1, '5h_resets_at': RESETS, 'weekly_resets_at': RESETS})
        future = RESETS - 60
        line = {'type': 'event_msg', 'payload': {'type': 'token_count', 'rate_limits': {
            'primary': {'used_percent': 40, 'resets_at': future},
            'secondary': {'used_percent': 5, 'resets_at': future}}}}
        newest = older.parent / 'rollout-3.jsonl'
        newest.write_text(json.dumps(line) + '\n')
        os.utime(newest, (now + 1, now + 1))
        self.assertEqual(route_mod.status()['codex'],
                         {'5h': 40, 'weekly': 5, '5h_resets_at': RESETS - 60, 'weekly_resets_at': RESETS - 60})

    def test_codex_quota_none_when_newest_20_files_lack_rate_limits(self):
        now = time.time()
        for i in range(20):
            self.bare_rollout(f'rollout-bare-{i}.jsonl', now - i)
        self.assertEqual(route_mod.status()['codex'], NO_QUOTA)
        old = self.rollout(primary=14, secondary=1)
        os.utime(old, (now - 100, now - 100))
        self.assertEqual(route_mod.status()['codex'], NO_QUOTA)

    def test_claude_exhausted_expired_reset_ignored(self):
        self.claude_limit(3 * 3600, -2 * 3600)
        self.assertIsNone(route_mod.status(str(self.scrum))['claude_exhausted_until'])

    def test_claude_exhausted_unparseable_reset_ignored(self):
        (self.scrum / 'runs' / 'y.log').write_text("You've hit your session limit · resets soon\n")
        self.assertIsNone(route_mod.claude_exhausted_until(str(self.scrum)))

    def test_record_appends_jsonl(self):
        job = self.job('014-x')
        self.assertEqual(route_mod.main(['record', job, 'codex-review', 'cloud', 'codex', '12.5', 'ok']), 0)
        self.assertEqual(route_mod.main(['record', job, 'codex-review', 'skip', 'none', '0', 'skipped']), 0)
        lines = [json.loads(x) for x in Path(job, 'routing.log').read_text().splitlines()]
        self.assertEqual(len(lines), 2)
        first = dict(lines[0])
        ts = first.pop('ts')
        self.assertEqual(datetime.fromisoformat(ts).utcoffset(), timedelta(0))
        self.assertEqual(first, {'role': 'codex-review', 'runner': 'cloud', 'model': 'codex',
                                 'duration_s': 12.5, 'outcome': 'ok'})
        self.assertEqual(lines[1]['duration_s'], 0.0)
        self.assertEqual(lines[1]['runner'], 'skip')

    def test_record_rejects_bad_runner(self):
        job = self.job('015-x')
        for args in (['record', job, 'codex-review', 'local', 'm', '1', 'ok'],
                     ['record', job, 'codex-review', 'gpu', 'm', '1', 'ok'],
                     ['record', job, 'codex-review', 'cloud', 'm', 'fast', 'ok'],
                     ['record', str(self.root / 'nope'), 'codex-review', 'cloud', 'm', '1', 'ok']):
            out = subprocess.run([sys.executable, str(ROUTE_PY), *args], capture_output=True, text=True)
            self.assertEqual(out.returncode, 2, args)
            self.assertTrue(out.stderr.strip(), args)
        self.assertFalse(Path(job, 'routing.log').exists())

    def test_status_shape(self):
        self.rollout(primary=27.0, secondary=8.0)
        with patch.object(socket, 'create_connection', side_effect=AssertionError('network used')), \
                patch.object(socket.socket, 'connect', side_effect=AssertionError('network used')):
            self.assertEqual(route_mod.status(), {
                'codex': {'5h': 27.0, 'weekly': 8.0, '5h_resets_at': RESETS, 'weekly_resets_at': RESETS},
                'codex_limits': {'5h': 85, 'weekly': 90}, 'claude_exhausted_until': None})
            self.claude_limit(60, 3600)
            self.assertIsNotNone(route_mod.status(str(self.scrum))['claude_exhausted_until'])

    def test_codex_quota_returns_resets_at(self):
        self.rollout(primary=42.0, secondary=17.0, future=4102448400)
        self.assertEqual(route_mod.codex_quota(), {'5h': 42.0, 'weekly': 17.0,
                                                   '5h_resets_at': 4102448400, 'weekly_resets_at': 4102448400})
        line = {'payload': {'rate_limits': {'primary': {'used_percent': 3, 'resets_at': 4102444800.5},
                                            'secondary': {'used_percent': 9, 'resets_at': 'soon'}}}}
        path = self.sessions / '2026' / '10' / '14' / 'rollout-2.jsonl'
        path.write_text(json.dumps(line) + '\n')
        os.utime(path, (time.time() + 5, time.time() + 5))
        self.assertEqual(route_mod.codex_quota(), {'5h': 3, 'weekly': 9,
                                                   '5h_resets_at': 4102444800.5, 'weekly_resets_at': None})
        line = {'payload': {'rate_limits': {'primary': {'used_percent': 3, 'resets_at': 4102444800}}}}
        path.write_text(json.dumps(line) + '\n')
        self.assertEqual(route_mod.codex_quota(), {'5h': 3, 'weekly': None,
                                                   '5h_resets_at': 4102444800, 'weekly_resets_at': None})

    def test_codex_quota_expired_window_has_no_reset(self):
        past = int(time.time()) - 60
        line = {'payload': {'rate_limits': {'primary': {'used_percent': 99.0, 'resets_at': past},
                                            'secondary': {'used_percent': 20.0, 'resets_at': 4102444800}}}}
        path = self.sessions / 'rollout-9.jsonl'
        path.write_text(json.dumps(line) + '\n')
        self.assertEqual(route_mod.codex_quota(), {'5h': None, 'weekly': 20.0,
                                                   '5h_resets_at': None, 'weekly_resets_at': 4102444800})

    def test_codex_limits_from_config(self):
        config = self.root / 'routing.json'
        config.write_text(json.dumps({'thresholds': {'codex_5h': 70, 'codex_weekly': 95}}))
        with patch.object(route_mod, 'CONFIG', str(config)):
            self.assertEqual(route_mod.codex_limits(), {'5h': 70, 'weekly': 95})
        self.assertEqual(route_mod.codex_limits(), {'5h': 85, 'weekly': 90})

    def test_codex_limits_missing_or_bad_config(self):
        config = self.root / 'routing.json'
        none = {'5h': None, 'weekly': None}
        with patch.object(route_mod, 'CONFIG', str(config)):
            self.assertEqual(route_mod.codex_limits(), none, 'missing file')
            for body in ('{not json', '[]', '{"thresholds": []}', '{"thresholds": {"codex_5h": 70}}',
                         '{"other": 1}', '"text"'):
                config.write_text(body)
                self.assertEqual(route_mod.codex_limits(), none, body)


if __name__ == '__main__':
    unittest.main()
