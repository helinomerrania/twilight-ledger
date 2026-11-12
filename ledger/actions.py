"""What can be done to the books from the screens: entering, correcting,
counting, writing off. Setup lives in setup.py.

Each action cleans what it was sent, calls one recipe in post.py, and returns.
None of them does arithmetic of its own.
"""
from . import db, kinds, post, queries, stock
from .dates import month_of, today
from .money import mround, to_int
from .registry import (ApiError, action, amount, clean_date, clean_period,
                       describe_entry, money_words, pot, who)


def _entry_line(con, body, out):
    return describe_entry(con, out["id"])


# ------------------------------------------------------------------ entering

@action("sales", summary=_entry_line)
def _sales(con, body):
    """Tonight's takings. Replaces the figure if one is already recorded for
    the day, rather than adding to it, because the till total is one number."""
    on = clean_date(body.get("on"))
    value = amount(body)
    replaced = [e["id"] for e in queries.entries(con, on=on, kind="daily_sales")
                if e["source"] in ("manual", "pos")]
    for rid in replaced:
        post.void(con, rid, why="replaced by a newer till figure")
    new_id = post.sales(con, value, on=on, into=pot(con, body))
    # the figure it replaced stands again if this one is taken back
    for rid in replaced:
        con.execute("UPDATE entry SET replaced_by = ? WHERE id = ?", (new_id, rid))
    return {"id": new_id}


@action("expense", summary=_entry_line)
def _expense(con, body):
    detail = str(body.get("detail") or "").strip()
    if not detail:
        raise ApiError("pick what it was spent on")
    return {"id": post.daily_expense(con, amount(body), detail=detail,
                                     on=clean_date(body.get("on")),
                                     out_of=pot(con, body),
                                     period=clean_period(body))}


@action("income", summary=_entry_line)
def _income(con, body):
    return {"id": post.other_income(con, amount(body),
                                    detail=str(body.get("detail") or "Other income"),
                                    on=clean_date(body.get("on")),
                                    into=pot(con, body), period=clean_period(body))}


@action("staff_advance", summary=_entry_line)
def _staff_advance(con, body):
    return {"id": post.staff_advance(con, amount(body), staff=who(con, body, "staff"),
                                     on=clean_date(body.get("on")),
                                     out_of=pot(con, body),
                                     period=clean_period(body))}


@action("staff_repay", summary=_entry_line)
def _staff_repay(con, body):
    return {"id": post.staff_repay(con, amount(body), staff=who(con, body, "staff"),
                                   on=clean_date(body.get("on")),
                                   into=pot(con, body), period=clean_period(body))}


@action("pay_salary", summary=_entry_line)
def _pay_salary(con, body):
    return {"id": post.pay_salary(con, amount(body), staff=who(con, body, "staff"),
                                  on=clean_date(body.get("on")),
                                  out_of=pot(con, body), period=clean_period(body))}


@action("pay_supplier", summary=_entry_line)
def _pay_supplier(con, body):
    return {"id": post.pay_supplier(con, amount(body),
                                    supplier=who(con, body, "supplier"),
                                    on=clean_date(body.get("on")),
                                    out_of=pot(con, body), period=clean_period(body))}


@action("pay_fixed", summary=_entry_line)
def _pay_fixed(con, body):
    name = str(body.get("who") or "").strip()
    if not db.one(con, "SELECT 1 FROM fixed_charge WHERE name = ?", (name,)):
        raise ApiError("pick which monthly charge is being paid")
    return {"id": post.pay_fixed(con, amount(body), name=name,
                                 on=clean_date(body.get("on")),
                                 out_of=pot(con, body), period=clean_period(body))}


@action("pay_electricity", summary=_entry_line)
def _pay_electricity(con, body):
    return {"id": post.pay_electricity(con, amount(body),
                                       on=clean_date(body.get("on")),
                                       out_of=pot(con, body),
                                       period=clean_period(body))}


@action("partner_draw", summary=_entry_line)
def _partner_draw(con, body):
    return {"id": post.partner_draw(con, amount(body),
                                    partner=who(con, body, "partner"),
                                    on=clean_date(body.get("on")),
                                    out_of=pot(con, body), period=clean_period(body))}


@action("partner_in", summary=_entry_line)
def _partner_in(con, body):
    return {"id": post.partner_in(con, amount(body),
                                  partner=who(con, body, "partner"),
                                  on=clean_date(body.get("on")),
                                  into=pot(con, body), period=clean_period(body))}


