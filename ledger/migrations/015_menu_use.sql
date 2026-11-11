-- What each menu item takes off the shelves is set here, menu item by menu
-- item. SambaPOS's own recipes were only ever tried out, so they are not used,
-- and nor is the link from SambaPOS's inventory items that went with them.
DROP TABLE pos_stock_link;

CREATE TABLE menu_use (
  menu_id       INTEGER PRIMARY KEY,         -- SambaPOS's menu item number
  item_id       INTEGER REFERENCES stock_item(id) ON DELETE CASCADE,
                                             -- NULL: it takes nothing
  amount_milli  INTEGER NOT NULL DEFAULT 1000 CHECK (amount_milli > 0)
                                             -- heads of tobacco, buckets of
                                             -- ice cream, pieces of the rest
);
