"""Filling a bucket (plan step 3.4): packs of sealed tobacco into a house mix.
A stock move, not money. Everything here is invented."""
import unittest

from ledger import api, db
from tests.helpers import fresh_books

ON = "2026-11-09"


class Filling(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.mix = self.item("House Mix", "A", 23000)
        self.a = self.item("Hill Leaf", "B", 30000)
        self.b = self.item("Star Leaf", "B", 25000)
        self.c = self.item("Moon Leaf", "B", 20000)

    def item(self, name, letter, price):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price})["id"]

    def fill(self, *lines, mix=None, **more):
        return api.run(self.con, "bucket_fill", {
            "mix": mix or self.mix, "on": ON,
            "lines": [{"item": i, "packs": p} for i, p in lines], **more})

    def price(self, item):
        return db.scalar(self.con, "SELECT price FROM stock_item WHERE id = ?", (item,))

    def stock_view(self):
        return api.state(self.con)["stock"]

    def test_the_worked_example_in_the_plan(self):
        # 8 packs at 30,000/kg is 400 g, 12,000; 6 at 25,000 is 300 g, 7,500;
        # 6 at 20,000 is 300 g, 6,000: a 1 kg bucket at 25,500 a kilo
        out = self.fill((self.a, "8"), (self.b, "6"), (self.c, "6"))
        self.assertEqual((out["grams"], out["value"], out["price_after"]), (1000, 25500, 25500))
        self.assertEqual(self.price(self.mix), 25500)

    def test_weighing_the_full_bucket_blends_in_what_was_there(self):
        # 1 kg went in; the bucket weighs 1,700 g with a 200 g bucket, so
        # 500 g at 23,000 was already in: (500 x 23,000 + 25,500,000) / 1,500
        tare = api.run(self.con, "tare_set", {"name": "Blue bucket", "grams": 200})
        tare_id = db.scalar(self.con, "SELECT id FROM tare WHERE name = 'Blue bucket'")
        out = self.fill((self.a, "8"), (self.b, "6"), (self.c, "6"),
                        gross_grams="1700", tare_id=tare_id)
        self.assertEqual((out["before_grams"], out["price_after"]), (500, 24667))
        self.assertIsNotNone(tare)

    def test_a_flavour_goes_in_at_its_brand_s_packs_and_price(self):
        api.run(self.con, "item_update", {"id": self.a, "packs": "1 kg"})
        mint = api.run(self.con, "item_add", {"brand": self.a, "name": "Mint"})["id"]
        out = self.fill((mint, "0.5"))
        self.assertEqual((out["grams"], out["value"]), (500, 15000))

    def test_the_same_tobacco_twice_is_one_line(self):
        self.fill((self.a, "2"), (self.a, "3"))
        self.assertEqual(db.scalar(self.con, "SELECT packs_milli FROM bucket_fill_line"), 5000)

    def test_only_sealed_tobacco_goes_in(self):
        cups = self.item("Cups", "C", 5000)
        with self.assertRaises(api.ApiError):
            self.fill((cups, "1"))
        with self.assertRaises(api.ApiError):
            self.fill((self.a, "1"), mix=self.b)            # into a sealed tobacco

    def test_something_has_to_go_in(self):
        with self.assertRaises(api.ApiError):
            self.fill()
        with self.assertRaises(api.ApiError):
            self.fill((self.a, "0"))
        with self.assertRaises(api.ApiError):
            self.fill((self.a, "-2"))

    def test_no_money_moves(self):
        before = db.scalar(self.con, "SELECT COUNT(*) FROM posting")
        self.fill((self.a, "8"))
        self.assertEqual(db.scalar(self.con, "SELECT COUNT(*) FROM posting"), before)

    def test_the_usual_is_kept_when_asked(self):
        self.fill((self.a, "8"), (self.b, "6"))
        mix = next(m for m in self.stock_view()["mixes"] if m["id"] == self.mix)
        self.assertEqual(mix["usual"], [])
        self.fill((self.a, "8"), (self.b, "6"), usual=True)
        mix = next(m for m in self.stock_view()["mixes"] if m["id"] == self.mix)
        self.assertEqual(mix["usual"], [{"item": self.a, "packs": 8}, {"item": self.b, "packs": 6}])

    def test_the_fills_are_listed(self):
        self.fill((self.a, "8"), (self.b, "6"))
        [f] = self.stock_view()["fills"]
        self.assertEqual((f["mix"], f["grams"], f["price_before"], f["price_after"]),
                         ("House Mix", 700, 23000, 27857))
        self.assertEqual([l["name"] for l in f["lines"]], ["Hill Leaf", "Star Leaf"])

    def test_deleting_a_fill_puts_the_price_back(self):
        fid = self.fill((self.a, "8"))["id"]
        api.run(self.con, "bucket_fill_delete", {"id": fid})
        self.assertEqual(self.price(self.mix), 23000)
        self.assertEqual(self.stock_view()["fills"], [])

    def test_unless_the_price_was_changed_since(self):
        fid = self.fill((self.a, "8"))["id"]
        api.run(self.con, "item_update", {"id": self.mix, "price": "26000"})
        api.run(self.con, "bucket_fill_delete", {"id": fid})
        self.assertEqual(self.price(self.mix), 26000)

    def test_a_closed_month_is_left_alone(self):
        fid = self.fill((self.a, "8"))["id"]
        self.con.execute("INSERT INTO period(month, status, closed_at) VALUES "
                         "('2026-11', 'closed', 'x') ON CONFLICT(month) DO "
                         "UPDATE SET status = 'closed', closed_at = 'x'")
        with self.assertRaises(api.ApiError):
            self.fill((self.a, "8"))
        with self.assertRaises(api.ApiError):
            api.run(self.con, "bucket_fill_delete", {"id": fid})

    def test_the_next_count_values_the_mix_at_its_new_price(self):
        self.fill((self.a, "8"), (self.b, "6"), (self.c, "6"))
        api.run(self.con, "count_line", {"on": ON, "item": self.mix, "gross_grams": "2000"})
        self.assertEqual(db.scalar(self.con, "SELECT value FROM stock_count_line "
                                             "WHERE item_id = ?", (self.mix,)), 51000)

    def test_setup_says_each_tobacco_s_pack_and_price(self):
        api.run(self.con, "item_update", {"id": self.a, "packs": "3×1 kg"})
        mint = api.run(self.con, "item_add", {"brand": self.a, "name": "Mint"})["id"]
        items = {i["id"]: i for i in api.state(self.con)["setup"]["items"]}
        self.assertEqual((items[mint]["pack_grams"], items[mint]["cost"]), (1000, 30000))
        self.assertEqual((items[self.b]["pack_grams"], items[self.b]["cost"]), (50, 25000))


if __name__ == "__main__":
    unittest.main()
