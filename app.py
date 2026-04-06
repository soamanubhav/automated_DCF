import numpy as np
import pandas as pd
import seaborn as sns
import streamlit as st
import matplotlib.pyplot as plt
import yfinance as yf

st.set_page_config(page_title="Financial Analysis & DCF Valuation Tool", layout="wide")


@st.cache_data(ttl=3600, show_spinner=False)
def fetch_company_data(ticker: str):
    data = yf.Ticker(ticker)

    income = data.financials.transpose()
    balance = data.balance_sheet.transpose()
    cashflow = data.cash_flow.transpose()

    for df in (income, balance, cashflow):
        if not df.empty:
            df.index = pd.to_datetime(df.index, errors="coerce")
            df["Year"] = df.index.year

    return income, balance, cashflow


def get_latest_value(df: pd.DataFrame, column: str):
    if df.empty or column not in df.columns:
        return np.nan
    series = pd.to_numeric(df[column], errors="coerce").dropna()
    if series.empty:
        return np.nan
    return float(series.iloc[0])


def get_value_by_year(df: pd.DataFrame, year: int, column: str):
    if df.empty or "Year" not in df.columns or column not in df.columns:
        return np.nan
    subset = df.loc[df["Year"] == year, column]
    subset = pd.to_numeric(subset, errors="coerce").dropna()
    if subset.empty:
        return np.nan
    return float(subset.iloc[0])


def infer_base_years(income: pd.DataFrame, max_years: int = 3):
    if income.empty or "Year" not in income.columns:
        return []
    years = sorted(income["Year"].dropna().astype(int).unique().tolist())
    if not years:
        return []
    return years[-max_years:]


def avg_ratio(numerator: list[float], denominator: list[float], default: float = 0.0):
    ratios = []
    for n, d in zip(numerator, denominator):
        if pd.notna(n) and pd.notna(d) and d != 0:
            ratios.append(n / d)
    return float(np.mean(ratios)) if ratios else default


