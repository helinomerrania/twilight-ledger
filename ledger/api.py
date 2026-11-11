"""What the screens read.

One request per screen, not one per card. `state` assembles the whole picture
— the books are small, so it costs a few milliseconds — and that removes every
chance of two cards on one screen disagreeing because they loaded at different
moments.

Nothing here does arithmetic of its own: every figure comes from queries.py.
What the screens can *do* lives in actions.py and setup.py; importing them is
what registers their actions.
"""
import json

from . import (accruals, actions, backup, buckets, cash, checks as _checks, db, kinds, money,
               stock, post, queries, setup, update)
from .dates import month_of, today
from .pos import actions as pos
from .registry import ACTIONS, ApiError, run            # noqa: F401  (re-exported)

assert actions and setup and pos and cash                # imported to register


def bootstrap(con):
    """Make an empty database usable: the accounts every set of books needs,
    one cash pot, and the stock categories. Does nothing to books that already
    have them."""
    with db.tx(con):
        post.ensure_system_accounts(con)
        if not db.one(con, "SELECT 1 FROM account WHERE kind = 'cash'"):
            post.ensure_account(con, "cash:box", "Box", "cash", 1)
        if not db.one(con, "SELECT 1 FROM stock_category"):
            for i, (letter, name) in enumerate([
                    ("A", "A - Mixed Tobacco (weighed)"),
                    ("B", "B - Sealed Tobacco (blocks)"),
                    ("C", "C - Shisha Supplies"), ("D", "D - Cafe Goods"),
                    ("E", "E - Ice Cream"), ("F", "F - Other")]):
                con.execute("INSERT INTO stock_category(letter, name, sort) "
                            "VALUES (?,?,?)", (letter, name, i))
        if not db.setting(con, "business"):
            db.set_setting(con, "business", {"name": "Twilight Rest & Cafe",
                                             "currency": "IQD", "note": 250})
    load_settings(con)


def load_settings(con):
    """Settings that change how figures are worked out, loaded once on the
    way up and again whenever Setup changes them."""
    b = db.setting(con, "business", {}) or {}
    money.set_note(b.get("note") or money.DEFAULT_NOTE)


# ------------------------------------------------------------------- reading

def state(con, *, month=None, on=None, count_date=None):
    now = month_of(today())
    month = month or now
    on = on or today()
    # Every month up to today is charged its rent and salaries the first time
    # it is needed, and an open one is put right if Setup has changed since.
    accruals.ensure_all(con)
    per = queries.period(con, month)
    return {
        "today": today(),
        "version": update.current(),
        "month": month,
        "this_month": now,
        "months": queries.months(con),
        "period": dict(per) if per else {"month": month, "status": "open"},
        "business": db.setting(con, "business", {}) or {},
        "note": money.NOTE,
        "kinds": kinds.LABELS,
        "main_pot": post.main_pot(con)["name"],
        "fixed_names": [r["name"] for r in db.all_(
            con, "SELECT name FROM fixed_charge WHERE active = 1 ORDER BY name")],
        "day": queries.day(con, on),
        "last_sales": db.scalar(con, "SELECT MAX(happened_on) FROM movement "
                                     "WHERE code = 'rev:sales'", default=None),
        "pos": pos.view(con, on, month),
        "result": queries.result(con, month),
        "so_far": queries.so_far(con, month),
        "drawings": queries.drawings(con, month),
        "pots": queries.pots(con),
        "cash": queries.cash_on_hand(con),
        "floats": queries.in_hands(con),
        "payroll": queries.payroll(con, month),
        "partners": queries.partners(con, month),
        "suppliers": queries.supplier_statement(con, month),
        "owed": queries.owed_to_suppliers(con),
        "settle": settle(con, month),
        "flow": queries.money_flow(con, month),
        "sales_by_day": queries.sales_by_day(con, month),
        "counts": queries.cash_counts(con)[-30:],
        "drawer": cash.drawer(con, on),
        "differences": cash.differences(con, month),
        "summary": queries.summary(con),
        "stock": stock_view(con, month, count_date),
        "checks": _checks.checks(con, month),
        "lists": pick_lists(con),
        "setup": setup_view(con, month),
        "electricity": accruals.electricity_view(con, month),
        "people": people(con),
        "entries": queries.entries(con, month=month, limit=600),
        "recent": queries.recent(con, 40),
        "backup": backup.status(con),
    }


