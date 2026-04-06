const runBtn = document.getElementById("run-btn");
const tickerInput = document.getElementById("ticker");
const statusEl = document.getElementById("status");
const defaultsChip = document.getElementById("defaults-chip");

const summaryEl = document.getElementById("summary");
const chartsEl = document.getElementById("charts");
const forecastEl = document.getElementById("forecast");
const sensitivityEl = document.getElementById("sensitivity");
const statementsEl = document.getElementById("statements");
const API_BASE = window.location.hostname.includes("github.io")
  ? "https://automated-dcf.onrender.com"
  : "";

function apiUrl(path) {
  return `${API_BASE}${path}`;
}

const ASSUMPTION_FIELDS = [
  "revenue_growth_rate",
  "ebit_margin",
  "depreciation_rate",
  "capex_percent",
  "nwc_percent",
  "wacc",
  "terminal_growth_rate",
  "tax_rate",
];

const STATEMENT_TABS = [
  ["balance_sheet", "Balance Sheet"],
  ["income_statement", "Income Statement"],
  ["cash_flow_statement", "Cash Flow Statement"],
];

let forecastChart;

function formatNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return Number(value).toLocaleString(undefined, {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  });
}

function formatPercent(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(2)}%`;
}

function formatMoney(value) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return "-";
  return `$${formatNumber(value, 2)}`;
}

function collectAssumptions() {
  const assumptions = {};
  ASSUMPTION_FIELDS.forEach((field) => {
    const value = document.getElementById(field).value.trim();
    if (value !== "") assumptions[field] = Number(value);
  });
  return assumptions;
}

function showPanels() {
  [summaryEl, chartsEl, forecastEl, sensitivityEl, statementsEl].forEach((el) => el.classList.remove("hidden"));
}

function setStatus(message, isError = false) {
  statusEl.classList.toggle("error", isError);
  statusEl.textContent = message;
}

function resetPanels() {
  [summaryEl, forecastEl, sensitivityEl, statementsEl].forEach((el) => {
    el.classList.add("hidden");
    el.innerHTML = "";
  });
  chartsEl.classList.add("hidden");
  defaultsChip.classList.add("hidden");
  defaultsChip.textContent = "";
}

function renderDefaultsChip(defaultedFields, assumptions) {
  if (!defaultedFields?.length) {
    defaultsChip.classList.add("hidden");
    defaultsChip.textContent = "";
    return;
  }

  const items = defaultedFields
    .map((key) => `${key}: ${key.includes("rate") || key.includes("margin") || key.includes("percent") || key === "wacc" ? formatPercent(assumptions[key]) : formatNumber(assumptions[key])}`)
    .join(" | ");

  defaultsChip.textContent = `Default assumptions applied for blank fields: ${items}`;
  defaultsChip.classList.remove("hidden");
}

function buildSummary(query, assumptions, valuation) {
  summaryEl.innerHTML = `
    <h2>Valuation Summary – ${query}</h2>
    <div class="summary-grid">
      <div><strong>Present Value of FCFF</strong><span>${formatMoney(valuation.pv_fcff_sum)}</span></div>
      <div><strong>Terminal Value (PV)</strong><span>${formatMoney(valuation.discounted_terminal_value)}</span></div>
      <div><strong>Enterprise Value (EV)</strong><span>${formatMoney(valuation.enterprise_value)}</span></div>
      <div><strong>Less: Net Debt</strong><span>${formatMoney(valuation.debt - valuation.cash)}</span></div>
      <div><strong>Equity Value</strong><span>${formatMoney(valuation.equity_value)}</span></div>
      <div><strong>Fair Value per Share</strong><span>${formatMoney(valuation.intrinsic_price_per_share)}</span></div>
      <div><strong>WACC</strong><span>${formatPercent(assumptions.wacc)}</span></div>
      <div><strong>Terminal Growth</strong><span>${formatPercent(assumptions.terminal_growth_rate)}</span></div>
    </div>

    <div class="table-wrap mt12">
      <table>
        <thead>
          <tr><th>Metric</th><th>Value</th></tr>
        </thead>
        <tbody>
          <tr><td>PV of FCFF</td><td>${formatMoney(valuation.pv_fcff_sum)}</td></tr>
          <tr><td>Terminal Value</td><td>${formatMoney(valuation.terminal_value)}</td></tr>
          <tr><td>Discounted Terminal Value</td><td>${formatMoney(valuation.discounted_terminal_value)}</td></tr>
          <tr><td>Enterprise Value</td><td>${formatMoney(valuation.enterprise_value)}</td></tr>
          <tr><td>Cash</td><td>${formatMoney(valuation.cash)}</td></tr>
          <tr><td>Debt</td><td>${formatMoney(valuation.debt)}</td></tr>
          <tr><td>Equity Value</td><td>${formatMoney(valuation.equity_value)}</td></tr>
          <tr><td>Shares Outstanding</td><td>${formatNumber(valuation.shares_outstanding, 0)}</td></tr>
          <tr><td>Fair Value per Share</td><td>${formatMoney(valuation.intrinsic_price_per_share)}</td></tr>
        </tbody>
      </table>
    </div>
  `;
}

function buildForecastTable(forecastRows) {
  const body = forecastRows
    .map(
      (row) => `
      <tr>
        <td>${row.year}</td>
        <td>${formatMoney(row.revenue)}</td>
        <td>${formatMoney(row.ebit)}</td>
        <td>${formatMoney(row.nopat)}</td>
        <td>${formatMoney(row.depreciation)}</td>
        <td>${formatMoney(row.capex)}</td>
        <td>${formatMoney(row.delta_nwc)}</td>
        <td>${formatMoney(row.fcff)}</td>
        <td>${formatMoney(row.pv_fcff)}</td>
      </tr>
    `
    )
    .join("");

  forecastEl.innerHTML = `
    <h2>5-Year FCFF Forecast</h2>
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Year</th><th>Revenue</th><th>EBIT</th><th>NOPAT</th><th>Depreciation</th>
            <th>Capex</th><th>ΔNWC</th><th>FCFF</th><th>PV(FCFF)</th>
          </tr>
        </thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function renderForecastChart(forecastRows) {
  const labels = forecastRows.map((row) => `Year ${row.year}`);
  const revenue = forecastRows.map((row) => row.revenue);
  const ebit = forecastRows.map((row) => row.ebit);
  const fcff = forecastRows.map((row) => row.fcff);

  const ctx = document.getElementById("forecast-chart");
  if (forecastChart) forecastChart.destroy();

  forecastChart = new Chart(ctx, {
    data: {
      labels,
      datasets: [
        {
          type: "bar",
          label: "Revenue",
          data: revenue,
          backgroundColor: "rgba(94, 161, 255, 0.25)",
          borderColor: "#5ea1ff",
          borderWidth: 1,
          yAxisID: "y",
        },
        {
          type: "line",
          label: "EBIT",
          data: ebit,
          borderColor: "#27c8b8",
          backgroundColor: "rgba(39, 200, 184, 0.2)",
          tension: 0.3,
          yAxisID: "y",
        },
        {
          type: "line",
          label: "FCFF",
          data: fcff,
          borderColor: "#f0a93b",
          backgroundColor: "rgba(240, 169, 59, 0.2)",
          borderDash: [6, 4],
          tension: 0.3,
          yAxisID: "y",
        },
      ],
    },
    options: {
      responsive: true,
      plugins: {
        legend: {
          labels: { color: "#d7e6ff" },
        },
      },
      scales: {
        x: { ticks: { color: "#b8caee" }, grid: { color: "rgba(255,255,255,0.05)" } },
        y: {
          ticks: {
            color: "#b8caee",
            callback: (value) => `$${formatNumber(value, 0)}`,
          },
          grid: { color: "rgba(255,255,255,0.08)" },
        },
      },
    },
  });
}

