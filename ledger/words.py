"""Every sentence the app says, by name.

The words live in one file, web/lang/en.json, read by the screens and the
server alike: the code names a sentence and hands it its values, and never
spells it out. {0}, {1}… are where the values go, numbered in the order they
are read, and every value is one: a number, a date, a name, a month (its name
and its year, as two). So each sentence is written just as the screens see it
when they look up its Kurdish (web/i18n.js), and the Kurdish for it, which
lives in the books, is found by it.
"""
import functools
import json
import re
from pathlib import Path

FILE = Path(__file__).resolve().parent.parent / "web" / "lang" / "en.json"
HOLE = re.compile(r"\{(\d+)\}")


@functools.cache
def words():
    """{name: sentence}, read once."""
    return json.loads(FILE.read_text(encoding="utf-8"))


def t(name, *values):
    """The sentence called `name`, with its values put in."""
    return HOLE.sub(lambda m: str(values[int(m.group(1))]), words()[name])
