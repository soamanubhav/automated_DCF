const runBtn = document.getElementById("run-btn");
const tickerInput = document.getElementById("ticker");
const statusEl = document.getElementById("status");
const summaryEl = document.getElementById("summary");
const forecastEl = document.getElementById("forecast");
const sensitivityEl = document.getElementById("sensitivity");

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
  [summaryEl, forecastEl, sensitivityEl].forEach((el) => el.classList.remove("hidden"));
}

function buildSummary(query, assumptions, valuation) {
  summaryEl.innerHTML = `
    <h2>Valuation Summary – ${query}</h2>
    <div class="summary-grid">
      <div><strong>Enterprise Value</strong><span>${formatMoney(valuation.enterprise_value)}</span></div>
      <div><strong>Equity Value</strong><span>${formatMoney(valuation.equity_value)}</span></div>
      <div><strong>Intrinsic Price / Share</strong><span>${formatMoney(valuation.intrinsic_price_per_share)}</span></div>
      <div><strong>Discounted Terminal Value</strong><span>${formatMoney(valuation.discounted_terminal_value)}</span></div>
      <div><strong>Cash</strong><span>${formatMoney(valuation.cash)}</span></div>
      <div><strong>Debt</strong><span>${formatMoney(valuation.debt)}</span></div>
      <div><strong>WACC</strong><span>${formatPercent(assumptions.wacc)}</span></div>
      <div><strong>Terminal Growth</strong><span>${formatPercent(assumptions.terminal_growth_rate)}</span></div>
    </div>
  `;
}

function buildForecast(forecastRows) {
  const header = `
    <tr>
      <th>Year</th>
      <th>Revenue</th>
      <th>EBIT</th>
      <th>NOPAT</th>
      <th>Depreciation</th>
      <th>Capex</th>
      <th>ΔNWC</th>
      <th>FCFF</th>
      <th>PV(FCFF)</th>
    </tr>
  `;

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
        <thead>${header}</thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function colorForCell(value, min, max) {
  if (value === null || value === undefined) return "background: #3a2130;";
  const normalized = max === min ? 0.5 : (value - min) / (max - min);
  const hue = Math.round(15 + normalized * 120);
  return `background: hsl(${hue}, 60%, 24%);`;
}

function buildSensitivity(sensitivity) {
  const { wacc_axis: waccAxis, growth_axis: growthAxis, enterprise_value_matrix: matrix } = sensitivity;
  const values = matrix.flat().filter((value) => value !== null);
  const min = Math.min(...values);
  const max = Math.max(...values);

  const headerCells = ["<th>g \\ WACC</th>"]
    .concat(waccAxis.map((wacc) => `<th>${formatPercent(wacc)}</th>`))
    .join("");

  const rows = growthAxis
    .map((g, rowIndex) => {
      const cells = matrix[rowIndex]
        .map((value) => `<td style="${colorForCell(value, min, max)}">${value === null ? "-" : formatMoney(value)}</td>`)
        .join("");
      return `<tr><td>${formatPercent(g)}</td>${cells}</tr>`;
    })
    .join("");

  sensitivityEl.innerHTML = `
    <h2>Sensitivity Analysis (Enterprise Value)</h2>
    <p class="muted">Matrix values reflect enterprise value under combinations of WACC and terminal growth rate.</p>
    <div class="table-wrap">
      <table>
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${rows}</tbody>
      </table>
    </div>
  `;
}

function setStatus(message, isError = false) {
  statusEl.classList.toggle("error", isError);
  statusEl.textContent = message;
}

runBtn.addEventListener("click", async () => {
  const query = tickerInput.value.trim().toUpperCase();
  if (!query) {
    setStatus("Please enter a ticker before running the model.", true);
    return;
  }

  setStatus("Running DCF model...");
  [summaryEl, forecastEl, sensitivityEl].forEach((el) => {
    el.classList.add("hidden");
    el.innerHTML = "";
  });

  try {
    const res = await fetch("/dcf", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query,
        assumptions: collectAssumptions(),
      }),
    });

    const data = await res.json();
    if (!res.ok) {
      setStatus(`Unable to run DCF: ${data.error || `HTTP ${res.status}`}`, true);
      return;
    }

    showPanels();
    buildSummary(data.query, data.assumptions, data.valuation);
    buildForecast(data.forecast || []);
    buildSensitivity(data.sensitivity);
    setStatus(`Model complete for ${data.query}. Default assumptions were applied for blank fields.`);
  } catch (error) {
    setStatus("Failed to reach backend service. Please try again.", true);
    console.error(error);
  }
});