def settle(con, month):
    """Everything still unpaid up to the end of `month`, as one list.

    Salaries and rent are "up to the end of this month" — what is owed for it
    and anything older that was never settled. A supplier is simply what is
    owed to them now, because that debt is a running account, not a monthly one.
    """
    lines = []
    for p in queries.payroll(con, month):
        if p["still_to_pay"]:
            lines.append({"action": "pay_salary", "what": "Salary", "who": p["name"],
                          "amount": p["still_to_pay"],
                          "note": (f"includes {p['from_earlier']:,} from earlier months"
                                   if p["from_earlier"] else "")})
    for f in queries.fixed_outstanding(con, month):
        if f["still_to_pay"]:
            lines.append({"action": "pay_fixed", "what": "Monthly charge",
                          "who": f["name"], "amount": f["still_to_pay"], "note": ""})
    elec = queries.electricity_outstanding(con, month)
    if elec:
        lines.append({"action": "pay_electricity", "what": "Electricity",
                      "who": "Electricity", "amount": elec, "note": ""})
    for s in queries.supplier_statement(con, month):
        if s["owed_now"] > 0:
            lines.append({"action": "pay_supplier", "what": "Supplier",
                          "who": s["name"], "amount": s["owed_now"],
                          "note": "everything owed to them now"})
    return lines


def setup_view(con, month):
    """Everything the Setup screen edits."""
    return {
        "salaries": {str(a["id"]): queries.salary_for(con, a["id"], month)
                     for a in queries.balances(con, "staff")},
        "fixed": [dict(r) for r in db.all_(con, "SELECT * FROM fixed_charge ORDER BY name")],
        "categories": [dict(r) for r in db.all_(
            con, "SELECT * FROM stock_category ORDER BY sort, letter")],
        "items": _setup_items(con),
        "tares": [dict(r) for r in db.all_(con, "SELECT * FROM tare ORDER BY name")],
        "conversions": db.setting(con, "conversions", {}) or {},
        "elec_factors": accruals.factors(con),
    }


def _flavour(item, brand):
    """A flavour's own part of its name: 'Mint' of 'Hill Leaf · Mint'."""
    if not brand:
        return None
    head = brand["name"] + setup.FLAVOUR
    return item["name"][len(head):] if item["name"].startswith(head) else item["name"]


def _levels(conv, item, brand):
    """The boxes an item is counted or received in, as [{key, label}]."""
    return [{"key": k, "label": lab} for k, lab in stock.levels(
        item["letter"], conv, stock.packs_of(item, brand),
        item["pack_size"] or (brand["pack_size"] if brand else None))]


def _setup_items(con):
    """Every stock item for Setup, a flavour after its brand, each with its
    packs said the way the boxes say them and its barcodes."""
    conv = db.setting(con, "conversions", {}) or {}
    rows = [dict(r) for r in db.all_(con, """
        SELECT si.*, sc.letter FROM stock_item si
          JOIN stock_category sc ON sc.id = si.category_id
         ORDER BY sc.sort, sc.letter, si.active DESC, si.sort, si.name""")]
    by_id = {r["id"]: r for r in rows}
    codes = {}
    for b in db.all_(con, "SELECT code, item_id FROM stock_barcode ORDER BY code"):
        codes.setdefault(b["item_id"], []).append(b["code"])
    for r in rows:
        brand = by_id.get(r["parent_id"])
        r["flavour"] = _flavour(r, brand)
        r["levels"] = _levels(conv, r, brand)
        if r["letter"] == "B":
            own = stock.packs_of(r)
            mine = stock.packs_of(r, brand)
            r["pack_grams"] = mine["grams"] if mine else stock.conversions(conv)["grams_per_pack"]
            r["cost"] = r["price"] or (brand["price"] if brand else 0)
            r["comes_as"] = stock.packs_label(conv, own) if own else ""
            r["comes_as_else"] = stock.packs_label(conv, stock.packs_of(brand) if brand else None)
        r["barcodes"] = codes.get(r["id"], [])
        r["minimum"] = r["minimum_milli"] / 1000 if r["minimum_milli"] is not None else None
    order = {r["id"]: n for n, r in enumerate(rows)}
    rows.sort(key=lambda r: (order.get(r["parent_id"], order[r["id"]]),
                             r["parent_id"] is not None, r["name"]))
    return rows


def receipt_lines(con):
    """Every receipt's lines, by receipt row: the item, the boxes as typed with
    the sizes they stand for, what they came to, and the amount."""
    conv = db.setting(con, "conversions", {}) or {}
    items = {r["id"]: dict(r) for r in db.all_(con, """
        SELECT si.*, sc.letter FROM stock_item si
          JOIN stock_category sc ON sc.id = si.category_id""")}
    out = {}
    for l in db.all_(con, "SELECT * FROM receipt_line ORDER BY receipt_id, id"):
        item = items[l["item_id"]]
        brand = items.get(item["parent_id"])
        out.setdefault(l["receipt_id"], []).append({
            "item": item["id"], "name": item["name"], "letter": item["letter"],
            "levels": _levels(conv, item, brand),
            "packages_milli": l["packages_milli"], "blocks_milli": l["blocks_milli"],
            "loose_milli": l["loose_milli"], "qty_milli": l["qty_milli"],
            "amount": l["amount"]})
    return out


