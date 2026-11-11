"""What each night's sales took off the shelves, by SambaPOS's own recipes.

SambaPOS already says what one of each menu item uses: a recipe per portion,
naming its own inventory items — so many grams of a tobacco, one tea bag, one
can. Those lists come in with every snapshot (catalog.py). What SambaPOS does
not know is which of the stock items here each inventory item is, so that is
the one thing set here, once, item by item (pos_stock_link). After that every
kept night takes stock off by itself: each order that used stock — a void
does not, a gift does — times its recipe.

Quantities come out in each stock item's own quantity, as counted: kilos for
tobacco and mixes, packages for the rest. "How many make one" turns SambaPOS's
unit into ours: 1000 grams to a kilo, 24 cans to a package of 24. Left blank,
it is worked out from the units: grams into kilos, pieces into the item's
package.

A head of tobacco is filled by hand, the same for every flavour, so Setup can
say how many grams a head is, in place of what each SambaPOS recipe says.
"""
from collections import defaultdict
from fractions import Fraction

from .. import db
from ..money import half_up
from ..registry import ApiError, action
from . import catalog

GRAMS = {"g", "gr", "grs", "gm", "gram", "grams", "گرام", "گرم", "غرام", "غم"}
KILOS = {"kg", "kgs", "kilo", "kilos", "کیلۆ", "کیلو", "كيلو"}
WEIGHED = ("A", "B")                     # stock counted in kilos


def _unit(inv):
    u = str(inv.get("BaseUnit") or "").strip().lower()
    return "g" if u in GRAMS else "kg" if u in KILOS else u


def _items(con):
    return {r["id"]: dict(r) for r in db.all_(con, """
        SELECT si.*, sc.letter FROM stock_item si
          JOIN stock_category sc ON sc.id = si.category_id""")}


def per_default(inv, item):
    """How many of SambaPOS's unit make one of the stock item's, when Setup
    does not say: None when it cannot be worked out."""
    unit = _unit(inv)
    if item["letter"] in WEIGHED:
        return 1000 if unit == "g" else 1 if unit == "kg" else None
    if unit in ("g", "kg"):
        return None
    return int(item["pack_size"] or 1) if item["letter"] != "E" else None


def links(con):
    return {r["pos_id"]: dict(r) for r in db.all_(con, "SELECT * FROM pos_stock_link")}


def head_grams(con):
    v = db.setting(con, "head_grams")
    return int(v) if v else None


def _recipes(con):
    """{portion id: [(inventory id, quantity)]} from SambaPOS's recipes."""
    by_recipe = defaultdict(list)
    for ri in catalog.rows(con, "recipe_item"):
        if not ri["_gone"]:
            try:
                q = Fraction(str(ri.get("Quantity") or 0))
            except ValueError:
                continue
            by_recipe[ri.get("RecipeId")].append((ri.get("InventoryItem_Id"), q))
    out = defaultdict(list)
    for r in catalog.rows(con, "recipe"):
        if not r["_gone"]:
            out[r.get("PortionId")].extend(by_recipe.get(r["Id"], []))
    return out


def _portions(con):
    """{(menu item id, portion name): portion id}, and menu item ids by name
    (a name kept by more than one, the one still on the menu)."""
    portions = {(p.get("MenuItemId"), p.get("Name")): p["Id"]
                for p in catalog.rows(con, "menu_portion")}
    ids = {}
    for m in sorted(catalog.rows(con, "menu_item"), key=lambda m: not m["_gone"]):
        ids[m.get("Name")] = m["Id"]
    return portions, ids


def _orders(con, since, until):
    """Each order of the kept nights from `since` to `until` that took stock,
    with its quantity and its recipe's lines (None when it has no recipe)."""
    recipes = _recipes(con)
    portions, ids = _portions(con)
    for o in db.all_(con, """
            SELECT o.item, o.portion, o.menu_id, o.qty_milli, o.counted, o.used
              FROM pos_order o JOIN pos_ticket t ON t.id = o.ticket_id
              JOIN pos_period p ON p.id = t.period_id
             WHERE p.night BETWEEN ? AND ?""", (since, until)):
        if not (o["used"] if o["used"] is not None else o["counted"]):
            continue
        menu_id = o["menu_id"] or ids.get(o["item"])
        lines = recipes.get(portions.get((menu_id, o["portion"] or "Normal")))
        if lines is None and o["portion"] is None:
            # an order that names no portion: the item's only one
            mine = [pid for (mid, _), pid in portions.items() if mid == menu_id]
            lines = recipes.get(mine[0]) if len(mine) == 1 else None
        yield o, Fraction(o["qty_milli"], 1000), lines or None


