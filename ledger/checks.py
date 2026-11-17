"""Things worth a look, each one a question with a yes or no answer.

A check that is always red teaches people to stop reading the list. So a check
only fails when there is something to do today:

  * salaries, rent and electricity are checked up to the end of *last* month.
    This month's are charged from the first day and nobody expects them to be
    paid on the first day.
  * a stock count is only asked for once a month has ended.

Every check that fails says, in its own words, what to do about it.
"""
import json

from . import backup, db, expected, queries
from .dates import month_of, month_words, prev_month, tonight
from .pos import auto, links
from .registry import pot_lows
from .words import t


def checks(con, month):
    out = []

    def add(ok, label, detail="", fix="", go=None):
        out.append({"ok": bool(ok), "label": label, "detail": detail,
                    "fix": fix, "go": go, "serious": False})

    now = month_of(tonight())
    # obligations are due once their month is over, its last night included
    due = month if month < now else prev_month(now)
    due_name = month_words(due)

    # ---- the ledger itself
    bad = db.all_(con, "SELECT * FROM unbalanced LIMIT 3")
    add(not bad, t("check.balance"),
        t("check.balance_yes") if not bad else t("check.balance_no", len(bad)),
        t("check.balance_fix"))
    out[-1]["serious"] = True          # the one that turns the banner red

    # ---- cash
    breaks = [c for c in queries.cash_counts(con) if c["diff"] != 0]
    add(not breaks, t("check.counts"),
        t("check.counts_yes") if not breaks else
        t("check.counts_no", len(breaks), breaks[-1]["on"], f"{breaks[-1]['diff']:+,}"),
        t("check.counts_fix"), "books/cash")

    lows = pot_lows(con)
    for code, p in lows.items():
        if p["low"] < 0:
            add(False, t("check.below_zero", p["name"]),
                t("check.below_zero_detail", f"{p['low']:,}", p["on"]),
                t("check.below_zero_fix"), "books/entries")
    if not any(p["low"] < 0 for p in lows.values()):
        add(True, t("check.never_below_zero"))

    # ---- months left open
    stale = [m for m in queries.months(con) if m < now and not queries.is_closed(con, m)]
    add(not stale, t("check.months_closed"),
        "" if not stale else t("check.months_open", ", ".join(" ".join(month_words(m))
                                                              for m in stale)),
        t("check.months_closed_fix"), "month/close")

    # ---- the viewed month's stock, once it has ended
    if month < now and not queries.is_closed(con, month):
        c = queries.cogs(con, month)
        add(c["counted_this_month"], t("check.counted", *month_words(month)),
            t("check.last_count", c["date"]) if c["date"] else t("check.last_count_never"),
            t("check.counted_fix"), "stock/count")
    c = queries.cogs(con, month)
    if c["counted_this_month"] or month < now:
        add(c["raw"] >= 0, t("check.cogs"),
            "" if c["raw"] >= 0 else t("check.cogs_detail", f"{c['raw']:,}"),
            t("check.cogs_fix"), "stock/count")

    # ---- stock running low, where Setup gives a minimum
    lows = expected.low(con)
    if lows is not None:
        some = "; ".join(expected.said(r) for r in lows[:6])
        add(not lows, t("check.low"),
            t("check.low_none") if not lows else
            t("check.low_more", some, len(lows) - 6) if len(lows) > 6 else some,
            t("check.low_fix"), "stock/shelf")

    # ---- what is owed, up to the end of the last finished month
    if queries.period(con, due):
        owed = [p for p in queries.payroll(con, due) if p["still_to_pay"]]
        add(not owed, t("check.salaries", *due_name),
            t("check.salaries_none") if not owed else
            ", ".join(f"{p['name']} {p['still_to_pay']:,}" for p in owed),
            t("check.settle_fix"), "month/settle")

        rent = [f for f in queries.fixed_outstanding(con, due) if f["still_to_pay"]]
        add(not rent, t("check.rent", *due_name),
            "" if not rent else
            ", ".join(f"{f['name']} {f['still_to_pay']:,}" for f in rent),
            t("check.settle_fix"), "month/settle")

        unpaid = queries.electricity_outstanding(con, due)
        add(unpaid <= 0, t("check.electricity_paid", *due_name),
            "" if unpaid <= 0 else t("check.electricity_unpaid", f"{unpaid:,}"),
            t("check.electricity_paid_fix"), "month/settle")

        if not queries.is_closed(con, due):
            charged = queries.period_total(con, "exp:electricity", due)
            add(charged > 0, t("check.electricity_charged", *due_name),
                "" if charged else t("check.no_reading"),
                t("check.electricity_charged_fix"), "month/settle")

    # ---- partners
    shares = queries.drawings(con, month)["shares_total"]
    add(abs(shares - 1) < 0.0005, t("check.shares", "100%"),
        "" if abs(shares - 1) < 0.0005 else t("check.shares_detail", f"{shares * 100:.0f}%"),
        t("check.shares_fix"), "setup/people")

    kept = [p["name"] for p in queries.partner_accounts(con)
            if not p["active"] and float(json.loads(p["meta"] or "{}").get("share") or 0)]
    if kept:
        add(False, t("check.retired_share"),
            t("check.retired_share_one" if len(kept) == 1 else "check.retired_share_many",
              ", ".join(kept)),
            t("check.retired_share_fix", 0), "setup/people")

    held = queries.retired_pots_holding(con)
    if held:
        add(False, t("check.retired_pot"),
            ", ".join(t("check.retired_pot_holds", n, f"{b:,}") for n, b in held),
            t("check.retired_pot_fix"), "setup/cash")

    # ---- SambaPOS's accounts and the people in the books
    gone = links.gone_but_here(con)
    if gone:
        add(False, t("check.pos_gone"),
            t("check.pos_gone_detail", ", ".join(g["books_name"] for g in gone)),
            t("check.pos_gone_fix"), "setup/sambapos")
    used = links.left_but_used(con)
    if used:
        add(False, t("check.pos_used"),
            t("check.pos_used_detail", ", ".join(u["books_name"] for u in used)),
            t("check.pos_used_fix"), "setup/sambapos")

    # ---- SambaPOS's own backups, once the app has been told where they are
    pos = auto.view(con)
    if pos["on"]:
        wrong = pos["problem"]
        add(not wrong, t("check.pos_backups"),
            wrong[0] if wrong else (t("check.pos_reading") if pos["waiting"]
                                    else t("check.pos_newest", pos["newest_when"])),
            wrong[1] if wrong else "", "setup/sambapos")

    # ---- the safety net
    b = backup.status(con)
    if not b["second"]:
        add(False, t("check.second_copy"), t("check.second_none"),
            t("check.second_none_fix"), "setup/app")
    else:
        fresh = b["second_ok"] and (b["days_old"] is not None and b["days_old"] <= 3)
        add(fresh, t("check.second_copy"),
            t("check.second_last", b["second"]) if fresh else
            (b["last"].get("second_error") or t("check.second_old", 3)),
            t("check.second_fix"), "setup/app")
    return out
