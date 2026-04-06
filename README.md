# Automated DCF - Financial Statement Fetcher

This app uses Flask + yfinance and can be deployed on Render.

## Run locally

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Start the Flask server:

   ```bash
   python app.py
   ```

3. Open your browser at:

   ```
   http://127.0.0.1:5000
   ```

4. Enter a company ticker (recommended, e.g. `AAPL`) and click **Fetch Data**.

The button sends a request to the backend endpoint `/fetch-data`, which returns:
- balance sheet
- income statement
- cash flow statement

## Deploy on Render

### Option 1: Using `render.yaml` (recommended)

1. Push this repository to GitHub.
2. In Render, choose **New +** → **Blueprint**.
3. Select your repository.
4. Render will detect `render.yaml` and create the web service.

### Option 2: Manual Render setup

- **Runtime:** Python
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app`
