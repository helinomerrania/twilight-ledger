"""Changing Setup: who is paid, who is owed, what is stocked and what it costs.

Nothing here deletes. Retiring a supplier, a member of staff or a stock item
keeps every entry that ever mentioned it and simply stops offering it.

And nothing here can reach a closed month. A salary or the rent applies from
the first month that is still open; a new price values the next stock count.
"""
import json
import re

from . import backup, db, money, post, queries, stock
from .dates import month_of, next_month, today
from .money import to_int
from .registry import ApiError, action, name_of

_WORDS = {
    "account_add": "Added {name}", "account_rename": "Renamed to {name}",
    "account_active": "{verb} {who}",
    "set_share": "Changed {who}'s share to {share}%",
    "set_salary": "Changed {who}'s salary to {amount}",
    "fixed_set": "Set {name} to {amount} a month",
    "fixed_remove": "Stopped charging {name}",
    "list_add": "Added {value} to a list", "list_remove": "Removed {value} from a list",
    "item_add": "Added stock item {name}", "item_update": "Changed stock item {who}",
    "tare_set": "Changed a bucket weight", "business_set": "Changed the business details",
    "conversions_set": "Changed the unit conversions",
    "elec_factors_set": "Changed the electricity factors",
    "backup_folder": "Changed the second backup folder",
}


def _line(name):
    """The sentence Recent changes shows for a Setup action."""
    def make(con, body, out):
        ctx = dict(body)
        if "id" in body:
            table = ("stock_item" if name.startswith("item")
                     else "tare" if name.startswith("tare") else "account")
            r = db.one(con, f"SELECT name FROM {table} WHERE id = ?", (int(body["id"]),))
            ctx["who"] = r["name"] if r else "something"
        ctx["verb"] = "Brought back" if body.get("active") else "Retired"
        try:
            return _WORDS.get(name, name).format(**ctx)
        except (KeyError, IndexError, ValueError):
            return _WORDS.get(name, name).split(" {")[0]
    return make


_KIND = {"cash": ("cash", 1), "float": ("float", 1), "supplier": ("sup", -1),
         "staff": ("staff", -1), "partner": ("prt", -1)}


def _taken(con, kind, name, but=None):
    """Is the name already in use? Pots and floats are both picked by name
    wherever money moves, so one name may only belong to one of them."""
    kinds = ("cash", "float") if kind in ("cash", "float") else (kind,)
    return bool(db.one(con, f"SELECT 1 FROM account WHERE kind IN ({','.join('?' * len(kinds))}) "
                            "AND name = ? AND id IS NOT ?", (*kinds, name, but)))


def _account(con, body):
    a = db.one(con, "SELECT * FROM account WHERE id = ?", (int(body["id"]),))
    if not a or a["kind"] not in _KIND or a["code"].startswith("eq:"):
        raise ApiError("no such account")
    return a


@action("account_add", guard_pots=False, summary=_line("account_add"))
def _account_add(con, body):
    kind = body.get("kind")
    if kind not in _KIND:
        raise ApiError("that is not something Setup can add")
    name = name_of(body)
    if _taken(con, kind, name):
        raise ApiError(f"there is already a {name}")
    prefix, normal = _KIND[kind]
    code, n = f"{prefix}:{post.slug(name)}", 2
    while db.one(con, "SELECT 1 FROM account WHERE code = ?", (code,)):
        code, n = f"{prefix}:{post.slug(name)}-{n}", n + 1
    meta = {"share": _share(body.get("share"))} if kind == "partner" else {}
    sort = db.scalar(con, "SELECT COALESCE(MAX(sort), 0) + 1 FROM account "
                          "WHERE kind = ? AND sort < 90", (kind,))
    aid = post.ensure_account(con, code, name, kind, normal, meta=meta, sort=sort)
    if kind == "staff" and to_int(body.get("salary")):
        _save_salary(con, aid, to_int(body.get("salary")), body.get("view_month"))
    return {"id": aid}


