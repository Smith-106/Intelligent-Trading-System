const state = {
  overview: null,
  dataHub: null,
  executionHub: null,
  monitoring: null,
  strategies: [],
  strategyMap: {},
  selectedStrategyId: null,
  strategyFilters: {
    search: "",
    timeframe: "all",
    symbol: "all",
  },
  session: null,
  terminalDraft: {
    mode: "paper",
    symbol: "BTC/USDT",
    timeframe: "1h",
    interval_seconds: 30,
    capital: 100000,
    strategies: [],
    dirty: false,
  },
  executionDraftMeta: {
    sourceType: "manual",
    sourceLabel: "手动草稿",
    sourcePanel: "execution",
    sourceRecordId: null,
    sourceSessionId: null,
    sourceStrategy: null,
    sourceSymbol: null,
    dataSource: null,
    dataMode: null,
    dataContextTitle: null,
    dataContextMessage: null,
    validationLabel: null,
    validationTone: "muted",
    validationReason: null,
    validationMethod: null,
    sourceTrail: [],
    edited: false,
  },
  latestResearchResult: null,
  latestValidationResult: null,
  pendingResearchSource: null,
  pendingValidationSource: null,
  researchContextMap: {},
  validationContextMap: {},
  researchHistory: [],
  validationHistory: [],
  researchView: {
    historyRecordId: null,
  },
  validationView: {
    historyRecordId: null,
  },
  sessionHistory: [],
  sessionEvents: [],
  liveSessionSnapshot: null,
  sessionView: {
    mode: "live",
    historyRecordId: null,
    historySessionId: null,
    pinLiveWhenIdle: false,
  },
  sessionAudit: {
    kind: null,
    key: null,
  },
  researchParams: {},
  validationParams: {},
  researchChart: {
    payload: null,
    start: 0,
    end: 0,
    secondaryMode: "equity",
    hoverIndex: null,
    drag: null,
  },
  sessionChart: {
    mode: "portfolio",
    hoverIndex: null,
  },
  executionChart: {
    mode: "portfolio",
    hoverIndex: null,
  },
  executionEventFilter: "all",
  executionInspector: {
    kind: null,
    key: null,
  },
  dataInspector: {
    kind: null,
    key: null,
  },
  monitoringInspector: {
    kind: null,
    key: null,
  },
  overviewInspector: {
    kind: null,
    key: null,
  },
  sessionEventFilter: "all",
  activePanel: "overview",
  dataDownloadState: {
    status: "idle",
    message: "尚未开始下载历史行情。",
  },
};

const refreshState = {
  runtimePromise: null,
  fullPromise: null,
  pollHandle: null,
  stalled: false, // M5: one-shot toast debounce for poll stall streaks
};

const WORKBENCH_STATE_STORAGE_KEY = "quantflow.station.workbench.v1";
const WORKBENCH_STATE_ENDPOINT = "/api/workbench/state";
let restoredWorkbenchState = null;
let lastPersistedWorkbenchState = "";
let lastSyncedWorkbenchState = "";
let workbenchPersistHandle = null;
let suspendWorkbenchPersistence = false;

const panels = {
  overview: document.getElementById("panel-overview"),
  data: document.getElementById("panel-data"),
  monitoring: document.getElementById("panel-monitoring"),
  research: document.getElementById("panel-research"),
  validation: document.getElementById("panel-validation"),
  execution: document.getElementById("panel-execution"),
  session: document.getElementById("panel-session"),
  strategies: document.getElementById("panel-strategies"),
};

const researchChartNodes = {
  stage: document.getElementById("research-chart-stage"),
  main: document.getElementById("research-candles"),
  secondary: document.getElementById("research-secondary"),
  tooltip: document.getElementById("research-chart-tooltip"),
  empty: document.getElementById("research-chart-empty"),
  legend: document.getElementById("research-chart-legend"),
  summary: document.getElementById("research-chart-summary"),
};

const sessionChartNodes = {
  stage: document.getElementById("session-telemetry-stage"),
  canvas: document.getElementById("session-telemetry-chart"),
  tooltip: document.getElementById("session-telemetry-tooltip"),
  empty: document.getElementById("session-telemetry-empty"),
  legend: document.getElementById("session-telemetry-legend"),
};

const executionChartNodes = {
  stage: document.getElementById("execution-telemetry-stage"),
  canvas: document.getElementById("execution-telemetry-chart"),
  tooltip: document.getElementById("execution-telemetry-tooltip"),
  empty: document.getElementById("execution-telemetry-empty"),
  legend: document.getElementById("execution-telemetry-legend"),
};

const panelChromeMeta = {
  overview: {
    label: "总览",
    context: "用总览页统一协调数据、研究、验证、执行和实时会话。",
    workbenchTitle: "统一交易平台",
    workbenchText: "把当前平台状态压缩成下一步最明确的业务动作。",
    actions: [
      { action: "open-session", label: "打开交易会话", primary: true },
      { action: "open-monitoring", label: "打开监控页" },
    ],
  },
  data: {
    label: "数据中心",
    context: "先准备好数据底座，再把交易对推入研究、验证或执行草稿。",
    workbenchTitle: "数据准备工作台",
    workbenchText: "在推进交易流程时，持续把来源质量、覆盖范围和下一步去向放在眼前。",
    actions: [
      { action: "focus-research", label: "进入研究页", primary: true },
      { action: "open-validation", label: "打开验证页" },
    ],
  },
  monitoring: {
    label: "监控运维",
    context: "在推进业务流程前，先确认服务可达性、活跃告警和最新业务快照。",
    workbenchTitle: "运营控制层",
    workbenchText: "把监控视为平台真实状态的来源，用它决定放行姿态和运行安全。",
    actions: [
      { action: "open-session", label: "打开交易会话", primary: true },
      { action: "open-validation", label: "复核验证结果" },
    ],
  },
  research: {
    label: "研究回测",
    context: "运行回测、查看最近研究，并把可用分析结果继续送往验证或执行草稿。",
    workbenchTitle: "研究推进层",
    workbenchText: "研究结果必须继续流向验证门禁和执行工作台，而不是停在单页里。",
    actions: [
      { action: "open-validation", label: "打开验证页", primary: true },
      { action: "research-stage-execution", label: "送入执行草稿" },
    ],
  },
  validation: {
    label: "验证门禁",
    context: "在把策略推进到执行演练前，先审阅 CPCV、DSR、WFO 等门禁证据。",
    workbenchTitle: "放行门禁层",
    workbenchText: "验证页必须直接影响执行准备度和启动决策。",
    actions: [
      { action: "validation-stage-execution", label: "送入执行草稿", primary: true },
      { action: "open-execution", label: "打开执行工作台" },
    ],
  },
  execution: {
    label: "执行工作台",
    context: "在同一个业务面板里管理执行草稿、运行终端、启动审阅和执行事件流。",
    workbenchTitle: "执行控制层",
    workbenchText: "在启动或重跑交易终端前，持续看清运行状态、草稿准备度和验证姿态。",
    actions: [
      { action: "open-session", label: "打开交易会话", primary: true },
      { action: "open-monitoring", label: "打开监控页" },
    ],
  },
  session: {
    label: "交易会话",
    context: "查看实时遥测、持仓、订单和会话历史，确认执行闭环是否按预期运转。",
    workbenchTitle: "实时会话层",
    workbenchText: "把交易会话视为执行、风控和组合遥测已经真正打通的最终证据。",
    actions: [
      { action: "open-execution", label: "打开执行工作台", primary: true },
      { action: "open-monitoring", label: "打开监控页" },
    ],
  },
  strategies: {
    label: "策略目录",
    context: "在不丢失配置上下文的前提下，把策略定义继续送往研究、验证和执行。",
    workbenchTitle: "策略工作区",
    workbenchText: "把策略目录当作业务流程入口，而不是静态目录页。",
    actions: [
      { action: "focus-research", label: "进入研究页", primary: true },
      { action: "open-execution", label: "打开执行工作台" },
    ],
  },
};

const RESEARCH_RANGE_PRESETS = ["48", "96", "180", "360", "all"];
const SESSION_CHART_PADDING = { top: 18, right: 18, bottom: 22, left: 56 };

function sessionViewIsHistory() {
  return state.sessionView?.mode === "history";
}

function setResearchView(record = null) {
  state.researchView = {
    historyRecordId: record?.record_id || null,
  };
  persistWorkbenchState();
}

function setValidationView(record = null) {
  state.validationView = {
    historyRecordId: record?.record_id || null,
  };
  persistWorkbenchState();
}

function isActiveResearchHistoryRecord(item = {}) {
  return Boolean(state.researchView?.historyRecordId) && item.record_id === state.researchView.historyRecordId;
}

function isActiveValidationHistoryRecord(item = {}) {
  return Boolean(state.validationView?.historyRecordId) && item.record_id === state.validationView.historyRecordId;
}

function normalizeSourceTrailItem(item = {}) {
  if (!item || typeof item !== "object") {
    return null;
  }
  const panel = safeText(item.panel || item.sourcePanel, "");
  const label = safeText(item.label || item.sourceLabel, "");
  const recordId = item.recordId || item.sourceRecordId || null;
  const sessionId = item.sessionId || item.sourceSessionId || null;
  const strategyId = item.strategyId || item.sourceStrategy || null;
  const symbol = item.symbol || item.sourceSymbol || null;
  const dataSource = item.dataSource ?? null;

  if (!panel && !label && !recordId && !sessionId && !strategyId && !symbol && !dataSource) {
    return null;
  }

  return {
    panel: panel || "execution",
    label,
    recordId,
    sessionId,
    strategyId,
    symbol,
    dataSource,
  };
}

function normalizeSourceContext(context = null) {
  if (!context || typeof context !== "object") {
    return null;
  }
  const primary = normalizeSourceTrailItem(context);
  const trail = Array.isArray(context.trail)
    ? context.trail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
    : [];

  if (!primary && !trail.length) {
    return null;
  }

  return {
    ...(primary || {
      panel: "execution",
      label: "",
      recordId: null,
      sessionId: null,
      strategyId: null,
      symbol: null,
      dataSource: null,
    }),
    trail,
  };
}

function setPendingResearchSource(context = null) {
  state.pendingResearchSource = normalizeSourceContext(context);
  return state.pendingResearchSource;
}

function setPendingValidationSource(context = null) {
  state.pendingValidationSource = normalizeSourceContext(context);
  return state.pendingValidationSource;
}

function rememberSourceContext(map, recordId, context = null) {
  if (!recordId) {
    return null;
  }
  const normalized = normalizeSourceContext(context);
  if (!normalized) {
    delete map[recordId];
    persistWorkbenchState();
    return null;
  }
  map[recordId] = normalized;
  persistWorkbenchState();
  return normalized;
}

function rememberResearchSourceContext(recordId, context = null) {
  return rememberSourceContext(state.researchContextMap, recordId, context ?? state.pendingResearchSource);
}

function rememberValidationSourceContext(recordId, context = null) {
  return rememberSourceContext(state.validationContextMap, recordId, context ?? state.pendingValidationSource);
}

function researchSourceContextForRecord(record = {}) {
  return normalizeSourceContext(
    state.researchContextMap[record.record_id]
      || state.researchContextMap[record.history_record?.record_id]
      || null,
  );
}

function validationSourceContextForRecord(record = {}) {
  return normalizeSourceContext(
    state.validationContextMap[record.record_id]
      || state.validationContextMap[record.history_record?.record_id]
      || null,
  );
}

function sourceTrailFromContext(context = null) {
  const normalized = normalizeSourceContext(context);
  if (!normalized) {
    return [];
  }
  return [
    {
      panel: normalized.panel,
      label: normalized.label,
      recordId: normalized.recordId,
      sessionId: normalized.sessionId,
      strategyId: normalized.strategyId,
      symbol: normalized.symbol,
      dataSource: normalized.dataSource,
    },
    ...normalized.trail,
  ];
}

function sourceContextLabel(item = {}) {
  const normalized = normalizeSourceTrailItem(item);
  if (!normalized) {
    return "";
  }
  if (normalized.label) {
    return normalized.label;
  }
  if (normalized.panel === "strategies" && normalized.strategyId) {
    return `策略目录 / ${localizeStrategyTitle(normalized.strategyId, normalized.strategyId)}`;
  }
  if (normalized.panel === "data" && normalized.symbol) {
    return `数据中心 / ${normalized.symbol}`;
  }
  if (normalized.panel === "research") {
    return normalized.symbol ? `研究记录 / ${normalized.symbol}` : "研究记录";
  }
  if (normalized.panel === "validation") {
    return normalized.symbol ? `验证记录 / ${normalized.symbol}` : "验证记录";
  }
  if (normalized.panel === "session") {
    return normalized.sessionId ? `会话记录 / ${normalized.sessionId}` : "会话记录";
  }
  return executionSourceAction({ sourcePanel: normalized.panel }).panelLabel;
}

function openSourceContext(context = null, sourceLabel = "来源") {
  const normalized = normalizeSourceTrailItem(context);
  if (!normalized) {
    return false;
  }

  if (normalized.panel === "research" && normalized.recordId) {
    const record = state.researchHistory.find((item) => item.record_id === normalized.recordId);
    if (record) {
      openResearchRecord(record, sourceLabel);
      return true;
    }
  }
  if (normalized.panel === "validation" && normalized.recordId) {
    const record = state.validationHistory.find((item) => item.record_id === normalized.recordId);
    if (record) {
      openValidationRecord(record, sourceLabel);
      return true;
    }
  }
  if (normalized.panel === "session" && (normalized.recordId || normalized.sessionId)) {
    const record = state.sessionHistory.find(
      (item) => item.record_id === normalized.recordId || item.session_id === normalized.sessionId,
    );
    if (record) {
      void openSessionHistoryRecord(record);
      return true;
    }
  }
  if (normalized.panel === "strategies" && normalized.strategyId) {
    focusStrategyDirectoryItem(normalized.strategyId);
    showPanel("strategies");
    return true;
  }
  if (normalized.panel === "data" && normalized.symbol) {
    showPanel("data");
    focusDataSymbolCoverage(normalized.symbol);
    return true;
  }

  const action = executionSourceAction({ sourcePanel: normalized.panel });
  if (!action) {
    return false;
  }
  if (action.formId) {
    focusPanelWorkspace(action.panel, action.formId);
    return true;
  }
  showPanel(action.panel);
  return true;
}

function strategyDirectorySourceContext(strategyId, symbol = null) {
  const normalizedStrategyId = safeText(strategyId, "");
  if (!normalizedStrategyId) {
    return null;
  }
  return normalizeSourceContext({
    panel: "strategies",
    label: `策略目录 / ${localizeStrategyTitle(normalizedStrategyId, normalizedStrategyId)}`,
    strategyId: normalizedStrategyId,
    symbol: symbol || null,
  });
}

function dataWorkspaceSourceContext(symbol, dataSource = null) {
  const normalizedSymbol = safeText(symbol, "");
  if (!normalizedSymbol) {
    return null;
  }
  return normalizeSourceContext({
    panel: "data",
    label: `数据中心 / ${normalizedSymbol}`,
    symbol: normalizedSymbol,
    dataSource,
  });
}

function researchRecordSourceContext(payload = {}, fallbackLabel = "研究记录") {
  const request = payload.request || {};
  const recordId = historyRecordIdOf(payload);
  const upstream = researchSourceContextForRecord({
    record_id: recordId,
    history_record: payload.history_record,
  });
  return normalizeSourceContext({
    panel: "research",
    label: request.symbol ? `${fallbackLabel} / ${request.symbol}` : fallbackLabel,
    recordId,
    strategyId: request.strategy || null,
    symbol: request.symbol || null,
    dataSource: payload.data_source ?? null,
    trail: sourceTrailFromContext(upstream),
  });
}

function validationRecordSourceContext(payload = {}, fallbackLabel = "验证记录") {
  const request = payload.request || {};
  const recordId = historyRecordIdOf(payload);
  const upstream = validationSourceContextForRecord({
    record_id: recordId,
    history_record: payload.history_record,
  });
  return normalizeSourceContext({
    panel: "validation",
    label: request.symbol ? `${fallbackLabel} / ${request.symbol}` : fallbackLabel,
    recordId,
    strategyId: request.strategy || null,
    symbol: request.symbol || null,
    dataSource: payload.data_source ?? null,
    trail: sourceTrailFromContext(upstream),
  });
}

function scrollHistoryCardIntoView(containerId, recordId) {
  if (!containerId || !recordId) {
    return;
  }
  requestAnimationFrame(() => {
    const card = document.querySelector(`#${containerId} [data-history-record-id="${recordId}"]`);
    card?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

function scrollElementIntoView(selector) {
  if (!selector) {
    return;
  }
  requestAnimationFrame(() => {
    document.querySelector(selector)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

function focusStrategyDirectoryItem(strategyId) {
  if (!strategyId || !state.strategyMap[strategyId]) {
    return;
  }
  selectStrategy(strategyId);
  scrollElementIntoView(`[data-strategy-select="${strategyId}"]`);
}

function focusDataSymbolCoverage(symbol) {
  if (!symbol) {
    return;
  }
  const selectors = [
    `#data-symbol-rows [data-symbol="${symbol}"]`,
    `#data-workflow-actions [data-symbol="${symbol}"]`,
    `#data-leader-grid [data-symbol="${symbol}"]`,
  ];
  requestAnimationFrame(() => {
    const node = selectors
      .map((selector) => document.querySelector(selector))
      .find(Boolean);
    node?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  });
}

function setSessionView(mode, record = null, options = {}) {
  const previous = state.sessionView || {};
  let nextView;
  if (mode === "history" && record) {
    nextView = {
      mode: "history",
      historyRecordId: record.record_id || null,
      historySessionId: record.session_id || null,
      pinLiveWhenIdle: false,
    };
  } else {
    const pinLiveWhenIdle = options.pinLiveWhenIdle === undefined
      ? Boolean(previous.pinLiveWhenIdle)
      : Boolean(options.pinLiveWhenIdle);
    nextView = {
      mode: "live",
      historyRecordId: null,
      historySessionId: null,
      pinLiveWhenIdle,
    };
  }
  const changed = previous.mode !== nextView.mode
    || previous.historyRecordId !== nextView.historyRecordId
    || previous.historySessionId !== nextView.historySessionId
    || Boolean(previous.pinLiveWhenIdle) !== Boolean(nextView.pinLiveWhenIdle);
  state.sessionView = nextView;
  if (changed) {
    state.sessionAudit = sessionAuditSelection();
  }
  persistWorkbenchState();
}

function isActiveSessionHistoryRecord(item = {}) {
  if (!sessionViewIsHistory()) {
    return false;
  }
  if (state.sessionView.historyRecordId && item.record_id) {
    return item.record_id === state.sessionView.historyRecordId;
  }
  return Boolean(state.sessionView.historySessionId) && item.session_id === state.sessionView.historySessionId;
}

function latestSessionHistoryRecord() {
  return Array.isArray(state.sessionHistory) && state.sessionHistory.length
    ? state.sessionHistory[0]
    : null;
}

function shouldDefaultToLatestSessionHistory(snapshot = state.liveSessionSnapshot || state.session || {}) {
  return !sessionViewIsHistory()
    && !Boolean(state.sessionView?.pinLiveWhenIdle)
    && !Boolean(snapshot?.session_id)
    && Boolean(latestSessionHistoryRecord());
}

function renderSessionViewControls() {
  const returnButton = document.getElementById("session-return-live");
  const pill = document.getElementById("session-view-pill");
  if (sessionViewIsHistory()) {
    returnButton.classList.remove("hidden");
    pill.className = pillToneClass("warning");
    pill.textContent = "历史回看";
    return;
  }
  returnButton.classList.add("hidden");
  pill.className = pillToneClass("accent");
  pill.textContent = "实时";
}

function showPanel(panelName) {
  const panel = panels[panelName];
  if (!panel) {
    return;
  }
  state.activePanel = panelName;

  document.querySelectorAll(".nav-btn").forEach((button) => {
    const isActive = button.dataset.panel === panelName;
    button.classList.toggle("active", isActive);
    if (isActive) {
      button.setAttribute("aria-current", "page");
    } else {
      button.removeAttribute("aria-current");
    }
  });
  Object.entries(panels).forEach(([name, node]) => {
    node.classList.toggle("active", name === panelName);
  });

  if (panelName === "research") {
    requestAnimationFrame(() => renderResearchChart());
  }
  if (panelName === "session") {
    requestAnimationFrame(() => renderSessionTelemetryChart());
  }
  refreshPlatformChrome();
  persistWorkbenchState();
}

document.querySelectorAll(".nav-btn").forEach((button) => {
  button.addEventListener("click", () => showPanel(button.dataset.panel));
});

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const rawText = await response.text();
  let payload = null;
  if (rawText) {
    try {
      payload = JSON.parse(rawText);
    } catch {
      payload = { rawText };
    }
  }
  if (!response.ok) {
    throw new Error(
      payload?.error
      || payload?.message
      || payload?.rawText
      || `Request failed (${response.status})`,
    );
  }
  return payload;
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#39;");
}

// setHTML: single audit-face choke point for assigning HTML to a node (M4).
// Mirrors the validate_symbol single-audit-face discipline: every innerHTML
// assignment should go through here so static guards can grep for raw
// `.innerHTML =` outside this function body. Callers MUST pre-escape any
// interpolated server/user text via escapeHtml/safeText/localizeInlineText —
// setHTML does NOT auto-escape (that would require HTML parsing).
function setHTML(node, html) {
  if (!node) return;
  node.innerHTML = html;
}

// Sync a toggle button's aria-pressed with its active class so screen readers
// announce selection state (WCAG 4.1.2 / toggle pattern). The two must never
// drift — always set both via this helper instead of raw classList.toggle.
function setSegmentPressed(button, isActive) {
  if (!button) {
    return;
  }
  button.classList.toggle("active", isActive);
  button.setAttribute("aria-pressed", isActive ? "true" : "false");
}

// ---------------------------------------------------------------------------
// UI Odyssey (2026-07-22) — feedback primitives: toast, spinner, in-flight
// guard, polling heartbeat. Additive; no existing call sites changed.
// ---------------------------------------------------------------------------

function ensureToastStack() {
  let stack = document.querySelector(".toast-stack");
  if (!stack) {
    stack = document.createElement("div");
    stack.className = "toast-stack";
    stack.setAttribute("role", "status");
    stack.setAttribute("aria-live", "polite");
    stack.setAttribute("aria-atomic", "false");
    document.body.appendChild(stack);
  }
  return stack;
}

function showToast(message, tone = "info", ttl = 3800) {
  const stack = ensureToastStack();
  const toast = document.createElement("div");
  toast.className = `toast tone-${tone}`;
  toast.textContent = safeText(message, "");
  stack.appendChild(toast);
  const dismiss = () => {
    toast.classList.add("leaving");
    window.setTimeout(() => toast.remove(), 160);
  };
  window.setTimeout(dismiss, ttl);
  toast.addEventListener("click", dismiss);
  return toast;
}

// Disable a control while async work is in flight and show an inline spinner.
// Returns a restore() callback. Safe to call on non-button elements.
function withInFlight(node, label) {
  if (!node) {
    return () => {};
  }
  const tag = node.tagName.toLowerCase();
  const isButton = tag === "button";
  let original = null;
  if (isButton) {
    original = { disabled: node.disabled, html: node.innerHTML };
    node.disabled = true;
    node.innerHTML = `<span class="btn-spinner"></span>${escapeHtml(safeText(label, "处理中"))}`;
  } else {
    node.setAttribute("data-inflight", "1");
    node.style.opacity = "0.6";
    node.style.pointerEvents = "none";
  }
  return () => {
    if (isButton) {
      node.disabled = original.disabled;
      node.innerHTML = original.html;
    } else {
      node.removeAttribute("data-inflight");
      node.style.opacity = "";
      node.style.pointerEvents = "";
    }
  };
}

// Hold-to-confirm for destructive actions (Kill Switch). Returns true only
// if the user held for the full duration.
function holdToConfirm(node, { duration = 1200, message = "按住以确认" } = {}) {
  return new Promise((resolve) => {
    if (!node) {
      resolve(false);
      return;
    }
    let held = false;
    let timer = null;
    const restore = withInFlight(node, message);
    const arm = () => {
      held = false;
      node.classList.add("hold-confirm", "holding");
      timer = window.setTimeout(() => {
        held = true;
        release();
      }, duration);
    };
    const release = () => {
      if (timer) {
        window.clearTimeout(timer);
        timer = null;
      }
      node.classList.remove("hold-confirm", "holding");
      restore();
      node.removeEventListener("pointerup", release);
      node.removeEventListener("pointerleave", release);
      node.removeEventListener("blur", release);
      resolve(held);
    };
    node.addEventListener("pointerup", release, { once: true });
    node.addEventListener("pointerleave", release, { once: true });
    node.addEventListener("blur", release, { once: true });
    arm();
  });
}

// Polling heartbeat — toggles stalled state when refresh throws.
function setPollHeartbeat(stalled) {
  const node = document.querySelector(".poll-heartbeat");
  if (!node) {
    return;
  }
  node.classList.toggle("stalled", !!stalled);
  node.textContent = stalled ? "刷新暂停" : "实时";
}

function ensurePollHeartbeat() {
  let node = document.querySelector(".poll-heartbeat");
  if (!node) {
    node = document.createElement("span");
    node.className = "poll-heartbeat";
    node.setAttribute("role", "status");
    node.setAttribute("aria-live", "polite");
    node.textContent = "实时";
    const target = document.getElementById("topbar-panel-pill");
    if (target && target.parentElement) {
      target.parentElement.appendChild(node);
    } else {
      document.body.appendChild(node);
    }
  }
  return node;
}

function metricCard(label, value) {
  let display;
  if (typeof value === "number") {
    // Guard NaN/Infinity — render placeholder rather than literal "NaN"/"Infinity".
    display = Number.isFinite(value) ? value : "待检测";
  } else if (typeof value === "string") {
    display = escapeHtml(localizeInlineText(value, value)); // M4: escape string branch
  } else if (value === null || value === undefined) {
    display = "待检测";
  } else {
    display = escapeHtml(String(value));
  }
  const safeLabel = escapeHtml(localizeInlineText(label, label)); // M4: escape label
  return `<div class="metric-card"><span class="label">${safeLabel}</span><span class="value">${display}</span></div>`;
}

function safeText(value, fallback = "N/A") {
  return value === null || value === undefined || value === "" ? fallback : value;
}

function localizeUiText(value, fallback = "N/A") {
  const text = safeText(value, fallback);
  const normalized = String(text).trim().toLowerCase();
  const mapping = {
    "n/a": "待检测",
    overview: "总览",
    data: "数据",
    "data hub": "数据中心",
    monitoring: "监控运维",
    research: "研究回测",
    validation: "验证门禁",
    execution: "执行工作台",
    session: "交易会话",
    strategies: "策略目录",
    "paper-ready": "纸面可运行",
    "not validated": "未验证",
    running: "运行中",
    stopped: "已停止",
    idle: "待机",
    ready: "就绪",
    unknown: "待检测",
    healthy: "健康",
    incident: "告警",
    degraded: "降级",
    warning: "注意",
    info: "信息",
    error: "错误",
    critical: "严重",
    "execution online": "执行在线",
    "attempt failed": "启动失败",
    unavailable: "不可达",
    attempted: "已尝试",
    "in-process": "进程内",
    registry: "指标注册",
    active: "已触发",
    armed: "已就绪",
    "within limits": "正常",
    triggered: "已触发",
    "manual draft": "手动草稿",
    "source unknown": "来源待确认",
    blocked: "已阻断",
    revalidate: "待复核",
    review: "待审阅",
    attention: "需关注",
    stable: "稳定",
    enabled: "已启用",
    disabled: "已禁用",
    missing: "缺失",
    none: "无",
    system: "系统",
    service: "服务",
    signal: "信号",
    order: "订单",
    fill: "成交",
    risk: "风控",
    event: "事件",
    lifecycle: "生命周期",
    backtest: "回测",
    paper: "模拟盘",
    sandbox: "沙盒",
    live: "实盘",
    buy: "买入",
    sell: "卖出",
    long: "多头",
    short: "空头",
    flat: "空仓",
    filled: "已成交",
    open: "挂单中",
    pending: "待处理",
    submitted: "已提交",
    cancelled: "已取消",
    rejected: "已拒绝",
    failed: "失败",
    success: "成功",
    go: "通过",
    "no-go": "不通过",
    "no go": "不通过",
    mixed: "需复核",
    yes: "是",
    no: "否",
    pass: "通过",
    fail: "失败",
    market: "市价",
    limit: "限价",
    stop: "止损",
    stop_market: "止损市价",
    stop_limit: "止损限价",
    take_profit: "止盈",
    "strategy workspace": "策略工作区",
    "strategy id": "策略 ID",
    "config path": "配置路径",
    "default symbol": "默认交易对",
    timeframe: "周期",
    "primary params": "核心参数",
    "param space": "参数空间",
    "exit rules": "退出规则",
    "risk rules": "风控规则",
    symbols: "交易对",
    "avg params": "平均参数",
    "risk ready": "风控就绪",
    configured: "已配置",
    tunable: "可调参数",
    keys: "个字段",
    metric: "指标",
    precision: "精确率",
    recall: "召回率",
    "oos sharpe": "样本外 Sharpe",
    signals: "信号数",
    "primary metric": "主指标",
    "signal quality": "信号质量",
    "gate outcome": "门禁结论",
    decision: "结论",
    paths: "路径数",
    optimized: "已优化",
    "cpcv quality": "CPCV 质量",
    "backtest snapshot": "回测快照",
    "execution quality": "执行质量",
    "total return": "总收益率",
    "max drawdown": "最大回撤",
    "final capital": "最终资金",
    "backtest evidence": "回测证据",
    "backtest kpi table": "回测 KPI 表",
    "overfit risk": "过拟合风险",
    "overfitting breakdown": "过拟合拆解",
    "return spread": "收益分布",
    "pbo signal": "PBO 信号",
    "gate breakdown": "门禁拆解",
    "path breakdown": "路径拆解",
    "window breakdown": "窗口拆解",
    "rolling windows": "滚动窗口",
    "anchored windows": "锚定窗口",
    "check matrix": "检查矩阵",
    check: "检查项",
    status: "状态",
    "signal intake": "信号接入",
    "order routing": "订单路由",
    "fill confirmation": "成交确认",
    "risk controls": "风控护栏",
    "open orders": "挂单数",
    "order events": "订单事件",
    "pending notional": "待成交名义金额",
    "open positions": "持仓数",
    upnl: "未实现盈亏",
    "gross notional": "总名义金额",
    latest: "最新时间",
    "visible events": "可见事件",
    "order id": "订单 ID",
    direction: "方向",
    strength: "强度",
    quantity: "数量",
    price: "价格",
    type: "类型",
    reason: "原因",
    source: "来源",
    session: "会话",
    "equity curve": "权益曲线",
    "drawdown curve": "回撤曲线",
    equity: "权益",
    drawdown: "回撤",
    volume: "成交量",
    verdict: "结论",
    "validation gate": "验证门禁",
    gate: "门禁校验",
    cpcv: "CPCV",
    dsr: "DSR",
    wfo: "WFO",
    pbo: "PBO",
    "validation run": "验证运行",
    "cross-validation quality": "交叉验证质量",
    "path coverage": "路径覆盖",
    "cpcv paths": "CPCV 路径",
    "dsr threshold": "DSR 阈值",
    "observed sharpe": "观测 Sharpe",
    "expected max sharpe": "期望最大 Sharpe",
    "annual return": "年化收益率",
    "win rate": "胜率",
    "profit factor": "盈亏比",
    "overfit share": "过拟合占比",
    "overfit paths": "过拟合路径数",
    "total paths": "总路径数",
    passed: "通过",
    recomputed: "已重算",
    "oos sharpe mean": "样本外 Sharpe 均值",
    "oos efficiency": "样本外效率",
    "is return mean": "样本内收益均值",
    "oos return mean": "样本外收益均值",
    "validation primary signal": "验证主信号",
    "gate currently resolves on cpcv evidence.": "当前门禁结论主要依据 CPCV 证据。",
    "out-of-sample signal quality aggregated across cpcv paths.": "样本外信号质量已按 CPCV 路径聚合。",
    "release gate evidence and check-level quality diagnostics.": "放行门证据与检查项级别诊断。",
    "every gate check that contributed to the final go / no-go decision.": "列出所有参与最终放行结论的门禁检查项。",
    "no checks returned.": "当前没有返回检查项。",
    "observed sharpe is deflated against the multiple-testing burden.": "观测 Sharpe 已按多重检验负担做折减处理。",
    "backing backtest used to contextualize the dsr verdict.": "用于解释 DSR 结论的配套回测快照。",
    "backtest efficiency and capital preservation snapshot.": "回测效率与资金保全表现快照。",
    "the backtest profile behind the deflated sharpe verdict.": "支撑折减 Sharpe 结论的回测画像。",
    "core return and risk statistics feeding the dsr interpretation.": "用于解释 DSR 的核心收益与风险指标。",
    "no backtest metrics available.": "暂无回测指标。",
    "higher pbo means parameter search is more likely to be fitting noise.": "PBO 越高，说明参数搜索越可能是在拟合噪声。",
    "how many train/test paths landed in the overfit regime.": "展示进入过拟合区间的训练/测试路径数量。",
    "the in-sample vs out-of-sample return spread should stay narrow.": "样本内外收益差应尽量保持收敛。",
    "path-level overfitting and return spread diagnostics.": "路径级过拟合与收益分布诊断。",
    "probability of backtest overfitting with supporting statistics.": "回测过拟合概率及其支撑统计。",
    "no overfitting metrics available.": "暂无过拟合指标。",
    "cross-path out-of-sample quality summary.": "跨路径样本外质量汇总。",
    "signal precision / recall aggregated across all cpcv paths.": "所有 CPCV 路径上的精确率与召回率聚合结果。",
    "how the cpcv run was evaluated and recomputed.": "展示 CPCV 运行的评估与重算方式。",
    "per-path out-of-sample quality across the cpcv run.": "CPCV 运行中每条路径的样本外质量。",
    "out-of-sample performance path by path.": "逐路径展示样本外表现。",
    "no path results returned.": "暂无路径结果。",
    "rolling windows test whether the strategy keeps adapting to regime changes.": "滚动窗口用于检验策略是否持续适应市场切换。",
    "anchored windows keep building on the full in-sample history.": "锚定窗口会持续累积完整样本内历史。",
    "use both modes together to spot brittle adaptation vs memory effects.": "结合两种模式观察脆弱适应与记忆效应。",
    "rolling vs anchored window-by-window evidence.": "滚动与锚定窗口的逐窗证据对比。",
    "train on the immediately preceding regime slice.": "基于紧邻的前序市场阶段进行训练。",
    "train on the full anchored history up to each oos window.": "在每个样本外窗口之前使用完整锚定历史训练。",
    "no rolling window results.": "暂无滚动窗口结果。",
    "no anchored window results.": "暂无锚定窗口结果。",
    "no highlights available.": "暂无可用要点。",
    "docker ready": "Docker 就绪",
    "docker missing": "Docker 缺失",
    "demo data seeded": "演示数据已写入",
    "workspace currently contains only seeded demo data for front-end walkthroughs.": "当前工作区仅包含用于前端演示的示例数据。",
    "active alerts need investigation before enabling live workflows.": "在启用 live 流程之前，需要先处理当前告警。",
    "review the current execution draft before launching.": "启动前请先复核当前执行草稿。",
    "validation evidence has not been linked into the current draft yet.": "当前执行草稿还没有关联可用的验证证据。",
    "monitoring is degraded, so operator signals are not yet fully trustworthy.": "监控链路已降级，当前运营信号还不能完全作为放行依据。",
    "data mode and monitoring posture are both part of the launch decision.": "数据模式与监控姿态都属于当前启动决策的一部分。",
    "no new global blockers. keep moving the current workflow.": "当前没有新的全局阻塞项，继续推进当前流程。",
    "kill switch active": "熔断中",
    "needs attention": "需关注",
    "data loop online": "数据环在线",
    "source mix": "来源构成",
    "source context": "来源说明",
    "data mode": "数据模式",
    services: "服务连通",
    mode: "模式",
    "open positions": "持仓数",
    "pending orders": "挂单数",
    cash: "现金",
    drawdown: "回撤",
    exposure: "敞口",
    warnings: "警告",
    errors: "错误",
    "session events": "会话事件",
    return: "收益率",
    trades: "交易笔数",
    method: "方法",
    entries: "入场数",
    exits: "出场数",
    "session id": "会话 ID",
    portfolio: "组合权益",
    "internal positions": "内部持仓",
    "exporter error": "导出器错误",
    "filled orders": "已成交订单",
    "bar latency": "Bar 延迟",
    "signal latency": "信号延迟",
    "order latency": "订单延迟",
    "market symbols": "实盘交易对",
    "demo symbols": "演示交易对",
    "unknown symbols": "未知来源交易对",
    "hybrid symbols": "混合来源交易对",
    "parquet root exists": "Parquet 根目录存在",
    "duckdb exists": "DuckDB 文件存在",
    "stored range": "已存区间",
    "bars saved": "已写入 Bar",
    "files updated": "已更新文件",
    "rows updated": "已更新记录",
    "operator endpoint": "运维访问入口",
    "no details": "暂无详情",
    "no run": "暂无运行",
    cold: "冷启动",
    reachable: "可达",
    "prometheus exporter failed to start inside the quantflow process.": "Prometheus 导出器未能在 QuantFlow 进程内启动。",
    "monitoring endpoints are not reachable from this workstation.": "当前工作站无法访问监控端点。",
    "metrics scrape endpoint": "指标抓取端点",
    "dashboards and operator panels": "看板与运维面板",
    "latest platform state, execution posture, and recent event mix.": "汇总最新平台状态、执行姿态和近期事件分布。",
    "latest research run, validation outcome, and managed session snapshot.": "展示最近研究、验证结果和受管会话快照。",
    "trading session is running.": "交易会话正在运行。",
    "6 recent validation runs ended in no-go.": "最近 6 次验证运行都以不通过结束。",
    "configured endpoint is currently unreachable from this workstation.": "当前工作站无法访问已配置端点。",
    "exporter startup failed inside the quantflow process.": "导出器未能在 QuantFlow 进程内启动。",
    "prometheus exporter failed": "Prometheus 导出器失败",
    "external unavailable": "外部不可达",
    "recent signal reached execution.": "最近已有信号进入执行层。",
    "no recent strategy signals reached the execution layer.": "最近没有策略信号进入执行层。",
    "watch when research output starts turning into live routing decisions.": "这里用于观察研究输出何时开始转化为真实执行决策。",
    "recent order activity captured.": "已捕获最近一次订单活动。",
    "no working orders are waiting in the execution book.": "当前执行簿中没有待成交挂单。",
    "this lane tracks intent after signals leave the strategy layer.": "这一路径用于跟踪信号离开策略层后的订单意图。",
    "recent fill captured.": "已捕获最近一次成交。",
    "positions are open, but no fill landed inside the visible event window.": "当前存在持仓，但可见事件窗口内没有新的成交记录。",
    "no recent fills have been captured yet.": "当前还没有捕获到新的成交记录。",
    "use this lane to confirm that routed orders are actually turning into inventory.": "这里用于确认路由后的订单是否真正转化为持仓。",
    "kill switch has been triggered.": "熔断开关已经触发。",
    "recent risk event captured.": "已捕获最近一次风控事件。",
    "risk controls are armed and no recent execution-side issues were observed.": "风控护栏已布防，最近没有观察到执行侧异常。",
    "this lane should stay quiet before considering any live promotion.": "推进到实盘之前，这一路径应尽量保持安静。",
    "no highlights available.": "暂无可用要点。",
    "waiting for live telemetry.": "等待实时遥测。",
    "signal generated": "信号生成",
    "order filled": "订单已成交",
    "session started": "会话启动",
    "session stopped": "会话停止",
    "session error": "会话异常",
    default: "默认值",
    unassigned: "未分配",
    high: "最高",
    low: "最低",
    max: "最高",
    min: "最低",
    sampled: "抽样视图",
    "full resolution": "完整分辨率",
    entry: "入场",
    exit: "出场",
    "trend following": "趋势跟踪",
    "mean reversion": "均值回归",
    "elliott wave": "艾略特波浪",
    "volatility breakout": "波动突破",
    "funding rate": "资金费率",
    "momentum rotation": "动量轮动",
    "ml ensemble": "机器学习集成",
  };
  return mapping[normalized] || text;
}

function localizeInlineText(value, fallback = "N/A") {
  const text = safeText(value, fallback);
  if (text === null || text === undefined) {
    return String(fallback);
  }

  let result = String(text);
  if (!result.trim()) {
    return String(fallback);
  }

  result = String(localizeUiText(result, result));

  const replacements = [
    [/Trend Following/g, "趋势跟踪"],
    [/Mean Reversion/g, "均值回归"],
    [/Elliott Wave/g, "艾略特波浪"],
    [/Volatility Breakout/g, "波动突破"],
    [/Funding Rate/g, "资金费率反转"],
    [/Momentum Rotation/g, "动量轮动"],
    [/ML Ensemble/g, "机器学习集成"],
    [/\btrend_following\b/g, "趋势跟踪"],
    [/\bmean_reversion\b/g, "均值回归"],
    [/\belliott_wave\b/g, "艾略特波浪"],
    [/\bvolatility_breakout\b/g, "波动突破"],
    [/\bfunding_rate\b/g, "资金费率反转"],
    [/\bmomentum_rotation\b/g, "动量轮动"],
    [/\bml_ensemble\b/g, "机器学习集成"],
    [/\bNO-GO\b/g, "不通过"],
    [/\bpaper\b/gi, "模拟盘"],
    [/\bsandbox\b/gi, "沙盒"],
    [/\blive\b/gi, "实盘"],
    [/\blong\b/gi, "多头"],
    [/\bshort\b/gi, "空头"],
    [/\bflat\b/gi, "空仓"],
    [/\binfo\b/gi, "信息"],
    [/\bsuccess\b/gi, "成功"],
    [/\bEvent\b/g, "事件"],
    [/\bValidation\b/g, "验证运行"],
    [/\btelemetry\b/gi, "遥测"],
    [/\bNo details\b/gi, "暂无详情"],
    [/\bNo reason provided\.?\b/gi, "暂无说明"],
    [/\bNot validated\b/gi, "未验证"],
    [/OKX Live \+ AI Factors/gi, "OKX 实盘 + AI 因子"],
    [/OKX Live/gi, "OKX 实盘"],
    [/AI Factors/gi, "AI 因子"],
    [/\bpaper-(\d+)\b/gi, "模拟单 #$1"],
    [/([0-9.]+)\s*pts\b/gi, "$1 个点"],
    [/(\d+)\s+strateg(?:y|ies)\b/gi, "$1 个策略"],
  ];

  replacements.forEach(([pattern, replacement]) => {
    result = result.replace(pattern, replacement);
  });

  return result;
}

function localizeResearchReport(report, fallback = "") {
  const text = safeText(report, fallback);
  if (!text) {
    return fallback;
  }
  let result = localizeInlineText(text, text);
  const replacements = [
    [/##\s*Backtest:/g, "## 回测："],
    [/\|\s*Metric\s*\|/g, "| 指标 |"],
    [/\|\s*Value\s*\|/g, "| 数值 |"],
    [/\|\s*Period\s*\|/g, "| 区间 |"],
    [/\|\s*Capital\s*\|/g, "| 资金 |"],
    [/\|\s*Total Return\s*\|/g, "| 总收益率 |"],
    [/\|\s*Annual Return\s*\|/g, "| 年化收益率 |"],
    [/\|\s*Sharpe(?: Ratio)?\s*\|/g, "| Sharpe |"],
    [/\|\s*Sortino(?: Ratio)?\s*\|/g, "| Sortino |"],
    [/\|\s*Calmar(?: Ratio)?\s*\|/g, "| Calmar |"],
    [/\|\s*Max Drawdown\s*\|/g, "| 最大回撤 |"],
    [/\|\s*Num Trades\s*\|/g, "| 交易笔数 |"],
    [/\|\s*Win Rate\s*\|/g, "| 胜率 |"],
    [/\|\s*Profit Factor\s*\|/g, "| 盈亏比 |"],
    [/\|\s*Final Capital\s*\|/g, "| 期末资金 |"],
  ];
  replacements.forEach(([pattern, replacement]) => {
    result = result.replace(pattern, replacement);
  });
  return result;
}

function formatTradingMode(mode) {
  return localizeUiText(mode, "待检测");
}

function formatOrderType(orderType) {
  return localizeUiText(orderType, safeText(orderType, "待检测"));
}

function formatOrderSide(side) {
  return localizeUiText(side, safeText(side, "待检测"));
}

function formatOrderStatus(status) {
  return localizeUiText(status, safeText(status, "待检测"));
}

function formatPositionSide(side) {
  return localizeUiText(side, safeText(side, "待检测"));
}

function formatPercent(value) {
  const n = Number(value);
  if (value === null || value === undefined || Number.isNaN(n) || !Number.isFinite(n)) {
    return "待检测";
  }
  return `${(n * 100).toFixed(2)}%`;
}

function formatMetricNumber(value, digits = 3) {
  const n = Number(value);
  if (value === null || value === undefined || Number.isNaN(n) || !Number.isFinite(n)) {
    return "待检测";
  }
  return n.toFixed(digits);
}

function formatLatencyMs(value) {
  const n = Number(value);
  if (value === null || value === undefined || Number.isNaN(n) || !Number.isFinite(n)) {
    return "待检测";
  }
  return `${(n * 1000).toFixed(1)} ms`;
}

function formatCompactNumber(value) {
  const n = Number(value);
  if (value === null || value === undefined || Number.isNaN(n) || !Number.isFinite(n)) {
    return "待检测";
  }
  return new Intl.NumberFormat("en-US", {
    notation: "compact",
    maximumFractionDigits: 2,
  }).format(n);
}

function formatTimestamp(value) {
  if (!value) {
    return "待检测";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return `${date.toISOString().slice(0, 10)} ${date.toISOString().slice(11, 19)}`;
}

function formatDateInput(value) {
  if (!value) {
    return "";
  }
  return new Date(value).toISOString().slice(0, 10);
}

function formatDateRange(range) {
  if (!range || range.length !== 2) {
    return "待检测";
  }
  return `${new Date(range[0]).toISOString().slice(0, 10)} - ${new Date(range[1]).toISOString().slice(0, 10)}`;
}

function formatDataSource(source) {
  const normalized = String(source || "").trim().toLowerCase();
  if (normalized === "okx" || normalized === "market") {
    return "市场";
  }
  if (normalized === "demo") {
    return "演示";
  }
  if (normalized === "unknown" || normalized === "source-unknown") {
    return "未知";
  }
  if (normalized === "hybrid") {
    return "混合";
  }
  return safeText(source, "N/A");
}

function dataSourceTone(source) {
  const normalized = String(source || "").trim().toLowerCase();
  if (normalized === "okx" || normalized === "market") {
    return "accent";
  }
  if (normalized === "demo") {
    return "muted";
  }
  if (normalized === "unknown" || normalized === "source-unknown" || normalized === "hybrid") {
    return "warning";
  }
  return "muted";
}

function formatDataMode(mode) {
  const normalized = String(mode || "").trim().toLowerCase();
  if (normalized === "market") {
    return "市场就绪";
  }
  if (normalized === "demo-seeded") {
    return "演示数据已就绪";
  }
  if (normalized === "source-unknown") {
    return "来源待确认";
  }
  if (normalized === "hybrid") {
    return "混合来源";
  }
  if (normalized === "demo-ready") {
    return "演示可用";
  }
  return localizeUiText(mode, "待检测");
}

function dataModeTone(mode) {
  const normalized = String(mode || "").trim().toLowerCase();
  if (normalized === "market") {
    return "accent";
  }
  if (normalized === "demo-seeded") {
    return "muted";
  }
  if (normalized === "source-unknown" || normalized === "hybrid" || normalized === "demo-ready") {
    return "warning";
  }
  return "muted";
}

function formatSourceMix(sourceCounts = {}, limit = 4) {
  const entries = Object.entries(sourceCounts || {})
    .filter(([, value]) => Number(value) > 0)
    .sort((left, right) => Number(right[1]) - Number(left[1]));
  if (!entries.length) {
    return "无";
  }
  return entries
    .slice(0, limit)
    .map(([label, value]) => `${formatDataSource(label)} ${value}`)
    .join(" · ");
}

function needsSourceTagging(source) {
  const normalized = String(source || "").trim().toLowerCase();
  return normalized === "unknown" || normalized === "source-unknown";
}

function renderSourceTagActions(symbol, source, options = {}) {
  const compact = options.compact === true;
  if (!needsSourceTagging(source)) {
    return "";
  }
  const symbolValue = escapeHtml(safeText(symbol, "BTC/USDT"));
  const buttonClass = compact ? "button ghost small" : "button ghost small";
  return `
    <button type="button" class="${buttonClass}" data-data-action="tag-market" data-symbol="${symbolValue}">标记为实盘来源</button>
    <button type="button" class="${buttonClass}" data-data-action="tag-demo" data-symbol="${symbolValue}">标记为演示来源</button>
  `;
}

function deepClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function currentPanelMeta(panelName = state.activePanel) {
  return panelChromeMeta[panelName] || panelChromeMeta.overview;
}

function platformSignalCard(title, value, note, tone = "muted", rows = []) {
  return `
    <article class="platform-signal-card ${toneClass(tone)}">
      <div class="platform-signal-meta">
        <strong>${escapeHtml(localizeInlineText(title, title))}</strong>
        <span class="${pillToneClass(tone)}">${escapeHtml(localizeInlineText(value, "N/A"))}</span>
      </div>
      <div class="platform-signal-value">${escapeHtml(localizeInlineText(value, "N/A"))}</div>
      <div class="platform-signal-note">${escapeHtml(localizeInlineText(note, "N/A"))}</div>
      <div class="platform-signal-details">
        ${rows.map(([label, rowValue]) => `
          <div class="platform-signal-detail">
            <span>${escapeHtml(localizeInlineText(label, label))}</span>
            <strong>${escapeHtml(localizeInlineText(rowValue, "N/A"))}</strong>
          </div>
        `).join("")}
      </div>
    </article>
  `;
}

function buildPlatformWorkbenchModel() {
  const panel = currentPanelMeta();
  const overviewModel = state.overview ? buildOverviewModel(state.overview) : null;
  const monitoring = state.monitoring || {};
  const sessionSnapshot = state.session || state.liveSessionSnapshot || {};
  const sessionDashboard = sessionSnapshot.dashboard || monitoring.latest?.session?.dashboard || {};
  const latestValidation = monitoring.latest?.validation || state.latestValidationResult || state.validationHistory[0] || null;
  const latestValidationSummary = latestValidation?.summary || {};
  const draftMeta = state.executionDraftMeta || executionDraftMetaDefaults();
  const draftReview = executionDraftReadinessModel(
    state.executionHub?.control || sessionSnapshot.request || state.terminalDraft || {},
  );
  const draftValidationContext = executionDraftValidationContext(draftMeta, draftReview.runtime);
  const dataMode = state.overview?.data?.mode || state.dataHub?.mode || null;
  const dataModeLabel = formatDataMode(dataMode);
  const dataTone = dataModeTone(dataMode);
  const validationLabel = localizeInlineText(
    draftValidationContext.label,
    "未验证",
  );
  const validationTone = draftValidationContext.tone || "muted";
  const validationReason = localizeInlineText(
    draftValidationContext.reason,
    "当前执行草稿还没有关联可用的验证证据。",
  );
  const validationMethod = draftValidationContext.label
    ? localizeUiText(safeText(draftValidationContext.method, "Validation"), "验证运行")
    : "待检测";
  const validationEntries = draftValidationContext.label ? safeText(latestValidationSummary.entries, 0) : "待检测";
  const validationExits = draftValidationContext.label ? safeText(latestValidationSummary.exits, 0) : "待检测";
  const servicesUp = Number(monitoring.metrics?.services_up || 0);
  const servicesTotal = Number(monitoring.metrics?.services_total || 0);
  const serviceLabel = servicesTotal > 0 ? `${servicesUp}/${servicesTotal}` : "N/A";
  const serviceTone = servicesTotal > 0 && servicesUp < servicesTotal ? "warning" : "accent";
  const healthTone = safeText(overviewModel?.healthTone || monitoring.health?.overall_tone, "muted");
  const healthLabel = safeText(overviewModel?.healthLabel || monitoring.health?.overall_label, "Unknown");
  let workbenchActions = Array.isArray(panel.actions) ? panel.actions.slice() : [];
  const note = [
    panel.workbenchText,
    panel.label === "执行工作台" && !draftValidationContext.label
      ? "当前执行草稿还没有关联可用的验证证据，应先回到研究或验证页绑定结果。"
      : draftReview.reasons?.[0],
    panel.label === "执行工作台" ? null : overviewModel?.nextStep,
  ].filter(Boolean).join(" ");
  let blockers = Array.isArray(overviewModel?.blockers) ? overviewModel.blockers.slice(0, 3) : [];

  if (panel.label === "执行工作台" && !draftValidationContext.label) {
    blockers = [
      {
        kind: "execution",
        title: "执行草稿未绑定验证",
        message: "当前执行草稿还没有关联可用的验证证据。先回到研究或验证页绑定结果，再决定是否继续演示模式运行。",
        tone: draftReview.tone === "warning" ? "warning" : "muted",
        actions: [
          { action: "open-research", label: "打开研究页" },
          { action: "open-validation", label: "打开验证页", primary: true },
        ],
      },
      ...blockers.filter((item) => item.kind !== "validation"),
    ].slice(0, 3);
  }

  if (panel.label === "执行工作台") {
    if (!draftValidationContext.label) {
      workbenchActions = draftMeta.sourceType === "research"
        ? [
            { action: "research-open-validation", label: "研究结果送验证", primary: true },
            { action: "open-draft-source", label: "打开当前来源" },
          ]
        : [
            { action: "open-validation", label: "打开验证页", primary: true },
            { action: "open-draft-source", label: "打开当前来源" },
          ];
    } else if (validationTone !== "accent") {
      workbenchActions = [
        { action: "open-validation", label: "查看验证页", primary: true },
        { action: "open-draft-source", label: "打开当前来源" },
      ];
    }
  }

  return {
    panel,
    healthTone,
    healthLabel: localizeUiText(healthLabel, "待检测"),
    note,
    statusRows: [
      statusRow("当前面板", panel.label, "accent"),
      statusRow("实时会话", localizeUiText(sessionSnapshot.running ? "Running" : "Stopped"), sessionSnapshot.running ? "accent" : "muted"),
      statusRow("会话 ID", safeText(sessionSnapshot.session_id, "N/A")),
      statusRow("执行草稿", draftReview.label, draftReview.tone),
      statusRow("草稿来源", safeText(draftMeta.sourceLabel, "手动草稿"), draftMeta.edited ? "warning" : "muted"),
      statusRow("草稿配置", terminalConfigText(draftReview.draft)),
      statusRow("草稿策略", terminalStrategyText(draftReview.draft.strategies)),
      statusRow("验证结论", validationLabel, validationTone),
      statusRow("数据模式", dataModeLabel, dataTone),
      statusRow("监控服务", serviceLabel, serviceTone),
    ].join(""),
    actionsHtml: workbenchActions
      .map((action) => stageStatusAction(action.action, action.label, action.primary))
      .join(""),
    blockersHtml: blockers.length
      ? blockers.map((item) => overviewBlockerCard(item)).join("")
      : `<div class="history-empty">${localizeUiText("No new global blockers. Keep moving the current workflow.")}</div>`,
    signalsHtml: [
      platformSignalCard(
        "实时会话",
        localizeUiText(sessionSnapshot.running ? "Running" : "Stopped"),
        sessionSnapshot.running
          ? `会话 ${safeText(sessionSnapshot.session_id, "N/A")} 正在运行，前端已经能直接看到实时状态。`
          : "当前没有正在运行的托管会话。",
        sessionSnapshot.running ? "accent" : "muted",
        [
          ["模式", formatTradingMode(sessionSnapshot.request?.mode || draftReview.draft.mode)],
          ["持仓数", safeText(sessionDashboard.open_positions, 0)],
          ["事件数", safeText(monitoring.metrics?.session_events, 0)],
        ],
      ),
      platformSignalCard(
        "执行草稿",
        draftReview.label,
        safeText(draftReview.reasons?.[0], localizeUiText("Review the current execution draft before launching.")),
        draftReview.tone,
        [
          ["来源", safeText(draftMeta.sourceLabel, "手动草稿")],
          ["配置", terminalConfigText(draftReview.draft)],
          ["策略", terminalStrategyText(draftReview.draft.strategies)],
        ],
      ),
      platformSignalCard(
        "放行门禁",
        validationLabel,
        validationReason,
        validationTone,
        [
          ["方法", validationMethod],
          ["入场数", validationEntries],
          ["出场数", validationExits],
        ],
      ),
      platformSignalCard(
        "数据与监控",
        dataModeLabel,
        servicesTotal > 0 && servicesUp < servicesTotal
          ? localizeUiText("Monitoring is degraded, so operator signals are not yet fully trustworthy.")
          : localizeUiText("Data mode and monitoring posture are both part of the launch decision."),
        servicesTotal > 0 && servicesUp < servicesTotal ? "warning" : dataTone,
        [
          ["数据", dataModeLabel],
          ["服务", serviceLabel],
          ["组合权益", formatMetricNumber(monitoring.internal_metrics?.portfolio_value ?? sessionSnapshot.portfolio?.equity, 2)],
        ],
      ),
    ].join(""),
  };
}

function renderHeaderContext() {
  const panel = currentPanelMeta();
  const contextNode = document.getElementById("header-context");
  if (contextNode) {
    contextNode.textContent = panel.context;
  }
  const panelNode = document.getElementById("topbar-panel-pill");
  if (panelNode) {
    panelNode.className = pillToneClass("accent");
    panelNode.textContent = panel.label;
  }
}

function renderPlatformWorkbench() {
  const shellNode = document.getElementById("platform-workbench");
  const signalNode = document.getElementById("platform-workbench-signals");
  if (!shellNode || !signalNode) {
    return;
  }
  const model = buildPlatformWorkbenchModel();
  const compactMode = state.activePanel !== "overview";
  shellNode.classList.toggle("is-compact", compactMode);
  document.getElementById("platform-workbench-title").textContent = model.panel.workbenchTitle;
  document.getElementById("platform-workbench-text").textContent = model.note;
  const healthNode = document.getElementById("platform-workbench-health");
  healthNode.className = pillToneClass(model.healthTone);
  healthNode.textContent = model.healthLabel;
  const panelNode = document.getElementById("platform-workbench-panel");
  panelNode.className = pillToneClass("accent");
  panelNode.textContent = model.panel.label;
  signalNode.innerHTML = model.signalsHtml;
  document.getElementById("platform-workbench-status").innerHTML = model.statusRows;
  document.getElementById("platform-workbench-actions").innerHTML = model.actionsHtml;
  document.getElementById("platform-workbench-note").textContent = model.note;
  document.getElementById("platform-workbench-blockers").innerHTML = model.blockersHtml;
}

function refreshPlatformChrome() {
  renderHeaderContext();
  renderPlatformWorkbench();
}

function mergeParams(defaults = {}, overrides = {}) {
  return { ...deepClone(defaults), ...(overrides || {}) };
}

function inferParamType(value) {
  if (Array.isArray(value)) {
    return "array";
  }
  if (typeof value === "boolean") {
    return "boolean";
  }
  if (typeof value === "number") {
    return "number";
  }
  if (value && typeof value === "object") {
    return "object";
  }
  return "string";
}

function parsePrimitive(raw) {
  const trimmed = String(raw).trim();
  if (trimmed === "") {
    return "";
  }
  if (trimmed === "true") {
    return true;
  }
  if (trimmed === "false") {
    return false;
  }
  const number = Number(trimmed);
  if (!Number.isNaN(number) && trimmed !== "") {
    return number;
  }
  return trimmed;
}

function parseParamValue(raw, paramType) {
  if (paramType === "boolean") {
    return raw === true || raw === "true";
  }
  if (paramType === "number") {
    const value = Number(raw);
    return Number.isNaN(value) ? 0 : value;
  }
  if (paramType === "array") {
    const text = String(raw).trim();
    if (!text) {
      return [];
    }
    if (text.startsWith("[")) {
      return JSON.parse(text);
    }
    return text.split(",").map((item) => parsePrimitive(item));
  }
  if (paramType === "object") {
    const text = String(raw).trim();
    return text ? JSON.parse(text) : {};
  }
  return raw;
}

function rangeHint(strategy, key) {
  const range = strategy?.param_space?.[key];
  if (!range || range.length !== 2) {
    return "默认值";
  }
  return `范围 ${range[0]} - ${range[1]}`;
}

function normalizeStrategyKey(value) {
  return String(value || "")
    .trim()
    .toLowerCase()
    .replaceAll("-", "_")
    .replace(/\s+/g, "_");
}

function localizeStrategyTitle(title, strategyId = null) {
  const mapping = {
    trend_following: "趋势跟踪",
    mean_reversion: "均值回归",
    elliott_wave: "艾略特波浪",
    volatility_breakout: "波动突破",
    funding_rate: "资金费率反转",
    momentum_rotation: "动量轮动",
    ml_ensemble: "机器学习集成",
  };
  const strategyKey = normalizeStrategyKey(strategyId);
  const titleKey = normalizeStrategyKey(title);
  return mapping[strategyKey] || mapping[titleKey] || safeText(title, safeText(strategyId, "未命名策略"));
}

function localizeStrategyDescription(description, strategyId = null) {
  const mapping = {
    trend_following: "基于均线交叉、MACD、RSI、ATR 与成交量多重过滤的趋势策略",
    mean_reversion: "结合 RSI、布林带与成交量确认的均值回归策略",
    elliott_wave: "基于规则量化、多参数 ZigZag 共识与铁律校验的波浪交易系统",
    volatility_breakout: "面向加密市场高波动环境的 ATR 与通道突破策略",
    funding_rate: "结合未平仓量过滤的资金费率极值反转策略",
    momentum_rotation: "跨资产动量排序与周期轮动策略",
    ml_ensemble: "使用可配置阈值的模型驱动集成信号策略",
  };
  const strategyKey = normalizeStrategyKey(strategyId);
  return mapping[strategyKey] || safeText(description, "暂无策略说明。");
}

function configAssetLabel(configPath, fallback = "已加载") {
  const text = String(safeText(configPath, "")).trim();
  if (!text) {
    return fallback;
  }
  const segments = text.split(/[\\/]/).filter(Boolean);
  return segments.length ? segments[segments.length - 1] : fallback;
}

function strategyReadinessLabel(strategy = {}, selected = false) {
  if (selected) {
    return { label: "已选", tone: "accent" };
  }
  if (strategyRiskCount(strategy) > 0) {
    return { label: "风控就绪", tone: "accent" };
  }
  if (strategyExitCount(strategy) > 0) {
    return { label: "研究就绪", tone: "muted" };
  }
  return { label: "可用", tone: "muted" };
}

function strategyOperationalStatus(strategy = {}) {
  if (strategyRiskCount(strategy) > 0) {
    return "风控就绪";
  }
  if (strategyExitCount(strategy) > 0) {
    return "研究就绪";
  }
  return "已加载";
}

function formatStrategyText(value) {
  if (Array.isArray(value)) {
    const items = value
      .filter((item) => item !== null && item !== undefined && item !== "")
      .map((item) => localizeStrategyTitle(String(item), String(item)));
    return items.length ? [...new Set(items)].join(", ") : "0 个策略";
  }

  const text = String(safeText(value, "")).trim();
  if (!text) {
    return "0 个策略";
  }

  const countMatch = text.match(/^(\d+)\s+strateg(?:y|ies)$/i);
  if (countMatch) {
    return `${countMatch[1]} 个策略`;
  }

  const segments = text
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
  if (segments.length > 1) {
    return formatStrategyText(segments);
  }

  return localizeStrategyTitle(text, text);
}

function renderParamField(panel, strategy, key, value) {
  const paramType = inferParamType(value);
  const inputId = `${panel}-param-${key}`;
  if (paramType === "boolean") {
    return `
      <label class="param-field checkbox-field" for="${inputId}">
        <div class="param-header">
          <span class="param-label">${escapeHtml(key)}</span>
          <span class="param-hint">${escapeHtml(rangeHint(strategy, key))}</span>
        </div>
        <input
          id="${inputId}"
          type="checkbox"
          data-param-panel="${panel}"
          data-param-key="${key}"
          data-param-type="${paramType}"
          ${value ? "checked" : ""}
        >
      </label>
    `;
  }

  if (paramType === "array" || paramType === "object") {
    return `
      <label class="param-field" for="${inputId}">
        <div class="param-header">
          <span class="param-label">${escapeHtml(key)}</span>
          <span class="param-hint">${escapeHtml(rangeHint(strategy, key))}</span>
        </div>
        <textarea
          id="${inputId}"
          rows="3"
          data-param-panel="${panel}"
          data-param-key="${key}"
          data-param-type="${paramType}"
        >${escapeHtml(JSON.stringify(value))}</textarea>
      </label>
    `;
  }

  return `
    <label class="param-field" for="${inputId}">
      <div class="param-header">
        <span class="param-label">${escapeHtml(key)}</span>
        <span class="param-hint">${escapeHtml(rangeHint(strategy, key))}</span>
      </div>
      <input
        id="${inputId}"
        type="${paramType === "number" ? "number" : "text"}"
        ${paramType === "number" ? 'step="any"' : ""}
        value="${escapeHtml(value)}"
        data-param-panel="${panel}"
        data-param-key="${key}"
        data-param-type="${paramType}"
      >
    </label>
  `;
}

function renderParamEditor(panel, strategyId, overrides = null) {
  const strategy = state.strategyMap[strategyId];
  const container = document.getElementById(`${panel}-params`);
  if (!container || !strategy) {
    return;
  }
  const merged = mergeParams(strategy.params || {}, overrides || {});
  state[`${panel}Params`] = merged;
  container.innerHTML = Object.entries(merged)
    .map(([key, value]) => renderParamField(panel, strategy, key, value))
    .join("");
  if (panel === "research") {
    renderResearchOpsSurface();
  }
}

function collectParams(panel) {
  const params = readParamEditorSnapshot(panel);
  state[`${panel}Params`] = params;
  return params;
}

function populateStrategySelectors(strategies) {
  const optionMarkup = strategies
    .map((strategy) => `<option value="${strategy.strategy_id}">${localizeStrategyTitle(strategy.title, strategy.strategy_id)}</option>`)
    .join("");
  document.getElementById("research-strategy").innerHTML = optionMarkup;
  document.getElementById("validation-strategy").innerHTML = optionMarkup;
  document.getElementById("session-strategies").innerHTML = optionMarkup;
  document.getElementById("execution-strategies").innerHTML = optionMarkup;

  ["session-strategies", "execution-strategies"].forEach((id) => {
    const select = document.getElementById(id);
    if (select.options.length > 0 && !Array.from(select.selectedOptions).length) {
      select.options[0].selected = true;
    }
  });
}

function strategySymbols(strategy) {
  const symbols = Array.isArray(strategy?.symbols) ? strategy.symbols.filter(Boolean) : [];
  if (!symbols.length && strategy?.default_symbol) {
    symbols.push(strategy.default_symbol);
  }
  return [...new Set(symbols.map((symbol) => String(symbol)))];
}

function strategyParamCount(strategy) {
  return Object.keys(strategy?.params || {}).length;
}

function strategyExitCount(strategy) {
  return Object.keys(strategy?.exit || {}).length;
}

function strategyRiskCount(strategy) {
  return Object.keys(strategy?.risk || {}).length;
}

function strategyParamSpaceCount(strategy) {
  return Object.keys(strategy?.param_space || {}).length;
}

function strategyRiskTone(strategy) {
  const riskCount = strategyRiskCount(strategy);
  const exitCount = strategyExitCount(strategy);
  if (riskCount > 0 && exitCount > 0) {
    return "accent";
  }
  if (riskCount > 0 || exitCount > 0) {
    return "warning";
  }
  return "danger";
}

function strategyCoverageTone(strategy) {
  const symbolCount = strategySymbols(strategy).length;
  if (symbolCount >= 3) {
    return "accent";
  }
  if (symbolCount >= 1) {
    return "muted";
  }
  return "warning";
}

function strategySummaryMetric(label, value, note, tone = "muted") {
  return `
    <article class="strategy-summary-card ${toneClass(tone)}">
      <span class="label">${escapeHtml(label)}</span>
      <strong class="value">${escapeHtml(String(value))}</strong>
      <span class="strategy-summary-note">${escapeHtml(String(note))}</span>
    </article>
  `;
}

function formatStrategyValue(value) {
  if (Array.isArray(value)) {
    return value.length ? value.join(", ") : "[]";
  }
  if (value && typeof value === "object") {
    return JSON.stringify(value);
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  return safeText(value, "N/A");
}

function strategyConfigRows(config = {}, emptyLabel = "未配置") {
  const entries = Object.entries(config || {});
  if (!entries.length) {
    return `<div class="strategy-empty-copy">${emptyLabel}</div>`;
  }
  return entries
    .map(
      ([key, value]) => `
        <div class="status-row">
          <span>${escapeHtml(key)}</span>
          <strong>${escapeHtml(String(formatStrategyValue(value)))}</strong>
        </div>
      `,
    )
    .join("");
}

function populateStrategyFilters(strategies) {
  const timeframeSelect = document.getElementById("strategy-timeframe-filter");
  const symbolSelect = document.getElementById("strategy-symbol-filter");
  if (!timeframeSelect || !symbolSelect) {
    return;
  }

  const timeframeOptions = [...new Set(
    strategies
      .map((strategy) => safeText(strategy.timeframe, "Unassigned"))
      .filter(Boolean),
  )].sort((left, right) => left.localeCompare(right));
  const symbolOptions = [...new Set(
    strategies.flatMap((strategy) => strategySymbols(strategy)),
  )].sort((left, right) => left.localeCompare(right));

  timeframeSelect.innerHTML = [
    '<option value="all">全部周期</option>',
    ...timeframeOptions.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`),
  ].join("");
  symbolSelect.innerHTML = [
    '<option value="all">全部交易对</option>',
    ...symbolOptions.map((value) => `<option value="${escapeHtml(value)}">${escapeHtml(value)}</option>`),
  ].join("");

  timeframeSelect.value = timeframeOptions.includes(state.strategyFilters.timeframe)
    ? state.strategyFilters.timeframe
    : "all";
  symbolSelect.value = symbolOptions.includes(state.strategyFilters.symbol)
    ? state.strategyFilters.symbol
    : "all";
  state.strategyFilters.timeframe = timeframeSelect.value;
  state.strategyFilters.symbol = symbolSelect.value;
}

function filteredStrategies() {
  const searchQuery = String(state.strategyFilters.search || "").trim().toLowerCase();
  return state.strategies.filter((strategy) => {
    const timeframe = safeText(strategy.timeframe, "Unassigned");
    const symbols = strategySymbols(strategy);
    if (state.strategyFilters.timeframe !== "all" && timeframe !== state.strategyFilters.timeframe) {
      return false;
    }
    if (state.strategyFilters.symbol !== "all" && !symbols.includes(state.strategyFilters.symbol)) {
      return false;
    }
    if (!searchQuery) {
      return true;
    }
    const haystack = [
      strategy.strategy_id,
      strategy.title,
      strategy.description,
      localizeStrategyTitle(strategy.title, strategy.strategy_id),
      localizeStrategyDescription(strategy.description, strategy.strategy_id),
      timeframe,
      strategy.default_symbol,
      symbols.join(" "),
      Object.keys(strategy.params || {}).join(" "),
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return haystack.includes(searchQuery);
  });
}

function ensureSelectedStrategy(strategies) {
  if (!strategies.length) {
    state.selectedStrategyId = null;
    return null;
  }
  if (!state.selectedStrategyId || !strategies.some((item) => item.strategy_id === state.selectedStrategyId)) {
    state.selectedStrategyId = strategies[0].strategy_id;
  }
  return state.selectedStrategyId;
}

function renderStrategyListItem(strategy, selected) {
  const symbols = strategySymbols(strategy);
  const riskTone = strategyRiskTone(strategy);
  const readiness = strategyReadinessLabel(strategy, selected);
  return `
    <article class="strategy-list-item ${selected ? "selected" : ""}">
      <button
        type="button"
        class="strategy-list-select"
        data-strategy-select="${strategy.strategy_id}"
        aria-pressed="${selected ? "true" : "false"}"
      >
        <div class="strategy-list-copy">
          <div class="surface-head">
            <h3>${escapeHtml(localizeStrategyTitle(strategy.title, strategy.strategy_id))}</h3>
            <span class="${pillToneClass(readiness.tone)}">${escapeHtml(readiness.label)}</span>
          </div>
          <p>${escapeHtml(localizeStrategyDescription(strategy.description, strategy.strategy_id))}</p>
          <div class="strategy-badge-row">
            <span class="tag">${escapeHtml(safeText(strategy.default_symbol, "N/A"))}</span>
            <span class="tag">${escapeHtml(safeText(strategy.timeframe, "未分配"))}</span>
            <span class="tag">${escapeHtml(`${strategyParamCount(strategy)} 个参数`)}</span>
            <span class="${pillToneClass(riskTone)}">${escapeHtml(`${strategyRiskCount(strategy)} 条风控`)}</span>
          </div>
        </div>
      </button>
      <div class="strategy-list-foot">
        <div class="strategy-list-meta">
          <span>${escapeHtml(`${symbols.length} 个交易对`)}</span>
          <span>${escapeHtml(`${strategyExitCount(strategy)} 条退出规则`)}</span>
        </div>
        <div class="strategy-actions">
          <button
            type="button"
            class="button ghost small"
            data-strategy-action="research"
            data-strategy-id="${strategy.strategy_id}"
          >研究</button>
          <button
            type="button"
            class="button ghost small"
            data-strategy-action="validation"
            data-strategy-id="${strategy.strategy_id}"
          >验证</button>
          <button
            type="button"
            class="button primary small"
            data-strategy-action="execution"
            data-strategy-id="${strategy.strategy_id}"
          >执行</button>
        </div>
      </div>
    </article>
  `;
}

function renderStrategyDetail(strategy) {
  const detailNode = document.getElementById("strategy-detail");
  if (!detailNode) {
    return;
  }
  if (!strategy) {
    detailNode.innerHTML = `
      <div class="empty-state strategy-empty-state">
        <div>
          <strong>没有匹配到策略</strong>
          <p>调整搜索、周期或交易对过滤后再试。</p>
        </div>
      </div>
    `;
    return;
  }

  const symbols = strategySymbols(strategy);
  const paramKeys = Object.keys(strategy.params || {});
  const paramSpaceKeys = Object.keys(strategy.param_space || {});
  const riskTone = strategyRiskTone(strategy);
  const configFileLabel = strategy.config_path ? "已加载策略配置" : "待检测";
  const configPreview = {
    params: strategy.params,
    exit: strategy.exit,
    risk: strategy.risk,
    param_space: strategy.param_space,
  };

  detailNode.innerHTML = `
    <article class="strategy-detail-card">
      <div class="surface-head strategy-detail-head">
        <div class="strategy-detail-copy">
          <div class="strategy-badge-row">
            <span class="${pillToneClass("accent")}">策略工作区</span>
            <span class="${pillToneClass(riskTone)}">${escapeHtml(`${strategyRiskCount(strategy)} 条风控规则`)}</span>
            <span class="${pillToneClass(strategyCoverageTone(strategy))}">${escapeHtml(`${symbols.length} 个交易对`)}</span>
          </div>
          <h3>${escapeHtml(localizeStrategyTitle(strategy.title, strategy.strategy_id))}</h3>
          <p>${escapeHtml(localizeStrategyDescription(strategy.description, strategy.strategy_id))}</p>
        </div>
        <div class="strategy-actions strategy-detail-actions">
          <button
            type="button"
            class="button ghost small"
            data-strategy-action="research"
            data-strategy-id="${strategy.strategy_id}"
          >进入研究</button>
          <button
            type="button"
            class="button ghost small"
            data-strategy-action="validation"
            data-strategy-id="${strategy.strategy_id}"
          >进入验证</button>
          <button
            type="button"
            class="button primary small"
            data-strategy-action="execution"
            data-strategy-id="${strategy.strategy_id}"
          >部署到执行</button>
        </div>
      </div>

      <div class="strategy-kv-grid">
        <div class="strategy-kv-card">
          <span class="label">业务状态</span>
          <strong>${escapeHtml(strategyOperationalStatus(strategy))}</strong>
        </div>
        <div class="strategy-kv-card">
          <span class="label">配置文件</span>
          <strong class="strategy-code">${escapeHtml(configFileLabel)}</strong>
        </div>
        <div class="strategy-kv-card">
          <span class="label">默认交易对</span>
          <strong>${escapeHtml(safeText(strategy.default_symbol, "N/A"))}</strong>
        </div>
        <div class="strategy-kv-card">
          <span class="label">周期</span>
          <strong>${escapeHtml(safeText(strategy.timeframe, "未分配"))}</strong>
        </div>
      </div>

      <div class="strategy-summary-grid">
        ${strategySummaryMetric("核心参数", paramKeys.length, "策略默认参数项", "accent")}
        ${strategySummaryMetric("参数空间", paramSpaceKeys.length, "可优化参数维度", paramSpaceKeys.length ? "accent" : "warning")}
        ${strategySummaryMetric("退出规则", strategyExitCount(strategy), "退出规则配置数", strategyExitCount(strategy) ? "muted" : "warning")}
        ${strategySummaryMetric("风控规则", strategyRiskCount(strategy), "风控规则配置数", riskTone)}
      </div>

      <section class="strategy-subsection">
        <div class="surface-head">
          <h4>交易覆盖</h4>
          <span class="${pillToneClass(strategyCoverageTone(strategy))}">${escapeHtml(`${symbols.length} 个已配置`)}</span>
        </div>
        <div class="strategy-badge-row">
          ${symbols.length
    ? symbols.map((symbol) => `<span class="tag">${escapeHtml(symbol)}</span>`).join("")
    : '<span class="tag">未配置交易对</span>'}
        </div>
      </section>

      <div class="strategy-section-grid">
        <section class="strategy-subsection">
          <div class="surface-head">
            <h4>参数摘要</h4>
            <span class="pill muted">${escapeHtml(`${paramKeys.length} 个字段`)}</span>
          </div>
          <div class="status-list">
            ${strategyConfigRows(strategy.params, "当前策略没有默认参数。")}
          </div>
        </section>

        <section class="strategy-subsection">
          <div class="surface-head">
            <h4>参数搜索空间</h4>
            <span class="pill muted">${escapeHtml(`${paramSpaceKeys.length} 个可调`)}</span>
          </div>
          <div class="status-list">
            ${strategyConfigRows(strategy.param_space, "当前策略未声明优化空间。")}
          </div>
        </section>

        <section class="strategy-subsection">
          <div class="surface-head">
            <h4>退出规则</h4>
            <span class="${pillToneClass(strategyExitCount(strategy) ? "muted" : "warning")}">${escapeHtml(`${strategyExitCount(strategy)} 条已配置`)}</span>
          </div>
          <div class="status-list">
            ${strategyConfigRows(strategy.exit, "当前策略未声明退出规则。")}
          </div>
        </section>

        <section class="strategy-subsection">
          <div class="surface-head">
            <h4>风控规则</h4>
            <span class="${pillToneClass(riskTone)}">${escapeHtml(`${strategyRiskCount(strategy)} 条已配置`)}</span>
          </div>
          <div class="status-list">
            ${strategyConfigRows(strategy.risk, "当前策略未声明风控规则。")}
          </div>
        </section>
      </div>

      <details class="json-details">
        <summary>查看完整策略配置摘要</summary>
        <pre class="json-card">${escapeHtml(JSON.stringify(configPreview, null, 2))}</pre>
      </details>
    </article>
  `;
}

function renderStrategyDirectory() {
  const listNode = document.getElementById("strategy-list");
  const countNode = document.getElementById("strategy-filtered-count");
  if (!listNode || !countNode) {
    return;
  }

  const searchInput = document.getElementById("strategy-search");
  if (searchInput && searchInput.value !== state.strategyFilters.search) {
    searchInput.value = state.strategyFilters.search;
  }

  const strategies = filteredStrategies();
  const selectedId = ensureSelectedStrategy(strategies);
  countNode.textContent = `显示 ${strategies.length}`;
  listNode.innerHTML = strategies.length
    ? strategies.map((strategy) => renderStrategyListItem(strategy, strategy.strategy_id === selectedId)).join("")
    : `
      <div class="empty-state strategy-empty-state">
        <div>
          <strong>没有匹配到策略</strong>
          <p>当前过滤条件下没有可显示的策略。</p>
        </div>
      </div>
    `;
  renderStrategyDetail(strategies.find((strategy) => strategy.strategy_id === selectedId) || null);
  persistWorkbenchState();
}

function renderStrategies(strategies) {
  state.strategies = strategies;
  populateStrategyFilters(strategies);

  const totalStrategies = strategies.length;
  const totalSymbols = new Set(strategies.flatMap((strategy) => strategySymbols(strategy))).size;
  const averageParamCount = totalStrategies
    ? (strategies.reduce((sum, strategy) => sum + strategyParamCount(strategy), 0) / totalStrategies).toFixed(1)
    : "0.0";
  const riskAwareStrategies = strategies.filter((strategy) => strategyRiskCount(strategy) > 0).length;

  document.getElementById("strategy-count").textContent = `${totalStrategies} 个策略`;
  document.getElementById("strategy-stat-grid").innerHTML = [
    strategySummaryMetric("策略总数", totalStrategies, "已加载策略总数", "accent"),
    strategySummaryMetric("覆盖交易对", totalSymbols, "策略配置覆盖交易对", totalSymbols ? "muted" : "warning"),
    strategySummaryMetric("平均参数", averageParamCount, "平均默认参数数量", "muted"),
    strategySummaryMetric("风控就绪", riskAwareStrategies, "已配置风控规则的策略", riskAwareStrategies ? "accent" : "warning"),
  ].join("");

  renderStrategyDirectory();
}

function selectStrategy(strategyId) {
  if (!state.strategyMap[strategyId]) {
    return;
  }
  state.selectedStrategyId = strategyId;
  renderStrategyDirectory();
}

function bindStrategyDirectoryControls() {
  const searchInput = document.getElementById("strategy-search");
  const timeframeSelect = document.getElementById("strategy-timeframe-filter");
  const symbolSelect = document.getElementById("strategy-symbol-filter");

  searchInput.addEventListener("input", (event) => {
    state.strategyFilters.search = event.target.value || "";
    renderStrategyDirectory();
  });

  timeframeSelect.addEventListener("change", (event) => {
    state.strategyFilters.timeframe = event.target.value || "all";
    renderStrategyDirectory();
  });

  symbolSelect.addEventListener("change", (event) => {
    state.strategyFilters.symbol = event.target.value || "all";
    renderStrategyDirectory();
  });
}

function overviewInspectorSelection(kind = null, key = null) {
  return {
    kind: kind || null,
    key: key || null,
  };
}

function overviewInspectorItemKey(kind, item = {}, index = 0) {
  return safeText(
    item.inspectorKey || item.key || item.id || `${kind || "item"}:${item.title || item.label || item.kind || index}`,
    `${kind || "item"}:${index}`,
  );
}

function overviewSelectableAttrs(options = {}) {
  if (!options.kind || !options.key) {
    return "";
  }
  return ` tabindex="0" data-overview-inspector-kind="${escapeHtml(options.kind)}" data-overview-inspector-key="${escapeHtml(options.key)}"`;
}

function overviewActionsSummary(actions = []) {
  return actions
    .map((action) => {
      if (typeof action === "string") {
        return action;
      }
      return action?.label || action?.action || "";
    })
    .filter(Boolean)
    .join(" / ");
}

function overviewStageCard(title, value, note, tone = "muted", actions = "", options = {}) {
  const selectableAttrs = overviewSelectableAttrs(options);
  const selectableClass = options.kind ? "overview-selectable" : "";
  const selectedClass = options.selected ? "is-selected" : "";
  return `
    <article class="overview-stage-card ${selectableClass} ${selectedClass} ${toneClass(tone)}"${selectableAttrs}>
      <div class="history-top">
        <strong>${escapeHtml(localizeInlineText(title, title))}</strong>
        <span class="${pillToneClass(tone)}">${escapeHtml(localizeInlineText(value, "N/A"))}</span>
      </div>
      <div class="history-note">${escapeHtml(localizeInlineText(note, "N/A"))}</div>
      ${actions ? `<div class="history-actions overview-card-actions">${actions}</div>` : ""}
    </article>
  `;
}

function overviewWorkflowCard(title, badge, tone, summary, rows = [], actions = "", options = {}) {
  const selectableAttrs = overviewSelectableAttrs(options);
  const selectableClass = options.kind ? "overview-selectable" : "";
  const selectedClass = options.selected ? "is-selected" : "";
  const content = rows.length
    ? rows.map(([label, value, rowTone = null]) => statusRow(label, value, rowTone)).join("")
    : statusRow("状态", "N/A");
  return `
    <article class="overview-workflow-card ${selectableClass} ${selectedClass} ${toneClass(tone)}"${selectableAttrs}>
      <div class="history-top">
        <strong>${escapeHtml(localizeInlineText(title, title))}</strong>
        <span class="${pillToneClass(tone)}">${escapeHtml(localizeInlineText(badge, "N/A"))}</span>
      </div>
      <div class="history-note">${escapeHtml(localizeInlineText(summary, "N/A"))}</div>
      <div class="status-list compact-status-list">${content}</div>
      ${actions ? `<div class="history-actions overview-card-actions">${actions}</div>` : ""}
    </article>
  `;
}

function overviewBlockerCard(blocker = {}, options = {}) {
  const tone = safeText(blocker.tone, "muted");
  const actions = Array.isArray(blocker.actions) && blocker.actions.length
    ? `
      <div class="history-actions overview-card-actions">
        ${blocker.actions.map((action) => `
          <button
            type="button"
            class="${escapeHtml(action.primary ? "button primary small" : "button ghost small")}"
            data-overview-action="${escapeHtml(action.action)}"
          >${escapeHtml(action.label)}</button>
        `).join("")}
      </div>
    `
    : "";
  const selectableAttrs = overviewSelectableAttrs(options);
  const selectableClass = options.kind ? "overview-selectable" : "";
  const selectedClass = options.selected ? "is-selected" : "";
  return `
    <article class="history-card ${selectableClass} ${selectedClass} ${toneClass(tone)}"${selectableAttrs}>
      <div class="history-top">
        <strong>${escapeHtml(safeText(blocker.title, "Blocker"))}</strong>
        <span class="${pillToneClass(tone)}">${escapeHtml(localizeUiText(safeText(blocker.kind, "notice"), "notice"))}</span>
      </div>
      <div class="history-note">${escapeHtml(safeText(blocker.message, "N/A"))}</div>
      ${actions}
    </article>
  `;
}

function stageStatusAction(action, label, primary = false) {
  return `
    <button
      type="button"
      class="${primary ? "button primary small" : "button ghost small"}"
      data-overview-action="${escapeHtml(action)}"
    >${escapeHtml(label)}</button>
  `;
}

function overviewPulseCard(title, value, note, tone = "muted", rows = [], options = {}) {
  const selectableAttrs = overviewSelectableAttrs(options);
  const selectableClass = options.kind ? "overview-selectable" : "";
  const selectedClass = options.selected ? "is-selected" : "";
  return `
    <article class="overview-pulse-card ${selectableClass} ${selectedClass} ${toneClass(tone)}"${selectableAttrs}>
      <div class="overview-pulse-meta">
        <strong>${escapeHtml(localizeInlineText(title, title))}</strong>
        <span class="${pillToneClass(tone)}">${escapeHtml(localizeInlineText(value, "N/A"))}</span>
      </div>
      <div class="overview-pulse-value">${escapeHtml(localizeInlineText(value, "N/A"))}</div>
      <div class="overview-pulse-note">${escapeHtml(localizeInlineText(note, "N/A"))}</div>
      <div class="overview-pulse-details">
        ${rows.map(([label, rowValue]) => `
          <div class="overview-pulse-detail">
            <span>${escapeHtml(localizeInlineText(label, label))}</span>
            <strong>${escapeHtml(localizeInlineText(rowValue, "N/A"))}</strong>
          </div>
        `).join("")}
      </div>
    </article>
  `;
}

function decorateOverviewSelectableMarkup(markup, options = {}) {
  if (!markup || !options.kind || !options.key) {
    return markup;
  }
  const selectableAttrs = overviewSelectableAttrs(options);
  const extraClasses = [
    "overview-selectable",
    options.selected ? "is-selected" : "",
  ].filter(Boolean).join(" ");
  return markup.replace(
    /<article class="([^"]+)"/,
    (_match, classes) => `<article class="${classes} ${extraClasses}"${selectableAttrs}`,
  );
}

function buildOverviewInspectorData(overview = state.overview || {}, overviewModel = buildOverviewModel(overview)) {
  const monitoring = state.monitoring || {};
  const execution = state.executionHub || {};
  const sessionSnapshot = state.session || state.liveSessionSnapshot || {};
  const dataHub = state.dataHub || {};
  const latestResearch = monitoring.latest?.research || state.latestResearchResult || state.researchHistory[0] || null;
  const latestValidation = monitoring.latest?.validation || state.latestValidationResult || state.validationHistory[0] || null;
  const latestSession = monitoring.latest?.session || sessionSnapshot || null;
  const validationSummary = latestValidation?.summary || {};
  const executionControl = execution.control || {};
  const executionSummary = execution.summary || {};
  const sessionDashboard = latestSession?.dashboard || sessionSnapshot?.dashboard || {};
  const dataMode = safeText(overview?.data?.mode || dataHub.mode, "unknown");
  const dataModeLabel = formatDataMode(dataMode);
  const dataTone = dataModeTone(dataMode);
  const dataContextTitle = localizeUiText(
    safeText(overview?.data?.source_context?.title || dataHub.source_context?.title, dataModeLabel),
    dataModeLabel,
  );
  const dataContextMessage = safeText(
    localizeUiText(
      overview?.data?.source_context?.message || dataHub.source_context?.message,
      "当前数据模式需要结合业务目标判断。",
    ),
    "当前数据模式需要结合业务目标判断。",
  );
  const validationLabel = localizeInlineText(
    validationSummary.outcome_label || validationSummary.decision,
    "未验证",
  );
  const validationTone = validationOutcomeTone(validationSummary);
  const validationReason = localizeInlineText(validationSummary.reason, "最近没有验证结论。");
  const latestResearchTitle = latestResearch
    ? localizeStrategyTitle(latestResearch.strategy, latestResearch.request?.strategy || latestResearch.strategy)
    : null;
  const executionModeLabel = formatTradingMode(executionControl.mode || executionSummary.mode || "paper");
  const executionTone = safeText(execution.status?.tone || executionControl.status_tone, "muted");
  const executionLabel = localizeUiText(
    execution.status?.session_label || execution.status?.label,
    executionControl.running ? "运行中" : "待机",
  );
  const sessionTone = safeText(sessionDashboard.status_tone, latestSession?.running ? "accent" : "muted");
  const sessionLabel = localizeUiText(
    sessionDashboard.status_label,
    latestSession?.running ? "运行中" : "已停止",
  );
  const health = monitoring.health || {};
  const servicesUp = Number(monitoring.metrics?.services_up || 0);
  const servicesTotal = Number(monitoring.metrics?.services_total || 0);
  const warningCount = Number(monitoring.metrics?.warning_events || 0);
  const errorCount = Number(monitoring.metrics?.error_events || 0);
  const telemetryPoints = Number(
    sessionSnapshot?.telemetry?.labels?.length
      || latestSession?.telemetry?.labels?.length
      || execution.telemetry?.point_count
      || 0,
  );
  const portfolioValue = monitoring.internal_metrics?.portfolio_value ?? sessionSnapshot?.portfolio?.equity ?? 0;
  const portfolioCash = monitoring.internal_metrics?.portfolio_cash ?? sessionSnapshot?.portfolio?.cash ?? 0;
  const drawdownValue = monitoring.internal_metrics?.portfolio_drawdown ?? sessionSnapshot?.portfolio?.drawdown ?? 0;

  return {
    pulseItems: [
      {
        title: "放行脉冲",
        value: validationTone === "accent" ? "纸面可运行" : validationLabel,
        note: validationTone === "accent"
          ? "验证门与数据准备已满足当前纸面执行要求。"
          : `最近验证结论为 ${validationLabel}，仍需处理放行阻塞项。`,
        tone: validationTone === "accent" ? "accent" : overviewModel.healthTone || "warning",
        rows: [
          ["验证结果", validationLabel],
          ["数据模式", dataModeLabel],
          ["服务连通", servicesTotal > 0 ? `${servicesUp}/${servicesTotal}` : "N/A"],
        ],
        actions: [],
      },
      {
        title: "执行脉冲",
        value: executionLabel,
        note: executionControl.running
          ? `会话 ${safeText(executionControl.session_id, "N/A")} 正在运行。`
          : "当前没有活跃执行终端。",
        tone: executionControl.running ? executionTone : "muted",
        rows: [
          ["模式", executionModeLabel],
          ["持仓数", safeText(sessionDashboard.open_positions, 0)],
          ["挂单数", safeText(sessionDashboard.pending_orders, 0)],
        ],
        actions: [],
      },
      {
        title: "资金脉冲",
        value: formatMetricNumber(portfolioValue, 2),
        note: executionControl.running ? "当前资金与回撤已进入实时观测。" : "当前以最近快照为准。",
        tone: Number(drawdownValue || 0) < 0 ? "warning" : "accent",
        rows: [
          ["现金", formatMetricNumber(portfolioCash, 2)],
          ["回撤", formatPercent(drawdownValue)],
          ["敞口", formatPercent(sessionDashboard.exposure_pct)],
        ],
        actions: [],
      },
      {
        title: "观测脉冲",
        value: telemetryPoints ? `${telemetryPoints} 个点` : "冷启动",
        note: servicesUp === servicesTotal
          ? "监控链路在线，可持续观察事件、延迟与组合指标。"
          : "监控链路未全通，首页信号存在降级风险。",
        tone: errorCount > 0 ? "danger" : warningCount > 0 || servicesUp < servicesTotal ? "warning" : "accent",
        rows: [
          ["警告", safeText(warningCount, 0)],
          ["错误", safeText(errorCount, 0)],
          ["会话事件", safeText(monitoring.metrics?.session_events, 0)],
        ],
        actions: [],
      },
    ],
    stageItems: [
      {
        title: "数据准备",
        value: dataModeLabel,
        note: dataContextTitle,
        tone: dataTone,
        actions: [
          { action: "open-data", label: "打开数据中心" },
          { action: "focus-research", label: "进入研究" },
        ],
      },
      {
        title: "研究回测",
        value: latestResearch ? formatDataSource(latestResearch.data_source) : "待运行",
        note: latestResearch
          ? `${safeText(latestResearchTitle, "未命名策略")} / 收益 ${formatPercent(latestResearch.summary?.total_return)} / Sharpe ${formatMetricNumber(latestResearch.summary?.sharpe_ratio)}`
          : "最近没有研究结果。",
        tone: latestResearch ? dataSourceTone(latestResearch.data_source) : "muted",
        actions: [
          { action: "open-research", label: "打开研究" },
          { action: "research-stage-execution", label: "送入执行", primary: true },
        ],
      },
      {
        title: "验证门禁",
        value: validationLabel,
        note: validationReason,
        tone: validationTone,
        actions: [
          { action: "open-validation", label: "打开验证" },
          { action: "validation-stage-execution", label: "送入执行", primary: validationTone === "accent" },
        ],
      },
      {
        title: "执行终端",
        value: executionLabel,
        note: safeText(
          executionControl.status_note,
          executionControl.running ? "执行链路在线。" : "当前没有活跃执行终端。",
        ),
        tone: executionTone,
        actions: [
          { action: "open-execution", label: "打开执行工作台" },
          { action: "open-session", label: "查看会话" },
        ],
      },
    ],
    workflowItems: [
      {
        title: "数据 -> 研究",
        badge: dataModeLabel,
        tone: dataTone,
        summary: dataContextMessage,
        rows: [
          ["交易对", safeText(dataHub.leaders?.latest_symbol?.symbol || overview?.data?.symbols?.[0]?.symbol, "BTC/USDT")],
          ["来源构成", formatSourceMix(overview?.data?.source_counts || dataHub.summary?.source_counts || {})],
          ["最近 Bar", safeText(dataHub.summary?.latest_bar_at ? dataHub.summary.latest_bar_at.slice(0, 10) : null, "N/A")],
        ],
        actions: [
          { action: "open-data", label: "检查数据" },
          { action: "focus-research", label: "运行研究", primary: true },
        ],
      },
      {
        title: "研究 -> 验证",
        badge: latestResearch ? safeText(latestResearchTitle, "待研究") : "待研究",
        tone: latestResearch ? "accent" : "muted",
        summary: latestResearch
          ? `最近研究结果已可转入验证。${safeText(latestResearch.symbol, "BTC/USDT")} 的回测结果已持久化。`
          : "需要先完成至少一次研究回测，才能形成可复用的验证输入。",
        rows: [
          ["研究结果", latestResearch ? `收益 ${formatPercent(latestResearch.summary?.total_return)}` : "暂无"],
          ["Sharpe", latestResearch ? formatMetricNumber(latestResearch.summary?.sharpe_ratio) : "N/A"],
          ["交易笔数", latestResearch ? safeText(latestResearch.summary?.num_trades, 0) : "N/A"],
        ],
        actions: [
          { action: "open-research", label: "查看研究" },
          { action: "open-validation", label: "进入验证", primary: Boolean(latestResearch) },
        ],
      },
      {
        title: "验证 -> 执行",
        badge: validationLabel,
        tone: validationTone,
        summary: validationReason,
        rows: [
          ["方法", localizeUiText(safeText(validationSummary.method_label || validationSummary.method, "Validation"))],
          ["入场数", safeText(validationSummary.entries, 0)],
          ["出场数", safeText(validationSummary.exits, 0)],
        ],
        actions: [
          { action: "open-validation", label: "查看验证" },
          { action: "validation-stage-execution", label: "送入执行", primary: validationTone === "accent" },
        ],
      },
      {
        title: "执行 -> 会话",
        badge: sessionLabel,
        tone: sessionTone,
        summary: executionControl.running
          ? "当前会话在线，可直接看到持仓、订单、事件和资金轨迹。"
          : "执行终端当前不在线，需要先从执行工作台或交易会话页启动。",
        rows: [
          ["会话 ID", safeText(executionControl.session_id || latestSession?.session_id, "N/A")],
          ["持仓数", safeText(sessionDashboard.open_positions, 0)],
          ["挂单数", safeText(sessionDashboard.pending_orders, 0)],
        ],
        actions: [
          { action: "open-execution", label: "打开执行" },
          { action: "open-session", label: "打开会话", primary: executionControl.running },
        ],
      },
    ],
    blockerItems: Array.isArray(overviewModel.blockers) ? overviewModel.blockers : [],
    healthSummary: safeText(health.summary, "暂无健康摘要"),
  };
}

function overviewInspectorCandidates(overviewModel = {}, overview = state.overview || {}) {
  const summary = {
    version: overview.version,
    phase: overview.phase,
    nextStep: overviewModel.nextStep,
    healthLabel: overviewModel.healthLabel,
    runtimeLabel: overviewModel.runtimeLabel,
    blockers: Array.isArray(overviewModel.blockerItems) ? overviewModel.blockerItems.length : 0,
  };
  return [
    {
      kind: "summary",
      key: "overview-summary",
      item: summary,
      index: 0,
    },
    ...(overviewModel.pulseItems || []).map((item, index) => ({
      kind: "pulse",
      key: overviewInspectorItemKey("pulse", item, index),
      item,
      index,
    })),
    ...(overviewModel.stageItems || []).map((item, index) => ({
      kind: "stage",
      key: overviewInspectorItemKey("stage", item, index),
      item,
      index,
    })),
    ...(overviewModel.workflowItems || []).map((item, index) => ({
      kind: "workflow",
      key: overviewInspectorItemKey("workflow", item, index),
      item,
      index,
    })),
    ...(overviewModel.blockerItems || []).map((item, index) => ({
      kind: "blocker",
      key: overviewInspectorItemKey("blocker", item, index),
      item,
      index,
    })),
  ];
}

function overviewInspectorCandidate(overviewModel = {}, overview = state.overview || {}, selection = state.overviewInspector) {
  return overviewInspectorCandidates(overviewModel, overview).find(
    (candidate) => candidate.kind === selection?.kind && candidate.key === selection?.key,
  ) || null;
}

function syncOverviewInspectorSelection(overviewModel = {}, overview = state.overview || {}) {
  const current = overviewInspectorCandidate(overviewModel, overview);
  if (current) {
    return current;
  }
  const candidates = overviewInspectorCandidates(overviewModel, overview);
  const preferred = candidates.find((candidate) => candidate.kind === "blocker")
    || candidates.find((candidate) => candidate.kind === "pulse")
    || candidates.find((candidate) => candidate.kind === "stage")
    || candidates.find((candidate) => candidate.kind === "workflow")
    || candidates.find((candidate) => candidate.kind === "summary")
    || null;
  state.overviewInspector = preferred
    ? overviewInspectorSelection(preferred.kind, preferred.key)
    : overviewInspectorSelection();
  return preferred;
}

function overviewInspectorContextMarkup(rows = []) {
  return executionInspectorContextMarkup(rows);
}

function overviewInspectorModel(candidate, overviewModel = {}, overview = state.overview || {}) {
  if (!candidate) {
    return {
      tone: "muted",
      pill: "总览摘要",
      subtitle: "聚焦总览摘要、业务脉冲、阶段、链路或阻塞项，查看它的摘要、上下文与原始对象。",
      summaryRows: [{ label: "状态", value: "等待总览对象", tone: "muted" }],
      contextRows: [],
      note: "在总览页内直接审阅关键业务信号，再决定要跳转到哪个工作台。",
      raw: overview,
    };
  }

  if (candidate.kind === "summary") {
    return {
      tone: overviewModel.healthTone || "muted",
      pill: "总览摘要",
      subtitle: "快速审阅平台阶段、下一步动作、阻塞数和运行标签。",
      summaryRows: [
        { label: "版本", value: safeText(candidate.item.version, "N/A") },
        { label: "阶段", value: safeText(candidate.item.phase, "N/A") },
        { label: "平台健康", value: safeText(candidate.item.healthLabel, "N/A"), tone: overviewModel.healthTone || "muted" },
        { label: "运行状态", value: safeText(candidate.item.runtimeLabel, "N/A"), tone: overviewModel.runtimeTone || "muted" },
        { label: "阻塞数", value: safeText(candidate.item.blockers, 0), tone: candidate.item.blockers ? "warning" : "accent" },
      ],
      contextRows: [
        { label: "下一步", value: safeText(candidate.item.nextStep, "N/A") },
        { label: "建议动作", value: overviewActionsSummary([
          ...(overviewModel.blockerItems?.[0]?.actions || []),
        ]) || "打开相关工作台" },
      ],
      note: "总览摘要用于先判定平台当前处于哪个业务推进阶段。",
      raw: {
        overview,
        summary: candidate.item,
      },
    };
  }

  if (candidate.kind === "pulse") {
    return {
      tone: safeText(candidate.item.tone, "muted"),
      pill: "业务脉冲",
      subtitle: `审阅 ${safeText(candidate.item.title, "业务脉冲")} 的状态、明细和动作建议。`,
      summaryRows: [
        { label: "对象", value: safeText(candidate.item.title, "N/A") },
        { label: "标签", value: safeText(candidate.item.value, "N/A"), tone: safeText(candidate.item.tone, "muted") },
      ],
      contextRows: (candidate.item.rows || []).map(([label, value]) => ({ label, value })),
      note: safeText(candidate.item.note, "当前脉冲卡提供的是运营级浓缩信号。"),
      raw: candidate.item,
    };
  }

  if (candidate.kind === "stage") {
    return {
      tone: safeText(candidate.item.tone, "muted"),
      pill: "业务阶段",
      subtitle: `审阅 ${safeText(candidate.item.title, "业务阶段")} 的当前状态与推荐动作。`,
      summaryRows: [
        { label: "阶段", value: safeText(candidate.item.title, "N/A") },
        { label: "状态", value: safeText(candidate.item.value, "N/A"), tone: safeText(candidate.item.tone, "muted") },
      ],
      contextRows: [
        { label: "说明", value: safeText(candidate.item.note, "N/A") },
        { label: "动作", value: overviewActionsSummary(candidate.item.actions || []) || "无" },
      ],
      note: "阶段卡反映的是当前业务工作流所处的位置。",
      raw: candidate.item,
    };
  }

  if (candidate.kind === "workflow") {
    return {
      tone: safeText(candidate.item.tone, "muted"),
      pill: "业务链路",
      subtitle: `审阅 ${safeText(candidate.item.title, "业务链路")} 的链路摘要、状态明细和后续动作。`,
      summaryRows: [
        { label: "链路", value: safeText(candidate.item.title, "N/A") },
        { label: "标签", value: safeText(candidate.item.badge, "N/A"), tone: safeText(candidate.item.tone, "muted") },
      ],
      contextRows: [
        { label: "摘要", value: safeText(candidate.item.summary, "N/A") },
        ...(candidate.item.rows || []).map(([label, value, tone = null]) => ({ label, value, tone })),
        { label: "动作", value: overviewActionsSummary(candidate.item.actions || []) || "无" },
      ],
      note: "业务链路用于把多个工作台串成一条可执行流程。",
      raw: candidate.item,
    };
  }

  return {
    tone: safeText(candidate.item.tone, "muted"),
    pill: "当前阻塞项",
    subtitle: `审阅阻塞项 ${safeText(candidate.item.title, "Blocker")} 的风险说明与处理动作。`,
    summaryRows: [
      { label: "阻塞项", value: safeText(candidate.item.title, "N/A") },
      { label: "类型", value: safeText(candidate.item.kind, "N/A"), tone: safeText(candidate.item.tone, "muted") },
    ],
    contextRows: [
      { label: "说明", value: safeText(candidate.item.message, "N/A"), tone: safeText(candidate.item.tone, "muted") },
      { label: "动作", value: overviewActionsSummary(candidate.item.actions || []) || "无" },
    ],
    note: "阻塞项优先展示会妨碍继续推进或演示闭环的问题。",
    raw: candidate.item,
  };
}

function renderOverviewInspector(overview = state.overview || {}, overviewModel = buildOverviewModel(overview)) {
  const candidate = syncOverviewInspectorSelection(overviewModel, overview);
  const model = overviewInspectorModel(candidate, overviewModel, overview);
  const pillNode = document.getElementById("overview-inspector-pill");
  pillNode.className = pillToneClass(model.tone);
  pillNode.textContent = model.pill;
  document.getElementById("overview-inspector-subtitle").textContent = model.subtitle;
  document.getElementById("overview-inspector-summary").innerHTML = model.summaryRows
    .map((row) => statusRow(row.label, row.renderedValue ?? row.value, row.tone))
    .join("");
  document.getElementById("overview-inspector-context").innerHTML = overviewInspectorContextMarkup(model.contextRows);
  document.getElementById("overview-inspector-note").textContent = model.note;
  document.getElementById("overview-inspector-json").textContent = JSON.stringify(model.raw, null, 2);
}

function selectOverviewInspector(kind = null, key = null) {
  if (!state.overview) {
    return;
  }
  state.overviewInspector = overviewInspectorSelection(kind, key);
  renderOverview(state.overview);
}

function buildOverviewModel(overview) {
  const monitoring = state.monitoring || {};
  const execution = state.executionHub || {};
  const sessionSnapshot = state.session || state.liveSessionSnapshot || {};
  const dataHub = state.dataHub || {};
  const latestResearch = monitoring.latest?.research || state.latestResearchResult || state.researchHistory[0] || null;
  const latestValidation = monitoring.latest?.validation || state.latestValidationResult || state.validationHistory[0] || null;
  const latestSession = monitoring.latest?.session || sessionSnapshot || null;

  const dataMode = safeText(overview?.data?.mode || dataHub.mode, "unknown");
  const dataModeLabel = formatDataMode(dataMode);
  const dataTone = dataModeTone(dataMode);
  const dataContextTitle = localizeUiText(
    safeText(overview?.data?.source_context?.title || dataHub.source_context?.title, dataModeLabel),
    dataModeLabel,
  );
  const dataContextMessage = safeText(
    localizeUiText(
      overview?.data?.source_context?.message || dataHub.source_context?.message,
      "当前工作区的数据模式需要结合业务目标进行判断。",
    ),
    "当前工作区的数据模式需要结合业务目标进行判断。",
  );

  const validationSummary = latestValidation?.summary || {};
  const validationLabel = localizeInlineText(
    validationSummary.outcome_label || validationSummary.decision,
    "未验证",
  );
  const validationTone = validationOutcomeTone(validationSummary);
  const validationReason = localizeInlineText(validationSummary.reason, "最近没有验证结论。");
  const latestResearchTitle = latestResearch
    ? localizeStrategyTitle(latestResearch.strategy, latestResearch.request?.strategy || latestResearch.strategy)
    : null;

  const executionControl = execution.control || {};
  const executionSummary = execution.summary || {};
  const executionModeLabel = formatTradingMode(executionControl.mode || executionSummary.mode || "paper");
  const executionTone = safeText(execution.status?.tone || executionControl.status_tone, "muted");
  const executionLabel = localizeUiText(
    execution.status?.session_label || execution.status?.label,
    executionControl.running ? "运行中" : "待机",
  );

  const sessionDashboard = latestSession?.dashboard || sessionSnapshot?.dashboard || {};
  const sessionTone = safeText(sessionDashboard.status_tone, latestSession?.running ? "accent" : "muted");
  const sessionLabel = localizeUiText(
    sessionDashboard.status_label,
    latestSession?.running ? "运行中" : "已停止",
  );

  const health = monitoring.health || {};
  const healthTone = safeText(health.overall_tone, "muted");
  const healthLabel = localizeUiText(health.overall_label, "待检测");
  const servicesUp = Number(monitoring.metrics?.services_up || 0);
  const servicesTotal = Number(monitoring.metrics?.services_total || 0);
  const warningCount = Number(monitoring.metrics?.warning_events || 0);
  const errorCount = Number(monitoring.metrics?.error_events || 0);
  const telemetryPoints = Number(
    sessionSnapshot?.telemetry?.labels?.length
      || latestSession?.telemetry?.labels?.length
      || execution.telemetry?.point_count
      || 0,
  );
  const portfolioValue = monitoring.internal_metrics?.portfolio_value ?? sessionSnapshot?.portfolio?.equity ?? 0;
  const portfolioCash = monitoring.internal_metrics?.portfolio_cash ?? sessionSnapshot?.portfolio?.cash ?? 0;
  const drawdownValue = monitoring.internal_metrics?.portfolio_drawdown ?? sessionSnapshot?.portfolio?.drawdown ?? 0;
  const servicesHealthy = servicesTotal > 0 && servicesUp === servicesTotal;
  const readinessTone = validationTone === "accent" && dataTone === "accent" && servicesHealthy
    ? "accent"
    : validationTone === "danger" || validationTone === "warning" || dataTone !== "accent" || !servicesHealthy
      ? "warning"
      : healthTone;
  const readinessValue = validationTone === "accent" ? "纸面可运行" : validationLabel;

  const heroTitle = executionControl.running
    ? `当前 ${executionModeLabel} 终端在线`
    : validationTone === "accent"
      ? "验证通过，可推进执行草稿"
      : dataTone === "accent"
        ? "市场数据已就绪，等待研究或验证"
        : "当前以前端演示与业务联调为主";

  const heroText = executionControl.running
    ? `实时会话 ${safeText(executionControl.session_id, "N/A")} 正在运行，前端已能看到持仓、订单、事件和资金轨迹。`
    : validationTone === "accent"
      ? `最近一次验证为 ${validationLabel}，可从前端直接送入执行草稿并启动纸面会话。`
      : `${dataContextMessage} 最近验证结论：${validationLabel}。`;

  const heroStats = [
    ["数据模式", dataModeLabel],
    ["验证结论", validationLabel],
    ["执行状态", executionLabel],
    ["会话事件", safeText(monitoring.metrics?.session_events, 0)],
    ["持仓数", safeText(sessionDashboard.open_positions, 0)],
    ["净敞口", formatPercent(sessionDashboard.exposure_pct)],
  ];

  const stageCards = [
    overviewStageCard(
      "数据准备",
      dataModeLabel,
      dataContextTitle,
      dataTone,
      [
        stageStatusAction("open-data", "打开数据中心"),
        stageStatusAction("focus-research", "进入研究"),
      ].join(""),
    ),
    overviewStageCard(
      "研究回测",
      latestResearch ? formatDataSource(latestResearch.data_source) : "待运行",
      latestResearch
        ? `${safeText(latestResearchTitle, "未命名策略")} · 收益率 ${formatPercent(latestResearch.summary?.total_return)} · Sharpe ${formatMetricNumber(latestResearch.summary?.sharpe_ratio)}`
        : "最近没有研究结果。",
      latestResearch ? dataSourceTone(latestResearch.data_source) : "muted",
      [
        stageStatusAction("open-research", "打开研究"),
        stageStatusAction("research-stage-execution", "送入执行", true),
      ].join(""),
    ),
    overviewStageCard(
      "验证门禁",
      validationLabel,
      validationReason,
      validationTone,
      [
        stageStatusAction("open-validation", "打开验证"),
        stageStatusAction("validation-stage-execution", "送入执行", validationTone === "accent"),
      ].join(""),
    ),
    overviewStageCard(
      "执行终端",
      executionLabel,
      safeText(
        executionControl.status_note,
        executionControl.running ? "执行链路在线。" : "当前没有活跃执行终端。",
      ),
      executionTone,
      [
        stageStatusAction("open-execution", "打开执行工作台"),
        stageStatusAction("open-session", "查看会话"),
      ].join(""),
    ),
  ];

  const workflowCards = [
    overviewWorkflowCard(
      "数据 -> 研究",
      dataModeLabel,
      dataTone,
      dataContextMessage,
      [
        ["交易对", safeText(dataHub.leaders?.latest_symbol?.symbol || overview?.data?.symbols?.[0]?.symbol, "BTC/USDT")],
        ["来源构成", formatSourceMix(overview?.data?.source_counts || dataHub.summary?.source_counts || {})],
        ["最近 Bar", safeText(dataHub.summary?.latest_bar_at ? dataHub.summary.latest_bar_at.slice(0, 10) : null, "N/A")],
      ],
      [
        stageStatusAction("open-data", "检查数据"),
        stageStatusAction("focus-research", "运行研究", true),
      ].join(""),
    ),
    overviewWorkflowCard(
      "研究 -> 验证",
      latestResearch ? safeText(latestResearchTitle, "待研究") : "待研究",
      latestResearch ? "accent" : "muted",
      latestResearch
        ? `最近研究结果已可直接转入验证。${safeText(latestResearch.symbol, "BTC/USDT")} 的回测结果已持久化。`
        : "需要先完成至少一次研究回测，才能形成可复用的验证输入。",
      [
        ["研究结果", latestResearch ? `收益率 ${formatPercent(latestResearch.summary?.total_return)}` : "暂无"],
        ["Sharpe", latestResearch ? formatMetricNumber(latestResearch.summary?.sharpe_ratio) : "N/A"],
        ["交易笔数", latestResearch ? safeText(latestResearch.summary?.num_trades, 0) : "N/A"],
      ],
      [
        stageStatusAction("open-research", "查看研究"),
        stageStatusAction("open-validation", "进入验证", Boolean(latestResearch)),
      ].join(""),
    ),
    overviewWorkflowCard(
      "验证 -> 执行",
      validationLabel,
      validationTone,
      validationReason,
      [
        ["方法", localizeUiText(safeText(validationSummary.method_label || validationSummary.method, "Validation"))],
        ["入场数", safeText(validationSummary.entries, 0)],
        ["出场数", safeText(validationSummary.exits, 0)],
      ],
      [
        stageStatusAction("open-validation", "查看验证"),
        stageStatusAction("validation-stage-execution", "送入执行", validationTone === "accent"),
      ].join(""),
    ),
    overviewWorkflowCard(
      "执行 -> 会话",
      sessionLabel,
      sessionTone,
      executionControl.running
        ? "当前会话在线，前端可直接看到持仓、订单、事件和资金轨迹。"
        : "执行终端当前不在线，需要先从执行工作台或交易会话页启动。",
      [
        ["会话 ID", safeText(executionControl.session_id || latestSession?.session_id, "N/A")],
        ["持仓数", safeText(sessionDashboard.open_positions, 0)],
        ["挂单数", safeText(sessionDashboard.pending_orders, 0)],
      ],
      [
        stageStatusAction("open-execution", "打开执行"),
        stageStatusAction("open-session", "打开会话", executionControl.running),
      ].join(""),
    ),
  ];

  const pulseCards = [
    overviewPulseCard(
      "放行脉冲",
      readinessValue,
      validationTone === "accent"
        ? "验证门与数据准备已满足当前纸面执行要求。"
        : `最近验证结论为 ${validationLabel}，仍需处理放行阻塞项。`,
      readinessTone,
      [
        ["验证结果", validationLabel],
        ["数据模式", dataModeLabel],
        ["服务连通", servicesTotal > 0 ? `${servicesUp}/${servicesTotal}` : "N/A"],
      ],
    ),
    overviewPulseCard(
      "执行脉冲",
      executionLabel,
      executionControl.running
        ? `会话 ${safeText(executionControl.session_id, "N/A")} 正在运行。`
        : "当前没有活跃执行终端，需要从执行工作台或会话页启动。",
      executionControl.running ? executionTone : "muted",
      [
        ["模式", executionModeLabel],
        ["持仓数", safeText(sessionDashboard.open_positions, 0)],
        ["挂单数", safeText(sessionDashboard.pending_orders, 0)],
      ],
    ),
    overviewPulseCard(
      "资金脉冲",
      formatMetricNumber(portfolioValue, 2),
      executionControl.running
        ? "当前资金、敞口与回撤已进入实时观测。"
        : "尚未形成实时资金闭环，当前以最近快照为准。",
      Number(drawdownValue || 0) < 0 ? "warning" : "accent",
      [
        ["现金", formatMetricNumber(portfolioCash, 2)],
        ["回撤", formatPercent(drawdownValue)],
        ["敞口", formatPercent(sessionDashboard.exposure_pct)],
      ],
    ),
    overviewPulseCard(
      "观测脉冲",
      telemetryPoints ? `${telemetryPoints} 个点` : "冷启动",
      servicesHealthy
        ? "监控链路在线，可持续观察事件、延迟与组合指标。"
        : "监控链路未全通，首页信号仍存在降级风险。",
      errorCount > 0 ? "danger" : warningCount > 0 || !servicesHealthy ? "warning" : "accent",
      [
        ["警告", safeText(warningCount, 0)],
        ["错误", safeText(errorCount, 0)],
        ["会话事件", safeText(monitoring.metrics?.session_events, 0)],
      ],
    ),
  ];

  const blockers = [];

  if (dataTone !== "accent") {
    blockers.push({
      kind: "data",
      title: dataContextTitle,
      message: dataContextMessage,
      tone: dataTone === "warning" ? "warning" : "muted",
      actions: [
        { action: "open-data", label: "打开数据中心" },
        { action: "focus-research", label: "去研究页", primary: true },
      ],
    });
  }

  if (validationTone !== "accent") {
    blockers.push({
      kind: "validation",
      title: `验证结论：${validationLabel}`,
      message: validationReason,
      tone: validationTone,
      actions: [
        { action: "open-validation", label: "查看验证" },
        { action: "validation-stage-execution", label: "送入执行草稿", primary: true },
      ],
    });
  }

  if (servicesTotal > 0 && servicesUp < servicesTotal) {
    blockers.push({
      kind: "monitoring",
      title: `监控链路未全通 (${servicesUp}/${servicesTotal})`,
      message: localizeUiText(safeText(health.summary, "当前监控链路存在不可达或降级状态。"), "当前监控链路存在不可达或降级状态。"),
      tone: healthTone === "danger" ? "danger" : "warning",
      actions: [
        { action: "open-monitoring", label: "打开监控页", primary: true },
      ],
    });
  }

  if (!executionControl.running) {
    blockers.push({
      kind: "execution",
      title: "当前没有活跃交易会话",
      message: "前端业务闭环已经具备，但要验证完整工作流，仍需要从执行工作台或交易会话页启动一个会话。",
      tone: "muted",
      actions: [
        { action: "open-execution", label: "打开执行工作台", primary: true },
        { action: "open-session", label: "打开交易会话" },
      ],
    });
  }

  let nextStep = "先补齐数据和验证，再推进执行与会话联调。";
  let nextActions = [
    stageStatusAction("open-data", "查看数据"),
    stageStatusAction("open-validation", "查看验证"),
  ];

  if (executionControl.running) {
    nextStep = "当前最适合继续观察实时会话与执行链路，再回到监控页检查可观测性。";
    nextActions = [
      stageStatusAction("open-session", "打开交易会话", true),
      stageStatusAction("open-monitoring", "打开监控页"),
    ];
  } else if (validationTone === "accent") {
    nextStep = "验证已经放行，下一步应从执行工作台启动纸面交易终端，验证前端执行闭环。";
    nextActions = [
      stageStatusAction("validation-stage-execution", "送入执行草稿", true),
      stageStatusAction("open-execution", "打开执行工作台"),
    ];
  } else if (latestResearch) {
    nextStep = "已有研究结果，但验证仍未放行。优先在验证门禁页复核最近结果，并决定是否继续演示模式运行。";
    nextActions = [
      stageStatusAction("open-validation", "打开验证", true),
      stageStatusAction("research-stage-execution", "研究结果送入执行"),
    ];
  }

  const inspectorData = buildOverviewInspectorData(overview, { blockers, healthTone });

  return {
    healthTone,
    healthLabel,
    runtimeTone: executionTone,
    runtimeLabel: executionLabel,
    heroTitle,
    heroText,
    heroStats,
    commandMetrics: [
      metricCard("数据交易对", safeText(overview?.data?.symbol_count, 0)),
      metricCard("研究次数", safeText(monitoring.metrics?.research_runs, 0)),
      metricCard("验证次数", safeText(monitoring.metrics?.validation_runs, 0)),
      metricCard("会话次数", safeText(monitoring.metrics?.session_runs, 0)),
      metricCard("持仓数", safeText(sessionDashboard.open_positions, 0)),
      metricCard("信号数", safeText(monitoring.internal_metrics?.signals_generated_total, 0)),
      metricCard("订单数", safeText(monitoring.internal_metrics?.orders_total, 0)),
      metricCard("风控事件", safeText(monitoring.internal_metrics?.risk_events_total, 0)),
    ].join(""),
    pulseCards,
    stageCards,
    workflowCards,
    pulseItems: inspectorData.pulseItems,
    stageItems: inspectorData.stageItems,
    workflowItems: inspectorData.workflowItems,
    blockerItems: inspectorData.blockerItems,
    blockers,
    nextStep,
    nextActions: nextActions.join(""),
    runtimeStatusRows: [
      statusRow("平台健康", healthLabel, healthTone),
      statusRow("实时会话", sessionLabel, sessionTone),
      statusRow("执行模式", formatTradingMode(overview?.execution?.mode), overview?.execution?.mode === "live" ? "warning" : "muted"),
      statusRow("数据模式", dataModeLabel, dataTone),
      statusRow("验证结论", validationLabel, validationTone),
      statusRow("Prometheus", `${safeText(monitoring.metrics?.services_up, 0)}/${safeText(monitoring.metrics?.services_total, 0)} 在线`, servicesUp < servicesTotal ? "warning" : "accent"),
      statusRow("组合权益", formatMetricNumber(monitoring.internal_metrics?.portfolio_value, 2)),
      statusRow("回撤", formatPercent(monitoring.internal_metrics?.portfolio_drawdown), Number(monitoring.internal_metrics?.portfolio_drawdown || 0) < 0 ? "warning" : "muted"),
    ].join(""),
    runtimeActivity: [
      activityCard("会话事件", safeText(monitoring.metrics?.session_events, 0), Number(monitoring.metrics?.session_events || 0) > 0 ? "accent" : "muted"),
      activityCard("成交数", safeText(sessionDashboard.fill_count, 0), Number(sessionDashboard.fill_count || 0) > 0 ? "accent" : "muted"),
      activityCard("警告", safeText(monitoring.metrics?.warning_events, 0), Number(monitoring.metrics?.warning_events || 0) > 0 ? "warning" : "muted"),
      activityCard("错误", safeText(monitoring.metrics?.error_events, 0), Number(monitoring.metrics?.error_events || 0) > 0 ? "danger" : "muted"),
      activityCard("净敞口", formatPercent(sessionDashboard.exposure_pct), Number(sessionDashboard.exposure_pct || 0) > 0 ? "accent" : "muted"),
      activityCard("已成交订单", safeText(monitoring.internal_metrics?.orders_filled_total, 0), Number(monitoring.internal_metrics?.orders_filled_total || 0) > 0 ? "accent" : "muted"),
    ].join(""),
  };
}

function refreshOverviewCommandDeck() {
  if (state.overview) {
    renderOverview(state.overview);
    return;
  }
  refreshPlatformChrome();
}

function renderOverview(overview) {
  state.overview = overview;
  const data = overview.data || {};
  const sourceCounts = data.source_counts || {};
  const sourceContext = data.source_context || {};
  const dataMode = safeText(data.mode, "unknown");
  const overviewModel = buildOverviewModel(overview);
  const activeOverviewInspector = syncOverviewInspectorSelection(overviewModel, overview);
  const selectedOverviewInspector = activeOverviewInspector
    ? overviewInspectorSelection(activeOverviewInspector.kind, activeOverviewInspector.key)
    : overviewInspectorSelection();
  const versionPill = document.getElementById("version-pill");
  versionPill.textContent = `v${overview.version}`;
  versionPill.dataset.state = "ready";
  document.getElementById("overview-metrics").innerHTML = [
    metricCard("策略数", overview.strategies.count),
    metricCard("数据交易对", data.symbol_count),
    metricCard("数据模式", formatDataMode(dataMode)),
    metricCard("Prometheus", overview.monitoring.prometheus_port),
    metricCard("Grafana", overview.monitoring.grafana_port),
  ].join("");
  document.getElementById("overview-captured-at").textContent = `更新时间：${formatTimestamp(new Date().toISOString())}`;
  const healthPill = document.getElementById("overview-health-pill");
  healthPill.className = pillToneClass(overviewModel.healthTone);
  healthPill.textContent = overviewModel.healthLabel;
  const runtimePill = document.getElementById("overview-runtime-pill");
  runtimePill.className = pillToneClass(overviewModel.runtimeTone);
  runtimePill.textContent = overviewModel.runtimeLabel;
  document.getElementById("overview-hero-title").textContent = overviewModel.heroTitle;
  document.getElementById("overview-hero-text").textContent = overviewModel.heroText;
  document.getElementById("overview-hero-stats").innerHTML = overviewModel.heroStats
    .map(([label, value]) => `
      <div class="hero-stat">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(String(value))}</strong>
      </div>
    `)
    .join("");
  document.getElementById("overview-command-metrics").innerHTML = overviewModel.commandMetrics;
  document.getElementById("overview-next-step").textContent = overviewModel.nextStep;
  document.getElementById("overview-next-actions").innerHTML = overviewModel.nextActions;
  document.getElementById("overview-pulse-grid").innerHTML = (overviewModel.pulseItems || []).map((item, index) => {
    const key = overviewInspectorItemKey("pulse", item, index);
    return overviewPulseCard(
      item.title,
      item.value,
      item.note,
      item.tone,
      item.rows || [],
      {
        kind: "pulse",
        key,
        selected: selectedOverviewInspector.kind === "pulse" && selectedOverviewInspector.key === key,
      },
    );
  }).join("");
  document.getElementById("overview-stage-grid").innerHTML = (overviewModel.stageItems || []).map((item, index) => {
    const key = overviewInspectorItemKey("stage", item, index);
    return overviewStageCard(
      item.title,
      item.value,
      item.note,
      item.tone,
      (item.actions || []).map((action) => stageStatusAction(action.action, action.label, Boolean(action.primary))).join(""),
      {
        kind: "stage",
        key,
        selected: selectedOverviewInspector.kind === "stage" && selectedOverviewInspector.key === key,
      },
    );
  }).join("");
  document.getElementById("overview-runtime-status").innerHTML = overviewModel.runtimeStatusRows;
  document.getElementById("overview-runtime-activity").innerHTML = overviewModel.runtimeActivity;
  document.getElementById("overview-workflow-grid").innerHTML = (overviewModel.workflowItems || []).map((item, index) => {
    const key = overviewInspectorItemKey("workflow", item, index);
    return overviewWorkflowCard(
      item.title,
      item.badge,
      item.tone,
      item.summary,
      item.rows || [],
      (item.actions || []).map((action) => stageStatusAction(action.action, action.label, Boolean(action.primary))).join(""),
      {
        kind: "workflow",
        key,
        selected: selectedOverviewInspector.kind === "workflow" && selectedOverviewInspector.key === key,
      },
    );
  }).join("");
  document.getElementById("overview-blocker-count").textContent = String(overviewModel.blockers.length);
  document.getElementById("overview-blockers").innerHTML = overviewModel.blockers.length
    ? (overviewModel.blockerItems || []).map((item, index) => {
      const key = overviewInspectorItemKey("blocker", item, index);
      return overviewBlockerCard(item, {
        kind: "blocker",
        key,
        selected: selectedOverviewInspector.kind === "blocker" && selectedOverviewInspector.key === key,
      });
    }).join("")
    : '<div class="history-empty">当前没有新的高优先级阻塞项。</div>';
  document.getElementById("docker-status").textContent = overview.docker_available ? "Docker 就绪" : "Docker 缺失";
  document.getElementById("data-count").textContent = `${data.symbol_count} 个交易对`;
  document.getElementById("system-status").innerHTML = [
    ["版本", overview.version],
    ["阶段", localizeInlineText(overview.phase, "N/A")],
    ["配置文件", configAssetLabel(overview.config_path)],
    ["Parquet", data.parquet_dir],
    ["DuckDB", data.duckdb_path],
    ["数据模式", formatDataMode(dataMode)],
    ["数据来源构成", formatSourceMix(sourceCounts)],
    ["数据说明", localizeUiText(safeText(sourceContext.title, "N/A"))],
    ["熔断开关", overview.risk.kill_switch_enabled ? "已启用" : "已禁用"],
    ["执行模式", formatTradingMode(overview.execution.mode)],
  ]
    .map(([label, value]) => statusRow(label, value))
    .join("");
  const symbols = Array.isArray(data.symbols) ? data.symbols : [];
  document.getElementById("data-symbols").innerHTML = symbols.length
    ? symbols
      .map(
        (item) => `<tr><td>${escapeHtml(safeText(item.symbol, "N/A"))}</td><td><span class="${pillToneClass(dataSourceTone(item.data_source))}">${escapeHtml(formatDataSource(item.data_source))}</span></td><td>${escapeHtml(String(safeText(item.files, 0)))}</td><td>${escapeHtml(formatDateRange(item.date_range))}</td></tr>`,
      )
      .join("")
    : tableFallback(4, "暂无数据覆盖。");
  renderOverviewInspector(overview, overviewModel);
  refreshPlatformChrome();
  persistWorkbenchState();
}

function dataLeaderCard(title, item = {}, tone = "muted", note = "", role = "latest") {
  const key = dataInspectorItemKey("leader", { ...item, leader_role: role }, 0);
  const selectable = Boolean(item && item.symbol);
  const selected = selectable
    && state.dataInspector?.kind === "leader"
    && state.dataInspector.key === key;
  const rows = item && item.symbol
    ? [
        ["交易对", safeText(item.symbol)],
        ["来源", formatDataSource(item.data_source)],
        ["文件数", safeText(item.files, 0)],
        ["开始", safeText(item.range_start ? item.range_start.slice(0, 10) : null, "N/A")],
        ["结束", safeText(item.range_end ? item.range_end.slice(0, 10) : null, "N/A")],
      ]
    : [["状态", "N/A"]];
  const actions = item && item.symbol
    ? `
      <div class="data-card-actions">
        <button type="button" class="button ghost small" data-data-action="research" data-symbol="${escapeHtml(safeText(item.symbol, "BTC/USDT"))}">打开研究</button>
        <button type="button" class="button ghost small" data-data-action="validation" data-symbol="${escapeHtml(safeText(item.symbol, "BTC/USDT"))}">打开验证</button>
        <button type="button" class="button primary small" data-data-action="execution" data-symbol="${escapeHtml(safeText(item.symbol, "BTC/USDT"))}">送入执行</button>
        ${renderSourceTagActions(item.symbol, item.data_source)}
      </div>
    `
    : "";
  const selectableAttrs = selectable
    ? ` tabindex="0" data-data-inspector-kind="leader" data-data-inspector-key="${escapeHtml(key)}"`
    : "";
  return `
    <article class="data-leader-card ${selectable ? "data-selectable" : ""} ${selected ? "is-selected" : ""} ${toneClass(tone)}"${selectableAttrs}>
      <div class="history-top">
        <strong>${escapeHtml(title)}</strong>
      </div>
      <div class="status-list compact-status-list">
        ${rows.map(([label, value]) => statusRow(label, value)).join("")}
      </div>
      ${note ? `<div class="monitoring-card-note">${escapeHtml(note)}</div>` : ""}
      ${actions}
    </article>
  `;
}

function dataInspectorSelection(kind = null, key = null) {
  return {
    kind: kind || null,
    key: key || null,
  };
}

function dataInspectorItemKey(kind, item = {}, index = 0) {
  if (kind === "summary") {
    return "data-summary";
  }
  if (kind === "leader") {
    return safeText(
      `${item.leader_role || "leader"}:${item.symbol || index}`,
      `leader:${index}`,
    );
  }
  if (kind === "symbol") {
    return safeText(item.symbol || `symbol:${index}`, `symbol:${index}`);
  }
  if (kind === "preparation") {
    return safeText(
      `${item.action || "preparation"}:${item.symbol || "N/A"}:${item.timeframe || item.data_source || index}:${item.status || "idle"}`,
      `preparation:${index}`,
    );
  }
  return `${kind || "item"}:${index}`;
}

function formatDataAgeLabel(value) {
  if (value === null || value === undefined || value === "") {
    return "待检测";
  }
  return `${value}d`;
}

function formatDataBreakdownLabel(sourceBreakdown = {}) {
  return compactMapSummary(sourceBreakdown, 4);
}

function dataPreparationTone(status = "idle") {
  if (status === "success") {
    return "accent";
  }
  if (status === "running") {
    return "warning";
  }
  if (status === "error") {
    return "danger";
  }
  return "muted";
}

function dataPreparationActionLabel(action = "") {
  if (action === "download") {
    return "历史下载";
  }
  if (action === "seed") {
    return "演示写入";
  }
  if (action === "tag-source") {
    return "来源标记";
  }
  return "数据准备";
}

function dataInspectorCandidates(payload = state.dataHub || {}) {
  const candidates = [];
  if (payload && Object.keys(payload).length) {
    candidates.push({
      kind: "summary",
      key: dataInspectorItemKey("summary"),
      item: payload,
      index: 0,
    });
  }

  const latestSymbol = payload?.leaders?.latest_symbol;
  if (latestSymbol?.symbol) {
    candidates.push({
      kind: "leader",
      key: dataInspectorItemKey("leader", { ...latestSymbol, leader_role: "latest" }, 0),
      item: {
        ...latestSymbol,
        leader_role: "latest",
        leader_title: "最新数据交易对",
        leader_note: "用于判断本地数据最近更新时间。",
      },
      index: 0,
    });
  }

  const widestSymbol = payload?.leaders?.widest_symbol;
  if (widestSymbol?.symbol) {
    candidates.push({
      kind: "leader",
      key: dataInspectorItemKey("leader", { ...widestSymbol, leader_role: "widest" }, 1),
      item: {
        ...widestSymbol,
        leader_role: "widest",
        leader_title: "覆盖最广交易对",
        leader_note: "按 parquet 分区文件数量衡量覆盖宽度。",
      },
      index: 1,
    });
  }

  const symbols = Array.isArray(payload?.symbols) ? payload.symbols : [];
  candidates.push(...symbols.map((item, index) => ({
    kind: "symbol",
    key: dataInspectorItemKey("symbol", item, index),
    item,
    index,
  })));

  const preparation = state.dataDownloadState || {};
  if (preparation.action || preparation.status !== "idle" || preparation.symbol) {
    candidates.push({
      kind: "preparation",
      key: dataInspectorItemKey("preparation", preparation, 0),
      item: preparation,
      index: 0,
    });
  }

  return candidates;
}

function dataInspectorCandidate(payload = state.dataHub || {}, selection = state.dataInspector) {
  return dataInspectorCandidates(payload).find(
    (candidate) => candidate.kind === selection?.kind && candidate.key === selection?.key,
  ) || null;
}

function syncDataInspectorSelection(payload = state.dataHub || {}) {
  const current = dataInspectorCandidate(payload);
  if (current) {
    return current;
  }

  const candidates = dataInspectorCandidates(payload);
  const preferred = candidates.find(
    (candidate) => candidate.kind === "preparation" && candidate.item?.status && candidate.item.status !== "idle",
  ) || candidates.find(
    (candidate) => candidate.kind === "leader" && candidate.item?.leader_role === "latest",
  ) || candidates.find((candidate) => candidate.kind === "symbol")
    || candidates.find((candidate) => candidate.kind === "leader")
    || candidates.find((candidate) => candidate.kind === "summary")
    || null;

  state.dataInspector = preferred
    ? dataInspectorSelection(preferred.kind, preferred.key)
    : dataInspectorSelection();
  return preferred;
}

function dataInspectorContextMarkup(rows = []) {
  return executionInspectorContextMarkup(rows);
}

function dataInspectorModel(candidate, payload = state.dataHub || {}) {
  const summary = payload.summary || {};
  const storage = payload.storage || {};
  const sourceContext = payload.source_context || {};
  const modeLabel = formatDataMode(payload.mode);
  const modeTone = dataModeTone(payload.mode);
  const workflowSymbol = safeText(
    payload.leaders?.latest_symbol?.symbol
      || payload.leaders?.widest_symbol?.symbol
      || state.terminalDraft?.symbol,
    "BTC/USDT",
  );

  if (!candidate) {
    return {
      tone: modeTone,
      pill: "数据摘要",
      subtitle: "聚焦当前数据模式、来源构成和覆盖边界。",
      summaryRows: [
        { label: "状态", value: "等待数据对象", tone: "muted" },
      ],
      contextRows: [],
      note: "先确认来源质量与覆盖边界，再把交易对推进到研究、验证或执行。",
      raw: payload,
    };
  }

  if (candidate.kind === "summary") {
    return {
      tone: modeTone,
      pill: "数据摘要",
      subtitle: "聚焦当前数据模式、来源构成和覆盖边界。",
      summaryRows: [
        { label: "数据模式", value: modeLabel, tone: modeTone },
        { label: "交易对数量", value: safeText(summary.symbol_count, 0) },
        { label: "分区文件", value: safeText(summary.files_total, 0) },
        { label: "来源构成", value: formatSourceMix(summary.source_counts), tone: modeTone },
        { label: "最新交易对", value: safeText(payload.leaders?.latest_symbol?.symbol, "待检测") },
      ],
      contextRows: [
        { label: "来源说明", value: safeText(sourceContext.title, "待检测") },
        { label: "来源备注", value: safeText(sourceContext.message, "待检测") },
        { label: "Parquet 目录", value: safeText(storage.parquet_dir, "N/A") },
        { label: "DuckDB 路径", value: safeText(storage.duckdb_path, "N/A") },
        { label: "工作流交易对", value: workflowSymbol },
      ],
      note: safeText(sourceContext.message, "先确认来源质量与覆盖边界，再把交易对推进到研究、验证或执行。"),
      raw: payload,
    };
  }

  if (candidate.kind === "leader") {
    const item = candidate.item || {};
    const tone = dataSourceTone(item.data_source);
    return {
      tone,
      pill: "覆盖焦点",
      subtitle: `当前聚焦 ${safeText(item.leader_title, "覆盖焦点")}。`,
      summaryRows: [
        { label: "焦点", value: safeText(item.leader_title, "覆盖焦点"), tone },
        { label: "交易对", value: safeText(item.symbol, "N/A") },
        { label: "来源", value: formatDataSource(item.data_source), tone },
        { label: "文件数", value: safeText(item.files, 0) },
        { label: "覆盖天数", value: safeText(item.coverage_days, "待检测") },
      ],
      contextRows: [
        { label: "开始", value: safeText(item.range_start ? item.range_start.slice(0, 10) : null, "N/A") },
        { label: "结束", value: safeText(item.range_end ? item.range_end.slice(0, 10) : null, "N/A") },
        { label: "最近 Bar 距今", value: formatDataAgeLabel(item.last_bar_age_days) },
        { label: "来源拆分", value: formatDataBreakdownLabel(item.source_breakdown) },
        { label: "建议动作", value: "研究 / 验证 / 执行" },
      ],
      note: safeText(item.leader_note, "优先从这个焦点对象判断本地数据是否足以推进下一步。"),
      raw: item,
    };
  }

  if (candidate.kind === "symbol") {
    const item = candidate.item || {};
    const tone = dataSourceTone(item.data_source);
    return {
      tone,
      pill: "交易对覆盖",
      subtitle: `审阅 ${safeText(item.symbol, "当前交易对")} 的本地覆盖范围与来源质量。`,
      summaryRows: [
        { label: "交易对", value: safeText(item.symbol, "N/A") },
        { label: "来源", value: formatDataSource(item.data_source), tone },
        { label: "文件数", value: safeText(item.files, 0) },
        { label: "覆盖天数", value: safeText(item.coverage_days, "待检测") },
        { label: "最近 Bar 距今", value: formatDataAgeLabel(item.last_bar_age_days) },
      ],
      contextRows: [
        { label: "开始", value: safeText(item.range_start ? item.range_start.slice(0, 10) : null, "N/A") },
        { label: "结束", value: safeText(item.range_end ? item.range_end.slice(0, 10) : null, "N/A") },
        { label: "来源拆分", value: formatDataBreakdownLabel(item.source_breakdown) },
        { label: "数据模式", value: modeLabel, tone: modeTone },
        { label: "建议动作", value: "研究 / 验证 / 执行" },
      ],
      note: item.data_source === "demo"
        ? "当前是演示来源，适合前端 walkthrough，不应直接作为真实市场证据。"
        : "优先确认覆盖区间与来源质量，再推进研究、验证或执行草稿。",
      raw: item,
    };
  }

  const item = candidate.item || {};
  const tone = dataPreparationTone(item.status);
  return {
    tone,
    pill: "数据准备",
    subtitle: "跟踪最近一次数据下载、演示写入或来源标记结果。",
    summaryRows: [
      { label: "状态", value: safeText(item.message, "待检测"), tone },
      { label: "操作", value: dataPreparationActionLabel(item.action), tone },
      { label: "交易对", value: safeText(item.symbol, "N/A") },
      { label: "周期", value: safeText(item.timeframe, "待检测") },
      { label: "数据来源", value: item.data_source ? formatDataSource(item.data_source) : "待检测", tone: item.data_source ? dataSourceTone(item.data_source) : null },
    ],
    contextRows: [
      { label: "已写入 Bar", value: safeText(item.rows_saved, "待检测"), tone: item.rows_saved ? "accent" : null },
      { label: "已更新文件", value: safeText(item.files_updated, "待检测"), tone: item.files_updated ? "accent" : null },
      { label: "已更新记录", value: safeText(item.rows_updated, "待检测"), tone: item.rows_updated ? "accent" : null },
      { label: "已存区间", value: item.date_range?.start || item.date_range?.end
        ? `${safeText(item.date_range?.start ? item.date_range.start.slice(0, 10) : null, "N/A")} - ${safeText(item.date_range?.end ? item.date_range.end.slice(0, 10) : null, "N/A")}`
        : "待检测" },
      { label: "下一步", value: "复核覆盖后送入研究 / 验证 / 执行" },
    ],
    note: safeText(item.message, "当前正在准备数据。"),
    raw: item,
  };
}

function renderDataLeaderGrid(payload = state.dataHub || {}) {
  const leaders = payload.leaders || {};
  document.getElementById("data-leader-grid").innerHTML = [
    dataLeaderCard(
      "最新数据交易对",
      leaders.latest_symbol || {},
      leaders.latest_symbol?.symbol ? "accent" : "muted",
      "用于判断本地数据最近更新时间。",
      "latest",
    ),
    dataLeaderCard(
      "覆盖最广交易对",
      leaders.widest_symbol || {},
      leaders.widest_symbol?.symbol ? "accent" : "muted",
      "按 parquet 分区文件数量衡量覆盖宽度。",
      "widest",
    ),
  ].join("");
}

function renderDataSymbolRows(payload = state.dataHub || {}) {
  const symbols = Array.isArray(payload.symbols) ? payload.symbols : [];
  document.getElementById("data-symbol-count").textContent = String(symbols.length);
  document.getElementById("data-symbol-rows").innerHTML = symbols.length
    ? symbols
      .map((item, index) => {
        const key = dataInspectorItemKey("symbol", item, index);
        const selected = state.dataInspector?.kind === "symbol" && state.dataInspector.key === key;
        return `
          <tr class="data-selectable ${selected ? "is-selected" : ""}" tabindex="0" data-data-inspector-kind="symbol" data-data-inspector-key="${escapeHtml(key)}">
            <td>${escapeHtml(safeText(item.symbol, "N/A"))}</td>
            <td><span class="${pillToneClass(dataSourceTone(item.data_source))}">${escapeHtml(formatDataSource(item.data_source))}</span></td>
            <td>${escapeHtml(String(safeText(item.files, 0)))}</td>
            <td>${escapeHtml(safeText(item.range_start ? item.range_start.slice(0, 10) : null, "N/A"))}</td>
            <td>${escapeHtml(safeText(item.range_end ? item.range_end.slice(0, 10) : null, "N/A"))}</td>
            <td>${escapeHtml(String(safeText(item.coverage_days, "N/A")))}</td>
            <td>${escapeHtml(item.last_bar_age_days === null || item.last_bar_age_days === undefined ? "N/A" : `${item.last_bar_age_days}d`)}</td>
            <td>
              <div class="table-actions">
                <button type="button" class="button ghost small" data-data-action="research" data-symbol="${escapeHtml(safeText(item.symbol, "BTC/USDT"))}">研究</button>
                <button type="button" class="button ghost small" data-data-action="validation" data-symbol="${escapeHtml(safeText(item.symbol, "BTC/USDT"))}">验证</button>
                <button type="button" class="button primary small" data-data-action="execution" data-symbol="${escapeHtml(safeText(item.symbol, "BTC/USDT"))}">执行</button>
                ${renderSourceTagActions(item.symbol, item.data_source, { compact: true })}
              </div>
            </td>
          </tr>
        `;
      })
      .join("")
    : tableFallback(8, "暂无本地 parquet 交易对数据。");
}

function renderDataInspector(payload = state.dataHub || {}) {
  const candidate = syncDataInspectorSelection(payload);
  const model = dataInspectorModel(candidate, payload);
  const pillNode = document.getElementById("data-inspector-pill");
  pillNode.className = pillToneClass(model.tone);
  pillNode.textContent = model.pill;
  document.getElementById("data-inspector-subtitle").textContent = model.subtitle;
  document.getElementById("data-inspector-summary").innerHTML = model.summaryRows
    .map((row) => statusRow(row.label, row.value, row.tone))
    .join("");
  document.getElementById("data-inspector-context").innerHTML = dataInspectorContextMarkup(model.contextRows);
  document.getElementById("data-inspector-note").textContent = model.note;
  document.getElementById("data-inspector-json").textContent = JSON.stringify(model.raw, null, 2);
}

function refreshDataInspectorSurfaces(payload = state.dataHub || {}) {
  renderDataDownloadState();
  renderDataLeaderGrid(payload);
  renderDataSymbolRows(payload);
  renderDataInspector(payload);
}

function renderDataHub(payload) {
  state.dataHub = payload;
  const summary = payload.summary || {};
  const storage = payload.storage || {};
  const leaders = payload.leaders || {};
  const mode = safeText(payload.mode, "unknown");
  const sourceCounts = summary.source_counts || {};
  const sourceContext = payload.source_context || {};
  const modeTone = dataModeTone(mode);
  const modeLabel = formatDataMode(mode);
  const symbolCount = safeText(summary.symbol_count, 0);
  const filesTotal = safeText(summary.files_total, 0);
  const sourceTitle = localizeUiText(safeText(sourceContext.title, modeLabel), modeLabel);
  const sourceMessage = safeText(
    localizeUiText(
      sourceContext.message,
      symbolCount
        ? "当前工作区的数据覆盖已经可以支撑研究、验证和会话回放。"
        : "当前工作区的数据覆盖尚未准备完成。",
    ),
    symbolCount
      ? "当前工作区的数据覆盖已经可以支撑研究、验证和会话回放。"
      : "当前工作区的数据覆盖尚未准备完成。",
  );

  document.getElementById("data-captured-at").textContent = `更新时间：${formatTimestamp(payload.captured_at)}`;
  const modePill = document.getElementById("data-mode-pill");
  modePill.className = pillToneClass(modeTone);
  modePill.textContent = modeLabel;

  document.getElementById("data-hero-title").textContent = symbolCount
    ? `${sourceTitle} · ${symbolCount} 个交易对，${filesTotal} 个分区文件`
    : sourceTitle;
  document.getElementById("data-hero-text").textContent = sourceMessage;

  const highlights = Array.isArray(payload.highlights) ? payload.highlights : [];
  document.getElementById("data-highlights").innerHTML = highlights.length
    ? highlights
      .map(
        (message, index) => `
          <article class="data-highlight ${toneClass(index === 0 ? modeTone : "muted")}">
            <span class="data-highlight-marker"></span>
            <span>${escapeHtml(localizeUiText(message, message))}</span>
          </article>
        `,
      )
      .join("")
    : '<div class="history-empty">暂无数据亮点。</div>';

  document.getElementById("data-metrics").innerHTML = [
    metricCard("交易对数量", symbolCount),
    metricCard("分区文件", filesTotal),
    metricCard("实盘交易对", safeText(summary.market_symbol_count, 0)),
    metricCard("演示交易对", safeText(summary.demo_symbol_count, 0)),
    metricCard("未知来源交易对", safeText(summary.unknown_symbol_count, 0)),
    metricCard("混合来源交易对", safeText(summary.hybrid_symbol_count, 0)),
    metricCard("最早 Bar", safeText(summary.earliest_bar_at ? summary.earliest_bar_at.slice(0, 10) : null, "N/A")),
    metricCard("最新 Bar", safeText(summary.latest_bar_at ? summary.latest_bar_at.slice(0, 10) : null, "N/A")),
  ].join("");

  document.getElementById("data-storage-status").innerHTML = [
    statusRow("数据模式", modeLabel, modeTone),
    statusRow("来源构成", formatSourceMix(sourceCounts), Object.keys(sourceCounts).length ? modeTone : "muted"),
    statusRow("来源说明", localizeUiText(safeText(sourceContext.title, "N/A"))),
    statusRow("Parquet 目录", safeText(storage.parquet_dir, "N/A")),
    statusRow("DuckDB 路径", safeText(storage.duckdb_path, "N/A")),
    statusRow("配置文件", configAssetLabel(storage.config_path)),
    statusRow("执行模式", formatTradingMode(storage.execution_mode), storage.execution_mode === "live" ? "warning" : "muted"),
    statusRow("Parquet 根目录存在", summary.parquet_root_exists ? "是" : "否", summary.parquet_root_exists ? "accent" : "warning"),
    statusRow("DuckDB 文件存在", summary.duckdb_exists ? "是" : "否", summary.duckdb_exists ? "accent" : "warning"),
  ].join("");

  const workflowSymbol = safeText(
    leaders.latest_symbol?.symbol
      || leaders.widest_symbol?.symbol
      || state.terminalDraft?.symbol
      || state.session?.request?.symbol,
    "BTC/USDT",
  );
  document.getElementById("data-workflow-note").textContent = symbolCount
    ? `${sourceMessage} 围绕 ${workflowSymbol} 继续推进研究、验证与执行工作流。`
    : `${sourceMessage} 可先围绕 ${workflowSymbol} 下载历史行情或写入演示数据。`;
  document.getElementById("data-workflow-actions").innerHTML = `
    <button type="button" class="button ghost small" data-data-action="research" data-symbol="${escapeHtml(workflowSymbol)}">打开研究</button>
    <button type="button" class="button ghost small" data-data-action="validation" data-symbol="${escapeHtml(workflowSymbol)}">打开验证</button>
    <button type="button" class="button primary small" data-data-action="execution" data-symbol="${escapeHtml(workflowSymbol)}">送入执行</button>
    ${renderSourceTagActions(workflowSymbol, leaders.latest_symbol?.data_source)}
  `;
  syncDataDownloadForm(workflowSymbol);
  refreshDataInspectorSurfaces(payload);
  refreshOverviewCommandDeck();
}

function compactMapSummary(items = {}, limit = 3) {
  const entries = Object.entries(items || {})
    .filter(([, value]) => Number(value) > 0)
    .sort((left, right) => Number(right[1]) - Number(left[1]));
  if (!entries.length) {
    return "无";
  }
  return entries
    .slice(0, limit)
    .map(([label, value]) => `${localizeUiText(label, label)} ${value}`)
    .join(" · ");
}

function syncDataDownloadForm(defaultSymbol = "BTC/USDT") {
  const form = document.getElementById("data-download-form");
  if (!form) {
    return;
  }

  const symbolInput = form.elements.symbol;
  const timeframeSelect = form.elements.timeframe;
  const startInput = form.elements.start;
  const endInput = form.elements.end;
  const today = new Date();
  const yearAgo = new Date(today);
  yearAgo.setUTCDate(yearAgo.getUTCDate() - 365);

  if (symbolInput && !symbolInput.value) {
    symbolInput.value = defaultSymbol;
  }
  if (timeframeSelect && !timeframeSelect.value) {
    timeframeSelect.value = "4h";
  }
  if (startInput && !startInput.value) {
    startInput.value = formatDateInput(yearAgo.toISOString());
  }
  if (endInput && !endInput.value) {
    endInput.value = formatDateInput(today.toISOString());
  }
}

function renderDataDownloadState() {
  const statusNode = document.getElementById("data-download-status");
  const summaryNode = document.getElementById("data-download-summary");
  const submitNode = document.getElementById("data-download-submit");
  const seedNode = document.getElementById("data-seed-demo");
  const downloadState = state.dataDownloadState || {
    status: "idle",
    message: "尚未开始下载历史行情。",
  };
  const toneByStatus = {
    idle: "muted",
    running: "warning",
    success: "accent",
    error: "danger",
  };
  const labelByStatus = {
    idle: "未启动",
    running: "下载中",
    success: "已完成",
    error: "失败",
  };
  const tone = toneByStatus[downloadState.status] || "muted";

  statusNode.className = pillToneClass(tone);
  statusNode.textContent = labelByStatus[downloadState.status] || "未启动";
  submitNode.disabled = downloadState.status === "running";
  seedNode.disabled = downloadState.status === "running";
  submitNode.textContent = downloadState.status === "running" && downloadState.action === "download"
    ? "下载中..."
    : "拉取历史行情";
  seedNode.textContent = downloadState.status === "running" && downloadState.action === "seed"
    ? "写入中..."
    : "写入演示数据";

  const rows = [
    ["状态", safeText(downloadState.message, "尚未开始下载历史行情。"), tone],
  ];
  if (downloadState.symbol) {
    rows.push(["交易对", safeText(downloadState.symbol, "N/A")]);
  }
  if (downloadState.timeframe) {
    rows.push(["周期", safeText(downloadState.timeframe, "N/A")]);
  }
  if (downloadState.data_source) {
    rows.push(["数据来源", formatDataSource(downloadState.data_source), dataSourceTone(downloadState.data_source)]);
  }
  if (downloadState.rows_saved !== undefined) {
    rows.push([
      "已写入 Bar",
      safeText(downloadState.rows_saved, 0),
      downloadState.rows_saved ? "accent" : "warning",
    ]);
  }
  if (downloadState.files_updated !== undefined) {
    rows.push([
      "已更新文件",
      safeText(downloadState.files_updated, 0),
      downloadState.files_updated ? "accent" : "warning",
    ]);
  }
  if (downloadState.rows_updated !== undefined) {
    rows.push([
      "已更新记录",
      safeText(downloadState.rows_updated, 0),
      downloadState.rows_updated ? "accent" : "warning",
    ]);
  }
  if (downloadState.date_range?.start || downloadState.date_range?.end) {
    rows.push([
      "已存区间",
      `${safeText(downloadState.date_range?.start ? downloadState.date_range.start.slice(0, 10) : null, "N/A")} - ${safeText(downloadState.date_range?.end ? downloadState.date_range.end.slice(0, 10) : null, "N/A")}`,
    ]);
  }
  summaryNode.innerHTML = rows
    .map(([label, value, rowTone = null]) => statusRow(label, value, rowTone))
    .join("");
}

function refreshDataPreparationState() {
  if (state.dataHub) {
    refreshDataInspectorSurfaces(state.dataHub);
    return;
  }
  renderDataDownloadState();
}

async function tagDataSource(symbol, dataSource) {
  const resolvedSymbol = safeText(symbol, "BTC/USDT");
  state.dataDownloadState = {
    status: "running",
    action: "tag-source",
    symbol: resolvedSymbol,
    data_source: dataSource,
    message: `正在将 ${resolvedSymbol} 标记为 ${formatDataSource(dataSource)}。`,
  };
  refreshDataPreparationState();

  try {
    const result = await api("/api/data/tag-source", {
      method: "POST",
      body: JSON.stringify({
        symbol: resolvedSymbol,
        data_source: dataSource,
      }),
    });
    state.dataDownloadState = {
      status: "success",
      action: "tag-source",
      ...result,
    };
    await loadOverview();
    await loadDataHub();
    await loadMonitoring();
    refreshDataPreparationState();
    return true;
  } catch (error) {
    state.dataDownloadState = {
      status: "error",
      action: "tag-source",
      symbol: resolvedSymbol,
      data_source: dataSource,
      message: error.message,
    };
    refreshDataPreparationState();
    return false;
  }
}

async function runDataPreparation(endpoint, payload, pendingMessage, action) {
  state.dataDownloadState = {
    status: "running",
    action,
    message: pendingMessage,
    symbol: payload.symbol,
    timeframe: payload.timeframe,
  };
  refreshDataPreparationState();

  try {
    const result = await api(endpoint, {
      method: "POST",
      body: JSON.stringify(payload),
    });
    state.dataDownloadState = {
      status: "success",
      action,
      ...result,
    };
    await loadOverview();
    await loadDataHub();
    await loadMonitoring();
    refreshDataPreparationState();
    return result;
  } catch (error) {
    state.dataDownloadState = {
      status: "error",
      action,
      message: error.message,
      symbol: payload.symbol,
      timeframe: payload.timeframe,
    };
    refreshDataPreparationState();
    return null;
  }
}

function monitoringServiceCard(service = {}, options = {}) {
  const tone = safeText(service.tone, "muted");
  const port = service.port ? `:${service.port}` : "N/A";
  const link = service.url
    ? `<a class="monitoring-service-link" href="${escapeHtml(service.url)}" target="_blank" rel="noreferrer">${escapeHtml(service.url)}</a>`
    : '<span class="monitoring-service-link disabled">未提供地址</span>';
  const selectable = Boolean(options.kind && options.key);
  const selectableAttrs = selectable
    ? ` tabindex="0" data-monitoring-inspector-kind="${escapeHtml(options.kind)}" data-monitoring-inspector-key="${escapeHtml(options.key)}"`
    : "";
  const detailTags = [
    service.status_kind && service.status_kind !== "reachable"
      ? localizeUiText(service.status_kind.replaceAll("_", " "))
      : null,
    service.attempted ? localizeUiText("attempted") : null,
    service.started_in_process ? localizeUiText("in-process") : null,
    service.registry_available ? localizeUiText("registry") : null,
  ].filter(Boolean);
  return `
    <article class="monitoring-service-card ${selectable ? "monitoring-selectable" : ""} ${options.selected ? "is-selected" : ""} ${toneClass(tone)}"${selectableAttrs}>
      <div class="history-top">
        <strong>${escapeHtml(localizeUiText(safeText(service.label, "Service"), "Service"))}</strong>
        <span class="${pillToneClass(tone)}">${escapeHtml(localizeUiText(safeText(service.status_label, "Unknown"), "Unknown"))}</span>
      </div>
      <div class="history-meta">${escapeHtml(localizeUiText(safeText(service.note, "Operator endpoint"), "Operator endpoint"))}</div>
      ${service.status_hint ? `<div class="history-note">${escapeHtml(localizeUiText(service.status_hint, service.status_hint))}</div>` : ""}
      <div class="monitoring-service-meta">
        <span class="tag">${escapeHtml(port)}</span>
        <span class="tag">${escapeHtml(localizeUiText(safeText(service.service_id, "service"), "service"))}</span>
        ${detailTags.map((tag) => `<span class="tag">${escapeHtml(tag)}</span>`).join("")}
      </div>
      <div class="monitoring-service-link-row">${link}</div>
      ${service.last_error ? `<div class="monitoring-card-note">${escapeHtml(localizeUiText(service.last_error, service.last_error))}</div>` : ""}
    </article>
  `;
}

function monitoringLatestCard(title, badgeText, badgeTone, meta, rows, note = "", actions = "", options = {}) {
  const content = Array.isArray(rows) && rows.length
    ? rows.map(([label, value, tone = null]) => statusRow(label, value, tone)).join("")
    : statusRow("状态", "N/A");
  const selectable = Boolean(options.kind && options.key);
  const selectableAttrs = selectable
    ? ` tabindex="0" data-monitoring-inspector-kind="${escapeHtml(options.kind)}" data-monitoring-inspector-key="${escapeHtml(options.key)}"`
    : "";
  return `
    <article class="monitoring-latest-card ${selectable ? "monitoring-selectable" : ""} ${options.selected ? "is-selected" : ""} ${toneClass(badgeTone || "muted")}"${selectableAttrs}>
      <div class="history-top">
        <strong>${escapeHtml(localizeInlineText(title, title))}</strong>
        <span class="${pillToneClass(badgeTone)}">${escapeHtml(localizeInlineText(badgeText, "N/A"))}</span>
      </div>
      <div class="history-meta">${escapeHtml(localizeInlineText(meta, "N/A"))}</div>
      <div class="status-list compact-status-list">${content}</div>
      ${note ? `<div class="monitoring-card-note">${escapeHtml(localizeInlineText(note, note))}</div>` : ""}
      ${actions ? `<div class="history-actions result-actions">${actions}</div>` : ""}
    </article>
  `;
}

function monitoringInspectorSelection(kind = null, key = null) {
  return {
    kind: kind || null,
    key: key || null,
  };
}

function monitoringInspectorItemKey(kind, item = {}, index = 0) {
  if (kind === "summary") {
    return "monitoring-summary";
  }
  if (kind === "runtime") {
    return "monitoring-runtime";
  }
  if (kind === "service") {
    return safeText(
      item.service_id || `${item.label || "service"}:${item.port || index}`,
      `service:${index}`,
    );
  }
  if (kind === "latest") {
    return safeText(
      `${item.latest_kind || "latest"}:${item.record_id || item.session_id || item.strategy || item.symbol || item.created_at || index}`,
      `latest:${index}`,
    );
  }
  if (kind === "alert") {
    return safeText(
      `${item.source || "alert"}:${item.title || index}:${item.created_at || ""}`,
      `alert:${index}`,
    );
  }
  return `${kind || "item"}:${index}`;
}

function monitoringInspectorCandidates(payload = state.monitoring || {}) {
  const candidates = [];
  if (payload && Object.keys(payload).length) {
    candidates.push({
      kind: "summary",
      key: monitoringInspectorItemKey("summary"),
      item: payload,
      index: 0,
    });
  }

  const runtimePayload = {
    health: payload.health || {},
    metrics: payload.metrics || {},
    platform: payload.platform || {},
    runtime: payload.runtime || {},
    activity: payload.activity || {},
    internal_metrics: payload.internal_metrics || {},
  };
  if (Object.values(runtimePayload).some((item) => item && Object.keys(item).length)) {
    candidates.push({
      kind: "runtime",
      key: monitoringInspectorItemKey("runtime"),
      item: runtimePayload,
      index: 0,
    });
  }

  const services = Array.isArray(payload.services) ? payload.services : [];
  candidates.push(...services.map((item, index) => ({
    kind: "service",
    key: monitoringInspectorItemKey("service", item, index),
    item,
    index,
  })));

  const latest = payload.latest || {};
  [
    ["research", latest.research, "最近研究"],
    ["validation", latest.validation, "最近验证"],
    ["session", latest.session, "最近会话"],
  ].forEach(([latestKind, item, latestTitle], index) => {
    if (item && typeof item === "object" && Object.keys(item).length) {
      candidates.push({
        kind: "latest",
        key: monitoringInspectorItemKey("latest", { ...item, latest_kind: latestKind }, index),
        item: {
          ...item,
          latest_kind: latestKind,
          latest_title: latestTitle,
        },
        index,
      });
    }
  });

  const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
  candidates.push(...alerts.map((item, index) => ({
    kind: "alert",
    key: monitoringInspectorItemKey("alert", item, index),
    item,
    index,
  })));

  return candidates;
}

function monitoringInspectorCandidate(payload = state.monitoring || {}, selection = state.monitoringInspector) {
  return monitoringInspectorCandidates(payload).find(
    (candidate) => candidate.kind === selection?.kind && candidate.key === selection?.key,
  ) || null;
}

function syncMonitoringInspectorSelection(payload = state.monitoring || {}) {
  const current = monitoringInspectorCandidate(payload);
  if (current) {
    return current;
  }

  const candidates = monitoringInspectorCandidates(payload);
  const preferred = candidates.find(
    (candidate) => candidate.kind === "alert" && safeText(candidate.item?.tone, "muted") === "danger",
  ) || candidates.find(
    (candidate) => candidate.kind === "alert" && safeText(candidate.item?.tone, "muted") === "warning",
  ) || candidates.find(
    (candidate) => candidate.kind === "service" && ["warning", "danger"].includes(safeText(candidate.item?.tone, "muted")),
  ) || candidates.find(
    (candidate) => candidate.kind === "latest" && candidate.item?.latest_kind === "validation",
  ) || candidates.find(
    (candidate) => candidate.kind === "latest" && candidate.item?.latest_kind === "session",
  ) || candidates.find(
    (candidate) => candidate.kind === "latest" && candidate.item?.latest_kind === "research",
  ) || candidates.find((candidate) => candidate.kind === "runtime")
    || candidates.find((candidate) => candidate.kind === "summary")
    || null;

  state.monitoringInspector = preferred
    ? monitoringInspectorSelection(preferred.kind, preferred.key)
    : monitoringInspectorSelection();
  return preferred;
}

function monitoringInspectorContextMarkup(rows = []) {
  return executionInspectorContextMarkup(rows);
}

function monitoringAlertActionHint(source = "") {
  if (source === "validation") {
    return "打开验证并决定是否继续送入执行草稿。";
  }
  if (source === "session") {
    return "打开交易会话或执行工作台，核对当前运行状态。";
  }
  if (source === "data") {
    return "回到数据中心确认来源标签与数据覆盖边界。";
  }
  if (source === "platform") {
    return "继续留在监控运维页，确认平台级链路是否恢复。";
  }
  return "结合监控上下文决定下一步联调动作。";
}

function monitoringInspectorModel(candidate, payload = state.monitoring || {}) {
  const health = payload.health || {};
  const metrics = payload.metrics || {};
  const platform = payload.platform || {};
  const runtime = payload.runtime || {};
  const activity = payload.activity || {};
  const latest = payload.latest || {};
  const internal = payload.internal_metrics || {};
  const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
  const healthTone = safeText(health.overall_tone, "muted");

  if (!candidate) {
    return {
      tone: healthTone,
      pill: "监控摘要",
      subtitle: "聚焦平台健康、服务可达性、运行状态和最新业务对象。",
      summaryRows: [
        { label: "状态", value: "等待监控对象", tone: "muted" },
      ],
      contextRows: [],
      note: "先确认服务、告警和最新业务对象，再决定是否继续推进验证、执行或会话联调。",
      raw: payload,
    };
  }

  if (candidate.kind === "summary") {
    return {
      tone: healthTone,
      pill: "监控摘要",
      subtitle: "聚焦平台健康、服务连通、告警数量和最近业务快照。",
      summaryRows: [
        { label: "平台健康", value: localizeUiText(safeText(health.overall_label, "Unknown"), "Unknown"), tone: healthTone },
        { label: "服务连通", value: `${safeText(metrics.services_up, 0)}/${safeText(metrics.services_total, 0)}` },
        { label: "验证不通过", value: safeText(metrics.validation_no_go, 0), tone: metrics.validation_no_go ? "warning" : "muted" },
        { label: "告警数", value: String(alerts.length), tone: alerts.length ? "warning" : "muted" },
        { label: "会话事件", value: safeText(metrics.session_events, 0), tone: metrics.session_events ? "accent" : "muted" },
      ],
      contextRows: [
        { label: "监控摘要", value: safeText(health.summary, "暂无监控摘要。") },
        { label: "执行模式", value: formatTradingMode(platform.execution_mode), tone: platform.execution_mode === "live" ? "warning" : "muted" },
        { label: "数据模式", value: formatDataMode(platform.data_mode), tone: dataModeTone(platform.data_mode) },
        { label: "最近研究", value: latest.research ? `${localizeStrategyTitle(latest.research.strategy, latest.research.request?.strategy || latest.research.strategy)} / ${safeText(latest.research.symbol, "N/A")}` : "暂无" },
        { label: "最近验证", value: latest.validation ? localizeUiText(safeText(latest.validation.summary?.outcome_label || latest.validation.summary?.decision, "暂无"), "暂无") : "暂无", tone: latest.validation ? validationOutcomeTone(latest.validation.summary || {}) : "muted" },
        { label: "最近会话", value: latest.session?.running ? "运行中" : "未运行", tone: latest.session?.running ? "accent" : "muted" },
      ],
      note: safeText(health.summary, "先确认监控链路与最新业务状态。"),
      raw: payload,
    };
  }

  if (candidate.kind === "runtime") {
    const item = candidate.item || {};
    const tone = safeText(item.runtime?.status_tone, healthTone);
    return {
      tone,
      pill: "运行摘要",
      subtitle: "审阅当前受管会话、平台姿态和事件分布，判断是否满足联调条件。",
      summaryRows: [
        { label: "对象", value: "运行摘要", tone: "muted" },
        { label: "会话状态", value: localizeUiText(safeText(item.runtime?.status_label, "Stopped"), "Stopped"), tone },
        { label: "会话 ID", value: safeText(item.runtime?.session_id, "N/A") },
        { label: "持仓数量", value: safeText(item.runtime?.open_positions, 0), tone: item.runtime?.open_positions ? "accent" : "muted" },
        { label: "挂单数量", value: safeText(item.runtime?.pending_orders, 0), tone: item.runtime?.pending_orders ? "warning" : "muted" },
        { label: "组合权益", value: formatMetricNumber(item.internal_metrics?.portfolio_value, 2) },
      ],
      contextRows: [
        { label: "版本", value: safeText(item.platform?.version, "N/A") },
        { label: "阶段", value: safeText(item.platform?.phase, "N/A") },
        { label: "执行模式", value: formatTradingMode(item.platform?.execution_mode), tone: item.platform?.execution_mode === "live" ? "warning" : "muted" },
        { label: "数据模式", value: formatDataMode(item.platform?.data_mode), tone: dataModeTone(item.platform?.data_mode) },
        { label: "来源构成", value: formatSourceMix(item.platform?.source_counts), tone: dataModeTone(item.platform?.data_mode) },
        { label: "事件类型", value: compactMapSummary(item.activity?.event_types) },
        { label: "验证分布", value: compactMapSummary(item.activity?.validation_outcomes) },
        { key: "drawdown", label: "回撤", renderedValue: formatPercent(item.internal_metrics?.portfolio_drawdown) },
      ],
      note: item.runtime?.active_session
        ? "当前监控已经对齐到受管会话，可继续切到执行工作台或交易会话做联调。"
        : "当前没有活跃会话，适合先处理验证结论或监控告警，再启动纸面终端。",
      raw: item,
    };
  }

  if (candidate.kind === "service") {
    const item = candidate.item || {};
    const tone = safeText(item.tone, "muted");
    const detailTags = [
      item.status_kind && item.status_kind !== "reachable" ? item.status_kind.replaceAll("_", " ") : null,
      item.attempted ? "attempted" : null,
      item.started_in_process ? "in-process" : null,
      item.registry_available ? "registry" : null,
    ].filter(Boolean);
    return {
      tone,
      pill: "服务节点",
      subtitle: `审阅 ${safeText(item.label, "监控服务")} 的可达状态、入口地址和运行提示。`,
      summaryRows: [
        { label: "对象", value: "服务节点", tone: "muted" },
        { label: "服务", value: safeText(item.label, "N/A") },
        { label: "状态", value: localizeUiText(safeText(item.status_label, "Unknown"), "Unknown"), tone },
        { label: "端口", value: item.port ? `:${item.port}` : "N/A" },
        { label: "标识", value: safeText(item.service_id, "N/A") },
      ],
      contextRows: [
        { label: "入口地址", value: safeText(item.url, "未提供地址") },
        { label: "节点说明", value: safeText(item.note, "暂无说明") },
        { label: "状态提示", value: safeText(item.status_hint, "暂无提示") },
        { label: "细节标签", value: detailTags.length ? detailTags.join(", ") : "无" },
        { label: "最近错误", value: safeText(item.last_error, "无"), tone: item.last_error ? "danger" : "muted" },
      ],
      note: `先确认 ${safeText(item.label, "该服务")} 可达，再依赖它提供的监控证据做放行判断。`,
      raw: item,
    };
  }

  if (candidate.kind === "latest") {
    const item = candidate.item || {};
    if (item.latest_kind === "research") {
      const tone = dataSourceTone(item.data_source);
      return {
        tone,
        pill: "研究快照",
        subtitle: "审阅最近一次研究结果，确认它是否仍适合作为验证或执行的上游输入。",
        summaryRows: [
          { label: "对象", value: "最近研究", tone: "muted" },
          { label: "策略", value: localizeStrategyTitle(item.strategy, item.request?.strategy || item.strategy) },
          { label: "交易对", value: safeText(item.symbol, "N/A") },
          { label: "数据源", value: formatDataSource(item.data_source), tone },
          { key: "return", label: "收益率", renderedValue: formatPercent(item.summary?.total_return) },
          { key: "sharpe", label: "Sharpe", renderedValue: formatMetricNumber(item.summary?.sharpe_ratio) },
        ],
        contextRows: [
          { key: "drawdown", label: "最大回撤", renderedValue: formatPercent(item.summary?.max_drawdown) },
          { label: "交易笔数", value: safeText(item.summary?.num_trades, 0) },
          { label: "样本区间", value: researchPeriodText(item) },
          { label: "创建时间", value: formatTimestamp(item.created_at) },
          { label: "下一步", value: item.request ? "打开研究 / 送入执行草稿" : "回到研究页补全结果上下文" },
        ],
        note: item.request
          ? "研究结果已经进入监控视角，可直接跳回研究页复盘，或继续送入执行草稿。"
          : "当前只有研究概览快照，若要继续推进，需要回到研究页补全上下文。",
        raw: item,
      };
    }

    if (item.latest_kind === "validation") {
      const summary = item.summary || {};
      const tone = validationOutcomeTone(summary);
      return {
        tone,
        pill: "验证快照",
        subtitle: "审阅最近一次验证门禁结果，确认它是否阻塞执行或允许继续推进。",
        summaryRows: [
          { label: "对象", value: "最近验证", tone: "muted" },
          { label: "结论", value: localizeUiText(safeText(summary.outcome_label || summary.decision, "待检测"), "待检测"), tone },
          { label: "方法", value: localizeUiText(safeText(summary.method_label, summary.method || "Validation"), "Validation") },
          { label: "交易对", value: safeText(item.symbol, "N/A") },
          { label: "入场数", value: safeText(summary.entries, 0) },
          { label: "出场数", value: safeText(summary.exits, 0) },
        ],
        contextRows: [
          { label: "原因", value: safeText(summary.reason, "暂无原因"), tone: tone === "accent" ? "muted" : tone },
          { label: "核心指标", value: validationHistoryPrimaryMetric(summary) },
          { label: "Bar 数", value: safeText(summary.bars, 0) },
          { label: "数据源", value: item.data_source ? formatDataSource(item.data_source) : "待检测", tone: item.data_source ? dataSourceTone(item.data_source) : "muted" },
          { label: "创建时间", value: formatTimestamp(item.created_at) },
        ],
        note: tone === "accent"
          ? "验证门禁当前允许继续推进，可以直接送入执行草稿并进入纸面终端联调。"
          : "验证门禁当前仍有阻塞项，适合先回到验证页查看证据板和阻塞原因。",
        raw: item,
      };
    }

    const tone = item.running ? "accent" : "muted";
    return {
      tone,
      pill: "会话快照",
      subtitle: "审阅最近一次受管会话快照，确认它是否已经形成完整的执行闭环。",
      summaryRows: [
        { label: "对象", value: "最近会话", tone: "muted" },
        { label: "状态", value: item.running ? "运行中" : "已停止", tone },
        { label: "模式", value: formatTradingMode(item.request?.mode), tone: item.request?.mode === "live" ? "warning" : "muted" },
        { label: "交易对", value: safeText(item.request?.symbol, "N/A") },
        { label: "持仓", value: safeText(item.health?.open_positions, 0), tone: item.health?.open_positions ? "accent" : "muted" },
        { label: "挂单", value: safeText(item.health?.pending_orders, 0), tone: item.health?.pending_orders ? "warning" : "muted" },
      ],
      contextRows: [
        { label: "会话 ID", value: safeText(item.session_id, "N/A") },
        { label: "启动时间", value: formatTimestamp(item.started_at) },
        { label: "策略", value: formatStrategyText(item.request?.strategies || item.request?.strategy || []) },
        { label: "周期", value: safeText(item.request?.timeframe, "N/A") },
        { key: "equity", label: "权益", renderedValue: formatMetricNumber(item.portfolio?.equity ?? item.portfolio?.total_value, 2) },
        { key: "cash", label: "现金", renderedValue: formatMetricNumber(item.portfolio?.cash, 2) },
      ],
      note: item.request
        ? (item.running
          ? "当前会话正在运行，适合切到交易会话或执行工作台检查事件、持仓和遥测。"
          : "当前会话已停止，但仍可作为最近一次闭环运行的参考快照。")
        : "当前会话快照信息不足，适合先打开交易会话页补全上下文。",
      raw: item,
    };
  }

  const item = candidate.item || {};
  const tone = safeText(item.tone, "muted");
  return {
    tone,
    pill: "监控告警",
    subtitle: "审阅平台级告警，确认阻塞来源、时间和建议动作。",
    summaryRows: [
      { label: "对象", value: "告警", tone: "muted" },
      { label: "来源", value: localizeUiText(safeText(item.source, "system"), "system") },
      { label: "标题", value: localizeUiText(safeText(item.title, "Alert"), "Alert"), tone },
      { label: "时间", value: formatTimestamp(item.created_at) },
      { label: "建议", value: monitoringAlertActionHint(String(item.source || "").toLowerCase()) },
    ],
    contextRows: [
      { label: "告警信息", value: safeText(item.message, "暂无详情"), tone },
      { label: "平台健康", value: localizeUiText(safeText(health.overall_label, "Unknown"), "Unknown"), tone: healthTone },
      { label: "服务连通", value: `${safeText(metrics.services_up, 0)}/${safeText(metrics.services_total, 0)}` },
      { label: "验证不通过", value: safeText(metrics.validation_no_go, 0), tone: metrics.validation_no_go ? "warning" : "muted" },
      { label: "活跃会话", value: runtime.active_session ? "有" : "无", tone: runtime.active_session ? "accent" : "muted" },
    ],
    note: monitoringAlertActionHint(String(item.source || "").toLowerCase()),
    raw: item,
  };
}

function renderMonitoringInspector(payload = state.monitoring || {}) {
  const candidate = syncMonitoringInspectorSelection(payload);
  const model = monitoringInspectorModel(candidate, payload);
  const pillNode = document.getElementById("monitoring-inspector-pill");
  pillNode.className = pillToneClass(model.tone);
  pillNode.textContent = model.pill;
  document.getElementById("monitoring-inspector-subtitle").textContent = model.subtitle;
  document.getElementById("monitoring-inspector-summary").innerHTML = model.summaryRows
    .map((row) => statusRow(row.label, row.renderedValue ?? row.value, row.tone))
    .join("");
  document.getElementById("monitoring-inspector-context").innerHTML = monitoringInspectorContextMarkup(model.contextRows);
  document.getElementById("monitoring-inspector-note").textContent = model.note;
  document.getElementById("monitoring-inspector-json").textContent = JSON.stringify(model.raw, null, 2);
}

function normalizeExecutionEventType(value) {
  const eventType = String(value || "event").toLowerCase();
  if (["signal", "order", "fill", "risk", "kill_switch"].includes(eventType)) {
    return eventType;
  }
  return "event";
}

function executionEventTypeLabel(eventType) {
  const normalized = normalizeExecutionEventType(eventType);
  if (normalized === "signal") {
    return "信号";
  }
  if (normalized === "order") {
    return "订单";
  }
  if (normalized === "fill") {
    return "成交";
  }
  if (normalized === "risk") {
    return "风控";
  }
  if (normalized === "kill_switch") {
    return "熔断";
  }
  return "事件";
}

function executionEventTone(item = {}) {
  const eventType = normalizeExecutionEventType(item.event_type);
  const level = String(item.level || "info").toLowerCase();
  if (eventType === "kill_switch") {
    return "danger";
  }
  if (eventType === "risk") {
    return level === "error" || level === "critical" ? "danger" : "warning";
  }
  if (eventType === "fill") {
    return "accent";
  }
  if (eventType === "order" || eventType === "signal") {
    return level === "warning" ? "warning" : "accent";
  }
  if (level === "error" || level === "critical") {
    return "danger";
  }
  if (level === "warning") {
    return "warning";
  }
  return "muted";
}

function latestExecutionEvent(items, eventTypes) {
  const typeSet = new Set(eventTypes.map((value) => normalizeExecutionEventType(value)));
  return items.find((item) => typeSet.has(normalizeExecutionEventType(item.event_type))) || null;
}

function filteredExecutionEvents(items = []) {
  const filter = state.executionEventFilter || "all";
  if (filter === "all") {
    return items;
  }
  if (filter === "risk") {
    return items.filter((item) => {
      const eventType = normalizeExecutionEventType(item.event_type);
      return eventType === "risk" || eventType === "kill_switch";
    });
  }
  return items.filter((item) => normalizeExecutionEventType(item.event_type) === filter);
}

function syncExecutionEventFilterControls() {
  document.querySelectorAll("#execution-event-filter-controls .segment-btn").forEach((button) => {
    setSegmentPressed(button, button.dataset.executionFilter === state.executionEventFilter);
  });
}

function normalizeSessionEventType(value) {
  const eventType = String(value || "event").toLowerCase();
  if (["signal", "order", "fill", "risk", "kill_switch"].includes(eventType)) {
    return eventType;
  }
  if (["session_started", "session_stopped", "session_error"].includes(eventType)) {
    return "lifecycle";
  }
  return "event";
}

function sessionEventTypeLabel(eventType) {
  const normalized = normalizeSessionEventType(eventType);
  if (normalized === "signal") {
    return "信号";
  }
  if (normalized === "order") {
    return "订单";
  }
  if (normalized === "fill") {
    return "成交";
  }
  if (normalized === "risk") {
    return "风控";
  }
  if (normalized === "kill_switch") {
    return "熔断";
  }
  if (normalized === "lifecycle") {
    return "生命周期";
  }
  return "事件";
}

function sessionEventTone(item = {}) {
  const eventType = normalizeSessionEventType(item.event_type);
  const level = String(item.level || "info").toLowerCase();
  if (eventType === "kill_switch") {
    return "danger";
  }
  if (eventType === "risk") {
    return level === "error" || level === "critical" ? "danger" : "warning";
  }
  if (eventType === "signal" || eventType === "order" || eventType === "fill") {
    return level === "warning" ? "warning" : "accent";
  }
  if (eventType === "lifecycle") {
    return level === "error" || level === "critical" ? "danger" : "muted";
  }
  if (level === "error" || level === "critical") {
    return "danger";
  }
  if (level === "warning") {
    return "warning";
  }
  return "muted";
}

function filteredSessionEvents(items = []) {
  const filter = state.sessionEventFilter || "all";
  if (filter === "all") {
    return items;
  }
  if (filter === "lifecycle") {
    return items.filter((item) => {
      const eventType = normalizeSessionEventType(item.event_type);
      return eventType === "lifecycle" || eventType === "kill_switch";
    });
  }
  if (filter === "risk") {
    return items.filter((item) => {
      const eventType = normalizeSessionEventType(item.event_type);
      return eventType === "risk" || eventType === "kill_switch";
    });
  }
  return items.filter((item) => normalizeSessionEventType(item.event_type) === filter);
}

function syncSessionEventFilterControls() {
  document.querySelectorAll("#session-event-filter-controls .segment-btn").forEach((button) => {
    setSegmentPressed(button, button.dataset.sessionFilter === state.sessionEventFilter);
  });
}

function sessionEventContextRows(item = {}) {
  const data = item.data && typeof item.data === "object" ? item.data : {};
  const eventType = normalizeSessionEventType(item.event_type);

  if (eventType === "signal") {
    return [
      { key: "strategy_id", label: "策略", value: data.strategy_id },
      { key: "symbol", label: "交易对", value: data.symbol },
      { key: "direction", label: "方向", value: data.direction, tone: "accent" },
      { key: "strength", label: "强度", value: data.strength },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "order") {
    return [
      { key: "order_id", label: "订单 ID", value: data.order_id },
      { key: "symbol", label: "交易对", value: data.symbol },
      { key: "side", label: "方向", value: data.side },
      { key: "status", label: "状态", value: data.status },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "fill") {
    return [
      { key: "order_id", label: "订单 ID", value: data.order_id },
      { key: "symbol", label: "交易对", value: data.symbol },
      { key: "side", label: "方向", value: data.side },
      { key: "quantity", label: "数量", value: data.quantity },
      { key: "price", label: "价格", value: data.price },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "risk") {
    return [
      { key: "type", label: "类型", value: data.type, tone: "warning" },
      { key: "reason", label: "原因", value: data.reason },
      { key: "strategy_id", label: "策略", value: data.strategy_id },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "kill_switch") {
    return [
      { key: "reason", label: "原因", value: data.reason, tone: "danger" },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "lifecycle") {
    return [
      { key: "session_id", label: "会话", value: item.session_id },
      { key: "source", label: "来源", value: data.source },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  return Object.entries(data)
    .slice(0, 4)
    .map(([key, value]) => ({ key, label: key.replaceAll("_", " "), value }));
}

function sessionEventContextMarkup(item = {}) {
  const rows = sessionEventContextRows(item);
  if (!rows.length) {
    return "";
  }
  return `
    <div class="execution-event-context-grid">
      ${rows.map((row) => `
        <div class="execution-event-context-item">
          <span class="execution-event-context-label">${escapeHtml(localizeInlineText(row.label, row.label))}</span>
          <strong class="${row.tone ? toneClass(row.tone) : ""}">${escapeHtml(formatExecutionEventContextValue(row.key, row.value))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function executionFlowCard(title, badgeValue, badgeTone, summary, rows, note = "") {
  const content = Array.isArray(rows) && rows.length
    ? rows.map(([label, value, tone = null]) => statusRow(label, value, tone)).join("")
    : statusRow("状态", "N/A");
  return `
    <article class="execution-flow-card ${toneClass(badgeTone || "muted")}">
      <div class="history-top">
        <strong>${escapeHtml(title)}</strong>
        <span class="${pillToneClass(badgeTone || "muted")}">${escapeHtml(String(badgeValue))}</span>
      </div>
      <div class="history-note">${escapeHtml(summary)}</div>
      <div class="status-list compact-status-list">${content}</div>
      ${note ? `<div class="execution-flow-note">${escapeHtml(note)}</div>` : ""}
    </article>
  `;
}

function localizeEventMessage(message, fallback = "") {
  const text = safeText(message, fallback);
  if (!text) {
    return fallback;
  }

  const signalMatch = text.match(/^(.+?) emitted ([+-]?\d+(?:\.\d+)?) on ([^ ]+) \(strength=([^)]+)\)\.$/i);
  if (signalMatch) {
    const [, strategyId, direction, symbol, strength] = signalMatch;
    const strategyTitle = localizeStrategyTitle(strategyId, strategyId);
    const directionNumber = Number(direction);
    const directionLabel = Number.isFinite(directionNumber)
      ? directionNumber > 0
        ? "做多"
        : directionNumber < 0
          ? "做空"
          : "中性"
      : safeText(direction, "中性");
    return `${strategyTitle} 在 ${symbol} 发出${directionLabel}信号（强度 ${formatMetricNumber(strength, 3)}）。`;
  }

  const orderMatch = text.match(/^(buy|sell) order for (.+?) is ([a-z_]+)\.?$/i);
  if (orderMatch) {
    const [, side, symbol, status] = orderMatch;
    return `${localizeUiText(side, side)}方向订单 ${symbol} 当前为${localizeUiText(status, status)}。`;
  }

  const fillMatch = text.match(/^(buy|sell) ([0-9.eE+-]+) (.+?) @ ([0-9.eE+-]+)\.?$/i);
  if (fillMatch) {
    const [, side, quantity, symbol, price] = fillMatch;
    return `${localizeUiText(side, side)} ${formatMetricNumber(quantity, 4)} ${symbol}，价格 ${formatMetricNumber(price, 2)}。`;
  }

  return localizeUiText(text, text);
}

function formatExecutionEventContextValue(field, value) {
  if (value === null || value === undefined || value === "") {
    return "待检测";
  }
  if (field === "strategy_id") {
    return localizeStrategyTitle(value, value);
  }
  if (field === "order_id") {
    return localizeInlineText(value, "待检测");
  }
  if (field === "direction") {
    const number = Number(value);
    if (Number.isFinite(number)) {
      if (number > 0) {
        return "做多";
      }
      if (number < 0) {
        return "做空";
      }
      return "中性";
    }
  }
  if (field === "price" || field === "entry_price" || field === "current_price") {
    return formatMetricNumber(value, 2);
  }
  if (field === "quantity" || field === "filled_quantity") {
    return formatMetricNumber(value, 4);
  }
  if (field === "strength") {
    return formatMetricNumber(value, 3);
  }
  if (field === "drawdown") {
    return formatPercent(value);
  }
  if (["side", "status", "type", "source"].includes(field)) {
    return localizeUiText(value, safeText(value, "待检测"));
  }
  return typeof value === "string"
    ? localizeInlineText(value, "待检测")
    : safeText(value, "待检测");
}

function executionEventContextRows(item = {}) {
  const data = item.data && typeof item.data === "object" ? item.data : {};
  const eventType = normalizeExecutionEventType(item.event_type);

  if (eventType === "signal") {
    return [
      { key: "strategy_id", label: "策略", value: data.strategy_id },
      { key: "symbol", label: "交易对", value: data.symbol },
      { key: "direction", label: "方向", value: data.direction, tone: "accent" },
      { key: "strength", label: "强度", value: data.strength },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "order") {
    return [
      { key: "order_id", label: "订单 ID", value: data.order_id },
      { key: "symbol", label: "交易对", value: data.symbol },
      { key: "side", label: "方向", value: data.side, tone: data.side === "buy" ? "accent" : data.side === "sell" ? "warning" : "muted" },
      { key: "status", label: "状态", value: data.status },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "fill") {
    return [
      { key: "order_id", label: "订单 ID", value: data.order_id },
      { key: "symbol", label: "交易对", value: data.symbol },
      { key: "side", label: "方向", value: data.side, tone: data.side === "buy" ? "accent" : data.side === "sell" ? "warning" : "muted" },
      { key: "quantity", label: "数量", value: data.quantity },
      { key: "price", label: "价格", value: data.price },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "risk") {
    return [
      { key: "type", label: "类型", value: data.type, tone: "warning" },
      { key: "reason", label: "原因", value: data.reason },
      { key: "strategy_id", label: "策略", value: data.strategy_id },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  if (eventType === "kill_switch") {
    return [
      { key: "reason", label: "原因", value: data.reason, tone: "danger" },
    ].filter((row) => row.value !== undefined && row.value !== null && row.value !== "");
  }

  return Object.entries(data)
    .slice(0, 4)
    .map(([key, value]) => ({ key, label: key.replaceAll("_", " "), value }));
}

function executionEventContextMarkup(item = {}) {
  const rows = executionEventContextRows(item);
  if (!rows.length) {
    return "";
  }
  return `
    <div class="execution-event-context-grid">
      ${rows.map((row) => `
        <div class="execution-event-context-item">
          <span class="execution-event-context-label">${escapeHtml(row.label)}</span>
          <strong class="${row.tone ? toneClass(row.tone) : ""}">${escapeHtml(formatExecutionEventContextValue(row.key, row.value))}</strong>
        </div>
      `).join("")}
    </div>
  `;
}

function executionInspectorSelection(kind = null, key = null) {
  return {
    kind: kind || null,
    key: key || null,
  };
}

function executionInspectorItemKey(kind, item = {}, index = 0) {
  if (kind === "event") {
    return safeText(
      item.record_id || item.event_id || `${normalizeExecutionEventType(item.event_type)}:${item.created_at || index}:${item.title || ""}`,
      `event:${index}`,
    );
  }
  if (kind === "position") {
    return safeText(
      item.position_id || `${item.symbol || "position"}:${item.side || "flat"}:${index}`,
      `position:${index}`,
    );
  }
  if (kind === "order") {
    return safeText(
      item.order_id || `${item.symbol || "order"}:${item.side || "na"}:${index}`,
      `order:${index}`,
    );
  }
  return `${kind || "item"}:${index}`;
}

function executionInspectorCandidates(payload = {}) {
  const events = Array.isArray(payload.events) ? payload.events : [];
  const positions = Array.isArray(payload.positions) ? payload.positions : [];
  const orders = Array.isArray(payload.orders) ? payload.orders : [];
  return [
    ...events.map((item, index) => ({
      kind: "event",
      key: executionInspectorItemKey("event", item, index),
      item,
      index,
    })),
    ...positions.map((item, index) => ({
      kind: "position",
      key: executionInspectorItemKey("position", item, index),
      item,
      index,
    })),
    ...orders.map((item, index) => ({
      kind: "order",
      key: executionInspectorItemKey("order", item, index),
      item,
      index,
    })),
  ];
}

function executionInspectorCandidate(payload = {}, selection = state.executionInspector) {
  return executionInspectorCandidates(payload).find(
    (candidate) => candidate.kind === selection?.kind && candidate.key === selection?.key,
  ) || null;
}

function syncExecutionInspectorSelection(payload = {}) {
  const current = executionInspectorCandidate(payload);
  if (current) {
    return current;
  }
  const candidates = executionInspectorCandidates(payload);
  const preferred = candidates.find(
    (candidate) => candidate.kind === "event"
      && ["kill_switch", "risk"].includes(normalizeExecutionEventType(candidate.item.event_type)),
  ) || candidates.find((candidate) => candidate.kind === "order")
    || candidates.find((candidate) => candidate.kind === "position")
    || candidates.find((candidate) => candidate.kind === "event")
    || null;
  state.executionInspector = preferred
    ? executionInspectorSelection(preferred.kind, preferred.key)
    : executionInspectorSelection();
  return preferred;
}

function executionInspectorContextMarkup(rows = []) {
  if (!rows.length) {
    return '<div class="history-empty">暂无关联上下文。</div>';
  }
  return `
    <div class="execution-event-context-grid">
      ${rows.map((row) => {
        const renderedValue = row.renderedValue ?? formatExecutionEventContextValue(row.key, row.value);
        return `
          <div class="execution-event-context-item">
            <span class="execution-event-context-label">${escapeHtml(localizeInlineText(row.label, row.label))}</span>
            <strong class="${row.tone ? toneClass(row.tone) : ""}">${escapeHtml(renderedValue)}</strong>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function executionOrderNotional(order = {}) {
  const explicit = Number(order.notional);
  if (Number.isFinite(explicit) && explicit > 0) {
    return explicit;
  }
  const price = Number(order.price);
  const quantity = Number(order.quantity);
  if (Number.isFinite(price) && Number.isFinite(quantity)) {
    return price * quantity;
  }
  return 0;
}

function sessionAuditSelection(kind = null, key = null) {
  return {
    kind: kind || null,
    key: key || null,
  };
}

function sessionAuditItemKey(kind, item = {}, index = 0) {
  if (kind === "session") {
    return safeText(item.session_id || item.record_id || "session-current", "session-current");
  }
  if (kind === "history") {
    return safeText(item.record_id || item.session_id || `history:${index}`, `history:${index}`);
  }
  if (kind === "event") {
    return safeText(
      item.record_id || item.event_id || `${normalizeSessionEventType(item.event_type)}:${item.created_at || index}:${item.title || ""}`,
      `event:${index}`,
    );
  }
  if (kind === "position") {
    return safeText(
      item.position_id || `${item.symbol || "position"}:${item.side || "flat"}:${index}`,
      `position:${index}`,
    );
  }
  if (kind === "order") {
    return safeText(
      item.order_id || `${item.symbol || "order"}:${item.side || "na"}:${index}`,
      `order:${index}`,
    );
  }
  return `${kind || "item"}:${index}`;
}

function sessionAuditCandidates(snapshot = state.session || {}) {
  const history = Array.isArray(state.sessionHistory) ? state.sessionHistory : [];
  const events = Array.isArray(state.sessionEvents) ? state.sessionEvents : [];
  const positions = Array.isArray(snapshot.positions) ? snapshot.positions : [];
  const orders = Array.isArray(snapshot.open_orders) ? snapshot.open_orders : [];
  const candidates = [];

  if (snapshot && (snapshot.session_id || snapshot.request || snapshot.running !== undefined)) {
    candidates.push({
      kind: "session",
      key: sessionAuditItemKey("session", snapshot, 0),
      item: snapshot,
      index: 0,
    });
  }

  return [
    ...candidates,
    ...history.map((item, index) => ({
      kind: "history",
      key: sessionAuditItemKey("history", item, index),
      item,
      index,
    })),
    ...events.map((item, index) => ({
      kind: "event",
      key: sessionAuditItemKey("event", item, index),
      item,
      index,
    })),
    ...positions.map((item, index) => ({
      kind: "position",
      key: sessionAuditItemKey("position", item, index),
      item,
      index,
    })),
    ...orders.map((item, index) => ({
      kind: "order",
      key: sessionAuditItemKey("order", item, index),
      item,
      index,
    })),
  ];
}

function sessionAuditCandidate(snapshot = state.session || {}, selection = state.sessionAudit) {
  return sessionAuditCandidates(snapshot).find(
    (candidate) => candidate.kind === selection?.kind && candidate.key === selection?.key,
  ) || null;
}

function syncSessionAuditSelection(snapshot = state.session || {}) {
  const hasLiveSession = Boolean(snapshot?.session_id);
  const hasHistory = Array.isArray(state.sessionHistory) && state.sessionHistory.length > 0;
  const pinLiveWhenIdle = Boolean(state.sessionView?.pinLiveWhenIdle) && !sessionViewIsHistory();
  const current = sessionAuditCandidate(snapshot);
  const currentIsProvisionalSession = current?.kind === "session" && !hasLiveSession;
  if (current && !(currentIsProvisionalSession && hasHistory && !sessionViewIsHistory())) {
    return current;
  }

  const candidates = sessionAuditCandidates(snapshot);
  const preferred = (
    sessionViewIsHistory()
      ? candidates.find(
        (candidate) => candidate.kind === "history" && isActiveSessionHistoryRecord(candidate.item),
      ) || candidates.find((candidate) => candidate.kind === "session")
      : pinLiveWhenIdle
        ? candidates.find((candidate) => candidate.kind === "session")
          || candidates.find((candidate) => candidate.kind === "event")
          || candidates.find((candidate) => candidate.kind === "history")
      : !hasLiveSession
        ? candidates.find((candidate) => candidate.kind === "history")
          || candidates.find((candidate) => candidate.kind === "event")
          || candidates.find((candidate) => candidate.kind === "session")
        : candidates.find((candidate) => candidate.kind === "session")
  ) || candidates.find(
    (candidate) => candidate.kind === "event"
      && ["kill_switch", "risk"].includes(normalizeSessionEventType(candidate.item.event_type)),
  ) || candidates.find((candidate) => candidate.kind === "position")
    || candidates.find((candidate) => candidate.kind === "order")
    || candidates.find((candidate) => candidate.kind === "event")
    || candidates.find((candidate) => candidate.kind === "history")
    || null;

  state.sessionAudit = preferred
    ? sessionAuditSelection(preferred.kind, preferred.key)
    : sessionAuditSelection();
  return preferred;
}

function openLatestSessionHistoryByDefault(snapshot = state.liveSessionSnapshot || state.session || {}) {
  const record = latestSessionHistoryRecord();
  if (!record || !shouldDefaultToLatestSessionHistory(snapshot)) {
    return false;
  }
  setSessionView("history", record);
  renderSessionViewControls();
  renderSessionV2(record);
  return true;
}

function sessionAuditContextMarkup(rows = []) {
  return executionInspectorContextMarkup(rows);
}

function sessionAuditModel(candidate, snapshot = state.session || {}) {
  if (!candidate) {
    return {
      tone: "muted",
      pill: "当前会话",
      subtitle: "聚焦当前会话、历史快照、事件、持仓或挂单，查看它的摘要、上下文与原始对象。",
      summaryRows: [{ label: "状态", value: "等待会话对象", tone: "muted" }],
      contextRows: [],
      note: "当前审阅的是会话级摘要。",
      raw: {},
    };
  }

  const historyMode = sessionViewIsHistory();
  const history = Array.isArray(state.sessionHistory) ? state.sessionHistory : [];
  const events = Array.isArray(state.sessionEvents) ? state.sessionEvents : [];
  const positions = Array.isArray(snapshot.positions) ? snapshot.positions : [];
  const orders = Array.isArray(snapshot.open_orders) ? snapshot.open_orders : [];

  if (candidate.kind === "session") {
    const item = candidate.item || {};
    const request = item.request || {};
    const health = item.health || {};
    const portfolio = item.portfolio || {};
    const dashboard = item.dashboard || {};
    const killSwitch = item.kill_switch || {};
    const strategies = Array.isArray(dashboard.strategies) ? dashboard.strategies : (request.strategies || []);
    const tone = killSwitch.active
      ? "danger"
      : item.last_error
        ? "warning"
        : (dashboard.status_tone || (item.running ? "accent" : "muted"));
    const note = historyMode
      ? "当前驾驶舱正在回看一份已归档会话，可继续切换事件、持仓和挂单做逐项审阅。"
      : "当前审阅的是实时会话摘要，适合确认资金、风控、持仓与遥测是否一致。";

    return {
      tone,
      pill: historyMode ? "回看会话" : "当前会话",
      subtitle: historyMode
        ? "当前驾驶舱正在回看一份已归档会话，结合事件、持仓与挂单审阅它的业务状态。"
        : "聚焦当前会话，确认资金、风控、持仓与遥测是否一致。",
      summaryRows: [
        { label: "对象", value: "会话快照", tone: "muted" },
        { label: "会话 ID", value: safeText(item.session_id, "待检测"), tone },
        { label: "状态", value: localizeUiText(dashboard.status_label || (item.running ? "Running" : "Stopped")), tone },
        { label: "模式", value: formatTradingMode(safeText(request.mode, dashboard.mode || "paper")) },
        { label: "事件数", value: safeText(dashboard.recent_event_count ?? item.event_summary?.total, 0) },
        { label: "遥测点", value: safeText(item.telemetry?.labels?.length, 0) },
      ],
      contextRows: [
        { key: "symbol", label: "交易对", value: request.symbol || dashboard.symbol },
        { key: "timeframe", label: "周期", value: request.timeframe || dashboard.timeframe },
        { key: "strategies", label: "策略", renderedValue: strategies.length ? formatStrategyText(strategies) : "N/A" },
        { key: "started_at", label: "启动时间", renderedValue: formatTimestamp(item.started_at) },
        { key: "updated_at", label: "更新时间", renderedValue: formatTimestamp(item.updated_at || item.started_at) },
        { key: "equity", label: "权益", renderedValue: formatMetricNumber(portfolio.equity ?? portfolio.total_value, 2) },
        {
          key: "drawdown",
          label: "回撤",
          renderedValue: formatPercent(portfolio.drawdown),
          tone: Number(portfolio.drawdown || 0) < 0 ? "warning" : "accent",
        },
        { key: "positions", label: "持仓数", value: safeText(health.open_positions, positions.length) },
        { key: "orders", label: "挂单数", value: safeText(health.pending_orders, orders.length) },
        {
          key: "kill_switch",
          label: "熔断开关",
          renderedValue: killSwitch.active ? safeText(killSwitch.reason, "已触发") : "已布防",
          tone: killSwitch.active ? "danger" : "accent",
        },
      ].filter((row) => row.value !== undefined || row.renderedValue !== undefined),
      note,
      raw: item,
    };
  }

  if (candidate.kind === "history") {
    const item = candidate.item || {};
    const request = item.request || {};
    const dashboard = item.dashboard || {};
    const health = item.health || {};
    const portfolio = item.portfolio || {};
    const killSwitch = item.kill_switch || {};
    const strategies = Array.isArray(dashboard.strategies) ? dashboard.strategies : (request.strategies || []);
    const active = isActiveSessionHistoryRecord(item);
    const tone = killSwitch.active
      ? "danger"
      : item.running
        ? "accent"
        : (item.recorded_running ? "warning" : safeText(dashboard.status_tone, "muted"));
    return {
      tone,
      pill: active ? "回看中" : "历史会话",
      subtitle: "聚焦某份已归档会话，确认它在记录时的风险、持仓、挂单与活动状态。",
      summaryRows: [
        { label: "对象", value: "历史快照", tone: "muted" },
        { label: "会话 ID", value: safeText(item.session_id, "session"), tone },
        { label: "状态", value: localizeUiText(dashboard.status_label || (item.running ? "Running" : "Stopped")), tone },
        { label: "是否实时", value: item.is_live ? "是" : "否", tone: item.is_live ? "accent" : "muted" },
        { label: "启动时间", value: formatTimestamp(item.started_at) },
        { label: "当前回看", value: active ? "是" : "否", tone: active ? "warning" : "muted" },
      ],
      contextRows: [
        { key: "mode", label: "模式", renderedValue: formatTradingMode(request.mode || dashboard.mode || "paper") },
        { key: "symbol", label: "交易对", value: request.symbol || dashboard.symbol },
        { key: "timeframe", label: "周期", value: request.timeframe || dashboard.timeframe },
        { key: "strategies", label: "策略", renderedValue: strategies.length ? formatStrategyText(strategies) : "N/A" },
        { key: "equity", label: "权益", renderedValue: formatMetricNumber(portfolio.equity ?? portfolio.total_value, 2) },
        { key: "positions", label: "持仓数", value: safeText(health.open_positions, Array.isArray(item.positions) ? item.positions.length : 0) },
        { key: "orders", label: "挂单数", value: safeText(health.pending_orders, Array.isArray(item.open_orders) ? item.open_orders.length : 0) },
        {
          key: "kill_switch",
          label: "熔断开关",
          renderedValue: killSwitch.active ? safeText(killSwitch.reason, "已触发") : "关闭",
          tone: killSwitch.active ? "danger" : "muted",
        },
        { key: "telemetry", label: "遥测点", value: safeText(item.telemetry?.labels?.length, 0) },
      ],
      note: active
        ? "当前驾驶舱已切换到这份历史会话。"
        : "点击“回看会话”可把驾驶舱切换到这份归档快照，再继续审阅事件与持仓。",
      raw: item,
    };
  }

  if (candidate.kind === "event") {
    const item = candidate.item || {};
    const tone = sessionEventTone(item);
    return {
      tone,
      pill: `${sessionEventTypeLabel(item.event_type)} 审计`,
      subtitle: "聚焦单个会话事件，确认它在会话生命周期中的位置与业务上下文。",
      summaryRows: [
        { label: "对象", value: "会话事件", tone: "muted" },
        { label: "类型", value: sessionEventTypeLabel(item.event_type), tone },
        { label: "级别", value: localizeUiText(safeText(item.level, "info"), "信息"), tone },
        { label: "发生时间", value: formatTimestamp(item.created_at) },
        { label: "会话 ID", value: safeText(item.session_id, snapshot.session_id || "待检测") },
        { label: "标题", value: safeText(item.title, "事件") },
      ],
      contextRows: [
        { key: "title", label: "标题", value: item.title },
        ...sessionEventContextRows(item),
      ],
      note: localizeEventMessage(item.message, "暂无详情"),
      raw: item,
    };
  }

  if (candidate.kind === "position") {
    const item = candidate.item || {};
    const relatedOrders = orders.filter((order) => safeText(order.symbol, "") === safeText(item.symbol, ""));
    const tone = positionTone(item);
    return {
      tone,
      pill: "持仓审计",
      subtitle: "聚焦单个持仓，确认收益、仓位方向与关联挂单是否符合当前会话状态。",
      summaryRows: [
        { label: "对象", value: "当前持仓", tone: "muted" },
        { label: "交易对", value: safeText(item.symbol, "N/A"), tone },
        { label: "方向", value: formatPositionSide(safeText(item.side, "flat")), tone },
        { label: "数量", value: formatMetricNumber(item.quantity, 4) },
        { label: "收益率", value: formatPercent(item.pnl_pct), tone: Number(item.pnl_pct || 0) >= 0 ? "accent" : "danger" },
        { label: "关联挂单", value: String(relatedOrders.length), tone: relatedOrders.length ? "warning" : "muted" },
      ],
      contextRows: [
        { key: "entry_price", label: "开仓价", renderedValue: formatMetricNumber(item.entry_price, 2) },
        { key: "current_price", label: "最新价", renderedValue: formatMetricNumber(item.current_price, 2) },
        { key: "market_value", label: "名义金额", renderedValue: formatMetricNumber(item.market_value, 2) },
        {
          key: "unrealized_pnl",
          label: "未实现盈亏",
          renderedValue: formatSignedMetricNumber(item.unrealized_pnl, 2),
          tone: Number(item.unrealized_pnl || 0) >= 0 ? "accent" : "danger",
        },
        { key: "session_id", label: "会话 ID", value: safeText(snapshot.session_id, "待检测") },
        { key: "pending_orders", label: "关联挂单数", value: String(relatedOrders.length) },
      ],
      note: `${safeText(item.symbol, "该持仓")} 当前为 ${formatPositionSide(safeText(item.side, "flat"))}，可继续检查关联挂单与会话事件。`,
      raw: item,
    };
  }

  if (candidate.kind === "order") {
    const item = candidate.item || {};
    const relatedPosition = positions.find((position) => safeText(position.symbol, "") === safeText(item.symbol, ""));
    const relatedEvents = events.filter((eventItem) => {
      const data = eventItem.data && typeof eventItem.data === "object" ? eventItem.data : {};
      return safeText(data.order_id, "") === safeText(item.order_id, "");
    });
    const tone = orderStatusTone(item.status);
    return {
      tone,
      pill: "挂单审计",
      subtitle: "聚焦单个挂单，确认它的价格、数量、名义金额以及与会话事件和持仓的关系。",
      summaryRows: [
        { label: "对象", value: "挂单", tone: "muted" },
        { label: "订单 ID", value: safeText(item.order_id, "N/A"), tone },
        { label: "状态", value: formatOrderStatus(safeText(item.status, "n/a")), tone },
        { label: "交易对", value: safeText(item.symbol, "N/A") },
        { label: "方向", value: formatOrderSide(safeText(item.side, "n/a")) },
        { label: "关联事件", value: String(relatedEvents.length), tone: relatedEvents.length ? "accent" : "muted" },
      ],
      contextRows: [
        { key: "order_type", label: "类型", renderedValue: formatOrderType(safeText(item.order_type, "market")) },
        { key: "quantity", label: "数量", renderedValue: formatMetricNumber(item.quantity, 4) },
        { key: "price", label: "价格", renderedValue: formatMetricNumber(item.price, 2) },
        { key: "notional", label: "名义金额", renderedValue: formatMetricNumber(executionOrderNotional(item), 2) },
        { key: "strategy_id", label: "策略", value: safeText(item.strategy_id, "N/A") },
        { key: "position", label: "关联持仓", value: relatedPosition ? safeText(relatedPosition.symbol, "N/A") : "无" },
      ],
      note: `${safeText(item.order_id, "该挂单")} 当前为 ${formatOrderStatus(safeText(item.status, "n/a"))}。`,
      raw: item,
    };
  }

  return {
    tone: "muted",
    pill: "会话对象",
    subtitle: "聚焦当前会话、历史快照、事件、持仓或挂单，查看它的摘要、上下文与原始对象。",
    summaryRows: [{ label: "状态", value: "未知对象", tone: "muted" }],
    contextRows: [],
    note: "当前对象缺少可展示上下文。",
    raw: candidate.item || {},
  };
}

function renderSessionPositions(positions = []) {
  document.getElementById("session-positions").innerHTML = positions.length
    ? positions.map((position, index) => {
      const key = sessionAuditItemKey("position", position, index);
      const selected = state.sessionAudit?.kind === "position" && state.sessionAudit.key === key;
      return `
        <tr class="session-selectable ${selected ? "is-selected" : ""}" tabindex="0" data-session-audit-kind="position" data-session-audit-key="${escapeHtml(key)}">
          <td>${escapeHtml(safeText(position.symbol, "N/A"))}</td>
          <td><span class="cell-badge ${toneClass(positionTone(position))}">${escapeHtml(formatPositionSide(safeText(position.side, "flat")))}</span></td>
          <td>${formatMetricNumber(position.quantity, 4)}</td>
          <td>${formatMetricNumber(position.market_value, 2)}</td>
          <td>${formatMetricNumber(position.entry_price, 2)}</td>
          <td>${formatMetricNumber(position.current_price, 2)}</td>
          <td class="${toneClass(Number(position.unrealized_pnl) >= 0 ? "accent" : "danger")}">${formatSignedMetricNumber(position.unrealized_pnl, 2)}</td>
          <td class="${toneClass(Number(position.pnl_pct) >= 0 ? "accent" : "danger")}">${formatPercent(position.pnl_pct)}</td>
        </tr>
      `;
    }).join("")
    : tableFallback(8, "暂无持仓。");
}

function renderSessionOrders(orders = []) {
  document.getElementById("session-orders").innerHTML = orders.length
    ? orders.map((order, index) => {
      const key = sessionAuditItemKey("order", order, index);
      const selected = state.sessionAudit?.kind === "order" && state.sessionAudit.key === key;
      return `
        <tr class="session-selectable ${selected ? "is-selected" : ""}" tabindex="0" data-session-audit-kind="order" data-session-audit-key="${escapeHtml(key)}">
          <td>${escapeHtml(safeText(order.order_id, "N/A"))}</td>
          <td>${escapeHtml(safeText(order.symbol, "N/A"))}</td>
          <td>${escapeHtml(formatOrderType(safeText(order.order_type, "market")))}</td>
          <td><span class="cell-badge ${toneClass(order.side === "buy" ? "accent" : order.side === "sell" ? "warning" : "muted")}">${escapeHtml(formatOrderSide(safeText(order.side, "n/a")))}</span></td>
          <td>${formatMetricNumber(order.quantity, 4)}</td>
          <td>${formatMetricNumber(order.price, 2)}</td>
          <td><span class="cell-badge ${toneClass(orderStatusTone(order.status))}">${escapeHtml(formatOrderStatus(safeText(order.status, "n/a")))}</span></td>
        </tr>
      `;
    }).join("")
    : tableFallback(7, "暂无挂单。");
}

function renderSessionAudit(snapshot = state.session || {}) {
  const candidate = syncSessionAuditSelection(snapshot);
  const model = sessionAuditModel(candidate, snapshot);
  const pillNode = document.getElementById("session-audit-pill");
  pillNode.className = pillToneClass(model.tone);
  pillNode.textContent = model.pill;
  document.getElementById("session-audit-subtitle").textContent = model.subtitle;
  document.getElementById("session-audit-summary").innerHTML = model.summaryRows
    .map((row) => statusRow(row.label, row.value, row.tone))
    .join("");
  document.getElementById("session-audit-context").innerHTML = sessionAuditContextMarkup(model.contextRows);
  document.getElementById("session-audit-note").textContent = model.note;
  document.getElementById("session-audit-json").textContent = JSON.stringify(model.raw, null, 2);
}

function refreshSessionAuditSurfaces(snapshot = state.session || {}) {
  renderSessionHistory(state.sessionHistory);
  renderSessionEvents(state.sessionEvents);
  renderSessionPositions(Array.isArray(snapshot.positions) ? snapshot.positions : []);
  renderSessionOrders(Array.isArray(snapshot.open_orders) ? snapshot.open_orders : []);
  renderSessionAudit(snapshot);
}

function executionInspectorModel(candidate, payload = {}) {
  if (!candidate) {
    return {
      tone: "muted",
      pill: "未选择",
      subtitle: "选择事件、持仓或挂单后，在这里查看它的详细上下文与原始对象。",
      summaryRows: [{ label: "状态", value: "等待执行对象", tone: "muted" }],
      contextRows: [],
      note: "当前还没有选中的执行对象。",
      raw: {},
    };
  }

  const events = Array.isArray(payload.events) ? payload.events : [];
  const positions = Array.isArray(payload.positions) ? payload.positions : [];
  const orders = Array.isArray(payload.orders) ? payload.orders : [];
  const summary = payload.summary || {};

  if (candidate.kind === "event") {
    const item = candidate.item || {};
    const tone = executionEventTone(item);
    return {
      tone,
      pill: `${executionEventTypeLabel(item.event_type)} 检查`,
      subtitle: "聚焦单个执行事件，确认它携带的上下文、级别与业务含义。",
      summaryRows: [
        { label: "对象", value: "执行事件", tone },
        { label: "类型", value: executionEventTypeLabel(item.event_type), tone },
        { label: "级别", value: localizeUiText(safeText(item.level, "info"), "信息"), tone },
        { label: "发生时间", value: formatTimestamp(item.created_at) },
        { label: "会话 ID", value: safeText(item.session_id, "N/A") },
        { label: "标题", value: localizeUiText(safeText(item.title, "事件"), "事件") },
      ],
      contextRows: executionEventContextRows(item),
      note: localizeEventMessage(item.message, "暂无事件详情。"),
      raw: item,
    };
  }

  if (candidate.kind === "position") {
    const item = candidate.item || {};
    const tone = positionTone(item);
    const relatedOrders = orders.filter((order) => safeText(order.symbol, "") === safeText(item.symbol, ""));
    const relatedEvents = events.filter((event) => {
      const data = event.data && typeof event.data === "object" ? event.data : {};
      return safeText(data.symbol, "") === safeText(item.symbol, "");
    });
    const equity = Number(summary.equity || 0);
    const marketValue = Number(item.market_value || 0);
    const exposurePct = equity > 0 ? marketValue / equity : null;
    const pnl = Number(item.unrealized_pnl || 0);
    return {
      tone,
      pill: `持仓检查 · ${safeText(item.symbol, "N/A")}`,
      subtitle: "查看当前持仓的盈亏、暴露度与关联执行活动，确认它是否仍然符合预期。",
      summaryRows: [
        { label: "对象", value: "持仓", tone },
        { label: "方向", value: formatPositionSide(safeText(item.side, "flat")), tone },
        { label: "数量", value: formatMetricNumber(item.quantity, 4) },
        { label: "名义金额", value: formatMetricNumber(item.market_value, 2) },
        { label: "未实现盈亏", value: formatSignedMetricNumber(item.unrealized_pnl, 2), tone: pnl >= 0 ? "accent" : "danger" },
        { label: "收益率", value: formatPercent(item.pnl_pct), tone: Number(item.pnl_pct || 0) >= 0 ? "accent" : "danger" },
        { label: "组合占比", value: exposurePct === null ? "N/A" : formatPercent(exposurePct) },
        { label: "关联挂单", value: String(relatedOrders.length), tone: relatedOrders.length ? "warning" : "muted" },
      ],
      contextRows: [
        { key: "symbol", label: "交易对", value: item.symbol },
        { key: "side", label: "方向", renderedValue: formatPositionSide(safeText(item.side, "flat")), tone },
        { key: "entry_price", label: "开仓价", value: item.entry_price },
        { key: "current_price", label: "最新价", value: item.current_price },
        { key: "related_events", label: "关联事件", renderedValue: String(relatedEvents.length), tone: relatedEvents.length ? "accent" : "muted" },
        { key: "symbol_orders", label: "同品种挂单", renderedValue: String(relatedOrders.length), tone: relatedOrders.length ? "warning" : "muted" },
      ],
      note: `${safeText(item.symbol, "当前持仓")} 当前${formatPositionSide(safeText(item.side, "flat"))}，${pnl >= 0 ? "处于浮盈状态" : "处于浮亏状态"}。${relatedOrders.length ? ` 同品种还有 ${relatedOrders.length} 笔挂单待处理。` : ""}`,
      raw: item,
    };
  }

  const item = candidate.item || {};
  const tone = orderStatusTone(item.status);
  const notional = executionOrderNotional(item);
  const relatedEvents = events.filter((event) => {
    const data = event.data && typeof event.data === "object" ? event.data : {};
    return safeText(data.order_id, "") === safeText(item.order_id, "")
      || safeText(data.symbol, "") === safeText(item.symbol, "");
  });
  const relatedPosition = positions.find((position) => safeText(position.symbol, "") === safeText(item.symbol, ""));
  const statusText = formatOrderStatus(safeText(item.status, "n/a"));
  return {
    tone,
    pill: `挂单检查 · ${safeText(item.order_id, "N/A")}`,
    subtitle: "查看单个挂单的状态、价格、数量和关联事件，确认它是否仍应留在执行队列中。",
    summaryRows: [
      { label: "对象", value: "挂单", tone },
      { label: "状态", value: statusText, tone },
      { label: "方向", value: formatOrderSide(safeText(item.side, "n/a")), tone: item.side === "buy" ? "accent" : item.side === "sell" ? "warning" : "muted" },
      { label: "类型", value: formatOrderType(safeText(item.order_type, "market")) },
      { label: "数量", value: formatMetricNumber(item.quantity, 4) },
      { label: "价格", value: formatMetricNumber(item.price, 2) },
      { label: "名义金额", value: formatMetricNumber(notional, 2) },
      { label: "关联事件", value: String(relatedEvents.length), tone: relatedEvents.length ? "accent" : "muted" },
    ],
    contextRows: [
      { key: "order_id", label: "订单 ID", value: item.order_id },
      { key: "symbol", label: "交易对", value: item.symbol },
      { key: "strategy_id", label: "策略", value: item.strategy_id || summary.strategy_text || null },
      { key: "status", label: "状态", renderedValue: statusText, tone },
      { key: "related_position", label: "关联持仓", renderedValue: relatedPosition ? formatPositionSide(safeText(relatedPosition.side, "flat")) : "无", tone: relatedPosition ? positionTone(relatedPosition) : "muted" },
      { key: "related_events", label: "同品种事件", renderedValue: String(relatedEvents.length), tone: relatedEvents.length ? "accent" : "muted" },
    ].filter((row) => row.value !== null || row.renderedValue !== undefined),
    note: item.status === "open"
      ? "这笔挂单仍在执行队列中，重点确认价格、数量与当前验证上下文是否一致。"
      : `这笔挂单当前状态为 ${statusText}。`,
    raw: item,
  };
}

function renderExecutionEvents(items, context = {}) {
  const countNode = document.getElementById("execution-events-count");
  const listNode = document.getElementById("execution-events");
  const filteredItems = filteredExecutionEvents(items);
  const eventMix = context.event_mix || {};
  const executionSummary = context.summary || {};
  const risk = context.risk || {};
  const positions = Array.isArray(context.positions) ? context.positions : [];
  const orders = Array.isArray(context.orders) ? context.orders : [];
  const signalEvent = latestExecutionEvent(items, ["signal"]);
  const orderEvent = latestExecutionEvent(items, ["order"]);
  const fillEvent = latestExecutionEvent(items, ["fill"]);
  const riskEvent = latestExecutionEvent(items, ["kill_switch", "risk"]);
  const signalCount = Number(eventMix.by_type?.signal || 0);
  const orderCount = Number(eventMix.by_type?.order || 0);
  const fillCount = Number(eventMix.by_type?.fill || 0);
  const riskCount = Number(eventMix.by_type?.risk || 0) + Number(eventMix.by_type?.kill_switch || 0);

  syncExecutionEventFilterControls();
  countNode.textContent = state.executionEventFilter === "all"
    ? String(items.length)
    : `${filteredItems.length} / ${items.length}`;
  listNode.innerHTML = `
    <div class="execution-flow-board">
      ${executionFlowCard(
        "信号接入",
        signalCount,
        signalCount ? "accent" : "muted",
        signalEvent
          ? localizeEventMessage(signalEvent.message, "最近已有信号进入执行层。")
          : "最近没有策略信号进入执行层。",
        [
          ["策略", safeText(executionSummary.strategy_text, "N/A")],
          ["最新时间", signalEvent ? formatTimestamp(signalEvent.created_at) : "N/A"],
          ["可见事件", signalCount, signalCount ? "accent" : "muted"],
        ],
        "这里用于观察研究输出何时开始转化为真实执行决策。",
      )}
      ${executionFlowCard(
        "订单路由",
        orders.length,
        orders.length ? "warning" : orderCount ? "accent" : "muted",
        orders.length
          ? `当前还有 ${orders.length} 笔挂单停留在执行簿中。`
          : orderEvent
            ? localizeEventMessage(orderEvent.message, "已捕获最近一次订单活动。")
            : "当前执行簿中没有待成交挂单。",
        [
          ["挂单数", orders.length, orders.length ? "warning" : "muted"],
          ["订单事件", orderCount, orderCount ? "accent" : "muted"],
          ["待成交名义金额", formatMetricNumber(executionSummary.pending_notional, 2)],
        ],
        "这一路径用于跟踪信号离开策略层后的订单意图。",
      )}
      ${executionFlowCard(
        "成交确认",
        fillCount,
        fillCount ? "accent" : positions.length ? "warning" : "muted",
        fillEvent
          ? localizeEventMessage(fillEvent.message, "已捕获最近一次成交。")
          : positions.length
            ? "当前存在持仓，但可见事件窗口内没有新的成交记录。"
            : "当前还没有捕获到新的成交记录。",
        [
          ["持仓数", positions.length, positions.length ? "accent" : "muted"],
          ["未实现盈亏", formatSignedMetricNumber(executionSummary.unrealized_pnl, 2), Number(executionSummary.unrealized_pnl || 0) >= 0 ? "accent" : "danger"],
          ["总名义金额", formatMetricNumber(executionSummary.gross_notional, 2)],
        ],
        "这里用于确认路由后的订单是否真正转化为持仓。",
      )}
      ${executionFlowCard(
        "风控护栏",
        risk.kill_switch_active ? "已布防" : riskCount,
        risk.kill_switch_active
          ? "danger"
          : risk.error_events
            ? "danger"
            : risk.warning_events || riskCount
              ? "warning"
              : "accent",
        risk.kill_switch_active
          ? safeText(risk.kill_switch_reason, "熔断开关已经触发。")
          : riskEvent
            ? localizeEventMessage(riskEvent.message, "已捕获最近一次风控事件。")
            : "风控护栏已布防，最近没有观察到执行侧异常。",
        [
          ["回撤", formatPercent(executionSummary.drawdown)],
          ["警告", safeText(risk.warning_events, 0), risk.warning_events ? "warning" : "muted"],
          ["错误", safeText(risk.error_events, 0), risk.error_events ? "danger" : "muted"],
        ],
        "推进到实盘之前，这一路径应尽量保持安静。",
      )}
    </div>
    <div class="execution-event-feed">
      ${filteredItems.length
        ? filteredItems.map((item) => {
          const fullIndex = items.indexOf(item);
          const eventKey = executionInspectorItemKey("event", item, fullIndex >= 0 ? fullIndex : 0);
          const selected = state.executionInspector?.kind === "event" && state.executionInspector.key === eventKey;
          return `
          <article class="timeline-item execution-event-item execution-selectable ${selected ? "is-selected" : ""}" tabindex="0" data-execution-select-kind="event" data-execution-select-key="${escapeHtml(eventKey)}">
            <div class="timeline-dot ${safeText(item.level, "info")}"></div>
            <div class="timeline-body">
              <div class="history-top">
                <strong>${escapeHtml(localizeUiText(safeText(item.title, "事件"), "事件"))}</strong>
                <span class="timeline-time">${escapeHtml(formatTimestamp(item.created_at))}</span>
              </div>
              <div class="execution-event-meta">
                <span class="cell-badge ${toneClass(executionEventTone(item))}">${escapeHtml(executionEventTypeLabel(item.event_type))}</span>
                <span class="cell-badge ${toneClass(executionEventTone({ level: item.level }))}">${escapeHtml(localizeUiText(safeText(item.level, "info"), "信息"))}</span>
              </div>
              <div class="history-note">${escapeHtml(localizeEventMessage(item.message, "暂无详情"))}</div>
              ${executionEventContextMarkup(item)}
            </div>
          </article>
        `;
        }).join("")
        : `<div class="history-empty">${state.executionEventFilter === "all" ? "暂无执行事件。" : "当前筛选条件下暂无执行事件。"}</div>`}
    </div>
  `;
}

function renderExecutionPositions(positions = []) {
  document.getElementById("execution-position-count").textContent = String(positions.length);
  document.getElementById("execution-positions").innerHTML = positions.length
    ? positions.map((position, index) => {
      const key = executionInspectorItemKey("position", position, index);
      const selected = state.executionInspector?.kind === "position" && state.executionInspector.key === key;
      return `
      <tr class="execution-selectable ${selected ? "is-selected" : ""}" tabindex="0" data-execution-select-kind="position" data-execution-select-key="${escapeHtml(key)}">
        <td>${escapeHtml(safeText(position.symbol, "N/A"))}</td>
        <td><span class="cell-badge ${toneClass(positionTone(position))}">${escapeHtml(formatPositionSide(safeText(position.side, "flat")))}</span></td>
        <td>${formatMetricNumber(position.quantity, 4)}</td>
        <td>${formatMetricNumber(position.market_value, 2)}</td>
        <td>${formatMetricNumber(position.entry_price, 2)}</td>
        <td>${formatMetricNumber(position.current_price, 2)}</td>
        <td class="${toneClass(Number(position.unrealized_pnl) >= 0 ? "accent" : "danger")}">${formatSignedMetricNumber(position.unrealized_pnl, 2)}</td>
        <td class="${toneClass(Number(position.pnl_pct) >= 0 ? "accent" : "danger")}">${formatPercent(position.pnl_pct)}</td>
      </tr>
    `;
    }).join("")
    : tableFallback(8, "暂无持仓。");
}

function renderExecutionOrders(orders = []) {
  document.getElementById("execution-order-count").textContent = String(orders.length);
  document.getElementById("execution-orders").innerHTML = orders.length
    ? orders.map((order, index) => {
      const key = executionInspectorItemKey("order", order, index);
      const selected = state.executionInspector?.kind === "order" && state.executionInspector.key === key;
      return `
      <tr class="execution-selectable ${selected ? "is-selected" : ""}" tabindex="0" data-execution-select-kind="order" data-execution-select-key="${escapeHtml(key)}">
        <td>${escapeHtml(safeText(order.order_id, "N/A"))}</td>
        <td>${escapeHtml(safeText(order.symbol, "N/A"))}</td>
        <td>${escapeHtml(formatOrderType(safeText(order.order_type, "market")))}</td>
        <td><span class="cell-badge ${toneClass(order.side === "buy" ? "accent" : order.side === "sell" ? "warning" : "muted")}">${escapeHtml(formatOrderSide(safeText(order.side, "n/a")))}</span></td>
        <td>${formatMetricNumber(order.quantity, 4)}</td>
        <td>${formatMetricNumber(order.price, 2)}</td>
        <td><span class="cell-badge ${toneClass(orderStatusTone(order.status))}">${escapeHtml(formatOrderStatus(safeText(order.status, "n/a")))}</span></td>
      </tr>
    `;
    }).join("")
    : tableFallback(7, "暂无挂单。");
}

function renderExecutionInspector(payload = state.executionHub || {}) {
  const candidate = syncExecutionInspectorSelection(payload);
  const model = executionInspectorModel(candidate, payload);
  const pillNode = document.getElementById("execution-inspector-pill");
  pillNode.className = pillToneClass(model.tone);
  pillNode.textContent = model.pill;
  document.getElementById("execution-inspector-subtitle").textContent = model.subtitle;
  document.getElementById("execution-inspector-summary").innerHTML = model.summaryRows
    .map((row) => statusRow(row.label, row.value, row.tone))
    .join("");
  document.getElementById("execution-inspector-context").innerHTML = executionInspectorContextMarkup(model.contextRows);
  document.getElementById("execution-inspector-note").textContent = model.note;
  document.getElementById("execution-inspector-json").textContent = JSON.stringify(model.raw, null, 2);
}

function refreshExecutionInspectorSurfaces(payload = state.executionHub || {}) {
  renderExecutionEvents(Array.isArray(payload.events) ? payload.events : [], payload);
  renderExecutionPositions(Array.isArray(payload.positions) ? payload.positions : []);
  renderExecutionOrders(Array.isArray(payload.orders) ? payload.orders : []);
  renderExecutionInspector(payload);
}

function renderExecutionHub(payload) {
  state.executionHub = payload;
  const status = payload.status || {};
  const summary = payload.summary || {};
  const control = payload.control || {};
  const telemetry = payload.telemetry || {};
  const risk = payload.risk || {};
  const positions = Array.isArray(payload.positions) ? payload.positions : [];
  const orders = Array.isArray(payload.orders) ? payload.orders : [];
  const eventMix = payload.event_mix || {};
  const executionContext = payload.execution_context || {};

  const currentMeta = state.executionDraftMeta || executionDraftMetaDefaults();
  if (!currentMeta.edited) {
    const allowRuntimeValidationPatch = executionDraftUsesRuntimeValidation(currentMeta, control);
    const metaPatch = {};
    if (
      (currentMeta.sourceType === "manual" || currentMeta.sourceType === "runtime")
      && executionContext.source_type
    ) {
      metaPatch.sourceType = executionContext.source_type;
      metaPatch.sourceLabel = executionContext.source_label || currentMeta.sourceLabel;
      metaPatch.sourcePanel = executionContext.source_panel || currentMeta.sourcePanel;
    }
    if (!currentMeta.dataSource && executionContext.data_source) {
      metaPatch.dataSource = executionContext.data_source;
    }
    if (executionContext.data_mode) {
      metaPatch.dataMode = executionContext.data_mode;
    }
    if (executionContext.data_context_title) {
      metaPatch.dataContextTitle = executionContext.data_context_title;
    }
    if (executionContext.data_context_message) {
      metaPatch.dataContextMessage = executionContext.data_context_message;
    }
    if (allowRuntimeValidationPatch && !currentMeta.validationLabel && executionContext.validation_label) {
      metaPatch.validationLabel = executionContext.validation_label;
      metaPatch.validationTone = executionContext.validation_tone || currentMeta.validationTone;
    }
    if (allowRuntimeValidationPatch && executionContext.validation_reason) {
      metaPatch.validationReason = executionContext.validation_reason;
    }
    if (allowRuntimeValidationPatch && executionContext.validation_method) {
      metaPatch.validationMethod = executionContext.validation_method;
    }
    if (Object.keys(metaPatch).length) {
      setExecutionDraftMeta(metaPatch, { preserveEdited: true });
    }
  }

  document.getElementById("execution-captured-at").textContent = `更新时间：${formatTimestamp(payload.captured_at)}`;
  const statusPill = document.getElementById("execution-status-pill");
  statusPill.className = pillToneClass(safeText(status.tone, "muted"));
  statusPill.textContent = localizeUiText(safeText(status.label, "N/A"));
  document.getElementById("execution-hero-title").textContent = localizeUiText(safeText(status.session_label, "Stopped"));
  document.getElementById("execution-hero-text").textContent = safeText(status.summary, "暂无执行层摘要。");
  document.getElementById("execution-control-summary").textContent = safeText(
    control.status_note,
    "在这里直接启动、停机或熔断交易终端，深度遥测保留在交易会话页。",
  );

  const controlTone = safeText(control.status_tone, "muted");
  const controlNote = controlTone === "danger"
    ? "熔断中"
    : controlTone === "warning"
      ? "需关注"
      : control.running
        ? "运行中"
        : control.session_id
          ? "就绪"
          : "待机";
  setExecutionControlFeedback(controlNote, controlTone);

  document.getElementById("execution-summary-list").innerHTML = [
    statusRow("模式", formatTradingMode(summary.mode), summary.mode === "live" ? "warning" : "muted"),
    statusRow("交易对", safeText(summary.symbol, "N/A")),
    statusRow("周期", safeText(summary.timeframe, "N/A")),
    statusRow("策略", formatStrategyText(summary.strategy_text || summary.strategies || [])),
    statusRow("持仓", safeText(summary.position_count, 0), summary.position_count ? "accent" : "muted"),
    statusRow("挂单", safeText(summary.order_count, 0), summary.order_count ? "warning" : "muted"),
  ].join("");

  document.getElementById("execution-metrics").innerHTML = [
    metricCard("权益", formatMetricNumber(summary.equity, 2)),
    metricCard("现金", formatMetricNumber(summary.cash, 2)),
    metricCard("总名义金额", formatMetricNumber(summary.gross_notional, 2)),
    metricCard("挂单名义金额", formatMetricNumber(summary.pending_notional, 2)),
    metricCard("未实现盈亏", formatSignedMetricNumber(summary.unrealized_pnl, 2)),
    metricCard("回撤", formatPercent(summary.drawdown)),
  ].join("");

  document.getElementById("execution-risk-list").innerHTML = [
    statusRow("熔断开关", risk.kill_switch_active ? safeText(risk.kill_switch_reason, "已触发") : "已布防", risk.kill_switch_active ? "danger" : "accent"),
    statusRow("回撤保护", risk.drawdown_ok ? "正常" : "已触发", risk.drawdown_ok ? "accent" : "warning"),
    statusRow("警告", safeText(risk.warning_events, 0), risk.warning_events ? "warning" : "muted"),
    statusRow("错误", safeText(risk.error_events, 0), risk.error_events ? "danger" : "muted"),
  ].join("");

  document.getElementById("execution-activity-grid").innerHTML = [
    activityCard("订单", safeText(eventMix.by_type?.order, 0), eventMix.by_type?.order ? "accent" : "muted"),
    activityCard("成交", safeText(eventMix.by_type?.fill, 0), eventMix.by_type?.fill ? "accent" : "muted"),
    activityCard("信号", safeText(eventMix.by_type?.signal, 0), eventMix.by_type?.signal ? "accent" : "muted"),
    activityCard("风控", safeText(eventMix.by_type?.risk, 0), eventMix.by_type?.risk ? "warning" : "muted"),
    activityCard("信息", safeText(eventMix.by_level?.info, 0), eventMix.by_level?.info ? "accent" : "muted"),
    activityCard("严重", safeText(eventMix.by_level?.critical, 0), eventMix.by_level?.critical ? "danger" : "muted"),
  ].join("");

  const runtimePill = document.getElementById("execution-runtime-pill");
  runtimePill.className = pillToneClass(safeText(status.session_tone, controlTone));
  runtimePill.textContent = localizeUiText(safeText(status.session_label, control.running ? "Running" : "Idle"));
  document.getElementById("execution-config-brief").textContent = terminalConfigText(control);
  document.getElementById("execution-strategy-brief").textContent = formatStrategyText(
    control.strategies || control.strategy_text || [],
  );
  renderExecutionDraftSummary(control);
  document.getElementById("execution-control-list").innerHTML = [
    statusRow("会话 ID", safeText(control.session_id, "N/A")),
    statusRow("运行时长", safeText(control.uptime_label, "0s")),
    statusRow("轮询间隔", `${safeText(control.interval_seconds, 0)}s`),
    statusRow("资金", formatMetricNumber(control.capital, 2)),
    statusRow("持仓数", safeText(control.open_positions, 0), control.open_positions ? "accent" : "muted"),
    statusRow("挂单数", safeText(control.pending_orders, 0), control.pending_orders ? "warning" : "muted"),
  ].join("");
  document.getElementById("execution-runtime-metrics").innerHTML = [
    metricCard("遥测点", safeText(telemetry.point_count, 0)),
    metricCard("最新权益", formatMetricNumber(telemetry.equity_last, 2)),
    metricCard("最新现金", formatMetricNumber(telemetry.cash_last, 2)),
    metricCard("最新市值", formatMetricNumber(telemetry.market_value_last, 2)),
    metricCard("净敞口", formatSignedMetricNumber(control.net_exposure_value, 2)),
    metricCard("事件数", safeText(control.recent_event_count, 0)),
  ].join("");
  const executionTelemetryPill = document.getElementById("execution-telemetry-pill");
  executionTelemetryPill.className = pillToneClass(
    safeText(
      telemetry.point_count
        ? (state.executionChart.mode === "drawdown" ? "warning" : "accent")
        : "muted",
      "muted",
    ),
  );
  executionTelemetryPill.textContent = telemetry.point_count
    ? `${safeText(telemetry.point_count, 0)} 个点`
    : "冷启动";
  renderExecutionTelemetryChart();

  refreshExecutionInspectorSurfaces(payload);
  syncTerminalForms(control);
  refreshOverviewCommandDeck();
}

function renderMonitoring(payload) {
  state.monitoring = payload;
  const health = payload.health || {};
  const metrics = payload.metrics || {};
  const platform = payload.platform || {};
  const runtime = payload.runtime || {};
  const activity = payload.activity || {};
  const latest = payload.latest || {};
  const internal = payload.internal_metrics || {};
  const healthTone = safeText(health.overall_tone, "muted");

  document.getElementById("monitoring-captured-at").textContent = `更新时间：${formatTimestamp(payload.captured_at)}`;

  const healthPill = document.getElementById("monitoring-health-pill");
  healthPill.className = pillToneClass(healthTone);
  healthPill.textContent = localizeUiText(safeText(health.overall_label, "Unknown"), "Unknown");

  document.getElementById("monitoring-health-summary").textContent = safeText(
    localizeUiText(health.overall_label, "监控快照"),
    "监控快照",
  );
  document.getElementById("monitoring-health-text").textContent = safeText(
    localizeUiText(health.summary, "暂无监控摘要。"),
    "暂无监控摘要。",
  );
  document.getElementById("monitoring-health-signals").innerHTML = Array.isArray(health.signals) && health.signals.length
    ? health.signals
      .map(
        (signal, index) => `
          <div class="monitoring-signal ${toneClass(index === 0 ? healthTone : "muted")}">
            <span class="monitoring-signal-marker"></span>
            <span>${escapeHtml(localizeUiText(signal, signal))}</span>
          </div>
        `,
      )
      .join("")
    : '<div class="history-empty">暂无监控信号。</div>';

  document.getElementById("monitoring-metrics").innerHTML = [
    metricCard("服务连通", `${safeText(metrics.services_up, 0)}/${safeText(metrics.services_total, 0)}`),
    metricCard("验证不通过", safeText(metrics.validation_no_go, 0)),
    metricCard("订单总数", safeText(internal.orders_total, 0)),
    metricCard("信号总数", safeText(internal.signals_generated_total, 0)),
    metricCard("风控事件", safeText(internal.risk_events_total, 0)),
    metricCard("会话事件", safeText(metrics.session_events, 0)),
  ].join("");

  const services = Array.isArray(payload.services) ? payload.services : [];
  const prometheusService = services.find((service) => service.service_id === "prometheus") || {};
  document.getElementById("monitoring-services").innerHTML = services.length
    ? services.map((service, index) => {
      const key = monitoringInspectorItemKey("service", service, index);
      return monitoringServiceCard(service, {
        kind: "service",
        key,
        selected: state.monitoringInspector?.kind === "service" && state.monitoringInspector.key === key,
      });
    }).join("")
    : '<div class="history-empty">未配置监控服务。</div>';

  document.getElementById("monitoring-runtime").innerHTML = [
    statusRow("版本", safeText(platform.version, "N/A")),
    statusRow("阶段", safeText(platform.phase, "N/A")),
    statusRow("执行模式", formatTradingMode(platform.execution_mode), platform.execution_mode === "live" ? "warning" : "muted"),
    statusRow("数据模式", formatDataMode(platform.data_mode), dataModeTone(platform.data_mode)),
    statusRow("来源构成", formatSourceMix(platform.source_counts), Object.keys(platform.source_counts || {}).length ? dataModeTone(platform.data_mode) : "muted"),
    statusRow("来源说明", localizeUiText(safeText(platform.source_context?.title, "N/A"))),
    statusRow("Docker", localizeUiText(platform.docker_available ? "Ready" : "Missing"), platform.docker_available ? "accent" : "warning"),
    statusRow("熔断开关", localizeUiText(platform.kill_switch_enabled ? "Enabled" : "Disabled"), platform.kill_switch_enabled ? "accent" : "danger"),
    statusRow("Prometheus", localizeUiText(safeText(prometheusService.status_label, "N/A"), "N/A"), safeText(prometheusService.tone, "muted")),
    statusRow("导出器模式", localizeUiText(safeText(prometheusService.status_kind, "idle").replaceAll("_", " ")), safeText(prometheusService.tone, "muted")),
    statusRow("会话状态", localizeUiText(safeText(runtime.status_label, "Stopped"), "Stopped"), safeText(runtime.status_tone, "muted")),
    statusRow("会话 ID", safeText(runtime.session_id, "N/A")),
    statusRow("持仓数量", safeText(runtime.open_positions, 0), runtime.open_positions ? "accent" : "muted"),
    statusRow("挂单数量", safeText(runtime.pending_orders, 0), runtime.pending_orders ? "warning" : "muted"),
    statusRow("组合权益", formatMetricNumber(internal.portfolio_value, 2)),
    statusRow("现金", formatMetricNumber(internal.portfolio_cash, 2)),
    statusRow("回撤", formatPercent(internal.portfolio_drawdown)),
    statusRow("内部持仓", safeText(internal.positions_count, 0), Number(internal.positions_count || 0) > 0 ? "accent" : "muted"),
    statusRow("导出器错误", localizeUiText(safeText(prometheusService.last_error, "None"), "None"), prometheusService.last_error ? "danger" : "muted"),
  ].join("");

  document.getElementById("monitoring-activity-grid").innerHTML = [
    activityCard("验证通过", safeText(metrics.validation_go, 0), metrics.validation_go ? "accent" : "muted"),
    activityCard("验证不通过", safeText(metrics.validation_no_go, 0), metrics.validation_no_go ? "warning" : "muted"),
    activityCard("告警", safeText(metrics.warning_events, 0), metrics.warning_events ? "warning" : "muted"),
    activityCard("错误", safeText(metrics.error_events, 0), metrics.error_events ? "danger" : "muted"),
    activityCard("已成交订单", safeText(internal.orders_filled_total, 0), Number(internal.orders_filled_total || 0) > 0 ? "accent" : "muted"),
    activityCard("Bar 延迟", formatLatencyMs(internal.bar_latency_avg), Number(internal.bar_latency_count || 0) > 0 ? "accent" : "muted"),
    activityCard("信号延迟", formatLatencyMs(internal.signal_latency_avg), Number(internal.signal_latency_count || 0) > 0 ? "accent" : "muted"),
    activityCard("订单延迟", formatLatencyMs(internal.order_latency_avg), Number(internal.order_latency_count || 0) > 0 ? "accent" : "muted"),
    activityCard("事件类型", compactMapSummary(activity.event_types), Object.keys(activity.event_types || {}).length ? "accent" : "muted"),
    activityCard("验证分布", compactMapSummary(activity.validation_outcomes), metrics.validation_no_go ? "warning" : "muted"),
  ].join("");

  const latestResearch = latest.research || {};
  const latestValidation = latest.validation || {};
  const latestSession = latest.session || {};
  const latestValidationSummary = latestValidation.summary || {};
  const latestResearchTitle = latestResearch.request
    ? localizeStrategyTitle(latestResearch.strategy, latestResearch.request.strategy || latestResearch.strategy)
    : localizeStrategyTitle(latestResearch.strategy, latestResearch.strategy);
  const latestResearchSelection = { ...latestResearch, latest_kind: "research" };
  const latestValidationSelection = { ...latestValidation, latest_kind: "validation" };
  const latestSessionSelection = { ...latestSession, latest_kind: "session" };
  const latestResearchKey = monitoringInspectorItemKey("latest", latestResearchSelection, 0);
  const latestValidationKey = monitoringInspectorItemKey("latest", latestValidationSelection, 1);
  const latestSessionKey = monitoringInspectorItemKey("latest", latestSessionSelection, 2);
  document.getElementById("monitoring-latest-grid").innerHTML = [
    monitoringLatestCard(
      "最近研究",
      formatDataSource(latestResearch.data_source),
      dataSourceTone(latestResearch.data_source),
      `${safeText(latestResearchTitle, "暂无运行")} | ${safeText(latestResearch.symbol, "N/A")} | ${formatTimestamp(latestResearch.created_at)}`,
      [
        ["收益率", formatPercent(latestResearch.summary?.total_return)],
        ["Sharpe", formatMetricNumber(latestResearch.summary?.sharpe_ratio)],
        ["最大回撤", formatPercent(latestResearch.summary?.max_drawdown)],
      ],
      "最近一次回测表现快照。",
      latestResearch.request
        ? `<button class="button ghost small" data-monitoring-action="open-research">打开研究</button>
           <button class="button primary small" data-monitoring-action="research-stage-execution">送入执行草稿</button>`
        : "",
      {
        kind: "latest",
        key: latestResearchKey,
        selected: state.monitoringInspector?.kind === "latest" && state.monitoringInspector.key === latestResearchKey,
      },
    ),
    monitoringLatestCard(
      "最近验证",
      safeText(latestValidationSummary.outcome_label || latestValidationSummary.decision, "N/A"),
      validationOutcomeTone(latestValidationSummary),
      `${localizeUiText(safeText(latestValidationSummary.method_label, latestValidationSummary.method || "Validation"))} | ${safeText(latestValidation.symbol, "N/A")} | ${formatTimestamp(latestValidation.created_at)}`,
      [
        ["原因", localizeUiText(safeText(latestValidationSummary.reason, "暂无原因"), "暂无原因")],
        ["开仓信号", safeText(latestValidationSummary.entries, 0)],
        ["平仓信号", safeText(latestValidationSummary.exits, 0)],
      ],
      "最近一次验证结论与运维上下文。",
      latestValidation.request
        ? `<button class="button ghost small" data-monitoring-action="open-validation">打开验证</button>
           <button class="button primary small" data-monitoring-action="validation-stage-execution">送入执行草稿</button>`
        : "",
      {
        kind: "latest",
        key: latestValidationKey,
        selected: state.monitoringInspector?.kind === "latest" && state.monitoringInspector.key === latestValidationKey,
      },
    ),
    monitoringLatestCard(
      "最近会话",
      latestSession.running ? "运行中" : "已停止",
      latestSession.running ? "accent" : "muted",
      `${formatTradingMode(latestSession.request?.mode || "paper")} | ${safeText(latestSession.request?.symbol, "N/A")} | ${formatTimestamp(latestSession.started_at)}`,
      [
        ["权益", formatMetricNumber(latestSession.portfolio?.equity ?? latestSession.portfolio?.total_value, 2)],
        ["持仓", safeText(latestSession.health?.open_positions, 0)],
        ["挂单", safeText(latestSession.health?.pending_orders, 0)],
      ],
      "最近一次受管交易会话快照。",
      latestSession.request
        ? `<button class="button ghost small" data-monitoring-action="open-session">打开会话</button>
           <button class="button primary small" data-monitoring-action="session-stage-execution">送入执行草稿</button>`
        : "",
      {
        kind: "latest",
        key: latestSessionKey,
        selected: state.monitoringInspector?.kind === "latest" && state.monitoringInspector.key === latestSessionKey,
      },
    ),
  ].join("");

  const alerts = Array.isArray(payload.alerts) ? payload.alerts : [];
  document.getElementById("monitoring-alert-count").textContent = String(alerts.length);
  document.getElementById("monitoring-alerts").innerHTML = alerts.length
    ? alerts
      .map(
        (alert, index) => {
          const key = monitoringInspectorItemKey("alert", alert, index);
          const selected = state.monitoringInspector?.kind === "alert" && state.monitoringInspector.key === key;
          return `
          <article class="history-card monitoring-alert-card monitoring-selectable ${selected ? "is-selected" : ""} ${toneClass(safeText(alert.tone, "muted"))}" tabindex="0" data-monitoring-inspector-kind="alert" data-monitoring-inspector-key="${escapeHtml(key)}">
            <div class="history-top">
              <strong>${escapeHtml(localizeUiText(safeText(alert.title, "Alert"), "Alert"))}</strong>
              <span class="${pillToneClass(safeText(alert.tone, "muted"))}">${escapeHtml(localizeUiText(safeText(alert.source, "system"), "system"))}</span>
            </div>
            <div class="history-note">${escapeHtml(localizeUiText(safeText(alert.message, "No details"), "No details"))}</div>
            ${monitoringAlertActions(alert)}
            <div class="monitoring-alert-meta">
              <span>${escapeHtml(formatTimestamp(alert.created_at))}</span>
            </div>
          </article>
        `;
        },
      )
      .join("")
    : '<div class="history-empty">暂无告警。</div>';
  renderMonitoringInspector(payload);
  persistWorkbenchState();
  refreshOverviewCommandDeck();
}

function selectMonitoringInspector(kind = null, key = null) {
  if (!state.monitoring) {
    return;
  }
  state.monitoringInspector = monitoringInspectorSelection(kind, key);
  renderMonitoring(state.monitoring);
}

function renderHistoryList(elementId, counterId, items, formatItem) {
  const node = document.getElementById(elementId);
  const counter = document.getElementById(counterId);
  counter.textContent = String(items.length);
  if (!items.length) {
    node.innerHTML = '<div class="history-empty">暂无记录。</div>';
    return;
  }
  node.innerHTML = items.map(formatItem).join("");
}

function renderResearchHistory(items) {
  state.researchHistory = items;
  renderHistoryList("research-history", "research-history-count", items, (item) => `
    <article class="history-card ${isActiveResearchHistoryRecord(item) ? "is-active" : ""}" data-history-record-id="${item.record_id || ""}">
      <div class="history-top">
        <strong>${localizeStrategyTitle(item.strategy, item.request?.strategy || item.strategy)}</strong>
        <span class="${pillToneClass(dataSourceTone(item.data_source))}">${escapeHtml(formatDataSource(item.data_source))}</span>
      </div>
      <div class="history-meta">${safeText(item.symbol)} | ${formatTimestamp(item.created_at)}</div>
      <div class="history-grid">
        <span>收益率 ${formatPercent(item.summary?.total_return)}</span>
        <span>Sharpe ${formatMetricNumber(item.summary?.sharpe_ratio)}</span>
        <span>最大回撤 ${formatPercent(item.summary?.max_drawdown)}</span>
        <span>交易笔数 ${safeText(item.summary?.num_trades, 0)}</span>
      </div>
      <div class="history-actions">
        <button class="button ghost small" data-history-kind="research" data-history-action="open" data-record-id="${item.record_id}">${isActiveResearchHistoryRecord(item) ? "查看中" : "打开结果"}</button>
        <button class="button ghost small" data-history-kind="research" data-history-action="load" data-record-id="${item.record_id}">加载参数</button>
        <button class="button ghost small" data-history-kind="research" data-history-action="rerun" data-record-id="${item.record_id}">再次运行</button>
        <button class="button primary small" data-history-kind="research" data-history-action="stage-execution" data-record-id="${item.record_id}">送入执行草稿</button>
      </div>
    </article>
  `);
  renderResearchDecisionSurface();
  refreshOverviewCommandDeck();
}

function renderValidationHistory(items) {
  state.validationHistory = items;
  renderHistoryList("validation-history", "validation-history-count", items, (item) => `
    <article class="history-card ${isActiveValidationHistoryRecord(item) ? "is-active" : ""}" data-history-record-id="${item.record_id || ""}">
      <div class="history-top">
        <strong>${localizeStrategyTitle(item.strategy, item.request?.strategy || item.strategy)}</strong>
        <span class="${pillToneClass(validationOutcomeTone(item.summary || {}))}">${localizeUiText(safeText(item.summary?.outcome_label || item.summary?.decision, "待检测"), "待检测")}</span>
      </div>
      <div class="history-meta">${safeText(item.symbol)} | ${localizeUiText(safeText(item.summary?.method_label, item.summary?.method || "Validation"), "验证")} | ${formatTimestamp(item.created_at)}</div>
      <div class="history-grid">
        <span>${validationHistoryPrimaryMetric(item.summary || {})}</span>
        <span>入场数 ${safeText(item.summary?.entries, 0)}</span>
        <span>出场数 ${safeText(item.summary?.exits, 0)}</span>
        <span>Bar 数 ${safeText(item.summary?.bars, 0)}</span>
      </div>
      <div class="history-note">${localizeUiText(safeText(item.summary?.reason, "暂无原因"), "暂无原因")}</div>
      <div class="history-actions">
        <button class="button ghost small" data-history-kind="validation" data-history-action="open" data-record-id="${item.record_id}">${isActiveValidationHistoryRecord(item) ? "查看中" : "打开结果"}</button>
        <button class="button ghost small" data-history-kind="validation" data-history-action="load" data-record-id="${item.record_id}">加载参数</button>
        <button class="button ghost small" data-history-kind="validation" data-history-action="rerun" data-record-id="${item.record_id}">再次运行</button>
        <button class="button primary small" data-history-kind="validation" data-history-action="stage-execution" data-record-id="${item.record_id}">送入执行草稿</button>
      </div>
    </article>
  `);
  renderResearchDecisionSurface();
  refreshOverviewCommandDeck();
}

function validationHistoryPrimaryMetric(summary = {}) {
  const label = summary.primary_metric_label;
  const value = summary.primary_metric_value;
  if (label && value !== null && value !== undefined && value !== "") {
    return `${localizeUiText(label, label)} ${formatValidationValue(value, summary.primary_metric_format)}`;
  }
  if (summary.method_label || summary.method) {
    return `${localizeUiText(safeText(summary.method_label, summary.method), "验证")}运行`;
  }
  return "验证运行";
}

function sourceContextIncludesRecord(context = null, panel, recordId) {
  if (!panel || !recordId) {
    return false;
  }
  const normalized = normalizeSourceContext(context);
  if (!normalized) {
    return false;
  }
  return [normalized, ...(normalized.trail || [])]
    .some((item) => item.panel === panel && item.recordId === recordId);
}

function researchPayloadRecordId(payload = {}) {
  return historyRecordIdOf(payload) || payload.record_id || payload.history_record?.record_id || null;
}

function researchPayloadMatchesRecord(record = {}, payload = {}) {
  const request = payload.request || {};
  const recordRequest = record.request || {};
  const strategy = safeText(request.strategy, "");
  const symbol = safeText(request.symbol, "");
  if (strategy && safeText(record.strategy || recordRequest.strategy, "") !== strategy) {
    return false;
  }
  if (symbol && safeText(record.symbol || recordRequest.symbol, "") !== symbol) {
    return false;
  }
  return Boolean(strategy || symbol);
}

function researchDateLabel(value) {
  const text = safeText(value, "").trim();
  if (!text) {
    return null;
  }
  if (/^\d{4}-\d{2}-\d{2}/.test(text)) {
    const date = new Date(text);
    return Number.isNaN(date.getTime()) ? null : date.toISOString().slice(0, 10);
  }
  if (/^\d{10,13}$/.test(text)) {
    const raw = Number(text);
    if (!Number.isFinite(raw)) {
      return null;
    }
    const millis = text.length <= 10 ? raw * 1000 : raw;
    const date = new Date(millis);
    return Number.isNaN(date.getTime()) ? null : date.toISOString().slice(0, 10);
  }
  return null;
}

function researchPeriodText(payload = {}) {
  const request = payload.request || {};
  const result = payload.result || {};
  const candles = Array.isArray(payload.chart?.candles) ? payload.chart.candles : [];
  const lastCandle = candles.length ? candles[candles.length - 1] : null;
  const candidates = [
    [candles[0]?.label, lastCandle?.label],
    [request.start, request.end],
    [result.start_date, result.end_date],
  ];
  for (const [start, end] of candidates) {
    const startLabel = researchDateLabel(start);
    const endLabel = researchDateLabel(end);
    if (startLabel && endLabel) {
      return `${startLabel} - ${endLabel}`;
    }
  }
  const fallbackStart = safeText(candles[0]?.label || request.start || result.start_date, "");
  const fallbackEnd = safeText(lastCandle?.label || request.end || result.end_date, "");
  if (fallbackStart && fallbackEnd) {
    return `样本 ${fallbackStart} - ${fallbackEnd}`;
  }
  return "待检测";
}

function readParamEditorSnapshot(panel) {
  const controls = document.querySelectorAll(`#${panel}-params [data-param-key]`);
  const params = {};
  controls.forEach((control) => {
    const key = control.dataset.paramKey;
    const paramType = control.dataset.paramType;
    const raw = control.type === "checkbox" ? control.checked : control.value;
    try {
      params[key] = parseParamValue(raw, paramType);
    } catch (error) {
      params[key] = typeof raw === "string" ? raw.trim() : raw;
    }
  });
  return params;
}

function normalizeResearchRequest(request = {}) {
  return {
    strategy: request.strategy ? String(request.strategy).trim() : "",
    symbol: request.symbol ? String(request.symbol).trim() : "",
    capital: Number.isFinite(Number(request.capital)) ? Number(request.capital) : null,
    fee: Number.isFinite(Number(request.fee)) ? Number(request.fee) : null,
    start: request.start ? String(request.start).trim() : "",
    end: request.end ? String(request.end).trim() : "",
    config_path: request.config_path ? String(request.config_path).trim() : "",
    params: deepClone(request.params || {}),
  };
}

function currentResearchDraftRequest() {
  const form = document.getElementById("research-form");
  const strategyId = form?.elements.strategy?.value || state.latestResearchResult?.request?.strategy || "";
  return normalizeResearchRequest({
    strategy: strategyId,
    symbol: form?.elements.symbol?.value,
    capital: form?.elements.capital?.value,
    fee: form?.elements.fee?.value,
    start: form?.elements.start?.value,
    end: form?.elements.end?.value,
    config_path: state.strategyMap[strategyId]?.config_path || state.latestResearchResult?.request?.config_path || "",
    params: readParamEditorSnapshot("research"),
  });
}

function researchComparableValue(value) {
  if (Array.isArray(value)) {
    return value.map((item) => researchComparableValue(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, researchComparableValue(value[key])]),
    );
  }
  if (typeof value === "number") {
    return Number.isFinite(value) ? Number(value) : null;
  }
  if (typeof value === "string") {
    return value.trim();
  }
  return value;
}

function researchValuesEqual(left, right) {
  return JSON.stringify(researchComparableValue(left)) === JSON.stringify(researchComparableValue(right));
}

function formatResearchValue(value, key = "") {
  if (value === null || value === undefined || value === "") {
    return "待检测";
  }
  if (typeof value === "boolean") {
    return formatBoolean(value);
  }
  if (typeof value === "number") {
    if (key === "capital") {
      return formatMetricNumber(value, 0);
    }
    if (key === "fee") {
      return formatMetricNumber(value, 4);
    }
    return Number.isInteger(value) ? String(value) : formatMetricNumber(value, Math.abs(value) >= 1 ? 3 : 4);
  }
  if (typeof value === "string") {
    const dateLabel = key === "start" || key === "end" ? researchDateLabel(value) : null;
    return dateLabel || value;
  }
  if (Array.isArray(value) || (value && typeof value === "object")) {
    return JSON.stringify(value);
  }
  return String(value);
}

function researchTunedParamCount(strategyId, params = {}) {
  const strategy = state.strategyMap[strategyId] || {};
  const defaults = strategy.params || {};
  return Object.keys(params).filter((key) => !researchValuesEqual(defaults[key], params[key])).length;
}

function researchRequestDiffRows(baselineRequest = {}, draftRequest = {}, options = {}) {
  const baseline = normalizeResearchRequest(baselineRequest);
  const draft = normalizeResearchRequest(draftRequest);
  const includeParams = options.includeParams !== false;
  const rows = [];
  const topLevelFields = [
    ["strategy", "策略"],
    ["symbol", "交易对"],
    ["capital", "资金"],
    ["fee", "手续费"],
    ["start", "开始"],
    ["end", "结束"],
  ];

  topLevelFields.forEach(([key, label]) => {
    if (!researchValuesEqual(baseline[key], draft[key])) {
      rows.push({
        label,
        before: formatResearchValue(baseline[key], key),
        after: formatResearchValue(draft[key], key),
      });
    }
  });

  if (includeParams) {
    const baselineParams = baseline.params || {};
    const draftParams = draft.params || {};
    const paramKeys = [...new Set([...Object.keys(baselineParams), ...Object.keys(draftParams)])].sort();
    paramKeys.forEach((key) => {
      if (!researchValuesEqual(baselineParams[key], draftParams[key])) {
        rows.push({
          label: `参数 / ${key}`,
          before: formatResearchValue(baselineParams[key], key),
          after: formatResearchValue(draftParams[key], key),
        });
      }
    });
  }

  return rows;
}

function researchOpsKpi(label, value, note, tone = "muted") {
  return `
    <article class="research-ops-kpi ${toneClass(tone)}">
      <span class="research-ops-kpi-label">${escapeHtml(label)}</span>
      <strong class="research-ops-kpi-value">${escapeHtml(String(value))}</strong>
      <span class="research-ops-kpi-note">${escapeHtml(note)}</span>
    </article>
  `;
}

function researchDiffRowsMarkup(rows = [], emptyText = "当前表单与已加载的研究结果一致。") {
  if (!rows.length) {
    return `<div class="history-empty">${escapeHtml(emptyText)}</div>`;
  }
  return `
    <div class="research-diff-list">
      ${rows.map((row) => `
        <article class="research-diff-row">
          <div class="research-diff-head">
            <strong>${escapeHtml(row.label)}</strong>
            <span class="${pillToneClass("warning")}">已变更</span>
          </div>
          <div class="research-diff-values">
            <div class="research-diff-value">
              <span class="research-diff-label">已加载</span>
              <strong>${escapeHtml(row.before)}</strong>
            </div>
            <div class="research-diff-value">
              <span class="research-diff-label">当前草稿</span>
              <strong>${escapeHtml(row.after)}</strong>
            </div>
          </div>
        </article>
      `).join("")}
    </div>
  `;
}

function researchParamSnapshotMarkup(strategyId, params = {}) {
  const paramKeys = Object.keys(params);
  if (!paramKeys.length) {
    return '<div class="history-empty">当前研究记录没有携带参数快照。</div>';
  }
  const defaults = (state.strategyMap[strategyId] || {}).params || {};
  return `
    <div class="status-list compact-status-list">
      ${paramKeys.slice(0, 8).map((key) => statusRow(
        key,
        formatResearchValue(params[key], key),
        researchValuesEqual(defaults[key], params[key]) ? "muted" : "accent",
      )).join("")}
      ${paramKeys.length > 8 ? statusRow("其他参数", `+${paramKeys.length - 8}`, "muted") : ""}
    </div>
  `;
}

function researchValidationCompareMarkup(payload = {}, validationRecord = null) {
  if (!validationRecord) {
    return `
      <article class="research-compare-card tone-warning">
        <span class="research-ops-kpi-label">验证门禁</span>
        <strong class="research-compare-value">待验证</strong>
        <span class="research-ops-kpi-note">当前研究结果还没有形成对应的验证记录，应先送入验证。</span>
      </article>
    `;
  }

  const validationSummary = validationRecord.summary || {};
  const baselineParamCount = Object.keys(payload.request?.params || {}).length;
  const diffCount = researchRequestDiffRows(payload.request || {}, validationRecord.request || {}, {
    includeParams: baselineParamCount > 0,
  }).length;
  const diffNote = baselineParamCount
    ? (diffCount
      ? "最近验证记录与研究基线已出现请求或参数差异。"
      : "最近验证记录与研究基线保持一致。")
    : "当前研究记录未保存参数快照，这里仅比较请求层面的差异。";
  return `
    <div class="research-compare-grid">
      <article class="research-compare-card ${toneClass(validationOutcomeTone(validationSummary))}">
        <span class="research-ops-kpi-label">放行结论</span>
        <strong class="research-compare-value">${escapeHtml(safeText(validationSummary.outcome_label || validationSummary.decision, "验证"))}</strong>
        <span class="research-ops-kpi-note">${escapeHtml(safeText(validationSummary.reason, "最近的验证记录已加载。"))}</span>
      </article>
      <article class="research-compare-card">
        <span class="research-ops-kpi-label">门禁方法</span>
        <strong class="research-compare-value">${escapeHtml(safeText(validationSummary.method_label || validationSummary.method, "Validation"))}</strong>
        <span class="research-ops-kpi-note">${escapeHtml(validationHistoryPrimaryMetric(validationSummary))}</span>
      </article>
      <article class="research-compare-card">
        <span class="research-ops-kpi-label">参数差异</span>
        <strong class="research-compare-value">${escapeHtml(String(diffCount))}</strong>
        <span class="research-ops-kpi-note">${escapeHtml(diffNote)}</span>
      </article>
    </div>
  `;
}

function researchOpsBoard(payload = {}) {
  const request = normalizeResearchRequest(payload.request || {});
  const draft = currentResearchDraftRequest();
  const strategyId = request.strategy || draft.strategy;
  const strategy = state.strategyMap[strategyId] || {};
  const validationRecord = linkedValidationRecordForResearch(payload);
  const paramCount = Object.keys(request.params || {}).length;
  const hasParamSnapshot = paramCount > 0;
  const diffRows = researchRequestDiffRows(request, draft, { includeParams: hasParamSnapshot });
  const tunedCount = researchTunedParamCount(strategyId, request.params || {});
  const draftTunedCount = researchTunedParamCount(draft.strategy || strategyId, draft.params || {});
  const diffEmptyText = hasParamSnapshot
    ? "当前表单与已加载的研究结果一致。"
    : "当前研究记录未保存参数快照，暂时只比较表单请求层面的差异。";
  const diffKpiNote = hasParamSnapshot
    ? (diffRows.length
      ? "当前表单与已加载研究结果存在差异。"
      : "当前表单与已加载研究结果一致。")
    : "研究记录未保存参数快照，暂时不对比参数层变更。";

  return `
    <article class="research-ops-panel">
      <div class="surface-head">
        <div>
          <h3>参数快照</h3>
          <div class="surface-subtitle">把这次研究的参数基线与当前草稿放在同一个决策面板里。</div>
        </div>
        <span class="${pillToneClass("accent")}">${escapeHtml(configAssetLabel(request.config_path || strategy.config_path, "已加载"))}</span>
      </div>
      <div class="research-ops-kpis">
        ${researchOpsKpi("参数数量", paramCount, "研究记录携带的参数项数。", paramCount ? "accent" : "muted")}
        ${researchOpsKpi("偏离默认", tunedCount, "相对策略默认值，已调整的参数数量。", tunedCount ? "warning" : "muted")}
        ${researchOpsKpi("当前草稿", diffRows.length, diffKpiNote, diffRows.length ? "warning" : "accent")}
      </div>
      <div class="research-ops-summary">
        <div class="status-list compact-status-list">
          ${statusRow("策略", localizeStrategyTitle(strategyId, strategyId), "accent")}
          ${statusRow("交易对", safeText(request.symbol, "BTC/USDT"))}
          ${statusRow("资金", formatResearchValue(request.capital, "capital"))}
          ${statusRow("手续费", formatResearchValue(request.fee, "fee"))}
          ${statusRow("时间窗口", researchPeriodText(payload))}
          ${statusRow("当前偏离默认", draftTunedCount, draftTunedCount ? "warning" : "muted")}
        </div>
        <div class="research-param-snapshot">
          ${researchParamSnapshotMarkup(strategyId, request.params || {})}
        </div>
      </div>
    </article>
    <article class="research-ops-panel">
      <div class="surface-head">
        <div>
          <h3>当前草稿差异</h3>
          <div class="surface-subtitle">直接比较已加载研究结果与当前表单，决定是否需要重跑回测。</div>
        </div>
        <span class="${pillToneClass(diffRows.length ? "warning" : "accent")}">${escapeHtml(diffRows.length ? `${diffRows.length} 项变更` : "已保持一致")}</span>
      </div>
      ${researchDiffRowsMarkup(diffRows, diffEmptyText)}
    </article>
    <article class="research-ops-panel">
      <div class="surface-head">
        <div>
          <h3>研究 - 验证对照</h3>
          <div class="surface-subtitle">把最近验证结论、主指标和参数差异放在同一个研究面板里。</div>
        </div>
        <span class="${pillToneClass(validationRecord ? validationOutcomeTone(validationRecord.summary || {}) : "warning")}">${escapeHtml(validationRecord ? safeText(validationRecord.summary?.method_label || validationRecord.summary?.method, "Validation") : "待验证")}</span>
      </div>
      ${researchValidationCompareMarkup(payload, validationRecord)}
    </article>
  `;
}

function researchDecisionTone(score = 0) {
  if (score >= 0.7) {
    return "accent";
  }
  if (score >= 0.45) {
    return "warning";
  }
  return "danger";
}

function researchDecisionTrack(label, valueText, score, note, tone = null) {
  const safeScore = clamp(Math.round((Number(score) || 0) * 100), 0, 100);
  const resolvedTone = tone || researchDecisionTone(Number(score) || 0);
  return `
    <article class="research-track-card ${toneClass(resolvedTone)}">
      <div class="research-track-head">
        <span class="research-track-label">${escapeHtml(localizeInlineText(label, label))}</span>
        <strong class="research-track-value">${escapeHtml(localizeInlineText(valueText, valueText))}</strong>
      </div>
      <div class="research-track-rail ${toneClass(resolvedTone)}">
        <div class="research-track-fill" style="width: ${safeScore}%"></div>
      </div>
      <div class="research-track-note">${escapeHtml(localizeInlineText(note, note))}</div>
    </article>
  `;
}

function researchReadinessCard(label, value, note, tone = "muted") {
  return `
    <article class="research-readiness-card ${toneClass(tone)}">
      <span class="research-readiness-label">${escapeHtml(localizeInlineText(label, label))}</span>
      <strong class="research-readiness-value">${escapeHtml(localizeInlineText(value, value))}</strong>
      <span class="research-flow-note">${escapeHtml(localizeInlineText(note, note))}</span>
    </article>
  `;
}

function researchFlowItem(item) {
  return `
    <article class="research-flow-item ${item.active ? "active" : ""} ${toneClass(item.tone || "muted")}">
      <div class="research-flow-item-head">
        <span class="research-flow-item-title">${escapeHtml(localizeInlineText(item.title, item.title))}</span>
        <span class="${pillToneClass(item.tone || "muted")}">${escapeHtml(localizeInlineText(item.badge, item.badge))}</span>
      </div>
      <div class="research-flow-note">${escapeHtml(localizeInlineText(item.note, item.note))}</div>
      <div class="research-flow-item-meta">
        <span class="research-readiness-label">${escapeHtml(localizeInlineText(item.valueLabel, item.valueLabel))}</span>
        <strong class="research-flow-item-value">${escapeHtml(localizeInlineText(item.valueText, item.valueText))}</strong>
      </div>
    </article>
  `;
}

function linkedValidationRecordForResearch(payload = {}) {
  const recordId = researchPayloadRecordId(payload);
  const candidates = [state.latestValidationResult, ...state.validationHistory].filter(Boolean);

  if (recordId) {
    const direct = candidates.find((record) => sourceContextIncludesRecord(
      validationRecordSourceContext(record),
      "research",
      recordId,
    ));
    if (direct) {
      return direct;
    }
  }

  return candidates.find((record) => researchPayloadMatchesRecord(record, payload)) || null;
}

function linkedExecutionDraftForResearch(payload = {}) {
  const recordId = researchPayloadRecordId(payload);
  const request = payload.request || {};
  const meta = state.executionDraftMeta || executionDraftMetaDefaults();
  const context = normalizeSourceContext(meta);
  const linkedByRecord = Boolean(recordId) && sourceContextIncludesRecord(context, "research", recordId);
  const linkedByMatch = safeText(meta.sourcePanel, "") === "research"
    && (!request.strategy || meta.sourceStrategy === request.strategy)
    && (!request.symbol || meta.sourceSymbol === request.symbol);
  const linked = linkedByRecord || linkedByMatch;
  if (!linked) {
    return {
      linked: false,
      badge: "未衔接",
      tone: "muted",
      note: "当前研究结果还没有进入执行草稿链路。",
      valueLabel: "下一步",
      valueText: "先送去验证或执行草稿",
    };
  }
  return {
    linked: true,
    badge: meta.edited ? "草稿已调整" : "已进入执行草稿",
    tone: meta.edited ? "warning" : "accent",
    note: meta.edited
      ? "执行草稿已经被手动调整，启动前应重新核对关键参数。"
      : "当前执行草稿已经与这次研究结果建立关联。",
    valueLabel: "草稿配置",
    valueText: `${terminalConfigText(state.terminalDraft)} | ${terminalStrategyText(state.terminalDraft.strategies)}`,
  };
}

function researchDecisionStatus(score, validationRecord, executionDraft) {
  const validationTone = validationRecord ? validationOutcomeTone(validationRecord.summary || {}) : "muted";
  if (validationTone === "danger") {
    return { label: "先回验证复核", tone: "danger", note: "最近的验证结论仍是阻塞状态，应先处理门禁问题。" };
  }
  if (validationTone === "accent" && executionDraft.linked) {
    return { label: "可进入执行准备", tone: "accent", note: "研究结果已通过验证，并已进入执行草稿链路。" };
  }
  if (validationTone === "accent") {
    return { label: "可送入执行草稿", tone: "accent", note: "验证已放行，下一步应推进到执行准备。" };
  }
  if (!validationRecord && score >= 0.62) {
    return { label: "可送去验证", tone: "accent", note: "回测质量已具备基础信心，下一步应进入验证门禁。" };
  }
  if (score >= 0.45) {
    return { label: "需要复核研究", tone: "warning", note: "结果可参考，但还需要结合信号质量、风险和样本继续判断。" };
  }
  return { label: "先优化策略", tone: "danger", note: "当前研究质量不足以继续推进到验证或执行层。" };
}

function researchDecisionBoard(payload = {}) {
  const request = payload.request || {};
  const result = payload.result || {};
  const validationRecord = linkedValidationRecordForResearch(payload);
  const executionDraft = linkedExecutionDraftForResearch(payload);
  const validationSummary = validationRecord?.summary || {};
  const validationTone = validationOutcomeTone(validationSummary);
  const alphaScore = validationAverage([
    validationNormalize(result.sharpe_ratio, -0.5, 2.5),
    validationNormalize(result.total_return, -0.15, 0.5),
  ]);
  const riskScore = validationAverage([
    validationNormalize(Math.abs(validationNumeric(result.max_drawdown) || 0), 0, 0.35, true),
    validationNormalize(result.profit_factor, 0.7, 2.5),
  ]);
  const executionScore = validationAverage([
    validationNormalize(result.num_trades, 2, 40),
    validationNormalize(result.win_rate, 0.35, 0.75),
  ]);
  const dataSourceScore = dataSourceTone(payload.data_source) === "accent"
    ? 1
    : dataSourceTone(payload.data_source) === "warning"
      ? 0.4
      : 0.55;
  const validationScore = validationRecord
    ? validationTone === "accent"
      ? 1
      : validationTone === "warning"
        ? 0.55
        : 0.18
    : 0.38;
  const workflowScore = validationAverage([
    dataSourceScore,
    validationScore,
    executionDraft.linked ? 0.85 : 0.35,
  ]);
  let overallScore = validationAverage([alphaScore, riskScore, executionScore, workflowScore]);
  if (validationTone === "danger") {
    overallScore = Math.min(overallScore, 0.45);
  }
  const recommendation = researchDecisionStatus(overallScore, validationRecord, executionDraft);
  const scorePercent = clamp(Math.round(overallScore * 100), 0, 100);
  const strategyTitle = localizeStrategyTitle(request.strategy, request.strategy);
  const strategyDescription = localizeStrategyDescription("", request.strategy);
  const researchFlowItems = [
    {
      title: "研究结果",
      badge: "已加载",
      tone: "accent",
      active: true,
      note: strategyDescription,
      valueLabel: "Sharpe / 最大回撤",
      valueText: `${formatMetricNumber(result.sharpe_ratio)} / ${formatPercent(result.max_drawdown)}`,
    },
    {
      title: "验证门禁",
      badge: validationRecord
        ? safeText(validationSummary.outcome_label || validationSummary.decision, "验证")
        : "待验证",
      tone: validationRecord ? validationTone : "warning",
      active: Boolean(validationRecord),
      note: validationRecord
        ? safeText(validationSummary.reason, "最近的验证结果已加载。")
        : "这次研究结果还没有形成对应的验证门禁记录。",
      valueLabel: validationRecord ? "方法" : "下一步",
      valueText: validationRecord
        ? safeText(validationSummary.method_label || validationSummary.method, "Validation")
        : "先送入验证",
    },
    {
      title: "执行草稿",
      badge: executionDraft.badge,
      tone: executionDraft.tone,
      active: executionDraft.linked,
      note: executionDraft.note,
      valueLabel: executionDraft.valueLabel,
      valueText: executionDraft.valueText,
    },
  ];
  return `
    <section class="research-decision-panel">
      <div class="research-decision-head">
        <div class="research-decision-copy">
          <div class="label">研究决策台</div>
          <h3 class="research-decision-title">${escapeHtml(`${strategyTitle} / ${safeText(request.symbol, "BTC/USDT")}`)}</h3>
          <div class="research-decision-subtitle">${escapeHtml(strategyDescription)}</div>
        </div>
        <span class="${pillToneClass(recommendation.tone)}">${escapeHtml(recommendation.label)}</span>
      </div>
      <div class="research-readiness-grid">
        ${researchReadinessCard("数据源", formatDataSource(payload.data_source), "当前回测样本来源。", dataSourceTone(payload.data_source))}
        ${researchReadinessCard("回测区间", researchPeriodText(payload), "用于判断样本覆盖时间范围。", "muted")}
        ${researchReadinessCard("验证状态", validationRecord ? safeText(validationSummary.outcome_label || validationSummary.decision, "验证") : "待验证", validationRecord ? safeText(validationSummary.reason, "最近验证结果已加载。") : "研究结果还没有进入验证门禁。", validationRecord ? validationTone : "warning")}
      </div>
      <div class="research-decision-score">
        <div class="research-decision-score-head">
          <span class="research-readiness-label">研究推进度</span>
          <strong class="research-decision-score-value">${scorePercent}</strong>
        </div>
        <div class="research-decision-score-track ${toneClass(recommendation.tone)}">
          <div class="research-decision-score-fill" style="width: ${scorePercent}%"></div>
        </div>
        <div class="research-decision-score-legend">
          <span>${escapeHtml(recommendation.note)}</span>
          <span>${escapeHtml(strategyTitle)}</span>
        </div>
      </div>
      <div class="research-decision-tracks">
        ${researchDecisionTrack("Alpha 质量", `${formatMetricNumber(result.sharpe_ratio)} / ${formatPercent(result.total_return)}`, alphaScore, "Sharpe 与总收益率决定这次研究的收益质量。")}
        ${researchDecisionTrack("风险控制", `${formatPercent(result.max_drawdown)} / ${formatMetricNumber(result.profit_factor)}`, riskScore, "回撤与盈利因子反映策略在风险面前的生存质量。")}
        ${researchDecisionTrack("执行可用性", `${safeText(result.num_trades, 0)} 笔 / ${formatPercent(result.win_rate)}`, executionScore, "交易笔数与胜率决定信号是否具备推进到执行层的密度。")}
        ${researchDecisionTrack("推进链路", validationRecord ? safeText(validationSummary.outcome_label || validationSummary.decision, "验证") : "待验证", workflowScore, validationRecord ? safeText(validationSummary.reason, "验证结果已加载。") : "研究结果还没有形成验证或执行的后续链路。", validationRecord ? validationTone : "warning")}
      </div>
    </section>
    <section class="research-flow-panel">
      <div class="research-flow-head">
        <div class="research-flow-copy">
          <div class="label">推进矩阵</div>
          <h3 class="research-decision-title">研究 -> 验证 -> 执行</h3>
          <div class="research-flow-meta">把当前研究结果在业务链路里的位置直接显示出来。</div>
        </div>
      </div>
      <div class="research-flow-list">
        ${researchFlowItems.map((item) => researchFlowItem(item)).join("")}
      </div>
    </section>
  `;
}

function renderResearchDecisionSurface(payload = state.latestResearchResult) {
  const node = document.getElementById("research-decision-board");
  if (!node) {
    return;
  }
  node.innerHTML = payload ? researchDecisionBoard(payload) : "";
  renderResearchOpsSurface(payload);
}

function renderResearchOpsSurface(payload = state.latestResearchResult) {
  const node = document.getElementById("research-ops-board");
  if (!node) {
    return;
  }
  node.innerHTML = payload ? researchOpsBoard(payload) : "";
}

function formatBoolean(value) {
  if (value === true) {
    return "是";
  }
  if (value === false) {
    return "否";
  }
  return "待检测";
}

function validationOutcomeTone(summary = {}) {
  if (summary.outcome_tone) {
    return summary.outcome_tone;
  }
  const decision = String(summary.outcome_label || summary.decision || "").toLowerCase();
  if (decision.includes("mix")) {
    return "warning";
  }
  if ((decision.includes("go") && !decision.includes("no")) || decision.includes("pass")) {
    return "accent";
  }
  if (decision.includes("no") || decision.includes("fail")) {
    return "danger";
  }
  return "muted";
}

function validationDecisionClass(tone = "muted") {
  if (tone === "accent") {
    return "go";
  }
  if (tone === "danger") {
    return "no-go";
  }
  if (tone === "warning") {
    return "warning";
  }
  return "neutral";
}

function formatValidationValue(value, formatHint = "number") {
  if (formatHint === "percent") {
    return formatPercent(value);
  }
  if (formatHint === "integer") {
    return value === null || value === undefined || Number.isNaN(Number(value))
      ? "待检测"
      : String(Math.round(Number(value)));
  }
  if (formatHint === "compact") {
    return formatCompactNumber(value);
  }
  if (formatHint === "string" || typeof value === "string") {
    return localizeUiText(value, safeText(value, "待检测"));
  }
  return formatMetricNumber(value);
}

function validationMetricCard(metric, toneFallback = "muted") {
  const tone = metric?.tone || toneFallback;
  return `
    <div class="metric-card validation-metric-card ${toneClass(tone)}">
      <span class="label">${escapeHtml(localizeInlineText(metric?.label || "Metric", "指标"))}</span>
      <span class="value">${escapeHtml(String(formatValidationValue(metric?.value, metric?.format)))}</span>
    </div>
  `;
}

function validationSummaryTile(label, value, note, tone = "muted") {
  return `
    <article class="validation-summary-tile ${toneClass(tone)}">
      <span class="validation-summary-label">${escapeHtml(localizeInlineText(label, label))}</span>
      <strong class="validation-summary-value">${escapeHtml(typeof value === "string" ? localizeInlineText(value, value) : String(value))}</strong>
      <span class="validation-summary-note">${escapeHtml(localizeInlineText(note, note))}</span>
    </article>
  `;
}

function validationHighlightCard(message, tone = "muted") {
  return `
    <article class="validation-highlight ${toneClass(tone)}">
      <span class="validation-highlight-marker"></span>
      <span>${escapeHtml(localizeInlineText(message, message))}</span>
    </article>
  `;
}

function validationInfoCard(title, rows, note = "", tone = "muted") {
  const rowMarkup = rows.length
    ? rows.map(([label, value, rowTone = null]) => statusRow(label, value, rowTone)).join("")
    : statusRow("状态", "待检测");
  return `
    <article class="validation-info-card ${toneClass(tone)}">
      <div class="validation-info-head">
        <h3>${escapeHtml(localizeInlineText(title, title))}</h3>
      </div>
      <div class="status-list compact-status-list">${rowMarkup}</div>
      ${note ? `<div class="validation-card-note">${escapeHtml(localizeInlineText(note, note))}</div>` : ""}
    </article>
  `;
}

function validationTable(headers, rows, emptyMessage = "暂无可展示数据。") {
  const head = headers.map((header) => `<th>${escapeHtml(localizeInlineText(header, header))}</th>`).join("");
  const body = rows.length
    ? rows
      .map((row) => `<tr>${row.map((cell) => `<td>${escapeHtml(typeof cell === "string" ? localizeInlineText(cell, cell) : String(cell))}</td>`).join("")}</tr>`)
      .join("")
    : tableFallback(headers.length, emptyMessage);
  return `
    <div class="table-scroll">
      <table>
        <thead><tr>${head}</tr></thead>
        <tbody>${body}</tbody>
      </table>
    </div>
  `;
}

function validationBreakdownCard(title, subtitle, body) {
  return `
    <section class="validation-breakdown-card">
      <div class="surface-head">
        <div>
          <h3>${escapeHtml(localizeInlineText(title, title))}</h3>
          ${subtitle ? `<div class="surface-subtitle">${escapeHtml(localizeInlineText(subtitle, subtitle))}</div>` : ""}
        </div>
      </div>
      ${body}
    </section>
  `;
}

function validationMetricRows(signalQuality = {}) {
  return [
    ["精确率", formatValidationValue(signalQuality.precision, "percent")],
    ["召回率", formatValidationValue(signalQuality.recall, "percent")],
    ["样本外 Sharpe", formatValidationValue(signalQuality.oos_sharpe)],
    ["信号数", formatValidationValue(signalQuality.n_signals, "integer")],
  ];
}

function validationNumeric(value) {
  const number = Number(value);
  return Number.isFinite(number) ? number : null;
}

function validationNormalize(value, min, max, invert = false) {
  const number = validationNumeric(value);
  if (number === null) {
    return 0;
  }
  if (max === min) {
    return invert ? 0 : 1;
  }
  const ratio = clamp((number - min) / (max - min), 0, 1);
  return invert ? 1 - ratio : ratio;
}

function validationAverage(values = []) {
  const numbers = values
    .map((value) => validationNumeric(value))
    .filter((value) => value !== null);
  if (!numbers.length) {
    return 0;
  }
  return numbers.reduce((total, value) => total + value, 0) / numbers.length;
}

function validationEvidenceKpi(label, value, note, tone = "muted") {
  return `
    <article class="validation-evidence-kpi ${toneClass(tone)}">
      <span class="validation-evidence-kpi-label">${escapeHtml(localizeInlineText(label, label))}</span>
      <strong class="validation-evidence-kpi-value">${escapeHtml(typeof value === "string" ? localizeInlineText(value, value) : String(value))}</strong>
      <span class="validation-score-note">${escapeHtml(localizeInlineText(note, note))}</span>
    </article>
  `;
}

function validationEvidenceTrackCard(track) {
  const tone = safeText(track?.tone, "muted");
  const scorePercent = clamp(Math.round(Number(track?.score || 0) * 100), 0, 100);
  const valueText = track?.valueText || formatValidationValue(track?.value, track?.format || "number");
  return `
    <article class="validation-evidence-track ${toneClass(tone)}">
      <div class="validation-track-head">
        <span class="validation-track-label">${escapeHtml(localizeInlineText(track?.label || "证据轨", "证据轨"))}</span>
        <strong class="validation-track-value">${escapeHtml(typeof valueText === "string" ? localizeInlineText(valueText, valueText) : String(valueText))}</strong>
      </div>
      <div class="validation-track-rail ${toneClass(tone)}">
        <div class="validation-track-fill" style="width: ${scorePercent}%"></div>
      </div>
      <div class="validation-track-note">${escapeHtml(localizeInlineText(track?.note || "", track?.note || ""))}</div>
    </article>
  `;
}

function validationMethodDefinitions() {
  return [
    {
      id: "gate",
      label: "Validation Gate",
      note: "聚合门禁检查后给出最终放行结论。",
      focus: "门禁结论",
    },
    {
      id: "cpcv",
      label: "CPCV",
      note: "观察多路径样本外质量与信号稳定性。",
      focus: "样本外质量",
    },
    {
      id: "dsr",
      label: "Deflated Sharpe Ratio",
      note: "修正多重试验后的 Sharpe 可信度。",
      focus: "Sharpe 可信度",
    },
    {
      id: "pbo",
      label: "PBO",
      note: "识别参数搜索是否滑入过拟合区间。",
      focus: "过拟合概率",
    },
    {
      id: "wfo",
      label: "WFO",
      note: "比较 rolling / anchored 的适应能力。",
      focus: "窗口适应性",
    },
  ];
}

function validationMethodItem(definition, activeMethod, evidence) {
  const active = definition.id === activeMethod;
  const tone = active ? safeText(evidence?.tone, "muted") : "muted";
  const pillLabel = active ? safeText(evidence?.decision, "当前") : "旁证";
  const valueLabel = active ? safeText(evidence?.primaryMetricLabel, "主指标") : safeText(definition.focus, "方法焦点");
  const valueText = active ? safeText(evidence?.primaryMetricValueText, "待检测") : safeText(definition.note, "待运行");
  const note = active
    ? `当前展示 ${safeText(evidence?.methodLabel, definition.label)} 的放行证据。`
    : safeText(definition.note, "等待该方法结果。");
  return `
    <article class="validation-method-item ${active ? "active" : ""}">
      <div class="validation-method-item-head">
        <span class="validation-method-item-name">${escapeHtml(localizeInlineText(definition.label, definition.label))}</span>
        <span class="${active ? pillToneClass(tone) : "pill muted"}">${escapeHtml(localizeInlineText(pillLabel, pillLabel))}</span>
      </div>
      <div class="validation-method-note">${escapeHtml(localizeInlineText(note, note))}</div>
      <div class="validation-method-item-meta">
        <span class="validation-method-item-label">${escapeHtml(localizeInlineText(valueLabel, valueLabel))}</span>
        <strong class="validation-method-item-value">${escapeHtml(localizeInlineText(valueText, valueText))}</strong>
      </div>
    </article>
  `;
}

function validationEvidenceVerdict(tone = "muted") {
  if (tone === "accent") {
    return "可进入执行准备";
  }
  if (tone === "danger") {
    return "存在放行阻塞";
  }
  if (tone === "warning") {
    return "需要人工复核";
  }
  return "等待更多证据";
}

function validationToneFromScore(score) {
  if (score >= 0.66) {
    return "accent";
  }
  if (score >= 0.4) {
    return "warning";
  }
  return "danger";
}

function validationTrack(label, value, format, score, note, tone = null) {
  const safeScore = clamp(Number(score) || 0, 0, 1);
  return {
    label,
    value,
    format,
    score: safeScore,
    tone: tone || validationToneFromScore(safeScore),
    note,
    valueText: formatValidationValue(value, format),
  };
}

function validationScoreFromTracks(tracks = []) {
  return clamp(validationAverage(tracks.map((track) => track.score)), 0, 1);
}

function validationEvidenceConfig(payload, summary, tone, tracks, score = null) {
  return {
    method: payload.method || summary.method || "gate",
    methodLabel: safeText(summary.method_label, payload.method || "Validation"),
    tone,
    decision: safeText(summary.outcome_label || summary.decision, "N/A"),
    reason: safeText(summary.reason, "暂无结论说明。"),
    rawDataSource: payload.data_source,
    dataSource: formatDataSource(payload.data_source),
    primaryMetricLabel: safeText(summary.primary_metric_label, "Primary Metric"),
    primaryMetricValueText: formatValidationValue(summary.primary_metric_value, summary.primary_metric_format || "number"),
    entries: safeText(summary.entries, 0),
    exits: safeText(summary.exits, 0),
    bars: safeText(summary.bars, 0),
    tracks,
    score: score === null ? validationScoreFromTracks(tracks) : clamp(Number(score) || 0, 0, 1),
  };
}

function validationEvidenceBoard(config) {
  const tone = safeText(config?.tone, "muted");
  const scorePercent = clamp(Math.round(Number(config?.score || 0) * 100), 0, 100);
  const scoreLabel = validationEvidenceVerdict(tone);
  const tracks = Array.isArray(config?.tracks) ? config.tracks : [];
  const methodItems = validationMethodDefinitions()
    .map((definition) => validationMethodItem(definition, config?.method, config))
    .join("");
  return `
    <section class="validation-evidence-panel">
      <div class="validation-evidence-head">
        <div class="validation-evidence-copy">
          <div class="label">放行证据板</div>
          <h3 class="validation-evidence-title">${escapeHtml(localizeInlineText(config?.methodLabel || "Validation", config?.methodLabel || "Validation"))}</h3>
          <div class="validation-evidence-subtitle">${escapeHtml(localizeInlineText(config?.reason || "暂无结论说明。", config?.reason || "暂无结论说明。"))}</div>
        </div>
        <span class="${pillToneClass(tone)}">${escapeHtml(localizeInlineText(config?.decision || "N/A", config?.decision || "N/A"))}</span>
      </div>
      <div class="validation-evidence-kpis">
        ${validationEvidenceKpi("数据源", safeText(config?.dataSource, "N/A"), "当前验证使用的数据来源。", dataSourceTone(config?.rawDataSource))}
        ${validationEvidenceKpi(safeText(config?.primaryMetricLabel, "主指标"), safeText(config?.primaryMetricValueText, "待检测"), "当前方法的关键判定指标。", tone)}
        ${validationEvidenceKpi("信号覆盖", `${safeText(config?.entries, 0)} / ${safeText(config?.exits, 0)}`, `Bars ${safeText(config?.bars, 0)}`, "muted")}
      </div>
      <div class="validation-evidence-score">
        <div class="validation-score-head">
          <span class="validation-evidence-kpi-label">发布准备度</span>
          <strong class="validation-score-value">${scorePercent}</strong>
        </div>
        <div class="validation-score-track ${toneClass(tone)}">
          <div class="validation-score-fill" style="width: ${scorePercent}%"></div>
        </div>
        <div class="validation-score-legend">
          <span>${escapeHtml(localizeInlineText(scoreLabel, scoreLabel))}</span>
          <span>${escapeHtml(localizeInlineText(config?.methodLabel || "Validation", config?.methodLabel || "Validation"))}</span>
        </div>
      </div>
      <div class="validation-evidence-tracks">
        ${tracks.map((track) => validationEvidenceTrackCard(track)).join("")}
      </div>
    </section>
    <section class="validation-method-panel">
      <div class="validation-method-head">
        <div class="validation-method-copy">
          <div class="label">方法视角</div>
          <h3 class="validation-evidence-title">验证方法矩阵</h3>
          <div class="validation-method-meta">当前页面聚焦单次验证结果，其余方法作为旁证入口与后续验证方向。</div>
        </div>
      </div>
      <div class="validation-method-list">${methodItems}</div>
    </section>
  `;
}

function validationWorkbenchModel(payload) {
  const summary = payload.summary || {};
  const tone = validationOutcomeTone(summary);
  const method = payload.method || summary.method || "gate";
  const primaryMetric = {
    label: summary.primary_metric_label || "Primary Metric",
    value: summary.primary_metric_value,
    format: summary.primary_metric_format || "number",
    tone,
  };
  const metrics = [primaryMetric, ...(summary.secondary_metrics || [])]
    .slice(0, 4)
    .map((metric) => validationMetricCard(metric, tone))
    .join("");
  const summaryTiles = [
    validationSummaryTile("Method", safeText(summary.method_label, method), formatDataSource(payload.data_source), tone),
    validationSummaryTile(
      safeText(summary.primary_metric_label, "Primary Metric"),
      formatValidationValue(summary.primary_metric_value, summary.primary_metric_format || "number"),
      "Validation primary signal",
      tone,
    ),
    validationSummaryTile(
      "Signals",
      `${safeText(summary.entries, 0)} / ${safeText(summary.exits, 0)}`,
      `Bar 数 ${safeText(summary.bars, 0)}`,
      "muted",
    ),
  ].join("");
  const highlights = (summary.highlights || [])
    .filter(Boolean)
    .map((message, index) => validationHighlightCard(message, index === 0 ? tone : "muted"))
    .join("");

  if (method === "gate") {
    const cpcv = payload.result?.checks?.cpcv || {};
    const signalQuality = cpcv.signal_quality || {};
    const checkEntries = Object.entries(payload.result?.checks || {});
    const failedChecks = checkEntries.filter(([, check]) => check?.passed === false);
    const passedChecks = checkEntries.filter(([, check]) => check?.passed === true);
    const gateCoverage = checkEntries.length ? passedChecks.length / checkEntries.length : 0;
    const gateDecisionScore = tone === "accent" ? 1 : tone === "warning" ? 0.45 : 0.08;
    const evidenceTracks = [
      validationTrack(
        "门禁校验",
        safeText(summary.outcome_label, "N/A"),
        "string",
        gateDecisionScore,
        "最终放行结论由门禁检查直接驱动。",
        tone,
      ),
      validationTrack(
        "OOS Efficiency",
        cpcv.oos_efficiency,
        "percent",
        validationNormalize(cpcv.oos_efficiency, 0, 1),
        "样本外效率越高，验证越接近可放行状态。",
      ),
      validationTrack(
        "PBO",
        cpcv.pbo,
        "number",
        validationNormalize(cpcv.pbo, 0, 0.35, true),
        "PBO 越低，说明门禁证据越不容易落入过拟合。",
      ),
      validationTrack(
        "检查覆盖",
        gateCoverage,
        "percent",
        gateCoverage,
        failedChecks.length
          ? `仍有 ${failedChecks.length} 个检查项阻塞放行。`
          : "所有门禁检查项都已通过。",
        failedChecks.length ? "danger" : passedChecks.length ? "accent" : "muted",
      ),
    ];
    const evidenceConfig = validationEvidenceConfig(
      payload,
      summary,
      tone,
      evidenceTracks,
      validationAverage([gateDecisionScore, gateCoverage, evidenceTracks[1].score, evidenceTracks[2].score]),
    );
    const detailCards = [
      validationInfoCard(
        "Gate Outcome",
        [
          ["Decision", safeText(summary.outcome_label, "N/A"), tone],
          ["Paths", formatValidationValue(cpcv.n_paths, "integer")],
          ["Optimized", formatBoolean(cpcv.optimized)],
        ],
        safeText(summary.reason, ""),
        tone,
      ),
      validationInfoCard(
        "CPCV Quality",
        [
          ["PBO", formatValidationValue(cpcv.pbo)],
          ["OOS Sharpe Mean", formatValidationValue(cpcv.oos_sharpe_mean)],
          ["OOS Efficiency", formatValidationValue(cpcv.oos_efficiency, "percent")],
        ],
        "Gate currently resolves on CPCV evidence.",
        cpcv.passed ? "accent" : "danger",
      ),
      validationInfoCard(
        "Signal Quality",
        validationMetricRows(signalQuality),
        "Out-of-sample signal quality aggregated across CPCV paths.",
        "muted",
      ),
    ].join("");
    const checkRows = Object.entries(payload.result?.checks || {})
      .map(([name, check]) => [
        name,
        check?.passed === true ? "PASS" : check?.passed === false ? "FAIL" : "N/A",
        check?.signal_quality
          ? `precision ${formatValidationValue(check.signal_quality.precision, "percent")}, oos sharpe ${formatValidationValue(check.signal_quality.oos_sharpe)}`
          : "暂无信号质量",
      ]);
    return {
      tone,
      metrics,
      summaryTiles,
      evidenceBoardHtml: validationEvidenceBoard(evidenceConfig),
      highlights,
      detailCards,
      breakdownTitle: "Gate Breakdown",
      breakdownSubtitle: "Release gate evidence and check-level quality diagnostics.",
      breakdownPill: safeText(summary.outcome_label, "Gate"),
      breakdownTone: tone,
      breakdownHtml: validationBreakdownCard(
        "Check Matrix",
        "Every gate check that contributed to the final GO / NO-GO decision.",
        validationTable(["Check", "Status", "Signal Quality"], checkRows, "No checks returned."),
      ),
    };
  }

  if (method === "dsr") {
    const result = payload.result || {};
    const backtest = payload.backtest || {};
    const evidenceTracks = [
      validationTrack(
        "DSR",
        result.dsr,
        "number",
        validationNormalize(result.dsr, 0, 1),
        "DSR 越高，越能证明 Sharpe 在多重试验后仍然可信。",
        tone,
      ),
      validationTrack(
        "Profit Factor",
        backtest.profit_factor,
        "number",
        validationNormalize(backtest.profit_factor, 0.7, 2.2),
        "盈利因子代表策略在交易执行层面的收益质量。",
      ),
      validationTrack(
        "Max Drawdown",
        backtest.max_drawdown,
        "percent",
        validationNormalize(Math.abs(validationNumeric(backtest.max_drawdown) || 0), 0, 0.35, true),
        "回撤越受控，DSR 结论越接近实际可执行。",
      ),
    ];
    const evidenceConfig = validationEvidenceConfig(payload, summary, tone, evidenceTracks);
    const detailCards = [
      validationInfoCard(
        "DSR Threshold",
        [
          ["DSR", formatValidationValue(result.dsr)],
          ["Observed Sharpe", formatValidationValue(result.observed_sharpe)],
          ["Expected Max Sharpe", formatValidationValue(result.expected_max_sharpe)],
        ],
        "Observed Sharpe is deflated against the multiple-testing burden.",
        tone,
      ),
      validationInfoCard(
        "Backtest Snapshot",
        [
          ["Total Return", formatValidationValue(backtest.total_return, "percent")],
          ["Max Drawdown", formatValidationValue(backtest.max_drawdown, "percent")],
          ["Trades", formatValidationValue(backtest.num_trades, "integer")],
        ],
        "Backing backtest used to contextualize the DSR verdict.",
        "muted",
      ),
      validationInfoCard(
        "Execution Quality",
        [
          ["Win Rate", formatValidationValue(backtest.win_rate, "percent")],
          ["Profit Factor", formatValidationValue(backtest.profit_factor)],
          ["Final Capital", formatValidationValue(backtest.final_capital, "compact")],
        ],
        "Backtest efficiency and capital preservation snapshot.",
        "muted",
      ),
    ].join("");
    const rows = [
      ["Total Return", formatValidationValue(backtest.total_return, "percent")],
      ["Annual Return", formatValidationValue(backtest.annual_return, "percent")],
      ["Sharpe", formatValidationValue(backtest.sharpe_ratio)],
      ["Sortino", formatValidationValue(backtest.sortino_ratio)],
      ["Calmar", formatValidationValue(backtest.calmar_ratio)],
      ["Max Drawdown", formatValidationValue(backtest.max_drawdown, "percent")],
      ["Win Rate", formatValidationValue(backtest.win_rate, "percent")],
      ["Profit Factor", formatValidationValue(backtest.profit_factor)],
    ];
    return {
      tone,
      metrics,
      summaryTiles,
      evidenceBoardHtml: validationEvidenceBoard(evidenceConfig),
      highlights,
      detailCards,
      breakdownTitle: "Backtest Evidence",
      breakdownSubtitle: "The backtest profile behind the deflated Sharpe verdict.",
      breakdownPill: safeText(summary.outcome_label, "DSR"),
      breakdownTone: tone,
      breakdownHtml: validationBreakdownCard(
        "Backtest KPI Table",
        "Core return and risk statistics feeding the DSR interpretation.",
        validationTable(["Metric", "Value"], rows, "No backtest metrics available."),
      ),
    };
  }

  if (method === "pbo") {
    const result = payload.result || {};
    const pathShare = result.total_paths
      ? Number(result.overfit_paths || 0) / Number(result.total_paths)
      : null;
    const spread = (() => {
      const isReturn = validationNumeric(result.is_return_mean);
      const oosReturn = validationNumeric(result.oos_return_mean);
      return isReturn === null || oosReturn === null ? null : Math.abs(isReturn - oosReturn);
    })();
    const evidenceTracks = [
      validationTrack(
        "PBO",
        result.pbo,
        "number",
        validationNormalize(result.pbo, 0, 0.4, true),
        "PBO 越低，越说明参数搜索没有明显滑入噪声拟合。",
        tone,
      ),
      validationTrack(
        "Overfit Share",
        pathShare,
        "percent",
        validationNormalize(pathShare, 0, 0.5, true),
        "过拟合路径占比越低，放行证据越稳。",
      ),
      validationTrack(
        "IS/OOS Spread",
        spread,
        "percent",
        validationNormalize(spread, 0, 0.25, true),
        "样本内外收益差越窄，泛化越可信。",
      ),
    ];
    const evidenceConfig = validationEvidenceConfig(payload, summary, tone, evidenceTracks);
    const detailCards = [
      validationInfoCard(
        "Overfit Risk",
        [
          ["PBO", formatValidationValue(result.pbo)],
          ["Overfit Share", formatValidationValue(pathShare, "percent")],
          ["Rank Correlation", formatValidationValue(result.rank_correlation)],
        ],
        "Higher PBO means parameter search is more likely to be fitting noise.",
        tone,
      ),
      validationInfoCard(
        "Path Mix",
        [
          ["Overfit Paths", formatValidationValue(result.overfit_paths, "integer")],
          ["Total Paths", formatValidationValue(result.total_paths, "integer")],
          ["Passed", formatBoolean(result.passed)],
        ],
        "How many train/test paths landed in the overfit regime.",
        "muted",
      ),
      validationInfoCard(
        "Return Spread",
        [
          ["IS Return Mean", formatValidationValue(result.is_return_mean, "percent")],
          ["OOS Return Mean", formatValidationValue(result.oos_return_mean, "percent")],
        ],
        "The in-sample vs out-of-sample return spread should stay narrow.",
        "muted",
      ),
    ].join("");
    return {
      tone,
      metrics,
      summaryTiles,
      evidenceBoardHtml: validationEvidenceBoard(evidenceConfig),
      highlights,
      detailCards,
      breakdownTitle: "Overfitting Breakdown",
      breakdownSubtitle: "Path-level overfitting and return spread diagnostics.",
      breakdownPill: safeText(summary.outcome_label, "PBO"),
      breakdownTone: tone,
      breakdownHtml: validationBreakdownCard(
        "PBO Signal",
        "Probability of backtest overfitting with supporting statistics.",
        validationTable(
          ["Metric", "Value"],
          [
            ["PBO", formatValidationValue(result.pbo)],
            ["Overfit Share", formatValidationValue(pathShare, "percent")],
            ["Overfit Paths", formatValidationValue(result.overfit_paths, "integer")],
            ["Total Paths", formatValidationValue(result.total_paths, "integer")],
            ["Rank Correlation", formatValidationValue(result.rank_correlation)],
          ],
          "No overfitting metrics available.",
        ),
      ),
    };
  }

  if (method === "cpcv") {
    const result = payload.result || {};
    const signalQuality = result.signal_quality || {};
    const evidenceTracks = [
      validationTrack(
        "OOS Sharpe Mean",
        result.oos_sharpe_mean,
        "number",
        validationNormalize(result.oos_sharpe_mean, -0.5, 1.5),
        "样本外 Sharpe 均值决定 CPCV 证据是否具备实际收益质量。",
        tone,
      ),
      validationTrack(
        "OOS Efficiency",
        result.oos_efficiency,
        "percent",
        validationNormalize(result.oos_efficiency, 0, 1),
        "效率越高，说明跨路径的样本外表现越稳定。",
      ),
      validationTrack(
        "Precision",
        signalQuality.precision,
        "percent",
        validationNormalize(signalQuality.precision, 0, 1),
        "信号精确率用于判断路径结果是否来自可交易信号而非噪声。",
      ),
    ];
    const evidenceConfig = validationEvidenceConfig(payload, summary, tone, evidenceTracks);
    const detailCards = [
      validationInfoCard(
        "Cross-Validation Quality",
        [
          ["OOS Sharpe Mean", formatValidationValue(result.oos_sharpe_mean)],
          ["OOS Efficiency", formatValidationValue(result.oos_efficiency, "percent")],
          ["PBO", formatValidationValue(result.pbo)],
        ],
        "Cross-path out-of-sample quality summary.",
        tone,
      ),
      validationInfoCard(
        "Signal Quality",
        validationMetricRows(signalQuality),
        "Signal precision / recall aggregated across all CPCV paths.",
        "muted",
      ),
      validationInfoCard(
        "Path Coverage",
        [
          ["Paths", formatValidationValue(result.n_paths, "integer")],
          ["Optimized", formatBoolean(result.optimized)],
          ["Recomputed", formatBoolean(result.oos_recomputed)],
        ],
        "How the CPCV run was evaluated and recomputed.",
        "muted",
      ),
    ].join("");
    const rows = (result.path_results || []).map((path) => [
      `Path ${safeText(path.path, "?")}`,
      formatValidationValue(path.oos_sharpe),
      formatValidationValue(path.oos_return, "percent"),
      formatValidationValue(path.oos_trades, "integer"),
      formatValidationValue(path.signal_quality?.precision, "percent"),
    ]);
    return {
      tone,
      metrics,
      summaryTiles,
      evidenceBoardHtml: validationEvidenceBoard(evidenceConfig),
      highlights,
      detailCards,
      breakdownTitle: "Path Breakdown",
      breakdownSubtitle: "Per-path out-of-sample quality across the CPCV run.",
      breakdownPill: `${safeText(result.n_paths, 0)} paths`,
      breakdownTone: tone,
      breakdownHtml: validationBreakdownCard(
        "CPCV Paths",
        "Out-of-sample performance path by path.",
        validationTable(["Path", "OOS Sharpe", "OOS Return", "Trades", "Precision"], rows, "No path results returned."),
      ),
    };
  }

  const rolling = payload.result?.rolling || {};
  const anchored = payload.result?.anchored || {};
  const rollingQuality = validationAverage([
    validationNormalize(rolling.oos_sharpe_mean, -0.5, 1.5),
    validationNormalize(rolling.oos_efficiency, 0, 1),
  ]);
  const anchoredQuality = validationAverage([
    validationNormalize(anchored.oos_sharpe_mean, -0.5, 1.5),
    validationNormalize(anchored.oos_efficiency, 0, 1),
  ]);
  const alignmentScore = rolling.passed && anchored.passed
    ? 1
    : rolling.passed || anchored.passed
      ? 0.45
      : 0.12;
  const evidenceTracks = [
    validationTrack(
      "Rolling",
      rolling.oos_sharpe_mean,
      "number",
      rollingQuality,
      "最近窗口更能代表策略对当前市场状态的适应能力。",
      rolling.passed ? "accent" : "danger",
    ),
    validationTrack(
      "Anchored",
      anchored.oos_sharpe_mean,
      "number",
      anchoredQuality,
      "Anchored 窗口反映长期样本累积后的稳健程度。",
      anchored.passed ? "accent" : "danger",
    ),
    validationTrack(
      "Window Alignment",
      rolling.passed && anchored.passed ? "PASS" : rolling.passed || anchored.passed ? "MIXED" : "FAIL",
      "string",
      alignmentScore,
      "Rolling 与 anchored 是否一致，是判断策略是否真的可迁移的关键。",
      alignmentScore >= 0.66 ? "accent" : alignmentScore >= 0.4 ? "warning" : "danger",
    ),
  ];
  const evidenceConfig = validationEvidenceConfig(
    payload,
    summary,
    tone === "muted" ? "warning" : tone,
    evidenceTracks,
  );
  const detailCards = [
    validationInfoCard(
      "Rolling Windows",
      [
        ["Decision", safeText(rolling.decision, "N/A"), rolling.passed ? "accent" : "danger"],
        ["OOS Sharpe", formatValidationValue(rolling.oos_sharpe_mean)],
        ["OOS Efficiency", formatValidationValue(rolling.oos_efficiency, "percent")],
      ],
      "Rolling windows test whether the strategy keeps adapting to regime changes.",
      rolling.passed ? "accent" : "danger",
    ),
    validationInfoCard(
      "Anchored Windows",
      [
        ["Decision", safeText(anchored.decision, "N/A"), anchored.passed ? "accent" : "danger"],
        ["OOS Sharpe", formatValidationValue(anchored.oos_sharpe_mean)],
        ["OOS Efficiency", formatValidationValue(anchored.oos_efficiency, "percent")],
      ],
      "Anchored windows keep building on the full in-sample history.",
      anchored.passed ? "accent" : "danger",
    ),
    validationInfoCard(
      "Window Split",
      [
        ["Rolling Windows", formatValidationValue(rolling.n_windows, "integer")],
        ["Anchored Windows", formatValidationValue(anchored.n_windows, "integer")],
        ["Verdict", safeText(summary.outcome_label, "N/A"), tone],
      ],
      "Use both modes together to spot brittle adaptation vs memory effects.",
      tone,
    ),
  ].join("");
  const rollingRows = (rolling.window_results || []).map((windowResult) => [
    `Window ${safeText(windowResult.window, "?")}`,
    formatValidationValue(windowResult.is_sharpe),
    formatValidationValue(windowResult.oos_sharpe),
    formatValidationValue(windowResult.oos_return, "percent"),
    formatValidationValue(windowResult.signal_quality?.precision, "percent"),
  ]);
  const anchoredRows = (anchored.window_results || []).map((windowResult) => [
    `Window ${safeText(windowResult.window, "?")}`,
    formatValidationValue(windowResult.is_sharpe),
    formatValidationValue(windowResult.oos_sharpe),
    formatValidationValue(windowResult.oos_return, "percent"),
    formatValidationValue(windowResult.signal_quality?.precision, "percent"),
  ]);
  return {
    tone,
    metrics,
    summaryTiles,
    evidenceBoardHtml: validationEvidenceBoard(evidenceConfig),
    highlights,
    detailCards,
    breakdownTitle: "Window Breakdown",
    breakdownSubtitle: "Rolling vs anchored window-by-window evidence.",
    breakdownPill: safeText(summary.outcome_label, "WFO"),
    breakdownTone: tone === "muted" ? "warning" : tone,
    breakdownHtml: `
      <div class="validation-breakdown-grid">
        ${validationBreakdownCard(
          "Rolling Windows",
          "Train on the immediately preceding regime slice.",
          validationTable(["Window", "IS Sharpe", "OOS Sharpe", "OOS Return", "Precision"], rollingRows, "No rolling window results."),
        )}
        ${validationBreakdownCard(
          "Anchored Windows",
          "Train on the full anchored history up to each OOS window.",
          validationTable(["Window", "IS Sharpe", "OOS Sharpe", "OOS Return", "Precision"], anchoredRows, "No anchored window results."),
        )}
      </div>
    `,
  };
}

function renderSessionEvents(items) {
  state.sessionEvents = Array.isArray(items) ? items : [];
  const countNode = document.getElementById("session-events-count");
  const listNode = document.getElementById("session-events");
  const filteredItems = filteredSessionEvents(state.sessionEvents);

  syncSessionEventFilterControls();
  countNode.textContent = state.sessionEventFilter === "all"
    ? String(state.sessionEvents.length)
    : `${filteredItems.length} / ${state.sessionEvents.length}`;

  if (!filteredItems.length) {
    listNode.innerHTML = `<div class="history-empty">${state.sessionEventFilter === "all" ? "暂无事件记录。" : "当前筛选条件下暂无事件。"}</div>`;
    return;
  }

  listNode.innerHTML = filteredItems.map((item) => `
    <article class="timeline-item session-event-item session-selectable ${state.sessionAudit?.kind === "event" && state.sessionAudit.key === sessionAuditItemKey("event", item, state.sessionEvents.indexOf(item)) ? "is-selected" : ""} ${toneClass(sessionEventTone(item))}" tabindex="0" data-session-audit-kind="event" data-session-audit-key="${escapeHtml(sessionAuditItemKey("event", item, state.sessionEvents.indexOf(item)))}">
      <div class="timeline-dot ${safeText(item.level, "info")}"></div>
      <div class="timeline-body">
        <div class="history-top">
          <strong>${escapeHtml(localizeUiText(safeText(item.title, "Event"), "事件"))}</strong>
          <span class="timeline-time">${formatTimestamp(item.created_at)}</span>
        </div>
        <div class="history-note">${escapeHtml(localizeEventMessage(item.message, "暂无详情"))}</div>
        <div class="execution-event-meta">
          <span class="cell-badge ${toneClass(sessionEventTone(item))}">${escapeHtml(sessionEventTypeLabel(item.event_type))}</span>
          <span class="cell-badge ${toneClass(safeText(item.level, "muted"))}">${escapeHtml(localizeUiText(safeText(item.level, "info"), "信息"))}</span>
          ${item.session_id ? `<span class="cell-badge tone-muted">${escapeHtml(safeText(item.session_id, "session"))}</span>` : ""}
        </div>
        ${sessionEventContextMarkup(item)}
      </div>
    </article>
  `).join("");
}

function renderSessionHistory(items) {
  state.sessionHistory = items;
  renderHistoryList("session-history", "session-history-count", items, (item, index) => `
    <article class="history-card session-selectable ${isActiveSessionHistoryRecord(item) ? "is-active" : ""} ${state.sessionAudit?.kind === "history" && state.sessionAudit.key === sessionAuditItemKey("history", item, index) ? "is-selected" : ""}" tabindex="0" data-history-record-id="${item.record_id || item.session_id || ""}" data-session-audit-kind="history" data-session-audit-key="${escapeHtml(sessionAuditItemKey("history", item, index))}">
      <div class="history-top">
        <strong>${safeText(item.session_id, "session")}</strong>
        <span class="pill ${item.running ? "accent" : "muted"}">${item.running ? "运行中" : "已停止"}</span>
      </div>
      <div class="history-meta">${formatTradingMode(item.request?.mode || "paper")} | ${safeText(item.request?.symbol, "N/A")} | ${formatTimestamp(item.started_at)}</div>
      <div class="history-grid">
        <span>权益 ${formatMetricNumber(item.portfolio?.equity ?? item.portfolio?.total_value ?? 0, 2)}</span>
        <span>持仓 ${safeText(item.health?.open_positions, 0)}</span>
        <span>挂单 ${safeText(item.health?.pending_orders, 0)}</span>
        <span>熔断 ${item.kill_switch?.active ? "开启" : "关闭"}</span>
      </div>
      ${item.request ? `
        <div class="history-actions">
          <button class="button ghost small" data-session-history-action="open-history" data-record-id="${item.record_id || item.session_id || ""}">${isActiveSessionHistoryRecord(item) ? "回看中" : "回看会话"}</button>
          <button class="button ghost small" data-session-history-action="restore-session" data-record-id="${item.record_id || item.session_id || ""}">恢复会话草稿</button>
          <button class="button primary small" data-session-history-action="stage-execution" data-record-id="${item.record_id || item.session_id || ""}">送入执行草稿</button>
        </div>
      ` : ""}
    </article>
  `);
}

function pillToneClass(tone = "muted") {
  if (tone === "accent") {
    return "pill accent";
  }
  if (tone === "warning") {
    return "pill warning";
  }
  if (tone === "danger") {
    return "pill danger";
  }
  return "pill muted";
}

function toneClass(tone = "muted") {
  if (tone === "accent") {
    return "tone-accent";
  }
  if (tone === "warning") {
    return "tone-warning";
  }
  if (tone === "danger") {
    return "tone-danger";
  }
  return "tone-muted";
}

function formatSignedMetricNumber(value, digits = 2) {
  if (value === null || value === undefined || Number.isNaN(Number(value))) {
    return "N/A";
  }
  const number = Number(value);
  const prefix = number > 0 ? "+" : "";
  return `${prefix}${number.toFixed(digits)}`;
}

function statusRow(label, value, tone = null) {
  const renderedValue = typeof value === "string" ? localizeInlineText(value, value) : String(value);
  return `
    <div class="status-row ${tone ? toneClass(tone) : ""}">
      <span>${escapeHtml(localizeInlineText(label, label))}</span>
      <strong>${escapeHtml(renderedValue)}</strong>
    </div>
  `;
}

function statusActionRow(label, value, buttonLabel, dataset = {}, tone = null) {
  const renderedValue = typeof value === "string" ? localizeInlineText(value, value) : String(value);
  const attrs = Object.entries(dataset)
    .filter(([, entryValue]) => entryValue !== null && entryValue !== undefined && entryValue !== false)
    .map(([key, entryValue]) => `data-${key}="${escapeHtml(String(entryValue))}"`)
    .join(" ");

  return `
    <div class="status-row ${tone ? toneClass(tone) : ""}">
      <span>${escapeHtml(localizeInlineText(label, label))}</span>
      <div class="status-row-trailing">
        <strong>${escapeHtml(renderedValue)}</strong>
        <button type="button" class="button ghost small status-row-action" ${attrs}>${escapeHtml(localizeInlineText(buttonLabel, buttonLabel))}</button>
      </div>
    </div>
  `;
}

function activityCard(label, value, tone = "muted") {
  const renderedValue = typeof value === "string" ? localizeInlineText(value, value) : String(value);
  return `
    <article class="activity-card ${toneClass(tone)}">
      <span class="activity-label">${escapeHtml(localizeInlineText(label, label))}</span>
      <strong class="activity-value">${escapeHtml(renderedValue)}</strong>
    </article>
  `;
}

function monitoringAlertActions(alert = {}) {
  const source = String(alert.source || "").toLowerCase();
  if (source === "validation") {
    return `
      <div class="history-actions">
        <button class="button ghost small" data-alert-action="open-validation">打开验证</button>
        <button class="button primary small" data-alert-action="validation-stage-execution">送入执行草稿</button>
      </div>
    `;
  }
  if (source === "session") {
    return `
      <div class="history-actions">
        <button class="button ghost small" data-alert-action="open-session">打开会话</button>
        <button class="button primary small" data-alert-action="session-stage-execution">送入执行草稿</button>
      </div>
    `;
  }
  if (source === "data") {
    return `
      <div class="history-actions">
        <button class="button ghost small" data-alert-action="open-data">打开数据中心</button>
        <button class="button ghost small" data-alert-action="tag-market">标记 Market</button>
        <button class="button ghost small" data-alert-action="tag-demo">标记 Demo</button>
        <button class="button primary small" data-alert-action="focus-research">打开研究</button>
      </div>
    `;
  }
  if (source === "platform") {
    return `
      <div class="history-actions">
        <button class="button ghost small" data-alert-action="open-monitoring">定位监控</button>
      </div>
    `;
  }
  return "";
}

function tableFallback(colspan, message) {
  return `<tr><td colspan="${colspan}" class="table-empty">${escapeHtml(message)}</td></tr>`;
}

function orderStatusTone(status) {
  const normalized = String(status || "").toLowerCase();
  if (
    normalized.includes("open")
    || normalized.includes("working")
    || normalized.includes("submitted")
    || normalized.includes("new")
  ) {
    return "accent";
  }
  if (normalized.includes("partial") || normalized.includes("pending")) {
    return "warning";
  }
  if (normalized.includes("cancel") || normalized.includes("reject") || normalized.includes("fail")) {
    return "danger";
  }
  return "muted";
}

function positionTone(position) {
  const quantity = Number(position?.quantity || 0);
  if (quantity > 0) {
    return "accent";
  }
  if (quantity < 0) {
    return "warning";
  }
  return "muted";
}

function formatTelemetryValue(seriesKey, value) {
  if (seriesKey === "drawdown") {
    return formatPercent(value);
  }
  return formatMetricNumber(value, 2);
}

function formatExecutionTelemetryValue(seriesKey, value) {
  if (seriesKey === "drawdown") {
    return formatPercent(value);
  }
  if (seriesKey === "open_positions" || seriesKey === "pending_orders") {
    return safeText(value, 0);
  }
  return formatMetricNumber(value, 2);
}

function sessionTelemetryModel() {
  const telemetry = state.session?.telemetry || {};
  const labels = Array.isArray(telemetry.labels) ? telemetry.labels : [];
  const openPositions = Array.isArray(telemetry.open_positions) ? telemetry.open_positions : [];
  const pendingOrders = Array.isArray(telemetry.pending_orders) ? telemetry.pending_orders : [];
  if (state.sessionChart.mode === "drawdown") {
    return {
      labels,
      openPositions,
      pendingOrders,
      series: [
      {
        key: "drawdown",
        label: "回撤",
        color: "#fb7185",
        values: Array.isArray(telemetry.drawdown) ? telemetry.drawdown : [],
      },
      ],
    };
  }

  return {
    labels,
    openPositions,
    pendingOrders,
    series: [
      {
        key: "equity",
        label: "权益",
        color: "#2dd4bf",
        values: Array.isArray(telemetry.equity) ? telemetry.equity : [],
      },
      {
        key: "cash",
        label: "现金",
        color: "#38bdf8",
        values: Array.isArray(telemetry.cash) ? telemetry.cash : [],
      },
      {
        key: "market_value",
        label: "持仓市值",
        color: "#f59e0b",
        values: Array.isArray(telemetry.market_value) ? telemetry.market_value : [],
      },
    ],
  };
}

function showSessionTelemetryTooltip(index, event) {
  const model = sessionTelemetryModel();
  const label = model.labels[index];
  if (!label) {
    return;
  }

  const lines = [`<div class="tooltip-title">${escapeHtml(formatTimestamp(label))}</div>`];
  model.series.forEach((series) => {
    const value = series.values[index];
    if (value !== null && value !== undefined && !Number.isNaN(Number(value))) {
      lines.push(`<div>${series.label} ${formatTelemetryValue(series.key, value)}</div>`);
    }
  });
  lines.push(`<div>持仓数 ${safeText(model.openPositions[index], 0)}</div>`);
  lines.push(`<div>挂单数 ${safeText(model.pendingOrders[index], 0)}</div>`);

  sessionChartNodes.tooltip.innerHTML = lines.join("");
  sessionChartNodes.tooltip.classList.remove("hidden");

  const stageRect = sessionChartNodes.stage.getBoundingClientRect();
  const tooltipRect = sessionChartNodes.tooltip.getBoundingClientRect();
  const left = clamp(event.clientX - stageRect.left + 16, 12, stageRect.width - tooltipRect.width - 12);
  const top = clamp(event.clientY - stageRect.top + 12, 12, stageRect.height - tooltipRect.height - 12);
  sessionChartNodes.tooltip.style.left = `${left}px`;
  sessionChartNodes.tooltip.style.top = `${top}px`;
}

function hideSessionTelemetryTooltip() {
  sessionChartNodes.tooltip.classList.add("hidden");
}

function renderSessionTelemetryChart() {
  const model = sessionTelemetryModel();
  const points = model.labels.length;
  const { ctx, width, height } = prepareCanvas(sessionChartNodes.canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(9, 14, 24, 0.88)";
  ctx.fillRect(0, 0, width, height);

  const allValues = model.series
    .flatMap((series) => series.values)
    .filter((value) => value !== null && value !== undefined && !Number.isNaN(Number(value)))
    .map((value) => Number(value));

  if (!points || !allValues.length) {
    sessionChartNodes.empty.classList.remove("hidden");
    sessionChartNodes.legend.innerHTML = "";
    document.getElementById("session-chart-subtitle").textContent = "等待实时遥测。";
    return;
  }

  sessionChartNodes.empty.classList.add("hidden");
  drawGrid(ctx, width, height, SESSION_CHART_PADDING);

  let min = Math.min(...allValues);
  let max = Math.max(...allValues);
  if (state.sessionChart.mode === "drawdown") {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  }
  const range = max - min || Math.max(Math.abs(max) * 0.05, 1);
  const plotWidth = width - SESSION_CHART_PADDING.left - SESSION_CHART_PADDING.right;
  const plotHeight = height - SESSION_CHART_PADDING.top - SESSION_CHART_PADDING.bottom;
  const pointX = (index) => (
    SESSION_CHART_PADDING.left
    + (index / Math.max(points - 1, 1)) * plotWidth
  );
  const pointY = (value) => (
    SESSION_CHART_PADDING.top
    + (1 - (Number(value) - min) / range) * plotHeight
  );

  model.series.forEach((series) => {
    let started = false;
    ctx.beginPath();
    series.values.forEach((value, index) => {
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return;
      }
      const x = pointX(index);
      const y = pointY(value);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.strokeStyle = series.color;
    ctx.lineWidth = state.sessionChart.mode === "drawdown" ? 2.4 : 2;
    ctx.stroke();

    if (state.sessionChart.mode === "drawdown") {
      const baselineY = pointY(0);
      ctx.lineTo(pointX(points - 1), baselineY);
      ctx.lineTo(pointX(0), baselineY);
      ctx.closePath();
      ctx.fillStyle = "rgba(251, 113, 133, 0.14)";
      ctx.fill();
    }
  });

  if (state.sessionChart.hoverIndex !== null) {
    const hoverIndex = clamp(state.sessionChart.hoverIndex, 0, points - 1);
    const x = pointX(hoverIndex);
    ctx.strokeStyle = "rgba(56, 189, 248, 0.5)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, SESSION_CHART_PADDING.top);
    ctx.lineTo(x, height - SESSION_CHART_PADDING.bottom);
    ctx.stroke();

    model.series.forEach((series) => {
      const value = series.values[hoverIndex];
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return;
      }
      ctx.fillStyle = series.color;
      ctx.beginPath();
      ctx.arc(x, pointY(value), 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  ctx.fillStyle = "#93a4bd";
  ctx.font = "12px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(
    state.sessionChart.mode === "drawdown" ? "回撤轨迹" : "组合遥测",
    SESSION_CHART_PADDING.left,
    14,
  );
  ctx.textAlign = "right";
  ctx.fillText(`最高 ${formatMetricNumber(max, 2)}`, width - SESSION_CHART_PADDING.right, 14);
  ctx.fillText(`最低 ${formatMetricNumber(min, 2)}`, width - SESSION_CHART_PADDING.right, height - 6);

  const latestLabel = model.labels[points - 1];
  document.getElementById("session-chart-subtitle").textContent = [
    `${points} 个点`,
    formatTimestamp(latestLabel),
    state.sessionChart.mode === "drawdown" ? "风险视角" : "权益、现金、持仓市值",
  ].join(" | ");
  sessionChartNodes.legend.innerHTML = model.series
    .map(
      (series) => `
        <div class="legend-item">
          <span class="legend-swatch" style="background:${series.color}"></span>
          <span>${series.label}</span>
        </div>
      `,
    )
    .join("");
}

function syncSessionChartControls() {
  document.querySelectorAll("#session-telemetry-controls .segment-btn").forEach((button) => {
    setSegmentPressed(button, button.dataset.sessionChart === state.sessionChart.mode);
  });
}

function bindSessionChartControls() {
  document.querySelectorAll("#session-telemetry-controls .segment-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.sessionChart.mode = button.dataset.sessionChart;
      syncSessionChartControls();
      renderSessionTelemetryChart();
    });
  });

  sessionChartNodes.canvas.addEventListener("mousemove", (event) => {
    const model = sessionTelemetryModel();
    if (!model.labels.length) {
      return;
    }
    const rect = sessionChartNodes.canvas.getBoundingClientRect();
    const plotWidth = rect.width - SESSION_CHART_PADDING.left - SESSION_CHART_PADDING.right;
    if (plotWidth <= 0) {
      return;
    }
    const ratio = clamp((event.clientX - rect.left - SESSION_CHART_PADDING.left) / plotWidth, 0, 0.999999);
    const index = clamp(Math.round(ratio * Math.max(model.labels.length - 1, 1)), 0, model.labels.length - 1);
    state.sessionChart.hoverIndex = index;
    renderSessionTelemetryChart();
    showSessionTelemetryTooltip(index, event);
  });

  sessionChartNodes.canvas.addEventListener("mouseleave", () => {
    state.sessionChart.hoverIndex = null;
    renderSessionTelemetryChart();
    hideSessionTelemetryTooltip();
  });
}

function executionTelemetryModel() {
  const telemetry = state.executionHub?.telemetry || {};
  const labels = Array.isArray(telemetry.labels) ? telemetry.labels : [];
  const openPositions = Array.isArray(telemetry.open_positions) ? telemetry.open_positions : [];
  const pendingOrders = Array.isArray(telemetry.pending_orders) ? telemetry.pending_orders : [];
  if (state.executionChart.mode === "drawdown") {
    return {
      labels,
      openPositions,
      pendingOrders,
      series: [
        {
          key: "drawdown",
          label: "回撤",
          color: "#fb7185",
          values: Array.isArray(telemetry.drawdown) ? telemetry.drawdown : [],
        },
      ],
    };
  }
  if (state.executionChart.mode === "activity") {
    return {
      labels,
      openPositions,
      pendingOrders,
      series: [
        {
          key: "open_positions",
          label: "持仓数",
          color: "#2dd4bf",
          values: openPositions,
        },
        {
          key: "pending_orders",
          label: "挂单数",
          color: "#f59e0b",
          values: pendingOrders,
        },
      ],
    };
  }

  return {
    labels,
    openPositions,
    pendingOrders,
    series: [
      {
        key: "equity",
        label: "权益",
        color: "#2dd4bf",
        values: Array.isArray(telemetry.equity) ? telemetry.equity : [],
      },
      {
        key: "cash",
        label: "现金",
        color: "#38bdf8",
        values: Array.isArray(telemetry.cash) ? telemetry.cash : [],
      },
      {
        key: "market_value",
        label: "持仓市值",
        color: "#f59e0b",
        values: Array.isArray(telemetry.market_value) ? telemetry.market_value : [],
      },
    ],
  };
}

function showExecutionTelemetryTooltip(index, event) {
  const model = executionTelemetryModel();
  const label = model.labels[index];
  if (!label) {
    return;
  }

  const lines = [`<div class="tooltip-title">${escapeHtml(formatTimestamp(label))}</div>`];
  model.series.forEach((series) => {
    const value = series.values[index];
    if (value !== null && value !== undefined && !Number.isNaN(Number(value))) {
      lines.push(`<div>${series.label} ${formatExecutionTelemetryValue(series.key, value)}</div>`);
    }
  });
  lines.push(`<div>持仓数 ${safeText(model.openPositions[index], 0)}</div>`);
  lines.push(`<div>挂单数 ${safeText(model.pendingOrders[index], 0)}</div>`);

  executionChartNodes.tooltip.innerHTML = lines.join("");
  executionChartNodes.tooltip.classList.remove("hidden");

  const stageRect = executionChartNodes.stage.getBoundingClientRect();
  const tooltipRect = executionChartNodes.tooltip.getBoundingClientRect();
  const left = clamp(event.clientX - stageRect.left + 16, 12, stageRect.width - tooltipRect.width - 12);
  const top = clamp(event.clientY - stageRect.top + 12, 12, stageRect.height - tooltipRect.height - 12);
  executionChartNodes.tooltip.style.left = `${left}px`;
  executionChartNodes.tooltip.style.top = `${top}px`;
}

function hideExecutionTelemetryTooltip() {
  executionChartNodes.tooltip.classList.add("hidden");
}

function renderExecutionTelemetryChart() {
  syncExecutionTelemetryControls();
  const model = executionTelemetryModel();
  const points = model.labels.length;
  const { ctx, width, height } = prepareCanvas(executionChartNodes.canvas);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(9, 14, 24, 0.88)";
  ctx.fillRect(0, 0, width, height);

  const allValues = model.series
    .flatMap((series) => series.values)
    .filter((value) => value !== null && value !== undefined && !Number.isNaN(Number(value)))
    .map((value) => Number(value));

  if (!points || !allValues.length) {
    executionChartNodes.empty.classList.remove("hidden");
    executionChartNodes.legend.innerHTML = "";
    document.getElementById("execution-chart-subtitle").textContent = "等待执行层遥测。";
    return;
  }

  executionChartNodes.empty.classList.add("hidden");
  drawGrid(ctx, width, height, SESSION_CHART_PADDING);

  let min = Math.min(...allValues);
  let max = Math.max(...allValues);
  if (state.executionChart.mode === "drawdown") {
    min = Math.min(min, 0);
    max = Math.max(max, 0);
  } else if (state.executionChart.mode === "activity") {
    min = Math.min(min, 0);
    max = Math.max(max, 1);
  }
  const range = max - min || Math.max(Math.abs(max) * 0.05, 1);
  const plotWidth = width - SESSION_CHART_PADDING.left - SESSION_CHART_PADDING.right;
  const plotHeight = height - SESSION_CHART_PADDING.top - SESSION_CHART_PADDING.bottom;
  const pointX = (index) => (
    SESSION_CHART_PADDING.left
    + (index / Math.max(points - 1, 1)) * plotWidth
  );
  const pointY = (value) => (
    SESSION_CHART_PADDING.top
    + (1 - (Number(value) - min) / range) * plotHeight
  );

  model.series.forEach((series) => {
    let started = false;
    ctx.beginPath();
    series.values.forEach((value, index) => {
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return;
      }
      const x = pointX(index);
      const y = pointY(value);
      if (!started) {
        ctx.moveTo(x, y);
        started = true;
      } else {
        ctx.lineTo(x, y);
      }
    });
    ctx.strokeStyle = series.color;
    ctx.lineWidth = state.executionChart.mode === "drawdown" ? 2.4 : 2;
    ctx.stroke();

    if (state.executionChart.mode === "drawdown") {
      const baselineY = pointY(0);
      ctx.lineTo(pointX(points - 1), baselineY);
      ctx.lineTo(pointX(0), baselineY);
      ctx.closePath();
      ctx.fillStyle = "rgba(251, 113, 133, 0.14)";
      ctx.fill();
    }
  });

  if (state.executionChart.hoverIndex !== null) {
    const hoverIndex = clamp(state.executionChart.hoverIndex, 0, points - 1);
    const x = pointX(hoverIndex);
    ctx.strokeStyle = "rgba(56, 189, 248, 0.5)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, SESSION_CHART_PADDING.top);
    ctx.lineTo(x, height - SESSION_CHART_PADDING.bottom);
    ctx.stroke();

    model.series.forEach((series) => {
      const value = series.values[hoverIndex];
      if (value === null || value === undefined || Number.isNaN(Number(value))) {
        return;
      }
      ctx.fillStyle = series.color;
      ctx.beginPath();
      ctx.arc(x, pointY(value), 3.5, 0, Math.PI * 2);
      ctx.fill();
    });
  }

  ctx.fillStyle = "#93a4bd";
  ctx.font = "12px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(
    state.executionChart.mode === "drawdown"
      ? "执行回撤轨迹"
      : state.executionChart.mode === "activity"
        ? "执行负载"
        : "执行组合遥测",
    SESSION_CHART_PADDING.left,
    14,
  );
  ctx.textAlign = "right";
  ctx.fillText(`最高 ${formatMetricNumber(max, 2)}`, width - SESSION_CHART_PADDING.right, 14);
  ctx.fillText(`最低 ${formatMetricNumber(min, 2)}`, width - SESSION_CHART_PADDING.right, height - 6);

  const latestLabel = model.labels[points - 1];
  document.getElementById("execution-chart-subtitle").textContent = [
    `${points} 个点`,
    formatTimestamp(latestLabel),
    state.executionChart.mode === "drawdown"
      ? "观察回撤与恢复"
      : state.executionChart.mode === "activity"
        ? "持仓数与挂单数"
        : "权益、现金、持仓市值",
  ].join(" | ");
  executionChartNodes.legend.innerHTML = model.series
    .map(
      (series) => `
        <div class="legend-item">
          <span class="legend-swatch" style="background:${series.color}"></span>
          <span>${series.label}</span>
        </div>
      `,
    )
    .join("");
}

function syncExecutionTelemetryControls() {
  document.querySelectorAll("#execution-telemetry-controls .segment-btn").forEach((button) => {
    setSegmentPressed(button, button.dataset.executionChart === state.executionChart.mode);
  });
}

function bindExecutionTelemetryControls() {
  document.querySelectorAll("#execution-telemetry-controls .segment-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.executionChart.mode = button.dataset.executionChart;
      syncExecutionTelemetryControls();
      renderExecutionTelemetryChart();
    });
  });

  executionChartNodes.canvas.addEventListener("mousemove", (event) => {
    const model = executionTelemetryModel();
    if (!model.labels.length) {
      return;
    }
    const rect = executionChartNodes.canvas.getBoundingClientRect();
    const plotWidth = rect.width - SESSION_CHART_PADDING.left - SESSION_CHART_PADDING.right;
    if (plotWidth <= 0) {
      return;
    }
    const ratio = clamp((event.clientX - rect.left - SESSION_CHART_PADDING.left) / plotWidth, 0, 0.999999);
    const index = clamp(Math.round(ratio * Math.max(model.labels.length - 1, 1)), 0, model.labels.length - 1);
    state.executionChart.hoverIndex = index;
    renderExecutionTelemetryChart();
    showExecutionTelemetryTooltip(index, event);
  });

  executionChartNodes.canvas.addEventListener("mouseleave", () => {
    state.executionChart.hoverIndex = null;
    renderExecutionTelemetryChart();
    hideExecutionTelemetryTooltip();
  });
}

function populateResearchForm(request) {
  if (!request) {
    return;
  }
  const form = document.getElementById("research-form");
  form.elements.strategy.value = safeText(request.strategy, "trend_following");
  form.elements.symbol.value = safeText(request.symbol, "BTC/USDT");
  form.elements.capital.value = safeText(request.capital, 10000);
  form.elements.fee.value = safeText(request.fee, 0.001);
  form.elements.start.value = request.start || "";
  form.elements.end.value = request.end || "";
  renderParamEditor("research", form.elements.strategy.value, request.params || {});
}

function populateValidationForm(request) {
  if (!request) {
    return;
  }
  const form = document.getElementById("validation-form");
  form.elements.strategy.value = safeText(request.strategy, "trend_following");
  form.elements.symbol.value = safeText(request.symbol, "BTC/USDT");
  form.elements.method.value = safeText(request.method, "gate");
  form.elements.optimize_trials.value = safeText(request.optimize_trials, 10);
  form.elements.wfo_windows.value = safeText(request.wfo_windows, 2);
  form.elements.capital.value = safeText(request.capital, 10000);
  renderParamEditor("validation", form.elements.strategy.value, request.params || {});
}

function normalizeTerminalRequest(request = {}, fallback = {}) {
  const requestStrategies = Array.isArray(request.strategies)
    ? request.strategies.filter((value) => value !== null && value !== undefined && value !== "").map(String)
    : [];
  const fallbackStrategies = Array.isArray(fallback.strategies)
    ? fallback.strategies.filter((value) => value !== null && value !== undefined && value !== "").map(String)
    : [];
  const defaultStrategy = state.strategies[0]?.strategy_id;
  const parseNumber = (value, fallbackValue) => {
    const number = Number(value);
    return Number.isFinite(number) ? number : fallbackValue;
  };

  return {
    mode: request.mode ? String(request.mode) : fallback.mode ? String(fallback.mode) : "paper",
    symbol: request.symbol ? String(request.symbol) : fallback.symbol ? String(fallback.symbol) : "BTC/USDT",
    timeframe: request.timeframe ? String(request.timeframe) : fallback.timeframe ? String(fallback.timeframe) : "1h",
    interval_seconds: parseNumber(request.interval_seconds, parseNumber(fallback.interval_seconds, 30)),
    capital: parseNumber(request.capital, parseNumber(fallback.capital, 100000)),
    strategies: requestStrategies.length
      ? requestStrategies
      : fallbackStrategies.length
        ? fallbackStrategies
        : defaultStrategy
          ? [defaultStrategy]
          : [],
  };
}

function terminalRequestsEqual(left = {}, right = {}) {
  return JSON.stringify(normalizeTerminalRequest(left)) === JSON.stringify(normalizeTerminalRequest(right));
}

function terminalConfigText(request = {}) {
  const normalized = normalizeTerminalRequest(request);
  return [
    formatTradingMode(normalized.mode),
    safeText(normalized.symbol, "BTC/USDT"),
    safeText(normalized.timeframe, "1h"),
  ].join(" | ");
}

function terminalStrategyText(strategies = []) {
  return formatStrategyText(strategies);
}

function executionDraftMetaDefaults() {
  return {
    sourceType: "manual",
    sourceLabel: "手动草稿",
    sourcePanel: "execution",
    sourceRecordId: null,
    sourceSessionId: null,
    sourceStrategy: null,
    sourceSymbol: null,
    dataSource: null,
    dataMode: null,
    dataContextTitle: null,
    dataContextMessage: null,
    validationLabel: null,
    validationTone: "muted",
    validationReason: null,
    validationMethod: null,
    sourceTrail: [],
    edited: false,
  };
}

function setExecutionDraftMeta(meta = {}, { preserveEdited = true } = {}) {
  const defaults = executionDraftMetaDefaults();
  const previous = state.executionDraftMeta || defaults;
  const next = {
    ...defaults,
    ...previous,
    ...meta,
    sourceTrail: Array.isArray(meta.sourceTrail)
      ? meta.sourceTrail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
      : Array.isArray(previous.sourceTrail)
        ? previous.sourceTrail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
        : [],
  };
  if (preserveEdited && previous.edited && meta.edited === undefined) {
    next.edited = true;
  }
  state.executionDraftMeta = next;
  persistWorkbenchState();
  renderResearchDecisionSurface();
  return next;
}

function normalizeWorkbenchPanel(panelName) {
  return Object.prototype.hasOwnProperty.call(panels, panelName) ? panelName : "overview";
}

function normalizeStoredSourceContextMap(map = {}) {
  if (!map || typeof map !== "object") {
    return {};
  }
  return Object.fromEntries(
    Object.entries(map)
      .map(([recordId, context]) => [recordId, normalizeSourceContext(context)])
      .filter((entry) => Boolean(entry[0]) && Boolean(entry[1])),
  );
}

function serializedWorkbenchState() {
  const terminalDraft = normalizeTerminalRequest(state.terminalDraft || {});
  const executionDraftMeta = state.executionDraftMeta || executionDraftMetaDefaults();
  return {
    activePanel: normalizeWorkbenchPanel(state.activePanel || "overview"),
    selectedStrategyId: state.selectedStrategyId || null,
    strategyFilters: {
      search: String(state.strategyFilters?.search || ""),
      timeframe: String(state.strategyFilters?.timeframe || "all"),
      symbol: String(state.strategyFilters?.symbol || "all"),
    },
    researchView: {
      historyRecordId: state.researchView?.historyRecordId || null,
    },
    validationView: {
      historyRecordId: state.validationView?.historyRecordId || null,
    },
    sessionView: {
      mode: state.sessionView?.mode === "history" ? "history" : "live",
      historyRecordId: state.sessionView?.historyRecordId || null,
      historySessionId: state.sessionView?.historySessionId || null,
      pinLiveWhenIdle: Boolean(state.sessionView?.pinLiveWhenIdle),
    },
    terminalDraft: {
      ...terminalDraft,
      dirty: Boolean(state.terminalDraft?.dirty),
    },
    executionDraftMeta: {
      ...executionDraftMetaDefaults(),
      ...executionDraftMeta,
      sourceTrail: Array.isArray(executionDraftMeta.sourceTrail)
        ? executionDraftMeta.sourceTrail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
        : [],
      edited: Boolean(executionDraftMeta.edited),
    },
    monitoringInspector: {
      kind: typeof state.monitoringInspector?.kind === "string" ? state.monitoringInspector.kind : null,
      key: typeof state.monitoringInspector?.key === "string" ? state.monitoringInspector.key : null,
    },
    overviewInspector: {
      kind: typeof state.overviewInspector?.kind === "string" ? state.overviewInspector.kind : null,
      key: typeof state.overviewInspector?.key === "string" ? state.overviewInspector.key : null,
    },
    researchContextMap: normalizeStoredSourceContextMap(state.researchContextMap),
    validationContextMap: normalizeStoredSourceContextMap(state.validationContextMap),
  };
}

function scheduleWorkbenchStateSync(serialized) {
  if (typeof window === "undefined" || serialized === lastSyncedWorkbenchState) {
    return;
  }
  if (workbenchPersistHandle) {
    window.clearTimeout(workbenchPersistHandle);
  }
  workbenchPersistHandle = window.setTimeout(() => {
    workbenchPersistHandle = null;
    void syncWorkbenchStateToServer(serialized);
  }, 300);
}

async function syncWorkbenchStateToServer(serialized) {
  try {
    await api(WORKBENCH_STATE_ENDPOINT, { method: "POST", body: serialized });
    lastSyncedWorkbenchState = serialized;
  } catch {}
}

function persistWorkbenchState() {
  if (suspendWorkbenchPersistence) {
    return;
  }
  const serialized = JSON.stringify(serializedWorkbenchState());
  if (serialized === lastPersistedWorkbenchState) {
    if (serialized !== lastSyncedWorkbenchState) {
      scheduleWorkbenchStateSync(serialized);
    }
    return;
  }
  if (typeof window !== "undefined" && window.localStorage) {
    try {
      window.localStorage.setItem(WORKBENCH_STATE_STORAGE_KEY, serialized);
    } catch {}
  }
  lastPersistedWorkbenchState = serialized;
  scheduleWorkbenchStateSync(serialized);
}

function loadLocalWorkbenchState() {
  if (typeof window === "undefined" || !window.localStorage) {
    return null;
  }
  try {
    const raw = window.localStorage.getItem(WORKBENCH_STATE_STORAGE_KEY);
    if (!raw) {
      return null;
    }
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function applyWorkbenchStateSnapshot(parsed) {
  if (!parsed || typeof parsed !== "object") {
    return null;
  }
  try {
    const strategyFilters = parsed.strategyFilters && typeof parsed.strategyFilters === "object"
      ? parsed.strategyFilters
      : {};
    const restoredSessionView = parsed.sessionView?.mode === "history"
      && (parsed.sessionView?.historyRecordId || parsed.sessionView?.historySessionId)
      ? {
          mode: "history",
          historyRecordId: parsed.sessionView.historyRecordId || null,
          historySessionId: parsed.sessionView.historySessionId || null,
          pinLiveWhenIdle: false,
        }
      : {
          mode: "live",
          historyRecordId: null,
          historySessionId: null,
          pinLiveWhenIdle: Boolean(parsed.sessionView?.pinLiveWhenIdle),
        };
    const restoredTerminalDraft = parsed.terminalDraft
      ? {
          ...normalizeTerminalRequest(parsed.terminalDraft, state.terminalDraft),
          dirty: Boolean(parsed.terminalDraft.dirty),
        }
      : null;
    const restoredExecutionDraftMeta = parsed.executionDraftMeta && typeof parsed.executionDraftMeta === "object"
      ? {
          ...executionDraftMetaDefaults(),
          ...parsed.executionDraftMeta,
          sourceTrail: Array.isArray(parsed.executionDraftMeta.sourceTrail)
            ? parsed.executionDraftMeta.sourceTrail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
            : [],
          edited: Boolean(parsed.executionDraftMeta.edited),
        }
      : null;

    state.activePanel = normalizeWorkbenchPanel(String(parsed.activePanel || state.activePanel || "overview"));
    state.selectedStrategyId = typeof parsed.selectedStrategyId === "string" && parsed.selectedStrategyId
      ? parsed.selectedStrategyId
      : null;
    state.strategyFilters = {
      search: typeof strategyFilters.search === "string" ? strategyFilters.search : "",
      timeframe: typeof strategyFilters.timeframe === "string" && strategyFilters.timeframe
        ? strategyFilters.timeframe
        : "all",
      symbol: typeof strategyFilters.symbol === "string" && strategyFilters.symbol
        ? strategyFilters.symbol
        : "all",
    };
    state.researchView = {
      historyRecordId: parsed.researchView?.historyRecordId || null,
    };
    state.validationView = {
      historyRecordId: parsed.validationView?.historyRecordId || null,
    };
    state.sessionView = restoredSessionView;
    state.monitoringInspector = {
      kind: typeof parsed.monitoringInspector?.kind === "string" ? parsed.monitoringInspector.kind : null,
      key: typeof parsed.monitoringInspector?.key === "string" ? parsed.monitoringInspector.key : null,
    };
    state.overviewInspector = {
      kind: typeof parsed.overviewInspector?.kind === "string" ? parsed.overviewInspector.kind : null,
      key: typeof parsed.overviewInspector?.key === "string" ? parsed.overviewInspector.key : null,
    };
    state.researchContextMap = normalizeStoredSourceContextMap(parsed.researchContextMap);
    state.validationContextMap = normalizeStoredSourceContextMap(parsed.validationContextMap);
    if (restoredTerminalDraft) {
      state.terminalDraft = restoredTerminalDraft;
    }
    if (restoredExecutionDraftMeta) {
      state.executionDraftMeta = restoredExecutionDraftMeta;
    }

    restoredWorkbenchState = serializedWorkbenchState();
    lastPersistedWorkbenchState = JSON.stringify(restoredWorkbenchState);
    return restoredWorkbenchState;
  } catch {
    restoredWorkbenchState = null;
    lastPersistedWorkbenchState = "";
    return null;
  }
}

async function restoreWorkbenchState() {
  const localState = loadLocalWorkbenchState();
  let serverState = null;
  try {
    const payload = await api(WORKBENCH_STATE_ENDPOINT);
    if (payload?.state && typeof payload.state === "object") {
      serverState = payload.state;
    }
  } catch {}
  const restored = applyWorkbenchStateSnapshot(serverState || localState);
  if (restored && serverState) {
    const serialized = JSON.stringify(restored);
    lastSyncedWorkbenchState = serialized;
    if (typeof window !== "undefined" && window.localStorage) {
      try {
        window.localStorage.setItem(WORKBENCH_STATE_STORAGE_KEY, serialized);
      } catch {}
    }
  }
  return restored;
}

function executionDraftUsesRuntimeValidation(meta = {}, runtimeControl = {}) {
  const sourceType = String(meta.sourceType || "").trim().toLowerCase();
  if (meta.edited) {
    return false;
  }
  if (sourceType === "runtime" || sourceType === "session") {
    return true;
  }
  if (sourceType === "manual") {
    const runtime = resolveRuntimeControl(runtimeControl);
    return terminalRequestsEqual(state.terminalDraft || {}, runtime);
  }
  return false;
}

function executionDraftValidationContext(meta = {}, runtimeControl = {}) {
  const executionContext = state.executionHub?.execution_context || {};
  const inheritRuntimeValidation = executionDraftUsesRuntimeValidation(meta, runtimeControl);
  const explicitLabel = safeText(meta.validationLabel, "");
  const hasExplicitValidation = Boolean(explicitLabel);

  return {
    label: hasExplicitValidation
      ? meta.validationLabel
      : (inheritRuntimeValidation ? executionContext.validation_label || null : null),
    tone: hasExplicitValidation
      ? (meta.validationTone || "muted")
      : (inheritRuntimeValidation ? executionContext.validation_tone || meta.validationTone || "muted" : meta.validationTone || "muted"),
    reason: meta.validationReason ?? (inheritRuntimeValidation ? executionContext.validation_reason || null : null),
    method: meta.validationMethod ?? (inheritRuntimeValidation ? executionContext.validation_method || null : null),
  };
}

function historyRecordIdOf(payload = {}) {
  return payload?.record_id || payload?.history_record?.record_id || null;
}

function executionSourceAction(meta = {}) {
  const sourcePanel = String(meta.sourcePanel || "execution");
  if (sourcePanel === "research") {
    return {
      panel: "research",
      label: "打开研究",
      panelLabel: "研究工作台",
      formId: "research-form",
    };
  }
  if (sourcePanel === "validation") {
    return {
      panel: "validation",
      label: "打开验证",
      panelLabel: "验证工作台",
      formId: "validation-form",
    };
  }
  if (sourcePanel === "session") {
    return {
      panel: "session",
      label: "打开会话",
      panelLabel: "交易会话",
      formId: "session-form",
    };
  }
  if (sourcePanel === "strategies") {
    return {
      panel: "strategies",
      label: "打开策略目录",
      panelLabel: "策略目录",
      formId: null,
    };
  }
  if (sourcePanel === "data") {
    return {
      panel: "data",
      label: "打开数据中心",
      panelLabel: "数据中心",
      formId: null,
    };
  }
  return {
    panel: "execution",
    label: "继续查看执行",
    panelLabel: "执行工作台",
    formId: "execution-launch-form",
  };
}

function executionDraftDiffRows(draft = {}, runtime = {}) {
  const normalizedDraft = normalizeTerminalRequest(draft);
  const normalizedRuntime = normalizeTerminalRequest(runtime, normalizedDraft);
  const rows = [];
  const pushDiff = (label, leftValue, rightValue, tone = "warning") => {
    if (String(leftValue) === String(rightValue)) {
      return;
    }
    rows.push({
      label,
      draft: leftValue,
      runtime: rightValue,
      tone,
    });
  };

  pushDiff("模式", formatTradingMode(normalizedDraft.mode), formatTradingMode(normalizedRuntime.mode));
  pushDiff("交易对", safeText(normalizedDraft.symbol, "BTC/USDT"), safeText(normalizedRuntime.symbol, "BTC/USDT"));
  pushDiff("周期", safeText(normalizedDraft.timeframe, "1h"), safeText(normalizedRuntime.timeframe, "1h"));
  pushDiff("轮询间隔", `${safeText(normalizedDraft.interval_seconds, 30)}s`, `${safeText(normalizedRuntime.interval_seconds, 30)}s`);
  pushDiff("资金", formatMetricNumber(normalizedDraft.capital, 2), formatMetricNumber(normalizedRuntime.capital, 2));
  pushDiff(
    "策略",
    terminalStrategyText(normalizedDraft.strategies),
    terminalStrategyText(normalizedRuntime.strategies),
  );

  return rows;
}

function executionDraftReadinessModel(runtimeControl = {}) {
  const runtime = resolveRuntimeControl(runtimeControl);
  const draft = normalizeTerminalRequest(state.terminalDraft, runtime);
  const meta = state.executionDraftMeta || executionDraftMetaDefaults();
  const executionContext = state.executionHub?.execution_context || {};
  const hasRuntimeReference = Boolean(state.executionHub?.control || state.session?.request);
  const validationContext = executionDraftValidationContext(meta, runtime);
  const validationLabel = validationContext.label;
  const validationTone = validationContext.tone || "muted";
  const normalizedValidation = String(validationLabel || "").trim().toLowerCase();
  const dataSource = meta.dataSource || executionContext.data_source || null;
  const normalizedDataSource = String(dataSource || "").trim().toLowerCase();
  const diffRows = hasRuntimeReference ? executionDraftDiffRows(draft, runtime) : [];
  const liveMode = draft.mode === "live";
  const sandboxMode = draft.mode === "sandbox";
  const demoWalkthroughMode = !liveMode && normalizedDataSource === "demo";
  const riskyDataSource = ["demo", "unknown", "source-unknown", "hybrid"].includes(normalizedDataSource);
  const validationApplies = Boolean(validationLabel)
    && !meta.edited
    && (!meta.sourceStrategy || draft.strategies.includes(meta.sourceStrategy))
    && (!meta.sourceSymbol || draft.symbol === meta.sourceSymbol);
  const staleValidation = Boolean(validationLabel) && !validationApplies;
  const validationFailed = validationTone === "danger"
    || normalizedValidation.includes("no-go")
    || normalizedValidation.includes("fail");
  const blockingValidation = validationApplies && validationFailed && !demoWalkthroughMode;
  const marketReady = normalizedDataSource === "okx" || normalizedDataSource === "market";
  const reasons = [];
  let tone = "muted";
  let label = "待审阅";

  if (blockingValidation) {
    tone = "danger";
    label = "禁止直启";
    reasons.push("验证结论仍为阻断状态，不能直接启动终端。");
  } else if (validationApplies && validationFailed && demoWalkthroughMode) {
    tone = "warning";
    label = "演示可启";
    reasons.push("当前为 Demo 演示场景，可继续启动终端，但该验证结论不能用于实盘放行。");
  } else if (liveMode) {
    tone = "warning";
    label = "实盘复核";
    reasons.push("当前草稿是 live 模式，建议逐项复核来源、风控和数据条件。");
  } else if (staleValidation) {
    tone = "warning";
    label = "待复验";
    reasons.push("草稿已编辑或与最近验证上下文不一致，请重新验证后再启动。");
  } else if (sandboxMode || riskyDataSource || diffRows.length || meta.edited) {
    tone = "warning";
    label = "建议复核";
    if (sandboxMode) {
      reasons.push("当前草稿使用 sandbox 模式，请确认环境与预期一致。");
    }
    if (riskyDataSource) {
      reasons.push(`当前数据源为 ${formatDataSource(dataSource)}，建议先确认样本质量。`);
    }
    if (diffRows.length) {
      reasons.push(`草稿与最近运行配置存在 ${diffRows.length} 处差异。`);
    }
    if (meta.edited) {
      reasons.push("草稿包含手动调整，建议再次核对关键参数。");
    }
  } else if (validationApplies && validationTone === "accent" && marketReady) {
    tone = "accent";
    label = "可启动";
    reasons.push("验证结论为 GO，且数据源已标记为 Market。");
  }

  if (!reasons.length) {
    reasons.push("当前草稿可继续补充来源、验证或数据上下文。");
  }

  return {
    tone,
    label,
    reasons,
    draft,
    runtime,
    meta,
    diffRows,
    validationApplies,
    staleValidation,
    startBlocked: blockingValidation,
    startBlockedReason: blockingValidation
      ? (validationContext.reason || `验证结果为 ${safeText(validationLabel, "NO-GO")}，当前禁止直启。`)
      : null,
  };
}

function openExecutionDraftSource() {
  const meta = state.executionDraftMeta || executionDraftMetaDefaults();
  if (meta.sourcePanel === "research" && meta.sourceRecordId) {
    const record = state.researchHistory.find((item) => item.record_id === meta.sourceRecordId);
    if (record) {
      openResearchRecord(record, "执行草稿来源");
      return;
    }
  }
  if (meta.sourcePanel === "validation" && meta.sourceRecordId) {
    const record = state.validationHistory.find((item) => item.record_id === meta.sourceRecordId);
    if (record) {
      openValidationRecord(record, "执行草稿来源");
      return;
    }
  }
  if (meta.sourcePanel === "session" && (meta.sourceRecordId || meta.sourceSessionId)) {
    const record = state.sessionHistory.find(
      (item) => item.record_id === meta.sourceRecordId || item.session_id === meta.sourceSessionId,
    );
    if (record) {
      void openSessionHistoryRecord(record);
      return;
    }
  }
  if (meta.sourcePanel === "strategies" && meta.sourceStrategy) {
    focusStrategyDirectoryItem(meta.sourceStrategy);
    showPanel("strategies");
    return;
  }
  if (meta.sourcePanel === "data" && meta.sourceSymbol) {
    showPanel("data");
    focusDataSymbolCoverage(meta.sourceSymbol);
    return;
  }
  const action = executionSourceAction(meta);
  if (!action) {
    return;
  }
  if (action.formId) {
    focusPanelWorkspace(action.panel, action.formId);
    return;
  }
  showPanel(action.panel);
}

function resetExecutionDraftToRuntime() {
  const runtimeReference = state.executionHub?.control || state.session?.request;
  if (!runtimeReference) {
    setExecutionControlFeedback("暂无最近运行配置可恢复。", "warning");
    return;
  }
  const normalized = normalizeTerminalRequest(runtimeReference, state.terminalDraft);
  setTerminalDraft(normalized, { dirty: false, syncForms: true });
  setExecutionDraftMeta({
    sourceType: "runtime",
    sourceLabel: runtimeReference.session_id ? "最近运行配置" : "最近会话草稿",
    sourcePanel: "execution",
    sourceRecordId: null,
    sourceSessionId: runtimeReference.session_id || null,
    sourceStrategy: normalized.strategies[0] || null,
    sourceSymbol: normalized.symbol || null,
    validationLabel: null,
    validationTone: "muted",
    validationReason: null,
    validationMethod: null,
    edited: false,
  }, { preserveEdited: false });
  renderExecutionDraftSummary(runtimeReference);
  setExecutionControlFeedback("已恢复最近运行配置。", "accent");
}

function resolveRuntimeControl(request = {}) {
  if (state.executionHub?.control) {
    return state.executionHub.control;
  }
  if (state.session) {
    return {
      ...(state.session.request || request),
      session_id: state.session.session_id,
      running: state.session.running,
    };
  }
  return request;
}

function executionLaunchFeedbackState(runtimeControl = {}) {
  const runtime = resolveRuntimeControl(runtimeControl);
  const review = executionDraftReadinessModel(runtime);
  if (review.startBlocked) {
    return { review, tone: "danger", note: "Blocked" };
  }
  if (review.staleValidation) {
    return { review, tone: "warning", note: "Revalidate" };
  }
  if (review.tone === "warning") {
    return { review, tone: "warning", note: "Review" };
  }
  if (review.validationApplies && review.tone === "accent") {
    return { review, tone: "accent", note: "Ready" };
  }
  return { review, tone: "muted", note: "Idle" };
}

function renderSessionLaunchState(snapshot = {}) {
  const request = snapshot.request || state.executionHub?.control || state.terminalDraft || {};
  const historyMode = sessionViewIsHistory();
  const running = Boolean(snapshot.running);
  const launchState = executionLaunchFeedbackState(request);

  const startButton = document.getElementById("session-start");
  const stopButton = document.getElementById("stop-session");
  const killButton = document.getElementById("kill-session");

  let note = launchState.note;
  let tone = launchState.tone;
  let title = "";

  if (historyMode) {
    note = "历史回看";
    tone = "warning";
    title = "正在回看历史会话，无法直接启动新会话。";
  } else if (running) {
    if (snapshot.kill_switch?.active) {
      note = "熔断中";
      tone = "danger";
      title = safeText(snapshot.kill_switch?.reason, "熔断开关已经触发。");
    } else if (snapshot.last_error) {
      note = "需关注";
      tone = "warning";
      title = safeText(snapshot.last_error, "当前会话需要关注。");
    } else {
      note = "运行中";
      tone = "accent";
      title = "当前已有活跃会话。";
    }
  } else if (launchState.review.startBlocked) {
    title = safeText(
      launchState.review.startBlockedReason,
      "验证阻断，当前禁止启动会话。",
    );
  } else if (launchState.review.reasons.length && tone === "warning") {
    title = safeText(launchState.review.reasons[0], "");
  }

  setSessionControlFeedback(note, tone);
  startButton.disabled = historyMode || running || Boolean(launchState.review.startBlocked);
  startButton.textContent = launchState.review.startBlocked ? "验证阻断" : "启动会话";
  startButton.title = title;
  stopButton.disabled = historyMode || !running;
  killButton.disabled = historyMode || !running;

  return launchState;
}

function setSelectValues(selectNode, values = []) {
  if (!selectNode) {
    return;
  }

  const selected = new Set(
    (Array.isArray(values) ? values : [])
      .filter((value) => value !== null && value !== undefined && value !== "")
      .map((value) => String(value)),
  );
  let matched = 0;

  Array.from(selectNode.options).forEach((option) => {
    const isSelected = selected.has(option.value);
    option.selected = isSelected;
    if (isSelected) {
      matched += 1;
    }
  });

  if (!matched && selectNode.options.length > 0) {
    selectNode.options[0].selected = true;
  }
}

function applyTerminalRequestToForms(request = {}) {
  const forms = [
    document.getElementById("session-form"),
    document.getElementById("execution-launch-form"),
  ];
  const normalized = normalizeTerminalRequest(request, state.terminalDraft);

  forms.forEach((form) => {
    if (!form) {
      return;
    }

    form.elements.mode.value = String(normalized.mode);
    form.elements.symbol.value = String(normalized.symbol);
    form.elements.timeframe.value = String(normalized.timeframe);
    form.elements.interval_seconds.value = String(normalized.interval_seconds);
    form.elements.capital.value = String(normalized.capital);
    setSelectValues(form.querySelector("[name='strategies']"), normalized.strategies);
  });
}

function renderExecutionDraftSummary(runtimeControl = {}) {
  const runtime = resolveRuntimeControl(runtimeControl);
  const meta = state.executionDraftMeta || executionDraftMetaDefaults();
  const executionContext = state.executionHub?.execution_context || {};
  const sourceAction = executionSourceAction(meta);
  const launchState = executionLaunchFeedbackState(runtime);
  const review = launchState.review;
  const draft = review.draft;
  const hasRuntimeReference = Boolean(state.executionHub?.control || state.session?.request);
  const hasRuntime = Boolean(runtime.session_id);
  const runtimeRunning = Boolean(runtime.running);
  const risk = state.executionHub?.risk || {};
  const diffRows = review.diffRows;
  const dataSource = meta.dataSource || executionContext.data_source || "unknown";
  const dataMode = meta.dataMode || executionContext.data_mode || null;
  const dataContextMessage = meta.dataContextMessage || executionContext.data_context_message || null;
  const validationContext = executionDraftValidationContext(meta, runtime);
  const validationLabel = validationContext.label;
  const localizedValidationLabel = localizeInlineText(validationLabel, "未关联");
  const validationTone = validationContext.tone || "muted";
  const validationReason = validationContext.reason;
  const localizedValidationReason = validationReason
    ? localizeInlineText(validationReason, validationReason)
    : null;
  const validationMethod = validationContext.method;
  let note = "当前表单已准备就绪，可直接启动终端。";

  if (runtimeRunning && terminalRequestsEqual(draft, runtime)) {
    note = "草稿与运行中的终端配置一致。";
  } else if (runtimeRunning) {
    note = "草稿已更新。停止当前终端后，可按草稿重新启动。";
  } else if (hasRuntime && terminalRequestsEqual(draft, runtime)) {
    note = "当前表单与最近一次执行配置一致。";
  } else if (hasRuntime) {
    note = "草稿已更新。启动终端后将按新配置创建会话。";
  }
  if (review.reasons.length) {
    note = `${note} ${review.reasons[0]}`;
  }
  if (localizedValidationReason && !note.includes(localizedValidationReason)) {
    note = `${note} ${localizedValidationReason}`;
  } else if (dataContextMessage && !note.includes(dataContextMessage)) {
    note = `${note} ${dataContextMessage}`;
  }

  document.getElementById("execution-draft-config").textContent = terminalConfigText(draft);
  document.getElementById("execution-draft-strategy").textContent = terminalStrategyText(draft.strategies);
  document.getElementById("execution-draft-note").textContent = note;

  const readinessNode = document.getElementById("execution-draft-readiness");
  readinessNode.className = pillToneClass(review.tone);
  readinessNode.textContent = review.label;

  const startButton = document.getElementById("execution-start");
  startButton.disabled = Boolean(runtimeRunning) || Boolean(review.startBlocked);
  startButton.textContent = review.startBlocked ? "验证阻断" : "启动终端";
  startButton.title = review.startBlocked
    ? safeText(review.startBlockedReason, "验证阻断，暂不可启动。")
    : launchState.tone === "warning" && review.reasons.length
      ? safeText(review.reasons[0], "")
      : "";
  document.getElementById("execution-stop-session").disabled = !runtimeRunning;
  document.getElementById("execution-kill-session").disabled = !runtimeRunning;

  if (!runtimeRunning) {
    setExecutionControlFeedback(launchState.note, launchState.tone);
  }

  const originNode = document.getElementById("execution-draft-origin");
  const originTone = meta.edited ? "warning" : meta.sourceType === "manual" ? "muted" : "accent";
  originNode.className = pillToneClass(originTone);
  originNode.textContent = `来源：${localizeInlineText(safeText(meta.sourceLabel, "手动草稿"), "手动草稿")}`;

  const validationNode = document.getElementById("execution-draft-validation");
  validationNode.className = pillToneClass(validationTone);
  validationNode.textContent = `验证：${localizedValidationLabel}`;

  const dataNode = document.getElementById("execution-draft-data");
  dataNode.className = pillToneClass(dataSourceTone(dataSource));
  dataNode.textContent = `数据：${formatDataSource(dataSource)}`;

  const sourceButton = document.getElementById("execution-open-draft-source");
  sourceButton.textContent = sourceAction.label;

  const resetButton = document.getElementById("execution-reset-runtime");
  resetButton.disabled = !hasRuntimeReference;

  const sourceTrailRows = Array.isArray(meta.sourceTrail)
    ? meta.sourceTrail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
    : [];

  const sourceList = [
    statusRow("来源面板", sourceAction.panelLabel, meta.sourceType === "manual" ? "muted" : "accent"),
    statusRow("来源说明", safeText(meta.sourceLabel, "手动草稿"), meta.edited ? "warning" : "muted"),
    statusRow(
      "来源策略",
      localizeStrategyTitle(meta.sourceStrategy || draft.strategies[0], meta.sourceStrategy || draft.strategies[0]),
    ),
    statusRow("来源交易对", safeText(meta.sourceSymbol || draft.symbol, "N/A")),
    statusRow("草稿策略", terminalStrategyText(draft.strategies)),
    statusRow("当前数据源", formatDataSource(dataSource), dataSourceTone(dataSource)),
    statusRow("验证结论", localizedValidationLabel, validationTone),
  ];
  sourceTrailRows.forEach((item, index) => {
    sourceList.push(
      statusActionRow(
        index === 0 ? "上游来源" : "继续上游",
        sourceContextLabel(item),
        "打开",
        { "source-jump-index": index },
        "muted",
      ),
    );
  });
  if (dataMode) {
    sourceList.push(statusRow("数据模式", formatDataMode(dataMode), dataModeTone(dataMode)));
  }
  if (validationMethod) {
    sourceList.push(statusRow("验证方法", localizeUiText(validationMethod, validationMethod), validationTone));
  }
  if (validationReason) {
    sourceList.push(statusRow("验证说明", localizedValidationReason, validationTone));
  }
  document.getElementById("execution-draft-source-list").innerHTML = sourceList.join("");

  const killSwitchActive = Boolean(risk.kill_switch_active || state.session?.kill_switch?.active);
  const killSwitchReason = risk.kill_switch_reason || state.session?.kill_switch?.reason || "Active";
  const dataCondition = dataMode
    ? `${formatDataMode(dataMode)} · ${formatDataSource(dataSource)}`
    : formatDataSource(dataSource);
  const dataConditionTone = dataMode ? dataModeTone(dataMode) : dataSourceTone(dataSource);
  const riskRows = [
    statusRow(
      "运行模式",
      formatTradingMode(draft.mode),
      draft.mode === "live" ? "warning" : draft.mode === "sandbox" ? "warning" : "accent",
    ),
    statusRow(
      "数据条件",
      dataCondition,
      dataConditionTone,
    ),
    statusRow(
      "验证门",
      localizedValidationLabel,
      validationTone,
    ),
    statusRow(
      "配置差异",
      hasRuntimeReference ? `${diffRows.length} 处差异` : "暂无基线",
      diffRows.length ? "warning" : hasRuntimeReference ? "accent" : "muted",
    ),
    statusRow(
      "当前终端",
      runtimeRunning ? "运行中" : hasRuntime ? "已停止" : "未启动",
      runtimeRunning ? "warning" : hasRuntime ? "muted" : "muted",
    ),
    statusRow(
      "熔断开关",
      killSwitchActive ? killSwitchReason : "已布防",
      killSwitchActive ? "danger" : "accent",
    ),
  ];
  document.getElementById("execution-draft-risk-list").innerHTML = riskRows.join("");

  const diffCountNode = document.getElementById("execution-draft-diff-count");
  diffCountNode.className = pillToneClass(
    !hasRuntimeReference ? "muted" : diffRows.length ? "warning" : "accent",
  );
  diffCountNode.textContent = hasRuntimeReference ? `${diffRows.length} 处差异` : "暂无基线";
  document.getElementById("execution-draft-diff-list").innerHTML = !hasRuntimeReference
    ? statusRow("比较基线", "暂无最近运行配置", "muted")
    : diffRows.length
      ? diffRows
        .map((row) => statusRow(row.label, `草稿 ${row.draft} / 运行 ${row.runtime}`, row.tone))
        .join("")
      : statusRow("状态", "暂无差异", "accent");

  renderSessionLaunchState(state.liveSessionSnapshot || state.session || {
    request: state.session?.request || runtime || draft,
    running: Boolean(state.liveSessionSnapshot?.running || state.session?.running),
  });

  return launchState;
}

function setTerminalDraft(request = {}, { dirty = false, syncForms = true } = {}) {
  const normalized = normalizeTerminalRequest(request, state.terminalDraft);
  state.terminalDraft = { ...normalized, dirty };
  if (syncForms) {
    applyTerminalRequestToForms(normalized);
  }
  renderExecutionDraftSummary(request);
  persistWorkbenchState();
}

function syncTerminalForms(request = {}, { force = false } = {}) {
  const normalized = normalizeTerminalRequest(request, state.terminalDraft);
  if (state.terminalDraft?.dirty && !force) {
    renderExecutionDraftSummary(normalized);
    return;
  }
  setTerminalDraft(normalized, { dirty: false, syncForms: true });
}

function buildSessionPayload(formNode) {
  const form = new FormData(formNode);
  const payload = Object.fromEntries(form.entries());
  const strategies = Array.from(formNode.querySelector("[name='strategies']").selectedOptions).map(
    (option) => option.value,
  );
  const defaultStrategy = state.strategies[0]?.strategy_id || "trend_following";
  const intervalSeconds = Number(payload.interval_seconds ?? 0);
  const capital = Number(payload.capital ?? 0);

  payload.interval_seconds = Number.isFinite(intervalSeconds) ? intervalSeconds : 0;
  payload.capital = Number.isFinite(capital) ? capital : 0;
  payload.strategies = strategies.length ? strategies : [defaultStrategy];
  return payload;
}

function captureTerminalDraft(formNode) {
  if (!formNode) {
    return;
  }
  const draft = buildSessionPayload(formNode);
  const currentMeta = state.executionDraftMeta || executionDraftMetaDefaults();
  const editedLabel = safeText(currentMeta.sourceLabel, "手动草稿").replace(/（已编辑）$/, "");
  setTerminalDraft(draft, { dirty: true, syncForms: true });
  setExecutionDraftMeta({
    sourceType: currentMeta.sourceType || "manual",
    sourceLabel: `${editedLabel}（已编辑）`,
    sourcePanel: currentMeta.sourcePanel || "execution",
    sourceStrategy: draft.strategies[0] || currentMeta.sourceStrategy || null,
    sourceSymbol: draft.symbol || currentMeta.sourceSymbol || null,
    edited: true,
  });
  renderExecutionDraftSummary(state.executionHub?.control || state.session?.request || draft);
}

async function refreshRuntimeViews() {
  await loadSessionEvents();
  await loadSessionHistory();
  await loadMonitoring();
  await loadExecutionHub();
  refreshOverviewCommandDeck();
}

function setExecutionControlFeedback(message, tone = "muted") {
  const node = document.getElementById("execution-control-note");
  node.className = pillToneClass(tone);
  node.textContent = safeText(message, "Idle");
}

function setSessionControlFeedback(message, tone = "muted") {
  const node = document.getElementById("session-control-note");
  node.className = pillToneClass(tone);
  node.textContent = safeText(message, "Idle");
}

async function startSessionFromForm(formNode, { errorMode = "session" } = {}) {
  const submitBtn = formNode?.querySelector?.("[type=submit]") || null;
  const restore = withInFlight(submitBtn, "启动中");
  try {
    const payload = buildSessionPayload(formNode);
    setTerminalDraft(payload, { dirty: false, syncForms: true });
    const review = executionDraftReadinessModel(
      state.executionHub?.control || state.session?.request || payload,
    );
    if (review.startBlocked) {
      renderExecutionDraftSummary(state.executionHub?.control || state.session?.request || payload);
      showToast("启动条件未满足，请检查执行草稿", "danger");
      return false;
    }
    renderSession(await api("/api/session/start", { method: "POST", body: JSON.stringify(payload) }));
    await refreshRuntimeViews();
    showToast("交易会话已启动", "success");
    return true;
  } catch (error) {
    if (errorMode === "execution") {
      setExecutionControlFeedback(error.message, "danger");
    } else {
      setSessionControlFeedback(error.message, "danger");
    }
    showToast(`启动失败：${error.message}`, "danger");
    return false;
  } finally {
    restore();
  }
}

async function stopManagedSession({ errorMode = "session" } = {}) {
  const btnId = errorMode === "execution" ? "execution-stop-session" : "stop-session";
  const restore = withInFlight(document.getElementById(btnId), "停止中");
  try {
    renderSession(await api("/api/session/stop", { method: "POST", body: "{}" }));
    await refreshRuntimeViews();
    renderExecutionDraftSummary(state.executionHub?.control || {});
    showToast("交易会话已停止", "info");
    return true;
  } catch (error) {
    if (errorMode === "execution") {
      setExecutionControlFeedback(error.message, "danger");
    } else {
      setSessionControlFeedback(error.message, "danger");
    }
    showToast(`停止失败：${error.message}`, "danger");
    return false;
  } finally {
    restore();
  }
}

async function triggerKillSwitch(reason, { errorMode = "session" } = {}) {
  const btnId = errorMode === "execution" ? "execution-kill-session" : "kill-session";
  const btn = document.getElementById(btnId);
  const restore = withInFlight(btn, "熔断中");
  try {
    await api("/api/session/kill-switch", {
      method: "POST",
      body: JSON.stringify({ reason }),
    });
    await refreshSession();
    await refreshRuntimeViews();
    showToast("Kill Switch 已触发", "danger");
    return true;
  } catch (error) {
    if (errorMode === "execution") {
      setExecutionControlFeedback(error.message, "danger");
    } else {
      setSessionControlFeedback(error.message, "danger");
    }
    showToast(`熔断失败：${error.message}`, "danger");
    return false;
  } finally {
    restore();
  }
}

function triggerFormSubmit(formId) {
  const form = document.getElementById(formId);
  form.dispatchEvent(new Event("submit", { cancelable: true, bubbles: true }));
}

function focusPanelWorkspace(panelName, formId) {
  showPanel(panelName);
  const form = document.getElementById(formId);
  if (!form) {
    return;
  }
  requestAnimationFrame(() => {
    form.scrollIntoView({ block: "start", behavior: "smooth" });
    const firstControl = form.querySelector("input, select, textarea, button");
    firstControl?.focus();
  });
}

function strategyWorkspaceDefaults(strategyId) {
  const strategy = state.strategyMap[strategyId];
  if (!strategy) {
    return null;
  }

  const requestDefaults = state.session?.request || state.executionHub?.control || {};
  return {
    strategyId,
    symbol: strategy.default_symbol || requestDefaults.symbol || "BTC/USDT",
    timeframe: strategy.timeframe || requestDefaults.timeframe || "4h",
    capital: Number(requestDefaults.capital || 10000),
    interval_seconds: Number(requestDefaults.interval_seconds || 30),
    params: deepClone(strategy.params || {}),
  };
}

function routeStrategyToWorkspace(strategyId, destination) {
  const defaults = strategyWorkspaceDefaults(strategyId);
  if (!defaults) {
    return;
  }
  const strategyTitle = localizeStrategyTitle(defaults.strategyId, defaults.strategyId);
  const sourceContext = strategyDirectorySourceContext(defaults.strategyId, defaults.symbol);

  if (destination === "research") {
    setPendingResearchSource(sourceContext);
    populateResearchForm({
      strategy: defaults.strategyId,
      symbol: defaults.symbol,
      capital: defaults.capital,
      fee: 0.001,
      start: "",
      end: "",
      params: defaults.params,
    });
    document.getElementById("research-status").textContent = "已从策略目录载入参数。";
    focusPanelWorkspace("research", "research-form");
    return;
  }

  if (destination === "validation") {
    setPendingValidationSource(sourceContext);
    populateValidationForm({
      strategy: defaults.strategyId,
      symbol: defaults.symbol,
      method: "gate",
      optimize_trials: 10,
      wfo_windows: 2,
      capital: defaults.capital,
      params: defaults.params,
    });
    document.getElementById("validation-status").textContent = "已从策略目录载入参数。";
    focusPanelWorkspace("validation", "validation-form");
    return;
  }

  setTerminalDraft({
    mode: "paper",
    strategies: [defaults.strategyId],
    symbol: defaults.symbol,
    timeframe: defaults.timeframe,
    interval_seconds: defaults.interval_seconds,
    capital: Math.max(defaults.capital, 100000),
  }, { dirty: true, syncForms: true });
  setExecutionDraftMeta({
    sourceType: "strategy",
    sourceLabel: `策略目录 / ${strategyTitle}`,
    sourcePanel: "strategies",
    sourceStrategy: defaults.strategyId,
    sourceSymbol: defaults.symbol,
    dataSource: null,
    validationLabel: null,
    validationTone: "muted",
    edited: false,
  }, { preserveEdited: false });
  renderExecutionDraftSummary(state.executionHub?.control || state.session?.request || {});
  setExecutionControlFeedback(`已载入 ${strategyTitle}，可直接启动终端。`, "accent");
  setSessionControlFeedback(`已载入 ${strategyTitle}，可直接启动会话。`, "accent");
  focusPanelWorkspace("execution", "execution-launch-form");
}

function routeDataSymbolToWorkspace(symbol, destination) {
  const resolvedSymbol = safeText(symbol, "BTC/USDT");
  const preferredStrategyId = document.getElementById("research-strategy")?.value
    || document.getElementById("validation-strategy")?.value
    || state.terminalDraft?.strategies?.[0]
    || state.strategies[0]?.strategy_id
    || "trend_following";
  const strategy = state.strategyMap[preferredStrategyId] || {};
  const capital = Number(
    state.session?.request?.capital
    || state.executionHub?.control?.capital
    || state.terminalDraft?.capital
    || 100000,
  );
  const dataSource = state.dataHub?.symbols?.find((item) => item.symbol === resolvedSymbol)?.data_source || null;
  const sourceContext = dataWorkspaceSourceContext(resolvedSymbol, dataSource);

  if (destination === "tag-market") {
    void tagDataSource(resolvedSymbol, "okx");
    return;
  }

  if (destination === "tag-demo") {
    void tagDataSource(resolvedSymbol, "demo");
    return;
  }

  if (destination === "research") {
    setPendingResearchSource(sourceContext);
    populateResearchForm({
      strategy: preferredStrategyId,
      symbol: resolvedSymbol,
      capital,
      fee: 0.001,
      start: "",
      end: "",
      params: deepClone(state.researchParams && Object.keys(state.researchParams).length
        ? state.researchParams
        : (strategy.params || {})),
    });
    document.getElementById("research-status").textContent = `已载入 ${resolvedSymbol} 数据覆盖。`;
    focusPanelWorkspace("research", "research-form");
    return;
  }

  if (destination === "validation") {
    setPendingValidationSource(sourceContext);
    populateValidationForm({
      strategy: preferredStrategyId,
      symbol: resolvedSymbol,
      method: "gate",
      optimize_trials: 10,
      wfo_windows: 2,
      capital,
      params: deepClone(state.validationParams && Object.keys(state.validationParams).length
        ? state.validationParams
        : (strategy.params || {})),
    });
    document.getElementById("validation-status").textContent = `已载入 ${resolvedSymbol} 数据覆盖。`;
    focusPanelWorkspace("validation", "validation-form");
    return;
  }

  stageAnalysisRequestForExecution({
    strategy: preferredStrategyId,
    symbol: resolvedSymbol,
    timeframe: strategy.timeframe || state.terminalDraft?.timeframe || "1h",
    capital,
  }, `${resolvedSymbol} 数据覆盖`, {
    sourceType: "data",
    sourcePanel: "data",
    dataSource,
  });
}

function handleMonitoringAction(action, origin = "latest") {
  const labelPrefix = origin === "alert" ? "监控告警 / " : "";
  const latestResearch = state.monitoring?.latest?.research || state.latestResearchResult;
  const latestValidation = state.monitoring?.latest?.validation || state.latestValidationResult;
  const latestSession = state.monitoring?.latest?.session || state.session;
  const latestSessionRequest = latestSession?.request || state.session?.request;
  const latestDataSymbol = safeText(
    state.dataHub?.leaders?.latest_symbol?.symbol
      || state.monitoring?.latest?.research?.symbol
      || latestSessionRequest?.symbol
      || state.overview?.data?.symbols?.[0]?.symbol,
    "BTC/USDT",
  );

  if (action === "open-research") {
    if (latestResearch) {
      openResearchRecord(latestResearch, `${labelPrefix}最近研究`);
    } else {
      document.getElementById("research-status").textContent = `${labelPrefix}已定位到研究工作台。`;
      focusPanelWorkspace("research", "research-form");
    }
    return true;
  }

  if (action === "research-stage-execution") {
    if (latestResearch?.request) {
      stageResearchForExecution(latestResearch, `${labelPrefix}最近研究`);
    } else {
      setExecutionControlFeedback(`${labelPrefix}缺少研究请求，已定位到执行工作台。`, "warning");
      focusPanelWorkspace("execution", "execution-launch-form");
    }
    return true;
  }

  if (action === "open-validation") {
    if (latestValidation) {
      openValidationRecord(latestValidation, `${labelPrefix}最近验证`);
    } else {
      document.getElementById("validation-status").textContent = `${labelPrefix}已定位到验证工作台。`;
      focusPanelWorkspace("validation", "validation-form");
    }
    return true;
  }

  if (action === "validation-stage-execution") {
    if (latestValidation) {
      stageValidationForExecution(latestValidation);
    } else {
      setExecutionControlFeedback(`${labelPrefix}缺少验证结果，已定位到执行工作台。`, "warning");
      focusPanelWorkspace("execution", "execution-launch-form");
    }
    return true;
  }

  if (action === "research-open-validation") {
    if (latestResearch) {
      stageResearchForValidation(latestResearch);
    } else {
      document.getElementById("validation-status").textContent = `${labelPrefix}缺少研究结果，已定位到验证工作台。`;
      focusPanelWorkspace("validation", "validation-form");
    }
    return true;
  }

  if (action === "open-session") {
    if (latestSessionRequest) {
      stageSessionRequest(latestSessionRequest, `${labelPrefix}最近会话`, "session", {
        sourceRecordId: latestSession?.record_id || null,
        sourceSessionId: latestSession?.session_id || null,
      });
    } else {
      setSessionControlFeedback(`${labelPrefix}缺少会话请求，已定位到会话工作台。`, "warning");
      focusPanelWorkspace("session", "session-form");
    }
    return true;
  }

  if (action === "session-stage-execution") {
    if (latestSessionRequest) {
      stageSessionRequest(latestSessionRequest, `${labelPrefix}最近会话`, "execution", {
        sourceRecordId: latestSession?.record_id || null,
        sourceSessionId: latestSession?.session_id || null,
      });
    } else {
      setExecutionControlFeedback(`${labelPrefix}缺少会话草稿，已定位到执行工作台。`, "warning");
      focusPanelWorkspace("execution", "execution-launch-form");
    }
    return true;
  }

  if (action === "open-data") {
    showPanel("data");
    return true;
  }

  if (action === "open-execution") {
    focusPanelWorkspace("execution", "execution-launch-form");
    return true;
  }

  if (action === "open-draft-source") {
    openExecutionDraftSource();
    return true;
  }

  if (action === "tag-market") {
    showPanel("data");
    void tagDataSource(latestDataSymbol, "okx");
    return true;
  }

  if (action === "tag-demo") {
    showPanel("data");
    void tagDataSource(latestDataSymbol, "demo");
    return true;
  }

  if (action === "focus-research") {
    document.getElementById("research-status").textContent = `${labelPrefix}已定位到研究工作台。`;
    focusPanelWorkspace("research", "research-form");
    return true;
  }

  if (action === "open-monitoring") {
    showPanel("monitoring");
    return true;
  }

  return false;
}

function stageAnalysisRequestForExecution(request = {}, sourceLabel = "分析结果", meta = {}) {
  const strategyId = request.strategy
    || request.strategies?.[0]
    || state.terminalDraft.strategies?.[0]
    || state.strategies[0]?.strategy_id
    || "trend_following";
  const strategy = state.strategyMap[strategyId] || {};
  const sourceTrail = Array.isArray(meta.sourceTrail)
    ? meta.sourceTrail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
    : [];
  const draft = {
    mode: "paper",
    strategies: [strategyId],
    symbol: request.symbol || strategy.default_symbol || state.terminalDraft.symbol || "BTC/USDT",
    timeframe: request.timeframe || strategy.timeframe || state.terminalDraft.timeframe || "1h",
    interval_seconds: request.interval_seconds ?? state.terminalDraft.interval_seconds ?? 30,
    capital: request.capital ?? state.terminalDraft.capital ?? 100000,
  };

  setTerminalDraft(draft, { dirty: true, syncForms: true });
  setExecutionDraftMeta({
    sourceType: meta.sourceType || "research",
    sourceLabel,
    sourcePanel: meta.sourcePanel || (meta.sourceType === "data" ? "data" : "research"),
    sourceRecordId: meta.sourceRecordId || null,
    sourceSessionId: meta.sourceSessionId || null,
    sourceStrategy: strategyId,
    sourceSymbol: draft.symbol,
    dataSource: meta.dataSource ?? request.data_source ?? state.latestResearchResult?.data_source ?? null,
    validationLabel: meta.validationLabel ?? null,
    validationTone: meta.validationTone || "muted",
    validationReason: meta.validationReason ?? null,
    validationMethod: meta.validationMethod ?? null,
    sourceTrail,
    edited: false,
  }, { preserveEdited: false });
  renderExecutionDraftSummary(state.executionHub?.control || state.session?.request || draft);
  setExecutionControlFeedback(`${sourceLabel} 已送入执行草稿。`, "accent");
  setSessionControlFeedback(`${sourceLabel} 已送入执行草稿。`, "accent");
  focusPanelWorkspace("execution", "execution-launch-form");
}

function resolvedHistoryRecordId(kind, payload = {}) {
  const direct = historyRecordIdOf(payload);
  if (direct) {
    return direct;
  }
  if (kind === "research") {
    return state.researchView?.historyRecordId || null;
  }
  if (kind === "validation") {
    return state.validationView?.historyRecordId || null;
  }
  return null;
}

function stageValidationForExecution(payload = {}) {
  const summary = payload.summary || {};
  const outcomeRaw = summary.outcome_label || summary.decision || "Validation";
  const outcome = localizeInlineText(outcomeRaw, "验证");
  const tone = validationOutcomeTone(summary);
  const recordId = resolvedHistoryRecordId("validation", payload);
  const payloadWithRecord = recordId && !historyRecordIdOf(payload)
    ? { ...payload, record_id: recordId }
    : payload;
  const sourceContext = validationRecordSourceContext(payloadWithRecord, `验证结果 ${outcome}`);

  stageAnalysisRequestForExecution(payload.request || {}, `验证结果 ${outcome}`, {
    sourceType: "validation",
    sourcePanel: "validation",
    sourceRecordId: recordId,
    dataSource: payload.data_source || null,
    validationLabel: outcomeRaw,
    validationTone: tone,
    validationReason: summary.reason || null,
    validationMethod: summary.method_label || summary.method || null,
    sourceTrail: sourceTrailFromContext(sourceContext).slice(1),
  });
  if (tone !== "accent") {
    setExecutionControlFeedback(`验证结果为 ${outcome}，草稿已载入，请先复核。`, "warning");
  }
}

function stageResearchForExecution(payload = {}, sourceLabel = "研究结果") {
  const request = payload.request || {};
  const recordId = resolvedHistoryRecordId("research", payload);
  const payloadWithRecord = recordId && !historyRecordIdOf(payload)
    ? { ...payload, record_id: recordId }
    : payload;
  const sourceContext = researchRecordSourceContext(payloadWithRecord, sourceLabel);

  stageAnalysisRequestForExecution(request, sourceLabel, {
    sourceType: "research",
    sourcePanel: "research",
    sourceRecordId: recordId,
    dataSource: payload.data_source || null,
    sourceTrail: sourceTrailFromContext(sourceContext).slice(1),
  });
}

function stageResearchForValidation(payload = {}) {
  const request = payload.request;
  if (!request) {
    return;
  }

  setPendingValidationSource(researchRecordSourceContext(payload, "研究结果"));
  populateValidationForm({
    strategy: request.strategy,
    symbol: request.symbol,
    method: "gate",
    optimize_trials: 10,
    wfo_windows: 2,
    capital: request.capital,
    params: request.params || {},
  });
  document.getElementById("validation-status").textContent = "已从研究结果载入参数。";
  focusPanelWorkspace("validation", "validation-form");
}

function stageSessionRequest(request = {}, sourceLabel = "会话草稿", destination = "session", meta = {}) {
  if (!request) {
    return;
  }

  if (destination === "session" && sessionViewIsHistory()) {
    setSessionView("live");
    renderSessionHistory(state.sessionHistory);
    if (state.liveSessionSnapshot) {
      renderSessionV2(state.liveSessionSnapshot);
    } else {
      renderSessionViewControls();
    }
  }

  const draft = normalizeTerminalRequest(
    request,
    state.session?.request || state.executionHub?.control || state.terminalDraft,
  );
  setTerminalDraft(draft, { dirty: true, syncForms: true });
  setExecutionDraftMeta({
    sourceType: "session",
    sourceLabel,
    sourcePanel: "session",
    sourceRecordId: meta.sourceRecordId || null,
    sourceSessionId: meta.sourceSessionId || request.session_id || state.session?.session_id || null,
    sourceStrategy: draft.strategies[0] || null,
    sourceSymbol: draft.symbol || null,
    edited: false,
  }, { preserveEdited: false });
  renderExecutionDraftSummary(state.executionHub?.control || state.session?.request || draft);

  if (destination === "execution") {
    setExecutionControlFeedback(`${sourceLabel} 已送入执行草稿。`, "accent");
    setSessionControlFeedback(`${sourceLabel} 已同步到会话草稿。`, "accent");
    focusPanelWorkspace("execution", "execution-launch-form");
    return;
  }

  setSessionControlFeedback(`${sourceLabel} 已恢复到会话草稿。`, "accent");
  setExecutionControlFeedback(`${sourceLabel} 已同步到执行草稿。`, "accent");
  focusPanelWorkspace("session", "session-form");
}

function openResearchRecord(record = {}, sourceLabel = "研究记录") {
  const payload = record.payload || record;
  if (!payload?.request) {
    return;
  }
  const recordId = historyRecordIdOf(payload) || record.record_id || null;
  if (
    recordId
    && state.pendingResearchSource
    && !researchSourceContextForRecord({ record_id: recordId, history_record: payload.history_record })
  ) {
    rememberResearchSourceContext(recordId, state.pendingResearchSource);
  }
  setResearchView(record);
  renderResearch(payload);
  populateResearchForm(payload.request);
  renderResearchHistory(state.researchHistory);
  document.getElementById("research-status").textContent = `${sourceLabel} 已载入`;
  scrollHistoryCardIntoView("research-history", recordId);
  showPanel("research");
}

function openValidationRecord(record = {}, sourceLabel = "验证记录") {
  const payload = record.payload || record;
  if (!payload?.request) {
    return;
  }
  const recordId = historyRecordIdOf(payload) || record.record_id || null;
  if (
    recordId
    && state.pendingValidationSource
    && !validationSourceContextForRecord({ record_id: recordId, history_record: payload.history_record })
  ) {
    rememberValidationSourceContext(recordId, state.pendingValidationSource);
  }
  setValidationView(record);
  renderValidation(payload);
  populateValidationForm(payload.request);
  renderValidationHistory(state.validationHistory);
  document.getElementById("validation-status").textContent = `${sourceLabel} 已载入`;
  scrollHistoryCardIntoView("validation-history", recordId);
  showPanel("validation");
}

function chartPayload() {
  return state.researchChart.payload;
}

function chartTotalBars() {
  return chartPayload()?.candles?.length || 0;
}

function clamp(value, min, max) {
  return Math.min(max, Math.max(min, value));
}

function syncRangeControls() {
  const total = chartTotalBars();
  const count = state.researchChart.end - state.researchChart.start;
  const buttons = document.querySelectorAll("#research-range-controls .segment-btn");
  buttons.forEach((button) => {
    const { range } = button.dataset;
    let active = false;
    if (range === "all") {
      active = count === total;
    } else {
      active = Number(range) === count;
    }
    setSegmentPressed(button, active);
  });
}

function setResearchVisibleRange(countOrAll) {
  const total = chartTotalBars();
  if (!total) {
    state.researchChart.start = 0;
    state.researchChart.end = 0;
    return;
  }
  const count = countOrAll === "all" ? total : clamp(Number(countOrAll), 24, total);
  state.researchChart.end = total;
  state.researchChart.start = Math.max(0, total - count);
  syncRangeControls();
  renderResearchChart();
}

function resetResearchChartViewport() {
  const payload = chartPayload();
  if (!payload?.candles?.length) {
    state.researchChart.start = 0;
    state.researchChart.end = 0;
    return;
  }
  const total = payload.candles.length;
  const visible = clamp(payload.visible_default || 180, 24, total);
  state.researchChart.start = Math.max(0, total - visible);
  state.researchChart.end = total;
  state.researchChart.hoverIndex = null;
  syncRangeControls();
}

function moveResearchWindow(barDelta) {
  const total = chartTotalBars();
  const visible = state.researchChart.end - state.researchChart.start;
  if (!total || visible >= total) {
    return;
  }
  const nextStart = clamp(state.researchChart.start + barDelta, 0, total - visible);
  state.researchChart.start = nextStart;
  state.researchChart.end = nextStart + visible;
  syncRangeControls();
  renderResearchChart();
}

function zoomResearchWindow(deltaY, anchorRatio = 0.5) {
  const total = chartTotalBars();
  if (!total) {
    return;
  }
  const current = state.researchChart.end - state.researchChart.start;
  const next = deltaY < 0 ? Math.max(24, Math.floor(current * 0.85)) : Math.min(total, Math.ceil(current * 1.15));
  if (next === current) {
    return;
  }
  const anchorIndex = state.researchChart.start + Math.floor(current * anchorRatio);
  const nextStart = clamp(anchorIndex - Math.floor(next * anchorRatio), 0, total - next);
  state.researchChart.start = nextStart;
  state.researchChart.end = nextStart + next;
  syncRangeControls();
  renderResearchChart();
}

function visibleResearchSlice() {
  const payload = chartPayload();
  if (!payload?.candles?.length) {
    return null;
  }
  const total = payload.candles.length;
  const start = clamp(state.researchChart.start, 0, Math.max(0, total - 1));
  const end = clamp(state.researchChart.end, start + 1, total);
  return {
    candles: payload.candles.slice(start, end),
    volume: payload.volume.slice(start, end),
    secondary: payload.secondary[state.researchChart.secondaryMode].slice(start, end),
    markers: {
      entries: payload.markers.entries.filter((item) => item.chart_index >= start && item.chart_index < end),
      exits: payload.markers.exits.filter((item) => item.chart_index >= start && item.chart_index < end),
    },
    start,
    end,
    total,
    timeframe: payload.timeframe,
    meta: payload.meta,
    sampled: payload.sampled,
  };
}

function prepareCanvas(canvas) {
  const rect = canvas.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const width = Math.max(1, Math.floor(rect.width));
  const height = Math.max(1, Math.floor(rect.height));
  if (canvas.width !== Math.floor(width * dpr) || canvas.height !== Math.floor(height * dpr)) {
    canvas.width = Math.floor(width * dpr);
    canvas.height = Math.floor(height * dpr);
  }
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  return { ctx, width, height };
}

function drawGrid(ctx, width, height, padding) {
  ctx.save();
  ctx.strokeStyle = "rgba(147, 164, 189, 0.12)";
  ctx.lineWidth = 1;
  for (let i = 0; i < 5; i += 1) {
    const y = padding.top + (i / 4) * (height - padding.top - padding.bottom);
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(width - padding.right, y);
    ctx.stroke();
  }
  ctx.restore();
}

function renderResearchMainChart(slice) {
  const { ctx, width, height } = prepareCanvas(researchChartNodes.main);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(9, 14, 24, 0.88)";
  ctx.fillRect(0, 0, width, height);

  const candles = slice.candles;
  if (!candles.length) {
    return;
  }

  const padding = { top: 16, right: 18, bottom: 18, left: 58 };
  const volumeHeight = Math.max(48, Math.floor(height * 0.18));
  const gap = 12;
  const priceBottom = height - padding.bottom - volumeHeight - gap;
  const priceHeight = priceBottom - padding.top;
  const volumeTop = priceBottom + gap;
  const volumeBottom = height - padding.bottom;

  const lows = candles.map((item) => Number(item.low));
  const highs = candles.map((item) => Number(item.high));
  const volumes = slice.volume.map((value) => Number(value || 0));
  const minPrice = Math.min(...lows);
  const maxPrice = Math.max(...highs);
  const pricePad = (maxPrice - minPrice || Math.max(maxPrice * 0.01, 1)) * 0.08;
  const priceRange = maxPrice + pricePad - (minPrice - pricePad) || 1;
  const plotWidth = width - padding.left - padding.right;
  const step = plotWidth / candles.length;
  const candleWidth = clamp(step * 0.62, 3, 14);
  const volumeMax = Math.max(...volumes, 1);

  drawGrid(ctx, width, priceBottom, { ...padding, bottom: height - priceBottom });

  const priceY = (price) => priceBottom - ((price - (minPrice - pricePad)) / priceRange) * priceHeight;
  const volumeY = (value) => volumeBottom - (value / volumeMax) * (volumeBottom - volumeTop);

  volumes.forEach((value, index) => {
    const candle = candles[index];
    const centerX = padding.left + step * index + step / 2;
    const barTop = volumeY(value);
    ctx.fillStyle = candle.close >= candle.open ? "rgba(45, 212, 191, 0.18)" : "rgba(251, 113, 133, 0.18)";
    ctx.fillRect(centerX - candleWidth / 2, barTop, candleWidth, volumeBottom - barTop);
  });

  candles.forEach((candle, index) => {
    const centerX = padding.left + step * index + step / 2;
    const openY = priceY(Number(candle.open));
    const closeY = priceY(Number(candle.close));
    const highY = priceY(Number(candle.high));
    const lowY = priceY(Number(candle.low));
    const rising = Number(candle.close) >= Number(candle.open);

    ctx.strokeStyle = rising ? "#2dd4bf" : "#fb7185";
    ctx.lineWidth = 1.4;
    ctx.beginPath();
    ctx.moveTo(centerX, highY);
    ctx.lineTo(centerX, lowY);
    ctx.stroke();

    const bodyTop = Math.min(openY, closeY);
    const bodyHeight = Math.max(2, Math.abs(closeY - openY));
    ctx.fillStyle = rising ? "rgba(45, 212, 191, 0.92)" : "rgba(251, 113, 133, 0.92)";
    ctx.fillRect(centerX - candleWidth / 2, bodyTop, candleWidth, bodyHeight);
  });

  const markerGroups = [
    { items: slice.markers.entries, fill: "#38bdf8", direction: -1, label: "E" },
    { items: slice.markers.exits, fill: "#f59e0b", direction: 1, label: "X" },
  ];
  markerGroups.forEach((group) => {
    group.items.forEach((marker) => {
      const localIndex = marker.chart_index - slice.start;
      if (localIndex < 0 || localIndex >= candles.length) {
        return;
      }
      const centerX = padding.left + step * localIndex + step / 2;
      const candle = candles[localIndex];
      const anchorY = priceY(Number(marker.price ?? candle.close));
      const offset = group.direction < 0 ? -12 : 12;
      const tipY = anchorY + offset;

      ctx.fillStyle = group.fill;
      ctx.beginPath();
      ctx.moveTo(centerX, tipY);
      ctx.lineTo(centerX - 6, tipY + (group.direction < 0 ? 10 : -10));
      ctx.lineTo(centerX + 6, tipY + (group.direction < 0 ? 10 : -10));
      ctx.closePath();
      ctx.fill();

      ctx.fillStyle = "rgba(230, 237, 247, 0.92)";
      ctx.font = "10px Inter, sans-serif";
      ctx.textAlign = "center";
      ctx.fillText(group.label, centerX, tipY + (group.direction < 0 ? 22 : -14));
    });
  });

  if (state.researchChart.hoverIndex !== null) {
    const localIndex = clamp(state.researchChart.hoverIndex, 0, candles.length - 1);
    const x = padding.left + step * localIndex + step / 2;
    ctx.strokeStyle = "rgba(56, 189, 248, 0.55)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, padding.top);
    ctx.lineTo(x, volumeBottom);
    ctx.stroke();
  }

  ctx.fillStyle = "#93a4bd";
  ctx.font = "12px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(`最高 ${formatMetricNumber(maxPrice, 2)}`, padding.left, 14);
  ctx.fillText(`最低 ${formatMetricNumber(minPrice, 2)}`, padding.left, priceBottom + 14);

  ctx.textAlign = "right";
  ctx.fillText(`成交量 ${formatCompactNumber(volumeMax)}`, width - padding.right, volumeTop - 4);
}

function renderResearchSecondaryChart(slice) {
  const { ctx, width, height } = prepareCanvas(researchChartNodes.secondary);
  ctx.clearRect(0, 0, width, height);
  ctx.fillStyle = "rgba(9, 14, 24, 0.88)";
  ctx.fillRect(0, 0, width, height);

  const values = slice.secondary.map((item) => Number(item));
  if (!values.length) {
    return;
  }

  const padding = { top: 16, right: 18, bottom: 20, left: 58 };
  const plotWidth = width - padding.left - padding.right;
  const plotHeight = height - padding.top - padding.bottom;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = max - min || Math.max(Math.abs(max) * 0.05, 1);
  const base = state.researchChart.secondaryMode === "drawdown" ? Math.max(max, 0) : min;

  drawGrid(ctx, width, height, padding);

  ctx.beginPath();
  values.forEach((value, index) => {
    const x = padding.left + (index / Math.max(values.length - 1, 1)) * plotWidth;
    const y = padding.top + (1 - (value - min) / range) * plotHeight;
    if (index === 0) {
      ctx.moveTo(x, y);
    } else {
      ctx.lineTo(x, y);
    }
  });
  ctx.strokeStyle = state.researchChart.secondaryMode === "equity" ? "#2dd4bf" : "#fb7185";
  ctx.lineWidth = 2.2;
  ctx.stroke();

  ctx.lineTo(padding.left + plotWidth, padding.top + (1 - (base - min) / range) * plotHeight);
  ctx.lineTo(padding.left, padding.top + (1 - (base - min) / range) * plotHeight);
  ctx.closePath();
  ctx.fillStyle = state.researchChart.secondaryMode === "equity"
    ? "rgba(45, 212, 191, 0.14)"
    : "rgba(251, 113, 133, 0.14)";
  ctx.fill();

  if (state.researchChart.hoverIndex !== null) {
    const localIndex = clamp(state.researchChart.hoverIndex, 0, values.length - 1);
    const x = padding.left + (localIndex / Math.max(values.length - 1, 1)) * plotWidth;
    ctx.strokeStyle = "rgba(56, 189, 248, 0.55)";
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(x, padding.top);
    ctx.lineTo(x, height - padding.bottom);
    ctx.stroke();
  }

  ctx.fillStyle = "#93a4bd";
  ctx.font = "12px Inter, sans-serif";
  ctx.textAlign = "left";
  ctx.fillText(
    state.researchChart.secondaryMode === "equity" ? "权益曲线" : "回撤曲线",
    padding.left,
    14,
  );
  ctx.textAlign = "right";
  ctx.fillText(`最高 ${formatMetricNumber(max, 2)}`, width - padding.right, 14);
  ctx.fillText(`最低 ${formatMetricNumber(min, 2)}`, width - padding.right, height - 6);
}

function updateResearchChartSummary(slice) {
  const payload = chartPayload();
  researchChartNodes.summary.textContent = [
    `${slice.timeframe} | ${slice.candles.length}/${slice.total} 根 Bar`,
    `入场 ${payload.meta.entry_count}`,
    `出场 ${payload.meta.exit_count}`,
    payload.sampled ? "抽样视图" : "完整分辨率",
  ].join(" | ");

  researchChartNodes.legend.innerHTML = [
    ["#2dd4bf", "上涨 K 线"],
    ["#fb7185", "下跌 K 线"],
    ["#38bdf8", `入场 ${payload.meta.entry_count}`],
    ["#f59e0b", `出场 ${payload.meta.exit_count}`],
    [state.researchChart.secondaryMode === "equity" ? "#2dd4bf" : "#fb7185", state.researchChart.secondaryMode === "equity" ? "副图：权益" : "副图：回撤"],
  ]
    .map(
      ([color, label]) => `
        <div class="legend-item">
          <span class="legend-swatch" style="background:${color}"></span>
          <span>${label}</span>
        </div>
      `,
    )
    .join("");
}

function showResearchTooltip(localIndex, event, slice) {
  const candle = slice.candles[localIndex];
  if (!candle) {
    return;
  }
  const secondaryValue = slice.secondary[localIndex];
  const entry = slice.markers.entries.find((item) => item.chart_index - slice.start === localIndex);
  const exit = slice.markers.exits.find((item) => item.chart_index - slice.start === localIndex);
  researchChartNodes.tooltip.innerHTML = `
    <div class="tooltip-title">${escapeHtml(candle.label)}</div>
    <div>开 ${formatMetricNumber(candle.open, 2)} | 高 ${formatMetricNumber(candle.high, 2)}</div>
    <div>低 ${formatMetricNumber(candle.low, 2)} | 收 ${formatMetricNumber(candle.close, 2)}</div>
    <div>成交量 ${formatCompactNumber(candle.volume)}</div>
    <div>${state.researchChart.secondaryMode === "equity" ? "权益" : "回撤"} ${formatMetricNumber(secondaryValue, 2)}</div>
    ${entry ? `<div class="tooltip-accent">入场价 ${formatMetricNumber(entry.price, 2)}</div>` : ""}
    ${exit ? `<div class="tooltip-warn">出场价 ${formatMetricNumber(exit.price, 2)}</div>` : ""}
  `;
  researchChartNodes.tooltip.classList.remove("hidden");

  const stageRect = researchChartNodes.stage.getBoundingClientRect();
  const tooltipRect = researchChartNodes.tooltip.getBoundingClientRect();
  const left = clamp(event.clientX - stageRect.left + 16, 12, stageRect.width - tooltipRect.width - 12);
  const top = clamp(event.clientY - stageRect.top + 12, 12, stageRect.height - tooltipRect.height - 12);
  researchChartNodes.tooltip.style.left = `${left}px`;
  researchChartNodes.tooltip.style.top = `${top}px`;
}

function hideResearchTooltip() {
  researchChartNodes.tooltip.classList.add("hidden");
}

function renderResearchChart() {
  const slice = visibleResearchSlice();
  if (!slice) {
    researchChartNodes.empty.classList.remove("hidden");
    researchChartNodes.legend.innerHTML = "";
    researchChartNodes.summary.textContent = "等待图表数据。";
    return;
  }

  researchChartNodes.empty.classList.add("hidden");
  updateResearchChartSummary(slice);
  renderResearchMainChart(slice);
  renderResearchSecondaryChart(slice);
}

function renderResearch(payload) {
  state.latestResearchResult = payload;
  if (state.pendingResearchSource) {
    rememberResearchSourceContext(historyRecordIdOf(payload), state.pendingResearchSource);
  }
  setPendingResearchSource(null);
  document.getElementById("research-empty").classList.add("hidden");
  document.getElementById("research-results").classList.remove("hidden");
  document.getElementById("research-status").textContent = payload.data_source ? `完成 | ${formatDataSource(payload.data_source)}` : "完成";
  const result = payload.result;
  renderResearchDecisionSurface(payload);
  document.getElementById("research-metrics").innerHTML = [
    metricCard("总收益率", formatPercent(result.total_return)),
    metricCard("Sharpe", formatMetricNumber(result.sharpe_ratio)),
    metricCard("最大回撤", formatPercent(result.max_drawdown)),
    metricCard("交易笔数", result.num_trades),
  ].join("");
  document.getElementById("research-report").textContent = localizeResearchReport(result.report_markdown, "");
  state.researchChart.payload = payload.chart || null;
  resetResearchChartViewport();
  renderResearchChart();
  refreshOverviewCommandDeck();
}

function renderValidation(payload) {
  state.latestValidationResult = payload;
  if (state.pendingValidationSource) {
    rememberValidationSourceContext(historyRecordIdOf(payload), state.pendingValidationSource);
  }
  setPendingValidationSource(null);
  const summary = payload.summary || {};
  const model = validationWorkbenchModel(payload);
  document.getElementById("validation-empty").classList.add("hidden");
  document.getElementById("validation-results").classList.remove("hidden");
  document.getElementById("validation-status").textContent = payload.data_source ? `完成 | ${formatDataSource(payload.data_source)}` : "完成";
  const decisionNode = document.getElementById("validation-decision");
  decisionNode.textContent = localizeUiText(safeText(summary.outcome_label || summary.decision, "N/A"), "待检测");
  decisionNode.className = `decision-text ${validationDecisionClass(model.tone)}`;
  document.getElementById("validation-reason").textContent = localizeUiText(safeText(summary.reason, "No reason provided."), "暂无说明");
  document.getElementById("validation-method").textContent = localizeUiText(safeText(summary.method_label, payload.method || "Validation"), "验证运行");
  document.getElementById("validation-method").className = pillToneClass(model.tone);
  document.getElementById("validation-source").textContent = formatDataSource(payload.data_source);
  document.getElementById("validation-summary-strip").innerHTML = model.summaryTiles;
  document.getElementById("validation-evidence-board").innerHTML = model.evidenceBoardHtml || "";
  document.getElementById("validation-metrics").innerHTML = model.metrics;
  document.getElementById("validation-highlights").innerHTML = model.highlights || validationHighlightCard("暂无可用要点。", "muted");
  document.getElementById("validation-detail-grid").innerHTML = model.detailCards;
  document.getElementById("validation-breakdown-title").textContent = localizeInlineText(model.breakdownTitle, model.breakdownTitle);
  document.getElementById("validation-breakdown-subtitle").textContent = localizeInlineText(model.breakdownSubtitle, model.breakdownSubtitle);
  const breakdownPill = document.getElementById("validation-breakdown-pill");
  breakdownPill.textContent = localizeInlineText(model.breakdownPill, model.breakdownPill);
  breakdownPill.className = pillToneClass(model.breakdownTone || model.tone);
  document.getElementById("validation-breakdown").innerHTML = model.breakdownHtml;
  document.getElementById("validation-json").textContent = JSON.stringify(payload, null, 2);
  renderResearchDecisionSurface();
  refreshOverviewCommandDeck();
}

function renderSessionV2(snapshot) {
  state.session = snapshot;
  renderSessionViewControls();
  const request = snapshot.request || {};
  const health = snapshot.health || {};
  const portfolio = snapshot.portfolio || {};
  const dashboard = snapshot.dashboard || {};
  const killSwitch = snapshot.kill_switch || {};
  const strategies = Array.isArray(dashboard.strategies) ? dashboard.strategies : (request.strategies || []);
  const statusTone = dashboard.status_tone || (snapshot.running ? "accent" : "muted");
  const statusLabel = localizeUiText(dashboard.status_label || (snapshot.running ? "Running" : "Stopped"));
  const historyMode = sessionViewIsHistory();
  const liveSessionId = state.liveSessionSnapshot?.session_id;

  const sessionRunning = document.getElementById("session-running");
  sessionRunning.className = pillToneClass(statusTone);
  sessionRunning.textContent = statusLabel;

  document.getElementById("session-status-chip").className = pillToneClass(statusTone);
  document.getElementById("session-status-chip").textContent = statusLabel;
  document.getElementById("session-updated").textContent = formatTimestamp(snapshot.updated_at || snapshot.started_at);

  document.getElementById("session-config-brief").textContent = [
    formatTradingMode(safeText(request.mode, dashboard.mode || "paper")),
    safeText(request.symbol, dashboard.symbol || "N/A"),
    safeText(request.timeframe, dashboard.timeframe || "N/A"),
  ].join(" | ");
  document.getElementById("session-strategy-brief").textContent = strategies.length
    ? formatStrategyText(strategies)
    : `${safeText(dashboard.strategy_count, 0)} 个策略`;

  const controlTone = killSwitch.active
    ? "danger"
    : snapshot.last_error
      ? "warning"
      : snapshot.running
        ? "accent"
        : "muted";
  const controlNote = killSwitch.active
    ? "熔断中"
    : snapshot.last_error
      ? "需关注"
      : snapshot.running
        ? "数据环在线"
        : "待机";
  document.getElementById("session-control-summary").innerHTML = [
    statusRow("资金", formatMetricNumber(request.capital ?? portfolio.equity ?? 0, 2)),
    statusRow("轮询间隔", `${safeText(request.interval_seconds, 0)}s`),
    statusRow("持仓数", safeText(health.open_positions, 0), health.open_positions ? "accent" : "muted"),
    statusRow("挂单数", safeText(health.pending_orders, 0), health.pending_orders ? "warning" : "muted"),
  ].join("");

  document.getElementById("session-telemetry-summary").textContent = snapshot.telemetry?.labels?.length
    ? `${snapshot.telemetry.labels.length} 个遥测点${historyMode ? "已归档" : "已采集"}。`
    : historyMode
      ? "历史快照未包含 telemetry。"
      : "等待会话遥测数据。";
  document.getElementById("session-hero-primary").textContent = historyMode
    ? safeText(snapshot.session_id, "历史会话")
    : snapshot.running
      ? `${formatTradingMode(safeText(request.mode, dashboard.mode || "paper"))} | ${safeText(request.symbol, dashboard.symbol || "N/A")}`
      : "当前没有活跃会话";
  document.getElementById("session-hero-secondary").textContent = historyMode
    ? [
        formatTradingMode(safeText(request.mode, dashboard.mode || "paper")),
        safeText(request.symbol, dashboard.symbol || "N/A"),
        safeText(request.timeframe, dashboard.timeframe || "N/A"),
        strategies.length ? formatStrategyText(strategies) : null,
      ].filter(Boolean).join(" | ")
    : strategies.length
      ? `${safeText(request.timeframe, dashboard.timeframe || "N/A")} | ${formatStrategyText(strategies)}`
      : "启动托管会话后，这里会展示实时遥测与活动摘要。";
  document.getElementById("session-uptime").textContent = safeText(dashboard.uptime_label, "0s");
  document.getElementById("session-exposure").textContent = formatPercent(dashboard.exposure_pct);
  document.getElementById("session-event-total").textContent = safeText(dashboard.recent_event_count, 0);

  document.getElementById("session-metrics").innerHTML = [
    metricCard("现金", formatMetricNumber(portfolio.cash, 2)),
    metricCard("权益", formatMetricNumber(portfolio.equity ?? portfolio.total_value, 2)),
    metricCard("总敞口", formatPercent(dashboard.gross_exposure_pct)),
    metricCard("回撤", formatPercent(portfolio.drawdown)),
  ].join("");

  const riskTone = killSwitch.active
    ? "danger"
    : snapshot.last_error || !health.drawdown_ok
      ? "warning"
      : "accent";
  const riskChip = document.getElementById("session-risk-chip");
  riskChip.className = pillToneClass(riskTone);
  riskChip.textContent = killSwitch.active ? "熔断中" : snapshot.last_error ? "降级" : "稳定";
  document.getElementById("session-risk-list").innerHTML = [
    statusRow("熔断开关", killSwitch.active ? safeText(killSwitch.reason, "已触发") : "已布防", killSwitch.active ? "danger" : "accent"),
    statusRow("回撤保护", health.drawdown_ok ? "正常" : "已触发", health.drawdown_ok ? "accent" : "warning"),
    statusRow("警告", safeText(dashboard.warning_event_count, 0), dashboard.warning_event_count ? "warning" : "muted"),
    statusRow("错误", safeText(dashboard.error_event_count, 0), dashboard.error_event_count ? "danger" : "muted"),
  ].join("");
  document.getElementById("session-activity-grid").innerHTML = [
    activityCard("信号", safeText(dashboard.signal_count, 0), dashboard.signal_count ? "accent" : "muted"),
    activityCard("成交", safeText(dashboard.fill_count, 0), dashboard.fill_count ? "accent" : "muted"),
    activityCard("风控事件", safeText(dashboard.risk_count, 0), dashboard.risk_count ? "warning" : "muted"),
    activityCard("持仓数", safeText(dashboard.open_positions, 0), dashboard.open_positions ? "accent" : "muted"),
    activityCard("挂单数", safeText(dashboard.pending_orders, 0), dashboard.pending_orders ? "warning" : "muted"),
    activityCard(
      "净敞口",
      formatSignedMetricNumber(dashboard.net_exposure_value, 2),
      Math.abs(Number(dashboard.net_exposure_value || 0)) > 0 ? "accent" : "muted",
    ),
  ].join("");

  const errorNode = document.getElementById("session-error");
  if (snapshot.last_error) {
    errorNode.classList.remove("hidden");
    errorNode.textContent = snapshot.last_error;
  } else {
    errorNode.classList.add("hidden");
    errorNode.textContent = "";
  }
  state.sessionEvents = Array.isArray(snapshot.recent_events) ? snapshot.recent_events : [];
  refreshSessionAuditSurfaces(snapshot);
  if (!historyMode) {
    syncTerminalForms(request);
  }
  renderSessionLaunchState(snapshot);
  syncSessionChartControls();
  renderSessionTelemetryChart();
  refreshOverviewCommandDeck();
}

function renderSession(snapshot) {
  state.liveSessionSnapshot = snapshot;
  if (shouldDefaultToLatestSessionHistory(snapshot)) {
    openLatestSessionHistoryByDefault(snapshot);
    return;
  }
  if (sessionViewIsHistory()) {
    renderSessionViewControls();
    renderSessionHistory(state.sessionHistory);
    return;
  }
  setSessionView("live", null, { pinLiveWhenIdle: Boolean(state.sessionView?.pinLiveWhenIdle) });
  return renderSessionV2(snapshot);
  state.session = snapshot;
  const sessionRunning = document.getElementById("session-running");
  sessionRunning.textContent = snapshot.running ? "运行中" : "未启动";
  document.getElementById("session-updated").textContent = formatTimestamp(snapshot.started_at);
  document.getElementById("session-metrics").innerHTML = snapshot.running
    ? [
        metricCard("现金", formatMetricNumber(snapshot.portfolio.cash, 2)),
        metricCard("权益", formatMetricNumber(snapshot.portfolio.equity, 2)),
        metricCard("回撤", formatPercent(snapshot.portfolio.drawdown)),
        metricCard("挂单", formatMetricNumber(snapshot.health.pending_orders, 0)),
      ].join("")
    : [metricCard("会话", "已停止")].join("");
  document.getElementById("session-positions").innerHTML = (snapshot.positions || [])
    .map(
      (position) =>
        `<tr><td>${escapeHtml(safeText(position.symbol, "—"))}</td><td>${formatMetricNumber(position.quantity, 4)}</td><td>${formatMetricNumber(position.entry_price, 2)}</td><td>${formatMetricNumber(position.current_price, 2)}</td><td>${formatMetricNumber(position.unrealized_pnl, 2)}</td></tr>`,
    )
    .join("");
  document.getElementById("session-orders").innerHTML = (snapshot.open_orders || [])
    .map(
      (order) =>
        `<tr><td>${order.order_id}</td><td>${order.symbol}</td><td>${order.side}</td><td>${order.status}</td></tr>`,
    )
    .join("");
  const errorNode = document.getElementById("session-error");
  if (snapshot.last_error) {
    errorNode.classList.remove("hidden");
    errorNode.textContent = snapshot.last_error;
  } else {
    errorNode.classList.add("hidden");
    errorNode.textContent = "";
  }
  renderSessionEvents(snapshot.recent_events || []);
}

async function loadOverview() {
  try {
    const overview = await api("/api/overview");
    const strategies = await api("/api/strategies");
    state.strategyMap = Object.fromEntries(strategies.map((strategy) => [strategy.strategy_id, strategy]));
    renderOverview(overview);
    state.strategies = strategies;
    populateStrategySelectors(strategies);
    renderStrategies(strategies);
    syncTerminalForms(state.session?.request || state.executionHub?.control || {});

    const researchStrategy = document.getElementById("research-strategy").value || strategies[0]?.strategy_id;
    const validationStrategy = document.getElementById("validation-strategy").value || strategies[0]?.strategy_id;
    if (researchStrategy) {
      renderParamEditor("research", researchStrategy, state.researchParams);
    }
    if (validationStrategy) {
      renderParamEditor("validation", validationStrategy, state.validationParams);
    }
  } catch (error) {
    showToast(`总览加载失败：${error.message}`, "danger");
    // L2: version-pill failure fallback — end perpetual "加载中".
    const pill = document.getElementById("version-pill");
    if (pill) {
      pill.textContent = "版本未知";
      pill.dataset.state = "failed";
    }
    throw error; // H1: surface failure, re-throw so M5 poll banner can trigger.
  }
}

async function loadResearchHistory() {
  try {
    const payload = await api("/api/research/history");
    renderResearchHistory(payload.items || []);
  } catch (error) {
    showToast(`研究历史加载失败：${error.message}`, "danger");
    throw error;
  }
}

async function loadValidationHistory() {
  try {
    const payload = await api("/api/validate/history");
    renderValidationHistory(payload.items || []);
  } catch (error) {
    showToast(`验证历史加载失败：${error.message}`, "danger");
    throw error;
  }
}

async function loadDataHub() {
  try {
    const payload = await api("/api/data");
    renderDataHub(payload);
  } catch (error) {
    showToast(`数据中心加载失败：${error.message}`, "danger");
    throw error;
  }
}

async function loadMonitoring() {
  try {
    const payload = await api("/api/monitoring");
    renderMonitoring(payload);
  } catch (error) {
    showToast(`监控加载失败：${error.message}`, "danger");
    throw error;
  }
}

async function loadExecutionHub() {
  try {
    const payload = await api("/api/execution");
    renderExecutionHub(payload);
  } catch (error) {
    showToast(`执行工作台加载失败：${error.message}`, "danger");
    throw error;
  }
}

async function refreshSession() {
  try {
    const snapshot = await api("/api/session");
    renderSession(snapshot);
  } catch (error) {
    showToast(`会话刷新失败：${error.message}`, "danger");
    throw error;
  }
}

async function loadSessionHistory() {
  try {
    const payload = await api("/api/session/history");
    state.sessionHistory = payload.items || [];
    const snapshot = state.liveSessionSnapshot || state.session || {};
    if (openLatestSessionHistoryByDefault(snapshot)) {
      await loadSessionEvents();
      return;
    }
    if (state.session || state.liveSessionSnapshot) {
      refreshSessionAuditSurfaces(state.session || state.liveSessionSnapshot || {});
      return;
    }
    renderSessionHistory(state.sessionHistory);
  } catch (error) {
    showToast(`会话历史加载失败：${error.message}`, "danger");
    throw error;
  }
}

async function loadSessionEvents() {
  try {
    const sessionId = sessionViewIsHistory()
      ? state.sessionView?.historySessionId
      : state.session?.session_id;
    const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const payload = await api(`/api/session/events${query}`);
    state.sessionEvents = payload.items || [];
    if (state.session || state.liveSessionSnapshot) {
      refreshSessionAuditSurfaces(state.session || state.liveSessionSnapshot || {});
      return;
    }
    renderSessionEvents(state.sessionEvents);
  } catch (error) {
    showToast(`会话事件加载失败：${error.message}`, "danger");
    throw error;
  }
}

async function refreshRuntimeSurfaces({ includeMonitoring = true } = {}) {
  if (refreshState.runtimePromise) {
    return refreshState.runtimePromise;
  }

  refreshState.runtimePromise = (async () => {
    await loadExecutionHub();
    await refreshSession();
    await loadSessionEvents();
    await loadSessionHistory();
    if (includeMonitoring) {
      await loadMonitoring();
    }
  })();

  try {
    return await refreshState.runtimePromise;
  } finally {
    refreshState.runtimePromise = null;
  }
}

async function refreshAllSurfaces() {
  if (refreshState.fullPromise) {
    return refreshState.fullPromise;
  }

  refreshState.fullPromise = (async () => {
    await loadOverview();
    await loadMonitoring();
    await loadDataHub();
    await loadResearchHistory();
    await loadValidationHistory();
    await refreshRuntimeSurfaces({ includeMonitoring: false });
    renderResearchChart();
    renderSessionTelemetryChart();
  })();

  try {
    return await refreshState.fullPromise;
  } finally {
    refreshState.fullPromise = null;
  }
}

async function openSessionHistoryRecord(record) {
  if (!record) {
    return;
  }
  setSessionView("history", record);
  renderSessionHistory(state.sessionHistory);
  renderSessionV2(record);
  showPanel("session");
  scrollHistoryCardIntoView("session-history", record.record_id || record.session_id);
  await loadSessionEvents();
}

async function restoreLiveSessionView() {
  setSessionView("live", null, { pinLiveWhenIdle: true });
  renderSessionHistory(state.sessionHistory);
  if (state.liveSessionSnapshot) {
    renderSessionV2(state.liveSessionSnapshot);
  } else {
    await refreshSession();
  }
  await loadSessionEvents();
}

async function replayRestoredWorkbenchState() {
  const restored = restoredWorkbenchState;
  if (!restored) {
    showPanel(state.activePanel || "overview");
    persistWorkbenchState();
    return;
  }

  suspendWorkbenchPersistence = true;
  try {
    if (restored.executionDraftMeta) {
      setExecutionDraftMeta(restored.executionDraftMeta, { preserveEdited: false });
    }
    if (restored.terminalDraft) {
      setTerminalDraft(restored.terminalDraft, {
        dirty: Boolean(restored.terminalDraft.dirty),
        syncForms: true,
      });
    }

    const researchRecordId = restored.researchView?.historyRecordId || null;
    const researchRecord = researchRecordId
      ? state.researchHistory.find((item) => item.record_id === researchRecordId)
      : null;
    if (researchRecord) {
      openResearchRecord(researchRecord, "已恢复研究记录");
    }

    const validationRecordId = restored.validationView?.historyRecordId || null;
    const validationRecord = validationRecordId
      ? state.validationHistory.find((item) => item.record_id === validationRecordId)
      : null;
    if (validationRecord) {
      openValidationRecord(validationRecord, "已恢复验证记录");
    }

    if (restored.sessionView?.mode === "history") {
      const sessionRecord = state.sessionHistory.find(
        (item) =>
          item.record_id === restored.sessionView.historyRecordId
          || item.session_id === restored.sessionView.historySessionId,
      );
      if (sessionRecord) {
        await openSessionHistoryRecord(sessionRecord);
      } else {
        setSessionView("live");
      }
    }

    if (restored.selectedStrategyId && state.strategyMap[restored.selectedStrategyId]) {
      state.selectedStrategyId = restored.selectedStrategyId;
    }
    renderStrategyDirectory();

    showPanel(normalizeWorkbenchPanel(restored.activePanel || state.activePanel || "overview"));
  } finally {
    suspendWorkbenchPersistence = false;
  }
  persistWorkbenchState();
}

function bindResearchChartControls() {
  document.querySelectorAll("#research-range-controls .segment-btn").forEach((button) => {
    button.addEventListener("click", () => setResearchVisibleRange(button.dataset.range));
  });

  document.querySelectorAll("#research-secondary-controls .segment-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.researchChart.secondaryMode = button.dataset.secondary;
      document
        .querySelectorAll("#research-secondary-controls .segment-btn")
        .forEach((item) => setSegmentPressed(item, item.dataset.secondary === state.researchChart.secondaryMode));
      renderResearchChart();
    });
  });

  researchChartNodes.main.addEventListener("wheel", (event) => {
    event.preventDefault();
    const rect = researchChartNodes.main.getBoundingClientRect();
    const anchorRatio = clamp((event.clientX - rect.left) / Math.max(rect.width, 1), 0, 1);
    zoomResearchWindow(event.deltaY, anchorRatio);
  });

  researchChartNodes.main.addEventListener("mousemove", (event) => {
    const slice = visibleResearchSlice();
    if (!slice?.candles?.length) {
      return;
    }
    const rect = researchChartNodes.main.getBoundingClientRect();
    const paddingLeft = 58;
    const paddingRight = 18;
    const plotWidth = rect.width - paddingLeft - paddingRight;
    if (plotWidth <= 0) {
      return;
    }
    const ratio = clamp((event.clientX - rect.left - paddingLeft) / plotWidth, 0, 0.999999);
    const localIndex = clamp(Math.floor(ratio * slice.candles.length), 0, slice.candles.length - 1);
    state.researchChart.hoverIndex = localIndex;
    renderResearchChart();
    showResearchTooltip(localIndex, event, slice);
  });

  researchChartNodes.main.addEventListener("mouseleave", () => {
    state.researchChart.hoverIndex = null;
    renderResearchChart();
    hideResearchTooltip();
  });

  researchChartNodes.main.addEventListener("mousedown", (event) => {
    const rect = researchChartNodes.main.getBoundingClientRect();
    state.researchChart.drag = {
      startX: event.clientX,
      startStart: state.researchChart.start,
      startEnd: state.researchChart.end,
      width: rect.width,
    };
  });

  window.addEventListener("mouseup", () => {
    state.researchChart.drag = null;
  });

  window.addEventListener("mousemove", (event) => {
    const drag = state.researchChart.drag;
    const total = chartTotalBars();
    if (!drag || !total) {
      return;
    }
    const visible = drag.startEnd - drag.startStart;
    if (visible >= total) {
      return;
    }
    const barsPerPixel = visible / Math.max(drag.width, 1);
    const shift = Math.round((drag.startX - event.clientX) * barsPerPixel);
    const nextStart = clamp(drag.startStart + shift, 0, total - visible);
    state.researchChart.start = nextStart;
    state.researchChart.end = nextStart + visible;
    syncRangeControls();
    renderResearchChart();
  });
}

function bindExecutionEventFilterControls() {
  document.querySelectorAll("#execution-event-filter-controls .segment-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.executionEventFilter = button.dataset.executionFilter || "all";
      syncExecutionEventFilterControls();
      if (state.executionHub) {
        renderExecutionEvents(Array.isArray(state.executionHub.events) ? state.executionHub.events : [], state.executionHub);
      }
    });
  });
}

function bindSessionEventFilterControls() {
  document.querySelectorAll("#session-event-filter-controls .segment-btn").forEach((button) => {
    button.addEventListener("click", () => {
      state.sessionEventFilter = button.dataset.sessionFilter || "all";
      syncSessionEventFilterControls();
      const snapshot = state.session || state.liveSessionSnapshot || {};
      if (state.sessionAudit?.kind === "event") {
        const visibleKeys = new Set(
          filteredSessionEvents(state.sessionEvents).map(
            (item) => sessionAuditItemKey("event", item, state.sessionEvents.indexOf(item)),
          ),
        );
        if (!visibleKeys.has(state.sessionAudit.key)) {
          state.sessionAudit = sessionAuditSelection();
        }
      }
      refreshSessionAuditSurfaces(snapshot);
    });
  });
}

document.getElementById("research-strategy").addEventListener("change", (event) => {
  renderParamEditor("research", event.target.value);
});

document.getElementById("validation-strategy").addEventListener("change", (event) => {
  renderParamEditor("validation", event.target.value);
});

document.getElementById("research-reset-params").addEventListener("click", () => {
  renderParamEditor("research", document.getElementById("research-strategy").value);
  document.getElementById("research-status").textContent = "参数已重置";
  renderResearchOpsSurface();
});

document.getElementById("validation-reset-params").addEventListener("click", () => {
  renderParamEditor("validation", document.getElementById("validation-strategy").value);
  document.getElementById("validation-status").textContent = "参数已重置";
});

document.getElementById("research-form").addEventListener("input", () => {
  renderResearchOpsSurface();
});

document.getElementById("research-form").addEventListener("change", () => {
  renderResearchOpsSurface();
});

document.getElementById("research-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitBtn = event.target.querySelector("[type=submit]");
  const restore = withInFlight(submitBtn, "回测中");
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.capital = Number(payload.capital);
  payload.fee = Number(payload.fee);
  payload.params = collectParams("research");
  setResearchView(null);
  renderResearchHistory(state.researchHistory);
  document.getElementById("research-status").textContent = "运行中";
  try {
    renderResearch(await api("/api/research", { method: "POST", body: JSON.stringify(payload) }));
    await loadResearchHistory();
    await loadMonitoring();
    await loadExecutionHub();
    showToast("回测完成", "success");
  } catch (error) {
    document.getElementById("research-status").textContent = error.message;
    showToast(`回测失败：${error.message}`, "danger");
  } finally {
    restore();
  }
});

document.getElementById("validation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const submitBtn = event.target.querySelector("[type=submit]");
  const restore = withInFlight(submitBtn, "验证中");
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.capital = Number(payload.capital);
  payload.optimize_trials = Number(payload.optimize_trials);
  payload.wfo_windows = Number(payload.wfo_windows);
  payload.params = collectParams("validation");
  setValidationView(null);
  renderValidationHistory(state.validationHistory);
  document.getElementById("validation-status").textContent = "运行中";
  try {
    renderValidation(await api("/api/validate", { method: "POST", body: JSON.stringify(payload) }));
    await loadValidationHistory();
    await loadMonitoring();
    await loadExecutionHub();
    showToast("验证完成", "success");
  } catch (error) {
    document.getElementById("validation-status").textContent = error.message;
    showToast(`验证失败：${error.message}`, "danger");
  } finally {
    restore();
  }
});

document.getElementById("session-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await startSessionFromForm(event.target, { errorMode: "session" });
});

document.getElementById("stop-session").addEventListener("click", async () => {
  await stopManagedSession({ errorMode: "session" });
});

document.getElementById("kill-session").addEventListener("click", async () => {
  const btn = document.getElementById("kill-session");
  const confirmed = await holdToConfirm(btn, { duration: 1200, message: "按住以熔断" });
  if (!confirmed) {
    return;
  }
  await triggerKillSwitch("station_manual_override", { errorMode: "session" });
});

document.getElementById("execution-launch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await startSessionFromForm(event.target, { errorMode: "execution" });
});

document.getElementById("execution-stop-session").addEventListener("click", async () => {
  await stopManagedSession({ errorMode: "execution" });
});

document.getElementById("execution-kill-session").addEventListener("click", async () => {
  const btn = document.getElementById("execution-kill-session");
  const confirmed = await holdToConfirm(btn, { duration: 1200, message: "按住以熔断" });
  if (!confirmed) {
    return;
  }
  await triggerKillSwitch("station_manual_override", { errorMode: "execution" });
});

document.getElementById("execution-open-session").addEventListener("click", () => {
  showPanel("session");
});

document.getElementById("execution-open-draft-source").addEventListener("click", () => {
  openExecutionDraftSource();
});

document.getElementById("execution-draft-source-list").addEventListener("click", (event) => {
  const target = event.target.closest("[data-source-jump-index]");
  if (!target) {
    return;
  }
  const index = Number(target.dataset.sourceJumpIndex);
  if (Number.isNaN(index)) {
    return;
  }
  const meta = state.executionDraftMeta || executionDraftMetaDefaults();
  const sourceTrail = Array.isArray(meta.sourceTrail)
    ? meta.sourceTrail.map((item) => normalizeSourceTrailItem(item)).filter(Boolean)
    : [];
  const item = sourceTrail[index];
  if (!item) {
    return;
  }
  openSourceContext(item, index === 0 ? "执行草稿上游来源" : "执行草稿继续上游");
});

document.getElementById("execution-reset-runtime").addEventListener("click", () => {
  resetExecutionDraftToRuntime();
});

document.getElementById("refresh-all").addEventListener("click", async () => {
  const restore = withInFlight(document.getElementById("refresh-all"), "刷新中");
  try {
    await refreshAllSurfaces();
    showToast("数据已刷新", "info", 2000);
  } catch (error) {
    showToast(`刷新失败：${error.message}`, "danger");
  } finally {
    restore();
  }
});

document.getElementById("data-download-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.target;
  const payload = Object.fromEntries(new FormData(form).entries());
  await runDataPreparation(
    "/api/data/download",
    payload,
    `正在拉取 ${safeText(payload.symbol, "BTC/USDT")} ${safeText(payload.timeframe, "4h")} 历史行情。`,
    "download",
  );
});

document.getElementById("data-seed-demo").addEventListener("click", async () => {
  const form = document.getElementById("data-download-form");
  const payload = Object.fromEntries(new FormData(form).entries());
  await runDataPreparation(
    "/api/data/seed-demo",
    payload,
    `正在为 ${safeText(payload.symbol, "BTC/USDT")} 写入 ${safeText(payload.timeframe, "4h")} 演示数据。`,
    "seed",
  );
});

document.getElementById("research-open-validation").addEventListener("click", () => {
  if (!state.latestResearchResult) {
    return;
  }
  stageResearchForValidation(state.latestResearchResult);
});

document.getElementById("research-stage-execution").addEventListener("click", () => {
  if (!state.latestResearchResult) {
    return;
  }
  stageResearchForExecution(state.latestResearchResult, "研究结果");
});

document.getElementById("validation-stage-execution").addEventListener("click", () => {
  if (!state.latestValidationResult) {
    return;
  }
  stageValidationForExecution(state.latestValidationResult);
});

document.getElementById("research-history").addEventListener("click", (event) => {
  const target = event.target.closest("[data-history-kind='research']");
  if (!target) {
    return;
  }
  const record = state.researchHistory.find((item) => item.record_id === target.dataset.recordId);
  if (!record) {
    return;
  }
  if (target.dataset.historyAction === "open") {
    openResearchRecord(record, "研究历史");
    return;
  }
  if (target.dataset.historyAction === "stage-execution") {
    stageResearchForExecution(record, "研究历史");
    return;
  }
  populateResearchForm(record.request);
  document.getElementById("research-status").textContent = "参数已载入";
  if (target.dataset.historyAction === "rerun") {
    triggerFormSubmit("research-form");
  }
});

document.getElementById("validation-history").addEventListener("click", (event) => {
  const target = event.target.closest("[data-history-kind='validation']");
  if (!target) {
    return;
  }
  const record = state.validationHistory.find((item) => item.record_id === target.dataset.recordId);
  if (!record) {
    return;
  }
  if (target.dataset.historyAction === "open") {
    openValidationRecord(record, "验证历史");
    return;
  }
  if (target.dataset.historyAction === "stage-execution") {
    stageValidationForExecution(record);
    return;
  }
  populateValidationForm(record.request);
  document.getElementById("validation-status").textContent = "参数已载入";
  if (target.dataset.historyAction === "rerun") {
    triggerFormSubmit("validation-form");
  }
});

document.getElementById("data-leader-grid").addEventListener("click", (event) => {
  const target = event.target.closest("[data-data-action]");
  if (target) {
    routeDataSymbolToWorkspace(target.dataset.symbol, target.dataset.dataAction);
    return;
  }
  const selectionTarget = event.target.closest("[data-data-inspector-kind]");
  if (!selectionTarget || !state.dataHub) {
    return;
  }
  state.dataInspector = dataInspectorSelection(
    selectionTarget.dataset.dataInspectorKind,
    selectionTarget.dataset.dataInspectorKey,
  );
  refreshDataInspectorSurfaces(state.dataHub);
});

document.getElementById("data-symbol-rows").addEventListener("click", (event) => {
  const target = event.target.closest("[data-data-action]");
  if (target) {
    routeDataSymbolToWorkspace(target.dataset.symbol, target.dataset.dataAction);
    return;
  }
  const selectionTarget = event.target.closest("[data-data-inspector-kind]");
  if (!selectionTarget || !state.dataHub) {
    return;
  }
  state.dataInspector = dataInspectorSelection(
    selectionTarget.dataset.dataInspectorKind,
    selectionTarget.dataset.dataInspectorKey,
  );
  refreshDataInspectorSurfaces(state.dataHub);
});

document.getElementById("data-workflow-actions").addEventListener("click", (event) => {
  const target = event.target.closest("[data-data-action]");
  if (!target) {
    return;
  }
  routeDataSymbolToWorkspace(target.dataset.symbol, target.dataset.dataAction);
});

document.getElementById("data-leader-grid").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const selectionTarget = event.target.closest("[data-data-inspector-kind]");
  if (!selectionTarget || !state.dataHub) {
    return;
  }
  event.preventDefault();
  state.dataInspector = dataInspectorSelection(
    selectionTarget.dataset.dataInspectorKind,
    selectionTarget.dataset.dataInspectorKey,
  );
  refreshDataInspectorSurfaces(state.dataHub);
});

document.getElementById("data-symbol-rows").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const selectionTarget = event.target.closest("[data-data-inspector-kind]");
  if (!selectionTarget || !state.dataHub) {
    return;
  }
  event.preventDefault();
  state.dataInspector = dataInspectorSelection(
    selectionTarget.dataset.dataInspectorKind,
    selectionTarget.dataset.dataInspectorKey,
  );
  refreshDataInspectorSurfaces(state.dataHub);
});

document.getElementById("monitoring-services").addEventListener("click", (event) => {
  const selectionTarget = event.target.closest("[data-monitoring-inspector-kind]");
  if (!selectionTarget || !state.monitoring) {
    return;
  }
  selectMonitoringInspector(
    selectionTarget.dataset.monitoringInspectorKind,
    selectionTarget.dataset.monitoringInspectorKey,
  );
});

document.getElementById("monitoring-services").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const selectionTarget = event.target.closest("[data-monitoring-inspector-kind]");
  if (!selectionTarget || !state.monitoring) {
    return;
  }
  event.preventDefault();
  selectMonitoringInspector(
    selectionTarget.dataset.monitoringInspectorKind,
    selectionTarget.dataset.monitoringInspectorKey,
  );
});

document.getElementById("monitoring-latest-grid").addEventListener("click", (event) => {
  const target = event.target.closest("[data-monitoring-action]");
  if (target) {
    handleMonitoringAction(target.dataset.monitoringAction, "latest");
    return;
  }
  const selectionTarget = event.target.closest("[data-monitoring-inspector-kind]");
  if (!selectionTarget || !state.monitoring) {
    return;
  }
  selectMonitoringInspector(
    selectionTarget.dataset.monitoringInspectorKind,
    selectionTarget.dataset.monitoringInspectorKey,
  );
});

document.getElementById("monitoring-latest-grid").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  if (event.target.closest("[data-monitoring-action]")) {
    return;
  }
  const selectionTarget = event.target.closest("[data-monitoring-inspector-kind]");
  if (!selectionTarget || !state.monitoring) {
    return;
  }
  event.preventDefault();
  selectMonitoringInspector(
    selectionTarget.dataset.monitoringInspectorKind,
    selectionTarget.dataset.monitoringInspectorKey,
  );
});

document.getElementById("monitoring-alerts").addEventListener("click", (event) => {
  const target = event.target.closest("[data-alert-action]");
  if (target) {
    handleMonitoringAction(target.dataset.alertAction, "alert");
    return;
  }
  const selectionTarget = event.target.closest("[data-monitoring-inspector-kind]");
  if (!selectionTarget || !state.monitoring) {
    return;
  }
  selectMonitoringInspector(
    selectionTarget.dataset.monitoringInspectorKind,
    selectionTarget.dataset.monitoringInspectorKey,
  );
});

document.getElementById("monitoring-alerts").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  if (event.target.closest("[data-alert-action]")) {
    return;
  }
  const selectionTarget = event.target.closest("[data-monitoring-inspector-kind]");
  if (!selectionTarget || !state.monitoring) {
    return;
  }
  event.preventDefault();
  selectMonitoringInspector(
    selectionTarget.dataset.monitoringInspectorKind,
    selectionTarget.dataset.monitoringInspectorKey,
  );
});

document.getElementById("overview-next-actions").addEventListener("click", (event) => {
  const target = event.target.closest("[data-overview-action]");
  if (!target) {
    return;
  }
  handleMonitoringAction(target.dataset.overviewAction, "overview");
});

function handleOverviewInspectorClick(event) {
  const actionTarget = event.target.closest("[data-overview-action]");
  if (actionTarget) {
    handleMonitoringAction(actionTarget.dataset.overviewAction, "overview");
    return;
  }
  const selectionTarget = event.target.closest("[data-overview-inspector-kind]");
  if (!selectionTarget || !state.overview) {
    return;
  }
  selectOverviewInspector(
    selectionTarget.dataset.overviewInspectorKind,
    selectionTarget.dataset.overviewInspectorKey,
  );
}

function handleOverviewInspectorKeydown(event) {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  if (event.target.closest("[data-overview-action]")) {
    return;
  }
  const selectionTarget = event.target.closest("[data-overview-inspector-kind]");
  if (!selectionTarget || !state.overview) {
    return;
  }
  event.preventDefault();
  selectOverviewInspector(
    selectionTarget.dataset.overviewInspectorKind,
    selectionTarget.dataset.overviewInspectorKey,
  );
}

document.getElementById("overview-pulse-grid").addEventListener("click", handleOverviewInspectorClick);
document.getElementById("overview-pulse-grid").addEventListener("keydown", handleOverviewInspectorKeydown);
document.getElementById("overview-stage-grid").addEventListener("click", handleOverviewInspectorClick);
document.getElementById("overview-stage-grid").addEventListener("keydown", handleOverviewInspectorKeydown);
document.getElementById("overview-workflow-grid").addEventListener("click", handleOverviewInspectorClick);
document.getElementById("overview-workflow-grid").addEventListener("keydown", handleOverviewInspectorKeydown);
document.getElementById("overview-blockers").addEventListener("click", handleOverviewInspectorClick);
document.getElementById("overview-blockers").addEventListener("keydown", handleOverviewInspectorKeydown);

document.getElementById("platform-workbench-actions").addEventListener("click", (event) => {
  const target = event.target.closest("[data-overview-action]");
  if (!target) {
    return;
  }
  handleMonitoringAction(target.dataset.overviewAction, "overview");
});

document.getElementById("platform-workbench-blockers").addEventListener("click", (event) => {
  const target = event.target.closest("[data-overview-action]");
  if (!target) {
    return;
  }
  handleMonitoringAction(target.dataset.overviewAction, "overview");
});

document.getElementById("panel-execution").addEventListener("click", (event) => {
  const target = event.target.closest("[data-execution-select-kind]");
  if (!target || !state.executionHub) {
    return;
  }
  state.executionInspector = executionInspectorSelection(
    target.dataset.executionSelectKind,
    target.dataset.executionSelectKey,
  );
  refreshExecutionInspectorSurfaces(state.executionHub);
});

document.getElementById("panel-execution").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const target = event.target.closest("[data-execution-select-kind]");
  if (!target || !state.executionHub) {
    return;
  }
  event.preventDefault();
  state.executionInspector = executionInspectorSelection(
    target.dataset.executionSelectKind,
    target.dataset.executionSelectKey,
  );
  refreshExecutionInspectorSurfaces(state.executionHub);
});

document.getElementById("session-return-live").addEventListener("click", async () => {
  await restoreLiveSessionView();
});

document.getElementById("panel-session").addEventListener("click", (event) => {
  const target = event.target.closest("[data-session-audit-kind]");
  if (!target) {
    return;
  }
  const snapshot = state.session || state.liveSessionSnapshot;
  if (!snapshot) {
    return;
  }
  state.sessionAudit = sessionAuditSelection(
    target.dataset.sessionAuditKind,
    target.dataset.sessionAuditKey,
  );
  refreshSessionAuditSurfaces(snapshot);
});

document.getElementById("panel-session").addEventListener("keydown", (event) => {
  if (event.key !== "Enter" && event.key !== " ") {
    return;
  }
  const target = event.target.closest("[data-session-audit-kind]");
  if (!target) {
    return;
  }
  const snapshot = state.session || state.liveSessionSnapshot;
  if (!snapshot) {
    return;
  }
  event.preventDefault();
  state.sessionAudit = sessionAuditSelection(
    target.dataset.sessionAuditKind,
    target.dataset.sessionAuditKey,
  );
  refreshSessionAuditSurfaces(snapshot);
});

document.getElementById("session-history").addEventListener("click", async (event) => {
  const target = event.target.closest("[data-session-history-action]");
  if (!target) {
    return;
  }

  const record = state.sessionHistory.find(
    (item) => item.record_id === target.dataset.recordId || item.session_id === target.dataset.recordId,
  );
  if (!record?.request) {
    return;
  }

  if (target.dataset.sessionHistoryAction === "open-history") {
    await openSessionHistoryRecord(record);
    return;
  }

  if (target.dataset.sessionHistoryAction === "stage-execution") {
    stageSessionRequest(record.request, "会话历史", "execution", {
      sourceRecordId: record.record_id || null,
      sourceSessionId: record.session_id || null,
    });
    return;
  }

  stageSessionRequest(record.request, "会话历史", "session", {
    sourceRecordId: record.record_id || null,
    sourceSessionId: record.session_id || null,
  });
});

document.getElementById("strategy-grid").addEventListener("click", (event) => {
  const selectTarget = event.target.closest("[data-strategy-select]");
  if (selectTarget) {
    selectStrategy(selectTarget.dataset.strategySelect);
    return;
  }

  const target = event.target.closest("[data-strategy-action]");
  if (!target) {
    return;
  }

  selectStrategy(target.dataset.strategyId);
  routeStrategyToWorkspace(target.dataset.strategyId, target.dataset.strategyAction);
});

["session-form", "execution-launch-form"].forEach((formId) => {
  const form = document.getElementById(formId);
  ["input", "change"].forEach((eventName) => {
    form.addEventListener(eventName, () => {
      captureTerminalDraft(form);
    });
  });
});

window.addEventListener("resize", () => {
  renderResearchChart();
  renderSessionTelemetryChart();
  renderExecutionTelemetryChart();
});

async function bootstrap() {
  await restoreWorkbenchState();
  bindResearchChartControls();
  bindSessionChartControls();
  bindExecutionTelemetryControls();
  bindExecutionEventFilterControls();
  bindSessionEventFilterControls();
  bindStrategyDirectoryControls();
  await loadOverview();
  await loadMonitoring();
  await loadDataHub();
  await loadResearchHistory();
  await loadValidationHistory();
  await refreshRuntimeSurfaces({ includeMonitoring: false });
  await replayRestoredWorkbenchState();
  if (refreshState.pollHandle) {
    window.clearInterval(refreshState.pollHandle);
  }
  refreshState.pollHandle = window.setInterval(() => {
    refreshRuntimeSurfaces()
      .then(() => {
        setPollHeartbeat(false);
        if (refreshState.stalled) {
          // Recovery after a stall streak — clear banner + one-shot info toast.
          refreshState.stalled = false;
          document.body.dataset.pollStalled = "false";
          showToast("实时数据已恢复", "info", 1500);
        }
      })
      .catch(() => {
        setPollHeartbeat(true);
        if (!refreshState.stalled) {
          // One-shot toast on FIRST failure of a stall streak (no 5s toast-spam).
          refreshState.stalled = true;
          document.body.dataset.pollStalled = "true";
          showToast("实时数据同步中断，显示上次同步数据", "warning");
        }
      });
  }, 5000);
  ensurePollHeartbeat();
}

// M1: bootstrap error overlay with retry affordance. Replaces the one-line
// .catch that only mutated header subtitle text. Uses DOM API (textContent)
// — no innerHTML with server text (M4-safe).
const bootstrapState = {
  status: "loading", // "loading" | "failed" | "ready"
  error: null,
};

function renderBootstrapError(message) {
  bootstrapState.status = "failed";
  bootstrapState.error = message;

  let overlay = document.getElementById("bootstrap-error-overlay");
  if (!overlay) {
    overlay = document.createElement("div");
    overlay.id = "bootstrap-error-overlay";
    overlay.className = "bootstrap-error-overlay";
    overlay.setAttribute("role", "alert");
    overlay.setAttribute("aria-live", "assertive");
    document.body.appendChild(overlay);
  }
  overlay.replaceChildren();

  const title = document.createElement("h2");
  title.className = "bootstrap-error-title";
  title.textContent = "初始化失败";

  const body = document.createElement("p");
  body.className = "bootstrap-error-body";
  body.textContent = safeText(message, "未知错误");

  const retry = document.createElement("button");
  retry.className = "btn btn-primary";
  retry.type = "button";
  retry.textContent = "重试";
  retry.addEventListener("click", () => {
    overlay.hidden = true;
    bootstrapState.status = "loading";
    runBootstrap();
  });

  overlay.append(title, body, retry);
  overlay.hidden = false;
}

async function runBootstrap() {
  try {
    await bootstrap();
    bootstrapState.status = "ready";
    const overlay = document.getElementById("bootstrap-error-overlay");
    if (overlay) overlay.hidden = true;
  } catch (error) {
    renderBootstrapError(error.message);
  }
}

runBootstrap();
