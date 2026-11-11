"""Opening the books, and keeping them openable.

One file on disk holds everything. Everything else — the code, this folder, the
whole repository — can be deleted and replaced from GitHub without touching it.
That is the point of the split: an update replaces code, never data.

Three habits make this safe rather than merely tidy:

  * WAL journalling, so a power cut mid-write leaves a consistent file. Ranya
    loses power; the books should not care.
  * foreign keys ON. SQLite leaves them off by default, per connection, which
    is the single most common way a SQLite app ends up with orphaned rows.
  * a copy set aside before every schema change, and before the first write of
    each day, kept under backups/ and never pruned automatically.
"""
import json
import os
import re
import shutil
import sqlite3
import sys
import threading
from datetime import date, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
MIGRATIONS = HERE / "migrations"
ROOT = HERE.parent

DEFAULT_DB = os.environ.get("TWILIGHT_DB") or str(ROOT / "data" / "twilight.db")


class LedgerError(RuntimeError):
    """Something is wrong with the books themselves, not with a request."""


class Books(sqlite3.Connection):
    """A connection that remembers which file it opened, so a backup or an
    error message can name it."""
    path = None


def data_dir(db_path):
    return Path(db_path).resolve().parent


def backup_dir(db_path):
    return data_dir(db_path) / "backups"


def connect(db_path=DEFAULT_DB, *, migrate=True, check=True, readonly=False):
    """Open the books. Creates them on first run."""
    path = Path(db_path).resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if readonly:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True, factory=Books)
    else:
        con = sqlite3.connect(str(path), isolation_level=None, factory=Books)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    if not readonly:
        con.execute("PRAGMA journal_mode = WAL")
        con.execute("PRAGMA synchronous = FULL")
    con.execute("PRAGMA busy_timeout = 5000")
    con.path = str(path)
    if migrate and not readonly:
        run_migrations(con)
    if check:
        assert_balanced(con)
    return con


_local = threading.local()


def thread_connection(db_path):
    """A connection belonging to the calling thread.

    SQLite objects cannot be shared between threads, and the server answers
    each request on its own. One connection per thread is the simple answer:
    WAL mode lets readers and a single writer run at the same time, and the
    writes in this app are one small transaction each, so nothing waits long.
    Migrations and the integrity check stay on the main connection, which has
    already run before any request is served.
    """
    con = getattr(_local, "con", None)
    if con is None or getattr(_local, "path", None) != str(db_path):
        if con is not None:
            try:
                con.close()
            except Exception:
                pass
        con = connect(db_path, migrate=False, check=False)
        _local.con = con
        _local.path = str(db_path)
    return con


# ---------------------------------------------------------------- migrations

def _applied(con):
    con.execute("""CREATE TABLE IF NOT EXISTS schema_migrations (
                     name TEXT PRIMARY KEY,
                     applied_at TEXT NOT NULL DEFAULT (datetime('now')),
                     sha TEXT)""")
    return {r["name"]: r["sha"] for r in con.execute(
        "SELECT name, sha FROM schema_migrations")}


def _sha(text):
    import hashlib
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


# Migrations whose wording changes in a comment and nowhere else, as
# (checksum the books recorded, checksum of the new wording). Not one statement
# differs, so books that ran the old wording have exactly the schema the new
# one describes; they are accepted and their record is brought up to date.
#
# The pair is listed here one version before the new wording ships. The
# version already installed on the PC is the one that inspects an update, so
# it has to know the new checksum in advance, or it would refuse the update as
# a rewritten migration.
REWORDED = {
    "001_core.sql": ("d9a551afe8e6d85b", "ec546572b16ecb29"),
    "002_stock.sql": ("4673199577fdb814", "30a6e0b11f5a110d"),
}


def same_migration(name, recorded, sha):
    """Is a migration with checksum `sha` the one the books recorded?"""
    return not recorded or recorded == sha or REWORDED.get(name) == (recorded, sha)


def migration_files():
    files = sorted(MIGRATIONS.glob("*.sql"))
    bad = [f.name for f in files if not re.match(r"^\d{3}_[a-z0-9_]+\.sql$", f.name)]
    if bad:
        raise LedgerError(f"migration names must look like 001_core.sql: {bad}")
    return files


def split_sql(script):
    """Split a .sql file into whole statements.

    Uses SQLite's own parser to decide where a statement ends, so a semicolon
    inside a string literal or a trigger body does not split it in the wrong
    place the way a naive text split would.
    """
    out, buf = [], ""
    for line in script.splitlines(keepends=True):
        stripped = line.strip()
        if not buf and (not stripped or stripped.startswith("--")):
            continue
        buf += line
        if sqlite3.complete_statement(buf):
            out.append(buf.strip())
            buf = ""
    if buf.strip():
        raise LedgerError("the migration ends in an unfinished statement: "
                          + buf.strip()[:80])
    return out


