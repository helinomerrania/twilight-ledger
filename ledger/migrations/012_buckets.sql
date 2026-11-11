-- Filling a bucket: packs of sealed tobacco go into one of the house mixes.
--
-- A stock move, not money: nothing is posted. The packs come off their
-- tobacco and their weight goes into the mix at what it cost, and the mix's
-- price per kilo follows, blended with what was already in the bucket when
-- the full bucket was weighed.

-- The usual batch of each mix, in packs of each tobacco.
CREATE TABLE mix_usual (
  mix_id       INTEGER NOT NULL REFERENCES stock_item(id) ON DELETE CASCADE,
  item_id      INTEGER NOT NULL REFERENCES stock_item(id) ON DELETE CASCADE,
  packs_milli  INTEGER NOT NULL CHECK (packs_milli > 0),
  sort         INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (mix_id, item_id)
);

CREATE TABLE bucket_fill (
  id            INTEGER PRIMARY KEY,
  mix_id        INTEGER NOT NULL REFERENCES stock_item(id),
  filled_on     TEXT    NOT NULL
                CHECK (filled_on GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
  grams         INTEGER NOT NULL CHECK (grams > 0),      -- what went in
  value         INTEGER NOT NULL CHECK (value >= 0),     -- what it cost
  net_grams     INTEGER,             -- the full bucket, less the bucket, when weighed
  price_before  INTEGER NOT NULL,    -- the mix's price per kilo before and after
  price_after   INTEGER NOT NULL,
  created_at    TEXT    NOT NULL DEFAULT (datetime('now')),
  voided_at     TEXT
);

CREATE INDEX bucket_fill_mix ON bucket_fill(mix_id, filled_on);

CREATE TABLE bucket_fill_line (
  fill_id      INTEGER NOT NULL REFERENCES bucket_fill(id) ON DELETE CASCADE,
  item_id      INTEGER NOT NULL REFERENCES stock_item(id),
  packs_milli  INTEGER NOT NULL CHECK (packs_milli > 0),
  grams        INTEGER NOT NULL CHECK (grams > 0),
  price        INTEGER NOT NULL,     -- per kilo, when it went in
  value        INTEGER NOT NULL,
  PRIMARY KEY (fill_id, item_id)
);

CREATE INDEX bucket_fill_line_item ON bucket_fill_line(item_id);
