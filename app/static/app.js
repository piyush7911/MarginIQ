const getEl = (id) => document.getElementById(id);

const appShell = getEl("app-shell");
const runButton = getEl("run-button");
const runButtonLabel = getEl("run-button-label");
const backButton = getEl("back-button");

let selectedScenarioKey = null;
let selectedScenarioTitle = null;

const recommendationTitle = getEl("recommendation-title");
const recommendationBody = getEl("recommendation-body");

let latestResponse = null;

function titleCase(value) {
  return value
    .replace(/_/g, " ")
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function formatMetricValue(value) {
  if (typeof value === "number") {
    return Number.isInteger(value) ? `${value}` : value.toFixed(2);
  }
  return value;
}

function getAgentStatus(agent) {
  const status = agent.metrics?.status;
  if (status === "error") return "error";
  if (agent.score < 0.3) return "risk";
  return "ok";
}

function getNodeTone(status) {
  if (status === "error") return "error";
  if (status === "risk") return "warning";
  if (status === "ok") return "positive";
  return "neutral";
}

function showResultsView() {
  appShell.classList.add("show-results");
}

function showLandingView() {
  appShell.classList.remove("show-results");
}

function updateSummary(response) {
  latestResponse = response;
  const title = getEl("recommendation-title");
  const body = getEl("recommendation-body");
  const conf = getEl("confidence-value");
  const exec = getEl("execution-id");
  const ring = document.querySelector(".confidence-ring");

  const rec = response.optimization?.recommended_discount;
  const decidedBy = response.optimization?.decided_by;
  if (title) title.textContent = rec !== undefined ? `Recommend a ${rec}% discount` : response.recommendation;

  if (body) {
    const factors = response.optimization?.decision_factors || [];
    const grounding = response.verification?.grounding_source;
    const factorsHtml = factors.length
      ? `<ul class="factor-list">${factors.map((f) => `<li>${f}</li>`).join("")}</ul>`
      : `<p>${response.recommendation}</p>`;
    const badge = grounding ? `<span class="grounding-badge">✓ policy grounded by ${grounding}</span>` : "";
    const owner = decidedBy ? `<span class="grounding-badge" style="color:#7B1FA2;background:#F3E5F5;border-color:#CE93D8;">decided by ${decidedBy}</span>` : "";
    body.innerHTML = factorsHtml + `<div style="display:flex;gap:8px;flex-wrap:wrap;">${badge}${owner}</div>`;
  }
  // Color-code confidence by level so the (now calibrated) value reads at a glance.
  const c = response.confidence || 0;
  const color = c >= 0.7 ? "#2E7D32" : c >= 0.4 ? "#E68A00" : "#C62828";
  if (conf) {
    conf.textContent = `${Math.round(c * 100)}%`;
    conf.style.color = color;
  }
  if (exec) exec.textContent = `Execution ID: ${response.execution_id}`;
  if (ring) ring.style.background = `radial-gradient(circle at center, #fffdf9 56%, transparent 57%), conic-gradient(${color} ${c * 360}deg, #e5ddd0 0deg)`;
}

function renderMetrics(response) {
  const grid = getEl("metrics-grid");
  if (!grid) return;
  const m = response.metrics || {};
  const o = response.optimization || {};
  const usd = (n) => `$${Math.round(n).toLocaleString()}`;

  // Aligned to the RECOMMENDED decision so the snapshot is consistent with the
  // recommendation and the scenario table (no candidate-vs-recommended mismatch).
  const items = [
    ["Recommended Discount", `${o.recommended_discount}%`],
    ["Expected Profit", usd(o.expected_profit)],
    ["Downside Risk", `${Math.round((o.downside_risk || 0) * 100)}%`],
    ["Inventory Risk", titleCase(m.inventory_risk || "low")],
    ["Cannibalization", titleCase(m.cannibalization_risk || "low")],
    ["Timing Score", formatMetricValue(m.timing_score)],
  ];

  grid.innerHTML = items
    .map(
      ([label, value]) => `
        <div class="metric-tile">
          <span class="mini-label">${label}</span>
          <strong>${value}</strong>
        </div>
      `
    )
    .join("");
}

function renderDebate(debateSummary) {
  const list = getEl("debate-list");
  if (list) {
    list.innerHTML = debateSummary.map((item) => `<div class="debate-item">${item}</div>`).join("");
  }
}

function renderScenarios(scenarios) {
  const table = getEl("scenario-table");
  if (!table) return;

  const best = scenarios.reduce((a, b) => (b.weighted_score > a.weighted_score ? b : a), scenarios[0]);
  const fmt = (n) => `$${Math.round(n).toLocaleString()}`;
  const header = `
    <div class="scenario-row scenario-head">
      <span>Disc.</span><span>Profit</span><span>Downside</span><span>Risk</span><span>Score</span>
    </div>`;
  const rows = scenarios
    .map(
      (scenario) => `
        <div class="scenario-row${scenario.discount === best.discount ? " scenario-best" : ""}">
          <strong>${scenario.discount}%</strong>
          <span>${fmt(scenario.expected_profit)}</span>
          <span>${Math.round(scenario.downside_risk * 100)}%</span>
          <span>${scenario.risk_outlook}</span>
          <span class="scenario-score">${scenario.weighted_score}</span>
        </div>`
    )
    .join("");
  const foot = `<div class="scenario-foot">Best of ${scenarios.length} simulated discounts · 300 Monte-Carlo samples each</div>`;
  table.innerHTML = header + rows + foot;
}

function renderGraph(agentInsights) {
  // Render Agent Swarm
  const agentsBoard = getEl("graph-board-agents");
  if (!agentsBoard) return;

  const agentStage = `
    <div class="graph-stage agent-stage">
      ${agentInsights
        .map((agent) => {
          const status = getAgentStatus(agent);
          const tone = getNodeTone(status);
          const isError = status === "error";
          
          if (isError) {
            return `
              <div class="graph-node active ${tone}">
                <div class="graph-node-label">${agent.agent}</div>
                <div class="graph-node-detail">
                  <div class="error-status-pill">Configuration Error</div>
                  <div class="graph-node-insight">${agent.summary}</div>
                </div>
              </div>
            `;
          }

          // Show only compact, numeric/short metrics as pills — drop long prose
          // fields (e.g. explanation, recommended_stance) that overflow the chip.
          const longFields = new Set(["explanation", "recommended_stance", "narrative_line", "summary", "stance"]);
          const metricsHtml = Object.entries(agent.metrics || {})
            .filter(([key, value]) =>
              value !== null && value !== "" && typeof value !== "object" &&
              !longFields.has(key) && !(typeof value === "string" && value.length > 18)
            )
            .map(([key, value]) => `
              <div class="node-metric-pill">
                <span>${titleCase(key)}</span>
                ${formatMetricValue(value)}
              </div>
            `)
            .join("");

          return `
            <div class="graph-node active ${tone}">
              <div class="graph-node-label">${agent.agent}</div>
              <div class="graph-node-meta">
                <span>${Math.round(agent.confidence * 100)}% Confidence</span>
              </div>
              <div class="graph-node-detail">
                <div class="graph-node-insight">${agent.summary}</div>
                <div class="graph-node-metrics">
                  ${metricsHtml}
                </div>
              </div>
            </div>
          `;
        })
        .join("")}
    </div>
  `;

  agentsBoard.innerHTML = agentStage;
}

function renderResponse(data) {
  updateSummary(data);
  renderMetrics(data);
  renderGraph(data.agent_insights);
  renderScenarios(data.scenarios);
  renderDebate(data.debate_summary);
  showResultsView();
}

function showAnalysisError(message) {
  if (recommendationTitle) recommendationTitle.textContent = "Analysis failed";
  if (recommendationBody) recommendationBody.textContent = message;
  showResultsView();
}

function selectScenario(key, title, btn) {
  selectedScenarioKey = key;
  selectedScenarioTitle = title;
  document.querySelectorAll(".scenario-chip").forEach((b) => b.classList.remove("selected"));
  if (btn) btn.classList.add("selected");
  if (runButton) runButton.disabled = false;
  if (runButtonLabel) runButtonLabel.textContent = `Run “${title}”`;
}

async function loadScenarioButtons() {
  const board = getEl("scenario-buttons");
  if (!board) return;
  try {
    const response = await fetch("/api/v1/scenarios");
    const { scenarios } = await response.json();
    board.innerHTML = scenarios
      .map(
        (s) => `
        <button class="scenario-chip" type="button" data-key="${s.key}" data-title="${s.title}" title="${s.summary}">
          <span class="chip-key">${s.key} · expect: ${s.expectation.split("—")[0].trim()}</span>
          <span class="chip-title">${s.title}</span>
          <span class="chip-expect">${s.expectation}</span>
        </button>`
      )
      .join("");
    board.querySelectorAll(".scenario-chip").forEach((btn) => {
      btn.addEventListener("click", () => selectScenario(btn.dataset.key, btn.dataset.title, btn));
    });
  } catch (error) {
    board.innerHTML = `<p class="mini-label-light">Could not load scenarios: ${error.message}</p>`;
  }
}

// Cycle pipeline stage labels in the loading overlay so the wait is informative.
const LOADING_STAGES = [
  "Ingesting & featurizing…",
  "Running core math agents…",
  "Selecting & running LLM experts…",
  "Monte-Carlo optimizing across discounts…",
  "Debating bull vs bear…",
  "Critic verifying against Foundry IQ policy…",
  "Arbiter finalizing the call…",
  "Writing the recommendation…",
];
let loadingTimer = null;

function startLoading() {
  const overlay = getEl("loading-overlay");
  const stage = getEl("loading-stage");
  if (!overlay) return;
  overlay.hidden = false;
  let i = 0;
  if (stage) stage.textContent = LOADING_STAGES[0];
  loadingTimer = setInterval(() => {
    i = (i + 1) % LOADING_STAGES.length;
    if (stage) stage.textContent = LOADING_STAGES[i];
  }, 1600);
}

function stopLoading() {
  const overlay = getEl("loading-overlay");
  if (overlay) overlay.hidden = true;
  if (loadingTimer) clearInterval(loadingTimer);
  loadingTimer = null;
}

async function runSelectedScenario() {
  if (!selectedScenarioKey) return;
  runButton.disabled = true;
  startLoading();
  try {
    const response = await fetch(`/api/v1/scenarios/${selectedScenarioKey}/analyze`, { method: "POST" });
    if (!response.ok) throw new Error(`Request failed with status ${response.status}`);
    renderResponse(await response.json());
  } catch (error) {
    showAnalysisError(error.message);
  } finally {
    stopLoading();
    runButton.disabled = false;
  }
}

async function bootstrap() {
  await loadScenarioButtons();
  if (runButton) runButton.addEventListener("click", runSelectedScenario);
  if (backButton) backButton.addEventListener("click", showLandingView);
}

bootstrap();
