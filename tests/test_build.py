import importlib.util
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

BUILD_PY = Path(__file__).resolve().parents[1] / 'local/build.py'
spec = importlib.util.spec_from_file_location('local_build', BUILD_PY)
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)

SPEC = """# Fix add
Lane: fast

## Acceptance criteria
1. `def add` returns the sum.

## Likely files
- `calc.py`: the `add` function
- notes/new.md
"""


def block(path, search, replace):
    return f'FILE: {path}\n<<<<<<< SEARCH\n{search}=======\n{replace}>>>>>>> REPLACE\n'


class BuildTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.wt = self.root / 'wt'
        (self.wt / 'notes').mkdir(parents=True)
        (self.wt / 'calc.py').write_text('def add(a, b):\n    return a - b\n')
        (self.wt / 'other.py').write_text('x = 1\n')
        for cmd in (['init', '-q'], ['add', '-A'], ['-c', 'user.email=t@t', '-c', 'user.name=t', 'commit', '-qm', 'base']):
            subprocess.run(['git', '-C', str(self.wt), *cmd], check=True)
        self.job = self.root / 'job'
        self.job.mkdir()
        (self.job / 'spec.md').write_text(SPEC)

    def test_likely_files_backticked_bare_and_new(self):
        self.assertEqual(build.likely_files(SPEC, self.wt.resolve()), ['calc.py', 'notes/new.md'])

    def test_apply_rejects_unlisted_file_ambiguous_and_noop_edits(self):
        allowed = ['calc.py']
        with self.assertRaisesRegex(ValueError, 'not under Likely files'):
            build.apply(block('other.py', 'x = 1\n', 'x = 2\n'), self.wt, allowed)
        with self.assertRaisesRegex(ValueError, 'matched 0 times'):
            build.apply(block('calc.py', 'nope\n', 'y\n'), self.wt, allowed)
        with self.assertRaisesRegex(ValueError, 'change nothing'):
            build.apply(block('calc.py', '    return a - b\n', '    return a - b\n'), self.wt, allowed)
        self.assertEqual((self.wt / 'calc.py').read_text(), 'def add(a, b):\n    return a - b\n')  # nothing written

    def test_view_sends_excerpts_of_a_big_file(self):
        text = '\n'.join(f'line {i}' for i in range(500)) + '\ndef add(a, b):\n    return a - b\n'
        out = build.view(text, SPEC, 2000)
        self.assertIn('def add(a, b):', out)
        self.assertIn('... (lines omitted) ...', out)
        self.assertNotIn('line 10\n', out)
        self.assertIsNone(build.view(text, '# nothing to point at', 2000))

    def test_main_builds_commits_and_writes_build_md(self):
        reply = block('calc.py', '    return a - b\n', '    return a + b\n')
        with patch.object(build.route, 'chat', return_value=reply) as chat:
            build.main([str(self.job), str(self.wt), 'm'])
        self.assertIn('=== SPEC ===', chat.call_args.args[1])
        self.assertEqual((self.wt / 'calc.py').read_text(), 'def add(a, b):\n    return a + b\n')
        log = subprocess.run(['git', '-C', str(self.wt), 'log', '--format=%s', '-1'], capture_output=True, text=True).stdout
        self.assertEqual(log.strip(), 'Build: Fix add')
        self.assertTrue((self.job / 'build.md').read_text().startswith('STATUS: READY_WITH_CONCERNS'))

    def test_main_reasks_once_then_fails(self):
        with patch.object(build.route, 'chat', return_value='no blocks') as chat, self.assertRaises(SystemExit) as e:
            build.main([str(self.job), str(self.wt), 'm'])
        self.assertEqual(chat.call_count, 2)
        self.assertIn('could not be applied', chat.call_args.args[1])
        self.assertIn('no edit blocks', str(e.exception))
        self.assertFalse((self.job / 'build.md').exists())

    def test_protected_path_refused(self):
        (self.job / 'spec.md').write_text(SPEC.replace('notes/new.md', 'prisma/schema.prisma'))
        (self.wt / 'prisma').mkdir()
        (self.wt / 'prisma' / 'schema.prisma').write_text('model A {}\n')
        with patch.object(build.route, 'chat') as chat, self.assertRaisesRegex(SystemExit, 'protected path'):
            build.main([str(self.job), str(self.wt), 'm'])
        chat.assert_not_called()


if __name__ == '__main__':
    unittest.main()
