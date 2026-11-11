"""Things used with each hookah — foil, coal, filters — by a ratio learnt
between counts.

Nobody writes down each roll of foil or box of coal opened, and they are
counted roughly, with fractions. Between two counts, what was used is the
count before, plus what receipts brought in, less the count after; the
hookahs SambaPOS sold in between, divided by it, is hookahs to each one
counted (a roll, a carton). The last three pairs of counts pooled are the
ratio, and from then on the nights' hookahs divided by it are roughly what
they used. A pair well below the ones before it means more went than the
sales explain.

What a hookah is comes from SambaPOS's recipes: an order whose recipe takes
tobacco or a mix (pos/recipes.py), so it needs the tobacco linked first.
"""
from datetime import date, timedelta
from fractions import Fraction

from . import db
from .pos import recipes
from .registry import ApiError, action

POOL = 3                     # pairs of counts pooled into the ratio
DROP = Fraction(8, 10)       # a pair under 80% of the ratio before it is pointed out
NIGHTS = 30                  # nights the "a night" figure is taken over


def _day_after(d):
    return (date.fromisoformat(d) + timedelta(days=1)).isoformat()


def items(con):
    return [dict(r) for r in db.all_(con, """
        SELECT si.*, sc.letter FROM stock_item si JOIN stock_category sc ON sc.id = si.category_id
         WHERE si.per_hookah = 1 ORDER BY si.name""")]


def pairs(con, item_id):
    """Each pair of counts in a row that both counted the item: what was used
    between them, the hookahs sold, and hookahs to each one used."""
    counts = [dict(r) for r in db.all_(con, """
        SELECT c.count_date, l.qty_milli FROM stock_count c
          JOIN stock_count_line l ON l.count_id = c.id AND l.item_id = ?
         WHERE c.source = 'counted' ORDER BY c.count_date""", (item_id,))]
    out = []
    for a, b in zip(counts, counts[1:]):
        came = db.scalar(con, """
            SELECT COALESCE(SUM(rl.qty_milli), 0) FROM receipt_line rl
              JOIN receipt r ON r.id = rl.receipt_id
             WHERE rl.item_id = ? AND r.voided_at IS NULL
               AND r.received_on > ? AND r.received_on <= ?""",
                         (item_id, a["count_date"], b["count_date"]))
        used = Fraction(a["qty_milli"] + came - b["qty_milli"], 1000)
        sold = recipes.hookahs(con, _day_after(a["count_date"]), b["count_date"])
        out.append({"from": a["count_date"], "to": b["count_date"], "used": used,
                    "hookahs": sold,
                    "ratio": sold / used if sold and used > 0 else None})
    return out


def learnt(con, item_id, upto=None):
    """Hookahs to each one, from the last pairs of counts ending by `upto`."""
    ps = [p for p in pairs(con, item_id) if p["ratio"] and (upto is None or p["to"] <= upto)]
    last = ps[-POOL:]
    if not last:
        return None
    return sum(p["hookahs"] for p in last) / sum(p["used"] for p in last)


def used(con, after, upto):
    """What the ratio items took between the day after `after` and `upto`,
    by the ratio learnt before it: {item id: exact quantity}."""
    sold = None
    out = {}
    for it in items(con):
        r = learnt(con, it["id"], after)
        if not r:
            continue
        if sold is None:
            sold = recipes.hookahs(con, _day_after(after), upto)
            if not sold:
                return {}
        out[it["id"]] = sold / r
    return out


def view(con):
    """The ratio items, each with its ratio, roughly what a night uses, and the
    pairs of counts it was learnt from."""
    last = db.scalar(con, "SELECT MAX(night) FROM pos_period", default=None)
    nights = db.scalar(con, "SELECT COUNT(DISTINCT night) FROM pos_period WHERE night > ?",
                       ((date.fromisoformat(last) - timedelta(days=NIGHTS)).isoformat(),)) \
        if last else 0
    a_night = None
    if last and nights:
        sold = recipes.hookahs(con, (date.fromisoformat(last) - timedelta(days=NIGHTS - 1))
                               .isoformat(), last)
        a_night = sold / nights if sold is not None else None
    out = []
    for it in items(con):
        ps = pairs(con, it["id"])
        r = learnt(con, it["id"])
        good = [p for p in ps if p["ratio"]]
        before = learnt(con, it["id"], good[-2]["to"]) if len(good) >= 2 else None
        out.append({
            "item": it["id"], "name": it["name"], "letter": it["letter"],
            "pack_size": it["pack_size"],
            "ratio": float(r) if r else None,
            "a_night": float(a_night / r) if r and a_night else None,
            "dropped": bool(before and good[-1]["ratio"] < before * DROP),
            "pairs": [{"from": p["from"], "to": p["to"], "used": float(p["used"]),
                       "hookahs": float(p["hookahs"]) if p["hookahs"] is not None else None,
                       "ratio": float(p["ratio"]) if p["ratio"] else None}
                      for p in ps[-6:]]})
    return {"items": out, "hookahs_known": recipes.tobacco_linked(con),
            "a_night": float(a_night) if a_night else None}


@action("per_hookah", guard_pots=False,
        summary=lambda con, body, out: (f"{out['name']} is now used with each hookah"
                                        if out["on"] else
                                        f"{out['name']} is no longer counted by hookahs"))
def _per_hookah(con, body):
    it = db.one(con, "SELECT si.*, sc.letter FROM stock_item si JOIN stock_category sc "
                     "ON sc.id = si.category_id WHERE si.id = ?", (int(body["id"]),))
    if not it:
        raise ApiError("no such stock item")
    on = bool(body.get("on"))
    if on and it["letter"] in ("A", "B"):
        raise ApiError("tobacco goes by recipe, not by a ratio")
    con.execute("UPDATE stock_item SET per_hookah = ? WHERE id = ?", (1 if on else 0, it["id"]))
    return {"name": it["name"], "on": on}
