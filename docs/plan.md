# The plan

Everything agreed for Twilight Ledger that is not built yet, in the order it
should be built. Each step stands on its own, so it can be picked up months
later by someone — or a Claude session — that remembers nothing of how it was
decided. Read `docs/design.md` first; this file assumes it.

When a step is finished, mark it done here in the same commit, with the
version it shipped in, and write down anything learned that changes a later
step.

**Status:** ✅ done · ▶ next · ○ later

| | Step | Needs |
|---|---|---|
| ✅ | 0. What is already built | — |
| ▶ | 0.1 Take real names and figures out of this repository | the files ✅ 2026.11.11.5 · the history ✅ 11 Nov · two migration comments: the PC on 2026.11.11.5 or later |
| ✅ | 1.1 Read the current SambaPOS backups | — |
| ✅ | 1.2 Link SambaPOS accounts to the books (2026.11.11.7) | — |
| ✅ | 1.3 Bring a whole night in with one click (2026.11.11.8, .9) | — |
| ✅ | 1.4 Keep everything SambaPOS knows, early (2026.11.11.10) | — |
| ○ | 1.5 First live read on the PC (optional now) | the PC |
| ✅ | 1.6 Bring in SambaPOS's own backups by itself (2026.11.11.6) | — |
| ✅ | 2.1 Cash and card kept apart (2026.11.11.11) | — |
| ✅ | 2.2 Count against SambaPOS, at the end of the work period (2026.11.11.11) | — |
| ✅ | 2.3 Blind count (2026.11.11.11) | — |
| ✅ | 2.4 Opening float (2026.11.11.11) | — |
| ✅ | 2.5 Differences over time, and who closed (2026.11.11.11) | — |
| ✅ | 3.1 Stock items: brand and flavour, barcodes, pack weights, minimums (2026.11.11.13) | — |
| ✅ | 3.2 Receipts with lines (2026.11.11.14) | — |
| ✅ | 3.3 Barcode scanner everywhere (2026.11.11.15) | — |
| ✅ | 3.4 Filling a bucket (mixes) (2026.11.11.16) | — |
| ○ | 3.5 Recipes: what each menu item uses | 1.4, 3.1 |
| ○ | 3.6 Expected stock and the gap at each count | 3.2, 3.4, 3.5 |
| ○ | 3.7 Ratio items: foil, coal, filters, cups | 3.6 |
| ○ | 3.8 Shortage warnings | 3.6 |
| ○ | 3.9 Cost and profit per hookah and per item | 3.4, 3.5 |
| ✅ | 4.1 Read the menu from SambaPOS (2026.11.11.12) | — |
| ○ | 4.2 Pictures and descriptions in the app | 4.1 |
| ○ | 4.3 Publish one menu for Twilight TV and the QR menu | 4.2 |
| ○ | 4.4 Sold out, from stock | 3.8, 4.3 |
| ○ | 5. Later | — |

---

## Rules that hold for every step

These were decided deliberately. Changing one is a conversation with
Mohammed, not a side effect of a step.

- **The repository is public.** No books, no SambaPOS backups, no real
  figures, no names of staff, partners or suppliers, ever. Tests use an
  invented lounge. A test that needs real data is skipped unless an
  environment variable points at a local file (`TWILIGHT_EXPORT`,
  `TWILIGHT_POS_BACKUP`). `.gitignore` already refuses `*.db`, `*.bak` and
  `SambaPOS*.zip`; keep it that way.
- **SambaPOS is read, never written.** SELECT only, through Windows' own
  login, no password stored anywhere. The app does not run, change or
  automate the nightly reset, and does not touch SambaPOS's licensing.
- **SambaPOS is the till; the app is the hub.** Prices and menu names are set
  in SambaPOS, because that is where the customer is charged. Who is who —
  staff, partners, salaries, who has left — lives in the app.
- **The books server listens on 127.0.0.1 only.** Anything that must reach
  another device (the menu for Twilight TV and the QR menu) is published as a
  menu-only file. Never the books. Any listener beyond loopback is Tailscale
  only (100.64.0.0/10), never the open internet.
- **Money:** whole dinar in INTEGER columns, Fractions in between, rounded
  once, halves away from zero, to the note (250). No floats near money.
- **Double entry:** money moves only through the recipes in `ledger/post.py`;
  entries are voided, never deleted; a closed month is frozen.
