import json, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"


def safe_url(hrefs):
    """Run dashboard.html's one-line safeUrl in node over each href; JSON null/undefined pass through as given."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    start = text.index("const safeUrl = ")
    line = text[start:text.index("\n", start)]
    script = line + "\nconst out = [];\nfor (const h of " + json.dumps(hrefs) + ".concat([undefined])) out.push(safeUrl(h));\n" \
        "console.log(JSON.stringify(out.map(v => v === undefined ? '<undefined>' : v)));"
    out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
    return out[:-1], out[-1]


class SafeUrl(unittest.TestCase):
    def test_safe_urls_pass(self):
        hrefs = ["https://x.y/a", "http://x.y", "mailto:a@b.c", "#frag", "/p/a.md", "./a.md", "a.md", "?q=1"]
        self.assertEqual(safe_url(hrefs)[0], ["https://x.y/a", "http://x.y", "mailto:a@b.c", "#frag", "/p/a.md", "./a.md", "a.md", "?q=1"])

    def test_unsafe_urls_blocked(self):
        hrefs = ["javascript:alert(1)", "JavaScript:alert(1)", "  javascript:alert(1)", "java\tscript:alert(1)",
                 "java\nscript:alert(1)", "\x01javascript:alert(1)", "javascript&#58;alert(1)", "javascript&colon;alert(1)",
                 "vbscript:x", "data:text/html,<script>alert(1)</script>", "file:///etc/passwd",
                 # Entities anywhere in the scheme: the browser decodes them inside href/src after marked writes them.
                 "&#106;avascript:alert(1)", "jav&#97;script:alert(1)", "javascript&Tab;:alert(1)", "java&#9;script:1",
                 "java&#x73;cript:alert(1)", "&#106;avascript&#58;alert(1)"]
        self.assertEqual(safe_url(hrefs)[0], [None] * 17)

    def test_ampersand_after_path_or_query_passes(self):
        self.assertEqual(safe_url(["a.md?x=1&y=2", "/p/a&b.md", "mailto:a@b.c?subject=a&body=b"])[0],
                         ["a.md?x=1&y=2", "/p/a&b.md", "mailto:a@b.c?subject=a&body=b"])

    def test_empty_and_missing_href(self):
        results, undef = safe_url(["", "   ", "\t\n", None])
        self.assertEqual(results, [None, None, None, None])
        self.assertIsNone(undef)


if __name__ == "__main__":
    unittest.main()
