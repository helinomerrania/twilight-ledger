"""The screens in Kurdish (Sorani), right to left.

The screens are drawn in English and translated as they are shown (web/
i18n.js): each piece of text, with numbers, dates, names and the elements
inside it taken out as {0}, {1}…, is looked up here. The Kurdish comes from
Mohammed, through Gemini: Setup → Language hands out the pieces with no
Kurdish yet as a prompt, and takes Gemini's answer back. Pieces come from the
app's own words (web/lang/en.json), each as the screens will look it up, and
from what the screens actually show, added as they are seen.
"""
import hashlib
import re

from . import db
from .registry import ApiError, action
from .words import t, words

LANGUAGES = ("en", "ckb")
LETTER = re.compile(r"[^\W\d_]")
# words that are never on a screen: what the black window says, the prompt for
# Gemini itself, and what only someone changing the app's code would see
OFF_SCREEN = ("cli.", "gemini.", "migration.")
# what the screens take out of a piece as a value (web/i18n.js keyOf): a hole
# already, a path, Kurdish, then dates, times and numbers; months and days are
# added from the words
FILES = r"[A-Za-z]:\\(?:[\w.\- ]+\\)*[\w.\-]*|https?://\S+|[\w\-.:]+\.(?:zip|bak|db|json|csv|txt|pdf|bat)\b"
KURDISH = r"[\u0600-\u06FF](?:[\u0600-\u06FF\u064B-\u065F\u200C-\u200F]|\s(?=[\u0600-\u06FF]))*"
NUMBERS = (r"\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}(?::\d{2})?)?|\d{1,2}:\d{2}(?::\d{2})?"
           r"|[-−+]?\d+(?:[,.]\d+)*%?")
_shipped = None


def _good(key):
    return isinstance(key, str) and 0 < len(key) <= 400 and LETTER.search(key)


def _pattern(w):
    months = [w[f"month.{m:02d}"] for m in range(1, 13)]
    short = [m[:3] for m in months]
    days = [w[f"day.{d}"] for d in range(1, 8)]
    calendar = (rf"(?:{'|'.join(months)})(?=\s\d{{4}})|(?<=\d\s)(?:{'|'.join(short)})\b"
                rf"|\b(?:{'|'.join(days)})\b")
    return re.compile("|".join([r"\{\d+\}", FILES, KURDISH, calendar, NUMBERS]))


def key_of(text, pattern):
    """A sentence as the screens see it, every value in it a hole numbered in
    the order it is read: "Use SambaPOS's figure in step 1" is looked up as
    "Use SambaPOS's figure in step {0}"."""
    holes = iter(range(10_000))
    key = pattern.sub(lambda m: f"{{{next(holes)}}}", text)
    return re.sub(r"\s+", " ", key).strip()


def shipped():
    """The pieces the app's own words make, and a short hash of them; worked
    out once."""
    global _shipped
    if _shipped is None:
        w = words()
        pattern = _pattern(w)
        keys = {key_of(v, pattern) for k, v in w.items() if not k.startswith(OFF_SCREEN)}
        # a month or a day in a piece is a value, put into Kurdish on its own
        keys |= {v for k, v in w.items() if re.fullmatch(r"(month|day)\.\d+", k)}
        keys |= {v[:3] for k, v in w.items() if re.fullmatch(r"month\.\d+", k)}
        keys = sorted(k for k in keys if _good(k))
        _shipped = (hashlib.sha256("\n".join(keys).encode("utf-8")).hexdigest()[:16], keys)
    return _shipped


def sync(con):
    """Add the app's pieces to the books, once for each version of its words."""
    stamp, keys = shipped()
    if con.in_transaction or db.setting(con, "lang_catalog") == stamp:
        return
    with db.tx(con):
        seen(con, keys)
        db.set_setting(con, "lang_catalog", stamp)


def seen(con, keys):
    """Remember pieces of text the screens showed. Returns how many were new."""
    new = 0
    if not isinstance(keys, list):
        return new
    for k in keys[:2000]:
        if _good(k):
            new += con.execute("INSERT OR IGNORE INTO lang_text(key) VALUES (?)", (k,)).rowcount
    return new


def language(con):
    v = db.setting(con, "language")
    return v if v in LANGUAGES else "en"


def texts(con):
    """Every piece that has Kurdish: {English: Kurdish}."""
    return {r["key"]: r["ckb"] for r in db.all_(
        con, "SELECT key, ckb FROM lang_text WHERE ckb IS NOT NULL AND ckb != ''")}


def todo(con, limit=150):
    """Pieces with no Kurdish yet, the longest-known first."""
    return [r["key"] for r in db.all_(
        con, "SELECT key FROM lang_text WHERE ckb IS NULL OR ckb = '' "
             "ORDER BY seen_at, rowid LIMIT ?", (int(limit),))]


def view(con):
    sync(con)
    done = db.scalar(con, "SELECT COUNT(*) FROM lang_text WHERE ckb IS NOT NULL AND ckb != ''")
    left = db.scalar(con, "SELECT COUNT(*) FROM lang_text WHERE ckb IS NULL OR ckb = ''")
    return {"language": language(con), "languages": {c: t(f"language.{c}") for c in LANGUAGES},
            "done": done, "todo": left,
            "version": db.setting(con, "lang_version", 0)}


@action("language_set", guard_pots=False,
        summary=lambda con, body, out: t("change.language", t(f"language.{out['language']}")))
def _language_set(con, body):
    lang = body.get("language")
    if lang not in LANGUAGES:
        raise ApiError(t("language.choose"))
    db.set_setting(con, "language", lang)
    return {"language": lang}


PLACEHOLDER = re.compile(r"\{\d+\}")


@action("lang_set", guard_pots=False,
        summary=lambda con, body, out: t("change.kurdish_saved", out["saved"]))
def _lang_set(con, body):
    """Save Kurdish for pieces of text: {"pairs": {English: Kurdish}}. A
    translation must keep every {0}, {1}… its English has, or it would lose
    a number or a name; one that does not is left out and said. Empty Kurdish
    takes a piece back to English."""
    pairs = body.get("pairs")
    if not isinstance(pairs, dict):
        raise ApiError(t("language.nothing"))
    saved, wrong = 0, []
    for key, ckb in pairs.items():
        if not _good(key) or not isinstance(ckb, str):
            continue
        ckb = ckb.strip()
        if ckb and sorted(PLACEHOLDER.findall(key)) != sorted(PLACEHOLDER.findall(ckb)):
            wrong.append(key)
            continue
        con.execute("INSERT INTO lang_text(key, ckb) VALUES (?, ?) ON CONFLICT(key) "
                    "DO UPDATE SET ckb = excluded.ckb", (key, ckb or None))
        saved += 1
    db.set_setting(con, "lang_version", int(db.setting(con, "lang_version", 0) or 0) + 1)
    return {"saved": saved, "wrong": wrong[:20], "wrong_count": len(wrong)}
