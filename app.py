from __future__ import annotations

import json
import logging
import math
import os
import random
import time
from datetime import datetime, timedelta, timezone
from typing import Any

from flask import Flask, jsonify, render_template, request, send_from_directory
from flask_cors import CORS
import pandas as pd
from supabase import Client, create_client
import yfinance as yf

app = Flask(__name__, template_folder='.')

CORS(app, resources={r"/*": {"origins": "*"}}, methods=["GET", "POST", "OPTIONS"])

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

FORECAST_YEARS = 5
CACHE_TTL_DAYS = 5
SUPABASE_TTL_DAYS = 60
YFINANCE_RETRY_DELAYS = [2, 4, 6]
DEFAULT_SUPABASE_URL = "https://siktkhguuriujksehvoy.supabase.co"
DEFAULT_SUPABASE_KEY = "sb_publishable_TWk9qxiciXlM4Cd3qR61Ww_t2wjcf0i"
DEFAULT_PROXY_LIST = [
    "http://cunkpcet:6hjr3wvrwsg1@31.59.20.176:6754",
    "http://cunkpcet:6hjr3wvrwsg1@23.95.150.145:6114",
    "http://cunkpcet:6hjr3wvrwsg1@198.23.239.134:6540",
    "http://cunkpcet:6hjr3wvrwsg1@45.38.107.97:6014",
    "http://cunkpcet:6hjr3wvrwsg1@107.172.163.27:6543",
    "http://cunkpcet:6hjr3wvrwsg1@198.105.121.200:6462",
    "http://cunkpcet:6hjr3wvrwsg1@216.10.27.159:6837",
    "http://cunkpcet:6hjr3wvrwsg1@142.111.67.146:5611",
    "http://cunkpcet:6hjr3wvrwsg1@191.96.254.138:6185",
    "http://cunkpcet:6hjr3wvrwsg1@31.58.9.4:6077",
]
COMPANY_CACHE: dict[str, dict[str, Any]] = {}


class RateLimitError(RuntimeError):
    pass


class InvalidTickerError(ValueError):
    pass


class SupabaseFetchError(RuntimeError):
    pass


class YFinanceFetchError(RuntimeError):
    pass


def _get_supabase_client() -> Client | None:
    url = os.environ.get("SUPABASE_URL") or DEFAULT_SUPABASE_URL
    key = os.environ.get("SUPABASE_KEY") or DEFAULT_SUPABASE_KEY
    if not url or not key:
        return None
    return create_client(url, key)


def _parse_proxy_list() -> list[str]:
    raw = (os.environ.get("PROXY_LIST") or "").strip()
    if not raw:
        return DEFAULT_PROXY_LIST.copy()

    normalized = raw.replace("\\\n", ",").replace("\n", ",")

    try:
        loaded = json.loads(normalized)
        if isinstance(loaded, list):
            return [str(item).strip() for item in loaded if str(item).strip()]
    except json.JSONDecodeError:
        pass

    cleaned = normalized.strip("[]")
    items = [item.strip().strip("\"'").strip("\\") for item in cleaned.split(",")]
    return [item for item in items if item]


def _proxy_label(proxy: str | None) -> str:
    if not proxy:
        return "direct"

    host = proxy
    if "@" in host:
        host = host.split("@", 1)[1]
    if "://" in host:
        host = host.split("://", 1)[1]
    host = host.split(":", 1)[0]

    octets = host.split(".")
    if len(octets) == 4:
        return f"{octets[0]}.{octets[1]}.X.X"
    return host


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


