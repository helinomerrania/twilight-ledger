"""The SambaPOS archive: reading a backup's bytes, reading the live database,
and keeping each night so that nothing is lost or counted twice.

Everything here is invented. The one test that reads a real SambaPOS backup
is skipped unless TWILIGHT_POS_BACKUP points at one, because a real backup
holds the lounge's own tickets and never belongs in this repository.
"""
import os
import struct
import tempfile
import unittest
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from ledger import api, db
from ledger.pos import archive, bak, sources
from ledger.pos import actions as pos
from tests.helpers import fresh_books


def T(s):
    return datetime.fromisoformat(s)


def snapshot(*, periods, tickets, orders=(), payments=(), calcs=(), menu=(), places=(),
             source="backup:test.zip", **more):
    return {"source": source, "tables": sources.normalise({
        "WorkPeriods": list(periods), "Tickets": list(tickets), "Orders": list(orders),
        "Payments": list(payments), "Calculations": list(calcs), "MenuItems": list(menu),
        "TicketEntities": list(places), **more})}


def night_of_ten(*, more=False, ended=False, source="backup:test.zip"):
    """A night in November: two hookahs and a tea at table 4, a free tea,
    paid in cash after midnight, and (if `more`) a second ticket still open."""
    periods = [{"Id": 1013, "StartDate": "2026-11-10T03:05:00",
                "EndDate": "2026-11-11T02:40:00" if ended else "2026-11-10T03:05:00"}]
    tickets = [{"Id": 2100, "TicketNumber": "1", "Date": "2026-11-10T20:15:00",
                "LastPaymentDate": "2026-11-11T00:30:00", "IsClosed": True,
                "RemainingAmount": "0.00", "TotalAmount": "13000.00"}]
    orders = [
        {"Id": 1, "TicketId": 2100, "MenuItemId": 7, "MenuItemName": "Apple", "PortionName": "Normal",
         "Price": "5000.00", "Quantity": "2.000", "CalculatePrice": True,
         "CreatedDateTime": "2026-11-10T20:15:00"},
        {"Id": 2, "TicketId": 2100, "MenuItemId": 9, "MenuItemName": "Tea", "PortionName": "Normal",
         "Price": "4000.00", "Quantity": "1.000", "CalculatePrice": True,
         "CreatedDateTime": "2026-11-10T20:20:00"},
        {"Id": 3, "TicketId": 2100, "MenuItemId": 9, "MenuItemName": "Tea", "PortionName": "Normal",
         "Price": "4000.00", "Quantity": "1.000", "CalculatePrice": False,
         "CreatedDateTime": "2026-11-10T20:21:00"},
    ]
    payments = [{"Id": 1, "TicketId": 2100, "Name": "Cash", "Date": "2026-11-11T00:30:00",
                 "Amount": "12000.00"}]
    calcs = [{"Id": 1, "TicketId": 2100, "Name": "Discount", "CalculationAmount": "-1000.00"}]
    places = [{"Id": 1, "Ticket_Id": 2100, "EntityName": "4"}]
    if more:
        tickets.append({"Id": 2101, "TicketNumber": "2", "Date": "2026-11-11T01:10:00",
                        "LastPaymentDate": "2026-11-11T01:10:00", "IsClosed": False,
                        "RemainingAmount": "5000.00", "TotalAmount": "5000.00"})
        orders.append({"Id": 4, "TicketId": 2101, "MenuItemId": 7, "MenuItemName": "Apple",
                       "Price": "5000.00", "Quantity": "1.000", "CalculatePrice": True})
    menu = [{"Id": 7, "Name": "Apple", "GroupCode": "Hookah"},
            {"Id": 9, "Name": "Tea", "GroupCode": "Drinks"}]
    return snapshot(periods=periods, tickets=tickets, orders=orders, payments=payments,
                    calcs=calcs, menu=menu, places=places, source=source)


