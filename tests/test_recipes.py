"""What each night's sales took off the shelves, by SambaPOS's own recipes
(plan step 3.5). Everything here is invented."""
import unittest
from fractions import Fraction

from ledger import api, db
from ledger.pos import archive, recipes, sources
from tests.helpers import fresh_books
from tests.test_pos import night_of_ten

NIGHT = "2026-11-10"


def with_recipes(snap, *, decrease=True, void=False):
    """The night of ten with SambaPOS's lists: an apple hookah takes 25 g of
    apple tobacco; a tea takes a tea bag and 10 g of sugar."""
    t = {k: [dict(r) for r in v] for k, v in snap["tables"].items()}
    for o in t["Orders"]:
        if decrease:
            o["DecreaseInventory"] = True                      # the free tea is a gift
    if void:
        t["Orders"].append({"Id": 5, "TicketId": 2100, "MenuItemId": 9, "MenuItemName": "Tea",
                            "PortionName": "Normal", "Price": "4000.00", "Quantity": "3.000",
                            "CalculatePrice": False, "DecreaseInventory": False})
    t["MenuItemPortions"] = [{"Id": 70, "MenuItemId": 7, "Name": "Normal"},
                             {"Id": 90, "MenuItemId": 9, "Name": "Normal"}]
    t["MenuItemPrices"] = [{"Id": 700, "MenuItemPortionId": 70, "Price": "5000.00"},
                           {"Id": 900, "MenuItemPortionId": 90, "Price": "4000.00"}]
    t["InventoryItems"] = [{"Id": 1, "Name": "Apple tobacco", "BaseUnit": "g"},
                           {"Id": 2, "Name": "Tea bag", "BaseUnit": "piece"},
                           {"Id": 3, "Name": "Sugar", "BaseUnit": "g"}]
    t["Recipes"] = [{"Id": 1, "Name": "Apple", "PortionId": 70},
                    {"Id": 2, "Name": "Tea", "PortionId": 90}]
    t["RecipeItems"] = [{"Id": 1, "RecipeId": 1, "InventoryItem_Id": 1, "Quantity": "25"},
                        {"Id": 2, "RecipeId": 2, "InventoryItem_Id": 2, "Quantity": "1"},
                        {"Id": 3, "RecipeId": 2, "InventoryItem_Id": 3, "Quantity": "10"}]
    raw = {k: t.get(k, []) for k in sources.TABLES}
    return {"source": snap["source"], "tables": sources.normalise(raw)}


