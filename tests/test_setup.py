"""Changing Setup, and what a change is and is not allowed to reach."""
import json
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


class Leaving(unittest.TestCase):
    """Someone who leaves part of the way through a month is charged for the
    days of it they worked, and nothing after it."""

    def setUp(self):
        self.con = fresh_books()
        with db.tx(self.con):
            for m in ("2026-09", "2026-10", NOW):
                accruals.ensure(self.con, m)
        self.bob = acct(self.con, "staff", "Bob")["id"]          # 200,000 a month

    def charged(self, month):
        return accruals._salary_charged(self.con, self.bob, month)

    def leave(self, on, active=0):
        out = api.run(self.con, "account_active", {"id": self.bob, "active": active,
                                                   "left_on": on})
        accruals.ensure_all(self.con)            # as the screens' next look does
        return out

    def close(self, *months):
        for m in months:
            self.con.execute("UPDATE period SET status='closed', closed_at='x' WHERE month=?", (m,))

    def test_the_month_they_left_in_is_charged_for_the_days_they_worked(self):
        self.leave("2026-09-10")
        self.assertEqual(self.charged("2026-09"), 66750)    # 200,000 x 10 / 30, to the note
        self.assertEqual(self.charged("2026-10"), 0)
        self.assertEqual(self.charged(NOW), 0)
        p = next(r for r in queries.payroll(self.con, "2026-09") if r["id"] == self.bob)
        self.assertEqual((p["gross"], p["left_on"], p["part"]),
                         (66750, "2026-09-10", {"days": 10, "of": 30}))

    def test_a_month_is_thirty_days_whatever_its_length(self):
        self.leave("2026-10-10")                            # October has 31
        self.assertEqual(self.charged("2026-10"), 66750)    # still 10 days of 30
        self.leave("2026-10-30")
        self.assertEqual(self.charged("2026-10"), 200000)   # the 30th is all thirty

    def test_leaving_on_the_last_day_is_the_whole_month(self):
        self.leave("2026-09-30")
        self.assertEqual(self.charged("2026-09"), 200000)
        self.assertEqual(self.charged("2026-10"), 0)
        p = next(r for r in queries.payroll(self.con, "2026-09") if r["id"] == self.bob)
        self.assertIsNone(p["part"])

    def test_the_day_can_be_put_right(self):
        self.leave("2026-09-10")
        marked = json.loads(acct(self.con, "staff", "Bob")["meta"])["retired_on"]
        self.leave("2026-09-20")
        self.assertEqual(self.charged("2026-09"), 133250)   # 20 days of 30
        meta = json.loads(acct(self.con, "staff", "Bob")["meta"])
        self.assertEqual((meta["left_on"], meta["retired_on"]), ("2026-09-20", marked))

    def test_bringing_them_back_charges_every_month_again(self):
        self.leave("2026-09-10")
        self.leave(None, active=1)
        for m in ("2026-09", "2026-10", NOW):
            self.assertEqual(self.charged(m), 200000, m)
        self.assertNotIn("left_on", json.loads(acct(self.con, "staff", "Bob")["meta"]))

    def test_a_closed_month_keeps_its_salary_and_says_so(self):
        self.close("2026-09")
        out = self.leave("2026-09-10")
        self.assertEqual(self.charged("2026-09"), 200000)
        self.assertEqual(self.charged("2026-10"), 0)
        self.assertEqual(out["note"], "September 2026 is closed, so the salary charged in it "
                                      "stands. Reopen it on Month to put it right.")
        self.con.execute("UPDATE period SET status='open', closed_at=NULL WHERE month='2026-09'")
        accruals.ensure_all(self.con)
        self.assertEqual(self.charged("2026-09"), 66750)

    def test_every_closed_month_it_reaches_is_named(self):
        self.close("2026-09", "2026-10")
        out = self.leave("2026-09-10")
        self.assertEqual(out["note"], "September 2026 and October 2026 are closed, so the "
                                      "salary charged in them stands. Reopen them, newest "
                                      "first, on Month to put it right.")

    def test_time_away_is_not_paid_for(self):
        self.leave("2026-09-10")
        api.run(self.con, "account_active", {"id": self.bob, "active": 1,
                                             "back_on": "2026-10-21"})
        accruals.ensure_all(self.con)
        self.assertEqual(self.charged("2026-09"), 66750)    # the 1st to the 10th
        self.assertEqual(self.charged("2026-10"), 66750)    # the 21st to the 30th
        self.assertEqual(self.charged(NOW), 200000)

    def test_back_the_day_after_is_never_away(self):
        self.leave("2026-09-10")
        api.run(self.con, "account_active", {"id": self.bob, "active": 1,
                                             "back_on": "2026-09-11"})
        accruals.ensure_all(self.con)
        self.assertEqual(self.charged("2026-09"), 200000)
        with self.assertRaises(api.ApiError):               # back before they left
            self.leave("2026-09-10")
            api.run(self.con, "account_active", {"id": self.bob, "active": 1,
                                                 "back_on": "2026-09-10"})

    def test_away_and_back_in_one_month(self):
        self.leave("2026-10-05")
        api.run(self.con, "account_active", {"id": self.bob, "active": 1,
                                             "back_on": "2026-10-16"})
        accruals.ensure_all(self.con)
        self.assertEqual(self.charged("2026-10"), 133250)   # 30 days less the 6th to the 15th

    def test_bringing_them_back_names_the_closed_months_too(self):
        self.leave("2026-09-10")
        self.close("2026-09", "2026-10")
        out = self.leave(None, active=1)
        self.assertIn("September 2026 and October 2026 are closed", out["note"])
        self.assertEqual(self.charged("2026-09"), 66750)

    def test_an_open_month_has_nothing_to_say(self):
        self.assertIsNone(self.leave("2026-09-10")["note"])

    def test_the_day_must_have_come(self):
        for bad in ("2099-01-31", "the tenth"):
            with self.assertRaises(api.ApiError):
                self.leave(bad)
        self.assertEqual(acct(self.con, "staff", "Bob")["active"], 1)

    def test_the_record_says_the_day(self):
        self.leave("2026-09-10")
        line = db.scalar(self.con, "SELECT detail FROM audit WHERE action = 'account_active' "
                                   "ORDER BY id DESC LIMIT 1")
        self.assertIn("Bob left on 2026-09-10", line)


