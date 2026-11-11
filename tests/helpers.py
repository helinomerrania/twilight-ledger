"""A set of books in a temporary file, with just enough Setup to post to.

Every test gets its own database. Nothing is shared and nothing is mocked: the
tests run against real SQLite with the real migrations, because the schema's
constraints are part of what is being tested.
"""
import atexit
import shutil
import tempfile
from pathlib import Path

from ledger import db, post

_dirs = []
_cons = []

# An invented lounge. Every name and amount here is made up: this repository
# is public, so nothing from the real books may appear in it. It has the same
# shape as the real one — three pots, four suppliers, four staff, two partners
# who split the profit in half, one fixed charge — so the tests read like the
# business without being it.
POTS = ["Box", "Bank", "Safe"]
SUPPLIERS = ["Acme Tobacco", "Star Store", "North Supply", "Corner Shop"]
STAFF = {"Alice": 500000, "Bob": 200000, "Carol Hunt": 300000, "Dave": 400000}
PARTNERS = ["Erin Moss", "Frank Hale"]
RENT = 600000
SALARIES = sum(STAFF.values())          # what a whole month of salaries comes to


def fresh_books(*, with_setup=True):
    tmp = Path(tempfile.mkdtemp(prefix="twilight-test-"))
    _dirs.append(tmp)
    con = db.connect(tmp / "twilight.db")
    _cons.append(con)
    if with_setup:
        seed(con)
    return con


def seed(con):
    """The invented lounge above, set up as Setup would leave it."""
    post.ensure_system_accounts(con)
    for i, name in enumerate(POTS):
        post.ensure_account(con, f"cash:{post.slug(name)}", name, "cash", 1, sort=i)
    for i, name in enumerate(SUPPLIERS):
        post.ensure_account(con, f"sup:{post.slug(name)}", name, "supplier", -1, sort=i)
    for i, (name, salary) in enumerate(STAFF.items()):
        aid = post.ensure_account(con, f"staff:{post.slug(name)}", name, "staff",
                                  -1, sort=i)
        con.execute("INSERT INTO salary(account_id, amount, from_month) "
                    "VALUES (?,?,?)", (aid, salary, "2026-07"))
    for i, name in enumerate(PARTNERS):
        post.ensure_account(con, f"prt:{post.slug(name)}", name, "partner", -1,
                            meta={"share": 0.5}, sort=i)
    con.execute("INSERT INTO fixed_charge(name, amount, account_id) VALUES (?,?,?)",
                ("Rent", RENT, post.account_id(con, "exp:rent")))
    for i, name in enumerate(["A", "B", "C", "D", "E", "F"]):
        con.execute("INSERT INTO stock_category(letter, name, sort) VALUES (?,?,?)",
                    (name, f"{name} - category", i))
    db.set_setting(con, "business", {"name": "Test Lounge",
                                     "currency": "IQD", "note": 250})
    return con


def add_count(con, date, closing, *, source="counted"):
    con.execute("INSERT INTO stock_count(count_date, closing, source) VALUES (?,?,?)",
                (date, closing, source))


def add_receipt(con, date, supplier, amount, terms="credit"):
    sup = post.account_by_name(con, "supplier", supplier)
    con.execute("INSERT INTO receipt(received_on, supplier_id, amount, terms) "
                "VALUES (?,?,?,?)", (date, sup, amount, terms))


@atexit.register
def _cleanup():
    for con in _cons:
        try:
            con.close()
        except Exception:
            pass
    for d in _dirs:
        shutil.rmtree(d, ignore_errors=True)
