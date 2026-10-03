from pathlib import Path
import streamlit as st
import pandas as pd
import plotly.express as px

from config import APP_TITLE, DEFAULT_WORKBOOK, THRESHOLDS
from data_layer import load_workbook, sales_rows
from analytics import kpis, monthly_sales, product_change, agency_trends, data_quality
from insight_engine import generate_insights

ROOT = Path(__file__).parent
st.set_page_config(page_title=APP_TITLE, page_icon="🎯", layout="wide", initial_sidebar_state="expanded")

@st.cache_data(show_spinner="Reading workbook and preparing analysis…")
def get_data(path, stamp):
    return load_workbook(path)

def rupees(value):
    return f"₹{value:,.0f}"

def selected_data():
    path = st.session_state.get("workbook_path", str(ROOT / DEFAULT_WORKBOOK))
    try:
        return get_data(path, Path(path).stat().st_mtime)
    except Exception as exc:
        st.error(f"Could not load the workbook: {exc}")
        st.stop()

def render_insight(item, compact=False):
    color = {"High": "🔴", "Medium": "🟠", "Low": "🔵"}.get(item["Severity"], "⚪")
    with st.container(border=True):
        st.markdown(f"**{color} {item['Title']}**")
        st.caption(f"{item['Severity']} · {item['Entity']} · {item['Period']}")
        st.write(item["Observation"])
        if item["Evidence"]:
            st.markdown(f"**Evidence:** {item['Evidence']}")
        if not compact:
            with st.expander("Calculation & source rows"):
                st.caption(item["Calculation"])
                if item["Source rows"]:
                    st.dataframe(pd.DataFrame({"Source row": item["Source rows"]}), hide_index=True, use_container_width=True)
                else:
                    st.caption("Derived from profile or price-list reference data; no transaction source row applies.")

def command_center(data):
    st.title("Command Center")
    st.caption("What changed · what matters · where to look next")
    metrics = kpis(data)
    cols = st.columns(5)
    labels = [("Total Sales", rupees(metrics["total_sales"])), ("MoM Sales Growth", f"{metrics['mom_growth']:+.1f}%" if metrics["mom_growth"] is not None else "—"), ("Purchase Value", rupees(metrics["purchase_value"])), ("Closing Inventory", rupees(metrics["closing_inventory"])), ("Active Products", f"{metrics['active_products']:,}")]
    for col, (label, value) in zip(cols, labels): col.metric(label, value)
    cols = st.columns(4)
    for col, label, key in zip(cols, ["Products Growing", "Products Declining", "High-potential Doctors", "Doctor/Product Opportunities"], ["products_growing", "products_declining", "high_potential_doctors", "doctor_product_opportunities"]): col.metric(label, f"{metrics[key]:,}")
    insights = generate_insights(data)
    st.subheader("Insights")
    if not insights: st.info("No insights meet the configured rules for the data currently available.")
    for item in insights[:10]: render_insight(item)
    if len(insights) > 10:
        with st.expander(f"Show all {len(insights)} generated insights"):
            for item in insights[10:]: render_insight(item)

def sales_page(data):
    st.title("Sales")
    rows = sales_rows(data)
    if rows.empty: st.info("No sales rows were found."); return
    trend = monthly_sales(data)
    if not trend.empty:
        trend["Month Label"] = trend.Month.dt.strftime("%b %Y")
        st.plotly_chart(px.line(trend, x="Month Label", y="Sale_Value", markers=True, title="Monthly sales value"), use_container_width=True)
    changes = product_change(data)
    st.subheader("Product contribution to latest change")
    if not changes.empty:
        display = changes[["Product", "Previous", "Current", "Change", "Change_Pct"]].copy()
        display.columns = ["Product", "Previous sales", "Current sales", "Change", "Change %"]
        st.dataframe(display.sort_values("Change"), hide_index=True, use_container_width=True, column_config={c: st.column_config.NumberColumn(format="₹%.0f") for c in ["Previous sales", "Current sales", "Change"]})
    st.subheader("Sales source rows")
    st.dataframe(rows.sort_values("Month", ascending=False), hide_index=True, use_container_width=True)

def products_page(data):
    st.title("Products")
    changes = product_change(data)
    config = data["PRODUCT_CONFIG"]
    if not changes.empty:
        st.subheader("Growth and decline")
        st.dataframe(changes[["Product", "Previous", "Current", "Change", "Change_Pct"]].sort_values("Change"), hide_index=True, use_container_width=True)
    st.subheader("Product configuration & mapping")
    left, right = st.columns(2)
    left.dataframe(config, hide_index=True, use_container_width=True)
    right.dataframe(data["PRODUCT_MAP"], hide_index=True, use_container_width=True)

