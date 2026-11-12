-- The screens in Kurdish. Each piece of English on the screens, with what
-- changes in it taken out as {0}, {1}…, and its Kurdish once Mohammed has made
-- it with Gemini (Setup → Language). Pieces the screens show that have no
-- Kurdish yet are added here as they are seen, so the next prompt asks for
-- them. The Kurdish is Mohammed's own: it lives in the books, never in the
-- app's code.
CREATE TABLE lang_text (
  key      TEXT PRIMARY KEY,
  ckb      TEXT,
  seen_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
