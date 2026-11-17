"""The screens in Kurdish (Later in the plan). The Kurdish comes from
Mohammed through Gemini and lives in the books; the stand-ins here are made
up. Nothing in Kurdish may be written in the app's code."""
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

from ledger import api, db, lang, queries, words
from tests.helpers import fresh_books

ROOT = Path(__file__).resolve().parent.parent


def kurdish_letters(text):
    return [c for c in text if unicodedata.category(c).startswith("L")
            and "ARABIC" in unicodedata.name(c, "")]


class Pieces(unittest.TestCase):
    def setUp(self):
        self.con = fresh_books()

    def seen(self, *keys):
        with db.tx(self.con):
            return lang.seen(self.con, list(keys))

    def save(self, pairs):
        return api.run(self.con, "lang_set", {"pairs": pairs})

    def test_what_the_screens_show_is_kept_to_ask_for(self):
        self.assertEqual(self.seen("Save", "Filled {0}: {1} g", "Save"), 2)
        self.assertEqual(self.seen("Save"), 0)
        self.assertEqual(lang.todo(self.con)[-2:], ["Save", "Filled {0}: {1} g"])

    def test_nothing_without_words_is_kept(self):
        self.seen("{0}", "", "12,000", "x" * 401, None, 7)
        self.assertEqual(db.scalar(self.con, "SELECT COUNT(*) FROM lang_text "
                                             "WHERE key IN ('{0}', '', '12,000')"), 0)

    def test_saving_kurdish(self):
        self.seen("Save", "Filled {0}: {1} g")
        out = self.save({"Save": "  [save]  ", "Filled {0}: {1} g": "[{1} g {0}]"})
        self.assertEqual((out["saved"], out["wrong_count"]), (2, 0))
        self.assertEqual(lang.texts(self.con), {"Save": "[save]", "Filled {0}: {1} g": "[{1} g {0}]"})
        self.assertNotIn("Save", lang.todo(self.con))

    def test_a_translation_that_loses_a_value_is_left_out(self):
        out = self.save({"Filled {0}: {1} g": "[filled {0}]", "Paid {0}": "[{0} {0}]",
                         "Owed {0}": "[{1}]"})
        self.assertEqual((out["saved"], out["wrong_count"]), (0, 3))
        self.assertEqual(lang.texts(self.con), {})

    def test_empty_kurdish_takes_a_piece_back_to_english(self):
        self.save({"Filled {0}: {1} g": "[{0} {1}]"})
        self.assertEqual(self.save({"Filled {0}: {1} g": ""})["saved"], 1)
        self.assertEqual(lang.texts(self.con), {})
        self.assertIn("Filled {0}: {1} g", lang.todo(self.con))

    def test_each_save_tells_the_screens_to_fetch_the_kurdish_again(self):
        before = lang.view(self.con)["version"]
        self.save({"Save": "[save]"})
        self.assertEqual(lang.view(self.con)["version"], before + 1)

    def test_it_is_in_recent_changes(self):
        self.save({"Save": "[save]", "Cancel": "[cancel]"})
        self.assertIn("Kurdish saved for 2 pieces of text", queries.recent(self.con)[0]["summary"])

    def test_choosing_the_language(self):
        self.assertEqual(api.state(self.con)["lang"]["language"], "en")
        api.run(self.con, "language_set", {"language": "ckb"})
        v = api.state(self.con)["lang"]
        self.assertEqual(v["language"], "ckb")
        self.assertEqual(set(v["languages"]), {"en", "ckb"})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "language_set", {"language": "fr"})

    def test_the_screens_are_told_how_far_it_has_got(self):
        self.seen("Save", "Cancel", "Back")
        self.save({"Save": "[save]"})
        v = lang.view(self.con)
        self.assertEqual(v["done"], 1)
        self.assertGreaterEqual(v["todo"], 2)

    def test_the_next_batch_is_the_longest_waiting_first(self):
        self.seen(*[f"Piece {n}" if n else "Piece" for n in range(3)])
        self.assertEqual(lang.todo(self.con, 400)[-3:], ["Piece", "Piece 1", "Piece 2"])
        self.assertEqual(len(lang.todo(self.con, 2)), 2)


