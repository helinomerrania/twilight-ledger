#!/usr/bin/env python3
"""Twilight Ledger — the books for Twilight Rest & Cafe.

    python twilight.py                  open the books in a browser
    python twilight.py check             is everything sound?
    python twilight.py backup            set a copy aside now (and to the second folder)
    python twilight.py restore FILE      put a copy back as the live books
    python twilight.py update            check GitHub for a newer version and install it
    python twilight.py pos save          keep tonight from SambaPOS, before the reset
    python twilight.py pos import FILE   keep what is in a SambaPOS backup
    python twilight.py import FILE       bring in a twilight-books.json export
    python twilight.py verify FILE       compare against the old app's figures
    python twilight.py close 2026-11     close a month from the command line
    python twilight.py sql "SELECT ..."  ask the books a question directly

Nothing here needs installing beyond Python itself.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ledger import db                                        # noqa: E402


def cmd_serve(a):
    from ledger.server import serve
    return serve(a.db, port=a.port, open_browser=not a.no_browser)


def cmd_check(a):
    con = db.connect(a.db)
    rep = db.integrity(con)
    print(f"books        {con.path}")
    print(f"migrations   {', '.join(rep['migrations'])}")
    print(f"entries      {rep['entries']:,}")
    print(f"postings     {rep['postings']:,}")
    print(f"sqlite       {rep['sqlite'][0]['integrity_check']}")
    print(f"foreign keys {'clean' if not rep['foreign_keys'] else rep['foreign_keys']}")
    print(f"balanced     {'yes' if not rep['unbalanced'] else rep['unbalanced']}")
    total = db.scalar(con, "SELECT COALESCE(SUM(amount), 0) FROM posting")
    print(f"debits less credits, across every account: {total}")
    ok = rep["ok"] and total == 0
    print("\nsound" if ok else "\nNOT SOUND")
    return 0 if ok else 1


def cmd_backup(a):
    from ledger import backup
    con = db.connect(a.db)
    out = backup.run(con, why=a.why)
    print(f"copied to {out['file']}  ({out['entries']:,} entries, checked)")
    if out["second"]:
        print(f"and to {out['second']}: " + ("checked" if out["second_ok"]
                                            else f"FAILED - {out['second_error']}"))
    else:
        print("no second folder is set, so this copy is only on this PC's disk")
    return 0 if out["second_ok"] is not False else 1


def cmd_restore(a):
    from ledger import backup
    if not a.yes:
        print("This replaces the live books with the copy. The books being replaced")
        print("are set aside first. Run again with --yes to go ahead.")
        print("\nCopies on this PC, newest last:")
        for f in backup.copies(a.db)[-12:]:
            print("  ", f)
        return 1
    out = backup.restore(a.db, a.file)
    print(f"restored {out['entries']:,} entries from {out['restored_from']}")
    if out["previous_kept_as"]:
        print(f"the books that were replaced are kept as {out['previous_kept_as']}")
    return 0


def cmd_update(a):
    from ledger import update
    info = update.check()
    print(f"this is version {info['current']}; GitHub has {info['latest']}")
    if not info["newer"]:
        print("nothing to do")
        return 0
    if a.check:
        return 0
    con = db.connect(a.db)
    out = update.download_and_apply(con)
    print(f"updated to {out['to']}. The books were copied first: {out['books_copy']}")
    print(f"the previous code is kept as {out['old_code']}")
    return 0


def cmd_pos(a):
    """SambaPOS: keep a night before the reset deletes it."""
    from ledger import api
    from ledger.pos import actions as pos, archive, sources
    con = db.connect(a.db)
    api.bootstrap(con)
    s = pos.settings(con)
    try:
        if a.what == "test":
            p = sources.test_live(s["server"], s["database"])
            print(f"connected to {p.get('db')} as {p.get('who')}: {p.get('tickets')} tickets "
                  f"in SambaPOS now, {p.get('open_periods')} work period(s) open")
            return 0
        if a.what == "nights":
            for r in db.all_(con, "SELECT night, SUM(tickets) t, SUM(takings) k, SUM(unpaid) u "
                                  "FROM pos_period WHERE tickets > 0 GROUP BY night ORDER BY night"):
                print(f"{r['night']}  {r['t']:>4} tickets  {r['k']:>12,} paid"
                      + (f"  {r['u']:,} unpaid" if r["u"] else ""))
            return 0
        if a.what == "import":
            if not a.files:
                print("name the backup files to bring in")
                return 1
            lines = []
            for f in a.files:
                lines += pos.keep(con, sources.read_backup(f), f"from {Path(f).name}")
        else:
            print(f"reading SambaPOS ({s['database']} on {s['server']})...")
            lines = pos.keep(con, sources.read_live(s["server"], s["database"]), "straight from its database")
    except sources.PosError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    lines = [l for l in lines if l["tickets"]]
    if not lines:
        print("SambaPOS has no tickets to keep. If the reset has already run, that night")
        print("is gone from SambaPOS: enter its takings from the printed report.")
        return 1
    worry = False
    for night in sorted({l["night"] for l in lines}):
        n = archive.night(con, night)
        print(f"\nthe night of {night}: {n['tickets']} tickets, {n['takings']:,} paid", end="")
        if n["unpaid"]:
            worry = True
            print(f", {n['unpaid']:,} still unpaid on {n['open_tickets']} open ticket(s)")
        else:
            print(", everything paid")
        if n["documents"]:
            moved = [d for d in n["documents"] if not d["reversed"]]
            print(f"  and {len(moved)} other record(s) - expenses, advances - "
                  f"{n['drawer_out']:,} out of the drawer"
                  + (f", {n['drawer_in']:,} into it" if n["drawer_in"] else ""))
        if not n["ended"] and a.what == "save":
            print("  the work period is still open; if more is sold, save again before the reset")
        elif not n["ended"]:
            print("  (its work period was still open when this copy was made)")
    if a.what == "save":
        if worry:
            print("\nClose the open tickets in SambaPOS, then run this again before the reset.")
        else:
            print("\nKept. It is safe to run the reset now.")
    return 1 if worry else 0


def cmd_import(a):
    from tools.import_json import main as run
    run([a.file, "--db", a.db] + (["--as-is"] if a.as_is else []))


def cmd_verify(a):
    from tools.verify import main as run
    return run([a.db, a.file])


def cmd_close(a):
    from ledger.close import close_month, ready
    con = db.connect(a.db)
    if a.dry_run:
        print(json.dumps(ready(con, a.month), indent=2, default=str))
        return 0
    with db.tx(con):
        out = close_month(con, a.month)
    print(f"{a.month} closed. Net {out['result']['net']:,}")
    for w in out["warnings"]:
        print(f"  note: {w}")
    return 0


def cmd_sql(a):
    """Read-only, so a typo cannot change the books."""
    con = db.connect(a.db, migrate=False, readonly=True)
    rows = db.all_(con, a.query)
    if not rows:
        print("(no rows)")
        return 0
    cols = rows[0].keys()
    width = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(width[c]) for c in cols))
    print("  ".join("-" * width[c] for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(width[c]) for c in cols))
    print(f"\n{len(rows)} rows")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="twilight", description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=db.DEFAULT_DB, help="where the books are kept")
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help="open the books in a browser (the default)")
    s.add_argument("--port", type=int, default=8788)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("check", help="is everything sound?")
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("backup", help="set a copy aside now")
    s.add_argument("--why", default="manual")
    s.set_defaults(fn=cmd_backup)

    s = sub.add_parser("restore", help="put a copy back as the live books")
    s.add_argument("file")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("update", help="install a newer version from GitHub")
    s.add_argument("--check", action="store_true", help="only say whether there is one")
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("pos", help="keep SambaPOS nights before the reset deletes them")
    s.add_argument("what", choices=["save", "import", "test", "nights"])
    s.add_argument("files", nargs="*", help="for import: SambaPOS backups (.zip or .bak)")
    s.set_defaults(fn=cmd_pos)

    s = sub.add_parser("import", help="bring in a twilight-books.json export")
    s.add_argument("file")
    s.add_argument("--as-is", action="store_true",
                   help="keep the five back-dated payments as they were")
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("verify", help="compare against the old app's figures")
    s.add_argument("file")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("close", help="close a month")
    s.add_argument("month")
    s.add_argument("--dry-run", action="store_true",
                   help="say what would happen, change nothing")
    s.set_defaults(fn=cmd_close)

    s = sub.add_parser("sql", help="ask the books a question (read-only)")
    s.add_argument("query")
    s.set_defaults(fn=cmd_sql)

    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        a = ap.parse_args((argv or []) + ["serve"])
    try:
        return a.fn(a) or 0
    except db.LedgerError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
