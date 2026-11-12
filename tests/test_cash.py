"""Cash you can trust (plan step 2): cash and card kept apart, the count set
beside what SambaPOS says, the float, a blind count, and differences over
time. The lounge and the night are invented."""
import unittest

from ledger import api, cash, db, queries
from ledger.pos import adding, archive, sources
from tests.helpers import fresh_books
from tests.test_pos import night_with_documents

NIGHT = "2026-11-10"
CASH_ACCOUNT, CARD_ACCOUNT, ICE, ALICE_POS = 5, 24, 20, 21


def card_night(*, types=True, card=8000):
    """The invented night, with a second ticket paid by card into its own
    SambaPOS account."""
    snap = night_with_documents()
    t = {k: [dict(r) for r in v] for k, v in snap["tables"].items()}
    t["Accounts"].append({"Id": CARD_ACCOUNT, "Name": "Card machine", "AccountTypeId": 3})
    t["Tickets"].append({"Id": 2102, "TicketNumber": "3", "Date": f"{NIGHT}T22:00:00",
                         "LastPaymentDate": f"{NIGHT}T22:30:00", "IsClosed": True,
                         "RemainingAmount": "0", "TotalAmount": str(card)})
    t["Payments"].append({"Id": 2, "TicketId": 2102, "Name": "Card",
                          "Date": f"{NIGHT}T22:30:00", "Amount": str(card)})
    if types:
        t["PaymentTypes"] = [{"Id": 1, "Name": "Cash", "Account_Id": CASH_ACCOUNT},
                             {"Id": 2, "Name": "Card", "Account_Id": CARD_ACCOUNT}]
        for p in t["Payments"]:
            p["PaymentTypeId"] = 1 if p["Name"] == "Cash" else 2
    raw = {k: t.get(k, []) for k in sources.TABLES}
    return {"source": "backup:test.zip", "tables": sources.normalise(raw)}


