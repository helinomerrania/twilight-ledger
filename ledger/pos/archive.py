"""Keeping each SambaPOS night, and reading it back.

A snapshot may hold several work periods, a work period may be brought in
many times as the night goes on, and an old backup may be brought in after a
newer one. So a work period is identified by SambaPOS's own id together with
the moment it started — ids keep counting up across resets, but a reinstall
would start them again — and a copy already kept is only ever replaced by a
fuller copy of the same period: one that was closed when this one was open,
or holds more tickets, or reaches later into the night.

A work period belongs to a business night. The lounge closes after midnight,
so a ticket opened before six in the morning belongs to the night before.

Besides tickets, SambaPOS records everything else that moves money as an
account document: an expense, a staff or owner advance, cash put in or taken
out. Those are kept as SambaPOS wrote them, account by account. A ticket's
own document is left out, because its sale and payment are in the ticket.
"""
from bisect import bisect_right
from collections import Counter, defaultdict
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from .. import db
from . import catalog, links

NIGHT_ENDS = 6


def whole(v):
    """Whole dinar, halves away from zero."""
    return int(Decimal(v or 0).quantize(Decimal(1), ROUND_HALF_UP))


def milli(v):
    return int((Decimal(v or 0) * 1000).quantize(Decimal(1), ROUND_HALF_UP))


def describe(line):
    """One kept work period in words: 'the night of 2026-11-10: 85 tickets,
    354,750 paid'."""
    bits = [f"{line['tickets']} tickets", f"{line['takings']:,} paid"]
    if line.get("unpaid"):
        bits.append(f"{line['unpaid']:,} unpaid")
    return f"the night of {line['night']}: " + ", ".join(bits)


