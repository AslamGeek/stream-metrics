"""Reusable calculations. No Streamlit dependencies."""

import pandas as pd
from data_layer import sales_rows


def monthly_sales(data):
    totals = data["MONTHLY_TOTALS"]
    if not totals.empty and "Sale_Value" in totals:
        return totals.groupby("Month", as_index=False)["Sale_Value"].sum().sort_values("Month")
    rows = sales_rows(data)
    return rows.groupby("Month", as_index=False)["Value"].sum().rename(columns={"Value": "Sale_Value"}).sort_values("Month")


def period_comparison(data):
    m = monthly_sales(data)
    if len(m) < 2:
        return None
    prev, cur = m.iloc[-2], m.iloc[-1]
    change = cur.Sale_Value - prev.Sale_Value
    return {"previous": prev.Month, "current": cur.Month, "previous_sales": float(prev.Sale_Value), "current_sales": float(cur.Sale_Value), "change": float(change), "growth_pct": (change / prev.Sale_Value * 100) if prev.Sale_Value else None}


def product_change(data):
    rows = sales_rows(data)
    if rows.empty or rows.Month.nunique() < 2:
        return pd.DataFrame()
    periods = sorted(rows.Month.dropna().unique())
    cur, prev = periods[-1], periods[-2]
    p = rows[rows.Month.isin([prev, cur])].pivot_table(index="Product", columns="Month", values="Value", aggfunc="sum", fill_value=0)
    p["Change"] = p[cur] - p[prev]
    p["Change_Pct"] = p.apply(lambda r: (r["Change"] / r[prev] * 100) if r[prev] else None, axis=1)
    p["Previous"] = p[prev]; p["Current"] = p[cur]
    return p.reset_index().sort_values("Change")


def agency_trends(data):
    t = data["MONTHLY_TOTALS"]
    if t.empty:
        return pd.DataFrame()
    return t.pivot_table(index="Month", columns="Agency", values="Sale_Value", aggfunc="sum").sort_index()


def kpis(data):
    rows = sales_rows(data)
    t = data["MONTHLY_TOTALS"]
    m = monthly_sales(data)
    growth = period_comparison(data)
    closing = t.groupby("Month")["Closing_Value"].sum().iloc[-1] if not t.empty else rows.groupby("Month")["Value"].sum().iloc[-1] if not rows.empty else 0
    config = data["PRODUCT_CONFIG"]
    active_products = config["Your_Status"].astype(str).str.upper().eq("ACTIVE").sum() if "Your_Status" in config else rows.Product.nunique()
    changes = product_change(data)
    doctors = data["DOCTORS"]
    active_doctors = doctors[doctors.get("Active", pd.Series("YES", index=doctors.index)).astype(str).str.upper().eq("YES")]
    high_potential = active_doctors[active_doctors.get("Potential", pd.Series(dtype=str)).astype(str).str.upper().isin(["A", "B"])].shape[0]
    links = data["DOCTOR_PRODUCTS"]
    doctor_products = int(links["Product_SKU"].nunique()) if "Product_SKU" in links else 0
    if "Your_SKU" in config:
        catalog_products = int(config.loc[config.get("Your_Status", pd.Series(index=config.index, dtype=str)).astype(str).str.upper().eq("ACTIVE"), "Your_SKU"].dropna().nunique())
    else:
        catalog_products = int(rows.Product.nunique())
    potential_profiles = high_potential * catalog_products
    eligible_ids = set(active_doctors[active_doctors.get("Potential", pd.Series(dtype=str)).astype(str).str.upper().isin(["A", "B"])].Doctor_ID.dropna()) if "Doctor_ID" in active_doctors else set()
    if {"Doctor_ID", "Product_SKU"}.issubset(links.columns):
        valid_links = links[links.Doctor_ID.isin(eligible_ids)]
        if "Active" in valid_links:
            valid_links = valid_links[valid_links.Active.astype(str).str.upper().eq("YES")]
        recorded_pairs = valid_links[["Doctor_ID", "Product_SKU"]].dropna().drop_duplicates().shape[0]
    else:
        recorded_pairs = 0
    return {
        "total_sales": float(m.iloc[-1].Sale_Value) if not m.empty else 0,
        "mom_growth": growth["growth_pct"] if growth else None,
        "purchase_value": float(t[t.Month == t.Month.max()].Purchase_Value.sum()) if not t.empty else 0,
        "closing_inventory": float(closing),
        "active_products": int(active_products),
        "products_growing": int((changes.Change > 0).sum()),
        "products_declining": int((changes.Change < 0).sum()),
        "high_potential_doctors": high_potential,
        "doctor_product_opportunities": max(0, potential_profiles - recorded_pairs),
    }


def data_quality(data):
    rows = sales_rows(data)
    out = []
    for sheet, frame in data.items():
        out.append({"Sheet": sheet, "Rows": len(frame), "Columns": len(frame.columns), "Empty": frame.empty})
    checks = []
    if not rows.empty:
        checks.extend([
            ("Missing product mapping", rows.Product.isna().sum()),
            ("Missing month", rows.Month.isna().sum()),
            ("Duplicate source lines", rows.duplicated([c for c in ["Statement_ID", "Source_Line_No"] if c in rows]).sum()),
            ("Negative sales values", (rows.Value < 0).sum()),
            ("Negative QOH", (rows.QOH < 0).sum()),
        ])
    return pd.DataFrame(out), pd.DataFrame(checks, columns=["Check", "Rows affected"])
