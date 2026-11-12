"""Dates as plain ISO strings, because that is what SQLite sorts correctly.

Every date in the database is 'YYYY-MM-DD' and every month is 'YYYY-MM'. Stored
that way, a text comparison is a chronological comparison, so ranges and
ordering need no conversion and no timezone ever enters the picture. The lounge
is in one place; a date here means the day in Ranya.
"""
from datetime import date, datetime, timedelta

ISO = "%Y-%m-%d"

# The lounge closes after midnight: until six in the morning it is still the
# night before, for the screens as for SambaPOS's work periods.
NIGHT_ENDS = 6


def today():
    return date.today().isoformat()


def tonight(now=None):
    """The night the lounge is in: until six in the morning, the one before."""
    return ((now or datetime.now()) - timedelta(hours=NIGHT_ENDS)).date().isoformat()


def ymd(value):
    """Normalise whatever a form, an old JSON file or a POS handed us."""
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    s = str(value).strip()
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        try:
            datetime.strptime(s[:10], ISO)
            return s[:10]
        except ValueError:
            pass
    for fmt in ("%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y", "%Y%m%d",
                "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(s[:len(datetime.now().strftime(fmt))], fmt).date().isoformat()
        except ValueError:
            continue
    raise ValueError(f"not a date: {value!r}")


def month_of(value):
    return ymd(value)[:7]


def month_start(month):
    return f"{month}-01"


def month_end(month):
    y, m = int(month[:4]), int(month[5:7])
    if m == 12:
        nxt = date(y + 1, 1, 1)
    else:
        nxt = date(y, m + 1, 1)
    return (nxt - timedelta(days=1)).isoformat()


def month_range(month):
    return month_start(month), month_end(month)


def next_month(month):
    y, m = int(month[:4]), int(month[5:7])
    return f"{y + 1}-01" if m == 12 else f"{y}-{m + 1:02d}"


def prev_month(month):
    y, m = int(month[:4]), int(month[5:7])
    return f"{y - 1}-12" if m == 1 else f"{y}-{m - 1:02d}"


MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July",
               "August", "September", "October", "November", "December"]


def month_name(month):
    return f"{MONTH_NAMES[int(month[5:7]) - 1]} {month[:4]}"


def days_in(month):
    a, b = month_range(month)
    start = datetime.strptime(a, ISO).date()
    end = datetime.strptime(b, ISO).date()
    return [(start + timedelta(days=i)).isoformat()
            for i in range((end - start).days + 1)]
