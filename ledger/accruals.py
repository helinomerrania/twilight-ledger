"""Charging a month with what it owes whether or not it has been paid.

Rent, salaries and metered electricity belong to the month they are for. The
importer wrote those charges for the months it brought across; this module is
what keeps doing it as new months arrive, and what puts a charge right when a
salary or the rent is changed in Setup while the month is still open.

Every function here works by reconciling: it looks at what has already been
charged to the month, compares it with what should be, and posts only the
difference. Running it twice changes nothing, and a closed month is never
touched.
"""
import json

from fractions import Fraction

from . import db, post, queries
from .dates import month_of, next_month, today
from .money import mround_fraction, to_int


def _charged(con, account_code, period, kind, detail):
    return db.scalar(con,
        "SELECT COALESCE(SUM(m.amount), 0) FROM movement m "
        "WHERE m.code = ? AND m.period = ? AND m.entry_kind = ? AND m.detail = ?",
        (account_code, period, kind, detail))


def _salary_charged(con, account_id, period):
    """Read off the person's own account, not matched by name, so renaming
    someone in Setup cannot make the month charge them a second time."""
    return db.scalar(con,
        "SELECT COALESCE(SUM(-m.amount), 0) FROM movement m "
        "WHERE m.account_id = ? AND m.period = ? AND m.entry_kind = 'salary_charge'",
        (account_id, period))


def _is_open(con, month):
    return post.period_status(con, month) == "open"


def _fixed_target(f, month):
    """What a monthly charge should come to in a month, or None to leave that
    month exactly as it stands.

    A change to the rent applies from the month it was made in. Months before
    that keep what they were charged at the time, even if they are still open
    — putting the rent up in November must not reach back into October.
    """
    if f["from_month"] and month < f["from_month"]:
        return None
    if f["to_month"]:
        return None if month <= f["to_month"] else 0
    return f["amount"] if f["active"] else 0


def reconcile_fixed(con, month):
    n = 0
    for f in db.all_(con, "SELECT * FROM fixed_charge"):
        target = _fixed_target(f, month)
        if target is None:
            continue
        have = _charged(con, "exp:rent", month, "fixed_charge", f["name"])
        if target != have:
            post.charge_fixed(con, target - have, name=f["name"], period=month)
            n += 1
    return n


def reconcile_salaries(con, month):
    """Each member of staff is charged their salary for the month. Someone who
    has left is still charged for the months up to and including the one they
    left in, because they worked it."""
    n = 0
    for a in queries.balances(con, "staff"):
        meta = json.loads(a["meta"] or "{}")
        if meta.get("former"):
            continue
        left = meta.get("left_after")
        works = bool(a["active"]) or (left and month <= left)
        target = queries.salary_for(con, a["id"], month) if works else 0
        have = _salary_charged(con, a["id"], month)
        if target != have:
            post.charge_salary(con, target - have, staff=a["name"], period=month)
            n += 1
    return n


def ensure_needed(con, month):
    """Would `ensure` post anything? Asked first so that simply looking at a
    month does not open a write transaction unless there is something to do."""
    if month > month_of(today()) or not _is_open(con, month):
        return False
    for f in db.all_(con, "SELECT * FROM fixed_charge"):
        target = _fixed_target(f, month)
        if target is not None and target != _charged(
                con, "exp:rent", month, "fixed_charge", f["name"]):
            return True
    for a in queries.balances(con, "staff"):
        meta = json.loads(a["meta"] or "{}")
        if meta.get("former"):
            continue
        left = meta.get("left_after")
        works = bool(a["active"]) or (left and month <= left)
        target = queries.salary_for(con, a["id"], month) if works else 0
        if target != _salary_charged(con, a["id"], month):
            return True
    return False


def ensure(con, month):
    """Make sure an open month carries its rent and salaries. Never a future
    month: December is not charged until December arrives."""
    if month > month_of(today()):
        return 0
    post.ensure_period(con, month)
    if not _is_open(con, month):
        return 0
    return reconcile_fixed(con, month) + reconcile_salaries(con, month)


