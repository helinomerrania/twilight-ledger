"""The rebuild against Mohammed's real books.

These are the tests that matter most. They import the actual export and check
every headline figure against tools/oracle.py — the old app's arithmetic,
reimplemented separately from its source, so the new code is not marking its
own homework — and against the export itself.

No figure and no name from the books is written in this file. The export is
the business's books and this repository is public, so the expected values are
worked out from the export when the tests run. Point TWILIGHT_EXPORT at a copy
to run these; without it they skip, loudly enough to notice.

If someone refactors this project in a year and one of these fails, the
refactor is wrong.
"""
import json
import os
import shutil
import tempfile
import unittest
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from ledger import db, queries
from ledger.dates import month_of
from tools.import_json import BACKDATED
from tools.oracle import Old

EXPORT = os.environ.get("TWILIGHT_EXPORT", "/home/claude/work/latest.json")

HEADLINE = ("sales", "other", "rev", "gross", "daily", "elec", "fixed", "salaries", "net")
COGS = ("opening", "purchases", "closing", "value")


def moved(e):
    """What one old cash-book row moved: out less in."""
    return int(e.get("out") or 0) - int(e.get("in") or 0)


def whole(v):
    """The old app could carry half a dinar, from the Excel workbook it grew
    out of. Money here is whole dinar, halves rounded away from zero."""
    return int(Decimal(str(v)).quantize(Decimal(1), rounding=ROUND_HALF_UP))


@unittest.skipUnless(Path(EXPORT).exists(),
                     f"no export at {EXPORT}; set TWILIGHT_EXPORT to run these")