@action("transfer", summary=_entry_line)
def _transfer(con, body):
    return {"id": post.transfer(con, amount(body), frm=pot(con, body, "from"),
                                to=pot(con, body, "to"),
                                on=clean_date(body.get("on")))}


@action("receipt", summary=_entry_line)
def _receipt(con, body):
    eid = _post_receipt(con, body)
    return {"id": eid, "receipt": db.scalar(con, "SELECT id FROM receipt WHERE entry_id = ?",
                                            (eid,))}


def _post_receipt(con, body):
    value = amount(body)
    on = clean_date(body.get("on"))
    supplier = who(con, body, "supplier")
    terms = "cash" if body.get("terms") == "cash" else "credit"
    what = str(body.get("what") or "").strip() or "Several items"
    number = str(body.get("number") or "").strip() or None
    eid = post.receipt_in(con, value, supplier=supplier, on=on, terms=terms,
                          what=what, number=number,
                          out_of=pot(con, body) if terms == "cash" else None)
    con.execute("INSERT INTO receipt(received_on, supplier_id, number, what, "
                "amount, terms, entry_id) VALUES (?,?,?,?,?,?,?)",
                (on, post.account_by_name(con, "supplier", supplier),
                 number, what, value, terms, eid))
    return eid


def _receipt_line_said(con, body, out):
    name = db.scalar(con, "SELECT name FROM stock_item WHERE id = ?", (out["item"],),
                     default="an item")
    return (f"Took {name} off a receipt" if out.get("removed")
            else f"Receipt line: {name}")


@action("receipt_line", guard_pots=False, summary=_receipt_line_said)
def _receipt_line(con, body):
    """What one line of a supplier receipt brought in: the boxes, as on the
    count sheet, and what the invoice charges for them if it says. Only the
    receipt's total moves money. Empty boxes take the line off."""
    r = db.one(con, "SELECT r.*, e.period FROM receipt r JOIN entry e ON e.id = r.entry_id "
                    "WHERE r.id = ?", (int(body["receipt"]),))
    if not r:
        raise ApiError("that receipt is not in the books")
    if r["voided_at"]:
        raise ApiError("that receipt was deleted")
    if queries.is_closed(con, r["period"]):
        raise ApiError("that receipt belongs to a closed month")
    item, brand = _stock_item(con, body["item"])
    packages, blocks, loose = _boxes(body)
    raw = body.get("amount")
    value = to_int(raw, "amount") if raw not in (None, "") else None
    if value is not None and value < 0:
        raise ApiError("an amount cannot be negative")
    if stock.is_empty(packages, blocks, loose, None):
        if value:
            raise ApiError("say how many came, not only what they cost")
        con.execute("DELETE FROM receipt_line WHERE receipt_id = ? AND item_id = ?",
                    (r["id"], item["id"]))
        return {"receipt": r["id"], "item": item["id"], "removed": True}
    if item["letter"] == "A":
        raise ApiError("a mix is made here, not bought: take in the tobacco that goes into it")
    qty_milli = stock.qty_milli_of(_quantity(con, item, brand, packages, blocks, loose))
    if qty_milli <= 0:
        raise ApiError("say how many came")
    con.execute(
        "INSERT INTO receipt_line(receipt_id, item_id, packages_milli, blocks_milli, "
        "loose_milli, qty_milli, amount) VALUES (?,?,?,?,?,?,?) "
        "ON CONFLICT(receipt_id, item_id) DO UPDATE SET "
        "packages_milli = excluded.packages_milli, blocks_milli = excluded.blocks_milli, "
        "loose_milli = excluded.loose_milli, qty_milli = excluded.qty_milli, "
        "amount = excluded.amount",
        (r["id"], item["id"], packages, blocks, loose, qty_milli, value))
    return {"receipt": r["id"], "item": item["id"], "qty_milli": qty_milli, "amount": value}


# ---------------------------------------------------------------- correcting

def _entry(con, entry_id):
    rows = queries.entries(con, ids=[int(entry_id)])
    if not rows:
        raise ApiError("that entry is not in the books any more")
    return rows[0]


def _void_line(con, body, out):
    return "Deleted: " + out.pop("_was", "an entry")


@action("void", summary=_void_line)
def _void(con, body):
    """Delete an entry. It is kept, marked as deleted, and can be put back."""
    e = _entry(con, body["id"])
    if not e["deletable"]:
        raise ApiError(_why_not(con, e, "deleted"))
    was = describe_entry(con, e["id"])
    post.void(con, e["id"], why=body.get("why"))
    return {"id": e["id"], "_was": was}


