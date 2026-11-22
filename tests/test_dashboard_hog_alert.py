"""board.hogAlert is machine-wide, so every board carries it; the alert line shows it once."""
import unittest
from test_dashboard_checkout_alert import render

HOG = "Spotify Helper is using 110% of one core while 1-a wait for the CPU. Quit it."
class HogAlert(unittest.TestCase):
    def test_line_shows_once(self):
        el = render([{"hogAlert": HOG}, {"checkoutAlert": "9-x merged, not live.", "hogAlert": HOG}])
        self.assertEqual(el, {"innerHTML": HOG + "<br>9-x merged, not live.", "hidden": False})
