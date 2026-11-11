"""What each menu item costs to make and what it made (plan step 3.9), from
what each one takes and the stock's prices. Everything here is invented."""
import unittest

from ledger import api, db
from ledger.pos import archive, uses
from tests.helpers import fresh_books
from tests.test_menu_use import takes, with_menu
from tests.test_pos import night_of_ten

APPLE, TEA = 7, 9


class Costs(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.mix = self.item("Apple Mix", "A", 24000)            # 24 a gram
        self.bags = self.item("Tea bags", "C", 3000, pack_size=100)
        with db.tx(self.con):
            archive.keep(self.con, with_menu(night_of_ten(), void=True))
        takes(self.con, APPLE, self.mix)
        takes(self.con, TEA, self.bags)
        api.run(self.con, "head_grams", {"grams": "25"})

    def item(self, name, letter, price, **more):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price, **more})["id"]

    def sold(self):
        return {s["item"]: s for s in api.state(self.con)["pos"]["month"]["items"]}

    def test_what_one_of_each_costs(self):
        costs = uses.costs(self.con)
        self.assertEqual(costs[APPLE], 600)            # 25 g at 24,000 a kilo
        self.assertEqual(costs[TEA], 30)               # a bag from a box of 100 at 3,000

    def test_beside_each_price_on_the_menu(self):
        menu = api.state(self.con)["pos"]["menu"]
        ports = {i["name"]: i["portions"][0] for g in menu["groups"] for i in g["items"]}
        self.assertEqual((ports["Apple"]["price"], ports["Apple"]["cost"]), (5000, 600))

    def test_what_each_item_made_this_month(self):
        s = self.sold()
        apple, tea = s["Apple"], s["Tea"]
        self.assertEqual((apple["value"], apple["cost"], apple["makes"]), (10000, 1200, 8800))
        # one tea paid, one given (it still took a bag), three voided (they did not)
        self.assertEqual((tea["qty"], tea["took"], tea["cost"], tea["makes"]), (1, 2, 60, 3940))

    def test_a_mix_costs_what_its_fills_did(self):
        leaf = self.item("Hill Leaf", "B", 32000)
        api.run(self.con, "bucket_fill", {"mix": self.mix, "on": "2026-11-09",
                                          "lines": [{"item": leaf, "packs": "10"}]})
        self.assertEqual(uses.costs(self.con)[APPLE], 800)     # 25 g at 32,000

    def test_one_head_for_every_flavour(self):
        api.run(self.con, "head_grams", {"grams": "30"})
        self.assertEqual(uses.costs(self.con)[APPLE], 720)

    def test_unknown_without_the_grams_in_a_head(self):
        api.run(self.con, "head_grams", {"grams": ""})
        self.assertIsNone(uses.costs(self.con)[APPLE])
        apple = self.sold()["Apple"]
        self.assertEqual((apple["cost"], apple["makes"]), (None, None))

    def test_unknown_when_the_stock_has_no_price(self):
        api.run(self.con, "item_update", {"id": self.bags, "price": "0"})
        self.assertIsNone(uses.costs(self.con)[TEA])

    def test_nothing_costs_nothing(self):
        takes(self.con, TEA, "0")
        self.assertEqual(self.sold()["Tea"]["makes"], 4000)


if __name__ == "__main__":
    unittest.main()
