# Why this is built the way it is

Twilight Ledger replaces TwilightBooks, a single HTML file that kept the whole
business in one JSON blob in the browser's `localStorage`. It worked, and it ran
the lounge for four months. This document is about why it was rebuilt rather
than patched, because that reasoning is the only thing that will stop the same
problems growing back.

## What actually went wrong

Four bugs were reported over one week:

1. A salary paid in November, settling October, counted against November.
2. A supplier's payable sometimes read 50,000 and sometimes read correctly —
   depending on which month was showing on screen.
3. A cash pot went below zero, which is impossible.
4. Five payments were dated 31 October but handed over in November, so two of
   sixty cash counts could never tie.

They look like four unrelated bugs. They are one bug four times.

In the old design, money was a flat list of rows, each with a type, an `in`
column and an `out` column. Nothing in the data said what a row *meant*. Every
screen had to decide for itself: the supplier card decided that a payable was
"receipts minus payments, but only after the rebase date"; the settle-up card
decided something slightly different; the payroll card read the current staff
list and so silently ignored 461,500 dinar paid to two people who had left.
When two screens disagreed there was no way to say which was right, because
there was no single definition to appeal to.

So the figures were not computed from the books. They were *opinions about* the
books, and there were a dozen of them.

## The one rule

Money moves only as a set of postings that cancel to zero.

Tea from the box for 5,000 dinar is `+5,000` on the daily-expenses account and
`-5,000` on the Box, and the two must sum to zero or the transaction is refused
before anything is written. There is no amount column on a transaction, no
in/out pair, nothing to interpret.

Everything else follows from that:

| figure | how it is worked out |
| --- | --- |
| cash on hand | one SUM over the cash accounts |
| what a supplier is owed | one SUM over that supplier's account |
| October's salary bill | one SUM over the salaries account, for period `2026-10` |
| what is still to pay someone on the staff | one SUM over their account |

One definition each, in `ledger/queries.py`, used by every screen. A second
opinion is no longer expressible.

The database enforces the rule rather than trusting the code to: the
`unbalanced` view lists any entry whose postings do not cancel, every commit
checks it, and the server refuses to start while it returns a row. A ledger that
has lost money should stop the app, not quietly show a wrong total.

## The date and the month are two different things

This is the fix for bug 1, and it is worth stating on its own because it is the
one piece of bookkeeping the app asks Mohammed to understand.

Every entry carries both:

- `happened_on` — the day the cash actually moved.
- `period` — the month the obligation belongs to.

A salary paid on 3 November that settles October is `happened_on 2026-11-03`,
`period 2026-10`. The cash leaves the box on the third, where it really did, and
October's payroll is settled by it. Both are true, and neither has to be faked
by back-dating.

The old app had no way to say this, so the Settle-up screen faked it: it wrote
the payment, stamped it with the end of the settlement month, and immediately
re-dated it to 31 October. The change log shows the add and the edit in the same
minute. That is bug 4 — not something Mohammed did wrong, something the app did
to him.

## Accruals, not payments

Rent is owed for a month whether or not it has been paid this month, and a
salary is earned in the month it is worked. So the charge and the payment are
separate transactions:

- **charge** — October owes a month's rent. Posts to the rent expense and to a
  "rent not yet paid" liability.
- **payment** — the rent leaves the Box on 8 November, settling October. Posts
  against the liability and the Box. It never touches profit again.

This is why re-dating those five payments to their real dates does not change
October's profit by a dinar, and the acceptance gate proves it.

The old app got the right answer here by a different route: it summed the
*current* Setup lists every time a screen rendered. That is also why editing a
salary moved a month that had already been closed. Here a closed month's result
is a stored record, and `test_a_closed_month_is_not_recomputed_from_setup`
doubles every salary in the database and asserts that August does not move.

## What is not double entry

Stock is not a cash movement. It is a count on a date, valued at the prices in
force then, and the cost of goods falls out of it: opening plus bought less
closing. The count's value is **stored on the count**, not recomputed, so
changing an item's price in Setup cannot move a figure a finished month was
built on.

Closing a month posts the cost of goods out of the stock account, and whatever
is then left over against the physical count is posted as a *stock difference*
rather than swept into cost. If stock is walking out of the door, that should be
a line on the result, not a rounding artifact.

## Whole dinar

