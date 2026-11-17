"""The app in a window of its own (ledger/window.py): it stops once the last
of its windows has gone, but not for a page being loaded again; started from
the black window it never stops itself; after an update it starts itself
again; and the start file is never changed. Everything here is invented."""
import hashlib
import http.client
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from ledger import api, server, update, window
from ledger.words import t
from tests.helpers import fresh_books

ROOT = Path(__file__).resolve().parent.parent


class ThePagesThatAreOpen(unittest.TestCase):

    def setUp(self):
        self.gone = threading.Event()
        self.pages = server.Pages(self.gone.set)
        self.pages.GRACE = 0.2

    def test_the_last_window_closed_stops_the_app(self):
        self.pages.here("a")
        self.pages.here("b")
        self.pages.bye("a")
        self.assertFalse(self.gone.wait(0.5))           # b is still open
        self.pages.bye("b")
        self.assertTrue(self.gone.wait(2))

    def test_a_page_loaded_again_does_not(self):
        self.pages.here("a")
        self.pages.bye("a")                             # the window reloading:
        self.pages.here("a again")                      # gone, and straight back
        self.assertFalse(self.gone.wait(0.6))

    def test_a_goodbye_from_a_page_it_never_saw_counts_for_nothing(self):
        self.pages.bye("stranger")
        self.assertFalse(self.gone.wait(0.5))

    def test_started_from_the_black_window_it_never_stops_itself(self):
        pages = server.Pages()
        pages.here("a")
        pages.bye("a")
        self.assertEqual(pages.open, set())


class OverHttp(unittest.TestCase):

    def setUp(self):
        self.con = fresh_books()
        api.bootstrap(self.con)
        server.Handler.db_path = self.con.path
        self.gone = threading.Event()
        server.Handler.pages = server.Pages(self.gone.set)
        server.Handler.pages.GRACE = 0.2
        self.srv = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.port = self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        server.Handler.pages = server.Pages()

    def ask(self, method, path, body=None, **headers):
        c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        c.request(method, path, body=body, headers=headers)
        r = c.getresponse()
        r.read()
        c.close()
        return r.status

    def test_a_page_says_it_is_here_and_goodbye(self):
        self.assertEqual(self.ask("GET", "/api/here?page=p1"), 200)
        # a page going away cannot send JSON, and need not
        self.assertEqual(self.ask("POST", "/api/bye?page=p1", b"",
                                  **{"Content-Type": "text/plain;charset=UTF-8"}), 200)
        self.assertTrue(self.gone.wait(2))

    def test_a_goodbye_under_another_name_is_refused(self):
        self.ask("GET", "/api/here?page=p1")
        self.assertEqual(self.ask("POST", "/api/bye?page=p1", b"", Host="books.example.com"), 403)
        self.assertFalse(self.gone.wait(0.5))

    def test_it_answers_with_the_version_it_started_as(self):
        # Once an update is in place the disk says the new version, but until
        # the app has started again it is the old one answering. A page told
        # the new one loaded itself again, against an app just stopping, and
        # sat on "Opening the books…".
        with mock.patch.object(update, "current", return_value="2099.1.1.1"):
            c = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
            c.request("GET", "/api/health")
            self.assertIn(f'"version": "{update.RUNNING}"', c.getresponse().read().decode())
            c.close()
            self.assertEqual(api.state(self.con)["version"], update.RUNNING)
        self.assertNotEqual(update.RUNNING, "2099.1.1.1")


class StartedAgainAfterAnUpdate(unittest.TestCase):

    def test_it_takes_back_the_same_port(self):
        # the pages left open are waiting at the old address; just after the
        # old app stops, its last connections still linger on the port
        con = fresh_books()
        api.bootstrap(con)
        server.Handler.db_path = con.path
        old = ThreadingHTTPServer(("127.0.0.1", 0), server.Handler)
        threading.Thread(target=old.serve_forever, daemon=True).start()
        port = old.server_address[1]
        for _ in range(3):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
            c.request("GET", "/api/here?page=p")
            c.getresponse().read()
            c.close()
        old.shutdown()
        old.server_close()
        new = server.take_back(port)
        try:
            self.assertIsNotNone(new)
            self.assertEqual(new.server_address[1], port)
        finally:
            if new:
                new.server_close()


class StartingInAWindow(unittest.TestCase):

    def setUp(self):
        self.books = fresh_books().path

    def test_after_an_update_it_starts_itself_again(self):
        argv = ["--db", self.books, "window"]
        with mock.patch.object(window.server, "serve", return_value=server.RESTART), \
                mock.patch.object(window.subprocess, "Popen") as popen:
            self.assertEqual(window.run(self.books, argv), 0)
        args, kw = popen.call_args
        self.assertEqual(args[0][-3:], argv)
        self.assertEqual(kw["env"]["TWILIGHT_RESTARTED"], "1")

    def test_closed_it_is_done(self):
        with mock.patch.object(window.server, "serve", return_value=0), \
                mock.patch.object(window.subprocess, "Popen") as popen:
            self.assertEqual(window.run(self.books, ["window"]), 0)
        popen.assert_not_called()

    def test_books_it_will_not_serve_are_said_in_a_box(self):
        with mock.patch.object(window.server, "serve", side_effect=SystemExit(2)), \
                mock.patch.object(window, "say") as say:
            self.assertEqual(window.run(self.books, ["window"]), 2)
        self.assertIn(t("cli.not_served"), say.call_args[0][0])

    def test_it_opens_in_a_window_of_its_own_where_it_can(self):
        with mock.patch.object(window, "browser", return_value="/edge"), \
                mock.patch.object(window.subprocess, "Popen") as popen:
            window.open_window("http://127.0.0.1:8788/")
        self.assertEqual(popen.call_args[0][0], ["/edge", "--app=http://127.0.0.1:8788/"])

    def test_else_in_the_browser(self):
        with mock.patch.object(window, "browser", return_value=None), \
                mock.patch.object(window.webbrowser, "open") as open_:
            window.open_window("http://127.0.0.1:8788/")
        open_.assert_called_once_with("http://127.0.0.1:8788/")

    def test_the_desktop_icon_is_windows_only(self):
        with mock.patch.object(window.os, "name", "posix"):
            self.assertIsNone(window.make_icon())


class TheStartFile(unittest.TestCase):

    def test_it_is_never_changed(self):
        """An update replaces it while it is running, and Windows reads a
        running batch file from disk a line at a time: after the restart a
        changed one would carry on from the middle of a line of the new one."""
        data = (ROOT / "Start Twilight Ledger.bat").read_bytes()
        self.assertEqual(hashlib.sha256(data).hexdigest(),
                         "22b69972d8800b18bb65ed32f6c1713cf29b3c5227ff6bf28b00a7a712cb2c20")

    def test_what_comes_with_an_update(self):
        # the window's files are in folders an update brings
        for f in ("ledger/window.py", "ledger/desktop.ps1", "web/icon.ico"):
            self.assertIn(f.split("/")[0], update.MANAGED_DIRS)
            self.assertTrue((ROOT / f).exists(), f)


if __name__ == "__main__":
    unittest.main()
