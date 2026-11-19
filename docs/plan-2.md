# The second plan: ready for real use

The first plan (`docs/plan.md`) is finished. What it left undone stays undone,
as Mohammed decided on 19 Nov 2026. This plan is about the app itself rather
than new features: make it safe to rely on every night, take out what is not
used, split the long files, and make the parts that are fragile simpler.

Each step stands on its own and ships as its own version, like before. Read
`docs/design.md` first. The rules in `docs/plan.md` still hold: nothing from
the real books in this public repository, the app listens on 127.0.0.1 only,
SambaPOS is only ever read, `Start Twilight Ledger.bat` never changes, and
Kurdish comes from Mohammed's Gemini prompts, never from Claude.

**Status:** ✅ done · ▶ next · ○ later · ? waiting for a decision

| | Step |
|---|---|
| ▶ | 1. A safety net first |
| ○ | 2. Ready for real use |
| ○ | 3. Clean-up |
| ○ | 4. Smaller files |
| ○ | 5. Simpler architecture |
| ○ | 6. The screens |
| ○ | 7. Bug hunts, after every step |
| ○ | 8. Pure Kurdish words (can run alongside any step) |

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

1.1 **Checks on GitHub.** Every push runs the tests, the lint and the
browser checks. If the checks fail, there is no new version.

1.2 **The browser checks in the repository**, under `tests/browser/`.
They are the tools from the bug hunts, which so far live only in Claude's
workspace:
- every screen in both languages: no script errors, no English left
- every button pressed once
- random clicking
- a page left open overnight and into a new month
- the update itself

They need Node and Playwright, but only on the machine running the checks,
never on the PC.

1.3 **A stable channel** (agreed 19 Nov). The app updates from a `stable`
branch instead of `main`, and `stable` moves only when the checks pass. The
first version that reads `stable` is shipped through `main` as usual.

1.4 **Go back a version.** Setup → This app gets a button that puts the
previous version back. Its code is already kept, zipped, at every update.

1.5 **Lock the GitHub account** (Mohammed): two-step sign-in, and nobody
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
  the building (a USB stick taken home, or a cloud folder) would cover
  those, and is not planned.

2.2 **Smaller copies** (decided 19 Nov: yes). Zip the daily copy: nothing
deleted, just 3.6 times smaller.
- Old copies already made stay as they are.
- Restore and "Check this copy" (2.3) read both kinds.
- Deleting old copies would need Mohammed's decision, and is not planned.

2.3 **Restore in the app.** Setup → Backups gets two things. "Check this
copy" opens it read-only and checks it. "Restore" saves the books first,
then restores. Today a restore needs the black window.

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

2.7 **Power** (a recommendation, not code). A small UPS for the PC and the
router. The books are written safely (synchronous = FULL), but every power
cut is still a hard stop.

## 3. Clean-up

3.1 **Remove the unused code** from the survey, and the `lang_text`
fallback with the `kept` path in `i18n.js`. First check on the PC that
nothing on its screens still uses it.

3.2 **Retire the old-books migration** (decided 19 Nov: TwilightBooks is
finished with). What goes:
- `tools/import_json.py`, `tools/verify.py` and the `import` and `verify`
  commands in `twilight.py`
- their tests, and the import-and-verify gate run before each push

`tools/privacy_scan.py` stays, because the repository is still public. It
takes the arithmetic it needs from `tools/oracle.py` (the class `Old`),
which moves into the scan or stays for it alone. Git keeps the rest.

3.3 **Each action says what it takes**: its fields, their types, which are
needed. The registry checks a body against that before the action runs.
The 216 fuzz crashes become plain refusals, and the inputs are written down
in one place.

3.4 **Fix the remaining lint notes**, and archive `docs/plan.md`.

## 4. Smaller files

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
  clock, formatting. Still plain files with no build step.
- `ledger/queries.py` → `ledger/queries/` by subject: entries, cash, the
  month's figures, suppliers, stock.
- `ledger/actions.py` and `ledger/setup.py` → by subject.
- The state in `ledger/api.py` → one part per page, which prepares 5.2.

## 5. Simpler architecture

5.1 **The server speaks the screens' language.** A message carries its
sentence name and values, and the page says it in English or Kurdish.
Recent changes store the name and values too. `i18n.js` shrinks to a
fallback for changes recorded before this.

5.2 **Smaller answers.** Send what every page needs, plus each page's own
part when it is opened. Long histories go by the month, with "show older".
Saves get faster, and stay fast as the years add up.

5.3 **List SambaPOS's backup folder once a minute**, not on every screen
load. At 747 files it takes 17 ms here, and more on Windows.

5.4 **Log slow requests**: anything over a second, with what it was. Then
slowness on the PC shows up in the problem report.

## 6. The screens

6.1 **A minimal design pass**, page by page, Kurdish first. Before and
after screenshots go to Mohammed for approval. The direction:
- fewer boxes and lines
- one accent colour
- quieter banners
- the same spacing everywhere

6.2 **Keyboard.** Enter saves, Esc closes a question, and the cursor goes
to where the next entry is typed.

6.3 **Retiring a pot that is below zero.** It says "Move it out first",
which makes no sense for a pot below zero. It needs one new sentence, so a
Gemini prompt.

6.4 ✅ **The Month tab at the end of a month** (decided 19 Nov: as now). A
page left open keeps the old month until it is reloaded, which is handy for
closing that month. Nothing to do.

## 7. Bug hunts, after every step

Each step ends with the hunt tools run again: crawls, every button, random
clicking, odd values sent to every action, random undo, two years of books.
New things to try:
- years of SambaPOS backups in the folder
- a slow PC (a throttled CPU)
- a full year of books shaped like the real ones

## 8. Pure Kurdish words

Decided 19 Nov: the screens say things in pure Kurdish, not the everyday
market words (مەعاش, مەسرەف, مەندووب, قاصە and the like). Mohammed's
Gemini review of the translation suggested the pure words. The Kurdish is
his, through Gemini; Claude never writes it, and never changes it by
find-and-replace, because a word changes with its sentence.

8.1 **The word list.** A Gemini prompt lists each market word the screens
use, with every sentence that uses it. Gemini answers with the pure word
for each. Mohammed checks the list.

8.2 **The sentences, in batches.** Prompts send each sentence that has one
of those words in English and in its current Kurdish, with the agreed word
list. Gemini returns the whole sentence rewritten, as JSON in a code block,
as before. Mohammed pastes it back.

8.3 **Merged and checked.**
- The tests hold: values, marks and spacing kept.
- Every sentence that had a market word now has its pure word.
- The crawls show no screen with a market word left.
- One version ships with all of it.

## Suggestions, only if wanted

- The app starts with Windows.
- The books from a phone over Tailscale, read-only. Tailscale addresses
  only, never the open internet.
- The month's report for the partners as a PDF.
- Jules for light tasks such as docs and small clean-ups.

## Decided (19 Nov 2026)

1. The second copy goes on another drive in the PC (2.1).
2. Daily copies are zipped (2.2).
3. TwilightBooks is finished with, so its import is retired (3.2).
4. The stable channel goes ahead (1.3).
5. The Month tab stays as it is (6.4).
6. Pure Kurdish words (8).

Still open: which suggestions, if any.