@action("account_rename", guard_pots=False, summary=_line("account_rename"))
def _account_rename(con, body):
    a = _account(con, body)
    name = name_of(body)
    if _taken(con, a["kind"], name, but=a["id"]):
        raise ApiError(f"there is already a {name}")
    con.execute("UPDATE account SET name = ? WHERE id = ?", (name, a["id"]))
    return {"id": a["id"]}


@action("account_active", guard_pots=False, summary=_line("account_active"))
def _account_active(con, body):
    """Retire something, or bring it back. Nothing is deleted: the history
    stays, it just stops being offered. A pot that still holds money cannot be
    retired, because the money would vanish from cash on hand."""
    a = _account(con, body)
    active = 1 if body.get("active") else 0
    if not active and a["kind"] in ("cash", "float") \
            and queries.balance(con, a["code"]) != 0:
        raise ApiError(f"{a['name']} still holds "
                       f"{queries.balance(con, a['code']):,}. Move it out first.")
    meta = json.loads(a["meta"] or "{}")
    if a["kind"] == "staff":
        if active:
            meta.pop("left_after", None)
            meta.pop("former", None)
        else:
            meta["left_after"] = month_of(today())
    if active:
        meta.pop("retired_on", None)
    else:
        meta["retired_on"] = today()
    con.execute("UPDATE account SET active = ?, meta = ? WHERE id = ?",
                (active, json.dumps(meta, ensure_ascii=False), a["id"]))
    return {"id": a["id"]}


def _share(v):
    """A share as typed on screen: always a percentage. Reading "1" as the
    whole because it is not above 1 is how a 1% partner would quietly be
    handed all the profit."""
    try:
        s = float(str(v if v is not None else 0).strip().rstrip("%") or 0)
    except (TypeError, ValueError):
        raise ApiError("a share is a percentage") from None
    if not 0 <= s <= 100:
        raise ApiError("a share is between 0 and 100")
    return round(s / 100, 4)


@action("set_share", guard_pots=False, summary=_line("set_share"))
def _set_share(con, body):
    a = _account(con, body)
    meta = json.loads(a["meta"] or "{}")
    meta["share"] = _share(body.get("share"))
    con.execute("UPDATE account SET meta = ? WHERE id = ?",
                (json.dumps(meta, ensure_ascii=False), a["id"]))
    return {"id": a["id"]}


def _save_salary(con, account_id, amount, month=None):
    """A salary applies from a month onward. Months already closed keep what
    they were closed with, so the earliest it can start is the first open one."""
    month = month or month_of(today())
    while post.period_status(con, month) == "closed":
        month = next_month(month)
    con.execute("INSERT INTO salary(account_id, amount, from_month) VALUES (?,?,?) "
                "ON CONFLICT(account_id, from_month) DO UPDATE SET amount = excluded.amount",
                (account_id, amount, month))
    # later rows would override this one, so they follow it
    con.execute("UPDATE salary SET amount = ? WHERE account_id = ? AND from_month > ?",
                (amount, account_id, month))
    return month


@action("set_salary", guard_pots=False, summary=_line("set_salary"))
def _set_salary(con, body):
    a = _account(con, body)
    if a["kind"] != "staff":
        raise ApiError("only staff have a salary")
    amount = to_int(body.get("amount"), "salary")
    if amount < 0:
        raise ApiError("a salary cannot be negative")
    return {"id": a["id"], "from": _save_salary(con, a["id"], amount,
                                                 body.get("view_month"))}


def _effective_month(con, body):
    """The first month a change to a charge can apply to: the one on screen,
    or the next one that is still open."""
    month = body.get("view_month") or month_of(today())
    if month > month_of(today()):
        month = month_of(today())
    while post.period_status(con, month) == "closed":
        month = next_month(month)
    return month


