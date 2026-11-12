"""Every figure the app shows, each worked out in exactly one place.

This module is the answer to the bug that prompted the rebuild. In the old app
"cash on hand" was computed in five different cards and "what we owe Sarkawt"
in two, and when they disagreed there was no way to say which was right. Here a
balance is a SUM over `movement`, and there is one function per figure.

Reading rule: `movement` already excludes voided entries, so no query in this
file has to remember to.
"""
from bisect import bisect_right
import json
from fractions import Fraction

from . import db, kinds
from .dates import (days_in, month_of, month_range, prev_month, today)
from .money import mround, mround_fraction, pct, split_shares

# --------------------------------------------------------------- balances

def balance(con, code, as_of=None):
    """An account's balance in its own natural direction, so the number a
    screen shows is positive when there is more of whatever it means: more cash
    in the Box, more owed to a supplier."""
    sql = ("SELECT COALESCE(SUM(m.amount * m.normal), 0) b FROM movement m "
           "WHERE m.code = ?")
    args = [code]
    if as_of:
        sql += " AND m.happened_on <= ?"
        args.append(as_of)
    return db.scalar(con, sql, args)


def balances(con, kind, as_of=None, *, include_inactive=True):
    """Every account of one kind with its balance, in Setup order."""
    sql = ("SELECT a.id, a.code, a.name, a.active, a.meta, a.kind, "
           "       COALESCE(SUM(CASE WHEN ? IS NULL OR m.happened_on <= ? "
           "                    THEN m.amount * a.normal END), 0) AS balance, "
           "       MAX(m.happened_on) AS last_used "
           "  FROM account a LEFT JOIN movement m ON m.account_id = a.id "
           " WHERE a.kind = ?")
    args = [as_of, as_of, kind]
    if not include_inactive:
        sql += " AND a.active = 1"
    sql += " GROUP BY a.id ORDER BY a.active DESC, a.sort, a.name"
    return db.all_(con, sql, args)


def cash_on_hand(con, as_of=None):
    """Mohammed's own cash. Floats are somebody else's pocket, so not here."""
    return _kind_total(con, "cash", as_of)


def in_hands(con, as_of=None):
    """Money the business owns that someone else is holding."""
    return _kind_total(con, "float", as_of)


def _kind_total(con, kind, as_of=None):
    sql = ("SELECT COALESCE(SUM(m.amount * m.normal), 0) t FROM movement m "
           "WHERE m.kind = ?")
    args = [kind]
    if as_of:
        sql += " AND m.happened_on <= ?"
        args.append(as_of)
    return db.scalar(con, sql, args)


def pots(con, as_of=None):
    """Every pot, own cash first then floats, each marked with whether it is
    worth showing day to day.

    A pot is `in_use` when it is the main one, holds money, or has moved in
    the last thirty days. The Bank has seen one movement in four months and a
    one-off pot holds nothing; neither needs a box on the nightly count.
    """
    rows = list(balances(con, "cash", as_of)) + list(balances(con, "float", as_of))
    main = con.execute("SELECT id FROM account WHERE kind = 'cash' AND active = 1 "
                       "ORDER BY sort, name LIMIT 1").fetchone()
    main_id = main["id"] if main else None
    cutoff = _days_ago(as_of or today(), 30)
    out = []
    for r in rows:
        d = dict(r)
        d["main"] = r["id"] == main_id
        d["in_use"] = bool(r["active"]) and (
            d["main"] or r["balance"] != 0
            or (r["last_used"] is not None and r["last_used"] >= cutoff))
        out.append(d)
    return out


def _days_ago(day, n):
    from datetime import date, timedelta
    y, m, d = (int(x) for x in day.split("-"))
    return (date(y, m, d) - timedelta(days=n)).isoformat()


def _day_before(d):
    return _days_ago(d, 1)


# -------------------------------------------------------------------- stock

def count_dates(con, *, valued_only=True):
    """The days the stock was counted, oldest first. A count values the
    stock once something is on it: one just started, with nothing typed into
    it yet, is not a count of anything."""
    sql = "SELECT count_date FROM stock_count"
    if valued_only:
        sql += (" WHERE closing <> 0 OR EXISTS (SELECT 1 FROM stock_count_line l "
                "WHERE l.count_id = stock_count.id)")
    return [r["count_date"] for r in db.all_(con, sql + " ORDER BY count_date")]


def booked(con, count_date):
    """What a count was booked at — the stored figure, never recomputed."""
    if not count_date:
        return 0
    return db.scalar(con, "SELECT closing FROM stock_count WHERE count_date = ?",
                     (count_date,))


def count_for(con, month):
    """The count that values the stock at the end of this month."""
    _, end = month_range(month)
    ds = [d for d in count_dates(con) if d <= end]
    return ds[-1] if ds else None


def opening_count(con, month):
    start, _ = month_range(month)
    ds = [d for d in count_dates(con) if d < start]
    return ds[-1] if ds else None


