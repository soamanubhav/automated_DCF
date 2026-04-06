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


def _series_latest_value(series: pd.Series, default: float = 0.0) -> float:
    cleaned = pd.to_numeric(series, errors="coerce").replace([math.inf, -math.inf], pd.NA).dropna()
    if cleaned.empty:
        return default
    return float(cleaned.iloc[-1])


def _require_finite(name: str, value: float) -> None:
    if value is None or not math.isfinite(value):
        raise ValueError(f"{name} must be finite.")


def _get_share_count(info: dict[str, Any]) -> float:
    for field in ("sharesOutstanding", "floatShares", "impliedSharesOutstanding"):
        shares = _safe_float(info.get(field))
        if shares and shares > 0:
            return shares
    raise ValueError("Shares outstanding is unavailable for this ticker.")


def _compute_operating_nwc(balance_sheet: pd.DataFrame, revenue_series: pd.Series) -> pd.Series:
    receivables = _extract_series(balance_sheet, ["Accounts Receivable", "Receivables"])
    inventory = _extract_series(balance_sheet, ["Inventory", "Inventories"])
    payables = _extract_series(balance_sheet, ["Accounts Payable", "Payables"])
    op_nwc = receivables.add(inventory, fill_value=0).subtract(payables, fill_value=0).dropna()
    if not op_nwc.empty:
        return op_nwc.sort_index()

    current_assets_series = _extract_series(balance_sheet, ["Current Assets"])
    current_liabilities_series = _extract_series(balance_sheet, ["Current Liabilities"])
    nwc_series = current_assets_series.subtract(current_liabilities_series, fill_value=0)
    if not nwc_series.empty:
        return nwc_series.sort_index()

    if revenue_series.empty:
        return pd.Series(dtype="float64")
    return revenue_series * 0.08


