-- Stock items as they really come in.

-- A flavour belongs to its brand. The brand is the item that was counted
-- before there were flavours, so old counts stay per brand and new ones are
-- per flavour. A flavour's price and packs are its brand's unless it has its
-- own.
ALTER TABLE stock_item ADD COLUMN parent_id INTEGER REFERENCES stock_item(id);

-- How a sealed tobacco comes, when it is not the usual packs, blocks and
-- cartons set in Setup: {"grams": 1000, "per_block": 3, "per_carton": null}
-- is 1 kg bags in boxes of 3. NULL means the usual.
ALTER TABLE stock_item ADD COLUMN packs TEXT;

-- Below this much, Tonight will warn. In the item's own quantity, x 1000:
-- kilos for tobacco, packages for the rest.
ALTER TABLE stock_item ADD COLUMN minimum_milli INTEGER;

-- One or more barcodes per item. A scanner types the code like a keyboard.
CREATE TABLE stock_barcode (
  code     TEXT PRIMARY KEY,
  item_id  INTEGER NOT NULL REFERENCES stock_item(id) ON DELETE CASCADE
);

CREATE INDEX stock_barcode_item ON stock_barcode(item_id);
