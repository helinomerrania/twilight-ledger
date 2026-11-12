"""The single door money goes through.

Nothing anywhere else in this project inserts into `posting`. Every kind of
transaction Mohammed can record — a night's sales, tea from the box, a salary,
a supplier payment, rent — is described once here as a pair of accounts, and
`record()` is what writes it. That is why the settlement-month bug cannot come
back: there is one function that decides which period an entry belongs to, and
one that decides which accounts move.

Reading the recipes below is the fastest way to understand the books.
"""
import json

from . import db
from .dates import month_of, today
from .money import to_int

# ----------------------------------------------------------------- accounts

# Accounts that always exist, whatever Mohammed has set up.
SYSTEM_ACCOUNTS = [
    # code,              name,                     kind,        normal
    ("rev:sales",        "Sales",                  "revenue",   -1),
    ("rev:other",        "Other income",           "revenue",   -1),
    ("exp:daily",        "Daily expenses",         "expense",    1),
    ("exp:rent",         "Rent",                   "expense",    1),
    ("exp:salaries",     "Salaries",               "expense",    1),
    ("exp:electricity",  "Electricity",            "expense",    1),
    ("exp:cogs",         "Cost of goods sold",     "expense",    1),
    ("exp:variance",     "Stock difference",       "expense",    1),
    ("inv:stock",        "Stock on hand",          "inventory",  1),
    ("acc:electricity",  "Electricity not yet paid", "accrual",  -1),
    ("eq:opening",       "Opening balances",       "partner",   -1),
    ("eq:profit",        "Profit allocated",       "partner",   -1),
    ("eq:difference",    "Cash differences",       "expense",    1),
]


def ensure_account(con, code, name, kind, normal, meta=None, sort=0, active=1):
    row = con.execute("SELECT * FROM account WHERE code = ?", (code,)).fetchone()
    if row:
        if row["name"] != name or (meta is not None and row["meta"] != json.dumps(meta, ensure_ascii=False)):
            con.execute("UPDATE account SET name = ?, meta = COALESCE(?, meta) WHERE id = ?",
                        (name, json.dumps(meta, ensure_ascii=False) if meta is not None else None,
                         row["id"]))
        return row["id"]
    cur = con.execute(
        "INSERT INTO account(code, name, kind, normal, sort, meta, active) "
        "VALUES (?,?,?,?,?,?,?)",
        (code, name, kind, normal, sort,
         json.dumps(meta or {}, ensure_ascii=False), active))
    return cur.lastrowid


def ensure_system_accounts(con):
    for code, name, kind, normal in SYSTEM_ACCOUNTS:
        ensure_account(con, code, name, kind, normal)


def slug(text):
    out = []
    for ch in str(text).strip().lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-") or "x"


def account_id(con, code):
    r = con.execute("SELECT id FROM account WHERE code = ?", (code,)).fetchone()
    if not r:
        raise db.LedgerError(f"no such account: {code}")
    return r["id"]


def account_by_name(con, kind, name):
    """Find a pot, supplier, member of staff or partner by the name on screen."""
    r = con.execute("SELECT id FROM account WHERE kind = ? AND name = ?",
                    (kind, name)).fetchone()
    if r:
        return r["id"]
    r = con.execute("SELECT id FROM account WHERE kind = ? AND code = ?",
                    (kind, f"{_prefix(kind)}:{slug(name)}")).fetchone()
    if r:
        return r["id"]
    raise db.LedgerError(f"no {kind} called {name!r}")


def main_pot(con):
    """The pot money goes into and comes out of when nobody says otherwise:
    the first active one in Setup order. Never a name written into the code —
    the old default was the word "Box", which broke the moment the pot was
    renamed."""
    r = con.execute("SELECT id, name FROM account WHERE kind = 'cash' AND active = 1 "
                    "ORDER BY sort, name LIMIT 1").fetchone()
    if not r:
        raise db.LedgerError("there is no cash pot. Add one in Setup.")
    return r


def pot_id(con, name=None):
    """A pot by name — one of Mohammed's own or a float — or the main pot."""
    if not name:
        return main_pot(con)["id"]
    return account_by_name_any(con, name)


def _prefix(kind):
    return {"cash": "cash", "float": "float", "supplier": "sup",
            "staff": "staff", "partner": "prt"}.get(kind, kind)


# ------------------------------------------------------------------- periods

def ensure_period(con, month):
    con.execute("INSERT INTO period(month) VALUES (?) ON CONFLICT(month) DO NOTHING",
                (month,))
    return month


