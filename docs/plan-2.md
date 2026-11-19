# The second plan: ready for real use

The first plan (`docs/plan.md`) is finished. What it left undone stays undone,
as Mohammed decided on 19 Nov 2026. This plan is about the app itself rather
than new features: make it safe to rely on every night, take out what is not
used, split the long files, and make the parts that are fragile simpler.

Later the same day Mohammed asked for research into today's (2026)
engineering for every part of the app, and then for this plan to follow it.
The research found the core already sound: double entry that is never
edited, one SQLite file, plain screens with no framework, and Kurdish from
Gemini that Mohammed checks. So it changes what is around the core. It
sharpened most steps, and added steps 3, 8, 9 and 10, the suggestions, and a
list of what is not planned and why.

Each step stands on its own and ships as its own version, like before. Read
`docs/design.md` first. The rules in `docs/plan.md` still hold: nothing from
the real books in this public repository, the app listens on 127.0.0.1 only
(anything beyond it is Tailscale only, never the open internet), SambaPOS is
only ever read, `Start Twilight Ledger.bat` never changes, and Kurdish comes
from Mohammed's Gemini prompts, never from Claude. A step that adds
sentences ends with a Gemini prompt for them.

**Status:** ✅ done · ▶ next · ○ later · ? waiting for a decision

| | Step |
|---|---|
| ▶ | 1. A safety net first |
| ○ | 2. Ready for real use |
| ○ | 3. A real Windows app |
| ○ | 4. Clean-up |
| ○ | 5. Smaller files |
| ○ | 6. Simpler architecture |
| ○ | 7. The screens |
| ○ | 8. SambaPOS through Microsoft's driver |
| ○ | 9. Asking the books, through Claude |
| ? | 10. When wanted (each part when Mohammed asks for it) |
| ○ | 11. Bug hunts, after every step |
| ○ | 12. Pure Kurdish words (can run alongside any step) |

Mohammed's decisions of 19 Nov 2026 are written into the steps they change.
He asked for them to be planned, not done yet.

## What a survey of the code found (19 Nov 2026)

- About 10,000 lines of Python, 5,400 of JavaScript and CSS, and 614 tests.
- Long files: `web/cards.js` 1,940 lines, `web/app.js` 1,924,
  `ledger/queries.py` 1,097, `ledger/actions.py` 640, `ledger/setup.py` 622.
- Little dead code. Every one of the 1,512 sentences is used. Every button
  has its handler and every handler a button. The CSS has no unused classes.
  What is unused: `kinds.labels()`, `pos/links.AS`, `dates.month_name()`
  (tests only), and the Kurdish kept in the books from the Gemini days
  (`lang_text`), now that `web/lang/ckb.json` has all 1,421 sentences.
- The weak spots are design, not dead code:
  - The server writes English and the page translates it back by matching
    patterns (`web/i18n.js`, 455 lines). A reworded English sentence quietly
    stops matching. Recent changes are stored in the books as English text.
  - Every load and every save sends the whole of every tab: about 150 KB on
    the real books today, about 0.5 MB after two years, every receipt ever
    made included.
  - The fuzzer still finds 216 crashes, all from fields of the wrong type,
    which the screens never send.
- Backups are full copies, one a day, never deleted. After two years of
  invented books a copy is 30 MB, about 11 GB a year. Zipped, 3.6 times
  smaller.
- The app updates itself from `main` on GitHub. One bad push would reach
  the PC. Nothing checks a push before it gets there except Claude.

## 1. A safety net first

Everything later moves a lot of code. This comes first so that nothing
broken can reach the PC.

1.1 **Checks on GitHub, on Windows and on Linux.** Every push runs the
tests, the lint and the browser checks in GitHub Actions: on a Windows
machine, like the lounge's PC, and on Linux. Standard runners cost nothing
for a public repository. If the checks fail, there is no new version. The
checks use invented books only; the real books never go to GitHub.

1.2 **The browser checks in the repository**, under `tests/browser/`,
written with Playwright. They are the tools from the bug hunts, which so far
live only in Claude's workspace:
- every screen in both languages: no script errors, no English left
- every button pressed once
- random clicking
- a page left open overnight and into a new month
- the update itself

They need Node and Playwright, but only on the machine running the checks,
never on the PC.

