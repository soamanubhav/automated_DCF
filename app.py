from __future__ import annotations

from typing import Any

import pandas as pd
import yfinance as yf
from flask import Flask, jsonify, render_template, request

app = Flask(__name__)


def _clean_financial_frame(df: pd.DataFrame) -> dict[str, Any]:
    """Convert a yfinance financial statement DataFrame into JSON-friendly rows."""
    if df is None or df.empty:
        return {"columns": [], "rows": []}

    cleaned = df.transpose().copy()
    cleaned.index = cleaned.index.astype(str)
    cleaned = cleaned.sort_index(ascending=False).head(5)
    cleaned = cleaned.where(pd.notnull(cleaned), None)

    for col in cleaned.columns:
        cleaned[col] = pd.to_numeric(cleaned[col], errors="ignore")

    rows = []
    for year, row in cleaned.iterrows():
        row_data = {"year": year}
        for key, value in row.items():
            if value is None:
                row_data[str(key)] = None
            elif isinstance(value, (int, float)):
                row_data[str(key)] = float(value)
            else:
                row_data[str(key)] = value
        rows.append(row_data)

    return {
        "columns": [str(c) for c in cleaned.columns],
        "rows": rows,
    }


@app.get("/")
def home() -> str:
    return render_template("index.html")


@app.post("/fetch-data")
def fetch_data():
    payload = request.get_json(silent=True) or {}
    ticker = (payload.get("ticker") or "RELIANCE.NS").strip().upper()

    if not ticker:
        return jsonify({"error": "Ticker is required."}), 400

    try:
        stock = yf.Ticker(ticker)
        income = _clean_financial_frame(stock.financials)
        balance = _clean_financial_frame(stock.balance_sheet)
        cashflow = _clean_financial_frame(stock.cashflow)

        if not income["rows"] and not balance["rows"] and not cashflow["rows"]:
            return (
                jsonify(
                    {
                        "error": (
                            "No financial data available for this ticker. "
                            "Please verify the symbol and try again."
                        )
                    }
                ),
                404,
            )

        return jsonify(
            {
                "ticker": ticker,
                "income_statement": income,
                "balance_sheet": balance,
                "cash_flow": cashflow,
            }
        )
    except Exception as exc:  # pylint: disable=broad-except
        return (
            jsonify(
                {
                    "error": (
                        "Failed to fetch financial data. "
                        "Please try again later."
                    ),
                    "details": str(exc),
                }
            ),
            500,
        )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
