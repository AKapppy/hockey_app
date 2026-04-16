(function () {
  const data = window.HOCKEY_APP_DATA;
  const app = document.getElementById("app");

  if (!data || !data.tables) {
    app.innerHTML = '<div class="coming-soon-wrap"><div class="coming-soon"><h2>No web data found</h2><p>Run python -m hockey_app.tools.export_web --out docs.</p></div></div>';
    return;
  }

  const metricOrder = data.metrics.map((m) => m.key);
  const metricLabels = Object.fromEntries(data.metrics.map((m) => [m.key, m.label]));
  const metricTitles = Object.fromEntries(data.metrics.map((m) => [m.key, m.title]));
  const byCode = new Map(data.teams.map((t) => [t.code, t]));
  const divisions = ["Pacific", "Central", "Atlantic", "Metro"];
  const tableHeaders = {
    madeplayoffs: "Playoffs",
    round2: "Round 2",
    round3: "Conf. Finals",
    round4: "Cup Final",
    woncup: "Win Cup",
  };
  const pwhlTeams = [
    ["BOS", "Boston Fleet"],
    ["MIN", "Minnesota Frost"],
    ["MTL", "Montreal Victoire"],
    ["NY", "New York Sirens"],
    ["OTT", "Ottawa Charge"],
    ["TOR", "Toronto Sceptres"],
    ["VAN", "Vancouver"],
    ["SEA", "Seattle"],
  ];

  const state = {
    mainTab: "Scoreboard",
    predTab: "Pie Chart",
    pred2Tab: "Pie Chart",
    statsTab: "Team Stats",
    modelsTab: "Playoff Picture",
    selectedTeam: null,
    league: "NHL",
    dateIdx: maxDateIndex(),
    metricSort: {},
    openMenu: null,
  };

  function esc(value) {
    return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    }[ch]));
  }

  function table(metric) {
    return data.tables[metric] || { columns: [], rows: {} };
  }

  function maxDateIndex() {
    const ref = data.tables.madeplayoffs || Object.values(data.tables)[0] || { columns: [] };
    return Math.max(0, (ref.columns || []).length - 1);
  }

  function clampDate(idx) {
    return Math.max(0, Math.min(maxDateIndex(), Number(idx) || 0));
  }

  function valueAt(metric, code, idx = state.dateIdx) {
    const values = table(metric).rows[code] || [];
    const value = values[Math.max(0, Math.min(idx, values.length - 1))];
    return Number.isFinite(value) ? value : null;
  }

  function latest(metric, code) {
    const values = table(metric).rows[code] || [];
    for (let i = values.length - 1; i >= 0; i -= 1) {
      if (Number.isFinite(values[i])) return values[i];
    }
    return 0;
  }

  function pct(value) {
    if (!Number.isFinite(value)) return "";
    return `${(value * 100).toFixed(1)}%`;
  }

  function dateLabel(idx = state.dateIdx) {
    const cols = table("madeplayoffs").columns || [];
    return cols[Math.max(0, Math.min(idx, cols.length - 1))] || "";
  }

  function prettyDate(idx = state.dateIdx) {
    const start = new Date(`${data.metadata.startDate}T00:00:00`);
    if (Number.isNaN(start.getTime())) return dateLabel(idx);
    start.setDate(start.getDate() + idx);
    return `${start.getDate()} ${start.toLocaleString("en-US", { month: "short" })} ${start.getFullYear()}`;
  }

  function teamCodes() {
    return [...byCode.keys()].sort();
  }

  function teamName(code) {
    if (state.league === "PWHL") {
      const pwhl = pwhlTeams.find(([c]) => c === code);
      if (pwhl) return pwhl[1];
    }
    const team = byCode.get(code);
    return team ? team.name : code;
  }

  function logo(code) {
    const team = byCode.get(code);
    return team ? team.logo : `assets/nhl_logos/${code}.png`;
  }

  function teamColor(code) {
    const team = byCode.get(code);
    return team ? team.color : "#888888";
  }

  function blend(hex, bg, amount) {
    const a = hexToRgb(hex);
    const b = hexToRgb(bg);
    const t = Math.max(0, Math.min(1, amount));
    return rgbToHex(
      Math.round(a[0] + (b[0] - a[0]) * t),
      Math.round(a[1] + (b[1] - a[1]) * t),
      Math.round(a[2] + (b[2] - a[2]) * t),
    );
  }

  function hexToRgb(hex) {
    const clean = String(hex || "#888888").replace("#", "");
    return [
      parseInt(clean.slice(0, 2), 16) || 0,
      parseInt(clean.slice(2, 4), 16) || 0,
      parseInt(clean.slice(4, 6), 16) || 0,
    ];
  }

  function rgbToHex(r, g, b) {
    return `#${[r, g, b].map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, "0")).join("")}`;
  }

  function luminance(hex) {
    const [r, g, b] = hexToRgb(hex).map((c) => {
      const v = c / 255;
      return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
    });
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  }

  function heatColor(metric, code, idx = state.dateIdx) {
    const vals = teamCodes()
      .map((c) => valueAt(metric, c, idx))
      .filter((v) => Number.isFinite(v))
      .sort((a, b) => a - b);
    const val = valueAt(metric, code, idx);
    if (!Number.isFinite(val) || !vals.length) return "#262626";
    const rank = vals.length === 1 ? 0.5 : vals.findIndex((v) => v >= val) / (vals.length - 1);
    const t = Math.round(Math.max(0, Math.min(1, rank)) * 31) / 31;
    let r;
    let g;
    let b = 0;
    if (t <= 0.5) {
      const u = t * 2;
      r = 255;
      g = Math.round(255 * u);
    } else {
      const u = (t - 0.5) * 2;
      r = Math.round(255 * (1 - u));
      g = 255;
    }
    r = Math.round(r * 0.56);
    g = Math.round(g * 0.56);
    b = Math.round(b * 0.56);
    return blend(rgbToHex(r, g, b), "#262626", 0.12);
  }

  function textForBg(bg) {
    return luminance(bg) > 0.4 ? "#101010" : "#f7f7f7";
  }

  function defaultPredictionOrder() {
    const priority = ["woncup", "round4", "round3", "round2", "madeplayoffs"];
    return teamCodes().sort((a, b) => {
      for (const metric of priority) {
        const delta = (valueAt(metric, b) ?? -1) - (valueAt(metric, a) ?? -1);
        if (Math.abs(delta) > 0.000001) return delta;
      }
      return teamName(a).localeCompare(teamName(b));
    });
  }

  function alphabeticalOrder() {
    return teamCodes().sort((a, b) => teamName(a).localeCompare(teamName(b)));
  }

  function orderForMetric(metric) {
    if (state.metricSort[metric] === "team") return alphabeticalOrder();
    return teamCodes().sort((a, b) => {
      const delta = (valueAt(metric, b) ?? -1) - (valueAt(metric, a) ?? -1);
      if (Math.abs(delta) > 0.000001) return delta;
      return teamName(a).localeCompare(teamName(b));
    });
  }

  function render() {
    app.innerHTML = `
      ${renderGlobalControls()}
      <div class="notebook">
        ${renderTabbar(["Scoreboard", "Stats", "Predictions", "Predictions 2", "Models"], state.mainTab, "main")}
        <div class="page">${renderMainPage()}</div>
      </div>
      <div id="menu-host"></div>
    `;
    renderMenu();
  }

  function renderGlobalControls() {
    const selected = state.selectedTeam;
    const selectedImg = selected ? `<img class="button-logo" src="${esc(logo(selected))}" alt="">` : "";
    const teamText = selected ? teamName(selected) : "Choose team";
    const season = data.metadata.season || "";
    const shortSeason = season.replace(/-(\d{2})\d{2}$/, "-$1");
    return `
      <div class="global-controls">
        <div class="global-left">
          <button class="tk-button ${state.openMenu === "team" ? "is-open" : ""}" data-action="team-menu">${selectedImg}<span>${esc(teamText)}</span></button>
          <button class="tk-button" data-action="reset">Reset</button>
          <button class="tk-button" data-action="toggle-league">League: ${esc(state.league)}</button>
        </div>
        <div class="global-right">
          <button class="tk-button ${state.openMenu === "season" ? "is-open" : ""}" data-action="season-menu">Season: ${esc(shortSeason || season)}</button>
        </div>
      </div>
    `;
  }

  function renderTabbar(labels, active, scope) {
    return `<div class="tabbar" data-scope="${scope}">
      ${labels.map((label, idx) => {
        const tab = `<button class="tab ${label === active ? "is-active" : ""}" data-tab="${esc(label)}">${esc(label)}</button>`;
        return idx < labels.length - 1 ? `${tab}<div class="tab-gap"></div>` : tab;
      }).join("")}
    </div>`;
  }

  function renderMainPage() {
    if (state.mainTab === "Scoreboard") {
      return renderComingSoon("Scoreboard", "The desktop app loads this from live NHL/PWHL data. The static web export is currently mirroring the prediction views.");
    }
    if (state.mainTab === "Stats") return renderStatsPage();
    if (state.mainTab === "Predictions") return renderPredictionsPage("predTab", "Data collected from MoneyPuck.com");
    if (state.mainTab === "Predictions 2") return renderPredictionsPage("pred2Tab", "Public NHL API model (non-MoneyPuck) | static export uses MoneyPuck data");
    return renderModelsPage();
  }

  function renderStatsPage() {
    const tabs = ["Team Stats", "Game Stats", "Player Stats", "Goal Differential", "Points"];
    return `
      <div class="nested-page">
        ${renderTabbar(tabs, state.statsTab, "stats")}
        ${renderComingSoon(state.statsTab, "This static web build uses the desktop notebook chrome. Exporting the full Stats XML into matching web canvases is the next step.")}
      </div>
    `;
  }

  function renderModelsPage() {
    const tabs = ["Playoff Picture", "Magic/Tragic", "Point Probabilities", "Playoff Win Probabilities"];
    return `
      <div class="nested-page">
        ${renderTabbar(tabs, state.modelsTab, "models")}
        ${renderComingSoon(state.modelsTab, "This static web build uses the desktop notebook chrome. Exporting the full Models XML into matching web canvases is the next step.")}
      </div>
    `;
  }

  function renderPredictionsPage(tabKey, note) {
    const tabs = ["Pie Chart", ...data.metrics.map((m) => m.label)];
    const active = state[tabKey];
    if (state.league === "PWHL") {
      return `
        <div class="nested-page">
          ${renderTabbar(tabs, active, tabKey)}
          ${renderComingSoon("Predictions Coming Soon", "PWHL prediction data is not available yet.")}
          <div class="source-note">${esc(note)}</div>
        </div>
      `;
    }
    const metric = metricOrder.find((m) => metricLabels[m] === active);
    return `
      <div class="nested-page">
        ${renderTabbar(tabs, active, tabKey)}
        ${active === "Pie Chart" ? renderPieView() : renderMetricView(metric || metricOrder[0])}
        <div class="source-note">${esc(note)}</div>
      </div>
    `;
  }

  function renderComingSoon(title, message) {
    return `
      <div class="coming-soon-wrap page-fill">
        <div class="coming-soon">
          <h2>${esc(title)}</h2>
          <p>${esc(message)}</p>
        </div>
      </div>
    `;
  }

  function renderStepper() {
    const max = maxDateIndex();
    const left = max <= 0 ? 0 : state.dateIdx / max * 100;
    return `
      <div class="step-row">
        <button type="button" data-action="step-date" data-delta="-1">◀</button>
        <div class="slider-track" data-action="slider">
          <div class="slider-thumb" style="left:${left}%"></div>
        </div>
        <button type="button" data-action="step-date" data-delta="1">▶</button>
      </div>
    `;
  }

  function renderPieView() {
    return `
      <div class="pie-view">
        ${renderStepper()}
        <div class="pie-content">
          <div class="pie-table-panel">${renderPieTable()}</div>
          <div class="pie-chart-panel">${renderPieChart()}</div>
        </div>
      </div>
    `;
  }

  function renderPieTable() {
    const rows = pieTableOrder();
    return `
      <table class="tk-table">
        <thead>
          <tr><th class="date-title" colspan="${metricOrder.length + 1}">${esc(prettyDate())}</th></tr>
          <tr>
            <th class="team-cell" data-action="pie-sort-team">Team</th>
            ${metricOrder.map((m) => `<th data-action="pie-sort-metric" data-metric="${esc(m)}">${esc(tableHeaders[m] || metricLabels[m])}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${rows.map((code) => `
            <tr>
              <td class="team-cell ${code === state.selectedTeam ? "selected-outline" : ""}" data-team="${esc(code)}">
                <div class="team-cell-inner"><img class="team-logo" src="${esc(logo(code))}" alt=""><span>${esc(code)}</span></div>
              </td>
              ${metricOrder.map((metric) => {
                const bg = heatColor(metric, code);
                return `<td data-team="${esc(code)}" data-metric="${esc(metric)}" style="background:${bg};color:${textForBg(bg)}">${esc(pct(valueAt(metric, code)))}</td>`;
              }).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  function pieOrder() {
    const present = new Set(teamCodes());
    const order = [];
    for (const div of ["Metro", "Atlantic", "Central", "Pacific"]) {
      const codes = data.teams
        .filter((t) => t.division === div && present.has(t.code))
        .map((t) => t.code);
      if (div === "Metro" && codes.includes("NYR")) {
        order.push("NYR", ...codes.filter((c) => c !== "NYR"));
      } else {
        order.push(...codes);
      }
    }
    return order;
  }

  function pieTableOrder() {
    if (state.metricSort.__pie === "team") return alphabeticalOrder();
    if (metricOrder.includes(state.metricSort.__pie)) {
      const metric = state.metricSort.__pie;
      return teamCodes().sort((a, b) => {
        const delta = (valueAt(metric, b) ?? -1) - (valueAt(metric, a) ?? -1);
        if (Math.abs(delta) > 0.000001) return delta;
        return teamName(a).localeCompare(teamName(b));
      });
    }
    return defaultPredictionOrder();
  }

  function renderPieChart() {
    const size = 720;
    const cx = size / 2;
    const cy = size / 2;
    const outer = 330;
    const inner = 78;
    const thick = (outer - inner) / metricOrder.length;
    const start0 = -90;
    const selected = state.selectedTeam;
    const pieces = [];
    const logos = [];
    metricOrder.forEach((metric, i) => {
      const rOut = outer - i * thick;
      const rIn = Math.max(inner, rOut - thick);
      const vals = pieOrder()
        .map((code) => [code, valueAt(metric, code)])
        .filter(([, value]) => Number.isFinite(value) && value > 0);
      const total = vals.reduce((sum, [, value]) => sum + value, 0);
      let cum = 0;
      vals.forEach(([code, value]) => {
        const extent = total > 0 ? 360 * value / total : 0;
        const start = start0 + cum;
        const mid = start + extent / 2;
        const fillBase = blend(teamColor(code), "#262626", 0.06 + 0.08 * i);
        const fill = selected && selected !== code ? blend(fillBase, "#262626", 0.65) : fillBase;
        pieces.push(`<path d="${annularPath(cx, cy, rIn, rOut, start, extent)}" fill="${fill}" data-team="${esc(code)}" data-metric="${esc(metric)}"><title>${esc(code)} ${esc(tableHeaders[metric] || metric)} ${esc(pct(value))}</title></path>`);
        if (metric === "madeplayoffs" && extent > 4) {
          const point = polar(cx, cy, rIn + (rOut - rIn) * 0.62, mid);
          const dim = selected && selected !== code ? "opacity:0.35" : "";
          logos.push(`<image href="${esc(logo(code))}" x="${point.x - 13}" y="${point.y - 13}" width="26" height="26" style="${dim}" data-team="${esc(code)}"></image>`);
        }
        cum += extent;
      });
    });
    const rings = metricOrder.slice(1).map((_, i) => {
      const r = outer - (i + 1) * thick;
      return `<circle cx="${cx}" cy="${cy}" r="${r}" fill="none" stroke="#262626" stroke-width="3"></circle>`;
    }).join("");
    return `
      <svg class="chart-svg" viewBox="0 0 ${size} ${size}" role="img" aria-label="Pie Chart">
        ${pieces.join("")}
        ${rings}
        <circle cx="${cx}" cy="${cy}" r="${inner - 5}" fill="#262626"></circle>
        <image href="assets/stanley_cup.png" x="${cx - 45}" y="${cy - 60}" width="90" height="120" preserveAspectRatio="xMidYMid meet"></image>
        <text x="${cx}" y="${cy + 72}" text-anchor="middle" fill="#f0f0f0" font-size="24" font-weight="700">${esc(dateLabel())}</text>
        ${logos.join("")}
      </svg>
    `;
  }

  function annularPath(cx, cy, rIn, rOut, startDeg, extentDeg) {
    const endDeg = startDeg + extentDeg;
    const p1 = polar(cx, cy, rOut, startDeg);
    const p2 = polar(cx, cy, rOut, endDeg);
    const p3 = polar(cx, cy, rIn, endDeg);
    const p4 = polar(cx, cy, rIn, startDeg);
    const large = extentDeg > 180 ? 1 : 0;
    return [
      `M ${p1.x} ${p1.y}`,
      `A ${rOut} ${rOut} 0 ${large} 1 ${p2.x} ${p2.y}`,
      `L ${p3.x} ${p3.y}`,
      `A ${rIn} ${rIn} 0 ${large} 0 ${p4.x} ${p4.y}`,
      "Z",
    ].join(" ");
  }

  function polar(cx, cy, r, deg) {
    const rad = deg * Math.PI / 180;
    return { x: cx + r * Math.cos(rad), y: cy + r * Math.sin(rad) };
  }

  function renderMetricView(metric) {
    const rows = orderForMetric(metric);
    return `
      <div class="metric-view">
        <div class="metric-top">
          <div class="heatmap-wrap">${renderHeatmapTable(metric, rows)}</div>
          <div class="bar-wrap">${renderBars(metric, rows)}</div>
        </div>
        <div class="metric-bottom">
          <div class="graph-wrap">${renderLineGraph(metric, rows)}</div>
          <div>
            <div class="metric-title">${esc(metricTitles[metric] || metricLabels[metric])}</div>
            <div class="logos-wrap">${renderLogoGrid(rows)}</div>
          </div>
        </div>
        ${renderStepper()}
      </div>
    `;
  }

  function renderHeatmapTable(metric, rows) {
    const cols = table(metric).columns || [];
    return `
      <table class="tk-table">
        <thead>
          <tr>
            <th class="team-cell" data-action="metric-sort-team" data-metric="${esc(metric)}">Team</th>
            ${cols.map((col, idx) => `<th data-action="select-date" data-idx="${idx}">${esc(col)}</th>`).join("")}
          </tr>
        </thead>
        <tbody>
          ${rows.map((code) => `
            <tr>
              <td class="team-cell ${code === state.selectedTeam ? "selected-outline" : ""}" data-team="${esc(code)}">
                <div class="team-cell-inner"><img class="team-logo" src="${esc(logo(code))}" alt=""><span>${esc(code)}</span></div>
              </td>
              ${cols.map((_, idx) => {
                const bg = heatColor(metric, code, idx);
                const selected = idx === state.dateIdx ? "selected-outline" : "";
                return `<td class="${selected}" data-team="${esc(code)}" data-idx="${idx}" style="background:${bg};color:${textForBg(bg)}">${esc(pct(valueAt(metric, code, idx)))}</td>`;
              }).join("")}
            </tr>
          `).join("")}
        </tbody>
      </table>
    `;
  }

  function renderBars(metric, rows) {
    const max = Math.max(0.05, ...rows.map((code) => valueAt(metric, code) || 0));
    return `
      <table class="tk-table" style="width:100%">
        <thead><tr><th>${esc(prettyDate())}</th></tr></thead>
      </table>
      <div style="padding:0 8px">
        ${rows.map((code) => {
          const value = valueAt(metric, code) || 0;
          const width = Math.max(1, value / max * 100);
          const dim = state.selectedTeam && state.selectedTeam !== code;
          const c0 = blend(teamColor(code), "#262626", dim ? 0.7 : 0.35);
          const c1 = blend(teamColor(code), "#ffffff", dim ? 0.72 : 0.45);
          return `
            <div class="bar-row" data-team="${esc(code)}">
              <div class="bar-track"><div class="bar-fill" style="width:${width}%;background:linear-gradient(90deg,${c0},${c1})"></div></div>
              <div class="bar-value">${esc(pct(value))}</div>
            </div>
          `;
        }).join("")}
      </div>
    `;
  }

  function renderLineGraph(metric, rows) {
    const cols = table(metric).columns || [];
    const width = Math.max(800, cols.length * 8);
    const height = 310;
    const pad = { left: 54, right: 18, top: 16, bottom: 34 };
    const yMax = Math.max(0.05, ...rows.flatMap((code) => (table(metric).rows[code] || []).filter(Number.isFinite)));
    const ticks = [0, 0.25, 0.5, 0.75, 1].filter((v) => v <= Math.max(1, yMax));
    const xFor = (idx) => pad.left + idx / Math.max(1, cols.length - 1) * (width - pad.left - pad.right);
    const yFor = (value) => pad.top + (1 - (value / Math.max(1, yMax))) * (height - pad.top - pad.bottom);
    const grid = ticks.map((tick) => {
      const y = yFor(tick);
      return `<line class="chart-grid" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line><text class="chart-axis" x="${pad.left - 8}" y="${y + 4}" text-anchor="end">${esc(pct(tick))}</text>`;
    }).join("");
    const lines = rows.map((code) => {
      const values = table(metric).rows[code] || [];
      const points = values.map((v, idx) => `${idx === 0 ? "M" : "L"} ${xFor(idx).toFixed(1)} ${yFor(Number.isFinite(v) ? v : 0).toFixed(1)}`).join(" ");
      const selected = state.selectedTeam === code;
      const color = selected || !state.selectedTeam ? teamColor(code) : blend(teamColor(code), "#262626", 0.65);
      return `<path class="line-path ${selected ? "is-selected" : ""}" d="${points}" stroke="${esc(color)}" data-team="${esc(code)}"><title>${esc(code)}</title></path>`;
    }).join("");
    const dateX = xFor(state.dateIdx);
    return `
      <svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none" role="img" aria-label="${esc(metricLabels[metric])}">
        ${grid}
        <line class="chart-grid" x1="${dateX}" y1="${pad.top}" x2="${dateX}" y2="${height - pad.bottom}" stroke="#6a6a6a" stroke-width="2"></line>
        ${lines}
        <text class="chart-axis" x="${pad.left}" y="${height - 10}">${esc(cols[0] || "")}</text>
        <text class="chart-axis" x="${width - pad.right}" y="${height - 10}" text-anchor="end">${esc(cols[cols.length - 1] || "")}</text>
      </svg>
    `;
  }

  function renderLogoGrid(rows) {
    const picks = rows.slice(0, 16);
    return `<div class="mini-logos">
      ${picks.map((code) => {
        const dim = state.selectedTeam && state.selectedTeam !== code;
        return `<button class="mini-logo ${dim ? "is-dim" : ""} ${state.selectedTeam === code ? "is-selected" : ""}" data-team="${esc(code)}" title="${esc(teamName(code))}"><img src="${esc(logo(code))}" alt="${esc(code)}"></button>`;
      }).join("")}
    </div>`;
  }

  function renderMenu() {
    const host = document.getElementById("menu-host");
    if (!host || !state.openMenu) return;
    if (state.openMenu === "team") {
      host.innerHTML = `<div class="menu team-menu" style="left:8px;top:44px">${renderTeamMenu()}</div>`;
    } else {
      host.innerHTML = `<div class="menu season-menu" style="right:8px;top:44px">${renderSeasonMenu()}</div>`;
    }
  }

  function renderTeamMenu() {
    if (state.league === "PWHL") {
      return `<div class="team-menu-grid" style="grid-template-columns:repeat(2,max-content)">${pwhlTeams.map(([code, name]) => `
        <div class="menu-item" data-team="${esc(code)}"><span>${esc(code)}</span><span>${esc(name)}</span></div>
      `).join("")}</div>`;
    }
    return `<div class="team-menu-grid">${divisions.map((div) => `
      <div>
        <div class="menu-title">${esc(div)}</div>
        ${data.teams.filter((t) => t.division === div).map((t) => `
          <div class="menu-item" data-team="${esc(t.code)}">
            <img src="${esc(t.logo)}" alt=""><span>${esc(t.code)}</span>
          </div>
        `).join("")}
      </div>
    `).join("")}</div>`;
  }

  function renderSeasonMenu() {
    const season = data.metadata.season || "2025-2026";
    const start = Number(String(season).slice(0, 4)) || 2025;
    const years = [];
    for (let y = start; y >= 2023; y -= 1) years.push(`${y}-${y + 1}`);
    return years.map((s) => {
      const short = s.replace(/-(\d{2})\d{2}$/, "-$1");
      return `<div class="menu-item" data-season="${esc(s)}">${esc(short)}${s === season ? "  (current)" : ""}</div>`;
    }).join("");
  }

  function onClick(event) {
    const tab = event.target.closest(".tab");
    if (tab) {
      const scope = tab.closest(".tabbar").dataset.scope;
      const label = tab.dataset.tab;
      if (scope === "main") state.mainTab = label;
      if (scope === "stats") state.statsTab = label;
      if (scope === "models") state.modelsTab = label;
      if (scope === "predTab") state.predTab = label;
      if (scope === "pred2Tab") state.pred2Tab = label;
      state.openMenu = null;
      render();
      return;
    }

    const actionEl = event.target.closest("[data-action]");
    if (actionEl) {
      const action = actionEl.dataset.action;
      if (action === "team-menu") state.openMenu = state.openMenu === "team" ? null : "team";
      if (action === "season-menu") state.openMenu = state.openMenu === "season" ? null : "season";
      if (action === "toggle-league") {
        state.league = state.league === "NHL" ? "PWHL" : "NHL";
        state.selectedTeam = null;
        state.openMenu = null;
      }
      if (action === "reset") {
        state.selectedTeam = null;
        state.dateIdx = maxDateIndex();
        state.metricSort = {};
        state.openMenu = null;
      }
      if (action === "step-date") {
        state.dateIdx = clampDate(state.dateIdx + Number(actionEl.dataset.delta || 0));
        state.openMenu = null;
      }
      if (action === "slider") {
        const rect = actionEl.getBoundingClientRect();
        const rel = (event.clientX - rect.left) / Math.max(1, rect.width);
        state.dateIdx = clampDate(Math.round(rel * maxDateIndex()));
        state.openMenu = null;
      }
      if (action === "metric-sort-team") {
        state.metricSort[actionEl.dataset.metric] = "team";
      }
      if (action === "select-date") {
        state.dateIdx = clampDate(Number(actionEl.dataset.idx));
      }
      if (action === "pie-sort-team") {
        state.metricSort.__pie = "team";
      }
      if (action === "pie-sort-metric") {
        state.metricSort.__pie = actionEl.dataset.metric;
      }
      render();
      return;
    }

    const teamEl = event.target.closest("[data-team]");
    if (teamEl) {
      state.selectedTeam = teamEl.dataset.team;
      state.openMenu = null;
      render();
      return;
    }

    const seasonEl = event.target.closest("[data-season]");
    if (seasonEl) {
      state.openMenu = null;
      render();
      return;
    }

    if (!event.target.closest(".menu")) {
      state.openMenu = null;
      render();
    }
  }

  app.addEventListener("click", onClick);
  render();
}());
