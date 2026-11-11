"""What each night's sales took off the shelves, by what each menu item is
set to take (plan step 3.5). Everything here is invented."""
import unittest
from fractions import Fraction

from ledger import api, db
from ledger.pos import archive, sources, uses
from tests.helpers import fresh_books
from tests.test_pos import night_of_ten

NIGHT = "2026-11-10"


def with_menu(snap, *, decrease=True, void=False, names_only=False):
    """The night of ten — two apple hookahs, a tea paid and a tea given — with
    SambaPOS's portions and prices, and SambaPOS's word on each order."""
    t = {k: [dict(r) for r in v] for k, v in snap["tables"].items()}
    for o in t["Orders"]:
        if decrease:
            o["DecreaseInventory"] = True                      # the free tea is a gift
        if names_only:
            o.pop("MenuItemId", None)                          # as an old copy kept it
    if void:
        t["Orders"].append({"Id": 5, "TicketId": 2100, "MenuItemId": 9, "MenuItemName": "Tea",
                            "PortionName": "Normal", "Price": "4000.00", "Quantity": "3.000",
                            "CalculatePrice": False, "DecreaseInventory": False})
    t["MenuItemPortions"] = [{"Id": 70, "MenuItemId": 7, "Name": "Normal"},
                             {"Id": 90, "MenuItemId": 9, "Name": "Normal"}]
    t["MenuItemPrices"] = [{"Id": 700, "MenuItemPortionId": 70, "Price": "5000.00"},
                           {"Id": 900, "MenuItemPortionId": 90, "Price": "4000.00"}]
    raw = {k: t.get(k, []) for k in sources.TABLES}
    return {"source": snap["source"], "tables": sources.normalise(raw)}


def takes(con, menu_id, item, amount=None):
    body = {"menu_id": menu_id, "item_id": item}
    if amount is not None:
        body["amount"] = amount
    return api.run(con, "menu_use", body)


class MenuUse(unittest.TestCase):
    APPLE, TEA = 7, 9

    def setUp(self):
        self.con = fresh_books()
        self.mix = self.item("Apple Mix", "A", 24000)
        self.bags = self.item("Tea bags", "C", 3000, pack_size=100)

    def item(self, name, letter, price, **more):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price, **more})["id"]

    def keep(self, snap):
        with db.tx(self.con):
            return archive.keep(self.con, snap)

    def set_all(self, head="25"):
        takes(self.con, self.APPLE, self.mix)
        takes(self.con, self.TEA, self.bags)
        if head:
            api.run(self.con, "head_grams", {"grams": head})

    def used(self):
        return uses.usage(self.con, NIGHT, NIGHT)

    def test_a_night_takes_what_its_menu_items_take(self):
        self.keep(with_menu(night_of_ten()))
        self.set_all()
        used, not_set, heads_unknown = self.used()
        # two apple hookahs of 25 g; two teas (one a gift) of a bag each
        self.assertEqual(used, {self.mix: Fraction(50, 1000), self.bags: Fraction(2, 100)})
        self.assertEqual((not_set, heads_unknown), ({}, 0))

    def test_a_void_takes_nothing(self):
        self.keep(with_menu(night_of_ten(), void=True))
        self.set_all()
        self.assertEqual(self.used()[0][self.bags], Fraction(2, 100))

    def test_a_night_kept_before_counts_what_was_charged(self):
        self.keep(with_menu(night_of_ten(), decrease=False))
        self.set_all()
        self.assertEqual(self.used()[0][self.bags], Fraction(1, 100))

    def test_and_learns_more_when_read_again(self):
        self.keep(with_menu(night_of_ten(), decrease=False))
        self.keep(with_menu(night_of_ten()))
        self.set_all()
        self.assertEqual(self.used()[0][self.bags], Fraction(2, 100))

    def test_orders_kept_without_a_number_are_matched_by_name(self):
        self.keep(with_menu(night_of_ten(), names_only=True))
        self.set_all()
        self.assertEqual(self.used()[0][self.mix], Fraction(50, 1000))

    def test_two_heads(self):
        self.keep(with_menu(night_of_ten()))
        self.set_all()
        takes(self.con, self.APPLE, self.mix, amount="2")
        self.assertEqual(self.used()[0][self.mix], Fraction(100, 1000))

    def test_with_no_grams_in_a_head_the_heads_are_said(self):
        self.keep(with_menu(night_of_ten()))
        self.set_all(head=None)
        used, _, heads_unknown = self.used()
        self.assertNotIn(self.mix, used)
        self.assertEqual(heads_unknown, 2)

    def test_a_menu_item_not_set_is_said(self):
        self.keep(with_menu(night_of_ten()))
        takes(self.con, self.APPLE, self.mix)
        api.run(self.con, "head_grams", {"grams": "25"})
        self.assertEqual(self.used()[1], {"Tea": 2})

    def test_one_that_takes_nothing_is_not(self):
        self.keep(with_menu(night_of_ten()))
        self.set_all()
        takes(self.con, self.TEA, "0")
        used, not_set, _ = self.used()
        self.assertNotIn(self.bags, used)
        self.assertEqual(not_set, {})

    def test_cleared_it_is_not_set_again(self):
        self.keep(with_menu(night_of_ten()))
        self.set_all()
        takes(self.con, self.TEA, "")
        self.assertEqual(self.used()[1], {"Tea": 2})

    def test_ice_cream_by_the_bucket(self):
        cream = self.item("Vanilla", "E", 30000)
        self.keep(with_menu(night_of_ten()))
        self.set_all()
        takes(self.con, self.TEA, cream, amount="0.5")       # half a bucket a tea, say
        self.assertEqual(self.used()[0][cream], Fraction(2, 1) * Fraction(1, 2) / 2)

    def test_setup_lists_every_menu_item(self):
        self.keep(with_menu(night_of_ten()))
        self.set_all()
        v = api.state(self.con)["pos"]["uses"]
        rows = {r["name"]: r for r in v["menu"]}
        self.assertEqual((rows["Apple"]["item_id"], rows["Apple"]["unit"]),
                         (self.mix, ["head", "heads"]))
        self.assertEqual((v["set"], len(v["menu"]), v["head_grams"]), (2, 2, 25))
        self.assertEqual({t["name"]: t["qty"] for t in v["took"]},
                         {"Apple Mix": 0.05, "Tea bags": 0.02})

    def test_bad_ones_are_refused(self):
        self.keep(with_menu(night_of_ten()))
        for body in ({"menu_id": 99, "item_id": self.mix},
                     {"menu_id": self.APPLE, "item_id": 9999},
                     {"menu_id": self.APPLE, "item_id": self.mix, "amount": "0"},
                     {"menu_id": self.APPLE, "item_id": self.mix, "amount": "lots"}):
            with self.assertRaises(api.ApiError, msg=str(body)):
                api.run(self.con, "menu_use", body)
        with self.assertRaises(api.ApiError):
            api.run(self.con, "head_grams", {"grams": "0"})

    def test_nothing_is_posted(self):
        self.keep(with_menu(night_of_ten()))
        before = db.scalar(self.con, "SELECT COUNT(*) FROM posting")
        self.set_all()
        self.assertEqual(db.scalar(self.con, "SELECT COUNT(*) FROM posting"), before)


if __name__ == "__main__":
    unittest.main()