1.3 **Long random runs, with Hypothesis.** Its stateful tests take over
from the hand-written fuzzers (odd values, random undo, voids and closes).
They play out long runs of actions (add, void, undo, close a month, reopen
it) and check after every step that the books balance, that undo puts back
exactly what was there, and that a closed month never moves. A failure
comes back shrunk to the few steps that cause it. Hypothesis is for the
checks only: its tests skip themselves where it is not installed, and
nothing is added to the app.

1.4 **A stable channel, through GitHub Releases** (agreed 19 Nov; the
research's way of doing it). The app updates from the latest release
instead of `main`. Only the checks make a release, when they pass, and they
publish its SHA-256 beside it; the app refuses a download that does not
match. The first version that reads releases is shipped through `main` as
usual. Step 3 keeps the same releases.

1.5 **Go back a version.** Setup → This app gets a button that puts the
previous version back. Its code is already kept, zipped, at every update.

1.6 **Lock the GitHub account** (Mohammed): two-step sign-in, and nobody
else with write access. Whoever can push to this repository can run code on
the lounge's PC.

## 2. Ready for real use

2.1 **A second copy on another drive in the PC** (decided 19 Nov). The app
has the setting already (Setup → Backups, the second folder), and one of
its checks flags that it is not set. Today every copy is on the same disk.
- It must be a separate physical disk. On many PCs D: is only a second
  part of the same disk, which dies with it. Windows' Disk Management
  shows which disk each letter is on.
- It covers the first disk dying, not theft or fire. A copy that leaves
  the building would cover those: see the suggestions.

2.2 **Smaller copies, with restic** (decided 19 Nov: smaller copies; the
research the same day chose restic over zipping). From the switch on, each
day's checked copy goes into a restic repository instead of a loose file:
one in the backups folder, and one on the second drive (2.1).
- restic keeps only what changed since the day before, compressed. A year
  of daily copies costs little more than one copy, where zipping would only
  have made each copy 3.6 times smaller.
- Copies already made stay as they are, and nothing is ever taken out of
  restic: its `forget` and `prune` are not used. Deleting old copies would
  need Mohammed's decision, and is not planned.
- restic always encrypts (AES-256), so a repository opens only with its
  password. On one PC the danger is a dead disk, not a thief, so the
  password is kept beside each repository and either disk alone can
  restore. Mohammed also writes it down. It never goes with an off-site
  copy, if there is ever one (see the suggestions).
- `restic check` proves a repository is sound; "Check this copy" (2.3)
  runs it.
- restic.exe comes with the app from step 3. Until then it is downloaded
  once from restic's own releases and checked against their published
  checksum.
- If restic is missing or fails, the day's copy is made as a loose file,
  as now, and the checks say so.

2.3 **Restore in the app.** Setup → Backups gets two things. "Check this
copy" checks it and opens it read-only. "Restore" saves the books first,
then restores. Both work with loose copies and with restic's. Today a
restore needs the black window.

2.4 **A restore drill, once.** Restore last week's copy into a scratch file
and compare it with the books.

2.5 **A problem report.** One button writes a file with the version, the
checks and the end of `twilight.log`, and no names or figures. Mohammed
sends it when something goes wrong on the PC.

2.6 **The Windows-only things**, tried once on the PC from a short list:
- the icon and the window
- printing on the lounge's printer
- the clock warning
- reading a SambaPOS backup
- an update, and going back a version
- a restic copy, and a restore from it

2.7 **Power** (a recommendation, not code). A small UPS for the PC and the
router. The books are written safely (synchronous = FULL), but every power
cut is still a hard stop.

2.8 **Each wallet its own pot** (Mohammed, settings only; from the
research). Paying by FIB, FastPay or ZainCash is growing in Kurdistan. The
app already puts each way of paying into the pot its SambaPOS account is
linked to (`ledger/pos/adding.py`). So each wallet the lounge accepts
becomes its own payment type in SambaPOS with its own account (Mohammed
sets that up in SambaPOS), linked here to its own pot. The drawer's count
then compares cash with cash, and no wallet payment hides in a cash
difference.

## 3. A real Windows app

New, from the research. Today the PC needs Python installed, the `.bat` or
the desktop icon starts the app, Edge lends it a window, and the pages send
a heartbeat so the app knows when that window closes (`docs/design.md`,
"Its own window"). The 2026 way keeps every screen and every line of the
server, and gives them a proper Windows shell.

3.1 **Python inside, and its own window.** PyInstaller bundles Python 3.14
with the app, so nothing has to be installed first. pywebview opens the
app's own window around the same pages, drawn by WebView2, Edge's engine.
Closing the window stops the app, so the heartbeat goes. About 40 MB.

3.2 **Installed and updated by Velopack.** One command (`vpk`) builds the
installer and the update packages for each release (1.4). An update
downloads in the background and applies in seconds, with no admin prompt.
Velopack's hooks run the app's own steps at each stage, so the two rules of
today's updater stay: the books are copied before an update, and the new
version must open them before it takes over. Going back a version (1.5)
uses Velopack's downgrade option.

3.3 **The move, once, on the PC.**
- The installed app opens the books where they are now,
  `C:\Twilight Ledger\data\twilight.db`. They are never copied to a second
  place that could drift apart.
- The version that makes the move adds no migration, so the old app can
  still open the books if the move has to be undone.
- `Start Twilight Ledger.bat` does not change. What it runs can: started
  by the `.bat`, `twilight.py` opens the installed app when there is one,
  so the `.bat` keeps working.
- The desktop icon moves to the installed app.
- The app already finds a copy of itself running against the same books
  and opens that instead of starting a second (`running_at` in
  `ledger/server.py`), so the old and the new never write side by side.

3.4 **SmartScreen.** Without a code-signing certificate, Windows warns once,
the first time the installer runs ("More info", then "Run anyway"). A
certificate costs money every year and is not planned.

3.5 **What it brings with it:** restic.exe (2.2), and later the libraries of
steps 4.3 and 8. Python 3.14 also brings template strings (6.1).

## 4. Clean-up

4.1 **Remove the unused code** from the survey, and the `lang_text`
fallback with the `kept` path in `i18n.js`. First check on the PC that
nothing on its screens still uses it.

4.2 **Retire the old-books migration** (decided 19 Nov: TwilightBooks is
finished with). What goes:
- `tools/import_json.py`, `tools/verify.py` and the `import` and `verify`
  commands in `twilight.py`
- their tests, and the import-and-verify gate run before each push

`tools/privacy_scan.py` stays, because the repository is still public. It
takes the arithmetic it needs from `tools/oracle.py` (the class `Old`),
which moves into the scan or stays for it alone. Git keeps the rest.

4.3 **Each action says what it takes**: its fields, their types, which are
needed. The registry checks a body against that before the action runs.
The 216 fuzz crashes become plain refusals, and the inputs are written down
in one place. With the bundled app (3), msgspec does the checking, a
library of under half a megabyte; without it, a short check in plain
Python.

4.4 **Take out what step 3 replaced**, once the PC runs the installed app:
Edge's app window and the heartbeat (`ledger/window.py`, the pages' hello
and goodbye), the desktop-icon script (`ledger/desktop.ps1`), and today's
updater. `twilight.py` keeps what the `.bat` needs (3.3).