_RECEIVED = ("SELECT COALESCE(SUM(amount), 0) FROM receipt "
             "WHERE voided_at IS NULL AND ")


def purchases_in(con, month):
    """What was bought in the window the counts actually measure.

    If the month holds its own count, the window runs from the previous count
    to that one — otherwise a count taken on the 2nd would be set against a
    whole month of deliveries and the cost of goods would be nonsense. With no
    count in the month, the month itself is the window.
    """
    start, end = month_range(month)
    cd, od = count_for(con, month), opening_count(con, month)
    if cd and cd >= start and od:
        return db.scalar(con, _RECEIVED + "received_on > ? AND received_on <= ?",
                         (od, cd))
    if cd and cd >= start:
        return db.scalar(con, _RECEIVED + "received_on >= ? AND received_on <= ?",
                         (start, cd))
    return db.scalar(con, _RECEIVED + "received_on >= ? AND received_on <= ?",
                     (start, end))


def cogs(con, month):
    """Opening stock, plus what was bought, less what is still on the shelves.

    A negative cost of goods is not a profit: it means either this is the first
    count, which is setting the opening position rather than measuring a month,
    or a delivery was never written down. Either way it is reported as zero and
    the raw figure is kept beside it so the Month screen can say so.
    """
    cd = count_for(con, month)
    od = opening_count(con, month)
    closing = booked(con, cd) if cd else 0
    opening = booked(con, od) if od else 0
    bought = purchases_in(con, month)
    raw = mround(opening + bought - closing)
    start, _ = month_range(month)
    return {"opening": opening, "purchases": bought, "closing": closing,
            "value": max(0, raw), "raw": raw, "date": cd, "opening_date": od,
            "counted_this_month": bool(cd and cd >= start)}


# ------------------------------------------------------------------- result

def period_total(con, code, month):
    """What hit one account in a month, by the month the entry belongs to.

    `period`, not the date. That is the whole point: a salary paid on 3
    November that settles October is October's business.
    """
    return db.scalar(con,
                     "SELECT COALESCE(SUM(m.amount * m.normal), 0) t FROM movement m "
                     "WHERE m.code = ? AND m.period = ?", (code, month))


def live_result(con, month):
    sales = period_total(con, "rev:sales", month)
    other = period_total(con, "rev:other", month)
    rev = sales + other
    c = cogs(con, month)
    gross = rev - c["value"]
    daily = period_total(con, "exp:daily", month)
    elec = period_total(con, "exp:electricity", month)
    fixed = period_total(con, "exp:rent", month)
    salaries = period_total(con, "exp:salaries", month)
    # Cash that was counted, found short and written off is a cost of the
    # month it went missing in. Positive is a loss.
    differences = period_total(con, "eq:difference", month)
    opex = daily + elec + fixed + salaries
    net = gross - opex - differences
    return {"month": month, "sales": sales, "other": other, "rev": rev,
            "cogs": c, "gross": gross, "grossPct": pct(gross, rev),
            "daily": daily, "elec": elec, "fixed": fixed, "salaries": salaries,
            "differences": differences, "opex": opex, "net": net,
            "netPct": pct(net, rev), "frozen": False}


def result(con, month):
    """A closed month returns what was frozen at the time, not a recalculation."""
    r = db.one(con, "SELECT status, result FROM period WHERE month = ?", (month,))
    if r and r["status"] == "closed" and r["result"]:
        out = json.loads(r["result"])
        out["month"] = month
        out["frozen"] = True
        return out
    return live_result(con, month)


def months(con):
    return [r["month"] for r in db.all_(con, "SELECT month FROM period ORDER BY month")]


def period(con, month):
    return db.one(con, "SELECT * FROM period WHERE month = ?", (month,))


def is_closed(con, month):
    r = period(con, month)
    return bool(r and r["status"] == "closed")


