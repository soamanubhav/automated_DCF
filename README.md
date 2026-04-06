# Automated DCF Dashboard

A Flask + yfinance web app that builds a full Discounted Cash Flow model from live financial statement data.

## Features

- Pulls balance sheet, income statement, and cash flow data by ticker symbol.
- Uses historical averages when assumptions are left blank.
- Projects 5-year revenue, EBIT, NOPAT, reinvestment, and FCFF.
- Discounts FCFF using WACC and computes terminal value.
- Outputs enterprise value, equity value, and intrinsic value per share.
- Includes WACC vs terminal growth sensitivity matrix.

## Run locally

```bash
pip install -r requirements.txt
python app.py
```

Then open: `http://127.0.0.1:5000`

## API

### `POST /dcf`

Request body:

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

Any omitted assumption is auto-filled from historical values (or model defaults).

### `GET /fetch-data?query=AAPL`

Returns raw statement data for balance sheet, income statement, and cash flow.

## Deploy on Render

Use the existing `render.yaml`:

- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
