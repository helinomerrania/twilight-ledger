"""Filling a bucket: packs of sealed tobacco into one of the house mixes.

A stock move, not money, so nothing is posted. Each tobacco gives up its packs
— so many grams at its price per kilo — and the mix takes the lot. The mix's
price per kilo, which values it at the next count, becomes the blend of what
went in and what was already in the bucket:

    new price = (grams already in x old price + cost of what went in x 1000)
                / (grams already in + grams that went in)

What was already in is known when the full bucket is weighed (the scales,
less the bucket). Unweighed, the bucket is taken to have been empty, so the
price becomes what this batch cost. Expected stock (plan step 3.6) can supply
the remainder later.
"""
from fractions import Fraction

from . import db, queries, stock
from .dates import month_of
from .money import half_up, to_int
from .registry import ApiError, action, clean_date


def _mix(con, mix_id):
    mix = db.one(con, "SELECT si.*, sc.letter FROM stock_item si JOIN stock_category sc "
                      "ON sc.id = si.category_id WHERE si.id = ?", (int(mix_id),))
    if not mix or mix["letter"] != "A":
        raise ApiError("pick one of the weighed mixes")
    return mix


def pack_and_price(con, item):
    """Grams in one pack of a sealed tobacco, and its price per kilo: its own,
    else its brand's, else (for the pack) Setup's usual."""
    brand = db.one(con, "SELECT * FROM stock_item WHERE id = ?",
                   (item["parent_id"],)) if item["parent_id"] else None
    packs = stock.packs_of(dict(item), dict(brand) if brand else None)
    grams = packs["grams"] if packs else \
        stock.conversions(db.setting(con, "conversions", {}))["grams_per_pack"]
    price = item["price"] or (brand["price"] if brand else 0)
    return grams, price


def _lines(con, raw):
    """What went in, as typed: [{item, packs}], one line per tobacco."""
    merged = {}
    for l in raw or []:
        try:
            packs = stock.to_milli(l.get("packs"))
        except (ValueError, ZeroDivisionError):
            raise ApiError("packs are a number") from None
        if packs < 0:
            raise ApiError("packs cannot be less than nothing")
        if packs:
            merged[int(l["item"])] = merged.get(int(l["item"]), 0) + packs
    out = []
    for item_id, packs in merged.items():
        item = db.one(con, "SELECT si.*, sc.letter FROM stock_item si JOIN stock_category sc "
                           "ON sc.id = si.category_id WHERE si.id = ?", (item_id,))
        if not item:
            raise ApiError("no such stock item")
        if item["letter"] != "B":
            raise ApiError(f"only sealed tobacco goes into a mix, not {item['name']}")
        grams_per_pack, price = pack_and_price(con, item)
        exact = Fraction(packs, 1000) * grams_per_pack
        grams = half_up(exact)
        if grams <= 0:
            raise ApiError(f"too little {item['name']} to weigh")
        out.append({"item": item_id, "packs_milli": packs, "grams": grams, "price": price,
                    "exact": exact * price / 1000})
    if not out:
        raise ApiError("say how many packs of which tobacco went in")
    return out


def _fill_said(con, body, out):
    name = db.scalar(con, "SELECT name FROM stock_item WHERE id = ?", (out["mix"],))
    return f"Filled {name}: {out['grams']:,} g"


