"""A stage-cloud job with a `shop` pid runs on the shop Mac: its card is highlighted (class shop), shows a Shop chip and
reads "Running on shop Mac". Cloud without `shop`, or a job past cloud, looks as before."""
import json, re, sys, unittest
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
        for other in (plain, left, none):
            self.assertNotIn("shop", other.lower())
        self.assertIn("Running in cloud, ", plain)
        self.assertIn("Checking, ", left)


if __name__ == "__main__":
    unittest.main()