def so_far(con, month):
    """The month we are in, measured against the days that have actually passed.

    The full result charges the whole month's rent and salaries from the first
    day, so on the 8th it sets thirty days of costs against eight days of sales
    and shows a loss that is not real. This sets eight days of rent and
    salaries against the eight days of sales instead.

    It is an estimate and says so: stock is only really known on the day it is
    counted, so sales after the last count are costed at last month's ratio,
    and electricity that has not been read yet is taken from last month's bill.
    """
    if month != month_of(today()) or is_closed(con, month):
        return None
    last = db.scalar(con, "SELECT MAX(happened_on) FROM movement "
                          "WHERE code = 'rev:sales' AND period = ? AND happened_on LIKE ?",
                     (month, month + "%"), default=None)
    if not last:
        return None
    days, total = int(last[8:10]), len(days_in(month))
    if days >= total:
        return None
    r = live_result(con, month)

    prev = prev_month(month)
    pr = result(con, prev) if period(con, prev) else None
    ratio = None
    if pr and (pr.get("rev") or 0) > 0 and ((pr.get("cogs") or {}).get("value") or 0) > 0:
        ratio = Fraction(str(pr["cogs"]["value"])) / Fraction(str(pr["rev"]))

    c = r["cogs"]
    if c["counted_this_month"]:
        later = db.scalar(con, "SELECT COALESCE(SUM(-amount), 0) FROM movement "
                               "WHERE code = 'rev:sales' AND period = ? AND happened_on > ?",
                          (month, c["date"]))
        extra = mround_fraction(later * ratio) if (ratio is not None and later > 0) else 0
        cost, basis = c["value"] + extra, "counted"
        note = f"counted {c['date']}" + (", days since estimated" if extra else "")
    elif ratio is not None:
        cost, basis = mround_fraction(r["rev"] * ratio), "estimated"
        note = f"no count yet this month, so taken at last month's {float(ratio) * 100:.0f}%"
    else:
        cost, basis, note = c["value"], "unknown", "no count to go on"

    # Each estimated line is rounded to the note like every other figure, so
    # the result can be split between the partners without odd dinar.
    def part(amount):                   # days' worth, rounded once, to the note
        return mround_fraction(Fraction(int(amount or 0)) * days / total)

    if r["elec"]:
        elec, elec_estimated = part(r["elec"]), False
    else:
        elec = part((pr or {}).get("elec") or 0)
        elec_estimated = bool(elec)
    fixed = part(r["fixed"])
    salaries = part(r["salaries"])
    net = r["rev"] - cost - r["daily"] - elec - fixed - salaries - r["differences"]
    return {"days": days, "days_in_month": total, "through": last,
            "rev": r["rev"], "cogs": cost, "cogs_basis": basis, "cogs_note": note,
            "daily": r["daily"], "elec": elec, "elec_estimated": elec_estimated,
            "fixed": fixed, "salaries": salaries, "differences": r["differences"],
            "net": net, "netPct": pct(net, r["rev"])}


def summary(con):
    return [{"month": m, "net": (result(con, m) or {}).get("net"),
             "status": period(con, m)["status"]} for m in months(con)]


# ------------------------------------------------------- running obligations

def outstanding(con, account_id, month, charge_kinds, *, paid_through=None):
    """What is still owed on a running account for everything charged up to
    and including `month`.

    With `paid_through` left out, every payment ever made counts, oldest debt
    first, whatever month a payment was tagged to — so a month can never go on
    showing a debt that has in fact been paid. That answers "is October
    settled?". With `paid_through` set to a month, only payments belonging to
    that month or earlier count — the position as it stood at the end of it.
    """
    marks = ",".join("?" for _ in charge_kinds)
    charged = db.scalar(con,
        f"SELECT COALESCE(SUM(-m.amount), 0) FROM movement m WHERE m.account_id = ? "
        f"AND m.period <= ? AND m.entry_kind IN ({marks})",
        (account_id, month, *charge_kinds))
    sql = (f"SELECT COALESCE(SUM(m.amount), 0) FROM movement m WHERE m.account_id = ? "
           f"AND m.entry_kind NOT IN ({marks})")
    args = [account_id, *charge_kinds]
    if paid_through:
        sql += " AND m.period <= ?"
        args.append(paid_through)
    paid = db.scalar(con, sql, args)
    return charged - paid


# ------------------------------------------------------------------ payroll

def salary_for(con, account_id, month):
    return db.scalar(con, "SELECT amount FROM salary WHERE account_id = ? "
                          "AND from_month <= ? ORDER BY from_month DESC LIMIT 1",
                     (account_id, month))


# A month's salary is thirty days' pay, whatever the month's length.
MONTH_DAYS = 30


def day_of_30(on):
    """A day as the salary counts it: every month has thirty days, and a
    month's last day is its thirtieth, so a 31st or a 28 February is the 30th."""
    d = int(on[8:10])
    return MONTH_DAYS if d >= len(days_in(on[:7])) else min(d, MONTH_DAYS)


def salary_days(a, month):
    """How many of `month`'s thirty days someone is paid for: all of them,
    unless they started or left in it, and none before they started or after
    they left. `a` is their account row (id, meta, active).

    Someone marked as left before the day was asked has `left_after` and no
    `left_on`: the whole of that month counts, as it always did."""
    meta = json.loads(a["meta"] or "{}")
    start, left_on = meta.get("started_on"), None
    if start and month < start[:7]:
        return 0
    if not a["active"]:
        left = meta.get("left_after")
        if not left or month > left:
            return 0
        left_on = meta.get("left_on")
    first = day_of_30(start) if start and start[:7] == month else 1
    last = day_of_30(left_on) if left_on and left_on[:7] == month else MONTH_DAYS
    return max(0, min(MONTH_DAYS, last - first + 1))