def _dict_to_frame(data: dict[str, dict[str, Any]] | None) -> pd.DataFrame:
    if not data:
        return pd.DataFrame()

    frame = pd.DataFrame.from_dict(data, orient="index")
    try:
        frame.columns = pd.to_datetime(frame.columns)
    except (TypeError, ValueError):
        pass
    return frame


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
    cash: float,
    debt: float,
    shares_outstanding: float,
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

    enterprise_value_matrix: list[list[float | None]] = []
    equity_value_matrix: list[list[float | None]] = []
    share_price_matrix: list[list[float | None]] = []
    for growth in growth_axis:
        enterprise_row: list[float | None] = []
        equity_row: list[float | None] = []
        price_row: list[float | None] = []
        for wacc in wacc_axis:
            if wacc <= growth:
                enterprise_row.append(None)
                equity_row.append(None)
                price_row.append(None)
                continue

            terminal_value = base_fcff * (1 + growth) / (wacc - growth)
            discounted_terminal = terminal_value / ((1 + wacc) ** discount_t)
            enterprise_value = present_value_sum + discounted_terminal
            equity_value = enterprise_value + cash - debt
            fair_value_per_share = equity_value / shares_outstanding if shares_outstanding > 0 else None

            enterprise_row.append(round(enterprise_value, 2))
            equity_row.append(round(equity_value, 2))
            price_row.append(round(fair_value_per_share, 2) if fair_value_per_share is not None else None)
        enterprise_value_matrix.append(enterprise_row)
        equity_value_matrix.append(equity_row)
        share_price_matrix.append(price_row)

    return {
        "wacc_axis": wacc_axis,
        "growth_axis": growth_axis,
        "enterprise_value_matrix": enterprise_value_matrix,
        "equity_value_matrix": equity_value_matrix,
        "share_price_matrix": share_price_matrix,
    }


