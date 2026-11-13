"""The actions a screen can ask for, and the checks every one of them passes.

An action is a small function registered by name. `run` wraps each one in a
single transaction, so a half-saved night is impossible, and applies the same
guards to all of them rather than trusting each to remember:

  * an amount is a positive whole number of dinar — money back has its own
    kind of entry, so a negative amount is always a mistake
  * a date is a real date and not in the future
  * nothing may take a pot below zero without being told it is about to

The last one is the important one. Cash cannot physically be negative, so a
payment larger than the pot means either the wrong pot, a typo, or money that
came in and was never recorded. The old app let it through silently and showed
a pot below zero.
"""
import re
import sqlite3

from . import db, kinds, post, queries
from .dates import month_name, month_of, prev_month, today, ymd
from .money import to_int


class ApiError(Exception):
    """Something the person can fix. `extra` rides along in the reply so the
    screen can ask a follow-up question instead of just showing a refusal."""

    def __init__(self, message, status=400, **extra):
        super().__init__(message)
        self.status = status
        self.extra = extra


ACTIONS = {}


def action(name, *, guard_pots=True, summary=None, in_tx=True, after=None):
    """Register an action.

    summary(con, body, out) returns the line for Recent changes, written while
    the action's own transaction is still open so it can describe what it did.
    after() runs once that transaction has committed, for anything that must
    see the change from another connection.
    """
    def wrap(fn):
        ACTIONS[name] = {"fn": fn, "guard_pots": guard_pots, "summary": summary,
                         "in_tx": in_tx, "after": after}
        return fn
    return wrap


# ------------------------------------------------------------------ cleaning

def amount(body, key="amount"):
    v = to_int(body.get(key), key)
    if v == 0:
        raise ApiError("an amount is needed")
    if v < 0:
        raise ApiError("an amount cannot be negative. If money came back, "
                       "record it as money back.")
    return v


def clean_date(value, *, what="the date"):
    """A real calendar date, today or earlier."""
    if value in (None, ""):
        return today()
    try:
        d = ymd(value)
    except ValueError:
        raise ApiError(f"{what} is not a date") from None
    if d > today():
        raise ApiError(f"{what} is in the future ({d}). Entries are dated the "
                       "day the money moved.")
    if d < "2000-01-01":
        raise ApiError(f"{what} ({d}) is not a believable date")
    return d


def clean_period(body, key="period"):
    """The month an entry is tagged to, when one was chosen. None means "the
    month of its date", which is the right answer almost every time."""
    v = body.get(key)
    if v in (None, ""):
        return None
    v = str(v)
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", v):
        raise ApiError("that is not a month")
    if v > month_of(today()):
        raise ApiError("an entry cannot be counted for a month that has not started")
    return v


def pot(con, body, key="pot"):
    """The pot named in the request, or the main pot. Must be one that is
    still in use — a retired pot is not offered and cannot be paid from."""
    name = body.get(key)
    if not name:
        return post.main_pot(con)["name"]
    r = db.one(con, "SELECT name, active FROM account "
                    "WHERE kind IN ('cash', 'float') AND name = ?", (name,))
    if not r:
        raise ApiError(f"there is no pot called {name}")
    if not r["active"]:
        raise ApiError(f"{name} has been retired. Bring it back in Setup first.")
    return r["name"]


def name_of(body, key="name"):
    v = str(body.get(key) or "").strip()
    if not v:
        raise ApiError("a name is needed")
    if len(v) > 80:
        raise ApiError("that name is too long")
    return v


def who(con, body, kind, key="who"):
    """A member of staff, supplier or partner that exists."""
    name = str(body.get(key) or "").strip()
    if not name:
        raise ApiError({"staff": "pick a member of staff",
                        "supplier": "pick a supplier",
                        "partner": "pick a partner"}.get(kind, "pick who"))
    r = db.one(con, "SELECT name FROM account WHERE kind = ? AND name = ?", (kind, name))
    if not r or (kind == "partner" and not db.one(
            con, "SELECT 1 FROM account WHERE kind='partner' AND name = ? "
                 "AND code LIKE 'prt:%'", (name,))):
        raise ApiError(f"there is no {kind} called {name}")
    return r["name"]


# ------------------------------------------------------------- the pot guard

