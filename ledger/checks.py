"""Things worth a look, each one a question with a yes or no answer.

A check that is always red teaches people to stop reading the list. So a check
only fails when there is something to do today:

  * salaries, rent and electricity are checked up to the end of *last* month.
    This month's are charged from the first day and nobody expects them to be
    paid on the first day.
  * a stock count is only asked for once a month has ended.

Every check that fails says, in its own words, what to do about it.
"""
from . import backup, db, expected, queries
from .dates import month_name, month_of, prev_month, today
from .pos import auto, links
from .registry import pot_lows


def checks(con, month):
    out = []

    def add(ok, label, detail="", fix="", go=None):
        out.append({"ok": bool(ok), "label": label, "detail": detail,
                    "fix": fix, "go": go})

    now = month_of(today())
    # obligations are due once their month is over
    due = month if month < now else prev_month(now)
    due_name = month_name(due)

    # ---- the ledger itself
    bad = db.all_(con, "SELECT * FROM unbalanced LIMIT 3")
    add(not bad, "The books balance",
        "every entry's two sides cancel" if not bad else f"{len(bad)} entries do not",
        "This should be impossible. Stop entering and send Claude the books.")

    # ---- cash
    breaks = [c for c in queries.cash_counts(con) if c["diff"] != 0]
    add(not breaks, "Every cash count ties",
        "all of them" if not breaks else
        f"{len(breaks)} do not — latest {breaks[-1]['on']}, out by {breaks[-1]['diff']:+,}",
        "Find the missing entry, or write the difference off on Books.", "books")

    lows = pot_lows(con)
    for code, p in lows.items():
        if p["low"] < 0:
            add(False, f"{p['name']} went below zero",
                f"down to {p['low']:,} on {p['on']}",
                "Cash cannot be negative: a payment is dated before the money "
                "that funded it, or came from the wrong pot.", "books")
    if not any(p["low"] < 0 for p in lows.values()):
        add(True, "No pot ever went below zero")

    # ---- months left open
    stale = [m for m in queries.months(con) if m < now and not queries.is_closed(con, m)]
    add(not stale, "Finished months are closed",
        "" if not stale else ", ".join(month_name(m) for m in stale) + " still open",
        "An open month can still be changed by accident. Close it on Month.", "month")

    # ---- the viewed month's stock, once it has ended
    if month < now and not queries.is_closed(con, month):
        c = queries.cogs(con, month)
        add(c["counted_this_month"], f"Stock was counted in {month_name(month)}",
            f"last count {c['date'] or 'never'}",
            "It cannot be closed without a count. Take one on Stock.", "stock")
    c = queries.cogs(con, month)
    if c["counted_this_month"] or month < now:
        add(c["raw"] >= 0, "Cost of goods makes sense",
            "" if c["raw"] >= 0 else f"came out at {c['raw']:,}",
            "More stock than you started with plus everything bought: a "
            "delivery is missing, or a count is wrong.", "stock")

    # ---- stock running low, where Setup gives a minimum
    lows = expected.low(con)
    if lows is not None:
        add(not lows, "Nothing is running low",
            "everything with a minimum is above it" if not lows else
            "; ".join(expected.said(r) for r in lows[:6])
            + (f"; and {len(lows) - 6} more" if len(lows) > 6 else ""),
            "Order more before it runs out. Stock shows what should be on the shelf.",
            "stock")

    # ---- what is owed, up to the end of the last finished month
    if queries.period(con, due):
        owed = [p for p in queries.payroll(con, due) if p["still_to_pay"]]
        add(not owed, f"Salaries are paid up to {due_name}",
            "nobody is owed" if not owed else
            ", ".join(f"{p['name']} {p['still_to_pay']:,}" for p in owed),
            "Settle up on Month.", "month")

        rent = [f for f in queries.fixed_outstanding(con, due) if f["still_to_pay"]]
        add(not rent, f"Rent is paid up to {due_name}",
            "" if not rent else
            ", ".join(f"{f['name']} {f['still_to_pay']:,}" for f in rent),
            "Settle up on Month.", "month")

        unpaid = queries.electricity_outstanding(con, due)
        add(unpaid <= 0, f"Electricity is paid up to {due_name}",
            "" if unpaid <= 0 else f"{unpaid:,} still to pay",
            "Pay it from the electricity card on Month.", "month")

        if not queries.is_closed(con, due):
            charged = queries.period_total(con, "exp:electricity", due)
            add(charged > 0, f"Electricity was charged to {due_name}",
                "" if charged else "no meter reading entered",
                "Every month uses power. Enter the reading on Month.", "month")

    # ---- partners
    shares = queries.drawings(con, month)["shares_total"]
    add(abs(shares - 1) < 0.0005, "Partners' shares add up to 100%",
        "" if abs(shares - 1) < 0.0005 else f"they add up to {shares * 100:.0f}%",
        "Fix the shares in Setup, or a month's profit will not split properly.", "setup")

    # ---- SambaPOS's accounts and the people in the books
    gone = links.gone_but_here(con)
    if gone:
        add(False, "Everyone SambaPOS has dropped is marked as left",
            "SambaPOS no longer has " + ", ".join(g["books_name"] for g in gone),
            "If they have left, mark them as left in Setup, under SambaPOS.", "setup")
    used = links.left_but_used(con)
    if used:
        add(False, "Nobody who has left is still in SambaPOS",
            "SambaPOS recorded money for " + ", ".join(u["books_name"] for u in used)
            + " after they left",
            "Remove their accounts from SambaPOS, so they cannot be used by mistake.",
            "setup")

    # ---- SambaPOS's own backups, once the app has been told where they are
    pos = auto.view(con)
    if pos["on"]:
        wrong = pos["problem"]
        add(not wrong, "SambaPOS's backups are coming in",
            wrong[0] if wrong else ("reading the newest now" if pos["waiting"]
                                    else f"the newest is from {pos['newest_when']}"),
            wrong[1] if wrong else "", "setup")

    # ---- the safety net
    b = backup.status(con)
    if not b["second"]:
        add(False, "The books have a copy somewhere else",
            "every backup is on this PC's own disk",
            "If this PC dies, so do they. Choose a second folder in Setup.", "setup")
    else:
        fresh = b["second_ok"] and (b["days_old"] is not None and b["days_old"] <= 3)
        add(fresh, "The books have a copy somewhere else",
            f"last copied to {b['second']}" if fresh else
            (b["last"].get("second_error") or "the last copy there is more than 3 days old"),
            "Check the second backup folder in Setup is plugged in and reachable.",
            "setup")
    return out