Every amount in the database is an INTEGER number of dinar, and
`ledger/money.py` contains no floating-point arithmetic in the money path.
Partner splits use exact fractions, so a 50/50 split of an odd number is
decided by a rule and not by a decimal representation.

The old app used JavaScript numbers. Its stored August result still carries
half a dinar in its gross profit, inherited from the Excel workbook the books
were started from. That record is kept exactly as it was frozen; everything
computed from here on is whole.

## Nothing is deleted

An entry is voided, not removed: the entry and its postings stay, `voided_at` is
set, and every balance reads the `movement` view, which skips them. A ledger
that can delete a row is a ledger that can stop explaining itself.

A deletion can be put back from Recent changes while its month is open.

A correction is a deletion and a new entry in one transaction, joined by
`replaced_by`, so the record shows what an entry said before, what it says now,
and when it changed. A corrected entry cannot be put back — its correction is
already standing in its place. Nothing in a closed month can be corrected or
deleted until the month is reopened, and the charges the app works out itself
(rent, salaries, electricity) are never edited by hand: change the salary, the
rent or the meter reading and the charge follows.

## Running balances start on 30 September 2026

The old books began in August from an Excel workbook, and what each person was
owed before then was never recorded. Every running balance — each supplier,
each member of staff, each partner, the rent — therefore starts at 30 September
2026. Anything from before that date sits against *Opening balances* and is
part of the record: it can be read, never edited, because re-posting it against
the person would invent a debt nobody owed.

## Asking, not refusing

Cash cannot be negative, and a pot that goes below zero almost always means an
entry is missing or in the wrong pot. But at night the commonest cause is
simply order: a salary handed over before tonight's sales are typed in. So a
payment that would take a pot further below zero than it already was is not
refused and not silently allowed. The server answers 409 with the pot, how
short it would be and on which day; the screen asks, and says to enter the
sales first if they are missing; the payment is sent again only on a yes.

A cash count works the same way. Counting is a reading, never a correction:
the difference is recorded beside the count and nothing is invented to make it
go away. Writing it off is a separate, deliberate step that sets the pot to
what was counted and makes the difference a cost (or a gain) of that month.
Without it, one missing 50,000 would make every later count wrong by 50,000.

## The month so far

Rent and salaries are charged for the whole month on the first day, so on the
8th the full result sets thirty days of costs against eight days of sales and
shows a loss that is not real. The Month screen shows both: the full month, and
*so far*, which charges only the days that have passed and estimates the cost
of goods since the last count at last month's ratio. It says it is an estimate.
The partners' share of profit and the drawings warning use the so-far figure
while the month is running, and the real one once it is over.

## Copies somewhere else

A copy on the same disk protects against a bad edit or a bad update and does
nothing if the PC dies. So the daily copy, the one before an update and any
taken by hand are also put in a second folder Mohammed chooses (a USB stick,
or a folder Google Drive or OneDrive keeps in step), and every copy is opened
and checked before it is trusted. A check stays red until
a copy elsewhere is less than four days old.

## SambaPOS, before the reset

The till is SambaPOS, and every night a reset deletes that night's tickets from
its database. The old books show the takings were typed in the next afternoon,
from a printed report — by which time SambaPOS no longer had the night at all.
So the night has to be copied out before the reset, and kept here.

There are two ways in, and both produce the same snapshot:

- **SambaPOS's database, read directly.** Windows PowerShell asks SQL Server a
  handful of `SELECT`s, signed in as the Windows user running the app, so no
  password is stored anywhere. The script refuses anything that is not a
  single `SELECT`, and asks SQL Server which columns exist before asking for
  them, so a SambaPOS update that adds or drops a column does not break it.
- **A SambaPOS backup file**, read without SQL Server. A `.bak` is mostly the
  database's own 8 KB pages; `ledger/pos/bak.py` finds them, decodes SQL
  Server's catalog from them, and reads the tables like SQL Server would.
  Deleted rows survive in a page as ghosts until the space is reused, and are
  skipped. This is what makes old backups readable on any PC.

A work period is identified by SambaPOS's id *and* the moment it started —
ids carry on counting across resets, but a reinstall would start them again.
A period already kept is only replaced by a fuller copy of itself: closed when
the kept one was open, more tickets, or later in the night. So bringing in an
older backup after a newer one cannot lose anything, and bringing anything in
twice changes nothing.