def pot_lows(con):
    """For every pot, the lowest its running balance ever reaches (never above
    zero), and the day it does."""
    lows = {}
    for p in db.all_(con, "SELECT id, code, name FROM account "
                          "WHERE kind IN ('cash', 'float')"):
        running, low, when = 0, 0, None
        for r in db.all_(con,
                "SELECT happened_on, SUM(amount) AS d FROM movement "
                "WHERE account_id = ? GROUP BY happened_on ORDER BY happened_on",
                (p["id"],)):
            running += r["d"]
            if running < low:
                low, when = running, r["happened_on"]
        lows[p["code"]] = {"name": p["name"], "low": low, "on": when,
                           "balance": running}
    return lows


def worsened(before, after):
    """Pots this action pushed further below zero than they already were."""
    out = []
    for code, a in after.items():
        b = before.get(code, {"low": 0})
        if a["low"] < 0 and a["low"] < b["low"]:
            out.append({"pot": a["name"], "short_by": -a["low"], "on": a["on"],
                        "holds": max(b.get("balance", 0), 0)})
    return out


# -------------------------------------------------------------------- running

def money_words(n):
    return f"{to_int(n):,}"


def describe_entry(con, entry_id):
    """One line for Recent changes: what, who, how much."""
    rows = queries.entries(con, ids=[entry_id])
    if not rows:
        r = db.one(con, "SELECT kind, detail FROM entry WHERE id = ?", (entry_id,))
        return f"{kinds.label(r['kind'])} {r['detail'] or ''}".strip() if r else "entry"
    e = rows[0]
    bits = [e["label"]]
    if e["detail"] and e["kind"] != "daily_sales":
        bits.append(e["detail"])
    bits.append(money_words(e["amount"]))
    if e["tagged"]:
        bits.append(f"for {e['period']}")
    return " · ".join(bits)


# How many months before the books begin a date may fall. Every month from
# the first one on is charged its rent and salaries, so a year typed wrong
# would charge a year of them, and taking the entry back would not undo it.
EARLY_MONTHS = 3


def _not_long_before(con, body):
    """Refuse a date far before the books begin: it is a slip of the year."""
    first = db.scalar(con, "SELECT MIN(month) FROM period")
    if not first or body.get("allow_early"):
        return
    limit = first
    for _ in range(EARLY_MONTHS):
        limit = prev_month(limit)
    for key in ("on", "period", "view_month"):
        value = body.get(key)
        try:
            month = ymd(value)[:7] if key == "on" else str(value or "")[:7]
        except (ValueError, TypeError):
            continue                      # not a date: the action says so itself
        if len(month) == 7 and month[:4].isdigit() and month < limit:
            raise ApiError(f"{value} is long before the books begin "
                           f"({month_name(first)}). Check the year.")


def run(con, name, body):
    spec = ACTIONS.get(name)
    if not spec:
        raise ApiError(f"no such action: {name}", 404)
    body = body or {}
    from . import accruals
    _not_long_before(con, body)
    try:
        if not spec["in_tx"]:
            return spec["fn"](con, body) or {}
        with db.tx(con):
            before = pot_lows(con) if spec["guard_pots"] else None
            out = spec["fn"](con, body) or {}
            if before is not None and not body.get("allow_overdraw"):
                short = worsened(before, pot_lows(con))
                if short:
                    s = short[0]
                    raise ApiError(
                        f"{s['pot']} does not hold that much. This would leave it "
                        f"{money_words(s['short_by'])} short on {s['on']}.",
                        status=409, overdraw=short)
            view = body.get("view_month") or month_of(today())
            accruals.ensure(con, view)
            accruals.ensure(con, month_of(today()))
            line = None
            if spec["summary"]:
                try:
                    line = spec["summary"](con, body, out)
                except Exception:                      # noqa: BLE001
                    line = None
            detail = {k: v for k, v in body.items()
                      if k not in ("pots", "view_month", "view_on", "view_count")}
            detail["summary"] = line or name.replace("_", " ")
            if isinstance(out, dict) and out.get("id"):
                detail["entry"] = out["id"]
            db.audit(con, name, None, detail)
        if spec["after"]:
            spec["after"]()
        return out
    except KeyError as exc:
        raise ApiError(f"{exc.args[0]} is needed") from exc
    except (ValueError, db.LedgerError) as exc:
        raise ApiError(str(exc)) from exc
    except sqlite3.IntegrityError as exc:
        # whatever the action forgot to check, the database did not
        raise ApiError("that would put the same thing in the books twice, so nothing "
                       "was changed") from exc
