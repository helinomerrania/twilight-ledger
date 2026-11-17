#!/usr/bin/env python3
"""Twilight Ledger, from the command line: `python twilight.py --help` says
what it can do (its words, like every other, are in web/lang/en.json)."""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ledger import db                                        # noqa: E402
from ledger.words import t                                   # noqa: E402


def cmd_serve(a):
    from ledger.server import serve
    return serve(a.db, port=a.port, open_browser=not a.no_browser)


def cmd_window(a):
    from ledger import window
    return window.run(a.db, a.argv)


def cmd_icon(a):
    from ledger import window
    made = window.make_icon(a.db)
    print(t("cli.icon_made", made) if made else t("cli.icon_failed", t("cli.icon_needs")))
    return 0 if made else 1


def cmd_check(a):
    con = db.connect(a.db)
    rep = db.integrity(con)
    print(t("cli.check_books", con.path))
    print(t("cli.check_migrations", ", ".join(rep["migrations"])))
    print(t("cli.check_entries", f"{rep['entries']:,}"))
    print(t("cli.check_postings", f"{rep['postings']:,}"))
    print(t("cli.check_sqlite", rep["sqlite"][0]["integrity_check"]))
    print(t("cli.check_keys", t("cli.clean") if not rep["foreign_keys"] else rep["foreign_keys"]))
    print(t("cli.check_balanced", t("cli.yes") if not rep["unbalanced"] else rep["unbalanced"]))
    total = db.scalar(con, "SELECT COALESCE(SUM(amount), 0) FROM posting")
    print(t("cli.check_total", total))
    ok = rep["ok"] and total == 0
    print("\n" + t("cli.sound" if ok else "cli.not_sound"))
    return 0 if ok else 1


def cmd_backup(a):
    from ledger import backup
    con = db.connect(a.db)
    out = backup.run(con, why=a.why)
    print(t("cli.copied", out["file"], f"{out['entries']:,}"))
    if out["second"]:
        print(t("cli.copied_second", out["second"]) if out["second_ok"]
              else t("cli.copied_second_failed", out["second"], out["second_error"]))
    else:
        print(t("cli.no_second"))
    return 0 if out["second_ok"] is not False else 1


def _open_on(db_path):
    """Where the app is open on these books, if it is. Replacing the books or
    the code under it leaves it running: old code against books a newer
    version has changed, or its screens on books that are no longer there."""
    from ledger import server
    return server.running_at(server.PORT, Path(db_path).resolve())


def cmd_restore(a):
    from ledger import backup
    here = _open_on(a.db)
    if here:
        print(t("cli.open_stop_first", here))
        return 1
    if not a.yes:
        print(t("cli.restore_warn"))
        print("\n" + t("cli.restore_copies"))
        for f in backup.copies(a.db)[-12:]:
            print("  ", f)
        return 1
    out = backup.restore(a.db, a.file)
    print(t("cli.restored", f"{out['entries']:,}", out["restored_from"]))
    if out["previous_kept_as"]:
        print(t("cli.restored_kept", out["previous_kept_as"]))
    return 0


def cmd_update(a):
    from ledger import update
    info = update.check()
    print(t("cli.versions", info["current"], info["latest"]))
    if not info["newer"]:
        print(t("cli.nothing_to_do"))
        return 0
    if a.check:
        return 0
    here = _open_on(a.db)
    if here:
        print(t("cli.open_update_there", here))
        return 1
    con = db.connect(a.db)
    out = update.download_and_apply(con)
    print(t("cli.updated", out["to"], out["books_copy"]))
    print(t("cli.old_code", out["old_code"]))
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
            print(t("cli.pos_connected", p.get("db"), p.get("who"), p.get("tickets"),
                    p.get("open_periods")))
            return 0
        if a.what == "nights":
            for r in db.all_(con, "SELECT night, SUM(tickets) t, SUM(takings) k, SUM(unpaid) u "
                                  "FROM pos_period WHERE tickets > 0 GROUP BY night ORDER BY night"):
                line = t("cli.pos_night", r["night"], f"{r['t']:>4}", f"{r['k']:>12,}")
                print(line + (t("cli.pos_night_unpaid", f"{r['u']:,}") if r["u"] else ""))
            return 0
        if a.what == "import":
            if not a.files:
                print(t("cli.pos_name_files"))
                return 1
            lines = []
            for f in a.files:
                lines += pos.keep(con, sources.read_backup(f), t("pos.kept_from", Path(f).name))
        else:
            print(t("cli.pos_reading", s["database"], s["server"]))
            lines = pos.keep(con, sources.read_live(s["server"], s["database"]),
                             t("pos.kept_live"))
    except sources.PosError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1
    lines = [l for l in lines if l["tickets"]]
    if not lines:
        print(t("cli.pos_no_tickets"))
        return 1
    worry = False
    for night in sorted({l["night"] for l in lines}):
        n = archive.night(con, night)
        print("\n" + t("cli.pos_kept_night", night, n["tickets"], f"{n['takings']:,}"), end="")
        if n["unpaid"]:
            worry = True
            print(t("cli.pos_kept_unpaid", f"{n['unpaid']:,}", n["open_tickets"]))
        else:
            print(t("cli.pos_kept_paid"))
        if n["documents"]:
            moved = [d for d in n["documents"] if not d["reversed"]]
            print(t("cli.pos_kept_records", len(moved), f"{n['drawer_out']:,}")
                  + (t("cli.pos_kept_records_in", f"{n['drawer_in']:,}") if n["drawer_in"] else ""))
        if not n["ended"] and a.what == "save":
            print(t("cli.pos_still_open_save"))
        elif not n["ended"]:
            print(t("cli.pos_was_open"))
    if a.what == "save":
        if worry:
            print("\n" + t("cli.pos_close_tickets"))
        else:
            print("\n" + t("cli.pos_safe"))
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
    print(t("cli.closed", a.month, f"{out['result']['net']:,}"))
    for w in out["warnings"]:
        print(t("cli.note", w))
    return 0