The archive is not the books. Its figures become money only when a night's
takings are used as that night's sales, which posts an ordinary entry. A
ticket opened before six in the morning belongs to the night before.

SambaPOS writes a backup into its backup folder just before every reset, so
the second way in needs nobody: `ledger/pos/auto.py` looks in that folder when
the app starts, every five minutes while it is open, and when a screen asks
for the books, on a thread of its own. `pos_file` remembers each file by name,
size and time, so each is read once; a file written in the last minute is left
for next time, because SambaPOS may still be writing it, and one that will not
read is remembered with the reason and not tried again unless it changes.
Nothing it finds wrong is raised — it becomes a check on Tonight, along with a
newest backup more than 30 hours old, which means the reset was not run or
SambaPOS now backs up somewhere else.

SambaPOS records an expense, a staff advance and an owner taking cash the same
way — money moved from the drawer to one of its own accounts — so what a
document means depends on the account. Each SambaPOS account is linked once
to what it is in the books (`ledger/pos/links.py`): an expense, a person, a
supplier, other income, a pot, or nothing. The link is by SambaPOS's number for
the account, never its name, so a rename there changes nothing here. The app
only suggests a link when the match is plain; it never guesses.

SambaPOS's own lists — payment types, the menu with its portions and prices,
inventory items, recipes — are not touched by the reset, so they are simply
kept as the newest snapshot has them (`ledger/pos/catalog.py`), ready for the
steps that will use them. Its users table is never read: it holds passwords.

With the accounts linked, a kept night becomes entries by itself
(`ledger/pos/adding.py`): the takings, and every document as the expense,
advance, owner withdrawal, money back or transfer it is, by its link and by
which way the money moved. **Add the night** posts them in one transaction,
each with `source = 'pos'` and a reference to the SambaPOS line it came from,
so a night added twice adds nothing twice and an entry deleted by hand stays
deleted. While nights are still typed by hand as well, a line is only added
when the books hold nothing of the same kind for the same person or expense
that night; when they do and it differs, it is shown and left alone, because
adding it would count the money twice.

Nothing here writes to SambaPOS, and nothing here runs or changes the reset.

## Updating from GitHub

The app updates itself from this repository. The download is checked before it
is allowed near the app: it must be this app, newer, compile, carry no `data/`
folder, and contain every migration these books have been through, unchanged.
Then the books are copied aside, the old code is zipped beside them, and the
new code is swapped in folder by folder, every one put back if any step fails.
Only `ledger/`, `web/`, `tools/`, `tests/`, `docs/` and a handful of named
files can ever be written; `data/` is not on the list.

## Why Python and SQLite

The requirement was that an update from GitHub must never touch the books. With
a database that is structural rather than a promise: code is replaced, the
`.db` file is not, and schema changes run as forward-only migrations with a copy
taken first.

SQLite because it is one file — a backup is a file copy, there is no service to
administer, and it survives a SambaPOS reinstall, which the SQL Server instance
next door might not. It is also fully transactional, which matters in Ranya:
WAL journalling means a power cut mid-write leaves a consistent file.

Python because its SQLite driver is in the standard library and has been stable
for twenty years. The alternatives were measured, not assumed: Node 22's
`node:sqlite` still prints *"SQLite is an experimental feature and might change
at any time"*, and `better-sqlite3` is a compiled module that breaks on Node
upgrades. Neither is something Mohammed should ever have to debug. One runtime
to install, zero packages, no build step.

The screens stay in a browser because the browser already prints his 72mm
thermal till rolls, there is nothing to install, and he knows it.

## The gate

`tools/oracle.py` is the old app's arithmetic reimplemented from its source,
deliberately kept independent of `ledger/`. `tools/verify.py` runs both against
the real export and compares every headline figure.

66 checks. The rebuild is only trustworthy because they all pass:

- October and November: net, revenue, cost of goods and every line between
- August and September: frozen exactly as closed, halves of a dinar included
- cash on hand, in the pots he left it in
- owed to suppliers, and each supplier's balance
- and the one figure that is *meant* to differ: cash at 31 October, because the
  five payments now fall in November, where they happened

After which every cash count ties, where two did not before.

None of those figures is written in this repository: the gate and
`tests/test_real_books.py` work them out from the export when they run, and
the export stays on the PC.
