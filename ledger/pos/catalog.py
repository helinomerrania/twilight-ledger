"""SambaPOS's own lists: payment types, the menu, inventory items, recipes.

The nightly reset deletes tickets and transactions, not these, so there is no
history to rescue: each snapshot simply brings them up to date, the way
links.refresh does for accounts. They are kept as SambaPOS wrote them, one
row each, so that later steps — card kept apart from cash, recipes, the menu
on the TV — find them waiting rather than starting from nothing.
"""
import json
from datetime import datetime
from decimal import Decimal

from .. import db

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


def rows(con, kind):
    return [{**json.loads(r["data"]), "_gone": bool(r["gone"])} for r in db.all_(
        con, "SELECT data, gone FROM pos_catalog WHERE kind = ? ORDER BY pos_id", (kind,))]