def period_status(con, month):
    r = con.execute("SELECT status FROM period WHERE month = ?", (month,)).fetchone()
    return r["status"] if r else "open"


def assert_open(con, month):
    if period_status(con, month) == "closed":
        raise db.LedgerError(
            f"{month} is closed. Reopen it on the Month screen before changing it.")


# -------------------------------------------------------------------- writing

def record(con, *, kind, legs, on=None, period=None, detail=None, memo=None,
           source="manual", source_ref=None, allow_closed=False):
    """Write one transaction.

    legs is a list of (account_id, amount) where a positive amount is a debit.
    They must sum to zero; `record` checks it before anything is inserted, so a
    half-written transaction is impossible.

    `on` is the day the money moved. `period` is the month the transaction
    belongs to, which defaults to the month of `on` but is set explicitly when
    a November payment settles October. Keeping the two apart is the whole fix
    for "I paid October but it counted in November".
    """
    on = on or today()
    period = period or month_of(on)
    legs = [(int(a), to_int(v)) for a, v in legs if to_int(v) != 0]
    if not legs:
        raise db.LedgerError("nothing to record: every leg was zero")
    off = sum(v for _, v in legs)
    if off != 0:
        raise db.LedgerError(
            f"{kind} does not balance: the legs are out by {off} dinar")
    ensure_period(con, period)
    if not allow_closed:
        assert_open(con, period)
    cur = con.execute(
        "INSERT INTO entry(happened_on, period, kind, detail, memo, source, source_ref) "
        "VALUES (?,?,?,?,?,?,?)",
        (on, period, kind, detail, memo, source, source_ref))
    eid = cur.lastrowid
    con.executemany("INSERT INTO posting(entry_id, account_id, amount) VALUES (?,?,?)",
                    [(eid, a, v) for a, v in legs])
    return eid


def void(con, entry_id, why=None):
    """Mark an entry as never having happened, keeping it visible and traceable.

    Deleting a row is how a ledger loses the ability to explain itself. A void
    leaves the entry and its postings in place; every balance query reads the
    `movement` view, which skips voided entries. If the entry is a supplier
    receipt, the receipt row the stock figures read is voided with it.
    """
    r = con.execute("SELECT * FROM entry WHERE id = ?", (entry_id,)).fetchone()
    if not r:
        raise db.LedgerError(f"no entry {entry_id}")
    if r["voided_at"]:
        return entry_id
    assert_open(con, r["period"])
    con.execute("UPDATE entry SET voided_at = datetime('now') WHERE id = ?", (entry_id,))
    con.execute("UPDATE receipt SET voided_at = datetime('now') WHERE entry_id = ? "
                "AND voided_at IS NULL", (entry_id,))
    db.audit(con, "entry.void", f"entry:{entry_id}",
             {"kind": r["kind"], "detail": r["detail"], "why": why})
    return entry_id


def takings(con, on, *, but=None):
    """The takings standing in the books for a night, other than `but`."""
    return con.execute(
        "SELECT e.id, e.source, (SELECT SUM(p.amount) FROM posting p "
        "WHERE p.entry_id = e.id AND p.amount > 0) AS amount FROM entry e "
        "WHERE e.kind = 'daily_sales' AND e.happened_on = ? "
        "AND e.voided_at IS NULL AND e.id IS NOT ?", (on, but)).fetchall()


def unvoid(con, entry_id):
    """Put a deleted entry back. Refused for one that was replaced by a
    correction, because the correction is already standing in its place."""
    r = con.execute("SELECT * FROM entry WHERE id = ?", (entry_id,)).fetchone()
    if not r:
        raise db.LedgerError(f"no entry {entry_id}")
    if not r["voided_at"]:
        return entry_id
    if r["replaced_by"]:
        raise db.LedgerError("that entry was corrected, not deleted. "
                             "The corrected one is in the books.")
    assert_open(con, r["period"])
    if r["kind"] == "daily_sales":
        # A night has one set of takings: a figure typed in, or SambaPOS's
        # lines, one for each way of paying. Putting one back beside another
        # would count the night's sales twice.
        there = [t for t in takings(con, r["happened_on"], but=entry_id)
                 if r["source"] != "pos" or t["source"] != "pos"]
        if there:
            raise db.LedgerError(
                f"{r['happened_on']} already has its takings in the books "
                f"({sum(t['amount'] for t in there):,}). Delete those first "
                "if this is the right figure.")
    con.execute("UPDATE entry SET voided_at = NULL WHERE id = ?", (entry_id,))
    con.execute("UPDATE receipt SET voided_at = NULL WHERE entry_id = ?", (entry_id,))
    db.audit(con, "entry.unvoid", f"entry:{entry_id}",
             {"kind": r["kind"], "detail": r["detail"]})
    return entry_id


