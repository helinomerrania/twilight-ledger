"""Where a copy of SambaPOS comes from: a backup file, or the live database.

Either way the result is the same snapshot:

    {"source": "backup:SambaPOS5_202611100230SQM.zip",
     "tables": {"Tickets": [{"Id": 2100, "Date": datetime(...), ...}, ...], ...}}

with the same Python types whichever way it came, so archive.py never needs
to know.
"""
import json
import os
import re
import shutil
import subprocess
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path

from . import bak

# What is read, and as what. A column some version of SambaPOS does not have
# is simply missing from the snapshot; a table it does not have is empty.
TABLES = {
    "WorkPeriods": {"Id": "int", "StartDate": "dt", "EndDate": "dt",
                    "StartByName": "str", "EndByName": "str"},
    "Tickets": {"Id": "int", "TicketNumber": "str", "Date": "dt",
                "LastPaymentDate": "dt", "IsClosed": "bool",
                "RemainingAmount": "dec", "TotalAmount": "dec", "Note": "str",
                "TransactionDocument_Id": "int"},
    "Orders": {"Id": "int", "TicketId": "int", "MenuItemId": "int",
               "MenuItemName": "str", "PortionName": "str", "Price": "dec",
               "Quantity": "dec", "CalculatePrice": "bool", "CreatedDateTime": "dt"},
    "Payments": {"Id": "int", "TicketId": "int", "Name": "str", "Date": "dt",
                 "Amount": "dec", "AccountTransactionId": "int", "PaymentTypeId": "int"},
    "Calculations": {"Id": "int", "TicketId": "int", "Name": "str",
                     "CalculationAmount": "dec"},
    "MenuItems": {"Id": "int", "Name": "str", "GroupCode": "str", "Barcode": "str"},
    "TicketEntities": {"Id": "int", "Ticket_Id": "int", "EntityName": "str"},
    # everything else that moved money: expenses, advances, cash in and out
    "AccountTransactionDocuments": {"Id": "int", "Date": "dt", "DocumentTypeId": "int",
                                    "Name": "str", "UserName": "str"},
    "AccountTransactionDocumentTypes": {"Id": "int", "Name": "str", "ButtonHeader": "str"},
    "AccountTransactions": {"Id": "int", "AccountTransactionDocumentId": "int",
                            "IsReversed": "bool"},
    "AccountTransactionValues": {"Id": "int", "AccountTransactionId": "int",
                                 "AccountTransactionDocumentId": "int",
                                 "AccountTypeId": "int", "AccountId": "int", "Date": "dt",
                                 "Debit": "dec", "Credit": "dec", "Name": "str"},
    "Accounts": {"Id": "int", "Name": "str", "AccountTypeId": "int"},
    "AccountTypes": {"Id": "int", "Name": "str"},
    # SambaPOS's own lists, kept for later steps (catalog.py). Users is never
    # read: it holds passwords and PINs.
    "PaymentTypes": {"Id": "int", "Name": "str", "Account_Id": "int"},
    "MenuItemPortions": {"Id": "int", "MenuItemId": "int", "Name": "str",
                         "Multiplier": "dec"},
    "MenuItemPrices": {"Id": "int", "MenuItemPortionId": "int", "Price": "dec",
                       "PriceTag": "str"},
    "InventoryItems": {"Id": "int", "Name": "str", "GroupCode": "str", "BaseUnit": "str",
                       "TransactionUnit": "str", "TransactionUnitMultiplier": "dec",
                       "Barcode": "str", "DefaultBaseUnitCost": "dec"},
    "Recipes": {"Id": "int", "Name": "str", "PortionId": "int", "FixedCost": "dec"},
    "RecipeItems": {"Id": "int", "RecipeId": "int", "InventoryItem_Id": "int",
                    "Quantity": "dec"},
}

MAX_BAK = 1024 ** 3                 # a SambaPOS database is a few megabytes
BACKUP_NAME = re.compile(r"(\d{12})", re.ASCII)


class PosError(Exception):
    """Something about SambaPOS that the person can act on."""


# ------------------------------------------------------------------ values

def coerce(kind, v):
    """One value, whichever way it arrived, as the type the archive expects."""
    if v is None:
        return None
    if kind == "int":
        return int(v)
    if kind == "dec":
        try:
            return v if isinstance(v, Decimal) else Decimal(str(v))
        except InvalidOperation as exc:
            raise PosError(f"SambaPOS sent {v!r} where a number belongs") from exc
    if kind == "dt":
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(str(v).replace("Z", "")[:26])
    if kind == "bool":
        if isinstance(v, str):
            return v.strip().lower() in ("1", "true", "yes")
        return bool(v)
    return str(v)


