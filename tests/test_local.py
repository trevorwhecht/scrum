import importlib.util
import json
from pathlib import Path
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
        _, command, env = self.launch(['claude', '-p', 'hello', '--model', 'sonnet'])
        self.assertEqual(command[1:3], ['-p', 'hello'])
        self.assertEqual(command[command.index('--model') + 1], run.MODEL)
        settings = json.loads(command[-1])['env']
        self.assertEqual(settings['ANTHROPIC_BASE_URL'], 'http://127.0.0.1:11434')
        for alias in ('SONNET', 'OPUS', 'HAIKU'):
            self.assertEqual(settings['ANTHROPIC_DEFAULT_' + alias + '_MODEL'], run.MODEL)
        self.assertEqual(env['ANTHROPIC_API_KEY'], '')

    def test_dashboard_inherits_review_shim_and_claude_wrapper(self):
        _, command, env = self.launch(['dashboard', '--port', '8766'])
        self.assertEqual(command[-2:], ['--port', '8766'])
        self.assertTrue(env['PATH'].startswith(str(run.HERE / 'bin')))
        self.assertIn('SCRUM_REAL_CODEX', env)
