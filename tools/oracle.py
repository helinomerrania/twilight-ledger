"""The old app's arithmetic, reimplemented from its source, as an oracle.

This file exists to be *independent*. It reads the exported JSON and works out
the figures the way TwilightBooks did — same rounding, same order of
operations, floating point and all — so the new database can be checked
against it without the new code grading its own homework.

It is not part of the application. Nothing in ledger/ imports it.

Usage:  python3 tools/oracle.py path/to/twilight-books.json 2026-10
"""
import json
import sys
from calendar import monthrange


def num(v):
    if v is None or v == "":
        return 0
    try:
        f = float(v)
    except (TypeError, ValueError):
        return 0
    return f if f == f else 0


def mround(v, note=250):
    # JavaScript Math.round: halves go towards +Infinity, not away from zero
    if note <= 1:
        return v
    import math
    return math.floor(v / note + 0.5) * note


def ymd(d):
    return str(d)[:10]


def month_of(d):
    return ymd(d)[:7]


def month_range(m):
    y, mm = int(m[:4]), int(m[5:7])
    return f"{m}-01", f"{m}-{monthrange(y, mm)[1]:02d}"


def next_month(m):
    y, mm = int(m[:4]), int(m[5:7])
    return f"{y + 1}-01" if mm == 12 else f"{y}-{mm + 1:02d}"


