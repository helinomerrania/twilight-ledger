"""Updating the app without touching the books.

Each test installs a copy of the app in a temporary folder, with its own books
in data/, and updates that copy from a zip built the way GitHub builds one. No
network, and the real app folder is never written to.
"""
import io
import os
import shutil
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

from ledger import api, db, update
from ledger.dates import month_of, today
from tests.helpers import seed

ROOT = Path(__file__).resolve().parent.parent
DAY = f"{month_of(today())}-01"
TOP = "twilight-ledger-main"


def github_zip(version="2099.1.1", *, extra=None, drop=(), change=None):
    """The app as GitHub hands it over: everything inside one top folder."""
    change = change or {}
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for d in update.MANAGED_DIRS:
            for f in sorted((ROOT / d).rglob("*")) if (ROOT / d).exists() else []:
                if not f.is_file() or "__pycache__" in f.parts:
                    continue
                rel = f.relative_to(ROOT).as_posix()
                if rel in drop:
                    continue
                z.writestr(f"{TOP}/{rel}", change.get(rel, f.read_bytes()))
        for name in update.MANAGED_FILES:
            if name == "VERSION":
                z.writestr(f"{TOP}/VERSION", version + "\n")
            elif (ROOT / name).exists():
                z.writestr(f"{TOP}/{name}", (ROOT / name).read_bytes())
        for rel, data in (extra or {}).items():
            z.writestr(f"{TOP}/{rel}", data)
    return buf.getvalue()


class Update(unittest.TestCase):
    def setUp(self):
        self.app = Path(tempfile.mkdtemp(prefix="twilight-app-"))
        for d in update.MANAGED_DIRS:
            if (ROOT / d).exists():
                shutil.copytree(ROOT / d, self.app / d,
                                ignore=shutil.ignore_patterns("__pycache__"))
        for name in update.MANAGED_FILES:
            if (ROOT / name).exists():
                shutil.copy2(ROOT / name, self.app / name)
        (self.app / "VERSION").write_text("2026.1.1\n", encoding="utf-8")
        self.con = db.connect(self.app / "data" / "twilight.db")
        seed(self.con)
        api.run(self.con, "sales", {"amount": 1000, "on": DAY})
        self.entries = db.scalar(self.con, "SELECT count(*) FROM entry")
        self.post_py = (self.app / "ledger" / "post.py").read_bytes()

    def tearDown(self):
        self.con.close()
        shutil.rmtree(self.app, ignore_errors=True)

    def refused(self, zip_bytes):
        with self.assertRaises(db.LedgerError) as cm:
            update.apply(zip_bytes, self.con, root=self.app)
        self.assertEqual(update.current(self.app), "2026.1.1")
        self.assertEqual((self.app / "ledger" / "post.py").read_bytes(), self.post_py)
        return str(cm.exception)

    def test_an_update_replaces_the_code_and_not_the_books(self):
        out = update.apply(github_zip(), self.con, root=self.app)
        self.assertEqual(update.current(self.app), "2099.1.1")
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM entry"), self.entries)
        self.assertTrue(Path(out["books_copy"]).exists())
        self.assertTrue(zipfile.is_zipfile(out["old_code"]))
        leftovers = [p.name for p in self.app.iterdir()
                     if p.name.startswith((".old-", ".update-"))]
        self.assertEqual(leftovers, [])

    def test_the_old_code_is_kept_whole(self):
        out = update.apply(github_zip(), self.con, root=self.app)
        with zipfile.ZipFile(out["old_code"]) as z:
            self.assertEqual(z.read("ledger/post.py"), self.post_py)
            self.assertEqual(z.read("VERSION").decode().strip(), "2026.1.1")

    def test_a_download_carrying_books_is_refused(self):
        self.assertIn("data folder", self.refused(github_zip(extra={"data/twilight.db": b"x"})))

    def test_a_download_that_rewrote_a_migration_is_refused(self):
        msg = self.refused(github_zip(change={"ledger/migrations/001_core.sql": b"-- other"}))
        self.assertIn("001_core.sql", msg)

    def test_a_download_with_a_migration_reworded_in_a_comment_is_accepted(self):
        """The updater installed on the PC must let the new wording through."""
        for name, (before, _after) in db.REWORDED.items():
            self.con.execute("UPDATE schema_migrations SET sha = ? WHERE name = ?",
                             (before, name))
        change = {f"ledger/migrations/{n}": reworded(n).encode("utf-8") for n in NEW_WORDING}
        update.apply(github_zip(change=change), self.con, root=self.app)
        self.assertEqual(update.current(self.app), "2099.1.1")

    def test_a_download_that_lost_a_migration_is_refused(self):
        self.refused(github_zip(drop=("ledger/migrations/004_corrections.sql",)))

    def test_a_download_with_broken_code_is_refused(self):
        self.assertIn("broken", self.refused(github_zip(change={"ledger/post.py": b"def ("})))

    def test_a_download_that_climbs_out_of_the_folder_is_refused(self):
        self.assertIn("unsafe", self.refused(github_zip(extra={"../outside.py": b""})))

    def test_something_that_is_not_this_app_is_refused(self):
        self.refused(github_zip(drop=("web/index.html",)))

    def test_the_same_version_is_not_installed_again(self):
        self.refused(github_zip("2026.1.1"))

    def test_a_swap_that_fails_half_way_puts_everything_back(self):
        real = Path.rename

        def flaky(self_, target):
            if Path(self_).name == "web" and ".update-staging" in Path(self_).parts:
                raise OSError("the folder is open in another program")
            return real(self_, target)

        with mock.patch.object(Path, "rename", flaky):
            msg = self.refused(github_zip())
        self.assertIn("left as it was", msg)
        self.assertTrue((self.app / "web" / "index.html").exists())
        self.assertFalse((self.app / ".update-staging").exists())
        self.assertEqual([p.name for p in self.app.iterdir() if p.name.startswith(".old")], [])

    def test_check_asks_the_address_it_is_given(self):
        (self.app / "latest").write_text("2099.1.1\n", encoding="utf-8")
        url = (self.app / "latest").as_uri()
        with mock.patch.dict(os.environ, {"TWILIGHT_UPDATE_VERSION": url}):
            info = update.check(self.app)
        self.assertEqual((info["current"], info["latest"], info["newer"]),
                         ("2026.1.1", "2099.1.1", True))


