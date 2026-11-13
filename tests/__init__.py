"""The tests' clock.

The tests' invented nights are dated around the middle of November 2026, and
the app refuses a date long before the books begin, and stops when the
computer's clock has jumped months past the books. On the real clock the
tests began to fail a few weeks after they were written. So for the tests
the app's clock says the evening of 14 November 2026, whatever the real date,
and runs on from there; `clock_at` puts it at another time for a test that
needs one. Only the app's own clock moves: the times on files and copies of
the books are the real ones."""
import contextlib
from datetime import datetime

from ledger import dates

THEN = datetime(2026, 11, 14, 20, 0)

_shift = [THEN - datetime.now()]
_tonight = dates.tonight


def _now():
    return datetime.now() + _shift[0]


def _today():
    return _now().date().isoformat()


def _tonight_at(now=None):
    return _tonight(now or _now())


# before anything else takes them: the app's modules import them by name
dates.today = _today
dates.tonight = _tonight_at


@contextlib.contextmanager
def clock_at(when):
    """The app's clock at `when`, a datetime, inside the with-block."""
    was = _shift[0]
    _shift[0] = when - datetime.now()
    try:
        yield
    finally:
        _shift[0] = was