def _undo_line(con, body, out):
    return "Taken back: " + out.pop("_was", "an entry")


@action("undo", summary=_undo_line)
def _undo(con, body):
    """Take back a change just made. The entry it wrote is deleted, and an
    entry it corrected or replaced stands again, as it was — with what came
    in on a corrected receipt listed on it again."""
    e = _entry(con, body["id"])
    if e.get("voided_at"):
        raise ApiError("That has already been taken back.")
    if not e["deletable"]:
        raise ApiError(_why_not(con, e, "taken back"))
    was = describe_entry(con, e["id"])
    post.void(con, e["id"], why="taken back")
    back = []
    for old in db.all_(con, "SELECT id FROM entry WHERE replaced_by = ?", (e["id"],)):
        con.execute("UPDATE entry SET replaced_by = NULL WHERE id = ?", (old["id"],))
        post.unvoid(con, old["id"])
        con.execute("UPDATE receipt_line SET receipt_id = (SELECT id FROM receipt WHERE entry_id = ?) "
                    "WHERE receipt_id = (SELECT id FROM receipt WHERE entry_id = ?)",
                    (old["id"], e["id"]))
        back.append(old["id"])
    return {"id": e["id"], "put_back": back, "_was": was}


@action("put_back", summary=lambda con, body, out: "Put back: " + describe_entry(con, out["id"]))
def _put_back(con, body):
    return {"id": post.unvoid(con, int(body["id"]))}


def _why_not(con, e, verb):
    if queries.is_closed(con, e["period"]):
        return (f"{e['period']} is closed, so its entries cannot be {verb}. "
                "Reopen the month first.")
    if any(l["code"] == "eq:opening" for l in e["legs"]):
        return ("that entry is from before these books began keeping a running "
                f"balance for each person, so it is part of the record and cannot be {verb}.")
    if e["kind"] in ("salary_charge", "fixed_charge", "electricity_charge"):
        return ("that is a charge the app works out itself. Change the salary, the "
                "rent or the meter reading and it follows.")
    return f"that kind of entry cannot be {verb} here"


# How to write each kind of entry again from a corrected form.
def _repost(con, kind, f):
    kw = dict(on=f["on"], period=f["period"])
    if kind == "daily_sales":
        return post.sales(con, f["amount"], into=f["pot"], **kw)
    if kind == "other_income":
        return post.other_income(con, f["amount"], detail=f["detail"], into=f["pot"], **kw)
    if kind == "daily_expense":
        return post.daily_expense(con, f["amount"], detail=f["detail"], out_of=f["pot"], **kw)
    if kind == "staff_advance":
        return post.staff_advance(con, f["amount"], staff=f["detail"], out_of=f["pot"], **kw)
    if kind == "staff_repayment":
        return post.staff_repay(con, f["amount"], staff=f["detail"], into=f["pot"], **kw)
    if kind == "salary_payment":
        return post.pay_salary(con, f["amount"], staff=f["detail"], out_of=f["pot"], **kw)
    if kind == "supplier_payment":
        return post.pay_supplier(con, f["amount"], supplier=f["detail"], out_of=f["pot"], **kw)
    if kind == "fixed_payment":
        return post.pay_fixed(con, f["amount"], name=f["detail"], out_of=f["pot"], **kw)
    if kind == "electricity_payment":
        return post.pay_electricity(con, f["amount"], out_of=f["pot"], **kw)
    if kind == "partner_draw":
        return post.partner_draw(con, f["amount"], partner=f["detail"], out_of=f["pot"], **kw)
    if kind == "partner_in":
        return post.partner_in(con, f["amount"], partner=f["detail"], into=f["pot"], **kw)
    if kind == "transfer":
        return post.transfer(con, f["amount"], frm=f["pot"], to=f["pot_to"], **kw)
    raise ApiError("that kind of entry cannot be corrected here")


_WHO_KIND = {"staff_advance": "staff", "staff_repayment": "staff",
             "salary_payment": "staff", "supplier_payment": "supplier",
             "receipt_credit": "supplier", "receipt_cash": "supplier",
             "partner_draw": "partner", "partner_in": "partner"}


def _edit_line(con, body, out):
    return f"Corrected: {out.pop('_was', 'an entry')} → {describe_entry(con, out['id'])}"