# The new wording of two old migrations, by line number. Only comments change:
# the old wording named a supplier and quoted a real count, and this
# repository is public. The installed app must accept the new wording before
# it ships (db.REWORDED), so these lines are fixed here and must match it.
NEW_WORDING = {
    "001_core.sql": {
        19: "  code      TEXT    NOT NULL UNIQUE,            -- 'cash:box', 'sup:star-store'"},
    "002_stock.sql": {
        68: "-- Counted amounts are held as thousandths, because Mohammed counts in",
        69: "-- fractions: a sheet can have 12.4 blocks of a tobacco and 0.1 of a packet",
        70: "-- of filters. Whole-number columns would quietly drop the .4 — 200 grams of",
        71: "-- tobacco — every time a line was saved."},
}


def reworded(name):
    rows = (db.MIGRATIONS / name).read_text(encoding="utf-8").split("\n")
    for n, line in NEW_WORDING[name].items():
        rows[n - 1] = line
    return "\n".join(rows)


class Reworded(unittest.TestCase):
    """An old migration can change its comments, and nothing else, without
    the app refusing to open its books or to update."""

    def test_the_new_wording_is_the_one_listed(self):
        self.assertEqual(sorted(NEW_WORDING), sorted(db.REWORDED))
        for name in NEW_WORDING:
            self.assertEqual(db._sha(reworded(name)), db.REWORDED[name][1], name)

    def test_not_one_statement_changes(self):
        def code(text):
            return [line.split("--")[0].rstrip() for line in text.split("\n")]
        for name in NEW_WORDING:
            old = (db.MIGRATIONS / name).read_text(encoding="utf-8")
            self.assertEqual(code(old), code(reworded(name)),
                             f"{name} changes more than a comment")
            self.assertEqual(len(db.split_sql(old)), len(db.split_sql(reworded(name))))

    def test_books_that_ran_the_old_wording_open_and_record_the_new(self):
        tmp = Path(tempfile.mkdtemp(prefix="twilight-reworded-"))
        try:
            con = db.connect(tmp / "books.db")
            for name, (before, _after) in db.REWORDED.items():
                con.execute("UPDATE schema_migrations SET sha = ? WHERE name = ?",
                            (before, name))
            con.close()
            moved = tmp / "migrations"
            shutil.copytree(db.MIGRATIONS, moved)
            for name in NEW_WORDING:
                (moved / name).write_text(reworded(name), encoding="utf-8")
            with mock.patch.object(db, "MIGRATIONS", moved):
                con = db.connect(tmp / "books.db")
            recorded = {r["name"]: r["sha"] for r in
                        con.execute("SELECT name, sha FROM schema_migrations")}
            con.close()
            for name, (_before, after) in db.REWORDED.items():
                self.assertEqual(recorded[name], after)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_any_other_change_is_still_refused(self):
        tmp = Path(tempfile.mkdtemp(prefix="twilight-reworded-"))
        try:
            db.connect(tmp / "books.db").close()
            moved = tmp / "migrations"
            shutil.copytree(db.MIGRATIONS, moved)
            (moved / "002_stock.sql").write_text(reworded("002_stock.sql") + "\n-- more",
                                                 encoding="utf-8")
            with mock.patch.object(db, "MIGRATIONS", moved):
                with self.assertRaises(db.LedgerError):
                    db.connect(tmp / "books.db")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)



if __name__ == "__main__":
    unittest.main()