def compute_assumptions(company_data: dict[str, Any], assumption_inputs: dict[str, Any]) -> tuple[dict[str, float], list[str], dict[str, Any]]:
    balance_sheet = company_data["balance_sheet"]
    income_statement = company_data["income_statement"]
    info = company_data["info"] or {}

    revenue_series = _extract_series(income_statement, ["Total Revenue", "Operating Revenue"])
    ebit_series = _extract_series(income_statement, ["EBIT", "Operating Income"])
    tax_provision_series = _extract_series(income_statement, ["Tax Provision"])
    pretax_income_series = _extract_series(income_statement, ["Pretax Income"])
    interest_expense_series = _extract_series(income_statement, ["Interest Expense", "InterestExpense"])
    ppe_series = _extract_series(balance_sheet, ["Property Plant Equipment", "Net PPE", "Gross PPE"])
    op_nwc_series = _compute_operating_nwc(balance_sheet, revenue_series)
    invested_capital_series = ppe_series.add(op_nwc_series, fill_value=0).dropna()

    if revenue_series.empty or ebit_series.empty:
        raise ValueError("Not enough revenue/EBIT data to build a DCF model.")

    aligned_margin = (ebit_series / revenue_series).replace([math.inf, -math.inf], pd.NA).dropna()
    revenue_growth_default = _bounded(_average(_growth_rates(revenue_series)[-3:], 0.07), -0.2, 0.25)
    ebit_margin_default = _bounded(_average(aligned_margin.tolist()[-3:], 0.18), 0.02, 0.55)

    pretax_pos_mask = pretax_income_series > 0
    tax_rate_series = (tax_provision_series[pretax_pos_mask] / pretax_income_series[pretax_pos_mask]).replace(
        [math.inf, -math.inf], pd.NA
    ).dropna()
    tax_rate_default = _bounded(_average(tax_rate_series.tolist()[-3:], 0.25), 0.10, 0.35)

    nopat_series = ebit_series * (1 - tax_rate_default)
    invested_capital_avg = invested_capital_series.rolling(2).mean().dropna()
    roic_series = (nopat_series / invested_capital_avg).replace([math.inf, -math.inf], pd.NA).dropna()
    roic_default = _bounded(_average(roic_series.tolist()[-3:], 0.12), 0.06, 0.35)
    terminal_roic_default = _bounded(roic_default * 0.85, 0.06, 0.20)

    beta = _safe_float(info.get("beta")) or 1.0
    risk_free_rate = _safe_float(info.get("riskFreeRate")) or 0.0425
    equity_risk_premium = _safe_float(info.get("equityRiskPremium")) or 0.05
    cost_of_equity_default = _bounded(risk_free_rate + beta * equity_risk_premium, 0.05, 0.20)

    debt_long = _series_latest_value(_extract_series(balance_sheet, ["Long Term Debt", "Long Term Debt And Capital Lease Obligation"]))
    debt_current = _series_latest_value(_extract_series(balance_sheet, ["Current Debt"]))
    debt_value = max(debt_long + debt_current, 0.0)
    interest_expense = abs(_series_latest_value(interest_expense_series, 0.0))
    cost_of_debt_default = _bounded((interest_expense / debt_value) if debt_value > 0 else 0.06, 0.03, 0.15)
    market_cap = _safe_float(info.get("marketCap")) or 0.0
    total_capital = market_cap + debt_value
    if total_capital > 0:
        weight_equity = market_cap / total_capital
        weight_debt = debt_value / total_capital
        wacc_default = (weight_equity * cost_of_equity_default) + (weight_debt * cost_of_debt_default * (1 - tax_rate_default))
    else:
        wacc_default = 0.10
    wacc_default = _bounded(wacc_default, 0.05, 0.20)

    defaults = {
        "revenue_growth_rate": revenue_growth_default,
        "terminal_growth_rate": 0.03,
        "ebit_margin": ebit_margin_default,
        "terminal_ebit_margin": _bounded(ebit_margin_default * 0.9, 0.02, 0.45),
        "tax_rate": tax_rate_default,
        "roic": roic_default,
        "terminal_roic": terminal_roic_default,
        "wacc": wacc_default,
        "cost_of_equity": cost_of_equity_default,
        "cost_of_debt": cost_of_debt_default,
        # Backward-compatible assumption fields retained:
        "depreciation_rate": 0.0,
        "capex_percent": 0.0,
        "nwc_percent": 0.0,
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

    assumptions["tax_rate"] = _bounded(assumptions["tax_rate"], 0.10, 0.35)
    assumptions["revenue_growth_rate"] = _bounded(assumptions["revenue_growth_rate"], -0.2, 0.30)
    assumptions["terminal_growth_rate"] = _bounded(assumptions["terminal_growth_rate"], 0.0, 0.045)
    assumptions["ebit_margin"] = _bounded(assumptions["ebit_margin"], 0.01, 0.65)
    assumptions["terminal_ebit_margin"] = _bounded(assumptions["terminal_ebit_margin"], 0.01, 0.50)
    assumptions["roic"] = _bounded(assumptions["roic"], 0.05, 0.50)
    assumptions["terminal_roic"] = _bounded(assumptions["terminal_roic"], 0.05, 0.30)
    assumptions["wacc"] = _bounded(assumptions["wacc"], 0.04, 0.30)
    assumptions["cost_of_equity"] = _bounded(assumptions["cost_of_equity"], 0.04, 0.30)
    assumptions["cost_of_debt"] = _bounded(assumptions["cost_of_debt"], 0.02, 0.20)

    if assumptions["wacc"] <= assumptions["terminal_growth_rate"]:
        raise ValueError("WACC must be greater than terminal growth rate.")

    shares = _get_share_count(info)
    if shares <= 0:
        raise ValueError("Shares outstanding must be greater than zero.")

    context = {
        "revenue_last": _series_latest_value(revenue_series),
        "ebit_last": _series_latest_value(ebit_series),
        "invested_capital_last": _series_latest_value(invested_capital_series, _series_latest_value(revenue_series) * 0.5),
        "cash": _series_latest_value(
            _extract_series(balance_sheet, ["Cash And Cash Equivalents", "Cash Cash Equivalents And Short Term Investments"])
        ),
        "debt": debt_value,
        "shares": shares,
    }
    _require_finite("Revenue", context["revenue_last"])
    _require_finite("EBIT", context["ebit_last"])
    _require_finite("Invested capital", context["invested_capital_last"])
    return assumptions, defaulted_fields, context


def project_cashflows(assumptions: dict[str, float], context: dict[str, Any]) -> tuple[list[dict[str, float]], float, float, float]:
    revenue = context["revenue_last"]
    invested_capital = max(context["invested_capital_last"], 1.0)
    pv_fcff_sum = 0.0
    forecast_rows: list[dict[str, float]] = []

    for year in range(1, 11):
        if year <= 5:
            growth = assumptions["revenue_growth_rate"]
            margin = assumptions["ebit_margin"]
            roic = assumptions["roic"]
        else:
            fade = (year - 5) / 5.0
            growth = assumptions["revenue_growth_rate"] + fade * (assumptions["terminal_growth_rate"] - assumptions["revenue_growth_rate"])
            margin = assumptions["ebit_margin"] + fade * (
                assumptions["terminal_ebit_margin"] - assumptions["ebit_margin"]
            )
            roic = assumptions["roic"] + fade * (assumptions["terminal_roic"] - assumptions["roic"])

        growth = _bounded(growth, -0.2, 0.30)
        margin = _bounded(margin, 0.01, 0.65)
        roic = _bounded(roic, 0.05, 0.50)

        revenue = revenue * (1 + growth)
        ebit = revenue * margin
        nopat = ebit * (1 - assumptions["tax_rate"])
        reinvestment_rate = _bounded(growth / roic if roic > 0 else 0.0, 0.0, 0.90)
        reinvestment = nopat * reinvestment_rate
        invested_capital += reinvestment
        fcff = nopat - reinvestment

        _require_finite("FCFF", fcff)
        discount_factor = (1 + assumptions["wacc"]) ** year
        pv_fcff = fcff / discount_factor
        pv_fcff_sum += pv_fcff

        forecast_rows.append(
            {
                "year": year,
                "revenue": revenue,
                "ebit": ebit,
                "nopat": nopat,
                "reinvestment": reinvestment,
                "reinvestment_rate": reinvestment_rate,
                "invested_capital": invested_capital,
                "roic": roic,
                "depreciation": 0.0,
                "capex": reinvestment,
                "nwc": 0.0,
                "delta_nwc": 0.0,
                "fcff": fcff,
                "discount_factor": discount_factor,
                "pv_fcff": pv_fcff,
            }
        )

    terminal_growth = min(assumptions["terminal_growth_rate"], 0.045)
    terminal_roic = max(assumptions["terminal_roic"], 0.05)
    terminal_reinvestment_rate = _bounded(terminal_growth / terminal_roic, 0.0, 0.80)
    terminal_fcff = forecast_rows[-1]["nopat"] * (1 - terminal_reinvestment_rate)
    _require_finite("Terminal FCFF", terminal_fcff)
    return forecast_rows, pv_fcff_sum, terminal_fcff, terminal_reinvestment_rate


def compute_terminal_value(assumptions: dict[str, float], terminal_fcff: float) -> tuple[float, float]:
    terminal_growth = min(assumptions["terminal_growth_rate"], 0.045)
    if assumptions["wacc"] <= terminal_growth:
        raise ValueError("WACC must be greater than terminal growth rate.")
    terminal_value = terminal_fcff * (1 + terminal_growth) / (assumptions["wacc"] - terminal_growth)
    discounted_terminal = terminal_value / ((1 + assumptions["wacc"]) ** 10)
    _require_finite("Terminal value", terminal_value)
    _require_finite("Discounted terminal value", discounted_terminal)
    return terminal_value, discounted_terminal


def compute_valuation(context: dict[str, Any], pv_fcff_sum: float, terminal_value: float, discounted_terminal: float) -> dict[str, float]:
    enterprise_value = pv_fcff_sum + discounted_terminal
    equity_value = enterprise_value + context["cash"] - context["debt"]
    shares = context["shares"]
    if shares <= 0:
        raise ValueError("Shares outstanding must be greater than zero.")
    price_per_share = equity_value / shares
    _require_finite("Enterprise value", enterprise_value)
    _require_finite("Equity value", equity_value)
    _require_finite("Price", price_per_share)
    return {
        "pv_fcff_sum": pv_fcff_sum,
        "terminal_value": terminal_value,
        "discounted_terminal_value": discounted_terminal,
        "enterprise_value": enterprise_value,
        "cash": context["cash"],
        "debt": context["debt"],
        "equity_value": equity_value,
        "shares_outstanding": shares,
        "intrinsic_price_per_share": price_per_share,
    }


def run_dcf_with_overrides(
    company_data: dict[str, Any], base_assumptions: dict[str, float], overrides: dict[str, float]
) -> dict[str, float] | None:
    assumptions = {**base_assumptions, **overrides}
    if assumptions["wacc"] <= assumptions["terminal_growth_rate"]:
        return None
    _, _, context = compute_assumptions(company_data, assumptions)
    forecast_rows, pv_fcff_sum, terminal_fcff, _ = project_cashflows(assumptions, context)
    terminal_value, discounted_terminal = compute_terminal_value(assumptions, terminal_fcff)
    valuation = compute_valuation(context, pv_fcff_sum, terminal_value, discounted_terminal)
    valuation["final_fcff"] = forecast_rows[-1]["fcff"]
    return valuation


def build_sensitivity(company_data: dict[str, Any], assumptions: dict[str, float]) -> dict[str, Any]:
    wacc_axis = [round(max(0.04, assumptions["wacc"] + step), 4) for step in [-0.01, -0.005, 0, 0.005, 0.01]]
    growth_axis = [round(max(0.0, min(0.045, assumptions["terminal_growth_rate"] + step)), 4) for step in [-0.01, -0.005, 0, 0.005, 0.01]]
    margin_axis = [round(max(0.01, min(0.60, assumptions["ebit_margin"] + step)), 4) for step in [-0.05, -0.025, 0, 0.025, 0.05]]
    high_growth_axis = [
        round(max(-0.2, min(0.30, assumptions["revenue_growth_rate"] + step)), 4) for step in [-0.03, -0.015, 0, 0.015, 0.03]
    ]

    def build_matrices(row_axis: list[float], col_axis: list[float], build_override) -> tuple[list[list[Any]], list[list[Any]], list[list[Any]]]:
        ev_matrix: list[list[Any]] = []
        eq_matrix: list[list[Any]] = []
        px_matrix: list[list[Any]] = []
        for row_value in row_axis:
            ev_row: list[Any] = []
            eq_row: list[Any] = []
            px_row: list[Any] = []
            for col_value in col_axis:
                result = run_dcf_with_overrides(company_data, assumptions, build_override(row_value, col_value))
                if result is None:
                    ev_row.append(None)
                    eq_row.append(None)
                    px_row.append(None)
                else:
                    ev_row.append(round(result["enterprise_value"], 2))
                    eq_row.append(round(result["equity_value"], 2))
                    px_row.append(round(result["intrinsic_price_per_share"], 2))
            ev_matrix.append(ev_row)
            eq_matrix.append(eq_row)
            px_matrix.append(px_row)
        return ev_matrix, eq_matrix, px_matrix

    wg_ev, wg_eq, wg_px = build_matrices(
        growth_axis,
        wacc_axis,
        lambda growth, wacc: {"terminal_growth_rate": growth, "wacc": wacc},
    )
    gm_ev, gm_eq, gm_px = build_matrices(
        high_growth_axis,
        margin_axis,
        lambda growth, margin: {"revenue_growth_rate": growth, "ebit_margin": margin},
    )

    return {
        "wacc_growth": {
            "wacc_axis": wacc_axis,
            "growth_axis": growth_axis,
            "enterprise_value": wg_ev,
            "equity_value": wg_eq,
            "price": wg_px,
        },
        "growth_margin": {
            "growth_axis": high_growth_axis,
            "margin_axis": margin_axis,
            "enterprise_value": gm_ev,
            "equity_value": gm_eq,
            "price": gm_px,
        },
        # Legacy shape for backward compatibility
        "wacc_axis": wacc_axis,
        "growth_axis": growth_axis,
        "enterprise_value_matrix": wg_ev,
    }


def _compute_dcf(company_data: dict[str, Any], assumption_inputs: dict[str, Any]) -> dict[str, Any]:
    ticker_symbol = company_data["ticker"]
    balance_sheet = company_data["balance_sheet"]
    income_statement = company_data["income_statement"]
    cashflow_statement = company_data["cashflow_statement"]

    assumptions, defaulted_fields, context = compute_assumptions(company_data, assumption_inputs)
    forecast_rows, pv_fcff_sum, terminal_fcff, terminal_reinvestment_rate = project_cashflows(assumptions, context)
    terminal_value, discounted_terminal = compute_terminal_value(assumptions, terminal_fcff)
    valuation = compute_valuation(context, pv_fcff_sum, terminal_value, discounted_terminal)

    sanity = {
        "ev_to_ebit": valuation["enterprise_value"] / max(abs(context["ebit_last"]), 1e-9),
        "terminal_value_percent_of_ev": (valuation["discounted_terminal_value"] / valuation["enterprise_value"])
        if valuation["enterprise_value"] != 0
        else None,
        "implied_growth": assumptions["terminal_growth_rate"],
    }

    sensitivity = build_sensitivity(company_data, assumptions)

    return {
        "query": ticker_symbol,
        "assumptions": assumptions,
        "defaulted_fields": defaulted_fields,
        "forecast": _sanitize_json_value(forecast_rows),
        "valuation": valuation,
        "sanity_checks": _sanitize_json_value(sanity),
        "terminal": {
            "fcff_terminal": terminal_fcff,
            "terminal_reinvestment_rate": terminal_reinvestment_rate,
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