# ------------------------------------------------------------------- recipes
#
# Each of these is one thing Mohammed does, written as the two accounts it
# moves between. The surface of the app speaks his language; this is the only
# place that knows it is double entry.

def sales(con, amount, *, on=None, into=None, period=None, source="manual",
          source_ref=None, detail="Total sales of the day"):
    """A night's takings: cash goes up, revenue goes up."""
    cash = pot_id(con, into)
    rev = account_id(con, "rev:sales")
    return record(con, kind="daily_sales", on=on, period=period, detail=detail,
                  source=source, source_ref=source_ref,
                  legs=[(cash, to_int(amount)), (rev, -to_int(amount))])


def other_income(con, amount, *, detail, on=None, into=None, period=None, **src):
    cash = pot_id(con, into)
    return record(con, kind="other_income", on=on, period=period, detail=detail, **src,
                  legs=[(cash, to_int(amount)),
                        (account_id(con, "rev:other"), -to_int(amount))])


def daily_expense(con, amount, *, detail, on=None, out_of=None, period=None, **src):
    """Tea, ice, gas: an expense of the month, paid out of a pot."""
    cash = pot_id(con, out_of)
    return record(con, kind="daily_expense", on=on, period=period, detail=detail, **src,
                  legs=[(account_id(con, "exp:daily"), to_int(amount)),
                        (cash, -to_int(amount))])


def charge_fixed(con, amount, *, name, period, account="exp:rent", on=None):
    """Charge rent (or another fixed cost) to a month whether or not it is paid.

    This is the accrual. Paying it later is a separate transaction that settles
    the liability, which is why rent shows in October's result even when the
    cash leaves in November.
    """
    on = on or f"{period}-01"
    liability = ensure_account(con, f"acc:{slug(name)}", f"{name} not yet paid",
                               "accrual", -1)
    return record(con, kind="fixed_charge", on=on, period=period, detail=name,
                  legs=[(account_id(con, account), to_int(amount)),
                        (liability, -to_int(amount))])


def pay_fixed(con, amount, *, name, on=None, out_of=None, period=None):
    """Pay a fixed cost. Settles the liability; never touches profit again."""
    liability = ensure_account(con, f"acc:{slug(name)}", f"{name} not yet paid",
                               "accrual", -1)
    cash = pot_id(con, out_of)
    return record(con, kind="fixed_payment", on=on, period=period, detail=name,
                  legs=[(liability, to_int(amount)), (cash, -to_int(amount))])


def charge_salary(con, amount, *, staff, period, on=None):
    """A month's salary, charged in full to that month."""
    on = on or f"{period}-01"
    who = account_by_name(con, "staff", staff)
    return record(con, kind="salary_charge", on=on, period=period, detail=staff,
                  legs=[(account_id(con, "exp:salaries"), to_int(amount)),
                        (who, -to_int(amount))])


def staff_advance(con, amount, *, staff, on=None, out_of=None, period=None, **src):
    """Cash handed to staff against a salary not yet due."""
    who = account_by_name(con, "staff", staff)
    cash = pot_id(con, out_of)
    return record(con, kind="staff_advance", on=on, period=period, detail=staff, **src,
                  legs=[(who, to_int(amount)), (cash, -to_int(amount))])


def staff_repay(con, amount, *, staff, on=None, into=None, period=None, **src):
    """Staff hand money back. The mirror of an advance: cash comes in, and
    what they have drawn against their salary goes down by the same amount.
    Its own kind, so the record reads as what happened rather than as an
    advance with the sign flipped."""
    who = account_by_name(con, "staff", staff)
    cash = pot_id(con, into)
    return record(con, kind="staff_repayment", on=on, period=period, detail=staff, **src,
                  legs=[(cash, to_int(amount)), (who, -to_int(amount))])


def pay_salary(con, amount, *, staff, on=None, out_of=None, period=None):
    """Hand over what is left of a salary. Same accounts as an advance: both
    reduce what is owed to that person. The distinction is only in the name."""
    who = account_by_name(con, "staff", staff)
    cash = pot_id(con, out_of)
    return record(con, kind="salary_payment", on=on, period=period, detail=staff,
                  legs=[(who, to_int(amount)), (cash, -to_int(amount))])


