from contextlib import redirect_stderr
from http.server import BaseHTTPRequestHandler, HTTPServer
import importlib.util
import io
import json
import os
from pathlib import Path
import socket
import threading
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('local_run', Path(__file__).resolve().parents[1] / 'local/run.py')
run = importlib.util.module_from_spec(spec)
spec.loader.exec_module(run)

class LocalLauncherTests(unittest.TestCase):
    def launch(self, args):
        with patch.object(run.sys, 'argv', ['run.py', *args]), patch.object(run.os, 'execvpe') as execute:
            run.main()
        return execute.call_args.args

    def test_review_replaces_cloud_model_and_preserves_review_flags(self):
        _, command, env = self.launch(['codex', 'exec', 'review', '--base', 'main', '-m', 'gpt-6.1-sol', '--ephemeral'])
        self.assertNotIn('gpt-6.1-sol', command)
        self.assertIn('--oss', command)
        self.assertIn('ollama', command)
        self.assertEqual(command[-5:], ['exec', 'review', '--base', 'main', '--ephemeral'])
        self.assertEqual(env['SCRUM_CLAUDE'], str(run.HERE / 'bin/claude-local'))

    def test_claude_subagent_aliases_and_settings_use_local_endpoint(self):
        with patch.object(run, 'preflight'):
            _, command, env = self.launch(['claude', '-p', 'hello', '--model', 'sonnet'])
        self.assertEqual(command[1:5], ['--bare', '--strict-mcp-config', '-p', 'hello'])
        self.assertEqual(command[command.index('--model') + 1], run.MODEL)
        settings = json.loads(command[-1])['env']
        self.assertEqual(settings['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:11434')
        for alias in ('SONNET', 'OPUS', 'HAIKU'):
            self.assertEqual(settings['ANTHROPIC_DEFAULT_' + alias + '_MODEL'], run.MODEL)
        self.assertEqual(env['ANTHROPIC_API_KEY'], '')
        # --bare drops hooks, so the safety rules must arrive as deny rules
        self.assertTrue(set(run.SAFETY_DENY) <= set(json.loads(command[-1])['permissions']['deny']))

    def test_dashboard_inherits_review_shim_and_claude_wrapper(self):
        _, command, env = self.launch(['dashboard', '--port', '8766'])
        self.assertEqual(command[-2:], ['--port', '8766'])
        self.assertTrue(env['PATH'].startswith(str(run.HERE / 'bin')))
        self.assertIn('SCRUM_REAL_CODEX', env)


class OllamaStub(BaseHTTPRequestHandler):
    """Answers /api/generate with {} and /api/ps with the class-level `ps` reply."""
    ps = {'models': []}
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

    def do_POST(self):
        length = int(self.headers.get('Content-Length', 0))
        OllamaStub.requests.append(('POST', self.path, json.loads(self.rfile.read(length) or b'{}')))
        self.reply({'done': True})

    def do_GET(self):
        OllamaStub.requests.append(('GET', self.path, None))
        self.reply(OllamaStub.ps)


class PreflightTests(unittest.TestCase):
    def setUp(self):
        OllamaStub.requests = []
        self.server = HTTPServer(('127.0.0.1', 0), OllamaStub)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f'http://127.0.0.1:{self.server.server_port}'

    def launch(self, args, url, context=32768, model='qwen2.5-coder:7b'):
        """Re-imports run.py with the test env, then runs main(); returns (exit code or None, stderr, execvpe mock)."""
        env = {'SCRUM_OLLAMA_URL': url, 'SCRUM_LOCAL_CONTEXT': str(context), 'SCRUM_LOCAL_MODEL': model}
        err = io.StringIO()
        with patch.dict(os.environ, env):
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
        with patch.object(mod.sys, 'argv', ['run.py', *args]), patch.object(mod.os, 'execvpe') as execute, \
                redirect_stderr(err):
            try:
                mod.main()
                code = None
            except SystemExit as e:
                code = e.code
        return code, err.getvalue(), execute

    def test_preflight_refuses_small_context(self):
        OllamaStub.ps = {'models': [{'name': 'qwen2.5-coder:7b', 'model': 'qwen2.5-coder:7b', 'context_length': 4096}]}
        code, _, execute = self.launch(['claude', '-p', 'hi'], self.url)
        self.assertEqual(code, 'Ollama loaded qwen2.5-coder:7b with context 4096 < 32768; '
                               'start Ollama with OLLAMA_CONTEXT_LENGTH=32768')
        execute.assert_not_called()
        self.assertIn(('POST', '/api/generate', {'model': 'qwen2.5-coder:7b', 'keep_alive': '10m'}),
                      OllamaStub.requests)
        self.assertIn(('GET', '/api/ps', None), OllamaStub.requests)

    def test_preflight_accepts_requested_context(self):
        OllamaStub.ps = {'models': [{'name': 'qwen2.5-coder:7b', 'model': 'qwen2.5-coder:7b', 'context_length': 32768}]}
        code, _, execute = self.launch(['claude', '-p', 'hi'], self.url + '/')
        self.assertIsNone(code)
        execute.assert_called_once()
        settings = json.loads(execute.call_args.args[1][-1])['env']
        self.assertEqual(settings['ANTHROPIC_BASE_URL'], self.url)

    def test_preflight_matches_untagged_model_as_latest(self):
        OllamaStub.ps = {'models': [{'name': 'scrum-local:latest', 'model': 'scrum-local:latest', 'context_length': 65536}]}
        code, _, execute = self.launch(['claude', '-p', 'hi'], self.url, context=65536, model='scrum-local')
        self.assertIsNone(code)
        execute.assert_called_once()
        self.assertIn(('POST', '/api/generate', {'model': 'scrum-local', 'keep_alive': '10m'}), OllamaStub.requests)

    def test_preflight_warns_without_context_field(self):
        OllamaStub.ps = {'models': [{'name': 'qwen2.5-coder:7b', 'model': 'qwen2.5-coder:7b'}]}
        code, err, execute = self.launch(['claude', '-p', 'hi'], self.url)
        self.assertIsNone(code)
        self.assertIn('warning', err.lower())
        self.assertIn('context_length', err)
        execute.assert_called_once()

    def test_preflight_refuses_unreachable_ollama(self):
        with socket.socket() as s:
            s.bind(('127.0.0.1', 0))
            port = s.getsockname()[1]
        code, _, execute = self.launch(['claude', '-p', 'hi'], f'http://127.0.0.1:{port}')
        self.assertTrue(code)
        self.assertNotEqual(code, 0)
        self.assertIn('Ollama', str(code))
        execute.assert_not_called()

    def test_codex_and_dashboard_modes_skip_preflight(self):
        for args in (['codex', 'exec', 'review'], ['dashboard', '--port', '8766']):
            code, _, execute = self.launch(args, self.url)
            self.assertIsNone(code, args)
            execute.assert_called_once()
        self.assertEqual(OllamaStub.requests, [])