def _rows(value):
    """A list of rows. Older PowerShell can hand back a lone row on its own
    rather than in a list of one."""
    if value is None:
        return []
    return [value] if isinstance(value, dict) else list(value)


def normalise(tables):
    out = {}
    for name, cols in TABLES.items():
        out[name] = [{c: coerce(kind, row[c]) for c, kind in cols.items() if c in row}
                     for row in _rows(tables.get(name))]
    return out


# ----------------------------------------------------------------- backups

def read_backup(path):
    """A SambaPOS backup — the .zip SambaPOS makes, or the .bak inside it."""
    path = Path(path)
    if not path.is_file():
        raise PosError(f"there is no file at {path}")
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as z:
            baks = [i for i in z.infolist()
                    if i.filename.lower().endswith(".bak") and not i.is_dir()]
            if not baks:
                raise PosError(f"{path.name} has no database backup in it")
            info = max(baks, key=lambda i: i.file_size)
            if info.file_size > MAX_BAK:
                raise PosError(f"{path.name} is far larger than a SambaPOS backup")
            data = z.read(info)
    else:
        if path.stat().st_size > MAX_BAK:
            raise PosError(f"{path.name} is far larger than a SambaPOS backup")
        data = path.read_bytes()
    try:
        b = bak.Backup(data)
    except bak.BakError as exc:
        raise PosError(f"{path.name} could not be read: {exc}") from exc
    if "Tickets" not in b.table_names():
        raise PosError(f"{path.name} is a database backup, but not SambaPOS's")
    tables = {name: b.rows(name, set(cols)) for name, cols in TABLES.items()}
    return {"source": f"backup:{path.name}", "at": backup_time(path),
            "tables": normalise(tables)}


def backup_time(path):
    """When a backup was made: from the name SambaPOS gives it
    (SambaPOS5_202611100230SQM.zip), else from the file."""
    m = BACKUP_NAME.search(Path(path).name)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y%m%d%H%M")
        except ValueError:
            pass
    return datetime.fromtimestamp(Path(path).stat().st_mtime)


def backups_in(folder):
    """Every SambaPOS backup in a folder, oldest first."""
    folder = Path(folder or "")
    if not str(folder) or not folder.is_dir():
        raise PosError("choose the folder SambaPOS puts its backups in, in Setup")
    files = [p for p in folder.iterdir()
             if p.is_file() and p.suffix.lower() in (".zip", ".bak")]
    return sorted(files, key=lambda p: (backup_time(p), p.name))


# -------------------------------------------------------------------- live

SCRIPT = Path(__file__).with_name("sambapos.ps1")


def powershell():
    if os.name != "nt":
        return None
    return shutil.which("powershell") or shutil.which("powershell.exe")


def available():
    """Can this PC read SambaPOS's database directly? Only Windows can."""
    return bool(powershell())


def windows_user():
    if os.name != "nt":
        return None
    return f"{os.environ.get('USERDOMAIN', '')}\\{os.environ.get('USERNAME', '')}"


def run_powershell(request, timeout=180):
    """Ask SQL Server the questions in `request` through Windows PowerShell,
    signed in as whoever is running the app. Returns {name: rows}."""
    exe = powershell()
    if not exe:
        raise PosError("reading SambaPOS directly only works on the Windows PC it "
                       "runs on. Bring in a SambaPOS backup instead.")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        p = subprocess.run(
            [exe, "-NoLogo", "-NoProfile", "-NonInteractive",
             "-ExecutionPolicy", "Bypass", "-File", str(SCRIPT)],
            input=json.dumps(request).encode("ascii"), capture_output=True,
            timeout=timeout, creationflags=flags)
    except subprocess.TimeoutExpired as exc:
        raise PosError("SambaPOS's database took too long to answer") from exc
    except OSError as exc:
        raise PosError(f"PowerShell could not be started: {exc}") from exc
    out = p.stdout.decode("utf-8", "replace")
    m = re.search(r"<<TWILIGHT>>(.*)<<END>>", out, re.S)
    if p.returncode != 0 or not m:
        raise PosError(explain(p.stderr.decode("utf-8", "replace") or out, request))
    return json.loads(m.group(1))


