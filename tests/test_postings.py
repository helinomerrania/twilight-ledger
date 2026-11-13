"""The rules the ledger enforces, and the bugs that made us rebuild.

Each class here is one failure the old app actually produced, written as a test
so it cannot come back.
"""
import unittest

from ledger import db, post, queries
from tests.helpers import STAFF, fresh_books

DAVE = STAFF["Dave"]
ALICE = STAFF["Alice"]


class Balancing(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_an_unbalanced_entry_is_refused_outright(self):
        with self.assertRaises(db.LedgerError) as caught:
            post.record(self.con, kind="test", on="2026-11-01", legs=[
                (post.account_id(self.con, "exp:daily"), 5000),
                (post.account_by_name(self.con, "cash", "Box"), -4000)])
        self.assertIn("out by 1000", str(caught.exception))

    def test_nothing_is_written_when_it_is_refused(self):
        before = db.scalar(self.con, "SELECT count(*) FROM entry")
        with self.assertRaises(db.LedgerError):
            post.record(self.con, kind="test", on="2026-11-01", legs=[
                (post.account_id(self.con, "exp:daily"), 5000),
                (post.account_by_name(self.con, "cash", "Box"), -1)])
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM entry"), before)

    def test_a_zero_amount_posting_cannot_exist(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            self.con.execute("INSERT INTO posting(entry_id, account_id, amount) "
                             "VALUES (1, 1, 0)")

    def test_the_guard_view_is_empty_for_real_books(self):
        with db.tx(self.con):
            post.sales(self.con, 500000, on="2026-11-01")
            post.daily_expense(self.con, 5000, detail="Ice", on="2026-11-01")
        self.assertEqual(db.all_(self.con, "SELECT * FROM unbalanced"), [])


class SettlementMonth(unittest.TestCase):
    """'Sometimes when I payed october, it will be counted on current month.'

    The cash leaves in November. The obligation is October's. Both are true at
    once, and the ledger now says so without back-dating anything.
    """

    def setUp(self):
        self.con = fresh_books()

    def test_a_november_payment_settles_october(self):
        with db.tx(self.con):
            post.charge_salary(self.con, DAVE, staff="Dave", period="2026-10")
            post.pay_salary(self.con, DAVE, staff="Dave",
                            on="2026-11-03", period="2026-10")
        pay = queries.payroll(self.con, "2026-10")
        row = next(p for p in pay if p["name"] == "Dave")
        self.assertEqual(row["gross"], DAVE)
        self.assertEqual(row["paid"], DAVE)
        self.assertEqual(row["still_to_pay"], 0)

    def test_and_november_is_not_charged_for_it(self):
        with db.tx(self.con):
            post.charge_salary(self.con, DAVE, staff="Dave", period="2026-10")
            post.pay_salary(self.con, DAVE, staff="Dave",
                            on="2026-11-03", period="2026-10")
        nov = [p for p in queries.payroll(self.con, "2026-11")
               if p["name"] == "Dave"]
        self.assertEqual(nov[0]["paid"] if nov else 0, 0)

    def test_but_the_cash_really_does_leave_in_november(self):
        with db.tx(self.con):
            post.sales(self.con, DAVE, on="2026-10-01")
            post.charge_salary(self.con, DAVE, staff="Dave", period="2026-10")
            post.pay_salary(self.con, DAVE, staff="Dave",
                            on="2026-11-03", period="2026-10")
        self.assertEqual(queries.cash_on_hand(self.con, "2026-10-31"), DAVE)
        self.assertEqual(queries.cash_on_hand(self.con, "2026-11-03"), 0)


class SupplierBalance(unittest.TestCase):
    """'The payable amount to suppliers change, for example the value
    automatically is 50000.'

    A supplier balance is now one sum over one account, so there is nothing
    for a second opinion to disagree with.
    """

    def setUp(self):
        self.con = fresh_books()

    def test_what_we_owe_is_what_arrived_less_what_was_paid(self):
        with db.tx(self.con):
            post.receipt_in(self.con, 1000000, supplier="Star Store", on="2026-10-02")
            post.receipt_in(self.con, 500000, supplier="Star Store", on="2026-10-20")
            post.pay_supplier(self.con, 420000, supplier="Star Store", on="2026-11-03")
        self.assertEqual(queries.balance(self.con, "sup:star-store"), 1080000)

    def test_changing_the_month_on_screen_cannot_change_it(self):
        with db.tx(self.con):
            post.receipt_in(self.con, 1000000, supplier="Star Store", on="2026-10-02")
            post.pay_supplier(self.con, 300000, supplier="Star Store", on="2026-11-03")
        for month in ("2026-09", "2026-10", "2026-11", "2026-12"):
            self.assertEqual(queries.balance(self.con, "sup:star-store"), 700000,
                             f"looking at {month} changed the balance")

    def test_a_cash_receipt_never_becomes_a_debt(self):
        with db.tx(self.con):
            post.receipt_in(self.con, 250000, supplier="Star Store",
                            on="2026-10-02", terms="cash")
        self.assertEqual(queries.balance(self.con, "sup:star-store"), 0)
        self.assertEqual(queries.balance(self.con, "inv:stock"), 250000)


class PotsAndTransfers(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_a_transfer_moves_money_and_changes_nothing_else(self):
        with db.tx(self.con):
            post.sales(self.con, 1000000, on="2026-11-01")
            post.transfer(self.con, 400000, frm="Box", to="Bank", on="2026-11-02")
        self.assertEqual(queries.balance(self.con, "cash:box"), 600000)
        self.assertEqual(queries.balance(self.con, "cash:bank"), 400000)
        self.assertEqual(queries.cash_on_hand(self.con), 1000000)
        self.assertEqual(queries.live_result(self.con, "2026-11")["rev"], 1000000)

    def test_a_transfer_to_the_same_pot_is_refused(self):
        with self.assertRaises(db.LedgerError), db.tx(self.con):
            post.transfer(self.con, 1000, frm="Box", to="Box", on="2026-11-02")

    def test_a_float_is_not_cash_on_hand(self):
        post.ensure_account(self.con, "float:alice", "Alice float", "float", 1)
        with db.tx(self.con):
            post.sales(self.con, 500000, on="2026-11-01")
            post.transfer(self.con, 100000, frm="Box", to="Alice float", on="2026-11-01")
        self.assertEqual(queries.cash_on_hand(self.con), 400000)
        self.assertEqual(queries.in_hands(self.con), 100000)


class ClosedMonths(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_a_closed_month_will_not_accept_a_new_entry(self):
        with db.tx(self.con):
            post.sales(self.con, 100000, on="2026-10-05")
        self.con.execute("UPDATE period SET status='closed', closed_at=datetime('now') "
                         "WHERE month='2026-10'")
        with self.assertRaises(db.LedgerError) as caught, db.tx(self.con):
            post.sales(self.con, 5000, on="2026-10-06")
        self.assertIn("closed", str(caught.exception))

    def test_an_import_may_still_seed_a_closed_month(self):
        self.con.execute("INSERT INTO period(month, status, closed_at) "
                         "VALUES ('2026-08','closed',datetime('now'))")
        with db.tx(self.con):                   # as tools/import_json.py books them
            post.record(self.con, kind="opening", on="2026-08-01", period="2026-08",
                        source="import", allow_closed=True,
                        legs=[(post.account_id(self.con, "inv:stock"), 1234567),
                              (post.account_id(self.con, "eq:opening"), -1234567)])
        self.assertEqual(queries.balance(self.con, "inv:stock"), 1234567)


class Voiding(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_a_voided_entry_leaves_the_balances_alone(self):
        with db.tx(self.con):
            eid = post.sales(self.con, 500000, on="2026-11-01")
            post.daily_expense(self.con, 5000, detail="Ice", on="2026-11-01")
        with db.tx(self.con):
            post.void(self.con, eid, why="typed twice")
        self.assertEqual(queries.balance(self.con, "cash:box"), -5000)
        self.assertEqual(queries.live_result(self.con, "2026-11")["rev"], 0)

    def test_but_it_is_still_on_the_record(self):
        with db.tx(self.con):
            eid = post.sales(self.con, 500000, on="2026-11-01")
        with db.tx(self.con):
            post.void(self.con, eid)
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM entry"), 1)
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM posting"), 2)
        self.assertTrue(db.one(self.con, "SELECT voided_at FROM entry")["voided_at"])


class MoneyBack(unittest.TestCase):
    """Staff sometimes hand an advance back, and the old app could only say so
    as a Staff Advance with the money coming in."""

    def setUp(self):
        self.con = fresh_books()

    def test_money_back_undoes_an_advance(self):
        with db.tx(self.con):
            post.charge_salary(self.con, ALICE, staff="Alice", period="2026-11")
            post.staff_advance(self.con, 700000, staff="Alice", on="2026-11-02")
            post.staff_repay(self.con, 400000, staff="Alice", on="2026-11-05")
        row = next(p for p in queries.payroll(self.con, "2026-11")
                   if p["name"] == "Alice")
        self.assertEqual(row["advances"], 300000)
        self.assertEqual(row["still_to_pay"], ALICE - 300000)
        self.assertEqual(queries.balance(self.con, "cash:box"), -300000)

    def test_it_never_touches_profit(self):
        with db.tx(self.con):
            post.staff_advance(self.con, 900000, staff="Alice", on="2026-11-02")
            post.staff_repay(self.con, 900000, staff="Alice", on="2026-11-05")
        self.assertEqual(queries.live_result(self.con, "2026-11")["net"], 0)


if __name__ == "__main__":
    unittest.main()