def payroll(con, month):
    """What each member of staff was charged this month, what they have had,
    and what is still owed to them for everything up to the end of it.

    Advances and salary payments are the same movement on the same account, so
    "still to pay" cannot drift from "what was handed over" the way two
    separate running totals can.

      still_to_pay   unpaid today for this month and earlier, after every
                     payment made since (oldest debt first)
      overpaid       handed over beyond what had been earned, as it stood at
                     the end of this month
      from_earlier   the part of still_to_pay that belongs to earlier months
    """
    out = []
    charge = ("salary_charge",)
    for a in balances(con, "staff"):
        gross = _on_account(con, a["id"], month, charge, sign=-1)
        # money handed back comes off the advances it is returning
        adv = _on_account(con, a["id"], month, ("staff_advance", "staff_repayment"))
        paid = _on_account(con, a["id"], month, ("salary_payment",))
        owed = outstanding(con, a["id"], month, charge)
        at_end = outstanding(con, a["id"], month, charge, paid_through=month)
        earlier = outstanding(con, a["id"], prev_month(month), charge)
        if not (gross or adv or paid or owed or at_end):
            continue
        # the days they started and left, and the days of this month paid for
        meta = json.loads(a["meta"] or "{}")
        started = meta.get("started_on")
        days = salary_days(a, month)
        out.append({"id": a["id"], "name": a["name"], "active": a["active"],
                    "gross": gross, "advances": adv, "paid": paid,
                    "from_earlier": max(min(earlier, owed), 0),
                    "still_to_pay": max(owed, 0), "overpaid": max(-at_end, 0),
                    "started_on": started if started and started[:7] == month else None,
                    "left_on": None if a["active"] else meta.get("left_on"),
                    "part": {"days": days, "of": MONTH_DAYS} if 0 < days < MONTH_DAYS else None})
    return out


def _on_account(con, account_id, month, entry_kinds, sign=1):
    marks = ",".join("?" for _ in entry_kinds)
    return sign * db.scalar(con,
        f"SELECT COALESCE(SUM(m.amount), 0) FROM movement m WHERE m.account_id = ? "
        f"AND m.period = ? AND m.entry_kind IN ({marks})",
        (account_id, month, *entry_kinds))


def fixed_outstanding(con, month):
    """Rent and the other monthly charges: what is still unpaid up to `month`."""
    from .post import slug
    out = []
    for f in db.all_(con, "SELECT * FROM fixed_charge ORDER BY name"):
        acc = db.one(con, "SELECT id FROM account WHERE code = ?",
                     (f"acc:{slug(f['name'])}",))
        if not acc:
            continue
        owed = outstanding(con, acc["id"], month, ("fixed_charge",))
        at_end = outstanding(con, acc["id"], month, ("fixed_charge",), paid_through=month)
        charged = _on_account(con, acc["id"], month, ("fixed_charge",), sign=-1)
        paid = _on_account(con, acc["id"], month, ("fixed_payment",))
        if owed or charged or paid:
            out.append({"name": f["name"], "charged": charged, "paid": paid,
                        "still_to_pay": max(owed, 0), "overpaid": max(-at_end, 0)})
    return out


def electricity_outstanding(con, month):
    acc = db.one(con, "SELECT id FROM account WHERE code = 'acc:electricity'")
    if not acc:
        return 0
    return max(outstanding(con, acc["id"], month, ("electricity_charge",)), 0)


# ----------------------------------------------------------------- partners

def partner_accounts(con):
    """The real partners. `eq:opening` and `eq:profit` are partner-shaped
    because that is what they are in accounting terms, but they are the
    business's own accounts and never belong in a partner list or a picker."""
    return [a for a in balances(con, "partner") if a["code"].startswith("prt:")]


def partners(con, month):
    """Each partner's share of the month, less what they have taken.

    While a month is open the share is a calculation; closing the month posts
    it to each partner's account, which is when `allocated` and `balance` stop
    being two views of the same thing.
    """
    rows = partner_accounts(con)
    shares = [(a["name"], float(json.loads(a["meta"] or "{}").get("share") or 0))
              for a in rows]
    # Part-way through the month the full result has thirty days of rent and
    # salaries against a few days of sales; a share of that is a share of a
    # loss that is not real. So the month in progress is split as it stands.
    sf = so_far(con, month)
    net = sf["net"] if sf else (result(con, month).get("net") or 0)
    cut = split_shares(net, [s for s in shares if s[1] > 0])
    closed = is_closed(con, month)
    out = []
    for a in rows:
        meta = json.loads(a["meta"] or "{}")
        share = float(meta.get("share") or 0)
        taken = _on_account(con, a["id"], month, ("partner_draw", "partner_settlement"))
        put_in = _on_account(con, a["id"], month, ("partner_in",), sign=-1)
        allocated = db.scalar(con,
            "SELECT COALESCE(SUM(-m.amount), 0) FROM movement m WHERE m.account_id = ? "
            "AND m.entry_kind = 'profit_share'", (a["id"],))
        if not (share or taken or put_in or a["balance"]):
            continue
        out.append({"id": a["id"], "name": a["name"], "share": share,
                    "active": a["active"], "profit": cut.get(a["name"], 0),
                    "so_far": bool(sf),
                    "allocated": allocated, "posted": closed,
                    "taken": taken, "put_in": put_in,
                    "balance": balance(con, a["code"]),
                    "this_month": cut.get(a["name"], 0) - taken + put_in})
    return out


