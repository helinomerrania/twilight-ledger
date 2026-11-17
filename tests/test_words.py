"""Every sentence the app says is in one file, web/lang/en.json, by name
(and its Kurdish in web/lang/ckb.json, by the same name: tests/test_lang.py).

The code names a sentence and gives it its values; it never spells one out.
These tests keep it that way: the file is well made, every name the code uses
is in it, everything in it is used, and no sentence has crept back into the
code, on the server or on the screens.
"""
import ast
import json
import re
import unittest
from pathlib import Path

from ledger import words

ROOT = Path(__file__).resolve().parent.parent
FILE = ROOT / "web" / "lang" / "en.json"
NAME = re.compile(r"[a-z0-9_]+(?:\.[a-z0-9_]+)+")
# what the books' own trail calls a change: names of actions, not of words
NOT_WORDS = {"entry.void", "entry.unvoid", "period.close", "period.reopen"}


def python_files():
    return sorted([*(ROOT / "ledger").rglob("*.py"), ROOT / "twilight.py"])


def js_files():
    return sorted((ROOT / "web").glob("*.js"))


def source(files):
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


class TheFile(unittest.TestCase):

    def setUp(self):
        self.text = FILE.read_text(encoding="utf-8")
        self.words = json.loads(self.text)

    def test_it_is_names_in_order_one_to_a_line(self):
        # so a change to the words shows as a change to one line
        lines = [f"{json.dumps(k)}: {json.dumps(v, ensure_ascii=False)}"
                 for k, v in sorted(self.words.items())]
        self.assertEqual(self.text, "{\n" + ",\n".join(lines) + "\n}\n")

    def test_names_are_area_dot_thing(self):
        for name, text in self.words.items():
            self.assertRegex(name, NAME)
            self.assertTrue(isinstance(text, str) and text.strip(), name)

    def test_values_go_in_numbered_from_nought(self):
        for name, text in self.words.items():
            holes = {int(n) for n in re.findall(r"\{(\d+)\}", text)}
            self.assertEqual(holes, set(range(len(holes))), name)

    def test_the_server_and_the_screens_read_the_same_file(self):
        self.assertEqual(words.FILE, FILE)
        self.assertEqual(words.t("look.many", 3), "3 things need a look.")
        self.assertIn("read('lang/en.json')", (ROOT / "web" / "lib.js").read_text(encoding="utf-8"))


class TheNames(unittest.TestCase):
    """A name the code uses that is not in the file would show as the name; a
    sentence in the file that nothing uses is one more to put into Kurdish for
    nothing."""

    def setUp(self):
        self.words = words.words()
        self.areas = {n.split(".")[0] for n in self.words}
        self.code = source(python_files()) + source(js_files())

    def named(self):
        # every quoted name in an area the words have: t("area.thing"), or a
        # name kept in a list to be looked up later
        found = re.findall(r"""['"]([a-z0-9_]+(?:\.[a-z0-9_]+)+)['"]""", self.code)
        return {n for n in found if n.split(".")[0] in self.areas} - NOT_WORDS

    def families(self):
        # names made as the code runs: t(`night_kind.${k}`), t(f"kind.{kind}")
        return set(re.findall(r"""\b(?:t|th|words)\((?:`|f["'])([a-z0-9_.]+?)(?:\$\{|\{)""", self.code))

    def test_every_name_the_code_uses_is_there(self):
        missing = sorted(self.named() - set(self.words))
        self.assertEqual(missing, [])

    def test_every_family_has_words(self):
        for prefix in self.families():
            self.assertTrue(any(n.startswith(prefix) for n in self.words), prefix)

    def test_everything_there_is_used(self):
        used, families = self.named(), tuple(self.families())
        unused = sorted(n for n in self.words if n not in used and not n.startswith(families))
        self.assertEqual(unused, [])


# ---------------------------------------------------------------- the server

SQL = re.compile(r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|PRAGMA|BEGIN|FROM|WHERE|JOIN|VALUES|"
                 r"LIMIT|ORDER BY|GROUP BY|COALESCE|LIKE|AND|OR|IN)\b|[=<>] \?")
# what the code matches in what other programs say, or names a thing with
PY_ALLOWED = {
    "Login failed", "Cannot open database", "Invalid object name",       # SQL Server's errors
    "was not found or was not accessible", "error: 26", "error: 40",
    "At ", "Line ", "#< CLIXML", '<S S="Error">(.*?)</S>',                 # PowerShell's
    "Start Twilight Ledger.bat", "Save tonight from SambaPOS.bat",         # files' names
    "application/json; charset=utf-8", "; charset=utf-8",
}


def sentence(s):
    s2 = s.strip()
    if not re.search(r"[A-Za-z]{2}", s2) or s in PY_ALLOWED:
        return False
    if SQL.search(s2):
        return False                                    # a query, or a piece of one
    if re.fullmatch(r"[A-Z][A-Za-z0-9_]*|[A-Z][a-z]+(?:-[A-Z][a-z]+)+", s2):
        return False                                    # SambaPOS's names; a header
    if re.search(r"\\[wdsS]|\(\?[:<!=]|\[\^?[A-Za-z]-|\|", s):
        return False                                    # a pattern
    if re.search(r"^\s*import |\nimport ", s):
        return False                                    # code the update runs in the new version
    if re.fullmatch(r"[a-z_][a-z0-9_.:%*\-/ ]*", s2) and " " not in s2:
        return False                                    # a key, a code
    return " " in s2 or bool(re.match(r"[A-Z][a-z]", s2))


