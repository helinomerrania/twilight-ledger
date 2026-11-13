-- Never used. Stock conversions are kept in the "conversions" setting, where
-- Setup saves them, and no stock item was ever given a block weight.
DROP TABLE IF EXISTS conversion;
ALTER TABLE stock_item DROP COLUMN block_grams;
