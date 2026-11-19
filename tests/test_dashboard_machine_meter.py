import json, os, re, shutil, subprocess, unittest
from pathlib import Path

DASHBOARD = Path(__file__).resolve().parent.parent / "skills" / "trevskills-scrum" / "dashboard.html"
NOW = 1763460000  # 2025-11-18 10:00 UTC
S = {"min_free_ram_pct": 20, "max_swap_pct": 25, "min_free_disk_gb": 10, "max_cpu_busy_pct": 90,
     "max_cpu_load_pct": 150, "cpu_cores": 8}
CPU_NONE = ('<span class="ring none" role="img" style="--pct:0" aria-label="CPU load — of 8 cores · busy — · limit 150%" '
            'title="CPU load — of 8 cores · busy — · limit 150%">—</span><span class="lbl">CPU</span>')


def G(inner):
    """One meter group (This Mac, a shop Mac, Claude, Codex): groups sit side by side and stack as wholes when a row is narrow."""
    return f'<span class="grp">{inner}</span>'


def T(title, inner):
    """One titled group: its plain title (uppercased by CSS), a space, then its readings."""
    return G(f'<span class="ttl">{title}</span> {inner}')


def MAC(inner):
    return T("This Mac", inner)


def L(label="", line=""):
    """A ring's label stacked over its sparkline, beside the ring."""
    return f'<span class="lbl">{label}{line}</span>'


def acct(lvl, pct, text, cap=90, title=""):
    """One account's usage: its bar (fill pct, tick at cap), its reading, then its reset text (job 1225: three grid cells)."""
    read, _, reset = text.partition(" resets ")
    return (f'<span class="acct {lvl}"{f' title="{title}"' if title else ""}><span class="bar" style="--pct:{pct};--cap:{cap}"></span>'
            f' <span class="rd">{read}</span>' + (f' <span class="rs">resets {reset}</span>' if reset else "") + '</span>')


def spark(points):
    return (f'<svg class="spark" width="40" height="14" viewBox="0 0 40 14" aria-hidden="true"><polyline points="{points}"/></svg>')


def fn_body(text, name):
    start = text.index(f"function {name}(")
    return text[start:text.index("\n}\n", start) + 2]


def meter_globals(text):
    """renderMachine's globals: nothing focused, and no shop Mac's Cool down POST in flight (job 1185)."""
    line = lambda s: text[text.index(s):text.index("\n", text.index(s))]
    return "const document = {activeElement: null};\n" + line("const shopCoolPending = ") + "\n" + line("let machineLast = ") + "\n"


