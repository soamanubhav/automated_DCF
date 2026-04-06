from __future__ import annotations

import math
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
import pandas as pd
import yfinance as yf

app = Flask(__name__, template_folder=".")

CORS(app, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "OPTIONS"])

FORECAST_YEARS = 5
CACHE_TTL_DAYS = 5
COMPANY_CACHE: dict[str, dict[str, Any]] = {}
MANUAL_FINANCIALS: dict[str, dict[str, Any]] = {}


def _sanitize_json_value(value: Any) -> Any:
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
    if frame is None or getattr(frame, "empty", True):
        return {}

    safe_frame = frame.copy()
    safe_frame.index = safe_frame.index.map(str)
    safe_frame.columns = safe_frame.columns.map(str)
    return _sanitize_json_value(safe_frame.to_dict(orient="index"))


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        parsed = float(value)
        if math.isnan(parsed) or math.isinf(parsed):
            return None
        return parsed
    except (TypeError, ValueError):
        return None


def _bounded(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, value))


def _extract_series(frame: pd.DataFrame | None, candidates: list[str]) -> pd.Series:
    if frame is None or frame.empty:
        return pd.Series(dtype="float64")

    for label in candidates:
        if label in frame.index:
            series = pd.to_numeric(frame.loc[label], errors="coerce")
            series.index = pd.to_datetime(series.index, errors="coerce")
            series = series.dropna()
            if series.empty:
                continue
            return series.sort_index()

    return pd.Series(dtype="float64")


def _average(values: list[float], fallback: float) -> float:
    cleaned = [value for value in values if value is not None and math.isfinite(value)]
    if not cleaned:
        return fallback
    return sum(cleaned) / len(cleaned)


def _growth_rates(series: pd.Series) -> list[float]:
    if series.empty:
        return []

    rates: list[float] = []
    values = series.tolist()
    for prev, curr in zip(values, values[1:]):
        if prev and prev != 0:
            rates.append((curr - prev) / prev)
    return rates


def _build_sensitivity(
    base_fcff: float,
    base_wacc: float,
    base_terminal_growth: float,
    discount_t: int,
    present_value_sum: float,
) -> dict[str, Any]:
    wacc_steps = [base_wacc - 0.01, base_wacc - 0.005, base_wacc, base_wacc + 0.005, base_wacc + 0.01]
    growth_steps = [
        base_terminal_growth - 0.01,
        base_terminal_growth - 0.005,
        base_terminal_growth,
        base_terminal_growth + 0.005,
        base_terminal_growth + 0.01,
    ]

    wacc_axis = [round(max(step, 0.01), 4) for step in wacc_steps]
    growth_axis = [round(max(min(step, 0.06), 0.0), 4) for step in growth_steps]

    matrix: list[list[float | None]] = []
    for growth in growth_axis:
        row: list[float | None] = []
        for wacc in wacc_axis:
            if wacc <= growth:
                row.append(None)
                continue

            terminal_value = base_fcff * (1 + growth) / (wacc - growth)
            discounted_terminal = terminal_value / ((1 + wacc) ** discount_t)
            enterprise_value = present_value_sum + discounted_terminal
            row.append(round(enterprise_value, 2))
        matrix.append(row)

    return {
        "wacc_axis": wacc_axis,
        "growth_axis": growth_axis,
        "enterprise_value_matrix": matrix,
    }




def _dict_to_frame(statement_data: dict[str, Any]) -> pd.DataFrame:
    if not isinstance(statement_data, dict) or not statement_data:
        return pd.DataFrame()

    frame = pd.DataFrame.from_dict(statement_data, orient="index")
    frame.columns = frame.columns.map(str)
    frame.index = frame.index.map(str)
    return frame


def _store_manual_financials(payload: dict[str, Any]) -> dict[str, Any]:
    symbol = str(payload.get("query", "")).strip().upper()
    if not symbol:
        raise ValueError("Missing ticker symbol in 'query'.")

    balance_sheet = payload.get("balance_sheet")
    income_statement = payload.get("income_statement")
    cash_flow_statement = payload.get("cash_flow_statement")

    if not isinstance(balance_sheet, dict) or not isinstance(income_statement, dict) or not isinstance(cash_flow_statement, dict):
        raise ValueError("balance_sheet, income_statement, and cash_flow_statement must be JSON objects.")

    now = datetime.now(timezone.utc)
    sanitized_payload = {
        "query": symbol,
        "balance_sheet": _sanitize_json_value(balance_sheet),
        "income_statement": _sanitize_json_value(income_statement),
        "cash_flow_statement": _sanitize_json_value(cash_flow_statement),
        "last_updated": now.isoformat(),
    }

    MANUAL_FINANCIALS[symbol] = sanitized_payload

    # Also hydrate the DCF cache with DataFrame-compatible objects to allow immediate reuse.
    COMPANY_CACHE[symbol] = {
        "ticker": symbol,
        "balance_sheet": _dict_to_frame(sanitized_payload["balance_sheet"]),
        "income_statement": _dict_to_frame(sanitized_payload["income_statement"]),
        "cashflow_statement": _dict_to_frame(sanitized_payload["cash_flow_statement"]),
        "info": {},
        "fetched_at": now,
    }

    return sanitized_payload

