"""Bringing in SambaPOS's own backups, without being asked.

SambaPOS writes a backup into its backup folder just before every nightly
reset, so every night already exists as a file. With that folder set in
Setup, the app looks in it when it starts, every few minutes while it is open,
and whenever a screen asks for the books, and brings in any backup it has not
read before.

Each file is read once: pos_file remembers it by name, size and time. A backup
that cannot be read is remembered too, with the reason, and is not tried again
unless the file changes. A file written in the last minute is left for next
time, because SambaPOS may still be writing it.

Nothing here can stop the app or the screens. A folder that has gone, or a
backup that is broken, is shown on Tonight and in Setup, never raised.
"""
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

from .. import db
from . import archive, sources

SETTLE = timedelta(seconds=60)   # a file this new may still be being written
STALE = timedelta(hours=30)      # one backup a night, with room for a late reset
EVERY = 300                      # seconds between looks while the app is open
GAP = 15                         # at least this many seconds between two looks

# Raised whenever reading a backup starts keeping something it did not keep
# before. Books read at a lower number read every backup in the folder once
# more, so nights kept earlier get it too (1: SambaPOS's accounts, 2: who
# opened and closed, payment types, the menu, recipes).
READS = 2
_lock = threading.Lock()         # one reader at a time, whoever asked
_wake = threading.Event()        # look now (a screen opened, or a folder was set)
_now = threading.Event()         # ... without waiting out the gap
_stop = threading.Event()

DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct",
          "Nov", "Dec")


def folder_of(con):
    return ((db.setting(con, "sambapos", {}) or {}).get("folder") or "").strip()


def when(at):
    """'Tue 10 Nov 03:12', in English whatever the PC's own language."""
    if isinstance(at, str):
        at = datetime.fromisoformat(at)
    return f"{DAYS[at.weekday()]} {at.day} {MONTHS[at.month - 1]} {at:%H:%M}"


# ------------------------------------------------------------------- files

def files_in(folder):
    """Every backup in the folder, oldest first, with what it is known by."""
    if not Path(folder).is_dir():
        raise sources.PosError(f"there is no folder at {folder} now")
    out = []
    for p in sources.backups_in(folder):
        st = p.stat()
        mtime = datetime.fromtimestamp(st.st_mtime)
        out.append({"path": p, "name": p.name, "size": st.st_size, "mtime": mtime,
                    "modified": mtime.isoformat(sep=" ", timespec="seconds"),
                    "made_at": sources.backup_time(p).isoformat(sep=" ", timespec="minutes")})
    return out


def _known(con):
    return {(r["name"], r["size"], r["modified"])
            for r in db.all_(con, "SELECT name, size, modified FROM pos_file")}


def unread(con, files, now):
    """The backups not read yet that have finished being written."""
    known = _known(con)
    return [f for f in files if (f["name"], f["size"], f["modified"]) not in known
            and now - f["mtime"] >= SETTLE]


def remember(con, f, ok, note):
    con.execute(
        "INSERT INTO pos_file(name, size, modified, made_at, ok, note) VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(name, size, modified) DO UPDATE SET ok = excluded.ok, "
        "note = excluded.note, read_at = datetime('now')",
        (f["name"], f["size"], f["modified"], f["made_at"], int(ok), note))


# --------------------------------------------------------------- reading

def run(con, *, now=None, wait=False):
    """Read every backup in SambaPOS's folder that has not been read before.

    Returns what happened: how many were read, the nights that are new or
    fuller than before, and the files that could not be read. With `wait`,
    waits for a look already under way to finish rather than skipping.
    """
    folder = folder_of(con)
    if not folder:
        return {"on": False}
    if not _lock.acquire(timeout=120 if wait else 0):
        return {"on": True, "busy": True}
    try:
        now = now or datetime.now()
        try:
            files = files_in(folder)
        except sources.PosError as exc:
            return {"on": True, "error": str(exc)}
        todo = unread(con, files, now)
        again = (db.setting(con, "sambapos_reads") or 0) < READS
        if again:
            # this version keeps more than the one that read these: once more
            todo = [f for f in files if now - f["mtime"] >= SETTLE]
        read, kept, failed = 0, [], []
        for f in todo:
            try:
                snap = sources.read_backup(f["path"])
            except OSError:
                continue            # still open in SambaPOS, or gone: next time
            except Exception as exc:                       # noqa: BLE001
                # a broken file must not stop the ones after it
                note = str(exc) if isinstance(exc, sources.PosError) \
                    else f"{type(exc).__name__}: {exc}"
                with db.tx(con):
                    remember(con, f, False, note)
                failed.append({"name": f["name"], "note": note})
                continue
            with db.tx(con):
                lines = archive.keep(con, snap)
                new = [l for l in lines if l["status"] in ("new", "updated") and l["tickets"]]
                remember(con, f, True, "; ".join(archive.describe(l) for l in new)
                          or "nothing new")
            read += 1
            kept += new
        if again and todo:
            db.set_setting(con, "sambapos_reads", READS)
        if kept:
            nights = sorted({l["night"] for l in kept})
            with db.tx(con):
                db.audit(con, "pos_keep", None, {
                    "summary": "Brought in SambaPOS's backups by itself: "
                               + "; ".join(archive.describe(l) for l in kept[-5:])
                               + (f" (and {len(nights) - 5} earlier nights)"
                                  if len(nights) > 5 else ""),
                    "source": "auto"})
        return {"on": True, "read": read, "kept": kept, "failed": failed}
    finally:
        _lock.release()


