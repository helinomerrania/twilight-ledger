"""A night from SambaPOS, turned into the entries it becomes in the books.

Every line SambaPOS recorded on a night — the takings, and each expense,
advance or owner withdrawal — becomes the entry it would be if it were typed on
Tonight, by way of what its SambaPOS account is linked to (links.py) and which
way the money moved. `plan` says what each would be and whether it is in the
books already; `add` posts the ones that are not, all in one transaction.

An entry made here carries source 'pos' and a reference to the SambaPOS line
it came from. So a night added twice adds nothing twice, an entry deleted by
hand is not brought back, and a line SambaPOS reversed is never added.

During the change-over, nights are still typed by hand as well. So a line is
only added when the books hold nothing typed by hand of the same kind, for
the same person or expense, that night. When they do and the amounts agree,
the line is already in the books; when they do not, it is left for Mohammed
to put right, because adding it would count the money twice.
"""
import json
from collections import defaultdict

from .. import db, post
from . import archive, links

ENTRY = {  # (what the account is, which way the money went) -> entry kind
    ("expense", "out"): "daily_expense",
    ("staff", "out"): "staff_advance",
    ("staff", "in"): "staff_repayment",
    ("partner", "out"): "partner_draw",
    ("partner", "in"): "partner_in",
    ("supplier", "out"): "supplier_payment",
    ("income", "in"): "other_income",
}
KINDS = set(ENTRY.values()) | {"transfer", "daily_sales"}


def _pots(con):
    return {r["id"]: r["name"] for r in db.all_(
        con, "SELECT id, name FROM account WHERE kind IN ('cash', 'float')")}


def _names(con):
    return {r["id"]: r["name"] for r in db.all_(con, "SELECT id, name FROM account")}


def _stamp(at):
    return "".join(ch for ch in str(at or "") if ch.isdigit())[:14]


def _drawer_pot(con, linked, pots):
    """The pot the night's takings go into: the one SambaPOS's drawer is
    linked to. Which SambaPOS account is the drawer is known from the
    documents; failing that, the main pot."""
    for r in db.all_(con, "SELECT DISTINCT account_id FROM pos_doc_line "
                          "WHERE drawer = 1 AND account_id IS NOT NULL"):
        link = linked.get(r["account_id"])
        if link and link["as_what"] == "pot" and link["account_id"] in pots:
            return pots[link["account_id"]]
    return post.main_pot(con)["name"]


def _lines_of(con, doc_id):
    return [dict(r) for r in db.all_(con, "SELECT * FROM pos_doc_line WHERE doc_id = ? "
                                          "AND reversed = 0 ORDER BY pos_id", (doc_id,))]