@action("edit_entry", summary=_edit_line)
def _edit_entry(con, body):
    """Correct an entry.

    The original is never changed. It is voided and a corrected one is written
    in the same transaction, joined to it, so the record shows what it said
    before, what it says now, and when it was changed.
    """
    e = _entry(con, body["id"])
    if not e["editable"]:
        raise ApiError(_why_not(con, e, "corrected"))
    kind = e["kind"]

    on = clean_date(body.get("on") or e["happened_on"])
    # The month an entry counts for follows its date unless it was deliberately
    # tagged to another month, or is being tagged now.
    chosen = clean_period(body)
    if chosen:
        period = chosen
    elif e["tagged"]:
        period = e["period"]
    else:
        period = month_of(on)

    detail = e["detail"]
    if "detail" in body and body["detail"] not in (None, ""):
        detail = str(body["detail"]).strip()
        if kind in _WHO_KIND:
            detail = who(con, {"who": detail}, _WHO_KIND[kind])
    f = {"on": on, "period": period, "detail": detail,
         "amount": amount(body) if body.get("amount") not in (None, "") else e["amount"],
         "pot": pot(con, {"pot": body.get("pot") or e["pot"]}) if (body.get("pot") or e["pot"]) else None,
         "pot_to": pot(con, {"pot": body.get("pot_to") or e["pot_to"]})
                   if kind == "transfer" else None}

    was = describe_entry(con, e["id"])
    post.void(con, e["id"], why="corrected")
    if kind in ("receipt_credit", "receipt_cash"):
        r = e["receipt"] or {}
        terms = body.get("terms") or r.get("terms") or ("cash" if kind == "receipt_cash" else "credit")
        new_id = _post_receipt(con, {
            "amount": f["amount"], "on": on, "who": detail, "terms": terms,
            "what": body.get("what") if "what" in body else r.get("what"),
            "number": body.get("number") if "number" in body else r.get("number"),
            "pot": f["pot"]})
        # what came in did not change because the receipt was corrected
        if r.get("id"):
            con.execute("UPDATE receipt_line SET receipt_id = (SELECT id FROM receipt "
                        "WHERE entry_id = ?) WHERE receipt_id = ?", (new_id, r["id"]))
    else:
        new_id = _repost(con, kind, f)
    con.execute("UPDATE entry SET replaced_by = ? WHERE id = ?", (new_id, e["id"]))
    return {"id": new_id, "replaced": e["id"], "_was": was}


# ------------------------------------------------------------------ counting

def _count_summary(con, body, out):
    c = next((x for x in queries.cash_counts(con) if x["id"] == out["id"]), None)
    if not c:
        return "Cash counted"
    return (f"Cash counted for {c['on']}: ties" if c["diff"] == 0
            else f"Cash counted for {c['on']}: out by {money_words(c['diff'])}")


@action("cash_count", guard_pots=False, summary=_count_summary)
def _cash_count(con, body):
    """Save a night's count. A reading, never a correction: the difference is
    recorded and explained, and nothing is invented to make it disappear.
    Writing a difference off is a separate, deliberate step."""
    on = clean_date(body.get("on"))
    cur = con.execute("INSERT INTO cash_count(counted_on, reason) VALUES (?,?) "
                      "ON CONFLICT(counted_on) DO UPDATE SET reason = excluded.reason",
                      (on, body.get("reason") or None))
    cid = db.one(con, "SELECT id FROM cash_count WHERE counted_on = ?", (on,))["id"]
    for name, value in (body.get("pots") or {}).items():
        aid = post.account_by_name_any(con, name)
        if value in (None, ""):
            con.execute("DELETE FROM cash_count_line WHERE count_id = ? AND account_id = ?",
                        (cid, aid))
            continue
        counted = to_int(value, name)
        if counted < 0:
            raise ApiError("a pot cannot hold less than nothing")
        con.execute("INSERT INTO cash_count_line(count_id, account_id, counted) "
                    "VALUES (?,?,?) ON CONFLICT(count_id, account_id) "
                    "DO UPDATE SET counted = excluded.counted", (cid, aid, counted))
    if not db.scalar(con, "SELECT count(*) FROM cash_count_line WHERE count_id = ?", (cid,)):
        con.execute("DELETE FROM cash_count WHERE id = ?", (cid,))
        raise ApiError("count at least one pot")
    return {"id": cid}


@action("delete_cash_count", guard_pots=False,
        summary=lambda con, body, out: f"Deleted the cash count for {out['on']}")