def receipt_in(con, amount, *, supplier, on=None, terms="credit", what=None,
               number=None, period=None, out_of=None):
    """Goods arrive. Stock goes up; either a supplier is owed or cash leaves."""
    sup = account_by_name(con, "supplier", supplier)
    inv = account_id(con, "inv:stock")
    if terms == "cash":
        other = pot_id(con, out_of)
        kind = "receipt_cash"
    else:
        other = sup
        kind = "receipt_credit"
    return record(con, kind=kind, on=on, period=period, detail=supplier,
                  memo=what or number,
                  legs=[(inv, to_int(amount)), (other, -to_int(amount))])


def pay_supplier(con, amount, *, supplier, on=None, out_of=None, period=None, **src):
    """Pay a supplier. A debt settlement, so it never changes profit."""
    sup = account_by_name(con, "supplier", supplier)
    cash = pot_id(con, out_of)
    return record(con, kind="supplier_payment", on=on, period=period,
                  detail=supplier, **src,
                  legs=[(sup, to_int(amount)), (cash, -to_int(amount))])


def partner_draw(con, amount, *, partner, on=None, out_of=None, period=None, **src):
    """A partner takes cash out of the business."""
    who = account_by_name(con, "partner", partner)
    cash = pot_id(con, out_of)
    return record(con, kind="partner_draw", on=on, period=period, detail=partner, **src,
                  legs=[(who, to_int(amount)), (cash, -to_int(amount))])


def partner_in(con, amount, *, partner, on=None, into=None, period=None, **src):
    """A partner puts cash in."""
    who = account_by_name(con, "partner", partner)
    cash = pot_id(con, into)
    return record(con, kind="partner_in", on=on, period=period, detail=partner, **src,
                  legs=[(cash, to_int(amount)), (who, -to_int(amount))])


def transfer(con, amount, *, frm, to, on=None, period=None, **src):
    """Box to bank, or a float handed to someone. Never touches profit."""
    a = account_by_name_any(con, frm)
    b = account_by_name_any(con, to)
    if a == b:
        raise db.LedgerError("a transfer needs two different pots")
    return record(con, kind="transfer", on=on, period=period,
                  detail=frm, memo=f"{frm} to {to}", **src,
                  legs=[(b, to_int(amount)), (a, -to_int(amount))])


def account_by_name_any(con, name):
    """A pot, whether it is one of Mohammed's own or a float someone holds."""
    r = con.execute("SELECT id FROM account WHERE kind IN ('cash','float') AND name = ?",
                    (name,)).fetchone()
    if not r:
        raise db.LedgerError(f"no pot called {name!r}")
    return r["id"]


def electricity_used(con, amount, *, period, on=None, note=None):
    """What the meter says was used this month, charged to the month."""
    on = on or f"{period}-01"
    return record(con, kind="electricity_charge", on=on, period=period,
                  detail="Electricity", memo=note,
                  legs=[(account_id(con, "exp:electricity"), to_int(amount)),
                        (account_id(con, "acc:electricity"), -to_int(amount))])


def pay_electricity(con, amount, *, on=None, out_of=None, period=None):
    cash = pot_id(con, out_of)
    return record(con, kind="electricity_payment", on=on, period=period,
                  detail="Electricity",
                  legs=[(account_id(con, "acc:electricity"), to_int(amount)),
                        (cash, -to_int(amount))])


def cash_difference(con, diff, *, pot, on, reason=None, source_ref=None):
    """Accept that a pot holds a different amount from what the books say.

    `diff` is counted less expected: negative when cash is missing. The pot is
    moved onto the counted figure and the other side is a cost of the month
    (or a gain, if there was more than expected), so a shortage shows on the
    month's result instead of leaving the books permanently wrong.
    """
    diff = to_int(diff)
    return record(con, kind="cash_difference", on=on, detail=pot, memo=reason,
                  source_ref=source_ref,
                  legs=[(pot_id(con, pot), diff),
                        (account_id(con, "eq:difference"), -diff)])


def opening_balance(con, amount, *, account_code, on, period=None, memo=None):
    """Seed a balance that predates the books, against Opening balances."""
    return record(con, kind="opening", on=on, period=period, memo=memo,
                  detail=account_code, source="import", allow_closed=True,
                  legs=[(account_id(con, account_code), to_int(amount)),
                        (account_id(con, "eq:opening"), -to_int(amount))])
