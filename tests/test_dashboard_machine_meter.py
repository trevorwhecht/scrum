import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"
S = {"min_free_ram_pct": 20, "max_swap_pct": 25, "min_free_disk_gb": 10}


def fn_body(text, name):
    start = text.index(f"function {name}(")
    return text[start:text.index("\n}\n", start) + 2]


class MachineMeter(unittest.TestCase):
    def test_machine_meter_markup_and_poll(self):
        text = DASHBOARD.read_text()
        header = text[text.index("<header>"):text.index("</header>")]
        meter = re.search(r'<span id="machine"[^>]*>', header)
        self.assertIsNotNone(meter, "the meter sits in <header>")
        self.assertIn(" hidden", meter.group(0), "hidden until the first good fetch")
        self.assertRegex(meter.group(0), r'data-agent-hint="[^"]*20%[^"]*25%[^"]*10 GB')
        self.assertIn("usage.json", meter.group(0), "the hint names the usage segment's source")
        self.assertIn("Trevor's Play and Resume are never tapered", meter.group(0))
        self.assertIn('${job.play_queued ? "queued, starts next" : ""}', fn_body(text, "renderActions"),
                      "the queued text is drawn from the flag, so a re-render keeps it")
        poll = fn_body(text, "poll")
        self.assertIn('getJson("api/machine", null).then(renderMachine)', poll)
        self.assertLess(poll.index('api/machine'), poll.index('fetch("api/projects"'),
                        "fetched before anything that can return early, on every poll")
        render = fn_body(text, "renderMachine")
        self.assertIn("el.hidden = !m", render, "a failed or 404 fetch (null) hides the meter")
        self.assertIn("if (!el) return", render, "tolerates a missing element")
        self.assertIn('"—"', render)

    def test_machine_meter_levels(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        cases = [[14, "ram"], [25, "ram"], [40, "ram"], [30, "swap"], [20, "swap"], [5, "swap"],
                 [5, "disk"], [15, "disk"], [100, "disk"], [None, "ram"]]
        script = (f"const $ = () => globalThis.el;\n{esc}\n{fn_body(text, 'machineLevel')}\n{fn_body(text, 'usagePart')}\n"
                  f"{fn_body(text, 'renderMachine')}\n"
                  f"const s = {json.dumps(S)};\n"
                  f"const levels = {json.dumps(cases)}.map(([v, k]) => machineLevel(v, k, s));\n"
                  "globalThis.el = {hidden: false, innerHTML: ''};\n"
                  "renderMachine({...s, free_ram_pct: 34.4, swap_pct: null, free_disk_gb: 120.2, verdict: null});\n"
                  "const ok = [el.hidden, el.innerHTML];\n"
                  "renderMachine({...s, free_ram_pct: 14, swap_pct: 3, free_disk_gb: 50, verdict: 'free RAM 14% (< 20%)'});\n"
                  "const bad = el.innerHTML;\n"
                  "const use = [{five_hour_pct: 93, seven_day_pct: 40, five_hour_resets_at: 1, allowance: 1},\n"
                  "  {five_hour_pct: 99.6, seven_day_pct: null, five_hour_resets_at: 1, allowance: 0},\n"
                  "  {five_hour_pct: null, seven_day_pct: 12, five_hour_resets_at: null, allowance: null}, 'unknown']\n"
                  "  .map(u => { renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: null, usage: u});\n"
                  "              return el.innerHTML; });\n"
                  "renderMachine({...s, free_ram_pct: 14, swap_pct: 1, free_disk_gb: 100, verdict: 'free RAM 14% (< 20%)', usage: 'unknown'});\n"
                  "const order = el.innerHTML;\n"
                  "renderMachine(null);\n"
                  "console.log(JSON.stringify({levels, ok, bad, gone: el.hidden, use, order}));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out["levels"], ["danger", "low", "ok", "danger", "low", "ok", "danger", "low", "ok", "ok"])
        self.assertEqual(out["ok"], [False, '<span class="ok">RAM 34% free</span> · <span class="ok">swap —</span> · '
                                            '<span class="ok">disk 120 GB</span>'])
        self.assertEqual(out["bad"], '<span class="danger">RAM 14% free</span> · <span class="ok">swap 3%</span> · '
                                     '<span class="ok">disk 50 GB</span> · <span class="danger">free RAM 14% (&lt; 20%)</span>')
        self.assertTrue(out["gone"])
        base = '<span class="ok">RAM 40% free</span> · <span class="ok">swap 1%</span> · <span class="ok">disk 100 GB</span> · '
        self.assertEqual(out["use"], [base + '<span class="low">5h 93% · 7d 40% · allowance 1</span>',
                                      base + '<span class="danger">5h 100% · 7d — · allowance 0</span>',
                                      base + '<span class="ok">5h — · 7d 12%</span>',
                                      base + '<span class="ok">usage: unknown</span>'])
        self.assertEqual(out["order"], '<span class="danger">RAM 14% free</span> · <span class="ok">swap 1%</span> · '
                                       '<span class="ok">disk 100 GB</span> · <span class="ok">usage: unknown</span> · '
                                       '<span class="danger">free RAM 14% (&lt; 20%)</span>', "usage sits before the verdict")

    def test_machine_meter_colours_are_theme_variables(self):
        text = DASHBOARD.read_text()
        css = re.findall(r"#machine[^{]*\{[^}]*\}", text)
        self.assertTrue(css)
        self.assertIn("var(--human)", " ".join(css))
        self.assertNotRegex(" ".join(css), r"#[0-9a-fA-F]{3,6}\b|\bwhite\b")


if __name__ == "__main__":
    unittest.main()
