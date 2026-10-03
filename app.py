from pathlib import Path
import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

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
    rows = sales_rows(data)
    totals = data["MONTHLY_TOTALS"].copy()
    months = sorted(totals.Month.dropna().unique())
    if len(months) < 2:
        st.info("At least two complete periods are needed for movement analysis.")
        return
    previous, current = months[-2:]
    period_totals = totals.groupby("Month").agg(Sales=("Sale_Value", "sum"), Purchases=("Purchase_Value", "sum"), Closing=("Closing_Value", "sum")).sort_index()
    prev_total, cur_total = period_totals.loc[previous], period_totals.loc[current]
    delta = cur_total.Sales - prev_total.Sales
    pct = delta / prev_total.Sales * 100 if prev_total.Sales else 0
    agency = totals[totals.Month.isin([previous, current])].pivot_table(index="Agency", columns="Month", values="Sale_Value", aggfunc="sum", fill_value=0)
    agency["Change"] = agency[current] - agency[previous]
    lead_agency = agency.Change.abs().idxmax()
    lead_change = agency.loc[lead_agency, "Change"]
    lead_share = abs(lead_change / delta * 100) if delta else 0
    st.caption(f"Latest reported period: {current:%B %Y} · compared with {previous:%B %Y}")
    st.subheader(f"Sales fell {abs(pct):.1f}% — {lead_agency} accounts for {lead_share:.1f}% of the net change")
    st.write(f"Sales moved from **{rupees(prev_total.Sales)}** to **{rupees(cur_total.Sales)}** ({rupees(delta)}). {lead_agency} changed by {rupees(lead_change)}; the other agency was {rupees(agency.drop(index=lead_agency).Change.sum()) if len(agency) > 1 else 'not separately reported'}. This locates the decline; it does not establish a cause.")
    cols = st.columns(4)
    cols[0].metric("Latest sales", rupees(cur_total.Sales), f"{pct:+.1f}% vs prior")
    cols[1].metric("Sales change", rupees(delta))
    cols[2].metric("Purchases", rupees(cur_total.Purchases), f"{(cur_total.Purchases-prev_total.Purchases):+,.0f} vs prior")
    cols[3].metric("Closing inventory value", rupees(cur_total.Closing), f"{(cur_total.Closing-prev_total.Closing):+,.0f} vs prior")

    left, right = st.columns([1, 1.25])
    with left:
        st.markdown("#### Agency sales paths")
        high_month = period_totals.Sales.idxmax()
        recent_down = 0
        for i in range(len(period_totals) - 1, 0, -1):
            if period_totals.Sales.iloc[i] < period_totals.Sales.iloc[i - 1]: recent_down += 1
            else: break
        st.caption(f"Peak reported sales: {high_month:%b %Y} ({rupees(period_totals.loc[high_month, 'Sales'])}). Latest run: {recent_down} consecutive month-over-month decline(s).")
        chart = totals.groupby(["Month", "Agency"], as_index=False).Sale_Value.sum()
        fig = px.line(chart, x="Month", y="Sale_Value", color="Agency", markers=True, custom_data=["Agency"])
        fig.update_traces(hovertemplate="%{customdata[0]}<br>%{x|%b %Y}: ₹%{y:,.0f}<extra></extra>")
        fig.update_layout(height=340, margin=dict(l=5,r=5,t=15,b=5), legend_title_text="")
        st.plotly_chart(fig, use_container_width=True)
    with right:
        st.markdown("#### What drove the latest change?")
        st.caption("Product-level sales value change for the agency with the largest absolute agency movement.")
        products = rows[rows.Agency.eq(lead_agency) & rows.Month.isin([previous, current])].pivot_table(index="Product", columns="Month", values="Value", aggfunc="sum", fill_value=0)
        products = products.rename(columns={previous: "Prior", current: "Latest"})
        products["Change"] = products["Latest"] - products["Prior"]
        drivers = products.sort_values("Change").copy()
        drivers = pd.concat([drivers.head(7), drivers.tail(7)]).drop_duplicates().sort_values("Change")
        driver_fig = px.bar(drivers.reset_index(), x="Change", y="Product", orientation="h", color="Change", color_continuous_scale=["#c7473a", "#d9dfe7", "#31846b"], hover_data={"Prior":":,.0f","Latest":":,.0f","Change":":+,.0f"})
        driver_fig.update_layout(height=430, margin=dict(l=5,r=5,t=10,b=5), coloraxis_showscale=False, xaxis_title="Change in sales value (₹)", yaxis_title="")
        st.plotly_chart(driver_fig, use_container_width=True)
        st.caption(f"Largest declines include: " + "; ".join(f"{p} ({rupees(v)})" for p,v in drivers.nsmallest(4,"Change")["Change"].items()) + ".")

    st.markdown("#### Product sales vs stock movement")
    st.caption(f"Each point compares {previous:%b} to {current:%b} for one {lead_agency} product with prior-period sales. Right = sales rose; above = QOH rose. Products with zero prior sales have no defined growth rate. Stock value is not available at product level.")
    p_rows = rows[rows.Agency.eq(lead_agency) & rows.Month.isin([previous,current])]
    product_period = p_rows.groupby(["Product","Month"], as_index=False).agg(Sales_Value=("Value","sum"), Units_Sold=("Sale","sum"), QOH=("QOH","sum"), Age_Days=("Age","max"))
    sales_wide = product_period.pivot(index="Product", columns="Month", values="Sales_Value").fillna(0)
    qoh_wide = product_period.pivot(index="Product", columns="Month", values="QOH").fillna(0)
    age_latest = product_period[product_period.Month.eq(current)].set_index("Product").Age_Days
    plot = pd.DataFrame(index=sales_wide.index)
    plot["Sales change"] = sales_wide[current] - sales_wide[previous]
    plot["Sales change %"] = plot.apply(lambda r: (r["Sales change"] / sales_wide.loc[r.name, previous] * 100) if sales_wide.loc[r.name, previous] else None, axis=1)
    plot["QOH change"] = qoh_wide[current] - qoh_wide[previous]
    plot["Latest QOH"] = qoh_wide[current]
    plot["Age (days)"] = age_latest
    plot = plot.reset_index()
    risk_count = int(((plot["Sales change"] < 0) & (plot["QOH change"] > 0)).sum())
    st.info(f"{risk_count} products had falling sales value and rising QOH in {lead_agency} over this comparison. This describes simultaneous movement, not cause.")
    # QOH includes one source row with -1 units. Keep that raw value visible in
    # hover, but clamp only the visual bubble size to Plotly's nonnegative range.
    scatter_data = plot.dropna(subset=["Sales change %", "QOH change", "Age (days)"]).copy()
    scatter_data["Bubble size"] = scatter_data["Latest QOH"].clip(lower=1)
    scatter = px.scatter(scatter_data, x="Sales change %", y="QOH change", size="Bubble size", color="Age (days)", hover_name="Product", hover_data={"Bubble size":False,"Sales change":":+,.0f","Sales change %":":+.1f","QOH change":":+,.0f","Latest QOH":":,.0f","Age (days)":":.0f"}, color_continuous_scale=["#f2d67a", "#db8c68", "#7b5b86"])
    scatter.add_hline(y=0, line_dash="dot", line_color="#8b95a1")
    scatter.add_vline(x=0, line_dash="dot", line_color="#8b95a1")
    scatter.add_annotation(x=0.99,y=0.02,xref="paper",yref="paper",text="Sales up · stock up",showarrow=False,font=dict(color="#777"))
    scatter.update_layout(height=440, margin=dict(l=5,r=5,t=12,b=5), xaxis_title="Sales value change (%)", yaxis_title="QOH change (units)", coloraxis_colorbar_title="Age days")
    st.plotly_chart(scatter, use_container_width=True)
    st.markdown("#### Flow through the business")
    flow_left, flow_right = st.columns(2)
    month_flow = period_totals.reset_index()
    with flow_left:
        st.caption(f"Sales and purchases, ₹ · latest: sales {pct:+.1f}% vs prior; purchases {((cur_total.Purchases-prev_total.Purchases)/prev_total.Purchases*100 if prev_total.Purchases else 0):+.1f}%.")
        flow = month_flow.melt(id_vars="Month", value_vars=["Sales", "Purchases"], var_name="Measure", value_name="₹")
        flow_fig = px.bar(flow, x="Month", y="₹", color="Measure", barmode="group", color_discrete_map={"Sales":"#315c94","Purchases":"#56a88b"})
        flow_fig.update_layout(height=320, margin=dict(l=5,r=5,t=10,b=5), legend_title_text="")
        st.plotly_chart(flow_fig, use_container_width=True)
    with flow_right:
        stock_delta = cur_total.Closing - prev_total.Closing
        st.caption(f"Agency-reported closing inventory value · latest change {rupees(stock_delta)} ({stock_delta/prev_total.Closing*100 if prev_total.Closing else 0:+.1f}%).")
        stock_fig = px.area(month_flow, x="Month", y="Closing", markers=True, color_discrete_sequence=["#bc8744"])
        stock_fig.update_layout(height=320, margin=dict(l=5,r=5,t=10,b=5), showlegend=False, yaxis_title="Closing inventory (₹)")
        st.plotly_chart(stock_fig, use_container_width=True)
    with st.expander("Inspect the underlying agency and product changes"):
        agency_view = agency[[previous,current,"Change"]].copy().reset_index()
        agency_view.columns = ["Agency", f"{previous:%b} sales", f"{current:%b} sales", "Change"]
        st.dataframe(agency_view, hide_index=True, use_container_width=True)
        st.dataframe(plot.sort_values("Sales change"), hide_index=True, use_container_width=True)

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
