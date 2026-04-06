const btn = document.getElementById("fetch-btn");
const input = document.getElementById("ticker");
const tabs = document.getElementById("tabs");
const queryChip = document.getElementById("query-chip");
const statementArea = document.getElementById("statement-area");
const valuationCards = document.getElementById("valuation-cards");
const revenueChart = document.getElementById("revenue-chart");
const fcffChart = document.getElementById("fcff-chart");
const sensitivityTable = document.getElementById("sensitivity-table");
const controlPanel = document.getElementById("control-panel");

const SECTIONS = [
  ["income_statement", "Income Statement"],
  ["balance_sheet", "Balance Sheet"],
  ["cash_flow_statement", "Cash Flow Statement"],
];

const ASSUMPTIONS = [
  ["revenueGrowth", "Revenue Growth (%)", 8, 0, 30, 0.5],
  ["ebitMargin", "EBIT Margin (%)", 15, 0, 60, 0.5],
  ["depreciationPct", "Depreciation/Rev (%)", 5, 0, 20, 0.25],
  ["nwcPct", "NWC/Rev (%)", 3, -10, 20, 0.25],
  ["debtPct", "Debt/Rev (%)", 20, 0, 200, 1],
  ["capexPct", "Capex/Rev (%)", 8, 0, 40, 0.5],
  ["wacc", "WACC (%)", 10, 5, 25, 0.25],
  ["terminalGrowth", "Terminal Growth (%)", 3, 0, 8, 0.1],
  ["taxRate", "Tax Rate (%)", 25, 0, 45, 0.5],
];

let latestData = null;

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function parseNum(value) {
  if (value === null || value === undefined || value === "") return null;
  if (typeof value === "number") return Number.isFinite(value) ? value : null;
  const cleaned = String(value).replaceAll(/[$₹,]/g, "").trim();
  const num = Number(cleaned);
  return Number.isFinite(num) ? num : null;
}

function formatMoney(value) {
  if (!Number.isFinite(value)) return "-";
  const abs = Math.abs(value);
  if (abs >= 1e12) return `₹ ${(value / 1e12).toFixed(2)} T`;
  if (abs >= 1e9) return `₹ ${(value / 1e9).toFixed(2)} B`;
  if (abs >= 1e6) return `₹ ${(value / 1e6).toFixed(2)} M`;
  return `₹ ${value.toFixed(2)}`;
}

function sortColumns(columns) {
  return [...columns].sort((a, b) => {
    const ad = Date.parse(a);
    const bd = Date.parse(b);
    if (!Number.isNaN(ad) && !Number.isNaN(bd)) return ad - bd;
    return a.localeCompare(b);
  });
}

function buildControls() {
  controlPanel.innerHTML = ASSUMPTIONS.map(
    ([key, label, value, min, max, step]) => `
      <label class="control">
        <div class="control-head">
          <span>${escapeHtml(label)}</span>
          <strong id="${escapeHtml(key)}-value">${value.toFixed(1)}</strong>
        </div>
        <input id="${escapeHtml(key)}" type="range" min="${min}" max="${max}" step="${step}" value="${value}" />
      </label>
    `
  ).join("");

  ASSUMPTIONS.forEach(([key]) => {
    const slider = document.getElementById(key);
    const out = document.getElementById(`${key}-value`);
    slider.addEventListener("input", () => {
      out.textContent = Number(slider.value).toFixed(1);
      if (latestData) renderDCF(latestData);
    });
  });
}

function getAssumptions() {
  return Object.fromEntries(
    ASSUMPTIONS.map(([key]) => [key, Number(document.getElementById(key).value) / 100])
  );
}

function pickLatestSeriesValue(statement, rowName, fallback = 0) {
  const row = statement?.[rowName];
  if (!row) return fallback;
  const cols = sortColumns(Object.keys(row));
  if (!cols.length) return fallback;
  const val = parseNum(row[cols[cols.length - 1]]);
  return val ?? fallback;
}

function pickHistoricalRevenue(statement) {
  const row = statement?.["Total Revenue"] || statement?.["Operating Revenue"] || {};
  const cols = sortColumns(Object.keys(row));
  const values = cols.map((col) => parseNum(row[col])).filter((n) => n !== null);
  return values;
}

function historicalAverageGrowth(revenues) {
  if (revenues.length < 2) return null;
  const growths = [];
  for (let i = 1; i < revenues.length; i += 1) {
    if (revenues[i - 1] > 0) growths.push((revenues[i] - revenues[i - 1]) / revenues[i - 1]);
  }
  if (!growths.length) return null;
  const tail = growths.slice(-3);
  return tail.reduce((a, b) => a + b, 0) / tail.length;
}

