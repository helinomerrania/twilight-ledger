# Twilight Ledger

The books for Twilight Rest & Cafe, a hookah lounge in Ranya.

It replaces TwilightBooks, a single HTML file that held the whole business in
one JSON blob in the browser. This one is a real double-entry ledger in SQLite,
with the screens served from the same PC. `docs/design.md` explains why, and is
worth reading before changing anything. `docs/plan.md` is what comes next, step
by step.

**This repository is public. It contains no business data of any kind** — the
books live in `data/`, which is never committed, and the tests run on an
invented lounge. The one import tool reads a file you point it at.

## Running it

You need Python 3.11 or newer. Nothing else — no packages to install, no build
step, no internet.

On Windows, double-click **Start Twilight Ledger.bat**. Anywhere else:

```
python twilight.py
```

That opens the books in your browser at `http://127.0.0.1:8788`. The server
listens on loopback only, so nothing on the network can reach it.

Other things it can do:

```
python twilight.py check              is everything sound?
python twilight.py backup             set a copy aside now (and to the second folder)
python twilight.py restore FILE --yes put a copy back as the live books
python twilight.py update             install a newer version from GitHub
python twilight.py pos save           keep tonight from SambaPOS, before the reset
python twilight.py pos import FILE    keep what is in a SambaPOS backup (.zip or .bak)
python twilight.py pos nights         the nights kept so far
python twilight.py import FILE        bring in a twilight-books.json export
python twilight.py verify FILE        compare against the old app's figures
python twilight.py close 2026-11      close a month
python twilight.py sql "SELECT ..."   ask the books a question (read-only)
```

## Updating

Setup → *This app* → **Check for updates**. An update replaces the code and
never the books: they are copied aside first, the old code is kept as a zip
next to them, and the download is refused if it carries a `data/` folder or
changes a migration the books have already been through. The app restarts by
itself and the page reloads.

## Where the books live

One file: `data/twilight.db`. Everything else in this repository can be deleted
and pulled again without touching it — that is the whole point of the split.

Copies are made into `data/backups/` the first time the app runs each day, and
again before an update, a restore or a change to the database's shape. Nothing
is ever pruned automatically. Choose a **second folder** in Setup — a USB stick,
or a folder Google Drive or OneDrive keeps in step — and every copy goes there
too, because a copy on the same disk does nothing if the PC dies.

If the ledger ever stops balancing, the app refuses to start rather than serve
figures from books that have lost money. `python twilight.py check` says what
is wrong.

## SambaPOS

SambaPOS's nightly reset deletes the night's tickets, but SambaPOS writes a
backup of its database just before it. Choose that backup folder in Setup →
SambaPOS, and every night comes in by itself: the app looks in the folder when
it starts, every few minutes while it is open, and when Tonight is opened, and
reads each new backup once. Tonight says so if the newest backup there is more
than a day old. The app reads the backup file itself, without SQL Server, so
old backups can be brought in on any PC too.

SambaPOS's accounts are linked once to what they are in the books — this
account is an expense for fruit, that one is a member of staff — in Setup →
SambaPOS accounts, or on Tonight the first time a night uses one. Then Tonight
shows each night as the entries it becomes, and **Add the night** puts them all
in the books at once. Anything already typed by hand is recognised and not
added twice.

The count on Tonight sets the cash beside what SambaPOS says went in and out
of the drawer, and says when the night's sales are not SambaPOS's, because a
sales figure worked out from the count hides a shortage. Setup → Counting the
cash sets a float to leave in the drawer (the rest is moved out in one click
after the count) and can make counts blind. Month shows each night's
difference over the month, and by who opened SambaPOS.

On the PC SambaPOS runs on, its database can also be read directly — double-
click **Save tonight from SambaPOS.bat**, or *Read SambaPOS now* in Setup — to
see tonight before the reset. That uses Windows' own login, so no password is
stored anywhere, and it only ever reads.