class Base(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.ids = {r["name"]: r["id"] for r in db.all_(self.con, "SELECT id, name FROM account")}
        api.run(self.con, "list_add", {"list": "expense", "value": "Ice"})

    def keep(self, snap):
        with db.tx(self.con):
            archive.keep(self.con, snap)

    def link(self, pos_id, to):
        api.run(self.con, "pos_link", {"pos_id": pos_id, "to": to})

    def link_all(self, card=True):
        self.link(CASH_ACCOUNT, f"pot:{self.ids['Box']}")
        self.link(ICE, "expense:Ice")
        self.link(ALICE_POS, f"staff:{self.ids['Alice']}")
        if card:
            self.link(CARD_ACCOUNT, f"pot:{self.ids['Bank']}")

    def takings(self):
        return [(l.get("words"), l["amount"], l["status"])
                for l in adding.plan(self.con, NIGHT)["lines"] if l["what"] == "Takings"]


class CashAndCard(Base):
    """2.1: only cash goes to the Box, so the count compares cash with cash."""

    def test_each_way_of_paying_goes_to_its_own_pot(self):
        self.keep(card_night())
        self.link_all()
        self.assertEqual(self.takings(), [("Sales by Cash, into Box", 12000, "new"),
                                          ("Sales by Card, into Bank", 8000, "new")])
        api.run(self.con, "pos_add_night", {"on": NIGHT, "allow_overdraw": True})
        self.assertEqual(queries.balance(self.con, "cash:bank"), 8000)
        self.assertEqual(queries.balance(self.con, "cash:box"), 12000 - 10500 - 10000)
        self.assertEqual(queries.day(self.con, NIGHT)["sales"], 20000)

    def test_a_way_of_paying_not_linked_yet_holds_the_night(self):
        self.keep(card_night())
        self.link_all(card=False)
        held = [l for l in adding.plan(self.con, NIGHT)["lines"] if l["status"] == "held"]
        self.assertEqual([l["account"]["pos_id"] for l in held], [CARD_ACCOUNT])

    def test_one_that_is_not_a_pot_is_left_to_enter_by_hand(self):
        self.keep(card_night())
        self.link_all(card=False)
        self.link(CARD_ACCOUNT, "ignore")
        line = next(l for l in adding.plan(self.con, NIGHT)["lines"] if l["status"] == "manual")
        self.assertIn("paid by Card", line["words"])

    def test_takings_typed_by_hand_are_matched_on_the_total(self):
        self.keep(card_night())
        self.link_all()
        api.run(self.con, "sales", {"amount": 20000, "on": NIGHT})
        self.assertEqual({s for _, _, s in self.takings()}, {"typed"})

    def test_a_night_kept_before_payment_types_were_goes_to_the_drawer(self):
        self.keep(card_night(types=False))
        self.link_all()
        self.assertEqual(self.takings(), [("Sales, into Box", 20000, "new")])

    def test_a_fuller_copy_only_replaces_the_way_of_paying_that_changed(self):
        self.keep(card_night())
        self.link_all()
        api.run(self.con, "pos_add_night", {"on": NIGHT, "allow_overdraw": True})
        self.keep(card_night(card=9000))
        self.assertEqual(self.takings(), [("Sales by Cash, into Box", 12000, "added"),
                                          ("Sales by Card, into Bank", 9000, "new")])
        api.run(self.con, "pos_add_night", {"on": NIGHT, "allow_overdraw": True})
        self.assertEqual(queries.day(self.con, NIGHT)["sales"], 21000)
        self.assertEqual(queries.balance(self.con, "cash:bank"), 9000)


class AgainstSambaPOS(Base):
    """2.2: what SambaPOS says moved through the drawer, beside the count."""

    def test_the_drawer_as_sambapos_saw_it(self):
        self.keep(night_with_documents())
        self.link_all(card=False)
        d = cash.drawer(self.con, NIGHT)
        self.assertEqual(d["pot"], "Box")
        self.assertEqual((d["pos"]["cash"], d["pos"]["out"], d["pos"]["in"], d["pos"]["net"]),
                         (12000, 20500, 0, -8500))
        self.assertNotIn("expected", d["pos"])

    def test_card_takings_are_not_counted_in_the_drawer(self):
        self.keep(card_night())
        self.link_all()
        self.assertEqual(cash.drawer(self.con, NIGHT)["pos"]["cash"], 12000)

    def test_with_a_float_it_says_what_should_be_there(self):
        self.keep(night_with_documents())
        self.link_all(card=False)
        api.run(self.con, "cash_settings", {"float": "50000"})
        self.assertEqual(cash.drawer(self.con, NIGHT)["pos"]["expected"], 50000 - 8500)

    def test_sales_that_are_not_sambapos_s_are_pointed_out(self):
        """If they were worked out from the count, a shortage is hidden in them."""
        self.keep(night_with_documents())
        self.link_all(card=False)
        api.run(self.con, "sales", {"amount": 11000, "on": NIGHT})
        self.assertEqual(cash.drawer(self.con, NIGHT)["sales_differ"],
                         {"books": 11000, "pos": 12000, "gap": 1000})
        api.run(self.con, "sales", {"amount": 12000, "on": NIGHT})
        self.assertIsNone(cash.drawer(self.con, NIGHT)["sales_differ"])

    def test_a_night_sambapos_never_kept_has_nothing_to_say(self):
        d = cash.drawer(self.con, "2026-11-01")
        self.assertEqual((d["pos"], d["sales_differ"], d["pot"]), (None, None, "Box"))


class FloatAndBlind(Base):
    """2.3 and 2.4."""

    def test_the_settings(self):
        api.run(self.con, "cash_settings", {"float": "50000", "blind": "1", "rest_to": "Safe"})
        d = api.state(self.con, on=NIGHT)["drawer"]
        self.assertEqual((d["float"], d["blind"], d["rest_to"]), (50000, True, "Safe"))
        api.run(self.con, "cash_settings", {"blind": "0"})
        self.assertFalse(cash.settings(self.con)["blind"])

    def test_a_float_cannot_be_less_than_nothing(self):
        with self.assertRaises(api.ApiError):
            api.run(self.con, "cash_settings", {"float": "-250"})

    def test_the_rest_goes_to_a_pot(self):
        with self.assertRaises(api.ApiError):
            api.run(self.con, "cash_settings", {"rest_to": "Alice"})

    def test_moving_the_rest_after_the_count_leaves_the_float(self):
        api.run(self.con, "cash_settings", {"float": "25000"})
        api.run(self.con, "sales", {"amount": 90000, "on": NIGHT})
        api.run(self.con, "cash_count", {"on": NIGHT, "pots": {"Box": 89000}})
        api.run(self.con, "move_rest", {"on": NIGHT, "to": "Safe", "amount": 89000 - 25000})
        c = queries.cash_counts(self.con)[-1]
        self.assertEqual((c["found"], c["diff"]), (-1000, -1000))    # the count is untouched
        self.assertEqual(queries.balance(self.con, "cash:box"), 25000 + 1000)
        self.assertEqual(queries.balance(self.con, "cash:safe"), 64000)
        self.assertEqual(cash.drawer(self.con, NIGHT)["moved"], 64000)

    def test_a_count_says_how_far_out_it_is_whatever_the_night(self):
        """The screen keeps only the latest thirty counts, so an older night
        counted again must say its own difference, not "ties"."""
        for day in range(1, 32):
            api.run(self.con, "cash_count", {"on": f"2026-10-{day:02d}", "pots": {"Box": 0}})
        api.run(self.con, "sales", {"amount": 5000, "on": "2026-09-30"})
        out = api.run(self.con, "cash_count", {"on": "2026-09-30", "pots": {"Box": 1000}})
        self.assertEqual(out["diff"], -4000)
        self.assertNotIn("2026-09-30", [c["on"] for c in api.state(self.con)["counts"]])

    def test_closing_up_shows_the_night_s_own_count_after_the_rest_is_moved(self):
        """The Box card set the count against the Box after the rest had gone
        to the Safe: 89,000 counted against 26,000 read as 63,000 over, when
        the night was 1,000 short."""
        api.run(self.con, "cash_settings", {"float": "25000"})
        api.run(self.con, "sales", {"amount": 90000, "on": NIGHT})
        api.run(self.con, "cash_count", {"on": NIGHT, "pots": {"Box": 89000}})
        api.run(self.con, "move_rest", {"on": NIGHT, "to": "Safe", "amount": 64000})
        box = next(p for p in api.state(self.con, on=NIGHT)["day"]["count"]["pots"]
                   if p["name"] == "Box")
        self.assertEqual((box["counted"], box["diff"]), (89000, -1000))

    def test_an_old_night_s_count_is_on_its_night(self):
        api.run(self.con, "cash_count", {"on": "2026-09-30", "pots": {"Box": 1000, "Safe": 0}})
        for day in range(1, 32):
            api.run(self.con, "cash_count", {"on": f"2026-10-{day:02d}", "pots": {"Box": 0}})
        st = api.state(self.con, on="2026-09-30")
        self.assertEqual(sorted(p["name"] for p in st["day"]["count"]["pots"]), ["Box", "Safe"])

    def test_a_drop_to_the_safe_earlier_in_the_night_is_not_the_rest(self):
        """Money taken from the Box to the Safe during a busy night made
        Closing up think the rest had been moved, and the step went away."""
        api.run(self.con, "cash_settings", {"float": "25000"})
        api.run(self.con, "sales", {"amount": 400000, "on": NIGHT})
        api.run(self.con, "transfer", {"amount": 200000, "from": "Box", "to": "Safe", "on": NIGHT})
        api.run(self.con, "cash_count", {"on": NIGHT, "pots": {"Box": 200000}})
        self.assertEqual(cash.drawer(self.con, NIGHT)["moved"], 0)
        api.run(self.con, "move_rest", {"on": NIGHT, "to": "Safe", "amount": 175000})
        self.assertEqual(cash.drawer(self.con, NIGHT)["moved"], 175000)

    def test_a_write_off_put_back_stays_on_its_own_night(self):
        """A deleted count's number is given to the next count. A write-off
        of the old night, put back, landed on the new night's count."""
        a, b = "2026-11-08", "2026-11-09"
        api.run(self.con, "sales", {"amount": 100000, "on": a})
        first = api.run(self.con, "cash_count", {"on": a, "pots": {"Box": 90000}})["id"]
        api.run(self.con, "write_off", {"id": first, "reason": "short"})
        off = db.scalar(self.con, "SELECT id FROM entry WHERE kind = 'cash_difference'")
        api.run(self.con, "void", {"id": off})
        api.run(self.con, "delete_cash_count", {"id": first})
        api.run(self.con, "sales", {"amount": 50000, "on": b})
        second = api.run(self.con, "cash_count", {"on": b, "pots": {"Box": 150000}})["id"]
        api.run(self.con, "put_back", {"id": off})
        night = next(c for c in queries.cash_counts(self.con) if c["id"] == second)
        # the books lost 10,000 on the 8th again, so the 9th's count is over by
        # it, but nothing was written off on the 9th
        self.assertEqual((night["written_off"], night["found"], night["diff"]), (0, 10000, 10000))
        # and it does not stop the new night's count being deleted
        api.run(self.con, "delete_cash_count", {"id": second})

    def test_the_rest_goes_only_to_a_pot_in_use(self):
        api.run(self.con, "sales", {"amount": 90000, "on": NIGHT})
        api.run(self.con, "cash_count", {"on": NIGHT, "pots": {"Box": 90000}})
        safe = db.scalar(self.con, "SELECT id FROM account WHERE name = 'Safe'")
        api.run(self.con, "account_active", {"id": safe, "active": 0})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "move_rest", {"on": NIGHT, "to": "Safe", "amount": 1000})

    def test_and_the_next_night_s_count_starts_from_the_float(self):
        api.run(self.con, "sales", {"amount": 90000, "on": NIGHT})
        api.run(self.con, "cash_count", {"on": NIGHT, "pots": {"Box": 90000}})
        api.run(self.con, "move_rest", {"on": NIGHT, "to": "Safe", "amount": 65000})
        api.run(self.con, "sales", {"amount": 10000, "on": "2026-11-11"})
        api.run(self.con, "cash_count", {"on": "2026-11-11", "pots": {"Box": 35000}})
        self.assertEqual(queries.cash_counts(self.con)[-1]["found"], 0)

    def test_moving_the_rest_needs_a_count_and_somewhere_else(self):
        api.run(self.con, "sales", {"amount": 90000, "on": NIGHT})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "move_rest", {"on": NIGHT, "to": "Safe", "amount": 1000})
        api.run(self.con, "cash_count", {"on": NIGHT, "pots": {"Box": 90000}})
        for body in ({"to": "Box", "amount": 1000}, {"to": "", "amount": 1000},
                     {"to": "Safe", "amount": 0}):
            with self.assertRaises(api.ApiError, msg=str(body)):
                api.run(self.con, "move_rest", {"on": NIGHT, **body})

    def test_what_was_moved_out_of_the_drawer_after_the_count(self):
        api.run(self.con, "cash_settings", {"float": "25000"})
        api.run(self.con, "sales", {"amount": 90000, "on": NIGHT})
        api.run(self.con, "cash_count", {"on": NIGHT, "pots": {"Box": 90000}})
        self.assertEqual(cash.drawer(self.con, NIGHT)["moved"], 0)
        api.run(self.con, "move_rest", {"on": NIGHT, "to": "Safe", "amount": 65000})
        self.assertEqual(cash.drawer(self.con, NIGHT)["moved"], 65000)


