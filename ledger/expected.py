"""What should be on the shelf, and the gap at a count.

    should be = the count before  + what receipts brought in
                                   + what went into a bucket (a mix)
                                   - what went out of its packs into a bucket
                                   - what the nights sold, by SambaPOS's recipes

Everything dated on or before a count is taken to be in it: a count dated the
31st is the shelf after the night of the 31st. So the movements counted are
the ones dated after the count before, up to and including the day asked
about.

Quantities are each item's own, as counted: kilos for tobacco and mixes,
cartons for ice cream, packages for the rest. A line that is not on a count
was not counted, as far as anyone can tell, so it has no gap: only what
should be there is shown.

A bucket dries between counts, so a mix short by no more than the drying
allowance (a percentage of what should be there) is not pointed out; nor is
a weighed gap of a few grams either way, which is the scales.
"""
from datetime import date, timedelta
from fractions import Fraction

from . import db, ratios
from .dates import today
from .money import half_up
from .pos import recipes
from .registry import ApiError, action

SCALES = Fraction(5, 1000)          # kg: what weighing the same bucket twice can differ by


def _day_after(d):
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def baseline(con, before):
    """The latest count taken item by item before the day `before`."""
    return db.one(con, "SELECT * FROM stock_count WHERE count_date < ? AND source = 'counted' "
                       "AND EXISTS (SELECT 1 FROM stock_count_line l WHERE l.count_id = "
                       "stock_count.id) ORDER BY count_date DESC LIMIT 1", (before,))


def _lines(con, count_id):
    return {r["item_id"]: dict(r) for r in db.all_(
        con, "SELECT * FROM stock_count_line WHERE count_id = ?", (count_id,))}


def movements(con, after, upto):
    """What moved between the day after `after` and `upto`, by item, exactly:
    {"in": ..., "filled_in": ..., "filled_out": ..., "sold": ...}."""
    out = {}

    def add(item, key, qty):
        out.setdefault(item, {"in": Fraction(0), "filled_in": Fraction(0),
                              "filled_out": Fraction(0), "sold": Fraction(0)})[key] += qty

    for r in db.all_(con, """
            SELECT rl.item_id, SUM(rl.qty_milli) AS q FROM receipt_line rl
              JOIN receipt r ON r.id = rl.receipt_id
             WHERE r.voided_at IS NULL AND r.received_on > ? AND r.received_on <= ?
             GROUP BY rl.item_id""", (after, upto)):
        add(r["item_id"], "in", Fraction(r["q"], 1000))
    for r in db.all_(con, """
            SELECT mix_id, SUM(grams) AS g FROM bucket_fill
             WHERE voided_at IS NULL AND filled_on > ? AND filled_on <= ?
             GROUP BY mix_id""", (after, upto)):
        add(r["mix_id"], "filled_in", Fraction(r["g"], 1000))
    for r in db.all_(con, """
            SELECT l.item_id, SUM(l.grams) AS g FROM bucket_fill_line l
              JOIN bucket_fill f ON f.id = l.fill_id
             WHERE f.voided_at IS NULL AND f.filled_on > ? AND f.filled_on <= ?
             GROUP BY l.item_id""", (after, upto)):
        add(r["item_id"], "filled_out", Fraction(r["g"], 1000))
    used, no_recipe, not_linked = recipes.usage(con, _day_after(after), upto)
    for item, q in used.items():
        add(item, "sold", q)
    # foil, coal and the like: the hookahs sold, by the ratio learnt before
    for item, q in ratios.used(con, after, upto).items():
        add(item, "sold", q)
    return out, no_recipe, not_linked


def drying(con):
    v = db.setting(con, "drying_pct")
    return Fraction(str(v)) if v not in (None, "") else Fraction(0)


def view(con, count_date=None):
    """Should be against counted at `count_date` — or, with no count that day,
    should be on the shelf at the end of today — from the count before it."""
    upto = count_date or today()
    base = baseline(con, upto)
    if not base:
        return None
    here = db.one(con, "SELECT * FROM stock_count WHERE count_date = ?", (upto,))
    counted = _lines(con, here["id"]) if here else {}
    was = _lines(con, base["id"])
    mov, no_recipe, not_linked = movements(con, base["count_date"], upto)
    items = {r["id"]: dict(r) for r in db.all_(con, """
        SELECT si.*, sc.letter FROM stock_item si JOIN stock_category sc ON sc.id = si.category_id""")}
    allow = drying(con)
    rows = []
    for item_id in set(was) | set(mov) | set(counted):
        it = items[item_id]
        m = mov.get(item_id) or {"in": 0, "filled_in": 0, "filled_out": 0, "sold": 0}
        start = Fraction(was[item_id]["qty_milli"], 1000) if item_id in was else Fraction(0)
        should = start + m["in"] + m["filled_in"] - m["filled_out"] - m["sold"]
        line = counted.get(item_id)
        price = (line or {}).get("price") or it["price"] or (
            items[it["parent_id"]]["price"] if it["parent_id"] in items else 0)
        row = {"item": item_id, "name": it["name"], "letter": it["letter"],
               "parent_id": it["parent_id"], "pack_size": it["pack_size"],
               "was": float(start), "in": float(m["in"]),
               "buckets": float(m["filled_in"] - m["filled_out"]), "sold": float(m["sold"]),
               "should": float(should), "counted": None, "gap": None, "worth": None,
               "flag": False}
        if line is not None:
            have = Fraction(line["qty_milli"], 1000)
            gap = have - should
            row.update(counted=float(have), gap=float(gap), worth=half_up(gap * price))
            if abs(gap) * 1000 < 1 or it["letter"] == "A" and abs(gap) <= SCALES:
                row["flag"] = False
            elif it["letter"] == "A" and gap < 0:   # a bucket dries
                row["flag"] = -gap > should * allow / 100
            else:
                row["flag"] = True
        rows.append(row)
    rows.sort(key=lambda r: (r["letter"], items[r["parent_id"]]["name"] if r["parent_id"] in items
                             else r["name"], r["parent_id"] is not None, r["name"]))
    gaps = [r for r in rows if r["flag"]]
    return {"from": base["count_date"], "to": upto, "counted": bool(here and counted),
            "rows": rows, "short": sum(r["worth"] for r in gaps if r["worth"] < 0),
            "over": sum(r["worth"] for r in gaps if r["worth"] > 0), "flagged": len(gaps),
            "drying": float(allow), "no_recipe": sorted(no_recipe),
            "not_linked": sorted(not_linked)}


@action("drying_pct", guard_pots=False,
        summary=lambda con, body, out: f"Buckets may dry by {out['pct']:g}% between counts")
def _drying_pct(con, body):
    raw = str(body.get("pct") or "").strip().replace("%", "")
    try:
        pct = Fraction(raw) if raw else Fraction(0)
    except (ValueError, ZeroDivisionError):
        raise ApiError("a percentage is a number") from None
    if not 0 <= pct <= 50:
        raise ApiError("between 0 and 50 per cent")
    db.set_setting(con, "drying_pct", str(pct) if pct else None)
    return {"pct": float(pct)}