def _delete_cash_count(con, body):
    c = db.one(con, "SELECT * FROM cash_count WHERE id = ?", (int(body["id"]),))
    if not c:
        raise ApiError("that count is not in the books")
    if db.one(con, "SELECT 1 FROM entry WHERE source_ref LIKE ? AND voided_at IS NULL "
                   "AND kind = 'cash_difference'", (f"count:{c['id']}:%",)):
        raise ApiError("a difference on that count was written off. Delete the "
                       "write-off on Books first.")
    con.execute("DELETE FROM cash_count WHERE id = ?", (c["id"],))
    return {"on": c["counted_on"]}


def _write_off_line(con, body, out):
    word = "short" if out["diff"] < 0 else "over"
    return (f"Wrote off {money_words(abs(out['diff']))} {word} in {out['pot']} "
            f"on {out['on']}")


@action("write_off", guard_pots=False, summary=_write_off_line)
def _write_off(con, body):
    """Accept a counted difference as real.

    The pot is moved onto what was counted and the shortage becomes a cost of
    that month. Without this a missing 50,000 is noted beside the count and
    then sits in the books for ever, making every later count wrong by the
    same amount.
    """
    count = next((c for c in queries.cash_counts(con) if c["id"] == int(body["id"])), None)
    if not count:
        raise ApiError("that count is not in the books")
    done = []
    for p in count["pots"]:
        if body.get("pot") and p["name"] != body["pot"]:
            continue
        if p["diff"] == 0:
            continue
        aid = post.account_by_name_any(con, p["name"])
        eid = post.cash_difference(
            con, p["diff"], pot=p["name"], on=count["on"],
            reason=str(body.get("reason") or count["reason"] or "").strip() or None,
            source_ref=f"count:{count['id']}:{aid}")
        done.append((eid, p["name"], p["diff"]))
    if not done:
        raise ApiError("there is nothing left to write off on that count")
    return {"id": done[0][0], "pot": ", ".join(d[1] for d in done),
            "diff": sum(d[2] for d in done), "on": count["on"]}


# --------------------------------------------------------------------- stock

@action("open_count", guard_pots=False)
def _open_count(con, body):
    """Start a count on a date. Opening one does not value the stock — an
    empty count is ignored until something is typed into it."""
    on = clean_date(body.get("on"))
    con.execute("INSERT INTO stock_count(count_date, closing, source) "
                "VALUES (?,0,'counted') ON CONFLICT(count_date) DO NOTHING", (on,))
    return {"count_date": on}


def _stock_item(con, item_id):
    """An item with its category letter, and its brand when it is a flavour."""
    item = db.one(con, "SELECT si.*, sc.letter FROM stock_item si "
                       "JOIN stock_category sc ON sc.id = si.category_id "
                       "WHERE si.id = ?", (int(item_id),))
    if not item:
        raise ApiError("no such stock item")
    brand = db.one(con, "SELECT * FROM stock_item WHERE id = ?",
                   (item["parent_id"],)) if item["parent_id"] else None
    return item, brand


def _boxes(body):
    """What was typed into the packages, blocks and loose boxes, x 1000."""
    try:
        boxes = [stock.to_milli(body.get(k)) for k in ("packages", "blocks", "loose")]
    except (ValueError, ZeroDivisionError):
        raise ApiError("a count is a number") from None
    if min(boxes) < 0:
        raise ApiError("a count cannot be less than nothing")
    return boxes


def _quantity(con, item, brand, packages, blocks, loose, gross=None, tare_grams=0):
    """What the boxes come to in the item's own quantity. A flavour comes in
    its brand's packs unless it has its own."""
    conv = stock.item_conversions(db.setting(con, "conversions", {}),
                                  stock.packs_of(dict(item), dict(brand) if brand else None))
    return stock.quantity(item["letter"], packages_milli=packages,
                          blocks_milli=blocks, loose_milli=loose,
                          gross_grams=gross, tare_grams=tare_grams,
                          pack_size=item["pack_size"] or (brand["pack_size"] if brand else None),
                          conv=conv)


def locked(con, count_date):
    """A count a closed month was built on cannot be edited."""
    if not count_date:
        return False
    return bool(db.one(con, "SELECT 1 FROM period WHERE count_date = ? "
                            "AND status = 'closed'", (count_date,)))


