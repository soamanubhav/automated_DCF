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

## Deploy on Render (step by step)

### 1) Push code to GitHub

1. Create a GitHub repository (or use an existing one).
2. Push this project branch to GitHub.

### 2) Create a Render account

1. Go to [https://render.com](https://render.com).
2. Sign in with GitHub (recommended for automatic deploys).

### 3) Deploy with Blueprint (`render.yaml`) — recommended

1. In Render dashboard, click **New +**.
2. Select **Blueprint**.
3. Choose your GitHub repo.
4. Render auto-detects `render.yaml` and pre-fills service settings.
5. Click **Apply** / **Create** to start deployment.

Current blueprint settings from this repo:
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app`
- Runtime: Python

### 4) Wait for first deploy

1. Open your new web service in Render.
2. Watch the deploy logs until you see a successful startup.
3. Open the generated Render URL (for example `https://<service-name>.onrender.com`).

### 5) Verify the app works

1. Visit the root URL and confirm the UI loads.
2. Enter a ticker such as `AAPL` and click **Fetch Data**.
3. Confirm JSON output appears with statement sections.

### 6) Optional: set manual environment variables

Most setups work without extra env vars, but you can set:
- `FLASK_DEBUG=false` (recommended in production)

> Note: Render automatically provides the `PORT` environment variable. The app already reads this variable.

### 7) Enable auto-deploys

1. In Render service settings, ensure **Auto-Deploy** is enabled.
2. Each push to your connected branch will trigger a new deployment.

### 8) Troubleshooting checklist

- **Build fails**: confirm `requirements.txt` includes all needed packages.
- **App doesn’t start**: verify start command is `gunicorn app:app`.
- **Button shows backend unreachable**: check service logs and confirm app is healthy.
- **No data for a company**: use a valid ticker symbol (e.g., `MSFT`, `GOOGL`, `AMZN`).

## Manual Render setup (without Blueprint)

If you do not want to use `render.yaml`, set this manually in Render:

- **Service type:** Web Service
- **Runtime:** Python
- **Build Command:** `pip install -r requirements.txt`
- **Start Command:** `gunicorn app:app`

## Use this API in your own website

If your site is hosted on another domain, call the deployed endpoint directly:

- API URL: `https://automated-dcf.onrender.com/fetch-data`
- Method: `POST`
- JSON body: `{ "query": "AAPL" }`

### Example frontend snippet

```html
<input id="ticker" placeholder="AAPL" />
<button id="fetch-data">Fetch Data</button>
<pre id="result"></pre>

<script>
  document.getElementById('fetch-data').addEventListener('click', async () => {
    const query = document.getElementById('ticker').value.trim();
    const res = await fetch('https://automated-dcf.onrender.com/fetch-data', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query })
    });

    const contentType = res.headers.get('content-type') || '';
    if (!contentType.includes('application/json')) {
      const text = await res.text();
      throw new Error(`Non-JSON response (HTTP ${res.status}): ${text.slice(0, 120)}`);
    }

    const data = await res.json();
    if (!res.ok) throw new Error(data.error || `HTTP ${res.status}`);

    document.getElementById('result').textContent = JSON.stringify(data, null, 2);
  });
</script>
```

### CORS control

- By default, this project allows all origins for `/fetch-data`.
- For production hardening, set `CORS_ORIGINS` on Render as a comma-separated list:

```text
https://yourdomain.com,https://www.yourdomain.com
```
