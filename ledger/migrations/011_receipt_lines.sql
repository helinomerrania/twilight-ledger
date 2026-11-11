-- What a supplier receipt brought in, line by line.
--
-- Only the receipt's total moves money, as before. A line says what came onto
-- the shelves: the stock it adds (expected stock, at the next count) and what
-- each item really cost. Quantities are kept as typed, in the boxes the item
-- comes in, and as the item's own quantity worked out when the line was
-- saved: kilos for tobacco, cartons for ice cream, packages for the rest. The
-- amount is what the invoice charges for the line, when it says.
--
-- A line belongs to the receipt row, so it is deleted with the receipt and
-- comes back with it; a corrected receipt takes its lines along.
CREATE TABLE receipt_line (
  id             INTEGER PRIMARY KEY,
  receipt_id     INTEGER NOT NULL REFERENCES receipt(id) ON DELETE CASCADE,
  item_id        INTEGER NOT NULL REFERENCES stock_item(id),
  packages_milli INTEGER NOT NULL DEFAULT 0,
  blocks_milli   INTEGER NOT NULL DEFAULT 0,
  loose_milli    INTEGER NOT NULL DEFAULT 0,
  qty_milli      INTEGER NOT NULL CHECK (qty_milli > 0),
  amount         INTEGER CHECK (amount IS NULL OR amount >= 0),
  UNIQUE (receipt_id, item_id)
);

CREATE INDEX receipt_line_item ON receipt_line(item_id);
