import subprocess, sys, unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SiblingImportTest(unittest.TestCase):
    def test_serve_tests_resolve_sibling_imports_when_run_as_a_package_path(self):
        # `python3 -m unittest tests.test_serve` leaves tests/ off sys.path; the sibling import must still resolve.
        r = subprocess.run([sys.executable, "-m", "unittest", "tests.test_serve.ServeTest.test_start_now_on_queued_job"],
                           cwd=ROOT, capture_output=True, text=True, timeout=300)
        self.assertNotIn("ModuleNotFoundError", r.stderr)
        self.assertEqual(r.returncode, 0, r.stderr[-2000:])


if __name__ == "__main__":
    unittest.main()
