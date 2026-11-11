"""Changing Setup, and what a change is and is not allowed to reach."""
import unittest

from ledger import accruals, api, db, post, queries
from ledger.dates import month_of, today
from tests.helpers import RENT, SALARIES, STAFF, fresh_books

NOW = month_of(today())


def acct(con, kind, name):
    return db.one(con, "SELECT * FROM account WHERE kind = ? AND name = ?", (kind, name))


class NewMonths(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_a_month_is_charged_rent_and_salaries_once(self):
        with db.tx(self.con):
            accruals.ensure(self.con, NOW)
            accruals.ensure(self.con, NOW)
        r = queries.live_result(self.con, NOW)
        self.assertEqual(r["fixed"], RENT)
        self.assertEqual(r["salaries"], SALARIES)

    def test_a_future_month_is_not_charged(self):
        with db.tx(self.con):
            self.assertEqual(accruals.ensure(self.con, "2099-01"), 0)

    def test_a_closed_month_is_left_alone(self):
        with db.tx(self.con):
            accruals.ensure(self.con, NOW)
        self.con.execute("UPDATE period SET status='closed', closed_at='x' WHERE month=?", (NOW,))
        self.con.execute("UPDATE salary SET amount = amount * 2")
        self.assertFalse(accruals.ensure_needed(self.con, NOW))


class Salaries(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        with db.tx(self.con):
            accruals.ensure(self.con, NOW)

    def test_a_raise_reaches_the_open_month(self):
        d = acct(self.con, "staff", "Dave")
        api.run(self.con, "set_salary", {"id": d["id"], "amount": STAFF["Dave"] + 100000,
                                         "view_month": NOW})
        self.assertEqual(queries.live_result(self.con, NOW)["salaries"], SALARIES + 100000)

    def test_renaming_someone_does_not_charge_them_twice(self):
        d = acct(self.con, "staff", "Dave")
        api.run(self.con, "account_rename", {"id": d["id"], "name": "Dave A."})
        self.assertEqual(queries.live_result(self.con, NOW)["salaries"], SALARIES)

    def test_someone_who_leaves_is_still_charged_for_the_month_they_left_in(self):
        d = acct(self.con, "staff", "Dave")
        api.run(self.con, "account_active", {"id": d["id"], "active": 0})
        self.assertEqual(queries.live_result(self.con, NOW)["salaries"], SALARIES)
        self.assertEqual(acct(self.con, "staff", "Dave")["active"], 0)

    def test_new_staff_are_charged_from_now(self):
        api.run(self.con, "account_add", {"kind": "staff", "name": "Grace",
                                          "salary": 300000, "view_month": NOW})
        self.assertEqual(queries.live_result(self.con, NOW)["salaries"], SALARIES + 300000)


class Accounts(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_two_things_cannot_share_a_name(self):
        with self.assertRaises(api.ApiError):
            api.run(self.con, "account_add", {"kind": "supplier", "name": "Star Store"})

    def test_a_pot_with_money_in_it_cannot_be_retired(self):
        with db.tx(self.con):
            post.sales(self.con, 5000, on=today())
        with self.assertRaises(api.ApiError):
            api.run(self.con, "account_active",
                    {"id": acct(self.con, "cash", "Box")["id"], "active": 0})

    def test_retiring_keeps_the_history(self):
        with db.tx(self.con):
            post.receipt_in(self.con, 90000, supplier="Corner Shop", on=today())
        a = acct(self.con, "supplier", "Corner Shop")
        api.run(self.con, "account_active", {"id": a["id"], "active": 0})
        self.assertEqual(queries.balance(self.con, a["code"]), 90000)

    def test_the_businesss_own_accounts_cannot_be_edited(self):
        eq = db.one(self.con, "SELECT id FROM account WHERE code='eq:opening'")
        with self.assertRaises(api.ApiError):
            api.run(self.con, "account_rename", {"id": eq["id"], "name": "Mine"})

    def test_a_share_typed_as_a_percentage(self):
        p = acct(self.con, "partner", "Frank Hale")
        api.run(self.con, "set_share", {"id": p["id"], "share": "40"})
        self.assertIn('"share": 0.4', acct(self.con, "partner", "Frank Hale")["meta"])


class Rent(unittest.TestCase):
    def test_changing_the_rent_corrects_the_open_month(self):
        con = fresh_books()
        with db.tx(con):
            accruals.ensure(con, NOW)
        api.run(con, "fixed_set", {"name": "Rent", "amount": 800000, "view_month": NOW})
        self.assertEqual(queries.live_result(con, NOW)["fixed"], 800000)


class Electricity(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_the_bill_is_worked_out_the_way_it_is_charged(self):
        b = accruals.electricity_bill(self.con, private_price=8000, elevator_price=6000,
                                      last_reading=1000, now_reading=1300)
        self.assertEqual(b, {"private": 200000, "elevator": 20000, "public": 18500,
                             "units": 300, "total": 238500})

    def test_saving_it_twice_charges_it_once(self):
        for _ in range(2):
            api.run(self.con, "set_electricity", {"month": NOW, "private_price": 8000})
        self.assertEqual(queries.live_result(self.con, NOW)["elec"], 200000)

    def test_a_corrected_reading_corrects_the_charge(self):
        api.run(self.con, "set_electricity", {"month": NOW, "private_price": 8000})
        api.run(self.con, "set_electricity", {"month": NOW, "private_price": 7000})
        self.assertEqual(queries.live_result(self.con, NOW)["elec"], 175000)


class StockItems(unittest.TestCase):
    def test_a_new_item_can_be_added_and_repriced(self):
        con = fresh_books()
        out = api.run(con, "item_add", {"name": "Mint", "letter": "A", "price": 20000})
        api.run(con, "item_update", {"id": out["id"], "price": 22000})
        self.assertEqual(db.one(con, "SELECT price FROM stock_item WHERE id=?",
                                (out["id"],))["price"], 22000)
