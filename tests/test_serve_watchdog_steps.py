"""Job 1429: watchdog_tick times its steps (a slow one is named on stderr), and pulse_tick runs from pulse_loop's own
60 s timer instead of inside the tick, so a blocked tick step never delays stuck_alert."""
import io, sys, threading, unittest
from unittest import mock

import test_serve  # noqa: F401  its import-time env pins (SCRUM_PS, SCRUM_FREE_RAM, ...) apply first
import serve


class TimedStepTest(unittest.TestCase):
    def run_step(self, seconds):
        ticks = iter([100.0, 100.0 + seconds])
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            got = serve.timed_step("cloud_tick", lambda a, b=0: a + b, 1, b=2, clock=lambda: next(ticks))
        return got, err.getvalue()

    def test_slow_step_is_named(self):
        got, err = self.run_step(31)
        self.assertEqual(got, 3)
        self.assertEqual(err, "watchdog: slow step cloud_tick 31s\n")

    def test_fast_step_logs_nothing(self):
        got, err = self.run_step(30)
        self.assertEqual((got, err), (3, ""))

    def test_exception_passes_through_and_is_still_timed(self):
        ticks = iter([0.0, 45.0])

        def boom():
            raise ValueError("x")
        with mock.patch("sys.stderr", new=io.StringIO()) as err, self.assertRaises(ValueError):
            serve.timed_step("auto_resume", boom, clock=lambda: next(ticks))
        self.assertEqual(err.getvalue(), "watchdog: slow step auto_resume 45s\n")


class TimeStepsTest(unittest.TestCase):
    def test_wrapped_step_logs_when_slow_and_keeps_result(self):
        def cloud_tick(a, b=0):
            """doc"""
            return a + b
        scope = {"cloud_tick": cloud_tick}
        serve.time_steps(("cloud_tick", "missing"), scope)
        serve.time_steps(("cloud_tick",), scope)  # twice wraps once
        self.assertIs(scope["cloud_tick"].__wrapped__, cloud_tick)
        self.assertEqual(scope["cloud_tick"].__doc__, "doc")
        ticks = iter([0.0, 40.0])
        with mock.patch.object(serve.time, "monotonic", side_effect=lambda: next(ticks)), \
                mock.patch("sys.stderr", new=io.StringIO()) as err:
            self.assertEqual(scope["cloud_tick"](1, b=2), 3)
        self.assertEqual(err.getvalue(), "watchdog: slow step cloud_tick 40s\n")

    def test_every_timed_step_exists_and_is_wrapped(self):
        for name in serve.TIMED_STEPS:
            self.assertTrue(getattr(serve, name).timed, name)


class PulseTimerTest(unittest.TestCase):
    def test_tick_does_not_run_pulse_and_publishes_busy(self):
        serve.PULSE_BUSY.clear()
        self.addCleanup(serve.PULSE_BUSY.clear)
        with mock.patch.object(serve.board, "projects", return_value={}), \
                mock.patch.object(serve, "pulse_tick") as pulse, \
                mock.patch.multiple(serve, window_tick=mock.DEFAULT, weekly_tick=mock.DEFAULT, cooldown_chime=mock.DEFAULT,
                                    idle_cleanup=mock.DEFAULT, stop_leftovers=mock.DEFAULT, stop_two_sessions=mock.DEFAULT,
                                    stop_same_tests=mock.DEFAULT, report_hogs=mock.DEFAULT, e2e_lock_reap=mock.DEFAULT,
                                    write_shop_room=mock.DEFAULT, agent_links_tick=mock.DEFAULT, hot_stop_tick=mock.DEFAULT,
                                    hard_stop_tick=mock.DEFAULT, auto_continue_tick=mock.DEFAULT), \
                mock.patch.object(serve.board, "record_cpu_sample"), mock.patch("sys.stderr", new=io.StringIO()):
            serve.watchdog_tick()
        pulse.assert_not_called()

    def test_pulse_loop_runs_pulse_tick_with_the_published_busy(self):
        serve.PULSE_BUSY.clear()
        serve.PULSE_BUSY.update({"p": True})
        self.addCleanup(serve.PULSE_BUSY.clear)
        calls = []
        with mock.patch.object(serve, "pulse_tick", side_effect=lambda busy: calls.append(busy)), \
                mock.patch.object(serve.time, "sleep", side_effect=StopIteration) as sleep:
            with self.assertRaises(StopIteration):
                serve.pulse_loop()
        self.assertEqual(calls, [{"p": True}])
        sleep.assert_called_once_with(60)

    def test_pulse_loop_survives_a_failing_pulse(self):
        sleeps = []

        def sleep(_):
            sleeps.append(1)
            if len(sleeps) == 2:
                raise StopIteration
        with mock.patch.object(serve, "pulse_tick", side_effect=RuntimeError("bad")) as pulse, \
                mock.patch.object(serve.time, "sleep", side_effect=sleep), mock.patch("sys.stderr", new=io.StringIO()) as err:
            with self.assertRaises(StopIteration):
                serve.pulse_loop()
        self.assertEqual(pulse.call_count, 2)
        self.assertIn("watchdog: pulse: bad", err.getvalue())


