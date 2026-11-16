"""Where the cash went, entry by entry: what the slips print for each name and
each kind, with the day of each and its time where the books know it.
Everything here is invented."""
import unittest
from datetime import datetime, timezone

from ledger import accruals, api, db, queries
from ledger.dates import month_of, today
from tests.helpers import fresh_books

NOW = month_of(today())
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


if __name__ == "__main__":
    unittest.main()
