"""What each night's sales took off the shelves.

Each SambaPOS menu item is given, here, the one stock item it takes from and
how much of it: a hookah takes a head from its bucket, a can of drink takes
one can. A menu item can also take nothing (a service charge), and one not
yet given anything is listed until it is. After that every kept night takes
stock off by itself: each order that took stock — SambaPOS says so on each
one: a gift does, a void does not — times what its menu item takes.

How much is said the way it is used: heads of tobacco, buckets of ice cream,
pieces of everything else. A head is filled by hand, the same for every
flavour, so its grams are one setting. What comes out is each stock item's own
quantity, as counted: kilos for tobacco and mixes, cartons for ice cream,
packages for the rest (so a can is 1/24 of a package of 24).

A menu item is linked by SambaPOS's number for it, which does not change when
it is renamed; orders kept before the number was kept are matched by name.
"""
from collections import defaultdict
from fractions import Fraction

from .. import db, stock
from ..money import half_up
from ..registry import ApiError, action
from . import catalog

WEIGHED = ("A", "B")                 # tobacco and mixes, counted in kilos
UNITS = {"A": ("head", "heads"), "B": ("head", "heads"), "E": ("bucket", "buckets")}


def unit_of(letter):
    """How one of what a menu item takes is said: [one, many]."""
    return list(UNITS.get(letter, ("piece", "pieces")))


def head_grams(con):
    v = db.setting(con, "head_grams")
    return int(v) if v else None


def _items(con):
    return {r["id"]: dict(r) for r in db.all_(con, """
        SELECT si.*, sc.letter FROM stock_item si
          JOIN stock_category sc ON sc.id = si.category_id""")}


def uses(con):
    """{menu id: {"item_id", "amount"}}; item_id None means it takes nothing."""
    return {r["menu_id"]: {"item_id": r["item_id"], "amount": Fraction(r["amount_milli"], 1000)}
            for r in db.all_(con, "SELECT * FROM menu_use")}


def _one(con, item, items, head):
    """One head, bucket or piece of a stock item, in its own quantity: None
    when that cannot be known (a head with no grams set)."""
    if item["letter"] in WEIGHED:
        return Fraction(head, 1000) if head else None
    if item["letter"] == "E":
        return Fraction(1, stock.conversions(db.setting(con, "conversions", {}))
                        ["buckets_per_carton"])
    brand = items.get(item["parent_id"])
    per = item["pack_size"] or (brand["pack_size"] if brand else None) or 1
    return Fraction(1, int(per))


def _menu_ids(con):
    """SambaPOS's menu item numbers by name; a name kept by more than one,
    the one still on the menu."""
    ids = {}
    for m in sorted(catalog.rows(con, "menu_item"), key=lambda m: not m["_gone"]):
        ids.setdefault(m.get("Name"), m["Id"])
    return ids


def _orders(con, since, until):
    """Each order of the kept nights from `since` to `until` that took stock,
    with its quantity and its menu item's number."""
    ids = _menu_ids(con)
    for o in db.all_(con, """
            SELECT o.item, o.menu_id, o.qty_milli, o.counted, o.used
              FROM pos_order o JOIN pos_ticket t ON t.id = o.ticket_id
              JOIN pos_period p ON p.id = t.period_id
             WHERE p.night BETWEEN ? AND ?""", (since, until)):
        if o["used"] if o["used"] is not None else o["counted"]:
            yield o, Fraction(o["qty_milli"], 1000), o["menu_id"] or ids.get(o["item"])


def usage(con, since, until):
    """What the kept nights from `since` to `until` took off the shelves:
    {item id: exact quantity}; the menu items sold that have not been given
    what they take, by how many; and how many heads were sold while the
    grams in a head were not set."""
    use = uses(con)
    items = _items(con)
    head = head_grams(con)
    used, not_set = defaultdict(Fraction), defaultdict(Fraction)
    heads_unknown = Fraction(0)
    for o, qty, menu_id in _orders(con, since, until):
        u = use.get(menu_id)
        if u is None:
            not_set[o["item"]] += qty
            continue
        item = items.get(u["item_id"])
        if item is None:
            continue                                   # it takes nothing
        one = _one(con, item, items, head)
        if one is None:
            heads_unknown += qty * u["amount"]
            continue
        used[item["id"]] += qty * u["amount"] * one
    return dict(used), dict(not_set), heads_unknown


def tobacco_set(con):
    """Whether any menu item has been given a tobacco or a mix to take."""
    return bool(db.scalar(con, """
        SELECT COUNT(*) FROM menu_use u JOIN stock_item si ON si.id = u.item_id
          JOIN stock_category sc ON sc.id = si.category_id WHERE sc.letter IN ('A', 'B')"""))


def hookahs(con, since, until):
    """How many hookahs the kept nights from `since` to `until` sold: orders
    of a menu item that takes tobacco or a mix. None until one does."""
    if not tobacco_set(con):
        return None
    use = uses(con)
    items = _items(con)
    n = Fraction(0)
    for _, qty, menu_id in _orders(con, since, until):
        item = items.get((use.get(menu_id) or {}).get("item_id"))
        if item and item["letter"] in WEIGHED:
            n += qty
    return n