# ------------------------------------------------------------- showing

def view(con, now=None):
    """What Tonight and Setup show about the backups in SambaPOS's folder."""
    folder = folder_of(con)
    if not folder:
        return {"on": False}
    now = now or datetime.now()
    out = {"on": True, "folder": folder, "error": None, "reading": _lock.locked()}
    try:
        files = files_in(folder)
    except sources.PosError as exc:
        out["error"] = str(exc)
        files = []
    known = {(r["name"], r["size"], r["modified"]): r for r in db.all_(
        con, "SELECT name, size, modified, ok, note FROM pos_file")}
    read, failed = [], []
    for f in files:
        r = known.get((f["name"], f["size"], f["modified"]))
        if r is not None:
            (read if r["ok"] else failed).append(
                {"name": f["name"], "made_at": f["made_at"], "note": r["note"]})
    newest = read[-1] if read else None
    out.update(in_folder=len(files), read=len(read), waiting=len(unread(con, files, now)),
               newest=newest, newest_when=when(newest["made_at"]) if newest else None,
               latest=files[-1]["made_at"] if files else None,
               failed=failed[::-1][:5])
    out["problem"] = problem(out, now)
    return out


def problem(v, now):
    """None while backups are coming in as they should; otherwise what is wrong
    and what to do about it, as (detail, fix)."""
    if not v.get("on"):
        return None
    if v["error"]:
        return (v["error"], "Set the folder SambaPOS backs up to again, in Setup.")
    if not v["in_folder"]:
        return ("there are no SambaPOS backups in that folder",
                "Check it is the folder SambaPOS backs up to, in Setup.")
    if now - datetime.fromisoformat(v["latest"]) > STALE:
        return (f"the newest there is from {when(v['latest'])}, more than a day ago",
                "SambaPOS makes one just before every reset, so was the reset run? "
                "If it was, SambaPOS may now be backing up somewhere else: set the "
                "folder again in Setup.")
    newest = v["newest"]
    late = [f for f in v["failed"] if not newest or f["made_at"] >= newest["made_at"]]
    if late:
        return (f"{late[0]['name']} could not be read: {late[0]['note']}",
                "The nights in it are not kept until it reads. Send Claude the file.")
    return None


# ----------------------------------------------------------- by itself

def kick(*, at_once=False):
    """Something wants the books: look in the folder soon. A screen opening
    asks at most every GAP seconds; a newly chosen folder is looked in at
    once."""
    if at_once:
        _now.set()
    _wake.set()


def start(db_path):
    """Look now, then every few minutes, and whenever kicked. Returns the
    thread, which stops with the app."""
    _stop.clear()
    t = threading.Thread(target=_loop, args=(str(db_path),), daemon=True,
                         name="sambapos-backups")
    t.start()
    return t


def stop():
    _stop.set()
    _now.set()
    _wake.set()


def _loop(db_path):
    con = None
    try:
        while not _stop.is_set():
            _wake.clear()
            _now.clear()
            began = time.monotonic()
            try:
                con = con or db.connect(db_path, migrate=False, check=False)
                run(con)
            except Exception:                              # noqa: BLE001
                pass    # never let the loop die; the screens show what is wrong
            _wake.wait(EVERY)
            rest = GAP - (time.monotonic() - began)
            if rest > 0:
                _now.wait(rest)
    finally:
        if con is not None:
            con.close()
