"""Cash you can trust: the count against what SambaPOS says, and differences
over time.

The counted cash and what SambaPOS says sometimes differ, up or down. The
books show the real sales and the difference separately: a sales figure
worked out from the count would hide a shortage inside the sales, and no
pattern could ever be seen. So:

- what SambaPOS says went into and out of the drawer is set beside the count
  (`drawer`), and the night's sales are flagged when they are not SambaPOS's;
- a float can be left in the drawer for the next night, set once in Setup,
  and the rest moved out in one click after the count;
- a count can be made blind, so nobody counts towards the answer;
- each count's difference is kept over the month, with who opened SambaPOS
  that night (`differences`).
"""
from . import db, post, queries
from .dates import month_of
from .money import to_int
from .pos import adding, archive, links
from .registry import ApiError, action, clean_date

DEFAULTS = {"float": 0, "blind": False, "rest_to": ""}


def settings(con):
    return {**DEFAULTS, **(db.setting(con, "cash", {}) or {})}


def drawer(con, on):
    """What the count step needs for the night of `on`: the pot SambaPOS's
    drawer is linked to, what SambaPOS says moved through it, and whether the
    books' sales are SambaPOS's. None-valued parts are simply not known."""
    s = settings(con)
    out = {"float": s["float"], "blind": bool(s["blind"]), "rest_to": s["rest_to"],
           "pot": None, "pos": None, "sales_differ": None, "moved": None}
    linked = links.links(con)
    pots = adding._pots(con)
    out["pot"] = adding._drawer_pot(con, linked, pots)
    night = archive.night(con, on)
    if night:
        p = adding.plan(con, on)
        cash = sum(l["amount"] for l in p["lines"]
                   if l.get("kind") == "daily_sales" and l.get("pot") == out["pot"])
        no_types = all(l.get("pot") is None for l in p["lines"]
                       if l.get("kind") == "daily_sales")
        if no_types:        # takings that cannot be placed yet: all of them, as cash
            cash = night["takings"]
        pos = {"cash": cash, "out": night["drawer_out"], "in": night["drawer_in"],
               "takings": night["takings"]}
        pos["net"] = cash - pos["out"] + pos["in"]
        if s["float"]:
            pos["expected"] = s["float"] + pos["net"]
        out["pos"] = pos
        books_sales = queries.day(con, on)["sales"]
        if books_sales and books_sales != night["takings"]:
            out["sales_differ"] = {"books": books_sales, "pos": night["takings"],
                                   "gap": night["takings"] - books_sales}
    # moved out of the drawer's pot that day already, after the count
    out["moved"] = db.scalar(con, """
        SELECT COALESCE(SUM(-m.amount), 0) FROM movement m
         WHERE m.entry_kind = 'transfer' AND m.happened_on = ? AND m.amount < 0
           AND m.account_id = (SELECT id FROM account WHERE name = ?
                                AND kind IN ('cash', 'float'))""", (on, out["pot"]))
    return out


def differences(con, month):
    """Every count in a month: the night's own difference, who opened
    SambaPOS that night — with totals, and the same grouped by who opened.

    A count's gap against the books includes whatever an earlier count left
    unexplained, so a shortage nobody wrote off would show again every night
    after. A night's own difference is its gap less what the count before it
    left: what this night added."""
    rows, left = [], 0
    for c in queries.cash_counts(con):
        own = c["found"] - left
        left = c["diff"]
        if month_of(c["on"]) != month:
            continue
        night = archive.night(con, c["on"])
        rows.append({"on": c["on"], "found": own, "gap": c["found"], "left": c["diff"],
                     "written_off": c["written_off"], "reason": c["reason"],
                     "opened_by": night["opened_by"] if night else None})
    by = {}
    for r in rows:
        who = r["opened_by"] or "not known"
        g = by.setdefault(who, {"who": who, "nights": 0, "short": 0, "over": 0, "net": 0})
        g["nights"] += 1
        g["net"] += r["found"]
        if r["found"] < 0:
            g["short"] += 1
        elif r["found"] > 0:
            g["over"] += 1
    return {"rows": rows,
            "short": sum(r["found"] for r in rows if r["found"] < 0),
            "over": sum(r["found"] for r in rows if r["found"] > 0),
            "net": sum(r["found"] for r in rows),
            "by_who": sorted(by.values(), key=lambda g: g["net"])}


def _moved_line(con, body, out):
    return f"Moved {out['amount']:,} out of {out['from']} to {out['to']}, leaving the float"


@action("move_rest", summary=_moved_line)
def _move_rest(con, body):
    """After the count: everything above the float out of the drawer's pot.
    The entry is tied to the count, which was taken before it, so the count
    does not expect it."""
    on = clean_date(body.get("on"))
    c = db.one(con, "SELECT id FROM cash_count WHERE counted_on = ?", (on,))
    if not c:
        raise ApiError("count the cash first")
    amount = to_int(body.get("amount"), "the amount")
    if amount <= 0:
        raise ApiError("there is nothing above the float to move")
    frm = drawer(con, on)["pot"]
    to = str(body.get("to") or "").strip()
    if not to:
        raise ApiError("pick where the rest goes")
    post.pot_id(con, to)
    if to == frm:
        raise ApiError("pick a different pot to move it to")
    eid = post.transfer(con, amount, frm=frm, to=to, on=on,
                        source_ref=f"count:{c['id']}:rest")
    return {"id": eid, "amount": amount, "from": frm, "to": to}


@action("cash_settings", guard_pots=False,
        summary=lambda con, body, out: "Changed how the cash is counted")
def _cash_settings(con, body):
    """The float left in the drawer, whether counts are blind, and where the
    rest of the drawer usually goes."""
    s = settings(con)
    if "float" in body:
        f = to_int(body.get("float") or 0, "the float")
        if f < 0:
            raise ApiError("a float cannot be less than nothing")
        s["float"] = f
    if "blind" in body:
        s["blind"] = str(body.get("blind")).strip().lower() in ("1", "true", "yes")
    if "rest_to" in body:
        name = str(body.get("rest_to") or "").strip()
        if name:
            post.pot_id(con, name)              # must be a pot
        s["rest_to"] = name
    db.set_setting(con, "cash", s)
    return {}
