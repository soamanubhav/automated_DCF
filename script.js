const btn = document.getElementById("fetch-btn");
const input = document.getElementById("ticker");
const output = document.getElementById("output");
const tabs = document.getElementById("tabs");
const queryChip = document.getElementById("query-chip");

const SECTIONS = [
  ["balance_sheet", "Balance Sheet"],
  ["income_statement", "Income Statement"],
  ["cash_flow_statement", "Cash Flow"],
];

const ROW_ORDER = {
  balance_sheet: [
    "Total Assets",
    "Current Assets",
    "Cash And Cash Equivalents",
    "Cash Cash Equivalents And Short Term Investments",
    "Other Short Term Investments",
    "Net Receivables",
    "Inventory",
    "Other Current Assets",
    "Total Non Current Assets",
    "Property Plant Equipment",
    "Gross PPE",
    "Accumulated Depreciation",
    "Goodwill",
    "Intangible Assets",
    "Investments And Advances",
    "Other Non Current Assets",
    "Total Liabilities Net Minority Interest",
    "Current Liabilities",
    "Payables",
    "Current Debt",
    "Current Deferred Liabilities",
    "Other Current Liabilities",
    "Total Non Current Liabilities Net Minority Interest",
    "Long Term Debt",
    "Long Term Debt And Capital Lease Obligation",
    "Non Current Deferred Liabilities",
    "Other Non Current Liabilities",
    "Stockholders Equity",
    "Total Equity Gross Minority Interest",
    "Common Stock Equity",
    "Retained Earnings",
    "Gains Losses Not Affecting Retained Earnings",
    "Other Equity Adjustments",
    "Total Capitalization",
    "Working Capital",
    "Net Tangible Assets",
    "Invested Capital",
    "Tangible Book Value",
  ],
  income_statement: [
    "Total Revenue",
    "Operating Revenue",
    "Cost Of Revenue",
    "Gross Profit",
    "Operating Expense",
    "Research And Development",
    "Selling General And Administration",
    "General And Administrative Expense",
    "Selling And Marketing Expense",
    "Operating Income",
    "Operating Margin",
    "EBIT",
    "EBITDA",
    "Interest Income",
    "Interest Expense",
    "Pretax Income",
    "Tax Provision",
    "Net Income",
    "Net Income Common Stockholders",
    "Diluted NI Availto Com Stockholders",
    "Basic EPS",
    "Diluted EPS",
    "Basic Average Shares",
    "Diluted Average Shares",
    "Normalized Income",
  ],
  cash_flow_statement: [
    "Operating Cash Flow",
    "Cash Flow From Continuing Operating Activities",
    "Net Income From Continuing Operations",
    "Depreciation And Amortization",
    "Deferred Tax",
    "Stock Based Compensation",
    "Change In Working Capital",
    "Changes In Receivables",
    "Changes In Inventory",
    "Changes In Payables And Accrued Expense",
    "Other Non Cash Items",
    "Investing Cash Flow",
    "Cash Flow From Continuing Investing Activities",
    "Capital Expenditure",
    "Purchase Of PPE",
    "Sale Of PPE",
    "Net Business Purchase And Sale",
    "Purchase Of Investment",
    "Sale Of Investment",
    "Financing Cash Flow",
    "Cash Flow From Continuing Financing Activities",
    "Net Long Term Debt Issuance",
    "Long Term Debt Issuance",
    "Long Term Debt Payments",
    "Cash Dividends Paid",
    "Common Stock Issuance",
    "Common Stock Payments",
    "Repurchase Of Capital Stock",
    "Net Other Financing Charges",
    "End Cash Position",
    "Beginning Cash Position",
    "Changes In Cash",
    "Effect Of Exchange Rate Changes",
    "Free Cash Flow",
  ],
};

