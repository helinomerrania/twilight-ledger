"""Shortage warnings (plan step 3.8): what should be on the shelf against the
minimum set for it, and roughly how many nights are left. Invented items."""
import unittest

from ledger import api, db, expected
from ledger.pos import archive
from tests.helpers import fresh_books
from tests.test_pos import night_of_ten
from tests.test_recipes import with_recipes

ON = "2026-11-11"


class Low(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.mix = api.run(self.con, "item_add", {"name": "Apple Mix", "letter": "A",
                                                  "price": 25000})["id"]
        api.run(self.con, "count_line", {"on": "2026-11-08", "item": self.mix,
                                         "gross_grams": "1500"})
        with db.tx(self.con):
            archive.keep(self.con, with_recipes(night_of_ten()))     # 2 heads of 25 g
        api.run(self.con, "pos_stock_link", {"pos_id": 1, "item_id": self.mix})

    def minimum(self, kilos):
        api.run(self.con, "item_update", {"id": self.mix, "minimum": kilos})

    def test_nothing_to_say_without_a_minimum(self):
        self.assertIsNone(expected.low(self.con, ON))

    def test_above_the_minimum_is_fine(self):
        self.minimum("1")
        self.assertEqual(expected.low(self.con, ON), [])

    def test_below_it_with_the_nights_left(self):
        self.minimum("2")
        [r] = expected.low(self.con, ON)
        self.assertAlmostEqual(r["left"], 1.45)
        self.assertEqual(r["nights"], 29)                 # 1,450 g at 50 g a night
        self.assertEqual(expected.said(r), "Apple Mix: 1.45 kg left, about 29 nights")

    def test_a_pace_nobody_knows_says_no_nights(self):
        api.run(self.con, "pos_stock_link", {"pos_id": 1, "item_id": ""})
        self.minimum("2")
        [r] = expected.low(self.con, ON)
        self.assertIsNone(r["nights"])
        self.assertEqual(expected.said(r), "Apple Mix: 1.5 kg left")

    def test_tonight_says_so(self):
        self.minimum("2")
        [c] = [c for c in api.state(self.con)["checks"] if c["label"] == "Nothing is running low"]
        self.assertFalse(c["ok"])
        self.assertIn("Apple Mix: 1.45 kg left", c["detail"])
        self.assertEqual(c["go"], "stock")

    def test_a_stopped_item_is_not_warned_about(self):
        self.minimum("2")
        api.run(self.con, "item_update", {"id": self.mix, "active": 0})
        self.assertIsNone(expected.low(self.con, ON))


if __name__ == "__main__":
    unittest.main()