def stamp(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S") if dt else None


def night_of(moment):
    return (moment - timedelta(hours=NIGHT_ENDS)).date().isoformat()


def _night(period, tickets):
    """The night most of the period's tickets were opened on."""
    if tickets:
        votes = Counter(night_of(t["Date"]) for t in tickets)
        return max(votes.items(), key=lambda kv: (kv[1], kv[0]))[0]
    return period["StartDate"].date().isoformat()


# ------------------------------------------------------------------ keeping

def as_of(snap):
    """When a snapshot was taken: as its source says (a backup's own time, or
    the moment of a live read), or else the latest moment it holds."""
    at = snap.get("at")
    if at:
        return stamp(at) if hasattr(at, "strftime") else str(at)
    t = snap["tables"]
    moments = [w.get(k) for w in t["WorkPeriods"] for k in ("StartDate", "EndDate")]
    moments += [tk.get(k) for tk in t["Tickets"] for k in ("Date", "LastPaymentDate")]
    moments += [d.get("Date") for d in t.get("AccountTransactionDocuments") or []]
    moments = [m for m in moments if m]
    return stamp(max(moments)) if moments else None


def keep(con, snap):
    """Archive every work period in a snapshot. Call inside a transaction.

    Returns one line per work period: what night, what it came to, and
    whether it was new, a fuller copy of one already kept, or an older copy
    that was left alone. SambaPOS's list of accounts is brought up to date
    too, if this snapshot is the newest yet.
    """
    t = snap["tables"]
    at = as_of(snap)
    if at:
        links.refresh(con, t, at)
        catalog.refresh(con, t, at)
    periods = sorted((w for w in t["WorkPeriods"] if w.get("StartDate")),
                     key=lambda w: (w["StartDate"], w["Id"]))
    if not periods:
        return []
    menu = {m["Id"]: m for m in t["MenuItems"]}
    orders, payments, calcs, places = (defaultdict(list) for _ in range(4))
    for o in t["Orders"]:
        orders[o.get("TicketId")].append(o)
    for p in t["Payments"]:
        payments[p.get("TicketId")].append(p)
    for c in t["Calculations"]:
        calcs[c.get("TicketId")].append(c)
    for e in t["TicketEntities"]:
        if e.get("EntityName"):
            places[e.get("Ticket_Id")].append(e["EntityName"])

    # a ticket or document belongs to the last period that had started when
    # it was made
    starts = [w["StartDate"] for w in periods]

    def period_of(moment):
        return max(bisect_right(starts, moment) - 1, 0)

    tickets_of = defaultdict(list)
    for tk in t["Tickets"]:
        if tk.get("Date"):
            tickets_of[period_of(tk["Date"])].append(tk)

    docs_of = defaultdict(list)
    for d in _documents(t):
        docs_of[period_of(d["at"])].append(d)

    out = []
    for i, w in enumerate(periods):
        tks = sorted(tickets_of[i], key=lambda x: (x["Date"], x["Id"]))
        ended = w.get("EndDate") if w.get("EndDate") and w["EndDate"] > w["StartDate"] else None
        docs = sorted(docs_of[i], key=lambda d: (d["at"], d["pos_id"]))
        moments = [w["StartDate"]] + ([ended] if ended else [])
        for tk in tks:
            moments += [m for m in (tk["Date"], tk.get("LastPaymentDate")) if m]
            moments += [p["Date"] for p in payments[tk["Id"]] if p.get("Date")]
        moments += [d["at"] for d in docs]
        seen_to = stamp(max(moments))
        takings = sum(whole(p.get("Amount")) for tk in tks for p in payments[tk["Id"]])
        line = {"pos_id": w["Id"], "started_at": stamp(w["StartDate"]),
                "ended_at": stamp(ended), "night": _night(w, tks), "tickets": len(tks),
                "total": sum(whole(tk.get("TotalAmount")) for tk in tks),
                "takings": takings,
                "unpaid": sum(whole(tk.get("RemainingAmount")) for tk in tks),
                "first_at": stamp(tks[0]["Date"]) if tks else None,
                "last_at": stamp(tks[-1]["Date"]) if tks else None,
                "docs": len(docs), "seen_to": seen_to, "source": snap["source"],
                "opened_by": w.get("StartByName") or None,
                "closed_by": (w.get("EndByName") or None) if ended else None}

        old = db.one(con, "SELECT * FROM pos_period WHERE pos_id = ? AND started_at = ?",
                     (line["pos_id"], line["started_at"]))
        if old:
            # closed beats open, then later beats earlier, then more beats less
            have = (old["ended_at"] is not None, old["seen_to"], old["tickets"], old["docs"])
            new = (ended is not None, seen_to, len(tks), len(docs))
            if have > new or (have == new and old["takings"] == takings):
                # nothing fuller, but fill in what an older version of the
                # app did not keep
                _fill_in(con, old["id"], line, tks, payments)
                out.append({**line, "status": "older" if have > new else "same"})
                continue
            con.execute("DELETE FROM pos_period WHERE id = ?", (old["id"],))

        pid = con.execute(
            "INSERT INTO pos_period(pos_id, started_at, ended_at, night, tickets, total, "
            "takings, unpaid, first_at, last_at, docs, seen_to, source, opened_by, "
            "closed_by) VALUES (:pos_id, :started_at, :ended_at, :night, :tickets, :total, "
            ":takings, :unpaid, :first_at, :last_at, :docs, :seen_to, :source, :opened_by, "
            ":closed_by)", line).lastrowid
        for d in docs:
            did = con.execute(
                "INSERT INTO pos_doc(period_id, pos_id, at, kind, name, user_name) "
                "VALUES (?,?,?,?,?,?)",
                (pid, d["pos_id"], stamp(d["at"]), d["kind"], d["name"], d["user"])).lastrowid
            for ln in d["lines"]:
                con.execute(
                    "INSERT INTO pos_doc_line(doc_id, pos_id, account_id, account, "
                    "account_type, amount, drawer, reversed) VALUES (?,?,?,?,?,?,?,?)",
                    (did, ln["pos_id"], ln["account_id"], ln["account"], ln["account_type"],
                     ln["amount"], ln["drawer"], ln["reversed"]))
        for tk in tks:
            tid = con.execute(
                "INSERT INTO pos_ticket(period_id, pos_id, number, opened_at, paid_at, "
                "total, unpaid, closed, tables, note) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (pid, tk["Id"], tk.get("TicketNumber"), stamp(tk["Date"]),
                 stamp(tk.get("LastPaymentDate")) if tk.get("LastPaymentDate") and
                 tk["LastPaymentDate"] >= tk["Date"] else None,
                 whole(tk.get("TotalAmount")), whole(tk.get("RemainingAmount")),
                 1 if tk.get("IsClosed") else 0,
                 ", ".join(dict.fromkeys(places[tk["Id"]])) or None,
                 tk.get("Note") or None)).lastrowid
            for o in orders[tk["Id"]]:
                item = menu.get(o.get("MenuItemId")) or {}
                con.execute(
                    "INSERT INTO pos_order(ticket_id, pos_id, item, portion, item_group, "
                    "qty_milli, price, counted, ordered_at) VALUES (?,?,?,?,?,?,?,?,?)",
                    (tid, o["Id"], o.get("MenuItemName") or item.get("Name") or "?",
                     o.get("PortionName") or None, item.get("GroupCode") or None,
                     milli(o.get("Quantity")), whole(o.get("Price")),
                     0 if o.get("CalculatePrice") is False else 1,
                     stamp(o.get("CreatedDateTime"))))
            for p in payments[tk["Id"]]:
                con.execute("INSERT INTO pos_payment(ticket_id, pos_id, kind, amount, paid_at, "
                            "type_id) VALUES (?,?,?,?,?,?)",
                            (tid, p["Id"], p.get("Name") or "Payment", whole(p.get("Amount")),
                             stamp(p.get("Date")), p.get("PaymentTypeId")))
            for c in calcs[tk["Id"]]:
                con.execute("INSERT INTO pos_calc(ticket_id, pos_id, name, amount) "
                            "VALUES (?,?,?,?)",
                            (tid, c["Id"], c.get("Name"), whole(c.get("CalculationAmount"))))
        out.append({**line, "status": "updated" if old else "new"})
    return out


