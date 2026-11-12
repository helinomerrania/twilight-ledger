"""SambaPOS's own backups, brought in without anyone asking.

The files in these tests are stand-ins and reading them is faked: reading a
real backup's bytes is tested in test_pos.py. What is tested here is which
files are read and when, that each is read once, and what the screens are told.
"""
import os
import shutil
import tempfile
import time
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

from ledger import api, checks, db, queries
from ledger.pos import archive, auto, sources
from tests.helpers import fresh_books
from tests.test_pos import snapshot

NOW = datetime(2026, 11, 11, 20, 0)
LABEL = "SambaPOS's backups are coming in"


def night(day, *, tickets=1, pid=None):
    """A small night: `tickets` paid tickets of 6,000, opened that evening."""
    d = datetime.fromisoformat(day)
    nxt = (d + timedelta(days=1)).date().isoformat()
    pid = pid or 1000 + d.day
    rows = [{"Id": pid * 10 + i, "TicketNumber": str(i + 1), "Date": f"{day}T21:0{i}:00",
             "LastPaymentDate": f"{nxt}T00:30:00", "IsClosed": True,
             "RemainingAmount": "0", "TotalAmount": "6000"} for i in range(tickets)]
    pays = [{"Id": pid * 10 + i, "TicketId": pid * 10 + i, "Name": "Cash",
             "Date": f"{nxt}T00:30:00", "Amount": "6000"} for i in range(tickets)]
    return snapshot(periods=[{"Id": pid, "StartDate": f"{day}T12:00:00",
                              "EndDate": f"{nxt}T02:40:00"}],
                    tickets=rows, payments=pays, source="backup:stand-in")


def name_for(made):
    return f"twilight_{made:%Y%m%d%H%M}SQT.zip"


