-- A copy of what SambaPOS recorded, kept before the nightly reset deletes it.
--
-- This is an archive, not the books: nothing here is money until a night's
-- takings are used as that night's sales, which posts an ordinary entry.
-- Amounts are whole dinar, quantities thousandths, times local and ISO.

CREATE TABLE pos_period (
  id          INTEGER PRIMARY KEY,
  pos_id      INTEGER NOT NULL,          -- WorkPeriods.Id in SambaPOS
  started_at  TEXT NOT NULL,             -- WorkPeriods.StartDate
  ended_at    TEXT,                      -- NULL while the period was still open
  night       TEXT NOT NULL,             -- the business night it belongs to
  tickets     INTEGER NOT NULL DEFAULT 0,
  total       INTEGER NOT NULL DEFAULT 0,   -- what the tickets came to
  takings     INTEGER NOT NULL DEFAULT 0,   -- what was paid
  unpaid      INTEGER NOT NULL DEFAULT 0,   -- still owed on open tickets
  first_at    TEXT,
  last_at     TEXT,
  seen_to     TEXT NOT NULL,             -- the latest moment this copy shows
  source      TEXT NOT NULL,             -- 'backup:<file>' or 'live:<database>'
  kept_at     TEXT NOT NULL DEFAULT (datetime('now')),
  UNIQUE (pos_id, started_at)
);

CREATE INDEX pos_period_night ON pos_period(night);

CREATE TABLE pos_ticket (
  id         INTEGER PRIMARY KEY,
  period_id  INTEGER NOT NULL REFERENCES pos_period(id) ON DELETE CASCADE,
  pos_id     INTEGER NOT NULL,           -- Tickets.Id
  number     TEXT,
  opened_at  TEXT NOT NULL,
  paid_at    TEXT,
  total      INTEGER NOT NULL,
  unpaid     INTEGER NOT NULL,
  closed     INTEGER NOT NULL,
  tables     TEXT,                       -- the table or customer it was for
  note       TEXT,
  UNIQUE (period_id, pos_id)
);

CREATE TABLE pos_order (
  id         INTEGER PRIMARY KEY,
  ticket_id  INTEGER NOT NULL REFERENCES pos_ticket(id) ON DELETE CASCADE,
  pos_id     INTEGER NOT NULL,           -- Orders.Id
  item       TEXT NOT NULL,
  portion    TEXT,
  item_group TEXT,
  qty_milli  INTEGER NOT NULL,
  price      INTEGER NOT NULL,           -- for one
  counted    INTEGER NOT NULL,           -- 0 when it was not charged for
  ordered_at TEXT,
  UNIQUE (ticket_id, pos_id)
);

CREATE INDEX pos_order_item ON pos_order(item);

CREATE TABLE pos_payment (
  id         INTEGER PRIMARY KEY,
  ticket_id  INTEGER NOT NULL REFERENCES pos_ticket(id) ON DELETE CASCADE,
  pos_id     INTEGER NOT NULL,           -- Payments.Id
  kind       TEXT NOT NULL,              -- Cash, or whatever else was set up
  amount     INTEGER NOT NULL,
  paid_at    TEXT,
  UNIQUE (ticket_id, pos_id)
);

CREATE TABLE pos_calc (
  id         INTEGER PRIMARY KEY,
  ticket_id  INTEGER NOT NULL REFERENCES pos_ticket(id) ON DELETE CASCADE,
  pos_id     INTEGER NOT NULL,           -- Calculations.Id
  name       TEXT,
  amount     INTEGER NOT NULL,           -- negative for a discount
  UNIQUE (ticket_id, pos_id)
);
