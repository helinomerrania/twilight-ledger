"""SambaPOS: keeping a copy of each night before the reset deletes it.

SambaPOS runs on its own SQL Server database, and every night the reset task
deletes that night's tickets, orders and payments. Whatever is not copied
out before then is gone. This package copies it out, two ways:

  * from a SambaPOS backup (.zip or .bak), read directly — no SQL Server
    needed, so it also works on old backups and on any PC
  * straight from SambaPOS's database while it is running, through
    Windows' own PowerShell and Windows' own login, read-only

Both produce the same snapshot, and archive.py keeps it. Nothing here writes
to SambaPOS, and nothing here touches the books until a night's takings are
deliberately used as that night's sales.
"""
