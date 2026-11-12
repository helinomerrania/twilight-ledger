"""Putting things right: the pot guard, corrections, deletions, write-offs,
and what the server refuses outright."""
import unittest

from ledger import accruals, api, db, post, queries
from ledger.dates import month_of, prev_month, today
from ledger.registry import ApiError
from tests.helpers import fresh_books

NOW = month_of(today())
DAY = f"{NOW}-01"                       # always today or earlier
PREV = prev_month(NOW)


def box(con):
    return queries.balance(con, "cash:box")


def last_of(con, kind):
    return queries.entries(con, kind=kind)[0]


class PotGuard(unittest.TestCase):
    """A payment the pot cannot cover is asked about, not silently made."""

    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 100000, "on": DAY})

    def test_paying_more_than_the_box_holds_is_stopped_and_explained(self):
        with self.assertRaises(ApiError) as cm:
            api.run(self.con, "expense", {"amount": 150000, "detail": "Ice", "on": DAY})
        self.assertEqual(cm.exception.status, 409)
        short = cm.exception.extra["overdraw"][0]
        self.assertEqual((short["pot"], short["short_by"], short["holds"]),
                         ("Box", 50000, 100000))

    def test_and_nothing_is_written_when_it_is_stopped(self):
        with self.assertRaises(ApiError):
            api.run(self.con, "expense", {"amount": 150000, "detail": "Ice", "on": DAY})
        self.assertEqual(box(self.con), 100000)
        self.assertEqual(queries.entries(self.con, kind="daily_expense"), [])

    def test_it_goes_through_when_the_answer_is_yes(self):
        api.run(self.con, "expense", {"amount": 150000, "detail": "Ice", "on": DAY,
                                      "allow_overdraw": True})
        self.assertEqual(box(self.con), -50000)

    def test_a_payment_dated_before_the_money_arrived_is_caught(self):
        with self.assertRaises(ApiError) as cm:
            api.run(self.con, "expense", {"amount": 50000, "detail": "Ice",
                                          "on": f"{PREV}-15"})
        self.assertEqual(cm.exception.status, 409)

    def test_money_coming_in_is_never_stopped(self):
        api.run(self.con, "expense", {"amount": 150000, "detail": "Ice", "on": DAY,
                                      "allow_overdraw": True})
        api.run(self.con, "income", {"amount": 1000, "detail": "Scrap", "on": DAY})
        self.assertEqual(box(self.con), -49000)


class Corrections(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 500000, "on": DAY})
        self.eid = api.run(self.con, "expense", {"amount": 5000, "detail": "Ice",
                                                 "on": DAY})["id"]

    def test_a_correction_stands_in_for_the_original(self):
        new = api.run(self.con, "edit_entry", {"id": self.eid, "amount": 6000})["id"]
        old = db.one(self.con, "SELECT * FROM entry WHERE id = ?", (self.eid,))
        self.assertIsNotNone(old["voided_at"])
        self.assertEqual(old["replaced_by"], new)
        self.assertEqual(queries.entries(self.con, ids=[new])[0]["amount"], 6000)
        self.assertEqual(queries.live_result(self.con, NOW)["daily"], 6000)
        self.assertEqual(box(self.con), 494000)

    def test_a_corrected_entry_cannot_be_put_back(self):
        api.run(self.con, "edit_entry", {"id": self.eid, "amount": 6000})
        with self.assertRaises(ApiError):
            api.run(self.con, "put_back", {"id": self.eid})
        self.assertFalse(any(r["can_put_back"] for r in queries.recent(self.con)))

    def test_a_new_date_brings_its_month_with_it(self):
        new = api.run(self.con, "edit_entry", {"id": self.eid, "on": f"{PREV}-20",
                                               "allow_overdraw": True})["id"]
        self.assertEqual(queries.entries(self.con, ids=[new])[0]["period"], PREV)

    def test_unless_it_was_put_in_a_month_on_purpose(self):
        with db.tx(self.con):
            accruals.ensure(self.con, PREV)
        pid = api.run(self.con, "pay_salary", {"amount": 100000, "who": "Bob",
                                               "on": DAY, "period": PREV})["id"]
        new = api.run(self.con, "edit_entry", {"id": pid, "amount": 117250})["id"]
        self.assertEqual(queries.entries(self.con, ids=[new])[0]["period"], PREV)

    def test_deleting_and_putting_back(self):
        api.run(self.con, "void", {"id": self.eid})
        self.assertEqual(queries.live_result(self.con, NOW)["daily"], 0)
        self.assertTrue(queries.recent(self.con)[0]["can_put_back"])
        api.run(self.con, "put_back", {"id": self.eid})
        self.assertEqual(queries.live_result(self.con, NOW)["daily"], 5000)

    def test_correcting_a_receipt_replaces_the_receipt_as_well(self):
        rid = api.run(self.con, "receipt", {"amount": 40000, "who": "Star Store",
                                            "on": DAY})["id"]
        api.run(self.con, "edit_entry", {"id": rid, "amount": 45000})
        rows = db.all_(self.con, "SELECT amount, voided_at FROM receipt ORDER BY id")
        self.assertEqual([(r["amount"], r["voided_at"] is not None) for r in rows],
                         [(40000, True), (45000, False)])
        self.assertEqual(queries.purchases_in(self.con, NOW), 45000)
        self.assertEqual(queries.balance(self.con, "sup:star-store"), 45000)

    def test_deleting_a_receipt_takes_it_out_of_what_was_bought(self):
        rid = api.run(self.con, "receipt", {"amount": 40000, "who": "Star Store",
                                            "on": DAY})["id"]
        api.run(self.con, "void", {"id": rid})
        self.assertEqual(queries.purchases_in(self.con, NOW), 0)
        self.assertEqual(queries.balance(self.con, "sup:star-store"), 0)
        api.run(self.con, "put_back", {"id": rid})
        self.assertEqual(queries.purchases_in(self.con, NOW), 40000)

    def test_a_charge_the_app_works_out_cannot_be_edited(self):
        with db.tx(self.con):
            accruals.ensure(self.con, NOW)
        charge = last_of(self.con, "salary_charge")
        self.assertFalse(charge["editable"])
        with self.assertRaises(ApiError):
            api.run(self.con, "edit_entry", {"id": charge["id"], "amount": 1})

    def test_a_closed_month_cannot_be_corrected(self):
        self.con.execute("INSERT OR IGNORE INTO period(month) VALUES (?)", (NOW,))
        self.con.execute("UPDATE period SET status = 'closed', closed_at = 'x' WHERE month = ?",
                         (NOW,))
        with self.assertRaises(ApiError):
            api.run(self.con, "edit_entry", {"id": self.eid, "amount": 6000})
        with self.assertRaises(ApiError):
            api.run(self.con, "void", {"id": self.eid})


