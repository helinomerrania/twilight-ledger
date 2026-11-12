"""Copies of the books, and a second place to keep them.

The books are one file. A copy of that file in the same folder protects
against a bad edit or a bad update, and does nothing at all if the disk dies or
the PC is stolen — which, for a business whose only accounts are on one
computer in a cafe, is the failure that actually ends things.

So there are two layers:

  * data/backups/ on the same disk: a copy the first time the app is used each
    day, and before anything risky (an update, a restore, a change to the
    database's shape). Never pruned.
  * a second folder Mohammed chooses — a USB stick, or a folder that Google
    Drive or OneDrive syncs — which gets the same copy at the same moment.

Every copy is opened and checked before it is trusted. A backup that cannot be
read is worse than none, because it is believed.
"""
import hashlib
import shutil
import sqlite3
from datetime import date, datetime
from pathlib import Path

from . import db

_last_daily = None          # the date the daily copy was last confirmed


def _sha(path):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def verify(path):
    """Open a copy and make sure it is a sound set of these books.

    Returns (entries, postings). Raises LedgerError if it is not usable.
    """
    try:
        con = sqlite3.connect(f"file:{Path(path).resolve()}?mode=ro", uri=True)
    except sqlite3.Error as exc:
        raise db.LedgerError(f"the copy cannot be opened: {exc}") from exc
    try:
        con.row_factory = sqlite3.Row
        ok = con.execute("PRAGMA integrity_check").fetchone()[0]
        if ok != "ok":
            raise db.LedgerError(f"the copy is damaged: {ok}")
        tables = {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'")}
        if not {"entry", "posting", "account", "schema_migrations"} <= tables:
            raise db.LedgerError("that file is not a set of Twilight Ledger books")
        if con.execute("SELECT 1 FROM unbalanced LIMIT 1").fetchone():
            raise db.LedgerError("the copy does not balance")
        entries = con.execute("SELECT count(*) FROM entry").fetchone()[0]
        postings = con.execute("SELECT count(*) FROM posting").fetchone()[0]
        return entries, postings
    except sqlite3.Error as exc:
        raise db.LedgerError(f"the copy cannot be read: {exc}") from exc
    finally:
        con.close()


def folder(con):
    return db.setting(con, "backup_folder", None)


def set_folder(con, path):
    """Choose the second place. It must exist, be writable, and not be inside
    the folder the books already live in."""
    path = str(path or "").strip().strip('"')
    if not path:
        db.set_setting(con, "backup_folder", None)
        return None
    p = Path(path).expanduser()
    if not p.is_absolute():
        raise db.LedgerError("give the whole path, for example G:\\My Drive\\Twilight")
    if not p.exists() or not p.is_dir():
        raise db.LedgerError(f"there is no folder at {p}. Create it first.")
    data = db.data_dir(con.path).resolve()
    try:
        p.resolve().relative_to(data)
        raise db.LedgerError("that is inside the folder the books already live "
                             "in. The point is a copy somewhere else.")
    except ValueError:
        pass
    probe = p / ".twilight-write-test"
    try:
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise db.LedgerError(f"that folder cannot be written to: {exc}") from exc
    db.set_setting(con, "backup_folder", str(p))
    return str(p)


def run(con, why="manual"):
    """Take a copy now, check it, and put it in the second place as well."""
    try:
        dest = db.snapshot(con.path, why=why)
    except sqlite3.Error as exc:
        raise db.LedgerError(f"the copy could not be made: {exc}") from exc
    if dest is None:
        raise db.LedgerError("there are no books to copy yet")
    try:
        entries, postings = verify(dest)
    except db.LedgerError:
        # a copy that does not check out is not kept as one, or today would
        # look as if it had been backed up
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    status = {"at": datetime.now().isoformat(timespec="seconds"), "why": why,
              "file": str(dest), "entries": entries, "postings": postings,
              "second": None, "second_ok": None, "second_error": None}
    second = folder(con)
    if second:
        status["second"] = second
        try:
            target = Path(second) / dest.name
            shutil.copy2(dest, target)
            if _sha(target) != _sha(dest):
                raise OSError("the copy does not match the original")
            verify(target)
            status["second_ok"] = True
        except (OSError, db.LedgerError) as exc:
            status["second_ok"] = False
            status["second_error"] = str(exc)
    db.set_setting(con, "backup_status", status)
    return status


def daily(con):
    """One copy a day, the first time the books are used that day.

    Also retries the second place if the last attempt failed — a USB stick
    that was unplugged yesterday should not mean no outside copy this week.
    """
    global _last_daily
    today = date.today().isoformat()
    if _last_daily == today:
        return None
    out = db.backup_dir(con.path)
    have = out.exists() and any(p.name.startswith(f"twilight-{today}")
                                for p in out.glob("*.db"))
    last = db.setting(con, "backup_status", None) or {}
    retry = bool(folder(con)) and (last.get("second") != folder(con)
                                   or last.get("second_ok") is not True)
    result = None
    if not have or retry:
        result = run(con, why="daily")
    _last_daily = today
    return result


def status(con):
    out = db.backup_dir(con.path)
    files = sorted(out.glob("twilight-*.db")) if out.exists() else []
    last = db.setting(con, "backup_status", None) or {}
    second = folder(con)
    days_old = None
    if last.get("at"):
        try:
            days_old = (date.today() - datetime.fromisoformat(last["at"]).date()).days
        except ValueError:
            days_old = None
    return {"local_folder": str(out), "copies": len(files),
            "newest": files[-1].name if files else None,
            "last": last, "second": second, "days_old": days_old,
            "second_ok": bool(second) and last.get("second") == second
                         and last.get("second_ok") is True}


def copies(db_path):
    out = db.backup_dir(db_path)
    return sorted(out.glob("twilight-*.db")) if out.exists() else []


def restore(db_path, source):
    """Put a copy back as the live books.

    The copy is checked first, and the books being replaced are set aside
    before anything is overwritten, so a restore can itself be undone.
    """
    source = Path(source).expanduser()
    if not source.exists():
        raise db.LedgerError(f"there is no file at {source}")
    entries, postings = verify(source)
    target = Path(db_path).resolve()
    kept = db.snapshot(target, why="before-restore") if target.exists() else None
    target.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{source.resolve()}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(str(target))
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    verify(target)
    return {"restored_from": str(source), "entries": entries, "postings": postings,
            "previous_kept_as": str(kept) if kept else None}
