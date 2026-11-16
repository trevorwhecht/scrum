"""The #autoOff header line shows each project's board.autoOff and hides when none has one (job 917)."""
import json, shutil, subprocess, unittest

from test_dashboard_job_modal import DASHBOARD

SINCE = 1794355200 + 3600  # 2026-11-11 01:00 UTC


def render(boards, names=("a", "b")):
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    esc = next(l for l in text.splitlines() if l.startswith("const esc = "))
    fn = text[text.index("function renderAutoOff("):text.index("async function poll()")]
    script = (f"const el = {{innerHTML: '', hidden: true}};\nconst $ = id => id === 'autoOff' ? el : null;\n{esc}\n{fn}\n"
              f"renderAutoOff({json.dumps(boards)}, {json.dumps(list(names))});\nconsole.log(JSON.stringify(el));")
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class AutoOff(unittest.TestCase):
    def test_one_project(self):
        self.assertEqual(render([{"autoOff": {"since": SINCE, "claimable": 3}}, {"autoOff": None}]),
                         {"innerHTML": "Auto continue off since 2026-11-11, 3 claimable", "hidden": False})

    def test_two_projects_prefix_escaped_name(self):
        el = render([{"autoOff": {"since": SINCE, "claimable": 3}}, {"autoOff": {"since": SINCE + 86400, "claimable": 1}}],
                    names=["<i>", "b"])
        self.assertEqual(el["innerHTML"], "&lt;i&gt; Auto continue off since 2026-11-11, 3 claimable"
                         " · b Auto continue off since 2026-11-12, 1 claimable")

    def test_none_hidden(self):
        self.assertEqual(render([{"autoOff": None}, {}]), {"innerHTML": "", "hidden": True})


if __name__ == "__main__":
    unittest.main()