class Shipped(unittest.TestCase):
    """The app's own words are put in the books as pieces once per version of
    them, so Gemini can be asked for all of it before any screen has shown it."""

    def setUp(self):
        self.con = fresh_books()
        lang._shipped = None

    def tearDown(self):
        lang._shipped = None

    def ship(self, more=None):
        lang._shipped = None
        with mock.patch.object(lang, "words", lambda: {**words.words(), **(more or {})}):
            lang.view(self.con)

    def test_the_words_are_added_once(self):
        self.ship()
        self.assertIn("Closing up", lang.todo(self.con, 5000))
        db.set_setting(self.con, "language", "en")
        self.con.execute("DELETE FROM lang_text")
        self.ship()                                         # the same words: not again
        self.assertEqual(lang.todo(self.con), [])

    def test_a_new_version_adds_what_is_new(self):
        self.ship()
        api.run(self.con, "lang_set", {"pairs": {"Closing up": "[closing]"}})
        before = set(lang.todo(self.con, 5000))
        self.ship({"test.new": "Count the spoons on {0}"})
        self.assertEqual(set(lang.todo(self.con, 5000)) - before, {"Count the spoons on {0}"})
        self.assertEqual(lang.texts(self.con), {"Closing up": "[closing]"})

    def test_each_is_the_piece_the_screens_look_up(self):
        p = lang._pattern(words.words())
        self.assertEqual(lang.key_of("Use SambaPOS's figure in step 1, then {0}.", p),
                         "Use SambaPOS's figure in step {0}, then {1}.")
        self.assertEqual(lang.key_of("Closed 2026-11-17 at 07:26, out by -1,250", p),
                         "Closed {0} at {1}, out by {2}")
        self.assertEqual(lang.key_of("Close {0} {1}?", p), "Close {0} {1}?")
        self.assertEqual(lang.key_of("Sales for November 2026 and 3 Nov, on Monday", p),
                         "Sales for {0} {1} and {2} {3}, on {4}")
        self.assertEqual(lang.key_of("Copied to G:\\My Drive\\Twilight", p), "Copied to {0}")

    def test_months_and_days_are_pieces_on_their_own(self):
        keys = lang.shipped()[1]
        for word in ("November", "Nov", "Monday"):
            self.assertIn(word, keys)

    def test_what_is_never_on_a_screen_is_not_asked_for(self):
        keys = set(lang.shipped()[1])
        w = words.words()
        p = lang._pattern(w)
        for name in ("cli.check_total", "cli.help", "gemini.prompt", "migration.edited"):
            self.assertNotIn(lang.key_of(w[name], p), keys, name)

    def test_the_pieces_are_english_only(self):
        keys = lang.shipped()[1]
        self.assertEqual(len(keys), len(set(keys)))
        for k in keys:
            self.assertTrue(lang._good(k), k)
            self.assertEqual(kurdish_letters(k), [], k)


class NoKurdishInTheCode(unittest.TestCase):
    """The Kurdish is Mohammed's own, made with Gemini, and lives in his
    books. The app holds none, except each language's own name in the
    language switch, which is in the words (language.ckb)."""

    def test_no_kurdish_words_in_the_app(self):
        files = [*(ROOT / "ledger").rglob("*.py"), *(ROOT / "ledger").rglob("*.sql"),
                 *(ROOT / "web").rglob("*.js"), *(ROOT / "web").rglob("*.css"),
                 *(ROOT / "web").rglob("*.html"), *(ROOT / "web").rglob("*.json")]
        for f in files:
            text = f.read_text(encoding="utf-8")
            if f.name == "en.json":
                text = text.replace(words.words()["language.ckb"], "")
            self.assertEqual(kurdish_letters(text), [], f.relative_to(ROOT))


if __name__ == "__main__":
    unittest.main()