@action("fixed_set", guard_pots=False, summary=_line("fixed_set"))
def _fixed_set(con, body):
    """Set a monthly charge. A change applies from the month on screen and
    every month after; earlier months keep what they were charged."""
    name = name_of(body)
    value = to_int(body.get("amount"), "amount")
    if value < 0:
        raise ApiError("a monthly charge cannot be negative")
    month = _effective_month(con, body)
    old = db.one(con, "SELECT * FROM fixed_charge WHERE name = ?", (name,))
    if old and old["amount"] == value and old["active"] and not old["to_month"]:
        return {"name": name}
    con.execute(
        "INSERT INTO fixed_charge(name, amount, account_id, from_month) VALUES (?,?,?,?) "
        "ON CONFLICT(name) DO UPDATE SET amount = excluded.amount, active = 1, "
        "from_month = excluded.from_month, to_month = NULL",
        (name, value, post.account_id(con, "exp:rent"), month))
    return {"name": name, "from": month}


@action("fixed_remove", guard_pots=False, summary=_line("fixed_remove"))
def _fixed_remove(con, body):
    """Stop a monthly charge from the month on screen. What earlier months
    were charged stays charged."""
    from .dates import prev_month
    month = _effective_month(con, body)
    con.execute("UPDATE fixed_charge SET active = 0, to_month = ? WHERE name = ?",
                (prev_month(month), name_of(body)))
    return {}


@action("list_add", guard_pots=False, summary=_line("list_add"))
def _list_add(con, body):
    if body.get("list") not in ("expense", "reason", "income", "bill"):
        raise ApiError("no such list")
    value = name_of(body, "value")
    sort = db.scalar(con, "SELECT COALESCE(MAX(sort), 0) + 1 FROM pick_list "
                          "WHERE list = ?", (body["list"],))
    con.execute("INSERT INTO pick_list(list, value, sort) VALUES (?,?,?) "
                "ON CONFLICT(list, value) DO UPDATE SET active = 1",
                (body["list"], value, sort))
    return {}


@action("list_remove", guard_pots=False, summary=_line("list_remove"))
def _list_remove(con, body):
    con.execute("UPDATE pick_list SET active = 0 WHERE list = ? AND value = ?",
                (body.get("list"), body.get("value")))
    return {}


@action("item_add", guard_pots=False, summary=_line("item_add"))
def _item_add(con, body):
    """A new stock item; or, with `brand`, a flavour of that brand, named
    'Brand · Flavour' and in the brand's category, at its price and packs."""
    brand = None
    if body.get("brand"):
        brand = db.one(con, "SELECT si.*, sc.letter FROM stock_item si JOIN stock_category "
                            "sc ON sc.id = si.category_id WHERE si.id = ?",
                       (int(body["brand"]),))
        if not brand or brand["parent_id"]:
            raise ApiError("a flavour belongs to a brand")
        body = {**body, "letter": brand["letter"],
                "name": brand["name"] + FLAVOUR + name_of(body), "price": body.get("price") or 0}
    cat = db.one(con, "SELECT * FROM stock_category WHERE letter = ?",
                 (str(body.get("letter") or "").upper(),))
    if not cat:
        raise ApiError("pick a category")
    name = name_of(body)
    if db.one(con, "SELECT 1 FROM stock_item WHERE name = ? AND category_id = ?",
              (name, cat["id"])):
        raise ApiError(f"{name} is already in that category")
    unit = {"A": "kg", "B": "kg", "E": "carton"}.get(cat["letter"], "piece")
    sort = db.scalar(con, "SELECT COALESCE(MAX(sort), 0) + 1 FROM stock_item")
    cur = con.execute(
        "INSERT INTO stock_item(name, category_id, unit, price, pack_size, sort, parent_id) "
        "VALUES (?,?,?,?,?,?,?)",
        (name, cat["id"], unit, to_int(body.get("price") or 0, "price"),
         to_int(body.get("pack_size")) or None, sort, brand["id"] if brand else None))
    return {"id": cur.lastrowid}


FLAVOUR = " · "