def _fill_in(con, period_id, line, tickets, payments):
    """Add to a period already kept what an older version of the app did not
    keep — who opened and closed it, each payment's type — without touching
    anything it did keep."""
    con.execute("UPDATE pos_period SET opened_by = COALESCE(opened_by, ?), "
                "closed_by = COALESCE(closed_by, ?) WHERE id = ?",
                (line["opened_by"], line["closed_by"], period_id))
    for tk in tickets:
        for p in payments[tk["Id"]]:
            if p.get("PaymentTypeId") is not None:
                con.execute("""
                    UPDATE pos_payment SET type_id = ?
                     WHERE type_id IS NULL AND pos_id = ? AND ticket_id IN
                           (SELECT id FROM pos_ticket WHERE period_id = ? AND pos_id = ?)""",
                            (p["PaymentTypeId"], p["Id"], period_id, tk["Id"]))


def _documents(t):
    """SambaPOS's account documents that are not a ticket's own, each with
    the accounts it moved money between.

    Which account is the drawer is learnt from the tickets: it is whatever
    their payments were paid into. With no payment to learn from, SambaPOS's
    own payment account type is used.
    """
    ticket_docs = {tk.get("TransactionDocument_Id") for tk in t["Tickets"]} - {None}
    accounts = {a["Id"]: a for a in t["Accounts"]}
    types = {a["Id"]: a.get("Name") for a in t["AccountTypes"]}
    doc_types = {d["Id"]: d.get("ButtonHeader") or d.get("Name")
                 for d in t["AccountTransactionDocumentTypes"]}
    reversed_ = {x["Id"] for x in t["AccountTransactions"] if x.get("IsReversed")}
    paid_tx = {p.get("AccountTransactionId") for p in t["Payments"]} - {None}
    values = defaultdict(list)
    drawer = set()
    for v in t["AccountTransactionValues"]:
        values[v.get("AccountTransactionDocumentId")].append(v)
        if v.get("AccountTransactionId") in paid_tx and (v.get("Debit") or 0) > 0:
            drawer.add(v.get("AccountId"))
    if not drawer:
        drawer = {a["Id"] for a in t["Accounts"] if a.get("AccountTypeId") == 3}

    out = []
    for d in t["AccountTransactionDocuments"]:
        if not d.get("Date") or d["Id"] in ticket_docs or not d.get("DocumentTypeId"):
            continue
        lines = []
        for v in sorted(values[d["Id"]], key=lambda v: v["Id"]):
            acc = accounts.get(v.get("AccountId")) or {}
            lines.append({"pos_id": v["Id"], "account_id": v.get("AccountId"),
                          "account": acc.get("Name") or v.get("Name") or "?",
                          "account_type": types.get(v.get("AccountTypeId")),
                          "amount": whole((v.get("Debit") or 0) - (v.get("Credit") or 0)),
                          "drawer": 1 if v.get("AccountId") in drawer else 0,
                          "reversed": 1 if v.get("AccountTransactionId") in reversed_ else 0})
        if lines:
            out.append({"pos_id": d["Id"], "at": d["Date"],
                        "kind": doc_types.get(d.get("DocumentTypeId")),
                        "name": d.get("Name"), "user": d.get("UserName"), "lines": lines})
    return out


