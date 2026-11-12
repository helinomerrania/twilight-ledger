"""Settling up with a supplier the way the lounge does it: their goods still
on the shelf stay owed until they are used, so what is due is what is owed
less their stock still here at the month's count. A payment made in the first
days of the next month for this month's goods counts for this month.
Everything here is invented."""
import unittest

from ledger import api, db, queries
from tests.helpers import SUPPLIERS, fresh_books

OCT, NOV = "2026-10", "2026-11"
SUP = SUPPLIERS[0]


class SettleUp(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.sup = db.scalar(self.con, "SELECT id FROM account WHERE name = ?", (SUP,))
        self.leaf = api.run(self.con, "item_add", {"name": "Hill Leaf", "letter": "B",
                                                   "price": 30000})["id"]
        api.run(self.con, "item_supplier", {"id": self.leaf, "supplier_id": self.sup})
        api.run(self.con, "receipt", {"amount": 600000, "on": f"{OCT}-05", "who": SUP})

    def count(self, blocks, on=f"{OCT}-31"):
        api.run(self.con, "count_line", {"on": on, "item": self.leaf, "blocks": str(blocks)})

    def pay(self, amount, on, period=None):
        api.run(self.con, "pay_supplier", {"amount": amount, "who": SUP, "on": on,
                                           "period": period, "allow_overdraw": True})

    def line(self, month=OCT):
        return next((l for l in api.settle(self.con, month) if l["who"] == SUP), None)

    def row(self, month):
        return next(r for r in queries.supplier_statement(self.con, month) if r["name"] == SUP)

    def test_what_is_due_is_what_was_used_up(self):
        self.count(20)                                   # 10 kg at 30,000: 300,000 still here
        line = self.line()
        self.assertEqual(line["amount"], 300000)
        self.assertEqual(line["note"], "600,000 owed − 300,000 of their stock still here")
        self.assertNotIn("done", line)

    def test_paid_early_next_month_for_this_month_is_paid(self):
        self.count(20)
        self.pay(300000, f"{NOV}-03", period=OCT)        # what Settle up on October does
        line = self.line()
        self.assertEqual((line["amount"], line["done"]), (0, "paid"))
        oct_, nov = self.row(OCT), self.row(NOV)
        self.assertEqual((oct_["paid"], oct_["closing"]), (300000, 300000))
        self.assertEqual((nov["brought_forward"], nov["paid"]), (300000, 0))
        self.assertEqual(oct_["owed_now"], 300000)

    def test_the_statement_adds_up_both_months(self):
        self.count(20)
        self.pay(300000, f"{NOV}-03", period=OCT)
        for month in (OCT, NOV):
            st = queries.supplier_lines(self.con, self.sup, month)
            self.assertEqual(st["opening"] + sum(l["amount"] for l in st["lines"]),
                             st["closing"], month)
        self.assertEqual([l["what"] for l in queries.supplier_lines(self.con, self.sup, OCT)["lines"]],
                         ["Goods received — Several items", "Paid"])
        self.assertEqual(queries.supplier_lines(self.con, self.sup, NOV)["lines"], [])

    def test_a_payment_without_a_month_counts_where_it_falls(self):
        self.count(20)
        self.pay(300000, f"{NOV}-03")
        self.assertEqual(self.line()["amount"], 300000)
        self.assertEqual(self.row(NOV)["paid"], 300000)

    def test_weighing_noise_never_asks_to_be_paid(self):
        self.count(20)
        self.pay(299900, f"{OCT}-31")                    # 100 short of what was used up
        line = self.line()
        self.assertEqual((line["amount"], line["done"]), (0, "paid"))

    def test_nothing_used_up(self):
        self.count(40)                                   # all 600,000 still on the shelf
        line = self.line()
        self.assertEqual((line["amount"], line["done"]), (0, "nothing consumed to pay"))

    def test_without_a_count_all_that_is_owed_is_due(self):
        line = self.line()
        self.assertEqual(line["amount"], 600000)
        self.assertEqual(line["note"], "600,000 owed, with no count to set against it")

    def test_nothing_owed_no_line(self):
        self.count(20)
        self.pay(600000, f"{OCT}-31")
        self.assertIsNone(self.line())

    def test_next_month_s_goods_are_not_due_for_this_month(self):
        self.count(20)
        api.run(self.con, "receipt", {"amount": 90000, "on": f"{NOV}-02", "who": SUP})
        self.assertEqual(self.line()["amount"], 300000)
        self.assertEqual(self.row(OCT)["owed_now"], 690000)

    def test_goods_that_came_after_the_count_are_not_due_yet(self):
        self.count(20, on=f"{OCT}-20")                   # 300,000 still here on the 20th
        api.run(self.con, "receipt", {"amount": 90000, "on": f"{OCT}-25", "who": SUP})
        line = self.line()
        self.assertEqual(line["amount"], 300000)
        self.assertEqual(line["note"], "600,000 owed − 300,000 of their stock still here; "
                                       "90,000 came after the count and is not due yet")
        self.assertEqual(self.row(OCT)["closing"], 690000)

    def test_a_payment_goes_to_the_oldest_goods_first(self):
        self.count(20, on=f"{OCT}-20")
        api.run(self.con, "receipt", {"amount": 90000, "on": f"{OCT}-25", "who": SUP})
        self.pay(300000, f"{OCT}-28")
        self.assertEqual((self.line()["amount"], self.line()["done"]), (0, "paid"))


if __name__ == "__main__":
    unittest.main()