@action("item_update", guard_pots=False, summary=_line("item_update"))
def _item_update(con, body):
    """Change an item. A new price values the next count; counts already
    taken keep the price they were counted at. A flavour is always called
    'Brand · Flavour', and a brand's flavours stop and come back with it."""
    item = db.one(con, "SELECT si.*, sc.letter FROM stock_item si JOIN stock_category sc "
                       "ON sc.id = si.category_id WHERE si.id = ?", (int(body["id"]),))
    if not item:
        raise ApiError("no such item")
    if "name" in body:
        _rename(con, item, name_of(body))
    if "price" in body:
        price = to_int(body.get("price"), "price")
        if price < 0:
            raise ApiError("a price cannot be negative")
        con.execute("UPDATE stock_item SET price = ? WHERE id = ?", (price, item["id"]))
    if "pack_size" in body:
        con.execute("UPDATE stock_item SET pack_size = ? WHERE id = ?",
                    (to_int(body.get("pack_size")) or None, item["id"]))
    if "active" in body:
        con.execute("UPDATE stock_item SET active = ? WHERE id = ? OR parent_id = ?",
                    (1 if body.get("active") else 0, item["id"], item["id"]))
    if "packs" in body:
        if item["letter"] != "B":
            raise ApiError("only sealed tobacco comes in packs and blocks")
        try:
            packs = stock.parse_packs(body.get("packs"))
        except ValueError as e:
            raise ApiError(str(e)) from None
        con.execute("UPDATE stock_item SET packs = ? WHERE id = ?",
                    (json.dumps(packs) if packs else None, item["id"]))
    if "minimum" in body:
        raw = str(body.get("minimum") or "").strip()
        try:
            low = stock.to_milli(raw) if raw else None
        except (ValueError, ZeroDivisionError):
            raise ApiError("a minimum is a number") from None
        if low is not None and low < 0:
            raise ApiError("a minimum cannot be less than nothing")
        con.execute("UPDATE stock_item SET minimum_milli = ? WHERE id = ?", (low, item["id"]))
    if body.get("barcode_add"):
        _barcode_add(con, item, body["barcode_add"])
    if body.get("barcode_remove"):
        con.execute("DELETE FROM stock_barcode WHERE code = ? AND item_id = ?",
                    (str(body["barcode_remove"]), item["id"]))
    return {"id": item["id"]}


def _rename(con, item, name):
    """A flavour keeps its brand in front of its name; a brand takes its
    flavours' names with it."""
    if item["parent_id"]:
        brand = db.scalar(con, "SELECT name FROM stock_item WHERE id = ?", (item["parent_id"],))
        if not name.startswith(brand + FLAVOUR):
            name = brand + FLAVOUR + name
    renamed = [(item["id"], name)] + [
        (f["id"], name + f["name"][len(item["name"]):]) for f in db.all_(
            con, "SELECT id, name FROM stock_item WHERE parent_id = ?", (item["id"],))
        if f["name"].startswith(item["name"] + FLAVOUR)]
    for item_id, new in renamed:
        if db.one(con, "SELECT 1 FROM stock_item WHERE name = ? AND id <> ? AND category_id = "
                       "(SELECT category_id FROM stock_item WHERE id = ?)", (new, item_id, item_id)):
            raise ApiError(f"{new} is already in that category")
    for item_id, new in renamed:
        con.execute("UPDATE stock_item SET name = ? WHERE id = ?", (new, item_id))


# A scanner types through the keyboard layout in use, so with a Kurdish or
# Arabic layout a code can arrive in Eastern Arabic digits. They are the same
# code.
EASTERN_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def _barcode_add(con, item, raw):
    """One more barcode an item answers to (or several, between spaces or
    commas). A code belongs to one item only. A scanner types the code and
    presses Enter, so this is what a scan into Setup does."""
    for code in re.split(r"[\s,;]+", str(raw).strip().translate(EASTERN_DIGITS)):
        if not code:
            continue
        if not re.fullmatch(r"[0-9A-Za-z._-]{3,64}", code):
            raise ApiError(f"{code[:20]} is not a barcode")
        other = db.one(con, "SELECT si.id, si.name FROM stock_barcode b JOIN stock_item si "
                            "ON si.id = b.item_id WHERE b.code = ?", (code,))
        if other and other["id"] != item["id"]:
            raise ApiError(f"{code} is already {other['name']}")
        con.execute("INSERT OR IGNORE INTO stock_barcode(code, item_id) VALUES (?,?)",
                    (code, item["id"]))