def compute_dcf(
    income: pd.DataFrame,
    balance: pd.DataFrame,
    assumptions: dict,
    projection_years: int = 5,
):
    base_years = infer_base_years(income)
    if len(base_years) < 2:
        raise ValueError("Not enough historical years available to run DCF.")

    revenue_hist = [get_value_by_year(income, y, "Total Revenue") for y in base_years]
    ebit_hist = [get_value_by_year(income, y, "EBIT") for y in base_years]
    dep_hist = [get_value_by_year(income, y, "Reconciled Depreciation") for y in base_years]
    net_ppe_hist = [get_value_by_year(balance, y, "Net PPE") for y in base_years]
    current_assets_hist = [get_value_by_year(balance, y, "Current Assets") for y in base_years]
    current_liabilities_hist = [get_value_by_year(balance, y, "Current Liabilities") for y in base_years]

    rev_growth_list = []
    for i in range(1, len(revenue_hist)):
        prev, curr = revenue_hist[i - 1], revenue_hist[i]
        if pd.notna(prev) and pd.notna(curr) and prev != 0:
            rev_growth_list.append(curr / prev - 1)

    auto_revenue_growth = float(np.mean(rev_growth_list)) if rev_growth_list else 0.0
    revenue_growth = assumptions["revenue_growth"] if assumptions["revenue_growth"] != 0 else auto_revenue_growth

    auto_ebit_margin = avg_ratio(ebit_hist, revenue_hist, default=0.12)
    ebit_margin = assumptions["ebit_margin"] if assumptions["ebit_margin"] != 0 else auto_ebit_margin

    auto_netppe_rev = avg_ratio(net_ppe_hist, revenue_hist, default=0.30)

    auto_dep_rate = avg_ratio(dep_hist, net_ppe_hist, default=0.08)
    dep_rate = assumptions["depreciation_rate"] if assumptions["depreciation_rate"] != 0 else auto_dep_rate

    auto_curr_assets_rev = avg_ratio(current_assets_hist, revenue_hist, default=0.20)
    auto_curr_liab_rev = avg_ratio(current_liabilities_hist, revenue_hist, default=0.15)
    nwc_rev = assumptions["nwc_rate"] if assumptions["nwc_rate"] != 0 else (auto_curr_assets_rev - auto_curr_liab_rev)

    tax_rate = assumptions["tax_rate"] if assumptions["tax_rate"] != 0 else 0.18
    capex_rate = assumptions["capex_rate"]

    start_year = base_years[-1]
    years = list(range(start_year, start_year + projection_years + 1))

    revenue = {start_year: revenue_hist[-1]}
    ebit = {start_year: ebit_hist[-1] if pd.notna(ebit_hist[-1]) else revenue[start_year] * ebit_margin}

    for y in years[1:]:
        revenue[y] = revenue[y - 1] * (1 + revenue_growth)
        ebit[y] = revenue[y] * ebit_margin

    nopat = {y: ebit[y] * (1 - tax_rate) for y in years}

    net_ppe = {start_year: net_ppe_hist[-1] if pd.notna(net_ppe_hist[-1]) else revenue[start_year] * auto_netppe_rev}
    for y in years[1:]:
        net_ppe[y] = revenue[y] * auto_netppe_rev

    depreciation = {y: net_ppe[y] * dep_rate for y in years}

    if capex_rate != 0:
        delta_capex = {y: revenue[y] * capex_rate for y in years[1:]}
    else:
        delta_capex = {y: net_ppe[y] - net_ppe[y - 1] for y in years[1:]}

    working_capital = {y: revenue[y] * nwc_rev for y in years}
    delta_nwc = {y: working_capital[y] - working_capital[y - 1] for y in years[1:]}

    fcff = {
        y: nopat[y] + depreciation[y] - delta_capex[y] - delta_nwc[y]
        for y in years[1:]
    }

    wacc = assumptions["wacc"] if assumptions["wacc"] != 0 else 0.35
    terminal_growth = assumptions["terminal_growth"] if assumptions["terminal_growth"] != 0 else 0.03

    if wacc <= terminal_growth:
        raise ValueError("WACC must be greater than Terminal Growth for terminal value calculation.")

    pv_fcff = {}
    for i, y in enumerate(years[1:], start=1):
        pv_fcff[y] = fcff[y] / ((1 + wacc) ** i)

    last_year = years[-1]
    terminal_value = (fcff[last_year] * (1 + terminal_growth)) / (wacc - terminal_growth)
    pv_terminal = terminal_value / ((1 + wacc) ** projection_years)

    enterprise_value = sum(pv_fcff.values()) + pv_terminal

    cash = get_latest_value(balance, "Cash Cash Equivalents And Short Term Investments")
    if pd.isna(cash):
        cash = get_latest_value(balance, "Cash And Cash Equivalents")

    debt = get_latest_value(balance, "Total Debt")
    shares = get_latest_value(balance, "Share Issued")

    cash = 0.0 if pd.isna(cash) else cash
    debt = 0.0 if pd.isna(debt) else debt

    equity_value = enterprise_value + cash - debt
    value_per_share = (equity_value / shares) if pd.notna(shares) and shares != 0 else np.nan

    return {
        "base_years": base_years,
        "projection_years": years,
        "revenue": revenue,
        "fcff": fcff,
        "pv_fcff": pv_fcff,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "value_per_share": value_per_share,
        "cash": cash,
        "debt": debt,
        "shares": shares,
        "wacc": wacc,
        "terminal_growth": terminal_growth,
        "last_fcff": fcff[last_year],
        "projection_horizon": projection_years,
    }


def build_sensitivity(result: dict):
    wacc = result["wacc"]
    terminal_growth = result["terminal_growth"]
    last_fcff = result["last_fcff"]
    projection_horizon = result["projection_horizon"]
    pv_sum = sum(result["pv_fcff"].values())

    wacc_range = np.round(np.arange(wacc - 0.05, wacc + 0.051, 0.01), 4)
    tg_range = np.round(np.arange(terminal_growth - 0.02, terminal_growth + 0.021, 0.005), 4)

    table = pd.DataFrame(
        index=[f"{tg * 100:.2f}%" for tg in tg_range],
        columns=[f"{w * 100:.2f}%" for w in wacc_range],
        dtype=float,
    )

    for i, tg in enumerate(tg_range):
        for j, w in enumerate(wacc_range):
            if w <= tg:
                table.iloc[i, j] = np.nan
                continue
            pv_terminal = ((last_fcff * (1 + tg)) / (w - tg)) / ((1 + w) ** projection_horizon)
            ev = pv_sum + pv_terminal
            eq = ev + result["cash"] - result["debt"]
            vps = eq / result["shares"] if pd.notna(result["shares"]) and result["shares"] != 0 else np.nan
            table.iloc[i, j] = vps

    return table


st.title("Financial Analysis & DCF Valuation Tool")

st.sidebar.header("Inputs")
ticker = st.sidebar.text_input("Company Ticker", value="RELIANCE.NS")