- **Migrations are forward-only.** Once one has shipped it is applied on the
  PC; never edit it. A change is a new numbered file. (The one exception is
  `db.REWORDED`, below in 0.1: a comment, agreed in advance with the version
  already installed.)
- **Every change ships the same way:** tests pass
  (`python -m unittest discover -s tests -t .`), the gate passes against a
  local export (`twilight.py verify`), every screen is opened in a browser,
  `VERSION` is bumped, and it is pushed to `main` — the app updates itself
  from `main`.
- **PC only, minimal.** One column of cards, no phone layouts. The screens
  are in English for now; Kurdish wording is done by giving Mohammed a prompt
  to run through Gemini, not by translating in code.

---

## 0. What is already built ✅

As of version 2026.11.11.4:

- The books: double entry in SQLite, five screens (Tonight, Stock, Month,
  Books, Setup), corrections that keep the original, the pot guard that asks
  before a pot goes below zero, cash counts with write-offs, the month so
  far, settle-up, supplier statements, checks, backups to a second folder,
  updating from GitHub.
- The SambaPOS archive (`ledger/pos/`): each night's work periods, tickets,
  orders, payments, discounts, and every account document (expenses,
  advances, cash in and out of the drawer) kept before the reset. Two ways
  in: SambaPOS's database read directly (`Save tonight from SambaPOS.bat`,
  or Setup → SambaPOS), or a SambaPOS backup file read without SQL Server.
- Tonight shows what SambaPOS took (with **Use** to make it the night's
  sales), what sold, and what SambaPOS recorded going in and out of the
  drawer. Month sets each kept night beside the books.

Not yet tried on the PC: the direct read of SambaPOS's database. It has only
been tested here against a stand-in (see 1.5).

### 0.1 Take real names and figures out of this repository ▶

The rule above was broken from the first commit. These hold real names of
staff, partners and suppliers, real salaries and rent, and real totals from
the books:

- `tests/helpers.py` and every test built on it (`test_postings`,
  `test_setup`, `test_month`, `test_corrections`, `test_stock`,
  `test_money`, `test_pos`)
- `tests/test_real_books.py` — the expected figures are written into it
- `tools/import_json.py` — comments on the five re-dated payments
- `tools/verify.py`, `ledger/queries.py` comments, `docs/design.md`

Done in 2026.11.11.5:

- the tests run on an invented lounge (`tests/helpers.py`: POTS, SUPPLIERS,
  STAFF, PARTNERS, RENT), and every test is moved onto it
- `test_real_books.py` and the gate work out every expected figure from the
  export when they run — through `tools/oracle.py`, or from the export's own
  rows — and hold none of them
- comments and docs say what happened without names or amounts
- `tools/privacy_scan.py` searches the files (or, with `--history`, every old
  version and commit message) for every name and amount in the export and in
  SambaPOS backups. On 2026.11.11.5 it finds one line: a supplier's name in
  a comment in `001_core.sql`
- the app accepts two old migrations reworded in a comment and nowhere else
  (`db.REWORDED`), so that line can go — see below

