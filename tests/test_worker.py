import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'local'))
os.environ.setdefault('SCRUM_WORKER_DIR', tempfile.mkdtemp())
import insights  # noqa: E402
import worker  # noqa: E402


class InsightsTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name) / 'scrum'
        job = self.root / 'jobs' / '001-a'
        (job / 'round-1').mkdir(parents=True)
        (job / 'decision.md').write_text('APPROVE\n## Rulings\n- accept the thing\n')
        (job / 'round-1' / 'check.md').write_text('CHECK: PASS\n')
        (job / 'round-1' / 'review-code.md').write_text('VERDICT: CHANGES\n- [blocking] missing test\n')
        (job / 'round-1' / 'review-ui.md').write_text('VERDICT: PASS\nSkipped by orchestrator: fast lane.\n')
        (job / 'routing.log').write_text('{"role": "scrum-builder", "runner": "local", "outcome": "review-changes"}\nbad\n')
        (self.root / 'jobs' / '002-b').mkdir()
        (self.root / 'digests' / '001').mkdir(parents=True)
        (self.root / 'digests' / '001' / 'jobs.txt').write_text('002-b\n')
        (self.root / 'board.json').write_text(json.dumps({'jobs': [
            {'id': '001-a', 'stage': 'done', 'lane': 'fast'}, {'id': '002-b', 'stage': 'done'},
            {'id': '003-c', 'stage': 'review'}]}))

    def test_pending_skips_digested_unfinished_and_written(self):
        self.assertEqual([j['id'] for j in insights.pending(self.root)], ['001-a'])

    def test_facts_are_counted_by_code_and_bad_bullets_dropped(self):
        reply = ('- Code review asked for a missing test [round-1/review-code.md]\n'
                 '- Invented thing [round-9/review-x.md]\n- no citation\n')
        with patch.object(insights.route, 'chat', return_value=reply):
            out = insights.write(self.root, {'id': '001-a', 'lane': 'fast'}, 'm').read_text()
        self.assertIn('Lane: fast · rounds: 1 · decision: APPROVE', out)
        self.assertIn('round-1: check PASS · reviews: code CHANGES', out)
        self.assertNotIn('ui', out.split('round-1:')[1].split('\n')[0])  # orchestrator skip files are not reviews
        self.assertIn('Routing: scrum-builder local review-changes ×1', out)
        self.assertIn('- Code review asked for a missing test [round-1/review-code.md]', out)
        self.assertNotIn('Invented', out)
        self.assertNotIn('no citation', out)
        self.assertEqual(insights.pending(self.root), [])

    def test_no_model_writes_facts_only(self):
        with patch.object(insights.route, 'chat') as chat:
            out = insights.write(self.root, {'id': '001-a'}, None).read_text()
        chat.assert_not_called()
        self.assertNotIn('## Findings', out)


class WorkerTests(unittest.TestCase):
    loaded = []
    def run_tick(self, idle, picks, n_tasks=3, dry=False):
        ran = []
        fake = [('estimator', 'p', lambda i=i: ran.append(i)) for i in range(n_tasks)]
        with patch.object(worker, 'idle_seconds', return_value=idle), patch.object(worker, 'tasks', return_value=iter(fake)), \
                patch.object(worker.route, 'route', side_effect=picks), \
                patch.object(worker.route, 'loaded_models', return_value=self.loaded):
            line = worker.tick(dry=dry)
        return line, ran

    def test_active_runs_one_task_idle_runs_all(self):
        local = lambda role: {'runner': 'local', 'model': 'm', 'why': 'x'}
        self.assertEqual(self.run_tick(0, local)[1], [0])
        self.assertEqual(self.run_tick(worker.IDLE_AFTER, local)[1], [0, 1, 2])

    def test_never_runs_when_router_says_cloud(self):
        line, ran = self.run_tick(worker.IDLE_AFTER, lambda role: {'runner': 'cloud', 'model': None, 'why': 'low memory (2 GB)'})
        self.assertEqual(ran, [])
        self.assertIn('stopped: estimator: low memory', line)

    def test_yields_to_another_loaded_scrum_model(self):
        self.loaded = ['scrum-qwen2.5-coder:7b']
        line, ran = self.run_tick(worker.IDLE_AFTER, lambda role: {'runner': 'local', 'model': 'scrum-qwen3.5:4b', 'why': 'x'})
        self.assertEqual(ran, [])
        self.assertIn('scrum-qwen2.5-coder:7b in use', line)

    def test_status_is_a_dry_run(self):
        line, ran = self.run_tick(0, lambda role: {'runner': 'local', 'model': 'm', 'why': 'x'}, dry=True)
        self.assertEqual(ran, [])
        self.assertTrue(line.startswith('would run estimator'))


if __name__ == '__main__':
    unittest.main()