@action("count_line", guard_pots=False)
def _count_line(con, body):
    """Save one line of a stock count, and revalue the whole count.

    The line's quantity and value are worked out here and stored, not
    recomputed when a screen asks for them. That is what stops a price change
    in Setup from moving a month that has already been closed.
    """
    on = body["on"]
    if locked(con, on):
        raise ApiError("that count belongs to a closed month")
    head = db.one(con, "SELECT * FROM stock_count WHERE count_date = ?", (on,))
    if not head:
        on = clean_date(on)
        con.execute("INSERT INTO stock_count(count_date, closing, source) "
                    "VALUES (?,0,'counted')", (on,))
        head = db.one(con, "SELECT * FROM stock_count WHERE count_date = ?", (on,))
    item, brand = _stock_item(con, body["item"])
    packages, blocks, loose = _boxes(body)
    gross = body.get("gross_grams")
    gross = to_int(gross, "gross_grams") if gross not in (None, "") else None
    if (gross or 0) < 0:
        raise ApiError("a count cannot be less than nothing")
    tare_id = body.get("tare_id") or None
    tare_grams = db.scalar(con, "SELECT grams FROM tare WHERE id = ?",
                           (tare_id,)) if tare_id else 0

    # a flavour comes in its brand's packs, at its brand's price, unless it
    # has its own
    qty = _quantity(con, item, brand, packages, blocks, loose, gross, tare_grams)
    qty_milli = stock.qty_milli_of(qty)
    # A line keeps the price it was counted at. Re-pricing an item in Setup
    # then changes what the next count is worth, never what an old one was.
    existing = db.one(con, "SELECT price FROM stock_count_line WHERE count_id = ? "
                           "AND item_id = ?", (head["id"], item["id"]))
    price = (existing["price"] if existing and existing["price"]
             else item["price"] or (brand["price"] if brand else 0))
    value = stock.value_of(qty, price)

    if stock.is_empty(packages, blocks, loose, gross):
        con.execute("DELETE FROM stock_count_line WHERE count_id = ? AND item_id = ?",
                    (head["id"], item["id"]))
    else:
        con.execute(
            "INSERT INTO stock_count_line(count_id, item_id, packages_milli, "
            "blocks_milli, loose_milli, gross_grams, tare_id, price, qty_milli, "
            "value) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(count_id, item_id) DO UPDATE SET "
            "packages_milli=excluded.packages_milli, blocks_milli=excluded.blocks_milli, "
            "loose_milli=excluded.loose_milli, gross_grams=excluded.gross_grams, "
            "tare_id=excluded.tare_id, qty_milli=excluded.qty_milli, "
            "value=excluded.value",
            (head["id"], item["id"], packages, blocks, loose, gross, tare_id,
             price, qty_milli, value))

    total = db.scalar(con, "SELECT COALESCE(SUM(value), 0) FROM stock_count_line "
                           "WHERE count_id = ?", (head["id"],))
    con.execute("UPDATE stock_count SET closing = ? WHERE id = ?",
                (mround(total), head["id"]))
    return {"item": item["id"], "qty_milli": qty_milli, "value": value,
            "closing": mround(total), "count_date": on}


@action("delete_count", guard_pots=False,
        summary=lambda con, body, out: f"Deleted the stock count for {out['deleted']}")
def _delete_count(con, body):
    on = body["on"]
    if locked(con, on):
        raise ApiError("that count belongs to a closed month")
    con.execute("DELETE FROM stock_count WHERE count_date = ?", (on,))
    return {"deleted": on}


# ------------------------------------------------------------------ the month

@action("set_electricity", guard_pots=False,
        summary=lambda con, body, out: f"Electricity charged: {money_words(out['bill']['total'])}")
def _set_electricity(con, body):
    from . import accruals
    month = body.get("month") or body.get("view_month") or month_of(today())
    return {"bill": accruals.set_electricity(
        con, month, private_price=body.get("private_price"),
        elevator_price=body.get("elevator_price"),
        last_reading=body.get("last_reading"), now_reading=body.get("now_reading"))}


@action("close_month", guard_pots=False,
        summary=lambda con, body, out: f"Closed {out['month']} at a net of "
                                       f"{money_words(out['result']['net'])}")
def _close_month(con, body):
    from .close import close_month
    return close_month(con, body.get("month") or month_of(today()))


@action("reopen_month", guard_pots=False,
        summary=lambda con, body, out: f"Reopened {out['month']}")
def _reopen_month(con, body):
    from .close import reopen_month
    return reopen_month(con, body.get("month"))
