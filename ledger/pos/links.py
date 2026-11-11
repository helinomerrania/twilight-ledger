"""What each SambaPOS account is in the books.

SambaPOS records an expense, a staff advance and an owner taking cash the same
way: money moved from the drawer to one of its own accounts. Which of those it
was depends on the account. So every SambaPOS account money moves to or from
is linked once to what it is in the books — an expense, a member of staff, a
partner, a supplier, other income or a pot — or left out.

A link is by SambaPOS's number for the account, never by its name, so a
rename in SambaPOS changes nothing but the name shown. Names are only used to
suggest a link, and only when the match is plain: the same name in the books,
or an account SambaPOS no longer has that was linked under the same name
(deleted and made again, so it has a new number).

Nothing here posts anything. Turning a night's documents into entries is done
from these links when a night is added (plan step 1.3).
"""
import json
import re

from .. import db
from ..registry import ApiError

ACCOUNT_KINDS = {"staff": ("staff",), "partner": ("partner",),
                 "supplier": ("supplier",), "pot": ("cash", "float")}
LIST_KINDS = {"expense": "expense", "income": "income"}
WORDS = {"expense": "Expense", "income": "Other income", "staff": "Staff",
         "partner": "Partner", "supplier": "Supplier", "pot": "Pot",
         "ignore": "Left out"}


def plain(name):
    return re.sub(r"\s+", " ", str(name or "")).strip().casefold()


# ------------------------------------------------------------ the accounts

def refresh(con, tables, at):
    """Bring the list of SambaPOS's accounts up to date from a snapshot made
    at `at`. An older snapshot than the newest one used changes nothing: its
    names may be out of date, and an account missing from it is not gone."""
    accounts = tables.get("Accounts") or []
    if not accounts:
        return
    last = db.setting(con, "sambapos_accounts_at")
    if last and at < last:
        return
    types = {t["Id"]: t.get("Name") for t in tables.get("AccountTypes") or []}
    for a in accounts:
        con.execute(
            "INSERT INTO pos_account(pos_id, name, type_id, type_name, seen_at, gone) "
            "VALUES (?,?,?,?,?,0) ON CONFLICT(pos_id) DO UPDATE SET name = excluded.name, "
            "type_id = excluded.type_id, type_name = excluded.type_name, "
            "seen_at = excluded.seen_at, gone = 0",
            (a["Id"], a.get("Name") or f"account {a['Id']}", a.get("AccountTypeId"),
             types.get(a.get("AccountTypeId")), at))
    marks = ",".join("?" * len(accounts))
    con.execute(f"UPDATE pos_account SET gone = 1 WHERE pos_id NOT IN ({marks})",
                [a["Id"] for a in accounts])
    db.set_setting(con, "sambapos_accounts_at", at)


# ---------------------------------------------------------------- choices

def targets(con):
    """What a SambaPOS account can be, as groups of (value, label) for a
    picker. Only what is in use in the books is offered."""
    lists = {k: [r["value"] for r in db.all_(con,
                 "SELECT value FROM pick_list WHERE list = ? AND active = 1 "
                 "ORDER BY sort, value", (k,))] for k in LIST_KINDS.values()}

    def accounts(kinds):
        marks = ",".join("?" * len(kinds))
        return db.all_(con, f"SELECT id, name FROM account WHERE kind IN ({marks}) "
                            "AND active = 1 ORDER BY sort, name", kinds)
    return [
        {"group": "Expense", "options": [[f"expense:{v}", v] for v in lists["expense"]]},
        {"group": "Staff", "options": [[f"staff:{a['id']}", a["name"]]
                                       for a in accounts(("staff",))]},
        {"group": "Partner", "options": [[f"partner:{a['id']}", a["name"]]
                                         for a in accounts(("partner",))]},
        {"group": "Supplier", "options": [[f"supplier:{a['id']}", a["name"]]
                                          for a in accounts(("supplier",))]},
        {"group": "Other income", "options": [[f"income:{v}", v] for v in lists["income"]]},
        {"group": "Pot", "options": [[f"pot:{a['id']}", a["name"]]
                                     for a in accounts(("cash", "float"))]},
    ]


def value_of(link):
    if link["as_what"] == "ignore":
        return "ignore"
    if link["as_what"] in LIST_KINDS:
        return f"{link['as_what']}:{link['detail']}"
    return f"{link['as_what']}:{link['account_id']}"


