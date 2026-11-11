"""Read the tables out of a SQL Server full backup (.bak) without SQL Server.

A .bak is a Microsoft Tape Format stream whose payload is, mostly, the
database's 8 KB pages copied as they are. Every page starts with a 96-byte
header saying which page it is and which allocation unit it belongs to, so
the pages can be found by scanning, and SQL Server's own catalog — the
system tables that say which tables exist, their columns, and where each
column sits in a row — decoded from them like any other table.

Read-only and offline: the file is only ever parsed, nothing in it is run.

What it can read is what a SambaPOS database needs: rows of tables with a
clustered index, fixed and variable columns, nulls, bits, and small values
of the (max) types, which SQL Server keeps in the row. Deleted rows are
skipped — which matters, because the nightly reset deletes rather than
truncates, and a page can still hold yesterday's tickets as ghosts.
"""
import struct
from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal

PAGE = 8192
DATA_PAGE = 1
KNOWN_PAGE_TYPES = {1, 2, 3, 4, 7, 8, 9, 10, 11, 13, 15, 16, 17, 18, 19, 20}

# allocation units of the system tables this reader needs (fixed in SQL Server)
AU_SYSRSCOLS = 196608
AU_SYSROWSETS = 327680
AU_SYSALLOCUNITS = 458752
AU_SYSSCHOBJS = (1 << 48) | (34 << 16)
AU_SYSCOLPARS = (1 << 48) | (41 << 16)

XTYPES = {34: "image", 35: "text", 36: "uniqueidentifier", 40: "date", 41: "time",
          42: "datetime2", 43: "datetimeoffset", 48: "tinyint", 52: "smallint",
          56: "int", 58: "smalldatetime", 59: "real", 60: "money", 61: "datetime",
          62: "float", 98: "sql_variant", 99: "ntext", 104: "bit", 106: "decimal",
          108: "numeric", 122: "smallmoney", 127: "bigint", 165: "varbinary",
          167: "varchar", 173: "binary", 175: "char", 189: "timestamp",
          231: "nvarchar", 239: "nchar", 241: "xml"}

FIXED_SIZES = {"int": 4, "bigint": 8, "smallint": 2, "tinyint": 1, "datetime": 8,
               "smalldatetime": 4, "money": 8, "smallmoney": 4, "float": 8,
               "real": 4, "uniqueidentifier": 16, "date": 3}


class BakError(ValueError):
    """The file is not something this reader can make sense of."""


def _u(b, fmt):
    return struct.unpack(fmt, b)[0]


# ------------------------------------------------------------------- pages

class Page:
    __slots__ = ("raw", "type", "index_id", "obj_id", "slot_cnt", "page_id",
                 "file_id", "lsn")

    def __init__(self, raw):
        self.raw = raw
        self.type = raw[1]
        self.index_id = _u(raw[6:8], "<H")
        self.slot_cnt = _u(raw[22:24], "<H")
        self.obj_id = _u(raw[24:28], "<i")
        self.page_id = _u(raw[32:36], "<I")
        self.file_id = _u(raw[36:38], "<H")
        self.lsn = struct.unpack_from("<IIH", raw, 40)

    @property
    def au(self):
        """The allocation unit, as SQL Server builds it from the header."""
        return (self.index_id << 48) | ((self.obj_id & 0xFFFFFFFF) << 16)

    def slots(self):
        out = []
        for i in range(self.slot_cnt):
            off = _u(self.raw[PAGE - 2 - 2 * i: PAGE - 2 * i], "<H")
            if 96 <= off < PAGE - 2 * self.slot_cnt:
                out.append(off)
        return out


def plausible(raw):
    """Does this 8 KB look like a page header rather than anything else?"""
    if len(raw) < PAGE or raw[0] != 1 or raw[1] not in KNOWN_PAGE_TYPES:
        return False
    slot_cnt = _u(raw[22:24], "<H")
    free_data = _u(raw[30:32], "<H")
    file_id = _u(raw[36:38], "<H")
    return 1 <= file_id <= 64 and 96 <= free_data <= PAGE and slot_cnt <= 4096


def scan(data):
    """Every page in the stream. Pages sit on 512-byte boundaries; if a page
    appears twice, the copy with the later log sequence number wins."""
    pages = {}
    view = memoryview(data)
    for off in range(0, len(data) - PAGE + 1, 512):
        if data[off] != 1 or data[off + 1] not in KNOWN_PAGE_TYPES:
            continue
        raw = bytes(view[off:off + PAGE])
        if not plausible(raw):
            continue
        p = Page(raw)
        old = pages.get((p.file_id, p.page_id))
        if old is None or p.lsn > old.lsn:
            pages[(p.file_id, p.page_id)] = p
    return pages


# ----------------------------------------------------------------- records