class WriteOff(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 100000, "on": DAY})
        self.cid = api.run(self.con, "cash_count", {"on": DAY, "pots": {"Box": 99000}})["id"]

    def count(self):
        return next(c for c in queries.cash_counts(self.con) if c["id"] == self.cid)

    def test_a_count_records_the_difference_and_moves_nothing(self):
        self.assertEqual(self.count()["diff"], -1000)
        self.assertEqual(box(self.con), 100000)

    def test_writing_it_off_makes_it_a_cost_of_the_month(self):
        before = queries.live_result(self.con, NOW)["net"]
        api.run(self.con, "write_off", {"id": self.cid})
        c = self.count()
        self.assertEqual((c["found"], c["written_off"], c["diff"]), (-1000, -1000, 0))
        self.assertEqual(box(self.con), 99000)
        r = queries.live_result(self.con, NOW)
        self.assertEqual(r["differences"], 1000)
        self.assertEqual(r["net"], before - 1000)

    def test_money_found_over_is_a_gain(self):
        cid = api.run(self.con, "cash_count", {"on": DAY, "pots": {"Box": 101000}})["id"]
        before = queries.live_result(self.con, NOW)["net"]
        api.run(self.con, "write_off", {"id": cid})
        self.assertEqual(queries.live_result(self.con, NOW)["net"], before + 1000)

    def test_there_is_nothing_to_write_off_twice(self):
        api.run(self.con, "write_off", {"id": self.cid})
        with self.assertRaises(ApiError):
            api.run(self.con, "write_off", {"id": self.cid})

    def test_a_written_off_count_is_kept_until_its_write_off_is_deleted(self):
        api.run(self.con, "write_off", {"id": self.cid})
        with self.assertRaises(ApiError):
            api.run(self.con, "delete_cash_count", {"id": self.cid})
        api.run(self.con, "void", {"id": last_of(self.con, "cash_difference")["id"]})
        api.run(self.con, "delete_cash_count", {"id": self.cid})
        self.assertEqual(queries.cash_counts(self.con), [])