@action("bucket_fill", guard_pots=False, summary=_fill_said)
def _bucket_fill(con, body):
    """Fill a mix's bucket from packs of sealed tobacco, and blend its price."""
    mix = _mix(con, body.get("mix") or 0)
    on = clean_date(body.get("on"))
    if queries.is_closed(con, month_of(on)):
        raise ApiError("that month is closed")
    lines = _lines(con, body.get("lines"))
    grams = sum(l["grams"] for l in lines)
    exact = sum(l["exact"] for l in lines)
    value = half_up(exact)

    net = None
    gross = body.get("gross_grams")
    if gross not in (None, ""):
        gross = to_int(gross, "gross_grams")
        tare = db.scalar(con, "SELECT grams FROM tare WHERE id = ?",
                         (body["tare_id"],)) if body.get("tare_id") else 0
        net = gross - tare
        if net <= 0:
            raise ApiError("the full bucket weighs no more than the bucket")
    before = max(net - grams, 0) if net is not None else 0
    p0 = mix["price"] or 0
    p1 = half_up((before * p0 + exact * 1000) / (before + grams))

    cur = con.execute(
        "INSERT INTO bucket_fill(mix_id, filled_on, grams, value, net_grams, price_before, "
        "price_after) VALUES (?,?,?,?,?,?,?)", (mix["id"], on, grams, value, net, p0, p1))
    fid = cur.lastrowid
    for l in lines:
        con.execute("INSERT INTO bucket_fill_line(fill_id, item_id, packs_milli, grams, price, "
                    "value) VALUES (?,?,?,?,?,?)",
                    (fid, l["item"], l["packs_milli"], l["grams"], l["price"],
                     half_up(l["exact"])))
    con.execute("UPDATE stock_item SET price = ? WHERE id = ?", (p1, mix["id"]))
    if body.get("usual"):
        con.execute("DELETE FROM mix_usual WHERE mix_id = ?", (mix["id"],))
        for n, l in enumerate(lines):
            con.execute("INSERT INTO mix_usual(mix_id, item_id, packs_milli, sort) "
                        "VALUES (?,?,?,?)", (mix["id"], l["item"], l["packs_milli"], n))
    return {"id": fid, "mix": mix["id"], "grams": grams, "value": value,
            "before_grams": before if net is not None else None,
            "price_before": p0, "price_after": p1}


@action("bucket_fill_delete", guard_pots=False,
        summary=lambda con, body, out: f"Deleted a fill of {out['name']}")
def _bucket_fill_delete(con, body):
    """Take a fill back. The mix's price goes back to what it was, unless it
    has been changed since."""
    f = db.one(con, "SELECT f.*, si.name, si.price AS now FROM bucket_fill f "
                    "JOIN stock_item si ON si.id = f.mix_id WHERE f.id = ?", (int(body["id"]),))
    if not f or f["voided_at"]:
        raise ApiError("that fill is not in the books")
    if queries.is_closed(con, month_of(f["filled_on"])):
        raise ApiError("that month is closed")
    con.execute("UPDATE bucket_fill SET voided_at = datetime('now') WHERE id = ?", (f["id"],))
    if f["now"] == f["price_after"]:
        con.execute("UPDATE stock_item SET price = ? WHERE id = ?",
                    (f["price_before"], f["mix_id"]))
    return {"id": f["id"], "name": f["name"]}


def view(con, limit=40):
    """The mixes with their usual batch, and the latest fills."""
    usual = {}
    for u in db.all_(con, "SELECT * FROM mix_usual ORDER BY mix_id, sort"):
        usual.setdefault(u["mix_id"], []).append(
            {"item": u["item_id"], "packs": u["packs_milli"] / 1000})
    mixes = [{"id": m["id"], "name": m["name"], "price": m["price"],
              "usual": usual.get(m["id"], [])}
             for m in db.all_(con, """
                SELECT si.* FROM stock_item si JOIN stock_category sc ON sc.id = si.category_id
                 WHERE sc.letter = 'A' AND si.active = 1 ORDER BY si.sort, si.name""")]
    fills = [dict(f) for f in db.all_(con, """
        SELECT f.id, f.mix_id, si.name AS mix, f.filled_on, f.grams, f.value, f.net_grams,
               f.price_before, f.price_after
          FROM bucket_fill f JOIN stock_item si ON si.id = f.mix_id
         WHERE f.voided_at IS NULL ORDER BY f.filled_on DESC, f.id DESC LIMIT ?""", (limit,))]
    closed = {m for m in queries.months(con) if queries.is_closed(con, m)}
    for f in fills:
        f["locked"] = f["filled_on"][:7] in closed
        f["lines"] = [dict(l) for l in db.all_(con, """
            SELECT l.item_id AS item, si.name, l.packs_milli, l.grams, l.value
              FROM bucket_fill_line l JOIN stock_item si ON si.id = l.item_id
             WHERE l.fill_id = ? ORDER BY si.name""", (f["id"],))]
    return {"mixes": mixes, "fills": fills}