def _placed(con):
    """For each SambaPOS inventory item: the stock item here and how many of
    SambaPOS's units make one of it, or (None, None)."""
    inv = {i["Id"]: i for i in catalog.rows(con, "inventory_item")}
    link = links(con)
    items = _items(con)

    def place(inv_id):
        ln = link.get(inv_id) or {}
        item = items.get(ln.get("item_id"))
        i = inv.get(inv_id) or {}
        per = ln.get("per") or (per_default(i, item) if item else None)
        return (item, per, i) if item and per else (None, None, i)
    return place


def usage(con, since, until):
    """What the kept nights from `since` to `until` took off the shelves:
    {item id: exact quantity}, and what could not be placed: menu items with
    no recipe, and inventory items not linked to stock here, by how many."""
    place = _placed(con)
    head = head_grams(con)
    used = defaultdict(Fraction)
    no_recipe, not_linked = defaultdict(Fraction), defaultdict(Fraction)
    for o, qty, lines in _orders(con, since, until):
        if not lines:
            no_recipe[o["item"]] += qty
            continue
        for inv_id, q in lines:
            item, per, i = place(inv_id)
            if not item:
                not_linked[i.get("Name") or f"item {inv_id}"] += qty
                continue
            if head and item["letter"] in WEIGHED and _unit(i) == "g":
                q = Fraction(head)
            used[item["id"]] += qty * q / per
    return dict(used), dict(no_recipe), dict(not_linked)


def tobacco_linked(con):
    """Whether any of SambaPOS's inventory items is a tobacco or a mix here."""
    return bool(db.scalar(con, """
        SELECT COUNT(*) FROM pos_stock_link l JOIN stock_item si ON si.id = l.item_id
          JOIN stock_category sc ON sc.id = si.category_id WHERE sc.letter IN ('A', 'B')"""))


def hookahs(con, since, until):
    """How many hookahs the kept nights from `since` to `until` sold: orders
    whose recipe takes tobacco or a mix. None when no tobacco is linked yet,
    so nothing could be known."""
    if not tobacco_linked(con):
        return None
    place = _placed(con)
    n = Fraction(0)
    for _, qty, lines in _orders(con, since, until):
        if lines and any((place(inv_id)[0] or {}).get("letter") in WEIGHED for inv_id, _ in lines):
            n += qty
    return n


def _unit_costs(con):
    """What one of each stock item costs, in its own quantity: a kilo of
    tobacco or of a mix (whose price follows its fills), a package of the
    rest. A flavour costs what its brand does unless it says otherwise."""
    items = _items(con)
    return {i["id"]: Fraction(i["price"] or (items[i["parent_id"]]["price"]
                                             if i["parent_id"] in items else 0) or 0)
            for i in items.values()}


def portion_costs(con):
    """What one of each portion costs to make, by its recipe: {portion id:
    exact dinar}, or None where some of it is not linked here or not priced."""
    place = _placed(con)
    head = head_grams(con)
    unit = _unit_costs(con)
    out = {}
    for pid, lines in _recipes(con).items():
        if not lines:
            continue
        total = Fraction(0)
        for inv_id, q in lines:
            item, per, i = place(inv_id)
            if not item or not unit.get(item["id"]):
                total = None
                break
            if head and item["letter"] in WEIGHED and _unit(i) == "g":
                q = Fraction(head)
            total += q / per * unit[item["id"]]
        out[pid] = total
    return out