def cmd_sql(a):
    """Read-only, so a typo cannot change the books."""
    con = db.connect(a.db, migrate=False, readonly=True)
    rows = db.all_(con, a.query)
    if not rows:
        print(t("cli.no_rows"))
        return 0
    cols = rows[0].keys()
    width = {c: max(len(c), *(len(str(r[c])) for r in rows)) for c in cols}
    print("  ".join(c.ljust(width[c]) for c in cols))
    print("  ".join("-" * width[c] for c in cols))
    for r in rows:
        print("  ".join(str(r[c]).ljust(width[c]) for c in cols))
    print("\n" + t("cli.rows", len(rows)))
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="twilight", description=t("cli.help"),
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=db.DEFAULT_DB, help=t("cli.help_db"))
    sub = ap.add_subparsers(dest="cmd")

    s = sub.add_parser("serve", help=t("cli.help_serve"))
    s.add_argument("--port", type=int, default=8788)
    s.add_argument("--no-browser", action="store_true")
    s.set_defaults(fn=cmd_serve)

    s = sub.add_parser("window", help=t("cli.help_window"))
    s.set_defaults(fn=cmd_window)

    s = sub.add_parser("icon", help=t("cli.help_icon"))
    s.set_defaults(fn=cmd_icon)

    s = sub.add_parser("check", help=t("cli.help_check"))
    s.set_defaults(fn=cmd_check)

    s = sub.add_parser("backup", help=t("cli.help_backup"))
    s.add_argument("--why", default="manual")
    s.set_defaults(fn=cmd_backup)

    s = sub.add_parser("restore", help=t("cli.help_restore"))
    s.add_argument("file")
    s.add_argument("--yes", action="store_true")
    s.set_defaults(fn=cmd_restore)

    s = sub.add_parser("update", help=t("cli.help_update"))
    s.add_argument("--check", action="store_true", help=t("cli.help_update_check"))
    s.set_defaults(fn=cmd_update)

    s = sub.add_parser("pos", help=t("cli.help_pos"))
    s.add_argument("what", choices=["save", "import", "test", "nights"])
    s.add_argument("files", nargs="*", help=t("cli.help_pos_files"))
    s.set_defaults(fn=cmd_pos)

    s = sub.add_parser("import", help=t("cli.help_import"))
    s.add_argument("file")
    s.add_argument("--as-is", action="store_true",
                   help=t("cli.help_as_is"))
    s.set_defaults(fn=cmd_import)

    s = sub.add_parser("verify", help=t("cli.help_verify"))
    s.add_argument("file")
    s.set_defaults(fn=cmd_verify)

    s = sub.add_parser("close", help=t("cli.help_close"))
    s.add_argument("month")
    s.add_argument("--dry-run", action="store_true",
                   help=t("cli.help_dry_run"))
    s.set_defaults(fn=cmd_close)

    s = sub.add_parser("sql", help=t("cli.help_sql"))
    s.add_argument("query")
    s.set_defaults(fn=cmd_sql)

    argv = sys.argv[1:] if argv is None else argv
    a = ap.parse_args(argv)
    if not getattr(a, "fn", None):
        a = ap.parse_args([*argv, "serve"])
    a.argv = argv
    try:
        return a.fn(a) or 0
    except db.LedgerError as exc:
        print(f"\n{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
