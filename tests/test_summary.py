"""The month-end summary for the partner (plan, Later): the screen has last
month's figures beside this month's. Everything here is invented."""
import unittest

from ledger import api
from tests.helpers import fresh_books


class Summary(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 30000, "on": "2026-10-20"})
        api.run(self.con, "sales", {"amount": 50000, "on": "2026-11-05"})

    def test_last_month_comes_with_this_one(self):
        s = api.state(self.con, month="2026-11")
        self.assertEqual((s["result"]["rev"], s["prev"]["rev"], s["prev"]["month"]),
                         (50000, 30000, "2026-10"))

    def test_a_month_with_nothing_before_it(self):
        s = api.state(self.con, month="2026-10")
        self.assertFalse((s["prev"] or {}).get("rev"))


if __name__ == "__main__":
    unittest.main()
