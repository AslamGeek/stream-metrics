"""Workbook loading, normalization, and source-row traceability."""

from pathlib import Path
import pandas as pd

PRIMARY_SHEETS = [
    "SALES_RAW", "MONTHLY_TOTALS", "PRODUCT_MAP", "PRODUCT_CONFIG", "DOCTORS",
    "PHARMACIES", "DOCTOR_PRODUCTS", "PRICE_LIST",
]


def load_workbook(path: str | Path) -> dict[str, pd.DataFrame]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Workbook not found: {path}")
    sheets = pd.read_excel(path, sheet_name=None, engine="openpyxl")
    result = {}
    for name in PRIMARY_SHEETS:
        frame = sheets.get(name, pd.DataFrame()).copy()
        frame.columns = [str(c).strip() for c in frame.columns]
        result[name] = frame
    sales = result["SALES_RAW"]
    for col in ("Month", "Period_Start", "Period_End"):
        if col in sales:
            sales[col] = pd.to_datetime(sales[col], errors="coerce")
    for col in ("O_Stk", "Purc", "Tot", "Sale", "QOH", "Value", "Age"):
        if col in sales:
            sales[col] = pd.to_numeric(sales[col], errors="coerce").fillna(0)
    totals = result["MONTHLY_TOTALS"]
    for col in ("Month", "Period_Start", "Period_End"):
        if col in totals:
            totals[col] = pd.to_datetime(totals[col], errors="coerce")
    for col in ("Opening_Value", "Purchase_Value", "Sale_Value", "Closing_Value"):
        if col in totals:
            totals[col] = pd.to_numeric(totals[col], errors="coerce").fillna(0)
    return result


def sales_rows(data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """Return sales rows with stable source identifiers for drill-down."""
    frame = data["SALES_RAW"].copy()
    if not frame.empty:
        frame["Source_Row"] = frame.get("Source_PDF", "Workbook").astype(str) + " · line " + frame.get("Source_Line_No", pd.Series(frame.index, index=frame.index)).astype(str)
        frame["Product"] = frame.get("Canonical_Product", pd.Series(dtype=str)).fillna("").replace("", pd.NA).fillna(frame.get("Product_Name", "Unknown"))
    return frame