function colorForCell(value, min, max) {
  if (value === null || value === undefined) return "background: #3a2130;";
  const normalized = max === min ? 0.5 : (value - min) / (max - min);
  const hue = Math.round(15 + normalized * 120);
  return `background: hsl(${hue}, 60%, 24%);`;
}

function buildSensitivityTable(title, waccAxis, growthAxis, matrix, valueFormatter = formatMoney) {
  const values = matrix.flat().filter((value) => value !== null);
  if (!values.length) {
    return `
      <h3>${title}</h3>
      <div class="empty">Sensitivity data unavailable for the current assumptions.</div>
    `;
  }
  const min = Math.min(...values);
  const max = Math.max(...values);

  const headerCells = ["<th>g \\ WACC</th>"]
    .concat(waccAxis.map((wacc) => `<th>${formatPercent(wacc)}</th>`))
    .join("");

  const rows = growthAxis
    .map((g, rowIndex) => {
      const cells = matrix[rowIndex]
        .map((value) => `<td style="${colorForCell(value, min, max)}">${value === null ? "-" : valueFormatter(value)}</td>`)
        .join("");
      return `<tr><td>${formatPercent(g)}</td>${cells}</tr>`;
    })
    .join("");

  return `
    <h3>${title}</h3>
    <div class="table-wrap">
      <table>
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function buildStatementTable(title, statementData) {
  const rows = Object.keys(statementData || {});
  if (!rows.length) return `<div class="empty">No ${title} data available.</div>`;

  const columnSet = new Set();
  rows.forEach((rowName) => Object.keys(statementData[rowName] || {}).forEach((c) => columnSet.add(c)));
  const columns = [...columnSet].sort((a, b) => (Date.parse(b) || 0) - (Date.parse(a) || 0));

  const header = ["<th>Breakdown</th>"].concat(columns.map((col) => `<th>${col}</th>`)).join("");
  const body = rows
    .map((rowName) => {
      const cells = columns.map((col) => `<td>${formatNumber(statementData[rowName][col], 0)}</td>`).join("");
      return `<tr><td>${rowName}</td>${cells}</tr>`;
    })
    .join("");

  return `
    <div class="table-wrap">
      <table>
        <thead><tr>${header}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function buildStatementTabs(sourceData) {
  const tabButtons = STATEMENT_TABS
    .map(([key, label], idx) => `<button class="tab-btn ${idx === 0 ? "active" : ""}" data-tab="${key}">${label}</button>`)
    .join("");

  const tabPanels = STATEMENT_TABS
    .map(([key, label], idx) => `
      <section class="statement-panel ${idx === 0 ? "active" : ""}" data-tab="${key}">
        <h3>${label}</h3>
        ${buildStatementTable(label, sourceData[key])}
      </section>
    `)
    .join("");

  statementsEl.innerHTML = `
    <h2>Financial Statements</h2>
    <div class="tabs">${tabButtons}</div>
    ${tabPanels}
  `;

  statementsEl.querySelectorAll(".tab-btn").forEach((btn) => {
    btn.addEventListener("click", () => {
      const tab = btn.dataset.tab;
      statementsEl.querySelectorAll(".tab-btn").forEach((item) => item.classList.toggle("active", item.dataset.tab === tab));
      statementsEl.querySelectorAll(".statement-panel").forEach((panel) => panel.classList.toggle("active", panel.dataset.tab === tab));
    });
  });
}

runBtn.addEventListener("click", async () => {
  const query = tickerInput.value.trim().toUpperCase();
  if (!query) {
    setStatus("Please enter a ticker before running the model.", true);
    return;
  }

  setStatus("Running DCF model...");
  resetPanels();

  try {
    const res = await fetch(apiUrl("/dcf"), {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query, assumptions: collectAssumptions() }),
    });

    const data = await res.json();
    if (!res.ok) {
      setStatus(`Unable to run DCF: ${data.error || `HTTP ${res.status}`}`, true);
      return;
    }

    showPanels();
    renderDefaultsChip(data.defaulted_fields, data.assumptions);
    buildSummary(data.query, data.assumptions, data.valuation);
    renderForecastChart(data.forecast || []);
    buildForecastTable(data.forecast || []);
    sensitivityEl.innerHTML = `
      <h2>Sensitivity Analysis</h2>
      ${buildSensitivityTable(
        "Enterprise Value",
        data.sensitivity.wacc_axis,
        data.sensitivity.growth_axis,
        data.sensitivity.enterprise_value_matrix,
        formatMoney
      )}
      ${buildSensitivityTable(
        "Fair Value per Share",
        data.sensitivity.wacc_axis,
        data.sensitivity.growth_axis,
        data.sensitivity.share_price_matrix,
        formatMoney
      )}
    `;
    buildStatementTabs(data.source_data || {});

    const cached = data.from_cache ? "(loaded from local cache)" : "(freshly fetched)";
    setStatus(`Model complete for ${data.query} ${cached}. Last data refresh: ${new Date(data.last_updated).toLocaleString()}`);
  } catch (error) {
    setStatus("Failed to reach backend service. Please try again.", true);
    console.error(error);
  }
});
