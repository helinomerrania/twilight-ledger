"""Turning a counted line into a quantity and a value.

Kept apart from the API because this is the one piece of arithmetic in the
project that is neither money nor dates, and because it is the piece most
likely to be wrong in a way nobody notices: an error here moves the closing
stock, which moves the cost of goods, which moves the month's profit.

Two rules:

  * counts are exact fractions, never floats. Counts come in tenths — 12.4
    blocks, 0.1 of a packet of filters — and those tenths are worth real
    money: 0.4 of a 500-gram block is 200 grams of tobacco.
  * a value is worked out from the exact quantity and rounded once, at the
    end. Rounding the quantity first and then multiplying by the price gets
    it wrong: 16 cans at 24 to a case, at 19,300 a case, is 12,867, but
    rounding the quantity to 0.667 first makes it 12,873.
"""
from fractions import Fraction

from .money import half_up

MILLI = 1000


def from_milli(value):
    return Fraction(int(value or 0), MILLI)


def to_milli(value):
    """Accept what a form sends ('65.4', 65.4, '', None) as thousandths."""
    if value in (None, ""):
        return 0
    if isinstance(value, str):
        value = value.strip().replace(",", "")
        if not value:
            return 0
    return half_up(Fraction(str(value)) * MILLI)


def conversions(raw):
    """The pack sizes, with the lounge's own defaults when Setup is silent."""
    raw = raw or {}

    def g(key, default):
        v = raw.get(key)
        return int(v) if v not in (None, "") else default
    return {"grams_per_kilo": g("gramsPerKilo", 1000) or 1000,
            "grams_per_pack": g("gramsPerPack", 50),
            "packs_per_block": g("packsPerBlock", 10),
            "blocks_per_carton": g("blocksPerCarton", 12),
            "buckets_per_carton": g("bucketsPerCarton", 2) or 1}


def quantity(letter, *, packages_milli=0, blocks_milli=0, loose_milli=0,
             gross_grams=None, tare_grams=0, pack_size=None, conv=None):
    """How much of an item a line comes to, as an exact Fraction.

      A  weighed      what the scales read, less the bucket
      B  sealed       cartons, then blocks, then loose packs, into kilos
      E  ice cream    cartons plus part-cartons of buckets
      everything else whole packages plus loose pieces
    """
    c = conversions(conv)
    packages = from_milli(packages_milli)
    blocks = from_milli(blocks_milli)
    loose = from_milli(loose_milli)

    if letter == "A":
        net = max(int(gross_grams or 0) - int(tare_grams or 0), 0)
        return Fraction(net, c["grams_per_kilo"])

    if letter == "B":
        per_block = c["packs_per_block"] * c["grams_per_pack"]        # grams
        grams = ((packages * c["blocks_per_carton"] + blocks) * per_block
                 + loose * c["grams_per_pack"])
        return grams / c["grams_per_kilo"]

    if letter == "E":
        return packages + loose / c["buckets_per_carton"]

    per = int(pack_size) if pack_size else 1
    return packages + loose / (per or 1)


def value_of(qty, price):
    """What a quantity is worth, rounded once at the end."""
    return half_up(qty * int(price or 0))


def qty_milli_of(qty):
    """The quantity as thousandths, for showing and for storing."""
    return half_up(qty * MILLI)


def is_empty(packages_milli, blocks_milli, loose_milli, gross_grams):
    return not (packages_milli or blocks_milli or loose_milli or gross_grams)