def drawings(con, month):
    """What the partners have taken out this month, beside what the month has
    actually made, so that taking out more than the month makes shows while
    it is happening rather than at the end."""
    prt = partners(con, month)
    taken = sum(p["taken"] - p["put_in"] for p in prt)
    sf = so_far(con, month)
    if sf:
        profit, basis = sf["net"], "so far"
    else:
        profit = result(con, month).get("net") or 0
        basis = "closed" if is_closed(con, month) else "month"
    return {"taken": taken, "profit": profit, "basis": basis,
            "over": max(taken - max(profit, 0), 0) if taken > 0 else 0,
            "shares_total": round(sum(p["share"] for p in prt), 4)}


# ---------------------------------------------------------------- suppliers

def supplier_owed(con, supplier_id, month, upto=None):
    """What a supplier is owed for everything up to the end of `month`, or for
    the goods that had come by `upto` within it. Goods count on the day they
    came; a payment counts for the month it was made for, so October's goods
    paid on 3 November are paid in October."""
    _, end = month_range(month)
    upto = min(upto or end, end)
    return db.scalar(con,
        "SELECT COALESCE(SUM(m.amount * m.normal), 0) FROM movement m "
        "WHERE m.account_id = ? AND CASE WHEN m.entry_kind = 'supplier_payment' "
        "THEN m.period <= ? ELSE m.happened_on <= ? END", (supplier_id, month, upto))


def on_shelves(con, supplier_id, count_date):
    """What a supplier's goods still on the shelves were worth at a count. A
    flavour comes from its brand's supplier unless it says otherwise."""
    if not count_date:
        return 0
    return db.scalar(con, """
        SELECT COALESCE(SUM(l.value), 0) FROM stock_count_line l
          JOIN stock_item si ON si.id = l.item_id
          JOIN stock_count sc ON sc.id = l.count_id
         WHERE COALESCE(si.supplier_id, (SELECT b.supplier_id FROM stock_item b
                                          WHERE b.id = si.parent_id)) = ?
           AND sc.count_date = ?""", (supplier_id, count_date))


def supplier_statement(con, month):
    """Owed coming in, what arrived, what was paid for the month, owed going
    out, and their goods still on the shelves at the month's count."""
    start, end = month_range(month)
    cd = count_for(con, month)
    out = []
    for a in balances(con, "supplier"):
        bf = supplier_owed(con, a["id"], prev_month(month))
        got = db.scalar(con, "SELECT COALESCE(SUM(amount), 0) FROM receipt "
                             "WHERE supplier_id = ? AND terms = 'credit' "
                             "AND voided_at IS NULL "
                             "AND received_on >= ? AND received_on <= ?",
                        (a["id"], start, end))
        paid = db.scalar(con,
            "SELECT COALESCE(SUM(m.amount), 0) FROM movement m WHERE m.account_id = ? "
            "AND m.entry_kind = 'supplier_payment' AND m.period = ?", (a["id"], month))
        closing = supplier_owed(con, a["id"], month)
        if not (bf or got or paid or closing):
            continue
        out.append({"id": a["id"], "name": a["name"], "brought_forward": bf,
                    "received": got, "paid": paid, "closing": closing,
                    "owed_now": a["balance"], "active": a["active"],
                    "on_shelves": on_shelves(con, a["id"], cd), "count_date": cd,
                    # what was owed for the goods that could have been on the
                    # shelf at the count: anything later was not there to count
                    "owed_at_count": supplier_owed(con, a["id"], month, cd) if cd else closing})
    return out


def supplier_lines(con, supplier_id, month):
    """One supplier's account for the month, line by line, built from the
    movements on the account itself so that it always adds up: what was owed
    coming in, plus every line, is what is owed going out. Goods are on the day
    they came, a payment in the month it was made for."""
    a = db.one(con, "SELECT * FROM account WHERE id = ? AND kind = 'supplier'",
               (supplier_id,))
    if not a:
        return None
    start, end = month_range(month)
    opening = supplier_owed(con, supplier_id, prev_month(month))
    lines = []
    for m in db.all_(con,
            "SELECT m.happened_on, m.entry_kind, m.memo, m.amount * m.normal AS delta "
            "FROM movement m WHERE m.account_id = ? AND CASE "
            "WHEN m.entry_kind = 'supplier_payment' THEN m.period = ? "
            "ELSE m.happened_on >= ? AND m.happened_on <= ? END "
            "ORDER BY m.happened_on, m.entry_id",
            (supplier_id, month, start, end)):
        what = {"receipt_credit": "Goods received",
                "supplier_payment": "Paid",
                "opening": "Owed when these books began"}.get(
                    m["entry_kind"], kinds.label(m["entry_kind"]))
        if m["entry_kind"] == "receipt_credit" and m["memo"]:
            what += f" — {m['memo']}"
        lines.append({"on": m["happened_on"], "what": what, "amount": m["delta"]})
    closing = supplier_owed(con, supplier_id, month)
    cd = count_for(con, month)
    return {"id": a["id"], "name": a["name"], "month": month, "opening": opening,
            "lines": lines, "closing": closing, "owed_now": balance(con, a["code"]),
            "received": sum(l["amount"] for l in lines if l["amount"] > 0),
            "paid": -sum(l["amount"] for l in lines if l["amount"] < 0),
            "on_shelves": on_shelves(con, supplier_id, cd), "count_date": cd}


