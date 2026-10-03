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
        stock_fig = px.area(month_flow, x="Month", y="Closing", color_discrete_sequence=["#bc8744"])
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
    totals = data["MONTHLY_TOTALS"]
    months = sorted(rows.Month.dropna().unique())
    previous, current = months[-2:] if len(months) >= 2 else (months[-1], months[-1])
    agencies = ["All agencies"] + sorted(rows.Agency.dropna().unique().tolist())
    chosen = st.selectbox("Scope", agencies, key="sales_scope")
    scoped = rows if chosen == "All agencies" else rows[rows.Agency.eq(chosen)]
    period_values = scoped.groupby("Month").Value.sum().sort_index()
    latest_value = float(period_values.iloc[-1]) if len(period_values) else 0
    prev_value = float(period_values.iloc[-2]) if len(period_values) > 1 else 0
    change_value = latest_value - prev_value
    growth_value = change_value / prev_value * 100 if prev_value else None
    a,b,c = st.columns(3)
    a.metric("Latest sales", rupees(latest_value), f"{growth_value:+.1f}% vs prior" if growth_value is not None else None)
    b.metric("Sales change", rupees(change_value))
    c.metric("Products with sales", f"{scoped[scoped.Month.eq(current)].Product.nunique():,}")

    trend = scoped.groupby(["Month", "Agency"], as_index=False).Value.sum()
    trend["Month label"] = trend.Month.dt.strftime("%b %Y")
    fig = px.line(trend, x="Month", y="Value", color="Agency" if chosen == "All agencies" else None, markers=True)
    fig.update_layout(height=340, margin=dict(l=5,r=5,t=10,b=5), legend_title_text="")
    st.plotly_chart(fig, use_container_width=True)

    # Largest product changes explain the latest month-over-month movement.
    product_period = scoped[scoped.Month.isin([previous,current])].pivot_table(index="Product", columns="Month", values="Value", aggfunc="sum", fill_value=0)
    if len(product_period.columns) >= 2:
        product_period = product_period.rename(columns={previous:"Prior", current:"Latest"})
        product_period["Change"] = product_period["Latest"] - product_period["Prior"]
        extremes = pd.concat([product_period.nsmallest(8,"Change"), product_period.nlargest(8,"Change")]).drop_duplicates().sort_values("Change")
        down = product_period[product_period.Change < 0].Change.sum()
        up = product_period[product_period.Change > 0].Change.sum()
        st.subheader("Which products moved sales?")
        st.caption(f"Across products, positive changes total {rupees(up)} and negative changes total {rupees(down)}; the net movement is {rupees(up+down)}.")
        fig = px.bar(extremes.reset_index(), x="Change", y="Product", orientation="h", color="Change", color_continuous_scale=["#c7473a","#e8e4dc","#31846b"], hover_data={"Prior":":,.0f","Latest":":,.0f","Change":":+,.0f"})
        fig.update_layout(height=460, margin=dict(l=5,r=5,t=10,b=5), coloraxis_showscale=False, xaxis_title="Sales value change (₹)", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

    st.subheader("Sales mix through time")
    top_products = scoped[scoped.Month.eq(current)].groupby("Product").Value.sum().nlargest(12).index
    mix = scoped[scoped.Product.isin(top_products)].pivot_table(index="Product", columns="Month", values="Value", aggfunc="sum", fill_value=0)
    if not mix.empty:
        mix.columns = [x.strftime("%b %Y") for x in mix.columns]
        fig = go.Figure(go.Heatmap(z=mix.values, x=mix.columns, y=mix.index, colorscale=[[0,"#f5f3ef"],[0.5,"#91a9bd"],[1,"#315c94"]], colorbar=dict(title="₹ sales"), hovertemplate="%{y}<br>%{x}: ₹%{z:,.0f}<extra></extra>"))
        fig.update_layout(height=420, margin=dict(l=5,r=5,t=10,b=5), xaxis_title="Reported month", yaxis_title="Top products in latest month")
        st.plotly_chart(fig, use_container_width=True)

    with st.expander("Source rows behind the charts"):
        st.dataframe(scoped.sort_values("Month", ascending=False), hide_index=True, use_container_width=True)

def products_page(data):
    st.title("Products")
    rows = sales_rows(data)
    changes = product_change(data)
    config = data["PRODUCT_CONFIG"]
    if not changes.empty:
        months = sorted(rows.Month.dropna().unique())
        current = months[-1]
        rising = changes.nlargest(8,"Change")
        falling = changes.nsmallest(8,"Change")
        growing_sales = changes.loc[changes.Change > 0,"Change"].sum()
        declining_sales = changes.loc[changes.Change < 0,"Change"].sum()
        a,b,c = st.columns(3)
        a.metric("Products growing", int((changes.Change > 0).sum()))
        b.metric("Products declining", int((changes.Change < 0).sum()))
        c.metric("Net product movement", rupees(changes.Change.sum()))
        st.markdown(f"Positive product changes sum to **{rupees(growing_sales)}**; negative changes sum to **{rupees(declining_sales)}**. The largest increase was **{rising.iloc[0].Product}** ({rupees(rising.iloc[0].Change)}); the largest fall was **{falling.iloc[0].Product}** ({rupees(falling.iloc[0].Change)}).")
        movement = pd.concat([falling,rising]).drop_duplicates(subset="Product").sort_values("Change")
        fig = px.bar(movement, x="Change", y="Product", orientation="h", color="Change", color_continuous_scale=["#c7473a","#e8e4dc","#31846b"], hover_data={"Previous":":,.0f","Current":":,.0f","Change":":+,.0f","Change_Pct":":+.1f"})
        fig.update_layout(height=470, margin=dict(l=5,r=5,t=10,b=5), coloraxis_showscale=False, xaxis_title="Latest month change in sales value (₹)", yaxis_title="")
        st.plotly_chart(fig, use_container_width=True)

        products = sorted(changes.Product.astype(str).unique())
        selection = st.selectbox("Inspect product trend", products, index=products.index(str(rising.iloc[0].Product)) if str(rising.iloc[0].Product) in products else 0, key="product_trend")
        product_rows = rows[rows.Product.eq(selection)].groupby("Month",as_index=False).agg(Sales_Value=("Value","sum"),Units_Sold=("Sale","sum"),QOH=("QOH","sum"),Stock_Age=("Age","max"))
        left,right = st.columns(2)
        with left:
            st.caption(f"{selection}: monthly sales value")
            fig = px.line(product_rows,x="Month",y="Sales_Value",markers=True)
            fig.update_layout(height=320,margin=dict(l=5,r=5,t=10,b=5),yaxis_title="Sales value (₹)")
            st.plotly_chart(fig,use_container_width=True)
        with right:
            st.caption("Units sold and reported QOH — same product, agency values combined")
            unit_rows = product_rows.melt(id_vars="Month",value_vars=["Units_Sold","QOH"],var_name="Measure",value_name="Units")
            fig = px.line(unit_rows,x="Month",y="Units",color="Measure",markers=True)
            fig.update_layout(height=320,margin=dict(l=5,r=5,t=10,b=5),legend_title_text="")
            st.plotly_chart(fig,use_container_width=True)

        latest = rows[rows.Month.eq(current)].groupby("Product",as_index=False).agg(QOH=("QOH","sum"),Units_Sold=("Sale","sum"),Age_Days=("Age","max"))
        latest = latest[(latest.QOH >= 0) & (latest.Age_Days.notna())]
        latest["Bubble size"] = latest.QOH.clip(lower=1)
        st.subheader("Stock age and latest sales")
        fig = px.scatter(latest,x="Age_Days",y="Units_Sold",size="Bubble size",color="Age_Days",hover_name="Product",hover_data={"QOH":":,.0f","Units_Sold":":,.0f","Age_Days":":.0f","Bubble size":False},color_continuous_scale=["#d9e7df","#d6a45a","#b84f42"])
        fig.add_vline(x=180,line_dash="dot",line_color="#a34a3f")
        fig.update_layout(height=390,margin=dict(l=5,r=5,t=10,b=5),xaxis_title="Reported stock age (days)",yaxis_title="Units sold in latest month")
        st.plotly_chart(fig,use_container_width=True)
    with st.expander("Product catalog and mapping"):
        left, right = st.columns(2)
        left.dataframe(config, hide_index=True, use_container_width=True)
        right.dataframe(data["PRODUCT_MAP"], hide_index=True, use_container_width=True)

def doctors_page(data):
    st.title("Doctors")
    doctors = data["DOCTORS"]
    links = data["DOCTOR_PRODUCTS"]
    active = doctors[doctors.get("Active", pd.Series("YES", index=doctors.index)).astype(str).str.upper().eq("YES")].copy()
    active_links = links[links.get("Active",pd.Series("YES",index=links.index)).astype(str).str.upper().eq("YES")].copy()
    linked = set(active_links.get("Doctor_ID", pd.Series(dtype=str)).dropna())
    active["Product relationship"] = active.Doctor_ID.map(lambda x: "Linked" if x in linked else "No link recorded")
    high = active[active.Potential.astype(str).str.upper().isin(["A","B"])] if "Potential" in active else active.iloc[0:0]
    nrx = high[high.Prescriber_Status.astype(str).str.upper().eq("NRX")] if "Prescriber_Status" in high else high.iloc[0:0]
    a, b, c = st.columns(3)
    a.metric("Active doctors", len(active))
    b.metric("A/B potential", len(high))
    c.metric("A/B marked NRx", len(nrx))
    st.caption("These are profile and relationship records. The workbook does not contain prescription outcomes or a measure of doctor-generated sales.")
    left,right=st.columns(2)
    with left:
        st.markdown("#### Potential × prescriber status")
        profile=active.groupby(["Potential","Prescriber_Status"],dropna=False).size().reset_index(name="Doctors")
        profile["Potential"]=profile.Potential.fillna("Unspecified")
        profile["Prescriber_Status"]=profile.Prescriber_Status.fillna("Unspecified")
        fig=px.bar(profile,x="Potential",y="Doctors",color="Prescriber_Status",barmode="stack",category_orders={"Potential":["A","B","C","Unspecified"]},color_discrete_map={"Rx":"#315c94","NRx":"#c58b45","Unspecified":"#9aa3ad"})
        fig.update_layout(height=340,margin=dict(l=5,r=5,t=10,b=5),legend_title_text="")
        st.plotly_chart(fig,use_container_width=True)
    with right:
        st.markdown("#### Recorded product relationships")
        if not active_links.empty and "Product_SKU" in active_links:
            counts=active_links.groupby("Product_SKU").Doctor_ID.nunique().sort_values(ascending=False).head(12).sort_values()
            fig=px.bar(counts.reset_index(name="Doctor count"),x="Doctor count",y="Product_SKU",orientation="h",color="Doctor count",color_continuous_scale=["#dfe8ef","#315c94"])
            fig.update_layout(height=340,margin=dict(l=5,r=5,t=10,b=5),coloraxis_showscale=False,yaxis_title="")
            st.plotly_chart(fig,use_container_width=True)
        else: st.info("No active doctor/product relationships are recorded.")
    if not active.empty and "Specialties" in active:
        specialties=active.Specialties.fillna("Unspecified").value_counts().head(10).sort_values()
        st.markdown("#### Profile distribution by specialty")
        fig=px.bar(specialties.reset_index(name="Doctors"),x="Doctors",y="Specialties",orientation="h",color="Doctors",color_continuous_scale=["#dfe8ef","#527e70"])
        fig.update_layout(height=360,margin=dict(l=5,r=5,t=10,b=5),coloraxis_showscale=False,yaxis_title="")
        st.plotly_chart(fig,use_container_width=True)
    with st.expander("Doctor profiles and recorded links"):
        st.dataframe(active, hide_index=True, use_container_width=True)
        st.dataframe(active_links, hide_index=True, use_container_width=True)

def inventory_page(data):
    st.title("Inventory")
    rows = sales_rows(data)
    if rows.empty: st.info("No inventory rows were found."); return
    periods = sorted(rows.Month.dropna().unique())
    current = periods[-1]
    latest = rows[rows.Month == periods[-1]].copy()
    totals = data["MONTHLY_TOTALS"]
    close=totals[totals.Month.eq(current)].Closing_Value.sum() if not totals.empty else 0
    stock=latest.groupby("Product",as_index=False).agg(QOH=("QOH","sum"),Units_Sold=("Sale","sum"),Age_Days=("Age","max"))
    old=stock[(stock.QOH>0)&(stock.Age_Days>=180)]
    stale_no_sales=old[old.Units_Sold.eq(0)]
    prior=periods[-2] if len(periods)>1 else current
    previous_close=totals[totals.Month.eq(prior)].Closing_Value.sum() if not totals.empty else close
    cols=st.columns(4)
    cols[0].metric("Latest closing inventory value",rupees(close),f"{rupees(close-previous_close)} vs prior")
    cols[1].metric("Latest QOH",f"{stock.QOH.sum():,.0f} units")
    cols[2].metric("Products aged 180+ days",len(old))
    cols[3].metric("Aged stock, no current sales",len(stale_no_sales))
    st.write(f"**{len(stale_no_sales)} products** have positive QOH, reported age of at least 180 days, and zero units sold in {current:%B}. This is an age/sales overlap signal; it does not establish why stock is unsold.")
    left,right=st.columns(2)
    with left:
        st.markdown("#### Agency closing inventory value")
        if not totals.empty:
            fig=px.line(totals,x="Month",y="Closing_Value",color="Agency",markers=True)
            fig.update_layout(height=350,margin=dict(l=5,r=5,t=10,b=5),yaxis_title="Closing inventory value (₹)",legend_title_text="")
            st.plotly_chart(fig,use_container_width=True)
    with right:
        st.markdown("#### Age against latest units sold")
        chart=stock[(stock.QOH>=0)&stock.Age_Days.notna()].copy()
        chart["Bubble size"]=chart.QOH.clip(lower=1)
        fig=px.scatter(chart,x="Age_Days",y="Units_Sold",size="Bubble size",color="Age_Days",hover_name="Product",hover_data={"QOH":":,.0f","Units_Sold":":,.0f","Age_Days":":.0f","Bubble size":False},color_continuous_scale=["#d9e7df","#d6a45a","#b84f42"])
        fig.add_vline(x=180,line_dash="dot",line_color="#a34a3f")
        fig.update_layout(height=350,margin=dict(l=5,r=5,t=10,b=5),xaxis_title="Reported stock age (days)",yaxis_title="Units sold in latest month")
        st.plotly_chart(fig,use_container_width=True)
    aged_view=old.sort_values(["Units_Sold","QOH"],ascending=[True,False])
    st.markdown("#### Aged stock details")
    st.dataframe(aged_view,hide_index=True,use_container_width=True)
    with st.expander("Product-level source rows"):
        st.dataframe(latest.sort_values(["Age","QOH"],ascending=[False,False]), hide_index=True, use_container_width=True)

def agencies_page(data):
    st.title("Agencies")
    totals = data["MONTHLY_TOTALS"]
    if totals.empty: st.info("No monthly agency totals found."); return
    months=sorted(totals.Month.dropna().unique())
    previous,current=months[-2:] if len(months)>1 else (months[-1],months[-1])
    sales=totals.pivot_table(index="Agency",columns="Month",values="Sale_Value",aggfunc="sum",fill_value=0)
    sales["Change"]=sales[current]-sales[previous]
    a,b,c=st.columns(3)
    a.metric("Agency count",sales.index.nunique())
    lead=sales.Change.idxmin()
    b.metric("Largest agency decline",lead,rupees(sales.loc[lead,"Change"]))
    c.metric("Latest sales",rupees(totals[totals.Month.eq(current)].Sale_Value.sum()))
    st.markdown("#### Sales and stock paths by agency")
    left,right=st.columns(2)
    with left:
        fig=px.line(totals,x="Month",y="Sale_Value",color="Agency",markers=True)
        fig.update_layout(height=350,margin=dict(l=5,r=5,t=10,b=5),yaxis_title="Sales (₹)",legend_title_text="")
        st.plotly_chart(fig,use_container_width=True)
    with right:
        fig=px.line(totals,x="Month",y="Closing_Value",color="Agency",markers=True)
        fig.update_layout(height=350,margin=dict(l=5,r=5,t=10,b=5),yaxis_title="Closing inventory value (₹)",legend_title_text="")
        st.plotly_chart(fig,use_container_width=True)
    movement=sales[[previous,current,"Change"]].reset_index()
    movement.columns=["Agency","Prior sales","Latest sales","Change"]
    st.markdown(f"#### Agency movement · {previous:%b} to {current:%b}")
    fig=px.bar(movement,x="Change",y="Agency",orientation="h",color="Change",color_continuous_scale=["#c7473a","#e8e4dc","#31846b"],hover_data={"Prior sales":":,.0f","Latest sales":":,.0f","Change":":+,.0f"})
    fig.update_layout(height=250,margin=dict(l=5,r=5,t=10,b=5),coloraxis_showscale=False,xaxis_title="Sales change (₹)",yaxis_title="")
    st.plotly_chart(fig,use_container_width=True)

    product_rows=sales_rows(data)
    product_month=product_rows[product_rows.Month.eq(current)].pivot_table(index="Product",columns="Agency",values="Value",aggfunc="sum",fill_value=0)
    agency_names=sorted(product_rows.Agency.dropna().unique())
    if len(agency_names)>=2 and not product_month.empty:
        first,second=agency_names[:2]
        for name in [first,second]:
            if name not in product_month: product_month[name]=0
        product_month["Difference"]=product_month[second]-product_month[first]
        comparison=pd.concat([product_month.nsmallest(8,"Difference"),product_month.nlargest(8,"Difference")]).drop_duplicates().sort_values("Difference")
        st.markdown(f"#### Product differences · {second} minus {first} · {current:%b %Y}")
        st.caption("Positive bars show higher recorded sales value in the second agency. This compares sales mix, not agency performance quality.")
        fig=px.bar(comparison.reset_index(),x="Difference",y="Product",orientation="h",color="Difference",color_continuous_scale=["#c7473a","#e8e4dc","#31846b"],hover_data={first:":,.0f",second:":,.0f","Difference":":+,.0f"})
        fig.update_layout(height=440,margin=dict(l=5,r=5,t=10,b=5),coloraxis_showscale=False,xaxis_title="Difference in sales value (₹)",yaxis_title="")
        st.plotly_chart(fig,use_container_width=True)
    with st.expander("Monthly agency totals"):
        st.dataframe(totals.sort_values("Month",ascending=False),hide_index=True,use_container_width=True)

def quality_page(data):
    st.title("Data Quality")
    sheet_stats, checks = data_quality(data)
    empty_count=int(sheet_stats.Empty.sum())
    affected=int(checks["Rows affected"].sum()) if not checks.empty else 0
    a,b,c=st.columns(3)
    a.metric("Populated analysis sheets",len(sheet_stats)-empty_count,f"{empty_count} empty")
    b.metric("Sales source rows",len(data["SALES_RAW"]))
    c.metric("Flagged check counts",affected)
    left,right=st.columns(2)
    with left:
        st.markdown("#### Workbook coverage")
        populated=sheet_stats[~sheet_stats.Empty].copy()
        fig=px.bar(populated,x="Rows",y="Sheet",orientation="h",color="Rows",color_continuous_scale=["#dfe8ef","#315c94"],text="Rows")
        fig.update_layout(height=370,margin=dict(l=5,r=5,t=10,b=5),coloraxis_showscale=False,yaxis_title="")
        st.plotly_chart(fig,use_container_width=True)
    with right:
        st.markdown("#### Sales row checks")
        nonzero=checks[checks["Rows affected"]>0].sort_values("Rows affected")
        if nonzero.empty:
            st.success("No flagged sales-row checks in the current workbook.")
        else:
            fig=px.bar(nonzero,x="Rows affected",y="Check",orientation="h",color="Rows affected",color_continuous_scale=["#eddcb1","#b84f42"],text="Rows affected")
            fig.update_layout(height=370,margin=dict(l=5,r=5,t=10,b=5),coloraxis_showscale=False,xaxis_title="Rows",yaxis_title="")
            st.plotly_chart(fig,use_container_width=True)
    rows=sales_rows(data)
    if not rows.empty:
        st.markdown("#### Reported source rows by month and agency")
        coverage=rows.groupby(["Month","Agency"]).size().reset_index(name="Rows")
        fig=px.bar(coverage,x="Month",y="Rows",color="Agency",barmode="group",text="Rows")
        fig.update_layout(height=310,margin=dict(l=5,r=5,t=10,b=5),legend_title_text="",yaxis_title="SALES_RAW rows")
        st.plotly_chart(fig,use_container_width=True)
        issues=rows[(rows.Value<0)|(rows.QOH<0)|rows.Product.isna()]
        if not issues.empty:
            st.caption("Source rows with negative sales value, negative QOH, or missing canonical product. Review against the statement before changing source data.")
            st.dataframe(issues[[c for c in ["Month","Agency","Product_Name","Value","QOH","Source_Row","Raw_Row_Text"] if c in issues]],hide_index=True,use_container_width=True)
    with st.expander("Sheet details and price list"):
        st.dataframe(sheet_stats,hide_index=True,use_container_width=True)
        st.dataframe(checks,hide_index=True,use_container_width=True)
        st.dataframe(data["PRICE_LIST"],hide_index=True,use_container_width=True)
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
