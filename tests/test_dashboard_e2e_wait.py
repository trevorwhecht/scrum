"""A Check job that has waited over 2 h on the E2E queue says how long, and who holds the lock, on its status line."""
import unittest

from test_dashboard_build_lock_wait import status

BASE = {"stage": "check", "updatedAt": "2026-01-01T00:00:00Z"}
WAIT = {"waitSecs": 7800, "holder": {"job": "1225", "pid": 4242, "ageSecs": 11100}}


class E2eWait(unittest.TestCase):
    def test_wait_and_holder(self):
        self.assertEqual(status({**BASE, "e2eWait": WAIT}), "Waiting for the E2E queue 2h 10m, held by 1225 for 3h 05m")

    def test_no_holder(self):
        self.assertEqual(status({**BASE, "e2eWait": {**WAIT, "holder": None}}), "Waiting for the E2E queue 2h 10m")

    def test_wins_over_build_lock_line(self):
        self.assertEqual(status({**BASE, "e2eWait": WAIT, "buildLockWait": True}),
                         "Waiting for the E2E queue 2h 10m, held by 1225 for 3h 05m")

    def test_other_cases_keep_their_line(self):
        self.assertEqual(status({**BASE, "buildLockWait": True}), "Waiting for the build lock")
        self.assertEqual(status({**BASE, "e2eWait": WAIT, "paused": True}), "Paused by you")
        self.assertRegex(status(BASE), r"^Checking, \d+ min$")


if __name__ == "__main__":
    unittest.main()
