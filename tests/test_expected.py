"""What should be on the shelf, and the gap at a count (plan step 3.6).
Everything here is invented."""
import unittest

from ledger import api, db, expected
from ledger.pos import archive
from tests.helpers import SUPPLIERS, fresh_books
from tests.test_pos import night_of_ten
from tests.test_recipes import with_recipes

BEFORE, AFTER = "2026-11-08", "2026-11-11"


class ShouldBe(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.leaf = self.item("Hill Leaf", "B", 30000)
        self.mix = self.item("Apple Mix", "A", 25000)
        self.cups = self.item("Cups", "C", 5000, pack_size=50)
        # the count before: 1 kg of leaf, 1.5 kg in the bucket, 3 packages of cups
        self.count(BEFORE, self.leaf, blocks="2")
        self.count(BEFORE, self.mix, gross_grams="1500")
        self.count(BEFORE, self.cups, packages="3")
        # a carton of leaf and two packages of cups come in
        r = api.run(self.con, "receipt", {"amount": 200000, "on": "2026-11-09",
                                          "who": SUPPLIERS[0]})
        self.entry = r["id"]
        for item, boxes in ((self.leaf, {"packages": "1"}), (self.cups, {"packages": "2"})):
            api.run(self.con, "receipt_line", {"receipt": r["receipt"], "item": item, **boxes})
        # 8 packs of leaf (400 g) go into the bucket
        self.fill = api.run(self.con, "bucket_fill", {
            "mix": self.mix, "on": "2026-11-09", "lines": [{"item": self.leaf, "packs": "8"}]})["id"]
        # the night of the 10th sells two apple hookahs at 25 g a head
        with db.tx(self.con):
            archive.keep(self.con, with_recipes(night_of_ten()))
        api.run(self.con, "pos_stock_link", {"pos_id": 1, "item_id": self.mix})

    def item(self, name, letter, price, **more):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price, **more})["id"]

    def count(self, on, item, **boxes):
        api.run(self.con, "count_line", {"on": on, "item": item, **boxes})

    def rows(self, on=AFTER):
        return {r["item"]: r for r in expected.view(self.con, on)["rows"]}

    def test_what_should_be_on_the_shelf(self):
        r = self.rows()
        leaf, mix, cups = r[self.leaf], r[self.mix], r[self.cups]
        # leaf: 1 kg + 6 kg in - 0.4 kg into the bucket
        self.assertEqual((leaf["was"], leaf["in"], leaf["buckets"], leaf["sold"]), (1, 6, -0.4, 0))
        self.assertAlmostEqual(leaf["should"], 6.6)
        # the mix: 1.5 kg + 0.4 kg filled - two heads of 25 g
        self.assertAlmostEqual(mix["should"], 1.85)
        self.assertEqual(mix["sold"], 0.05)
        self.assertEqual(cups["should"], 5)

    def test_the_gap_at_the_count(self):
        self.count(AFTER, self.leaf, packages="1", loose="10")       # 6.5 kg
        self.count(AFTER, self.mix, gross_grams="1800")
        r = self.rows()
        self.assertAlmostEqual(r[self.leaf]["gap"], -0.1)
        self.assertEqual(r[self.leaf]["worth"], -3000)
        self.assertTrue(r[self.leaf]["flag"])
        self.assertAlmostEqual(r[self.mix]["gap"], -0.05)
        self.assertTrue(r[self.mix]["flag"])
        # not on the count: nothing to compare with
        self.assertIsNone(r[self.cups]["gap"])
        v = expected.view(self.con, AFTER)
        self.assertEqual((v["from"], v["counted"], v["flagged"]), (BEFORE, True, 2))

    def test_a_bucket_may_dry_a_little(self):
        self.count(AFTER, self.mix, gross_grams="1800")              # 50 g short of 1,850
        api.run(self.con, "drying_pct", {"pct": "3"})                # up to 55.5 g
        self.assertFalse(self.rows()[self.mix]["flag"])
        api.run(self.con, "drying_pct", {"pct": "2"})                # up to 37 g
        self.assertTrue(self.rows()[self.mix]["flag"])
        with self.assertRaises(api.ApiError):
            api.run(self.con, "drying_pct", {"pct": "80"})

    def test_a_few_grams_either_way_is_the_scales(self):
        self.count(AFTER, self.mix, gross_grams="1854")
        self.assertFalse(self.rows()[self.mix]["flag"])

    def test_more_than_should_be_there_is_pointed_out_too(self):
        self.count(AFTER, self.mix, gross_grams="2000")
        r = self.rows()[self.mix]
        self.assertTrue(r["flag"])
        self.assertGreater(r["worth"], 0)

    def test_what_is_dated_on_the_count_is_in_it(self):
        r = api.run(self.con, "receipt", {"amount": 100000, "on": BEFORE, "who": SUPPLIERS[0]})
        api.run(self.con, "receipt_line", {"receipt": r["receipt"], "item": self.cups,
                                           "packages": "10"})
        self.assertEqual(self.rows()[self.cups]["in"], 2)

    def test_a_deleted_receipt_or_fill_moves_nothing(self):
        api.run(self.con, "void", {"id": self.entry})
        api.run(self.con, "bucket_fill_delete", {"id": self.fill})
        r = self.rows()
        self.assertEqual((r[self.leaf]["in"], r[self.leaf]["buckets"]), (0, 0))
        self.assertAlmostEqual(r[self.mix]["should"], 1.45)

    def test_with_no_count_that_day_it_is_what_should_be_there_now(self):
        v = expected.view(self.con, None)
        self.assertEqual((v["from"], v["counted"]), (BEFORE, False))

    def test_nothing_to_go_from_without_a_count(self):
        self.assertIsNone(expected.view(self.con, BEFORE))

    def test_on_the_stock_screen(self):
        self.count(AFTER, self.leaf, packages="1", loose="10")
        v = api.state(self.con)["stock"]["expected"]
        self.assertEqual((v["from"], v["to"]), (BEFORE, AFTER))

    def test_what_sales_could_not_take_is_said(self):
        api.run(self.con, "pos_stock_link", {"pos_id": 1, "item_id": ""})
        v = expected.view(self.con, AFTER)
        self.assertEqual(v["not_linked"], ["Apple tobacco", "Sugar", "Tea bag"])


if __name__ == "__main__":
    unittest.main()
