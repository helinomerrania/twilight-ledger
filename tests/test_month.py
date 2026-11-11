"""The month: how far through it we are, what is due, what Setup can reach,
and what has to be true before it closes."""
import unittest
from fractions import Fraction

from ledger import accruals, api, checks, close, db, queries
from ledger.dates import days_in, month_name, month_of, next_month, prev_month, today
from ledger.money import mround_fraction
from tests.helpers import RENT, SALARIES, STAFF, add_count, fresh_books

NOW = month_of(today())
PREV = prev_month(NOW)
DAY = f"{NOW}-01"


def charge(con, *months):
    with db.tx(con):
        for m in months:
            accruals.ensure(con, m)


class SoFar(unittest.TestCase):
    """Part-way through the month, only the days that have passed are charged."""

    def setUp(self):
        self.con = fresh_books()
        charge(self.con, NOW)
        api.run(self.con, "sales", {"amount": 400000, "on": DAY})
        self.sf = queries.so_far(self.con, NOW)
        self.total = len(days_in(NOW))

    def test_one_night_of_sales_carries_one_days_rent_and_salaries(self):
        self.assertEqual(self.sf["days"], 1)
        self.assertEqual(self.sf["fixed"], mround_fraction(Fraction(RENT, self.total)))
        self.assertEqual(self.sf["salaries"], mround_fraction(Fraction(SALARIES, self.total)))

    def test_it_adds_up(self):
        s = self.sf
        self.assertEqual(s["net"], s["rev"] - s["cogs"] - s["daily"] - s["elec"]
                         - s["fixed"] - s["salaries"] - s["differences"])

    def test_every_line_is_whole_notes(self):
        for k in ("cogs", "elec", "fixed", "salaries", "net"):
            self.assertEqual(self.sf[k] % 250, 0, k)

    def test_the_partners_share_what_has_been_made_so_far(self):
        prt = queries.partners(self.con, NOW)
        self.assertTrue(all(p["so_far"] for p in prt))
        self.assertEqual(sum(p["profit"] for p in prt), self.sf["net"])

    def test_and_their_drawings_are_set_against_it(self):
        api.run(self.con, "partner_draw", {"amount": 100000, "who": "Frank Hale",
                                           "on": DAY})
        d = queries.drawings(self.con, NOW)
        self.assertEqual((d["taken"], d["basis"]), (100000, "so far"))
        self.assertEqual(d["profit"], queries.so_far(self.con, NOW)["net"])

    def test_a_finished_month_has_no_so_far(self):
        self.assertIsNone(queries.so_far(self.con, PREV))


class WhatIsDue(unittest.TestCase):
    """This month's salaries are charged from the first day, but nobody is
    expected to have paid them on the first day."""

    def setUp(self):
        self.con = fresh_books()
        charge(self.con, PREV, NOW)

    def labels(self, month=NOW):
        return {c["label"]: c["ok"] for c in checks.checks(self.con, month)}

    def test_salaries_are_checked_to_the_end_of_last_month(self):
        self.assertIs(self.labels()[f"Salaries are paid up to {month_name(PREV)}"], False)

    def test_paying_last_month_clears_it_and_this_month_is_not_asked_for(self):
        for name, amount in STAFF.items():
            api.run(self.con, "pay_salary", {"amount": amount, "who": name, "on": DAY,
                                             "period": PREV, "allow_overdraw": True})
        self.assertIs(self.labels()[f"Salaries are paid up to {month_name(PREV)}"], True)

    def test_settle_lists_everything_unpaid_up_to_the_month(self):
        lines = api.settle(self.con, NOW)
        alice = next(l for l in lines if l["who"] == "Alice")
        self.assertEqual(alice["amount"], 2 * STAFF["Alice"])    # two months of salary
        self.assertIn("from earlier", alice["note"])


class SetupReachesForwardOnly(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        charge(self.con, PREV, NOW)

    def rent(self, month):
        return queries.live_result(self.con, month)["fixed"]

    def test_a_new_rent_starts_in_the_month_on_screen(self):
        api.run(self.con, "fixed_set", {"name": "Rent", "amount": 800000, "view_month": NOW})
        self.assertEqual((self.rent(PREV), self.rent(NOW)), (RENT, 800000))

    def test_stopping_a_charge_leaves_earlier_months_charged(self):
        api.run(self.con, "fixed_remove", {"name": "Rent", "view_month": NOW})
        self.assertEqual((self.rent(PREV), self.rent(NOW)), (RENT, 0))

    def test_a_new_charge_is_not_backdated(self):
        api.run(self.con, "fixed_set", {"name": "Internet", "amount": 50000,
                                        "view_month": NOW})
        self.assertEqual((self.rent(PREV), self.rent(NOW)), (RENT, RENT + 50000))

    def test_a_share_is_always_a_percentage(self):
        p = db.one(self.con, "SELECT id FROM account WHERE name = 'Frank Hale'")
        api.run(self.con, "set_share", {"id": p["id"], "share": "1"})
        meta = db.one(self.con, "SELECT meta FROM account WHERE id = ?", (p["id"],))["meta"]
        self.assertIn('"share": 0.01', meta)


class MonthsArriveCharged(unittest.TestCase):
    def test_months_the_app_was_not_opened_in_are_charged_too(self):
        con = fresh_books()
        start = prev_month(prev_month(PREV))
        charge(con, start)
        accruals.ensure_all(con)
        m = start
        while m <= NOW:
            self.assertEqual(queries.live_result(con, m)["fixed"], RENT, m)
            m = next_month(m)

    def test_and_asking_again_changes_nothing(self):
        con = fresh_books()
        charge(con, PREV)
        accruals.ensure_all(con)
        n = db.scalar(con, "SELECT count(*) FROM entry")
        self.assertEqual(accruals.ensure_all(con), 0)
        self.assertEqual(db.scalar(con, "SELECT count(*) FROM entry"), n)


class BeforeClosing(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        charge(self.con, PREV)
        add_count(self.con, f"{PREV}-28", 1000000)

    def test_unpaid_rent_and_electricity_are_pointed_out(self):
        warnings = " ".join(close.ready(self.con, PREV)["warnings"])
        self.assertIn(f"Rent is still owed {RENT:,}", warnings)
        self.assertIn("No electricity has been charged", warnings)

    def test_but_they_do_not_stop_it(self):
        self.assertTrue(close.ready(self.con, PREV)["can_close"])


if __name__ == "__main__":
    unittest.main()