4.5 **Fix the remaining lint notes**, and archive `docs/plan.md`.

## 5. Smaller files

No file over about 500 lines, each about one thing. These are moves only,
with no change in behaviour. Each is checked by:
- the identical-figures comparison used for the speed fix (every screen's
  data, old code against new, on the real books and on two years of
  invented ones)
- the tests
- the crawls

The files:
- `web/app.js` and `web/cards.js` → one module per tab (tonight, stock,
  month, books, setup), each with its cards and its buttons' handlers.
  Small shared modules: talking to the server, dialogs, the night's
  clock, formatting. Still plain files with no build step. A card that
  grows behaviour of its own can become a Web Component: a small class,
  no library.
- `ledger/queries.py` → `ledger/queries/` by subject: entries, cash, the
  month's figures, suppliers, stock.
- `ledger/actions.py` and `ledger/setup.py` → by subject.
- The state in `ledger/api.py` → one part per page, which prepares 6.2.

## 6. Simpler architecture

The server stays on Python's own HTTP server and SQLite. The research found
nothing to gain, for one PC, from a web framework (FastAPI, Litestar) or a
database server.

6.1 **The server speaks the screens' language.** A message carries its
sentence name and values, and the page says it in English or Kurdish.
Recent changes store the name and values too. `i18n.js` shrinks to a
fallback for changes recorded before this.
- Python 3.14's template strings (`t"…"`, PEP 750), which come with the
  bundled app (3), keep a message's words and values apart: exactly this.
- It is the idea behind MessageFormat 2, the Unicode standard for app
  messages. Its syntax is not needed yet: `{0}` stays.

