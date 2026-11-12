"""Undo, right after a change: the entry it wrote goes, and whatever it
corrected or replaced stands again. Everything here is invented."""
import unittest

from ledger import api, db, queries
from tests.helpers import SUPPLIERS, fresh_books

ON = "2026-11-09"


class Undo(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 400000, "on": ON})

    def box(self):
        return next(p["balance"] for p in queries.pots(self.con) if p["name"] == "Box")

    def sales(self):
        return [e["amount"] for e in queries.entries(self.con, on=ON, kind="daily_sales")]

    def test_an_expense_is_taken_back(self):
        before = self.box()
        out = api.run(self.con, "expense", {"amount": 5000, "detail": "Ice", "on": ON})
        self.assertEqual(self.box(), before - 5000)
        back = api.run(self.con, "undo", {"id": out["id"]})
        self.assertEqual((self.box(), back["put_back"]), (before, []))
        self.assertIn("Taken back", queries.recent(self.con)[0]["summary"])

    def test_a_new_till_figure_taken_back_leaves_the_old_one(self):
        out = api.run(self.con, "sales", {"amount": 450000, "on": ON})
        self.assertEqual(self.sales(), [450000])
        back = api.run(self.con, "undo", {"id": out["id"]})
        self.assertEqual(self.sales(), [400000])
        self.assertEqual(len(back["put_back"]), 1)

    def test_a_replaced_till_figure_cannot_be_put_back_beside_the_new_one(self):
        first = queries.entries(self.con, on=ON, kind="daily_sales")[0]["id"]
        api.run(self.con, "sales", {"amount": 450000, "on": ON})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "put_back", {"id": first})

    def test_a_correction_taken_back_leaves_the_original(self):
        out = api.run(self.con, "expense", {"amount": 5000, "detail": "Ice", "on": ON})
        fixed = api.run(self.con, "edit_entry", {"id": out["id"], "amount": 7000})
        api.run(self.con, "undo", {"id": fixed["id"]})
        rows = [e["amount"] for e in queries.entries(self.con, on=ON, kind="daily_expense")]
        self.assertEqual(rows, [5000])
        # and the original can be corrected again
        api.run(self.con, "edit_entry", {"id": out["id"], "amount": 6000})

    def test_a_corrected_receipt_taken_back_keeps_what_came_in(self):
        item = api.run(self.con, "item_add", {"name": "Hill Leaf", "letter": "B",
                                              "price": 30000})["id"]
        r = api.run(self.con, "receipt", {"amount": 300000, "on": ON, "who": SUPPLIERS[0]})
        api.run(self.con, "receipt_line", {"receipt": r["receipt"], "item": item,
                                           "packages": "1"})
        fixed = api.run(self.con, "edit_entry", {"id": r["id"], "amount": 310000})
        api.run(self.con, "undo", {"id": fixed["id"]})
        lines = db.all_(self.con, """SELECT rc.entry_id FROM receipt_line l
                                     JOIN receipt rc ON rc.id = l.receipt_id""")
        self.assertEqual([x["entry_id"] for x in lines], [r["id"]])

    def test_only_once(self):
        out = api.run(self.con, "expense", {"amount": 5000, "detail": "Ice", "on": ON})
        api.run(self.con, "undo", {"id": out["id"]})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "undo", {"id": out["id"]})

    def test_not_in_a_closed_month(self):
        out = api.run(self.con, "expense", {"amount": 5000, "detail": "Ice", "on": ON})
        self.con.execute("INSERT INTO period(month, status, closed_at) VALUES "
                         "('2026-11', 'closed', 'x') ON CONFLICT(month) DO "
                         "UPDATE SET status = 'closed', closed_at = 'x'")
        with self.assertRaises(api.ApiError):
            api.run(self.con, "undo", {"id": out["id"]})


if __name__ == "__main__":
    unittest.main()
