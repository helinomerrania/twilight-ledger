"""The acceptance gate: the new books must agree with the old ones.

The rebuild is only trustworthy if it reproduces Mohammed's real figures to the
dinar. This compares every headline number the new database computes against
tools/oracle.py, which is an independent reimplementation of the old app's
arithmetic read off its source. If any line differs, the build has failed.

Two differences are expected and are checked rather than ignored:

  * the five back-dated payments now carry their real dates, so cash on hand
    *at a date inside the affected window* moves. The totals as at today, and
    every month's result, must not.
  * figures the old app carried as halves of a dinar, inherited from the Excel
    workbook, are whole dinar here. Any gap is reported and must be under a
    dinar per figure.

Usage:  python3 tools/verify.py data/twilight.db twilight-books.json
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ledger import db, queries                                  # noqa: E402
from tools.import_json import BACKDATED                         # noqa: E402
from tools.oracle import Old                                    # noqa: E402

TOL = 1.0          # a figure may differ by less than a dinar, nothing more


class Check:
    def __init__(self):
        self.rows, self.failed = [], 0

    def __call__(self, label, old, new, tol=TOL, note=""):
        old = 0 if old is None else float(old)
        new = 0 if new is None else float(new)
        gap = new - old
        ok = abs(gap) < tol
        if not ok:
            self.failed += 1
        self.rows.append((ok, label, old, new, gap, note))
        return ok

    def expect_change(self, label, old, new, by, note=""):
        """A difference that is the point of the exercise, not a regression."""
        old = float(old or 0)
        new = float(new or 0)
        gap = new - old
        ok = abs(gap - by) < TOL
        if not ok:
            self.failed += 1
        self.rows.append((ok, label, old, new, gap,
                          note or f"expected to move by {by:+,.0f}"))
        return ok

    def report(self):
        width = max(len(r[1]) for r in self.rows) + 2
        print(f"{'':2}{'figure':<{width}}{'old app':>16}{'new books':>16}{'gap':>12}")
        print("-" * (width + 48))
        for ok, label, old, new, gap, note in self.rows:
            mark = "  " if ok else "!!"
            print(f"{mark}{label:<{width}}{old:>16,.1f}{new:>16,.1f}{gap:>12,.1f}"
                  + (f"   {note}" if note else ""))
        print("-" * (width + 48))
        print(f"{len(self.rows)} checks, {self.failed} failed")
        return self.failed == 0


def main(argv=None):
    argv = argv or sys.argv[1:]
    dbp = argv[0] if argv else db.DEFAULT_DB
    jsonp = argv[1] if len(argv) > 1 else "/home/claude/work/latest.json"
    data = json.loads(Path(jsonp).read_text(encoding="utf-8"))
    con = db.connect(dbp, migrate=False)
    c = Check()

    months = queries.months(con)

    # ---------------------------------------------------- the month's result
    for m in months:
        o = Old(data, m)
        old = o.result()
        new = queries.result(con, m)
        tag = " (closed)" if new.get("frozen") else ""
        for key in ("sales", "other", "rev", "gross", "daily", "elec",
                    "fixed", "salaries", "net"):
            c(f"{m} {key}{tag}", old.get(key), new.get(key))
        oc, nc = old.get("cogs") or {}, new.get("cogs") or {}
        for key in ("opening", "purchases", "closing", "value"):
            c(f"{m} cogs {key}{tag}", oc.get(key), nc.get(key))
        c(f"{m} stock count date{tag}",
          0 if oc.get("date") == nc.get("date") else 1, 0,
          note=f"old {oc.get('date')} / new {nc.get('date')}")

    # ------------------------------------------------------------ cash today
    o = Old(data, months[-1])
    c("cash on hand (today)", o.cash_on_hand(), queries.cash_on_hand(con))
    for p in o.pots():
        c(f"pot {p} (today)", o.pot_balance(p),
          queries.balance(con, _pot_code(con, p)))

    # ------------------------------------------------------------- suppliers
    owed = o.supplier_owed()
    c("owed to suppliers", sum(max(v, 0) for v in owed.values()),
      queries.owed_to_suppliers(con))
    for name, v in owed.items():
        code = db.one(con, "SELECT code FROM account WHERE kind='supplier' AND name=?",
                      (name,))
        if code:
            c(f"owed {name}", v, queries.balance(con, code["code"]))

    # ------------------------------- the five rows: what should have changed
    # 31 October: the cash no longer leaves on a day it did not. The amount
    # is read from the export, so no figure from the books is written here.
    rows = {str(e.get("id")): e for e in data.get("cb") or []}
    redated = sum(float(rows[r].get("out") or 0) - float(rows[r].get("in") or 0)
                  for r in BACKDATED if r in rows)
    c.expect_change("cash on hand at 2026-10-31",
                    o.cash_on_hand("2026-10-31"),
                    queries.cash_on_hand(con, "2026-10-31"),
                    by=redated,
                    note="the five payments now fall in November, where they happened")

    # ------------------------------------------- and what the fix is for
    counts = queries.cash_counts(con)
    breaks = [x for x in counts if x["diff"] != 0]
    print()
    print(f"cash counts: {len(counts)} recorded, {len(breaks)} do not tie")
    for b in breaks:
        print(f"    {b['on']}  out by {b['diff']:+,}  ({b['reason'] or 'no reason given'})")
    old_breaks = _old_breaks(data)
    print(f"    the old app had {len(old_breaks)} breaks: "
          + ", ".join(f"{d} {v:+,.0f}" for d, v in old_breaks))

    # ------------------------------------------------------------- integrity
    rep = db.integrity(con)
    print()
    print(f"integrity: sqlite {rep['sqlite']}, foreign keys "
          f"{'clean' if not rep['foreign_keys'] else rep['foreign_keys']}, "
          f"unbalanced entries {len(rep['unbalanced'])}")
    print(f"           {rep['entries']} entries, {rep['postings']} postings")

    print()
    ok = c.report()
    if rep["unbalanced"] or rep["foreign_keys"]:
        ok = False
    print()
    print("GATE PASSED" if ok else "GATE FAILED")
    return 0 if ok else 1


def _pot_code(con, name):
    r = db.one(con, "SELECT code FROM account WHERE kind IN ('cash','float') "
                    "AND name = ?", (name,))
    return r["code"] if r else "cash:box"


def _old_breaks(data):
    """What the old app's own count history showed, for the before/after line."""
    out = []
    o = Old(data, "2026-11")
    for r in sorted(data.get("rc") or [], key=lambda x: str(x["d"])[:10]):
        on = str(r["d"])[:10]
        per_pot = r.get("counts") or {}
        if per_pot:
            counted = sum(float(v or 0) for v in per_pot.values())
            expected = sum(o.pot_balance(p, on) for p in per_pot)
        elif r.get("counted") is not None:
            counted = float(r["counted"])
            expected = o.pot_balance("Box", on)
        else:
            continue
        if abs(counted - expected) > 0.5:
            out.append((on, counted - expected))
    return out


if __name__ == "__main__":
    raise SystemExit(main())
