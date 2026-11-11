"""More of what SambaPOS knows, kept early for the steps that need it: who
opened and closed each work period, each payment's type, and SambaPOS's own
lists — payment types, the menu, inventory items, recipes. Everything here is
invented."""
import unittest

from ledger import api, db
from ledger.pos import archive, catalog, sources
from tests.helpers import fresh_books
from tests.test_pos import night_of_ten


def with_more(snap, *, names=True, at=None, menu=True, drop_item=False):
    t = {k: [dict(r) for r in v] for k, v in snap["tables"].items()}
    if names:
        t["WorkPeriods"][0].update(StartByName="Alice", EndByName="Bob")
    for p in t["Payments"]:
        p["PaymentTypeId"] = 1
    t["PaymentTypes"] = [{"Id": 1, "Name": "Cash", "Account_Id": 5},
                         {"Id": 2, "Name": "Card", "Account_Id": 20}]
    if menu:
        t["MenuItemPortions"] = [{"Id": 70, "MenuItemId": 7, "Name": "Normal", "Multiplier": "1"},
                                 {"Id": 90, "MenuItemId": 9, "Name": "Normal", "Multiplier": "1"}]
        t["MenuItemPrices"] = [{"Id": 700, "MenuItemPortionId": 70, "Price": "5000.00"},
                               {"Id": 900, "MenuItemPortionId": 90, "Price": "4000.00"}]
        t["InventoryItems"] = [{"Id": 1, "Name": "Apple tobacco", "BaseUnit": "g",
                                "TransactionUnit": "pack", "TransactionUnitMultiplier": "50"}]
        t["Recipes"] = [{"Id": 1, "Name": "Apple", "PortionId": 70, "FixedCost": "0"}]
        t["RecipeItems"] = [{"Id": 1, "RecipeId": 1, "InventoryItem_Id": 1, "Quantity": "25.5"}]
    if drop_item:
        t["MenuItems"] = [m for m in t["MenuItems"] if m["Id"] != 9]
    raw = {k: t.get(k, []) for k in sources.TABLES}
    out = {"source": snap["source"], "tables": sources.normalise(raw)}
    if at:
        out["at"] = at
    return out


class KeptEarly(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def keep(self, snap):
        with db.tx(self.con):
            return archive.keep(self.con, snap)

    def test_who_opened_and_who_closed(self):
        self.keep(with_more(night_of_ten(ended=True)))
        n = archive.night(self.con, "2026-11-10")
        self.assertEqual((n["opened_by"], n["closed_by"]), ("Alice", "Bob"))

    def test_a_period_still_open_has_not_been_closed_by_anyone(self):
        self.keep(with_more(night_of_ten(ended=False)))
        self.assertIsNone(archive.night(self.con, "2026-11-10")["closed_by"])

    def test_each_payment_s_type(self):
        self.keep(with_more(night_of_ten(ended=True)))
        self.assertEqual(db.scalar(self.con, "SELECT type_id FROM pos_payment"), 1)

    def test_a_night_kept_before_gets_them_when_read_again(self):
        self.keep(night_of_ten(ended=True))                   # as an older version kept it
        self.assertIsNone(archive.night(self.con, "2026-11-10")["opened_by"])
        lines = self.keep(with_more(night_of_ten(ended=True)))
        self.assertEqual(lines[0]["status"], "same")
        n = archive.night(self.con, "2026-11-10")
        self.assertEqual((n["opened_by"], n["closed_by"], n["takings"]), ("Alice", "Bob", 12000))
        self.assertEqual(db.scalar(self.con, "SELECT type_id FROM pos_payment"), 1)

    def test_samba_pos_s_lists_are_kept(self):
        self.keep(with_more(night_of_ten(ended=True)))
        self.assertEqual(catalog.counts(self.con),
                         {"payment_type": 2, "menu_item": 2, "menu_portion": 2, "menu_price": 2,
                          "inventory_item": 1, "recipe": 1, "recipe_item": 1})
        prices = {p["MenuItemPortionId"]: p["Price"] for p in catalog.rows(self.con, "menu_price")}
        self.assertEqual(prices, {70: "5000", 90: "4000"})
        self.assertEqual(catalog.rows(self.con, "recipe_item")[0]["Quantity"], "25.5")

    def test_the_newest_snapshot_decides_and_an_older_one_changes_nothing(self):
        self.keep(with_more(night_of_ten(ended=True), at="2026-11-11 03:00:00"))
        self.keep(with_more(night_of_ten(ended=True), at="2026-11-12 03:00:00", drop_item=True))
        self.assertEqual(catalog.counts(self.con)["menu_item"], 1)
        self.keep(with_more(night_of_ten(ended=True), at="2026-11-10 03:00:00"))
        self.assertEqual(catalog.counts(self.con)["menu_item"], 1)
        gone = [r for r in catalog.rows(self.con, "menu_item") if r["_gone"]]
        self.assertEqual([r["Name"] for r in gone], ["Tea"])

    def test_a_snapshot_without_a_list_leaves_it_as_it_was(self):
        self.keep(with_more(night_of_ten(ended=True), at="2026-11-11 03:00:00"))
        self.keep(with_more(night_of_ten(ended=True), at="2026-11-12 03:00:00", menu=False))
        self.assertEqual(catalog.counts(self.con)["recipe"], 1)

    def test_the_menu_as_samba_pos_has_it(self):
        self.keep(with_more(night_of_ten(ended=True)))
        m = catalog.menu(self.con)
        self.assertEqual(m["items"], 2)
        groups = {g["name"]: g["items"] for g in m["groups"]}
        self.assertEqual(sorted(groups), ["Drinks", "Hookah"])
        apple = groups["Hookah"][0]
        self.assertEqual((apple["name"], apple["portions"], apple["sold"]),
                         ("Apple", [{"name": "Normal", "price": 5000, "tag": None}], 2))
        self.assertEqual(groups["Drinks"][0]["sold"], 2)        # one of them given free
        self.assertEqual(m["odd"], [])

    def test_a_price_that_needs_odd_change_is_pointed_out(self):
        snap = with_more(night_of_ten(ended=True))
        snap["tables"]["MenuItemPrices"][1]["Price"] = sources.coerce("dec", "4100")
        self.keep(snap)
        self.assertEqual(catalog.menu(self.con)["odd"],
                         [{"item": "Tea", "portion": "Normal", "price": 4100}])

    def test_a_price_per_gram_is_not_odd_change(self):
        snap = with_more(night_of_ten(ended=True))
        snap["tables"]["MenuItemPrices"][1]["Price"] = sources.coerce("dec", "50")
        self.keep(snap)
        self.assertEqual(catalog.menu(self.con)["odd"], [])

    def test_samba_pos_s_users_are_never_read(self):
        """They hold passwords and PINs."""
        self.assertNotIn("Users", sources.TABLES)

    def test_setup_says_what_is_kept(self):
        self.keep(with_more(night_of_ten(ended=True)))
        self.assertEqual(api.state(self.con)["pos"]["catalog"]["menu_price"], 2)


if __name__ == "__main__":
    unittest.main()
