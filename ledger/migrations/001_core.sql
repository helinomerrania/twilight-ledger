-- 001_core: accounts, entries and balanced postings.
--
-- The whole design rests on one rule: money only ever moves as a set of
-- postings that sum to zero. There is no "amount" column on a transaction and
-- no in/out pair to interpret. If 5,000 dinar leaves the Box for tea, that is
-- +5,000 on the tea expense account and -5,000 on the Box, and the two must
-- cancel. Cash on hand is then one SUM over the cash accounts, and what a
-- supplier is owed is one SUM over that supplier's account. Nothing computes
-- its own private version of the truth.
--
-- Sign convention: amount is positive for a debit, negative for a credit.
--   cash, inventory, expense accounts    debit-normal   (+ means more)
--   supplier, staff, partner, revenue    credit-normal  (- means more owed)
-- account.normal carries the direction so a screen can show a positive number
-- without every query remembering which way round the account sits.

CREATE TABLE account (
  id        INTEGER PRIMARY KEY,
  code      TEXT    NOT NULL UNIQUE,            -- 'cash:box', 'sup:zhule-store'
  name      TEXT    NOT NULL,
  kind      TEXT    NOT NULL
            CHECK (kind IN ('cash','float','supplier','staff','partner',
                            'revenue','expense','inventory','accrual')),
  normal    INTEGER NOT NULL CHECK (normal IN (1,-1)),
  active    INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  sort      INTEGER NOT NULL DEFAULT 0,
  meta      TEXT    NOT NULL DEFAULT '{}'       -- JSON: share, salary, terms
);

CREATE INDEX account_kind ON account(kind, active, sort);

-- A month of trading. Entries point at one, which is what finally fixes the
-- bug where paying October's salaries in November landed in November: the
-- cash moves on happened_on, the obligation belongs to period.
CREATE TABLE period (
  month      TEXT PRIMARY KEY                   -- '2026-10'
             CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
  status     TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open','closed')),
  closed_at  TEXT,
  count_date TEXT,                              -- the stock count it closed on
  result     TEXT,                              -- JSON, frozen at close
  CHECK (status = 'open' OR closed_at IS NOT NULL)
);

CREATE TABLE entry (
  id          INTEGER PRIMARY KEY,
  happened_on TEXT    NOT NULL                  -- the day the cash moved
              CHECK (happened_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  period      TEXT    NOT NULL REFERENCES period(month),
  kind        TEXT    NOT NULL,                 -- 'daily_sales', 'rent', ...
  detail      TEXT,                             -- category, person or supplier
  memo        TEXT,
  source      TEXT    NOT NULL DEFAULT 'manual'
              CHECK (source IN ('manual','import','pos','close')),
  source_ref  TEXT,                             -- POS ticket id, import row id
  created_at  TEXT    NOT NULL DEFAULT (datetime('now')),
  voided_at   TEXT                              -- soft delete; postings stay
);

CREATE INDEX entry_day    ON entry(happened_on);
CREATE INDEX entry_period ON entry(period, kind);
CREATE INDEX entry_kind   ON entry(kind, detail);
CREATE UNIQUE INDEX entry_pos_once ON entry(source, source_ref)
  WHERE source = 'pos' AND source_ref IS NOT NULL;

CREATE TABLE posting (
  id         INTEGER PRIMARY KEY,
  entry_id   INTEGER NOT NULL REFERENCES entry(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES account(id),
  amount     INTEGER NOT NULL CHECK (amount <> 0)   -- whole dinar, + debit
);

CREATE INDEX posting_entry   ON posting(entry_id);
CREATE INDEX posting_account ON posting(account_id);

-- The guard. Any entry whose postings do not cancel shows up here, and the
-- server refuses to start while this view returns a row. A corrupt ledger
-- should stop the app, not quietly show a wrong total.
CREATE VIEW unbalanced AS
  SELECT e.id AS entry_id, e.happened_on, e.kind, SUM(p.amount) AS out_by
    FROM entry e JOIN posting p ON p.entry_id = e.id
   GROUP BY e.id
  HAVING SUM(p.amount) <> 0;

-- Every live posting with the things a query always needs beside it.
CREATE VIEW movement AS
  SELECT p.id, p.entry_id, p.account_id, p.amount,
         a.code, a.name AS account, a.kind, a.normal,
         e.happened_on, e.period, e.kind AS entry_kind, e.detail, e.memo
    FROM posting p
    JOIN entry   e ON e.id = p.entry_id
    JOIN account a ON a.id = p.account_id
   WHERE e.voided_at IS NULL;