def owed_to_suppliers(con, as_of=None):
    return sum(max(r["balance"], 0) for r in balances(con, "supplier", as_of))


# -------------------------------------------------------------- cash counts

def cash_counts(con):
    """Every count, with what the books expected and where any gap sat.

    The expected figure is worked out per pot at the count date, so a
    difference points at a pot instead of just existing. A difference that has
    been written off is shown as found-and-dealt-with: `found` is what the
    count turned up, `diff` is what is still unexplained.
    """
    # A write-off belongs to its count by the count's number and its night: a
    # deleted count's number is given to the next one, and a write-off of the
    # old night put back must not land on the new one.
    written = {}
    for r in db.all_(con, """
            SELECT e.source_ref, e.happened_on, p.account_id, p.amount FROM entry e
              JOIN posting p ON p.entry_id = e.id
              JOIN account a ON a.id = p.account_id
             WHERE e.kind = 'cash_difference' AND e.voided_at IS NULL
               AND a.kind IN ('cash', 'float') AND e.source_ref LIKE 'count:%'"""):
        try:
            count_id = int(r["source_ref"].split(":")[1])
        except (IndexError, ValueError):
            continue
        key = (count_id, r["account_id"], r["happened_on"])
        written[key] = written.get(key, 0) + r["amount"]
    # what was moved out of the drawer after a count, leaving the float: it
    # happened after the counting, so that night's count must not expect it
    after = {}
    for r in db.all_(con, """
            SELECT e.source_ref, e.happened_on, p.account_id, p.amount FROM entry e
              JOIN posting p ON p.entry_id = e.id
             WHERE e.kind = 'transfer' AND e.voided_at IS NULL
               AND e.source_ref LIKE 'count:%:rest'"""):
        try:
            count_id = int(r["source_ref"].split(":")[1])
        except (IndexError, ValueError):
            continue
        key = (count_id, r["account_id"], r["happened_on"])
        after[key] = after.get(key, 0) + r["amount"]

    # Each pot's balance at the end of every day it moved, read once: summing
    # a pot's whole history again for every count grew with the square of
    # the nights, and the screens slowed down month by month.
    days, sums = {}, {}
    for r in db.all_(con, """
            SELECT account_id, happened_on, SUM(amount * normal) AS d FROM movement
             WHERE kind IN ('cash', 'float') GROUP BY account_id, happened_on
             ORDER BY account_id, happened_on"""):
        days.setdefault(r["account_id"], []).append(r["happened_on"])
        run = sums.setdefault(r["account_id"], [])
        run.append((run[-1] if run else 0) + r["d"])

    def held(account_id, on):
        i = bisect_right(days.get(account_id, []), on)
        return sums[account_id][i - 1] if i else 0

    lines_of = {}
    for line in db.all_(con,
            "SELECT l.count_id, l.counted, a.id AS account_id, a.name FROM cash_count_line l "
            "JOIN account a ON a.id = l.account_id ORDER BY a.sort, a.id"):
        lines_of.setdefault(line["count_id"], []).append(line)

    out = []
    for c in db.all_(con, "SELECT * FROM cash_count ORDER BY counted_on"):
        lines = lines_of.get(c["id"], [])
        per_pot, counted, expected, found, left = [], 0, 0, 0, 0
        for line in lines:
            now = held(line["account_id"], c["counted_on"]) \
                - after.get((c["id"], line["account_id"], c["counted_on"]), 0)
            off = written.get((c["id"], line["account_id"], c["counted_on"]), 0)
            before = now - off                 # what the books said that night
            per_pot.append({"name": line["name"], "counted": line["counted"],
                            "expected": before, "found": line["counted"] - before,
                            "written_off": off, "diff": line["counted"] - now})
            counted += line["counted"]
            expected += before
            found += line["counted"] - before
            left += line["counted"] - now
        out.append({"id": c["id"], "on": c["counted_on"], "reason": c["reason"],
                    "counted": counted, "expected": expected, "found": found,
                    "written_off": found - left, "diff": left, "pots": per_pot,
                    "split": len(lines) > 1})
    return out


# -------------------------------------------------------------- the day view

