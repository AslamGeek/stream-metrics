"""Configurable thresholds for insight rules."""

THRESHOLDS = {
    "material_change_pct": 10.0,
    "concentration_pct": 70.0,
    "slow_moving_age_days": 180,
    "low_qoh_units": 10,
    "strong_sales_units": 20,
    "sustained_periods": 3,
    "price_tolerance_pct": 5.0,
}

APP_TITLE = "Sales Intelligence"
DEFAULT_WORKBOOK = "data/Sales_Data.xlsx"