class Keeping(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()
        self.entries = db.scalar(self.con, "SELECT count(*) FROM entry")

    def keep(self, snap):
        with db.tx(self.con):
            return archive.keep(self.con, snap)

    def test_a_ticket_after_midnight_belongs_to_the_night_before(self):
        line = self.keep(night_of_ten(more=True))[0]
        self.assertEqual(line["night"], "2026-11-10")

    def test_the_night_adds_up(self):
        self.keep(night_of_ten(more=True))
        n = archive.night(self.con, "2026-11-10")
        self.assertEqual((n["tickets"], n["total"], n["takings"], n["unpaid"]),
                         (2, 18000, 12000, 5000))
        self.assertEqual((n["open_tickets"], n["discounts"]), (1, 1000))
        self.assertEqual(n["by_kind"], [["Cash", 12000]])

    def test_what_sold_counts_what_was_charged_and_what_was_given(self):
        self.keep(night_of_ten(more=True))
        sold = {i["item"]: i for i in archive.night(self.con, "2026-11-10")["items"]}
        self.assertEqual((sold["Apple"]["qty"], sold["Apple"]["value"]), (3, 15000))
        self.assertEqual((sold["Tea"]["qty"], sold["Tea"]["free"], sold["Tea"]["value"]),
                         (1, 1, 4000))
        self.assertEqual(sold["Apple"]["group"], "Hookah")

    def test_the_hours_run_in_the_order_the_night_does(self):
        self.keep(night_of_ten(more=True))
        self.assertEqual([h[0] for h in archive.hours(self.con, "2026-11-10")], [20, 1])

    def test_keeping_the_same_copy_twice_changes_nothing(self):
        self.keep(night_of_ten())
        self.assertEqual(self.keep(night_of_ten())[0]["status"], "same")
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM pos_ticket"), 1)

    def test_a_fuller_copy_replaces_the_earlier_one(self):
        self.keep(night_of_ten())
        self.assertEqual(self.keep(night_of_ten(more=True, ended=True))[0]["status"], "updated")
        self.assertEqual(archive.night(self.con, "2026-11-10")["tickets"], 2)

    def test_an_older_copy_brought_in_later_cannot_lose_tickets(self):
        self.keep(night_of_ten(more=True, ended=True))
        self.assertEqual(self.keep(night_of_ten())[0]["status"], "older")
        self.assertEqual(archive.night(self.con, "2026-11-10")["tickets"], 2)

    def test_tickets_go_to_the_period_that_was_open_when_they_were_made(self):
        snap = night_of_ten()
        snap["tables"]["WorkPeriods"].append(
            {"Id": 1014, "StartDate": T("2026-11-11T03:00:00"), "EndDate": T("2026-11-11T03:00:00")})
        snap["tables"]["Tickets"].append(
            {"Id": 2200, "Date": T("2026-11-11T19:00:00"), "IsClosed": True,
             "RemainingAmount": Decimal(0), "TotalAmount": Decimal(7000)})
        lines = {l["pos_id"]: l for l in self.keep(snap)}
        self.assertEqual((lines[1013]["tickets"], lines[1014]["tickets"]), (1, 1))
        self.assertEqual(lines[1014]["night"], "2026-11-11")

    def test_keeping_never_touches_the_books(self):
        self.keep(night_of_ten(more=True))
        self.assertEqual(db.scalar(self.con, "SELECT count(*) FROM entry"), self.entries)

    def test_a_month_lists_its_nights(self):
        self.keep(night_of_ten(more=True))
        m = archive.month(self.con, "2026-11")
        self.assertEqual([n["night"] for n in m["nights"]], ["2026-11-10"])
        self.assertIsNone(archive.month(self.con, "2026-10"))

    def test_the_trail_says_what_was_kept(self):
        pos.keep(self.con, night_of_ten(), "from test.zip")
        self.assertIn("Kept SambaPOS from test.zip", api.queries.recent(self.con)[0]["summary"])


def night_with_documents(*, extra=False, paid=True):
    """The same night, with what else SambaPOS recorded: ice bought from the
    drawer, an advance to a member of staff, and an expense that was entered by mistake
    and reversed. The ticket's own document must not count again."""
    base = night_of_ten()["tables"]
    raw = {k: [] for k in sources.TABLES}
    for k, rows in base.items():
        raw[k] = [dict(r) for r in rows]
    raw["Tickets"][0]["TransactionDocument_Id"] = 300
    if paid:
        raw["Payments"][0]["AccountTransactionId"] = 401
    else:
        raw["Payments"] = []
    raw["AccountTypes"] = [{"Id": 1, "Name": "Receivable Accounts"},
                           {"Id": 3, "Name": "Payment Accounts"},
                           {"Id": 7, "Name": "خەرجییەکان"}, {"Id": 8, "Name": "Staff"}]
    raw["Accounts"] = [{"Id": 2, "Name": "Receivables", "AccountTypeId": 1},
                       {"Id": 5, "Name": "Cash", "AccountTypeId": 3},
                       {"Id": 20, "Name": "سەهۆڵ", "AccountTypeId": 7},
                       {"Id": 21, "Name": "ئالیس", "AccountTypeId": 8}]
    raw["AccountTransactionDocumentTypes"] = [{"Id": 4, "Name": "Expense", "ButtonHeader": "خەرجی"},
                                              {"Id": 5, "Name": "Advance", "ButtonHeader": "سولفە"}]
    docs = [(300, 0, "2026-11-11T00:30:00"), (301, 4, "2026-11-10T21:00:00"),
            (302, 5, "2026-11-10T22:00:00"), (303, 4, "2026-11-10T22:30:00")]
    if extra:
        docs.append((304, 4, "2026-11-11T01:00:00"))
    raw["AccountTransactionDocuments"] = [{"Id": i, "DocumentTypeId": t, "Date": d,
                                           "Name": f"doc {i}", "UserName": "Administrator"}
                                          for i, t, d in docs]
    raw["AccountTransactions"] = [{"Id": 401, "AccountTransactionDocumentId": 300},
                                  {"Id": 402, "AccountTransactionDocumentId": 301},
                                  {"Id": 403, "AccountTransactionDocumentId": 302},
                                  {"Id": 404, "AccountTransactionDocumentId": 303, "IsReversed": True},
                                  {"Id": 405, "AccountTransactionDocumentId": 304}]

    def move(vid, tx, doc, frm, to, amount, at):
        return [{"Id": vid, "AccountTransactionId": tx, "AccountTransactionDocumentId": doc,
                 "AccountId": frm, "AccountTypeId": {2: 1, 5: 3, 20: 7, 21: 8}[frm],
                 "Date": at, "Debit": "0", "Credit": str(amount)},
                {"Id": vid + 1, "AccountTransactionId": tx, "AccountTransactionDocumentId": doc,
                 "AccountId": to, "AccountTypeId": {2: 1, 5: 3, 20: 7, 21: 8}[to],
                 "Date": at, "Debit": str(amount), "Credit": "0"}]
    raw["AccountTransactionValues"] = (
        move(10, 401, 300, 2, 5, 12000, "2026-11-11T00:30:00")       # the ticket paid into Cash
        + move(20, 402, 301, 5, 20, 10500, "2026-11-10T21:00:00")    # ice from the drawer
        + move(30, 403, 302, 5, 21, 10000, "2026-11-10T22:00:00")    # advance to Alice
        + move(40, 404, 303, 5, 20, 5000, "2026-11-10T22:30:00")     # reversed
        + (move(50, 405, 304, 5, 20, 2000, "2026-11-11T01:00:00") if extra else []))
    return {"source": "backup:test.zip", "tables": sources.normalise(raw)}


class Documents(unittest.TestCase):
    """Expenses and advances recorded in SambaPOS are kept with the night."""

    def setUp(self):
        self.con = fresh_books()

    def keep(self, snap):
        with db.tx(self.con):
            return archive.keep(self.con, snap)

    def docs(self):
        return archive.documents(self.con, "2026-11-10")

    def test_what_went_in_and_out_of_the_drawer_is_kept(self):
        self.keep(night_with_documents())
        d = {x["pos_id"]: x for x in self.docs()}
        self.assertEqual(sorted(d), [301, 302, 303])               # not the ticket's own
        self.assertEqual((d[301]["kind"], d[301]["drawer"]), ("خەرجی", -10500))
        self.assertEqual(d[301]["accounts"],
                         [{"pos_id": 20, "name": "سەهۆڵ", "type": "خەرجییەکان", "amount": 10500}])
        self.assertEqual(d[302]["accounts"][0]["name"], "ئالیس")

    def test_a_reversed_entry_is_kept_but_moves_nothing(self):
        self.keep(night_with_documents())
        d = {x["pos_id"]: x for x in self.docs()}
        self.assertTrue(d[303]["reversed"])
        self.assertEqual((d[303]["drawer"], d[303]["accounts"]), (0, []))
        n = archive.night(self.con, "2026-11-10")
        self.assertEqual((n["drawer_out"], n["drawer_in"]), (20500, 0))

    def test_the_drawer_is_known_even_on_a_night_with_no_payments(self):
        self.keep(night_with_documents(paid=False))
        self.assertEqual(archive.night(self.con, "2026-11-10")["drawer_out"], 20500)

    def test_a_later_copy_with_one_more_entry_replaces_the_earlier(self):
        self.keep(night_with_documents())
        self.assertEqual(self.keep(night_with_documents(extra=True))[0]["status"], "updated")
        self.assertEqual(len(self.docs()), 4)
        self.assertEqual(self.keep(night_with_documents())[0]["status"], "older")
        self.assertEqual(len(self.docs()), 4)


class Live(unittest.TestCase):
    """Reading SambaPOS's own database, with SQL Server stood in for."""

    def fake(self, columns, rows):
        self.asked = []

        def runner(request):
            self.asked.append(request)
            if request["queries"][0]["name"] == "columns":
                return {"columns": [{"t": t, "c": c} for t, cs in columns.items() for c in cs]}
            return {q["name"]: rows.get(q["name"], []) for q in request["queries"]}
        return runner

    def test_only_columns_that_exist_are_asked_for(self):
        runner = self.fake({"Tickets": ["Id", "Date", "TotalAmount"], "WorkPeriods": ["Id", "StartDate"]}, {})
        sources.read_live("localhost", "twilight", runner)
        sqls = {q["name"]: q["sql"] for q in self.asked[1]["queries"]}
        self.assertEqual(sqls["Tickets"], "SELECT [Id], [Date], [TotalAmount] FROM [dbo].[Tickets]")
        self.assertNotIn("Orders", sqls)
        self.assertTrue(all(s.startswith("SELECT ") and ";" not in s for s in sqls.values()))

    def test_what_comes_back_as_text_is_turned_into_dates_and_amounts(self):
        runner = self.fake({"Tickets": ["Id", "Date", "TotalAmount"], "WorkPeriods": ["Id"]},
                           {"Tickets": [{"Id": 5, "Date": "2026-11-10T21:04:05.250",
                                         "TotalAmount": "8500.00"}]})
        snap = sources.read_live("localhost", "twilight", runner)
        t = snap["tables"]["Tickets"][0]
        self.assertEqual((t["Date"], t["TotalAmount"]), (T("2026-11-10T21:04:05.250"), Decimal("8500.00")))
        self.assertEqual(snap["source"], "live:twilight")

    def test_a_lone_row_handed_back_on_its_own_is_still_read(self):
        runner = self.fake({"Tickets": ["Id"], "WorkPeriods": ["Id"]},
                           {"Tickets": {"Id": 9}})
        self.assertEqual(sources.read_live("localhost", "twilight", runner)["tables"]["Tickets"],
                         [{"Id": 9}])

    def test_a_database_without_tickets_is_not_sambapos(self):
        with self.assertRaises(sources.PosError):
            sources.read_live("localhost", "master", self.fake({"Other": ["Id"]}, {}))

    def test_a_name_that_could_carry_anything_else_is_refused(self):
        with self.assertRaises(sources.PosError):
            sources.read_live("localhost", "twilight]; DROP TABLE Tickets--", self.fake({}, {}))

    def test_what_went_wrong_is_said_in_plain_words(self):
        req = {"server": "localhost", "database": "twilight"}
        self.assertIn("would not let", sources.explain("Login failed for user 'X'.", req))
        self.assertIn("No SQL Server answered", sources.explain(
            "A network-related or instance-specific error occurred", req))
        clixml = ('#< CLIXML\n<Objs><S S="Error">Cannot open database "twilight" requested'
                  '_x000D__x000A_</S></Objs>')
        self.assertIn("no database called twilight", sources.explain(clixml, req))


class Backups(unittest.TestCase):
    def test_backups_are_taken_oldest_first_by_the_time_in_their_name(self):
        d = Path(tempfile.mkdtemp(prefix="twilight-pos-"))
        for name in ("SambaPOS5_202611101830SQM.zip", "SambaPOS5_202611090230SQM.zip",
                     "notes.txt", "SambaPOS5_202611100230SQT.zip"):
            (d / name).write_bytes(b"")
        self.assertEqual([p.name for p in sources.backups_in(d)],
                         ["SambaPOS5_202611090230SQM.zip", "SambaPOS5_202611100230SQT.zip",
                          "SambaPOS5_202611101830SQM.zip"])

    def test_a_file_that_is_not_a_backup_is_refused_in_words(self):
        d = Path(tempfile.mkdtemp(prefix="twilight-pos-"))
        (d / "junk.bak").write_bytes(b"\0" * 20000)
        with self.assertRaises(sources.PosError):
            sources.read_backup(d / "junk.bak")

    def test_the_folder_must_exist(self):
        con = fresh_books()
        with self.assertRaises(api.ApiError):
            api.run(con, "pos_settings", {"folder": "/no/such/folder/for/twilight"})


class Pages(unittest.TestCase):
    """The pieces of SQL Server's on-disk format the reader depends on."""

    def test_a_decimal(self):
        raw = bytes([1]) + (1234550).to_bytes(8, "little")
        self.assertEqual(bak.decimal_of(raw, 2), Decimal("12345.50"))
        self.assertEqual(bak.decimal_of(bytes([0]) + raw[1:], 2), Decimal("-12345.50"))

    def test_a_datetime(self):
        # 45,970 days after 1900-01-01, and 21:30 in three-hundredths of a second
        raw = struct.pack("<Ii", (21 * 3600 + 30 * 60) * 300, 45970)
        self.assertEqual(bak.dt_datetime(raw), datetime(2025, 11, 11, 21, 30))

    def test_a_row_with_a_null_and_two_strings(self):
        # status A: has a null bitmap (0x10) and variable columns (0x20)
        fixed = struct.pack("<i", 42)
        name, note = "Apple".encode("utf-16-le"), "".encode("utf-16-le")
        head = bytes([0x30, 0]) + struct.pack("<H", 4 + len(fixed))
        cols = struct.pack("<H", 3) + bytes([0b010])       # three columns, the 2nd is null
        start = len(head) + len(fixed) + len(cols) + 2 + 2 * 2
        ends = struct.pack("<HH", start + len(name), start + len(name) + len(note))
        row = head + fixed + cols + struct.pack("<H", 2) + ends + name + note
        parts = bak.record_parts(row, 0)
        self.assertEqual(struct.unpack("<i", parts["fixed"])[0], 42)
        self.assertTrue(bak.is_null(parts, 2))
        self.assertFalse(bak.is_null(parts, 1))
        self.assertEqual(parts["var"][0][0].decode("utf-16-le"), "Apple")

    def test_something_that_is_not_a_backup(self):
        with self.assertRaises(bak.BakError):
            bak.Backup(b"\0" * 50000)


@unittest.skipUnless(os.environ.get("TWILIGHT_POS_BACKUP"),
                     "set TWILIGHT_POS_BACKUP to a real SambaPOS backup to run this")
class RealBackup(unittest.TestCase):
    def test_every_ticket_adds_up(self):
        snap = sources.read_backup(os.environ["TWILIGHT_POS_BACKUP"])
        t = snap["tables"]
        self.assertTrue(t["WorkPeriods"])
        orders, calcs = {}, {}
        for o in t["Orders"]:
            if o.get("CalculatePrice"):
                orders[o["TicketId"]] = orders.get(o["TicketId"], 0) + o["Price"] * o["Quantity"]
        for c in t["Calculations"]:
            calcs[c["TicketId"]] = calcs.get(c["TicketId"], 0) + c["CalculationAmount"]
        for tk in t["Tickets"]:
            self.assertEqual(tk["TotalAmount"],
                             orders.get(tk["Id"], 0) + calcs.get(tk["Id"], 0), tk["Id"])
        paid = sum(p["Amount"] for p in t["Payments"])
        self.assertEqual(sum(tk["TotalAmount"] for tk in t["Tickets"]),
                         paid + sum(tk["RemainingAmount"] for tk in t["Tickets"]))


if __name__ == "__main__":
    unittest.main()
