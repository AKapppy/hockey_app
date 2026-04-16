(function () {
  const data = window.HOCKEY_APP_DATA;
  const state = {
    metric: "madeplayoffs",
    selectedTeam: "",
    query: "",
  };

  const els = {
    status: document.getElementById("data-status"),
    tabs: document.getElementById("metric-tabs"),
    search: document.getElementById("team-search"),
    summary: document.getElementById("summary-grid"),
    chartHeading: document.getElementById("chart-heading"),
    chartKicker: document.getElementById("chart-kicker"),
    chartWrap: document.getElementById("chart-wrap"),
    teamSelect: document.getElementById("team-select"),
    table: document.getElementById("team-table"),
  };

  if (!data || !data.tables) {
    document.body.innerHTML = '<main class="shell"><section class="empty-state">No web data found. Run <strong>python -m hockey_app.tools.export_web --out docs</strong>.</section></main>';
    return;
  }

  const byCode = new Map(data.teams.map((team) => [team.code, team]));

  function metricInfo() {
    return data.metrics.find((metric) => metric.key === state.metric) || data.metrics[0];
  }

  function tableFor(metricKey) {
    return data.tables[metricKey] || { columns: [], rows: {} };
  }

  function latestValue(values) {
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (values[i] !== null && Number.isFinite(values[i])) return values[i];
    }
    return 0;
  }

  function priorValue(values, days) {
    const lastIndex = values.length - 1;
    const idx = Math.max(0, lastIndex - days);
    for (let i = idx; i >= 0; i -= 1) {
      if (values[i] !== null && Number.isFinite(values[i])) return values[i];
    }
    return latestValue(values);
  }

  function pct(value) {
    return `${Math.round((value || 0) * 1000) / 10}%`;
  }

  function signedPct(value) {
    const rounded = Math.round(value * 1000) / 10;
    if (rounded > 0) return `+${rounded}%`;
    if (rounded < 0) return `${rounded}%`;
    return "0.0%";
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function sortedRows(metricKey) {
    const table = tableFor(metricKey);
    return Object.entries(table.rows)
      .map(([code, values]) => {
        const latest = latestValue(values);
        const week = latest - priorValue(values, 7);
        const team = byCode.get(code) || { code, name: code, color: "#777777" };
        return { code, values, latest, week, team };
      })
      .sort((a, b) => b.latest - a.latest || a.team.name.localeCompare(b.team.name));
  }

  function filteredRows() {
    const query = state.query.trim().toLowerCase();
    const rows = sortedRows(state.metric);
    if (!query) return rows;
    return rows.filter(({ code, team }) => {
      return code.toLowerCase().includes(query) || String(team.name).toLowerCase().includes(query);
    });
  }

  function ensureSelectedTeam() {
    const rows = sortedRows(state.metric);
    if (!state.selectedTeam || !rows.some((row) => row.code === state.selectedTeam)) {
      state.selectedTeam = rows[0] ? rows[0].code : "";
    }
  }

  function renderStatus() {
    const meta = data.metadata || {};
    const generated = meta.generatedAt ? new Date(meta.generatedAt).toLocaleString([], {
      month: "short",
      day: "numeric",
      hour: "numeric",
      minute: "2-digit",
    }) : "unknown";
    els.status.textContent = `${meta.season || ""} through ${meta.endDate || ""} · updated ${generated}`;
  }

  function renderTabs() {
    els.tabs.innerHTML = data.metrics.map((metric) => {
      const pressed = metric.key === state.metric ? "true" : "false";
      return `<button class="metric-tab" type="button" data-metric="${escapeHtml(metric.key)}" aria-pressed="${pressed}">${escapeHtml(metric.label)}</button>`;
    }).join("");
  }

  function renderTeamSelect() {
    const rows = sortedRows(state.metric);
    els.teamSelect.innerHTML = rows.map(({ code, team }) => {
      const selected = code === state.selectedTeam ? " selected" : "";
      return `<option value="${escapeHtml(code)}"${selected}>${escapeHtml(team.name)} (${escapeHtml(code)})</option>`;
    }).join("");
  }

  function renderSummary() {
    const rows = sortedRows(state.metric);
    const selected = rows.find((row) => row.code === state.selectedTeam) || rows[0];
    const riser = rows.slice().sort((a, b) => b.week - a.week)[0];
    const faller = rows.slice().sort((a, b) => a.week - b.week)[0];
    const leader = rows[0];
    const cards = [
      ["Leader", leader ? leader.team.name : "No data", leader ? pct(leader.latest) : "", ""],
      ["Highlight", selected ? selected.team.name : "No data", selected ? pct(selected.latest) : "", selected ? signedPct(selected.week) + " in 7 days" : ""],
      ["Best week", riser ? riser.team.name : "No data", riser ? signedPct(riser.week) : "", riser ? pct(riser.latest) + " current" : ""],
      ["Sharpest drop", faller ? faller.team.name : "No data", faller ? signedPct(faller.week) : "", faller ? pct(faller.latest) + " current" : ""],
    ];
    els.summary.innerHTML = cards.map(([label, title, value, sub]) => `
      <article class="summary-card">
        <p class="label">${escapeHtml(label)}</p>
        <p class="value">${escapeHtml(value)}</p>
        <p class="sub">${escapeHtml(title)}</p>
        <p class="sub">${escapeHtml(sub)}</p>
      </article>
    `).join("");
  }

  function pointsFor(values, width, height, pad) {
    const usableW = width - pad.left - pad.right;
    const usableH = height - pad.top - pad.bottom;
    const last = Math.max(1, values.length - 1);
    return values.map((value, idx) => {
      const safeValue = Number.isFinite(value) ? value : 0;
      const x = pad.left + (idx / last) * usableW;
      const y = pad.top + (1 - Math.max(0, Math.min(1, safeValue))) * usableH;
      return [x, y];
    });
  }

  function linePath(points) {
    return points.map(([x, y], idx) => `${idx === 0 ? "M" : "L"}${x.toFixed(2)} ${y.toFixed(2)}`).join(" ");
  }

  function renderChart() {
    const info = metricInfo();
    const rows = sortedRows(state.metric);
    const highlighted = rows.find((row) => row.code === state.selectedTeam);
    const topRows = rows.slice(0, 8);
    const chartRows = highlighted && !topRows.some((row) => row.code === highlighted.code)
      ? [...topRows.slice(0, 7), highlighted]
      : topRows;
    const table = tableFor(state.metric);
    const width = 960;
    const height = 360;
    const pad = { left: 56, right: 18, top: 18, bottom: 42 };
    const yTicks = [0, 0.25, 0.5, 0.75, 1];
    const xLabels = [
      { label: table.columns[0] || "", index: 0 },
      { label: table.columns[Math.floor((table.columns.length - 1) / 2)] || "", index: Math.floor((table.columns.length - 1) / 2) },
      { label: table.columns[table.columns.length - 1] || "", index: table.columns.length - 1 },
    ];

    els.chartHeading.textContent = info.title;
    els.chartKicker.textContent = info.label;

    const grid = yTicks.map((tick) => {
      const y = pad.top + (1 - tick) * (height - pad.top - pad.bottom);
      return `<line class="grid-line" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line>
        <text class="chart-label" x="8" y="${y + 4}">${pct(tick)}</text>`;
    }).join("");

    const xAxisLabels = xLabels.map(({ label, index }) => {
      const x = pad.left + (index / Math.max(1, table.columns.length - 1)) * (width - pad.left - pad.right);
      return `<text class="chart-label" x="${x}" y="${height - 12}" text-anchor="middle">${escapeHtml(label)}</text>`;
    }).join("");

    const lines = chartRows.map(({ code, values, team }) => {
      const pts = pointsFor(values, width, height, pad);
      const last = pts[pts.length - 1] || [pad.left, pad.top];
      const selected = code === state.selectedTeam;
      return `<path class="chart-line${selected ? " is-selected" : ""}" d="${linePath(pts)}" stroke="${escapeHtml(team.color)}"></path>
        <circle class="chart-dot" cx="${last[0]}" cy="${last[1]}" r="${selected ? 5 : 3}" fill="${escapeHtml(team.color)}"></circle>`;
    }).join("");

    const legend = chartRows.map(({ code, team }) => `
      <button class="team-chip" type="button" data-team="${escapeHtml(code)}" aria-pressed="${code === state.selectedTeam ? "true" : "false"}">
        <img src="${escapeHtml(team.logo)}" alt="" loading="lazy" onerror="this.style.display='none'">
        <span>${escapeHtml(code)}</span>
      </button>
    `).join("");

    els.chartWrap.innerHTML = `
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" role="img" aria-label="${escapeHtml(info.label)} trend chart">
        ${grid}
        <line class="axis" x1="${pad.left}" y1="${height - pad.bottom}" x2="${width - pad.right}" y2="${height - pad.bottom}"></line>
        <line class="axis" x1="${pad.left}" y1="${pad.top}" x2="${pad.left}" y2="${height - pad.bottom}"></line>
        ${xAxisLabels}
        ${lines}
      </svg>
      <div class="legend">${legend}</div>
    `;
  }

  function sparkline(values, color) {
    const width = 112;
    const height = 34;
    const pts = pointsFor(values.slice(-28), width, height, { left: 2, right: 2, top: 3, bottom: 3 });
    return `<svg class="spark" viewBox="0 0 ${width} ${height}" aria-hidden="true">
      <path d="${linePath(pts)}" fill="none" stroke="${escapeHtml(color)}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"></path>
    </svg>`;
  }

  function renderTable() {
    const rows = filteredRows();
    if (!rows.length) {
      els.table.innerHTML = '<tr><td colspan="6" class="empty-state">No matching teams.</td></tr>';
      return;
    }
    els.table.innerHTML = rows.map(({ code, values, latest, week, team }) => {
      const cls = week > 0 ? "delta-up" : week < 0 ? "delta-down" : "";
      return `<tr data-team="${escapeHtml(code)}" class="${code === state.selectedTeam ? "is-selected" : ""}">
        <td>
          <div class="team-cell">
            <img class="team-logo" src="${escapeHtml(team.logo)}" alt="" loading="lazy" onerror="this.style.display='none'">
            <div>
              <strong>${escapeHtml(team.name)}</strong>
              <div class="team-code">${escapeHtml(code)}</div>
            </div>
          </div>
        </td>
        <td>${escapeHtml(team.conference || "-")}</td>
        <td>${escapeHtml(team.division || "-")}</td>
        <td class="number"><strong>${pct(latest)}</strong></td>
        <td class="number ${cls}">${signedPct(week)}</td>
        <td>${sparkline(values, team.color)}</td>
      </tr>`;
    }).join("");
  }

  function renderAll() {
    ensureSelectedTeam();
    renderStatus();
    renderTabs();
    renderTeamSelect();
    renderSummary();
    renderChart();
    renderTable();
  }

  els.tabs.addEventListener("click", (event) => {
    const button = event.target.closest("[data-metric]");
    if (!button) return;
    state.metric = button.getAttribute("data-metric");
    renderAll();
  });

  els.teamSelect.addEventListener("change", () => {
    state.selectedTeam = els.teamSelect.value;
    renderAll();
  });

  els.search.addEventListener("input", () => {
    state.query = els.search.value;
    renderTable();
  });

  els.chartWrap.addEventListener("click", (event) => {
    const button = event.target.closest("[data-team]");
    if (!button) return;
    state.selectedTeam = button.getAttribute("data-team");
    renderAll();
  });

  els.table.addEventListener("click", (event) => {
    const row = event.target.closest("[data-team]");
    if (!row) return;
    state.selectedTeam = row.getAttribute("data-team");
    renderAll();
  });

  renderAll();
}());