Once a night is kept, Tonight shows what SambaPOS took and fills in the sales
with one click, and lists what sold; Month sets each night beside what the books
say. The archive is separate from the books: nothing in it is money until it is
used as a night's sales.

## The five screens

Each screen is a few pages, picked from a row under its title, so nothing has
to be scrolled through to find it.

| | what it is for | its pages |
| --- | --- | --- |
| **Tonight** | the nightly job | Closing up · Today · Sold tonight |
| **Stock** | what arrived, what is left, what it is worth | Count · Fill a bucket · Receipts · Should be there · Past counts |
| **Month** | the result, settling up, closing the month | Profit · Settle up · Cash · Sales · Checks and closing |
| **Books** | the record: correcting, searching, the cash counts | Entries · Cash counts · Recent changes |
| **Setup** | the lists and accounts everything else is built from | People · Cash · Rent and bills · Stock · Lists · SambaPOS · This app |

## The idea in one paragraph

Money only ever moves as a set of postings that cancel to zero. Tea from the box
for 5,000 is `+5,000` on daily expenses and `-5,000` on the Box, and the
transaction is refused before anything is written if the two do not cancel. Cash
on hand is then one sum over the cash accounts; what a supplier is owed is one
sum over that supplier's account. Nothing computes its own private version of
the truth, which is what the old app did in a dozen places and why its screens
could disagree with each other.

Every entry also carries two separate facts: **the day the cash moved** and
**the month it belongs to**. A salary paid on 3 November settling October is
both at once. Nothing has to be back-dated to make a month come out right.

## Tests

```
python -m unittest discover -s tests -t .
```

528 tests, no dependencies. They run against real SQLite with the real
migrations, because the schema's constraints are part of what is being tested.
Their invented nights are dated November 2026, so the tests set the app's clock
to the evening of 14 November 2026, whatever the real date (`tests/__init__.py`).

The tests in `tests/test_real_books.py` check the import against the actual
books and are skipped unless you point `TWILIGHT_EXPORT` at an export:

```
TWILIGHT_EXPORT=~/twilight-books.json python -m unittest discover -s tests -t .
```

Likewise `tests/test_pos.py` reads one real SambaPOS backup only if
`TWILIGHT_POS_BACKUP` points at it, and checks every ticket adds up to its
orders and every payment is accounted for.

Before anything is pushed, `tools/privacy_scan.py` searches the repository for
every name and amount in a local export, and in SambaPOS backups if given a
folder of them. `--history` searches every old version and commit message too:

```
python tools/privacy_scan.py ~/twilight-books.json --pos <SambaPOS backup folder>
```

## Importing from the old app

```
python twilight.py import ~/Downloads/twilight-books.json
```

It refuses to import into books that already exist, because that would double
every entry. `tools/verify.py` then compares the result against
`tools/oracle.py` — an independent reimplementation of the old app's arithmetic,
read off its source — figure by figure.

## Layout

```
twilight.py            the one command
ledger/
  db.py                opening and migrating the books
  post.py              the only place money is written
  queries.py           every figure the screens show, each defined once
  accruals.py          rent, salaries and electricity charged to their month
  stock.py             counted amounts and what they are worth
  close.py             closing a month and reopening it
  registry.py          how an action runs: cleaning, the pot guard, the trail
  actions.py           entering, correcting, counting, writing off
  setup.py             changing Setup
  checks.py            the yes-or-no questions on Month
  backup.py            copies, the second folder, restoring
  update.py            updating from GitHub without touching the books
  pos/                 SambaPOS: reading its backups and its database, and
                       keeping each night before the reset
  api.py               the one state the screens read
  server.py            a small loopback web server
  migrations/          forward-only SQL, never edited once applied
web/                   the five screens
tools/
  import_json.py       the old books in
  oracle.py            the old app's arithmetic, for checking against
  verify.py            the acceptance gate
tests/
docs/design.md         why it is built this way
```
