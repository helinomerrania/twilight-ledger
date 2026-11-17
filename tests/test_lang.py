"""The screens in Kurdish. The Kurdish comes with the app, in
web/lang/ckb.json, by the same names as the English in web/lang/en.json; the
screens use it themselves (web/i18n.js), and the server only ever speaks
English. Nothing else in the app is in Kurdish."""
import json
import re
import unicodedata
import unittest
from pathlib import Path
from unittest import mock

from ledger import api, db, lang, queries, registry, words
from tests.helpers import fresh_books

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "web" / "lang" / "ckb.json"
HOLES = re.compile(r"\{\d+\}")


def kurdish_letters(text):
    return [c for c in text if unicodedata.category(c).startswith("L")
            and "ARABIC" in unicodedata.name(c, "")]


class TheKurdishFile(unittest.TestCase):

    def setUp(self):
        self.text = FILE.read_text(encoding="utf-8")
        self.kurdish = json.loads(self.text)
        self.english = words.words()

    def test_it_is_names_in_order_one_to_a_line(self):
        # as the English is, so a change to the Kurdish shows as a change to one line
        lines = [f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}"
                 for k, v in sorted(self.kurdish.items())]
        self.assertEqual(self.text, "{\n" + ",\n".join(lines) + "\n}\n" if lines else "{}\n")

    def test_every_name_is_one_of_the_english(self):
        self.assertEqual(sorted(set(self.kurdish) - set(self.english)), [])

    def test_what_stays_english_has_no_kurdish(self):
        self.assertEqual([n for n in self.kurdish if lang.ENGLISH_ONLY.fullmatch(n)], [])

    def test_every_value_goes_in_once(self):
        # Kurdish that lost a {0} would lose a number or a name
        for name, text in self.kurdish.items():
            self.assertEqual(sorted(HOLES.findall(text)), sorted(HOLES.findall(self.english[name])), name)

    def test_each_is_in_kurdish(self):
        for name, text in self.kurdish.items():
            self.assertTrue(kurdish_letters(text), name)
            self.assertEqual(text, text.rstrip(), name)

    def test_what_goes_on_after_another_sentence_still_does(self):
        # " Opened by {0}…" and ", in {0}" follow another sentence on the screen
        for name, text in self.kurdish.items():
            e = self.english[name]
            self.assertEqual(text[:len(text) - len(text.lstrip())], e[:len(e) - len(e.lstrip())], name)
            if e[:1] in ",;":
                self.assertIn(text[:1], ",;،؛", name)

    def test_the_screens_and_the_server_read_it(self):
        self.assertIn("read('lang/ckb.json')", (ROOT / "web" / "lib.js").read_text(encoding="utf-8"))
        self.assertEqual(words.KURDISH, FILE)


class TheLanguage(unittest.TestCase):

    def setUp(self):
        self.con = fresh_books()

    def test_choosing_the_language(self):
        self.assertEqual(api.state(self.con)["lang"]["language"], "en")
        api.run(self.con, "language_set", {"language": "ckb"})
        v = api.state(self.con)["lang"]
        self.assertEqual(v["language"], "ckb")
        self.assertEqual(set(v["languages"]), {"en", "ckb"})
        with self.assertRaises(api.ApiError):
            api.run(self.con, "language_set", {"language": "fr"})

    def test_it_is_in_recent_changes(self):
        api.run(self.con, "language_set", {"language": "ckb"})
        self.assertEqual(queries.recent(self.con)[0]["summary"],
                         words.t("change.language", words.t("language.ckb")))

    def test_the_server_speaks_english_with_the_screens_in_kurdish(self):
        # what it writes into the books and the black window stays English
        api.run(self.con, "language_set", {"language": "ckb"})
        with self.assertRaises(api.ApiError) as no:
            api.run(self.con, "language_set", {"language": "fr"})
        self.assertEqual(str(no.exception), words.words()["language.choose"])

    def test_the_screens_are_told_how_much_has_its_kurdish(self):
        shown = [n for n in words.words() if not lang.ENGLISH_ONLY.fullmatch(n)]
        with mock.patch.object(lang, "kurdish", lambda: {"closing.title": "[x]", "tab.stock": "[y]"}):
            v = lang.view(self.con)
        self.assertEqual((v["done"], v["total"]), (2, len(shown)))

    def test_what_never_goes_into_kurdish_is_not_counted(self):
        for name in ("cli.help", "migration.edited", "language.ckb", "language.en", "app.name",
                     "backup.example_path", "setup.first_pot", "page.sambapos"):
            self.assertIn(name, words.words())
            self.assertTrue(lang.ENGLISH_ONLY.fullmatch(name), name)
        for name in ("closing.title", "language.choose", "cli_like", "page.stock"):
            self.assertFalse(lang.ENGLISH_ONLY.fullmatch(name), name)

    def test_the_kurdish_kept_in_the_books_is_still_handed_over(self):
        # made with Gemini before the Kurdish came with the app; the screens
        # use it where lang/ckb.json has none
        with db.tx(self.con):
            self.con.execute("INSERT INTO lang_text(key, ckb) VALUES ('Closing up', '[closing]'), "
                             "('Filled {0}: {1} g', '[{1} {0}]'), ('Save', NULL), ('Back', '')")
        self.assertEqual(lang.texts(self.con), {"Closing up": "[closing]", "Filled {0}: {1} g": "[{1} {0}]"})


class NothingLeftOfGemini(unittest.TestCase):
    """The Kurdish is no longer made in the app: nothing hands out a prompt,
    takes an answer back, or notes what the screens show."""

    def test_no_action_saves_kurdish(self):
        self.assertEqual(sorted(n for n in registry.ACTIONS if n.startswith("lang")), ["language_set"])

    def test_not_a_word_of_it(self):
        files = [*(ROOT / "ledger").rglob("*.py"), *(ROOT / "web").glob("*.*"),
                 *(ROOT / "web" / "lang").glob("*.json"), ROOT / "twilight.py"]
        for f in files:
            text = f.read_text(encoding="utf-8")
            for gone in ("gemini", "lang/seen", "lang/todo", "langBatch", "lang_set"):
                self.assertNotIn(gone, text.lower(), f.relative_to(ROOT))


class NoKurdishInTheCode(unittest.TestCase):
    """All the Kurdish is in web/lang/ckb.json. Apart from it the app holds
    none, but the name of the language itself in the language switch, which
    is in the words (language.ckb)."""

    def test_no_kurdish_words_in_the_app(self):
        files = [*(ROOT / "ledger").rglob("*.py"), *(ROOT / "ledger").rglob("*.sql"),
                 *(ROOT / "web").rglob("*.js"), *(ROOT / "web").rglob("*.css"),
                 *(ROOT / "web").rglob("*.html"), *(ROOT / "web").rglob("*.json"),
                 *(ROOT / "tools").rglob("*.py"), ROOT / "twilight.py"]
        for f in files:
            if f == FILE:
                continue
            text = f.read_text(encoding="utf-8")
            if f.name == "en.json":
                text = text.replace(words.words()["language.ckb"], "")
            self.assertEqual(kurdish_letters(text), [], f.relative_to(ROOT))


if __name__ == "__main__":
    unittest.main()
