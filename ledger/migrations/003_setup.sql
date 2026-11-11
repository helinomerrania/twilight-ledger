-- 003_setup: the lists Mohammed maintains, and the app's own bookkeeping.
--
-- The old app kept these in a `setup` object alongside the data, which meant
-- changing a price could move a figure in a month that was supposed to be
-- finished. Here Setup is reference data, and anything a closed month needs is
-- copied into the month's own rows at the time (see stock_count_line.value).

CREATE TABLE settings (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL              -- JSON
);

-- Daily expense categories, cash-difference reasons, and the like: short
-- editable lists that drive the pickers on the night screen.
CREATE TABLE pick_list (
  id    INTEGER PRIMARY KEY,
  list  TEXT    NOT NULL,          -- 'expense', 'reason', 'income', 'bill'
  value TEXT    NOT NULL,
  sort  INTEGER NOT NULL DEFAULT 0,
  active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  UNIQUE (list, value)
);

CREATE INDEX pick_list_list ON pick_list(list, active, sort);

-- Rent and anything else charged to every month whether or not it is paid.
CREATE TABLE fixed_charge (
  id         INTEGER PRIMARY KEY,
  name       TEXT    NOT NULL UNIQUE,
  amount     INTEGER NOT NULL,
  account_id INTEGER NOT NULL REFERENCES account(id),
  from_month TEXT,                 -- charge it from this month on
  to_month   TEXT,                 -- and stop after this one
  active     INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1))
);

-- Salaries change; a month must be able to say what the salary was then.
CREATE TABLE salary (
  id         INTEGER PRIMARY KEY,
  account_id INTEGER NOT NULL REFERENCES account(id),
  amount     INTEGER NOT NULL,
  from_month TEXT    NOT NULL
             CHECK (from_month GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]'),
  UNIQUE (account_id, from_month)
);

-- Everything that has been changed, so a wrong figure can always be traced.
CREATE TABLE audit (
  id        INTEGER PRIMARY KEY,
  at        TEXT NOT NULL DEFAULT (datetime('now')),
  action    TEXT NOT NULL,         -- 'entry.add', 'period.close', 'import'
  subject   TEXT,                  -- table and id it touched
  detail    TEXT                   -- JSON: what changed
);

CREATE INDEX audit_at ON audit(at DESC);
