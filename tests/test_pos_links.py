"""What each SambaPOS account is in the books.

The night here is the invented one from test_pos: SambaPOS's Cash drawer, an
expense account for ice, and an account for Alice, who is on the staff. Links
are by SambaPOS's number for an account, so a rename, a deletion and an
account made again are each tested.
"""
import json
import unittest

from ledger import api, checks, db
from ledger.pos import adding, archive, links
from tests.helpers import fresh_books
from tests.test_pos import night_with_documents

ICE, ALICE_POS, CASH = 20, 21, 5


def renamed(snap, **names):
    """The same snapshot, a day later, with some accounts renamed (or None to
    drop one)."""
    t = {k: [dict(r) for r in v] for k, v in snap["tables"].items()}
    accounts = []
    for a in t["Accounts"]:
        new = names.get(f"a{a['Id']}", a["Name"])
        if new is not None:
            accounts.append({**a, "Name": new})
    t["Accounts"] = accounts
    return {**snap, "tables": t, "at": "2026-11-12 03:00:00"}


class Linking(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.keep(night_with_documents())
        self.alice = db.scalar(self.con, "SELECT id FROM account WHERE name = 'Alice'")
        self.box = db.scalar(self.con, "SELECT id FROM account WHERE code = 'cash:box'")
        api.run(self.con, "list_add", {"list": "expense", "value": "Ice"})

    def keep(self, snap):
        with db.tx(self.con):
            return archive.keep(self.con, snap)

    def link(self, pos_id, to):
        return api.run(self.con, "pos_link", {"pos_id": pos_id, "to": to})

    def row(self, pos_id):
        return next(r for r in links.listing(self.con) if r["pos_id"] == pos_id)

    def labels(self):
        return {c["label"]: c for c in checks.checks(self.con, "2026-11")}

    # ------------------------------------------------------- the accounts
    def test_samba_pos_s_accounts_are_kept_with_the_night(self):
        rows = {r["pos_id"]: r for r in db.all_(self.con, "SELECT * FROM pos_account")}
        self.assertEqual(rows[ALICE_POS]["name"], "ئالیس")
        self.assertEqual(rows[ALICE_POS]["type_name"], "Staff")
        self.assertEqual(rows[CASH]["type_name"], "Payment Accounts")

    def test_an_older_snapshot_does_not_undo_a_rename(self):
        self.keep(renamed(night_with_documents(), a21="ئالیسی نوێ"))
        self.keep(night_with_documents())                  # brought in late
        self.assertEqual(self.row(ALICE_POS)["name"], "ئالیسی نوێ")

    # ----------------------------------------------------------- linking
    def test_an_account_is_linked_once_by_its_number(self):
        out = self.link(ALICE_POS, f"staff:{self.alice}")
        self.assertEqual(out["label"], "Staff · Alice")
        self.assertEqual(self.row(ALICE_POS)["link"]["value"], f"staff:{self.alice}")

    def test_a_rename_in_samba_pos_keeps_the_link(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        self.keep(renamed(night_with_documents(), a21="ئالیس کەریم"))
        r = self.row(ALICE_POS)
        self.assertEqual(r["name"], "ئالیس کەریم")
        self.assertEqual(r["link"]["label"], "Staff · Alice")
        self.assertEqual(r["link"]["name_then"], "ئالیس")

    def test_an_expense_account_becomes_an_expense(self):
        self.assertEqual(self.link(ICE, "expense:Ice")["label"], "Expense · Ice")

    def test_or_a_new_expense_named_as_samba_pos_names_it(self):
        out = self.link(ICE, "new-expense")
        self.assertEqual(out["value"], "expense:سەهۆڵ")
        self.assertIn("سەهۆڵ", api.pick_lists(self.con)["expense"])

    def test_the_drawer_is_a_pot(self):
        self.assertEqual(self.link(CASH, f"pot:{self.box}")["label"], "Pot · Box")

    def test_anything_else_can_be_left_out(self):
        self.assertEqual(self.link(ICE, "ignore")["label"], "Left out")

    def test_a_link_must_point_at_something_real(self):
        for bad in (f"pot:{self.alice}", "staff:99999", "expense:Not on the list",
                    "staff:x", "", "anything"):
            with self.assertRaises(api.ApiError, msg=bad):
                self.link(ALICE_POS, bad)
        with self.assertRaises(api.ApiError):
            self.link(4242, "ignore")                  # no such SambaPOS account

    def test_linking_is_in_recent_changes(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        line = api.queries.recent(self.con)[0]["summary"]
        self.assertIn("ئالیس", line)
        self.assertIn("Staff · Alice", line)

    # --------------------------------------------------------- suggesting
    def test_a_plain_name_match_is_suggested(self):
        api.run(self.con, "list_add", {"list": "expense", "value": "سەهۆڵ"})
        self.assertEqual(self.row(ICE)["suggest"], "expense:سەهۆڵ")

    def test_but_nothing_is_guessed(self):
        self.assertIsNone(self.row(ALICE_POS)["suggest"])     # ئالیس is not "Alice"

    def test_the_drawer_is_suggested_as_the_main_pot(self):
        self.assertEqual(self.row(CASH)["suggest"], f"pot:{self.box}")

    def test_an_account_made_again_gets_the_old_link_suggested(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        snap = renamed(night_with_documents(), a21=None)
        snap["tables"]["Accounts"].append({"Id": 22, "Name": "ئالیس", "AccountTypeId": 8})
        self.keep(snap)
        self.assertEqual(self.row(22)["suggest"], f"staff:{self.alice}")

    def test_tonight_shows_each_account_with_its_link_or_asks(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        self.link(CASH, f"pot:{self.box}")
        api.run(self.con, "list_add", {"list": "expense", "value": "سەهۆڵ"})
        lines = {l["account"]["pos_id"]: l for l in adding.plan(self.con, "2026-11-10")["lines"]
                 if l.get("account")}
        self.assertEqual(lines[ALICE_POS]["account"]["link"]["label"], "Staff · Alice")
        self.assertEqual(lines[ICE]["status"], "held")
        self.assertEqual(lines[ICE]["account"]["suggest"], "expense:سەهۆڵ")

    # ------------------------------------------------------------ listing
    def test_setup_lists_what_money_moved_through_and_its_kind(self):
        snap = night_with_documents()
        snap["tables"]["Accounts"].append({"Id": 23, "Name": "شیر", "AccountTypeId": 7})
        self.keep(renamed(snap))
        listed = {r["pos_id"] for r in links.listing(self.con)}
        self.assertIn(23, listed)                  # unused, but an expense account
        self.assertIn(CASH, listed)
        self.assertNotIn(2, listed)                # Receivables: never moves drawer money

    def test_books_kept_before_accounts_were_remembered_still_list_them(self):
        self.con.execute("DELETE FROM pos_account")
        listed = {r["pos_id"]: r for r in links.listing(self.con)}
        self.assertEqual(listed[ALICE_POS]["name"], "ئالیس")
        self.link(ALICE_POS, f"staff:{self.alice}")

    # -------------------------------------------------- gone, and left
    def test_an_account_samba_pos_no_longer_has_asks_if_they_left(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        self.keep(renamed(night_with_documents(), a21=None))
        self.assertTrue(self.row(ALICE_POS)["gone"])
        c = self.labels()["Everyone SambaPOS has dropped is marked as left"]
        self.assertFalse(c["ok"])
        self.assertIn("Alice", c["detail"])
        api.run(self.con, "pos_left", {"pos_id": ALICE_POS})
        self.assertEqual(db.scalar(self.con, "SELECT active FROM account WHERE id = ?",
                                   (self.alice,)), 0)
        self.assertNotIn("Everyone SambaPOS has dropped is marked as left", self.labels())

    def test_the_day_they_left_is_kept_for_their_salary(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        self.keep(renamed(night_with_documents(), a21=None))
        out = api.run(self.con, "pos_left", {"pos_id": ALICE_POS, "left_on": "2026-11-10"})
        meta = json.loads(db.scalar(self.con, "SELECT meta FROM account WHERE id = ?",
                                    (self.alice,)))
        self.assertEqual((meta["left_on"], meta["left_after"]), ("2026-11-10", "2026-11"))
        self.assertIsNone(out["note"])

    def test_only_a_person_can_be_marked_as_left(self):
        self.link(ICE, "expense:Ice")
        with self.assertRaises(api.ApiError):
            api.run(self.con, "pos_left", {"pos_id": ICE})

    def test_money_recorded_for_someone_who_left_is_pointed_out_once(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        self.link(CASH, f"pot:{self.box}")
        self.leave(self.alice, "2026-11-01")           # the night is the 10th
        c = self.labels()["Nobody who has left is still in SambaPOS"]
        self.assertFalse(c["ok"])
        self.assertIn("Alice", c["detail"])
        line = next(l for l in adding.plan(self.con, "2026-11-10")["lines"]
                    if l.get("account") and l["account"]["pos_id"] == ALICE_POS)
        self.assertTrue(line["account"]["link"]["left"])
        api.run(self.con, "pos_told", {"pos_id": ALICE_POS})
        self.assertNotIn("Nobody who has left is still in SambaPOS", self.labels())

    def test_money_from_before_they_left_is_not(self):
        self.link(ALICE_POS, f"staff:{self.alice}")
        self.leave(self.alice, "2026-11-20")
        self.assertNotIn("Nobody who has left is still in SambaPOS", self.labels())

    def leave(self, aid, on):
        meta = json.loads(db.scalar(self.con, "SELECT meta FROM account WHERE id = ?",
                                    (aid,)) or "{}")
        meta["retired_on"] = on
        self.con.execute("UPDATE account SET active = 0, meta = ? WHERE id = ?",
                         (json.dumps(meta), aid))

    # ------------------------------------------------------------ the state
    def test_the_screens_get_all_of_it(self):
        p = api.state(self.con, on="2026-11-10")["pos"]
        self.assertEqual([g["group"] for g in p["targets"]],
                         ["Expense", "Staff", "Partner", "Supplier", "Other income", "Pot"])
        self.assertIn([f"staff:{self.alice}", "Alice"], p["targets"][1]["options"])
        self.assertTrue(any(r["pos_id"] == ALICE_POS for r in p["accounts"]))
        self.assertEqual((p["gone"], p["left_used"]), ([], []))


if __name__ == "__main__":
    unittest.main()
