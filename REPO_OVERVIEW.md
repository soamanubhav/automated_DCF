# Repository Overview

## Purpose
`automated_DCF` is a small Flask web service that fetches a company's core financial statements from Yahoo Finance (`yfinance`) and returns them as JSON.

## Runtime architecture
- **Backend (`app.py`)**
  - Serves the UI at `/` via `templates/index.html`.
  - Exposes `/fetch-data` for both `GET` and `POST`.
  - Uses `yf.Ticker(query)` to fetch:
    - balance sheet
    - income statement
    - cash flow statement
  - Normalizes pandas/yfinance values into JSON-safe primitives (timestamps to ISO strings, `NaN`/`inf` to `null`).
  - Returns consistent error payloads for missing input, upstream fetch failures, and empty statements.
- **Frontend (`templates/index.html`)**
  - Single-page form for ticker/company input.
  - Calls `/fetch-data` on the deployed Render domain by default, with optional override via `window.API_BASE_URL`.
  - Shows user-facing status and pretty-printed JSON response.

## Files and roles
- `app.py`: Flask app + API logic.
- `templates/index.html`: main UI actually served by Flask.
- `index.html`: standalone/static alternative UI (not used by Flask routes).
- `requirements.txt`: Python dependencies.
- `render.yaml`: Render Blueprint deployment config.
- `README.md`: local run + deployment instructions.

## Data flow
1. User enters company/ticker in browser UI.
2. Frontend sends request to `/fetch-data`.
3. Backend fetches statements with yfinance.
4. Backend sanitizes dataframe output and returns JSON.
5. Frontend renders JSON or error message.

## Operational notes
- CORS is currently open to all origins (`*`).
- Production serving is expected through `gunicorn app:app`.
- Service reads `PORT` (Render-compatible) and optional `FLASK_DEBUG` env var.
