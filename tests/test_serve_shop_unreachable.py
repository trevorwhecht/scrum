"""Job 1650: shop_tick on a worker that drops mid-dispatch costs one failed ssh call, not one STEP_TIMEOUT per step.
Unlike test_serve_shop.py, the real shop.py runs here; only subprocess.run (the ssh) is faked."""
import subprocess, sys, unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import test_serve_shop as base  # noqa: E402

import shop  # noqa: E402
REAL = {n: getattr(shop, n) for n in base.SHOP_FNS}  # captured before any test replaces them


class UnreachableWorkerTest(base.ShopTickTest):
    def setUp(self):
        super().setUp()
        import shop
        shop._cache.clear()
        shop._ready.clear()
        self.addCleanup(shop._cache.clear)
        self.addCleanup(shop._ready.clear)
        p = mock.patch.multiple(self.serve.shop, **REAL)
        p.start()
        self.addCleanup(p.stop)

    def test_unreachable_worker_costs_one_bounded_call(self):
        self.workers("shopmac 2 owa,main\n")
        self.project("mm", self.runall({"id": "043-a"}))
        import shop
        tools = {t: True for t in shop.TOOLS}  # probe answered up a moment ago (UP_TTL), ready() not yet cached
        shop._cache["shopmac"] = (__import__("time").monotonic(), {"up": True, "load": 1.0, "tools": tools})
        calls = []

        def fake_run(argv, **kw):
            if argv and argv[0] == "ssh":
                calls.append(argv[1])
                raise subprocess.TimeoutExpired(argv, kw.get("timeout", 0))
            return subprocess.CompletedProcess(argv, 0, b"", b"")

        with mock.patch.object(subprocess, "run", side_effect=fake_run):
            got, _, _ = self.tick()
        self.assertFalse(got)
        self.assertLessEqual(calls.count("shopmac"), 1, calls)


for _n in dir(base.ShopTickTest):  # run only this file's tests, not the inherited ones
    if _n.startswith("test_"):
        setattr(UnreachableWorkerTest, _n, None)
del _n