def record_parts(raw, off):
    """Split a row into its fixed bytes, null bitmap, and variable columns.

    Variable columns come back as (bytes, complex) pairs; `complex` marks a
    pointer to a value kept outside the row.
    """
    status_a = raw[off]
    fixed_end = _u(raw[off + 2:off + 4], "<H")
    if fixed_end < 4 or off + fixed_end + 2 > len(raw):
        raise BakError("not a row")
    fixed = raw[off + 4: off + fixed_end]
    pos = off + fixed_end
    ncols = _u(raw[pos:pos + 2], "<H")
    pos += 2
    nullmap = b""
    if status_a & 0x10:
        nb = (ncols + 7) // 8
        nullmap = raw[pos:pos + nb]
        pos += nb
    var = []
    if status_a & 0x20:
        nvar = _u(raw[pos:pos + 2], "<H")
        pos += 2
        start = pos + 2 * nvar
        for i in range(nvar):
            end = _u(raw[pos + 2 * i: pos + 2 * i + 2], "<H")
            complex_ = bool(end & 0x8000)
            end = off + (end & 0x7FFF)
            if end < start or end > len(raw):
                raise BakError("not a row")
            var.append((raw[start:end], complex_))
            start = end
    return {"type": (status_a >> 1) & 7, "fixed": fixed, "null": nullmap, "var": var}


def is_null(parts, bit):
    """`bit` is the 1-based position of the column in the null bitmap."""
    nm = parts["null"]
    if not nm or not bit:
        return False
    byte, b = divmod(bit - 1, 8)
    return byte >= len(nm) or bool(nm[byte] & (1 << b))


def records(pages):
    """The live rows on a set of pages: primary records only, so ghosts of
    deleted rows, forwarding stubs and index rows are all left out."""
    for p in pages:
        if p.type != DATA_PAGE:
            continue
        for off in p.slots():
            try:
                parts = record_parts(p.raw, off)
            except (BakError, struct.error, IndexError):
                continue
            if parts["type"] == 0:
                yield parts


# ------------------------------------------------------------------ values

EPOCH = datetime(1900, 1, 1)


def dt_datetime(b):
    """datetime: days since 1900 and three-hundredths of a second since midnight."""
    ticks, days = struct.unpack("<Ii", b)
    return EPOCH + timedelta(days=days, milliseconds=round(ticks * 10 / 3))


def dt_smalldatetime(b):
    minutes, days = struct.unpack("<HH", b)
    return EPOCH + timedelta(days=days, minutes=minutes)


