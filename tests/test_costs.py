"""What each menu item costs to make and what it made (plan step 3.9), from
SambaPOS's recipes and the stock's prices. Everything here is invented."""
import unittest

from ledger import api, db
from ledger.pos import archive, recipes
from tests.helpers import fresh_books
from tests.test_pos import night_of_ten
from tests.test_recipes import with_recipes


class Costs(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.mix = self.item("Apple Mix", "A", 24000)            # 24 a gram
        self.bags = self.item("Tea bags", "C", 3000, pack_size=100)
        self.sugar = self.item("Sugar", "D", 2000)               # a 1 kg package
        with db.tx(self.con):
            archive.keep(self.con, with_recipes(night_of_ten(), void=True))
        api.run(self.con, "pos_stock_link", {"pos_id": 1, "item_id": self.mix})
        api.run(self.con, "pos_stock_link", {"pos_id": 2, "item_id": self.bags})
        api.run(self.con, "pos_stock_link", {"pos_id": 3, "item_id": self.sugar, "per": "1000"})

    def item(self, name, letter, price, **more):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price, **more})["id"]

    def sold(self):
        return {s["item"]: s for s in api.state(self.con)["pos"]["month"]["items"]}

    def test_what_one_of_each_costs(self):
        costs = recipes.portion_costs(self.con)
        self.assertEqual(costs[70], 600)               # 25 g at 24,000 a kilo
        self.assertEqual(costs[90], 50)                # a bag at 30, 10 g of sugar at 20

    def test_beside_each_price_on_the_menu(self):
        menu = api.state(self.con)["pos"]["menu"]
        ports = {i["name"]: i["portions"][0] for g in menu["groups"] for i in g["items"]}
        self.assertEqual((ports["Apple"]["price"], ports["Apple"]["cost"]), (5000, 600))

    def test_what_each_item_made_this_month(self):
        s = self.sold()
        apple, tea = s["Apple"], s["Tea"]
        self.assertEqual((apple["value"], apple["cost"], apple["makes"]), (10000, 1200, 8800))
        # one tea paid, one given (it still took a bag and sugar), three voided (they did not)
        self.assertEqual((tea["qty"], tea["took"], tea["cost"], tea["makes"]), (1, 2, 100, 3900))

    def test_a_mix_costs_what_its_fills_did(self):
        leaf = self.item("Hill Leaf", "B", 32000)
        api.run(self.con, "bucket_fill", {"mix": self.mix, "on": "2026-11-09",
                                          "lines": [{"item": leaf, "packs": "10"}]})
        self.assertEqual(recipes.portion_costs(self.con)[70], 800)   # 25 g at 32,000

    def test_one_head_for_every_flavour(self):
        api.run(self.con, "head_grams", {"grams": "30"})
        self.assertEqual(recipes.portion_costs(self.con)[70], 720)

    def test_unknown_when_something_is_not_linked(self):
        api.run(self.con, "pos_stock_link", {"pos_id": 3, "item_id": ""})
        self.assertIsNone(recipes.portion_costs(self.con)[90])
        tea = self.sold()["Tea"]
        self.assertEqual((tea["cost"], tea["makes"]), (None, None))

    def test_unknown_when_the_stock_has_no_price(self):
        api.run(self.con, "item_update", {"id": self.bags, "price": "0"})
        self.assertIsNone(recipes.portion_costs(self.con)[90])


if __name__ == "__main__":
    unittest.main()
