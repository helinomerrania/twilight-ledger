"""Copies of the books: made, checked, put somewhere else, and put back."""
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from ledger import api, backup, checks, db
from ledger.dates import month_of, today
from tests.helpers import fresh_books

NOW = month_of(today())
DAY = f"{NOW}-01"


def entries(con):
    return db.scalar(con, "SELECT count(*) FROM entry")


class Copies(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 1000, "on": DAY})
        self.away = Path(tempfile.mkdtemp(prefix="twilight-away-"))

    def tearDown(self):
        shutil.rmtree(self.away, ignore_errors=True)

    def test_a_copy_is_opened_and_checked_before_it_is_trusted(self):
        out = backup.run(self.con)
        self.assertTrue(Path(out["file"]).exists())
        self.assertEqual(backup.verify(out["file"]), (out["entries"], out["postings"]))
        self.assertEqual(out["entries"], entries(self.con))

    def test_the_second_folder_gets_the_same_copy(self):
        backup.set_folder(self.con, str(self.away))
        out = backup.run(self.con)
        self.assertTrue(out["second_ok"])
        self.assertTrue((self.away / Path(out["file"]).name).exists())
        self.assertTrue(backup.status(self.con)["second_ok"])

    def test_choosing_the_folder_puts_a_copy_there_at_once(self):
        out = api.run(self.con, "backup_folder", {"folder": str(self.away)})
        self.assertTrue(out["backup"]["second_ok"])
        self.assertEqual(len(list(self.away.glob("twilight-*.db"))), 1)
        ok = {c["label"]: c["ok"] for c in checks.checks(self.con, NOW)}
        self.assertTrue(ok["The books have a copy somewhere else"])

    def test_a_folder_that_has_gone_is_reported_not_hidden(self):
        backup.set_folder(self.con, str(self.away))
        shutil.rmtree(self.away)
        out = backup.run(self.con)
        self.assertFalse(out["second_ok"])
        self.assertTrue(out["second_error"])
        ok = {c["label"]: c["ok"] for c in checks.checks(self.con, NOW)}
        self.assertFalse(ok["The books have a copy somewhere else"])


class SecondFolder(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def refused(self, path):
        with self.assertRaises(db.LedgerError):
            backup.set_folder(self.con, path)
        self.assertIsNone(backup.folder(self.con))

    def test_a_path_that_is_not_whole_is_refused(self):
        self.refused("Twilight backups")

    def test_a_folder_that_does_not_exist_is_refused(self):
        self.refused(str(Path(tempfile.gettempdir()) / "no-such-folder-for-twilight"))

    def test_the_books_own_folder_is_not_somewhere_else(self):
        self.refused(str(db.data_dir(self.con.path)))

    def test_it_can_be_cleared(self):
        away = Path(tempfile.mkdtemp(prefix="twilight-away-"))
        try:
            backup.set_folder(self.con, str(away))
            backup.set_folder(self.con, "")
            self.assertIsNone(backup.folder(self.con))
        finally:
            shutil.rmtree(away, ignore_errors=True)


class Restore(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        api.run(self.con, "sales", {"amount": 1000, "on": DAY})
        self.copy = backup.run(self.con)
        api.run(self.con, "expense", {"amount": 250, "detail": "Ice", "on": DAY})
        self.later = entries(self.con)
        self.path = self.con.path
        self.con.close()

    def test_a_copy_is_put_back_and_the_books_it_replaces_are_kept(self):
        out = backup.restore(self.path, self.copy["file"])
        con = db.connect(self.path)
        try:
            self.assertEqual(entries(con), self.copy["entries"])
        finally:
            con.close()
        self.assertEqual(backup.verify(out["previous_kept_as"])[0], self.later)

    def test_a_file_that_is_not_books_is_refused_and_nothing_changes(self):
        junk = Path(tempfile.mkdtemp(prefix="twilight-junk-")) / "junk.db"
        c = sqlite3.connect(junk)
        c.execute("CREATE TABLE x (y)")
        c.commit()
        c.close()
        with self.assertRaises(db.LedgerError):
            backup.restore(self.path, junk)
        con = db.connect(self.path)
        try:
            self.assertEqual(entries(con), self.later)
        finally:
            con.close()
        shutil.rmtree(junk.parent, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
