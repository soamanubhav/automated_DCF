const tickerInput = document.getElementById("tickerInput");
const fetchBtn = document.getElementById("fetchBtn");
const loading = document.getElementById("loading");
const message = document.getElementById("message");
const results = document.getElementById("results");

const incomeContainer = document.getElementById("incomeContainer");
const balanceContainer = document.getElementById("balanceContainer");
const cashflowContainer = document.getElementById("cashflowContainer");

function formatValue(value) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "number") {
    return new Intl.NumberFormat("en-US", {
      maximumFractionDigits: 0,
    }).format(value);
  }
  return String(value);
}

function createTable(statement) {
  if (!statement || !statement.rows || statement.rows.length === 0) {
    return `<div class="no-data">No data available.</div>`;
  }

  const columns = ["year", ...statement.columns];

  const thead = `
    <thead>
      <tr>${columns.map((column) => `<th>${column.replaceAll("_", " ")}</th>`).join("")}</tr>
    </thead>`;

  const tbody = `
    <tbody>
      ${statement.rows
        .map(
          (row) =>
            `<tr>${columns
              .map((column) => `<td>${formatValue(row[column])}</td>`)
              .join("")}</tr>`
        )
        .join("")}
    </tbody>`;

  return `<div class="table-wrapper"><table>${thead}${tbody}</table></div>`;
}

function setLoading(state) {
  fetchBtn.disabled = state;
  loading.classList.toggle("hidden", !state);
}

function setMessage(text = "", type = "") {
  message.textContent = text;
  message.className = `message ${type}`.trim();
}

async function fetchData() {
  const ticker = tickerInput.value.trim() || "RELIANCE.NS";
  setMessage();
  results.classList.add("hidden");
  setLoading(true);

  try {
    const response = await fetch("/fetch-data", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ ticker }),
    });

    const data = await response.json();

    if (!response.ok) {
      throw new Error(data.error || "Request failed.");
    }

    incomeContainer.innerHTML = createTable(data.income_statement);
    balanceContainer.innerHTML = createTable(data.balance_sheet);
    cashflowContainer.innerHTML = createTable(data.cash_flow);
    results.classList.remove("hidden");
    setMessage(`Showing data for ${data.ticker}`, "success");
  } catch (error) {
    setMessage(error.message || "Failed to fetch data.", "error");
  } finally {
    setLoading(false);
  }
}

fetchBtn.addEventListener("click", fetchData);

tickerInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter") {
    fetchData();
  }
});