def pick_lists(con):
    out = {"expense": [], "income": [], "reason": [], "bill": []}
    for r in db.all_(con, "SELECT list, value FROM pick_list WHERE active = 1 "
                          "ORDER BY list, sort, value"):
        out.setdefault(r["list"], []).append(r["value"])
    return out


def people(con):
    out = {}
    for kind in ("cash", "float", "supplier", "staff", "partner"):
        rows = (queries.partner_accounts(con) if kind == "partner"
                else queries.balances(con, kind))
        out[kind] = [{"id": a["id"], "name": a["name"], "code": a["code"],
                      "active": a["active"], "balance": a["balance"],
                      "last_used": a["last_used"],
                      "meta": json.loads(a["meta"] or "{}")}
                     for a in rows]
    return out


def stock_view(con, month, count_date=None):
    c = queries.cogs(con, month)
    dates = queries.count_dates(con)
    chosen = count_date or c["date"] or (dates[-1] if dates else None)
    receipts = queries.entries(con, kind="receipt_credit") + \
        queries.entries(con, kind="receipt_cash")
    receipts.sort(key=lambda e: (e["happened_on"], e["id"]), reverse=True)
    lines = receipt_lines(con)
    for e in receipts:
        e["lines"] = lines.get((e["receipt"] or {}).get("id"), [])
    return {**buckets.view(con), "cogs": c, "count_dates": dates, "count_date": chosen,
            "count": count_sheet(con, chosen),
            "counts": [dict(r) for r in db.all_(
                con, "SELECT count_date, closing, source, note FROM stock_count "
                     "ORDER BY count_date DESC")],
            "receipts": receipts}


def count_sheet(con, count_date):
    """Every stock item, with whatever has been counted on this date beside it.

    Items with nothing entered come back too, with empty figures: a count
    sheet that hides the things you have not counted yet is how an item gets
    forgotten and the closing stock comes out short.

    An item that has since been retired still shows on a count it was part of,
    so an old count keeps adding up to the figure it was booked at.
    """
    head = db.one(con, "SELECT * FROM stock_count WHERE count_date = ?", (count_date,))
    conv = db.setting(con, "conversions", {}) or {}
    rows = db.all_(con, """
        SELECT si.id, si.name, si.unit, si.price, si.pack_size, si.active,
               si.parent_id, si.packs,
               sc.letter, sc.name AS category,
               l.packages_milli, l.blocks_milli, l.loose_milli,
               l.gross_grams, l.tare_id, l.qty_milli, l.value,
               COALESCE(l.price, si.price) AS counted_at
          FROM stock_item si
          JOIN stock_category sc ON sc.id = si.category_id
          LEFT JOIN stock_count_line l
                 ON l.item_id = si.id
                AND l.count_id = (SELECT id FROM stock_count WHERE count_date = ?)
         WHERE si.active = 1 OR l.id IS NOT NULL
         ORDER BY sc.sort, sc.letter, si.sort, si.name""", (count_date,))
    items = {r["id"]: dict(r) for r in db.all_(con, "SELECT * FROM stock_item")}
    flavours = {}
    for i in items.values():
        if i["parent_id"] and i["active"]:
            flavours[i["parent_id"]] = flavours.get(i["parent_id"], 0) + 1
    groups = {}
    for r in rows:
        g = groups.setdefault(r["letter"], {"letter": r["letter"],
                                            "name": r["category"], "items": [],
                                            "value": 0})
        line = dict(r)
        brand = items.get(r["parent_id"])
        line["brand"] = brand["name"] if brand else None
        line["flavour"] = _flavour(r, brand)
        line["flavours"] = flavours.get(r["id"], 0)
        if brand and not r["price"]:
            line["price"] = brand["price"]
            if line["counted_at"] == 0:
                line["counted_at"] = brand["price"]
        if r["letter"] == "B":
            line["levels"] = _levels(conv, {**items[r["id"]], "letter": "B"}, brand)
        g["items"].append(line)
        g["value"] += r["value"] or 0
    for g in groups.values():
        # a flavour sits under its brand, whatever it is called
        order = {i["id"]: n for n, i in enumerate(g["items"])}
        g["items"].sort(key=lambda i: (order.get(i["parent_id"], order[i["id"]]),
                                       i["parent_id"] is not None, i["name"]))
    return {"date": count_date,
            "closing": head["closing"] if head else 0,
            "source": head["source"] if head else None,
            "locked": actions.locked(con, count_date),
            "groups": list(groups.values()),
            "tares": [dict(t) for t in db.all_(con, "SELECT * FROM tare ORDER BY name")]}