def ensure_all(con):
    """Bring every month up to today into being, charged.

    Covers the gap as well as the present: if the app is not opened for all
    of January, January still needs its rent and salaries when it is opened
    in February.
    """
    now = month_of(today())
    existing = queries.months(con)
    m = existing[0] if existing else now
    todo = []
    while m <= now:
        if not queries.period(con, m) or ensure_needed(con, m):
            todo.append(m)
        m = next_month(m)
    if not todo:
        return 0
    with db.tx(con):
        return sum(ensure(con, m) for m in todo)


# ----------------------------------------------------------------- electricity

DEFAULT_FACTORS = {"privateAmps": 25, "elevatorAmps": 20, "elevatorShare": 6,
                   "publicRate": 185, "publicShare": 3}


def factors(con):
    f = dict(DEFAULT_FACTORS)
    for k, v in (db.setting(con, "elec_factors", {}) or {}).items():
        if v not in (None, ""):
            f[k] = to_int(v)
    return f


def electricity_bill(con, *, private_price=0, elevator_price=0,
                     last_reading=None, now_reading=None):
    """The month's electricity, worked out the way the lounge is billed:

      private generator   price per amp x the amps the lounge takes
      elevator            price per amp x the elevator's amps, split between
                          the shops that share it
      public grid         units used on the meter x the rate, split likewise
    """
    f = factors(con)
    private = mround_fraction(Fraction(to_int(private_price) * f["privateAmps"]))
    elevator = mround_fraction(Fraction(to_int(elevator_price) * f["elevatorAmps"],
                                        max(f["elevatorShare"], 1)))
    units = None
    if last_reading not in (None, "") and now_reading not in (None, ""):
        units = to_int(now_reading) - to_int(last_reading)
        if units < 0:
            raise db.LedgerError("the meter cannot have gone backwards: the reading "
                                 "now is lower than the last one")
    public = mround_fraction(Fraction(units * f["publicRate"], max(f["publicShare"], 1))) \
        if units else 0
    return {"private": private, "elevator": elevator, "public": public,
            "units": units, "total": private + elevator + public}


def set_electricity(con, month, *, private_price=0, elevator_price=0,
                    last_reading=None, now_reading=None):
    if not _is_open(con, month):
        raise db.LedgerError(f"{month} is closed")
    bill = electricity_bill(con, private_price=private_price,
                            elevator_price=elevator_price,
                            last_reading=last_reading, now_reading=now_reading)
    have = _charged(con, "exp:electricity", month, "electricity_charge", "Electricity")
    if bill["total"] != have:
        post.electricity_used(con, bill["total"] - have, period=month,
                              note="from the meter reading")
    note = json.dumps({"pp": to_int(private_price), "pe": to_int(elevator_price),
                       "last": last_reading, "now": now_reading})
    con.execute("INSERT INTO meter_reading(read_on, units, rate, note) VALUES (?,?,?,?) "
                "ON CONFLICT(read_on) DO UPDATE SET units=excluded.units, "
                "rate=excluded.rate, note=excluded.note",
                (f"{month}-01", to_int(now_reading), factors(con)["publicRate"], note))
    return bill


def electricity_view(con, month):
    row = db.one(con, "SELECT * FROM meter_reading WHERE read_on = ?", (f"{month}-01",))
    prev = db.one(con, "SELECT * FROM meter_reading WHERE read_on < ? "
                       "ORDER BY read_on DESC LIMIT 1", (f"{month}-01",))
    saved = json.loads(row["note"]) if row and row["note"] else {}
    last = saved.get("last")
    if last in (None, "") and prev:
        last = prev["units"]
    return {"private_price": saved.get("pp") or "", "elevator_price": saved.get("pe") or "",
            "last_reading": last if last is not None else "",
            "now_reading": saved.get("now") if saved.get("now") is not None else "",
            "charged": _charged(con, "exp:electricity", month,
                                "electricity_charge", "Electricity"),
            "unpaid": queries.balance(con, "acc:electricity"),
            "factors": factors(con)}