def get_from_supabase(ticker: str) -> dict[str, Any] | None:
    client = _get_supabase_client()
    if client is None:
        return None

    try:
        response = (
            client.table("financial_cache")
            .select("ticker,balance_sheet,income_statement,cash_flow_statement,fetched_at")
            .eq("ticker", ticker)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        raise SupabaseFetchError(f"Supabase query failed: {exc}") from exc

    rows = response.data or []
    if not rows:
        return None

    row = rows[0]
    fetched_at_raw = row.get("fetched_at")
    fetched_at = pd.to_datetime(fetched_at_raw, utc=True, errors="coerce")
    if fetched_at is pd.NaT:
        return None

    return {
        "ticker": ticker,
        "balance_sheet": _dict_to_frame(row.get("balance_sheet") or {}),
        "income_statement": _dict_to_frame(row.get("income_statement") or {}),
        "cashflow_statement": _dict_to_frame(row.get("cash_flow_statement") or {}),
        "info": {},
        "fetched_at": fetched_at.to_pydatetime(),
        "last_updated": fetched_at.isoformat(),
    }


def save_to_supabase(ticker: str, data: dict[str, Any]) -> None:
    client = _get_supabase_client()
    if client is None:
        return

    payload = {
        "ticker": ticker,
        "balance_sheet": _frame_to_dict(data["balance_sheet"]),
        "income_statement": _frame_to_dict(data["income_statement"]),
        "cash_flow_statement": _frame_to_dict(data["cashflow_statement"]),
        "fetched_at": data["fetched_at"].isoformat(),
    }

    try:
        client.table("financial_cache").upsert(payload).execute()
    except Exception as exc:
        raise SupabaseFetchError(f"Supabase upsert failed: {exc}") from exc


def get_proxy_session() -> str | None:
    proxies = _parse_proxy_list()
    if proxies:
        proxy = random.choice(proxies)
        logger.info("Using proxy: %s", _proxy_label(proxy))
        return proxy

    logger.info("Using proxy: direct")
    return None


def fetch_from_yfinance_with_retry(ticker: str) -> dict[str, Any]:
    last_error: Exception | None = None

    for attempt, delay in enumerate(YFINANCE_RETRY_DELAYS, start=1):
        proxy = get_proxy_session()
        prev_http = os.environ.get("HTTP_PROXY")
        prev_https = os.environ.get("HTTPS_PROXY")

        if proxy:
            os.environ["HTTP_PROXY"] = proxy
            os.environ["HTTPS_PROXY"] = proxy
        else:
            os.environ.pop("HTTP_PROXY", None)
            os.environ.pop("HTTPS_PROXY", None)

        try:
            stock = yf.Ticker(ticker)
            balance_sheet = stock.balance_sheet
            income_statement = stock.financials
            cashflow_statement = stock.cashflow
            info = stock.info or {}

            if all(getattr(frame, "empty", True) for frame in [balance_sheet, income_statement, cashflow_statement]):
                raise InvalidTickerError(f"Invalid ticker or no financial statements found for '{ticker}'.")

            if balance_sheet is None or income_statement is None or cashflow_statement is None:
                raise InvalidTickerError(f"Financial statements are not available for '{ticker}'.")

            now = datetime.now(timezone.utc)
            logger.info("Fetched from yfinance")
            return {
                "ticker": ticker,
                "balance_sheet": balance_sheet,
                "income_statement": income_statement,
                "cashflow_statement": cashflow_statement,
                "info": info,
                "fetched_at": now,
                "last_updated": now.isoformat(),
                "from_cache": False,
            }
        except InvalidTickerError:
            raise
        except Exception as exc:
            message = str(exc).lower()
            if any(token in message for token in ["429", "rate limit", "too many requests"]):
                last_error = RateLimitError(f"Rate limited by yfinance for '{ticker}'.")
            else:
                last_error = exc

            logger.warning("yfinance fetch failed for %s on attempt %s: %s", ticker, attempt, exc)
            if attempt < len(YFINANCE_RETRY_DELAYS):
                time.sleep(delay)
        finally:
            if prev_http is None:
                os.environ.pop("HTTP_PROXY", None)
            else:
                os.environ["HTTP_PROXY"] = prev_http
            if prev_https is None:
                os.environ.pop("HTTPS_PROXY", None)
            else:
                os.environ["HTTPS_PROXY"] = prev_https

    if isinstance(last_error, RateLimitError):
        raise last_error
    raise YFinanceFetchError(f"Failed to fetch yfinance data for '{ticker}': {last_error}")


def _get_company_financials(ticker_symbol: str) -> dict[str, Any]:
    symbol = ticker_symbol.upper()
    now = datetime.now(timezone.utc)

    cached = COMPANY_CACHE.get(symbol)
    if cached and now - cached["fetched_at"] < timedelta(days=CACHE_TTL_DAYS):
        return {
            "ticker": cached["ticker"],
            "balance_sheet": cached["balance_sheet"],
            "income_statement": cached["income_statement"],
            "cashflow_statement": cached["cashflow_statement"],
            "info": cached.get("info", {}),
            "from_cache": True,
            "last_updated": cached["fetched_at"].isoformat(),
        }

    try:
        supabase_data = get_from_supabase(symbol)
        if supabase_data and now - supabase_data["fetched_at"] < timedelta(days=SUPABASE_TTL_DAYS):
            logger.info("Loaded from Supabase")
            COMPANY_CACHE[symbol] = {
                "ticker": symbol,
                "balance_sheet": supabase_data["balance_sheet"],
                "income_statement": supabase_data["income_statement"],
                "cashflow_statement": supabase_data["cashflow_statement"],
                "info": supabase_data.get("info", {}),
                "fetched_at": supabase_data["fetched_at"],
            }
            return {
                "ticker": symbol,
                "balance_sheet": supabase_data["balance_sheet"],
                "income_statement": supabase_data["income_statement"],
                "cashflow_statement": supabase_data["cashflow_statement"],
                "info": supabase_data.get("info", {}),
                "from_cache": True,
                "last_updated": supabase_data["fetched_at"].isoformat(),
            }
    except SupabaseFetchError as exc:
        logger.warning("Supabase read failed for %s; falling back to yfinance: %s", symbol, exc)

    fresh_data = fetch_from_yfinance_with_retry(symbol)

    COMPANY_CACHE[symbol] = {
        "ticker": symbol,
        "balance_sheet": fresh_data["balance_sheet"],
        "income_statement": fresh_data["income_statement"],
        "cashflow_statement": fresh_data["cashflow_statement"],
        "info": fresh_data["info"],
        "fetched_at": fresh_data["fetched_at"],
    }

    try:
        save_to_supabase(symbol, COMPANY_CACHE[symbol])
    except SupabaseFetchError as exc:
        logger.warning("Supabase save failed for %s (continuing): %s", symbol, exc)

    return fresh_data


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
        cash=cash,
        debt=debt,
        shares_outstanding=shares,
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
    except InvalidTickerError as exc:
        return jsonify({"error": str(exc), "error_type": "invalid_ticker"}), 400
    except RateLimitError as exc:
        return jsonify({"error": str(exc), "error_type": "rate_limit"}), 429
    except YFinanceFetchError as exc:
        return jsonify({"error": str(exc), "error_type": "yfinance_failure"}), 502
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
    except InvalidTickerError as exc:
        return jsonify({"error": str(exc), "error_type": "invalid_ticker"}), 400
    except RateLimitError as exc:
        return jsonify({"error": str(exc), "error_type": "rate_limit"}), 429
    except YFinanceFetchError as exc:
        return jsonify({"error": str(exc), "error_type": "yfinance_failure"}), 502
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