function renderStatementTable(statement, title, shortRows) {
  const rows = Object.keys(statement || {});
  if (!rows.length) {
    return `<div class="statement-card"><h4>${escapeHtml(title)}</h4><div class="error">No data.</div></div>`;
  }

  const columnSet = new Set();
  rows.forEach((rowName) => Object.keys(statement[rowName] || {}).forEach((c) => columnSet.add(c)));
  const columns = sortColumns([...columnSet]).slice(-2);

  const preferred = shortRows.filter((name) => rows.includes(name));
  const selectedRows = preferred.length ? preferred : rows.slice(0, 6);

  const header = ["<th>Metric</th>"]
    .concat(columns.map((c) => `<th>${escapeHtml(new Date(c).getFullYear() || c)}</th>`))
    .join("");

  const body = selectedRows
    .map((r) => {
      const vals = columns
        .map((c) => `<td>${escapeHtml(formatMoney(parseNum(statement[r]?.[c]) || 0))}</td>`)
        .join("");
      return `<tr><td>${escapeHtml(r)}</td>${vals}</tr>`;
    })
    .join("");

  return `
    <div class="statement-card">
      <h4>${escapeHtml(title)}</h4>
      <div class="statement-wrap">
        <table>
          <thead><tr>${header}</tr></thead>
          <tbody>${body}</tbody>
        </table>
      </div>
    </div>
  `;
}

function renderStatements(data) {
  const income = renderStatementTable(data.income_statement, "Income Statement", ["Total Revenue", "EBIT", "Net Income"]);
  const balance = renderStatementTable(data.balance_sheet, "Balance Sheet", ["Total Assets", "Total Liabilities Net Minority Interest", "Stockholders Equity"]);
  const cash = renderStatementTable(data.cash_flow_statement, "Cash Flow Statement", ["Operating Cash Flow", "Investing Cash Flow", "Financing Cash Flow"]);

  const sections = {
    income_statement: `<div class="statement-grid">${income}</div>`,
    balance_sheet: `<div class="statement-grid">${balance}</div>`,
    cash_flow_statement: `<div class="statement-grid">${cash}</div>`,
    all: `<div class="statement-grid">${income}${balance}${cash}</div>`,
  };

  statementArea.innerHTML = Object.entries(sections)
    .map(([key, html]) => `<div class="statement" data-tab="${escapeHtml(key)}">${html}</div>`)
    .join("");
}

function renderTabs() {
  const defs = [["all", "All"], ...SECTIONS];
  tabs.innerHTML = defs
    .map(([k, label]) => `<button class="tab-btn" data-tab="${escapeHtml(k)}">${escapeHtml(label)}</button>`)
    .join("");

  tabs.querySelectorAll(".tab-btn").forEach((tab) => {
    tab.addEventListener("click", () => activateTab(tab.dataset.tab));
  });
  activateTab("all");
}

function activateTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((btnNode) => {
    btnNode.classList.toggle("active", btnNode.dataset.tab === tabName);
  });
  document.querySelectorAll(".statement").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.tab === tabName);
  });
}

function projectDCF(data, assumptions) {
  const income = data.income_statement || {};
  const balance = data.balance_sheet || {};

  const historicalRevenue = pickHistoricalRevenue(income);
  const latestRevenue = historicalRevenue[historicalRevenue.length - 1] || 0;
  const averageGrowth = historicalAverageGrowth(historicalRevenue);
  const growth = assumptions.revenueGrowth || averageGrowth || 0.08;

  const baseEbitMargin = (pickLatestSeriesValue(income, "EBIT", 0) / (latestRevenue || 1)) || assumptions.ebitMargin;
  const ebitMargin = assumptions.ebitMargin || baseEbitMargin;

  const cash = pickLatestSeriesValue(balance, "Cash And Cash Equivalents", 0)
    || pickLatestSeriesValue(balance, "Cash Cash Equivalents And Short Term Investments", 0);
  const debt = pickLatestSeriesValue(balance, "Total Debt", latestRevenue * assumptions.debtPct);
  const shares = pickLatestSeriesValue(income, "Diluted Average Shares", 1);

  const years = [1, 2, 3, 4, 5];
  const forecast = [];
  let revenue = latestRevenue;

  years.forEach((year) => {
    revenue *= 1 + growth;
    const ebit = revenue * ebitMargin;
    const nopat = ebit * (1 - assumptions.taxRate);
    const depreciation = revenue * assumptions.depreciationPct;
    const capex = revenue * assumptions.capexPct;
    const deltaNwc = revenue * assumptions.nwcPct;
    const fcff = nopat + depreciation - capex - deltaNwc;
    const pv = fcff / ((1 + assumptions.wacc) ** year);

    forecast.push({ year, revenue, fcff, pv });
  });

  const lastFcff = forecast[forecast.length - 1]?.fcff || 0;
  const terminalValue = (lastFcff * (1 + assumptions.terminalGrowth))
    / Math.max(assumptions.wacc - assumptions.terminalGrowth, 0.0001);
  const pvTerminal = terminalValue / ((1 + assumptions.wacc) ** 5);
  const enterpriseValue = forecast.reduce((sum, row) => sum + row.pv, 0) + pvTerminal;
  const equityValue = enterpriseValue + cash - debt;
  const valuePerShare = equityValue / Math.max(shares, 1);

  return {
    forecast,
    enterpriseValue,
    equityValue,
    valuePerShare,
  };
}

