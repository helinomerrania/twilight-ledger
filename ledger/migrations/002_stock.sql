-- 002_stock: what is on the shelves, what arrived, what it is worth.
--
-- Stock is the one thing that is not a cash movement. It is a count on a date,
-- valued at Setup prices, and the cost of goods for a month falls out of it:
-- opening + bought - closing. Counts are rows, not a blob, so a single item on
-- a single date can be corrected without rewriting the month.

CREATE TABLE stock_category (
  id     INTEGER PRIMARY KEY,
  letter TEXT NOT NULL UNIQUE CHECK (length(letter) = 1),
  name   TEXT NOT NULL,
  sort   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE stock_item (
  id          INTEGER PRIMARY KEY,
  name        TEXT    NOT NULL,
  category_id INTEGER NOT NULL REFERENCES stock_category(id),
  unit        TEXT    NOT NULL DEFAULT 'piece',  -- kg | piece | pack | litre
  price       INTEGER NOT NULL DEFAULT 0,        -- dinar per unit
  pack_size   INTEGER,                           -- pieces in a sealed package
  block_grams INTEGER,                           -- a sealed block, in grams
  active      INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0,1)),
  sort        INTEGER NOT NULL DEFAULT 0,
  UNIQUE (name, category_id)
);

-- Weighed tobacco comes in buckets; the bucket itself is not stock.
CREATE TABLE tare (
  id     INTEGER PRIMARY KEY,
  name   TEXT    NOT NULL UNIQUE,
  grams  INTEGER NOT NULL CHECK (grams >= 0)
);

-- Cartons to blocks, blocks to kilos, and so on.
CREATE TABLE conversion (
  id       INTEGER PRIMARY KEY,
  name     TEXT    NOT NULL UNIQUE,
  from_unit TEXT   NOT NULL,
  to_unit   TEXT   NOT NULL,
  factor_n INTEGER NOT NULL CHECK (factor_n > 0),   -- exact ratio, no floats
  factor_d INTEGER NOT NULL DEFAULT 1 CHECK (factor_d > 0)
);

CREATE TABLE stock_count (
  id         INTEGER PRIMARY KEY,
  count_date TEXT NOT NULL UNIQUE
             CHECK (count_date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  -- What the count was booked at. Stored rather than recomputed, so changing an
  -- item's price in Setup can never move a figure a finished month was built on.
  closing    INTEGER NOT NULL DEFAULT 0,
  source     TEXT NOT NULL DEFAULT 'counted'
             CHECK (source IN ('counted','carried')),   -- counted here, or
                                                        -- carried in from the
                                                        -- old Excel workbook
  note       TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

-- A counted line. Three slots, because sealed tobacco is genuinely counted at
-- three levels — cartons, then blocks, then loose packs — and squeezing that
-- into two would silently lose whichever one had nowhere to go.
--
--   category A (weighed)   gross_grams on the scales, less the bucket's tare
--   category B (sealed)    packages = cartons, blocks, loose = packs
--   category E (ice cream) packages = cartons, loose = buckets
--   everything else        packages = whole packages, loose = pieces
-- Counted amounts are held as thousandths, because Mohammed counts in
-- fractions: his 9 November sheet has 65.4 blocks of Fakher and 0.1 of a
-- packet of filters. Whole-number columns would quietly drop the .4 — 200
-- grams of tobacco — every time a line was saved.
CREATE TABLE stock_count_line (
  id            INTEGER PRIMARY KEY,
  count_id      INTEGER NOT NULL REFERENCES stock_count(id) ON DELETE CASCADE,
  item_id       INTEGER NOT NULL REFERENCES stock_item(id),
  packages_milli INTEGER NOT NULL DEFAULT 0,  -- largest unit  x 1000
  blocks_milli   INTEGER NOT NULL DEFAULT 0,  -- middle unit   x 1000 (sealed)
  loose_milli    INTEGER NOT NULL DEFAULT 0,  -- smallest unit x 1000
  gross_grams   INTEGER,                      -- the scale reads whole grams
  tare_id       INTEGER REFERENCES tare(id),
  -- the price this line was valued at. Stored, so changing an item's price in
  -- Setup can never reach back and move a count that has already been taken.
  price         INTEGER NOT NULL DEFAULT 0,
  -- what the line works out to, stored so a closed month cannot be moved by a
  -- later price change in Setup
  qty_milli     INTEGER NOT NULL DEFAULT 0,   -- quantity x 1000, keeps kg exact
  value         INTEGER NOT NULL DEFAULT 0,   -- whole dinar
  UNIQUE (count_id, item_id)
);

CREATE INDEX count_line_item ON stock_count_line(item_id);

CREATE TABLE receipt (
  id          INTEGER PRIMARY KEY,
  received_on TEXT    NOT NULL
              CHECK (received_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  supplier_id INTEGER NOT NULL REFERENCES account(id),
  number      TEXT,
  what        TEXT,
  amount      INTEGER NOT NULL CHECK (amount <> 0),
  terms       TEXT    NOT NULL DEFAULT 'credit' CHECK (terms IN ('credit','cash')),
  entry_id    INTEGER REFERENCES entry(id) ON DELETE SET NULL,
  created_at  TEXT    NOT NULL DEFAULT (datetime('now'))
);

CREATE INDEX receipt_day      ON receipt(received_on);
CREATE INDEX receipt_supplier ON receipt(supplier_id, received_on);

-- Counting the cash box. A count is a reading, never a correction: if it does
-- not tie, that is a fact about the night, recorded with a reason.
CREATE TABLE cash_count (
  id         INTEGER PRIMARY KEY,
  counted_on TEXT NOT NULL UNIQUE
             CHECK (counted_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  reason     TEXT,
  created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE cash_count_line (
  id         INTEGER PRIMARY KEY,
  count_id   INTEGER NOT NULL REFERENCES cash_count(id) ON DELETE CASCADE,
  account_id INTEGER NOT NULL REFERENCES account(id),
  counted    INTEGER NOT NULL,
  UNIQUE (count_id, account_id)
);

-- Electricity is metered, not billed as a flat line.
CREATE TABLE meter_reading (
  id       INTEGER PRIMARY KEY,
  read_on  TEXT    NOT NULL UNIQUE
           CHECK (read_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  units    INTEGER NOT NULL,            -- meter face, amperes or kWh
  rate     INTEGER NOT NULL DEFAULT 0,  -- dinar per unit
  note     TEXT
);
