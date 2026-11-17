"""What the screens can ask of the SambaPOS archive.

Reading a backup or SambaPOS's database can take a few seconds, so those
actions run outside the books' transaction and open their own short one only
to keep what they read. None of them changes the books: using a night's
takings as its sales goes through the ordinary `sales` action.
"""
from pathlib import Path

from .. import db
from ..money import half_up
from ..registry import ApiError, action, clean_date
from ..words import t
from . import adding, archive, auto, catalog, links, sources, uses

DEFAULTS = {"folder": "", "server": "localhost", "database": "twilight"}


def settings(con):
    return {**DEFAULTS, **(db.setting(con, "sambapos", {}) or {})}


def _menu(con):
    """The menu, each portion with what one costs to make beside its price."""
    m = catalog.menu(con)
    costs = uses.costs(con)
    for g in m["groups"]:
        for it in g["items"]:
            c = costs.get(it["id"])
            for p in it["portions"]:
                p["cost"] = half_up(c) if c is not None else None
    return m


def _month(con, month):
    m = archive.month(con, month)
    if m:
        m["items"] = uses.costed(con, m["items"])
    return m


def view(con, on, month):
    """Everything the screens show about SambaPOS."""
    return {"settings": settings(con),
            "can_read_live": sources.available(),
            "windows_user": sources.windows_user(),
            "status": archive.status(con),
            "catalog": catalog.counts(con),
            "menu": _menu(con),
            "auto": auto.view(con),
            "night": archive.night(con, on),
            "adding": adding.plan(con, on) if on else None,
            "month": _month(con, month),
            "accounts": links.listing(con),
            "targets": links.targets(con),
            "gone": links.gone_but_here(con),
            "uses": uses.view(con)}


def keep(con, snap, why):
    """Keep a snapshot in one transaction, and say what happened."""
    with db.tx(con):
        lines = archive.keep(con, snap)
        kept = [l for l in lines if l["status"] in ("new", "updated") and l["tickets"]]
        if kept:
            db.audit(con, "pos_keep", None, {
                "summary": t("change.pos_kept", why, "; ".join(archive.describe(l) for l in kept)),
                "source": snap["source"]})
    return lines


def _fail(exc):
    raise ApiError(str(exc)) from exc


# once saved, look in a newly chosen folder straight away — after the commit,
# or the reader's own connection would still see the old folder
@action("pos_settings", guard_pots=False,
        summary=lambda con, body, out: t("change.pos_settings"),
        after=lambda: auto.kick(at_once=True))
def _pos_settings(con, body):
    s = settings(con)
    for key in ("folder", "server", "database"):
        if key in body:
            s[key] = str(body[key] or "").strip().strip('"')
    if s["folder"]:
        p = Path(s["folder"]).expanduser()
        if not p.is_absolute():
            raise ApiError(t("backup.whole_path", t("pos.example_path")))
        if not p.is_dir():
            raise ApiError(t("pos.no_folder", p))
    db.set_setting(con, "sambapos", s)
    return {}


def _pos_id(body):
    try:
        return int(body.get("pos_id"))
    except (TypeError, ValueError):
        raise ApiError(t("pos.which_account")) from None


def _link_line(con, body, out):
    a = links.account(con, _pos_id(body))
    return t("change.pos_linked", a["name"] if a else t("change.pos_account"),
             out.get("label") or t("change.pos_the_books"))


@action("pos_link", guard_pots=False, summary=_link_line)
def _pos_link(con, body):
    """Say what a SambaPOS account is in the books, or change it."""
    return links.link(con, _pos_id(body), body.get("to"))


def _left_line(con, body, out):
    who = out.get("name") or t("change.someone")
    if body.get("left_on"):
        return t("change.pos_left_on", who, body["left_on"])
    return t("change.pos_left", who)


@action("pos_left", guard_pots=False, summary=_left_line)
def _pos_left(con, body):
    """SambaPOS no longer has an account for someone: they have left."""
    from ..setup import _account_active
    link = db.one(con, "SELECT * FROM pos_link WHERE pos_id = ?", (_pos_id(body),))
    if not link or link["as_what"] not in ("staff", "partner", "supplier"):
        raise ApiError(t("pos.not_linked"))
    out = _account_active(con, {"id": link["account_id"], "active": 0,
                                "left_on": body.get("left_on")})
    name = db.scalar(con, "SELECT name FROM account WHERE id = ?", (link["account_id"],))
    return {"name": name, "note": out["note"]}


@action("pos_told", guard_pots=False,
        summary=lambda con, body, out: t("change.pos_told"))
def _pos_told(con, body):
    """The reminder to remove someone who left from SambaPOS has been seen."""
    con.execute("UPDATE pos_link SET told = 1 WHERE pos_id = ?", (_pos_id(body),))
    return {}


def _night_line(con, body, out):
    n = out.get("added", 0)
    return t("change.pos_night_one" if n == 1 else "change.pos_night", out.get("night"), n)


@action("pos_add_night", summary=_night_line)
def _pos_add_night(con, body):
    """Every line SambaPOS recorded on a night that is not in the books yet,
    added as the entries they are, in one go. The pot guard asks as usual."""
    on = clean_date(body.get("on"))
    p = adding.plan(con, on)
    if p is None:
        raise ApiError(t("pos.not_kept", on))
    if p["held"]:
        raise ApiError(t("pos.link_first_one" if p["held"] == 1 else "pos.link_first", p["held"]))
    if not p["to_add"]:
        raise ApiError(t("pos.all_in"))
    return {"added": adding.add(con, p), "night": on}


@action("pos_auto", guard_pots=False, in_tx=False)
def _pos_auto(con, body):
    """Look in SambaPOS's backup folder now, and bring in anything not read."""
    out = auto.run(con, wait=True)
    if not out.get("on"):
        raise ApiError(t("pos.choose_folder"))
    if out.get("error"):
        raise ApiError(out["error"])
    return out


@action("pos_folder", guard_pots=False, in_tx=False)
def _pos_folder(con, body):
    """Read every backup in the folder again, oldest first, whether it was
    read before or not. Bringing one in twice changes nothing, so this is safe
    to run whenever."""
    try:
        files = auto.files_in(settings(con)["folder"])
    except sources.PosError as exc:
        _fail(exc)
    lines, failed = [], []
    for f in files:
        try:
            snap = sources.read_backup(f["path"])
        except sources.PosError as exc:
            failed.append(str(exc))
            with db.tx(con):
                auto.remember(con, f, False, str(exc))
            continue
        lines += keep(con, snap, t("pos.kept_from", f["name"]))
        with db.tx(con):
            auto.remember(con, f, True, t("pos.read_again"))
    return {"files": len(files), "kept": lines, "failed": failed}


@action("pos_live", guard_pots=False, in_tx=False)
def _pos_live(con, body):
    """Read SambaPOS's database as it stands now and keep it."""
    s = settings(con)
    try:
        snap = sources.read_live(s["server"], s["database"])
    except sources.PosError as exc:
        _fail(exc)
    return {"kept": keep(con, snap, t("pos.kept_live"))}


@action("pos_test", guard_pots=False, in_tx=False)
def _pos_test(con, body):
    s = settings(con)
    try:
        return {"probe": sources.test_live(s["server"], s["database"])}
    except sources.PosError as exc:
        _fail(exc)