def _get_company_financials(ticker_symbol: str) -> dict[str, Any]:
    symbol = ticker_symbol.upper()
    now = datetime.now(timezone.utc)

    cached = COMPANY_CACHE.get(symbol)
    if cached:
        fetched_at = cached["fetched_at"]
        if now - fetched_at < timedelta(days=CACHE_TTL_DAYS):
            return {
                "ticker": cached["ticker"],
                "balance_sheet": cached["balance_sheet"],
                "income_statement": cached["income_statement"],
                "cashflow_statement": cached["cashflow_statement"],
                "info": cached["info"],
                "from_cache": True,
                "last_updated": fetched_at.isoformat(),
            }

    ticker = yf.Ticker(symbol)
    balance_sheet = ticker.balance_sheet
    income_statement = ticker.financials
    cashflow_statement = ticker.cashflow

    if balance_sheet is None or income_statement is None or cashflow_statement is None:
        raise ValueError("Financial statements are not available for this ticker.")

    info = ticker.info or {}

    COMPANY_CACHE[symbol] = {
        "ticker": symbol,
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "cashflow_statement": cashflow_statement,
        "info": info,
        "fetched_at": now,
    }

    return {
        "ticker": symbol,
        "balance_sheet": balance_sheet,
        "income_statement": income_statement,
        "cashflow_statement": cashflow_statement,
        "info": info,
        "from_cache": False,
        "last_updated": now.isoformat(),
    }