def cool(worker="shopmac"):
    """A shop Mac's own Cool down button, at the end of its group."""
    return f' <button class="btn" type="button" data-worker="{worker}" aria-label="Cool down {worker}">Cool down</button>'


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
        self.assertNotIn("usage.json", meter.group(0), "row 1 is the computers only: AI usage is row 2's hint")
        self.assertIn("read over ssh in the background at most every 30 s", meter.group(0), "the hint names the shop rings")
        self.assertIn("a grey — ring after a Shop title means that shop Mac did not answer", meter.group(0))
        self.assertIn("each group titled (This Mac, then Shop and the worker's name) and every ring labelled RAM or CPU", meter.group(0))
        self.assertIn("a sparkline of its last 30 minutes", meter.group(0), "the hint names the sparklines")
        ai = re.search(r'<button class="btn" id="aiUsage" type="button" hidden aria-haspopup="dialog"[^>]*>', header)
        self.assertIsNotNone(ai, "row 2 is a static button in <header>, hidden until it has something to show")
        self.assertIn("usage.json", ai.group(0), "the hint names the Claude bars' source")
        self.assertIn("Trevor's Play and Resume are never tapered", ai.group(0))
        self.assertIn("as in main 49% resets Sat 5 PM, each account's bar starting its reading with no · between", ai.group(0),
                      "the hint names the per-account usage reading with its reset")
        self.assertNotIn("Claude's 5h and 7d used %", ai.group(0), "the header has no Claude 5h reading")
        self.assertIn("a bar filled to its weekly used %, with a tick at its reserve", ai.group(0), "the hint names the usage bars")
        self.assertIn("Codex 5h and weekly used % and reset time, from the newest Codex rollout file", ai.group(0))
        self.assertIn("refreshed every 60 s", ai.group(0))
        self.assertIn("Opens the Usage dialog", ai.group(0))
        self.assertLess(header.index('id="machine"'), header.index('id="aiUsage"'), "row 1 sits above row 2")
        meters = header[header.index('<div id="meters">'):header.index('<div id="controls">')]
        self.assertIn('id="machine"', meters)
        self.assertIn('id="aiUsage"', meters)
        ra = fn_body(text, "renderActions")
        self.assertIn('''job.play_queued ? '<p class="note" role="status">queued, starts next</p>' : ""''', ra,
                      "the queued text is a neutral note drawn from the flag, so a re-render keeps it")
        self.assertIn('<p class="error" role="alert"></p>', ra, "the empty error slot stays for failed clicks")
        self.assertNotRegex(ra, r'role="alert">[^<]*queued')
        poll = fn_body(text, "poll")
        self.assertIn('getJson("api/machine", null).then(m => { renderMachine(m); renderAiUsage(m); renderCooldown(m); })', poll)
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
        script = (f"const $ = () => globalThis.el;\n{meter_globals(text)}{esc}\n{fn_body(text, 'machineLevel')}\n{fn_body(text, 'usagePart')}\n"
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
        self.assertEqual(out["ok"], [False, MAC('<span class="ring ok" role="img" style="--pct:66" aria-label="RAM 34% free · swap —" title="RAM 34% free · swap —">34%</span><span class="lbl">RAM</span> '
                                              + CPU_NONE + ' <span class="ok">disk 120 GB</span>')])
        self.assertEqual(out["bad"], MAC('<span class="ring danger" role="img" style="--pct:86" aria-label="RAM 14% free · swap 3%" title="RAM 14% free · swap 3%">14%</span><span class="lbl">RAM</span> '
                                       + CPU_NONE + ' <span class="ok">disk 50 GB</span>'), "the red ring already shows the RAM verdict")
        self.assertEqual(out["gone"], [False, '<span class="danger" title="Couldn\'t load machine status.">—</span>'])
        base = MAC('<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span><span class="lbl">RAM</span> ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>')
        self.assertEqual(out["use"], [base] * 4, "row 1 never shows Claude usage: that is row 2 (aiUsageHtml)")
        self.assertEqual(out["order"], MAC('<span class="ring danger" role="img" style="--pct:86" aria-label="RAM 14% free · swap 1%" title="RAM 14% free · swap 1%">14%</span><span class="lbl">RAM</span> '
                                           + CPU_NONE + ' <span class="ok">disk 100 GB</span>'))
        tail = ' ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>'
        self.assertEqual(out["rings"], [MAC('<span class="ring low" role="img" style="--pct:75" aria-label="RAM 25% free · swap 1%" title="RAM 25% free · swap 1%">25%</span><span class="lbl">RAM</span>' + tail),
                                        MAC('<span class="ring none" role="img" style="--pct:0" aria-label="RAM — · swap 1%" title="RAM — · swap 1%">—</span><span class="lbl">RAM</span>' + tail)])
        self.assertEqual(out["sessions"], base, "no trailing verdict text (Trevor 2026-11-18: it wrapped the meter)")
        self.assertEqual(out["swap"], MAC('<span class="ring danger" role="img" style="--pct:60" aria-label="RAM 40% free · swap 29%" title="RAM 40% free · swap 29%">40%</span><span class="lbl">RAM</span>'
                                        + ' ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>'), "swap has no text: it turns the ring red and sits in its tooltip")
        self.assertEqual(out["stale"], MAC('<span class="ring low" role="img" style="--pct:28" aria-label="RAM 72% free · swap 37%" title="RAM 72% free · swap 37%">72%</span><span class="lbl">RAM</span>'
                                         + ' ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>'), "stale swap past 25% with no swap verdict turns the ring yellow, not red")
        ring40 = '<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span><span class="lbl">RAM</span>'
        self.assertEqual(out["cpu"], MAC(ring40 + ' <span class="ring danger" role="img" style="--pct:100" aria-label="CPU load 168% of 8 cores · busy 51% · limit 150%" '
                                       'title="CPU load 168% of 8 cores · busy 51% · limit 150%">2x</span><span class="lbl">CPU</span> <span class="ok">disk 100 GB</span>'),
                         "the red CPU ring already shows the CPU verdict")
        self.assertEqual(out["cpuNear"], MAC(ring40 + ' <span class="ring low" role="img" style="--pct:100" aria-label="CPU load 145% of 8 cores · busy — · limit 150%" '
                                           'title="CPU load 145% of 8 cores · busy — · limit 150%">1x</span><span class="lbl">CPU</span> <span class="ok">disk 100 GB</span>'))

        self.assertEqual(out["disk"], MAC(ring40 + ' ' + CPU_NONE + ' <span class="danger">disk 8 GB, launches wait for 10 GB free</span>'),
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
        script = (f"const $ = () => globalThis.el;\n{meter_globals(text)}{esc}\n{fn_body(text, 'machineLevel')}\n{fn_body(text, 'usagePart')}\n"
                  f"{fn_body(text, 'renderMachine')}\n"
                  f"const s = {json.dumps(S)};\n"
                  "globalThis.el = {hidden: false, innerHTML: ''};\n"
                  f"renderMachine({{...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: null, server: {json.dumps(slow)}}});\n"
                  "console.log(JSON.stringify(el.innerHTML));")
        out = json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True).stdout)
        base = MAC('<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span><span class="lbl">RAM</span> '
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
        hint = re.search(r'<button class="btn" id="aiUsage"[^>]*>', text).group(0)
        self.assertRegex(hint, r'Fable[^"]*65%[^"]*75%[^"]*80%[^"]*85%')

    def node_meter(self, body):
        """Runs `body` after the meter's functions, with the clock at NOW (2025-11-18 10:00 UTC) in TZ=UTC."""
        node = shutil.which("node")
        if not node:
            raise unittest.SkipTest("node not on PATH")
        text = DASHBOARD.read_text()
        esc = text[text.index("const esc = "):text.index("\n", text.index("const esc = "))]
        ago = text[text.index("const ago = "):text.index("\n};\n", text.index("const ago = ")) + 3]
        script = (f"Date.now = () => {NOW} * 1000;\nconst $ = () => globalThis.el;\nglobalThis.el = {{hidden: false, innerHTML: ''}};\n"
                  f"{meter_globals(text)}{esc}\n{ago}\n" + "".join(fn_body(text, f) + "\n" for f in ("machineLevel", "heldUntilText", "resetText", "usagePart",
                                                                                         "aiUsageHtml", "renderMachine"))
                  + f"const s = {json.dumps(S)};\n{body}")
        return json.loads(subprocess.run([node, "-e", script], capture_output=True, text=True, check=True,
                                         env={**os.environ, "TZ": "UTC"}).stdout)

    def test_machine_meter_usage_per_account(self):
        """Row 2's Claude group: each account's bar, then its name, % and visible reset day and time."""
        reset = NOW + 4 * 3600 + 300  # Tue 14:05
        main = {"name": "main", "seven_day_pct": 49, "resets_at": reset, "max_pct": 90}
        owa = {"name": "owa", "seven_day_pct": 90, "resets_at": NOW + 86000, "max_pct": 90}
        cases = [{"accounts": [main, owa], "allowance": None, "fable": "ok", "hold_until": None},
                 {"accounts": [{**main, "seven_day_pct": 80}, {**owa, "seven_day_pct": 79.4}], "allowance": None},
                 {"accounts": [{**main, "seven_day_pct": 95}, {**owa, "seven_day_pct": None, "resets_at": None}],
                  "allowance": 0, "hold_until": reset, "fable": "paused"},
                 {"accounts": [{**main, "max_pct": 85, "seven_day_pct": 75.2, "name": "<b>"}], "allowance": 2},
                 {"accounts": [{**main, "seven_day_pct": 104.4}], "allowance": None}]
        out = self.node_meter(f"console.log(JSON.stringify({json.dumps(cases)}.map(u => aiUsageHtml(u))));")
        main_r, owa_r = "resets Tue 2:05 PM", "resets Wed 9:53 AM"
        self.assertEqual(out, [T("Claude", x) for x in (
            # Parts are joined by a space, never a "·", so no separator is left dangling at a line end when the group wraps.
            acct("ok", 49, f"main 49% {main_r}", title="resets 14:05") + " " + acct("danger", 90, f"owa 90% {owa_r}", title="resets 09:53"),
            acct("low", 80, f"main 80% {main_r}", title="resets 14:05") + " " + acct("ok", 79, f"owa 79% {owa_r}", title="resets 09:53"),
            acct("danger", 95, f"main 95% {main_r}", title="resets 14:05") + " " + acct("ok", 0, "owa —")
            + ' <span class="danger">held until 14:05</span> <span class="danger">Fable paused, using Opus</span>',
            acct("low", 75, f"&lt;b&gt; 75% {main_r}", cap=85, title="resets 14:05") + ' <span class="low">allowance 2</span>',
            acct("danger", 100, f"main 104% {main_r}", title="resets 14:05"))])

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
        mac = MAC(ring("ok", 60, "40%", "RAM 40% free · swap 1%") + L("RAM") + " " + CPU_NONE + ' <span class="ok">disk 100 GB</span>')
        shop = T("Shop shopmac", ring("ok", 59, "41%", "Shop shopmac RAM 41% free · read 40s ago") + L("RAM") + " "
                 + ring("ok", 63, "63%", "Shop shopmac CPU load 63% of 4 cores · read 40s ago") + L("CPU") + cool())
        self.assertEqual(out, [
            mac + shop,
            mac + T("Shop shopmac", ring("none", 0, "—", "Shop shopmac unreachable · checked 40s ago") + L() + cool()),
            mac + T("Shop shopmac", ring("danger", 86, "14%", "Shop shopmac RAM 14% free · read 40s ago") + L("RAM") + " "
                    + ring("danger", 100, "2x", "Shop shopmac CPU load 168% of 4 cores · read 40s ago") + L("CPU") + cool()),
            mac + T("Shop shopmac", ring("none", 0, "—", "Shop shopmac RAM — · read 40s ago") + L("RAM") + " "
                    + ring("ok", 63, "63%", "Shop shopmac CPU load 63% of 4 cores · read 40s ago") + L("CPU") + cool()),
            mac + shop + T("Shop mac2", ring("none", 0, "—", "Shop mac2 unreachable · checked 40s ago") + L() + cool("mac2")),
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
        plain = MAC(ram + L("RAM") + " " + cpu + L("CPU") + disk)
        self.assertEqual(out, [
            MAC(ram + L("RAM", spark("0,8.2 20,5.8 40,3.4")) + " " + cpu + L("CPU", spark("0,10.6 40,1")) + disk)
            + T("Shop shopmac", ring("ok", 50, "50%", "Shop shopmac RAM 50% free · read 40s ago") + L("RAM", spark("0,7 40,7")) + " "
                + ring("ok", 10, "10%", "Shop shopmac CPU load 10% of 4 cores · read 40s ago") + L("CPU") + cool()),
            plain, plain, plain])

    def hog_meter(self, cases):
        """renderMachine's innerHTML for each case's hogs value ('missing' leaves the key out)."""
        return self.node_meter(f"console.log(JSON.stringify({json.dumps(cases)}.map(h => {{\n"
                               "  const m = {...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: null};\n"
                               "  if (h !== 'missing') m.hogs = h;\n"
                               "  renderMachine(m); return el.innerHTML; })));")

    METER = MAC('<span class="ring ok" role="img" style="--pct:60" aria-label="RAM 40% free · swap 1%" title="RAM 40% free · swap 1%">40%</span>'
                '<span class="lbl">RAM</span> ' + CPU_NONE + ' <span class="ok">disk 100 GB</span>')

    def test_machine_meter_hogs(self):
        """Job 1179: one line per CPU hog (serve.py report_hogs) after the meter groups, in list order; a missing name or
        pct shows —."""
        hog = lambda name, pct: f'<span class="hog"><span class="hogname" title="{name}">{name}</span> {pct} CPU</span>'
        out = self.hog_meter([[{"name": "python3", "pid": 4242, "pct": 180, "minutes": 12}],
                              [{"name": "b", "pid": 2, "pct": 300, "minutes": 11}, {"name": "a", "pid": 1, "pct": 120, "minutes": 10}],
                              [{"pid": 3, "pct": 150, "minutes": 10}, {"name": "x", "pid": 4, "minutes": 10},
                               {"name": None, "pid": 5, "pct": None, "minutes": 10}, {"name": "", "pid": 6, "pct": "x"}]])
        self.assertEqual(out, [self.METER + hog("python3", "180%"),
                               self.METER + hog("b", "300%") + hog("a", "120%"),
                               self.METER + hog("—", "150%") + hog("x", "—") + hog("—", "—") + hog("—", "—")])
        for bad in ("undefined", "null", "NaN"):
            self.assertNotIn(bad, out[2])
        text = DASHBOARD.read_text()
        meter = re.search(r'<span id="machine"[^>]*>', text).group(0)
        for phrase in ("outside the scrum", "over one core for 10+ minutes", "reported only, never stopped"):
            self.assertIn(phrase, meter)

    def test_machine_meter_no_hogs(self):
        out = self.hog_meter([[], "missing", None, "python3", {"name": "x", "pct": 150}])
        self.assertEqual(out, [self.METER] * 5, "no hogs: the meter is exactly as before")

    def test_machine_meter_long_hog_name(self):
        name = "Google Chrome Helper (Renderer) & Tools for Very Long Names!"
        self.assertEqual(len(name), 60)
        out = self.hog_meter([[{"name": name, "pid": 4242, "pct": 210, "minutes": 10}]])
        shown = name.replace("&", "&amp;")
        self.assertEqual(out, [self.METER + f'<span class="hog"><span class="hogname" title="{shown}">{shown}</span> 210% CPU</span>'])
        text = DASHBOARD.read_text()
        cut = re.search(r"#meters \.hogname\{[^}]*\}", text)
        self.assertIsNotNone(cut)
        for rule in ("max-width:24ch", "overflow:hidden", "text-overflow:ellipsis", "white-space:nowrap"):
            self.assertIn(rule, cut.group(0), "a long name ends in …, its full text in the title")
        line = re.search(r"#meters \.hog\{[^}]*\}", text)
        self.assertIsNotNone(line)
        self.assertIn("display:block", line.group(0), "each hog on its own line under the groups")

    def test_machine_meter_group_titles(self):
        """Row 1's groups each start with a plain title: This Mac, then Shop and the worker's name (escaped), even with
        one worker; the title is uppercased by CSS in the muted colour, so the markup keeps the name as configured."""
        at = NOW - 40
        bad = {"name": "<b>", "free_ram_pct": 41, "cpu_load_pct": 62.5, "cpu_cores": 4, "at": at}
        out = self.node_meter("renderMachine({...s, free_ram_pct: 40, swap_pct: 1, free_disk_gb: 100, verdict: null, "
                              f"shop: [{json.dumps(bad)}]}}); console.log(JSON.stringify(el.innerHTML));")
        self.assertTrue(out.startswith('<span class="grp"><span class="ttl">This Mac</span> <span class="ring ok"'), out)
        self.assertIn('<span class="grp"><span class="ttl">Shop &lt;b&gt;</span> <span class="ring ok" role="img" style="--pct:59" '
                      'aria-label="Shop &lt;b&gt; RAM 41% free · read 40s ago"', out)
        self.assertNotIn("<b>", out)
        self.assertEqual(out.count('<span class="lbl">RAM</span>'), 2, out)
        self.assertEqual(out.count('<span class="lbl">CPU</span>'), 2, out)
        text = DASHBOARD.read_text()
        ttl = re.search(r"#meters \.ttl\{[^}]*\}", text)
        self.assertIsNotNone(ttl)
        self.assertIn("text-transform:uppercase", ttl.group(0))
        self.assertIn("color:var(--muted)", ttl.group(0))

    def test_reset_text(self):
        """Weekday, 12-hour time (minutes only off the hour) and AM/PM from the local Date getters; "" for no reset."""
        out = self.node_meter("console.log(JSON.stringify([1763830800, 1763474700, 1763424000, 1763467200, null, undefined, "
                              "'1763830800', NaN].map(resetText)));")
        self.assertEqual(out, ["Sat 5 PM", "Tue 2:05 PM", "Tue 12 AM", "Tue 12 PM", "", "", "", ""])

    def test_ai_usage_row(self):
        """Row 2: a Claude group (the per-account bars) then a Codex group (5h and week bars in the same markup, ticked at
        routing.json's limit); undefined status (first routing poll pending) has no Codex group, null shows its error."""
        main = {"name": "main", "seven_day_pct": 49, "resets_at": 1763830800, "max_pct": 90}
        claude = {"accounts": [main], "allowance": None, "fable": "ok", "hold_until": None}
        held = {"accounts": [main], "allowance": 0, "hold_until": NOW + 3600, "fable": "warn"}
        codex = lambda five, week, r5=1763474700, rw=1763830800, lim=(85, 90): {
            "codex": {"5h": five, "weekly": week, "5h_resets_at": r5, "weekly_resets_at": rw},
            "codex_limits": {"5h": lim[0], "weekly": lim[1]}}
        cases = [[claude, codex(42, 17)], [held, codex(85, 76, lim=(85, 86))], [None, codex(90, 30, lim=(None, None))],
                 [None, codex(None, 12.6, r5=None)], [claude, None], ["unknown", None],
                 [{**claude, "accounts": [{**main, "name": "<b>", "resets_at": None}]}, None], [None, None], [None, {}]]
        cases_js = json.dumps(cases).replace("[null, null]", "[null, undefined]")
        out = self.node_meter(f"console.log(JSON.stringify({cases_js}.map(([c, st]) => aiUsageHtml(c, st))));")
        cl = T("Claude", acct("ok", 49, "main 49% resets Sat 5 PM", title="resets Sat 17:00"))
        err = T("Codex", '<span class="danger" title="Couldn\'t load usage.">—</span>')
        self.assertEqual(out, [
            cl + T("Codex", acct("ok", 42, "5h 42% resets Tue 2:05 PM", cap=85) + " " + acct("ok", 17, "week 17% resets Sat 5 PM")),
            T("Claude", acct("ok", 49, "main 49% resets Sat 5 PM", title="resets Sat 17:00")
              + ' <span class="danger">held until 11:00</span> <span class="low">Fable near limit</span>')
            + T("Codex", acct("danger", 85, "5h 85% resets Tue 2:05 PM", cap=85) + " " + acct("low", 76, "week 76% resets Sat 5 PM", cap=86)),
            T("Codex", acct("ok", 90, "5h 90% resets Tue 2:05 PM", cap=100) + " " + acct("ok", 30, "week 30% resets Sat 5 PM", cap=100)),
            T("Codex", acct("ok", 0, "5h —", cap=85) + " " + acct("ok", 13, "week 13% resets Sat 5 PM")),
            cl + err,
            T("Claude", '<span class="ok">usage: unknown</span>') + err,
            T("Claude", acct("ok", 49, "&lt;b&gt; 49%")) + err,
            "",
            T("Codex", acct("ok", 0, "5h —", cap=100) + " " + acct("ok", 0, "week —", cap=100))])

    def test_machine_meter_colours_are_theme_variables(self):
        text = DASHBOARD.read_text()
        css = re.findall(r"#(?:meters|machine|aiUsage)[^{]*\{[^}]*\}", text)
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
            self.assertRegex(text, rf"#meters \.acct\.{lvl},#meters \.ring\.{lvl}\{{--ring:", "a usage bar (both rows share one rule) fills in its level's ring colour")
        bar = re.search(r"#meters \.bar\{[^}]*\}", text)
        self.assertIsNotNone(bar)
        self.assertIn("var(--ring) calc(var(--pct) * 1%)", bar.group(0), "the fill is the weekly used %")
        tick = re.search(r"#meters \.bar::after\{[^}]*\}", text)
        self.assertIsNotNone(tick, "a tick marks the account's cap")
        self.assertIn("left:calc(var(--cap) * 1%)", tick.group(0))
        self.assertIn("var(--ink)", tick.group(0))
        self.assertIn("#meters .spark polyline{fill:none;stroke:currentColor", text, "the sparkline takes the meter's text colour")
        self.assertIn("#meters .grp>span:not(.ring,.lbl){display:inline-block}", text,
                      "a reading such as disk 35 GB or an account's bar and label wraps as a whole, never mid-text")
        lbl = re.search(r"#meters \.lbl\{[^}]*\}", text)
        self.assertIsNotNone(lbl)
        self.assertIn("display:inline-grid", lbl.group(0), "the label sits over the sparkline")
        size = re.search(r"#meters \.ring\{[^}]*width:(\d+)px;height:(\d+)px", text)
        self.assertIsNotNone(size)
        self.assertLessEqual(max(int(size.group(1)), int(size.group(2))), 32, "room for the % inside, still fits the header")


if __name__ == "__main__":
    unittest.main()
