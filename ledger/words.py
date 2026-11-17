"""Every sentence the app says, by name.

The words live in one file, web/lang/en.json, read by the screens and the
server alike: the code names a sentence and hands it its values, and never
spells it out. {0}, {1}… are where the values go, numbered in the order they
are read, and every value is one: a number, a date, a name, a month (its name
and its year, as two). Their Kurdish is in web/lang/ckb.json, by the same
names. The server itself only ever speaks English, so that what it writes
into the books and the black window stays English; the screens put what it
says into Kurdish as they show it (web/i18n.js).
"""
import functools
import json
import re
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "web" / "lang" / "en.json"
KURDISH = FILE.with_name("ckb.json")
HOLE = re.compile(r"\{(\d+)\}")


@functools.cache
def words():
    """{name: sentence}, read once."""
    return json.loads(FILE.read_text(encoding="utf-8"))


@functools.cache
def kurdish():
    """{name: its Kurdish}, for the sentences that have it, read once."""
    return json.loads(KURDISH.read_text(encoding="utf-8"))


def t(name, *values):
    """The sentence called `name`, with its values put in."""
    return HOLE.sub(lambda m: str(values[int(m.group(1))]), words()[name])
