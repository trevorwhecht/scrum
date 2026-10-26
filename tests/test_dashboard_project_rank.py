import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"


def fn_body(text, name):
    start = text.index(f"function {name}(")
    return text[start:text.index("\n}\n", start) + 2]


class ProjectRankDialog(unittest.TestCase):
    """Job 427: a Rank button after #filter opens a dialog that reorders projects (projects.json order)."""

    def test_markup_and_click(self):
        text = DASHBOARD.read_text()
        header = text[text.index("<header>"):text.index("</header>")]
        self.assertRegex(header, r'<select id="filter"[^>]*>.*?</select>\s*<button class="btn" id="rankBtn" type="button"[^>]*>Rank</button>')
        dialog = text[text.index('<dialog id="rank" aria-label="Project rank">'):]
        dialog = dialog[:dialog.index("</dialog>")]
        self.assertRegex(dialog, r'<p class="error" id="rankError" aria-live="polite"></p>')
        self.assertIn('<ol id="rankList"></ol>', dialog)
        click = text[text.index('$("rankList").addEventListener("click"'):]
        click = click[:click.index("\n});\n")]
        self.assertIn('post("api/projects/rank", {name, to: projects.indexOf(name) + (dir === "up" ? -1 : 1)})', click)
        self.assertIn('renderSelect($("filter"), filter, true)', click, "#filter follows the new order")
        self.assertIn('$("rankError").textContent = err.message', click)
        self.assertIn('if ($("rank")?.open) renderRank();', fn_body(text, "poll"))
        css = " ".join(re.findall(r"#rank[^{]*\{[^}]*\}", text))
        self.assertIn("#rank .close,#rankBtn,#rankList .btn{min-height:44px;min-width:44px}", css)
        self.assertNotRegex(css, r"#[0-9a-fA-F]{3,6}\b|\bwhite\b")
        self.assertIn("#usage,#rank{width:100%", text, "full width at 390 px like the other dialogs")

    def run_node(self, body):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        # A list whose innerHTML setter turns each <button ...> into an object with dataset, disabled and focus().
        script = f"""{esc}
let projects = [], active = null;
const document = {{get activeElement() {{ return active; }}}};
const list = {{dataset: {{}}, buttons: [], html: "", childElementCount: 0,
  set innerHTML(h) {{ this.html = h; this.childElementCount = (h.match(/<li/g) || []).length;
    this.buttons = [...h.matchAll(/<button[^>]*data-rank="([^"]*)" data-dir="(\\w+)"[^>]*>/g)].map(m => ({{
      dataset: {{rank: m[1].replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, "&"), dir: m[2]}}, disabled: m[0].includes(" disabled"), focus() {{ active = this; }}}})); }},
  get innerHTML() {{ return this.html; }},
  contains(n) {{ return this.buttons.includes(n); }}, querySelectorAll() {{ return this.buttons; }}}};
const els = {{rankList: list}};
const $ = id => els[id];
{fn_body(text, 'renderRank')}
{body}"""
        return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)

    def test_render_rows_and_focus(self):
        out = self.run_node("""
const seen = [];
renderRank(); seen.push(list.innerHTML);
projects = ["boise", "a<b"]; renderRank(); seen.push(list.innerHTML);
const up = list.buttons.find(b => b.dataset.rank === "a<b" && b.dataset.dir === "up");
up.focus(); projects = ["a<b", "boise"]; renderRank(["a<b", "up"]);
seen.push([active.dataset.rank, active.dataset.dir]);
projects = ["boise", "a<b"]; renderRank();
seen.push([active.dataset.rank, active.dataset.dir]);
const before = list.buttons; renderRank(); seen.push(list.buttons === before);
delete els.rankList; renderRank(); seen.push("no throw");
console.log(JSON.stringify(seen));""")
        self.assertEqual(out[0], '<li class="note">No projects yet.</li>')
        self.assertEqual(out[1],
                         '<li><span class="rnum">1.</span><span class="rname">boise</span>'
                         '<button class="btn" type="button" data-rank="boise" data-dir="up" aria-label="Move boise up" disabled>↑</button>'
                         '<button class="btn" type="button" data-rank="boise" data-dir="down" aria-label="Move boise down">↓</button></li>'
                         '<li><span class="rnum">2.</span><span class="rname">a&lt;b</span>'
                         '<button class="btn" type="button" data-rank="a&lt;b" data-dir="up" aria-label="Move a&lt;b up">↑</button>'
                         '<button class="btn" type="button" data-rank="a&lt;b" data-dir="down" aria-label="Move a&lt;b down" disabled>↓</button></li>')
        self.assertEqual(out[2], ["a<b", "down"], "moved to the top: up is disabled, focus goes to its down button")
        self.assertEqual(out[3], ["a<b", "up"], "a poll re-render keeps focus on the same project")
        self.assertEqual(out[4:], [True, "no throw"], "an unchanged order leaves the rows alone; a missing list is fine")


if __name__ == "__main__":
    unittest.main()