def dt_datetime2(b, scale):
    tlen = len(b) - 3
    ticks = int.from_bytes(b[:tlen], "little")
    days = int.from_bytes(b[tlen:], "little")
    return datetime(1, 1, 1) + timedelta(days=days, microseconds=ticks * 10 ** (6 - scale)
                                         if scale <= 6 else ticks // 10 ** (scale - 6))


def decimal_of(b, scale):
    """decimal and numeric: a sign byte (1 is positive), then the digits as a
    little-endian integer."""
    v = int.from_bytes(b[1:], "little")
    d = Decimal(v).scaleb(-scale)
    return d if b[0] == 1 else -d


def money_of(b):
    if len(b) == 8:
        hi, lo = struct.unpack("<iI", b)
        return Decimal((hi << 32) | lo) / 10000
    return Decimal(_u(b, "<i")) / 10000


def fixed_size(col):
    return FIXED_SIZES.get(col["type"], col["length"])


def decode_fixed(col, b):
    t = col["type"]
    if t == "int":
        return _u(b, "<i")
    if t == "bigint":
        return _u(b, "<q")
    if t == "smallint":
        return _u(b, "<h")
    if t == "tinyint":
        return b[0]
    if t == "datetime":
        return dt_datetime(b)
    if t == "smalldatetime":
        return dt_smalldatetime(b)
    if t == "datetime2":
        return dt_datetime2(b, col["scale"])
    if t in ("money", "smallmoney"):
        return money_of(b)
    if t in ("decimal", "numeric"):
        return decimal_of(b, col["scale"])
    if t == "float":
        return _u(b, "<d")
    if t == "real":
        return _u(b, "<f")
    if t == "nchar":
        return b.decode("utf-16-le", "replace").rstrip()
    if t == "char":
        return b.decode("cp1252", "replace").rstrip()
    return b.hex()


def decode_var(col, b):
    t = col["type"]
    if t in ("nvarchar", "nchar", "ntext", "xml"):
        return b.decode("utf-16-le", "replace")
    if t in ("varchar", "char", "text"):
        return b.decode("cp1252", "replace")
    return b.hex()


# ----------------------------------------------------------------- tables

class Backup:
    """The tables in one backup, read from its bytes."""

    def __init__(self, data):
        self.pages = scan(data)
        if not self.pages:
            raise BakError("there are no database pages in that file")
        self.by_au = defaultdict(list)
        for p in self.pages.values():
            self.by_au[p.au].append(p)
        for ps in self.by_au.values():
            ps.sort(key=lambda p: p.page_id)
        self._catalog()

    def _recs(self, au):
        return list(records(self.by_au.get(au, [])))

    def _catalog(self):
        self.objects = {}
        for r in self._recs(AU_SYSSCHOBJS):
            f = r["fixed"]
            if len(f) < 19 or not r["var"]:
                continue
            oid = _u(f[0:4], "<i")
            self.objects[oid] = {"id": oid,
                                 "name": r["var"][0][0].decode("utf-16-le", "replace"),
                                 "type": f[13:15].decode("ascii", "replace").strip()}
        if not any(o["type"] == "U" for o in self.objects.values()):
            raise BakError("no tables could be found in that backup")

        self.columns = defaultdict(list)
        for r in self._recs(AU_SYSCOLPARS):
            f = r["fixed"]
            if len(f) < 27 or not r["var"]:
                continue
            if _u(f[4:6], "<h") != 0:
                continue                 # parameters of procedures live here too
            self.columns[_u(f[0:4], "<i")].append({
                "colid": _u(f[6:10], "<i"),
                "name": r["var"][0][0].decode("utf-16-le", "replace"),
                "type": XTYPES.get(f[10], str(f[10])),
                "length": _u(f[15:17], "<h"), "scale": f[18]})

        self.rowsets = {}
        for r in self._recs(AU_SYSROWSETS):
            f = r["fixed"]
            if len(f) >= 17:
                self.rowsets[_u(f[0:8], "<q")] = {"object": _u(f[9:13], "<i"),
                                                  "index": _u(f[13:17], "<i")}

        self.au_of = {}
        for r in self._recs(AU_SYSALLOCUNITS):
            f = r["fixed"]
            if len(f) >= 17 and f[8] == 1:          # in-row data
                self.au_of[_u(f[9:17], "<q")] = _u(f[0:8], "<q")

        # where each column of each rowset sits in a row:
        # rsid 0-8, rscolid 8-12, hbcolid 12-16, rcmodified 16-24, ti 24-28,
        # cid 28-32, ordkey 32-34, maxinrowlen 34-36, status 36-40,
        # offset 40-44, nullbit 44-48, bitpos 48-50
        self.layout = defaultdict(dict)
        for r in self._recs(AU_SYSRSCOLS):
            f = r["fixed"]
            if len(f) < 50:
                continue
            leaf = _u(f[40:44], "<i") & 0xFFFF
            if leaf & 0x8000:
                leaf -= 0x10000
            self.layout[_u(f[0:8], "<q")][_u(f[8:12], "<i")] = {
                "offset": leaf, "null_bit": _u(f[44:48], "<i") & 0xFFFF,
                "bitpos": _u(f[48:50], "<h")}

    def table_names(self):
        return sorted(o["name"] for o in self.objects.values() if o["type"] == "U")

    def _table(self, name):
        for o in self.objects.values():
            if o["type"] == "U" and o["name"].lower() == name.lower():
                return o
        return None

    def rows(self, name, columns=None):
        """Every live row of a table, as dicts. `columns` limits which are
        decoded; a column the table does not have is simply absent."""
        o = self._table(name)
        if o is None:
            return []
        rsid = next((rs for rs, v in self.rowsets.items()
                     if v["object"] == o["id"] and v["index"] in (0, 1)), None)
        if rsid is None:
            return []
        lay = self.layout.get(rsid, {})
        cols = [c for c in self.columns[o["id"]]
                if columns is None or c["name"] in columns]
        out = []
        for parts in records(self.by_au.get(self.au_of.get(rsid), [])):
            row = {}
            for c in cols:
                spot = lay.get(c["colid"])
                if spot is None:
                    continue
                if is_null(parts, spot["null_bit"]):
                    row[c["name"]] = None
                elif spot["offset"] > 0:                 # a fixed-width column
                    start = spot["offset"] - 4
                    if c["type"] == "bit":
                        row[c["name"]] = bool(parts["fixed"][start] & (1 << spot["bitpos"]))
                    else:
                        row[c["name"]] = decode_fixed(
                            c, parts["fixed"][start:start + fixed_size(c)])
                else:                                     # a variable one
                    i = -spot["offset"] - 1
                    if i >= len(parts["var"]):
                        row[c["name"]] = None             # trailing empty columns
                        continue
                    b, complex_ = parts["var"][i]
                    # a value kept outside the row is never something a
                    # till needs (ticket logs, layouts); leave it out
                    row[c["name"]] = None if complex_ else decode_var(c, b)
            out.append(row)
        return out
