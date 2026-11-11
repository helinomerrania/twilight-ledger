-- SambaPOS's own accounts, and what each one is in the books.
--
-- SambaPOS records an expense, a staff advance or an owner taking cash the same
-- way: money moved from the drawer to one of its accounts. Which of those it
-- was depends on the account, so each account is linked once to what it is in
-- the books. An account is known by SambaPOS's number for it (Accounts.Id),
-- never by its name: renaming it in SambaPOS changes nothing here but the name
-- shown. The nightly reset deletes transactions, not accounts, so the number
-- stays.

-- The accounts as SambaPOS's newest snapshot lists them.
CREATE TABLE pos_account (
  pos_id     INTEGER PRIMARY KEY,            -- Accounts.Id
  name       TEXT    NOT NULL,               -- what SambaPOS calls it now
  type_id    INTEGER,
  type_name  TEXT,
  seen_at    TEXT    NOT NULL,               -- the newest snapshot that listed it
  gone       INTEGER NOT NULL DEFAULT 0 CHECK (gone IN (0, 1))
);

-- What each one is in the books.
CREATE TABLE pos_link (
  pos_id      INTEGER PRIMARY KEY,           -- Accounts.Id
  as_what     TEXT    NOT NULL CHECK (as_what IN
                ('expense', 'income', 'staff', 'partner', 'supplier', 'pot', 'ignore')),
  account_id  INTEGER REFERENCES account(id), -- the person, supplier or pot
  detail      TEXT,                          -- the expense or income, as the books name it
  name_then   TEXT    NOT NULL,              -- SambaPOS's name for it when it was linked
  linked_at   TEXT    NOT NULL DEFAULT (datetime('now')),
  told        INTEGER NOT NULL DEFAULT 0 CHECK (told IN (0, 1)),
                                             -- 1: Mohammed was reminded to remove it
  CHECK ((as_what IN ('staff', 'partner', 'supplier', 'pot')) = (account_id IS NOT NULL)),
  CHECK ((as_what IN ('expense', 'income')) = (detail IS NOT NULL))
);
