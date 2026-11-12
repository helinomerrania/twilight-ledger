"""Read-only look at the SambaPOS database, so the archiver can be written
against what is actually there.

Why this exists: every published description of the SambaPOS V5 schema is from
2015 and names four tables without their columns. Guessing would produce an
archiver that works on a forum poster's install and silently drops half of
Mohammed's tickets. So this prints the real shape, he sends the output, and the
archiver is written against fact.

It is deliberately incapable of doing harm:

  * it opens the connection read-only where the driver allows it, and only
    ever runs SELECT and schema queries
  * it never prints an amount, a customer name, or anything else that is
    business data — only table names, column names, types and row counts, plus
    a count of tickets per day
  * it never writes, and it never touches the licence

It also needs its own login rather than `sa`. Create one once, in SQL Server
Management Studio or sqlcmd:

    CREATE LOGIN twilight_export WITH PASSWORD = '<something new and long>';
    USE SambaPOS5;                     -- or whatever the database is called
    CREATE USER twilight_export FOR LOGIN twilight_export;
    ALTER ROLE db_datareader ADD MEMBER twilight_export;

Then run, from the folder this file is in:

    python probe_sambapos.py --server localhost --database SambaPOS5 \
                             --user twilight_export

It will ask for the password rather than taking it on the command line, so it
does not end up in the shell history.
"""
import argparse
import getpass
from datetime import datetime

# Tables worth describing in full. Anything else is listed by name and row
# count only, to keep the output short enough to paste.
INTERESTING = ["Tickets", "Orders", "Payments", "WorkPeriods", "AccountTransactions",
               "AccountTransactionValues", "Accounts", "MenuItems", "TicketEntities",
               "Calculations", "PaymentTypes", "Departments", "Terminals"]

SAFE_PREFIXES = ("select", "with", "sp_columns", "exec sp_")


def connect(args):
    """Try the drivers people actually have, in the order they are likely to work."""
    errors = []
    password = args.password or getpass.getpass(
        f"Password for {args.user} on {args.server}: ")

    try:
        import pyodbc
        for driver in ("ODBC Driver 18 for SQL Server",
                       "ODBC Driver 17 for SQL Server",
                       "SQL Server Native Client 11.0",
                       "SQL Server"):
            try:
                extra = ";Encrypt=no;TrustServerCertificate=yes" \
                    if "18" in driver else ""
                con = pyodbc.connect(
                    f"DRIVER={{{driver}}};SERVER={args.server};"
                    f"DATABASE={args.database};UID={args.user};PWD={password}"
                    f";ApplicationIntent=ReadOnly{extra}", timeout=8)
                return con, f"pyodbc / {driver}"
            except Exception as exc:                       # noqa: BLE001
                errors.append(f"{driver}: {str(exc)[:120]}")
    except ImportError:
        errors.append("pyodbc is not installed (pip install pyodbc)")

    try:
        import pymssql
        con = pymssql.connect(server=args.server, user=args.user,
                              password=password, database=args.database,
                              login_timeout=8)
        return con, "pymssql"
    except ImportError:
        errors.append("pymssql is not installed (pip install pymssql)")
    except Exception as exc:                               # noqa: BLE001
        errors.append(f"pymssql: {str(exc)[:120]}")

    print("Could not connect. What was tried:")
    for e in errors:
        print("   ", e)
    print("\nIf none of the drivers are installed, the quickest fix is usually:")
    print("    pip install pyodbc")
    raise SystemExit(2)


def rows(cur, sql, args=()):
    low = sql.strip().lower()
    if not low.startswith(SAFE_PREFIXES):
        raise RuntimeError("this tool only runs SELECT statements")
    cur.execute(sql, args)
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r, strict=False)) for r in cur.fetchall()]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--server", default="localhost")
    ap.add_argument("--database", default="SambaPOS5")
    ap.add_argument("--user", default="twilight_export")
    ap.add_argument("--password", help="better to leave this out and be asked")
    ap.add_argument("--out", default="sambapos-shape.txt")
    a = ap.parse_args(argv)

    con, how = connect(a)
    cur = con.cursor()
    out = []

    def say(line=""):
        print(line)
        out.append(str(line))

    say(f"SambaPOS schema, read {datetime.now():%Y-%m-%d %H:%M} via {how}")
    say(f"database: {a.database}")
    say()

    tables = rows(cur, """
        SELECT t.name AS table_name, SUM(p.rows) AS row_count
          FROM sys.tables t
          JOIN sys.partitions p ON p.object_id = t.object_id AND p.index_id IN (0,1)
         GROUP BY t.name ORDER BY t.name""")
    say(f"{len(tables)} tables")
    say()

    say("== tables with rows ==")
    for t in sorted(tables, key=lambda r: -(r["row_count"] or 0)):
        if t["row_count"]:
            say(f"  {t['table_name']:<40} {t['row_count']:>9,}")
    say()

    names = {t["table_name"] for t in tables}
    say("== columns of the tables the archiver needs ==")
    for name in INTERESTING:
        if name not in names:
            say(f"  {name}: not in this database")
            continue
        say(f"  {name}")
        for c in rows(cur, """
                SELECT c.name, ty.name AS type, c.max_length, c.is_nullable
                  FROM sys.columns c
                  JOIN sys.types ty ON ty.user_type_id = c.user_type_id
                 WHERE c.object_id = OBJECT_ID(?)
                 ORDER BY c.column_id""", (name,)):
            say(f"      {c['name']:<34} {c['type']}"
                f"{'' if c['is_nullable'] else ' not null'}")
        say()

    # How much history is actually in there right now. Counts only — this is
    # what says whether a nightly archive would be catching everything.
    for table, column in (("Tickets", "Date"), ("Tickets", "LastPaymentTime"),
                          ("WorkPeriods", "StartDate")):
        if table not in names:
            continue
        try:
            got = rows(cur, f"""
                SELECT CAST([{column}] AS date) AS day, COUNT(*) AS n
                  FROM [{table}] GROUP BY CAST([{column}] AS date)
                 ORDER BY day DESC""")
        except Exception:                                   # noqa: BLE001
            continue
        if not got:
            continue
        say(f"== {table} by {column} ==")
        total = sum(r["n"] for r in got)
        say(f"  {len(got)} days, {total:,} rows"
            f"  (the trial starts warning at 500 tickets)")
        for r in got[:14]:
            say(f"      {r['day']}  {r['n']:>6,}")
        if len(got) > 14:
            say(f"      … and {len(got) - 14} earlier days")
        say()
        break

    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
    print(f"\nWritten to {a.out} — send that file.")
    print("It holds table and column names and row counts. No amounts, no "
          "names, no prices.")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
