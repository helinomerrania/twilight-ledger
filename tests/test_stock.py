"""Counting stock, and the arithmetic that turns a count into a value.

The bug these were written for: the count sheet sent back to the screen left
out the `blocks` column, so the box rendered empty and saving the line blanked
every block of a tobacco counted in blocks, without a word. Anything that
round-trips through the screen gets a test here now. The items and prices here
are invented.
"""
import unittest

from fractions import Fraction

from ledger import api, db, queries, stock
from tests.helpers import add_count, fresh_books


CONV = {"gramsPerKilo": 1000, "gramsPerPack": 50, "packsPerBlock": 10,
        "blocksPerCarton": 12, "bucketsPerCarton": 2}


def q(letter, **kw):
    kw.setdefault("conv", CONV)
    return stock.quantity(letter, **kw)


class Quantity(unittest.TestCase):
    """A quantity is an exact fraction. Counts come in tenths — 12.4 blocks,
    0.1 of a packet of filters — and those tenths are worth real money."""

    def test_weighed_takes_the_bucket_off(self):
        # 1,449 g on the scales in a 321 g bucket is 1.128 kg
        self.assertEqual(q("A", gross_grams=1449, tare_grams=321),
                         Fraction(1128, 1000))

    def test_weighed_never_goes_negative(self):
        self.assertEqual(q("A", gross_grams=100, tare_grams=321), 0)

    def test_sealed_counts_at_three_levels(self):
        """A block is 10 packs of 50 g, so 500 g. A carton is 12 blocks, 6 kg."""
        self.assertEqual(q("B", packages_milli=1000), 6)
        self.assertEqual(q("B", blocks_milli=1000), Fraction(1, 2))
        self.assertEqual(q("B", loose_milli=1000), Fraction(1, 20))

    def test_sealed_keeps_a_fraction_of_a_block(self):
        """12.4 blocks is 6.2 kg. The .4 is 200 g — 5,720 dinar at 28,600 a
        kilo, and the old integer column dropped it on every save."""
        self.assertEqual(q("B", blocks_milli=12400), Fraction(31, 5))
        self.assertEqual(stock.value_of(q("B", blocks_milli=12400), 28600), 177320)

    def test_sealed_adds_the_three_levels_together(self):
        self.assertEqual(q("B", packages_milli=2000, blocks_milli=3000,
                            loose_milli=4000), 2 * 6 + 3 * Fraction(1, 2)
                         + 4 * Fraction(1, 20))

    def test_ice_cream_counts_cartons_and_buckets(self):
        self.assertEqual(q("E", packages_milli=3000, loose_milli=1000),
                         Fraction(7, 2))

    def test_everything_else_is_packages_and_pieces(self):
        self.assertEqual(q("D", packages_milli=6000, loose_milli=2000,
                            pack_size=4), Fraction(13, 2))

    def test_a_fraction_of_a_package(self):
        """A sheet can say 1.1 packets of olives and 0.1 of a packet of
        filters."""
        self.assertEqual(q("D", packages_milli=1100, pack_size=1),
                         Fraction(11, 10))
        self.assertEqual(stock.value_of(q("D", packages_milli=1100,
                                          pack_size=1), 813), 894)
        self.assertEqual(stock.value_of(q("C", loose_milli=100, pack_size=1),
                                        35000), 3500)

    def test_a_missing_pack_size_counts_pieces_whole(self):
        self.assertEqual(q("D", packages_milli=1000, loose_milli=3000), 4)

    def test_the_value_is_rounded_once_at_the_end(self):
        """16 cans at 24 to a case, at 19,300 a case, is 12,867. Rounding the
        quantity to 0.667 first and then multiplying makes it 12,873."""
        qty = q("D", loose_milli=16000, pack_size=24)
        self.assertEqual(stock.value_of(qty, 19300), 12867)
        rounded_first = round(float(qty), 3) * 19300
        self.assertNotEqual(round(rounded_first), 12867)

    def test_a_typed_decimal_survives_the_trip(self):
        for typed, milli in (("12.4", 12400), (12.4, 12400), (4.35, 4350), ("0.1", 100),
                             ("", 0), (None, 0), ("1.1", 1100), ("12", 12000)):
            self.assertEqual(stock.to_milli(typed), milli, repr(typed))