6.2 **Smaller answers.** Send what every page needs, plus each page's own
part when it is opened. Long histories go by the month, with "show older".
Saves get faster, and stay fast as the years add up.

6.3 **List SambaPOS's backup folder once a minute**, not on every screen
load. At 747 files it takes 17 ms here, and more on Windows.

6.4 **Log slow requests**: anything over a second, with what it was. Then
slowness on the PC shows up in the problem report.

6.5 **One save, once.** Each save carries a key the page makes for it. If
the same save arrives twice (a double press, a retry after a slow answer),
the server returns the first answer instead of saving again. Payment
systems call this idempotency.

6.6 **New tables are STRICT**, so SQLite itself refuses a value of the
wrong type, below the app's own checks. Tables already made stay as they
are: migrations only go forward.

## 7. The screens

7.1 **A minimal design pass**, page by page, Kurdish first. Before and
after screenshots go to Mohammed for approval. The direction:
- fewer boxes and lines
- one accent colour
- quieter banners
- the same spacing everywhere

7.2 **Keyboard.** Enter saves, Esc closes a question, and the cursor goes
to where the next entry is typed. The questions become the browser's own
`<dialog>`, which brings Esc and the cursor's place with it.

7.3 **The browser's own parts for the rest**, all in Edge already, with no
framework and no build step:
- the Navigation API for the `#tonight/close` addresses
- the Popover API and anchor positioning for hints and menus, placed next
  to what they belong to
- a quiet fade between pages (view transitions), only if Mohammed likes it
  in the screenshots

7.4 **Retiring a pot that is below zero.** It says "Move it out first",
which makes no sense for a pot below zero. It needs one new sentence, so a
Gemini prompt.

7.5 ✅ **The Month tab at the end of a month** (decided 19 Nov: as now). A
page left open keeps the old month until it is reloaded, which is handy for
closing that month. Nothing to do.

## 8. SambaPOS through Microsoft's driver

New, from the research. Today the app reads SambaPOS live through a
PowerShell script, and its nightly backups with its own reader.

8.1 **mssql-python**, Microsoft's own Python driver for SQL Server
(generally available since November 2025), replaces the PowerShell script.
It signs in with Windows as now, so there is still no password anywhere,
and it needs no ODBC setup. Numbers and dates come back as themselves, not
as text. It comes with the bundled app (3).

8.2 **Still only SELECT**, and SambaPOS's `Users` table is never read.
SambaPOS's GraphQL API is not used: it can also change prices and tickets.

8.3 **The backup reader stays.** It works when SQL Server is down, and it
is how old nights get in.

8.4 **Nothing about matching changes here.** How typed figures are matched
with SambaPOS's waits for a talk with Mohammed.

## 9. Asking the books, through Claude

New, from the research.

9.1 **A read-only helper for Claude Desktop**, packed as one `.mcpb` file
(an MCP bundle) and installed with one click under Settings → Extensions.
Mohammed asks Claude, for example, what charcoal cost each month this year,
and Claude answers from the books.
- Its tools are the app's own reports: the month's figures, the pots, a
  night's close, the Entries search. Claude's figures are then the app's
  figures, worked out by the same code.
- It never writes: the books are opened read-only, SQLite is told to
  refuse writes, and no tool saves anything. Entries are made in the app.
- Whatever Claude reads to answer goes to Anthropic, like anything asked
  of Claude. Nothing is sent until he asks.

9.2 **Warnings about unusual figures, in the app and without AI:** a night
far below the usual for its weekday, an expense far above its usual, a
drawer difference that keeps coming back. Plain rules compare each figure
with its own recent history. Nothing leaves the PC, and each warning says
why it appeared.

## 10. When wanted

New, from the research. Each part is small, ships on its own, and waits
until Mohammed asks for it.