class NothingSpeltOutOnTheServer(unittest.TestCase):

    def test_no_sentences_in_the_python(self):
        found = []
        for f in python_files():
            tree = ast.parse(f.read_text(encoding="utf-8"))
            parents = {c: n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
            for n in ast.walk(tree):
                if not isinstance(n, (ast.Constant, ast.JoinedStr)) \
                        or isinstance(parents.get(n), (ast.JoinedStr, ast.Expr)):
                    continue                            # part of an f-string, or a docstring
                if isinstance(n, ast.Constant):
                    s = n.value if isinstance(n.value, str) else ""
                else:
                    s = "".join(v.value if isinstance(v, ast.Constant) else "{}" for v in n.values)
                if sentence(s):
                    found.append(f"{f.relative_to(ROOT)}:{n.lineno}: {s[:80]!r}")
        self.assertEqual(found, [])


# --------------------------------------------------------------- the screens

def js_strings(src):
    """Every string in JavaScript source: (line, kind, text), kind 'str' for a
    quoted string and 'tpl' for a template, its ${...} as {}."""
    out, n = [], len(src)
    last = ""                                          # the last thing that was not a space

    def line(at):
        return src.count("\n", 0, at) + 1

    def quoted(i, q):
        j = i + 1
        while src[j] != q:
            j += 2 if src[j] == "\\" else 1
        return j + 1

    def template(i):
        j, parts, buf = i + 1, [], ""
        while src[j] != "`":
            if src[j] == "\\":
                buf += src[j:j + 2]
                j += 2
            elif src.startswith("${", j):
                buf += "{}"
                j = code(j + 2, "}")
            else:
                buf += src[j]
                j += 1
        parts.append(buf)
        out.append((line(i), "tpl", "".join(parts)))
        return j + 1

    def code(j, until):
        nonlocal last
        depth = 0
        while j < n:
            c = src[j]
            if c == until and depth == 0:
                return j + 1
            if c in "{([":
                depth += 1
            elif c in "})]":
                depth -= 1
            if src.startswith("//", j):
                j = src.index("\n", j)
                continue
            if src.startswith("/*", j):
                j = src.index("*/", j) + 2
                continue
            if c in "'\"":
                end = quoted(j, c)
                out.append((line(j), "str", src[j + 1:end - 1]))
                j, last = end, "a"
                continue
            if c == "`":
                j, last = template(j), "a"
                continue
            if c == "/" and (last == "" or last in "(,=:[!&|?{};+-*%<>~^" or
                             re.search(r"\b(return|typeof|case)\s*$", src[max(0, j - 8):j])):
                k = j + 1                              # a pattern: /.../flags
                cls = False
                while src[k] != "/" or cls:
                    if src[k] == "\\":
                        k += 1
                    elif src[k] == "[":
                        cls = True
                    elif src[k] == "]":
                        cls = False
                    k += 1
                j, last = k + 1, "a"
                continue
            if not c.isspace():
                last = c
            j += 1
        return j

    code(0, None)
    return out


SHOWN = re.compile(r'\b(title|placeholder|aria-label|label|alt|data-confirm|data-confirm-body|data-yes)='
                   r'"([^"{]*)"')
# names of keys, of what SambaPOS calls things, and what a developer reads
JS_ALLOWED = {"Escape", "Enter", "Shift", "ArrowUp", "ArrowDown", "Normal", "no words called {}",
              "YOUR-PC\\\\you", "<code>sa</code>"}


def screen_words(kind, text):
    """The words a string would put on the screen, if any."""
    if text in JS_ALLOWED:
        return []
    found = [v for _, v in SHOWN.findall(text) if re.search(r"[A-Za-z]{2}", v)]
    if re.search(r"<[a-z/!]", text, re.IGNORECASE):
        between = re.sub(r"<[^>]*>|<[^>]*$|^[^<]*>", " ", text)
        between = re.sub(r"&[a-z]+;|\{\}", " ", between)
        if re.search(r"[A-Za-z]{2}", between):
            found.append(between.strip())
        return found
    if re.search(r'[\w-]="', text):
        return found                                    # only the attributes of a tag
    plain = text.replace("{}", " ").strip()
    if re.search(r"[\[\]=#/\\|]", plain) or re.fullmatch(r"[A-Z][a-z]+(?:-[A-Z][a-z]+)+", plain):
        return []                                       # a selector, an address, a pattern, a header
    if kind == "tpl" and re.search(r"(?:CREATE|ALTER) ", plain):
        return []                                       # the SQL lines Setup shows
    if re.fullmatch(r"[a-z0-9 _:.,()=\-]*|[a-z][A-Za-z0-9]*", plain):
        return []                                       # classes, keys, codes
    if re.search(r"[A-Za-z]{2,}", plain) and (" " in plain or re.match(r"[A-Z][a-z]", plain)):
        return [plain]
    return []


class NothingSpeltOutOnTheScreens(unittest.TestCase):

    def test_the_reader_finds_strings(self):
        got = js_strings("const a = 'x' + `b ${c ? 'd' : `e ${f}`} g`; // 'no'\nh(/'/g, '/')")
        self.assertEqual([(k, s) for _, k, s in got],
                         [("str", "x"), ("str", "d"), ("tpl", "e {}"), ("tpl", "b {} g"), ("str", "/")])

    def test_no_sentences_in_the_screens(self):
        found = []
        for f in js_files():
            for ln, kind, text in js_strings(f.read_text(encoding="utf-8")):
                found += [f"{f.name}:{ln}: {w[:80]!r}" for w in screen_words(kind, text)]
        self.assertEqual(found, [])

    def test_the_page_itself_has_no_words(self):
        html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
        body = re.sub(r"<!--.*?-->|<[^>]*>", " ", html, flags=re.DOTALL)
        self.assertEqual(body.split(), [])
        self.assertNotRegex(html, SHOWN)


if __name__ == "__main__":
    unittest.main()
