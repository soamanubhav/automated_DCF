from __future__ import annotations

import math
import os
from typing import Any

from flask import Flask, jsonify, render_template, request
import pandas as pd
import yfinance as yf

app = Flask(__name__)


def _sanitize_json_value(value: Any) -> Any:
    """Recursively convert values into JSON-safe primitives."""
    if isinstance(value, dict):
        return {str(k): _sanitize_json_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple, set)):
        return [_sanitize_json_value(item) for item in value]

    if isinstance(value, pd.Timestamp):
        return value.isoformat()

    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None

    try:
        if pd.isna(value):
            return None
    except TypeError:
        pass

    return value


def _frame_to_dict(frame: Any) -> dict[str, dict[str, Any]]:
    """Convert a yfinance DataFrame to a JSON-safe nested dictionary."""
    if frame is None or getattr(frame, "empty", True):
        return {}

    safe_frame = frame.copy()
    safe_frame.index = safe_frame.index.map(str)
    safe_frame.columns = safe_frame.columns.map(str)
    safe_frame = safe_frame.applymap(_sanitize_json_value)

    raw_data = safe_frame.to_dict(orient="index")
    return _sanitize_json_value(raw_data)


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.post("/fetch-data")
def fetch_data():
    payload = request.get_json(silent=True) or {}
    query = str(payload.get("query", "")).strip()

    if not query:
        return jsonify({"error": "Missing company name or ticker."}), 400

    ticker = yf.Ticker(query)

    balance_sheet = _frame_to_dict(ticker.balance_sheet)
    income_statement = _frame_to_dict(ticker.financials)
    cash_flow_statement = _frame_to_dict(ticker.cashflow)

    if not any([balance_sheet, income_statement, cash_flow_statement]):
        return (
            jsonify(
                {
                    "error": (
                        "No financial statement data found. "
                        "Try a valid ticker symbol such as AAPL or MSFT."
                    )
                }
            ),
            404,
        )

    return jsonify(
        {
            "query": query,
            "balance_sheet": balance_sheet,
            "income_statement": income_statement,
            "cash_flow_statement": cash_flow_statement,
        }
    )


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
    )
