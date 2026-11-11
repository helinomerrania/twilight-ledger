-- What SambaPOS recorded besides tickets: expenses, staff and owner advances,
-- money paid into or out of the drawer. SambaPOS keeps each as a document that
-- moves an amount between its own accounts; one row here per document, and
-- one per account it touched. Kept as SambaPOS wrote it: what each SambaPOS
-- account means in the books is decided separately.

CREATE TABLE pos_doc (
  id         INTEGER PRIMARY KEY,
  period_id  INTEGER NOT NULL REFERENCES pos_period(id) ON DELETE CASCADE,
  pos_id     INTEGER NOT NULL,           -- AccountTransactionDocuments.Id
  at         TEXT NOT NULL,
  kind       TEXT,                       -- the button or document type that made it
  name       TEXT,
  user_name  TEXT,
  UNIQUE (period_id, pos_id)
);

CREATE TABLE pos_doc_line (
  id           INTEGER PRIMARY KEY,
  doc_id       INTEGER NOT NULL REFERENCES pos_doc(id) ON DELETE CASCADE,
  pos_id       INTEGER NOT NULL,         -- AccountTransactionValues.Id
  account_id   INTEGER,                  -- Accounts.Id in SambaPOS
  account      TEXT NOT NULL,
  account_type TEXT,
  amount       INTEGER NOT NULL,         -- debit less credit, whole dinar
  drawer       INTEGER NOT NULL DEFAULT 0, -- 1 for the account ticket payments go into
  reversed     INTEGER NOT NULL DEFAULT 0, -- 1 if SambaPOS reversed it afterwards
  UNIQUE (doc_id, pos_id)
);

ALTER TABLE pos_period ADD COLUMN docs INTEGER NOT NULL DEFAULT 0;