# ------------------------------------------------------------------ reading

def _where(night=None, month=None):
    if night:
        return "p.night = ?", (night,)
    return "p.night LIKE ?", (f"{month}%",)


def items(con, *, night=None, month=None):
    """What sold, item by item: how many, and what they came to."""
    where, args = _where(night, month)
    rows = db.all_(con, f"""
        SELECT COALESCE(o.item_group, '') AS grp, o.item AS name,
               COALESCE(NULLIF(o.portion, 'Normal'), '') AS size,
               SUM(CASE WHEN o.counted THEN o.qty_milli ELSE 0 END) AS qty_milli,
               SUM(CASE WHEN o.counted THEN o.qty_milli * o.price ELSE 0 END) AS value_milli,
               SUM(CASE WHEN o.counted THEN 0 ELSE o.qty_milli END) AS free_milli
          FROM pos_order o
          JOIN pos_ticket t ON t.id = o.ticket_id
          JOIN pos_period p ON p.id = t.period_id
         WHERE {where}
         GROUP BY COALESCE(o.item_group, ''), o.item,
                  COALESCE(NULLIF(o.portion, 'Normal'), '')""", args)
    out = [{"group": r["grp"], "item": r["name"], "portion": r["size"],
            "qty": r["qty_milli"] / 1000, "value": whole(Decimal(r["value_milli"]) / 1000),
            "free": r["free_milli"] / 1000} for r in rows]
    return sorted(out, key=lambda r: (-r["value"], -r["qty"], r["item"]))


def hours(con, night):
    """Tickets opened in each hour of the night, in the order the night runs."""
    rows = db.all_(con, """
        SELECT CAST(substr(t.opened_at, 12, 2) AS INTEGER) AS h, COUNT(*) AS n,
               SUM(t.total) AS total
          FROM pos_ticket t JOIN pos_period p ON p.id = t.period_id
         WHERE p.night = ? GROUP BY h""", (night,))
    return sorted(([r["h"], r["n"], r["total"]] for r in rows),
                  key=lambda r: (r[0] - NIGHT_ENDS) % 24)


def documents(con, night):
    """Everything besides tickets that SambaPOS recorded on a night, each with
    the accounts it touched and what it did to the drawer: positive is money
    into the drawer, negative money out of it."""
    docs = db.all_(con, """
        SELECT d.* FROM pos_doc d JOIN pos_period p ON p.id = d.period_id
         WHERE p.night = ? ORDER BY d.at, d.pos_id""", (night,))
    out = []
    for d in docs:
        lines = [dict(r) for r in db.all_(con, "SELECT * FROM pos_doc_line WHERE doc_id = ? "
                                               "ORDER BY pos_id", (d["id"],))]
        live = [l for l in lines if not l["reversed"]]
        out.append({"id": d["id"], "pos_id": d["pos_id"], "at": d["at"], "kind": d["kind"],
                    "name": d["name"], "user": d["user_name"],
                    "accounts": [{"pos_id": l["account_id"], "name": l["account"],
                                  "type": l["account_type"], "amount": l["amount"]}
                                 for l in live if not l["drawer"]],
                    "drawer": sum(l["amount"] for l in live if l["drawer"]),
                    "reversed": bool(lines) and not live})
    return out