function formatValue(value) {
  if (value === null || value === undefined) return "-";
  if (typeof value === "number") return value.toLocaleString();
  return String(value);
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

function sortColumns(columns) {
  return columns.sort((left, right) => {
    const leftDate = Date.parse(left);
    const rightDate = Date.parse(right);
    const leftIsDate = !Number.isNaN(leftDate);
    const rightIsDate = !Number.isNaN(rightDate);

    if (leftIsDate && rightIsDate) return rightDate - leftDate;
    if (left === "TTM") return -1;
    if (right === "TTM") return 1;
    return left.localeCompare(right);
  });
}

function buildTable(statementData, sectionKey) {
  const title = SECTIONS.find(([key]) => key === sectionKey)?.[1] || sectionKey;
  const rows = orderRows(Object.keys(statementData || {}), sectionKey);

  if (!rows.length) {
    return `
      <div class="statement-group">
        <h4 class="statement-head">${escapeHtml(title)}</h4>
        <div class="empty-state">No data found for this statement.</div>
      </div>
    `;
  }

  const columnSet = new Set();
  for (const rowName of rows) {
    const row = statementData[rowName] || {};
    Object.keys(row).forEach((col) => columnSet.add(col));
  }

  const columns = sortColumns(Array.from(columnSet));

  const headerCells = [`<th>Breakdown</th>`]
    .concat(columns.map((col) => `<th>${escapeHtml(col)}</th>`))
    .join("");

  const bodyRows = rows
    .map((rowName) => {
      const row = statementData[rowName] || {};
      const dataCells = columns
        .map((col) => `<td>${escapeHtml(formatValue(row[col]))}</td>`)
        .join("");
      return `<tr><td>${escapeHtml(rowName)}</td>${dataCells}</tr>`;
    })
    .join("");

  return `
    <div class="statement-group">
      <h4 class="statement-head">${escapeHtml(title)}</h4>
      <table>
        <thead><tr>${headerCells}</tr></thead>
        <tbody>${bodyRows}</tbody>
      </table>
    </div>
  `;
}

function normalizeKey(value) {
  return String(value || "")
    .toLowerCase()
    .replaceAll(/[^a-z0-9]/g, "");
}

function orderRows(rows, sectionKey) {
  const preferredOrder = ROW_ORDER[sectionKey] || [];

  if (!preferredOrder.length) return rows;

  const preferredMap = new Map(
    preferredOrder.map((label, index) => [normalizeKey(label), index])
  );

  return [...rows].sort((left, right) => {
    const leftRank = preferredMap.get(normalizeKey(left));
    const rightRank = preferredMap.get(normalizeKey(right));

    const leftMatched = leftRank !== undefined;
    const rightMatched = rightRank !== undefined;

    if (leftMatched && rightMatched) return leftRank - rightRank;
    if (leftMatched) return -1;
    if (rightMatched) return 1;
    return left.localeCompare(right);
  });
}

function activateTab(tabName) {
  document.querySelectorAll(".tab-btn").forEach((tabButton) => {
    tabButton.classList.toggle("active", tabButton.dataset.tab === tabName);
  });

  document.querySelectorAll(".statement").forEach((panel) => {
    panel.classList.toggle("active", panel.dataset.tab === tabName);
  });
}

function renderTabs() {
  const tabDefinitions = [["all", "All Statements"], ...SECTIONS];

  tabs.innerHTML = tabDefinitions
    .map(([key, label]) => `<button class="tab-btn" data-tab="${escapeHtml(key)}">${escapeHtml(label)}</button>`)
    .join("");

  tabs.style.display = "flex";

  tabs.querySelectorAll(".tab-btn").forEach((tabButton) => {
    tabButton.addEventListener("click", () => activateTab(tabButton.dataset.tab));
  });
}

function renderFinancialTables(data) {
  const allEmpty = SECTIONS.every(([key]) => !Object.keys(data[key] || {}).length);

  if (allEmpty) {
    tabs.style.display = "none";
    output.innerHTML = `<div class="error">No tabular financial data returned.</div>`;
    return;
  }

  const fullViewHtml = SECTIONS
    .map(([key, title]) => buildTable(data[key], key))
    .join("");

  const singleViews = SECTIONS
    .map(([key, title]) => {
      const body = buildTable(data[key], key);
      return `<section class="statement" data-tab="${escapeHtml(key)}">${body}</section>`;
    })
    .join("");

  output.innerHTML = `
    <section class="statement" data-tab="all">${fullViewHtml}</section>
    ${singleViews}
  `;

  renderTabs();
  activateTab("all");
}

function resetResults() {
  tabs.style.display = "none";
  tabs.innerHTML = "";
  output.innerHTML = `<div class="empty-state">Loading...</div>`;
}

btn.addEventListener("click", async () => {
  const query = input.value.trim();

  if (!query) {
    alert("Enter ticker");
    return;
  }

  resetResults();
  queryChip.style.display = "none";

  try {
    const res = await fetch(
      `https://automated-dcf.onrender.com/fetch-data?query=${encodeURIComponent(query)}`
    );

    const data = await res.json();

    if (data.error) {
      output.innerHTML = `<div class="error">❌ ${escapeHtml(data.error)}</div>`;
      tabs.style.display = "none";
    } else {
      queryChip.textContent = `Showing data for: ${query}`;
      queryChip.style.display = "inline-flex";
      renderFinancialTables(data);
    }
  } catch (err) {
    output.innerHTML = `<div class="error">❌ Cannot reach backend</div>`;
    tabs.style.display = "none";
    console.error(err);
  }
});
