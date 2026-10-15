from contextlib import redirect_stderr, redirect_stdout
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('local_bench', ROOT / 'local/bench.py')
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)

FIX = json.dumps({'path': 'calc.py', 'content': 'def add(a, b):\n    return a + b\n'})
GOOD = {
    'estimating': '```json\n{"points": 3, "why": "a few files"}\n```',
    'Summarise': '- Resume restarts the last agent [jobs/a/feature.md]\n- done needs a merged PR [jobs/b/spec.md]',
    'calc.py has a bug': FIX,
}


class OllamaStub(BaseHTTPRequestHandler):
    """Answers /api/tags, /api/ps and /api/chat from class-level fixtures; records every request."""
    tags = {'models': [{'name': 'm1'}, {'name': 'm2'}]}
    ps = {'models': []}
    replies = GOOD
    requests = []

    def log_message(self, *args):
        pass

    def reply(self, body):
        data = json.dumps(body).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        OllamaStub.requests.append(('GET', self.path, None))
        self.reply(OllamaStub.tags if self.path == '/api/tags' else OllamaStub.ps)

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        OllamaStub.requests.append(('POST', self.path, body))
        prompt = body['messages'][0]['content']
        content = next(text for key, text in OllamaStub.replies.items() if key in prompt)
        self.reply({'message': {'role': 'assistant', 'content': content}, 'done': True})


