import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"

ACTIVE = {"name": "Ship <v2>", "phases": [
    {"n": 1, "title": "Base", "steps": [{"n": 1, "kind": "standard", "job": "001-a", "status": "done", "request": "Lay base"}]},
    {"n": 2, "title": "Grow", "steps": [
        {"n": 1, "kind": "bigboy", "job": "002-b", "status": "stopped", "request": "Build the <grid>"},
        {"n": 2, "kind": "standard", "job": None, "status": "todo", "request": "Polish it"},
        {"n": 3, "kind": "standard", "job": None, "status": "todo", "request": "Ship it"}]}],
    "current": {"p": 2, "s": 1}, "next": {"p": 2, "s": 2, "kind": "standard", "request": "Polish it"},
    "blocker": {"job": "002-b", "reason": "review: CHANGES"}}
DONE = {"name": "Old plan", "phases": [{"n": 1, "title": "Only", "steps": [
    {"n": 1, "kind": "standard", "job": "001-a", "status": "done", "request": "Do it"}]}],
    "current": None, "next": None, "blocker": None}

STUBS = """
const window = {}, localStorage = undefined;
const els = {};
const el = id => els[id] ??= {id, style: {}, dataset: {}, innerHTML: "", textContent: "", open: false,
  querySelector: () => null, querySelectorAll: () => [], showModal() { this.open = true; }};
const document = {activeElement: null, getElementById: el, querySelectorAll: () => []};
const fetched = [];
const fetch = async url => { fetched.push(url); return {ok: true, text: async () => "# Road <map>"}; };
"""


