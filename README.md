# Automated DCF - Financial Statement Fetcher

This app uses Flask + yfinance.

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
