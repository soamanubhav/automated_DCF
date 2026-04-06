from __future__ import annotations

import os
from typing import Any

from flask import Flask, jsonify, render_template, request
import yfinance as yf

app = Flask(__name__)


def _frame_to_dict(frame: Any) -> dict[str, dict[str, Any]]:
    """Convert a yfinance DataFrame to a JSON-safe nested dictionary."""
    if frame is None or getattr(frame, "empty", True):
        return {}

    safe_frame = frame.where(frame.notna(), None)
    converted: dict[str, dict[str, Any]] = {}

    for row_name, row_values in safe_frame.to_dict(orient="index").items():
        converted[str(row_name)] = {
            str(column): value for column, value in row_values.items()
        }

    return converted


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
