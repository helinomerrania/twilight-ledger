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

A night is not a calendar day either. The lounge closes after midnight, so
until six in the morning it is still the night before: the screens open on
that night, a count taken at one in the morning after the last night of the
month is that month's count, and a page left open moves on to the next night
by itself. A day picked by hand is let go when the night changes, so tonight's
takings are never typed over last night's.

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

Someone who leaves is asked the day they left. Every month before it carries
their whole salary; the month they left in carries the days of it they worked
(their last day over the days in that month, to the note), and the months after
it carry nothing. Giving the day again, or bringing them back, sets the open
months right, and a closed month that would now be charged differently is named
rather than touched: reopening it is what puts it right.

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

A correction stays with the person it was for. It is found by the account the
entry was posted to, under the name that account has now, never by the name
written on the entry: that name may since have been given to someone else.

A night has one set of takings: a figure typed in, or SambaPOS's lines, one
for each way of paying. Putting a deleted figure back, or moving one to
another night, is refused while that night already has takings, so its sales
are never counted twice.

A change that has been saved is never reported as failed. The day's copy of
the books and the new state for the screen come after the save; if either
fails, the answer says so beside the change, not instead of it, so nothing is
entered a second time. On the screens, each card is drawn on its own, and one
that cannot be drawn says so in its place while the rest of the page works.

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

## Cash you can trust

The counted cash and what SambaPOS says sometimes differ. The books keep the
real sales and the difference apart: if the sales were worked out from the
count, a shortage would disappear into them and no pattern could be seen.
`ledger/cash.py` sets the count beside what SambaPOS says went into and out of
the drawer, points out a night whose sales are not SambaPOS's, leaves a fixed
float in the drawer and moves the rest out in a transfer tied to the count,
and keeps each night's own difference over the month. A difference accepted
as real is still written off, as a cost of its month. Closing up shows each
pot against the books as they stood at the count, so moving the rest out
afterwards never reads as cash found, and a drop to the safe earlier in the
night is part of the night, not the rest. A write-off belongs to its count by
the count's number and its night, since a deleted count's number is given to
the next one.

A stock count values the stock once something is entered on it: a count just
started is not the month's count. No count is started, changed or deleted in
a closed month, since a later one would become the next month's opening stock
without the closed month knowing.

## Stock items as they come

Sealed tobacco does not all come the same way, so an item can say how it
comes (`stock_item.packs`, typed as the box says it: `3×1 kg`), and a count
line converts with the packs the item had when it was counted, so changing
them later never moves a count already taken. A flavour is an item with a
`parent_id`: it borrows its brand's price, packs and supplier until it has
its own, which keeps the old per-brand counts valid beside new per-flavour
ones. Barcodes are a table of their own, one item per code.

A supplier receipt's lines (`receipt_line`) say what came onto the shelves;
only the receipt's total moves money, so a line can never put the books out
of balance. Each line keeps the boxes as typed and what they came to when
saved, belongs to the receipt row, and moves to the new row when the receipt
is corrected.

Filling a bucket (`ledger/buckets.py`) is a stock move with no money in it:
packs leave their tobacco at its price per kilo and the mix takes the grams.
The mix's price is a moving average, weighted by what was already in the
bucket when it was weighed, and each fill keeps the price before and after,
so taking a fill back can put the price back.

What sales take is set here, menu item by menu item (`ledger/pos/uses.py`):
the one stock item each takes from and how much, linked by SambaPOS's number
for the menu item so a rename changes nothing. SambaPOS's own recipes are not
read; the ones in it are test data. Each order keeps SambaPOS's word on
whether it took stock, so a void takes nothing and a gift does.

What should be on the shelf (`ledger/expected.py`) is worked out when asked,
never stored: the count before, plus receipt lines, plus and minus bucket
fills, minus what the menu items sold took. Nothing in it moves money, so a
wrong setting or a missing receipt line shows up as a gap, never as a wrong
balance. Foil, coal and the like are not taken by a menu item; `ledger/ratios.py` learns
hookahs to each one between counts, and should-be uses the ratio learnt
before a count, never the one the count itself would give. What an item costs
to make is what it takes at the stock's prices, so it is only as good as
those settings and prices, and an item that cannot be costed says so instead
of showing a cost of nothing.

## Settling up with a supplier

A supplier's balance is one running account, the same whichever month is on
screen. Settle up asks it the question the lounge pays by: what has been used
up. Their goods still on the shelf stay owed until they are used, so a month's
due is what was owed for the goods that had come by that month's count, less
their stock at the count, rounded down to a whole note so the noise in weighing
never asks to be paid. Goods that came after the count were not on the shelf to
be counted, so they are not due yet, and the line says so. Both sides belong to
the month: goods by the day they came, a payment by
the month it was made for, so October's goods paid on 3 November are paid in
October, and whatever Settle up pays is counted for the month on screen. When
nothing is due the line says so, so a month whose goods are all paid for can
be seen to be.

## The screens in Kurdish

The screens are written in English, and Kurdish (Sorani) is laid over them as
they are drawn (`web/i18n.js`), rather than every card asking for its text by
name. That keeps the cards readable and means nothing in them had to change.
A piece of text is one element's own words, with what changes in it taken out
as `{0}`, `{1}`…: numbers, dates, the elements inside it, anything already in
Kurdish script, and the names in the books. The names are found in the state
by the field they sit in, so "Filled Apple Mix: 1,500 g" and "Filled House
Mix: 300 g" are one piece, and the Kurdish can put `{0}` and `{1}` where its
grammar wants them. Values go back in wrapped in Unicode isolates, so a minus
sign or an English name keeps its own direction inside right-to-left text.

The Kurdish is Mohammed's, made with Gemini, and lives in the books
(`lang_text`); no Kurdish is written in the code, and a test keeps it that
way. Setup → Language copies the next batch of text with no Kurdish yet as a
prompt, and takes Gemini's answer back; a line that lost a `{0}` is refused,
because it would lose a number or a name, and is asked again. The text the app
ships with is listed in `web/lang/catalog.json` (made by opening every screen
on invented books), so all of it can be asked for before any screen has shown
it; text a screen shows that is not on the list is added as it is seen.

A name that is also one of the app's own words — an expense called "Ice"
beside "Ice cream", one called "Electricity" — is taken as the word, because
the shipped list says it is one, so the app's sentences keep their words.
Right to left is the CSS written in logical sides (`margin-inline-start`, not
`margin-left`), with number boxes kept left to right.

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
