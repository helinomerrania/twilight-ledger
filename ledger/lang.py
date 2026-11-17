"""The screens in Kurdish (Sorani), right to left.

The Kurdish comes with the app, in web/lang/ckb.json, by the same names as the
English in web/lang/en.json, and the screens use it themselves (web/i18n.js).
The server speaks only English. Here are the choice of language, how much of
the app has its Kurdish, and the Kurdish Mohammed kept in his books before it
came with the app (lang_text), which the screens fall back on where
ckb.json has none.
"""
import re

from . import db
from .registry import ApiError, action
from .words import kurdish, t, words

LANGUAGES = ("en", "ckb")
# Never put into Kurdish: what only the black window says, what only someone
# changing the app's code sees, each language's own name, the app's name and
# the programs it works with, examples of a folder, and what the app writes
# into new books.
ENGLISH_ONLY = re.compile(
    r"(?:cli|migration)\.\w+|language\.(?:en|ckb)|app\.name|(?:backup|pos)\.example_path"
    r"|setup\.first_(?:business|pot)|(?:drawer|page)\.sambapos|sambapos_card\.(?:title|server)")


def language(con):
    v = db.setting(con, "language")
    return v if v in LANGUAGES else "en"


def texts(con):
    """The Kurdish kept in the books: {piece of English: Kurdish}."""
    return {r["key"]: r["ckb"] for r in db.all_(
        con, "SELECT key, ckb FROM lang_text WHERE ckb IS NOT NULL AND ckb != ''")}


def view(con):
    shown = [n for n in words() if not ENGLISH_ONLY.fullmatch(n)]
    have = kurdish()
    return {"language": language(con), "languages": {c: t(f"language.{c}") for c in LANGUAGES},
            "done": sum(n in have for n in shown), "total": len(shown)}


@action("language_set", guard_pots=False,
        summary=lambda con, body, out: t("change.language", t(f"language.{out['language']}")))
def _language_set(con, body):
    lang = body.get("language")
    if lang not in LANGUAGES:
        raise ApiError(t("language.choose"))
    db.set_setting(con, "language", lang)
    return {"language": lang}
