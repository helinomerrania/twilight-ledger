-- 004_corrections: what is needed to correct an entry rather than only delete it.
--
-- An entry is never edited in place. Correcting one voids the original and
-- writes a new one, and `replaced_by` joins the two so the record can say
-- "this was changed into that" instead of showing an unexplained deletion
-- beside an unexplained addition. It also stops a replaced entry being put
-- back, which would count the same money twice.

ALTER TABLE entry ADD COLUMN replaced_by INTEGER REFERENCES entry(id);

-- A supplier receipt lives in two places: the entry that moves the money and
-- the receipt row the stock figures read. Deleting the entry used to leave the
-- receipt behind, still counted as bought. The receipt is now voided with it,
-- and comes back with it if the entry is put back.

ALTER TABLE receipt ADD COLUMN voided_at TEXT;

-- Which supplier an item comes from, so a supplier's statement can say how
-- much of what is owed is still sitting on the shelves.

ALTER TABLE stock_item ADD COLUMN supplier_id INTEGER REFERENCES account(id);
