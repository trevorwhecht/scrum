import json, shutil, subprocess, unittest

from test_dashboard_roadmap_card import DASHBOARD, run

SIX = ["trevskills-scrum", "onewitharts", "trevorhecht-skills", "boisepartyco", "imessageHelper", "the-ritzy-mist-google"]


def hues(tail):
    """Run tail in node over dashboard.html's fnv1a, projectHue, projectHues and hue lines; returns its one JSON log."""
    node = shutil.which("node")
    if not node:
        raise unittest.SkipTest("node not on PATH")
    text = DASHBOARD.read_text()
    lines = [l for l in text.splitlines() if l.startswith(("const fnv1a = ", "let projectHue = ", "const hue = "))]
    start = text.index("function projectHues(")
    fn = text[start:text.index("\n}\n", start) + 2]
    script = "\n".join(lines) + "\n" + fn + f"\nconsole.log(JSON.stringify({tail}));"
    return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=10).stdout)


class ProjectHues(unittest.TestCase):
    def test_hues_distinct_and_order_independent(self):
        got = hues(f"[projectHues({json.dumps(SIX)}), projectHues({json.dumps(SIX[::-1])}), fnv1a('a'),"
                   f" (projectHue = projectHues({json.dumps(SIX)}), hue('trevskills-scrum'))]")
        fwd, rev, fa, read = got
        # FNV-1a 32-bit slots, probed in name order: boisepartyco 1, imessageHelper 7, onewitharts 5,
        # the-ritzy-mist-google 1 -> 2, trevorhecht-skills 4, trevskills-scrum 5 -> 6.
        self.assertEqual(fwd, {"boisepartyco": 30, "imessageHelper": 210, "onewitharts": 150,
                               "the-ritzy-mist-google": 60, "trevorhecht-skills": 120, "trevskills-scrum": 180})
        self.assertEqual(len(set(fwd.values())), 6)
        self.assertEqual(rev, fwd)
        self.assertEqual(fa, 3826002220, "fnv1a returns the uint32 FNV-1a hash")
        self.assertEqual(read, 180, "hue() reads the projectHue map, not the 150 fallback")

    def test_hue_falls_back_for_unknown_name(self):
        # fnv1a("a") = 3826002220, % 12 = 4, * 30 = 120.
        self.assertEqual(hues("hue('a')"), 120)

    def test_more_than_twelve_projects_terminates(self):
        names = [f"p{i}" for i in range(14)]
        got = hues(f"projectHues({json.dumps(names)})")
        self.assertEqual(sorted(got), sorted(names))
        self.assertTrue(all(h in range(0, 360, 30) for h in got.values()), got)
        self.assertEqual(len(set(got.values())), 12, "the first 12 fill every slot; the rest repeat")

    def test_poll_rebuilds_the_map(self):
        text = DASHBOARD.read_text()
        poll = text[text.index("async function poll()"):]
        poll = poll[:poll.index("\n}\n")]
        self.assertLess(poll.index("const list = await res.json()"), poll.index("projects = list.map(p => p.name)"))
        self.assertLess(poll.index("projects = list.map(p => p.name)"), poll.index("projectHue = projectHues(projects)"))
        self.assertIn("projectColour = Object.fromEntries(list.map(p => [p.name, p.colour ?? null]))", poll)

    def test_override_wins_over_auto_hue(self):
        text = DASHBOARD.read_text()
        tail = "\n".join(l for l in text.splitlines() if l.startswith(("const esc = ", "let projectColour = ", "const tagStyle = ", "const tag = ")))
        got = hues(f"(projectHue = projectHues({json.dumps(SIX)}), (() => {{ {tail}\n"
                   "projectColour = {'trevskills-scrum': 90, onewitharts: '#a1b2c3', boisepartyco: null};"
                   "return ['trevskills-scrum', 'onewitharts', 'boisepartyco', 'imessageHelper'].map(tag); })())")
        self.assertEqual(got, ['<span class="tag" data-project="trevskills-scrum" style="--h:90">trevskills-scrum</span>',
                               '<span class="tag" data-project="onewitharts" style="--h:150;--c:#a1b2c3">onewitharts</span>',
                               '<span class="tag" data-project="boisepartyco" style="--h:30">boisepartyco</span>',
                               '<span class="tag" data-project="imessageHelper" style="--h:210">imessageHelper</span>'])
        self.assertIn("background:var(--c,hsl(var(--h) 50% 42%))", text[text.index(".tag{"):text.index("}", text.index(".tag{"))],
                      "--c (a stored #rrggbb) beats the hue in the tag's CSS")


    def test_tag_button_markup(self):
        text = DASHBOARD.read_text()
        tail = "\n".join(l for l in text.splitlines() if l.startswith(("const esc = ", "let projectColour = ", "const tagStyle = ", "const tagButton = ")))
        got = hues(f"(projectHue = projectHues({json.dumps(SIX)}), (() => {{ {tail}\n"
                   "projectColour = {'trevskills-scrum': 90, onewitharts: '#a1b2c3'};"
                   "return ['trevskills-scrum', 'onewitharts', 'a<b'].map(tagButton); })())")
        self.assertEqual(got, ['<button type="button" class="tag" data-project="trevskills-scrum" style="--h:90" aria-label="Change trevskills-scrum colour">trevskills-scrum</button>',
                               '<button type="button" class="tag" data-project="onewitharts" style="--h:150;--c:#a1b2c3" aria-label="Change onewitharts colour">onewitharts</button>',
                               '<button type="button" class="tag" data-project="a&lt;b" style="--h:210" aria-label="Change a&lt;b colour">a&lt;b</button>'])

    def test_tag_hit_area_is_44px(self):
        text = DASHBOARD.read_text()
        self.assertIn(".tag[data-project]{position:relative}", text)
        self.assertIn('.tag[data-project]::after{content:"";position:absolute;left:50%;top:50%;width:max(100%,44px);height:44px;transform:translate(-50%,-50%)}', text)
        self.assertIn(".tag:focus-visible{outline:2px solid var(--accent)", text)

    def test_stale_colour_reply_leaves_reopened_dialog_alone(self):
        """Save on project a, close, open project b, then a's POST lands: b's dialog stays open with no error."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        src = text[text.index("function openColour("):text.index('$("colourSwatches").addEventListener')]
        script = """