class BenchServerTests(unittest.TestCase):
    def setUp(self):
        OllamaStub.requests, OllamaStub.replies, OllamaStub.ps = [], GOOD, {'models': []}
        OllamaStub.tags = {'models': [{'name': 'm1'}, {'name': 'm2'}]}
        self.server = HTTPServer(('127.0.0.1', 0), OllamaStub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.env = patch.dict(os.environ, {'SCRUM_OLLAMA_URL': f'http://127.0.0.1:{self.server.server_port}'})
        self.env.start()
        self.addCleanup(self.env.stop)

    def run_main(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = bench.main(args)
        return code, out.getvalue().splitlines(), err.getvalue()

    def test_all_pass_exits_zero_and_prints_one_line_per_run(self):
        code, lines, _ = self.run_main(['--model', 'm1', '--model', 'm2', '--model', 'm1', '--runs', '2'])
        self.assertEqual(code, 0)
        runs = [json.loads(line) for line in lines[:12]]
        self.assertEqual([(r['model'], r['task'], r['run']) for r in runs[:6]],
                         [('m1', 'estimate', 1), ('m1', 'estimate', 2), ('m1', 'summary', 1),
                          ('m1', 'summary', 2), ('m1', 'edit', 1), ('m1', 'edit', 2)])
        self.assertEqual(set(runs[0]), {'model', 'task', 'run', 'pass', 'why', 'duration_s', 'ps'})
        self.assertTrue(all(r['pass'] for r in runs))
        self.assertEqual(lines[12:], ['m1 estimate 2/2', 'm1 summary 2/2', 'm1 edit 2/2',
                                      'm2 estimate 2/2', 'm2 summary 2/2', 'm2 edit 2/2'])
        chats = [body for method, path, body in OllamaStub.requests if path == '/api/chat']
        self.assertEqual(len(chats), 12)
        self.assertTrue(all(b['stream'] is False and b['think'] is False and 'options' not in b for b in chats))
        self.assertIn('Item: Add a --json flag', chats[0]['messages'][0]['content'])

    def test_one_failed_run_exits_one(self):
        OllamaStub.replies = dict(GOOD, estimating='{"points": 4, "why": "x"}')
        code, lines, _ = self.run_main(['--model', 'm1', '--runs', '1', '--task', 'estimate'])
        self.assertEqual(code, 1)
        self.assertFalse(json.loads(lines[0])['pass'])
        self.assertEqual(lines[1], 'm1 estimate 0/1')

    def test_defaults_are_routing_models_deduplicated(self):
        self.assertEqual(bench.default_models(), ['scrum-qwen3.5:4b', 'scrum-qwen2.5-coder:7b'])

    def test_unreachable_or_missing_or_cloud_model_exits_two(self):
        code, lines, err = self.run_main(['--model', 'absent'])
        self.assertEqual((code, lines), (2, []))
        self.assertEqual(err, 'FAIL: model absent missing from Ollama\n')
        OllamaStub.tags = {'models': [{'name': 'm1'}, {'name': 'gpt-oss:20b-cloud'}]}
        code, lines, err = self.run_main(['--model', 'm1', '--model', 'gpt-oss:20b-cloud'])
        self.assertEqual((code, lines), (2, []))
        self.assertEqual(err, 'FAIL: model gpt-oss:20b-cloud is cloud-tagged\n')
        with patch.dict(os.environ, {'SCRUM_OLLAMA_URL': 'http://127.0.0.1:9'}):
            code, lines, err = self.run_main(['--model', 'm1'])
        self.assertEqual((code, lines), (2, []))
        self.assertTrue(err.startswith('FAIL: Ollama down'))
        self.assertFalse([r for r in OllamaStub.requests if r[1] == '/api/chat'])

    def test_ps_fields_recorded_after_each_run(self):
        OllamaStub.ps = {'models': [{'name': 'm1', 'model': 'm1', 'size': 6000, 'size_vram': 5000,
                                     'context_length': 16384, 'digest': 'x', 'expires_at': 'y'}]}
        _, lines, _ = self.run_main(['--model', 'm1', '--model', 'm2', '--runs', '1', '--task', 'estimate'])
        self.assertEqual(json.loads(lines[0])['ps'], {'size': 6000, 'size_vram': 5000, 'context_length': 16384})
        self.assertIsNone(json.loads(lines[1])['ps'])
        paths = [path for _, path, _ in OllamaStub.requests]
        self.assertEqual(paths[paths.index('/api/chat') + 1], '/api/ps')


class ValidatorTests(unittest.TestCase):
    def test_estimate_rejects_bad_points_and_empty_why(self):
        self.assertEqual(bench.check_estimate('Sure: {"points": 5, "why": "several layers"}'), (True, ''))
        ok, why = bench.check_estimate('{"points": 4, "why": "x"}')
        self.assertFalse(ok)
        self.assertIn('points 4', why)
        self.assertEqual(bench.check_estimate('{"points": 3, "why": ""}'), (False, 'why is empty'))
        self.assertEqual(bench.check_estimate('three points'), (False, 'no JSON object'))

    def test_summary_rejects_uncited_or_unknown_path(self):
        paths = ('jobs/a/feature.md', 'jobs/b/spec.md')
        good = '- one [jobs/a/feature.md]\n- two [jobs/b/spec.md]'
        self.assertEqual(bench.check_summary(good, paths), (True, ''))
        self.assertEqual(bench.check_summary('- one [jobs/a/feature.md]', paths), (False, '1 bullets, want 2-5'))
        self.assertEqual(bench.check_summary('- one [jobs/a/feature.md]\n- two', paths),
                         (False, 'uncited bullet: - two'))
        self.assertEqual(bench.check_summary('- one [jobs/a/feature.md]\n- two [jobs/c/plan.md]', paths),
                         (False, 'unknown path jobs/c/plan.md'))

    def test_edit_passes_on_fix_and_fails_on_wrong_path_or_failing_test(self):
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp)
            bench.setup_edit(work)
            self.assertEqual((work / 'calc.py').read_text(), 'def add(a, b):\n    return a - b\n')
            test_before = (work / 'test_calc.py').read_bytes()
            ok, why = bench.check_edit(json.dumps({'path': 'other.py', 'content': 'x = 1\n'}), work)
            self.assertEqual((ok, why), (False, "path 'other.py' is not calc.py"))
            self.assertEqual(sorted(p.name for p in work.iterdir()), ['calc.py', 'test_calc.py'])
            self.assertEqual(bench.check_edit(json.dumps({'path': 'calc.py', 'content': 'def add(a, b):\n    return 0\n'}),
                                              work), (False, 'test_calc failed'))
            self.assertEqual(bench.check_edit(FIX, work), (True, ''))
            self.assertEqual((work / 'test_calc.py').read_bytes(), test_before)


class ReadmeTests(unittest.TestCase):
    def test_readme_has_benchmark_and_recovery(self):
        text = (ROOT / 'local/README.md').read_text()
        for needle in ('## Benchmark', 'python3 local/bench.py', '## Recovery', 'SCRUM_ROUTE=cloud', 'ollama stop',
                       '.agents/skills/trevskills-scrum'):
            self.assertIn(needle, text)


if __name__ == '__main__':
    unittest.main()