def costed(con, sold):
    """What sold (archive.items), each with what one costs to make, what all
    that took stock cost — a gift costs as much as a sale — and what it made."""
    costs = portion_costs(con)
    portions, ids = _portions(con)
    out = []
    for s in sold:
        menu_id = ids.get(s["item"])
        pid = portions.get((menu_id, s["portion"] or "Normal"))
        if pid is None:
            mine = [p for (m, _), p in portions.items() if m == menu_id]
            pid = mine[0] if len(mine) == 1 else None
        one = costs.get(pid)
        cost = half_up(one * Fraction(str(s["took"]))) if one is not None else None
        out.append({**s, "one": half_up(one) if one is not None else None, "cost": cost,
                    "makes": s["value"] - cost if cost is not None else None})
    return out


def view(con):
    """SambaPOS's inventory items with what each is here, and the menu items
    that have no recipe, for Setup."""
    recipes = _recipes(con)
    count = defaultdict(int)
    for lines in recipes.values():
        for inv_id, _ in lines:
            count[inv_id] += 1
    link = links(con)
    items = _items(con)
    rows = []
    for i in catalog.rows(con, "inventory_item"):
        if i["_gone"]:
            continue
        ln = link.get(i["Id"]) or {}
        item = items.get(ln.get("item_id"))
        rows.append({"pos_id": i["Id"], "name": i.get("Name"), "unit": i.get("BaseUnit") or "",
                     "group": i.get("GroupCode") or "", "item_id": item["id"] if item else None,
                     "per": ln.get("per"),
                     "per_default": per_default(i, item) if item else None,
                     "recipes": count.get(i["Id"], 0)})
    rows.sort(key=lambda r: (r["group"], r["name"] or ""))
    portions = defaultdict(list)
    for p in catalog.rows(con, "menu_portion"):
        if not p["_gone"]:
            portions[p.get("MenuItemId")].append(p["Id"])
    bare = sorted(m.get("Name") or "" for m in catalog.rows(con, "menu_item")
                  if not m["_gone"] and not any(recipes.get(pid) for pid in portions[m["Id"]]))
    last = db.scalar(con, "SELECT MAX(night) FROM pos_period", default=None)
    took = []
    if last:
        used, _, _ = usage(con, last, last)
        for item_id, q in sorted(used.items(), key=lambda kv: items[kv[0]]["name"]):
            took.append({"item": item_id, "name": items[item_id]["name"],
                         "letter": items[item_id]["letter"], "qty": float(q)})
    return {"inventory": rows, "no_recipe": bare, "head_grams": head_grams(con),
            "last_night": last, "took": took}


def _link_said(con, body, out):
    return f"SambaPOS's {out['name']} is now {out['item'] or 'nothing here'}"


@action("pos_stock_link", guard_pots=False, summary=_link_said)
def _pos_stock_link(con, body):
    """Say which stock item one of SambaPOS's inventory items is here, and
    how many of SambaPOS's units make one of ours."""
    pos_id = int(body["pos_id"])
    inv = next((i for i in catalog.rows(con, "inventory_item") if i["Id"] == pos_id), None)
    if not inv:
        raise ApiError("SambaPOS has no such inventory item")
    have = links(con).get(pos_id) or {"item_id": None, "per": None}
    item_id = have["item_id"]
    if "item_id" in body:
        item_id = int(body["item_id"]) if body.get("item_id") else None
        if item_id and not db.one(con, "SELECT 1 FROM stock_item WHERE id = ?", (item_id,)):
            raise ApiError("no such stock item")
    per = have["per"]
    if "per" in body:
        raw = str(body.get("per") or "").strip().replace(",", "")
        try:
            per = int(raw) if raw else None
        except ValueError:
            raise ApiError("how many make one is a whole number") from None
        if per is not None and per < 1:
            raise ApiError("at least one makes one")
    con.execute("INSERT INTO pos_stock_link(pos_id, item_id, per) VALUES (?,?,?) "
                "ON CONFLICT(pos_id) DO UPDATE SET item_id = excluded.item_id, "
                "per = excluded.per", (pos_id, item_id, per))
    name = db.scalar(con, "SELECT name FROM stock_item WHERE id = ?", (item_id,)) if item_id else None
    return {"name": inv.get("Name"), "item": name}


@action("head_grams", guard_pots=False,
        summary=lambda con, body, out: (f"A head is now {out['grams']} g" if out["grams"]
                                        else "A head is as SambaPOS's recipes say"))
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