function renderValuation(result) {
  valuationCards.innerHTML = [
    ["Present Value", formatMoney(result.enterpriseValue)],
    ["Equity Value", formatMoney(result.equityValue)],
    ["Value Per Share", formatMoney(result.valuePerShare)],
  ].map(([title, value]) => `
      <article class="metric-card">
        <p class="metric-title">${escapeHtml(title)}</p>
        <p class="metric-value">${escapeHtml(value)}</p>
      </article>
    `).join("");
}

function renderBarChart(values, container) {
  const max = Math.max(...values.map((v) => v.value), 1);
  container.innerHTML = values.map((item) => {
    const height = Math.max((item.value / max) * 150, 6);
    return `<div class="bar" style="height:${height}px"><span>${escapeHtml(item.label)}</span></div>`;
  }).join("");
}

function renderLineChart(values, container) {
  const w = 460;
  const h = 170;
  const max = Math.max(...values, 1);
  const min = Math.min(...values, 0);
  const range = Math.max(max - min, 1);

  const points = values.map((v, i) => {
    const x = (i / Math.max(values.length - 1, 1)) * (w - 40) + 20;
    const y = h - ((v - min) / range) * (h - 24) - 12;
    return `${x},${y}`;
  }).join(" ");

  container.innerHTML = `<svg viewBox="0 0 ${w} ${h}"><polyline fill="none" stroke="#d87834" stroke-width="3" points="${points}"/></svg>`;
}

function renderSensitivity(baseData, assumptions) {
  const waccSteps = [-0.02, -0.01, 0, 0.01, 0.02];
  const gSteps = [-0.01, -0.005, 0, 0.005, 0.01];

  const matrix = waccSteps.map((dw) => gSteps.map((dg) => {
    const sim = projectDCF(baseData, {
      ...assumptions,
      wacc: Math.max(assumptions.wacc + dw, 0.03),
      terminalGrowth: Math.max(Math.min(assumptions.terminalGrowth + dg, 0.08), 0),
    });
    return sim.valuePerShare;
  }));

  const flat = matrix.flat();
  const low = Math.min(...flat);
  const high = Math.max(...flat);

  const cellClass = (value) => {
    const pct = (value - low) / Math.max(high - low, 1);
    if (pct > 0.66) return "good";
    if (pct > 0.33) return "mid";
    return "bad";
  };

  const header = `<tr><th>g \\ WACC</th>${waccSteps
    .map((dw) => `<th>${((assumptions.wacc + dw) * 100).toFixed(1)}%</th>`)
    .join("")}</tr>`;

  const body = matrix
    .map((row, rIx) => `<tr><th>${((assumptions.terminalGrowth + gSteps[rIx]) * 100).toFixed(1)}%</th>${row
      .map((value) => `<td class="${cellClass(value)}">${escapeHtml(value.toFixed(0))}</td>`)
      .join("")}</tr>`)
    .join("");

  sensitivityTable.innerHTML = `<table><thead>${header}</thead><tbody>${body}</tbody></table>`;
}

function renderDCF(data) {
  const assumptions = getAssumptions();
  const result = projectDCF(data, assumptions);

  renderValuation(result);
  renderBarChart(
    result.forecast.map((f, index) => ({ label: `${new Date().getFullYear() + index + 1}`, value: f.revenue })),
    revenueChart
  );
  renderLineChart(result.forecast.map((f) => f.fcff), fcffChart);
  renderSensitivity(data, assumptions);
}

function renderError(message) {
  statementArea.innerHTML = `<div class="error">${escapeHtml(message)}</div>`;
  valuationCards.innerHTML = "";
  revenueChart.innerHTML = "";
  fcffChart.innerHTML = "";
  sensitivityTable.innerHTML = "";
}

btn.addEventListener("click", async () => {
  const query = input.value.trim();
  if (!query) {
    alert("Enter ticker");
    return;
  }

  try {
    const response = await fetch(`/fetch-data?query=${encodeURIComponent(query)}`);
    const data = await response.json();

    if (!response.ok || data.error) {
      throw new Error(data.error || `HTTP ${response.status}`);
    }

    latestData = data;
    queryChip.textContent = `Ticker: ${query.toUpperCase()}`;
    renderTabs();
    renderStatements(data);
    renderDCF(data);
  } catch (error) {
    renderError(error.message || "Unable to fetch data.");
  }
});

buildControls();
