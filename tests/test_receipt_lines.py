"""What a supplier receipt brought in, line by line (plan step 3.2). Only the
receipt's total moves money; the lines say what came onto the shelves. The
items, suppliers and prices are invented."""
import unittest

from ledger import api, db
from tests.helpers import SUPPLIERS, fresh_books

ON = "2026-11-09"


class Lines(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.brand = self.item("Hill Leaf", "B", 30000)
        self.cups = self.item("Cups", "C", 5000, pack_size=50)
        out = api.run(self.con, "receipt", {"amount": 900000, "on": ON, "who": SUPPLIERS[0],
                                            "terms": "credit"})
        self.entry, self.receipt = out["id"], out["receipt"]

    def item(self, name, letter, price, **more):
        return api.run(self.con, "item_add", {"name": name, "letter": letter,
                                              "price": price, **more})["id"]

    def line(self, item, receipt=None, **boxes):
        return api.run(self.con, "receipt_line",
                       {"receipt": receipt or self.receipt, "item": item, **boxes})

    def shown(self):
        """The receipt's lines as the Stock screen gets them."""
        for e in api.state(self.con)["stock"]["receipts"]:
            if e["id"] == self.entry:
                return e["lines"]
        raise AssertionError("the receipt is not on the Stock screen")

    def postings(self):
        return db.scalar(self.con, "SELECT COUNT(*) FROM posting")

    def test_a_new_receipt_says_which_receipt_it_made(self):
        self.assertEqual(db.scalar(self.con, "SELECT entry_id FROM receipt WHERE id = ?",
                                   (self.receipt,)), self.entry)
        self.assertEqual(self.shown(), [])

    def test_tobacco_by_the_carton_comes_in_as_kilos(self):
        self.line(self.brand, packages="2", amount="350000")
        [l] = self.shown()
        self.assertEqual((l["name"], l["qty_milli"], l["amount"], l["packages_milli"]),
                         ("Hill Leaf", 12000, 350000, 2000))        # 2 x 12 x 10 x 50 g
        self.assertEqual([x["label"] for x in l["levels"]], ["12×10×50 g", "10×50 g", "50 g"])

    def test_in_the_packs_it_comes_in(self):
        api.run(self.con, "item_update", {"id": self.brand, "packs": "3×1 kg"})
        mint = api.run(self.con, "item_add", {"brand": self.brand, "name": "Mint"})["id"]
        self.line(mint, blocks="2", loose="1")
        self.assertEqual(self.shown()[0]["qty_milli"], 7000)

    def test_pieces_come_in_as_packages(self):
        self.line(self.cups, packages="3", loose="25")
        [l] = self.shown()
        self.assertEqual(l["qty_milli"], 3500)
        self.assertEqual([x["label"] for x in l["levels"]], ["packages of 50", "pieces"])

    def test_the_amount_can_be_left_out(self):
        self.line(self.cups, packages="1")
        self.assertIsNone(self.shown()[0]["amount"])

    def test_the_same_item_again_changes_its_line(self):
        self.line(self.brand, packages="1")
        self.line(self.brand, blocks="5")
        [l] = self.shown()
        self.assertEqual((l["packages_milli"], l["blocks_milli"], l["qty_milli"]), (0, 5000, 2500))

    def test_empty_boxes_take_the_line_off(self):
        self.line(self.brand, packages="1")
        self.line(self.brand, packages="", amount="")
        self.assertEqual(self.shown(), [])

    def test_an_amount_alone_is_refused(self):
        with self.assertRaises(api.ApiError):
            self.line(self.brand, amount="50000")

    def test_nothing_less_than_nothing(self):
        for bad in ({"packages": "-1"}, {"packages": "1", "amount": "-5"}, {"packages": "x"}):
            with self.assertRaises(api.ApiError, msg=str(bad)):
                self.line(self.brand, **bad)

    def test_a_mix_is_made_here_not_bought(self):
        mix = self.item("House Mix", "A", 25000)
        with self.assertRaises(api.ApiError):
            self.line(mix, packages="1")

    def test_only_the_total_moves_money(self):
        owed = api.state(self.con)["people"]["supplier"]
        before = self.postings()
        self.line(self.brand, packages="2", amount="350000")
        self.line(self.cups, packages="3", amount="15000")
        self.assertEqual(self.postings(), before)
        self.assertEqual(api.state(self.con)["people"]["supplier"], owed)

    def test_lines_follow_a_corrected_receipt(self):
        self.line(self.brand, packages="2", amount="350000")
        new = api.run(self.con, "edit_entry", {"id": self.entry, "amount": 950000})["id"]
        self.entry = new
        [l] = self.shown()
        self.assertEqual(l["qty_milli"], 12000)
        self.assertEqual(db.scalar(self.con, "SELECT COUNT(*) FROM receipt_line"), 1)

    def test_a_deleted_receipt_s_lines_come_back_with_it(self):
        self.line(self.brand, packages="1")
        api.run(self.con, "void", {"id": self.entry})
        with self.assertRaises(api.ApiError):
            self.line(self.cups, packages="1")
        api.run(self.con, "put_back", {"id": self.entry})
        self.assertEqual(len(self.shown()), 1)

    def test_a_closed_month_s_receipt_is_kept_as_it_was(self):
        self.line(self.brand, packages="1")
        self.con.execute("INSERT INTO period(month, status, closed_at) VALUES "
                         "('2026-11', 'closed', 'x') ON CONFLICT(month) DO "
                         "UPDATE SET status = 'closed', closed_at = 'x'")
        with self.assertRaises(api.ApiError):
            self.line(self.brand, packages="2")
        with self.assertRaises(api.ApiError):
            self.line(self.brand, packages="")

    def test_no_such_receipt(self):
        with self.assertRaises(api.ApiError):
            self.line(self.brand, receipt=9999, packages="1")

    def test_it_is_in_recent_changes(self):
        self.line(self.brand, packages="1")
        self.line(self.brand, packages="")
        said = [r["summary"] for r in db.all_(
            self.con, "SELECT json_extract(detail, '$.summary') AS summary FROM audit "
                      "ORDER BY id DESC LIMIT 2")]
        self.assertEqual(said, ["Took Hill Leaf off a receipt", "Receipt line: Hill Leaf"])


if __name__ == "__main__":
    unittest.main()
