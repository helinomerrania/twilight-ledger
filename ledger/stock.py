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
import json
import re
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


def packs_of(item, parent=None):
    """How a sealed tobacco comes: its own packs, else its brand's, else the
    usual ones from Setup (None). As {"grams", "per_block", "per_carton"},
    where a missing level is None: 250 g packs have no blocks."""
    for raw in (item.get("packs") if item else None, parent.get("packs") if parent else None):
        if raw:
            p = json.loads(raw) if isinstance(raw, str) else raw
            return {"grams": int(p["grams"]), "per_block": p.get("per_block") or None,
                    "per_carton": p.get("per_carton") or None}
    return None


# '12×10×50 g', '3x1kg', '250gm': up to two counts, then the size of a pack
_PACKS = re.compile(r"(?:(\d+)x)?(?:(\d+)x)?(\d+(?:\.\d+)?)"
                    r"(kg|kgm|kgs|kilo|kilos|g|gm|gms|gr|gram|grams)")


def parse_packs(text):
    """How a sealed tobacco comes, typed the way the boxes say it:
    '12×10×50 g' is cartons of 12 blocks of 10 packs of 50 g, '3×1 kg' is
    boxes of three 1 kg bags, '250 g' is single 250 g packs. Blank is None,
    the usual. pack_levels says it back the same way."""
    s = re.sub(r"\s+", "", str(text or "")).lower().replace("×", "x").replace("*", "x")
    if not s:
        return None
    m = _PACKS.fullmatch(s)
    if not m:
        raise ValueError("say how it comes, like 12×10×50 g, 3×1 kg or 250 g")
    *counts, size, unit = m.groups()
    grams = Fraction(size) * (1000 if unit.startswith("k") else 1)
    if grams.denominator != 1 or not 1 <= grams <= 100000:
        raise ValueError("a pack is whole grams, from 1 g to 100 kg")
    counts = [int(n) for n in counts if n]
    if any(not 1 <= n <= 1000 for n in counts):
        raise ValueError("a box holds from 1 to 1000 of what is inside it")
    counts = [n for n in counts if n > 1]        # 12×1×50 g is 12×50 g
    per_carton, per_block = ([None, None] + counts)[-2:]
    return {"grams": int(grams), "per_block": per_block, "per_carton": per_carton}


def packs_label(conv, packs):
    """The whole of how it comes, largest first: '12×10×50 g'."""
    return pack_levels(conv, packs)[0][1]


def item_conversions(conv, packs):
    """Setup's conversions, with one item's own packs in place of the usual."""
    out = dict(conv or {})
    if packs:
        out.update(gramsPerPack=packs["grams"], packsPerBlock=packs["per_block"] or 1,
                   blocksPerCarton=packs["per_carton"] or 1)
    return out


def pack_levels(conv, packs):
    """The levels a sealed tobacco is counted at, largest first, as
    (key, label): ('packages', '12×10×50 g'), ('blocks', '10×50 g'),
    ('loose', '50 g'). Said the way the boxes say it."""
    c = conversions(conv)
    g = packs["grams"] if packs else c["grams_per_pack"]
    per_block = packs["per_block"] if packs else c["packs_per_block"]
    per_carton = packs["per_carton"] if packs else c["blocks_per_carton"]
    small = f"{g / 1000:g} kg" if g >= 1000 and g % 100 == 0 else f"{g} g"
    out = [("loose", small)]
    if per_block and per_block > 1:
        out.insert(0, ("blocks", f"{per_block}×{small}"))
        if per_carton and per_carton > 1:
            out.insert(0, ("packages", f"{per_carton}×{per_block}×{small}"))
    return out


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
