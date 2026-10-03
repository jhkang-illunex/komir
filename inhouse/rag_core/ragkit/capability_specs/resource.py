"""Existing resource IR field allowances, not population or unit guarantees."""

PRODUCTION_IR_FIELDS = frozenset({
    "production", "production_volume", "value", "country", "country_code", "year", "period", "unit",
})
RESERVES_IR_FIELDS = frozenset({
    "reserves", "reserves_volume", "value", "country", "country_code", "year", "period", "unit",
})
