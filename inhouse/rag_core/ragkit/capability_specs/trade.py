"""Equivalent legacy trade IR fallback fields; no share/amount equivalence."""

IMPORT_AMOUNT_IR_FIELDS = frozenset({
    "import_value", "import_amount", "import_amount_change", "value", "country", "period", "unit",
})
IMPORT_CHANGE_IR_FIELDS = frozenset({
    "import_change", "import_value_change", "import_amount_change", "change_pct", "country", "period", "unit",
})