class RealBooks(unittest.TestCase):
    con = None
    tmp = None

    @classmethod
    def setUpClass(cls):
        from tools.import_json import Importer
        cls.tmp = Path(tempfile.mkdtemp(prefix="twilight-real-"))
        cls.data = json.loads(Path(EXPORT).read_text(encoding="utf-8"))
        cls.con = db.connect(cls.tmp / "twilight.db")
        Importer(cls.data, cls.con).run()
        cls.months = queries.months(cls.con)
        cls.open = [m for m in cls.months if not queries.result(cls.con, m)["frozen"]]
        cls.closed = [m for m in cls.months if m not in cls.open]
        cls.old = Old(cls.data, cls.months[-1])          # the old app, as at today

    @classmethod
    def tearDownClass(cls):
        if cls.con:
            cls.con.close()
        if cls.tmp:
            shutil.rmtree(cls.tmp, ignore_errors=True)

    def code(self, kinds, name):
        marks = ",".join("?" * len(kinds))
        row = db.one(self.con, f"SELECT code FROM account WHERE kind IN ({marks}) "
                               "AND name = ?", (*kinds, name))
        self.assertIsNotNone(row, f"no account for one of the old app's {kinds[0]} names")
        return row["code"]

    # ------------------------------------------------------------ the months
    def test_there_are_open_and_closed_months_to_check(self):
        self.assertTrue(self.open, "the export should leave at least one month open")
        self.assertEqual(sorted(self.closed), sorted(self.data.get("closed") or {}))

    def test_each_open_month_comes_out_as_the_old_app_had_it(self):
        for m in self.open:
            old, new = Old(self.data, m).result(), queries.result(self.con, m)
            for key in HEADLINE:
                self.assertEqual(new[key], old[key], f"{m} {key}")

    def test_each_open_months_cost_of_goods(self):
        for m in self.open:
            old = Old(self.data, m).result()["cogs"]
            new = queries.result(self.con, m)["cogs"]
            for key in COGS:
                self.assertEqual(new[key], old[key], f"{m} cost of goods {key}")
            self.assertEqual(new["date"], old["date"], f"{m} is valued by another count")

    def test_closed_months_stay_exactly_as_they_were_closed(self):
        """Halves of a dinar and all: a closed month is a record of what was
        decided, not something to work out again."""
        for m in self.closed:
            old, new = Old(self.data, m).result(), queries.result(self.con, m)
            self.assertTrue(new["frozen"], f"{m} should be a frozen record")
            for key in HEADLINE:
                if key in old:
                    self.assertEqual(new[key], old[key], f"{m} {key}")

    def test_a_closed_month_is_not_recomputed_from_setup(self):
        """The old app summed the current staff list every time it drew the
        screen, so hiring someone moved a finished month's profit. Here the
        result is a stored record: changing a salary now cannot reach it."""
        first = self.closed[0]
        before = queries.result(self.con, first)["salaries"]
        self.con.execute("UPDATE salary SET amount = amount * 2")
        try:
            self.assertEqual(queries.result(self.con, first)["salaries"], before)
        finally:
            self.con.execute("UPDATE salary SET amount = amount / 2")

    # -------------------------------------------------------------- the cash
    def test_cash_on_hand(self):
        self.assertEqual(queries.cash_on_hand(self.con), self.old.cash_on_hand())

    def test_cash_sits_where_he_left_it(self):
        pots = self.old.pots()
        self.assertTrue(pots)
        for name in pots:
            self.assertEqual(queries.balance(self.con, self.code(("cash", "float"), name)),
                             self.old.pot_balance(name), "a pot holds something else")

    def test_floats_hold_what_they_held(self):
        floats = [p.get("name") for p in self.data["setup"].get("pots") or []
                  if p.get("kind") == "float"]
        self.assertEqual(queries.in_hands(self.con),
                         sum(self.old.pot_balance(n) for n in floats))

    # --------------------------------------------------------- the suppliers
    def test_owed_to_suppliers(self):
        owed = self.old.supplier_owed()
        self.assertEqual(queries.owed_to_suppliers(self.con),
                         sum(max(v, 0) for v in owed.values()))

    def test_each_supplier_balance(self):
        owed = self.old.supplier_owed()
        self.assertTrue(owed)
        for name, want in owed.items():
            self.assertEqual(queries.balance(self.con, self.code(("supplier",), name)),
                             want, "a supplier's balance differs from the old app")

    def test_a_supplier_balance_does_not_depend_on_the_month_on_screen(self):
        """His actual report: 'sometimes it is not 50000 and it is the perfect
        number, especially when i change the months in the settlement months.'"""
        suppliers = queries.balances(self.con, "supplier")
        standing = {a["name"]: a["balance"] for a in suppliers}
        last = self.months[-1]
        for month in self.months:
            rows = {r["name"]: r for r in queries.supplier_statement(self.con, month)}
            self.assertEqual({a["name"]: queries.balance(self.con, a["code"])
                              for a in suppliers}, standing,
                             f"looking at {month} moved a balance")
            if month == last:
                self.assertTrue(rows)
                for name, row in rows.items():
                    self.assertEqual(row["closing"], standing[name],
                                     "the last month's closing is not the balance")

    # ------------------------------------------------- the counts, after the fix
    def test_every_cash_count_ties(self):
        """In the old app two counts never tied, because five payments were
        stamped 31 October and handed over in November. With their real dates,
        every count ties — which is the whole case for having fixed them on
        the way in."""
        breaks = [c for c in queries.cash_counts(self.con) if c["diff"] != 0]
        self.assertEqual(breaks, [], f"{len(breaks)} counts do not tie: "
                                     f"{[(b['on'], b['diff']) for b in breaks]}")

    def test_every_cash_count_came_across(self):
        days = {str(r["d"])[:10] for r in self.data.get("rc") or []}
        self.assertTrue(days)
        self.assertEqual(len(queries.cash_counts(self.con)), len(days))

    def test_the_re_dated_payments_left_when_they_really_did(self):
        """Each of the five is in the export stamped 31 October; here it is on
        the day the money was handed over, still settling October."""
        rows = {str(e.get("id")): e for e in self.data["cb"]}
        for rid, (on, period) in BACKDATED.items():
            e = rows.get(rid)
            self.assertIsNotNone(e, f"row {rid} is not in the export")
            self.assertEqual(month_of(e["d"]), period, f"row {rid} was not stamped {period}")
            found = db.all_(self.con, """
                SELECT e.period FROM entry e
                 WHERE e.happened_on = ? AND e.detail = ? AND e.voided_at IS NULL
                   AND e.kind IN ('salary_payment', 'supplier_payment', 'fixed_payment')
                   AND (SELECT SUM(p.amount) FROM posting p
                         WHERE p.entry_id = e.id AND p.amount > 0) = ?""",
                (on, e.get("x") or "Rent", abs(moved(e))))
            self.assertEqual([f["period"] for f in found], [period],
                             f"row {rid} should be one payment on {on} for {period}")

    # ----------------------------------------------------- nothing was lost
    def test_everything_came_across(self):
        """Counted against the source file, not against the importer's opinion
        of itself: every row in the export that moved money is an entry here."""
        data = self.data
        carries_money = [e for e in data["cb"] if moved(e)]
        stats = json.loads(db.one(self.con, "SELECT detail FROM audit "
                                            "WHERE action='import'")["detail"])["stats"]
        self.assertEqual(stats["entries"], len(carries_money))
        self.assertEqual(stats["receipts"], len(data["pu"]))
        self.assertEqual(stats["cash_counts"], len(data["rc"]))
        self.assertEqual(stats["stock_counts"], len(data["inv"]))
        self.assertEqual(stats["closed_months"], len(data["closed"]))
        self.assertEqual(stats["backdated_fixed"], len(BACKDATED))

        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM receipt"),
                         len(data["pu"]))
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM stock_count"),
                         len(data["inv"]))

    def test_every_cash_book_row_can_be_found_again(self):
        """Not just the right number of rows — the right rows. Each type and
        amount in the export must appear with the same amount here."""
        data = self.data
        want = {}
        for e in data["cb"]:
            if moved(e):
                want[e["t"]] = want.get(e["t"], 0) + abs(moved(e))
        # Daily Sales and Daily Expense are the two that land on their own
        # account and so can be checked straight against it.
        self.assertEqual(
            -db.scalar(self.con, "SELECT SUM(amount) FROM movement "
                                 "WHERE code='rev:sales'"),
            want["Daily Sales"])
        bills = want.get("Monthly Bill", 0)
        electric = sum(abs(moved(e)) for e in data["cb"] if e["t"] == "Monthly Bill"
                       and "electric" in str(e.get("x", "")).lower())
        self.assertEqual(
            db.scalar(self.con, "SELECT SUM(amount) FROM movement "
                                "WHERE code='exp:daily'"),
            want["Daily Expense"] + bills - electric)

    def test_the_people_who_left_are_still_in_the_books(self):
        """Some advances and salaries went to people who are no longer in the
        staff list. The old payroll card read the current list, so that money
        moved the cash and appeared in no table at all. Here every one of those
        payments is an entry with their name on it, on an account marked as
        gone."""
        here = {s.get("name") for s in self.data["setup"].get("staff") or []}
        gone = {}
        for e in self.data["cb"]:
            if (e.get("t") in ("Staff Advance", "Salary Payment") and e.get("x")
                    and e["x"] not in here and moved(e)):
                gone[e["x"]] = gone.get(e["x"], 0) + abs(moved(e))
        self.assertTrue(gone, "the export should hold payments to people who left")
        for name in gone:
            row = db.one(self.con, "SELECT id, active FROM account "
                                   "WHERE kind='staff' AND name = ?", (name,))
            self.assertIsNotNone(row, "someone who left has no account")
            self.assertEqual(row["active"], 0, "someone who left is not marked as gone")
        marks = ",".join("?" * len(gone))
        total = db.scalar(self.con,
            "SELECT COALESCE(SUM(p.amount), 0) FROM entry e "
            "JOIN posting p ON p.entry_id = e.id "
            f"WHERE e.detail IN ({marks}) AND p.amount > 0", tuple(gone))
        self.assertEqual(total, sum(gone.values()))

    def test_nobody_carries_invented_arrears(self):
        """Per-person balances start on 1 October, the same date the old app
        rebased supplier debt on. Before that there is nothing to import: the
        old payroll never carried a balance between months, and the partner
        ledger it wrote shows both partners square at 31 August and 30
        September. Charging four months of today's salaries to people who may
        not have been on them would put imaginary arrears on the screen."""
        for p in queries.payroll(self.con, "2026-10"):
            charged = db.scalar(self.con,
                "SELECT COALESCE(SUM(-m.amount), 0) FROM movement m "
                "WHERE m.account_id = ? AND m.entry_kind = 'salary_charge'",
                (p["id"],))
            top = db.scalar(self.con, "SELECT COALESCE(MAX(amount), 0) FROM salary "
                                      "WHERE account_id = ?", (p["id"],))
            self.assertLessEqual(charged, 2 * top,
                                 "someone is charged for more than two months")
        for prt in queries.partners(self.con, "2026-10"):
            before = queries.balance(self.con,
                db.one(self.con, "SELECT code FROM account WHERE id = ?",
                       (prt["id"],))["code"], as_of="2026-09-30")
            self.assertEqual(before, 0, "a partner does not start square")

    def test_the_books_start_in_august(self):
        """July holds the opening stock count and nothing else. Treating it as
        a month of trading would invent a loss the size of a month's rent and
        salaries, for a month with no sales."""
        self.assertEqual(self.months, ["2026-08", "2026-09", "2026-10", "2026-11"])
        opening = queries.booked(self.con, "2026-07-31")
        self.assertGreater(opening, 0)
        self.assertEqual(opening, whole(Old(self.data, "2026-08").booked("2026-07-31")))

    # ----------------------------------------------------------------- stock
    def test_every_count_is_booked_as_the_old_app_booked_it(self):
        dates = self.old.valued_dates()
        self.assertTrue(dates)
        for d in dates:
            self.assertEqual(queries.booked(self.con, d),
                             whole(Old(self.data, month_of(d)).booked(d)),
                             f"the count on {d}")

    def test_opening_every_count_and_saving_it_back_changes_nothing(self):
        """The test that would have caught the worst bug in this rebuild.

        Reading a count sheet and writing every line straight back must leave
        the figure identical. It did not: the sheet left out the `blocks`
        column, so the box rendered empty and the next save silently wiped
        every tobacco counted in blocks out of the closing stock.
        """
        from ledger import api
        for count_date in queries.count_dates(self.con):
            sheet = api.count_sheet(self.con, count_date)
            if sheet["locked"] or sheet["source"] != "counted":
                continue
            before = queries.booked(self.con, count_date)
            for group in sheet["groups"]:
                for line in group["items"]:
                    if not (line["packages_milli"] or line["blocks_milli"]
                            or line["loose_milli"] or line["gross_grams"]):
                        continue
                    api.run(self.con, "count_line", {
                        "on": count_date, "item": line["id"],
                        "packages": f'{(line["packages_milli"] or 0) / 1000:g}',
                        "blocks": f'{(line["blocks_milli"] or 0) / 1000:g}',
                        "loose": f'{(line["loose_milli"] or 0) / 1000:g}',
                        "gross_grams": line["gross_grams"],
                        "tare_id": line["tare_id"]})
            self.assertEqual(queries.booked(self.con, count_date), before,
                             f"the count on {count_date} moved when saved back")

    def test_the_fractional_counts_survived(self):
        """He counts in tenths — blocks, packs and buckets with a decimal
        point. Dropping the tenths loses tobacco, and money, on every such
        line, so every fractional amount in the export must be here to the
        thousandth."""
        columns = {"B": (("cartons", "packages_milli"), ("blocks", "blocks_milli"),
                         ("packs", "loose_milli")),
                   "E": (("cartons", "packages_milli"), ("buckets", "loose_milli"))}
        others = (("pkg", "packages_milli"), ("pcs", "loose_milli"))
        letters = {it["name"]: str(it.get("category") or "F").strip()[:1].upper()
                   for it in self.data["setup"].get("stockItems") or []}
        seen = 0
        for date, inv in (self.data.get("inv") or {}).items():
            for name, c in (inv.get("counts") or {}).items():
                letter = letters.get(name)
                if letter in (None, "A"):
                    continue
                for field, column in columns.get(letter, others):
                    if c.get(field) in (None, ""):
                        continue
                    v = Decimal(str(c[field]))
                    if v == v.to_integral_value():
                        continue
                    line = db.one(self.con, f"""
                        SELECT l.{column} AS milli FROM stock_count_line l
                          JOIN stock_item si ON si.id = l.item_id
                          JOIN stock_category k ON k.id = si.category_id
                          JOIN stock_count sc ON sc.id = l.count_id
                         WHERE si.name = ? AND k.letter = ? AND sc.count_date = ?""",
                        (name, letter, date))
                    self.assertIsNotNone(line, f"a line counted on {date} is missing")
                    self.assertEqual(line["milli"], int(v * 1000),
                                     f"a fraction counted on {date} was lost")
                    seen += 1
        self.assertGreater(seen, 0, "the export should hold counts in tenths")

    def test_a_setup_price_change_cannot_move_a_count_already_taken(self):
        last = queries.count_dates(self.con)[-1]
        before = queries.booked(self.con, last)
        self.con.execute("UPDATE stock_item SET price = price * 2")
        try:
            self.assertEqual(queries.booked(self.con, last), before)
            self.assertEqual(queries.result(self.con, month_of(last))["cogs"]["closing"],
                             before)
        finally:
            self.con.execute("UPDATE stock_item SET price = price / 2")

    # ------------------------------------------------------------- integrity
    def test_the_books_balance(self):
        self.assertEqual(db.all_(self.con, "SELECT * FROM unbalanced"), [])

    def test_every_account_total_cancels_out(self):
        """The deepest check there is: across all accounts, debits equal
        credits. If this is ever false the ledger has lost money somewhere."""
        self.assertEqual(db.scalar(self.con, "SELECT SUM(amount) FROM posting"), 0)

    def test_sqlite_is_happy(self):
        rep = db.integrity(self.con)
        self.assertEqual(rep["sqlite"], [{"integrity_check": "ok"}])
        self.assertEqual(rep["foreign_keys"], [])
        self.assertTrue(rep["ok"])


if __name__ == "__main__":
    unittest.main()