def day(con, on=None):
    on = on or today()
    sales = db.scalar(con, "SELECT COALESCE(SUM(-m.amount), 0) FROM movement m "
                           "WHERE m.code = 'rev:sales' AND m.happened_on = ?", (on,))
    spent = db.scalar(con, "SELECT COALESCE(SUM(m.amount), 0) FROM movement m "
                           "WHERE m.code = 'exp:daily' AND m.happened_on = ?", (on,))
    # everything that physically left a pot today, whatever it was for
    paid_out = db.scalar(con, """
        SELECT COALESCE(SUM(-t.delta), 0) FROM (
          SELECT SUM(m.amount) AS delta FROM movement m
           WHERE m.kind IN ('cash', 'float') AND m.happened_on = ?
             AND m.entry_kind <> 'transfer'
           GROUP BY m.entry_id) t WHERE t.delta < 0""", (on,))
    # the night's own cash count, however long ago: the screen's list holds
    # only the latest ones
    count = next((c for c in cash_counts(con) if c["on"] == on), None)
    return {"on": on, "sales": sales, "spent": spent, "paid_out": paid_out,
            "cash": cash_on_hand(con, on), "floats": in_hands(con, on),
            "pots": pots(con, as_of=on), "entries": entries(con, on=on), "count": count}


def entries(con, *, on=None, month=None, limit=None, q=None, detail=None,
            kind=None, date_from=None, date_to=None, ids=None):
    """Entries with everything a row on screen needs: what it was, who, which
    pot, how much, and whether it can still be corrected.

    `month` selects by the month an entry belongs to; the date arguments
    select by the day the cash moved. `q` searches every month.
    """
    sql = ("SELECT e.id, e.happened_on, e.period, e.kind, e.detail, e.memo, "
           "       e.source, e.source_ref FROM entry e WHERE e.voided_at IS NULL")
    args = []
    if on:
        sql += " AND e.happened_on = ?"
        args.append(on)
    if month:
        sql += " AND e.period = ?"
        args.append(month)
    if detail is not None:
        sql += " AND COALESCE(e.detail, '') = ?"
        args.append(detail)
    if kind:
        sql += " AND e.kind = ?"
        args.append(kind)
    if date_from:
        sql += " AND e.happened_on >= ?"
        args.append(date_from)
    if date_to:
        sql += " AND e.happened_on <= ?"
        args.append(date_to)
    if ids is not None:
        if not ids:
            return []
        sql += f" AND e.id IN ({','.join('?' for _ in ids)})"
        args.extend(ids)
    for word in str(q or "").split():
        like = f"%{word}%"
        named = [k for k, v in kinds.LABELS.items() if word.lower() in v.lower()]
        clause = "(e.detail LIKE ? OR e.memo LIKE ? OR e.happened_on LIKE ?"
        wargs = [like, like, like]
        if named:
            clause += f" OR e.kind IN ({','.join('?' for _ in named)})"
            wargs.extend(named)
        digits = word.replace(",", "")
        if digits.isdigit():
            clause += (" OR EXISTS (SELECT 1 FROM posting p WHERE p.entry_id = e.id "
                       "AND ABS(p.amount) = ?)")
            wargs.append(int(digits))
        sql += " AND " + clause + ")"
        args.extend(wargs)
    sql += " ORDER BY e.happened_on DESC, e.id DESC"
    if limit:
        sql += f" LIMIT {int(limit)}"
    rows = [dict(r) for r in db.all_(con, sql, args)]
    if not rows:
        return []

    by_id = {r["id"]: r for r in rows}
    for r in rows:
        r["legs"] = []
    marks = ",".join("?" for _ in rows)
    for leg in db.all_(con,
            f"SELECT p.entry_id, a.name, a.code, a.kind, p.amount FROM posting p "
            f"JOIN account a ON a.id = p.account_id WHERE p.entry_id IN ({marks}) "
            f"ORDER BY p.amount DESC", [r["id"] for r in rows]):
        by_id[leg["entry_id"]]["legs"].append(
            {"name": leg["name"], "code": leg["code"], "kind": leg["kind"],
             "amount": leg["amount"]})
    receipts = {r["entry_id"]: dict(r) for r in db.all_(con,
        f"SELECT r.entry_id, r.id, r.number, r.what, r.terms, a.name AS supplier "
        f"FROM receipt r LEFT JOIN account a ON a.id = r.supplier_id "
        f"WHERE r.entry_id IN ({marks})", [r["id"] for r in rows])}
    closed = {m for m in months(con) if is_closed(con, m)}

    for r in rows:
        legs = r["legs"]
        r["label"] = kinds.label(r["kind"])
        r["amount"] = sum(l["amount"] for l in legs if l["amount"] > 0)
        cash = [l for l in legs if l["kind"] in ("cash", "float")]
        r["cash"] = sum(l["amount"] for l in cash)      # + came in, - went out
        if r["kind"] == "transfer":
            r["pot"] = next((l["name"] for l in cash if l["amount"] < 0), None)
            r["pot_to"] = next((l["name"] for l in cash if l["amount"] > 0), None)
        else:
            r["pot"] = cash[0]["name"] if cash else None
            r["pot_to"] = None
        r["tagged"] = r["period"] != r["happened_on"][:7]
        r["receipt"] = receipts.get(r["id"])
        # the person it was for, by the account it was posted to, as they are
        # called now: `detail` keeps the name written at the time
        person = next((l for l in legs if l["kind"] in ("staff", "supplier")
                       or l["code"].startswith("prt:")), None)
        r["who"] = person["name"] if person else (r["receipt"] or {}).get("supplier")
        # An imported row from before the rebase date has its other side on
        # Opening balances; correcting it would re-post it against the person
        # and invent a balance, so it is part of the record and left alone.
        historic = any(l["code"] == "eq:opening" for l in legs)
        open_ = r["period"] not in closed
        r["editable"] = (open_ and not historic and r["source"] != "close"
                         and r["kind"] in kinds.EDITABLE)
        r["deletable"] = (open_ and not historic and r["source"] != "close"
                          and r["kind"] in kinds.DELETABLE)
    return rows