def doctors_page(data):
    st.title("Doctors")
    doctors = data["DOCTORS"]
    links = data["DOCTOR_PRODUCTS"]
    active = doctors[doctors.get("Active", pd.Series("YES", index=doctors.index)).astype(str).str.upper().eq("YES")].copy()
    linked = set(links.get("Doctor_ID", pd.Series(dtype=str)).dropna())
    active["Product relationship"] = active.Doctor_ID.map(lambda x: "Linked" if x in linked else "No link recorded")
    a, b, c = st.columns(3)
    a.metric("Active doctors", len(active))
    b.metric("A/B potential", active.Potential.astype(str).str.upper().isin(["A", "B"]).sum() if "Potential" in active else 0)
    c.metric("A/B with no link", ((active.Potential.astype(str).str.upper().isin(["A", "B"])) & (~active.Doctor_ID.isin(linked))).sum() if "Potential" in active else 0)
    st.dataframe(active, hide_index=True, use_container_width=True)
    st.subheader("Recorded doctor/product relationships")
    st.dataframe(links, hide_index=True, use_container_width=True)

def inventory_page(data):
    st.title("Inventory")
    rows = sales_rows(data)
    if rows.empty: st.info("No inventory rows were found."); return
    periods = sorted(rows.Month.dropna().unique())
    latest = rows[rows.Month == periods[-1]].copy()
    c1, c2 = st.columns(2)
    c1.metric("Latest reported stock value", rupees(latest.Value.sum()))
    c2.metric("Latest reported QOH", f"{latest.QOH.sum():,.0f} units")
    st.caption("Product stock age, QOH and sales are reported as supplied in SALES_RAW.")
    st.dataframe(latest.sort_values("Value", ascending=False), hide_index=True, use_container_width=True)
    totals = data["MONTHLY_TOTALS"]
    if not totals.empty:
        st.subheader("Agency closing inventory")
        st.plotly_chart(px.line(totals, x="Month", y="Closing_Value", color="Agency", markers=True), use_container_width=True)

def agencies_page(data):
    st.title("Agencies")
    totals = data["MONTHLY_TOTALS"]
    if totals.empty: st.info("No monthly agency totals found."); return
    st.plotly_chart(px.line(totals, x="Month", y="Sale_Value", color="Agency", markers=True, title="Sales by agency"), use_container_width=True)
    st.plotly_chart(px.line(totals, x="Month", y="Closing_Value", color="Agency", markers=True, title="Closing inventory by agency"), use_container_width=True)
    if len(totals.Month.unique()) >= 2:
        months = sorted(totals.Month.dropna().unique())
        pivot = totals[totals.Month.isin(months[-2:])].pivot_table(index="Agency", columns="Month", values=["Sale_Value", "Closing_Value"], aggfunc="sum", fill_value=0)
        st.subheader("Latest period comparison")
        st.dataframe(pivot, use_container_width=True)
    st.dataframe(totals.sort_values("Month", ascending=False), hide_index=True, use_container_width=True)

def quality_page(data):
    st.title("Data Quality")
    sheet_stats, checks = data_quality(data)
    st.subheader("Workbook coverage")
    st.dataframe(sheet_stats, hide_index=True, use_container_width=True)
    st.subheader("Sales data checks")
    st.dataframe(checks, hide_index=True, use_container_width=True)
    st.subheader("Commercial reference data")
    st.dataframe(data["PRICE_LIST"], hide_index=True, use_container_width=True)
    st.caption("Empty operational sheets (including VISITS and POB_ACTIVITY) are intentionally excluded from analysis.")

with st.sidebar:
    st.title("🎯 Sales Intelligence")
    default_path = str(ROOT / DEFAULT_WORKBOOK)
    st.text_input("Workbook path", value=st.session_state.get("workbook_path", default_path), key="workbook_path")
    st.caption("Source workbook is read-only. Replace the file or change this path to refresh analysis.")
    if st.button("Clear cached data", use_container_width=True): get_data.clear()

data = selected_data()

# st.Page callables must be zero-argument page functions. Keep workbook loading
# in the entrypoint so the cached data is shared by all seven pages.
def command_center_page(): command_center(data)
def sales_page_view(): sales_page(data)
def products_page_view(): products_page(data)
def doctors_page_view(): doctors_page(data)
def inventory_page_view(): inventory_page(data)
def agencies_page_view(): agencies_page(data)
def data_quality_page(): quality_page(data)

pages = [
    st.Page(command_center_page, title="Command Center", icon="🎯", default=True),
    st.Page(sales_page_view, title="Sales", icon="📈"),
    st.Page(products_page_view, title="Products", icon="🧴"),
    st.Page(doctors_page_view, title="Doctors", icon="🩺"),
    st.Page(inventory_page_view, title="Inventory", icon="📦"),
    st.Page(agencies_page_view, title="Agencies", icon="🏭"),
    st.Page(data_quality_page, title="Data Quality", icon="✅"),
]
nav = st.navigation(pages)
nav.run()