def night(con, on):
    """One night as SambaPOS recorded it, or None if it was never kept."""
    ps = db.all_(con, "SELECT * FROM pos_period WHERE night = ? ORDER BY started_at", (on,))
    ps = [p for p in ps if p["tickets"] or p["docs"]] or ps
    if not ps:
        return None
    paid = db.all_(con, """
        SELECT pp.kind, SUM(pp.amount) AS amount FROM pos_payment pp
          JOIN pos_ticket t ON t.id = pp.ticket_id
          JOIN pos_period p ON p.id = t.period_id
         WHERE p.night = ? GROUP BY pp.kind ORDER BY amount DESC""", (on,))
    off = db.scalar(con, """
        SELECT COALESCE(SUM(c.amount), 0) FROM pos_calc c
          JOIN pos_ticket t ON t.id = c.ticket_id
          JOIN pos_period p ON p.id = t.period_id
         WHERE p.night = ? AND c.amount < 0""", (on,))
    open_tickets = db.scalar(con, """
        SELECT COUNT(*) FROM pos_ticket t JOIN pos_period p ON p.id = t.period_id
         WHERE p.night = ? AND t.unpaid <> 0""", (on,))
    return {"night": on,
            "tickets": sum(p["tickets"] for p in ps),
            "total": sum(p["total"] for p in ps),
            "takings": sum(p["takings"] for p in ps),
            "unpaid": sum(p["unpaid"] for p in ps),
            "open_tickets": open_tickets,
            "discounts": -off,
            "by_kind": [[r["kind"], r["amount"]] for r in paid],
            "ended": all(p["ended_at"] for p in ps),
            "first_at": min((p["first_at"] for p in ps if p["first_at"]), default=None),
            "last_at": max((p["last_at"] for p in ps if p["last_at"]), default=None),
            "seen_to": max(p["seen_to"] for p in ps),
            "source": ps[-1]["source"],
            "kept_at": max(p["kept_at"] for p in ps),
            "opened_by": ps[0]["opened_by"],
            "closed_by": ps[-1]["closed_by"],
            "items": items(con, night=on),
            "hours": hours(con, on),
            "documents": (docs := documents(con, on)),
            "drawer_out": -sum(d["drawer"] for d in docs if d["drawer"] < 0),
            "drawer_in": sum(d["drawer"] for d in docs if d["drawer"] > 0)}


def month(con, month):
    """Every night of a month that was kept, and what sold across them."""
    rows = db.all_(con, """
        SELECT night, SUM(tickets) AS tickets, SUM(takings) AS takings,
               SUM(total) AS total, SUM(unpaid) AS unpaid
          FROM pos_period WHERE night LIKE ? AND tickets > 0
         GROUP BY night ORDER BY night""", (f"{month}%",))
    if not rows:
        return None
    return {"month": month,
            "nights": [dict(r) for r in rows],
            "tickets": sum(r["tickets"] for r in rows),
            "takings": sum(r["takings"] for r in rows),
            "items": items(con, month=month)}


def status(con):
    """How much has been kept, and when it was last added to."""
    r = db.one(con, """
        SELECT COUNT(DISTINCT night) AS nights, MIN(night) AS first, MAX(night) AS last
          FROM pos_period WHERE tickets > 0""")
    last = db.one(con, "SELECT kept_at, source, night FROM pos_period "
                       "ORDER BY kept_at DESC, id DESC LIMIT 1")
    return {"nights": r["nights"] or 0, "first": r["first"], "last": r["last"],
            "kept_at": last["kept_at"] if last else None,
            "source": last["source"] if last else None}