def run(tail, roadmaps, projects=("p", "q"), filt="", lane=""):
    """Run tail in node over dashboard.html from STAGES through render() plus show()/open()/openRoadmap(), with a stub DOM
    and fetch, `roadmaps` as the roadmap API results and no jobs. Prints whatever tail logs, one JSON per line."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    src = (text[text.index("const STAGES = "):text.index("function renderSelect(")]
           + text[text.index("async function show("):text.index("// Diverged bullets are read")])
    setup = (f"projects = {json.dumps(list(projects))}; roadmaps = {json.dumps(roadmaps)}; "
             f"filter = {json.dumps(filt)}; laneFilter = {json.dumps(lane)};\n")
    script = STUBS + src + "\n" + setup + f"(async () => {{ {tail} }})();"
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout
    return [json.loads(l) for l in out.splitlines()]


def cols(html):
    return re.findall(r'<section class="col[^"]*" data-col="([^"]+)"', html)


class RoadmapCard(unittest.TestCase):
    def test_card_shows_name_position_step_and_blocker(self):
        html, = run('render(); console.log(JSON.stringify(els.board.innerHTML));', {"p": ACTIVE, "q": None})
        self.assertNotIn("roadmap", cols(html))
        self.assertEqual(cols(html)[0], "spec")
        col = html[html.index('data-col="spec"'):html.index('data-col="build"')]
        self.assertEqual(col.count('class="card roadmap"'), 1, "step 002-b is not on the board, so the card waits in spec")
        self.assertIn("<span>· 1</span>", col, "the card counts in its column")
        # With the current step's job on the board, the card sits in that job's column, ahead of the job's own card.
        # card() is stubbed: its helpers sit outside the slice run() loads, and only the placement is under test.
        html, = run('card = j => `<i data-key="${j.key}"></i>`; jobs = [{id: "002-b", project: "p", key: "p/002-b", stage: "needs-human", title: "B", '
                    'updatedAt: "2026-10-01T00:00:00Z"}]; render(); console.log(JSON.stringify(els.board.innerHTML));',
                    {"p": ACTIVE, "q": None})
        col = html[html.index('data-col="needs-human"'):html.index('data-col="done"')]
        self.assertEqual(col.count('class="card roadmap"'), 1)
        self.assertLess(col.index('class="card roadmap"'), col.index('data-key="p/002-b"'))
        self.assertIn("<span>· 2</span>", col)
        self.assertNotIn('class="card roadmap"', html[html.index('data-col="spec"'):html.index('data-col="needs-human"')])
        card, = run('console.log(JSON.stringify(roadmapCard("p")));', {"p": ACTIVE})
        self.assertTrue(card.startswith('<button class="card roadmap" data-roadmap="p"'), card)
        for want in ('<span class="tag" data-project="p" style="--h:', '>p</span>', '<span class="lanechip">roadmap</span>',
                     'Ship &lt;v2&gt;', 'P2/2 Grow · S1/3', 'Build the &lt;grid&gt;', 'next: S2 Polish it',
                     'blocker: <b>002-b review: CHANGES</b>'):
            self.assertIn(want, card)
        # The next line names the phase only when it differs from the current one, as the banner did.
        other, = run('console.log(JSON.stringify(roadmapCard("p")));',
                     {"p": {**ACTIVE, "next": {"p": 3, "s": 1, "kind": "bigboy", "request": "Later"}, "blocker": None}})
        self.assertIn("next: P3 S1 Later", other)
        self.assertIn("blocker: none", other)
        self.assertNotIn("<b>", other)
        # Long text keeps its full value in a title, so the CSS ellipsis loses nothing.
        self.assertIn('title="Build the &lt;grid&gt;"', card)
        self.assertIn('title="blocker: 002-b review: CHANGES"', card)

    def test_done_roadmap_and_missing_roadmap(self):
        done, missing = run('console.log(JSON.stringify(roadmapCard("p"))); console.log(JSON.stringify(roadmapCard("q")));',
                            {"p": DONE, "q": None})
        self.assertIn("Old plan", done)
        self.assertIn(">done<", done)
        self.assertNotIn("next:", done)
        self.assertNotIn("blocker:", done)
        self.assertEqual(missing, "")
        html, = run('render(); console.log(JSON.stringify(els.board.innerHTML));', {"p": DONE, "q": None})
        self.assertNotIn("roadmap", cols(html))
        col = html[html.index('data-col="done"'):]
        self.assertEqual(col.count('class="card roadmap"'), 1, "a finished roadmap sits in done")
        self.assertNotIn('class="card roadmap"', html[:html.index('data-col="done"')])
        # The roadmap card is not one of the Done column's paged cards: 10 done jobs plus the card, no Load more.
        html, = run('card = j => `<i data-key="${j.key}"></i>`; jobs = Array.from({length: 10}, (_, i) => ({id: `00${i}-x`, project: "p", key: `p/00${i}-x`, '
                    'stage: "done", title: "x", updatedAt: "2026-10-01T00:00:00Z"})); render(); '
                    'console.log(JSON.stringify(els.board.innerHTML));', {"p": DONE, "q": None})
        col = html[html.index('data-col="done"'):]
        self.assertEqual(col.count('data-key="p/'), 10)
        self.assertNotIn("data-more", col)
        self.assertIn("<span>· 11</span>", col)
        html, = run('render(); console.log(JSON.stringify(els.board.innerHTML));', {"p": None, "q": None})
        self.assertNotIn("roadmap", cols(html))
        self.assertEqual(cols(html)[0], "spec")
        html, = run('render(); console.log(JSON.stringify(els.board.innerHTML));', {}, projects=())
        self.assertNotIn("roadmap", cols(html))

    def test_roadmap_cards_follow_project_and_lane_filter(self):
        both = {"p": ACTIVE, "q": DONE}
        self.assertEqual(run('console.log(JSON.stringify(roadmapShown()));', both), [["p", "q"]])
        self.assertEqual(run('console.log(JSON.stringify(roadmapShown()));', both, filt="q"), [["q"]])
        self.assertEqual(run('console.log(JSON.stringify(roadmapShown()));', both, lane="roadmap"), [["p", "q"]])
        for lane in ("fast", "standard", "debug", "bigboy", "runall", "lilguy"):
            self.assertEqual(run('console.log(JSON.stringify(roadmapShown()));', both, lane=lane), [[]], lane)
            html, = run('render(); console.log(JSON.stringify(els.board.innerHTML));', both, lane=lane)
            self.assertNotIn("roadmap", cols(html), lane)
        # Under the roadmap lane the step jobs still pass the job filter beside the card.
        text = DASHBOARD.read_text()
        self.assertIn('laneFilter === "roadmap" ? !!roadmapSteps[j.key]', text)

    def test_gold_theme_variable(self):
        text = DASHBOARD.read_text()
        root = text[text.index(":root{"):text.index("}", text.index(":root{"))]
        self.assertIn("--roadmap:var(--p5)", root)
        rule = re.search(r"\.card\.roadmap\{([^}]*)\}", text)
        self.assertIsNotNone(rule)
        self.assertIn("var(--roadmap)", rule.group(1))
        chip = re.search(r"\.card\.roadmap \.lanechip\{([^}]*)\}", text)
        self.assertIsNotNone(chip)
        self.assertIn("color:var(--roadmap)", chip.group(1))
        self.assertIn("border-color:var(--roadmap)", chip.group(1))
        self.assertNotRegex("".join(re.findall(r"\.card\.roadmap[^{]*\{[^}]*\}", text)), r"#[0-9a-fA-F]{3}")

    def test_roadmap_card_opens_viewer_with_roadmap_md(self):
        got, = run('openRoadmap("p"); await new Promise(r => setTimeout(r, 10)); console.log(JSON.stringify({'
                   'title: els.viewerTitle.textContent, tabs: els.tabs.innerHTML, doc: els.doc.innerHTML, '
                   'actions: els.actions.innerHTML, diverged: els.diverged.innerHTML, open: els.viewer.open, '
                   'key: els.viewer.dataset.key, fetched}));',
                   {"p": ACTIVE}, projects=("p",))
        self.assertEqual(got["title"], "Ship <v2>")
        self.assertTrue(got["open"])
        self.assertEqual(re.findall(r'<button data-file="([^"]+)"', got["tabs"]), ["roadmap.md"])
        self.assertIn('<button type="button" class="tag" data-project="p" style="--h:', got["tabs"])
        self.assertIn('aria-label="Change p colour">p</button>', got["tabs"])
        self.assertIn('class="close"', got["tabs"])
        self.assertEqual(got["fetched"], ["p/p/roadmap.md"])
        self.assertEqual(got["doc"], "<pre># Road &lt;map&gt;</pre>")
        self.assertEqual(got["actions"], "")
        self.assertEqual(got["diverged"], "")
        # A poll re-renders actions only for a board job key (project/id); this key is never one.
        self.assertEqual(got["key"], "p#roadmap")
        text = DASHBOARD.read_text()
        click = text[text.index('  const el = e.target.closest(".card");\n  if (el?.dataset.roadmap)'):]
        self.assertIn("openRoadmap(", click[:click.index("});")])

    def test_render_keeps_focus_on_roadmap_card(self):
        got, = run('let focused = null; document.activeElement = {matches: s => s.includes("data-roadmap"), dataset: {roadmap: "q"}}; '
                   '$("board").querySelectorAll = () => ["p", "q"].map(r => ({dataset: {roadmap: r}, focus() { focused = r; }})); '
                   'render(); console.log(JSON.stringify(focused));', {"p": ACTIVE, "q": DONE})
        self.assertEqual(got, "q")

    def test_banner_removed(self):
        text = DASHBOARD.read_text()
        for gone in ('id="roadmaps"', "function roadmapBanner(", ".rm{", "#roadmaps"):
            self.assertNotIn(gone, text)


if __name__ == "__main__":
    unittest.main()
