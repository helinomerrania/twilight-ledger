"""Where the cash went, entry by entry: what the slips print for each name and
each kind, with the day of each and its time where the books know it.
Everything here is invented."""
import unittest
from datetime import datetime, timezone

from ledger import accruals, api, db, queries, words
from ledger.dates import month_of, prev_month, today
from tests.helpers import RENT, STAFF, fresh_books

NOW = month_of(today())
PREV = prev_month(NOW)
D5, D6 = f"{NOW}-05", f"{NOW}-06"


def local(day, hour, minute):
    """A time on the lounge's clock, on a day of this month."""
    return datetime.fromisoformat(f"{NOW}-{day}T{hour:02d}:{minute:02d}").astimezone()


def written_at(con, entry_id, when):
    """Say an entry was written down at `when`, a time on the lounge's clock."""
    utc = when.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    con.execute("UPDATE entry SET created_at = ? WHERE id = ?", (utc, entry_id))


class EntryByEntry(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        with db.tx(self.con):
            accruals.ensure(self.con, NOW)

    def advance(self, amount, on, who="Alice"):
        return api.run(self.con, "staff_advance", {"amount": amount, "who": who, "on": on,
                                                   "pot": "Box", "allow_overdraw": True})["id"]

    def lines(self, name=None):
        f = queries.money_flow(self.con, NOW)
        return [l for l in f["lines"] if name is None or l["name"] == name]

    def time_of(self, entry_id):
        return next(l["time"] for l in self.lines() if l["id"] == entry_id)

    def test_each_advance_is_there_with_its_day(self):
        self.advance(20000, D5)
        self.advance(100000, D6)
        self.advance(50000, D6, who="Bob")
        alice = self.lines("Alice")
        self.assertEqual([(l["on"], l["amount"], l["out"]) for l in alice],
                         [(D5, 20000, True), (D6, 100000, True)])
        f = queries.money_flow(self.con, NOW)
        group = next(g for g in f["out"] if g["kind"] == "staff_advance")
        self.assertEqual(group["total"], sum(l["amount"] for l in self.lines()
                                             if l["kind"] == "staff_advance"))

    def test_a_renamed_person_is_still_one_person(self):
        """Their entries keep the name written at the time; split by it, the
        same person was two names, and a slip of one missed the other's."""
        self.advance(20000, D5, who="Bob")
        bob = db.one(self.con, "SELECT id FROM account WHERE name = 'Bob'")["id"]
        api.run(self.con, "account_rename", {"id": bob, "name": "Bob Kane"})
        self.advance(30000, D6, who="Bob Kane")
        f = queries.money_flow(self.con, NOW)
        group = next(g for g in f["out"] if g["kind"] == "staff_advance")
        self.assertEqual(group["rows"], [["Bob Kane", 50000]])
        self.assertEqual([l["amount"] for l in self.lines("Bob Kane")], [20000, 30000])
        # and Books finds both by the name they have now
        found = queries.entries(self.con, q="Kane", kind="staff_advance")
        self.assertEqual(sorted(e["amount"] for e in found), [20000, 30000])

    def test_a_kind_is_found_by_the_name_the_screens_show(self):
        """With the screens in Kurdish, an advance is shown by its Kurdish
        name, and the search box only knew the English one."""
        self.advance(20000, D5, who="Bob")
        kurdish = words.kurdish()["kind.staff_advance"]
        for q in ("advance", kurdish, kurdish.split()[0]):
            found = queries.entries(self.con, q=q)
            self.assertEqual([e["kind"] for e in found], ["staff_advance"], q)

    def test_written_down_on_its_night_it_has_that_time(self):
        late = self.advance(20000, D5)
        written_at(self.con, late, local("05", 21, 40))
        self.assertEqual(self.time_of(late), "21:40")

    def test_after_midnight_it_is_still_that_night(self):
        e = self.advance(20000, D5)
        written_at(self.con, e, local("06", 1, 30))
        self.assertEqual(self.time_of(e), "01:30")

    def test_written_down_the_next_day_it_has_only_its_date(self):
        """The time it was typed in is not the time it happened."""
        e = self.advance(20000, D5)
        written_at(self.con, e, local("06", 14, 0))
        self.assertIsNone(self.time_of(e))

    def test_a_correction_keeps_the_time_it_was_first_written(self):
        e = self.advance(20000, D5)
        written_at(self.con, e, local("05", 21, 40))
        new = api.run(self.con, "edit_entry", {"id": e, "amount": 25000, "on": D5,
                                               "pot": "Box", "allow_overdraw": True})["id"]
        written_at(self.con, new, local("07", 12, 0))
        self.assertEqual(self.time_of(new), "21:40")

    def test_from_sambapos_it_has_sambapos_time(self):
        e = self.advance(20000, D5)
        self.con.execute("UPDATE entry SET source = 'pos', source_ref = ? WHERE id = ?",
                         (f"pos:doc:77:{D5.replace('-', '')}223015", e))
        written_at(self.con, e, local("09", 12, 0))
        self.assertEqual(self.time_of(e), "22:30")

    def test_a_nights_takings_have_no_one_time(self):
        api.run(self.con, "sales", {"amount": 400000, "on": D5})
        sales = [l for l in self.lines() if l["kind"] == "daily_sales"]
        self.assertEqual([(l["amount"], l["out"], l["time"]) for l in sales],
                         [(400000, False, None)])


class ForEarlierMonths(unittest.TestCase):
    """The cash that went out this month to pay what was owed from before it,
    oldest debt first, as Settle up and the staff table count it, whichever
    month a payment was said to be for."""

    def setUp(self):
        self.con = fresh_books()
        with db.tx(self.con):
            accruals.ensure(self.con, PREV)
            accruals.ensure(self.con, NOW)

    def pay(self, action, who, amount, period, on=D5):
        return api.run(self.con, action, {"amount": amount, "who": who, "on": on,
                                          "period": period, "pot": "Box",
                                          "allow_overdraw": True})["id"]

    def flow(self):
        return queries.money_flow(self.con, NOW)

    def test_what_was_owed_from_before_is_added_up_by_month_and_by_what(self):
        api.run(self.con, "receipt", {"amount": 150000, "who": "Acme Tobacco",
                                      "on": f"{PREV}-20", "terms": "credit"})
        self.pay("pay_salary", "Alice", STAFF["Alice"], PREV)
        self.pay("pay_salary", "Bob", STAFF["Bob"], PREV, on=D6)
        self.pay("pay_fixed", "Rent", RENT, PREV)
        self.pay("pay_supplier", "Acme Tobacco", 150000, NOW)
        self.pay("pay_supplier", "Star Store", 40000, NOW)      # owed nothing from before
        f = self.flow()
        [m] = f["earlier"]
        kinds = {k["kind"]: (k["total"], k["rows"]) for k in m["kinds"]}
        self.assertEqual(m["month"], PREV)
        self.assertEqual(kinds["salary_payment"],
                         (STAFF["Alice"] + STAFF["Bob"],
                          [["Alice", STAFF["Alice"]], ["Bob", STAFF["Bob"]]]))
        self.assertEqual(kinds["fixed_payment"][0], RENT)
        self.assertEqual(kinds["supplier_payment"], (150000, [["Acme Tobacco", 150000]]))
        self.assertEqual(f["earlier_total"], STAFF["Alice"] + STAFF["Bob"] + RENT + 150000)

    def test_paid_from_this_months_screen_it_still_paid_the_older_debt(self):
        """Paid on this month's Settle up, a payment says it is for this month,
        but what it paid first was last month's salary, as the staff table
        says; counted by what it said, it was missed."""
        e = self.pay("pay_salary", "Carol Hunt", STAFF["Carol Hunt"], NOW)
        line = next(l for l in self.flow()["lines"] if l["id"] == e)
        self.assertEqual(line["earlier"], [[PREV, STAFF["Carol Hunt"]]])
        carol = next(p for p in queries.payroll(self.con, PREV) if p["name"] == "Carol Hunt")
        self.assertEqual(carol["still_to_pay"], 0)

    def test_only_the_older_debt_is_counted_of_a_bigger_payment(self):
        e = self.pay("pay_salary", "Alice", STAFF["Alice"] + 100000, NOW)
        line = next(l for l in self.flow()["lines"] if l["id"] == e)
        self.assertEqual(line["earlier"], [[PREV, STAFF["Alice"]]])
        self.assertEqual(self.flow()["earlier_total"], STAFF["Alice"])

    def test_a_debt_paid_before_the_month_is_not_paid_again(self):
        self.pay("pay_salary", "Alice", STAFF["Alice"], PREV, on=f"{PREV}-28")
        self.pay("pay_salary", "Alice", 100000, NOW)
        self.assertEqual(self.flow()["earlier_total"], 0)

    def test_paid_in_its_own_month_it_is_not_counted(self):
        self.pay("pay_salary", "Alice", STAFF["Alice"], PREV, on=f"{PREV}-28")
        self.assertEqual(queries.money_flow(self.con, NOW)["earlier_total"], 0)
        self.assertEqual(queries.money_flow(self.con, PREV)["earlier_total"], 0)

    def test_money_coming_in_is_not_counted(self):
        api.run(self.con, "staff_repay", {"amount": 10000, "who": "Alice", "on": D5,
                                          "period": PREV, "pot": "Box"})
        self.assertEqual(queries.money_flow(self.con, NOW)["earlier_total"], 0)


if __name__ == "__main__":
    unittest.main()
