"""The kinds of entry, in the words the screens use.

One list, because the old app spelled these out separately in the entry form,
the entry list, the print slips and the money-flow card, and they drifted.
"""

LABELS = {
    "daily_sales": "Sales",
    "other_income": "Other income",
    "daily_expense": "Expense",
    "staff_advance": "Staff advance",
    "staff_repayment": "Staff paid money back",
    "salary_payment": "Salary paid",
    "salary_charge": "Salary charged",
    "supplier_payment": "Supplier paid",
    "receipt_credit": "Goods in, on credit",
    "receipt_cash": "Goods in, paid cash",
    "fixed_charge": "Monthly charge",
    "fixed_payment": "Rent or monthly charge paid",
    "electricity_charge": "Electricity used",
    "electricity_payment": "Electricity paid",
    "partner_draw": "Partner took cash",
    "partner_in": "Partner put cash in",
    "transfer": "Moved between pots",
    "cash_difference": "Cash difference written off",
    "opening": "Opening balance",
    "cogs": "Cost of goods",
    "stock_difference": "Stock account adjustment",
    "profit_share": "Profit share",
}

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
    return LABELS.get(kind) or str(kind or "").replace("_", " ")