Done on 11 November, with Mohammed's yes: the history on GitHub was
rewritten to one fresh commit of the cleaned files, force-pushed to `main`.
The old branches `audit-fixes` and `sambapos-archive` were pointed at that
same commit (deleting a branch is refused from Claude's workspace; they can be
deleted on GitHub's website, the branch list, the bin icon). A fresh clone's
`tools/privacy_scan.py --history` finds one line: the migration comment below.
GitHub can keep old commits reachable by their id for a while; GitHub Support
can purge them for good.

Still to do once Setup → Update on the PC shows 2026.11.11.5 or later
(Mohammed to confirm):

1. Reword the comments in `001_core.sql` and `002_stock.sql` exactly as
   `NEW_WORDING` in `tests/test_update.py` says, line for line. The app
   already installed accepts exactly that wording and refuses any other
   change to an applied migration. Shipping it before the PC has
   2026.11.11.5 would stop the PC from updating at all.
2. Squash the history to one commit again and force-push, so the old wording
   is gone from it too, and point the two old branches at it.
3. Run `tools/privacy_scan.py --history` on a fresh clone: nothing found.

Anything already copied from GitHub cannot be recalled; that is why this
comes first.

Done when: a search of the whole repository and its history finds no real
name, salary or total, and the tests and the gate still pass.

---

## 1. SambaPOS as the source of the night

Mohammed records everything in SambaPOS during the day — sales, expenses,
staff advances, owner advances — and types it into the books at night, then
runs the reset. The goal of this part: the books take the whole night from
SambaPOS, and he only checks it and presses one button.

### 1.1 Read the current SambaPOS backups ✅

The backups looked at so far are from June 2025, the week SambaPOS was set
up; that database had only SambaPOS's five default accounts. The current one
has his own Kurdish account types (expenses, staff, owners) and reports.

- Get several recent backups, each made before the reset, and a photo of the
  printed daily report for one of those nights.
- Bring them in with `twilight.py pos import` into a copy of the books, never
  the real ones, and never commit them.
- Check that the app's figures match the printed report: sales, expenses,
  and what was in the drawer.
- List every account type and account, and which document types (buttons)
  he uses. That list is what 1.2 is built on.
- Write down what was learned here, under this step.

Done when: a recent night read from a backup matches its printed report to
the dinar.

Learned so far:

- *11 Nov 2026* — six more backups, of the `twilight` database (SambaPOS
  names its backups after the database, which is the name the app already
  expects). All from 25 June 2025, 00:54–01:25: the night the reset was being
  tried out, with work periods opened and closed within minutes and the
  database restored once in between. Read correctly. The accounts then were
  only SambaPOS's defaults, renamed in Kurdish, plus credit customers; one
  document type (collecting a debt); payment types cash and credit (قەرز).
  No expenses or advances were recorded yet, so these still predate today's
  setup.
- *11 Nov 2026* — seven recent backups (5–11 November 2026). **SambaPOS
  makes one by itself just before every reset** (`twilight_<when>SQT.zip`),
  so every night already has a backup. All seven were read correctly and
  each became the right night.
  - The current setup: one account type for expenses holds three kinds of
    account — staff, owners, and expense categories. Payment accounts: cash
    and a bank (FIB). A second "cafeteria" account type holds one account, a
    second drawer. Document types: expense (خەرجکردن), put cash in
    (تێخستن), take cash out (دەرهێنان), and collecting a debt. Only the cash
    payment type is used now.
  - Expenses and advances in SambaPOS matched the books entry by entry, with
    a handful of exceptions. Salaries, the larger owner withdrawals, rent,
    supplier goods and moves between pots are only in the books: they are
    paid from elsewhere, so they stay entered by hand.
  - The books' sales and what SambaPOS took are not always the same
    figure. Step 2 rests on SambaPOS's figure being the sales and the cash
    count showing any difference, never the sales worked out from the count.
  - A backup is made while the work period is still open (the reset ends
    it), so "ended" cannot tell whether a backup is complete; the backup's
    own time is the latest moment it shows.
  - An expense document can have an amount of nothing (one was entered by
    mistake): leave those out.
  - Work periods are ended at all hours, sometimes the next afternoon. A
    period still belongs to one night — the one most of its tickets were
    opened on — because that is how the printed report and the books treat it.

### 1.2 Link SambaPOS accounts to the books ✅

Every SambaPOS account that money moves to or from is linked once to what it
is in the books. The link is by SambaPOS's own account number
(`Accounts.Id`), never by name — renaming an account in SambaPOS must not
break anything. The nightly reset deletes transactions, not accounts, so the
number stays.

What an account can be linked to:

| In SambaPOS | In the books |
|---|---|
| an expense account | a daily expense category |
| a staff member's account | that person (advance out, money back in) |
| an owner's account | that partner (took cash, put cash in) |
| a supplier's account | that supplier (payment) |
| an income account | other income |
| another drawer or bank | a pot (transfer) |
| anything else | leave out |

- New migration: a `pos_link` table — SambaPOS account id, its account type
  id, the name it had when linked, what it is linked to, when.
- The first time a night brings in an account that is not linked, Tonight
  asks inline, once. It suggests a match by name if one is obvious.
- Setup → SambaPOS lists every link with SambaPOS's current name beside the
  books' name, and lets a link be changed.
- Renamed in SambaPOS: the link stays, the shown name follows.
- Gone from SambaPOS's accounts: the app asks "has this person left?" with
  one click to mark them as left.
- Marked as left in the app but SambaPOS still records money for them:
  Tonight points it out, and reminds once to remove the account from
  SambaPOS.
- An account deleted and made again in SambaPOS has a new number, so it is
  asked about again, with the old link suggested by name.

Done when: tests cover a rename, a deletion, a person who left, and an
unlinked account; every account in the real backups from 1.1 can be linked.

Done in 2026.11.11.7:

- `ledger/pos/links.py`; migration 008 adds `pos_account` (SambaPOS's
  accounts as its newest snapshot lists them — an older backup read late
  changes nothing) and `pos_link` (what each is in the books).
- Tonight's "What SambaPOS recorded" card shows each account's link, or a
  picker the first time. Setup → SambaPOS accounts lists every account money
  moved through, and the unused ones of the same kinds, so a new one can be
  linked before it is used. A picker can also make a new expense named as
  SambaPOS names it.
- Suggestions only when plain: the same name in the books, an account made
  again under the name of one that was linked, and the drawer as the main pot.
  SambaPOS's names are in Kurdish and the books' mostly not, so expect to pick
  most of them by hand, once.
- Two checks on Tonight: someone SambaPOS no longer has is still active in
  the books (one click marks them as left), and SambaPOS recorded money for
  someone after they were marked as left (until dismissed with Done).
- Retiring anything in Setup now records the day (`retired_on`), so "after
  they left" is exact.

Learned from the November backups: every expense, staff advance and owner
withdrawal is one document type, Expense (خەرجکردن), from the Cash drawer to
an account of the one expense account type; which it is depends only on the
account. The current account list: 2 payment accounts, 21 expense-type
accounts (staff, owners, categories), plus SambaPOS's own.

### 1.3 Bring a whole night in with one click ✅

Tonight shows the night as SambaPOS recorded it, each line already turned
into the books entry it will become:

- sales: the paid figure (as **Use** does now)
- each account document: an expense, advance, owner withdrawal, money back,
  supplier payment or transfer, from its link and from which way it moved
  the drawer

**Add the night** posts them all in one transaction. Each entry carries
`source = 'pos'` and `source_ref = 'pos:doc:<SambaPOS document id>'`, so:

- bringing the night in twice adds nothing twice
- an entry deleted in the books by hand is not brought back
- a document that SambaPOS reversed is never added

A line whose account is not linked holds the night back until it is linked
(1.2). The pot guard applies as usual. Entries already typed by hand for the
same night are shown beside the SambaPOS lines, so nothing gets doubled
during the switch-over.

Done when: a real night from 1.1 goes into a copy of the books in one click
and matches what Mohammed typed by hand for that night, or every difference
is explained.

Done in 2026.11.11.8 (`ledger/pos/adding.py`; Tonight's card "The night in
SambaPOS"). Decided while building it:

- References are `pos:doc:<document id>:<its time>` and
  `pos:sales:<night>:<amount>`. The time is there because a reinstalled
  SambaPOS would count document ids from 1 again.
- Takings typed by hand are never replaced by **Add the night**, even when
  SambaPOS's figure differs: the cash of that night may already have been
  counted against them. The line says "check", and **Use** in step 1 is the
  way to replace them on purpose. Takings added from SambaPOS before are
  replaced by a fuller copy of the night.
- A line counts as typed by hand when the books hold entries of the same kind
  for the same person or expense that night with the same amounts, or the
  same total split differently. Otherwise it says "check" and is not added,
  so nothing is counted twice; entries only in the books are listed under
  the card.
- A document with no amount, a reversed one, and an account linked as "leave
  it out" are not added. Money moving a way the books have no entry for (an
  expense account paying into the drawer) says "enter by hand".

Learned: on the real nights of 4 to 10 November every line agreed with what
was typed by hand, except the differences already found in 1.1 — the takings
on four nights, and three expenses or advances. The nights with nothing typed
by hand went into a copy of the books in one click, and the cash moved by
exactly what SambaPOS says left and entered the drawer.

### 1.4 Keep everything SambaPOS knows, early ✅

Later steps need tables the archive does not keep yet. Add them to the
nightly save now, so the history exists by the time they are built:

- `WorkPeriods.StartByName`, `EndByName` — who opened and who closed (2.5)
- `PaymentTypes` and each payment's type — cash against card or transfer (2.1)
- `MenuItemPortions`, `MenuItemPrices`, menu item group — the menu (4.1)
- whatever inventory and recipe tables SambaPOS holds, if 1.1 shows they are
  used (3.2, 3.5)

`sources.TABLES` takes care of a column a version of SambaPOS does not have.
Menu tables are not wiped by the reset, so they can be read whole each time.

Done in 2026.11.11.10 (migration 009, `ledger/pos/catalog.py`):

- each work period's `opened_by` and `closed_by`, each payment's `type_id`
- `pos_catalog`: payment types, menu items, portions, prices, inventory
  items, recipes and their lines, one row each as SambaPOS has them, kept up
  to date from the newest snapshot. SambaPOS's `Users` table is never read:
  it holds passwords and PINs.
- `auto.READS`: when reading a backup starts keeping something new, every
  backup in the folder is read once more, so nights kept earlier get it too.

Learned from the real backups:

- **Who closed a work period is never in SambaPOS's own backup.** The backup
  is made just before the reset, while the period is still open, and each
  backup holds only the current period. Who opened it is there. For 2.5,
  who closed has to come from a live read after closing, or be asked for.
- SambaPOS already has inventory items and recipes set up (one recipe per
  menu portion), but no inventory transactions and no end-of-day counts are
  entered in it. 3.5 can start from those recipes rather than from nothing.
- One payment type is in use: cash.

### 1.5 First live read on the PC ○ (optional now)

Since SambaPOS backs itself up before every reset (1.1), reading its
database directly is only a convenience now — for seeing tonight before the
reset has run. The nightly double-click is not needed.


The direct read (`ledger/pos/sambapos.ps1` through Windows PowerShell) has
only been tested here with PowerShell 7 against a stand-in for SQL Server.
On the PC:

- Setup → SambaPOS → **Test the connection**.
- If SQL Server will not let the Windows account in, Setup shows four lines
  to run once as `sa` that grant read-only access to SambaPOS's database.
- Then **Bring it in now**, and compare with the printed report.
- From then on: double-click **Save tonight from SambaPOS** just before the
  reset, every night.

Done when: a night read live matches the printed report.

### 1.6 Bring in SambaPOS's own backups by itself ✅

Done in 2026.11.11.6. SambaPOS puts a backup in its backup folder before
every reset. With that folder set in Setup → SambaPOS, the app brings in any
backup it has not read, so every night is kept without anyone doing anything:

- `ledger/pos/auto.py`, on a thread of its own: when the app starts, every
  five minutes, when a screen asks for the books (at most every 15 seconds),
  and at once when a folder is chosen. While backups are waiting, the screen
  asks again every few seconds, so the night appears by itself.
- `pos_file` (migration 007) remembers every file read, by name, size and
  time — not just the newest, so an old backup copied in later is read too,
  and one that changes is read again. A file written in the last minute is
  left for next time. One that will not read is remembered with the reason.
- A check on Tonight: the folder is gone, holds no backups, its newest backup
  is more than 30 hours old (the reset was not run, or SambaPOS backs up
  somewhere else now), or its newest backup will not read.
- Setup → SambaPOS shows how many backups were read and the newest; **Look in
  the folder now** and **Read every backup there again** do it by hand.

Learned: a backup of about 5.6 MB reads in about 0.15 s, so the seven recent
ones take about a second.

---

## 2. Cash you can trust

The counted cash and what SambaPOS says sometimes differ, up or down. The
usual causes: money leaving the drawer with no entry, a card or transfer
payment entered as cash (or the reverse), tickets left unpaid, change
mistakes, and counting at a different moment from the report. The books must
show the real sales and the difference separately — if the sales figure is
ever adjusted to match the cash, a shortage disappears and no pattern can be
seen.

### 2.1 Cash and card kept apart ✅

Use SambaPOS's payment types (1.4). Only cash goes to the Box; a card or
transfer payment goes to its own pot (a bank or FIB pot) automatically when
the night is added. The count then compares cash with cash.

SambaPOS also has a credit payment type (قەرز): a ticket put on a customer's
account is not cash at all. It must not go into the Box, and it should show
as money customers owe until they pay — collecting it is its own SambaPOS
document type. Until this step is done, **Use** on Tonight takes every
payment as cash, so a night with credit on it needs checking by hand.

### 2.2 Count against SambaPOS, at the end of the work period ✅

What should be in the drawer = opening float + cash payments − cash out of
the drawer + cash into it, all from SambaPOS for that work period. Tonight's
count compares against that, and says when the count was taken long after
the work period ended.

### 2.3 Blind count ✅

An option in Setup. Whoever counts types what they find before the app shows
what was expected; the expected figure and the difference appear only once
the count is saved. A well-known control: nobody can count towards the
answer.

### 2.4 Opening float ✅

A fixed float in small notes at the start of each work period, set once in
Setup, so change is always possible and the count knows what was there
before the first sale. Prices that are all multiples of 250 also cut change
mistakes; worth a check on the menu (4.1 makes that easy).

### 2.5 Differences over time, and who closed ✅

A card on Month: each night's difference, as a small chart, and differences
grouped by who closed the work period (1.4). Small ups and downs are normal;
a steady shortage on certain nights or shifts is not. Write-offs stay as
they are: a difference accepted as real becomes a cost of its month.

### Step 2 as built (2026.11.11.11)

`ledger/cash.py`; Tonight's count step; Setup → Counting the cash; Month →
Cash differences. Decided while building it:

- **2.1** A payment's type leads to its SambaPOS account, and that account's
  link (1.2) to a pot: cash into the drawer's pot, a card or FIB into the
  bank's, one sales entry each. Payments kept before their types were go
  into the drawer as one line, as before. A way of paying whose account is
  not a pot — credit (قەرز) would be one — says "enter by hand": customers
  owing money is not in the books yet, and only cash is in use today.
- **2.2** The count step shows, under the drawer's pot, what SambaPOS says
  went in as cash and out and in through the drawer that night, and with a
  float set, what should be there. When the books' sales for the night are
  not SambaPOS's, it says a shortage (or surplus) of the difference may be
  hidden in them. Not built: saying the count was taken long after the work
  period ended. The app only knows when a count was typed in, not when it
  was taken, and SambaPOS's own backup never records the close, so the note
  would mislead.
- **2.3** Blind counting is a choice in Setup. Until the night's count is
  saved, Tonight hides what the books and SambaPOS expect. It is a habit for
  the counting screen, not a lock: the same figures are on other screens.
- **2.4** The float is set in Setup. After the count, Tonight offers to move
  everything above it out of the drawer's pot in one click. That transfer is
  tied to the count (`source_ref = 'count:<id>:rest'`), so the night's count
  does not expect it: it happened after the counting.
- **2.5** Month → Cash differences: each night's own difference — its gap
  with the books, less whatever the count before it left unexplained, so a
  shortage nobody wrote off counts once — with totals, and grouped by who
  **opened** SambaPOS that night. Who closed is never in SambaPOS's backup
  (see 1.4), so it can only come from a live read after closing (1.5).

---

## 3. Stock that adds up

"Perfect" is not possible — a free hookah, spillage and staff use never get
recorded — but the app can know at any moment what should be on the shelf,
and show the gap at every count. Expensive things (tobacco) are tracked
exactly; cheap things (foil, coal, filters, cups) by a learned ratio.

Everything bought is recorded, in one of two ways:

- **stock that is kept and counted** — tobacco, drinks, coal, foil, cups: a
  receipt with lines saying what and how much (3.2)
- **things used up the same day** — fruit, vegetables, ice, staff food: a
  daily expense, as now

### 3.1 Stock items: brand and flavour, barcodes, pack weights, minimums ✅

- Sealed tobacco becomes one item per brand and flavour (Hill Leaf · Two
  Apples, Hill Leaf · Mint, Star Leaf · Love, …), grouped under the brand on
  the count sheet, flavours not carried folded away.
- The price is set per brand; a flavour can override it.
- Pack weight per item, default 50 g (10 packs to a block today, set in
  Setup); a brand with other packs gets its own.
- One or more barcodes per item.
- A minimum per item, for 3.8.
- Each item says how it is tracked: packs, pieces, weighed (buckets), or by
  ratio (3.7).
- Migration: these columns, and a way to move the existing counts across —
  today's sealed tobacco lines are per brand, so old counts stay per brand
  and new ones are per flavour.

As built (2026.11.11.13), in Setup → Stock items:

- **Comes as.** Packs differ by brand — 50 g, 10×50 g, 12×10×50 g, 1 kg,
  3×1 kg, 6×1 kg, 250 g — so a sealed tobacco says how it comes, typed the
  way the box says it. Blank means the usual packs (Setup → How sealed
  tobacco converts) or, for a flavour, its brand's. The count sheet shows a
  box for each size the item comes in, with the size written under it.
- **Flavours.** "Add a flavour" puts one under its brand, named
  "Brand · Flavour". It costs what its brand costs, comes as its brand does
  and is on its brand's supplier's statement, unless it says otherwise.
  Renaming a brand renames its flavours; stopping a brand stops them, and
  bringing it back brings them back.
- **Old counts stay per brand.** On the count sheet a brand with flavours is
  only their heading, unless the count being looked at has a line for the
  brand itself.
- **Warn below.** A minimum per item, in kilos for tobacco and packages for
  the rest, for 3.8.
- **Barcodes.** As many per item as needed: scan (or type) into the item's
  box and it is added; ✕ takes one off. A code belongs to one item only.
  3.3 puts the scanner to work.
- Not built: a separate "how it is tracked" per item. The category already
  says it (weighed, sealed, ice cream, packages); tracking by ratio waits
  for 3.7.

### 3.2 Receipts with lines ✅

A supplier receipt lists what came in: item, how many, price. Its total
still has to match the supplier's invoice, and only the total moves money,
as now. Lines can be added by scanning. If 1.1 shows purchases are entered in
SambaPOS, they can come in from the nightly save instead of being typed
twice.

As built (2026.11.11.14), on Stock → Receipts: a new receipt opens **What
came in** with the cursor in its item box. Type or pick an item, or scan its
barcode (a scanner types the code and presses Enter), and it gets a line in
the boxes it comes in — the same sizes as the count sheet — and an amount,
which can be left out. Each line saves as you leave it, and ✕ takes it off.
The lines say whether they come to the receipt's total. Only the total moves
money. A corrected receipt keeps its lines, a deleted one takes them with it
(and brings them back if it is put back), and a closed month's lines are
kept as they were. Purchases are not entered in SambaPOS (1.1), so nothing
comes in from the nightly save. A mix is made here, not bought, so weighed
items are not received.

### 3.3 Barcode scanner everywhere ✅

A USB scanner types the code and presses Enter, like a keyboard, so it needs
no setup: any box that accepts a scan works with it. Used in receipts,
counts, and filling buckets. The first time an unknown barcode is scanned,
the app asks once what it is (brand, flavour, pack weight) and remembers.

As built (2026.11.11.15): a scan works wherever the cursor is. Very fast
typing that ends in Enter is a scan, and it is taken back out of whatever box
it landed in, so a code can never become a count or an amount. Then:

- with a receipt's lines open, the item goes on the receipt
- on Stock with a count open, the sheet goes to the item's line, lights it
  and puts the cursor in its first box
- anywhere else, it says what the item is

Setup's barcode boxes take a scan as typed. A code nobody has seen asks once
which item it is, from the list, and is remembered; an item that is not on
the list yet is added in Setup first. A code typed through a Kurdish or
Arabic keyboard layout (٠١٢…) is read as the same code. Filling a bucket
(3.4) takes scans the same way.

### 3.4 Filling a bucket (mixes) ✅

Mohammed makes his own mixes in buckets from several brands and flavours,
counting packs, not weighing.

- Each mix has a usual batch, in packs: say 8 Fakher · Two Apples +
  6 Adalya · Love 66 + 6 Serbetli · Mint.
- Stock → **Fill a bucket**: pick the mix, press "the usual" or change the
  numbers (or scan the packs as they go in), optionally weigh the full
  bucket. Only tobacco goes into a mix.
- Saving it is a stock move, not money: those packs come off each item, and
  their weight goes into the bucket at their cost. A bucket that still had
  some mix in it averages the cost of old and new.
- So each mix gets a real cost per kilo from what went in, instead of a
  fixed price.

Worked example, with invented prices: 8 packs of a brand at 30,000/kg is
400 g, 12,000; 6 packs at 25,000/kg is 300 g, 7,500; 6 packs at 20,000/kg is
300 g, 6,000 — a 1 kg bucket at 25,500 a kilo.

As built (2026.11.11.16), on Stock → Fill a bucket: pick the mix and its
usual batch is filled in. The first time there is none: add what goes in by
name or barcode, and it is kept as the usual. Change any figure, or scan the
packs as they go in (each scan is one more pack); grams and cost work
themselves out from each tobacco's pack size and price. **Fill it** moves the
packs and no money. The mix's price per kilo becomes the blend of what went
in and what was already in the bucket, known when the full bucket is weighed
(the scales less the bucket); unweighed, the bucket is taken as empty, so the
price is what this batch cost. The new price values the next count. A fill
can be deleted, and the mix's price goes back unless something has changed
it since. Expected stock (3.6) takes the packs off each tobacco and adds the
grams to the mix.

### 3.5 Recipes: what each menu item uses ○

Each SambaPOS menu item, linked by SambaPOS's menu item number, says what
one of it uses: a hookah of a flavour takes so many grams from its bucket (or
straight from one flavour), a tea takes a tea bag and sugar, a can of drink
is one can. Every kept night (orders are already archived) then takes stock
off automatically. Items with no recipe are listed until they have one.
A head takes the same grams whatever the flavour, so that is one setting; it
is filled by hand, so it is an average, and 3.6 allows for that.

### 3.6 Expected stock and the gap at each count ○

For every item at every moment:

    expected = last count + received + filled into it − filled out of it − used by sales

At a count, the gap between expected and counted shows item by item:

- a bucket lighter than expected: over-packed heads, waste, or drying —
  Setup holds a small drying allowance so normal drying is not flagged
- a sealed flavour short of what it should be: it left the shelf without
  going into a bucket

Count the expensive things (tobacco) weekly and cheap things monthly.

### 3.7 Ratio items: foil, coal, filters, cups ○

Foil comes in rolls, 6 to a carton, and the staff cut and pierce it; coal
comes in 12 kg cartons. Both are counted roughly, with fractions. Between two
counts the app divides the hookahs SambaPOS sold by what was used and learns
**hookahs per roll** (per box of coal, and so on). From then on it knows
roughly what each night uses. A ratio that suddenly drops means more is
going somewhere than the sales explain.

### 3.8 Shortage warnings ○

When an item's expected stock falls below its minimum, Tonight says so —
and, from the recent pace of sales, roughly how many nights are left — so
reordering happens before it runs out.

### 3.9 Cost and profit per hookah and per item ○

From recipes and mix costs: what each menu item costs to make, beside its
price, so it is clear which flavours and items make the most. Best and worst
sellers by month, from the archive.

---

## 4. One menu for SambaPOS, Twilight TV and the QR menu

The same names, prices and pictures everywhere, set in one place. The price
a customer pays is the one SambaPOS charges, so SambaPOS stays where names
and prices are set; the app reads them and adds what SambaPOS lacks.

### 4.1 Read the menu from SambaPOS ✅

Menu items, groups, portions and prices (1.4), kept current each time
SambaPOS is read. The nightly reset does not touch the menu.

Done in 2026.11.11.12: Setup → SambaPOS → "The menu, as SambaPOS has it"
(`catalog.menu`): each group folded, every item with its portions and prices
and how many sold over the last 30 nights kept, and the prices that are not
a multiple of the smallest note. Learned: every whole price on the menu is a
multiple of 250; the only others are below 250, prices per gram or per piece.

### 4.2 Pictures and descriptions in the app ○

Linked by SambaPOS's menu item number: a picture, a description, which
items show on the TV and in what order. A rename or price change in
SambaPOS flows through by itself.

### 4.3 Publish one menu for Twilight TV and the QR menu ○

The app writes a menu-only file (names, groups, prices, pictures) and
publishes it where the TV box and customers' phones can reach it — for
example a page on Mohammed's own website, or over Tailscale for the TV box.
Never the books, and the books server stays on 127.0.0.1. Twilight TV (its
own repository) and the QR menu page both read that one file, so a price
changed in SambaPOS changes on the TV and the QR menu the same night.

### 4.4 Sold out, from stock ○

When the expected stock of what an item needs reaches nothing (3.6, 3.8),
the published menu marks it sold out.

---

## 5. Later

Ideas raised and worth keeping, not yet planned in detail:

- sales by hour and by day of the week, and table turnover — SambaPOS
  already has custom reports for these; the archive can do them over months
- Kurdish wording on the screens, via a Gemini prompt Mohammed runs himself
- a month-end summary he can print or send to his partner

---

## Questions to settle when the step comes up

- 1.1 — answered: see 1.1, 1.2 and 1.4. Purchases are not entered in
  SambaPOS; inventory items and recipes are set up but not used.
- 2.1 — answered: cash is the only payment type in use.
- 2.4 — answered: a float is always left in the drawer. Its amount is set in
  Setup → Counting the cash.
- 3.1 — answered: no, packs differ by brand (see 3.1 as built).
- 3.4 — answered: only tobacco goes into the mixes. Still to settle when 3.4
  is built: the usual batch for each mix.
- 3.5 — answered: the same for all flavours, and rough, since heads are
  filled by hand.
- 3.7 — answered: foil in rolls, 6 to a carton, cut by the staff; coal in
  12 kg cartons.