def _described(con, link):
    """A link as the screens show it: its value, its words, and whether it
    points at someone who has left."""
    out = {"value": value_of(link), "as": link["as_what"], "name_then": link["name_then"],
           "told": bool(link["told"]), "left": False}
    if link["as_what"] in ACCOUNT_KINDS:
        a = db.one(con, "SELECT name, active FROM account WHERE id = ?", (link["account_id"],))
        name = a["name"] if a else "?"
        out["left"] = bool(a) and not a["active"]
    else:
        name = link["detail"]
    out["name"] = name
    out["label"] = WORDS[link["as_what"]] + (f" · {name}" if name else "")
    return out


def parse(con, value, pos_name):
    """'staff:12', 'expense:Ice', 'new-expense' or 'ignore', checked against
    the books, as (as_what, account_id, detail)."""
    value = str(value or "").strip()
    if value == "ignore":
        return "ignore", None, None
    if value == "new-expense":
        name = re.sub(r"\s+", " ", str(pos_name or "")).strip()[:80]
        if not name:
            raise ApiError("this account has no name to use")
        sort = db.scalar(con, "SELECT COALESCE(MAX(sort), 0) + 1 FROM pick_list "
                              "WHERE list = 'expense'")
        con.execute("INSERT INTO pick_list(list, value, sort) VALUES ('expense', ?, ?) "
                    "ON CONFLICT(list, value) DO UPDATE SET active = 1", (name, sort))
        return "expense", None, name
    kind, _, rest = value.partition(":")
    if kind in LIST_KINDS:
        if not db.one(con, "SELECT 1 FROM pick_list WHERE list = ? AND value = ?",
                      (LIST_KINDS[kind], rest)):
            raise ApiError(f"{rest} is not on the {WORDS[kind].lower()} list")
        return kind, None, rest
    if kind in ACCOUNT_KINDS:
        try:
            aid = int(rest)
        except ValueError:
            raise ApiError("pick what this is in the books") from None
        a = db.one(con, "SELECT kind FROM account WHERE id = ?", (aid,))
        if not a or a["kind"] not in ACCOUNT_KINDS[kind]:
            raise ApiError("that is not in the books")
        return kind, aid, None
    raise ApiError("pick what this is in the books")


def link(con, pos_id, value):
    """Say once what a SambaPOS account is in the books, or change it."""
    acct = account(con, pos_id)
    if acct is None:
        raise ApiError("SambaPOS has no such account in anything kept here")
    as_what, aid, detail = parse(con, value, acct["name"])
    con.execute(
        "INSERT INTO pos_link(pos_id, as_what, account_id, detail, name_then) "
        "VALUES (?,?,?,?,?) ON CONFLICT(pos_id) DO UPDATE SET as_what = excluded.as_what, "
        "account_id = excluded.account_id, detail = excluded.detail, "
        "name_then = excluded.name_then, linked_at = datetime('now'), told = 0",
        (pos_id, as_what, aid, detail, acct["name"]))
    return _described(con, db.one(con, "SELECT * FROM pos_link WHERE pos_id = ?", (pos_id,)))


def account(con, pos_id):
    """One SambaPOS account: from its newest list, or failing that from the
    last document that used it."""
    a = db.one(con, "SELECT pos_id, name, type_name, gone FROM pos_account WHERE pos_id = ?",
               (pos_id,))
    if a:
        return dict(a)
    line = db.one(con, "SELECT account AS name, account_type AS type_name FROM pos_doc_line "
                       "WHERE account_id = ? ORDER BY id DESC LIMIT 1", (pos_id,))
    return {"pos_id": pos_id, "name": line["name"], "type_name": line["type_name"],
            "gone": 0} if line else None


# ------------------------------------------------------------- suggesting

def _books_names(con):
    """Every name in the books an account could plainly be, by its plain form."""
    out = {}
    for kind, kinds in ACCOUNT_KINDS.items():
        marks = ",".join("?" * len(kinds))
        for a in db.all_(con, f"SELECT id, name FROM account WHERE kind IN ({marks}) "
                              "AND active = 1", kinds):
            out.setdefault(plain(a["name"]), []).append(f"{kind}:{a['id']}")
    for kind, lst in LIST_KINDS.items():
        for r in db.all_(con, "SELECT value FROM pick_list WHERE list = ? AND active = 1",
                         (lst,)):
            out.setdefault(plain(r["value"]), []).append(f"{kind}:{r['value']}")
    return out