def _from_document(con, d, linked, pots, names):
    """What one SambaPOS document is in the books: a list of entries, or the
    reason it cannot be added by itself."""
    base = {"at": d["at"], "what": d["kind"] or d["name"], "pos_doc": d["pos_id"]}
    lines = _lines_of(con, d["id"])
    if not lines:
        return [{**base, "status": "skip", "words": "reversed in SambaPOS", "amount": 0,
                 "account": None}]
    lines = [l for l in lines if l["amount"]]
    if not lines:
        # entered by mistake with no amount: nothing moved
        return [{**base, "status": "skip", "words": "no amount in SambaPOS", "amount": 0,
                 "account": None}]
    unlinked = [l for l in lines if l["account_id"] not in linked]
    if unlinked:
        held = []
        for l in unlinked:
            known = links.account(con, l["account_id"]) or {
                "pos_id": l["account_id"], "name": l["account"]}
            held.append({**base, "status": "held", "amount": abs(l["amount"]),
                         "account": {"pos_id": l["account_id"], "name": l["account"],
                                     "type": l["account_type"], "link": None,
                                     "suggest": links.suggest(con, known,
                                                              drawer=bool(l["drawer"]))},
                         "words": "needs linking"})
        return held
    pot_lines = [l for l in lines if linked[l["account_id"]]["as_what"] == "pot"]
    others = [l for l in lines if linked[l["account_id"]]["as_what"] not in ("pot", "ignore")]

    def acct(l):
        return {"pos_id": l["account_id"], "name": l["account"], "type": l["account_type"],
                "link": links._described(con, linked[l["account_id"]])}

    ref = f"pos:doc:{d['pos_id']}:{_stamp(d['at'])}"
    if not others and len(pot_lines) == 2:
        frm = min(pot_lines, key=lambda l: l["amount"])
        to = max(pot_lines, key=lambda l: l["amount"])
        a, b = pots.get(linked[frm["account_id"]]["account_id"]), pots.get(
            linked[to["account_id"]]["account_id"])
        if a and b and a != b and to["amount"] > 0:
            return [{**base, "ref": ref, "kind": "transfer", "detail": a, "pot": a, "to": b,
                     "amount": to["amount"], "account": acct(to), "status": "new",
                     "words": f"Moved from {a} to {b}"}]
        if a and a == b:
            return [{**base, "status": "skip", "amount": to["amount"], "account": acct(to),
                     "words": f"both sides are {a} in the books"}]
    if not others:
        return [{**base, "status": "skip", "amount": sum(abs(l["amount"]) for l in lines) // 2,
                 "account": acct(lines[0]) if lines else None,
                 "words": "left out, as linked"}]
    if len(pot_lines) != 1 or pots.get(linked[pot_lines[0]["account_id"]]["account_id"]) is None:
        return [{**base, "status": "manual", "amount": abs(o["amount"]), "account": acct(o),
                 "words": "SambaPOS moved this between accounts that are not one pot "
                          "and one other: enter it by hand"} for o in others]
    pot = pots[linked[pot_lines[0]["account_id"]]["account_id"]]
    out = []
    for o in others:
        link = linked[o["account_id"]]
        way = "out" if o["amount"] > 0 else "in"
        kind = ENTRY.get((link["as_what"], way))
        line = {**base, "amount": abs(o["amount"]), "account": acct(o), "pot": pot}
        if kind is None:
            out.append({**line, "status": "manual",
                        "words": f"money {'out to' if way == 'out' else 'in from'} "
                                 f"{links.WORDS[link['as_what']].lower()}: enter it by hand"})
            continue
        detail = link["detail"] if link["as_what"] in links.LIST_KINDS \
            else names.get(link["account_id"], "?")
        out.append({**line, "status": "new", "kind": kind, "detail": detail,
                    "ref": ref if len(others) == 1 else f"{ref}:{o['pos_id']}",
                    "words": f"{_label(kind)} · {detail}, "
                             f"{'out of' if way == 'out' else 'into'} {pot}"})
    return out


def _label(kind):
    from ..kinds import LABELS
    return LABELS.get(kind, kind)


def _books(con, on):
    """The night's entries in the books that a SambaPOS line could be."""
    marks = ",".join("?" * len(KINDS))
    rows = db.all_(con, f"""
        SELECT e.id, e.kind, e.detail, e.source, e.source_ref, e.voided_at, e.replaced_by,
               (SELECT SUM(p.amount) FROM posting p WHERE p.entry_id = e.id
                 AND p.amount > 0) AS amount
          FROM entry e WHERE e.happened_on = ? AND e.kind IN ({marks})""",
        (on, *sorted(KINDS)))
    return [dict(r) for r in rows]