- **A PDF of every closed month**, saved by itself beside the backups when
  the month is closed: the printed month and its summary. With step 3's
  window, WebView2 prints the page straight to a file, in the same Kurdish
  as on screen. (Before, this was the suggestion "the month's report for
  the partners as a PDF".)
- **Comparisons:** each month beside the months before it (and, from next
  year, beside the same month a year earlier), and nights by weekday.
  Small charts drawn by the app itself, with no chart library.
- **A slip for each member of staff:** the month's salary, advances,
  repayments and what is left, printed the way a supplier's statement is.
- **Receipt photos:** a photo of a supplier's receipt, read by a vision
  model (Claude or Gemini) into the receipt form. Nothing is saved until
  Mohammed checks it and presses Save. It needs an API key, and the photo
  goes to the AI company.
- **Weighing straight into the count** through the Web Serial API, if a
  scale with a USB or serial port is bought. Check the model before buying.
- **FIB:** salaries paid by transfer from a FIB pot (2.8). Later, if wallet
  payments grow, the day's payments read from FIB's API, so the night's
  figure is checked against the bank, not typed.

## 11. Bug hunts, after every step

Each step ends with the hunt tools run again: crawls, every button, random
clicking, odd values sent to every action, random undo, two years of books,
and Hypothesis's long runs (1.3). New things to try:
- years of SambaPOS backups in the folder
- a slow PC (a throttled CPU)
- a full year of books shaped like the real ones
- the installed app (3): installing, updating, going back, and the `.bat`

## 12. Pure Kurdish words

Decided 19 Nov: the screens say things in pure Kurdish, not the everyday
market words (مەعاش, مەسرەف, مەندووب, قاصە and the like). Mohammed's
Gemini review of the translation suggested the pure words. The Kurdish is
his, through Gemini; Claude never writes it, and never changes it by
find-and-replace, because a word changes with its sentence.

12.1 **The word list.** A Gemini prompt lists each market word the screens
use, with every sentence that uses it. Gemini answers with the pure word
for each. Mohammed checks the list. It is then kept in the repository as
the glossary, each English term with its pure word, and every later Gemini
prompt carries it, so the same thing is always called the same thing.

12.2 **The sentences, in batches.** Prompts send each sentence that has one
of those words in English and in its current Kurdish, with the agreed word
list. Gemini returns the whole sentence rewritten, as JSON in a code block,
as before. Mohammed pastes it back.

12.3 **Merged and checked.**
- The tests hold: values, marks and spacing kept.
- Every sentence that had a market word now has its pure word.
- The crawls show no screen with a market word left.
- One version ships with all of it.

## Suggestions, only if wanted

- The app starts with Windows.
- **The books from a phone, read-only.** Mohammed opens the books only on
  this PC and wants no phone layouts; this stays here in case that
  changes. Tailscale Serve gives the PC an HTTPS address that only his own
  devices can open, while the app keeps listening on 127.0.0.1. The app
  would accept that one address, only with Tailscale's sign-in headers and
  only for the people he names. Never Tailscale Funnel, which opens a
  service to anyone. Installable on the phone, with a note at closing time
  by Web Push, which Apple's and Google's push services cannot read. Not a
  Telegram bot: its chats are not end-to-end encrypted.
- **A copy off-site:** the restic repository copied to Cloudflare R2, about
  $0.015 per GB a month. R2 only ever sees encrypted data, and with Object
  Lock not even ransomware on the PC could delete those copies.
- **A tamper-evident record of changes:** each line of Recent changes
  carries a fingerprint of the line before it, so an edit to the books file
  outside the app shows.
- **An export to Beancount**, so Fava can give the partners an independent
  view of the same books.
- Jules for light tasks such as docs and small clean-ups.

## Not planned, and why (from the research)

- The books in the cloud, or an online accounting service: the books would
  leave the PC and stop when the internet does.
- A rewrite in a framework (React, Svelte, Vue, htmx, Electron, FastAPI):
  what is there works.
- A ledger database (TigerBeetle) or a database server: built for volumes
  far beyond one lounge.
- Anything open to the internet: Tailscale Funnel, port forwarding.
- AI that saves entries by itself, or Kurdish that nobody checks.
- SambaPOS's API for changes, or anything near its licence.
- Forecasting stock with AI. Fingerprint clocks or shift apps: pay is
  monthly.
- Litestream: not supported on Windows yet.
- Free-threaded Python: nothing to gain for one user.

## Decided (19 Nov 2026)

1. The second copy goes on another drive in the PC (2.1).
2. Daily copies are made smaller (2.2): zipped at first, then, by the
   research the same day, with restic.
3. TwilightBooks is finished with, so its import is retired (4.2).
4. The stable channel goes ahead (1.4), through GitHub Releases.
5. The Month tab stays as it is (7.5).
6. Pure Kurdish words (12).
7. The plan follows the 2026 research: steps 3, 8, 9 and 10 are new.

Still open: which suggestions, if any, and when each part of step 10 is
wanted.
