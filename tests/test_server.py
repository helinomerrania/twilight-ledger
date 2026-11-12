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

    def test_a_refused_write_ends_its_connection(self):
        # its body is never read, so it must not be taken for the next request
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request("POST", "/api/do/expense", body=b'{"amount": 5000}',
                  headers={"Content-Type": "text/plain"})
        r = c.getresponse()
        r.read()
        self.assertEqual((r.status, r.getheader("Connection")), (403, "close"))
        c.close()

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


if __name__ == "__main__":
    unittest.main()