class ThirtyDays(unittest.TestCase):
    """A salary counts every month as thirty days: a month's last day is its
    thirtieth, so a 31st or the end of February is the 30th."""

    def test_the_days(self):
        for on, day in [("2026-10-29", 29), ("2026-10-30", 30), ("2026-10-31", 30),
                        ("2027-02-27", 27), ("2027-02-28", 30), ("2028-02-28", 28),
                        ("2028-02-29", 30), ("2026-11-01", 1)]:
            self.assertEqual(queries.day_of_30(on), day, on)


class Starting(unittest.TestCase):
    """Someone who starts part of the way through a month is charged for the
    days of it they work, at a thirtieth of the salary a day."""

    def setUp(self):
        self.con = fresh_books()
        with db.tx(self.con):
            for m in ("2026-09", "2026-10", NOW):
                accruals.ensure(self.con, m)

    def add(self, on, salary=300000):
        out = api.run(self.con, "account_add", {"kind": "staff", "name": "Hana",
                                                "salary": salary, "started_on": on,
                                                "view_month": NOW})
        accruals.ensure_all(self.con)
        self.hana = out["id"]
        return out

    def charged(self, month):
        return accruals._salary_charged(self.con, self.hana, month)

    def started(self, on):
        out = api.run(self.con, "staff_started", {"id": self.hana, "on": on})
        accruals.ensure_all(self.con)
        return out

    def test_the_month_they_start_in_is_charged_for_the_days_they_work(self):
        self.add("2026-10-21")
        self.assertEqual(self.charged("2026-09"), 0)
        self.assertEqual(self.charged("2026-10"), 100000)   # the 21st to the 30th: 10 days
        self.assertEqual(self.charged(NOW), 300000)
        p = next(r for r in queries.payroll(self.con, "2026-10") if r["id"] == self.hana)
        self.assertEqual((p["started_on"], p["part"]), ("2026-10-21", {"days": 10, "of": 30}))

    def test_starting_on_the_first_is_the_whole_month(self):
        self.add("2026-10-01")
        self.assertEqual(self.charged("2026-10"), 300000)
        p = next(r for r in queries.payroll(self.con, "2026-10") if r["id"] == self.hana)
        self.assertIsNone(p["part"])

    def test_starting_on_the_last_day_is_one_day(self):
        self.add("2026-10-31")
        self.assertEqual(self.charged("2026-10"), 10000)

    def test_starting_and_leaving_in_one_month(self):
        self.add("2026-10-11")
        api.run(self.con, "account_active", {"id": self.hana, "active": 0,
                                             "left_on": "2026-10-20"})
        accruals.ensure_all(self.con)
        self.assertEqual(self.charged("2026-10"), 100000)   # the 11th to the 20th
        self.assertEqual(self.charged(NOW), 0)

    def test_the_day_can_be_put_right(self):
        self.add("2026-10-21")
        self.started("2026-09-16")                          # earlier: the salary goes back with it
        self.assertEqual(self.charged("2026-09"), 150000)
        self.assertEqual(self.charged("2026-10"), 300000)
        self.started("2026-10-21")                          # and later again
        self.assertEqual(self.charged("2026-09"), 0)
        self.assertEqual(self.charged("2026-10"), 100000)

    def test_a_salary_set_afterwards_starts_with_them(self):
        self.add("2026-10-21", salary="")
        api.run(self.con, "set_salary", {"id": self.hana, "amount": 300000, "view_month": NOW})
        accruals.ensure_all(self.con)
        self.assertEqual(self.charged("2026-10"), 100000)

    def test_a_closed_month_keeps_what_it_was_charged_and_says_so(self):
        self.con.execute("UPDATE period SET status='closed', closed_at='x' WHERE month='2026-09'")
        out = self.add("2026-09-16")
        self.assertEqual(self.charged("2026-09"), 0)
        self.assertEqual(out["note"], "September 2026 is closed, so the salary charged in it "
                                      "stands. Reopen it on Month to put it right.")
        self.assertEqual(self.charged("2026-10"), 300000)
        self.con.execute("UPDATE period SET status='open', closed_at=NULL WHERE month='2026-09'")
        accruals.ensure_all(self.con)
        self.assertEqual(self.charged("2026-09"), 150000)   # the 16th to the 30th

    def test_the_days_must_make_sense(self):
        with self.assertRaises(api.ApiError):
            self.add("2099-01-01")                          # not come yet
        self.add("2026-10-21")
        with self.assertRaises(api.ApiError):               # left before they started
            api.run(self.con, "account_active", {"id": self.hana, "active": 0,
                                                 "left_on": "2026-10-20"})
        api.run(self.con, "account_active", {"id": self.hana, "active": 0,
                                             "left_on": "2026-10-25"})
        with self.assertRaises(api.ApiError):               # started after they left
            self.started("2026-10-26")
        with self.assertRaises(api.ApiError):
            self.started("the first")

    def test_the_record_says_the_day(self):
        self.add("2026-10-21")
        line = db.scalar(self.con, "SELECT detail FROM audit WHERE action = 'account_add' "
                                   "ORDER BY id DESC LIMIT 1")
        self.assertIn("Added Hana, who started on 2026-10-21", line)

    def test_setup_offers_to_put_the_day_right_while_its_month_is_open(self):
        self.add("2026-10-21")
        hana = next(a for a in api.people(self.con)["staff"] if a["id"] == self.hana)
        self.assertTrue(hana["start_open"])
        self.con.execute("UPDATE period SET status='closed', closed_at='x' WHERE month='2026-10'")
        hana = next(a for a in api.people(self.con)["staff"] if a["id"] == self.hana)
        self.assertFalse(hana["start_open"])


