import json, re, shutil, subprocess, unittest

from test_dashboard_ai_focus import DASHBOARD


def digest_cards(calls):
    """Run dashboard.html's esc, tag and digestCard in node over [project, digestId, proposal] triples."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    lines = [l for l in text.splitlines() if l.startswith(("const esc = ", "const hue = ", "const tag = "))]
    start = text.index("function digestCard(")
    fn = text[start:text.index("\n}\n", start) + 2]
    script = "\n".join(lines) + "\n" + fn + f"\nconsole.log(JSON.stringify({json.dumps(calls)}.map(a => digestCard(...a))));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


class DigestCards(unittest.TestCase):
    def test_reason_line_and_target(self):
        prop = {"id": "p2", "target": "/r/agents/scrum-x.md", "status": "pending", "obvious_reason": "one job only <b>"}
        html, = digest_cards([["reg", "004", prop]])
        self.assertIn('<span class="reason">Digest 004 p2: one job only &lt;b&gt;</span>', html)
        self.assertIn("/r/agents/scrum-x.md", html)
        self.assertRegex(html, r'^<div class="card human')  # a div: its buttons must not nest in a <button>
        self.assertEqual(len(re.findall(r'<button class="btn tall[^"]*" type="button" data-decide="(approve|reject)"', html)), 2)
        self.assertIn('data-project="reg" data-digest="004" data-pid="p2"', html)

    def test_reason_without_obvious_reason(self):
        html, = digest_cards([["reg", "004", {"id": "p1", "target": "/t", "status": "pending", "obvious_reason": ""}]])
        self.assertIn('<span class="reason">Digest 004 p1</span>', html)

    def test_board_posts_decision_to_digest_endpoint(self):
        text = DASHBOARD.read_text()
        self.assertIn("post(`api/p/${enc(c.dataset.project)}/digests/${enc(c.dataset.digest)}/${enc(c.dataset.pid)}`, {decision: b.dataset.decide})", text)
        poll = text[text.index("async function poll()"):]
        self.assertIn("getJson(`api/p/${enc(p)}/digests?brief=1`, null)", poll[:poll.index("\n}\n")])
        load = text[text.index("async function loadDigests()"):]
        self.assertIn("getJson(`api/p/${enc(p)}/digests`, null, STALE)", load[:load.index("\n}\n")])


if __name__ == "__main__":
    unittest.main()