def _compute_dcf(company_data: dict[str, Any], assumption_inputs: dict[str, Any]) -> dict[str, Any]:
    ticker_symbol = company_data["ticker"]
    balance_sheet = company_data["balance_sheet"]
    income_statement = company_data["income_statement"]
    cashflow_statement = company_data["cashflow_statement"]
    info = company_data["info"]

    revenue_series = _extract_series(income_statement, ["Total Revenue", "Operating Revenue"])
    ebit_series = _extract_series(income_statement, ["EBIT", "Operating Income"])
    tax_provision_series = _extract_series(income_statement, ["Tax Provision"])
    pretax_income_series = _extract_series(income_statement, ["Pretax Income"])
    depreciation_series = _extract_series(cashflow_statement, ["Depreciation And Amortization", "Depreciation"])
    capex_series = _extract_series(cashflow_statement, ["Capital Expenditure", "Purchase Of PPE"])
    ppe_series = _extract_series(balance_sheet, ["Property Plant Equipment", "Net PPE", "Gross PPE"])

    current_assets_series = _extract_series(balance_sheet, ["Current Assets"])
    current_liabilities_series = _extract_series(balance_sheet, ["Current Liabilities"])
    nwc_series = current_assets_series.subtract(current_liabilities_series, fill_value=0)

    if revenue_series.empty or ebit_series.empty:
        raise ValueError("Not enough revenue/EBIT data to build a DCF model.")

    revenue_growth_default = _bounded(_average(_growth_rates(revenue_series)[-3:], 0.08), -0.2, 0.30)

    aligned_ebit_margin = (ebit_series / revenue_series).replace([math.inf, -math.inf], pd.NA).dropna()
    ebit_margin_default = _bounded(_average(aligned_ebit_margin.tolist()[-3:], 0.18), 0.02, 0.50)

    dep_rate_series = (depreciation_series.abs() / ppe_series.abs()).replace([math.inf, -math.inf], pd.NA).dropna()
    depreciation_rate_default = _bounded(_average(dep_rate_series.tolist()[-3:], 0.04), 0.01, 0.15)

    capex_percent_series = (capex_series.abs() / revenue_series.abs()).replace([math.inf, -math.inf], pd.NA).dropna()
    capex_percent_default = _bounded(_average(capex_percent_series.tolist()[-3:], 0.06), 0.01, 0.20)

    nwc_percent_series = (nwc_series / revenue_series).replace([math.inf, -math.inf], pd.NA).dropna()
    nwc_percent_default = _bounded(_average(nwc_percent_series.tolist()[-3:], 0.08), 0.0, 0.25)

    tax_rate_series = (tax_provision_series / pretax_income_series).replace([math.inf, -math.inf], pd.NA).dropna()
    tax_rate_default = _bounded(_average(tax_rate_series.tolist()[-3:], 0.23), 0.10, 0.35)

    defaults = {
        "revenue_growth_rate": revenue_growth_default,
        "ebit_margin": ebit_margin_default,
        "depreciation_rate": depreciation_rate_default,
        "capex_percent": capex_percent_default,
        "nwc_percent": nwc_percent_default,
        "wacc": 0.10,
        "terminal_growth_rate": 0.03,
        "tax_rate": tax_rate_default,
    }

    assumptions: dict[str, float] = {}
    defaulted_fields: list[str] = []
    for key, default_value in defaults.items():
        provided = _safe_float(assumption_inputs.get(key))
        if provided is None:
            assumptions[key] = default_value
            defaulted_fields.append(key)
        else:
            assumptions[key] = provided

    assumptions["wacc"] = _bounded(assumptions["wacc"], 0.03, 0.30)
    assumptions["terminal_growth_rate"] = _bounded(assumptions["terminal_growth_rate"], 0.0, 0.06)
    assumptions["revenue_growth_rate"] = _bounded(assumptions["revenue_growth_rate"], -0.2, 0.35)
    assumptions["ebit_margin"] = _bounded(assumptions["ebit_margin"], 0.01, 0.60)
    assumptions["depreciation_rate"] = _bounded(assumptions["depreciation_rate"], 0.0, 0.25)
    assumptions["capex_percent"] = _bounded(assumptions["capex_percent"], 0.0, 0.35)
    assumptions["nwc_percent"] = _bounded(assumptions["nwc_percent"], -0.10, 0.35)
    assumptions["tax_rate"] = _bounded(assumptions["tax_rate"], 0.0, 0.45)

    if assumptions["wacc"] <= assumptions["terminal_growth_rate"]:
        raise ValueError("WACC must be greater than terminal growth rate.")

    revenue = float(revenue_series.iloc[-1])
    opening_ppe = float(ppe_series.iloc[-1]) if not ppe_series.empty else revenue * 0.5

    historical_nwc = nwc_series.dropna()
    previous_nwc = float(historical_nwc.iloc[-1]) if not historical_nwc.empty else revenue * assumptions["nwc_percent"]

    forecast_rows: list[dict[str, float]] = []
    pv_fcff_total = 0.0

    for year in range(1, FORECAST_YEARS + 1):
        revenue = revenue * (1 + assumptions["revenue_growth_rate"])
        ebit = revenue * assumptions["ebit_margin"]
        nopat = ebit * (1 - assumptions["tax_rate"])

        depreciation = opening_ppe * assumptions["depreciation_rate"]
        capex = revenue * assumptions["capex_percent"]
        closing_ppe = opening_ppe + capex - depreciation

        nwc = revenue * assumptions["nwc_percent"]
        delta_nwc = nwc - previous_nwc
        previous_nwc = nwc

        fcff = nopat + depreciation - capex - delta_nwc
        discount_factor = (1 + assumptions["wacc"]) ** year
        pv_fcff = fcff / discount_factor
        pv_fcff_total += pv_fcff

        forecast_rows.append(
            {
                "year": year,
                "revenue": revenue,
                "ebit": ebit,
                "nopat": nopat,
                "depreciation": depreciation,
                "capex": capex,
                "opening_ppe": opening_ppe,
                "closing_ppe": closing_ppe,
                "nwc": nwc,
                "delta_nwc": delta_nwc,
                "fcff": fcff,
                "discount_factor": discount_factor,
                "pv_fcff": pv_fcff,
            }
        )

        opening_ppe = closing_ppe

    final_fcff = forecast_rows[-1]["fcff"]
    terminal_value = final_fcff * (1 + assumptions["terminal_growth_rate"]) / (
        assumptions["wacc"] - assumptions["terminal_growth_rate"]
    )
    discounted_terminal = terminal_value / ((1 + assumptions["wacc"]) ** FORECAST_YEARS)

    enterprise_value = pv_fcff_total + discounted_terminal

    cash_series = _extract_series(balance_sheet, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])
    debt_long_series = _extract_series(balance_sheet, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"])
    debt_current_series = _extract_series(balance_sheet, ["Current Debt"])

    cash = float(cash_series.iloc[-1]) if not cash_series.empty else 0.0
    debt = 0.0
    if not debt_long_series.empty:
        debt += float(debt_long_series.iloc[-1])
    if not debt_current_series.empty:
        debt += float(debt_current_series.iloc[-1])

    equity_value = enterprise_value + cash - debt

    shares = float(info.get("sharesOutstanding") or 0)
    if shares <= 0:
        shares = 1.0

    price_per_share = equity_value / shares

    sensitivity = _build_sensitivity(
        base_fcff=final_fcff,
        base_wacc=assumptions["wacc"],
        base_terminal_growth=assumptions["terminal_growth_rate"],
        discount_t=FORECAST_YEARS,
        present_value_sum=pv_fcff_total,
    )

    return {
        "query": ticker_symbol,
        "assumptions": assumptions,
        "defaulted_fields": defaulted_fields,
        "forecast": _sanitize_json_value(forecast_rows),
        "valuation": {
            "pv_fcff_sum": pv_fcff_total,
            "terminal_value": terminal_value,
            "discounted_terminal_value": discounted_terminal,
            "enterprise_value": enterprise_value,
            "cash": cash,
            "debt": debt,
            "equity_value": equity_value,
            "shares_outstanding": shares,
            "intrinsic_price_per_share": price_per_share,
        },
        "sensitivity": sensitivity,
        "source_data": {
            "balance_sheet": _frame_to_dict(balance_sheet),
            "income_statement": _frame_to_dict(income_statement),
            "cash_flow_statement": _frame_to_dict(cashflow_statement),
        },
    }


@app.get("/")
def index() -> str:
    return render_template("index.html")


@app.get("/styles.css")
def styles() -> Any:
    return send_from_directory(".", "styles.css")


@app.get("/script.js")
def script() -> Any:
    return send_from_directory(".", "script.js")


@app.route("/fetch-data", methods=["GET", "POST"])
def fetch_data():
    if request.method == "GET":
        query = str(request.args.get("query", "")).strip().upper()
    else:
        payload = request.get_json(silent=True) or {}
        query = str(payload.get("query", "")).strip().upper()

    if not query:
        return jsonify({"error": "Missing company name or ticker."}), 400

    try:
        company_data = _get_company_financials(query)
        balance_sheet = _frame_to_dict(company_data["balance_sheet"])
        income_statement = _frame_to_dict(company_data["income_statement"])
        cash_flow_statement = _frame_to_dict(company_data["cashflow_statement"])
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Failed to fetch financial data: {exc}"}), 502

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
            "from_cache": company_data["from_cache"],
            "last_updated": company_data["last_updated"],
            "balance_sheet": balance_sheet,
            "income_statement": income_statement,
            "cash_flow_statement": cash_flow_statement,
        }
    )


