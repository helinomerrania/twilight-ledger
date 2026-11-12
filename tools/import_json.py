"""Move the old books into the new ones.

Reads a twilight-books.json export and rebuilds it as accounts, periods and
balanced postings. Nothing is thrown away: every cash entry, supplier receipt,
cash count and stock count, the closed months and all the Setup lists come
across.

Five rows need a decision rather than a translation, and this is where it is
made. The old Settle-up screen wrote a payment, stamped it with the end of the
settlement month, and then immediately re-dated it to the month being settled
— the change log shows the add and the edit in the same minute. The result was
five payments dated 31 October that had actually been handed over in November,
which is why two of the sixty cash counts could never tie.

  two salary payments    really paid 2026-11-03
  one supplier payment   really paid 2026-11-03
  one salary payment     really paid 2026-11-05
  the rent               really paid 2026-11-08

Each keeps its real payment date and is tagged to the October period, so the
cash leaves in November where it really did and October's obligations are still
settled by it. October's profit is unchanged: rent and salaries are charged to
the month regardless of when they are paid.

Usage:
    python3 tools/import_json.py twilight-books.json [--db data/twilight.db]
                                 [--as-is] [--quiet]

--as-is imports the five rows exactly as the old app held them.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import db, post, stock                             # noqa: E402
from ledger.dates import month_of, next_month, ymd             # noqa: E402
from ledger.money import to_int                                # noqa: E402

# The five, by the row id they carry in the old file.
BACKDATED = {
    "rmw0pl865nejv": ("2026-11-03", "2026-10"),   # Salary Payment
    "rmw0qyfhzfao6": ("2026-11-03", "2026-10"),   # Supplier Payment
    "rmw0s1h3ebx2u": ("2026-11-03", "2026-10"),   # Salary Payment
    "rmw3ehn72st3w": ("2026-11-05", "2026-10"),   # Salary Payment
    "rmw7m7tt6slvo": ("2026-11-08", "2026-10"),   # Fixed Expense Payment, the rent
}

XFER = "Cash Transfer"
EPAY = "Electricity Payment"


def rnd(v):
    """Old figures can carry a half dinar from the Excel workbook. Money here is
    whole dinar, so a stored figure is rounded once, on the way in, and the
    original stays in the frozen month record."""
    f = float(v or 0)
    return int(f + 0.5) if f >= 0 else -int(-f + 0.5)


class Importer:
    def __init__(self, data, con, *, fix=True, log=print):
        self.d = data
        self.setup = data.get("setup") or {}
        self.con = con
        self.fix = fix
        self.log = log
        self.counts = {}        # account name -> id cache
        self.stats = {}
        self.skipped = []
        self.former = []        # people in the history but not in Setup

    # ------------------------------------------------------------- accounts
    def accounts(self):
        con = self.con
        post.ensure_system_accounts(con)
        n = 0
        for p in self.setup.get("pots") or []:
            kind = "float" if p.get("kind") == "float" else "cash"
            post.ensure_account(con, f"{post._prefix(kind)}:{post.slug(p['name'])}",
                                p["name"], kind, 1, sort=n)
            n += 1
        for i, s in enumerate(self.setup.get("suppliers") or []):
            post.ensure_account(con, f"sup:{post.slug(s)}", s, "supplier", -1, sort=i)
        for i, s in enumerate(self.setup.get("staff") or []):
            post.ensure_account(con, f"staff:{post.slug(s['name'])}", s["name"],
                                "staff", -1, meta={"carryIn": to_int(s.get("carryIn"))},
                                sort=i)
        for i, p in enumerate(self.setup.get("partners") or []):
            post.ensure_account(con, f"prt:{post.slug(p['name'])}", p["name"],
                                "partner", -1, meta={"share": p.get("share")}, sort=i)
        self.stats["accounts"] = db.scalar(con, "SELECT count(*) FROM account")

    # ---------------------------------------------------------------- setup
    def reference_data(self):
        con = self.con
        b = self.setup.get("business") or {}
        db.set_setting(con, "business", {
            "name": b.get("name") or "Twilight Rest & Cafe",
            "owner": b.get("owner"),
            "currency": b.get("currency") or "IQD",
            "note": to_int(b.get("rounding") or 250)})
        db.set_setting(con, "conversions", self.setup.get("conversions") or {})
        db.set_setting(con, "elec_factors", (self.d.get("elec") or {}).get("factors") or {})
        db.set_setting(con, "imported_from", {
            "savedAt": self.d.get("savedAt"), "version": self.d.get("v")})

        lists = {"expense": None, "reason": self.setup.get("reasons") or [],
                 "income": None, "bill": None}
        for t in self.setup.get("types") or []:
            if t.get("name") == "Daily Expense":
                lists["expense"] = t.get("details") or []
            elif t.get("name") == "Other Income":
                lists["income"] = t.get("details") or []
            elif t.get("name") == "Monthly Bill":
                lists["bill"] = t.get("details") or []
        for name, values in lists.items():
            for i, v in enumerate(values or []):
                con.execute("INSERT INTO pick_list(list, value, sort) VALUES (?,?,?) "
                            "ON CONFLICT(list, value) DO NOTHING", (name, v, i))

        for i, c in enumerate(self.setup.get("categories") or []):
            letter = str(c).strip()[:1].upper()
            con.execute("INSERT INTO stock_category(letter, name, sort) VALUES (?,?,?) "
                        "ON CONFLICT(letter) DO UPDATE SET name = excluded.name",
                        (letter, c, i))
        cats = {r["letter"]: r["id"] for r in db.all_(con, "SELECT * FROM stock_category")}
        for i, it in enumerate(self.setup.get("stockItems") or []):
            letter = str(it.get("category") or "F").strip()[:1].upper()
            cid = cats.get(letter)
            if cid is None:
                con.execute("INSERT INTO stock_category(letter, name, sort) VALUES (?,?,?)",
                            (letter, it.get("category") or letter, 99))
                cid = con.execute("SELECT id FROM stock_category WHERE letter = ?",
                                  (letter,)).fetchone()["id"]
                cats[letter] = cid
            supplier = None
            if it.get("supplier"):
                r = con.execute("SELECT id FROM account WHERE kind = 'supplier' AND name = ?",
                                (it["supplier"],)).fetchone()
                supplier = r["id"] if r else None
            con.execute(
                "INSERT INTO stock_item(name, category_id, unit, price, pack_size, sort, "
                "supplier_id) VALUES (?,?,?,?,?,?,?) ON CONFLICT(name, category_id) DO UPDATE "
                "SET price = excluded.price, pack_size = excluded.pack_size, "
                "supplier_id = excluded.supplier_id",
                (it["name"], cid, _unit(letter), to_int(it.get("price")),
                 to_int(it.get("per")) or None, i, supplier))
        for t in self.setup.get("tare") or []:
            con.execute("INSERT INTO tare(name, grams) VALUES (?,?) "
                        "ON CONFLICT(name) DO UPDATE SET grams = excluded.grams",
                        (t["name"], to_int(t.get("g"))))

        for i, f in enumerate(self.setup.get("fixedExpenses") or []):
            con.execute(
                "INSERT INTO fixed_charge(name, amount, account_id) VALUES (?,?,?) "
                "ON CONFLICT(name) DO UPDATE SET amount = excluded.amount",
                (f["name"], to_int(f.get("amount")),
                 post.account_id(con, "exp:rent")))
        # Salaries are dated from the first month that is still open. The
        # closed months keep the totals they were closed with, so there is
        # nothing to say about what anyone earned before that.
        for s in self.setup.get("staff") or []:
            con.execute("INSERT INTO salary(account_id, amount, from_month) VALUES (?,?,?) "
                        "ON CONFLICT(account_id, from_month) DO UPDATE SET amount = excluded.amount",
                        (post.account_by_name(con, "staff", s["name"]),
                         to_int(s.get("salary")), self.first_open_month()))
        self.stats["stock_items"] = db.scalar(con, "SELECT count(*) FROM stock_item")

    # -------------------------------------------------------------- periods
    def first_month(self):
        """The first month the business actually traded.

        Deliberately not the first stock count: the earliest count is dated
        2026-07-31 and is the opening position carried in from the Excel
        workbook, not a month of trading. Including July would invent a month
        with no sales but a full rent and salary bill — a phantom loss that
        never happened.
        """
        days = [ymd(e["d"]) for e in self.d.get("cb") or []]
        days += [ymd(p["d"]) for p in self.d.get("pu") or []]
        return min(days)[:7] if days else "2026-08"

    def first_open_month(self):
        """The first month that was never closed — where live tracking begins."""
        closed = set(self.d.get("closed") or {})
        for m in self.months():
            if m not in closed:
                return m
        return self.last_month()

    def last_month(self):
        days = [ymd(e["d"]) for e in self.d.get("cb") or []]
        return max(days)[:7] if days else self.first_month()

    def months(self):
        m, last, out = self.first_month(), self.last_month(), []
        while m <= last:
            out.append(m)
            m = next_month(m)
        return out

    def periods(self):
        for m in self.months():
            post.ensure_period(self.con, m)
        self.stats["months"] = len(self.months())

    # ------------------------------------------------------- opening position
    def openings(self):
        """Debts and stock that predate the books, booked against Opening balances."""
        con = self.con
        debt = self.d.get("debt") or {}
        as_at = debt.get("asAt")
        n = 0
        for name, amount in (debt.get("brought") or {}).items():
            amount = to_int(amount)
            if not amount:
                continue
            sup = post.account_by_name(con, "supplier", name)
            post.record(con, kind="opening", on=as_at or self.first_month() + "-01",
                        detail=name, memo=f"owed to {name} as at {as_at}",
                        source="import", allow_closed=True,
                        legs=[(post.account_id(con, "eq:opening"), amount),
                              (sup, -amount)])
            n += 1
        self.stats["supplier_openings"] = n

        # Stock on hand at the very first count, so the inventory account starts
        # where the workbook left off.
        inv = self.d.get("inv") or {}
        if inv:
            first_count = min(inv)
            opening = rnd((inv[first_count] or {}).get("closing") or 0)
            if opening:
                # Dated when the count was taken, but belonging to the first
                # month of trading. Without the explicit period this entry
                # would open a July that never traded, and the app would show
                # a month with no sales carrying a full rent and salary bill.
                post.record(con, kind="opening", on=first_count,
                            period=self.first_month(),
                            detail="Stock on hand", source="import",
                            allow_closed=True,
                            memo=f"carried in from the workbook at {first_count}",
                            legs=[(post.account_id(con, "inv:stock"), opening),
                                  (post.account_id(con, "eq:opening"), -opening)])
                self.stats["opening_stock"] = opening

        for s in self.setup.get("staff") or []:
            carry = to_int(s.get("carryIn"))
            if carry:
                who = post.account_by_name(con, "staff", s["name"])
                post.record(con, kind="opening", on=self.first_month() + "-01",
                            detail=s["name"], source="import", allow_closed=True,
                            legs=[(post.account_id(con, "eq:opening"), carry),
                                  (who, -carry)])

    # ----------------------------------------------------------------- stock
    def stock_counts(self):
        con = self.con
        from tools.oracle import Old
        n, counts_todo = 0, []
        for date in sorted(self.d.get("inv") or {}):
            raw = (self.d["inv"] or {}).get(date) or {}
            counted = bool(raw.get("counts"))
            o = Old(self.d, month_of(date))
            closing = rnd(o.booked(date))
            cur = con.execute(
                "INSERT INTO stock_count(count_date, closing, source, note) VALUES (?,?,?,?)",
                (date, closing, "counted" if counted else "carried", raw.get("note")))
            cid = cur.lastrowid
            n += 1
            if not counted:
                continue
            counts_todo.append((cid, date, raw))
            for item in self.setup.get("stockItems") or []:
                c = (raw.get("counts") or {}).get(item["name"])
                if not c:
                    continue
                letter = str(item.get("category") or "F").strip()[:1].upper()
                qty = o.item_qty(item, raw.get("counts") or {})
                price = o.price_of(item, date)
                row = con.execute(
                    "SELECT si.id FROM stock_item si JOIN stock_category sc "
                    "ON sc.id = si.category_id WHERE si.name = ? AND sc.letter = ?",
                    (item["name"], letter)).fetchone()
                if not row:
                    continue
                tare_id = None
                if c.get("bucket"):
                    t = con.execute("SELECT id FROM tare WHERE name = ?",
                                    (c["bucket"],)).fetchone()
                    tare_id = t["id"] if t else None
                # Each category counts in its own units; see the comment on
                # stock_count_line. Getting this mapping wrong is invisible
                # until someone edits a line and the value jumps.
                #
                # Counted amounts arrive as decimals — 65.4 blocks, 0.1 of a
                # packet — and are stored as thousandths so the tenths survive.
                if letter == "B":
                    packages, blocks, loose = (c.get("cartons"), c.get("blocks"),
                                               c.get("packs"))
                elif letter == "E":
                    packages, blocks, loose = c.get("cartons"), None, c.get("buckets")
                else:
                    packages, blocks, loose = c.get("pkg"), None, c.get("pcs")
                con.execute(
                    "INSERT INTO stock_count_line(count_id, item_id, packages_milli, "
                    "blocks_milli, loose_milli, gross_grams, tare_id, price, "
                    "qty_milli, value) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (cid, row["id"], stock.to_milli(packages),
                     stock.to_milli(blocks), stock.to_milli(loose),
                     to_int(c.get("g")) or None, tare_id, rnd(price),
                     rnd(qty * 1000), rnd(qty * price)))
        # Book each counted sheet at the sum of its own lines, so the figure on
        # screen and the lines underneath it can never drift apart. Every one of
        # his counts rounds to the same figure the old app booked.
        from ledger.money import mround
        for cid, date, _raw in counts_todo:
            total = db.scalar(con, "SELECT COALESCE(SUM(value),0) FROM stock_count_line "
                                   "WHERE count_id = ?", (cid,))
            con.execute("UPDATE stock_count SET closing = ? WHERE id = ?",
                        (mround(total), cid))
        self.stats["stock_counts"] = n

    # -------------------------------------------------------------- receipts
    def receipts(self):
        con = self.con
        n = 0
        for p in sorted(self.d.get("pu") or [], key=lambda x: ymd(x["d"])):
            amount = to_int(p.get("amt"))
            if not amount:
                continue
            name = p.get("s")
            try:
                sup = post.account_by_name(con, "supplier", name)
            except db.LedgerError:
                sup = post.ensure_account(con, f"sup:{post.slug(name)}", name,
                                          "supplier", -1)
            on = ymd(p["d"])
            terms = "cash" if str(p.get("terms")).lower() == "cash" else "credit"
            # A credit receipt from before the rebase date is already inside the
            # brought-forward figure, so it must not add to the debt again. The
            # goods did arrive, so stock still goes up and the other side lands
            # on Opening balances.
            if terms == "credit" and self.before_rebase(on):
                eid = post.record(
                    con, kind="receipt_credit", on=on, period=month_of(on),
                    detail=name, source="import", memo=p.get("w") or p.get("no"),
                    legs=[(post.account_id(con, "inv:stock"), amount),
                          (post.account_id(con, "eq:opening"), -amount)])
            else:
                eid = post.receipt_in(con, amount, supplier=name, on=on, terms=terms,
                                      what=p.get("w"), number=p.get("no"),
                                      period=month_of(on))
            con.execute(
                "INSERT INTO receipt(received_on, supplier_id, number, what, amount, "
                "terms, entry_id) VALUES (?,?,?,?,?,?,?)",
                (on, sup, p.get("no"), p.get("w"), amount, terms, eid))
            n += 1
        self.stats["receipts"] = n

    # ------------------------------------------------------------ cash book
    def cashbook(self):
        rows = sorted(self.d.get("cb") or [], key=lambda e: (ymd(e["d"]), str(e.get("id"))))
        n, fixed = 0, 0
        for e in rows:
            rid = str(e.get("id"))
            on = ymd(e["d"])
            period = month_of(e.get("m") or on) if e.get("m") else month_of(on)
            if self.fix and rid in BACKDATED:
                on, period = BACKDATED[rid]
                fixed += 1
            try:
                if self.one_row(e, on, period):
                    n += 1
            except db.LedgerError as exc:
                self.skipped.append({"id": rid, "type": e.get("t"),
                                     "detail": e.get("x"), "why": str(exc)})
        self.stats["entries"] = n
        self.stats["backdated_fixed"] = fixed

    def one_row(self, e, on, period):
        """Translate one old cash-book row.

        A handful of rows run the opposite way to their type: a Staff Advance
        with money coming *in* is a repayment, not an advance. Rather than
        inventing new types for those, the amount is signed — `out` minus `in`
        for a type that normally takes money out — and the recipes reverse
        naturally, because a negative debit is a credit.
        """
        con = self.con
        t = e.get("t")
        detail = e.get("x")
        pot = e.get("p") or "Box"
        inn, out = to_int(e.get("in")), to_int(e.get("out"))
        paid = out - inn          # positive: money left the pot
        got = inn - out           # positive: money came into the pot
        if paid == 0:
            return False
        kw = dict(on=on, period=period)

        if t == "Daily Sales":
            post.sales(con, got, into=pot, detail=detail or "Total sales of the day", **kw)
        elif t == "Other Income":
            post.other_income(con, got, detail=detail or "Other income", into=pot, **kw)
        elif t == "Daily Expense":
            post.daily_expense(con, paid, detail=detail or "Other", out_of=pot, **kw)
        elif t == "Monthly Bill":
            if _is_electric(detail):
                post.pay_electricity(con, paid, out_of=pot, **kw)
            else:
                post.daily_expense(con, paid, detail=detail or "Bill", out_of=pot, **kw)
        elif t == EPAY:
            post.pay_electricity(con, paid, out_of=pot, **kw)
        elif t == "Staff Advance":
            who = self.staff(detail)
            # Money coming in on a Staff Advance is the member of staff
            # handing cash back — Mohammed recorded returned advances
            # this way on purpose. It is imported as what it was.
            kind = "staff_advance" if paid > 0 else "staff_repayment"
            if self.before_rebase(on):
                self.pre_rebase(kind=kind, on=on, period=period,
                                detail=who, amount=paid, pot=pot)
            elif paid > 0:
                post.staff_advance(con, paid, staff=who, out_of=pot, **kw)
            else:
                post.staff_repay(con, -paid, staff=who, into=pot, **kw)
        elif t == "Salary Payment":
            who = self.staff(detail)
            if self.before_rebase(on):
                self.pre_rebase(kind="salary_payment", on=on, period=period,
                                detail=who, amount=paid, pot=pot)
            else:
                post.pay_salary(con, paid, staff=who, out_of=pot, **kw)
        elif t == "Supplier Payment":
            name = self.supplier(detail)
            if self.before_rebase(on):
                # The brought-forward figure already says what was still owed
                # on the rebase date, so a payment made before it must not come
                # off the debt a second time. The cash still left the box, so
                # the other side goes to Opening balances, which is what that
                # account is for: absorbing a set of books that starts
                # part-way through a story.
                post.record(con, kind="supplier_payment", on=on, period=period,
                            detail=name, source="import",
                            memo=f"paid before the debt was rebased at {self.as_at()}",
                            legs=[(post.account_id(con, "eq:opening"), paid),
                                  (post.account_by_name_any(con, pot), -paid)])
            else:
                post.pay_supplier(con, paid, supplier=name, out_of=pot, **kw)
        elif t == "Supplier Cash Purchase":
            post.receipt_in(con, paid, supplier=self.supplier(detail), terms="cash",
                            out_of=pot, **kw)
        elif t in ("Owner Advance", "Partner Settlement"):
            who = self.partner(detail)
            kind = "partner_draw" if paid > 0 else "partner_in"
            if self.before_rebase(on):
                self.pre_rebase(kind=kind, on=on, period=period,
                                detail=who, amount=paid, pot=pot)
            elif paid > 0:
                post.partner_draw(con, paid, partner=who, out_of=pot, **kw)
            else:
                post.partner_in(con, -paid, partner=who, into=pot, **kw)
        elif t in ("Owner Repayment", "Owner Capital In"):
            who = self.partner(detail)
            if self.before_rebase(on):
                self.pre_rebase(kind="partner_in", on=on, period=period,
                                detail=who, amount=-got, pot=pot)
            else:
                post.partner_in(con, got, partner=who, into=pot, **kw)
        elif t == "Fixed Expense Payment":
            if self.before_rebase(on):
                self.pre_rebase(kind="fixed_payment", on=on, period=period,
                                detail=detail or "Rent", amount=paid, pot=pot)
            else:
                post.pay_fixed(con, paid, name=detail or "Rent", out_of=pot, **kw)
        elif t == XFER:
            post.transfer(con, paid, frm=pot, to=e.get("p2") or "Bank", **kw)
        else:
            raise db.LedgerError(f"unknown type {t!r}")
        return True

    # Names that appear in the history but not in the current Setup lists.
    # Two members of staff left; their advances and salary
    # payments were moving cash while the old payroll table, which read the
    # current staff list, showed nothing at all. They get an account, marked
    # as no longer here, so the money stays visible instead of unexplained.
    def staff(self, name):
        return self._ensure_person(name or "Unnamed", "staff", "staff")

    def partner(self, name):
        return self._ensure_person(name or "Unnamed", "partner", "prt")

    def supplier(self, name):
        return self._ensure_person(name or "Unnamed", "supplier", "sup")

    def pre_rebase(self, *, kind, on, period, detail, amount, pot):
        """Cash that moved before per-person tracking starts.

        The old app never carried a staff or partner balance from one month to
        the next — `still to pay` was always this month's salary less this
        month's advances and payments, and the partner ledger it wrote shows
        both partners square at 31 August and 30 September. So there is no
        historical per-person balance to import, and inventing one would put
        four months of imaginary arrears in front of Mohammed.

        Everything on or before the rebase date is therefore recorded as what
        it reliably is — cash that left a pot — with the other side against
        Opening balances. Per-person balances start clean on 1 October, which
        is the same date the old app rebased supplier debt on.
        """
        self.con and post.record(
            self.con, kind=kind, on=on, period=period, detail=detail,
            source="import", allow_closed=True,
            memo=f"before per-person balances start on {self.as_at()}",
            legs=[(post.account_id(self.con, "eq:opening"), amount),
                  (post.account_by_name_any(self.con, pot), -amount)])

    def as_at(self):
        """The date the old app rebased supplier debt on. Before it, the books
        are cash history; the brought-forward figures are the truth."""
        return (self.d.get("debt") or {}).get("asAt")

    def before_rebase(self, on):
        a = self.as_at()
        return bool(a) and on <= a

    def _ensure_person(self, name, kind, prefix):
        con = self.con
        try:
            post.account_by_name(con, kind, name)
            return name
        except db.LedgerError:
            pass
        post.ensure_account(con, f"{prefix}:{post.slug(name)}", name, kind, -1,
                            meta={"former": True, "share": 0}, active=0, sort=90)
        self.former.append({"kind": kind, "name": name})
        return name

    # ------------------------------------------------------------- accruals
    def accruals(self):
        """Charge rent, salaries and metered electricity to each month.

        The old app did this by summing Setup every time a screen rendered,
        which is why editing a salary silently moved a finished month. Here it
        is written once, as entries belonging to the month.
        """
        con = self.con
        from tools.oracle import Old
        fixed = db.all_(con, "SELECT * FROM fixed_charge WHERE active = 1")
        closed = self.d.get("closed") or {}
        n = 0
        for m in self.months():
            frozen = (closed.get(m) or {}).get("result")
            if frozen:
                # August's and September's rent and salary bills are not what
                # today's Setup would produce — the staff list has changed
                # since. The figures they were closed with are the record, so
                # they are posted as single charges rather than rebuilt from
                # the current lists. Posting today's salary bill to a month
                # that was closed with a smaller one would make the ledger
                # disagree with the month's own result.
                # Rent, like every running balance, starts on the rebase date.
                # Before it, both the charges and the payments are history on
                # Opening balances: August's rent was paid partly before these
                # books began (only a small part of it is in them), so charging
                # it to the rent account would invent arrears. A closed
                # month after the rebase date is charged to the rent account
                # like any other, so its payments have something to settle.
                rent = rnd(frozen.get("fixed"))
                rebased = bool(self.as_at()) and m <= self.as_at()[:7]
                if rent and len(fixed) == 1 and not rebased:
                    liability = post.ensure_account(
                        con, f"acc:{post.slug(fixed[0]['name'])}",
                        f"{fixed[0]['name']} not yet paid", "accrual", -1)
                    post.record(con, kind="fixed_charge", on=f"{m}-01", period=m,
                                detail=fixed[0]["name"], source="import",
                                allow_closed=True, memo="as this month was closed",
                                legs=[(post.account_id(con, "exp:rent"), rent),
                                      (liability, -rent)])
                    n += 1
                elif rent:
                    post.record(con, kind="fixed_charge", on=f"{m}-01", period=m,
                                detail="Rent", source="import", allow_closed=True,
                                memo="as this month was closed",
                                legs=[(post.account_id(con, "exp:rent"), rent),
                                      (post.account_id(con, "eq:opening"), -rent)])
                    n += 1
                # Salaries stay as one figure: who was on the payroll then, and
                # at what salary, is not in the old books, and the payments
                # made before per-person tracking began are on Opening
                # balances as well, so the two sides still meet.
                wages = rnd(frozen.get("salaries"))
                if wages:
                    post.record(con, kind="fixed_charge", on=f"{m}-01", period=m,
                                detail="Salaries", source="import", allow_closed=True,
                                memo="as this month was closed",
                                legs=[(post.account_id(con, "exp:salaries"), wages),
                                      (post.account_id(con, "eq:opening"), -wages)])
                    n += 1
            else:
                for f in fixed:
                    post.charge_fixed(con, f["amount"], name=f["name"], period=m)
                    n += 1
                for s in db.all_(con, "SELECT a.name, s.amount FROM salary s "
                                      "JOIN account a ON a.id = s.account_id "
                                      "JOIN account a2 ON a2.id = s.account_id "
                                      "WHERE s.from_month <= ? AND a2.active = 1",
                                 (m,)):
                    post.charge_salary(con, s["amount"], staff=s["name"], period=m)
                    n += 1
            used = rnd(Old(self.d, m).elec_charged(m))
            if used:
                post.electricity_used(con, used, period=m,
                                      note="from the meter reading")
                n += 1
        self.stats["accruals"] = n

        for r in sorted((self.d.get("elec") or {}).get("rows") or [],
                        key=lambda x: x.get("m", "")):
            if r.get("now") in (None, ""):
                continue
            con.execute("INSERT INTO meter_reading(read_on, units, rate, note) "
                        "VALUES (?,?,?,?) ON CONFLICT(read_on) DO NOTHING",
                        (f"{r['m']}-01", to_int(r.get("now")),
                         to_int((self.d.get('elec') or {}).get('factors', {}).get('publicRate')),
                         json.dumps({k: v for k, v in r.items() if k != "m"})))

    # ---------------------------------------------------------- cash counts
    def cash_counts(self):
        con = self.con
        n = 0
        for r in sorted(self.d.get("rc") or [], key=lambda x: ymd(x["d"])):
            on = ymd(r["d"])
            cur = con.execute("INSERT INTO cash_count(counted_on, reason) VALUES (?,?) "
                              "ON CONFLICT(counted_on) DO UPDATE SET reason = excluded.reason",
                              (on, r.get("note")))
            cid = cur.lastrowid or con.execute(
                "SELECT id FROM cash_count WHERE counted_on = ?", (on,)).fetchone()["id"]
            per_pot = r.get("counts") or {}
            if per_pot:
                for pot, value in per_pot.items():
                    try:
                        aid = post.account_by_name_any(con, pot)
                    except db.LedgerError:
                        continue
                    con.execute("INSERT INTO cash_count_line(count_id, account_id, counted) "
                                "VALUES (?,?,?) ON CONFLICT(count_id, account_id) "
                                "DO UPDATE SET counted = excluded.counted",
                                (cid, aid, to_int(value)))
            elif r.get("counted") is not None:
                # An old single-total count, before per-pot counting existed.
                aid = post.account_by_name_any(con, "Box")
                con.execute("INSERT INTO cash_count_line(count_id, account_id, counted) "
                            "VALUES (?,?,?) ON CONFLICT(count_id, account_id) "
                            "DO UPDATE SET counted = excluded.counted",
                            (cid, aid, to_int(r["counted"])))
            n += 1
        self.stats["cash_counts"] = n

    # -------------------------------------------------------- closed months
    def closed(self):
        """Mark the finished months closed, keeping their result exactly as the
        old app froze it — halves of a dinar and all. A closed month's figures
        are a record of what was decided, not something to recompute."""
        con = self.con
        from ledger import queries
        n = 0
        for m, info in sorted((self.d.get("closed") or {}).items()):
            post.ensure_period(con, m)
            # The stock side of closing: cost of goods leaves the stock
            # account, and whatever is then left over against the count is a
            # stock difference rather than something swept quietly into cost.
            res = info.get("result") or {}
            value = rnd((res.get("cogs") or {}).get("value") or 0)
            if value:
                post.record(con, kind="cogs", on=info.get("countDate") or f"{m}-28",
                            period=m, detail="Cost of goods sold", source="close",
                            allow_closed=True,
                            legs=[(post.account_id(con, "exp:cogs"), value),
                                  (post.account_id(con, "inv:stock"), -value)])
            count_date = info.get("countDate")
            if count_date:
                counted = queries.booked(con, count_date)
                have = queries.balance(con, "inv:stock", as_of=count_date)
                drift = have - counted
                if drift:
                    post.record(con, kind="stock_difference", on=count_date, period=m,
                                detail="Stock difference", source="close",
                                allow_closed=True,
                                memo="brings the stock account onto the count",
                                legs=[(post.account_id(con, "exp:variance"), drift),
                                      (post.account_id(con, "inv:stock"), -drift)])
            con.execute("UPDATE period SET status='closed', closed_at=?, count_date=?, "
                        "result=? WHERE month=?",
                        (info.get("closedAt"), count_date,
                         json.dumps(res, ensure_ascii=False), m))
            n += 1
        self.stats["closed_months"] = n

    # ------------------------------------------------------------------- run
    def run(self):
        con = self.con
        with db.tx(con):
            self.accounts()
            self.reference_data()
            self.periods()
            self.openings()
            self.stock_counts()
            self.receipts()
            self.cashbook()
            self.accruals()
            self.cash_counts()
            self.closed()
            self.stats["former_people"] = len(self.former)
            db.audit(con, "import", "twilight-books.json",
                     {"stats": self.stats, "fixed_backdated": self.fix,
                      "former": self.former, "skipped": self.skipped})
        return self.stats


def _unit(letter):
    return {"A": "kg", "B": "kg", "E": "carton"}.get(letter, "piece")


def _is_electric(detail):
    return "electric" in str(detail or "").lower()


def main(argv=None):
    ap = argparse.ArgumentParser(description="Import a twilight-books.json export")
    ap.add_argument("json", help="the exported twilight-books.json")
    ap.add_argument("--db", default=db.DEFAULT_DB)
    ap.add_argument("--as-is", action="store_true",
                    help="keep the five back-dated rows exactly as they were")
    ap.add_argument("--quiet", action="store_true")
    a = ap.parse_args(argv)

    data = json.loads(Path(a.json).read_text(encoding="utf-8"))
    fresh = not Path(a.db).exists()
    if not fresh:
        raise SystemExit(
            f"{a.db} already exists. Importing into books that already hold "
            "entries would double them. Move it aside first.")
    con = db.connect(a.db)
    imp = Importer(data, con, fix=not a.as_is)
    stats = imp.run()
    if not a.quiet:
        print(f"imported into {a.db}")
        for k, v in stats.items():
            print(f"  {k:20} {v}")
        if imp.skipped:
            print(f"  {'could not import':20} {len(imp.skipped)}")
            for s in imp.skipped[:10]:
                print(f"      {s['type']} / {s['detail']}: {s['why']}")
    return stats


if __name__ == "__main__":
    main()
