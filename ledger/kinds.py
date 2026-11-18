"""The kinds of entry, and what each is called (in the words, kind.*).

One list, because the old app spelled these out separately in the entry form,
the entry list, the print slips and the money-flow card, and they drifted.
"""
from .words import kurdish, t

KINDS = (
    "daily_sales",
    "other_income",
    "daily_expense",
    "staff_advance",
    "staff_repayment",
    "salary_payment",
    "salary_charge",
    "supplier_payment",
    "receipt_credit",
    "receipt_cash",
    "fixed_charge",
    "fixed_payment",
    "electricity_charge",
    "electricity_payment",
    "partner_draw",
    "partner_in",
    "transfer",
    "cash_difference",
    "opening",
    "cogs",
    "stock_difference",
    "profit_share",
)

# What a person can correct from the Books screen. Everything else is written
# by the app itself — charges, closing entries, opening balances — and is put
# right by changing what it was worked out from, not by editing the entry.
EDITABLE = {
    "daily_sales", "other_income", "daily_expense", "staff_advance",
    "staff_repayment", "salary_payment", "supplier_payment", "fixed_payment",
    "electricity_payment", "partner_draw", "partner_in", "transfer",
    "receipt_credit", "receipt_cash",
}

# Deleting is allowed for a few more: a write-off can be undone.
DELETABLE = EDITABLE | {"cash_difference"}


def label(kind):
    return t(f"kind.{kind}") if kind in KINDS else str(kind or "").replace("_", " ")


def labels():
    """{kind: what it is called}, for every kind."""
    return {k: label(k) for k in KINDS}


def called(word):
    """The kinds whose name has `word` in it, in English or in Kurdish: the
    screens can be in either, and the search box is asked what they show."""
    word = word.lower()
    ckb = kurdish()
    return [k for k in KINDS
            if word in label(k).lower() or word in ckb.get(f"kind.{k}", "").lower()]