class APartnerRetired(unittest.TestCase):
    """Closing splits a month's profit by every partner's share, a retired
    partner's too: retiring one with a share says so, and so do the checks."""

    def setUp(self):
        self.con = fresh_books()
        self.erin = db.scalar(self.con, "SELECT id FROM account WHERE name = 'Erin Moss'")

    def flagged(self):
        from ledger import checks
        return [c["ok"] for c in checks.checks(self.con, NOW) if "retired" in c["label"]]

    def test_retiring_a_partner_with_a_share_says_so(self):
        out = api.run(self.con, "account_active", {"id": self.erin, "active": 0})
        self.assertIn("Erin Moss still has a 50% share", out["note"])
        self.assertEqual(self.flagged(), [False])
        api.run(self.con, "set_share", {"id": self.erin, "share": 0})
        self.assertEqual(self.flagged(), [])

    def test_retiring_one_without_a_share_says_nothing(self):
        api.run(self.con, "set_share", {"id": self.erin, "share": 0})
        out = api.run(self.con, "account_active", {"id": self.erin, "active": 0})
        self.assertIsNone(out["note"])


class Accounts(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_two_things_cannot_share_a_name(self):
        with self.assertRaises(api.ApiError):
            api.run(self.con, "account_add", {"kind": "supplier", "name": "Star Store"})

    def test_nor_a_float_and_a_pot(self):
        """Money is moved by a pot's name, so a float called Bank beside the
        Bank pot could never be paid into: it would all go to the pot."""
        with self.assertRaises(api.ApiError):
            api.run(self.con, "account_add", {"kind": "float", "name": "Bank"})
        f = api.run(self.con, "account_add", {"kind": "float", "name": "Alice holds"})["id"]
        with self.assertRaises(api.ApiError):
            api.run(self.con, "account_rename", {"id": f, "name": "Safe"})
        # a member of staff may still have a pot's name: they are never mixed up
        api.run(self.con, "account_add", {"kind": "staff", "name": "Bank"})

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

    def test_a_month_without_a_meter_reading_does_not_reset_the_meter(self):
        """Saved with only the generator's price, a month stored the meter as
        0, so the next month offered 0 as the last reading and charged every
        unit the meter had ever counted."""
        api.run(self.con, "set_electricity", {"month": "2026-09", "private_price": 8000,
                                              "last_reading": 1000, "now_reading": 1200})
        api.run(self.con, "set_electricity", {"month": "2026-10", "private_price": 8000})
        self.assertEqual(accruals.electricity_view(self.con, "2026-11")["last_reading"], 1200)


class StockItems(unittest.TestCase):
    def test_a_new_item_can_be_added_and_repriced(self):
        con = fresh_books()
        out = api.run(con, "item_add", {"name": "Mint", "letter": "A", "price": 20000})
        api.run(con, "item_update", {"id": out["id"], "price": 22000})
        self.assertEqual(db.one(con, "SELECT price FROM stock_item WHERE id=?",
                                (out["id"],))["price"], 22000)

    def test_a_name_already_in_the_category_is_said_plainly(self):
        con = fresh_books()
        api.run(con, "item_add", {"name": "Hill Leaf", "letter": "B", "price": 30000})
        sea = api.run(con, "item_add", {"name": "Sea Leaf", "letter": "B", "price": 30000})["id"]
        api.run(con, "item_add", {"brand": sea, "name": "Mint"})
        with self.assertRaises(api.ApiError) as cm:
            api.run(con, "item_update", {"id": sea, "name": "Hill Leaf"})
        self.assertEqual(str(cm.exception), "Hill Leaf is already in that category")
        # nor may a brand's new name clash through one of its flavours
        api.run(con, "item_add", {"name": "Bay Leaf · Mint", "letter": "B", "price": 1})
        with self.assertRaises(api.ApiError):
            api.run(con, "item_update", {"id": sea, "name": "Bay Leaf"})
        self.assertEqual(db.scalar(con, "SELECT name FROM stock_item WHERE id = ?", (sea,)),
                         "Sea Leaf")
