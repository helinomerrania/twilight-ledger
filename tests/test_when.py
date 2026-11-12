"""When the month sold (plan, Later): by hour, by day of the week, and by
table, from every night kept. Everything here is invented."""
import unittest

from ledger import db
from ledger.pos import archive
from tests.helpers import fresh_books
from tests.test_pos import night_of_ten


class When(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        with db.tx(self.con):
            archive.keep(self.con, night_of_ten(more=True))
        self.w = archive.month(self.con, "2026-11")["when"]

    def test_by_the_hour_in_the_order_a_night_runs(self):
        # one ticket opened at 20:15, one at 01:10: after midnight comes last
        self.assertEqual(self.w["hours"], [[20, 1, 13000], [1, 1, 5000]])

    def test_by_the_day_of_the_week(self):
        [d] = self.w["days"]                         # 10 November 2026 is a Tuesday
        self.assertEqual((d["day"], d["nights"], d["takings"], d["average"]),
                         ("Tuesday", 1, 12000, 12000))

    def test_by_table_with_how_long_they_stayed(self):
        by = {t["place"]: t for t in self.w["tables"]}
        self.assertEqual((by["4"]["tickets"], by["4"]["total"], by["4"]["minutes"]),
                         (1, 13000, 255))           # 20:15 to 00:30
        self.assertIsNone(by["—"]["minutes"])        # still open, never paid
        self.assertEqual(self.w["minutes"], 255)

    def test_a_month_with_nothing_kept(self):
        self.assertIsNone(archive.month(self.con, "2026-10"))


if __name__ == "__main__":
    unittest.main()
