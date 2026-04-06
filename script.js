const btn = document.getElementById("fetch-btn");
const input = document.getElementById("ticker");
const output = document.getElementById("output");
const tabs = document.getElementById("tabs");
const queryChip = document.getElementById("query-chip");

const SECTIONS = [
  ["income_statement", "Income Statement"],
  ["balance_sheet", "Balance Sheet"],
  ["cash_flow_statement", "Cash Flow"],
];

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

function buildTable(statementData, title) {
  const rows = Object.keys(statementData || {});

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
    .map(([key, title]) => buildTable(data[key], title))
    .join("");

  const singleViews = SECTIONS
    .map(([key, title]) => {
      const body = buildTable(data[key], title);
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