const els = {}, $ = id => els[id] ??= {id, dataset: {}, textContent: "", open: false, showModal() { this.open = true; }, close() { this.open = false; }};
let projectColour = {}, painted = 0, settle;
const renderColour = () => {}, paintTags = () => painted++, enc = encodeURIComponent;
const post = () => new Promise((ok, no) => { settle = {ok, no}; });
""" + src + """
(async () => {
  const out = [];
  for (const fail of [false, true]) {
    openColour("a");
    const saving = saveColour(90);
    $("colour").close(); openColour("b");
    fail ? settle.no(new Error("boom")) : settle.ok({colour: 90});
    await saving;
    out.push([$("colour").open, $("colour").dataset.project, $("colourError").textContent, projectColour.a ?? null]);
    $("colour").close();
  }
  openColour("a");
  const saving = saveColour(30); settle.ok({colour: 30}); await saving;
  out.push([$("colour").open, projectColour.a, painted]);
  console.log(JSON.stringify(out));
})();
"""
        got = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True, timeout=10).stdout)
        self.assertEqual(got, [[True, "b", "", 90], [True, "b", "", 90], [False, 30, 2]])

class Header(unittest.TestCase):
    def test_header_has_no_counts(self):
        got, = run('render(); console.log(JSON.stringify(els.status.textContent));', {"p": None})
        self.assertEqual(got, "")
        none, = run('render(); console.log(JSON.stringify(els.status.textContent));', {}, projects=())
        self.assertEqual(none, "No projects yet. Run /trevskills-scrum in a repo and it shows up here.")


if __name__ == "__main__":
    unittest.main()
