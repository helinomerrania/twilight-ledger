"""The server itself, over real HTTP: who it answers, what it refuses, and that
a change it has saved is never reported as failed because something after
the save went wrong. Everything here is invented."""
import http.client
import json
import threading
import unittest
from http.server import ThreadingHTTPServer
from unittest import mock

from ledger import api, backup, queries, server
from tests.helpers import fresh_books

ON = "2026-11-09"


class Server(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        api.bootstrap(self.con)
        server.Handler.db_path = self.con.path
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def ask(self, method, path, body=None, **headers):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        data = json.dumps(body).encode() if body is not None else None
        if data is not None:
            headers.setdefault("Content-Type", "application/json")
        c.request(method, path, body=data, headers=headers)
        r = c.getresponse()
        raw = r.read()
        c.close()
        try:
            return r.status, json.loads(raw)
        except ValueError:
            return r.status, raw

    def expense(self, **headers):
        return self.ask("POST", "/api/do/expense", {"amount": 5000, "detail": "Ice", "on": ON,
                                                    "allow_overdraw": True}, **headers)

    def saved(self):
        return len(queries.entries(self.con, on=ON, kind="daily_expense"))

    # ------------------------------------------------------------- who it answers
    def test_it_answers_on_localhost(self):
        status, out = self.ask("GET", "/api/health")
        self.assertEqual((status, out["ok"]), (200, True))

    def test_not_under_any_other_name(self):
        status, _ = self.ask("GET", "/api/health", Host="books.example.com")
        self.assertEqual(status, 403)
        status, _ = self.expense(Host="books.example.com")
        self.assertEqual((status, self.saved()), (403, 0))

    def test_a_write_from_another_site_is_refused(self):
        status, _ = self.expense(Origin="https://example.com")
        self.assertEqual((status, self.saved()), (403, 0))

    def test_a_write_that_is_not_json_is_refused(self):
        status, _ = self.expense(**{"Content-Type": "text/plain"})
        self.assertEqual((status, self.saved()), (403, 0))

    def test_a_page_older_than_the_app_is_told_to_load_again(self):
        # left open across an update, its screens are the old ones
        status, out = self.expense(**{"X-Twilight-Version": "2020.1.1.1"})
        self.assertEqual((status, out.get("reload"), self.saved()), (409, True, 0))
        status, _ = self.expense(**{"X-Twilight-Version": server.update.current()})
        self.assertEqual((status, self.saved()), (200, 1))

    def test_a_refused_write_ends_its_connection(self):
        # its body is never read, so it must not be taken for the next request
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/do/expense", body=b'{"amount": 5000}',
                  headers={"Content-Type": "text/plain"})
        r = c.getresponse()
        r.read()
        self.assertEqual((r.status, r.getheader("Connection")), (403, "close"))
        c.close()

    def test_each_screen_file_says_what_it_is_whatever_windows_thinks(self):
        """Told by Windows' registry that a stylesheet or a script is plain
        text, the server said so, and a browser told not to guess refused it:
        the screens came up bare, or blank."""
        with mock.patch("mimetypes.guess_type", return_value=("text/plain", None)):
            for path, kind in (("/app.css", "text/css"), ("/app.js", "text/javascript"),
                               ("/", "text/html"), ("/lang/en.json", "application/json")):
                c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
                c.request("GET", path)
                r = c.getresponse()
                r.read()
                c.close()
                self.assertEqual(r.getheader("Content-Type").split(";")[0], kind, path)

    def test_nothing_outside_the_screens_folder_is_served(self):
        for path in ("/../ledger/db.py", "/..%2fledger%2fdb.py", "/lang/../../twilight.py"):
            status, _ = self.ask("GET", path)
            self.assertEqual(status, 404, path)

    def test_an_unknown_endpoint(self):
        self.assertEqual(self.ask("GET", "/api/nothing")[0], 404)
        self.assertEqual(self.ask("POST", "/api/nothing", {})[0], 404)

    def test_started_again_it_finds_itself_rather_than_run_twice(self):
        here = server.running_at(self.port, self.con.path)
        self.assertEqual(here, f"http://127.0.0.1:{self.port}/")
        self.assertIsNone(server.running_at(self.port, self.con.path + "-other"))

    def test_the_books_are_not_replaced_under_the_open_app(self):
        """Restored from the command line while the app was open, the books
        changed under it: old code against books a newer version had changed,
        and screens on books that were no longer there."""
        import twilight
        copy = backup.run(self.con, why="test")["file"]
        api.run(self.con, "sales", {"amount": 5000, "on": ON})
        with mock.patch.object(server, "PORT", self.port):
            self.assertEqual(twilight.main(["--db", self.con.path, "restore", copy, "--yes"]), 1)
        self.assertEqual(queries.day(self.con, ON)["sales"], 5000)      # still there

    # ------------------------------------------------------------------ saving
    def test_a_save_comes_back_with_the_new_state(self):
        status, out = self.expense()
        self.assertEqual((status, self.saved()), (200, 1))
        self.assertIn("state", out)
        self.assertNotIn("warning", out)

    def test_a_refusal_saves_nothing(self):
        status, out = self.ask("POST", "/api/do/expense", {"amount": 5000, "on": ON})
        self.assertEqual((status, self.saved()), (400, 0))
        self.assertIn("error", out)

    def test_a_failed_copy_of_the_books_does_not_unsay_a_save(self):
        with mock.patch.object(backup, "daily", side_effect=OSError("No space left on device")):
            status, out = self.expense()
        self.assertEqual((status, self.saved()), (200, 1))
        self.assertIn("state", out)
        self.assertIn("No space left on device", out["warning"])

    def test_nor_does_a_screen_that_could_not_be_brought_up_to_date(self):
        with mock.patch.object(api, "state", side_effect=RuntimeError("a query failed")):
            status, out = self.expense()
        self.assertEqual((status, self.saved()), (200, 1))
        self.assertNotIn("state", out)
        self.assertTrue(out["warning"].startswith("Saved, but"))

    # ------------------------------------------------- what a screen asks to see
    def test_a_night_or_month_that_cannot_be_shown_is_said_plainly(self):
        """A year typed as 0001 in the night's date box stopped the screen
        with 'OverflowError: date value out of range'."""
        for path, said in (
                ("/api/state?on=0001-01-01", "the date (0001-01-01) is not a believable date"),
                ("/api/state?on=2026-02-30", "2026-02-30 is not a date"),
                ("/api/state?on=275760-01-01", "275760-01-01 is not a date"),
                ("/api/state?count_date=9999-12-31",
                 "the date (9999-12-31) is not a believable date"),
                ("/api/state?month=2026-13", "that is not a month"),
                ("/api/state?month=0000-01", "that is not a month"),
                ("/api/supplier?id=1&month=x", "that is not a month"),
                ("/api/close?month=2026-13", "that is not a month")):
            status, out = self.ask("GET", path)
            self.assertEqual((status, out.get("error")), (400, said), path)
        status, out = self.ask("GET", "/api/state?on=2026-11-02&month=2026-10")
        self.assertEqual((status, out["day"]["on"], out["month"]), (200, "2026-11-02", "2026-10"))

    def test_odd_figures_in_an_address_are_not_a_crash(self):
        for path, status in (("/api/entries?limit=abc", 200), ("/api/entries?limit=%C2%B2", 200),
                             ("/api/supplier?id=abc&month=2026-11", 404), ("/api/close", 200)):
            self.assertEqual(self.ask("GET", path)[0], status, path)

    def test_a_long_code_in_the_search_box(self):
        """A number past 19 digits (a code scanned into the search) stopped the
        search with an error about SQLite."""
        self.expense()
        for q in ("99999999999999999999", "%C2%B2", "5000", "5,000"):
            self.assertEqual(self.ask("GET", f"/api/entries?q={q}")[0], 200, q)
        self.assertEqual(len(self.ask("GET", "/api/entries?q=5,000")[1]), 1)

    def test_a_page_that_went_away_mid_answer_is_not_logged(self):
        """The browser drops a download it no longer needs (a page reloaded,
        or closed) and the log filled with tracebacks of it."""
        srv = server.Server.__new__(server.Server)
        for exc, logged in ((BrokenPipeError(), False), (ConnectionResetError(), False),
                            (ConnectionAbortedError(), False), (KeyError("x"), True)):
            with mock.patch("socketserver.BaseServer.handle_error") as base:
                try:
                    raise exc
                except Exception:                          # noqa: BLE001
                    srv.handle_error(None, ("127.0.0.1", 1))
            self.assertEqual(base.called, logged, repr(exc))


class OpenPages(unittest.TestCase):
    def test_a_page_name_past_any_the_app_gives_is_not_kept(self):
        pages = server.Pages()
        pages.here("x" * 65)
        pages.here("k2x9q1lmv0" * 2)
        self.assertEqual(pages.open, {"k2x9q1lmv0" * 2})


if __name__ == "__main__":
    unittest.main()