def _takings(con, on, night, linked, pots):
    """The night's takings as sales lines: one for each way of paying, each
    into the pot its SambaPOS account is linked to — cash into the drawer's
    pot, a card or transfer into the bank's — so the count compares cash with
    cash. With one way of paying it is the single line it always was."""
    base = {"at": None, "what": "Takings", "kind": "daily_sales",
            "detail": "Total sales of the day", "account": None}
    drawer = _drawer_pot(con, linked, pots)
    takings = night["takings"]
    if takings <= 0:
        return [{**base, "amount": takings, "pot": drawer, "status": "skip",
                 "words": "nothing was paid"}]
    types = {r["pos_id"]: json.loads(r["data"]) for r in db.all_(
        con, "SELECT pos_id, data FROM pos_catalog WHERE kind = 'payment_type'")}
    groups = db.all_(con, """
        SELECT pp.type_id, pp.kind, SUM(pp.amount) AS amount FROM pos_payment pp
          JOIN pos_ticket t ON t.id = pp.ticket_id
          JOIN pos_period p ON p.id = t.period_id
         WHERE p.night = ? GROUP BY pp.type_id, pp.kind ORDER BY amount DESC""", (on,))
    # payments kept before their types were: one line into the drawer, as
    # it always was
    untyped = [g for g in groups if g["type_id"] is None]
    groups = [g for g in groups if g["type_id"] is not None]
    if untyped:
        groups.append({"type_id": None, "kind": "",
                       "amount": sum(g["amount"] for g in untyped)})
    lines = []
    for g in groups:
        if not g["amount"]:
            continue
        line = {**base, "amount": g["amount"], "payment": g["kind"]}
        acct = (types.get(g["type_id"]) or {}).get("Account_Id")
        if acct is None:
            line.update(pot=drawer, status="new")
        elif acct not in linked:
            known = links.account(con, acct) or {"pos_id": acct, "name": g["kind"]}
            was_drawer = bool(db.scalar(con, "SELECT 1 FROM pos_doc_line WHERE account_id = ? "
                                             "AND drawer = 1 LIMIT 1", (acct,)))
            line.update(pot=None, status="held", words="needs linking", account={
                "pos_id": acct, "name": known["name"], "type": known.get("type_name"),
                "link": None, "suggest": links.suggest(con, known, drawer=was_drawer)})
        elif linked[acct]["as_what"] == "pot" and linked[acct]["account_id"] in pots:
            line.update(pot=pots[linked[acct]["account_id"]], status="new")
        else:
            line.update(pot=None, status="manual",
                        words=f"paid by {g['kind']}, which is not money in a pot: "
                              "enter it by hand")
        lines.append(line)
    one = len(lines) == 1
    for l in lines:
        if l["status"] == "new":
            l["ref"] = (f"pos:sales:{on}:{l['amount']}" if one
                        else f"pos:sales:{on}:{l['payment']}:{l['amount']}")
            l["words"] = (f"Sales, into {l['pot']}" if one
                          else f"Sales by {l['payment']}, into {l['pot']}")
    return lines


def plan(con, on):
    """Every line SambaPOS recorded on the night of `on`, as the entry it
    becomes, and whether it is in the books already. None if no night was
    kept for that day."""
    night = archive.night(con, on)
    if not night:
        return None
    linked = links.links(con)
    pots, names = _pots(con), _names(con)
    books = _books(con, on)
    by_ref = {b["source_ref"]: b for b in books if b["source"] == "pos" and b["source_ref"]}
    lines = []

    # the takings. Takings added from SambaPOS before, when less of the night
    # was in, are replaced; takings typed by hand are not touched — Use, on
    # Tonight, is the way to replace those on purpose
    takings = night["takings"]
    sales_lines = _takings(con, on, night, linked, pots)
    refs = {l.get("ref") for l in sales_lines}
    other_sales = [b for b in books if b["kind"] == "daily_sales" and not b["voided_at"]
                   and b["source_ref"] not in refs]
    typed_sales = [b for b in other_sales if b["source"] != "pos"]
    lines += sales_lines

    docs = db.all_(con, """
        SELECT d.* FROM pos_doc d JOIN pos_period p ON p.id = d.period_id
         WHERE p.night = ? ORDER BY d.at, d.pos_id""", (on,))
    for d in docs:
        lines += _from_document(con, d, linked, pots, names)

    # what is already in the books: added before, or typed by hand
    hand = defaultdict(list)
    for b in books:
        if b["source"] == "manual" and not b["voided_at"] and b["kind"] != "daily_sales":
            hand[(b["kind"], b["detail"])].append(b)
    ours = defaultdict(list)
    for line in lines:
        if line.get("status") != "new":
            continue
        had = by_ref.get(line["ref"])
        if had and not had["voided_at"]:
            line["status"] = "added"
            if (had["amount"] or 0) != line["amount"]:
                line["note"] = f"the books have {had['amount']:,}"
        elif had and had["replaced_by"]:
            line["status"] = "added"
            line["note"] = "corrected by hand in the books"
        elif had:
            line["status"] = "deleted"
        elif line["kind"] != "daily_sales":
            ours[(line["kind"], line["detail"])].append(line)
    for key, group in ours.items():
        typed = hand.pop(key, [])
        if not typed:
            continue
        mine = [l["amount"] for l in group]
        theirs = [b["amount"] for b in typed]
        if sorted(mine) == sorted(theirs):
            for l in group:
                l["status"] = "typed"
        elif sum(mine) == sum(theirs):
            # the same money, split differently
            for l in group:
                l["status"] = "typed"
                l["note"] = f"entered by hand as {sum(theirs):,} in all"
        else:
            for l in group:
                l["status"] = "check"
                l["note"] = ("entered by hand as " + ", ".join(f"{a:,}" for a in theirs)
                             + ": put one of them right")
    new_sales = [l for l in sales_lines if l["status"] == "new"]
    if new_sales and typed_sales:
        hand_total = sum(b["amount"] or 0 for b in typed_sales)
        for l in new_sales:
            l["status"] = "typed" if hand_total == takings else "check"
        if hand_total != takings:
            new_sales[0]["note"] = (f"entered by hand as {hand_total:,}. To make "
                                    "SambaPOS's figure the sales, use it in step 1")
    elif new_sales and other_sales:
        new_sales[0]["replaces"] = sum(b["amount"] or 0 for b in other_sales)
    only_books = [{"id": b["id"], "kind": b["kind"], "label": _label(b["kind"]),
                   "detail": b["detail"], "amount": b["amount"]}
                  for group in hand.values() for b in group]
    return {"night": on, "lines": lines, "books_only": only_books,
            "held": sum(1 for l in lines if l["status"] == "held"),
            "to_add": sum(1 for l in lines if l["status"] == "new")}


