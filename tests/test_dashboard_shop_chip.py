"""A job with a `shop` pid ran on the shop Mac: its card stays highlighted (class shop) with a Shop chip in every column,
and reads "Running on shop Mac" only while it is in stage cloud. Cloud without `shop` looks as before."""
import json, sys, unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))  # sibling import works from the repo root too

from test_dashboard_play_queued import run

JOB = {"key": "p/300-a", "project": "p", "id": "300-a", "title": "Cloud job", "stage": "cloud", "updatedAt": "2026-11-13T10:00:00Z"}


def card(**kw):
    return f"out(card({json.dumps({**JOB, **kw})}));"


class ShopChip(unittest.TestCase):
    def test_shop_card_highlight_chip_and_label(self):
        html, plain, left, none = run(card(shop="4242") + card() + card(shop="4242", stage="check") + card(shop=""))
        self.assertIn('class="card shop"', html)
        self.assertIn('<span class="lanechip">Shop</span>', html)
        self.assertIn("Running on shop Mac, ", html)
        self.assertIn('<span class="lanechip">Shop · mac2</span>', run(card(shop="4242", worker="mac2"))[0])
        for other in (plain, none):
            self.assertNotIn("shop", other.lower())
        self.assertIn("Running in cloud, ", plain)
        self.assertIn('class="card shop"', left, "a shop job past cloud keeps its blue border")
        self.assertIn("Checking, ", left)
        self.assertNotIn("Running on shop Mac", left)

    def test_finished_shop_job_stays_blue(self):
        done, aborted = run(card(shop="4242", stage="done", worker="mac2") + card(shop="4242", stage="aborted"))
        self.assertIn('class="card shop"', done)
        self.assertIn('<span class="lanechip">Shop · mac2</span>', done)
        self.assertIn('class="card aborted shop"', aborted)
        for html in (done, aborted):
            self.assertNotIn("Running on shop Mac", html)


if __name__ == "__main__":
    unittest.main()
