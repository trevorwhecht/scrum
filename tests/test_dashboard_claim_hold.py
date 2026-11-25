"""The #claimHold header line shows each project's board.claimHold as `New work held: <why>` and hides when none (job 1552)."""
import json, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD

WHY = "finishing work in flight first: onewitharts/1998 waits on the Check queue"


def render(boards, names=("a", "b")):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
    fn = text[text.index("function renderClaimHold("):text.index("async function poll()")]
    script = (f"const el = {{innerHTML: '', hidden: true}};\nconst $ = id => id === 'claimHold' ? el : null;\n{esc}\n{fn}\n"
              f"renderClaimHold({json.dumps(boards)}, {json.dumps(list(names))});\nconsole.log(JSON.stringify(el));")
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class ClaimHold(unittest.TestCase):
    def test_one_project(self):
        self.assertEqual(render([{"claimHold": WHY}, {"claimHold": None}]),
                         {"innerHTML": "New work held: " + WHY, "hidden": False})

    def test_two_projects_prefix_escaped(self):
        el = render([{"claimHold": "a<b"}, {"claimHold": "cool-down"}], names=["<i>", "b"])
        self.assertEqual(el["innerHTML"], "&lt;i&gt;: New work held: a&lt;b · b: New work held: cool-down")

    def test_none_hidden(self):
        self.assertEqual(render([{"claimHold": None}, {}]), {"innerHTML": "", "hidden": True})

    def test_header_element_exists(self):
        self.assertIn('id="claimHold"', DASHBOARD.read_text())


if __name__ == "__main__":
    unittest.main()