def run_migrations(con, *, quiet=True):
    """Apply anything new, in order, each in its own transaction.

    Forward only. A migration that has already run is never re-run and never
    edited: if its contents change on disk the mismatch is reported rather
    than silently ignored, because an edited migration means two installs with
    the same version number have different schemas.
    """
    files = migration_files()
    done = _applied(con)
    pending = [f for f in files if f.name not in done]
    for f in files:
        if f.name in done:
            sha = _sha(f.read_text(encoding="utf-8"))
            if not same_migration(f.name, done[f.name], sha):
                raise LedgerError(
                    f"{f.name} has been edited since it was applied. "
                    "Add a new migration instead of changing an old one.")
            if done[f.name] and done[f.name] != sha:
                # reworded in a comment only (REWORDED): record the new wording
                con.execute("UPDATE schema_migrations SET sha = ? WHERE name = ?",
                            (sha, f.name))
    if not pending:
        return []
    if Path(con.path).exists() and done:
        snapshot(con.path, why="before-" + pending[0].name.split("_")[0])
    applied = []
    for f in pending:
        body = f.read_text(encoding="utf-8")
        # Not executescript(): that commits any open transaction first, which
        # would make a half-applied migration possible. SQLite's DDL is
        # transactional, so the statements are run one by one inside BEGIN and
        # a failure half way through leaves the schema exactly as it was.
        try:
            con.execute("BEGIN")
            for statement in split_sql(body):
                con.execute(statement)
            con.execute("INSERT INTO schema_migrations(name, sha) VALUES (?,?)",
                        (f.name, _sha(body)))
            con.execute("COMMIT")
        except Exception as exc:
            try:
                con.execute("ROLLBACK")
            except sqlite3.OperationalError:
                pass
            raise LedgerError(f"{f.name} failed: {exc}") from exc
        applied.append(f.name)
        if not quiet:
            print(f"  applied {f.name}")
    return applied


# ------------------------------------------------------------------- backups

def snapshot(db_path=DEFAULT_DB, why="manual"):
    """Copy the books aside, using SQLite's own backup so a live write is safe."""
    src = Path(db_path).resolve()
    if not src.exists():
        return None
    out = backup_dir(db_path)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    safe = re.sub(r"[^a-zA-Z0-9._-]", "-", why)[:40]
    dest = out / f"twilight-{stamp}-{safe}.db"
    con = sqlite3.connect(f"file:{src}?mode=ro", uri=True)
    try:
        target = sqlite3.connect(str(dest))
        try:
            con.backup(target)
            # A copy is one self-contained file: without this it would be in
            # WAL mode like the live books, and merely opening it to check it
            # would leave -wal and -shm files beside it.
            target.execute("PRAGMA journal_mode=DELETE")
        finally:
            target.close()
    finally:
        con.close()
    return dest


def daily_snapshot(db_path=DEFAULT_DB):
    """One copy per day, taken the first time the app runs that day."""
    out = backup_dir(db_path)
    today = date.today().isoformat()
    if out.exists() and any(p.name.startswith(f"twilight-{today}") for p in out.glob("*.db")):
        return None
    return snapshot(db_path, why="daily")


# ------------------------------------------------------------------- guards

def assert_balanced(con):
    """Refuse to go on if any entry's postings do not cancel."""
    try:
        rows = con.execute("SELECT * FROM unbalanced LIMIT 5").fetchall()
    except sqlite3.OperationalError:
        return  # schema not built yet
    if rows:
        lines = ", ".join(
            f"entry {r['entry_id']} on {r['happened_on']} out by {r['out_by']}"
            for r in rows)
        raise LedgerError(
            "the books do not balance and will not be served: " + lines)


def integrity(con):
    """Everything worth checking before trusting a figure. Returns a report."""
    report = {}
    report["sqlite"] = [dict(r) for r in con.execute("PRAGMA integrity_check")]
    report["foreign_keys"] = [dict(r) for r in con.execute("PRAGMA foreign_key_check")]
    report["unbalanced"] = [dict(r) for r in con.execute("SELECT * FROM unbalanced")]
    report["entries"] = con.execute(
        "SELECT count(*) c FROM entry WHERE voided_at IS NULL").fetchone()["c"]
    report["postings"] = con.execute("SELECT count(*) c FROM posting").fetchone()["c"]
    report["migrations"] = [r["name"] for r in con.execute(
        "SELECT name FROM schema_migrations ORDER BY name")]
    report["ok"] = (report["sqlite"] == [{"integrity_check": "ok"}]
                    and not report["foreign_keys"]
                    and not report["unbalanced"])
    return report


# -------------------------------------------------------------------- helpers

def one(con, sql, args=()):
    r = con.execute(sql, args).fetchone()
    return r


def all_(con, sql, args=()):
    return con.execute(sql, args).fetchall()


def scalar(con, sql, args=(), default=0):
    r = con.execute(sql, args).fetchone()
    if r is None:
        return default
    v = r[0]
    return default if v is None else v


def setting(con, key, default=None):
    r = con.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return json.loads(r["value"]) if r else default


def set_setting(con, key, value):
    con.execute("INSERT INTO settings(key, value) VALUES (?,?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value, ensure_ascii=False)))


def audit(con, action, subject=None, detail=None):
    """Write the trail. `default=str` because the trail must never be the
    thing that fails a save: an unusual value is worth recording as text."""
    con.execute("INSERT INTO audit(action, subject, detail) VALUES (?,?,?)",
                (action, subject,
                 json.dumps(detail, ensure_ascii=False, default=str)
                 if detail is not None else None))


class tx:
    """A transaction. Money is only ever written inside one of these."""

    def __init__(self, con):
        self.con = con

    def __enter__(self):
        self.con.execute("BEGIN IMMEDIATE")
        return self.con

    def __exit__(self, kind, value, tb):
        if kind is None:
            # nothing commits without balancing first
            rows = self.con.execute("SELECT * FROM unbalanced LIMIT 3").fetchall()
            if rows:
                self.con.execute("ROLLBACK")
                raise LedgerError(
                    "refused to save: " + ", ".join(
                        f"entry {r['entry_id']} out by {r['out_by']}" for r in rows))
            self.con.execute("COMMIT")
        else:
            self.con.execute("ROLLBACK")
        return False
