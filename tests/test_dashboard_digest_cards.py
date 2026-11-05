import json, re, shutil, subprocess, unittest

from test_dashboard_ai_focus import DASHBOARD


def prop_rows(calls):
    """Run dashboard.html's esc, diffHtml and propRow in node over [digestId, proposal] pairs."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    lines = [l for l in text.splitlines() if l.startswith(("const esc = ", "const diffHtml = ", "const shortPath = "))]
    start = text.index("const propRow = ")
    fn = text[start:text.index("\nfunction renderDigests(", start)]
    script = "\n".join(lines) + "\n" + fn + f"\nconsole.log(JSON.stringify({json.dumps(calls)}.map(a => propRow(...a))));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)


def digest_code(text):
    """dashboard.html's Digest dialog code: from its `let digestData` comment to the Pipelines block."""
    return text[text.index("// Digest: proposals from"):text.index("// Pipelines:")]


class DigestLogTest(unittest.TestCase):
    def test_no_needs_human_digest_card(self):
        text = DASHBOARD.read_text()
        for gone in ("function digestCard(", "digestCards", 'data-decide="approve"', 'data-decide="reject"', ".dcard"):
            self.assertNotIn(gone, text, gone)
        for gone in (">Approve</button>", ">Reject</button>", "data-decide"):
            self.assertNotIn(gone, digest_code(text), gone)
        poll = text[text.index("async function poll()"):]
        poll = poll[:poll.index("\n}\n")]
        self.assertNotIn("digests?brief=1", poll)
        self.assertNotIn("digests", poll.split("const text = JSON.stringify(")[1].split(")")[0])

    def test_dialog_loads_full_digests(self):
        text = DASHBOARD.read_text()
        load = text[text.index("async function loadDigests()"):]
        self.assertIn("getJson(`api/p/${enc(p)}/digests`, null, STALE)", load[:load.index("\n}\n")])

    def test_prop_row_read_only_has_no_revert(self):
        p = {"id": "p1", "target": "/r/x.md", "why": "w", "old": "a", "new": "b", "kind": "edit", "status": "applied"}
        editable, frozen = prop_rows([["004", p], ["004", p, True]])
        self.assertIn("data-revert", editable)
        self.assertNotIn("data-revert", frozen)
        self.assertIn('<span class="chip applied">applied</span>', frozen)

    def test_prop_row_parts(self):
        statuses = ["applied", "queued", "skipped", "reverted", "pending", "rejected", "odd<x>"]
        base = {"target": "/r/agents/scrum-x.md", "why": "Seen in 001-a & 002-b.", "old": "old <line>", "new": "new line", "kind": "edit"}
        rows = [["004", {**base, "id": f"p{i}", "status": s, "reason": f"because {s}"}] for i, s in enumerate(statuses)]
        rows.append(["004", {**base, "id": "q9", "status": "queued"}])  # no stored reason
        rows.append(["004", {**base, "id": "s9", "status": "skipped", "old": "", "kind": "skill"}])
        html = prop_rows(rows)
        for i, (s, h) in enumerate(zip(statuses, html)):
            with self.subTest(s):
                self.assertTrue(h.startswith(f'<div class="prop" data-digest="004" data-pid="p{i}">'), h)
                self.assertIn(f'<span class="id">p{i} <span class="chip ', h)
                self.assertIn('<span class="path" title="/r/agents/scrum-x.md">/r/agents/scrum-x.md</span>', h)
                self.assertIn("Seen in 001-a &amp; 002-b.", h)
                self.assertIn('<pre>old &lt;line&gt;</pre>', h)
                self.assertIn('<pre>new line</pre>', h)
                self.assertIn('<p class="error" role="alert"></p>', h)
                self.assertNotIn("undefined", h)
                self.assertEqual(h.count("data-revert"), 1 if s == "applied" else 0)
                self.assertEqual(h.count("<button"), 1 if s == "applied" else 0)
                if s in ("queued", "skipped"):
                    self.assertIn(f'<span class="note">because {s}</span>', h)
                else:
                    self.assertNotIn("because", h)
        self.assertIn('<span class="chip applied">applied</span>', html[0])
        self.assertIn('<span class="chip reverted">reverted</span>', html[3])
        self.assertIn('<span class="chip rejected">rejected</span>', html[5])
        self.assertIn('<span class="chip odd&lt;x&gt;">odd&lt;x&gt;</span>', html[6])
        self.assertIn('<button class="btn" type="button" data-revert data-agent-hint="', html[0])
        self.assertRegex(html[0], r'data-agent-hint="[^"]+">Revert</button>')
        for h in html[7:]:
            self.assertNotIn("undefined", h)
            self.assertNotIn('class="note">', h.split('<div class="diff">')[0])
        self.assertIn("<pre></pre>", html[8])  # a skill has an empty Old side

    def test_prop_row_short_target_full_title(self):
        base = {"id": "p1", "why": "w", "old": "a", "new": "b", "kind": "edit", "status": "applied"}
        targets = ["/Users/trev/Developer/repos/app/agents/x.md", "/Users/trev/.claude/rules/y.md", "/home/ci/z.md",
                   "agents/rel.md", ""]
        html = prop_rows([["004", {**base, "target": t}] for t in targets])
        self.assertIn('<span class="path" title="/Users/trev/Developer/repos/app/agents/x.md">app/agents/x.md</span>', html[0])
        self.assertIn('<span class="path" title="/Users/trev/.claude/rules/y.md">~/.claude/rules/y.md</span>', html[1])
        self.assertIn('<span class="path" title="/home/ci/z.md">~/z.md</span>', html[2])
        self.assertIn('<span class="path" title="agents/rel.md">agents/rel.md</span>', html[3])
        self.assertIn('<span class="path" title=""></span>', html[4])
        self.assertIn('data-pid="p1"', html[0])

    def test_load_error_clears_list(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node not on PATH")
        text = DASHBOARD.read_text()
        start = text.index("async function loadDigests()")
        fn = text[start:text.index("\n}\n", start) + 2]
        script = ('const els = {dgList: {innerHTML: \'<p class="empty">loading…</p>\'}, dgError: {textContent: ""}};'
                  ' const $ = id => els[id], enc = encodeURIComponent, STALE = "stale", dgProject = () => "p";'
                  ' let digestData = null, digestText = "", rendered = 0; const renderDigests = () => rendered++;'
                  ' const getJson = async () => null;\n' + fn
                  + '\nloadDigests().then(() => console.log(JSON.stringify([els.dgList.innerHTML, els.dgError.textContent, rendered])));')
        got = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(got, ["", "Couldn't load digests. Is serve.py running?", 0])

    def test_diff_colours_use_theme_vars(self):
        css = DASHBOARD.read_text().split("<style>")[1].split("</style>")[0]
        rules = re.findall(r"\.prop \.diff[^{]*\{([^}]*)\}", css)
        body = " ".join(rules)
        self.assertIn("line-through", body)
        self.assertIn("var(--human)", body)
        self.assertIn("var(--pass)", body)
        self.assertNotRegex(body, r"#[0-9a-fA-F]{3}")
        old = next(r for r in rules if "line-through" in r)
        self.assertIn("var(--human)", old)

    def test_revert_click_posts_revert(self):
        code = digest_code(DASHBOARD.read_text())
        self.assertIn('closest("button[data-revert]")', code)
        self.assertIn('{decision: "revert"}', code)

    def test_legend_digest_step_is_log(self):
        text = DASHBOARD.read_text()
        line = next(l for l in text.splitlines() if l.lstrip().startswith('"Digest": ['))
        self.assertIn('{step: "Digest dialog", note: "log", hint: "Each proposal is applied automatically; an applied one can be '
                      'reverted in the Digest dialog."}', line)
        self.assertNotIn("you decide", line)


if __name__ == "__main__":
    unittest.main()
