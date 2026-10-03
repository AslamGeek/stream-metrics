# Sales Intelligence

An insight-led Streamlit business intelligence app built from `Sales_Data.xlsx`. It treats the workbook as read-only and uses `SALES_RAW`, `MONTHLY_TOTALS`, product references, doctor/product relationships, and price-list data. Empty `VISITS` and `POB_ACTIVITY` sheets are ignored.

## Run

```bash
python -m pip install -r requirements.txt
streamlit run app.py
```

The app defaults to `data/Sales_Data.xlsx`; change the path in the sidebar to analyze another workbook with the same sheet structure.

## Structure

- `data_layer.py` loads, normalizes, and retains source line references.
- `analytics.py` contains reusable metrics and comparisons.
- `insight_engine.py` contains configurable signal rules.
- `app.py` contains Streamlit navigation and presentation.
- `config.py` contains insight thresholds.

Insights include their period, evidence, calculation, and source rows where a transaction row exists. Profile and price-list signals reference their source sheet/entity because they are not tied to a sales transaction row. Rules describe co-occurrences and comparisons; they do not infer causes.
