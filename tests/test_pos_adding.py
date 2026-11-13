"""A night from SambaPOS, added to the books in one click.

The night is the invented one from test_pos: 12,000 of takings paid into the
Cash drawer, 10,500 of ice from the drawer, a 10,000 advance to Alice, and an
expense SambaPOS reversed. More documents are added where a test needs them.
"""
import unittest

from ledger import api, db, queries
from ledger.pos import adding, archive, sources
from tests.helpers import fresh_books
from tests.test_pos import night_with_documents

NIGHT = "2026-11-10"
CASH, ICE, ALICE_POS, DRAWER2 = 5, 20, 21, 22


def with_documents(*more):
    """night_with_documents, plus more documents: (id, from account, to
    account, amount, time). Account 22 is a second drawer."""
    snap = night_with_documents()
    t = {k: [dict(r) for r in v] for k, v in snap["tables"].items()}
    t["Accounts"].append({"Id": DRAWER2, "Name": "Drawer downstairs", "AccountTypeId": 6})
    t["AccountTypes"].append({"Id": 6, "Name": "Cafeteria"})
    kinds = {2: 1, CASH: 3, ICE: 7, ALICE_POS: 8, DRAWER2: 6}
    for doc, frm, to, amount, at in more:
        at = f"{NIGHT}T{at}:00"
        t["AccountTransactionDocuments"].append({"Id": doc, "DocumentTypeId": 4, "Date": at,
                                                 "Name": f"doc {doc}"})
        t["AccountTransactions"].append({"Id": doc + 1000, "AccountTransactionDocumentId": doc})
        for vid, acc, dr, cr in ((doc * 10, frm, 0, amount), (doc * 10 + 1, to, amount, 0)):
            t["AccountTransactionValues"].append({
                "Id": vid, "AccountTransactionId": doc + 1000,
                "AccountTransactionDocumentId": doc, "AccountId": acc,
                "AccountTypeId": kinds[acc], "Date": at, "Debit": str(dr), "Credit": str(cr)})
    return {"source": "backup:test.zip", "tables": sources.normalise(t)}