class Recipes(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.mix = self.item("Apple Mix", "A", 25000)
        self.bags = self.item("Tea bags", "C", 3000, pack_size=100)
        self.sugar = self.item("Sugar", "D", 2000)

    def item(self, name, letter, price, **more):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price, **more})["id"]

    def keep(self, snap):
        with db.tx(self.con):
            return archive.keep(self.con, snap)

    def link(self, pos_id, item, per=None):
        body = {"pos_id": pos_id, "item_id": item}
        if per is not None:
            body["per"] = per
        api.run(self.con, "pos_stock_link", body)

    def link_all(self):
        self.link(1, self.mix)
        self.link(2, self.bags)
        self.link(3, self.sugar, per="1000")      # sugar in 1 kg packages

    def used(self):
        return recipes.usage(self.con, NIGHT, NIGHT)

    def test_a_night_takes_what_its_recipes_say(self):
        self.keep(with_recipes(night_of_ten()))
        self.link_all()
        used, no_recipe, not_linked = self.used()
        # two apple hookahs at 25 g; two teas (one a gift) at a bag and 10 g of sugar
        self.assertEqual(used, {self.mix: Fraction(50, 1000), self.bags: Fraction(2, 100),
                                self.sugar: Fraction(20, 1000)})
        self.assertEqual((no_recipe, not_linked), ({}, {}))

    def test_a_void_takes_nothing(self):
        self.keep(with_recipes(night_of_ten(), void=True))
        self.link_all()
        self.assertEqual(self.used()[0][self.bags], Fraction(2, 100))

    def test_a_night_kept_before_counts_what_was_charged(self):
        self.keep(with_recipes(night_of_ten(), decrease=False))
        self.link_all()
        self.assertEqual(self.used()[0][self.bags], Fraction(1, 100))

    def test_and_learns_more_when_read_again(self):
        self.keep(with_recipes(night_of_ten(), decrease=False))
        self.keep(with_recipes(night_of_ten()))
        self.link_all()
        self.assertEqual(self.used()[0][self.bags], Fraction(2, 100))

    def test_a_head_can_be_the_same_for_every_flavour(self):
        self.keep(with_recipes(night_of_ten()))
        self.link_all()
        api.run(self.con, "head_grams", {"grams": "30"})
        self.assertEqual(self.used()[0][self.mix], Fraction(60, 1000))
        api.run(self.con, "head_grams", {"grams": ""})
        self.assertEqual(self.used()[0][self.mix], Fraction(50, 1000))
        with self.assertRaises(api.ApiError):
            api.run(self.con, "head_grams", {"grams": "0"})

    def test_what_cannot_be_placed_is_said(self):
        self.keep(with_recipes(night_of_ten()))
        self.link(1, self.mix)
        used, no_recipe, not_linked = self.used()
        self.assertEqual(used, {self.mix: Fraction(50, 1000)})
        self.assertEqual(not_linked, {"Tea bag": 2, "Sugar": 2})

    def test_a_menu_item_with_no_recipe_is_listed(self):
        snap = with_recipes(night_of_ten())
        snap["tables"]["Recipes"] = snap["tables"]["Recipes"][:1]
        self.keep(snap)
        self.link_all()
        self.assertEqual(self.used()[1], {"Tea": 2})
        self.assertEqual(api.state(self.con)["pos"]["recipes"]["no_recipe"], ["Tea"])

    def test_how_many_make_one_is_worked_out_from_the_units(self):
        self.keep(with_recipes(night_of_ten()))
        self.link_all()
        rows = {r["name"]: r for r in api.state(self.con)["pos"]["recipes"]["inventory"]}
        self.assertEqual((rows["Apple tobacco"]["per_default"], rows["Tea bag"]["per_default"]),
                         (1000, 100))
        self.assertEqual((rows["Sugar"]["per"], rows["Sugar"]["per_default"]), (1000, None))
        self.assertEqual(rows["Apple tobacco"]["recipes"], 1)

    def test_setup_shows_what_the_last_night_took(self):
        self.keep(with_recipes(night_of_ten()))
        self.link_all()
        r = api.state(self.con)["pos"]["recipes"]
        self.assertEqual(r["last_night"], NIGHT)
        self.assertEqual({t["name"]: t["qty"] for t in r["took"]},
                         {"Apple Mix": 0.05, "Sugar": 0.02, "Tea bags": 0.02})

    def test_a_link_can_be_undone(self):
        self.keep(with_recipes(night_of_ten()))
        self.link_all()
        self.link(2, "")
        self.assertNotIn(self.bags, self.used()[0])

    def test_bad_links_are_refused(self):
        self.keep(with_recipes(night_of_ten()))
        for body in ({"pos_id": 99, "item_id": self.mix}, {"pos_id": 1, "item_id": 9999},
                     {"pos_id": 1, "per": "0"}, {"pos_id": 1, "per": "lots"}):
            with self.assertRaises(api.ApiError, msg=str(body)):
                api.run(self.con, "pos_stock_link", body)

    def test_nothing_is_posted(self):
        self.keep(with_recipes(night_of_ten()))
        before = db.scalar(self.con, "SELECT COUNT(*) FROM posting")
        self.link_all()
        api.run(self.con, "head_grams", {"grams": "30"})
        self.assertEqual(db.scalar(self.con, "SELECT COUNT(*) FROM posting"), before)


if __name__ == "__main__":
    unittest.main()
