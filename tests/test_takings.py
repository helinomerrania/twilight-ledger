"""A night has one set of takings: the figure typed in, or SambaPOS's lines,
one for each way of paying. Nothing that puts an entry back, or moves one to
another night, may leave a night with its sales counted twice. Everything
here is invented."""
import unittest

from ledger import api, db, post, queries
from tests.helpers import fresh_books

ON, OTHER = "2026-11-09", "2026-11-08"


class OneSetOfTakings(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def sales(self, on=ON):
        return sorted(e["amount"] for e in queries.entries(self.con, on=on, kind="daily_sales"))

    def test_a_deleted_figure_is_not_put_back_beside_a_newer_one(self):
        old = api.run(self.con, "sales", {"amount": 400000, "on": ON})["id"]
        api.run(self.con, "void", {"id": old})
        api.run(self.con, "sales", {"amount": 450000, "on": ON})
        with self.assertRaises(api.ApiError) as cm:
            api.run(self.con, "put_back", {"id": old})
        self.assertIn("already has its takings", str(cm.exception))
        self.assertEqual(self.sales(), [450000])

    def test_it_comes_back_once_the_newer_one_is_deleted(self):
        old = api.run(self.con, "sales", {"amount": 400000, "on": ON})["id"]
        api.run(self.con, "void", {"id": old})
        new = api.run(self.con, "sales", {"amount": 450000, "on": ON})["id"]
        api.run(self.con, "void", {"id": new})
        api.run(self.con, "put_back", {"id": old})
        self.assertEqual(self.sales(), [400000])

    def test_a_figure_is_not_moved_onto_a_night_that_has_one(self):
        api.run(self.con, "sales", {"amount": 400000, "on": ON})
        other = api.run(self.con, "sales", {"amount": 450000, "on": OTHER})["id"]
        with self.assertRaises(api.ApiError):
            api.run(self.con, "edit_entry", {"id": other, "on": ON})
        self.assertEqual((self.sales(), self.sales(OTHER)), ([400000], [450000]))

    def test_but_it_can_still_be_moved_to_an_empty_night_or_corrected_where_it_is(self):
        other = api.run(self.con, "sales", {"amount": 450000, "on": OTHER})["id"]
        moved = api.run(self.con, "edit_entry", {"id": other, "on": ON})["id"]
        api.run(self.con, "edit_entry", {"id": moved, "amount": 460000})
        self.assertEqual((self.sales(), self.sales(OTHER)), ([460000], []))

    def pos_lines(self):
        """Two SambaPOS lines for one night: cash into the Box, card into the Bank."""
        ids = [post.sales(self.con, 300000, on=ON, into="Box", source="pos",
                          source_ref=f"pos:sales:{ON}:Cash:300000"),
               post.sales(self.con, 100000, on=ON, into="Bank", source="pos",
                          source_ref=f"pos:sales:{ON}:Card:100000")]
        return ids

    def test_sambapos_lines_stand_together(self):
        cash, _card = self.pos_lines()
        api.run(self.con, "void", {"id": cash})
        api.run(self.con, "put_back", {"id": cash})
        self.assertEqual(self.sales(), [100000, 300000])

    def test_but_not_beside_a_typed_figure(self):
        cash, card = self.pos_lines()
        for i in (cash, card):
            api.run(self.con, "void", {"id": i})
        api.run(self.con, "sales", {"amount": 410000, "on": ON})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "put_back", {"id": cash})

    def test_a_typed_figure_taken_back_brings_sambapos_lines_back_together(self):
        self.pos_lines()
        typed = api.run(self.con, "sales", {"amount": 410000, "on": ON})["id"]
        back = api.run(self.con, "undo", {"id": typed})
        self.assertEqual((len(back["put_back"]), self.sales()), (2, [100000, 300000]))

    def test_lines_replaced_by_a_fuller_copy_of_the_night_stay_replaced(self):
        from ledger.pos import adding
        stale = post.sales(self.con, 300000, on=ON, source="pos",
                           source_ref=f"pos:sales:{ON}:300000")
        plan = {"night": ON, "lines": [
            {"kind": "daily_sales", "status": "new", "amount": 350000, "pot": "Box",
             "detail": "Total sales of the day", "ref": f"pos:sales:{ON}:350000"}]}
        with db.tx(self.con):
            adding.add(self.con, plan)
        with self.assertRaises(api.ApiError):
            api.run(self.con, "put_back", {"id": stale})
        self.assertEqual(self.sales(), [350000])


if __name__ == "__main__":
    unittest.main()