@action("tare_set", guard_pots=False, summary=_line("tare_set"))
def _tare_set(con, body):
    grams = to_int(body.get("grams"), "grams")
    if grams < 0:
        raise ApiError("a bucket cannot weigh less than nothing")
    if body.get("id"):
        con.execute("UPDATE tare SET grams = ? WHERE id = ?", (grams, int(body["id"])))
    else:
        con.execute("INSERT INTO tare(name, grams) VALUES (?,?) "
                    "ON CONFLICT(name) DO UPDATE SET grams = excluded.grams",
                    (name_of(body), grams))
    return {}


@action("business_set", guard_pots=False, summary=_line("business_set"))
def _business_set(con, body):
    b = dict(db.setting(con, "business", {}) or {})
    for key in ("name", "owner", "currency"):
        if key in body:
            b[key] = str(body[key] or "").strip()
    if "note" in body and body["note"] not in (None, ""):
        note = to_int(body["note"], "note")
        if note < 1 or note > 100000:
            raise ApiError("the smallest banknote must be a sensible figure")
        b["note"] = note
        money.set_note(note)
    db.set_setting(con, "business", b)
    return {}


@action("item_supplier", guard_pots=False, summary=_line("item_update"))
def _item_supplier(con, body):
    """Which supplier an item comes from, so their statement can show how
    much of what is owed is still on the shelves."""
    sid = body.get("supplier_id") or None
    if sid and not db.one(con, "SELECT 1 FROM account WHERE id = ? AND kind = 'supplier'",
                          (int(sid),)):
        raise ApiError("no such supplier")
    con.execute("UPDATE stock_item SET supplier_id = ? WHERE id = ?",
                (int(sid) if sid else None, int(body["id"])))
    return {}


_CONVERSIONS = {"gramsPerKilo": (1, 100000), "gramsPerPack": (1, 100000),
                "packsPerBlock": (1, 1000), "blocksPerCarton": (1, 1000),
                "bucketsPerCarton": (1, 1000)}


@action("conversions_set", guard_pots=False, summary=_line("conversions_set"))
def _conversions_set(con, body):
    """How sealed tobacco and ice cream convert. A change applies to lines
    counted from now on; lines already counted keep the quantity they had."""
    conv = dict(db.setting(con, "conversions", {}) or {})
    for key, (low, high) in _CONVERSIONS.items():
        if key in body and body[key] not in (None, ""):
            v = to_int(body[key], key)
            if not low <= v <= high:
                raise ApiError(f"{key} must be between {low} and {high}")
            conv[key] = v
    db.set_setting(con, "conversions", conv)
    return {}


_FACTORS = ("privateAmps", "elevatorAmps", "elevatorShare", "publicRate", "publicShare")


@action("elec_factors_set", guard_pots=False, summary=_line("elec_factors_set"))
def _elec_factors_set(con, body):
    f = dict(db.setting(con, "elec_factors", {}) or {})
    for key in _FACTORS:
        if key in body and body[key] not in (None, ""):
            v = to_int(body[key], key)
            if v < 0 or (key.endswith("Share") and v < 1):
                raise ApiError("that is not a usable figure")
            f[key] = v
    db.set_setting(con, "elec_factors", f)
    return {}


@action("backup_folder", guard_pots=False, summary=_line("backup_folder"))
def _backup_folder(con, body):
    """Choose the second place, and put a copy there straight away, so the
    choice is proved to work while the person is still looking at it."""
    chosen = backup.set_folder(con, body.get("folder"))
    out = {"folder": chosen}
    if chosen:
        out["backup"] = backup.run(con, why="second-folder")
    return out


@action("backup_now", guard_pots=False, in_tx=False)
def _backup_now(con, body):
    return {"backup": backup.run(con, why="manual")}
