import json, os, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"
NOW = 1763460000  # 2025-11-18 10:00 UTC
S = {"min_free_ram_pct": 20, "max_swap_pct": 25, "min_free_disk_gb": 10, "max_cpu_busy_pct": 90,
     "max_cpu_load_pct": 150, "cpu_cores": 8}
CPU_NONE = ('<span class="ring none" role="img" style="--pct:0" aria-label="CPU load — of 8 cores · busy — · limit 150%" '
            'title="CPU load — of 8 cores · busy — · limit 150%">—</span><span class="lbl">CPU</span>')


def G(inner):
    """One meter group (This Mac, a shop Mac, usage): groups sit side by side and stack as wholes when the meter is narrow."""
    return f'<span class="grp">{inner}</span>'


def L(label="", line=""):
    """A ring's label stacked over its sparkline, beside the ring."""
    return f'<span class="lbl">{label}{line}</span>'


def acct(lvl, pct, text, cap=90, title=""):
    """One account's usage: its bar (fill pct, tick at cap) and its label."""
    return (f'<span class="acct {lvl}"{f' title="{title}"' if title else ""}><span class="bar" style="--pct:{pct};--cap:{cap}"></span>'
            f' {text}</span>')


def spark(points):
    return (f'<svg class="spark" width="40" height="14" viewBox="0 0 40 14" aria-hidden="true"><polyline points="{points}"/></svg>')


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
        self.assertRegex(meter.group(0), r'data-agent-hint="[^"]*20%[^"]*25%[^"]*10 GB[^"]*300%')
        self.assertIn("5-minute load average", meter.group(0), "the hint names the CPU ring's reading")
        self.assertIn("of all cores", meter.group(0))
        self.assertIn("usage.json", meter.group(0), "the hint names the usage segment's source")
        self.assertIn("Trevor's Play and Resume are never tapered", meter.group(0))
        self.assertIn("as in main 49% owa 90%, each account's bar starting its reading with no · between", meter.group(0),
                      "the hint names the per-account usage segment")
        self.assertNotIn("Claude's 5h and 7d used %", meter.group(0), "the header has no 5h reading")
        self.assertIn("read over ssh in the background at most every 30 s", meter.group(0), "the hint names the shop rings")
        self.assertIn("grey Shop —", meter.group(0))
        self.assertIn("a bar filled to its weekly used %, with a tick at its reserve", meter.group(0), "the hint names the usage bars")
        self.assertIn("a sparkline of its last 30 minutes", meter.group(0), "the hint names the sparklines")
        ra = fn_body(text, "renderActions")
        self.assertIn('''job.play_queued ? '<p class="note" role="status">queued, starts next</p>' : ""''', ra,
                      "the queued text is a neutral note drawn from the flag, so a re-render keeps it")
        self.assertIn('<p class="error" role="alert"></p>', ra, "the empty error slot stays for failed clicks")
        self.assertNotRegex(ra, r'role="alert">[^<]*queued')
        poll = fn_body(text, "poll")
        self.assertIn('getJson("api/machine", null).then(m => { renderMachine(m); renderCooldown(m); })', poll)
        self.assertLess(poll.index('api/machine'), poll.index('timed("api/projects"'),
                        "fetched before anything that can return early, on every poll")
        render = fn_body(text, "renderMachine")
        self.assertIn("el.hidden = false", render, "a failed or 404 fetch (null) keeps the meter, showing —")
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
                 [160, "cpu"], [145, "cpu"], [150, "cpu"], [140, "cpu"], [40, "cpu"], [None, "cpu"]]
        script = (f"const $ = () => globalThis.el;\n{esc}\n{fn_body(text, 'machineLevel')}\n{fn_body(text, 'usagePart')}\n"
                  f"{fn_body(text, 'renderMachine')}\n"
                  f"const s = {json.dumps(S)};\n"
                  f"const levels = {json.dumps(cases)}.map(([v, k]) => machineLevel(v, k, s));\n"
                  "globalThis.el = {hidden: false, innerHTML: ''};\n"
                  "renderMachine({...s, free_ram_pct: 34.4, swap_pct: null, free_disk_gb: 120.2, verdict: null});\n"
                  "const ok = [el.hidden, el.innerHTML];\n"
                  "renderMachine({...s, free_ram_pct: 14, swap_pct: 3, free_disk_gb: 50, verdict: 'free RAM 14% (< 20%)'});\n"
                  "const bad = el.innerHTML;\n"
                  "const acc = v => [{name: 'main', seven_day_pct: v, resets_at: null, max_pct: 90}];\n"
                  "const use = [{accounts: acc(40), allowance: 1}, {accounts: acc(null), allowance: 0},\n"
                  "  {accounts: acc(12), allowance: null}, 'unknown']\n"
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
                  "renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, cpu_load_pct: 168.4, cpu_busy_pct: 51, verdict: 'CPU load 168% of 8 cores (> 150%)'});\n"
                  "const cpu = el.innerHTML;\n"
                  "renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, cpu_load_pct: 144.6, verdict: null});\n"
                  "const cpuNear = el.innerHTML;\n"
                  "renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 8.1, verdict: 'free disk 8.1 GB (< 10 GB)'});\n"
                  "const disk = el.innerHTML;\n"
                  "renderMachine(null);\n"
                  "console.log(JSON.stringify({levels, ok, bad, gone: [el.hidden, el.innerHTML], use, order, rings, sessions, swap, stale, cpu, cpuNear, disk}));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        self.assertEqual(out["levels"], ["danger", "low", "ok", "danger", "low", "ok", "danger", "low", "ok", "ok",
                                         "danger", "low", "low", "ok", "ok", "none"])
        self.assertEqual(out["ok"], [False, G('<span class="ring ok" role="img" style="--pct:66" aria-label="RAM 34% free · swap —" title="RAM 34% free · swap —">34%</span><span class="lbl">RAM</span> '
                                              + CPU_NONE + ' <span class="ok">disk 120 GB</span>')])
        self.assertEqual(out["bad"], G('<span class="ring danger" role="img" style="--pct:86" aria-label="RAM 14% free · swap 3%" title="RAM 14% free · swap 3%">14%</span><span class="lbl">RAM</span> '
                                       + CPU_NONE + ' <span class="ok">disk 50 GB</span>'), "the red ring already shows the RAM verdict")
        self.assertEqual(out["gone"], [False, '<span class="danger" title="Couldn\'t load machine status.">—</span>'])
        base = G('<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span><span class="lbl">RAM</span> ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>')
        self.assertEqual(out["use"], [base + G(acct("ok", 40, "main 40%") + ' <span class="low">allowance 1</span>'),
                                      base + G(acct("ok", 0, "main —") + ' <span class="danger">allowance 0</span>'),
                                      base + G(acct("ok", 12, "main 12%")),
                                      base + G('<span class="ok">usage: unknown</span>')])
        self.assertEqual(out["order"], G('<span class="ring danger" role="img" style="--pct:86" aria-label="RAM 14% free · swap 1%" title="RAM 14% free · swap 1%">14%</span><span class="lbl">RAM</span> '
                                         + CPU_NONE + ' <span class="ok">disk 100 GB</span>') + G('<span class="ok">usage: unknown</span>'))
        tail = ' ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>'
        self.assertEqual(out["rings"], [G('<span class="ring low" role="img" style="--pct:75" aria-label="RAM 25% free · swap 1%" title="RAM 25% free · swap 1%">25%</span><span class="lbl">RAM</span>' + tail),
                                        G('<span class="ring none" role="img" style="--pct:0" aria-label="RAM — · swap 1%" title="RAM — · swap 1%">—</span><span class="lbl">RAM</span>' + tail)])
        self.assertEqual(out["sessions"], base, "no trailing verdict text (Trevor 2026-11-18: it wrapped the meter)")
        self.assertEqual(out["swap"], G('<span class="ring danger" role="img" style="--pct:60" aria-label="RAM 40% free · swap 29%" title="RAM 40% free · swap 29%">40%</span><span class="lbl">RAM</span>'
                                        + ' ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>'), "swap has no text: it turns the ring red and sits in its tooltip")
        self.assertEqual(out["stale"], G('<span class="ring low" role="img" style="--pct:28" aria-label="RAM 72% free · swap 37%" title="RAM 72% free · swap 37%">72%</span><span class="lbl">RAM</span>'
                                         + ' ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>'), "stale swap past 25% with no swap verdict turns the ring yellow, not red")
        ring40 = '<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span><span class="lbl">RAM</span>'
        self.assertEqual(out["cpu"], G(ring40 + ' <span class="ring danger" role="img" style="--pct:100" aria-label="CPU load 168% of 8 cores · busy 51% · limit 150%" '
                                       'title="CPU load 168% of 8 cores · busy 51% · limit 150%">2x</span><span class="lbl">CPU</span> <span class="ok">disk 100 GB</span>'),
                         "the red CPU ring already shows the CPU verdict")
        self.assertEqual(out["cpuNear"], G(ring40 + ' <span class="ring low" role="img" style="--pct:100" aria-label="CPU load 145% of 8 cores · busy — · limit 150%" '
                                           'title="CPU load 145% of 8 cores · busy — · limit 150%">1x</span><span class="lbl">CPU</span> <span class="ok">disk 100 GB</span>'))

        self.assertEqual(out["disk"], G(ring40 + ' ' + CPU_NONE + ' <span class="danger">disk 8 GB, launches wait for 10 GB free</span>'),
                         "a red disk reading says launches wait on it and names the limit")
        meter = re.search(r'<span id="machine"[^>]*>', text).group(0)
        self.assertIn("launches wait for 10 GB free", meter, "the hint names the disk segment's wait text")

    def test_machine_meter_no_server_slow(self):
        text = DASHBOARD.read_text()
        meter = re.search(r'<span id="machine"[^>]*>', text).group(0)
        self.assertNotIn("Server slow", meter)
        self.assertNotIn("Trailing red text", meter)
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        slow = {"routes": {"GET /a": {"p95_ms": 2400, "count": 9}}, "disconnects": 3, "slow": True, "worst": "GET /a"}
        script = (f"const $ = () => globalThis.el;\n{esc}\n{fn_body(text, 'machineLevel')}\n{fn_body(text, 'usagePart')}\n"
                  f"{fn_body(text, 'renderMachine')}\n"
                  f"const s = {json.dumps(S)};\n"
                  "globalThis.el = {hidden: false, innerHTML: ''};\n"
                  f"renderMachine({{...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: null, server: {json.dumps(slow)}}});\n"
                  "console.log(JSON.stringify(el.innerHTML));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        base = G('<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span><span class="lbl">RAM</span> '
                 + CPU_NONE + ' <span class="ok">disk 100 GB</span>')
        self.assertEqual(out, base, "an old server's slow flag adds no text to the meter")

    def test_machine_meter_fable_text(self):
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        u = {"accounts": [{"name": "main", "seven_day_pct": 20, "resets_at": None, "max_pct": 90}], "allowance": None}
        cases = [{**u, "fable": "warn"}, {**u, "fable": "paused"}, {**u, "fable": "ok"}, u, {**u, "fable": "unknown"},
                 "unknown"]
        script = (f"{esc}\n{fn_body(text, 'usagePart')}\n"
                  f"console.log(JSON.stringify({json.dumps(cases)}.map(usagePart)));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        plain = acct("ok", 20, "main 20%")
        self.assertEqual(out, [plain + ' <span class="low">Fable near limit</span>',
                               plain + ' <span class="danger">Fable paused, using Opus</span>',
                               plain, plain, plain, '<span class="ok">usage: unknown</span>'])
        meter = re.search(r'<span id="machine"[^>]*>', text).group(0)
        self.assertRegex(meter, r'Fable[^"]*65%[^"]*75%[^"]*80%[^"]*85%')

    def node_meter(self, body):
        """Runs `body` after the meter's functions, with the clock at NOW (2025-11-18 10:00 UTC) in TZ=UTC."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        ago = text[text.index("const ago = "):text.index("\n};\n", text.index("const ago = ")) + 3]
        script = (f"Date.now = () => {NOW} * 1000;\nconst $ = () => globalThis.el;\nglobalThis.el = {{hidden: false, innerHTML: ''}};\n"
                  f"{esc}\n{ago}\n" + "".join(fn_body(text, f) + "\n" for f in ("machineLevel", "heldUntilText", "usagePart", "renderMachine"))
                  + f"const s = {json.dumps(S)};\n{body}")
        return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True,
                                         env={**os.environ, "TZ": "UTC"}).stdout)

    def test_machine_meter_usage_per_account(self):
        reset = NOW + 4 * 3600 + 300  # 14:05
        main = {"name": "main", "seven_day_pct": 49, "resets_at": reset, "max_pct": 90}
        owa = {"name": "owa", "seven_day_pct": 90, "resets_at": NOW + 86000, "max_pct": 90}
        cases = [{"accounts": [main, owa], "allowance": None, "fable": "ok", "hold_until": None},
                 {"accounts": [{**main, "seven_day_pct": 80}, {**owa, "seven_day_pct": 79.4}], "allowance": None},
                 {"accounts": [{**main, "seven_day_pct": 95}, {**owa, "seven_day_pct": None, "resets_at": None}],
                  "allowance": 0, "hold_until": reset, "fable": "paused"},
                 {"accounts": [{**main, "max_pct": 85, "seven_day_pct": 75.2, "name": "<b>"}], "allowance": 2},
                 {"accounts": [{**main, "seven_day_pct": 104.4}], "allowance": None}]
        out = self.node_meter(f"console.log(JSON.stringify({json.dumps(cases)}.map(usagePart)));")
        self.assertEqual(out, [
            # Parts are joined by a space, never a "·", so no separator is left dangling at a line end when the group wraps.
            acct("ok", 49, "main 49%", title="resets 14:05") + " " + acct("danger", 90, "owa 90%", title="resets 09:53"),
            acct("low", 80, "main 80%", title="resets 14:05") + " " + acct("ok", 79, "owa 79%", title="resets 09:53"),
            acct("danger", 95, "main 95%", title="resets 14:05") + " " + acct("ok", 0, "owa —")
            + ' <span class="danger">held until 14:05</span> <span class="danger">Fable paused, using Opus</span>',
            acct("low", 75, "&lt;b&gt; 75%", cap=85, title="resets 14:05") + ' <span class="low">allowance 2</span>',
            acct("danger", 100, "main 104%", title="resets 14:05")])

    def test_machine_meter_shop_rings(self):
        at = NOW - 40
        up = {"name": "shopmac", "free_ram_pct": 41, "cpu_load_pct": 62.5, "cpu_cores": 4, "at": at}
        down = {"name": "shopmac", "free_ram_pct": None, "cpu_load_pct": None, "cpu_cores": None, "at": at}
        cases = [[up], [down], [{**up, "free_ram_pct": 14, "cpu_load_pct": 168.4}],
                 [{**up, "free_ram_pct": None}], [up, {**down, "name": "mac2"}], [], None]
        out = self.node_meter(f"console.log(JSON.stringify({json.dumps(cases)}.map(shop => {{\n"
                              "  const m = {...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: null};\n"
                              "  if (shop) m.shop = shop;\n"
                              "  renderMachine(m); return el.innerHTML; })));")
        ring = lambda lvl, pct, text, tip: f'<span class="ring {lvl}" role="img" style="--pct:{pct}" aria-label="{tip}" title="{tip}">{text}</span>'
        mac = G(ring("ok", 60, "40%", "RAM 40% free · swap 1%") + L("RAM") + " " + CPU_NONE + ' <span class="ok">disk 100 GB</span>')
        shop = (ring("ok", 59, "41%", "Shop RAM 41% free · read 40s ago") + L()
                + ring("ok", 63, "63%", "Shop CPU load 63% of 4 cores · read 40s ago") + L("Shop"))
        self.assertEqual(out, [
            mac + G(shop),
            mac + G(ring("none", 0, "—", "Shop unreachable · checked 40s ago") + L("Shop")),
            mac + G(ring("danger", 86, "14%", "Shop RAM 14% free · read 40s ago") + L()
                    + ring("danger", 100, "2x", "Shop CPU load 168% of 4 cores · read 40s ago") + L("Shop")),
            mac + G(ring("none", 0, "—", "Shop RAM — · read 40s ago") + L()
                    + ring("ok", 63, "63%", "Shop CPU load 63% of 4 cores · read 40s ago") + L("Shop")),
            mac + G(shop.replace("Shop", "Shop shopmac")) + G(ring("none", 0, "—", "Shop mac2 unreachable · checked 40s ago") + L("Shop mac2")),
            mac, mac])

    def test_machine_meter_sparklines(self):
        """A 40x14 line of each ring's last 30 min beside it, under its label, scaled 0-100 (CPU: to its peak past 100):
        RAM plots RAM in use, as the ring's arc does; a gap is skipped; fewer than 2 readings draw none."""
        at = NOW - 40
        up = {"name": "shopmac", "free_ram_pct": 50, "cpu_load_pct": 10, "cpu_cores": 4, "at": at,
              "history": {"free_ram_pct": [50, 50], "cpu_load_pct": [None, 10]}}
        cases = [{"history": {"free_ram_pct": [60, 40, None, 20], "cpu_load_pct": [50, 250]}, "shop": [up]},
                 {"history": {"free_ram_pct": [40], "cpu_load_pct": []}},
                 {"history": {"free_ram_pct": [None, None], "cpu_load_pct": None}},
                 {"history": None}]
        out = self.node_meter(f"console.log(JSON.stringify({json.dumps(cases)}.map(c => {{\n"
                              "  renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, cpu_load_pct: 50, verdict: null, ...c});\n"
                              "  return el.innerHTML; })));")
        ring = lambda lvl, pct, text, tip: f'<span class="ring {lvl}" role="img" style="--pct:{pct}" aria-label="{tip}" title="{tip}">{text}</span>'
        ram = ring("ok", 60, "40%", "RAM 40% free · swap 1%")
        cpu = ring("ok", 50, "50%", "CPU load 50% of 8 cores · busy — · limit 150%")
        disk = ' <span class="ok">disk 100 GB</span>'
        plain = G(ram + L("RAM") + " " + cpu + L("CPU") + disk)
        self.assertEqual(out, [
            G(ram + L("RAM", spark("0,8.2 20,5.8 40,3.4")) + " " + cpu + L("CPU", spark("0,10.6 40,1")) + disk)
            + G(ring("ok", 50, "50%", "Shop RAM 50% free · read 40s ago") + L("", spark("0,7 40,7"))
                + ring("ok", 10, "10%", "Shop CPU load 10% of 4 cores · read 40s ago") + L("Shop")),
            plain, plain, plain])

    def test_machine_meter_colours_are_theme_variables(self):
        text = DASHBOARD.read_text()
        css = re.findall(r"#machine[^{]*\{[^}]*\}", text)
        self.assertTrue(css)
        self.assertIn("var(--human)", " ".join(css))
        self.assertNotRegex(" ".join(css), r"#[0-9a-fA-F]{3,6}\b|\bwhite\b(?!-space)")  # white-space is not a colour
        ring = " ".join(c for c in css if ".ring" in c)
        self.assertIn("conic-gradient(", ring)
        self.assertIn("var(--pct)", ring)
        for want in (".ring.ok{--ring:var(--pass)}", ".ring.low{--ring:var(--p5)}", ".ring.danger{--ring:var(--human)}",
                     ".ring.none{--ring:var(--pending)}"):
            self.assertIn(want, text)
        for lvl in ("ok", "low", "danger"):
            self.assertRegex(text, rf"#machine \.acct\.{lvl},#machine \.ring\.{lvl}\{{--ring:", "a usage bar fills in its level's ring colour")
        bar = re.search(r"#machine \.bar\{[^}]*\}", text)
        self.assertIsNotNone(bar)
        self.assertIn("var(--ring) calc(var(--pct) * 1%)", bar.group(0), "the fill is the weekly used %")
        tick = re.search(r"#machine \.bar::after\{[^}]*\}", text)
        self.assertIsNotNone(tick, "a tick marks the account's cap")
        self.assertIn("left:calc(var(--cap) * 1%)", tick.group(0))
        self.assertIn("var(--ink)", tick.group(0))
        self.assertIn("#machine .spark polyline{fill:none;stroke:currentColor", text, "the sparkline takes the meter's text colour")
        self.assertIn("#machine .grp>span:not(.ring,.lbl){display:inline-block}", text,
                      "a reading such as disk 35 GB or an account's bar and label wraps as a whole, never mid-text")
        lbl = re.search(r"#machine \.lbl\{[^}]*\}", text)
        self.assertIsNotNone(lbl)
        self.assertIn("display:inline-grid", lbl.group(0), "the label sits over the sparkline")
        size = re.search(r"#machine \.ring\{[^}]*width:(\d+)px;height:(\d+)px", text)
        self.assertIsNotNone(size)
        self.assertLessEqual(max(int(size.group(1)), int(size.group(2))), 32, "room for the % inside, still fits the header")


if __name__ == "__main__":
    unittest.main()
