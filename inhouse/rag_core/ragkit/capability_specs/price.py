"""Existing price declarations, without source aliases or execution policy."""

PRICE_CRITERION_MODES = frozenset({"REPRESENTATIVE", "EXPLICIT", "ALL"})
PRICE_IDENTITY_FIELDS = ("price_measure", "price_criterion", "price_measure_label", "price_criterion_serial")
# Projection allowance for overview/series, NOT guaranteed populated fields.
PRICE_ALLOWED_OUTPUT_FIELDS = frozenset({
    "mineral", "price", "date", "unit", "price_criterion", "price_criterion_serial",
    "price_measure", "price_measure_label", "source", "provenance",
})
# The unresolved-metric IR fallback is distinct from capability output fields.
PRICE_CHANGE_IR_FIELDS = frozenset({
    "price_change", "price_change_rate", "pct_change", "change_pct", "date", "period",
})
