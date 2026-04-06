# Automated DCF Dashboard

A Flask + yfinance app that builds a full Discounted Cash Flow model and displays an interactive dashboard.

## What it does

- Pulls balance sheet, income statement, and cash flow statement for a ticker.
- Caches company financial data in local server memory for 5 days.
- Uses default assumptions from historical averages when input fields are left blank.
- Builds a 5-year FCFF forecast table.
- Shows valuation summary (PV of FCFF, terminal value, EV, equity value, intrinsic share price).
- Shows WACC vs terminal growth sensitivity table.
- Shows interactive projection chart for Revenue, EBIT, and FCFF.
- Shows financial statements in 3 tabs:
  - Balance Sheet
  - Income Statement
  - Cash Flow Statement

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Open `http://127.0.0.1:5000`

## API

### `POST /dcf`

```json
{
  "query": "AAPL",
  "assumptions": {
    "revenue_growth_rate": 0.08,
    "ebit_margin": 0.20,
    "depreciation_rate": 0.04,
    "capex_percent": 0.06,
    "nwc_percent": 0.08,
    "wacc": 0.10,
    "terminal_growth_rate": 0.03,
    "tax_rate": 0.23
  }
}
```

Response includes:
- `assumptions`
- `defaulted_fields`
- `forecast`
- `valuation`
- `sensitivity`
- `source_data`
- `from_cache`
- `last_updated`

### `GET /fetch-data?query=AAPL`

Returns statement data and cache metadata (`from_cache`, `last_updated`).


### `POST /company-financials`

Store company financials directly in JSON format:

```json
{
  "query": "AAPL",
  "balance_sheet": {"Total Assets": {"2024-09-30": 1000}},
  "income_statement": {"Total Revenue": {"2024-09-30": 500}},
  "cash_flow_statement": {"Operating Cash Flow": {"2024-09-30": 120}}
}
```

### `GET /company-financials?query=AAPL`

Retrieve previously stored JSON financials for a company.
