import json, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"
S = {"min_free_ram_pct": 20, "max_swap_pct": 25, "min_free_disk_gb": 10, "max_cpu_busy_pct": 90}
CPU_NONE = ('<span class="ring none" role="img" style="--pct:0" aria-label="CPU busy — · limit 90%" '
            'title="CPU busy — · limit 90%">—</span> CPU')


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
        self.assertRegex(meter.group(0), r'data-agent-hint="[^"]*20%[^"]*25%[^"]*10 GB[^"]*90%')
        self.assertIn("averaged over the last 3 watchdog readings", meter.group(0), "the hint names the CPU reading's window")
        self.assertIn("share of CPU time busy across all cores (0-100%", meter.group(0))
        for gone in ("5-min", "load average", "150%", "pass 100"):
            self.assertNotIn(gone, meter.group(0), "the hint no longer describes the load-average ring")
        self.assertIn("usage.json", meter.group(0), "the hint names the usage segment's source")
        self.assertIn("Trevor's Play and Resume are never tapered", meter.group(0))
        ra = fn_body(text, "renderActions")
        self.assertIn('''job.play_queued ? '<p class="note" role="status">queued, starts next</p>' : ""''', ra,
                      "the queued text is a neutral note drawn from the flag, so a re-render keeps it")
        self.assertIn('<p class="error" role="alert"></p>', ra, "the empty error slot stays for failed clicks")
        self.assertNotRegex(ra, r'role="alert">[^<]*queued')
        poll = fn_body(text, "poll")
        self.assertIn('getJson("api/machine", null).then(m => { renderMachine(m); renderCooldown(m); })', poll)
        self.assertLess(poll.index('api/machine'), poll.index('fetch("api/projects"'),
                        "fetched before anything that can return early, on every poll")
        render = fn_body(text, "renderMachine")
        self.assertIn("el.hidden = !m", render, "a failed or 404 fetch (null) hides the meter")
        self.assertIn("if (!el) return", render, "tolerates a missing element")
        self.assertIn('"—"', render)
        self.assertEqual(render.count('class="ring '), 1, "RAM and CPU rings share one ring helper")

    def test_machine_meter_levels(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        cases = [[14, "ram"], [25, "ram"], [40, "ram"], [30, "swap"], [20, "swap"], [5, "swap"],
                 [5, "disk"], [15, "disk"], [100, "disk"], [None, "ram"],
                 [95, "cpu"], [85, "cpu"], [90, "cpu"], [80, "cpu"], [40, "cpu"], [None, "cpu"]]
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
                  "const rings = [25, null].map(v => { renderMachine({...s, free_ram_pct: v, swap_pct: 1, free_disk_gb: 100, verdict: null});\n"
                  "                                  return el.innerHTML; });\n"
                  "renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: '15 sessions running (ceiling 14)'});\n"
                  "const sessions = el.innerHTML;\n"
                  "renderMachine({...s, free_ram_pct: 40, swap_pct: 29.3, free_disk_gb: 100, verdict: 'swap used 29.3% of RAM (> 25%)'});\n"
                  "const swap = el.innerHTML;\n"
                  "renderMachine({...s, free_ram_pct: 72, swap_pct: 37.1, free_disk_gb: 100, verdict: null});\n"
                  "const stale = el.innerHTML;\n"
                  "renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, cpu_busy_pct: 95.4, verdict: 'CPU busy 95% (> 90%)'});\n"
                  "const cpu = el.innerHTML;\n"
                  "renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, cpu_busy_pct: 84.6, verdict: null});\n"
                  "const cpuNear = el.innerHTML;\n"
                  "renderMachine(null);\n"
                  "console.log(JSON.stringify({levels, ok, bad, gone: el.hidden, use, order, rings, sessions, swap, stale, cpu, cpuNear}));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out["levels"], ["danger", "low", "ok", "danger", "low", "ok", "danger", "low", "ok", "ok",
                                         "danger", "low", "low", "ok", "ok", "none"])
        self.assertEqual(out["ok"], [False, '<span class="ring ok" role="img" style="--pct:66" aria-label="RAM 34% free · swap —" title="RAM 34% free · swap —">34%</span> RAM · '
                                            + CPU_NONE + ' · <span class="ok">disk 120 GB</span>'])
        self.assertEqual(out["bad"], '<span class="ring danger" role="img" style="--pct:86" aria-label="RAM 14% free · swap 3%" title="RAM 14% free · swap 3%">14%</span> RAM · '
                                     + CPU_NONE + ' · <span class="ok">disk 50 GB</span>', "the red ring already shows the RAM verdict")
        self.assertTrue(out["gone"])
        base = '<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span> RAM · ' + CPU_NONE + ' · <span class="ok">disk 100 GB</span> · '
        self.assertEqual(out["use"], [base + '<span class="low">5h 93% · 7d 40% · allowance 1</span>',
                                      base + '<span class="danger">5h 100% · 7d — · allowance 0</span>',
                                      base + '<span class="ok">5h — · 7d 12%</span>',
                                      base + '<span class="ok">usage: unknown</span>'])
        self.assertEqual(out["order"], '<span class="ring danger" role="img" style="--pct:86" aria-label="RAM 14% free · swap 1%" title="RAM 14% free · swap 1%">14%</span> RAM · '
                                       + CPU_NONE + ' · <span class="ok">disk 100 GB</span> · <span class="ok">usage: unknown</span>')
        tail = ' · ' + CPU_NONE + ' · <span class="ok">disk 100 GB</span>'
        self.assertEqual(out["rings"], ['<span class="ring low" role="img" style="--pct:75" aria-label="RAM 25% free · swap 1%" title="RAM 25% free · swap 1%">25%</span> RAM' + tail,
                                        '<span class="ring none" role="img" style="--pct:0" aria-label="RAM — · swap 1%" title="RAM — · swap 1%">—</span> RAM' + tail])
        self.assertEqual(out["sessions"], base + '<span class="danger">15 sessions running (ceiling 14)</span>',
                         "a verdict that repeats no shown reading stays, after the usage segment")
        self.assertEqual(out["swap"], '<span class="ring danger" role="img" style="--pct:60" aria-label="RAM 40% free · swap 29%" title="RAM 40% free · swap 29%">40%</span> RAM'
                         + ' · ' + CPU_NONE + ' · <span class="ok">disk 100 GB</span>', "swap has no text: it turns the ring red and sits in its tooltip")
        self.assertEqual(out["stale"], '<span class="ring low" role="img" style="--pct:28" aria-label="RAM 72% free · swap 37%" title="RAM 72% free · swap 37%">72%</span> RAM'
                         + ' · ' + CPU_NONE + ' · <span class="ok">disk 100 GB</span>', "stale swap past 25% with no swap verdict turns the ring yellow, not red")
        ring40 = '<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span> RAM'
        self.assertEqual(out["cpu"], ring40 + ' · <span class="ring danger" role="img" style="--pct:95" aria-label="CPU busy 95% · limit 90%" '
                         'title="CPU busy 95% · limit 90%">95%</span> CPU · <span class="ok">disk 100 GB</span>',
                         "the red CPU ring already shows the CPU verdict")
        self.assertEqual(out["cpuNear"], ring40 + ' · <span class="ring low" role="img" style="--pct:85" aria-label="CPU busy 85% · limit 90%" '
                         'title="CPU busy 85% · limit 90%">85%</span> CPU · <span class="ok">disk 100 GB</span>')

    def test_machine_meter_fable_text(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        u = {"five_hour_pct": 70, "seven_day_pct": 20, "five_hour_resets_at": 1, "allowance": None}
        cases = [{**u, "fable": "warn"}, {**u, "fable": "paused"}, {**u, "fable": "ok"}, u, {**u, "fable": "unknown"},
                 "unknown"]
        script = (f"{esc}\n{fn_body(text, 'usagePart')}\n"
                  f"console.log(JSON.stringify({json.dumps(cases)}.map(usagePart)));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        plain = '<span class="ok">5h 70% · 7d 20%</span>'
        self.assertEqual(out, [plain + ' · <span class="low">Fable near limit</span>',
                               plain + ' · <span class="danger">Fable paused, using Opus</span>',
                               plain, plain, plain, '<span class="ok">usage: unknown</span>'])
        meter = re.search(r'<span id="machine"[^>]*>', text).group(0)
        self.assertRegex(meter, r'Fable[^"]*65%[^"]*75%[^"]*80%[^"]*85%')

    def test_machine_meter_colours_are_theme_variables(self):
        text = DASHBOARD.read_text()
        css = re.findall(r"#machine[^{]*\{[^}]*\}", text)
        self.assertTrue(css)
        self.assertIn("var(--human)", " ".join(css))
        self.assertNotRegex(" ".join(css), r"#[0-9a-fA-F]{3,6}\b|\bwhite\b")
        ring = " ".join(c for c in css if ".ring" in c)
        self.assertIn("conic-gradient(", ring)
        self.assertIn("var(--pct)", ring)
        for want in (".ring.ok{--ring:var(--pass)}", ".ring.low{--ring:var(--p5)}", ".ring.danger{--ring:var(--human)}",
                     ".ring.none{--ring:var(--pending)}"):
            self.assertIn(want, text)
        size = re.search(r"#machine \.ring\{[^}]*width:(\d+)px;height:(\d+)px", text)
        self.assertIsNotNone(size)
        self.assertLessEqual(max(int(size.group(1)), int(size.group(2))), 32, "room for the % inside, still fits the header")


if __name__ == "__main__":
    unittest.main()