def suggest(con, acct, *, names=None, drawer=False):
    """A link that is plain from the name, or None. Never a guess."""
    names = names if names is not None else _books_names(con)
    same = names.get(plain(acct["name"])) or []
    if len(same) == 1:
        return same[0]
    # deleted in SambaPOS and made again: a new number, the old name
    old = db.all_(con, """
        SELECT l.* FROM pos_link l JOIN pos_account a ON a.pos_id = l.pos_id
         WHERE a.gone = 1 AND l.pos_id <> ? AND l.as_what <> 'ignore'""", (acct["pos_id"],))
    old = [l for l in old if plain(l["name_then"]) == plain(acct["name"])]
    if len({value_of(l) for l in old}) == 1:
        return value_of(old[0])
    if drawer:
        pot = db.one(con, "SELECT id FROM account WHERE kind = 'cash' AND active = 1 "
                          "ORDER BY sort, id LIMIT 1")
        if pot:
            return f"pot:{pot['id']}"
    return None


# ---------------------------------------------------------------- showing

def links(con):
    return {r["pos_id"]: r for r in db.all_(con, "SELECT * FROM pos_link")}


def listing(con):
    """Every SambaPOS account worth linking: those money has moved through,
    those already linked, and the rest of the accounts of the same kinds
    SambaPOS still has, so a new one can be linked before it is first used."""
    used = {r["account_id"]: r for r in db.all_(con, """
        SELECT l.account_id, COUNT(*) AS n, MAX(d.at) AS last_at, MAX(l.drawer) AS drawer,
               MAX(l.account) AS name, MAX(l.account_type) AS type_name
          FROM pos_doc_line l JOIN pos_doc d ON d.id = l.doc_id
         WHERE l.reversed = 0 AND l.account_id IS NOT NULL
         GROUP BY l.account_id""")}
    linked = links(con)
    known = {r["pos_id"]: dict(r) for r in db.all_(con, "SELECT * FROM pos_account")}
    kinds = {known[i]["type_id"] for i in used if i in known} - {None}
    wanted = set(used) | set(linked) | {i for i, a in known.items()
                                        if a["type_id"] in kinds and not a["gone"]}
    names = _books_names(con)
    out = []
    for pid in wanted:
        a = known.get(pid) or {"pos_id": pid, "name": used[pid]["name"] if pid in used else "?",
                               "type_name": used[pid]["type_name"] if pid in used else None,
                               "type_id": None, "gone": 0}
        u = used.get(pid)
        row = {"pos_id": pid, "name": a["name"], "type": a["type_name"],
               "gone": bool(a["gone"]), "used": u["n"] if u else 0,
               "last_at": u["last_at"] if u else None, "drawer": bool(u and u["drawer"]),
               "link": _described(con, linked[pid]) if pid in linked else None,
               "suggest": None}
        if not row["link"]:
            row["suggest"] = suggest(con, a, names=names, drawer=row["drawer"])
        out.append(row)
    return sorted(out, key=lambda r: (r["type"] or "", not r["drawer"], -r["used"],
                                      plain(r["name"])))


def left_but_used(con):
    """People marked as left in the books whom SambaPOS has recorded money for
    since, and nobody has yet been reminded to remove from SambaPOS."""
    out = []
    for r in db.all_(con, """
        SELECT l.pos_id, a.name AS books_name, a.meta, p.name AS pos_name,
               MAX(d.at) AS last_at
          FROM pos_link l
          JOIN account a ON a.id = l.account_id
          JOIN pos_doc_line dl ON dl.account_id = l.pos_id AND dl.reversed = 0
          JOIN pos_doc d ON d.id = dl.doc_id
          LEFT JOIN pos_account p ON p.pos_id = l.pos_id
         WHERE a.active = 0 AND l.told = 0 AND l.as_what IN ('staff', 'partner', 'supplier')
         GROUP BY l.pos_id"""):
        meta = json.loads(r["meta"] or "{}")
        last = r["last_at"] or ""
        # the day they were marked as left, or failing that the month
        since = meta.get("retired_on")
        if since and last[:10] <= since:
            continue
        if not since and meta.get("left_after") and last[:7] <= meta["left_after"]:
            continue
        out.append({"pos_id": r["pos_id"], "books_name": r["books_name"],
                    "pos_name": r["pos_name"] or r["books_name"], "last_at": last})
    return out


def gone_but_here(con):
    """People SambaPOS no longer has an account for, who are still active in
    the books: perhaps they have left."""
    return [dict(r) for r in db.all_(con, """
        SELECT l.pos_id, l.account_id, a.name AS books_name, p.name AS pos_name, l.as_what
          FROM pos_link l
          JOIN pos_account p ON p.pos_id = l.pos_id
          JOIN account a ON a.id = l.account_id
         WHERE p.gone = 1 AND a.active = 1 AND l.as_what IN ('staff', 'partner', 'supplier')
         ORDER BY a.name""")]
