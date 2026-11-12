"""The screens in Kurdish (Sorani), right to left.

The screens are drawn in English and translated as they are shown (web/
i18n.js): each piece of text, with numbers, dates, names and the elements
inside it taken out as {0}, {1}…, is looked up here. The Kurdish comes from
Mohammed, through Gemini: Setup → Language hands out the pieces with no
Kurdish yet as a prompt, and takes Gemini's answer back. Pieces come from the
list shipped with the app (web/lang/catalog.json) and from what the screens
actually show, added as they are seen.
"""
import hashlib
import json
import re
from pathlib import Path

from . import db
from .registry import ApiError, action

CATALOG = Path(__file__).resolve().parent.parent / "web" / "lang" / "catalog.json"
LANGUAGES = {"en": "English", "ckb": "کوردی"}
LETTER = re.compile(r"[^\W\d_]")
_shipped = None


def _good(key):
    return isinstance(key, str) and 0 < len(key) <= 400 and LETTER.search(key)


def _catalog():
    """The pieces shipped with this version of the app, and a short hash of
    them, read again only when the file changes."""
    global _shipped
    try:
        stamp = CATALOG.stat().st_mtime_ns
    except OSError:
        return None
    if not _shipped or _shipped[0] != stamp:
        raw = CATALOG.read_bytes()
        try:
            keys = json.loads(raw)
        except ValueError:
            keys = []
        _shipped = (stamp, hashlib.sha256(raw).hexdigest()[:16],
                    keys if isinstance(keys, list) else [])
    return _shipped


def sync(con):
    """Add the shipped pieces to the books, once for each version of the list."""
    c = _catalog()
    if not c or con.in_transaction or db.setting(con, "lang_catalog") == c[1]:
        return
    with db.tx(con):
        seen(con, c[2])
        db.set_setting(con, "lang_catalog", c[1])


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
    return {"language": language(con), "languages": LANGUAGES, "done": done, "todo": left,
            "version": db.setting(con, "lang_version", 0)}


@action("language_set", guard_pots=False,
        summary=lambda con, body, out: f"The screens are now in {LANGUAGES[out['language']]}")
def _language_set(con, body):
    lang = body.get("language")
    if lang not in LANGUAGES:
        raise ApiError("choose English or Kurdish")
    db.set_setting(con, "language", lang)
    return {"language": lang}


PLACEHOLDER = re.compile(r"\{\d+\}")


@action("lang_set", guard_pots=False,
        summary=lambda con, body, out: f"Kurdish saved for {out['saved']} pieces of text")
def _lang_set(con, body):
    """Save Kurdish for pieces of text: {"pairs": {English: Kurdish}}. A
    translation must keep every {0}, {1}… its English has, or it would lose
    a number or a name; one that does not is left out and said. Empty Kurdish
    takes a piece back to English."""
    pairs = body.get("pairs")
    if not isinstance(pairs, dict):
        raise ApiError("nothing to save")
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