class OverTime(Base):
    """2.5: each count's difference over the month, and who opened."""

    def count(self, on, sales, counted):
        api.run(self.con, "sales", {"amount": sales, "on": on})
        api.run(self.con, "cash_count", {"on": on, "pots": {"Box": counted}})

    def test_each_count_s_difference_and_the_totals(self):
        box = 0
        for on, sales, off in (("2026-11-08", 50000, -1000), ("2026-11-09", 60000, 0),
                               ("2026-11-10", 40000, 500)):
            box += sales
            self.count(on, sales, box + off)
            box += off
        d = cash.differences(self.con, "2026-11")
        self.assertEqual([(r["on"], r["found"]) for r in d["rows"]],
                         [("2026-11-08", -1000), ("2026-11-09", 0), ("2026-11-10", 500)])
        self.assertEqual((d["short"], d["over"], d["net"]), (-1000, 500, -500))

    def test_grouped_by_who_opened_sambapos(self):
        snap = night_with_documents()
        snap["tables"]["WorkPeriods"][0]["StartByName"] = "Dara"
        self.keep(snap)
        self.count("2026-11-10", 30000, 29000)
        d = cash.differences(self.con, "2026-11")
        self.assertEqual(d["rows"][0]["opened_by"], "Dara")
        self.assertEqual([(g["who"], g["nights"], g["short"], g["net"]) for g in d["by_who"]],
                         [("Dara", 1, 1, -1000)])

    def test_a_written_off_difference_still_shows_what_was_found(self):
        self.count("2026-11-10", 30000, 29000)
        c = queries.cash_counts(self.con)[-1]
        api.run(self.con, "write_off", {"id": c["id"], "pot": "Box"})
        self.assertEqual(cash.differences(self.con, "2026-11")["rows"][0]["found"], -1000)


if __name__ == "__main__":
    unittest.main()
