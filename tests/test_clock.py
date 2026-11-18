"""The computer's clock, set against the internet's."""
import threading
import unittest
from datetime import datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest import mock

from ledger import api, clock
from tests.helpers import fresh_books


def internet(off):
    """An internet that has the time `off` behind this computer's clock, in
    Kurdistan: nought for a computer whose clock is right."""
    return lambda: (datetime.now() - off).replace(tzinfo=clock.KURDISTAN)


RIGHT = timedelta(0)


class Looking(unittest.TestCase):
    def setUp(self):
        clock.forget()
        self.addCleanup(clock.forget)

    def test_nothing_is_said_before_a_look_or_when_the_clock_is_right(self):
        self.assertIsNone(clock.view())
        self.assertAlmostEqual(clock.look(internet(RIGHT)), 0, delta=2)
        self.assertIsNone(clock.view())
        clock.look(internet(timedelta(minutes=4)))           # a little out: let be
        self.assertIsNone(clock.view())

    def test_a_clock_hours_out_is_said_with_both_times(self):
        clock.look(internet(timedelta(hours=3)))              # three hours ahead
        seen = clock.view()
        says = datetime.strptime(seen["says"], "%Y-%m-%d %H:%M")
        is_ = datetime.strptime(seen["is"], "%Y-%m-%d %H:%M")
        self.assertEqual(says - is_, timedelta(hours=3))
        self.assertLess(abs(datetime.now() - says), timedelta(minutes=2))
        clock.look(internet(-timedelta(days=1)))              # a day behind
        seen = clock.view()
        self.assertEqual(datetime.strptime(seen["is"], "%Y-%m-%d %H:%M")
                         - datetime.strptime(seen["says"], "%Y-%m-%d %H:%M"), timedelta(days=1))

    def test_the_wrong_time_zone_is_a_wrong_clock(self):
        """Right by the world's clock but in London's time zone, it is three
        hours behind: at eight in the morning the books are still on last night."""
        clock.look(internet(-timedelta(hours=3)))
        seen = clock.view()
        self.assertEqual(datetime.strptime(seen["is"], "%Y-%m-%d %H:%M")
                         - datetime.strptime(seen["says"], "%Y-%m-%d %H:%M"), timedelta(hours=3))

    def test_no_internet_is_not_a_wrong_clock(self):
        self.assertIsNone(clock.look(lambda: None))
        self.assertIsNone(clock.view())

    def test_once_the_clock_is_set_the_old_answer_is_not_shown(self):
        """Put right in Windows, the clock jumps; what the last look found no
        longer holds, and a new look is wanted soon."""
        clock.look(internet(timedelta(hours=3)))
        self.assertIsNotNone(clock.view())
        now = clock.wall()
        with mock.patch.object(clock, "wall", lambda: now - 3 * 3600):
            self.assertIsNone(clock.view())
            self.assertFalse(clock.due())                      # not this very moment
            later = clock.mono()
            with mock.patch.object(clock, "mono", lambda: later + 31):
                self.assertTrue(clock.due())

    def test_how_often_it_asks(self):
        self.assertTrue(clock.due())                           # never asked
        clock.look(lambda: None)                               # no internet
        self.assertFalse(clock.due())
        then = clock.mono()
        with mock.patch.object(clock, "mono", lambda: then + clock.RETRY):
            self.assertTrue(clock.due())
        clock.look(internet(RIGHT))
        then = clock.mono()
        with mock.patch.object(clock, "mono", lambda: then + clock.AGAIN - 1), \
                mock.patch.object(clock, "wall", lambda: clock.time.time() + clock.AGAIN - 1):
            self.assertFalse(clock.due())
        with mock.patch.object(clock, "mono", lambda: then + clock.AGAIN), \
                mock.patch.object(clock, "wall", lambda: clock.time.time() + clock.AGAIN):
            self.assertTrue(clock.due())

    def test_the_watch_looks_and_stops(self):
        looked = threading.Event()

        def fetch():
            looked.set()
            return internet(timedelta(hours=2))()
        stop = clock.watch(fetch, every=0.01)
        self.addCleanup(stop.set)
        self.assertTrue(looked.wait(5))
        stop.set()
        for _ in range(200):
            if clock.view():
                break
            threading.Event().wait(0.01)
        self.assertIsNotNone(clock.view())

    def test_a_screen_carries_it(self):
        con = fresh_books()
        self.assertIsNone(api.state(con)["clock_off"])
        clock.look(internet(timedelta(hours=5)))
        self.assertEqual(set(api.state(con)["clock_off"]), {"says", "is"})


class TheInternetsTime(unittest.TestCase):
    """What a server says the time is, read from its answer's Date."""

    def serve(self, date, status=200):
        class Answer(BaseHTTPRequestHandler):
            def do_HEAD(self):
                self.send_response(status)
                self.end_headers()

            def date_time_string(self, timestamp=None):
                return date

            def log_message(self, *args):
                pass
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Answer)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        self.addCleanup(srv.server_close)
        self.addCleanup(srv.shutdown)
        return f"http://127.0.0.1:{srv.server_address[1]}/VERSION"

    def test_its_date_is_read(self):
        got = clock.internet_time(self.serve("Wed, 18 Nov 2026 16:19:28 GMT"))
        self.assertEqual(got.isoformat(), "2026-11-18T16:19:28+00:00")

    def test_a_refusal_is_still_dated(self):
        got = clock.internet_time(self.serve("Wed, 18 Nov 2026 16:19:28 GMT", 404))
        self.assertEqual(got.isoformat(), "2026-11-18T16:19:28+00:00")

    def test_a_date_that_is_not_one(self):
        for said in ("not a date", "Wed, 18 Nov 2026 16:19:28"):    # nor without its zone
            self.assertIsNone(clock.internet_time(self.serve(said)), said)

    def test_nothing_there(self):
        url = self.serve("Wed, 18 Nov 2026 16:19:28 GMT")
        closed = url.rsplit(":", 1)[0] + ":9/VERSION"
        self.assertIsNone(clock.internet_time(closed, timeout=2))
