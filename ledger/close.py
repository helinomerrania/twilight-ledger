"""Closing a month, and opening it again.

Closing writes down what the month came to and freezes it, so that nothing
changed afterwards — a price in Setup, a salary, a tare weight — can move a
figure that has already been acted on. The old app recomputed closed months
from the current Setup every time a screen rendered, which is why hiring
someone moved August.
"""
import json

from . import db, post, queries
from .dates import month_end, month_of, next_month, today
from .money import split_shares


def ready(con, month):
    """What stands in the way of closing, in plain words."""
    stops, warnings = [], []
    per = queries.period(con, month)
    if per and per["status"] == "closed":
        stops.append(f"{month} is already closed.")
    bad = db.all_(con, "SELECT * FROM unbalanced LIMIT 1")
    if bad:
        stops.append("The books do not balance.")
    c = queries.cogs(con, month)
    if not c["date"] or c["date"] < f"{month}-01":
        stops.append("There is no stock count in this month, so the cost of "
                     "goods cannot be measured.")
    prev = _previous(con, month)
    if prev and queries.period(con, prev) and queries.period(con, prev)["status"] == "open":
        stops.append(f"{prev} is still open. Months close in order.")
    if c["raw"] < 0:
        warnings.append(f"The cost of goods comes out at {c['raw']:,}, which is "
                        "negative — a delivery may be missing.")
    for p in queries.payroll(con, month):
        if p["still_to_pay"]:
            warnings.append(f"{p['name']} is still owed {p['still_to_pay']:,}.")
    for f in queries.fixed_outstanding(con, month):
        if f["still_to_pay"]:
            warnings.append(f"{f['name']} is still owed {f['still_to_pay']:,}.")
    if not queries.period_total(con, "exp:electricity", month):
        warnings.append("No electricity has been charged to this month yet.")
    elif queries.electricity_outstanding(con, month):
        warnings.append(f"Electricity is still owed "
                        f"{queries.electricity_outstanding(con, month):,}.")
    breaks = [x for x in queries.cash_counts(con)
              if x["diff"] != 0 and x["on"][:7] == month]
    for b in breaks:
        warnings.append(f"The count on {b['on']} is out by {b['diff']:+,}.")
    return {"can_close": not stops, "stops": stops, "warnings": warnings,
            "count_date": c["date"], "result": queries.live_result(con, month)}


def _previous(con, month):
    ms = queries.months(con)
    before = [m for m in ms if m < month]
    return before[-1] if before else None


def close_month(con, month):
    """Freeze the month.

    Three things happen, in this order: the cost of goods is posted out of the
    stock account; whatever is then left over against the physical count is
    posted as a stock difference, so shrinkage shows as a line rather than
    hiding inside cost; and the result is stored as a record.
    """
    check = ready(con, month)
    if not check["can_close"]:
        raise db.LedgerError(" ".join(check["stops"]))

    c = queries.cogs(con, month)
    count_date = c["date"]
    if c["value"]:
        post.record(con, kind="cogs", on=count_date, period=month,
                    detail="Cost of goods sold", source="close",
                    legs=[(post.account_id(con, "exp:cogs"), c["value"]),
                          (post.account_id(con, "inv:stock"), -c["value"])])
    have = queries.balance(con, "inv:stock", as_of=count_date)
    drift = have - c["closing"]
    if drift:
        post.record(con, kind="stock_difference", on=count_date, period=month,
                    detail="Stock difference", source="close",
                    memo="brings the stock account onto the count",
                    legs=[(post.account_id(con, "exp:variance"), drift),
                          (post.account_id(con, "inv:stock"), -drift)])

    result = queries.live_result(con, month)

    # Allocate the month's profit to the partners. Until this happens a
    # partner's account only holds what they have taken out, so the balance
    # reads as if they owe the business everything they have ever drawn.
    # Closing is the moment the share becomes real.
    import json as _json
    shares = [(a["name"], float(_json.loads(a["meta"] or "{}").get("share") or 0))
              for a in queries.partner_accounts(con)]
    cut = split_shares(result["net"], [s for s in shares if s[1] > 0])
    for name, amount in cut.items():
        if not amount:
            continue
        post.record(con, kind="profit_share", on=month_end(month), period=month,
                    detail=name, source="close",
                    memo=f"share of {month}",
                    legs=[(post.account_id(con, "eq:profit"), amount),
                          (post.account_by_name(con, "partner", name), -amount)])
    result["allocated"] = cut

    result["closed_cash"] = queries.cash_on_hand(con, month_end(month))
    result["closed_floats"] = queries.in_hands(con, month_end(month))
    con.execute("UPDATE period SET status='closed', closed_at=datetime('now'), "
                "count_date=?, result=? WHERE month=?",
                (count_date, json.dumps(result, ensure_ascii=False), month))
    post.ensure_period(con, next_month(month))
    db.audit(con, "period.close", f"period:{month}",
             {"net": result["net"], "count_date": count_date,
              "warnings": check["warnings"]})
    return {"month": month, "result": result, "warnings": check["warnings"]}


def reopen_month(con, month):
    """Unfreeze a month, undoing the postings that closing made.

    The stored result is kept, not deleted: it is the record of what was
    reported at the time, and if the month closes again to a different figure
    that difference is worth being able to see.
    """
    per = queries.period(con, month)
    if not per or per["status"] != "closed":
        raise db.LedgerError(f"{month} is not closed")
    later = [m for m in queries.months(con)
             if m > month and queries.period(con, m)
             and queries.period(con, m)["status"] == "closed"]
    if later:
        raise db.LedgerError(
            f"{later[0]} was closed after this one. Reopen months newest first.")
    con.execute("UPDATE period SET status='open', closed_at=NULL WHERE month=?",
                (month,))
    for e in db.all_(con, "SELECT id FROM entry WHERE period = ? AND source = 'close' "
                          "AND voided_at IS NULL", (month,)):
        post.void(con, e["id"], why=f"{month} reopened")
    db.audit(con, "period.reopen", f"period:{month}",
             {"kept_result": json.loads(per["result"]) if per["result"] else None})
    return {"month": month, "reopened": True}
