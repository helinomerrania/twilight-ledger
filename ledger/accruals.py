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
    if f["to_month"]:
        # stopped: nothing after its last month, and that month and those
        # before it as they stand
        return None if month <= f["to_month"] else 0
    if f["from_month"] and month < f["from_month"]:
        return None
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


def _staff(con):
    """Everyone on the staff list, without summing their accounts: asked for
    every open month each time a screen is drawn, it only needs who they are."""
    return db.all_(con, "SELECT id, name, meta, active FROM account WHERE kind = 'staff' "
                        "ORDER BY active DESC, sort, name")


def salary_target(con, a, month):
    """What someone's salary for `month` is charged at: the whole of it, or
    in the month they started or left in a thirtieth of it for each day they
    worked (`queries.salary_days`), to the note."""
    full = queries.salary_for(con, a["id"], month)
    days = queries.salary_days(a, month)
    if days >= queries.MONTH_DAYS:
        return full
    return mround_fraction(Fraction(full) * days / queries.MONTH_DAYS) if days else 0


def closed_off(con, account_id, since):
    """Closed months from `since` to now whose salary charge for someone is no
    longer what it should be, as when the day they started or left is given
    after the month closed. A closed month is never changed, so this is said
    instead."""
    a = db.one(con, "SELECT id, name, meta, active FROM account WHERE id = ?", (account_id,))
    out, m, now = [], since, month_of(today())
    while a and m <= now:
        if queries.is_closed(con, m) \
                and salary_target(con, a, m) != _salary_charged(con, account_id, m):
            out.append(m)
        m = next_month(m)
    return out


def reconcile_salaries(con, month):
    """Each member of staff is charged their salary for the month; someone who
    has left, up to the day they left (`salary_target`)."""
    n = 0
    for a in _staff(con):
        meta = json.loads(a["meta"] or "{}")
        if meta.get("former"):
            continue
        target = salary_target(con, a, month)
        have = _salary_charged(con, a["id"], month)
        if target != have:
            post.charge_salary(con, target - have, staff=a["name"], period=month)
            n += 1
    return n


def ensure_needed(con, month):
    """Would `ensure` post anything? Asked first so that simply looking at a
    month does not open a write transaction unless there is something to do."""
    if month > month_of(today()) or not _is_open(con, month) or clock_jump(con):
        return False
    for f in db.all_(con, "SELECT * FROM fixed_charge"):
        target = _fixed_target(f, month)
        if target is not None and target != _charged(
                con, "exp:rent", month, "fixed_charge", f["name"]):
            return True
    for a in _staff(con):
        meta = json.loads(a["meta"] or "{}")
        if meta.get("former"):
            continue
        if salary_target(con, a, month) != _salary_charged(con, a["id"], month):
            return True
    return False


# How many months the computer's date may be ahead of the newest month in
# the books before it is doubted. Every month up to "today" is charged its
# rent and salaries, so a clock set to the wrong year would charge years of
# them at a glance, and nothing would take them back.
CLOCK_GAP = 3


def clock_jump(con):
    """The computer's date, if it is far ahead of the books and nobody has
    said it is right: {"last", "now"}. None when all is well."""
    now = month_of(today())
    last = db.scalar(con, "SELECT MAX(month) FROM period")
    if not last:
        return None
    limit = last
    for _ in range(CLOCK_GAP):
        limit = next_month(limit)
    if now <= limit or db.setting(con, "clock_ok") == now:
        return None
    return {"last": last, "now": now}


def ensure(con, month):
    """Make sure an open month carries its rent and salaries. Never a future
    month: December is not charged until December arrives."""
    if month > month_of(today()) or clock_jump(con):
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
    if clock_jump(con):
        return 0                # nothing is charged on a date nobody trusts
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


def _read(r):
    """Did this month's saving include a reading of the meter?"""
    if not r["note"]:
        return bool(r["units"])                  # brought in from the old app
    return json.loads(r["note"]).get("now") not in (None, "")


def electricity_view(con, month):
    row = db.one(con, "SELECT * FROM meter_reading WHERE read_on = ?", (f"{month}-01",))
    # the meter as it last read: a month saved without a reading (only the
    # generator's price, say) has nothing to carry over, so it is passed by
    prev = next((r for r in db.all_(con, "SELECT * FROM meter_reading WHERE read_on < ? "
                                         "ORDER BY read_on DESC", (f"{month}-01",))
                 if _read(r)), None)
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
