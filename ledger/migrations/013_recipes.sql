-- What each order took off the shelves, by SambaPOS's own recipes.

-- Which menu item an order was, by SambaPOS's number (its name can change),
-- and whether it took stock: a void does not, a gift does. Orders kept before
-- this say neither; for them a charged order is taken to have used stock.
ALTER TABLE pos_order ADD COLUMN menu_id INTEGER;
ALTER TABLE pos_order ADD COLUMN used INTEGER CHECK (used IN (0, 1));

-- Which stock item each of SambaPOS's inventory items is here, and how many
-- of SambaPOS's units make one of ours: 1000 grams to a kilo of tobacco, 24
-- cans to a package of 24. NULL works it out from the units.
CREATE TABLE pos_stock_link (
  pos_id   INTEGER PRIMARY KEY,                        -- InventoryItems.Id
  item_id  INTEGER REFERENCES stock_item(id) ON DELETE SET NULL,
  per      INTEGER CHECK (per IS NULL OR per > 0)
);
