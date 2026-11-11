"""Look for anything from the real books or from SambaPOS in this repository.

The repository is public, so it must never hold a name of staff, partners or
suppliers, or a figure from the books. This collects every such name and
amount from a local export (and, if given, from SambaPOS backups) and searches
every file — or, with --history, every version of every file and every commit
message — for them. Nothing it reads is written anywhere; it only prints where
it found something.

Round amounts are left out — under 100,000, or a multiple of 50,000 —
because tests are full of invented ones and on their own they say nothing.
So are names made only of ordinary words (Store, Payment Accounts). Use --all
to see everything.

Usage:
    python3 tools/privacy_scan.py EXPORT.json [--pos FOLDER] [--history] [--all]
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.oracle import Old                                     # noqa: E402

WORDS = {"box", "bank", "rent", "unnamed", "business", "store", "shop", "holding",
         "cash", "administrator", "tea", "receivables", "discount", "sales",
         "payment", "accounts", "account", "customer", "customers", "expense",
         "expenses", "advance", "default", "normal", "table", "tables", "ticket",
         "tickets", "water", "coffee", "apple", "mint", "lemon", "orange", "grape",
         "juice", "sale", "receivable", "tips", "service", "open", "close",
         "transaction", "document", "twilight", "foil", "head", "mixed", "shisha",
         "cream", "olives", "filter", "filters", "carton", "english", "coal", "cups",
         "fakher", "adalya", "serbetli"}
PEOPLE_TYPES = {"Staff Advance", "Salary Payment", "Owner Advance", "Partner Settlement",
                "Owner Repayment", "Owner Capital In", "Supplier Payment",
                "Supplier Cash Purchase"}


def words_of(names, minlen=4):
    out = set()
    for n in names:
        n = str(n or "").strip()
        parts = [t for t in re.split(r"[\s\-_.()/]+", n.lower()) if t]
        if not n or n.isdigit() or all(t in WORDS or t.isdigit() for t in parts):
            continue
        if len(n) >= minlen:
            out.add(n)
        for t in re.split(r"[\s\-_.()/]+", n):
            if len(t) >= minlen and t.lower() not in WORDS and not t.isdigit():
                out.add(t)
    return out


def numbers(v, into):
    if isinstance(v, dict):
        for x in v.values():
            numbers(x, into)
    elif isinstance(v, list):
        for x in v:
            numbers(x, into)
    elif isinstance(v, (int, float)) and not isinstance(v, bool):
        into.add(float(v))
    elif isinstance(v, str) and re.fullmatch(r"-?\d+(\.\d+)?", v):
        into.add(float(v))


def from_export(path):
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    s = d.get("setup") or {}
    names = set()
    for k in ("staff", "partners", "suppliers", "pots"):
        for x in s.get(k) or []:
            names.add(x if isinstance(x, str) else x.get("name"))
    names |= {e.get("x") for e in d.get("cb") or [] if e.get("t") in PEOPLE_TYPES}
    names |= {p.get("s") for p in d.get("pu") or []}

    figures = set()
    numbers([x.get("salary") for x in s.get("staff") or []], figures)
    numbers([s.get("fixedExpenses"), d.get("closed"), d.get("debt"), s.get("stockItems")],
            figures)
    numbers([v.get("closing") for v in (d.get("inv") or {}).values()], figures)
    figures.add(sum(float(x.get("salary") or 0) for x in s.get("staff") or []))
    months = sorted({str(e.get("d"))[:7] for e in d.get("cb") or []})
    for m in months:
        o = Old(d, m)
        numbers(o.result(), figures)
        owed = o.supplier_owed()
        numbers(owed, figures)
        figures.add(sum(max(v, 0) for v in owed.values()))
        figures.add(o.cash_on_hand())
        numbers([o.pot_balance(p) for p in o.pots()], figures)
        numbers([o.booked(x) for x in o.valued_dates()], figures)
    rows = set()
    numbers([[e.get("in"), e.get("out")] for e in d.get("cb") or []], rows)
    numbers([p.get("amt") for p in d.get("pu") or []], rows)
    return names, figures, rows


def from_pos(folder):
    from ledger.pos import sources
    names, prices = set(), set()
    for f in sources.backups_in(folder):
        try:
            t = sources.read_backup(f)["tables"]
        except sources.PosError:
            continue                    # some other zip in the same folder
        for table, col in (("MenuItems", "Name"), ("Accounts", "Name"),
                           ("AccountTypes", "Name"), ("TicketEntities", "EntityName"),
                           ("AccountTransactionDocuments", "UserName"),
                           ("Orders", "MenuItemName"), ("Tickets", "Note")):
            names |= {r.get(col) for r in t.get(table, [])}
        numbers([r.get("Price") for r in t.get("Orders", [])], prices)
    return names, prices


def patterns(names, figures, rows, show_all):
    def keep(n):
        return show_all or (abs(n) >= 100000 and n % 50000 != 0)

    def forms(n):
        f = abs(n)
        if f == int(f):
            i = int(f)
            return {str(i), f"{i:,}", f"{i:_}"}
        return {repr(f), f"{f:,}"}

    out = []
    for label, nums in (("figure", figures), ("amount", rows - figures)):
        for n in sorted(x for x in nums if keep(x)):
            for form in forms(n):
                if len(form) >= 4:
                    out.append((f"{label} {n:g}", re.compile(
                        r"(?<![\d.,_])" + re.escape(form) + r"(?![\d_]|[.,]\d)")))
    for w in sorted(words_of(names)):
        out.append((f"name {w}", re.compile(r"(?<!\w)" + re.escape(w) + r"(?!\w)", re.I)))
        slug = re.sub(r"[^a-z0-9]+", "-", w.lower()).strip("-")
        if len(slug) >= 4 and slug != w.lower():
            out.append((f"name {w}", re.compile(re.escape(slug), re.I)))
    return out


def git(*args, text=True):
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True,
                          text=text).stdout


def files_now():
    for f in git("ls-files", "-co", "--exclude-standard").split("\n"):
        p = ROOT / f
        if f and p.is_file():
            yield f, p.read_bytes()


def files_ever():
    seen = set()
    revs = git("rev-list", "--all").split()
    for r in revs:
        for line in git("ls-tree", "-r", r).splitlines():
            meta, path = line.split("\t", 1)
            blob = meta.split()[2]
            if blob not in seen:
                seen.add(blob)
                yield f"{r[:7]}:{path}", git("cat-file", "-p", blob, text=False)
    for r in revs:
        yield f"{r[:7]}:(commit message)", git("log", "-1", "--format=%B", r, text=False)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("export")
    ap.add_argument("--pos", help="a folder of SambaPOS backups")
    ap.add_argument("--history", action="store_true")
    ap.add_argument("--all", action="store_true")
    a = ap.parse_args(argv)
    names, figures, rows = from_export(a.export)
    if a.pos:
        more, prices = from_pos(a.pos)
        names |= more
        figures |= prices
    pats = patterns(names - {None}, figures, rows, a.all)
    found = 0
    for where, data in (files_ever() if a.history else files_now()):
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError:
            continue
        for i, line in enumerate(text.splitlines(), 1):
            hits = sorted({label for label, pat in pats if pat.search(line)})
            if hits:
                found += 1
                print(f"{where}:{i}: {'; '.join(hits)}")
    print(f"{found} lines found" if found else "nothing found")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
