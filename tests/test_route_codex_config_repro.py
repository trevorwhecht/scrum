"""Repro: route.py codex-review answers cloud even when ~/.codex/config.toml points Codex at a local
(Ollama) server, so every review hangs up to 10 minutes and writes nothing."""
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROUTE_PY = Path(__file__).resolve().parents[1] / 'local/route.py'
spec = importlib.util.spec_from_file_location('local_route_codex_config_repro', ROUTE_PY)
route_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route_mod)


class CodexConfigRepro(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        root = Path(tmp.name)
        (root / 'sessions').mkdir()  # no rollout files: both quota windows unknown, i.e. below thresholds
        self.config = root / 'config.toml'
        env = patch.dict(os.environ, {'SCRUM_CODEX_SESSIONS': str(root / 'sessions'),
                                      'SCRUM_CODEX_CONFIG': str(self.config)})
        env.start()
        self.addCleanup(env.stop)
        codex = patch.object(route_mod, '_codex_installed', lambda: True)
        codex.start()
        self.addCleanup(codex.stop)

    def test_codex_review_skips_when_config_points_at_local_server(self):
        self.config.write_text('model = "gemma4:31b:cloud"\n'
                               'openai_base_url = "http://127.0.0.1:11434/api/codex/v1"\n')
        self.assertEqual(route_mod.route('codex-review'), {
            'runner': 'skip', 'model': None,
            'why': 'codex config points at a local server (http://127.0.0.1:11434/api/codex/v1)'})


if __name__ == '__main__':
    unittest.main()