class PulseLockTest(unittest.TestCase):
    """Job 1447: PULSE_LOCK guards PULSE_BUSY (watchdog_tick publishes, pulse_loop snapshots) and PULSE_HOLDS
    (note_hold writes, pulse_tick reads), which live on two threads since job 1429."""

    def setUp(self):
        busy, holds = serve.PULSE_BUSY, serve.PULSE_HOLDS
        busy.clear()
        holds.clear()
        self.addCleanup(busy.clear)
        self.addCleanup(holds.clear)
        self.addCleanup(lambda: (self.assertIs(serve.PULSE_BUSY, busy), self.assertIs(serve.PULSE_HOLDS, holds)))

    def test_busy_publish_holds_lock(self):
        started = threading.Event()

        def publish():
            started.set()
            serve.publish_busy({"app": True, "lib": False})
        serve.PULSE_BUSY.update({"old": True})
        with serve.PULSE_LOCK:
            t = threading.Thread(target=publish, daemon=True)
            t.start()
            self.assertTrue(started.wait(30))
            t.join(0.5)
            self.assertTrue(t.is_alive())  # blocked on the lock this test holds
            self.assertEqual(serve.PULSE_BUSY, {"old": True})
        t.join(30)
        self.assertFalse(t.is_alive())
        self.assertEqual(serve.PULSE_BUSY, {"app": True, "lib": False})

    def test_watchdog_tick_publishes_through_publish_busy(self):
        with mock.patch.object(serve.board, "projects", return_value={}), \
                mock.patch.object(serve, "publish_busy") as publish, \
                mock.patch.multiple(serve, window_tick=mock.DEFAULT, weekly_tick=mock.DEFAULT, cooldown_chime=mock.DEFAULT,
                                    idle_cleanup=mock.DEFAULT, stop_leftovers=mock.DEFAULT, stop_two_sessions=mock.DEFAULT,
                                    stop_same_tests=mock.DEFAULT, report_hogs=mock.DEFAULT, e2e_lock_reap=mock.DEFAULT,
                                    write_shop_room=mock.DEFAULT, agent_links_tick=mock.DEFAULT, hot_stop_tick=mock.DEFAULT,
                                    hard_stop_tick=mock.DEFAULT, auto_continue_tick=mock.DEFAULT), \
                mock.patch.object(serve.board, "record_cpu_sample"), mock.patch("sys.stderr", new=io.StringIO()):
            serve.watchdog_tick()
        publish.assert_called_once_with({})

    def test_pulse_snapshot_never_empty(self):
        """pulse_loop's snapshot, run 20000 times against a thread republishing the same full map, never sees it empty
        or half built. A tiny switch interval makes the GIL hand over between clear() and update() often."""
        full = {f"p{i}": bool(i % 2) for i in range(50)}
        serve.publish_busy(full)
        old = sys.getswitchinterval()
        sys.setswitchinterval(1e-6)
        self.addCleanup(sys.setswitchinterval, old)
        stop = threading.Event()

        def publisher():
            while not stop.is_set():
                serve.publish_busy(full)
        t = threading.Thread(target=publisher, daemon=True)
        t.start()
        self.addCleanup(t.join, 30)
        self.addCleanup(stop.set)
        snaps, sleeps = [], []

        def sleep(_):
            sleeps.append(1)
            if len(sleeps) == 20000:
                raise StopIteration
        with mock.patch.object(serve, "pulse_tick", side_effect=snaps.append), \
                mock.patch.object(serve.time, "sleep", side_effect=sleep):
            with self.assertRaises(StopIteration):
                serve.pulse_loop()
        self.assertEqual(len(snaps), 20000)
        bad = [len(s) for s in snaps if s != full]
        self.assertEqual((len(bad), bad[:5]), (0, []))  # count and the first few bad snapshot sizes


class PulseHoldsRaceTest(unittest.TestCase):
    """Job 1447: a hold note_hold adds from another thread while pulse_tick reads the project's holds never makes its
    gates None. PulseTest's fixture (two projects, fake readings) is reused."""
    NOW = test_serve.PulseTest.NOW
    setUp = test_serve.PulseTest.setUp
    lines = test_serve.PulseTest.lines

    def test_pulse_holds_mutation_during_gates(self):
        s = self.serve
        root = (self.base / "app" / "scrum").resolve()
        s.PULSE_HOLDS.clear()
        self.addCleanup(s.PULSE_HOLDS.clear)
        added = []

        class Stamp(float):
            """A hold time that, when pulse_tick's gates step reads it, has a thread note a new hold for the project."""
            def __rsub__(self, now):
                t = threading.Thread(target=lambda: (s.note_hold(root, "mid_gates"), added.append(1)), daemon=True)
                t.start()
                t.join(30)
                return 0.0
        s.PULSE_HOLDS[root] = {"before": Stamp(self.NOW)}
        with mock.patch("sys.stderr", new=io.StringIO()) as err:
            s.pulse_tick({}, now=self.NOW)
        self.assertEqual(added, [1])  # note_hold finished while pulse_tick was mid-iteration (not blocked on the lock)
        self.assertNotIn("gates:", err.getvalue())
        self.assertEqual(self.lines()[-1]["projects"]["app"]["gates"], ["held:before"])
        self.assertEqual(set(s.PULSE_HOLDS[root]), {"before", "mid_gates"})


if __name__ == "__main__":
    unittest.main()
