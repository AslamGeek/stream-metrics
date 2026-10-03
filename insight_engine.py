"""Rule-based insight generation with evidence and source-row references."""

import pandas as pd
from config import THRESHOLDS
from data_layer import sales_rows
from analytics import monthly_sales, period_comparison, product_change


def _insight(title, severity, entity, period, observation, evidence, calculation, rows=None):
    return {"Title": title, "Severity": severity, "Entity": entity, "Period": period,
            "Observation": observation, "Evidence": evidence, "Calculation": calculation,
            "Source rows": rows or []}


def generate_insights(data, thresholds=None):
    t = {**THRESHOLDS, **(thresholds or {})}
    rows = sales_rows(data)
    insights = []
    comparison = period_comparison(data)
    period_label = "—"
    if comparison:
        period_label = f"{comparison['previous']:%b %Y} → {comparison['current']:%b %Y}"
        pct = comparison["growth_pct"]
        if pct is not None and abs(pct) >= t["material_change_pct"]:
            direction = "increased" if pct > 0 else "declined"
            insights.append(_insight(f"Overall sales {direction} {abs(pct):.1f}% month over month", "High" if pct < 0 else "Medium", "All agencies", period_label,
                f"Sales {direction} from ₹{comparison['previous_sales']:,.0f} to ₹{comparison['current_sales']:,.0f}.",
                f"Change: ₹{comparison['change']:,.0f} ({pct:+.1f}%).", "(current month sales − previous month sales) ÷ previous month sales × 100", rows[rows.Month.isin([comparison["previous"], comparison["current"]])]["Source_Row"].drop_duplicates().tolist()))

    changes = product_change(data)
    if not changes.empty:
        material = changes[changes.Change.abs() > 0].copy()
        for _, r in material.iterrows():
            if r.Change_Pct is not None and pd.notna(r.Change_Pct) and abs(r.Change_Pct) >= t["material_change_pct"]:
                direc = "growing" if r.Change > 0 else "declining"
                source = rows[(rows.Product == r.Product) & rows.Month.isin([comparison["previous"], comparison["current"]])]["Source_Row"].drop_duplicates().tolist() if comparison else []
                insights.append(_insight(f"{r.Product} sales {direc} {abs(r.Change_Pct):.1f}%", "High" if r.Change < 0 else "Low", r.Product, period_label,
                    f"Sales changed from ₹{r.Previous:,.0f} to ₹{r.Current:,.0f}.", f"Net change: ₹{r.Change:,.0f} ({r.Change_Pct:+.1f}%).",
                    "Product sales current month − product sales previous month; percentage change over previous month.", source))
        total_change = changes.Change.sum()
        falling = changes[changes.Change < 0].nsmallest(5, "Change")
        if total_change < 0 and not falling.empty:
            share = abs(falling.Change.sum()) / abs(total_change) * 100
            insights.append(_insight("Largest product declines account for a material share of the net sales change", "Medium", "Products", period_label,
                f"{len(falling)} products account for {share:.1f}% of the absolute net sales decline calculation.", "; ".join(f"{r.Product}: ₹{r.Change:,.0f}" for _, r in falling.iterrows()),
                "Absolute sum of five largest negative product changes ÷ absolute net change × 100", rows[rows.Product.isin(falling.Product)]["Source_Row"].drop_duplicates().tolist()))
        if len(changes) >= 2:
            latest = rows[rows.Month == rows.Month.max()].groupby("Product").Value.sum().sort_values(ascending=False)
            concentration = latest.head(max(1, (latest.cumsum() / latest.sum() < t["concentration_pct"] / 100).sum() + 1)).sum() / latest.sum() * 100 if latest.sum() else 0
            insights.append(_insight("Sales concentration", "Medium" if concentration >= t["concentration_pct"] else "Low", "Products", f"{rows.Month.max():%b %Y}",
                f"The top products represent {concentration:.1f}% of latest-month sales.", ", ".join(f"{k}: ₹{v:,.0f}" for k, v in latest.head(5).items()),
                "Cumulative sales share of products, ranked by latest-month sales; shown as a concentration indicator.", rows[rows.Month == rows.Month.max()].sort_values("Value", ascending=False).head(10)["Source_Row"].tolist()))

        # Repeated direction across recent comparable reported periods.
        n = int(t["sustained_periods"])
        month_product = rows.groupby(["Month", "Product"]).Value.sum().unstack(fill_value=0).sort_index()
        if len(month_product) >= n + 1:
            recent = month_product.tail(n + 1)
            delta = recent.diff().iloc[1:]
            for product in delta.columns:
                if (delta[product] > 0).all():
                    insights.append(_insight(f"{product}: sales increased for {n} consecutive periods", "Low", product, f"Last {n} period changes",
                        f"Sales rose in each of the last {n} period-to-period comparisons.", "; ".join(f"{m:%b}: ₹{v:,.0f}" for m, v in recent[product].items()),
                        f"Positive sales change in each of the last {n} month comparisons.", rows[rows.Product == product]["Source_Row"].drop_duplicates().tolist()))
                elif (delta[product] < 0).all():
                    insights.append(_insight(f"{product}: sales declined for {n} consecutive periods", "Medium", product, f"Last {n} period changes",
                        f"Sales fell in each of the last {n} period-to-period comparisons.", "; ".join(f"{m:%b}: ₹{v:,.0f}" for m, v in recent[product].items()),
                        f"Negative sales change in each of the last {n} month comparisons.", rows[rows.Product == product]["Source_Row"].drop_duplicates().tolist()))

    # Inventory comparisons at product level, using observed month-end QOH and sales.
    if not rows.empty and rows.Month.nunique() >= 2:
        periods = sorted(rows.Month.dropna().unique())
        cur, prev = periods[-1], periods[-2]
        inv = rows[rows.Month.isin([prev, cur])].groupby(["Product", "Month"])[["QOH", "Sale", "Value", "Age", "Purc"]].sum().reset_index()
        for product, g in inv.groupby("Product"):
            g = g.set_index("Month")
            if prev not in g.index or cur not in g.index: continue
            a, b = g.loc[prev], g.loc[cur]
            if b.QOH > a.QOH and b.Sale < a.Sale:
                insights.append(_insight(f"{product}: inventory increased while sales declined", "High", product, period_label,
                    f"QOH moved {a.QOH:,.0f} → {b.QOH:,.0f} units while sales moved {a.Sale:,.0f} → {b.Sale:,.0f} units.",
                    f"QOH change: {b.QOH-a.QOH:+,.0f}; sales change: {b.Sale-a.Sale:+,.0f} units.", "Compare latest and prior period row sums for QOH and Sale; no causal inference.", rows[(rows.Product == product) & rows.Month.isin([prev, cur])]["Source_Row"].tolist()))
        old = rows[(rows.Month == cur) & (rows.Age >= t["slow_moving_age_days"]) & (rows.QOH > 0)]
        if not old.empty:
            for _, r in old.nlargest(10, "Value").iterrows():
                insights.append(_insight(f"{r.Product}: stock age is {r.Age:.0f} days", "Medium", r.Product, f"{cur:%b %Y}",
                    f"{r.QOH:,.0f} units remain on hand with reported age of {r.Age:.0f} days.", f"Inventory value: ₹{r.Value:,.0f}; sales: {r.Sale:,.0f} units.",
                    f"Source Age ≥ {t['slow_moving_age_days']} days and QOH > 0.", [r.Source_Row]))
        low = rows[(rows.Month == cur) & (rows.QOH <= t["low_qoh_units"]) & (rows.Sale >= t["strong_sales_units"])]
        for _, r in low.iterrows():
            insights.append(_insight(f"{r.Product}: low QOH with strong reported sales", "High", r.Product, f"{cur:%b %Y}",
                f"QOH is {r.QOH:,.0f} units against {r.Sale:,.0f} units sold.", f"Thresholds: QOH ≤ {t['low_qoh_units']}; sales ≥ {t['strong_sales_units']} units.",
                "Compare source QOH and Sale values against configured thresholds.", [r.Source_Row]))
        # Purchasing pace is a comparison signal, not a causal claim.
        mismatch = rows[rows.Month == cur].groupby("Product")[["Purc", "Sale"]].sum()
        for product, r in mismatch.iterrows():
            if r.Purc > 0 and r.Sale > 0 and r.Purc >= 2 * r.Sale:
                insights.append(_insight(f"{product}: purchases substantially exceed sales", "Medium", product, f"{cur:%b %Y}",
                    f"Reported purchases are {r.Purc/r.Sale:.1f}× reported sales in units.", f"Purchases: {r.Purc:,.0f}; sales: {r.Sale:,.0f} units.",
                    "Flag when purchase units are at least twice sales units in the same reported period.", rows[(rows.Product == product) & (rows.Month == cur)]["Source_Row"].tolist()))

    # Agency sales trend comparison from monthly summary rows.
    agency = data["MONTHLY_TOTALS"]
    if not agency.empty and agency.Month.nunique() >= 2:
        am = agency.groupby(["Agency", "Month"]).Sale_Value.sum().unstack(fill_value=0).sort_index(axis=1)
        first, last = am.columns[-2], am.columns[-1]
        for name, r in am.iterrows():
            delta = r[last] - r[first]
            pct = delta / r[first] * 100 if r[first] else None
            if pct is not None and abs(pct) >= t["material_change_pct"]:
                insights.append(_insight(f"{name} sales {'increased' if delta > 0 else 'declined'} {abs(pct):.1f}%", "High" if delta < 0 else "Low", name, f"{first:%b %Y} → {last:%b %Y}",
                    f"Agency sales moved from ₹{r[first]:,.0f} to ₹{r[last]:,.0f}.", f"Change: ₹{delta:,.0f} ({pct:+.1f}%).", "Compare MONTHLY_TOTALS Sale_Value across the latest two months.", []))

    # Doctor potential and product-link gaps are profile coverage signals only.
    doctors, links = data["DOCTORS"], data["DOCTOR_PRODUCTS"]
    if not doctors.empty and "Potential" in doctors:
        active = doctors[doctors.get("Active", pd.Series("YES", index=doctors.index)).astype(str).str.upper().eq("YES")]
        linked = set(links.loc[links.get("Active", pd.Series("YES", index=links.index)).astype(str).str.upper().eq("YES"), "Doctor_ID"].dropna()) if "Doctor_ID" in links else set()
        eligible = active[active.Potential.astype(str).str.upper().isin(["A", "B"])]
        unlinked = eligible[~eligible.Doctor_ID.isin(linked)]
        if not unlinked.empty:
            insights.append(_insight("A/B potential doctors without a product relationship", "Medium", "Doctors", "Current profile", f"{len(unlinked)} active A/B potential doctors have no active product link recorded.", ", ".join(unlinked.Doctor_Name.fillna(unlinked.Doctor_ID).head(12).astype(str)),
                "Count active doctors with Potential A or B whose Doctor_ID is absent from active DOCTOR_PRODUCTS links.", []))
        config = data["PRODUCT_CONFIG"]
        catalog = set(config.loc[config.get("Your_Status", pd.Series(index=config.index, dtype=str)).astype(str).str.upper().eq("ACTIVE"), "Your_SKU"].dropna().astype(str)) if "Your_SKU" in config else set()
        ab_ids = set(eligible.Doctor_ID.dropna())
        if catalog and ab_ids:
            active_links = links[links.Doctor_ID.isin(ab_ids) & links.Product_SKU.astype(str).isin(catalog)] if {"Doctor_ID", "Product_SKU"}.issubset(links.columns) else pd.DataFrame()
            if "Active" in active_links:
                active_links = active_links[active_links.Active.astype(str).str.upper().eq("YES")]
            candidates = len(ab_ids) * len(catalog)
            missing_pairs = max(0, candidates - active_links[["Doctor_ID", "Product_SKU"]].drop_duplicates().shape[0])
            if missing_pairs:
                insights.append(_insight("Potential doctor/product coverage gaps", "Low", "A/B doctors × active catalog", "Current profile", f"{missing_pairs:,} A/B doctor and active product combinations have no relationship recorded.", f"{len(ab_ids)} active A/B doctors × {len(catalog)} active catalog products; {active_links[['Doctor_ID', 'Product_SKU']].drop_duplicates().shape[0]:,} combinations linked.",
                    "Candidate profile combinations minus distinct matching DOCTOR_PRODUCTS relationships; this is a coverage prompt, not evidence of prescribing or demand.", []))
        nrx = eligible[eligible.Prescriber_Status.astype(str).str.upper().eq("NRX")] if "Prescriber_Status" in eligible else eligible.iloc[0:0]
        if not nrx.empty:
            insights.append(_insight("A/B potential with NRx status", "Medium", "Doctors", "Current profile", f"{len(nrx)} active A/B potential doctors are marked NRx.", ", ".join(nrx.Doctor_Name.fillna(nrx.Doctor_ID).head(12).astype(str)), "Filter active doctor profiles to Potential A/B and Prescriber_Status NRx.", []))
        if linked:
            linked_counts = links[links.Doctor_ID.isin(linked)].groupby("Doctor_ID").Product_SKU.nunique().sort_values(ascending=False)
            if not linked_counts.empty:
                insights.append(_insight("Doctor/product relationship concentration", "Low", "Doctor-product links", "Current profile", f"{linked_counts.max()} product links are associated with one doctor; {linked_counts.nunique()} distinct link counts across doctors.", f"Most linked doctor ID: {linked_counts.index[0]}; links: {linked_counts.iloc[0]}.", "Count distinct active linked Product_SKU per doctor and compare distribution.", []))

    # Pricing integrity: surface only relationships that violate basic price ordering.
    prices = data["PRICE_LIST"]
    if not prices.empty and all(c in prices for c in ["PTS", "PTR", "MRP", "Net_Price"]):
        p = prices.copy()
        for c in ["PTS", "PTR", "MRP", "Net_Price"]: p[c] = pd.to_numeric(p[c], errors="coerce")
        bad = p[(p.PTS > p.PTR * (1 + t["price_tolerance_pct"] / 100)) | (p.PTR > p.MRP * (1 + t["price_tolerance_pct"] / 100)) | (p.Net_Price > p.PTS * (1 + t["price_tolerance_pct"] / 100))]
        for _, r in bad.iterrows():
            insights.append(_insight(f"Review price relationship: {r.Product_Name}", "Medium", r.Product_SKU, str(r.get("Effective_From", "Current")),
                "A listed price ordering is outside the configured tolerance; verify mapping and source values.", f"PTS ₹{r.PTS}; PTR ₹{r.PTR}; MRP ₹{r.MRP}; Net price ₹{r.Net_Price}.",
                f"Flag when PTS > PTR, PTR > MRP, or Net_Price > PTS by more than {t['price_tolerance_pct']}%.", []))
        if {"Paid_Packs", "Free_Packs"}.issubset(p.columns):
            p["Paid_Packs"] = pd.to_numeric(p.Paid_Packs, errors="coerce")
            p["Free_Packs"] = pd.to_numeric(p.Free_Packs, errors="coerce")
            valid = p[(p.PTS > 0) & (p.Paid_Packs > 0) & p.Free_Packs.notna() & p.Net_Price.notna()].copy()
            valid["Implied_Net"] = valid.PTS * valid.Paid_Packs / (valid.Paid_Packs + valid.Free_Packs)
            valid["Scheme_Delta_Pct"] = (valid.Net_Price - valid.Implied_Net).abs() / valid.Implied_Net * 100
            for _, r in valid[valid.Scheme_Delta_Pct > t["price_tolerance_pct"]].iterrows():
                insights.append(_insight(f"Review scheme/net price: {r.Product_Name}", "Medium", r.Product_SKU, str(r.get("Effective_From", "Current")),
                    "Listed net price differs from the simple paid/free pack implication; confirm taxes and scheme terms.", f"Scheme {r.get('Scheme', '—')}; listed net ₹{r.Net_Price:.2f}; implied ₹{r.Implied_Net:.2f}.",
                    "Implied net = PTS × paid packs ÷ (paid packs + free packs); flag variance above configured tolerance.", []))
    return sorted(insights, key=lambda x: {"High": 0, "Medium": 1, "Low": 2}.get(x["Severity"], 3))