@app.route("/company-financials", methods=["GET", "POST"])
def company_financials_json():
    if request.method == "GET":
        query = str(request.args.get("query", "")).strip().upper()
        if not query:
            return jsonify({"error": "Missing company ticker for retrieval."}), 400

        data = MANUAL_FINANCIALS.get(query)
        if not data:
            return jsonify({"error": "No stored JSON financials found for this ticker."}), 404

        return jsonify(data)

    payload = request.get_json(silent=True) or {}

    try:
        stored = _store_manual_financials(payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    return jsonify({"message": "Company financial JSON stored successfully.", **stored})


@app.route("/dcf", methods=["GET", "POST"])
def dcf_valuation():
    if request.method == "GET":
        payload = dict(request.args)
    else:
        payload = request.get_json(silent=True) or {}

    query = str(payload.get("query", "")).strip().upper()

    if not query:
        return jsonify({"error": "Missing company ticker for DCF valuation."}), 400

    assumptions = payload.get("assumptions", {})
    if not isinstance(assumptions, dict):
        return jsonify({"error": "Assumptions must be a JSON object."}), 400

    try:
        company_data = _get_company_financials(query)
        result = _compute_dcf(company_data, assumptions)
        result["from_cache"] = company_data["from_cache"]
        result["last_updated"] = company_data["last_updated"]
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    except Exception as exc:
        return jsonify({"error": f"Failed to compute DCF model: {exc}"}), 502

    return jsonify(_sanitize_json_value(result))


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true",
    )
