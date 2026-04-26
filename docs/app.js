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
  const desktop = data.desktop || {};
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
    scoreboardDate: null,
    dateIdx: maxDateIndex(),
    modelDateIdx: maxDesktopDateIndex("points"),
    statsPhase: "regular",
    gamePhase: "regular",
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

  function desktopStats() {
    return desktop.stats || {};
  }

  function desktopModels() {
    return desktop.models || {};
  }

  function desktopTable(key) {
    return desktopStats()[key] || desktopModels()[key] || null;
  }

  function maxDesktopDateIndex(key) {
    const t = desktopTable(key);
    return Math.max(0, ((t && t.columns) || []).length - 1);
  }

  function desktopValue(key, code, idx = state.modelDateIdx) {
    const t = desktopTable(key);
    if (!t || !t.rows) return null;
    const values = t.rows[code] || [];
    const value = values[Math.max(0, Math.min(idx, values.length - 1))];
    return Number.isFinite(value) ? value : null;
  }

  function desktopCodes(key) {
    const t = desktopTable(key);
    return t && t.rows ? Object.keys(t.rows).sort() : teamCodes();
  }

  function clampDesktopDate(key, idx) {
    return Math.max(0, Math.min(maxDesktopDateIndex(key), Number(idx) || 0));
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

  function prettyLongDate(value) {
    if (!value) return "";
    const date = new Date(`${value}T00:00:00`);
    if (Number.isNaN(date.getTime())) return value;
    return `${date.getDate()} ${date.toLocaleString("en-US", { month: "long" })} ${date.getFullYear()}`;
  }

  function scoreboardDays() {
    const scoreboard = desktop.scoreboard || {};
    return Object.keys(scoreboard.days || {}).sort();
  }

  function currentScoreboardDay() {
    const scoreboard = desktop.scoreboard || {};
    const days = scoreboardDays();
    if (!days.length) return "";
    if (state.scoreboardDate && days.includes(state.scoreboardDate)) return state.scoreboardDate;
    state.scoreboardDate = scoreboard.latestDay && days.includes(scoreboard.latestDay)
      ? scoreboard.latestDay
      : days[days.length - 1];
    return state.scoreboardDate;
  }

  function clampScoreboardDay(idx) {
    const days = scoreboardDays();
    if (!days.length) return "";
    const next = days[Math.max(0, Math.min(days.length - 1, Number(idx) || 0))];
    state.scoreboardDate = next;
    return next;
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
    syncChromeLayout();
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

  function syncChromeLayout() {
    const controls = app.querySelector(".global-controls");
    const left = app.querySelector(".global-left");
    const right = app.querySelector(".global-right");
    if (!controls) return;
    const controlsHeight = Math.ceil(controls.getBoundingClientRect().height || 0);
    const leftWidth = Math.ceil(left ? left.getBoundingClientRect().width : 0);
    const rightWidth = Math.ceil(right ? right.getBoundingClientRect().width : 0);
    app.style.setProperty("--chrome-offset", `${Math.max(40, controlsHeight + 6)}px`);
    app.style.setProperty("--main-tab-left", `${Math.max(0, leftWidth + 12)}px`);
    app.style.setProperty("--main-tab-right", `${Math.max(0, rightWidth + 12)}px`);
  }

  function renderMainPage() {
    if (state.mainTab === "Scoreboard") {
      return renderScoreboardPage();
    }
    if (state.mainTab === "Stats") return renderStatsPage();
    if (state.mainTab === "Predictions") return renderPredictionsPage("predTab", "Data collected from MoneyPuck.com");
    if (state.mainTab === "Predictions 2") return renderPredictionsPage("pred2Tab", "Public NHL API model (non-MoneyPuck) | static export uses MoneyPuck data");
    return renderModelsPage();
  }

  function renderStatsPage() {
    const tabs = ["Team Stats", "Game Stats", "Player Stats", "Goal Differential", "Points"];
    const body = {
      "Team Stats": renderTeamStatsPage(),
      "Game Stats": renderGameStatsPage(),
      "Player Stats": renderPlayerStatsPage(),
      "Goal Differential": renderDesktopMetricView("goalDifferential", "Goal Differential", "number"),
      "Points": renderDesktopMetricView("points", "Points", "number"),
    }[state.statsTab] || renderComingSoon(state.statsTab, "No data.");
    return `
      <div class="nested-page">
        ${renderTabbar(tabs, state.statsTab, "stats")}
        ${body}
      </div>
    `;
  }

  function renderModelsPage() {
    const tabs = ["Playoff Picture", "Magic/Tragic", "Point Probabilities", "Playoff Win Probabilities"];
    const body = {
      "Playoff Picture": renderPlayoffPicturePage(),
      "Magic/Tragic": renderMagicTragicPage(),
      "Point Probabilities": renderPointProbabilitiesPage(),
      "Playoff Win Probabilities": renderPlayoffWinProbabilitiesPage(),
    }[state.modelsTab] || renderComingSoon(state.modelsTab, "No data.");
    return `
      <div class="nested-page">
        ${renderTabbar(tabs, state.modelsTab, "models")}
        ${body}
      </div>
    `;
  }

  function renderScoreboardPage() {
    const scoreboard = desktop.scoreboard || {};
    const days = scoreboard.days || {};
    const day = currentScoreboardDay();
    const games = day ? (days[day] || []) : [];
    if (!games.length) return renderComingSoon("Scoreboard", "No exported scoreboard data is available yet.");
    const grouped = groupScoreboardGames(games);
    return `
      <div class="scoreboard-page page-fill">
        ${renderScoreboardStepper()}
        <div class="scoreboard-date">${esc(prettyLongDate(day))}</div>
        ${grouped.map(([league, leagueGames]) => `
          <section class="scoreboard-section">
            <div class="scoreboard-section-title">${esc(league)}</div>
            <div class="scoreboard-grid">
              ${leagueGames.map(renderGameCard).join("")}
            </div>
          </section>
        `).join("")}
      </div>
    `;
  }

  function scoreboardLeagueOrder(league) {
    const value = String(league || "NHL").toUpperCase();
    if (value === "NHL") return 0;
    if (value.startsWith("OLYMPICS")) return 1;
    if (value === "PWHL") return 2;
    return 9;
  }

  function groupScoreboardGames(games) {
    const byLeague = new Map();
    games.forEach((game) => {
      const league = game.league || "NHL";
      if (!byLeague.has(league)) byLeague.set(league, []);
      byLeague.get(league).push(game);
    });
    return [...byLeague.entries()].sort((a, b) => {
      const delta = scoreboardLeagueOrder(a[0]) - scoreboardLeagueOrder(b[0]);
      return delta || String(a[0]).localeCompare(String(b[0]));
    });
  }

  function renderScoreboardStepper() {
    const days = scoreboardDays();
    const max = Math.max(0, days.length - 1);
    const idx = Math.max(0, days.indexOf(currentScoreboardDay()));
    const left = max <= 0 ? 0 : idx / max * 100;
    return `
      <div class="step-row">
        <button type="button" data-action="scoreboard-step-date" data-delta="-1">◀</button>
        <div class="slider-track" data-action="scoreboard-slider">
          <div class="slider-thumb" style="left:${left}%"></div>
        </div>
        <button type="button" data-action="scoreboard-step-date" data-delta="1">▶</button>
      </div>
    `;
  }

  function periodSuffix(value) {
    const num = Number(value);
    if (!Number.isFinite(num) || num <= 0) return "";
    if (num % 100 >= 11 && num % 100 <= 13) return `${num}TH`;
    return `${num}${{ 1: "ST", 2: "ND", 3: "RD" }[num % 10] || "TH"}`;
  }

  function scoreboardStatus(game) {
    const state = String(game.state || "").toUpperCase();
    const status = String(game.status || "").trim();
    const clock = game.clock || {};
    const period = game.periodDescriptor || {};
    const timeRemaining = String(clock.timeRemaining || clock.time || "").trim();
    const inIntermission = Boolean(clock.inIntermission);
    const periodType = String(period.periodType || "").toUpperCase().trim();
    const periodNumber = Number(period.number);

    if (state === "FINAL" || state === "OFF" || state.startsWith("FINAL")) {
      if (periodType === "OT" || periodType === "SO") return `FINAL - ${periodType}`;
      return status || "FINAL";
    }

    if (state === "LIVE" || state === "CRIT") {
      if (periodType === "OT" || periodType === "SO") {
        if (inIntermission) return `${periodType} INTERMISSION`;
        if (timeRemaining) return `${periodType} - ${timeRemaining}`;
        return periodType || status || "LIVE";
      }
      if (Number.isFinite(periodNumber) && periodNumber > 0) {
        const label = periodSuffix(periodNumber);
        if (inIntermission) return `${label} INTERMISSION`;
        if (timeRemaining) return `${label} - ${timeRemaining}`;
        return `${label} PERIOD`;
      }
      if (timeRemaining) return timeRemaining;
    }

    return status || state || "";
  }

  function scoreboardShotsLabel(team) {
    const shots = Number(team && team.shots);
    return Number.isFinite(shots) ? `SOG ${shots}` : "";
  }

  function renderGameCard(game) {
    const status = scoreboardStatus(game);
    return `
      <article class="game-card">
        <div class="game-meta"><span>${esc(game.league || "NHL")}</span><span class="game-meta-status">${esc(status)}</span></div>
        ${renderGameTeam(game.away)}
        ${renderGameTeam(game.home)}
      </article>
    `;
  }

  function renderGameTeam(team) {
    const code = team.code || "";
    const score = team.score ?? "";
    const shots = scoreboardShotsLabel(team);
    return `
      <div class="game-team" data-team="${esc(code)}">
        <img src="${esc(logo(code))}" alt="">
        <div class="game-team-main">
          <span>${esc(code)}</span>
          <span class="game-team-shots">${esc(shots)}</span>
        </div>
        <strong>${esc(score)}</strong>
      </div>
    `;
  }

  function renderPhaseButtons(phases, active, action) {
    return `<div class="phase-row">${phases.map((phase) => `
      <button class="tk-button ${phase === active ? "is-open" : ""}" data-action="${action}" data-phase="${esc(phase)}">${esc(phaseLabel(phase))}</button>
    `).join("")}</div>`;
  }

  function phaseLabel(phase) {
    return { preseason: "Preseason", regular: "Regular Season", postseason: "Postseason" }[phase] || phase;
  }

  function teamStatsRowsWithData(rows) {
    return (rows || []).filter((row) => Number(row && row.gp) > 0);
  }

  function renderTeamStatsPage() {
    const stats = desktopStats().teamStats;
    if (!stats) return renderComingSoon("Team Stats", "No exported team stats data is available yet.");
    const phases = ["preseason", "regular", "postseason"].filter((p) => stats[p]);
    if (!phases.includes(state.statsPhase)) state.statsPhase = phases[0] || "regular";
    const phase = stats[state.statsPhase] || stats[phases[0]];
    const dates = phase.dates || [];
    const day = dates[dates.length - 1];
    const rows = teamStatsRowsWithData((phase.rowsByDate || {})[day] || []).slice().sort((a, b) => Number(b.pts || 0) - Number(a.pts || 0));
    const cols = [
      ["record", "RECORD"], ["gp", "GP"], ["w", "W"], ["l", "L"], ["pts", "PTS"],
      ["gf", "GF"], ["ga", "GA"], ["gd", "GD"], ["p_pct", "P%"], ["w_pct", "W%"],
    ];
    return `
      <div class="stats-table page-fill">
        ${renderPhaseButtons(phases, state.statsPhase, "set-stats-phase")}
        <div class="table-scroll">
          <table class="tk-table wide-table">
            <thead><tr><th class="team-cell">Team</th>${cols.map(([, h]) => `<th>${esc(h)}</th>`).join("")}</tr></thead>
            <tbody>${rows.map((row) => `
              <tr>
                <td class="team-cell ${row.team === state.selectedTeam ? "selected-outline" : ""}" data-team="${esc(row.team)}">
                  <div class="team-cell-inner"><img class="team-logo" src="${esc(logo(row.team))}" alt=""><span>${esc(row.team)}</span></div>
                </td>
                ${cols.map(([key]) => renderStatCell(row[key], key, rows)).join("")}
              </tr>
            `).join("")}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderStatCell(value, key, rows) {
    if (key === "record") return `<td>${esc(value || "")}</td>`;
    const vals = rows.map((r) => Number(r[key])).filter(Number.isFinite).sort((a, b) => a - b);
    const val = Number(value);
    const rank = vals.length <= 1 || !Number.isFinite(val) ? 0.5 : vals.findIndex((v) => v >= val) / (vals.length - 1);
    const inverse = key === "l" || key === "ga";
    const bg = rankHeat(inverse ? 1 - rank : rank);
    const text = key.endsWith("_pct") && Number.isFinite(val) ? `${(val * 100).toFixed(1)}%` : value;
    return `<td style="background:${bg};color:${textForBg(bg)}">${esc(text)}</td>`;
  }

  function renderGameStatsPage() {
    const stats = desktopStats().gameStats;
    if (!stats) return renderComingSoon("Game Stats", "No exported game stats data is available yet.");
    const phases = ["preseason", "regular", "postseason"].filter((p) => stats[p]);
    if (!phases.includes(state.gamePhase)) state.gamePhase = phases[0] || "regular";
    const phase = stats[state.gamePhase] || stats[phases[0]];
    const cols = phase.date_cols || [];
    const rows = (phase.rows || []).slice().sort((a, b) => teamName(a.team).localeCompare(teamName(b.team)));
    return `
      <div class="stats-table page-fill">
        ${renderPhaseButtons(phases, state.gamePhase, "set-game-phase")}
        <div class="table-scroll">
          <table class="tk-table wide-table">
            <thead><tr><th class="team-cell">Team</th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
            <tbody>${rows.map((row) => `
              <tr>
                <td class="team-cell ${row.team === state.selectedTeam ? "selected-outline" : ""}" data-team="${esc(row.team)}">
                  <div class="team-cell-inner"><img class="team-logo" src="${esc(logo(row.team))}" alt=""><span>${esc(row.team)}</span></div>
                </td>
                ${cols.map((col) => renderOutcomeCell(row[col] || "")).join("")}
              </tr>
            `).join("")}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderOutcomeCell(value) {
    const colors = { W: "#265a2f", OTW: "#2f7040", SOW: "#2f7040", L: "#5a2727", OTL: "#5c4a28", SOL: "#5c4a28" };
    const bg = colors[value] || "#262626";
    return `<td style="background:${bg};color:#f7f7f7">${esc(value)}</td>`;
  }

  function renderPlayerStatsPage() {
    const payload = desktopStats().playerStats;
    if (!payload) return renderComingSoon("Player Stats", "No exported player stats data is available yet.");
    return `
      <div class="players-grid page-fill">
        ${renderPlayerGroup("Skaters", payload.skaters || {}, ["team", "Goals", "Assists", "Points", "Shots", "Hits", "Blocks", "+/-", "PIM"])}
        ${renderPlayerGroup("Goalies", payload.goalies || {}, ["team", "Wins", "Losses", "OTL", "Save %", "Shutouts", "Saves", "Games Started", "GAA"])}
      </div>
    `;
  }

  function renderPlayerGroup(title, rowsObj, cols) {
    const rows = Object.entries(rowsObj).sort((a, b) => Number(b[1].Points || b[1].Wins || 0) - Number(a[1].Points || a[1].Wins || 0)).slice(0, 30);
    return `
      <section class="player-panel">
        <h2>${esc(title)}</h2>
        <div class="table-scroll">
          <table class="tk-table wide-table">
            <thead><tr><th>Player</th>${cols.map((c) => `<th>${esc(c)}</th>`).join("")}</tr></thead>
            <tbody>${rows.map(([name, row]) => `
              <tr>
                <td>${esc(name)}</td>
                ${cols.map((c) => c === "team" ? `<td data-team="${esc(row.team)}">${esc(row.team || "")}</td>` : `<td>${esc(formatPlayerValue(c, row[c]))}</td>`).join("")}
              </tr>
            `).join("")}</tbody>
          </table>
        </div>
      </section>
    `;
  }

  function formatPlayerValue(key, value) {
    const num = Number(value);
    if (!Number.isFinite(num)) return value || "";
    if (key === "Save %") return num.toFixed(3);
    if (key === "GAA") return num.toFixed(2);
    return Number.isInteger(num) ? String(num) : num.toFixed(1);
  }

  function renderDesktopMetricView(key, title, valueKind) {
    const payload = desktopTable(key);
    if (!payload) return renderComingSoon(title, `No exported ${title} data is available yet.`);
    const rows = desktopCodes(key).sort((a, b) => (desktopValue(key, b, clampDesktopDate(key, state.dateIdx)) ?? -999) - (desktopValue(key, a, clampDesktopDate(key, state.dateIdx)) ?? -999));
    return renderGenericMetricView(payload, key, title, valueKind, rows, clampDesktopDate(key, state.dateIdx));
  }

  function renderGenericMetricView(payload, key, title, valueKind, rows, idx) {
    return `
      <div class="metric-view">
        <div class="metric-top">
          <div class="heatmap-wrap">${renderGenericHeatmap(payload, key, rows, idx, valueKind)}</div>
          <div class="bar-wrap">${renderGenericBars(payload, key, rows, idx, valueKind)}</div>
        </div>
        <div class="metric-bottom">
          <div class="graph-wrap">${renderGenericLineGraph(payload, key, rows, idx, valueKind)}</div>
          <div>
            <div class="metric-title">${esc(title)}</div>
            <div class="logos-wrap">${renderLogoGrid(rows)}</div>
          </div>
        </div>
        ${renderDesktopStepper(key, idx)}
      </div>
    `;
  }

  function genericValue(payload, code, idx) {
    const values = (payload.rows || {})[code] || [];
    const value = values[Math.max(0, Math.min(idx, values.length - 1))];
    return Number.isFinite(value) ? value : null;
  }

  function formatGeneric(value, valueKind) {
    if (!Number.isFinite(value)) return "";
    if (valueKind === "percent") return pct(value);
    return Number.isInteger(value) ? String(value) : value.toFixed(1);
  }

  function rankHeat(rank) {
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
    return blend(rgbToHex(Math.round(r * 0.56), Math.round(g * 0.56), Math.round(b * 0.56)), "#262626", 0.12);
  }

  function genericHeat(payload, code, idx, allowNegative = false) {
    const vals = Object.keys(payload.rows || {})
      .map((c) => genericValue(payload, c, idx))
      .filter(Number.isFinite)
      .sort((a, b) => a - b);
    const val = genericValue(payload, code, idx);
    if (!Number.isFinite(val) || !vals.length) return "#262626";
    if (allowNegative) {
      const min = vals[0];
      const max = vals[vals.length - 1];
      const t = max === min ? 0.5 : (val - min) / (max - min);
      return rankHeat(t);
    }
    const rank = vals.length === 1 ? 0.5 : vals.findIndex((v) => v >= val) / (vals.length - 1);
    return rankHeat(rank);
  }

  function renderGenericHeatmap(payload, key, rows, selectedIdx, valueKind) {
    const cols = payload.columns || [];
    const allowNegative = key === "goalDifferential";
    return `
      <table class="tk-table">
        <thead>
          <tr><th class="team-cell">Team</th>${cols.map((col, idx) => `<th data-action="select-desktop-date" data-metric="${esc(key)}" data-idx="${idx}">${esc(col)}</th>`).join("")}</tr>
        </thead>
        <tbody>${rows.map((code) => `
          <tr>
            <td class="team-cell ${code === state.selectedTeam ? "selected-outline" : ""}" data-team="${esc(code)}">
              <div class="team-cell-inner"><img class="team-logo" src="${esc(logo(code))}" alt=""><span>${esc(code)}</span></div>
            </td>
            ${cols.map((_, idx) => {
              const bg = genericHeat(payload, code, idx, allowNegative);
              const cls = idx === selectedIdx ? "selected-outline" : "";
              return `<td class="${cls}" style="background:${bg};color:${textForBg(bg)}">${esc(formatGeneric(genericValue(payload, code, idx), valueKind))}</td>`;
            }).join("")}
          </tr>
        `).join("")}</tbody>
      </table>
    `;
  }

  function renderGenericBars(payload, key, rows, idx, valueKind) {
    const vals = rows.map((code) => genericValue(payload, code, idx)).filter(Number.isFinite);
    const min = key === "goalDifferential" ? Math.min(0, ...vals) : 0;
    const max = Math.max(1, ...vals);
    return `
      <table class="tk-table" style="width:100%"><thead><tr><th>${esc((payload.columns || [])[idx] || "")}</th></tr></thead></table>
      <div style="padding:0 8px">
        ${rows.map((code) => {
          const value = genericValue(payload, code, idx) || 0;
          const width = Math.max(1, (value - min) / Math.max(1, max - min) * 100);
          const c0 = blend(teamColor(code), "#262626", state.selectedTeam && state.selectedTeam !== code ? 0.7 : 0.35);
          const c1 = blend(teamColor(code), "#ffffff", state.selectedTeam && state.selectedTeam !== code ? 0.72 : 0.45);
          return `<div class="bar-row" data-team="${esc(code)}"><div class="bar-track"><div class="bar-fill" style="width:${width}%;background:linear-gradient(90deg,${c0},${c1})"></div></div><div class="bar-value">${esc(formatGeneric(value, valueKind))}</div></div>`;
        }).join("")}
      </div>
    `;
  }

  function renderGenericLineGraph(payload, key, rows, selectedIdx, valueKind) {
    const cols = payload.columns || [];
    const width = Math.max(800, cols.length * 8);
    const height = 310;
    const pad = { left: 54, right: 18, top: 16, bottom: 34 };
    const allVals = rows.flatMap((code) => ((payload.rows || {})[code] || []).filter(Number.isFinite));
    const min = key === "goalDifferential" ? Math.min(0, ...allVals) : 0;
    const max = Math.max(1, ...allVals);
    const xFor = (i) => pad.left + i / Math.max(1, cols.length - 1) * (width - pad.left - pad.right);
    const yFor = (v) => pad.top + (1 - ((v - min) / Math.max(1, max - min))) * (height - pad.top - pad.bottom);
    const ticks = [min, (min + max) / 2, max];
    const grid = ticks.map((tick) => {
      const y = yFor(tick);
      return `<line class="chart-grid" x1="${pad.left}" y1="${y}" x2="${width - pad.right}" y2="${y}"></line><text class="chart-axis" x="${pad.left - 8}" y="${y + 4}" text-anchor="end">${esc(formatGeneric(tick, valueKind))}</text>`;
    }).join("");
    const lines = rows.map((code) => {
      const values = (payload.rows || {})[code] || [];
      const points = values.map((v, idx) => `${idx === 0 ? "M" : "L"} ${xFor(idx).toFixed(1)} ${yFor(Number.isFinite(v) ? v : min).toFixed(1)}`).join(" ");
      const color = state.selectedTeam && state.selectedTeam !== code ? blend(teamColor(code), "#262626", 0.65) : teamColor(code);
      return `<path class="line-path ${state.selectedTeam === code ? "is-selected" : ""}" d="${points}" stroke="${esc(color)}" data-team="${esc(code)}"></path>`;
    }).join("");
    const dateX = xFor(selectedIdx);
    return `<svg class="chart-svg" viewBox="0 0 ${width} ${height}" preserveAspectRatio="none">${grid}<line class="chart-grid" x1="${dateX}" y1="${pad.top}" x2="${dateX}" y2="${height - pad.bottom}" stroke="#6a6a6a" stroke-width="2"></line>${lines}</svg>`;
  }

  function pointsPayload() {
    return desktopModels().points || desktopStats().points;
  }

  function modelDayLabel() {
    const p = pointsPayload();
    return p ? (p.columns || [])[state.modelDateIdx] || "" : "";
  }

  function pointsSnapshot() {
    const p = pointsPayload();
    if (!p) return {};
    const out = {};
    Object.keys(p.rows || {}).forEach((code) => {
      out[code] = genericValue(p, code, state.modelDateIdx) || 0;
    });
    return out;
  }

  function currentModelDay() {
    const label = modelDayLabel();
    if (label) return label;
    const scoreboard = desktop.scoreboard || {};
    return scoreboard.latestDay || "";
  }

  function latestTeamStatMap() {
    const stats = desktopModels().teamStats || desktopStats().teamStats;
    const regular = stats && (stats.regular || stats.postseason || stats.preseason);
    if (!regular) return {};
    const dates = regular.dates || [];
    const day = dates[Math.min(dates.length - 1, state.modelDateIdx)] || dates[dates.length - 1];
    const rows = ((regular.rowsByDate || {})[day] || []);
    return Object.fromEntries(rows.map((r) => [r.team, r]));
  }

  function sortedByPoints(codes, pts) {
    return codes.slice().sort((a, b) => (pts[b] || 0) - (pts[a] || 0) || teamName(a).localeCompare(teamName(b)));
  }

  function playoffColumns(pts) {
    const out = { Pacific: [], Central: [], Atlantic: [], Metro: [], WestWC: [], EastWC: [] };
    divisions.forEach((div) => {
      out[div] = sortedByPoints(teamCodes().filter((c) => (byCode.get(c) || {}).division === div), pts);
    });
    const westTaken = new Set([...out.Pacific.slice(0, 3), ...out.Central.slice(0, 3)]);
    const eastTaken = new Set([...out.Atlantic.slice(0, 3), ...out.Metro.slice(0, 3)]);
    const west = sortedByPoints(teamCodes().filter((c) => (byCode.get(c) || {}).conference === "West"), pts);
    const east = sortedByPoints(teamCodes().filter((c) => (byCode.get(c) || {}).conference === "East"), pts);
    out.WestWC = west.filter((c) => !westTaken.has(c));
    out.EastWC = east.filter((c) => !eastTaken.has(c));
    return out;
  }

  function conferenceBracketTeams(pts, firstDiv, secondDiv, wcKey) {
    const cols = playoffColumns(pts);
    const first = cols[firstDiv] || [];
    const second = cols[secondDiv] || [];
    const wildcards = cols[wcKey] || [];
    const betterWildcard = wildcards[0] || "";
    const lesserWildcard = wildcards[1] || "";
    const divisionWinners = [first[0], second[0]].filter(Boolean);
    const bestWinner = sortedByPoints(divisionWinners, pts)[0] || "";
    const firstWinner = first[0] || "";
    const secondWinner = second[0] || "";
    const firstWildcard = firstWinner && firstWinner === bestWinner ? lesserWildcard : betterWildcard;
    const secondWildcard = secondWinner && secondWinner === bestWinner ? lesserWildcard : betterWildcard;
    return [
      firstWinner, firstWildcard, first[1], first[2],
      secondWinner, secondWildcard, second[1], second[2],
    ].filter(Boolean);
  }

  function bracketTeams(pts) {
    return [
      ...conferenceBracketTeams(pts, "Pacific", "Central", "WestWC"),
      ...conferenceBracketTeams(pts, "Atlantic", "Metro", "EastWC"),
    ];
  }

  function isFinalState(stateValue) {
    const value = String(stateValue || "").toUpperCase();
    return value === "FINAL" || value === "OFF" || value.startsWith("FINAL");
  }

  function isNhlPlayoffGame(game) {
    if (!game || String(game.league || "").toUpperCase() !== "NHL") return false;
    const gameType = String(game.gameType || "").toUpperCase();
    const gid = String(game.id || "");
    return gameType === "3" || gameType === "P" || gid.startsWith("202503");
  }

  function playoffSeriesScoresByDay(day) {
    const targetDay = day || currentModelDay();
    if (!targetDay) return {};
    const scoreboard = desktop.scoreboard || {};
    const days = Object.keys(scoreboard.days || {}).sort();
    const out = {};
    days.forEach((iso) => {
      if (iso > targetDay) return;
      (scoreboard.days[iso] || []).forEach((game) => {
        if (!isNhlPlayoffGame(game) || !isFinalState(game.state)) return;
        const away = String((game.away || {}).code || "").toUpperCase();
        const home = String((game.home || {}).code || "").toUpperCase();
        const awayScore = Number((game.away || {}).score);
        const homeScore = Number((game.home || {}).score);
        if (!away || !home || !Number.isFinite(awayScore) || !Number.isFinite(homeScore) || awayScore === homeScore) return;
        const key = [away, home].sort().join("|");
        if (!out[key]) out[key] = { [away]: 0, [home]: 0 };
        if (!Object.prototype.hasOwnProperty.call(out[key], away)) out[key][away] = 0;
        if (!Object.prototype.hasOwnProperty.call(out[key], home)) out[key][home] = 0;
        const winner = awayScore > homeScore ? away : home;
        out[key][winner] = Number(out[key][winner] || 0) + 1;
      });
    });
    return out;
  }

  function renderModelStepper() {
    const p = pointsPayload();
    const max = Math.max(0, ((p && p.columns) || []).length - 1);
    const left = max <= 0 ? 0 : state.modelDateIdx / max * 100;
    return `
      <div class="step-row">
        <button type="button" data-action="model-step-date" data-delta="-1">◀</button>
        <div class="slider-track" data-action="model-slider"><div class="slider-thumb" style="left:${left}%"></div></div>
        <button type="button" data-action="model-step-date" data-delta="1">▶</button>
      </div>
    `;
  }

  function pickBracketWinner(a, b, pts) {
    if (!a && !b) return "";
    if (a && !b) return a;
    if (b && !a) return b;
    return pickBracketWinnerWithScores(a, b, pts, {});
  }

  function seriesWins(a, b, seriesScores) {
    if (!a || !b) return [0, 0];
    const key = [a, b].sort().join("|");
    const wins = (seriesScores && seriesScores[key]) || {};
    return [Number(wins[a] || 0), Number(wins[b] || 0)];
  }

  function pickBracketWinnerWithScores(a, b, pts, seriesScores) {
    if (!a && !b) return "";
    if (a && !b) return a;
    if (b && !a) return b;
    const [aWins, bWins] = seriesWins(a, b, seriesScores);
    if (aWins >= 4 || bWins >= 4) {
      if (aWins === bWins) return String(a) <= String(b) ? a : b;
      return aWins > bWins ? a : b;
    }
    if ((aWins + bWins) > 0) return "";
    const pa = Number(pts[a] || 0);
    const pb = Number(pts[b] || 0);
    if (pa === pb) return String(a) <= String(b) ? a : b;
    return pa > pb ? a : b;
  }

  function buildConferenceBracket(teams, pts, seriesScores) {
    const seeded = Array.from({ length: 8 }, (_, idx) => teams[idx] || "");
    const round1 = [];
    for (let i = 0; i < seeded.length; i += 2) {
      round1.push([seeded[i], seeded[i + 1]]);
    }
    const round2 = [
      [pickBracketWinnerWithScores(...round1[0], pts, seriesScores), pickBracketWinnerWithScores(...round1[1], pts, seriesScores)],
      [pickBracketWinnerWithScores(...round1[2], pts, seriesScores), pickBracketWinnerWithScores(...round1[3], pts, seriesScores)],
    ];
    const final = [pickBracketWinnerWithScores(...round2[0], pts, seriesScores), pickBracketWinnerWithScores(...round2[1], pts, seriesScores)];
    return {
      round1,
      round2,
      final,
      champion: pickBracketWinnerWithScores(final[0], final[1], pts, seriesScores),
    };
  }

  function renderStandingRow(code, pts, extraClass = "") {
    const classes = ["standing-row"];
    if (extraClass) classes.push(extraClass);
    if (!code) {
      classes.push("is-empty");
      return `<div class="${classes.join(" ")}"></div>`;
    }
    return `<div class="${classes.join(" ")}" data-team="${esc(code)}"><img src="${esc(logo(code))}" alt=""><span>${esc(code)}</span><strong>${esc(pts[code] || 0)}</strong></div>`;
  }

  function renderLeagueStandingsPanel(pts) {
    const rows = sortedByPoints(teamCodes(), pts);
    return `
      <section class="league-standings-panel">
        <h3>League</h3>
        <div class="league-standings-list">
          ${rows.map((code) => renderStandingRow(code, pts, "is-league")).join("")}
        </div>
      </section>
    `;
  }

  function renderWildcardBoard(cols, pts) {
    const wildcardDepth = Math.max(2, cols.WestWC.length, cols.EastWC.length);
    return `
      <section class="wildcard-board">
        <div class="wildcard-board-title">Wildcard</div>
        <div class="wildcard-board-grid">
          ${divisions.map((div) => `<div class="wildcard-head">${esc(div)}</div>`).join("")}
          ${Array.from({ length: 3 }, (_, rowIdx) => divisions.map((div) => (
            renderStandingRow((cols[div] || [])[rowIdx] || "", pts, "is-wildcard")
          )).join("")).join("")}
          <div class="wildcard-spanner">West WC</div>
          <div class="wildcard-spanner">East WC</div>
          ${Array.from({ length: wildcardDepth }, (_, rowIdx) => `
            <div class="wildcard-span-cell">${renderStandingRow((cols.WestWC || [])[rowIdx] || "", pts, "is-wildcard")}</div>
            <div class="wildcard-span-cell">${renderStandingRow((cols.EastWC || [])[rowIdx] || "", pts, "is-wildcard")}</div>
          `).join("")}
        </div>
      </section>
    `;
  }

  function renderBracketTeamLine(code, pts, wins, winner) {
    if (!code) return '<div class="bracket-team-line is-empty"></div>';
    const winValue = Object.keys(wins || {}).length ? Number(wins[code] || 0) : "";
    return `
      <div class="bracket-team-line ${winner === code ? "is-predicted" : ""}" data-team="${esc(code)}">
        <img src="${esc(logo(code))}" alt="">
        <span>${esc(code)}</span>
        <span class="series-win">${esc(winValue)}</span>
        <strong class="series-points">${esc(pts[code] || 0)}</strong>
      </div>
    `;
  }

  function renderBracketSeriesCard(a, b, pts, seriesScores, kind = "") {
    const codes = [a, b].filter(Boolean).sort();
    const wins = codes.length === 2 ? (seriesScores[codes.join("|")] || {}) : {};
    const winner = pickBracketWinnerWithScores(a, b, pts, seriesScores);
    return `
      <article class="bracket-series ${esc(kind)} ${!a && !b ? "is-empty" : ""}">
        ${renderBracketTeamLine(a, pts, wins, winner)}
        ${renderBracketTeamLine(b, pts, wins, winner)}
      </article>
    `;
  }

  function renderConferenceBracket(title, bracket, pts, seriesScores, side) {
    return `
      <section class="conference-bracket is-${esc(side)}">
        <div class="conference-title">${esc(title)}</div>
        <div class="conference-round round-one">
          <div class="round-label">Round 1</div>
          <div class="round-stack">
            ${bracket.round1.map(([a, b]) => renderBracketSeriesCard(a, b, pts, seriesScores, "is-round-one")).join("")}
          </div>
        </div>
        <div class="conference-round round-two">
          <div class="round-label">Round 2</div>
          <div class="round-stack">
            ${bracket.round2.map(([a, b]) => renderBracketSeriesCard(a, b, pts, seriesScores, "is-round-two")).join("")}
          </div>
        </div>
        <div class="conference-round round-three">
          <div class="round-label">Conference Final</div>
          <div class="round-stack">
            ${renderBracketSeriesCard(bracket.final[0], bracket.final[1], pts, seriesScores, "is-round-three")}
          </div>
        </div>
      </section>
    `;
  }

  function renderCupColumn(westChampion, eastChampion, pts, seriesScores) {
    const winner = pickBracketWinnerWithScores(westChampion, eastChampion, pts, seriesScores);
    return `
      <section class="cup-column">
        <div class="round-label">Stanley Cup Final</div>
        ${renderBracketSeriesCard(westChampion, eastChampion, pts, seriesScores, "cup-series")}
        <div class="cup-image-wrap">
          <img class="cup-image" src="assets/stanley_cup.png" alt="">
        </div>
        <div class="cup-winner-wrap">
          <div class="cup-winner-label">Projected Winner</div>
          ${renderBracketSeriesCard(winner, "", pts, {}, "cup-winner")}
        </div>
      </section>
    `;
  }

  function renderPlayoffPicturePage() {
    const p = pointsPayload();
    if (!p) return renderComingSoon("Playoff Picture", "No exported points history data is available yet.");
    const pts = pointsSnapshot();
    const cols = playoffColumns(pts);
    const seriesScores = playoffSeriesScoresByDay(currentModelDay());
    const westBracket = buildConferenceBracket(conferenceBracketTeams(pts, "Pacific", "Central", "WestWC"), pts, seriesScores);
    const eastBracket = buildConferenceBracket(conferenceBracketTeams(pts, "Atlantic", "Metro", "EastWC"), pts, seriesScores);
    return `
      <div class="model-page page-fill playoff-page">
        ${renderModelStepper()}
        <div class="model-date">${esc(modelDayLabel())}</div>
        <div class="playoff-shell">
          <section class="playoff-stage">
            <div class="playoff-stage-header">Standings</div>
            <div class="playoff-stage-body">
              ${renderLeagueStandingsPanel(pts)}
              ${renderWildcardBoard(cols, pts)}
            </div>
          </section>
          <section class="bracket-stage">
            <div class="bracket-stage-header">
              <span>Bracket</span>
              <span class="bracket-mode-pill">NHL (Divisional)</span>
            </div>
            <div class="conference-grid">
              ${renderConferenceBracket("West", westBracket, pts, seriesScores, "west")}
              ${renderCupColumn(westBracket.champion, eastBracket.champion, pts, seriesScores)}
              ${renderConferenceBracket("East", eastBracket, pts, seriesScores, "east")}
            </div>
          </section>
        </div>
      </div>
    `;
  }

  function renderMagicTragicPage() {
    const p = pointsPayload();
    if (!p) return renderComingSoon("Magic/Tragic", "No exported points history data is available yet.");
    const pts = pointsSnapshot();
    const stats = latestTeamStatMap();
    const rows = sortedByPoints(teamCodes(), pts);
    const eastCut = sortedByPoints(rows.filter((c) => (byCode.get(c) || {}).conference === "East"), pts)[8] || "";
    const westCut = sortedByPoints(rows.filter((c) => (byCode.get(c) || {}).conference === "West"), pts)[8] || "";
    return `
      <div class="model-page page-fill">
        ${renderModelStepper()}
        <div class="model-date">Magic/Tragic - ${esc(modelDayLabel())}</div>
        <div class="table-scroll">
          <table class="tk-table wide-table">
            <thead><tr><th class="team-cell">Team</th><th>PTS</th><th>GR</th><th>MAX</th><th>Playoff Magic</th><th>Elim Tragic</th></tr></thead>
            <tbody>${rows.map((code) => {
              const row = stats[code] || {};
              const gr = Number(row.gr ?? Math.max(0, 82 - Number(row.gp || 0)));
              const maxPts = Number(row.mxp ?? ((pts[code] || 0) + gr * 2));
              const cutTeam = (byCode.get(code) || {}).conference === "East" ? eastCut : westCut;
              const cut = cutTeam ? (pts[cutTeam] || 0) : 0;
              const magic = Math.max(0, Math.ceil((cut + 1 - (pts[code] || 0)) / 2));
              const tragic = maxPts < cut + 1 ? "X" : Math.max(0, Math.ceil((maxPts - cut) / 2));
              return `<tr><td class="team-cell" data-team="${esc(code)}"><div class="team-cell-inner"><img class="team-logo" src="${esc(logo(code))}" alt=""><span>${esc(code)}</span></div></td><td>${esc(pts[code] || 0)}</td><td>${esc(gr)}</td><td>${esc(maxPts)}</td><td>${esc(magic === 0 ? "*" : magic)}</td><td>${esc(tragic)}</td></tr>`;
            }).join("")}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderPointProbabilitiesPage() {
    const p = pointsPayload();
    if (!p) return renderComingSoon("Point Probabilities", "No exported points history data is available yet.");
    const pts = pointsSnapshot();
    const stats = latestTeamStatMap();
    const rows = sortedByPoints(teamCodes(), pts);
    const totals = [...new Set(rows.flatMap((code) => {
      const gr = Number((stats[code] || {}).gr ?? 0);
      const cur = Number(pts[code] || 0);
      return [cur, cur + Math.ceil(gr), cur + gr * 2];
    }))].sort((a, b) => a - b).slice(-28);
    return `
      <div class="model-page page-fill">
        ${renderModelStepper()}
        <div class="model-date">Point Probabilities - ${esc(modelDayLabel())}</div>
        <div class="table-scroll">
          <table class="tk-table wide-table">
            <thead><tr><th class="team-cell">Team</th>${totals.map((n) => `<th>${esc(n)}</th>`).join("")}</tr></thead>
            <tbody>${rows.map((code) => {
              const gr = Number((stats[code] || {}).gr ?? 0);
              const cur = Number(pts[code] || 0);
              const center = cur + gr;
              return `<tr><td class="team-cell" data-team="${esc(code)}"><div class="team-cell-inner"><img class="team-logo" src="${esc(logo(code))}" alt=""><span>${esc(code)}</span></div></td>${totals.map((n) => {
                const prob = Math.max(0, 1 - Math.abs(n - center) / Math.max(1, gr * 2));
                const bg = rankHeat(prob);
                return `<td style="background:${bg};color:${textForBg(bg)}">${prob > 0 ? esc((prob * 100).toFixed(1) + "%") : ""}</td>`;
              }).join("")}</tr>`;
            }).join("")}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function renderPlayoffWinProbabilitiesPage() {
    const p = pointsPayload();
    if (!p) return renderComingSoon("Playoff Win Probabilities", "No exported points history data is available yet.");
    const pts = pointsSnapshot();
    const seriesScores = playoffSeriesScoresByDay(currentModelDay());
    const pairs = [];
    const teams = bracketTeams(pts);
    for (let i = 0; i < teams.length; i += 2) if (teams[i] && teams[i + 1]) pairs.push([teams[i], teams[i + 1]]);
    return `
      <div class="model-page page-fill">
        <div class="model-date">Playoff Win Probabilities - ${esc(modelDayLabel())}</div>
        <div class="table-scroll">
          <table class="tk-table wide-table">
            <thead><tr><th>Series</th><th>Team</th><th>in 4</th><th>in 5</th><th>in 6</th><th>in 7</th><th>Prediction</th></tr></thead>
            <tbody>${pairs.map(([a, b]) => renderSeriesRows(a, b, pts, seriesScores)).join("")}</tbody>
          </table>
        </div>
      </div>
    `;
  }

  function seriesProb(a, b, pts) {
    const d = ((pts[a] || 0) - (pts[b] || 0)) / 8;
    return Math.max(0.08, Math.min(0.92, 1 / (1 + Math.exp(-d))));
  }

  function lengthProbsFromScore(p, winsFor, winsAgainst) {
    const clamped = Math.max(0.001, Math.min(0.999, Number(p) || 0));
    const q = 1 - clamped;
    const wf = Math.max(0, Number(winsFor) || 0);
    const wa = Math.max(0, Number(winsAgainst) || 0);
    const played = wf + wa;
    if (wf >= 4) return [4, 5, 6, 7].map((total) => (total === played ? 1 : 0));
    if (wa >= 4) return [0, 0, 0, 0];
    const out = [];
    const winsNeeded = 4 - wf;
    for (let totalGames = 4; totalGames <= 7; totalGames += 1) {
      const remainingGames = totalGames - played;
      if (remainingGames < winsNeeded || remainingGames <= 0) {
        out.push(0);
        continue;
      }
      const oppFutureWins = remainingGames - winsNeeded;
      if (wa + oppFutureWins >= 4) {
        out.push(0);
        continue;
      }
      const beforeFinal = remainingGames - 1;
      const neededBeforeFinal = winsNeeded - 1;
      if (beforeFinal < neededBeforeFinal || neededBeforeFinal < 0) {
        out.push(0);
        continue;
      }
      out.push(nCr(beforeFinal, neededBeforeFinal) * (clamped ** winsNeeded) * (q ** oppFutureWins));
    }
    return out;
  }

  function nCr(n, r) {
    if (r < 0 || r > n) return 0;
    let out = 1;
    const k = Math.min(r, n - r);
    for (let i = 1; i <= k; i += 1) out = out * (n - k + i) / i;
    return out;
  }

  function renderSeriesRows(a, b, pts, seriesScores) {
    const pa = seriesProb(a, b, pts);
    const wins = seriesScores[[a, b].sort().join("|")] || {};
    const aWins = Number(wins[a] || 0);
    const bWins = Number(wins[b] || 0);
    const av = lengthProbsFromScore(pa, aWins, bWins);
    const bv = lengthProbsFromScore(1 - pa, bWins, aWins);
    const aTotal = av.reduce((sum, value) => sum + value, 0);
    const bTotal = bv.reduce((sum, value) => sum + value, 0);
    const predTeam = aTotal >= bTotal ? a : b;
    const predVals = predTeam === a ? av : bv;
    const predText = `${predTeam} in ${4 + predVals.indexOf(Math.max(...predVals))}`;
    const cells = (vals) => vals.map((v) => {
      const impossible = v <= 0;
      const styles = impossible
        ? ' style="background:#353535;color:#9a9a9a"'
        : "";
      return `<td${styles}>${esc((v * 100).toFixed(2) + "%")}</td>`;
    }).join("");
    return `
      <tr><td rowspan="2">${esc(a)} vs ${esc(b)}</td><td data-team="${esc(a)}">${esc(a)}</td>${cells(av)}<td rowspan="2">${esc(predText)}</td></tr>
      <tr><td data-team="${esc(b)}">${esc(b)}</td>${cells(bv)}</tr>
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

  function renderDesktopStepper(key, idx) {
    const max = maxDesktopDateIndex(key);
    const left = max <= 0 ? 0 : idx / max * 100;
    return `
      <div class="step-row">
        <button type="button" data-action="desktop-step-date" data-metric="${esc(key)}" data-delta="-1">◀</button>
        <div class="slider-track" data-action="desktop-slider" data-metric="${esc(key)}">
          <div class="slider-thumb" style="left:${left}%"></div>
        </div>
        <button type="button" data-action="desktop-step-date" data-metric="${esc(key)}" data-delta="1">▶</button>
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
      if (scope === "stats" && label === "Points") state.dateIdx = clampDesktopDate("points", state.dateIdx);
      if (scope === "stats" && label === "Goal Differential") state.dateIdx = clampDesktopDate("goalDifferential", state.dateIdx);
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
        state.scoreboardDate = null;
        state.dateIdx = maxDateIndex();
        state.modelDateIdx = maxDesktopDateIndex("points");
        state.metricSort = {};
        state.openMenu = null;
      }
      if (action === "scoreboard-step-date") {
        const days = scoreboardDays();
        const idx = Math.max(0, days.indexOf(currentScoreboardDay()));
        clampScoreboardDay(idx + Number(actionEl.dataset.delta || 0));
        state.openMenu = null;
      }
      if (action === "scoreboard-slider") {
        const days = scoreboardDays();
        const rect = actionEl.getBoundingClientRect();
        const rel = (event.clientX - rect.left) / Math.max(1, rect.width);
        clampScoreboardDay(Math.round(rel * Math.max(0, days.length - 1)));
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
      if (action === "select-desktop-date") {
        const metric = actionEl.dataset.metric || "points";
        state.dateIdx = clampDesktopDate(metric, Number(actionEl.dataset.idx));
      }
      if (action === "desktop-step-date") {
        const metric = actionEl.dataset.metric || "points";
        state.dateIdx = clampDesktopDate(metric, state.dateIdx + Number(actionEl.dataset.delta || 0));
        state.openMenu = null;
      }
      if (action === "desktop-slider") {
        const metric = actionEl.dataset.metric || "points";
        const rect = actionEl.getBoundingClientRect();
        const rel = (event.clientX - rect.left) / Math.max(1, rect.width);
        state.dateIdx = clampDesktopDate(metric, Math.round(rel * maxDesktopDateIndex(metric)));
        state.openMenu = null;
      }
      if (action === "model-step-date") {
        state.modelDateIdx = clampDesktopDate("points", state.modelDateIdx + Number(actionEl.dataset.delta || 0));
        state.openMenu = null;
      }
      if (action === "model-slider") {
        const rect = actionEl.getBoundingClientRect();
        const rel = (event.clientX - rect.left) / Math.max(1, rect.width);
        state.modelDateIdx = clampDesktopDate("points", Math.round(rel * maxDesktopDateIndex("points")));
        state.openMenu = null;
      }
      if (action === "set-stats-phase") {
        state.statsPhase = actionEl.dataset.phase || state.statsPhase;
      }
      if (action === "set-game-phase") {
        state.gamePhase = actionEl.dataset.phase || state.gamePhase;
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
  window.addEventListener("resize", syncChromeLayout);
  render();
}());