class Refused(unittest.TestCase):
    """What the server will not accept, whatever the screen sends."""

    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 100000, "on": DAY})

    def refused(self, action, body):
        with self.assertRaises(ApiError):
            api.run(self.con, action, body)

    def test_a_date_in_the_future(self):
        self.refused("expense", {"amount": 1000, "detail": "Ice", "on": "2999-01-01"})

    def test_a_date_that_is_not_one(self):
        self.refused("expense", {"amount": 1000, "detail": "Ice", "on": "2026-02-30"})

    def test_a_negative_or_missing_amount(self):
        self.refused("expense", {"amount": -1000, "detail": "Ice", "on": DAY})
        self.refused("expense", {"amount": 0, "detail": "Ice", "on": DAY})
        self.refused("expense", {"amount": "lots", "detail": "Ice", "on": DAY})

    def test_a_month_that_has_not_started(self):
        self.refused("expense", {"amount": 1000, "detail": "Ice", "on": DAY,
                                 "period": "2999-01"})

    def test_a_pot_that_does_not_exist(self):
        self.refused("expense", {"amount": 1000, "detail": "Ice", "on": DAY,
                                 "pot": "Under the mattress"})

    def test_a_retired_pot(self):
        bank = db.one(self.con, "SELECT id FROM account WHERE name = 'Bank'")
        api.run(self.con, "account_active", {"id": bank["id"], "active": 0})
        self.refused("expense", {"amount": 1000, "detail": "Ice", "on": DAY, "pot": "Bank"})

    def test_someone_who_is_not_on_the_staff(self):
        self.refused("staff_advance", {"amount": 1000, "who": "Frank Hale", "on": DAY})

    def test_an_expense_with_no_name(self):
        self.refused("expense", {"amount": 1000, "on": DAY})


class MainPot(unittest.TestCase):
    def test_renaming_the_box_keeps_it_the_main_pot(self):
        con = fresh_books()
        b = db.one(con, "SELECT id FROM account WHERE name = 'Box'")
        api.run(con, "account_rename", {"id": b["id"], "name": "Cash drawer"})
        api.run(con, "sales", {"amount": 1000, "on": DAY})
        self.assertEqual(post.main_pot(con)["name"], "Cash drawer")
        self.assertEqual(queries.balance(con, "cash:box"), 1000)


class AfterARename(unittest.TestCase):
    """A correction stays with the person it was for, found by the account it
    was posted to, whatever the name written on it now belongs to."""

    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 400000, "on": DAY})
        self.adv = api.run(self.con, "staff_advance",
                           {"amount": 10000, "who": "Bob", "on": DAY})["id"]
        self.bob = db.one(self.con, "SELECT id, code FROM account WHERE name = 'Bob'")

    def rename(self, name):
        api.run(self.con, "account_rename", {"id": self.bob["id"], "name": name})

    def posted_to(self, entry_id):
        return {r["account_id"] for r in db.all_(
            self.con, "SELECT account_id FROM posting WHERE entry_id = ?", (entry_id,))}

    def test_not_to_someone_new_with_the_old_name(self):
        self.rename("Bob (left)")
        api.run(self.con, "account_add", {"kind": "staff", "name": "Bob", "salary": 100000})
        e = queries.entries(self.con, ids=[self.adv])[0]
        self.assertEqual((e["detail"], e["who"]), ("Bob", "Bob (left)"))
        fixed = api.run(self.con, "edit_entry", {"id": self.adv, "amount": 12000})["id"]
        self.assertIn(self.bob["id"], self.posted_to(fixed))

    def test_after_two_renames(self):
        self.rename("Bobby")
        later = api.run(self.con, "staff_advance", {"amount": 5000, "who": "Bobby", "on": DAY})["id"]
        self.rename("Robert")
        fixed = api.run(self.con, "edit_entry", {"id": later, "amount": 6000})["id"]
        self.assertIn(self.bob["id"], self.posted_to(fixed))

    def test_moved_to_someone_else_on_purpose(self):
        fixed = api.run(self.con, "edit_entry", {"id": self.adv, "detail": "Alice"})["id"]
        alice = db.scalar(self.con, "SELECT id FROM account WHERE name = 'Alice'")
        self.assertIn(alice, self.posted_to(fixed))

    def test_a_receipt_paid_in_cash_keeps_its_supplier(self):
        r = api.run(self.con, "receipt", {"amount": 20000, "on": DAY, "who": "Star Store",
                                          "terms": "cash"})["id"]
        sup = db.scalar(self.con, "SELECT id FROM account WHERE name = 'Star Store'")
        api.run(self.con, "account_rename", {"id": sup, "name": "Star Store (old)"})
        api.run(self.con, "account_add", {"kind": "supplier", "name": "Star Store"})
        fixed = api.run(self.con, "edit_entry", {"id": r, "amount": 21000})["id"]
        self.assertEqual(db.scalar(self.con, "SELECT supplier_id FROM receipt WHERE entry_id = ?",
                                   (fixed,)), sup)


if __name__ == "__main__":
    unittest.main()
