import re, subprocess, sys, tempfile, unittest
from pathlib import Path

RUNNER = Path(__file__).resolve().parent / "run_parallel.py"


class RunParallelTest(unittest.TestCase):
    """tests/run_parallel.py over a temp folder of tiny test modules."""

    def run_on(self, modules, *args):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        for name, text in modules.items():
            (Path(tmp.name) / f"{name}.py").write_text(text)
        return subprocess.run([sys.executable, str(RUNNER), "--start", tmp.name, *args], capture_output=True, text=True,
                              timeout=120)

    @staticmethod
    def shard_lines(out):
        return re.findall(r"^shard \d+/\d+: .*$", out, re.M)

    def test_one_failing_test_fails_the_run_and_the_rest_still_run(self):
        mods = {"test_a": "import unittest\nclass A(unittest.TestCase):\n"
                          "    def test_one(self): pass\n    def test_two(self): pass\n"
                          "    def test_boom(self): self.fail('boom here')\n    def test_four(self): pass\n"}
        r = self.run_on(mods, "-j", "4")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("test_boom", r.stdout)
        self.assertIn("boom here", r.stdout)
        lines = self.shard_lines(r.stdout)
        self.assertEqual(len(lines), 4, r.stdout)
        self.assertEqual(sum("1 tests OK" in line for line in lines), 3, lines)
        self.assertEqual(sum("FAILED" in line for line in lines), 1, lines)
        self.assertTrue(r.stdout.rstrip().splitlines()[-1].startswith("Ran 4 tests in "), r.stdout)

    def test_syntax_error_module_fails_with_its_name(self):
        r = self.run_on({"test_good": "import unittest\nclass G(unittest.TestCase):\n    def test_ok(self): pass\n",
                         "test_broken": "def oops(:\n"}, "-j", "2")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("test_broken", r.stdout)
        self.assertIn("SyntaxError", r.stdout)

    def test_more_workers_than_tests_starts_no_empty_shard(self):
        mods = {"test_b": "import unittest\nclass B(unittest.TestCase):\n    def test_x(self): pass\n    def test_y(self): pass\n"}
        r = self.run_on(mods, "-j", "8")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.shard_lines(r.stdout), [l for l in self.shard_lines(r.stdout) if " 1 tests OK " in l])
        self.assertEqual(len(self.shard_lines(r.stdout)), 2, r.stdout)
        self.assertTrue(r.stdout.rstrip().splitlines()[-1].startswith("Ran 2 tests in "), r.stdout)

    def test_zero_workers_is_refused_before_running(self):
        r = self.run_on({"test_c": "import unittest\nclass C(unittest.TestCase):\n    def test_x(self): pass\n"}, "-j", "0")
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual(self.shard_lines(r.stdout), [])
        self.assertNotIn("Ran ", r.stdout)


if __name__ == "__main__":
    unittest.main()