class Folder(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.dir = Path(tempfile.mkdtemp(prefix="twilight-sambapos-"))
        self.addCleanup(shutil.rmtree, self.dir, True)
        db.set_setting(self.con, "sambapos", {"folder": str(self.dir)})
        # read as this version reads: only the test of upgrading asks for less
        db.set_setting(self.con, "sambapos_reads", auto.READS)
        self.holds, self.reads = {}, []
        patcher = mock.patch.object(sources, "read_backup", self.read)
        patcher.start()
        self.addCleanup(patcher.stop)

    def read(self, path):
        name = Path(path).name
        self.reads.append(name)
        if name not in self.holds:
            raise sources.PosError(f"{name} could not be read: it is not a database backup")
        return self.holds[name]

    def backup(self, made, snap, *, written=None, size=64):
        """SambaPOS's backup made at `made`, finished writing at `written`."""
        p = self.dir / name_for(made)
        p.write_bytes(b"x" * size)
        t = (written or made + timedelta(minutes=1)).timestamp()
        os.utime(p, (t, t))
        if snap is not None:
            self.holds[p.name] = snap
        return p

    def look(self, now=NOW):
        return auto.run(self.con, now=now)

    def check(self, now=NOW):
        with mock.patch.object(auto, "datetime", wraps=datetime) as fake:
            fake.now.return_value = now
            out = [c for c in checks.checks(self.con, "2026-11") if c["label"] == LABEL]
        return out[0] if out else None

    # ------------------------------------------------------------ reading
    def test_a_new_backup_is_brought_in(self):
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        out = self.look()
        self.assertEqual(out["read"], 1)
        self.assertEqual(archive.night(self.con, "2026-11-10")["takings"], 6000)
        self.assertEqual([l["night"] for l in out["kept"]], ["2026-11-10"])

    def test_and_only_once(self):
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        self.look()
        self.look(NOW + timedelta(hours=1))
        self.assertEqual(len(self.reads), 1)

    def test_one_still_being_written_is_left_for_next_time(self):
        made = datetime(2026, 11, 11, 19, 59)
        self.backup(made, night("2026-11-10"), written=NOW - timedelta(seconds=10))
        self.assertEqual(self.look()["read"], 0)
        self.assertEqual(self.look(NOW + timedelta(minutes=2))["read"], 1)

    def test_one_that_changed_is_read_again(self):
        made = datetime(2026, 11, 11, 3, 0)
        self.backup(made, night("2026-11-10"))
        self.look()
        self.backup(made, night("2026-11-10", tickets=2), size=99)
        self.look()
        self.assertEqual(len(self.reads), 2)
        self.assertEqual(archive.night(self.con, "2026-11-10")["takings"], 12000)

    def test_an_older_one_put_in_the_folder_later_is_read_too(self):
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        self.look()
        self.backup(datetime(2026, 11, 9, 3, 0), night("2026-11-08"))
        self.assertEqual(self.look()["read"], 1)
        self.assertIsNotNone(archive.night(self.con, "2026-11-08"))

    def test_a_broken_backup_is_noted_and_not_tried_again(self):
        self.backup(datetime(2026, 11, 11, 3, 0), None)
        out = self.look()
        self.assertEqual([f["name"] for f in out["failed"]],
                         ["twilight_202611110300SQT.zip"])
        self.look(NOW + timedelta(hours=1))
        self.assertEqual(len(self.reads), 1)

    def test_a_broken_one_does_not_stop_the_ones_after_it(self):
        self.backup(datetime(2026, 11, 10, 3, 0), None)
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        self.assertEqual(self.look()["read"], 1)

    def test_a_file_that_is_still_locked_is_tried_again(self):
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        with mock.patch.object(sources, "read_backup", side_effect=PermissionError("in use")):
            self.assertEqual(self.look()["read"], 0)
        self.assertEqual(self.look()["read"], 1)

    def test_nights_brought_in_together_are_one_line_in_recent_changes(self):
        for day in ("2026-11-08", "2026-11-09", "2026-11-10"):
            made = datetime.fromisoformat(day) + timedelta(days=1, hours=3)
            self.backup(made, night(day))
        self.look()
        lines = [r["summary"] for r in queries.recent(self.con)
                 if "SambaPOS" in r["summary"]]
        self.assertEqual(len(lines), 1)
        self.assertIn("by itself", lines[0])
        self.assertIn("2026-11-10", lines[0])

    def test_nothing_happens_without_a_folder(self):
        db.set_setting(self.con, "sambapos", {"folder": ""})
        self.assertEqual(auto.run(self.con), {"on": False})
        self.assertIsNone(self.check())

    def test_backups_read_by_an_older_version_are_read_once_more(self):
        """An older version kept less from each backup: SambaPOS's accounts,
        who opened and closed, payment types. Every backup in the folder is
        read once more, so the nights kept before have it too."""
        snap = night("2026-11-09")
        snap["tables"]["Accounts"] = [{"Id": 5, "Name": "Cash", "AccountTypeId": 3}]
        self.backup(datetime(2026, 11, 10, 3, 0), snap)
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        self.look()
        self.con.execute("DELETE FROM pos_account")
        self.con.execute("DELETE FROM settings WHERE key = 'sambapos_accounts_at'")
        db.set_setting(self.con, "sambapos_reads", 1)
        self.assertEqual(self.look()["read"], 2)
        self.assertEqual(db.scalar(self.con, "SELECT name FROM pos_account"), "Cash")
        self.assertEqual(self.look()["read"], 0)
        self.assertEqual(len(self.reads), 4)

    # ------------------------------------------------------------ telling
    def test_a_backup_from_last_night_is_all_right(self):
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        self.look()
        c = self.check()
        self.assertTrue(c["ok"])
        self.assertEqual(c["detail"], "the newest is from Wed 11 Nov 03:00")

    def test_tonight_says_when_the_newest_is_more_than_a_day_old(self):
        self.backup(datetime(2026, 11, 9, 3, 0), night("2026-11-08"))
        self.look()
        c = self.check()
        self.assertFalse(c["ok"])
        self.assertIn("Mon 9 Nov 03:00, more than a day ago", c["detail"])
        self.assertIn("was the reset run?", c["fix"])
        self.assertEqual(c["go"], "setup/sambapos")

    def test_a_late_reset_is_not_a_missing_one(self):
        self.backup(datetime(2026, 11, 10, 15, 0), night("2026-11-09"))
        self.look()
        self.assertTrue(self.check()["ok"])

    def test_a_newest_backup_that_will_not_read_is_pointed_out(self):
        self.backup(datetime(2026, 11, 10, 3, 0), night("2026-11-09"))
        self.backup(datetime(2026, 11, 11, 3, 0), None)
        self.look()
        c = self.check()
        self.assertFalse(c["ok"])
        self.assertIn("twilight_202611110300SQT.zip could not be read", c["detail"])

    def test_an_empty_folder_is_pointed_out(self):
        c = self.check()
        self.assertFalse(c["ok"])
        self.assertIn("no SambaPOS backups in that folder", c["detail"])

    def test_a_folder_that_has_gone_is_shown_not_raised(self):
        db.set_setting(self.con, "sambapos", {"folder": str(self.dir / "unplugged")})
        self.assertIn("no folder", auto.run(self.con)["error"])
        self.assertIn("no folder", self.check()["detail"])
        state = api.state(self.con)
        self.assertIn("no folder", state["pos"]["auto"]["error"])

    def test_the_screens_are_told_what_is_still_to_read(self):
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        v = auto.view(self.con, NOW)
        self.assertEqual((v["in_folder"], v["waiting"], v["read"]), (1, 1, 0))
        self.look()
        v = auto.view(self.con, NOW)
        self.assertEqual((v["waiting"], v["read"]), (0, 1))
        self.assertEqual(v["newest"]["name"], "twilight_202611110300SQT.zip")

    # ------------------------------------------------------------ buttons
    def test_look_now_reads_what_is_new(self):
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        out = api.run(self.con, "pos_auto", {})
        self.assertEqual(out["read"], 1)

    def test_look_now_without_a_folder_says_so(self):
        db.set_setting(self.con, "sambapos", {"folder": ""})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "pos_auto", {})

    def test_reading_everything_again_remembers_each_file(self):
        self.backup(datetime(2026, 11, 10, 3, 0), night("2026-11-09"))
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        api.run(self.con, "pos_folder", {})
        self.assertEqual(self.look()["read"], 0)
        self.assertEqual(len(self.reads), 2)

    def test_choosing_a_folder_asks_for_a_look_straight_away(self):
        auto._wake.clear()
        auto._now.clear()
        api.run(self.con, "pos_settings", {"folder": str(self.dir)})
        self.assertTrue(auto._wake.is_set() and auto._now.is_set())

    def test_the_folder_on_screen_is_the_one_that_counts(self):
        """A backup read from another folder says nothing about this one."""
        self.backup(datetime(2026, 11, 11, 3, 0), night("2026-11-10"))
        self.look()
        other = self.dir / "older"
        other.mkdir()
        old = other / name_for(datetime(2026, 11, 7, 3, 0))
        old.write_bytes(b"x")
        t = datetime(2026, 11, 7, 3, 1).timestamp()
        os.utime(old, (t, t))
        db.set_setting(self.con, "sambapos", {"folder": str(other)})
        c = self.check()
        self.assertFalse(c["ok"])
        self.assertIn("Sat 7 Nov 03:00", c["detail"])


class ByItself(unittest.TestCase):
    """The reader the app starts: it looks straight away, and again when asked."""

    def test_it_reads_a_backup_without_being_asked(self):
        con = fresh_books()
        folder = Path(tempfile.mkdtemp(prefix="twilight-sambapos-"))
        self.addCleanup(shutil.rmtree, folder, True)
        db.set_setting(con, "sambapos", {"folder": str(folder)})
        made = datetime.now() - timedelta(hours=2)
        p = folder / name_for(made)
        p.write_bytes(b"x")
        t = (made + timedelta(minutes=1)).timestamp()
        os.utime(p, (t, t))
        snap = night("2026-11-10")
        with mock.patch.object(sources, "read_backup", return_value=snap):
            thread = auto.start(con.path)
            try:
                for _ in range(100):
                    if db.scalar(con, "SELECT COUNT(*) FROM pos_file"):
                        break
                    time.sleep(0.05)
            finally:
                auto.stop()
                thread.join(5)
        self.assertFalse(thread.is_alive())
        self.assertIsNotNone(archive.night(con, "2026-11-10"))


if __name__ == "__main__":
    unittest.main()