class Old:
    def __init__(self, data, month):
        self.S = data
        self.setup = data.get("setup") or {}
        self.cb = data.get("cb") or []
        self.pu = data.get("pu") or []
        self.inv = data.get("inv") or {}
        self.closed = data.get("closed") or {}
        self.elec = data.get("elec") or {}
        self.month = month
        self.start, self.end = month_range(month)

    # ---------------------------------------------------------------- basics
    def in_per(self, d):
        return self.start <= ymd(d) <= self.end

    def sum_cb(self, type_, field, detail=None):
        t = 0.0
        for e in self.cb:
            if e.get("t") != type_:
                continue
            if not self.in_per(e.get("d")):
                continue
            if detail is not None and e.get("x") != detail:
                continue
            t += num(e.get(field))
        return t

    # ----------------------------------------------------------------- stock
    def cat_letter(self, c):
        return str(c or "").strip()[:1].upper()

    def tare_of(self, name):
        for x in self.setup.get("tare") or []:
            if x.get("name") == name:
                return num(x.get("g"))
        return 0

    def counts_for(self, date):
        d = self.inv.get(date) or {}
        return d.get("counts") or {}

    def has_counts(self, date):
        return bool(self.counts_for(date))

    def price_of(self, item, date):
        d = self.inv.get(date) or {}
        p = (d.get("prices") or {}).get(item.get("name"))
        return num(p) if p is not None else num(item.get("price"))

    def item_qty(self, item, counts):
        c = counts.get(item.get("name")) or {}
        cv = self.setup.get("conversions") or {}
        L = self.cat_letter(item.get("category"))
        gk = num(cv.get("gramsPerKilo")) or 1000
        gp = num(cv.get("gramsPerPack")) or 50
        pb = num(cv.get("packsPerBlock")) or 10
        bc = num(cv.get("blocksPerCarton")) or 12
        bk = num(cv.get("bucketsPerCarton")) or 2
        if L == "A":
            return max(num(c.get("g")) - self.tare_of(c.get("bucket")), 0) / gk
        if L == "B":
            per_block = pb * gp / gk
            return (num(c.get("cartons")) * bc * per_block
                    + num(c.get("blocks")) * per_block
                    + num(c.get("packs")) * (gp / gk))
        if L == "E":
            return num(c.get("cartons")) + num(c.get("buckets")) / bk
        return num(c.get("pkg")) + num(c.get("pcs")) / (num(item.get("per")) or 1)

    def stock_value(self, date):
        counts = self.counts_for(date)
        t = 0.0
        for it in self.setup.get("stockItems") or []:
            t += self.item_qty(it, counts) * self.price_of(it, date)
        return t

    def is_counted(self, date):
        d = self.inv.get(date) or {}
        return self.has_counts(date) or d.get("closing") is not None

    def valued_dates(self):
        return [d for d in sorted(self.inv) if self.is_counted(d)]

    def booked(self, date):
        if not date:
            return 0
        d = self.inv.get(date)
        if not d:
            return 0
        if d.get("closing") is not None and (
                self.closed.get(month_of(date)) or not self.has_counts(date)):
            return num(d["closing"])
        return mround(self.stock_value(date))

    def count_for_period(self):
        ds = [d for d in self.valued_dates() if d <= self.end]
        return ds[-1] if ds else None

    def opening_date(self):
        ds = [d for d in self.valued_dates() if d < self.start]
        return ds[-1] if ds else None

    def purchases_in(self):
        cd, od = self.count_for_period(), self.opening_date()
        use_window = bool(cd and cd >= self.start and od)
        frm = od if use_window else None
        to = cd if (cd and cd >= self.start) else None
        t = 0.0
        for p in self.pu:
            d = ymd(p.get("d"))
            if frm is not None:
                if frm < d <= to:
                    t += num(p.get("amt"))
            elif self.in_per(p.get("d")):
                t += num(p.get("amt"))
        return t

    def cogs(self):
        cd = self.count_for_period()
        closing = self.booked(cd) if cd else 0
        od = self.opening_date()
        opening = self.booked(od) if od else 0
        purch = self.purchases_in()
        raw = mround(opening + purch - closing)
        return {"opening": opening, "purchases": purch, "closing": closing,
                "value": max(0, raw), "raw": raw, "date": cd}

    # ----------------------------------------------------------- electricity
    def elec_factors(self):
        f = (self.elec or {}).get("factors") or {}

        def s(v, d):
            return d if v in (None, "") else num(v)
        return {"privateAmps": s(f.get("privateAmps"), 25),
                "elevatorAmps": s(f.get("elevatorAmps"), 20),
                "elevatorShare": num(f.get("elevatorShare")) or 6,
                "publicRate": s(f.get("publicRate"), 185),
                "publicShare": num(f.get("publicShare")) or 3}

    def elec_details(self):
        for t in self.setup.get("types") or []:
            if t.get("name") == "Monthly Bill":
                d = [x for x in (t.get("details") or []) if "electric" in str(x).lower()]
                if d:
                    return d
        return ["Electricity (Private)", "Electricity (Elevator)", "Electricity (Public)"]

    def elec_calc(self):
        f = self.elec_factors()
        rows = sorted((self.elec or {}).get("rows") or [], key=lambda r: r.get("m", ""))
        out, prev_now = [], None
        for r in rows:
            last = num(r["last"]) if r.get("last") not in (None, "") else prev_now
            now = num(r["now"]) if r.get("now") not in (None, "") else None
            units = (now - last) if (now is not None and last is not None) else None
            priv = mround(num(r.get("pp")) * f["privateAmps"]) if r.get("pp") else None
            elev = (mround(num(r.get("pe")) * f["elevatorAmps"] / f["elevatorShare"])
                    if r.get("pe") else None)
            pub = (mround(units * f["publicRate"] / f["publicShare"])
                   if units is not None else None)
            any_ = priv is not None or elev is not None or pub is not None
            total = (num(priv) + num(elev) + num(pub)) if any_ else None
            out.append({"m": r.get("m"), "total": total})
            if now is not None:
                prev_now = now
        return out

    def elec_charged(self, month):
        for x in self.elec_calc():
            if x["m"] == month and x["total"]:
                return x["total"]
        return 0

    def elec_in_period(self):
        t, m = 0.0, month_of(self.start)
        while m <= month_of(self.end):
            t += self.elec_charged(m)
            m = next_month(m)
        return t

    # ---------------------------------------------------------------- result
    def result(self):
        f = self.closed.get(self.month)
        if f and f.get("result"):
            return dict(f["result"], frozen=True)
        sales = self.sum_cb("Daily Sales", "in")
        other = self.sum_cb("Other Income", "in")
        rev = sales + other
        c = self.cogs()
        gross = rev - c["value"]
        el = self.elec_details()
        bills = sum(num(e.get("out")) for e in self.cb
                    if e.get("t") == "Monthly Bill" and self.in_per(e.get("d"))
                    and e.get("x") not in el)
        daily = self.sum_cb("Daily Expense", "out") + bills
        elec = self.elec_in_period()
        fixed = sum(num(x.get("amount")) for x in self.setup.get("fixedExpenses") or [])
        salaries = sum(num(x.get("salary")) for x in self.setup.get("staff") or [])
        opex = daily + elec + fixed + salaries
        return {"sales": sales, "other": other, "rev": rev, "cogs": c,
                "gross": gross, "daily": daily, "elec": elec, "fixed": fixed,
                "salaries": salaries, "opex": opex, "net": gross - opex,
                "frozen": False}

    # ------------------------------------------------------------------ cash
    def pots(self):
        return [p.get("name") for p in self.setup.get("pots") or []]

    def pot_balance(self, name, as_of=None):
        t = 0.0
        for e in self.cb:
            if as_of and ymd(e.get("d")) > as_of:
                continue
            p, p2 = e.get("p"), e.get("p2")
            if e.get("t") == "Cash Transfer":
                if p == name:
                    t -= num(e.get("out"))
                if p2 == name:
                    t += num(e.get("out"))
                continue
            if p != name:
                continue
            t += num(e.get("in")) - num(e.get("out"))
        return t

    def cash_on_hand(self, as_of=None):
        own = [p.get("name") for p in self.setup.get("pots") or []
               if p.get("kind") != "float"]
        return sum(self.pot_balance(n, as_of) for n in own)

    # -------------------------------------------------------------- suppliers
    def supplier_owed(self):
        """Total owed to suppliers, rebased at debt.asAt like the old app."""
        debt = self.S.get("debt") or {}
        as_at = debt.get("asAt")
        brought = debt.get("brought") or {}
        out = {}
        for s in self.setup.get("suppliers") or []:
            bf = num(brought.get(s))
            got = sum(num(p.get("amt")) for p in self.pu
                      if p.get("s") == s and (not as_at or ymd(p.get("d")) > as_at)
                      and p.get("terms") != "Cash")
            paid = sum(num(e.get("out")) for e in self.cb
                       if e.get("t") == "Supplier Payment" and e.get("x") == s
                       and (not as_at or ymd(e.get("d")) > as_at))
            out[s] = bf + got - paid
        return out


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "/home/claude/work/latest.json"
    months = sys.argv[2:] or ["2026-08", "2026-09", "2026-10", "2026-11"]
    data = json.load(open(path, encoding="utf-8"))
    report = {}
    for m in months:
        o = Old(data, m)
        r = o.result()
        report[m] = r
        print(f"=== {m}{'  (closed, frozen)' if r.get('frozen') else ''}")
        for k in ("sales", "other", "rev", "gross", "daily", "elec", "fixed",
                  "salaries", "net"):
            print(f"    {k:9} {r.get(k)}")
        c = r.get("cogs") or {}
        print(f"    cogs      opening {c.get('opening')}  bought {c.get('purchases')}"
              f"  closing {c.get('closing')}  = {c.get('value')}  (count {c.get('date')})")
    o = Old(data, months[-1])
    print("=== cash")
    for p in o.pots():
        print(f"    {p:10} {o.pot_balance(p)}")
    print(f"    on hand    {o.cash_on_hand()}")
    print("=== suppliers")
    owed = o.supplier_owed()
    for k, v in owed.items():
        print(f"    {k:20} {v}")
    print(f"    total owed {sum(max(v, 0) for v in owed.values())}")
    print(f"    (raw sum)  {sum(owed.values())}")
    return report


if __name__ == "__main__":
    main()
