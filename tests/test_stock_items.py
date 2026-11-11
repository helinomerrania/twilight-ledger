"""Stock items as they really come in (plan step 3.1): tobacco in packs of
many sizes, brands with flavours, a minimum to warn at, and barcodes. The
items and prices are invented."""
import unittest

from ledger import api, db, queries, stock
from tests.helpers import fresh_books

ON = "2026-11-09"


class Items(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.brand = self.add("Hill Leaf", "B", 30000)

    def add(self, name, letter="B", price=0, **more):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price, **more})["id"]

    def flavour(self, name, brand=None):
        return api.run(self.con, "item_add", {"brand": brand or self.brand, "name": name})["id"]

    def update(self, item, **fields):
        return api.run(self.con, "item_update", {"id": item, **fields})

    def count(self, item, **boxes):
        api.run(self.con, "count_line", {"on": ON, "item": item, **boxes})
        return db.one(self.con, "SELECT l.* FROM stock_count_line l JOIN stock_count c "
                                "ON c.id = l.count_id WHERE c.count_date = ? AND l.item_id = ?",
                      (ON, item))

    def row(self, item):
        return db.one(self.con, "SELECT * FROM stock_item WHERE id = ?", (item,))

    def sheet_item(self, item):
        sheet = api.count_sheet(self.con, ON)
        return next(i for g in sheet["groups"] for i in g["items"] if i["id"] == item)

    def setup_item(self, item):
        return next(i for i in api.state(self.con)["setup"]["items"] if i["id"] == item)

    def levels(self, item):
        return [l["label"] for l in self.sheet_item(item)["levels"]]

    # ------------------------------------------------------------- packs
    def test_packs_are_typed_the_way_the_box_says_them(self):
        said = {"12×10×50 g": (50, 10, 12), "10x50g": (50, 10, None), "50 gm": (50, None, None),
                "6X1KGM": (1000, 6, None), "3 x 1 kg": (1000, 3, None), "1kg": (1000, None, None),
                "250g": (250, None, None), "1.5 kg": (1500, None, None),
                "12×1×50 g": (50, 12, None)}
        for text, (grams, block, carton) in said.items():
            self.assertEqual(stock.parse_packs(text),
                             {"grams": grams, "per_block": block, "per_carton": carton}, text)
        self.assertIsNone(stock.parse_packs("  "))
        for bad in ("50", "x50 g", "0 g", "1.25 g", "0×50 g", "2×3×4×5 g", "fifty grams"):
            with self.assertRaises(ValueError, msg=bad):
                stock.parse_packs(bad)

    def test_and_said_back_the_same_way(self):
        for text in ("12×10×50 g", "10×50 g", "6×1 kg", "1 kg", "250 g", "1.5 kg"):
            self.assertEqual(stock.packs_label({}, stock.parse_packs(text)), text)

    def test_the_usual_packs_are_unchanged(self):
        line = self.count(self.brand, packages="1", blocks="2", loose="3")
        self.assertEqual(line["qty_milli"], 7150)            # (12 + 2) x 500 g + 150 g
        self.assertEqual(line["value"], 214500)
        self.assertEqual(self.levels(self.brand), ["12×10×50 g", "10×50 g", "50 g"])

    def test_a_tobacco_in_kilo_bags_boxed_in_threes(self):
        kilo = self.add("Kilo Leaf", price=20000)
        self.update(kilo, packs="3×1 kg")
        self.assertEqual(self.levels(kilo), ["3×1 kg", "1 kg"])
        line = self.count(kilo, blocks="2", loose="1")
        self.assertEqual((line["qty_milli"], line["value"]), (7000, 140000))

    def test_a_tobacco_in_single_250_gram_packs(self):
        small = self.add("Quarter Leaf", price=40000)
        self.update(small, packs="250 g")
        self.assertEqual(self.levels(small), ["250 g"])
        self.assertEqual(self.count(small, loose="6")["qty_milli"], 1500)

    def test_blank_goes_back_to_the_usual(self):
        self.update(self.brand, packs="1 kg")
        self.update(self.brand, packs="")
        self.assertIsNone(self.row(self.brand)["packs"])

    def test_a_typo_is_refused_and_changes_nothing(self):
        self.update(self.brand, packs="3×1 kg")
        with self.assertRaises(api.ApiError):
            self.update(self.brand, packs="3×1")
        self.assertEqual(self.levels(self.brand), ["3×1 kg", "1 kg"])

    def test_only_sealed_tobacco_comes_in_packs(self):
        cups = self.add("Cups", "C", 5000)
        with self.assertRaises(api.ApiError):
            self.update(cups, packs="10×50 g")

    def test_a_count_keeps_the_packs_it_was_counted_in(self):
        self.count(self.brand, blocks="2")
        self.update(self.brand, packs="3×1 kg")
        self.assertEqual(queries.booked(self.con, ON), 30000)   # 1 kg at 30,000
        self.assertEqual(self.sheet_item(self.brand)["qty_milli"], 1000)

    # ---------------------------------------------------------- flavours
    def test_a_flavour_belongs_to_its_brand(self):
        mint = self.flavour("Mint")
        row = db.one(self.con, "SELECT si.*, sc.letter FROM stock_item si JOIN stock_category "
                               "sc ON sc.id = si.category_id WHERE si.id = ?", (mint,))
        self.assertEqual((row["name"], row["letter"], row["parent_id"], row["price"]),
                         ("Hill Leaf · Mint", "B", self.brand, 0))
        self.assertEqual(self.setup_item(mint)["flavour"], "Mint")
        self.assertEqual(self.sheet_item(mint)["flavour"], "Mint")

    def test_a_flavour_is_counted_in_its_brand_s_packs_at_its_brand_s_price(self):
        self.update(self.brand, packs="3×1 kg")
        mint = self.flavour("Mint")
        line = self.count(mint, blocks="1")
        self.assertEqual((line["qty_milli"], line["price"], line["value"]), (3000, 30000, 90000))

    def test_unless_it_has_its_own(self):
        grape = self.flavour("Grape")
        self.update(grape, price="36000", packs="250 g")
        line = self.count(grape, loose="2")
        self.assertEqual((line["qty_milli"], line["value"]), (500, 18000))

    def test_two_brands_can_have_the_same_flavour(self):
        other = self.add("Star Leaf", price=25000)
        for b in (self.brand, other):
            self.flavour("Mint", b)
        self.assertEqual(db.scalar(self.con, "SELECT COUNT(*) FROM stock_item "
                                             "WHERE name LIKE '% · Mint'"), 2)

    def test_the_count_sheet_puts_flavours_under_their_brand(self):
        zebra = self.add("Zebra Leaf", price=1000)
        for f in ("Mint", "Apple"):
            self.flavour(f)
        names = [i["name"] for g in api.count_sheet(self.con, ON)["groups"]
                 for i in g["items"] if g["letter"] == "B"]
        self.assertEqual(names, ["Hill Leaf", "Hill Leaf · Apple", "Hill Leaf · Mint",
                                 "Zebra Leaf"])
        self.assertEqual(self.sheet_item(self.brand)["flavours"], 2)
        self.assertEqual(self.sheet_item(zebra)["flavours"], 0)

    def test_an_old_count_by_brand_stays_by_brand(self):
        self.count(self.brand, blocks="2")
        self.flavour("Mint")
        self.assertEqual(self.sheet_item(self.brand)["value"], 30000)

    def test_a_flavour_has_no_flavours(self):
        mint = self.flavour("Mint")
        with self.assertRaises(api.ApiError):
            self.flavour("Extra", mint)

    def test_renaming_a_flavour_keeps_its_brand_in_front(self):
        mint = self.flavour("Mint")
        self.update(mint, name="Fresh Mint")
        self.assertEqual(self.row(mint)["name"], "Hill Leaf · Fresh Mint")
        self.update(mint, name="Hill Leaf · Mint")
        self.assertEqual(self.row(mint)["name"], "Hill Leaf · Mint")

    def test_renaming_a_brand_renames_its_flavours(self):
        mint = self.flavour("Mint")
        self.update(self.brand, name="Hill Gold")
        self.assertEqual(self.row(mint)["name"], "Hill Gold · Mint")
        self.assertEqual(self.setup_item(mint)["flavour"], "Mint")

    def test_a_brand_s_flavours_stop_and_come_back_with_it(self):
        mint = self.flavour("Mint")
        self.update(self.brand, active=0)
        self.assertEqual(self.row(mint)["active"], 0)
        self.update(self.brand, active=1)
        self.assertEqual(self.row(mint)["active"], 1)
        self.update(mint, active=0)
        self.assertEqual(self.row(self.brand)["active"], 1)

    def test_a_flavour_on_the_brand_s_supplier_s_statement(self):
        sup = db.scalar(self.con, "SELECT id FROM account WHERE kind = 'supplier' LIMIT 1")
        api.run(self.con, "item_supplier", {"id": self.brand, "supplier_id": sup})
        mint = self.flavour("Mint")
        self.count(mint, blocks="1")
        self.assertEqual(queries.supplier_lines(self.con, sup, ON[:7])["on_shelves"], 15000)

    # ------------------------------------------------- minimum, barcodes
    def test_a_minimum_to_warn_at(self):
        self.update(self.brand, minimum="2.5")
        self.assertEqual(self.setup_item(self.brand)["minimum"], 2.5)
        self.update(self.brand, minimum="")
        self.assertIsNone(self.setup_item(self.brand)["minimum"])
        with self.assertRaises(api.ApiError):
            self.update(self.brand, minimum="-1")

    def test_barcodes_are_added_one_scan_at_a_time(self):
        self.update(self.brand, barcode_add="6281234500011")
        self.update(self.brand, barcode_add="6281234500028")
        self.update(self.brand, barcode_add="6281234500028")          # scanned twice
        self.assertEqual(self.setup_item(self.brand)["barcodes"],
                         ["6281234500011", "6281234500028"])
        self.update(self.brand, barcode_remove="6281234500011")
        self.assertEqual(self.setup_item(self.brand)["barcodes"], ["6281234500028"])

    def test_a_barcode_belongs_to_one_item(self):
        other = self.add("Star Leaf", price=25000)
        self.update(self.brand, barcode_add="6281234500011")
        with self.assertRaises(api.ApiError) as cm:
            self.update(other, barcode_add="6281234500011")
        self.assertIn("Hill Leaf", str(cm.exception))

    def test_a_code_scanned_through_a_kurdish_layout_is_the_same_code(self):
        self.update(self.brand, barcode_add="٦٢٨١٢٣٤٥٠٠٠١١")
        self.assertEqual(self.setup_item(self.brand)["barcodes"], ["6281234500011"])

    def test_a_barcode_is_a_barcode(self):
        with self.assertRaises(api.ApiError):
            self.update(self.brand, barcode_add="<script>")
        self.assertEqual(self.setup_item(self.brand)["barcodes"], [])

    def test_setup_says_how_each_item_comes(self):
        kilo = self.add("Kilo Leaf", price=20000)
        self.update(kilo, packs="6×1 kg")
        mint = self.flavour("Mint", kilo)
        self.assertEqual([l["label"] for l in self.setup_item(kilo)["levels"]],
                         ["6×1 kg", "1 kg"])
        self.assertEqual((self.setup_item(kilo)["comes_as"],
                          self.setup_item(kilo)["comes_as_else"]), ("6×1 kg", "12×10×50 g"))
        self.assertEqual((self.setup_item(mint)["comes_as"],
                          self.setup_item(mint)["comes_as_else"]), ("", "6×1 kg"))
        self.assertEqual(self.setup_item(self.brand)["comes_as"], "")


if __name__ == "__main__":
    unittest.main()