def _clixml(text):
    """PowerShell sometimes reports errors as XML; pull the words out."""
    if not text.lstrip().startswith("#< CLIXML"):
        return text
    parts = re.findall(r'<S S="Error">(.*?)</S>', text, re.S)
    text = "".join(parts) if parts else text
    return (text.replace("_x000D__x000A_", "\n").replace("&lt;", "<")
                .replace("&gt;", ">").replace("&amp;", "&"))


def explain(stderr, request):
    """Turn what went wrong into what to do about it."""
    text = re.sub(r"\x1b\[[0-9;]*m", "", _clixml(stderr))
    server, database = request.get("server"), request.get("database")
    who = windows_user() or "this Windows account"
    if "Login failed" in text:
        return (f"SQL Server would not let {who} into {database}. Setup shows the "
                "three lines that give it permission to read.")
    if "Cannot open database" in text:
        return (f"There is no database called {database} on {server}, or {who} "
                "may not open it. Check the name in Setup.")
    if ("network-related" in text or "was not found or was not accessible" in text
            or "error: 26" in text or "error: 40" in text):
        return (f"No SQL Server answered at {server}. Is SambaPOS running? If it "
                "is, check the server name in Setup.")
    if "Invalid object name" in text:
        return f"{database} is a database, but not SambaPOS's: it has no tickets."
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    # newer PowerShell puts the message last, after a "|"; Windows PowerShell
    # puts it first, before "At line ..." and the "+ ~~~" underlining
    piped = [l.lstrip("|").strip() for l in lines if l.startswith("|")]
    piped = [l for l in piped if l and set(l) - set("~ ")]
    plain = [l for l in lines if not l.startswith(("At ", "+", "|", "Line ", "CategoryInfo",
                                                   "FullyQualifiedErrorId"))]
    reason = piped[-1] if piped else (plain[0] if plain else "no reason given")
    return "SambaPOS's database could not be read: " + reason


def _columns_sql():
    names = ", ".join(f"'{t}'" for t in TABLES)
    return ("SELECT TABLE_NAME AS t, COLUMN_NAME AS c FROM INFORMATION_SCHEMA.COLUMNS "
            f"WHERE TABLE_SCHEMA = 'dbo' AND TABLE_NAME IN ({names})")


def _settings(server, database):
    server = str(server or "").strip()
    database = str(database or "").strip()
    if not server or not database:
        raise PosError("give SambaPOS's server and database in Setup first")
    if not re.fullmatch(r"[\w.\\,:() -]{1,128}", server) \
            or not re.fullmatch(r"[\w .-]{1,128}", database):
        raise PosError("that server or database name has characters it cannot have")
    return server, database


def read_live(server, database, runner=None):
    """Everything SambaPOS holds right now, read straight from its database."""
    server, database = _settings(server, database)
    runner = runner or run_powershell
    base = {"server": server, "database": database}
    have = runner({**base, "queries": [{"name": "columns", "sql": _columns_sql()}]})
    present = {}
    for r in _rows(have.get("columns")):
        present.setdefault(r["t"], set()).add(r["c"])
    if "Tickets" not in present:
        raise PosError(f"{database} is a database, but not SambaPOS's: it has no tickets.")
    queries = []
    for table, cols in TABLES.items():
        use = [c for c in cols if c in present.get(table, ())]
        if use:
            queries.append({"name": table, "sql": "SELECT " + ", ".join(f"[{c}]" for c in use)
                                                  + f" FROM [dbo].[{table}]"})
    tables = runner({**base, "queries": queries})
    return {"source": f"live:{database}", "at": datetime.now(), "tables": normalise(tables)}


def test_live(server, database, runner=None):
    """Can SambaPOS be read? Says who signed in and what is there now."""
    server, database = _settings(server, database)
    runner = runner or run_powershell
    out = runner({"server": server, "database": database, "queries": [{
        "name": "probe",
        "sql": ("SELECT DB_NAME() AS db, SUSER_SNAME() AS who, "
                "(SELECT COUNT(*) FROM [dbo].[Tickets]) AS tickets, "
                "(SELECT COUNT(*) FROM [dbo].[WorkPeriods] "
                " WHERE EndDate <= StartDate) AS open_periods")}]})
    rows = _rows(out.get("probe")) or [{}]
    return rows[0]