def add(con, p):
    """Post every line of a plan that is new. Call inside a transaction."""
    on, n = p["night"], 0
    sales = [l for l in p["lines"] if l.get("kind") == "daily_sales"]
    replaced, takings = [], None
    if any(l["status"] == "new" for l in sales):
        # replace takings added from SambaPOS before, never ones typed by hand
        # (the plan holds new takings back while there are any)
        keep = {l["ref"] for l in sales if l["status"] == "added"}
        for e in db.all_(con, "SELECT id, source_ref FROM entry WHERE happened_on = ? AND "
                              "kind = 'daily_sales' AND source = 'pos' AND voided_at IS NULL",
                         (on,)):
            if e["source_ref"] not in keep:
                post.void(con, e["id"], why="replaced by a fuller copy of the night")
                replaced.append(e["id"])
    for line in p["lines"]:
        if line["status"] != "new":
            continue
        src = {"source": "pos", "source_ref": line["ref"]}
        kind, amount, pot, detail = line["kind"], line["amount"], line["pot"], line["detail"]
        if kind == "daily_sales":
            eid = post.sales(con, amount, on=on, into=pot, **src)
            takings = takings or eid
        elif kind == "daily_expense":
            post.daily_expense(con, amount, detail=detail, on=on, out_of=pot, **src)
        elif kind == "staff_advance":
            post.staff_advance(con, amount, staff=detail, on=on, out_of=pot, **src)
        elif kind == "staff_repayment":
            post.staff_repay(con, amount, staff=detail, on=on, into=pot, **src)
        elif kind == "partner_draw":
            post.partner_draw(con, amount, partner=detail, on=on, out_of=pot, **src)
        elif kind == "partner_in":
            post.partner_in(con, amount, partner=detail, on=on, into=pot, **src)
        elif kind == "supplier_payment":
            post.pay_supplier(con, amount, supplier=detail, on=on, out_of=pot, **src)
        elif kind == "other_income":
            post.other_income(con, amount, detail=detail, on=on, into=pot, **src)
        elif kind == "transfer":
            post.transfer(con, amount, frm=pot, to=line["to"], on=on, **src)
        else:
            continue
        n += 1
    # what they replaced is not put back beside them
    for rid in replaced:
        con.execute("UPDATE entry SET replaced_by = ? WHERE id = ?", (takings, rid))
    return n