st.sidebar.subheader("Assumptions (%)")
revenue_growth = st.sidebar.slider("Revenue Growth", -50.0, 100.0, 0.0, 0.5)
ebit_margin = st.sidebar.slider("EBIT Margin", -50.0, 80.0, 0.0, 0.5)
dep_rate = st.sidebar.slider("Depreciation / Net PPE", 0.0, 30.0, 0.0, 0.1)
nwc_rate = st.sidebar.slider("NWC / Revenue", -20.0, 40.0, 0.0, 0.1)
capex_rate = st.sidebar.slider("Capex / Revenue", 0.0, 50.0, 0.0, 0.1)
wacc = st.sidebar.slider("WACC", 1.0, 50.0, 12.0, 0.1)
terminal_growth = st.sidebar.slider("Terminal Growth", 0.0, 10.0, 3.0, 0.1)
tax_rate = st.sidebar.slider("Tax Rate", 0.0, 50.0, 18.0, 0.1)

run_btn = st.sidebar.button("Get Data", type="primary")

if run_btn:
    with st.spinner(f"Fetching and calculating for {ticker}..."):
        try:
            income_statement, balance_sheet, cash_flow = fetch_company_data(ticker)

            if income_statement.empty and balance_sheet.empty and cash_flow.empty:
                st.error("No financial data found for this ticker.")
                st.stop()

            assumptions = {
                "revenue_growth": revenue_growth / 100,
                "ebit_margin": ebit_margin / 100,
                "depreciation_rate": dep_rate / 100,
                "nwc_rate": nwc_rate / 100,
                "capex_rate": capex_rate / 100,
                "wacc": wacc / 100,
                "terminal_growth": terminal_growth / 100,
                "tax_rate": tax_rate / 100,
            }

            dcf_result = compute_dcf(income_statement, balance_sheet, assumptions)
            sensitivity = build_sensitivity(dcf_result)

        except Exception as exc:
            st.error(f"Error: {exc}")
            st.stop()

    st.header("1) Financial Statements")
    tab1, tab2, tab3 = st.tabs(["Income Statement", "Balance Sheet", "Cash Flow"])

    with tab1:
        st.dataframe(income_statement, use_container_width=True)
    with tab2:
        st.dataframe(balance_sheet, use_container_width=True)
    with tab3:
        st.dataframe(cash_flow, use_container_width=True)

    st.header("2) DCF Output")
    c1, c2, c3 = st.columns(3)
    c1.metric("Present Value (Enterprise Value)", f"{dcf_result['enterprise_value']:,.2f}")
    c2.metric("Equity Value", f"{dcf_result['equity_value']:,.2f}")
    vps = dcf_result["value_per_share"]
    c3.metric("Value Per Share", "N/A" if pd.isna(vps) else f"{vps:,.2f}")

    st.header("3) Charts")
    chart_col1, chart_col2 = st.columns(2)

    with chart_col1:
        rev_df = pd.DataFrame(
            {
                "Year": list(dcf_result["revenue"].keys()),
                "Revenue": list(dcf_result["revenue"].values()),
            }
        )
        fig1, ax1 = plt.subplots(figsize=(8, 4))
        ax1.bar(rev_df["Year"].astype(str), rev_df["Revenue"], color="#1f77b4")
        ax1.set_title("Revenue Projection")
        ax1.set_xlabel("Year")
        ax1.set_ylabel("Revenue")
        st.pyplot(fig1)

    with chart_col2:
        fcff_df = pd.DataFrame(
            {
                "Year": list(dcf_result["fcff"].keys()),
                "FCFF": list(dcf_result["fcff"].values()),
            }
        )
        fig2, ax2 = plt.subplots(figsize=(8, 4))
        ax2.plot(fcff_df["Year"].astype(str), fcff_df["FCFF"], marker="o", color="#ff7f0e")
        ax2.set_title("FCFF Projection")
        ax2.set_xlabel("Year")
        ax2.set_ylabel("FCFF")
        st.pyplot(fig2)

    st.header("4) Sensitivity Heatmap")
    fig3, ax3 = plt.subplots(figsize=(10, 5))
    sns.heatmap(sensitivity, annot=True, fmt=".2f", cmap="RdYlGn", ax=ax3, cbar_kws={"label": "Value/Share"})
    ax3.set_title("WACC vs Terminal Growth")
    st.pyplot(fig3)
else:
    st.info("Set assumptions in the sidebar and click **Get Data**.")