def _unit_costs(items):
    """What one of each stock item costs in its own quantity: a kilo of
    tobacco or of a mix (whose price follows its fills), a carton of ice
    cream, a package of the rest. A flavour costs what its brand does unless
    it says otherwise."""
    return {i["id"]: Fraction(i["price"] or (items[i["parent_id"]]["price"]
                                             if i["parent_id"] in items else 0) or 0)
            for i in items.values()}


def costs(con):
    """What one of each menu item costs to make: {menu id: exact dinar}; 0 for
    one that takes nothing, None where it cannot be known yet."""
    items = _items(con)
    unit = _unit_costs(items)
    head = head_grams(con)
    out = {}
    for menu_id, u in uses(con).items():
        item = items.get(u["item_id"])
        if item is None:
            out[menu_id] = Fraction(0)
            continue
        one = _one(con, item, items, head)
        out[menu_id] = u["amount"] * one * unit[item["id"]] \
            if one is not None and unit[item["id"]] else None
    return out


def costed(con, sold):
    """What sold (archive.items), each with what one costs to make, what all
    that took stock cost — a gift costs as much as a sale — and what it made."""
    each = costs(con)
    ids = _menu_ids(con)
    out = []
    for s in sold:
        one = each.get(ids.get(s["item"]))
        cost = half_up(one * Fraction(str(s["took"]))) if one is not None else None
        out.append({**s, "one": half_up(one) if one is not None else None, "cost": cost,
                    "makes": s["value"] - cost if cost is not None else None})
    return out


def view(con):
    """Every menu item with what it takes, for Setup; and what the last night
    kept took."""
    use = uses(con)
    items = _items(con)
    rows = []
    for m in catalog.rows(con, "menu_item"):
        if m["_gone"]:
            continue
        u = use.get(m["Id"])
        item = items.get(u["item_id"]) if u else None
        rows.append({"menu_id": m["Id"], "name": m.get("Name") or f"item {m['Id']}",
                     "group": m.get("GroupCode") or "",
                     "set": u is not None, "item_id": item["id"] if item else None,
                     "amount": float(u["amount"]) if u else 1,
                     "unit": unit_of(item["letter"]) if item else None})
    rows.sort(key=lambda r: (r["group"], r["name"]))
    last = db.scalar(con, "SELECT MAX(night) FROM pos_period", default=None)
    took = []
    if last:
        used, _, _ = usage(con, last, last)
        for item_id, q in sorted(used.items(), key=lambda kv: items[kv[0]]["name"]):
            it = items[item_id]
            took.append({"item": item_id, "name": it["name"], "letter": it["letter"],
                         "pack_size": it["pack_size"], "qty": float(q)})
    return {"menu": rows, "set": sum(1 for r in rows if r["set"]),
            "head_grams": head_grams(con), "last_night": last, "took": took}


def _use_said(con, body, out):
    if out["takes"] is None:
        return f"{out['menu']} is not set"
    return f"{out['menu']} takes {out['takes'] or 'nothing'}"


@action("menu_use", guard_pots=False, summary=_use_said)
def _menu_use(con, body):
    """Say what one of a menu item takes: a stock item (`item_id`), nothing
    ("0"), or not set yet (blank); and how much (`amount`)."""
    menu_id = int(body["menu_id"])
    m = next((r for r in catalog.rows(con, "menu_item") if r["Id"] == menu_id), None)
    if not m:
        raise ApiError("SambaPOS has no such menu item")
    have = uses(con).get(menu_id)
    if "item_id" in body:
        raw = str(body.get("item_id") or "").strip()
        if raw == "":
            con.execute("DELETE FROM menu_use WHERE menu_id = ?", (menu_id,))
            return {"menu": m.get("Name"), "takes": None}
        item_id = int(raw) or None
        if item_id and not db.one(con, "SELECT 1 FROM stock_item WHERE id = ?", (item_id,)):
            raise ApiError("no such stock item")
    else:
        item_id = have["item_id"] if have else None
    amount = have["amount"] if have else Fraction(1)
    if "amount" in body:
        raw = str(body.get("amount") or "").strip()
        try:
            amount = Fraction(stock.to_milli(raw), 1000) if raw else Fraction(1)
        except (ValueError, ZeroDivisionError):
            raise ApiError("how much is a number") from None
        if amount <= 0:
            raise ApiError("it takes more than nothing; or choose “takes nothing”")
    con.execute("INSERT INTO menu_use(menu_id, item_id, amount_milli) VALUES (?,?,?) "
                "ON CONFLICT(menu_id) DO UPDATE SET item_id = excluded.item_id, "
                "amount_milli = excluded.amount_milli",
                (menu_id, item_id, half_up(amount * 1000)))
    name = db.scalar(con, "SELECT name FROM stock_item WHERE id = ?", (item_id,)) \
        if item_id else ""
    return {"menu": m.get("Name"), "takes": name}


@action("head_grams", guard_pots=False,
        summary=lambda con, body, out: (f"A head is now {out['grams']} g" if out["grams"]
                                        else "Grams in a head cleared"))
def _head_grams(con, body):
    raw = str(body.get("grams") or "").strip()
    try:
        grams = int(raw) if raw else None
    except ValueError:
        raise ApiError("grams are a whole number") from None
    if grams is not None and not 1 <= grams <= 500:
        raise ApiError("a head is between 1 and 500 grams")
    db.set_setting(con, "head_grams", grams)
    return {"grams": grams}
