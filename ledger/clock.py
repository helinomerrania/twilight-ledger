"""Is the computer's clock right? Asked of the internet now and then.

Everything in the books goes by the computer's clock: which night a sale is
on, when a night ends at six, which month a bill falls in. SambaPOS stamps
its tickets by the same clock, so the two always agree with each other, and
a wrong clock is wrong for both, quietly. A date months ahead of the books is
caught already (accruals.clock_jump); this is for a clock hours or days out,
or set to the wrong time zone.

So while the app runs, and the internet is there, the time GitHub's servers
give with any answer (the Date of the small file an update reads) is set
against the computer's: as the time in Kurdistan, UTC+3 all year. That time
is only ever used to say so. Entries still go by the computer's clock, which
is put right in Windows, and puts SambaPOS right with it.
"""
import email.utils
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

from . import update

KURDISTAN = timezone(timedelta(hours=3))   # no summer time since 2007
OFF_BY = 5 * 60      # seconds out before it is worth saying
AGAIN = 60 * 60      # a clock found right is looked at again after an hour
RETRY = 5 * 60       # and the internet, when it was not there, after five minutes
JUMPED = 60          # the clock and the time gone by this far apart: the
                     # computer slept, or someone set the clock

_lock = threading.Lock()
_seen = None         # after a look: {"wall", "mono", "off"}, off in seconds
_tried = None        # mono() at the last look, answered or not


def wall():
    """The computer's clock, which can be set."""
    return time.time()


def mono():
    """The time gone by, which cannot."""
    return time.monotonic()


def internet_time(url=None, timeout=10):
    """The time now, as GitHub's servers have it (UTC), or None."""
    req = urllib.request.Request(url or update._version_url(), method="HEAD",
                                 headers={"User-Agent": "twilight-ledger",
                                          "Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            said = r.headers.get("Date")
    except urllib.error.HTTPError as exc:    # a refusal is still dated
        said = exc.headers.get("Date") if exc.headers else None
    except (urllib.error.URLError, OSError, ValueError):
        return None
    try:
        when = email.utils.parsedate_to_datetime(said) if said else None
    except (TypeError, ValueError):
        return None
    return when if when is not None and when.tzinfo is not None else None


def look(fetch=internet_time):
    """Ask once, and remember how far the computer's clock is from Kurdistan's:
    seconds, ahead above nought. None when the internet did not answer."""
    global _seen, _tried
    before = wall()
    there = fetch()
    after = wall()
    with _lock:
        _tried = mono()
        if there is None:
            return None
        # the clock as the books read it, halfway through the asking
        here = datetime.fromtimestamp((before + after) / 2)
        kurdistan = there.astimezone(KURDISTAN).replace(tzinfo=None)
        _seen = {"wall": after, "mono": _tried, "off": (here - kurdistan).total_seconds()}
        return _seen["off"]


def _jumped(seen):
    """Has the clock moved other than by the time gone by, since that look?"""
    return abs((wall() - seen["wall"]) - (mono() - seen["mono"])) > JUMPED


def due():
    """Is a look wanted now? Not more than once in five minutes while the
    internet is not answering, and soon after the clock has been set."""
    with _lock:
        since = None if _tried is None else mono() - _tried
        if _seen is None:
            return since is None or since >= RETRY
        if _jumped(_seen):
            return since >= 30
        return mono() - _seen["mono"] >= AGAIN and since >= RETRY


def view():
    """{"says", "is"} while the computer's clock is out, else None. Only what
    the last look found: never waits for the internet."""
    with _lock:
        seen = _seen
        if seen is None or _jumped(seen) or abs(seen["off"]) <= OFF_BY:
            return None
    now = datetime.now()
    return {"says": now.strftime("%Y-%m-%d %H:%M"),
            "is": (now - timedelta(seconds=seen["off"])).strftime("%Y-%m-%d %H:%M")}


def watch(fetch=internet_time, every=30, stop=None):
    """While the app runs (or until `stop` is set): look whenever one is due."""
    stop = stop or threading.Event()

    def loop():
        while not stop.is_set():
            try:
                if due():
                    look(fetch)
            except Exception:  # noqa: BLE001, S110 - the clock is a nicety, never a crash
                pass
            stop.wait(every)
    threading.Thread(target=loop, name="clock", daemon=True).start()
    return stop


def forget():
    """Start from nothing (for the tests)."""
    global _seen, _tried
    with _lock:
        _seen = _tried = None
