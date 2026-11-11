"""Foil, coal and the like, used up by a ratio learnt between counts (plan
step 3.7). Everything here is invented."""
import unittest
from datetime import date, timedelta

from ledger import api, db, expected, ratios
from ledger.pos import archive, sources
from tests.helpers import SUPPLIERS, fresh_books


def night(day, hookahs, n):
    """A night that sold `hookahs` apple hookahs."""
    nxt = (date.fromisoformat(day) + timedelta(days=1)).isoformat()
    pay = str(5000 * hookahs)
    raw = {
        "WorkPeriods": [{"Id": 5000 + n, "StartDate": f"{day}T03:05:00",
                         "EndDate": f"{nxt}T02:40:00"}],
        "Tickets": [{"Id": 9000 + n, "TicketNumber": str(n), "Date": f"{day}T20:15:00",
                     "LastPaymentDate": f"{day}T23:30:00", "IsClosed": True,
                     "RemainingAmount": "0", "TotalAmount": pay}],
        "Orders": [{"Id": 100 + n, "TicketId": 9000 + n, "MenuItemId": 7,
                    "MenuItemName": "Apple", "PortionName": "Normal", "Price": "5000",
                    "Quantity": str(hookahs), "CalculatePrice": True,
                    "DecreaseInventory": True}],
        "Payments": [{"Id": 100 + n, "TicketId": 9000 + n, "Name": "Cash",
                      "Date": f"{day}T23:30:00", "Amount": pay}],
        "MenuItems": [{"Id": 7, "Name": "Apple", "GroupCode": "Hookah"}],
        "MenuItemPortions": [{"Id": 70, "MenuItemId": 7, "Name": "Normal"}],
    }
    return {"source": f"backup:{day}.zip", "tables": sources.normalise(raw)}


class Ratios(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.mix = self.item("Apple Mix", "A", 25000)
        self.foil = self.item("Foil", "C", 12000)
        api.run(self.con, "per_hookah", {"id": self.foil, "on": 1})
        for n, (day, sold) in enumerate((("2026-11-02", 40), ("2026-11-03", 60),
                                         ("2026-11-05", 50), ("2026-11-06", 50),
                                         ("2026-11-08", 60))):
            with db.tx(self.con):
                archive.keep(self.con, night(day, sold, n))
        api.run(self.con, "menu_use", {"menu_id": 7, "item_id": self.mix})
        self.count("2026-11-01", "10")
        self.count("2026-11-04", "8")             # 2 rolls for 100 hookahs
        r = api.run(self.con, "receipt", {"amount": 60000, "on": "2026-11-05",
                                          "who": SUPPLIERS[0]})
        api.run(self.con, "receipt_line", {"receipt": r["receipt"], "item": self.foil,
                                           "packages": "5"})
        self.count("2026-11-07", "11")            # 8 + 5 - 11: 2 rolls for 100 hookahs
        self.count("2026-11-09", "9")             # 2 rolls for only 60 hookahs

    def item(self, name, letter, price):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price})["id"]

    def count(self, on, rolls):
        api.run(self.con, "count_line", {"on": on, "item": self.foil, "packages": rolls})

    def foil_view(self):
        return next(i for i in ratios.view(self.con)["items"] if i["item"] == self.foil)

    def test_hookahs_to_each_roll_between_counts(self):
        ps = ratios.pairs(self.con, self.foil)
        self.assertEqual([(p["used"], p["hookahs"], p["ratio"]) for p in ps],
                         [(2, 100, 50), (2, 100, 50), (2, 60, 30)])

    def test_the_last_three_pairs_pooled(self):
        self.assertAlmostEqual(self.foil_view()["ratio"], 260 / 6)

    def test_a_ratio_that_drops_is_pointed_out(self):
        self.assertTrue(self.foil_view()["dropped"])
        self.count("2026-11-09", "9.8")           # as many as it should
        self.assertFalse(self.foil_view()["dropped"])

    def test_roughly_what_a_night_uses(self):
        v = ratios.view(self.con)
        self.assertEqual(v["a_night"], 52)             # 260 hookahs over five nights
        self.assertAlmostEqual(self.foil_view()["a_night"], 52 / (260 / 6))

    def test_what_should_be_there_uses_the_ratio_learnt_before(self):
        r = {x["item"]: x for x in expected.view(self.con, "2026-11-09")["rows"]}[self.foil]
        self.assertAlmostEqual(r["sold"], 1.2)         # 60 hookahs at 50 to a roll
        self.assertAlmostEqual(r["gap"], -0.8)

    def test_nothing_is_known_until_a_hookah_takes_tobacco(self):
        api.run(self.con, "menu_use", {"menu_id": 7, "item_id": ""})
        v = ratios.view(self.con)
        self.assertFalse(v["hookahs_known"])
        self.assertIsNone(self.foil_view()["ratio"])

    def test_tobacco_goes_by_recipe(self):
        with self.assertRaises(api.ApiError):
            api.run(self.con, "per_hookah", {"id": self.mix, "on": 1})

    def test_it_can_stop(self):
        api.run(self.con, "per_hookah", {"id": self.foil, "on": 0})
        self.assertEqual(ratios.view(self.con)["items"], [])

    def test_on_the_stock_screen(self):
        self.assertEqual([i["name"] for i in api.state(self.con)["stock"]["ratios"]["items"]],
                         ["Foil"])


if __name__ == "__main__":
    unittest.main()
