"""SambaPOS's own lists: payment types, the menu, inventory items, recipes.

The nightly reset deletes tickets and transactions, not these, so there is no
history to rescue: each snapshot simply brings them up to date, the way
links.refresh does for accounts. They are kept as SambaPOS wrote them, one
row each, so that later steps — card kept apart from cash, recipes, the menu
on the TV — find them waiting rather than starting from nothing.
"""
import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from .. import db
from ..money import NOTE

# which SambaPOS table each kind comes from
KINDS = {
    "payment_type": "PaymentTypes",
    "menu_item": "MenuItems",
    "menu_portion": "MenuItemPortions",
    "menu_price": "MenuItemPrices",
    "inventory_item": "InventoryItems",
    "recipe": "Recipes",
    "recipe_item": "RecipeItems",
}


def _plain(v):
    if isinstance(v, Decimal):
        return format(v.normalize(), "f")          # 5000.00 -> "5000", 25.50 -> "25.5"
    if isinstance(v, datetime):
        return v.isoformat(sep=" ")
    return v


def refresh(con, tables, at):
    """Bring each list up to date from a snapshot made at `at`. A list the
    snapshot does not have is left as it was; an older snapshot than the
    newest one used changes nothing."""
    last = db.setting(con, "sambapos_catalog_at")
    if last and at < last:
        return
    touched = False
    for kind, table in KINDS.items():
        rows = tables.get(table) or []
        if not rows:
            continue
        touched = True
        for r in rows:
            data = {k: _plain(v) for k, v in r.items()}
            con.execute(
                "INSERT INTO pos_catalog(kind, pos_id, name, data, seen_at, gone) "
                "VALUES (?,?,?,?,?,0) ON CONFLICT(kind, pos_id) DO UPDATE SET "
                "name = excluded.name, data = excluded.data, seen_at = excluded.seen_at, "
                "gone = 0",
                (kind, r["Id"], r.get("Name"), json.dumps(data, ensure_ascii=False), at))
        marks = ",".join("?" * len(rows))
        con.execute(f"UPDATE pos_catalog SET gone = 1 WHERE kind = ? AND pos_id NOT IN ({marks})",
                    [kind] + [r["Id"] for r in rows])
    if touched:
        db.set_setting(con, "sambapos_catalog_at", at)


def counts(con):
    """How much of each list is kept, for Setup."""
    return {r["kind"]: r["n"] for r in db.all_(
        con, "SELECT kind, COUNT(*) AS n FROM pos_catalog WHERE gone = 0 GROUP BY kind")}


def _whole(v):
    try:
        return int(Decimal(str(v)))
    except Exception:                                          # noqa: BLE001
        return None


def menu(con, nights=30):
    """The menu as SambaPOS has it now: groups, items, portions and prices,
    with how many of each item sold over the last `nights` nights kept, and
    the prices that are not a multiple of the smallest note."""
    portions = defaultdict(list)
    for p in rows(con, "menu_portion"):
        if not p["_gone"]:
            portions[p.get("MenuItemId")].append(p)
    prices = defaultdict(list)
    for p in rows(con, "menu_price"):
        if not p["_gone"]:
            prices[p.get("MenuItemPortionId")].append(p)
    last = db.scalar(con, "SELECT MAX(night) FROM pos_period", default=None)
    sold = {}
    if last:
        since = (date.fromisoformat(last) - timedelta(days=nights - 1)).isoformat()
        sold = {r["item"]: r["qty"] / 1000 for r in db.all_(con, """
            SELECT o.item, SUM(o.qty_milli) AS qty FROM pos_order o
              JOIN pos_ticket t ON t.id = o.ticket_id
              JOIN pos_period p ON p.id = t.period_id
             WHERE p.night >= ? GROUP BY o.item""", (since,))}
    groups, odd = defaultdict(list), []
    for it in rows(con, "menu_item"):
        if it["_gone"]:
            continue
        name = it.get("Name") or f"item {it['Id']}"
        ports = []
        for p in sorted(portions[it["Id"]], key=lambda p: p["Id"]):
            for pr in prices[p["Id"]] or [{}]:
                price = _whole(pr.get("Price")) if pr else None
                ports.append({"id": p["Id"], "name": p.get("Name"), "price": price,
                              "tag": pr.get("PriceTag") or None})
                # a price below the smallest note is a price per gram or per
                # piece, paid in multiples; only a whole price can need change
                # nobody has
                if price and price >= NOTE and price % NOTE:
                    odd.append({"item": name, "portion": p.get("Name"), "price": price})
        groups[it.get("GroupCode") or ""].append(
            {"id": it["Id"], "name": name, "barcode": it.get("Barcode") or None,
             "portions": ports, "sold": sold.get(name, 0)})
    return {"groups": [{"name": g, "items": sorted(v, key=lambda i: -i["sold"])}
                       for g, v in sorted(groups.items(), key=lambda kv: kv[0])],
            "items": sum(len(v) for v in groups.values()), "odd": odd,
            "nights": nights if last else 0,
            "at": db.setting(con, "sambapos_catalog_at")}


def rows(con, kind):
    return [{**json.loads(r["data"]), "_gone": bool(r["gone"])} for r in db.all_(
        con, "SELECT data, gone FROM pos_catalog WHERE kind = ? ORDER BY pos_id", (kind,))]
