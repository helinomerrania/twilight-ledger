"""Money is whole dinar, always, and always an int.

The old app did its arithmetic in JavaScript numbers. That is a floating-point
type, so 0.1 + 0.2 is not 0.3 and a long column of figures can drift by a
dinar or two with nothing to show why. Here every amount in the database is an
INTEGER number of dinar and every calculation in this file is integer
arithmetic. There is no float anywhere in the money path.

The Iraqi dinar has no subunit in daily use and the smallest note Mohammed
handles is 250, so a figure he has to physically pay out is rounded to the
note size. Rounding is explicit: it happens where a payment is proposed, never
silently inside a total.
"""
from fractions import Fraction

NOTE = 250          # smallest note in circulation at the lounge
DEFAULT_NOTE = 250


def set_note(note):
    """Change the smallest banknote money is rounded to. Setup stores it; the
    app loads it on the way up. Everything that rounds asks for it at the
    moment of rounding, so there is one place it can be different."""
    global NOTE
    note = int(note or DEFAULT_NOTE)
    NOTE = note if note >= 1 else DEFAULT_NOTE
    return NOTE


def to_int(v, field="amount"):
    """Accept what a form or an old JSON file might hand us; return whole dinar.

    Rejects anything that is not a finite number, because a silent 0 in a
    ledger is worse than a loud error.
    """
    if v is None or v == "":
        return 0
    if isinstance(v, bool):
        raise ValueError(f"{field}: a true/false is not an amount")
    if isinstance(v, int):
        return v
    if isinstance(v, float):
        if v != v or v in (float("inf"), float("-inf")):
            raise ValueError(f"{field}: {v!r} is not a real number")
        # Half away from zero, not Python's round(), which rounds halves to the
        # nearest even number: round(0.5) is 0 and round(1.5) is 2. Fine for
        # statistics, surprising in a cash book, and inconsistent with the
        # rounding used everywhere else here.
        return int(v + 0.5) if v >= 0 else -int(-v + 0.5)
    if isinstance(v, str):
        s = v.strip().replace(",", "").replace("٬", "")
        if not s:
            return 0
        try:
            return to_int(float(s), field)
        except ValueError:
            raise ValueError(f"{field}: {v!r} is not an amount")
    raise ValueError(f"{field}: {type(v).__name__} is not an amount")


def mround(amount, note=None):
    """Round to the nearest note. Halves go away from zero, so 125 -> 250."""
    note = NOTE if note is None else note
    amount = to_int(amount)
    if note <= 1:
        return amount
    sign = -1 if amount < 0 else 1
    a = abs(amount)
    q, rem = divmod(a, note)
    if rem * 2 >= note:
        q += 1
    return sign * q * note


def split_shares(total, shares, note=None):
    """Split a total between partners by share, rounded to the note size.

    Shares arrive as decimals (0.5, 0.33) but are converted to exact fractions
    first, so the split never depends on how a decimal happens to be stored.

    Every split has a remainder. Giving it to whoever comes last in the list
    would make the result depend on the order rows happen to be stored in, so
    the remainder goes to the largest share, and ties break on name. The
    returned amounts always sum to exactly `total`.
    """
    note = NOTE if note is None else note
    total = to_int(total)
    if not shares:
        return {}
    weights = [(name, Fraction(str(s)) if isinstance(s, float) else Fraction(s))
               for name, s in shares]
    weight = sum(w for _, w in weights)
    if weight <= 0:
        return {n: 0 for n, _ in weights}
    out, running = {}, 0
    for name, w in weights:
        exact = Fraction(total) * w / weight
        part = mround_fraction(exact, note)
        out[name] = part
        running += part
    gap = total - running
    if gap:
        anchor = sorted(weights, key=lambda kv: (-kv[1], kv[0]))[0][0]
        out[anchor] += gap
    return out


def mround_fraction(exact, note=None):
    """Round an exact Fraction to the nearest note, halves away from zero."""
    note = NOTE if note is None else note
    if note <= 1:
        q, rem = divmod(abs(exact), 1)
        n = int(q) + (1 if rem * 2 >= 1 else 0)
        return -n if exact < 0 else n
    sign = -1 if exact < 0 else 1
    a = abs(exact)
    q = int(a // note)
    rem = a - q * note
    if rem * 2 >= note:
        q += 1
    return sign * q * note


def half_up(frac):
    """Round an exact Fraction to a whole number, halves away from zero."""
    frac = Fraction(frac)
    if frac < 0:
        return -half_up(-frac)
    whole = frac.numerator // frac.denominator
    if (frac - whole) * 2 >= 1:
        whole += 1
    return int(whole)


def share_of(amount, part, whole):
    """amount x part / whole, exactly, rounded once. For a pro-rata figure such
    as eight days' worth of a thirty-day rent."""
    if not whole:
        return 0
    return half_up(Fraction(to_int(amount)) * Fraction(part) / Fraction(whole))


def money(amount, currency=""):
    """Format for a screen: thousands separated, minus sign kept in front."""
    amount = to_int(amount)
    s = f"{abs(amount):,}"
    s = ("-" + s) if amount < 0 else s
    return f"{s} {currency}".strip() if currency else s


def pct(part, whole, places=1):
    """Percentage as a float for display only; never used in the money path."""
    part, whole = to_int(part), to_int(whole)
    if whole == 0:
        return None
    return round(part * 100 / whole, places)
