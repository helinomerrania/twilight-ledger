-- More of what SambaPOS knows, kept from now on so that the history is there
-- by the time later steps need it.

-- Who opened and who closed each work period.
ALTER TABLE pos_period ADD COLUMN opened_by TEXT;
ALTER TABLE pos_period ADD COLUMN closed_by TEXT;

-- Which payment type each payment was: cash, card, transfer, credit.
ALTER TABLE pos_payment ADD COLUMN type_id INTEGER;   -- PaymentTypes.Id

-- SambaPOS's own lists, as its newest snapshot has them: payment types, the
-- menu with its portions and prices, inventory items, recipes. The nightly
-- reset leaves these alone, so each read simply brings them up to date. Each
-- row is kept as SambaPOS wrote it until a later step needs a shape of its
-- own. SambaPOS's users are never read: that table holds passwords and PINs.
CREATE TABLE pos_catalog (
  id       INTEGER PRIMARY KEY,
  kind     TEXT    NOT NULL,        -- 'payment_type', 'menu_item', 'recipe', ...
  pos_id   INTEGER NOT NULL,        -- its Id in SambaPOS
  name     TEXT,
  data     TEXT    NOT NULL,        -- the row, as JSON
  seen_at  TEXT    NOT NULL,        -- the newest snapshot that had it
  gone     INTEGER NOT NULL DEFAULT 0 CHECK (gone IN (0, 1)),
  UNIQUE (kind, pos_id)
);