class CountSheet(unittest.TestCase):
    """What the screen is given must be everything the screen sends back."""

    def setUp(self):
        self.con = fresh_books()
        db.set_setting(self.con, "conversions", {"gramsPerKilo": 1000,
                                                 "gramsPerPack": 50,
                                                 "packsPerBlock": 10,
                                                 "blocksPerCarton": 12})
        cid = db.one(self.con, "SELECT id FROM stock_category WHERE letter='B'")["id"]
        self.con.execute("INSERT INTO stock_item(name, category_id, unit, price) "
                         "VALUES ('Double Apple', ?, 'kg', 28600)", (cid,))
        self.item = db.one(self.con, "SELECT id FROM stock_item")["id"]
        api.run(self.con, "open_count", {"on": "2026-11-09"})
        api.run(self.con, "count_line",
                {"on": "2026-11-09", "item": self.item, "blocks": "12.4"})

    def test_the_line_is_valued(self):
        self.assertEqual(queries.booked(self.con, "2026-11-09"), 177250)

    def test_the_sheet_hands_back_every_field_it_will_be_sent(self):
        """The regression test proper. Each editable field on the sheet must
        come back from the server, or the screen renders it blank and the next
        save silently wipes it."""
        sheet = api.count_sheet(self.con, "2026-11-09")
        line = sheet["groups"][0]["items"][0]
        for field in ("packages_milli", "blocks_milli", "loose_milli",
                      "gross_grams", "tare_id"):
            self.assertIn(field, line, f"the sheet does not return {field}")
        self.assertEqual(line["blocks_milli"], 12400)

    def test_saving_the_sheet_back_unchanged_changes_nothing(self):
        """Read the sheet, send every line straight back, and the count must
        come out at exactly the same figure."""
        before = queries.booked(self.con, "2026-11-09")
        sheet = api.count_sheet(self.con, "2026-11-09")
        for group in sheet["groups"]:
            for line in group["items"]:
                api.run(self.con, "count_line", {
                    "on": "2026-11-09", "item": line["id"],
                    # exactly what the screen puts in the box
                    "packages": f'{(line["packages_milli"] or 0) / 1000:g}',
                    "blocks": f'{(line["blocks_milli"] or 0) / 1000:g}',
                    "loose": f'{(line["loose_milli"] or 0) / 1000:g}',
                    "gross_grams": line["gross_grams"],
                    "tare_id": line["tare_id"]})
        self.assertEqual(queries.booked(self.con, "2026-11-09"), before)

    def test_clearing_a_line_removes_it(self):
        api.run(self.con, "count_line",
                {"on": "2026-11-09", "item": self.item, "blocks": 0})
        self.assertEqual(queries.booked(self.con, "2026-11-09"), 0)
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM stock_count_line"), 0)

    def test_a_count_in_a_closed_month_cannot_be_edited(self):
        self.con.execute("INSERT INTO period(month, status, closed_at, count_date) "
                         "VALUES ('2026-11','closed',datetime('now'),'2026-11-09') "
                         "ON CONFLICT(month) DO UPDATE SET status='closed', "
                         "closed_at=excluded.closed_at, count_date=excluded.count_date")
        with self.assertRaises(api.ApiError):
            api.run(self.con, "count_line",
                    {"on": "2026-11-09", "item": self.item, "blocks": 1})


class CostOfGoods(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def test_opening_plus_bought_less_closing(self):
        add_count(self.con, "2026-09-30", 2100000)
        add_count(self.con, "2026-10-31", 2400000)
        from tests.helpers import add_receipt
        add_receipt(self.con, "2026-10-10", "Star Store", 3200000)
        c = queries.cogs(self.con, "2026-10")
        self.assertEqual(c["opening"], 2100000)
        self.assertEqual(c["purchases"], 3200000)
        self.assertEqual(c["closing"], 2400000)
        self.assertEqual(c["value"], 2900000)

    def test_a_negative_cost_is_reported_not_hidden(self):
        add_count(self.con, "2026-09-30", 1000000)
        add_count(self.con, "2026-10-31", 5000000)
        c = queries.cogs(self.con, "2026-10")
        self.assertEqual(c["value"], 0, "a negative cost must not read as profit")
        self.assertEqual(c["raw"], -4000000, "but the real figure stays visible")

    def test_what_was_bought_is_measured_between_the_counts(self):
        """A count on the 2nd must not be set against a whole month of
        deliveries — the window runs from the previous count to this one."""
        add_count(self.con, "2026-09-30", 1000000)
        add_count(self.con, "2026-10-02", 1200000)
        from tests.helpers import add_receipt
        add_receipt(self.con, "2026-10-01", "Star Store", 500000)
        add_receipt(self.con, "2026-10-20", "Star Store", 9000000)
        c = queries.cogs(self.con, "2026-10")
        self.assertEqual(c["purchases"], 500000,
                         "only what arrived before the count should count")


if __name__ == "__main__":
    unittest.main()