# ------------------------------------------------------- where the money went

def money_flow(con, month):
    """Cash that physically left or entered a pot during the month, by kind
    and then by name.

    By the day the cash moved, not by the month an entry belongs to — this is
    the cash view. A salary handed over on 3 November for October is November
    cash going out, and shows here in November.
    """
    start, end = month_range(month)
    out, inn = {}, {}
    for r in db.all_(con, """
            SELECT m.entry_id, m.entry_kind, COALESCE(m.detail, '') AS detail,
                   SUM(m.amount) AS delta
              FROM movement m
             WHERE m.kind IN ('cash', 'float') AND m.happened_on >= ?
               AND m.happened_on <= ? AND m.entry_kind <> 'transfer'
             GROUP BY m.entry_id""", (start, end)):
        if not r["delta"]:
            continue
        side = out if r["delta"] < 0 else inn
        g = side.setdefault(r["entry_kind"], {"kind": r["entry_kind"],
                                              "label": kinds.label(r["entry_kind"]),
                                              "total": 0, "by": {}})
        name = r["detail"] or "(not named)"
        g["total"] += abs(r["delta"])
        g["by"][name] = g["by"].get(name, 0) + abs(r["delta"])

    def shape(side):
        groups = []
        for g in side.values():
            rows = sorted(g["by"].items(), key=lambda kv: (-kv[1], kv[0]))
            groups.append({"kind": g["kind"], "label": g["label"],
                           "total": g["total"], "rows": [list(x) for x in rows]})
        return sorted(groups, key=lambda g: -g["total"])
    o, i = shape(out), shape(inn)
    return {"out": o, "in": i, "out_total": sum(g["total"] for g in o),
            "in_total": sum(g["total"] for g in i), "from": start, "to": end}


def sales_by_day(con, month):
    start, end = month_range(month)
    return [[r["happened_on"], r["s"]] for r in db.all_(con,
        "SELECT m.happened_on, SUM(-m.amount) AS s FROM movement m "
        "WHERE m.code = 'rev:sales' AND m.happened_on >= ? AND m.happened_on <= ? "
        "GROUP BY m.happened_on ORDER BY m.happened_on", (start, end))]


# ------------------------------------------------------------ recent changes

QUIET_ACTIONS = {"count_line", "open_count"}


def recent(con, limit=40):
    """What has been done to the books lately, newest first, in plain words.

    A stock count saves line by line, so a run of those is folded into one row
    rather than burying everything else under fifty of them.
    """
    rows = db.all_(con,
        "SELECT id, at, action, subject, detail FROM audit "
        "WHERE action NOT LIKE '%.%' AND action <> 'import' "
        "ORDER BY id DESC LIMIT ?", (limit * 6,))
    out, run_of = [], None
    for r in rows:
        d = json.loads(r["detail"]) if r["detail"] else {}
        if r["action"] in QUIET_ACTIONS:
            key = d.get("on") or d.get("count_date")
            if run_of and run_of["key"] == key:
                run_of["row"]["lines"] += 1
                run_of["row"]["summary"] = (f"Stock count for {key}: "
                                            f"{run_of['row']['lines']} lines saved")
                continue
            row = {"id": r["id"], "at": r["at"], "action": "count",
                   "summary": f"Stock count for {key}: 1 line saved",
                   "lines": 1, "entry": None, "can_put_back": False}
            run_of = {"key": key, "row": row}
            out.append(row)
        else:
            run_of = None
            out.append({"id": r["id"], "at": r["at"], "action": r["action"],
                        "summary": d.get("summary") or r["action"].replace("_", " "),
                        "entry": d.get("entry"), "can_put_back": False})
        if len(out) >= limit:
            break
    # a deletion can be put back while the entry is still deleted, was not
    # replaced by a correction, and its month is open
    voids = [o for o in out if o["action"] == "void" and o["entry"]]
    if voids:
        marks = ",".join("?" for _ in voids)
        state = {e["id"]: e for e in db.all_(con,
            f"SELECT id, voided_at, replaced_by, period FROM entry WHERE id IN ({marks})",
            [o["entry"] for o in voids])}
        for o in voids:
            e = state.get(o["entry"])
            o["can_put_back"] = bool(e and e["voided_at"] and not e["replaced_by"]
                                     and not is_closed(con, e["period"]))
    return out
