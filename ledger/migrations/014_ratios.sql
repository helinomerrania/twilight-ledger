-- Things used with each hookah — foil, coal, filters — and so used up by a
-- ratio learnt between counts rather than by a recipe.
ALTER TABLE stock_item ADD COLUMN per_hookah INTEGER NOT NULL DEFAULT 0
  CHECK (per_hookah IN (0, 1));
