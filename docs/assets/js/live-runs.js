async function fetchJsonl(path) {
  const response = await fetch(path);
  if (!response.ok) {
    throw new Error(`Failed to load ${path}: ${response.status}`);
  }
  const text = await response.text();
  return text
    .split("\n")
    .map((line) => line.trim())
    .filter((line) => line.length > 0)
    .map((line) => JSON.parse(line));
}

function formatNumber(value) {
  if (value === null || value === undefined) {
    return "-";
  }
  const num = Number(value);
  if (Number.isNaN(num)) {
    return String(value);
  }
  return num.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function formatTime(value) {
  if (!value) {
    return "-";
  }
  return new Date(value).toISOString().replace("T", " ").replace("Z", "");
}

function renderLatestSummary(latest) {
  const container = document.getElementById("latest-summary");
  if (!latest) {
    container.textContent = "No runs found.";
    return;
  }
  const status = latest.status || "-";
  const equity = formatNumber(latest.equity);
  const buyingPower = formatNumber(latest.buying_power);
  const signature = latest.model_signature || "-";
  container.innerHTML = `
    <div><strong>Status:</strong> ${status}</div>
    <div><strong>Signature:</strong> ${signature}</div>
    <div><strong>Equity:</strong> ${equity}</div>
    <div><strong>Buying Power:</strong> ${buyingPower}</div>
    <div><strong>Timestamp:</strong> ${formatTime(latest.timestamp)}</div>
  `;
}

function renderRunsTable(runs) {
  const tbody = document.getElementById("runs-body");
  tbody.innerHTML = "";
  runs.forEach((run) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>${formatTime(run.timestamp)}</td>
      <td>${run.run_id || "-"}</td>
      <td>${run.model_signature || "-"}</td>
      <td>${run.status || "-"}</td>
      <td>${formatNumber(run.equity)}</td>
      <td>${formatNumber(run.buying_power)}</td>
    `;
    tbody.appendChild(row);
  });
}

function renderAlerts(alerts) {
  const container = document.getElementById("alert-summary");
  if (!alerts.length) {
    container.textContent = "No alerts found.";
    return;
  }
  const items = alerts
    .slice(-5)
    .reverse()
    .map((alert) => {
      const event = alert.event || "alert";
      const when = formatTime(alert.timestamp);
      const details = alert.details ? JSON.stringify(alert.details) : "";
      return `<div><strong>${event}</strong> (${when})<pre>${details}</pre></div>`;
    })
    .join("");
  container.innerHTML = items;
}

async function init() {
  try {
    const runs = await fetchJsonl("/data/live_runs.jsonl");
    runs.sort((a, b) => (a.timestamp < b.timestamp ? 1 : -1));
    renderLatestSummary(runs[0]);
    renderRunsTable(runs.slice(0, 25));
  } catch (error) {
    document.getElementById("latest-summary").textContent = error.message;
  }

  try {
    const alerts = await fetchJsonl("/data/live_alerts.jsonl");
    renderAlerts(alerts);
  } catch (error) {
    document.getElementById("alert-summary").textContent = error.message;
  }
}

init();