class AddingANight(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.keep(night_with_documents())
        self.ids = {r["name"]: r["id"] for r in db.all_(self.con, "SELECT id, name FROM account")}
        api.run(self.con, "list_add", {"list": "expense", "value": "Ice"})

    def keep(self, snap):
        with db.tx(self.con):
            archive.keep(self.con, snap)

    def link_all(self):
        for pos_id, to in ((CASH, f"pot:{self.ids['Box']}"), (ICE, "expense:Ice"),
                           (ALICE_POS, f"staff:{self.ids['Alice']}")):
            api.run(self.con, "pos_link", {"pos_id": pos_id, "to": to})

    def plan(self):
        return adding.plan(self.con, NIGHT)

    def add(self, **more):
        return api.run(self.con, "pos_add_night", {"on": NIGHT, "allow_overdraw": True, **more})

    def entries(self, kind=None):
        rows = db.all_(self.con, "SELECT e.*, (SELECT SUM(amount) FROM posting p WHERE "
                                 "p.entry_id = e.id AND p.amount > 0) AS amount FROM entry e "
                                 "WHERE e.voided_at IS NULL AND e.happened_on = ?"
                                 + (" AND e.kind = ?" if kind else ""),
                       (NIGHT, kind) if kind else (NIGHT,))
        return [dict(r) for r in rows]

    def status(self, p=None):
        p = p or self.plan()
        return [(l["kind"] if l.get("kind") else l["words"], l["amount"], l["status"])
                for l in p["lines"]]

    # ------------------------------------------------------------- linking
    def test_an_unlinked_account_holds_the_night_back(self):
        p = self.plan()
        self.assertGreater(p["held"], 0)
        with self.assertRaises(api.ApiError) as cm:
            self.add()
        self.assertIn("link every SambaPOS account", str(cm.exception))
        self.assertEqual(self.entries(), [])

    def test_each_line_becomes_the_entry_it_is(self):
        self.link_all()
        self.assertEqual(self.status(), [
            ("daily_sales", 12000, "new"),
            ("daily_expense", 10500, "new"),
            ("staff_advance", 10000, "new"),
            ("reversed in SambaPOS", 0, "skip")])
        words = [l["words"] for l in self.plan()["lines"]]
        self.assertEqual(words[:3], ["Sales, into Box", "Expense · Ice, out of Box",
                                     "Staff advance · Alice, out of Box"])

    # -------------------------------------------------------------- adding
    def test_the_night_goes_in_with_one_click(self):
        self.link_all()
        self.assertEqual(self.add()["added"], 3)
        got = {(e["kind"], e["detail"], e["amount"], e["source"]) for e in self.entries()}
        self.assertEqual(got, {("daily_sales", "Total sales of the day", 12000, "pos"),
                               ("daily_expense", "Ice", 10500, "pos"),
                               ("staff_advance", "Alice", 10000, "pos")})
        self.assertEqual(queries.balance(self.con, "cash:box"), 12000 - 10500 - 10000)
        self.assertEqual(db.all_(self.con, "SELECT * FROM unbalanced"), [])

    def test_the_pot_guard_asks_as_usual(self):
        self.link_all()
        with self.assertRaises(api.ApiError) as cm:
            api.run(self.con, "pos_add_night", {"on": NIGHT})
        self.assertEqual(cm.exception.status, 409)
        self.assertEqual(self.entries(), [])

    def test_adding_twice_adds_nothing_twice(self):
        self.link_all()
        self.add()
        self.assertEqual({l["status"] for l in self.plan()["lines"]}, {"added", "skip"})
        with self.assertRaises(api.ApiError):
            self.add()
        self.assertEqual(len(self.entries()), 3)

    def test_and_a_fuller_copy_of_the_night_adds_only_what_is_new(self):
        self.link_all()
        self.add()
        self.keep(with_documents((310, CASH, ICE, 2500, "23:30")))
        self.assertEqual(self.add()["added"], 1)
        self.assertEqual(len(self.entries("daily_expense")), 2)

    def test_an_entry_deleted_by_hand_is_not_brought_back(self):
        self.link_all()
        self.add()
        ice = self.entries("daily_expense")[0]
        api.run(self.con, "void", {"id": ice["id"]})
        line = next(l for l in self.plan()["lines"] if l.get("kind") == "daily_expense")
        self.assertEqual(line["status"], "deleted")
        self.assertEqual(self.plan()["to_add"], 0)

    def test_a_corrected_entry_counts_as_in_the_books(self):
        self.link_all()
        self.add()
        ice = self.entries("daily_expense")[0]
        api.run(self.con, "edit_entry", {"id": ice["id"], "amount": 11000,
                                         "allow_overdraw": True})
        line = next(l for l in self.plan()["lines"] if l.get("kind") == "daily_expense")
        self.assertEqual((line["status"], line["note"]),
                         ("added", "corrected by hand in the books"))

    def test_a_line_left_out_is_not_added(self):
        self.link_all()
        api.run(self.con, "pos_link", {"pos_id": ICE, "to": "ignore"})
        self.assertEqual(self.add()["added"], 2)
        self.assertEqual(self.entries("daily_expense"), [])

    # ------------------------------------------------- typed by hand as well
    def test_a_line_already_typed_by_hand_is_not_added_again(self):
        self.link_all()
        api.run(self.con, "expense", {"amount": 10500, "detail": "Ice", "on": NIGHT,
                                      "allow_overdraw": True})
        line = next(l for l in self.plan()["lines"] if l.get("kind") == "daily_expense")
        self.assertEqual(line["status"], "typed")
        self.assertEqual(self.add()["added"], 2)
        self.assertEqual(len(self.entries("daily_expense")), 1)

    def test_one_typed_differently_is_left_to_put_right(self):
        self.link_all()
        api.run(self.con, "expense", {"amount": 12000, "detail": "Ice", "on": NIGHT,
                                      "allow_overdraw": True})
        line = next(l for l in self.plan()["lines"] if l.get("kind") == "daily_expense")
        self.assertEqual(line["status"], "check")
        self.assertIn("12,000", line["note"])
        self.add()
        self.assertEqual([e["amount"] for e in self.entries("daily_expense")], [12000])

    def test_entries_only_in_the_books_are_shown_beside(self):
        self.link_all()
        api.run(self.con, "expense", {"amount": 3000, "detail": "Tea", "on": NIGHT,
                                      "allow_overdraw": True})
        only = self.plan()["books_only"]
        self.assertEqual([(b["label"], b["detail"], b["amount"]) for b in only],
                         [("Expense", "Tea", 3000)])

    def test_takings_typed_by_hand_the_same_are_left_alone(self):
        self.link_all()
        api.run(self.con, "sales", {"amount": 12000, "on": NIGHT})
        self.assertEqual(self.plan()["lines"][0]["status"], "typed")
        self.add()
        self.assertEqual([e["source"] for e in self.entries("daily_sales")], ["manual"])

    def test_takings_typed_differently_are_left_alone_too(self):
        """Replacing them would move a night whose cash may already have been
        counted against them. Use, on Tonight, does that on purpose."""
        self.link_all()
        api.run(self.con, "sales", {"amount": 11000, "on": NIGHT})
        sales = self.plan()["lines"][0]
        self.assertEqual(sales["status"], "check")
        self.assertIn("11,000", sales["note"])
        self.add()
        self.assertEqual([(e["amount"], e["source"]) for e in self.entries("daily_sales")],
                         [(11000, "manual")])

    def test_a_fuller_copy_of_the_night_replaces_the_takings_added_before(self):
        self.link_all()
        self.add()
        # a later copy of the night, with 3,000 more paid on it
        self.con.execute("UPDATE pos_period SET takings = 15000 WHERE night = ?", (NIGHT,))
        self.con.execute("UPDATE pos_payment SET amount = amount + 3000")
        sales = self.plan()["lines"][0]
        self.assertEqual((sales["status"], sales["replaces"]), ("new", 12000))
        self.add()
        self.assertEqual([(e["amount"], e["source"]) for e in self.entries("daily_sales")],
                         [(15000, "pos")])

    def test_takings_a_fuller_copy_replaced_cannot_be_put_back_beside_it(self):
        self.link_all()
        self.add()
        old = self.entries("daily_sales")[0]["id"]
        self.con.execute("UPDATE pos_period SET takings = 15000 WHERE night = ?", (NIGHT,))
        self.con.execute("UPDATE pos_payment SET amount = amount + 3000")
        self.add()
        with self.assertRaises(api.ApiError):
            api.run(self.con, "put_back", {"id": old})
        self.assertEqual([e["amount"] for e in self.entries("daily_sales")], [15000])

    def test_the_same_money_split_differently_counts_as_typed(self):
        self.link_all()
        for amount in (5000, 5500):
            api.run(self.con, "expense", {"amount": amount, "detail": "Ice", "on": NIGHT,
                                          "allow_overdraw": True})
        line = next(l for l in self.plan()["lines"] if l.get("kind") == "daily_expense")
        self.assertEqual((line["status"], line["note"]), ("typed", "entered by hand as 10,500 in all"))

    def test_a_document_with_no_amount_is_left_out(self):
        self.link_all()
        self.keep(with_documents((340, CASH, ICE, 0, "23:40")))
        line = next(l for l in self.plan()["lines"] if l["words"] == "no amount in SambaPOS")
        self.assertEqual(line["status"], "skip")
        self.assertEqual(self.add()["added"], 3)

    def test_and_typing_the_takings_again_replaces_samba_pos_s(self):
        self.link_all()
        self.add()
        api.run(self.con, "sales", {"amount": 12500, "on": NIGHT})
        self.assertEqual([(e["amount"], e["source"]) for e in self.entries("daily_sales")],
                         [(12500, "manual")])

    # ------------------------------------------------------- other kinds
    def test_money_back_from_staff_and_moving_between_drawers(self):
        self.link_all()
        self.keep(with_documents((320, ALICE_POS, CASH, 3000, "23:00"),
                                 (321, CASH, DRAWER2, 4000, "23:10")))
        api.run(self.con, "pos_link", {"pos_id": DRAWER2, "to": f"pot:{self.ids['Safe']}"})
        kinds = {l["kind"]: l for l in self.plan()["lines"] if l.get("kind")}
        self.assertEqual(kinds["staff_repayment"]["words"], "Staff paid money back · Alice, into Box")
        self.assertEqual(kinds["transfer"]["words"], "Moved from Box to Safe")
        self.add()
        self.assertEqual(queries.balance(self.con, "cash:safe"), 4000)

    def test_a_direction_the_books_have_no_entry_for_is_left_to_enter_by_hand(self):
        self.link_all()
        self.keep(with_documents((330, ICE, CASH, 1500, "23:20")))      # ice money back
        line = next(l for l in self.plan()["lines"] if l["status"] == "manual")
        self.assertIn("enter it by hand", line["words"])
        self.assertEqual(self.add()["added"], 3)

    def test_a_closed_month_will_not_take_a_night(self):
        self.link_all()
        self.con.execute("INSERT INTO period(month, status, closed_at) VALUES "
                         "('2026-11', 'closed', datetime('now')) ON CONFLICT(month) DO "
                         "UPDATE SET status = 'closed', closed_at = datetime('now')")
        with self.assertRaises(api.ApiError):
            self.add()

    def test_it_is_in_recent_changes(self):
        self.link_all()
        self.add()
        self.assertIn("Added the night of 2026-11-10 from SambaPOS: 3 entries",
                      queries.recent(self.con)[0]["summary"])

    def test_the_screens_get_the_plan_for_the_day_on_screen(self):
        self.link_all()
        p = api.state(self.con, on=NIGHT)["pos"]["adding"]
        self.assertEqual((p["to_add"], p["held"]), (3, 0))
        self.assertIsNone(api.state(self.con, on="2026-11-01")["pos"]["adding"])


if __name__ == "__main__":
    unittest.main()
