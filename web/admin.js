"use strict";

const adminState = {
  csrf: "",
  dashboard: null,
  currentView: "overview",
  pollTimer: null,
  messageTimer: null,
  loading: false,
  boardPageTimer: null,
  boardPages: { groups: 0, students: 0 },
  rosterScrollFrame: null,
  rosterScrollLastTime: 0,
  rosterFingerprint: "",
  rosterLoopSetupFrame: null,
  liveFeedFingerprint: "",
  liveFeedScrollFrame: null,
  liveFeedScrollLastTime: 0,
  liveFeedLoopSetupFrame: null,
  revealedActivationCodes: new Map(),
  activationHideTimers: new Map(),
  phaseActionPending: false,
  serverClockOffset: 0,
  recentRenderedAt: 0,
  lastActivityId: null,
  connectionInterrupted: false,
  lastBackgroundErrorAt: 0,
};

const adminEls = {
  loginView: document.querySelector("#admin-login-view"),
  loginForm: document.querySelector("#admin-login-form"),
  loginError: document.querySelector("#admin-login-error"),
  app: document.querySelector("#admin-app"),
  title: document.querySelector("#admin-title"),
  statusBadge: document.querySelector("#admin-status-badge"),
  statusButton: document.querySelector("#toggle-status"),
  readinessPanel: document.querySelector("#readiness-panel"),
  readinessIcon: document.querySelector("#readiness-icon"),
  readinessSummary: document.querySelector("#readiness-summary"),
  readinessDetails: document.querySelector("#readiness-details"),
  lastRefresh: document.querySelector("#last-refresh"),
  selected: document.querySelector("#metric-selected"),
  unselected: document.querySelector("#metric-unselected"),
  waitingOnline: document.querySelector("#waiting-online"),
  waitingAbsent: document.querySelector("#waiting-absent"),
  waitingRate: document.querySelector("#waiting-rate"),
  waitingRateBar: document.querySelector("#waiting-rate-bar"),
  rate: document.querySelector("#metric-rate"),
  rateBar: document.querySelector("#metric-rate-bar"),
  groupProgress: document.querySelector("#group-progress"),
  groupProgressPage: document.querySelector("#group-progress-page"),
  liveSelectionFeed: document.querySelector("#live-selection-feed"),
  liveFeedState: document.querySelector("#live-feed-state"),
  qr: document.querySelector("#student-qr"),
  qrPlaceholder: document.querySelector("#qr-placeholder"),
  publicUrl: document.querySelector("#public-url-label"),
  boardNotice: document.querySelector(".qr-notice"),
  boardStatus: document.querySelector("#board-status-text"),
  boardLiveNote: document.querySelector("#board-live-note"),
  boardStage: document.querySelector("#board-stage"),
  boardStageLabel: document.querySelector("#board-stage-label"),
  boardStageDetail: document.querySelector("#board-stage-detail"),
  boardCountdown: document.querySelector("#board-countdown-value"),
  boardOverlayCountdown: document.querySelector("#board-overlay-countdown"),
  boardStart: document.querySelector("#board-start-countdown"),
  boardActivityTitle: document.querySelector("#board-activity-title"),
  boardHeaderPhase: document.querySelector("#board-header-phase"),
  boardClock: document.querySelector("#board-clock"),
  boardExitFullscreen: document.querySelector("#board-exit-fullscreen"),
  boardRosterHeading: document.querySelector("#board-roster-heading"),
  statsTitle: document.querySelector("#stats-title"),
  unselectedCount: document.querySelector("#unselected-count"),
  unselectedPage: document.querySelector("#unselected-page"),
  unselectedTitle: document.querySelector("#unselected-title"),
  studentListKicker: document.querySelector("#student-list-kicker"),
  unselectedList: document.querySelector("#unselected-list"),
  unselectedSearch: document.querySelector("#unselected-search"),
  recentBody: document.querySelector("#recent-selection-body"),
  majorEditor: document.querySelector("#major-editor"),
  groupEditor: document.querySelector("#group-editor"),
  majorCount: document.querySelector("#major-count-label"),
  groupCount: document.querySelector("#group-count-label"),
  structureLock: document.querySelector("#structure-lock-hint"),
  quotaMatrix: document.querySelector("#quota-matrix"),
  assignmentBody: document.querySelector("#assignment-body"),
  rosterBody: document.querySelector("#student-roster-body"),
  rosterSearch: document.querySelector("#student-roster-search"),
  rosterCount: document.querySelector("#student-roster-count"),
  settingsForm: document.querySelector("#settings-form"),
  activityList: document.querySelector("#activity-list"),
  activityCount: document.querySelector("#activity-count-label"),
  newActivityForm: document.querySelector("#new-activity-form"),
  importForm: document.querySelector("#student-import-form"),
  importFile: document.querySelector("#student-csv"),
  importFileName: document.querySelector("#import-file-name"),
  importMode: document.querySelector("#student-import-mode"),
  importResult: document.querySelector("#import-result"),
  exportSelections: document.querySelector("#export-selections"),
  exportCompleteResults: document.querySelector("#export-complete-results"),
  exportCompletionCallout: document.querySelector("#export-completion-callout"),
  exportUnselected: document.querySelector("#export-unselected"),
  toast: document.querySelector("#admin-toast"),
  dangerDialog: document.querySelector("#danger-dialog"),
};

async function adminApi(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const activityId = options.activityId ?? adminState.dashboard?.settings.activity_id;
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
  if (adminState.csrf && !["GET", "HEAD"].includes((options.method || "GET").toUpperCase())) {
    headers.set("X-CSRF-Token", adminState.csrf);
  }
  if (
    activityId
    && !["GET", "HEAD"].includes((options.method || "GET").toUpperCase())
    && !["/api/admin/logout", "/api/admin/password"].includes(path)
  ) {
    headers.set("X-Activity-ID", String(activityId));
  }
  const { activityId: _activityId, ...fetchOptions } = options;
  let response;
  try {
    response = await fetch(path, { ...fetchOptions, headers, credentials: "same-origin" });
  } catch (_) {
    const error = new Error("网络连接失败，请检查网络后重试");
    error.status = 0;
    throw error;
  }
  const type = response.headers.get("content-type") || "";
  let data = null;
  if (type.includes("application/json")) {
    try { data = await response.json(); } catch (_) { data = null; }
  }
  if (!response.ok) {
    const error = new Error(adminErrorMessage(data, response.status));
    error.status = response.status;
    throw error;
  }
  return data;
}

function adminErrorMessage(data, status) {
  const detail = data?.detail;
  if (typeof detail === "string" && detail.trim()) return detail;
  const messages = {
    400: "提交内容格式不正确，请检查后重试",
    401: "管理员会话已失效，请重新登录",
    403: "当前账号无权执行此操作，请刷新页面后重试",
    404: "目标数据不存在或已被更新",
    409: "操作与当前活动状态冲突，请刷新后重试",
    413: "上传文件过大，请拆分后重试",
    422: "提交内容未通过校验，请检查必填项和文件格式",
    428: "活动版本已经变化，请刷新页面后重试",
    429: "操作过于频繁，请稍后再试",
    500: "服务暂时异常，请稍后重试",
    503: "当前访问人数较多，请稍后重试",
  };
  return messages[status] || `请求未完成（${status}），请稍后重试`;
}

function showAdminToast(text, kind = "info") {
  clearTimeout(adminState.messageTimer);
  adminEls.toast.textContent = text;
  adminEls.toast.className = `toast toast--admin is-visible${kind === "error" ? " is-error" : kind === "success" ? " is-success" : ""}`;
  adminState.messageTimer = setTimeout(() => adminEls.toast.classList.remove("is-visible"), 3500);
}

function formatAdminTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function createCell(text, className = "") {
  const cell = document.createElement("td");
  cell.textContent = text;
  if (className) cell.className = className;
  return cell;
}

function confirmDanger(title, message) {
  const originalParent = adminEls.dangerDialog.parentElement;
  const fullscreenHost = document.fullscreenElement;
  if (fullscreenHost && !fullscreenHost.contains(adminEls.dangerDialog)) {
    fullscreenHost.append(adminEls.dangerDialog);
  }
  document.querySelector("#danger-dialog-title").textContent = title;
  document.querySelector("#danger-dialog-message").textContent = message;
  adminEls.dangerDialog.returnValue = "";
  try {
    adminEls.dangerDialog.showModal();
  } catch (error) {
    if (originalParent && adminEls.dangerDialog.parentElement !== originalParent) {
      originalParent.append(adminEls.dangerDialog);
    }
    throw error;
  }
  return new Promise((resolve) => {
    adminEls.dangerDialog.addEventListener("close", () => {
      const confirmed = adminEls.dangerDialog.returnValue === "confirm";
      if (originalParent && adminEls.dangerDialog.parentElement !== originalParent) {
        originalParent.append(adminEls.dangerDialog);
      }
      resolve(confirmed);
    }, { once: true });
  });
}

function showAdminApp() {
  adminEls.loginView.classList.add("is-hidden");
  adminEls.app.classList.remove("is-hidden");
}

function showAdminLogin() {
  adminEls.app.classList.add("is-hidden");
  adminEls.loginView.classList.remove("is-hidden");
  clearInterval(adminState.pollTimer);
  clearInterval(adminState.boardPageTimer);
  for (const timer of adminState.activationHideTimers.values()) clearTimeout(timer);
  adminState.activationHideTimers.clear();
  adminState.revealedActivationCodes.clear();
  scrubRevealedActivationCodeDom();
  stopRosterAutoScroll();
  stopLiveFeedAutoScroll();
  adminState.rosterFingerprint = "";
  adminState.liveFeedFingerprint = "";
}

function dashboardField(data, key) {
  return data?.[key] ?? data?.settings?.[key] ?? null;
}

function synchronizeServerClock(data) {
  const serverNow = dashboardField(data, "server_now");
  const parsed = Date.parse(serverNow || "");
  if (Number.isFinite(parsed)) adminState.serverClockOffset = parsed - Date.now();
}

function millisecondsUntilSelection(data = adminState.dashboard) {
  const opensAt = dashboardField(data, "selection_opens_at");
  const target = Date.parse(opensAt || "");
  if (!Number.isFinite(target)) return null;
  return target - (Date.now() + adminState.serverClockOffset);
}

function dashboardPhase(data = adminState.dashboard) {
  const raw = String(dashboardField(data, "phase") || "").toLowerCase();
  const status = String(data?.settings?.status || data?.status || "closed").toLowerCase();
  const remaining = millisecondsUntilSelection(data);
  if (["archived", "finished"].includes(raw) || status === "archived") return "closed";
  if (["closed", "paused", "ended"].includes(raw)) return "closed";
  if (raw === "waiting" && status === "closed" && Number(data?.totals?.selected || 0) > 0) return "closed";
  if ((raw === "countdown" || ["countdown", "open"].includes(status)) && remaining !== null && remaining > 0) return "countdown";
  if (raw === "countdown" && (remaining === null || remaining <= 0)) return "open";
  if (["open", "selecting", "active"].includes(raw) || status === "open") return "open";
  return "waiting";
}

function boardDisplayMode(data = adminState.dashboard, phase = dashboardPhase(data)) {
  if (phase === "countdown") return "countdown";
  if (phase === "open") return "selection";
  const currentActivity = (data?.activities || []).find((activity) => activity.current);
  const hasStarted = Boolean(currentActivity?.opened_at) || Number(data?.totals?.selected || 0) > 0;
  return phase === "closed" && hasStarted ? "selection" : "waiting";
}

function normalizedPresence(data = adminState.dashboard) {
  const raw = data?.presence || data?.settings?.presence || {};
  const total = Number(data?.totals?.students || 0);
  const absentStudents = Array.isArray(raw.absent_students)
    ? raw.absent_students
    : Array.isArray(data?.absent_students)
      ? data.absent_students
      : (data?.students || []).filter((student) => student.active);
  const online = Number(raw.entered ?? raw.online_count ?? raw.entered_count ?? Math.max(0, total - absentStudents.length));
  const absent = Number(raw.absent ?? raw.absent_count ?? Math.max(0, total - online));
  return {
    online: Number.isFinite(online) ? online : 0,
    absent: Number.isFinite(absent) ? absent : absentStudents.length,
    absentStudents,
  };
}

function boardIsPresentation() {
  return Boolean(document.fullscreenElement || document.querySelector("#live-board")?.classList.contains("is-presentation"));
}

function boardPageSize(kind) {
  const presenting = boardIsPresentation();
  if (!presenting) return kind === "groups" ? 6 : 7;
  return kind === "groups" ? 6 : 8;
}

function boardPage(items, kind) {
  const size = boardPageSize(kind);
  const pages = Math.max(1, Math.ceil(items.length / size));
  const index = adminState.boardPages[kind] % pages;
  adminState.boardPages[kind] = index;
  return {
    items: items.slice(index * size, index * size + size),
    index,
    pages,
  };
}

async function loadAdminSession() {
  try {
    const me = await adminApi("/api/admin/me");
    adminState.csrf = me.csrf_token;
    showAdminApp();
    await loadDashboard();
    startAdminPolling();
  } catch (error) {
    if (error.status !== 401) adminEls.loginError.textContent = error.message;
    showAdminLogin();
  }
}

async function loadDashboard({ quiet = false } = {}) {
  if (adminState.loading) return;
  adminState.loading = true;
  try {
    const dashboard = await adminApi("/api/admin/dashboard");
    adminState.dashboard = dashboard;
    renderDashboard(dashboard);
    adminEls.lastRefresh.textContent = `刷新于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
    if (adminState.connectionInterrupted) {
      adminState.connectionInterrupted = false;
      showAdminToast("管理端实时连接已恢复", "success");
    }
  } catch (error) {
    if (error.status === 401) {
      showAdminLogin();
      adminEls.loginError.textContent = "登录已失效，请重新登录";
    } else if (!quiet) {
      showAdminToast(error.message, "error");
    } else if (!adminState.connectionInterrupted || Date.now() - adminState.lastBackgroundErrorAt >= 10_000) {
      adminState.connectionInterrupted = true;
      adminState.lastBackgroundErrorAt = Date.now();
      showAdminToast(error.status === 0 ? "实时数据网络同步中断，系统会自动重试" : `${error.message}；系统会自动重试`, "error");
    }
  } finally {
    adminState.loading = false;
  }
}

function startAdminPolling() {
  clearInterval(adminState.pollTimer);
  adminState.pollTimer = setInterval(() => {
    if (adminState.currentView === "overview" && !document.hidden) loadDashboard({ quiet: true });
  }, 1000);
  clearInterval(adminState.boardPageTimer);
  adminState.boardPageTimer = setInterval(() => {
    adminEls.boardClock.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
    if (adminState.currentView !== "overview" || document.hidden || !adminState.dashboard) return;
    adminState.boardPages.groups += 1;
    renderGroupProgress(adminState.dashboard.groups || []);
  }, 5000);
  adminEls.boardClock.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
}

function renderDashboard(data) {
  synchronizeServerClock(data);
  const phase = dashboardPhase(data);
  const displayMode = boardDisplayMode(data, phase);
  const structureLocked = phase === "countdown" || phase === "open" || data.settings.status === "open";
  const presence = normalizedPresence(data);
  const activityId = Number(data.settings.activity_id);
  if (adminState.lastActivityId !== null && adminState.lastActivityId !== activityId) {
    for (const timer of adminState.activationHideTimers.values()) clearTimeout(timer);
    adminState.activationHideTimers.clear();
    adminState.revealedActivationCodes.clear();
    scrubRevealedActivationCodeDom();
    stopRosterAutoScroll();
    stopLiveFeedAutoScroll();
    adminState.rosterFingerprint = "";
    adminState.liveFeedFingerprint = "";
  }
  adminState.lastActivityId = activityId;
  const rate = data.totals.students ? Math.round((data.totals.selected / data.totals.students) * 100) : 0;
  adminEls.title.textContent = data.settings.activity_title;
  adminEls.boardActivityTitle.textContent = data.settings.activity_title;
  adminEls.boardClock.textContent = new Date().toLocaleTimeString("zh-CN", { hour12: false });
  document.title = `${data.settings.activity_title} · 管理端`;
  adminEls.selected.textContent = String(data.totals.selected);
  adminEls.unselected.textContent = String(data.totals.unselected);
  const waitingRate = data.totals.students ? Math.round((presence.online / data.totals.students) * 100) : 0;
  adminEls.waitingOnline.textContent = String(presence.online);
  adminEls.waitingAbsent.textContent = String(presence.absent);
  adminEls.waitingRate.textContent = `${waitingRate}%`;
  adminEls.waitingRateBar.style.width = `${waitingRate}%`;
  adminEls.rate.textContent = `${rate}%`;
  adminEls.rateBar.style.width = `${rate}%`;
  const badgeLabels = { waiting: "候场中", countdown: "倒计时", open: "进行中", closed: "已关闭" };
  adminEls.boardHeaderPhase.textContent = badgeLabels[phase];
  adminEls.statusBadge.className = `status-badge status-badge--${phase === "open" ? "open" : phase === "countdown" ? "countdown" : "closed"}`;
  adminEls.statusBadge.textContent = badgeLabels[phase];
  renderReadiness(data.readiness, structureLocked);
  renderBoardStage(data, phase, presence);
  liveBoard.dataset.displayMode = displayMode;
  liveBoard.classList.toggle("phase-waiting", displayMode === "waiting");
  liveBoard.classList.toggle("phase-selection", displayMode === "selection");
  liveBoard.classList.toggle("phase-countdown", displayMode === "countdown");
  adminEls.statsTitle.textContent = displayMode === "waiting" ? "候场进度" : "各教学组抢选进度";
  adminEls.boardRosterHeading.textContent = displayMode === "waiting" ? "候场学生情况" : "当前抢选进度";

  const activityQuery = `activity_id=${encodeURIComponent(data.settings.activity_id)}`;
  adminEls.exportSelections.href = `/api/admin/export/selections.csv?${activityQuery}`;
  adminEls.exportCompleteResults.href = `/api/admin/export/results.xlsx?${activityQuery}`;
  const complete = Number(data.totals.students) > 0 && Number(data.totals.unselected) === 0;
  adminEls.exportCompleteResults.classList.toggle("is-complete", complete);
  adminEls.exportCompleteResults.textContent = complete ? "全部完成 · 导出本场完整结果 Excel" : "导出本场完整结果 Excel";
  adminEls.exportCompletionCallout.classList.toggle("is-hidden", !complete);
  adminEls.exportUnselected.href = `/api/admin/export/unselected.csv?${activityQuery}`;
  if (adminState.currentView === "overview") {
    renderGroupProgress(data.groups);
    renderLiveSelectionFeed(data.recent_selections || []);
    renderQr(data.settings.public_base_url);
    renderUnselectedList();
    if (Date.now() - adminState.recentRenderedAt >= 5000) {
      renderRecentSelections(data.recent_selections);
      adminEls.recentBody.dataset.activityId = String(data.settings.activity_id);
      adminState.recentRenderedAt = Date.now();
    }
  } else if (adminState.currentView === "structure") {
    renderStructure(data, structureLocked);
  } else if (adminState.currentView === "students") {
    renderAssignmentTable(data);
    adminEls.assignmentBody.dataset.activityId = String(data.settings.activity_id);
    renderStudentRoster(data);
    adminEls.rosterBody.dataset.activityId = String(data.settings.activity_id);
  } else if (adminState.currentView === "settings") {
    renderActivities(data.activities || []);
    fillSettingsForm(data.settings);
  }
}

function renderBoardStage(data, phase, presence) {
  const total = Number(data.totals?.students || 0);
  const remainingMs = millisecondsUntilSelection(data);
  const remainingSeconds = remainingMs === null ? 10 : Math.max(0, Math.ceil(remainingMs / 1000));
  const readiness = normalizeReadiness(data.readiness);
  adminEls.boardStage.className = `board-stage board-stage--${phase}`;
  adminEls.boardNotice.classList.toggle("is-open", phase === "open");
  adminEls.statusButton.disabled = adminState.phaseActionPending || phase === "countdown";
  adminEls.boardStart.disabled = adminState.phaseActionPending || phase === "countdown" || ((phase === "waiting" || phase === "closed") && !readiness.ready);

  if (phase === "countdown") {
    adminEls.boardStageLabel.textContent = "全体同步倒计时";
    adminEls.boardCountdown.textContent = String(remainingSeconds);
    adminEls.boardOverlayCountdown.textContent = String(remainingSeconds);
    adminEls.boardStageDetail.textContent = `已进入候场 ${presence.online} / ${total} 人，倒计时结束后同时进入抢选`;
    adminEls.boardStatus.textContent = "倒计时正在同步到全部学生端";
    adminEls.boardLiveNote.textContent = "请保持大屏与学生手机页面打开";
    adminEls.statusButton.textContent = `倒计时 ${remainingSeconds} 秒`;
    adminEls.statusButton.className = "button button--primary";
    adminEls.boardStart.textContent = `倒计时 ${remainingSeconds} 秒`;
    adminEls.boardStart.className = "button button--primary button--wide";
    return;
  }

  if (phase === "open") {
    adminEls.boardStageLabel.textContent = "抢选进行中";
    adminEls.boardCountdown.textContent = "LIVE";
    adminEls.boardStageDetail.textContent = `已完成 ${data.totals.selected} / ${total} 人，名额与名单每秒自动同步`;
    adminEls.boardStatus.textContent = "抢选正在进行，扫码仍可登录";
    adminEls.boardLiveNote.textContent = "扫码仍可登录 · 名额与名单实时更新";
    adminEls.statusButton.textContent = "关闭抢选";
    adminEls.statusButton.className = "button button--secondary";
    adminEls.boardStart.textContent = "关闭抢选";
    adminEls.boardStart.className = "button button--secondary button--wide";
    return;
  }

  const isClosed = phase === "closed";
  adminEls.boardStageLabel.textContent = isClosed ? "抢选已关闭" : "扫码候场中";
  adminEls.boardCountdown.textContent = "READY";
  adminEls.boardStageDetail.textContent = `已进入候场 ${presence.online} / ${total} 人，尚未进入 ${presence.absent} 人`;
  adminEls.boardStatus.textContent = isClosed ? "当前不可提交，可再次发起统一倒计时" : "候场数据实时更新";
  adminEls.boardLiveNote.textContent = "扫码入口持续开放，页面自动同步";
  adminEls.statusButton.textContent = "开始 10 秒倒计时";
  adminEls.statusButton.className = "button button--primary";
  adminEls.boardStart.textContent = readiness.ready ? "开始 10 秒倒计时" : "就绪检查未通过";
  adminEls.boardStart.className = "button button--primary button--wide";
}

function normalizeReadiness(readiness) {
  if (!readiness) {
    return {
      ready: false,
      blockers: ["服务尚未返回开放就绪检查，请刷新页面后重试。"],
      warnings: [],
    };
  }
  const blockers = Array.isArray(readiness.blockers) ? [...readiness.blockers] : [];
  const warnings = Array.isArray(readiness.warnings) ? [...readiness.warnings] : [];
  if (!readiness.ready && blockers.length === 0) blockers.push("就绪检查未通过，但服务未返回具体原因。请刷新后重试。");
  return { ready: Boolean(readiness.ready) && blockers.length === 0, blockers, warnings };
}

function renderReadiness(readiness, open) {
  adminEls.readinessPanel.classList.toggle("is-hidden", open);
  if (open) return;
  const { ready, blockers, warnings } = normalizeReadiness(readiness);
  adminEls.readinessPanel.className = `readiness-panel ${ready ? (warnings.length ? "is-warning" : "is-ready") : "is-blocked"}`;
  adminEls.readinessIcon.textContent = ready ? (warnings.length ? "!" : "✓") : "×";
  adminEls.readinessSummary.textContent = ready
    ? warnings.length
      ? `已具备开放条件，仍有 ${warnings.length} 项提醒需要确认。`
      : "名单、专业、教学组和配额检查均已通过，可以开放抢选。"
    : `暂不能开放抢选，请先处理 ${blockers.length || 1} 项阻止问题。`;
  const items = [];
  for (const message of blockers) {
    const item = document.createElement("li");
    item.className = "is-blocker";
    item.textContent = message;
    items.push(item);
  }
  for (const message of warnings) {
    const item = document.createElement("li");
    item.className = "is-warning";
    item.textContent = message;
    items.push(item);
  }
  adminEls.readinessDetails.replaceChildren(...items);
}

function renderActivities(activities) {
  adminEls.activityCount.textContent = `${activities.length} 场`;
  const statusLabels = { open: "进行中", closed: "已关闭", archived: "已归档" };
  const rows = activities.map((activity) => {
    const row = document.createElement("article");
    row.className = `activity-row${activity.current ? " is-current" : ""}`;
    const info = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = activity.title;
    const summary = activity.summary || { students: 0, selected: 0, unselected: 0 };
    const detail = document.createElement("small");
    detail.textContent = `${activity.code} · 名单 ${summary.students || 0} 人 · 已选 ${summary.selected || 0} 人`;
    info.append(title, detail);
    const meta = document.createElement("div");
    meta.className = "activity-row__meta";
    const status = document.createElement("span");
    status.className = `activity-row__status${activity.status === "open" ? " is-open" : ""}${activity.current ? " is-current" : ""}`;
    status.textContent = activity.current ? `当前 · ${statusLabels[activity.status]}` : statusLabels[activity.status];
    meta.append(status);
    if (activity.status === "archived") {
      const download = document.createElement("a");
      download.href = `/api/admin/activities/${activity.id}/archive.json`;
      download.textContent = "下载归档";
      download.title = activity.snapshot_sha256 ? `SHA-256：${activity.snapshot_sha256}` : "下载活动归档";
      const remove = document.createElement("button");
      remove.type = "button";
      remove.className = "button button--danger activity-delete";
      remove.dataset.action = "delete-archive";
      remove.dataset.activityId = String(activity.id);
      remove.dataset.activityTitle = activity.title;
      remove.textContent = "删除";
      remove.title = "永久删除该历史归档（需要二次确认）";
      meta.append(download, remove);
    }
    row.append(info, meta);
    return row;
  });
  adminEls.activityList.replaceChildren(...rows);
  const current = activities.find((activity) => activity.current);
  const disabled = current?.status === "open";
  adminEls.newActivityForm.querySelectorAll("input, button").forEach((element) => { element.disabled = disabled; });
}

adminEls.activityList.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action=delete-archive]");
  if (!button) return;
  const targetActivityId = Number(button.dataset.activityId);
  const title = button.dataset.activityTitle || "该活动";
  if (!await confirmDanger("删除历史归档", `即将删除“${title}”。删除后管理端不再保留该场活动的归档快照，请先确认已经下载并妥善保存。`)) return;
  if (!await confirmDanger("再次确认永久删除", `这是最后一次确认：确定永久删除“${title}”吗？此操作不可撤销。`)) return;
  button.disabled = true;
  try {
    await adminApi(`/api/admin/activities/${targetActivityId}`, {
      method: "DELETE",
      body: JSON.stringify({ confirmation: "DELETE" }),
      activityId: adminState.dashboard?.settings.activity_id,
    });
    showAdminToast("历史归档已删除", "success");
    await loadDashboard();
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

function renderGroupProgress(groups) {
  const activeGroups = groups.filter((group) => group.active);
  const page = boardPage(activeGroups, "groups");
  adminEls.groupProgressPage.textContent = page.pages > 1 ? `第 ${page.index + 1} / ${page.pages} 页` : activeGroups.length ? "实时更新" : "";
  if (!activeGroups.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "尚未启用教学组";
    adminEls.groupProgress.replaceChildren(empty);
    return;
  }
  const elements = page.items.map((group) => {
    const wrapper = document.createElement("div");
    wrapper.className = "group-progress__row";
    const label = document.createElement("div");
    label.className = "group-progress__label";
    const name = document.createElement("span");
    name.textContent = group.name;
    const count = document.createElement("strong");
    count.textContent = `${group.selected_count}/${group.total_capacity}`;
    label.append(name, count);
    const track = document.createElement("div");
    track.className = "group-progress__track";
    const fill = document.createElement("span");
    fill.style.width = `${group.total_capacity ? Math.min(100, (group.selected_count / group.total_capacity) * 100) : 100}%`;
    track.append(fill);
    wrapper.append(label, track);
    return wrapper;
  });
  adminEls.groupProgress.replaceChildren(...elements);
}

function captureLiveFeedScrollRatio() {
  const list = adminEls.liveSelectionFeed;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  if (loopHeight > 0) return (list.scrollTop % loopHeight) / loopHeight;
  const max = Math.max(0, list.scrollHeight - list.clientHeight);
  return max > 0 ? list.scrollTop / max : 0;
}

function restoreLiveFeedScrollRatio(ratio) {
  const list = adminEls.liveSelectionFeed;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  const max = loopHeight > 0 ? loopHeight - 1 : Math.max(0, list.scrollHeight - list.clientHeight);
  list.scrollTop = Math.min(max, Math.max(0, ratio * max));
}

function stopLiveFeedAutoScroll() {
  if (adminState.liveFeedScrollFrame) cancelAnimationFrame(adminState.liveFeedScrollFrame);
  if (adminState.liveFeedLoopSetupFrame) cancelAnimationFrame(adminState.liveFeedLoopSetupFrame);
  adminState.liveFeedScrollFrame = null;
  adminState.liveFeedLoopSetupFrame = null;
  adminState.liveFeedScrollLastTime = 0;
}

function startLiveFeedAutoScroll() {
  stopLiveFeedAutoScroll();
  if (reducedMotionPreference.matches) return;
  const loopHeight = Number(adminEls.liveSelectionFeed.dataset.loopHeight || 0);
  if (loopHeight <= 0) return;
  const tick = (now) => {
    if (document.hidden || adminState.currentView !== "overview") {
      stopLiveFeedAutoScroll();
      return;
    }
    const list = adminEls.liveSelectionFeed;
    const cycleHeight = Number(list.dataset.loopHeight || 0);
    if (cycleHeight > 0) {
      const elapsed = adminState.liveFeedScrollLastTime ? Math.min(80, now - adminState.liveFeedScrollLastTime) : 0;
      const next = list.scrollTop + elapsed * 0.022;
      list.scrollTop = next >= cycleHeight ? next - cycleHeight : next;
    }
    adminState.liveFeedScrollLastTime = now;
    adminState.liveFeedScrollFrame = requestAnimationFrame(tick);
  };
  adminState.liveFeedScrollFrame = requestAnimationFrame(tick);
}

function setupLiveFeedLoop(previousScrollRatio) {
  if (adminState.liveFeedLoopSetupFrame) cancelAnimationFrame(adminState.liveFeedLoopSetupFrame);
  adminState.liveFeedLoopSetupFrame = requestAnimationFrame(() => {
    adminState.liveFeedLoopSetupFrame = null;
    const list = adminEls.liveSelectionFeed;
    list.querySelectorAll("[data-feed-clone]").forEach((clone) => clone.remove());
    delete list.dataset.loopHeight;
    list.scrollTop = 0;
    const originals = [...list.children];
    const canLoop = originals.length > 1 && list.scrollHeight > list.clientHeight + 4;
    adminEls.liveFeedState.textContent = canLoop && !reducedMotionPreference.matches ? "连续滚动" : originals.length ? "实时更新" : "";
    if (!canLoop || reducedMotionPreference.matches) {
      restoreLiveFeedScrollRatio(previousScrollRatio);
      stopLiveFeedAutoScroll();
      return;
    }
    const firstTop = originals[0].offsetTop;
    const clones = originals.map((item) => {
      const clone = item.cloneNode(true);
      clone.dataset.feedClone = "true";
      clone.setAttribute("aria-hidden", "true");
      return clone;
    });
    list.append(...clones);
    const loopHeight = clones[0].offsetTop - firstTop;
    if (loopHeight <= 0) return;
    list.dataset.loopHeight = String(loopHeight);
    restoreLiveFeedScrollRatio(previousScrollRatio);
    startLiveFeedAutoScroll();
  });
}

function renderLiveSelectionFeed(rows, { force = false } = {}) {
  const recentRows = rows.slice(0, 20);
  const fingerprint = JSON.stringify([
    boardDisplayMode(),
    ...recentRows.map((record) => [
      record.student_id,
      record.name,
      record.major_name,
      record.group_name,
      record.selected_at,
    ]),
  ]);
  if (!force && adminState.liveFeedFingerprint === fingerprint) return;
  const previousScrollRatio = captureLiveFeedScrollRatio();
  adminState.liveFeedFingerprint = fingerprint;
  stopLiveFeedAutoScroll();
  const items = recentRows.map((record) => {
    const item = document.createElement("article");
    item.className = "selection-feed-item";
    const marker = document.createElement("span");
    marker.className = "selection-feed-item__marker";
    marker.textContent = "✓";
    const detail = document.createElement("div");
    const title = document.createElement("strong");
    title.textContent = `${record.name} → ${record.group_name}`;
    const meta = document.createElement("small");
    meta.textContent = `${record.major_name} · ${formatAdminTime(record.selected_at)}`;
    detail.append(title, meta);
    item.append(marker, detail);
    return item;
  });
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "selection-feed-empty";
    empty.textContent = "等待第一条选择记录";
    items.push(empty);
  }
  adminEls.liveSelectionFeed.replaceChildren(...items);
  setupLiveFeedLoop(previousScrollRatio);
}

function renderQr(publicUrl) {
  adminEls.publicUrl.textContent = publicUrl || "尚未设置访问地址";
  if (publicUrl) {
    adminEls.qr.classList.remove("is-hidden");
    adminEls.qrPlaceholder.classList.add("is-hidden");
    const nextSrc = `/api/admin/qr.png?v=${encodeURIComponent(publicUrl)}`;
    if (!adminEls.qr.src.endsWith(nextSrc)) adminEls.qr.src = nextSrc;
    adminEls.qr.onerror = () => {
      adminEls.qr.classList.add("is-hidden");
      adminEls.qrPlaceholder.classList.remove("is-hidden");
      adminEls.qrPlaceholder.textContent = "二维码生成失败，请检查访问地址";
    };
  } else {
    adminEls.qr.removeAttribute("src");
    adminEls.qr.classList.add("is-hidden");
    adminEls.qrPlaceholder.classList.remove("is-hidden");
    adminEls.qrPlaceholder.textContent = "请先在系统设置中填写学生端访问地址";
  }
}

function filteredUnselectedStudents() {
  const all = boardStudentListData();
  const query = boardIsPresentation() ? "" : adminEls.unselectedSearch.value.trim().toLowerCase();
  if (!query) return all;
  return all.filter((student) => [student.student_no, student.name, student.major_name].some((value) => String(value).toLowerCase().includes(query)));
}

function boardStudentListData() {
  const mode = boardDisplayMode();
  if (["waiting", "countdown"].includes(mode)) return normalizedPresence().absentStudents;
  return adminState.dashboard?.unselected_students || [];
}

function captureRosterScrollRatio() {
  const list = adminEls.unselectedList;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  if (loopHeight > 0) return (list.scrollTop % loopHeight) / loopHeight;
  const max = Math.max(0, list.scrollHeight - list.clientHeight);
  return max > 0 ? list.scrollTop / max : 0;
}

function restoreRosterScrollRatio(ratio) {
  const list = adminEls.unselectedList;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  if (loopHeight > 0) {
    list.scrollTop = Math.min(loopHeight - 1, Math.max(0, ratio * loopHeight));
    return;
  }
  const max = Math.max(0, list.scrollHeight - list.clientHeight);
  list.scrollTop = Math.min(max, Math.max(0, ratio * max));
}

function stopRosterAutoScroll() {
  if (adminState.rosterScrollFrame) cancelAnimationFrame(adminState.rosterScrollFrame);
  if (adminState.rosterLoopSetupFrame) cancelAnimationFrame(adminState.rosterLoopSetupFrame);
  adminState.rosterScrollFrame = null;
  adminState.rosterLoopSetupFrame = null;
  adminState.rosterScrollLastTime = 0;
}

function startRosterAutoScroll() {
  if (adminState.rosterScrollFrame) cancelAnimationFrame(adminState.rosterScrollFrame);
  adminState.rosterScrollFrame = null;
  adminState.rosterScrollLastTime = 0;
  if (reducedMotionPreference.matches) return;
  const loopHeight = Number(adminEls.unselectedList.dataset.loopHeight || 0);
  if (loopHeight <= 0) return;
  const tick = (now) => {
    if (document.hidden || adminState.currentView !== "overview") {
      stopRosterAutoScroll();
      return;
    }
    const list = adminEls.unselectedList;
    const cycleHeight = Number(list.dataset.loopHeight || 0);
    if (cycleHeight > 0) {
      const elapsed = adminState.rosterScrollLastTime ? Math.min(80, now - adminState.rosterScrollLastTime) : 0;
      const next = list.scrollTop + elapsed * 0.018;
      list.scrollTop = next >= cycleHeight ? next - cycleHeight : next;
    }
    adminState.rosterScrollLastTime = now;
    adminState.rosterScrollFrame = requestAnimationFrame(tick);
  };
  adminState.rosterScrollFrame = requestAnimationFrame(tick);
}

function setupRosterLoop(previousScrollRatio) {
  if (adminState.rosterLoopSetupFrame) cancelAnimationFrame(adminState.rosterLoopSetupFrame);
  adminState.rosterLoopSetupFrame = requestAnimationFrame(() => {
    adminState.rosterLoopSetupFrame = null;
    const list = adminEls.unselectedList;
    list.querySelectorAll("[data-roster-clone]").forEach((clone) => clone.remove());
    delete list.dataset.loopHeight;
    list.scrollTop = 0;
    const originals = [...list.children];
    const canLoop = originals.length > 1 && list.scrollHeight > list.clientHeight + 4;
    adminEls.unselectedPage.textContent = canLoop && !reducedMotionPreference.matches
      ? "连续滚动"
      : originals.length ? "实时更新" : "";
    if (!canLoop || reducedMotionPreference.matches) {
      restoreRosterScrollRatio(previousScrollRatio);
      stopRosterAutoScroll();
      return;
    }
    const firstTop = originals[0].offsetTop;
    const clones = originals.map((item) => {
      const clone = item.cloneNode(true);
      clone.dataset.rosterClone = "true";
      clone.setAttribute("aria-hidden", "true");
      return clone;
    });
    list.append(...clones);
    const loopHeight = clones[0].offsetTop - firstTop;
    if (loopHeight <= 0) return;
    list.dataset.loopHeight = String(loopHeight);
    restoreRosterScrollRatio(previousScrollRatio);
    startRosterAutoScroll();
  });
}

function renderUnselectedList({ force = false } = {}) {
  const mode = boardDisplayMode();
  const isCheckIn = ["waiting", "countdown"].includes(mode);
  const all = boardStudentListData();
  const filtered = filteredUnselectedStudents();
  const previousScrollRatio = captureRosterScrollRatio();
  const visibleStudents = filtered;
  adminEls.studentListKicker.textContent = isCheckIn ? "CHECK-IN LIST" : "WAITING LIST";
  adminEls.unselectedTitle.textContent = isCheckIn ? "尚未进入候场" : "当前未选学生";
  adminEls.unselectedCount.textContent = `${all.length} 人`;
  adminEls.unselectedPage.textContent = visibleStudents.length ? "实时更新" : "";
  const fingerprint = JSON.stringify([
    mode,
    adminEls.unselectedSearch.value.trim().toLowerCase(),
    ...visibleStudents.map((student) => [student.id, student.name, student.major_name]),
  ]);
  if (!force && adminState.rosterFingerprint === fingerprint) return;
  adminState.rosterFingerprint = fingerprint;
  stopRosterAutoScroll();
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = all.length
      ? "没有匹配的学生"
      : isCheckIn
        ? "全部学生均已进入候场"
        : "所有学生都已完成选择";
    adminEls.unselectedList.replaceChildren(empty);
    stopRosterAutoScroll();
    return;
  }
  const items = visibleStudents.map((student, index) => {
    const item = document.createElement("article");
    item.className = "student-list-item";
    const ordinal = document.createElement("span");
    ordinal.className = "student-list-item__index";
    ordinal.textContent = String(index + 1);
    const info = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = student.name;
    const major = document.createElement("small");
    major.textContent = student.major_name;
    info.append(name, major);
    item.append(ordinal, info);
    return item;
  });
  adminEls.unselectedList.replaceChildren(...items);
  setupRosterLoop(previousScrollRatio);
}

function renderRecentSelections(rows) {
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = createCell("尚无选择记录");
    cell.colSpan = 6;
    cell.className = "empty-state";
    row.append(cell);
    adminEls.recentBody.replaceChildren(row);
    return;
  }
  const elements = rows.map((record) => {
    const row = document.createElement("tr");
    const student = document.createElement("td");
    const name = document.createElement("strong");
    name.textContent = record.name;
    const no = document.createElement("small");
    no.textContent = record.student_no;
    student.append(name, document.createElement("br"), no);
    row.append(student, createCell(record.major_name), createCell(record.group_name), createCell(formatAdminTime(record.selected_at)), createCell(record.source === "admin" ? "管理员补位" : "学生提交"));
    const action = document.createElement("td");
    const revoke = document.createElement("button");
    revoke.type = "button";
    revoke.className = "button button--quiet";
    revoke.dataset.action = "revoke-selection";
    revoke.dataset.studentId = String(record.student_id);
    revoke.dataset.studentName = record.name;
    revoke.textContent = "撤销";
    action.append(revoke);
    row.append(action);
    return row;
  });
  adminEls.recentBody.replaceChildren(...elements);
}

function makeEntityStatus(active, disabled, action) {
  const wrapper = document.createElement("div");
  wrapper.className = "entity-status-control";
  const badge = document.createElement("span");
  badge.className = `entity-status ${active ? "is-active" : "is-inactive"}`;
  badge.textContent = active ? "使用中" : "已停用";
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.action = action;
  button.dataset.nextActive = String(!active);
  button.className = "button button--quiet entity-status-action";
  button.textContent = active ? "停用" : "重新启用";
  button.disabled = disabled;
  wrapper.append(badge, button);
  return wrapper;
}

function makeIconButton(action, text, title, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.dataset.action = action;
  button.className = `icon-button${danger ? " icon-button--danger" : ""}`;
  button.title = title;
  button.setAttribute("aria-label", title);
  button.textContent = text;
  return button;
}

function renderMajorEditor(majors, locked) {
  const rows = majors.map((major) => {
    const row = document.createElement("div");
    row.className = "entity-row";
    row.dataset.id = String(major.id);
    const drag = document.createElement("span");
    drag.className = "entity-row__drag";
    drag.textContent = "⋮⋮";
    const name = document.createElement("input");
    name.value = major.name;
    name.maxLength = 80;
    name.disabled = locked;
    name.setAttribute("aria-label", "专业名称");
    const status = makeEntityStatus(major.active, locked, "toggle-major-status");
    const save = makeIconButton("save-major", "✓", "保存专业");
    const remove = makeIconButton("delete-major", "×", "删除专业", true);
    save.disabled = locked;
    remove.disabled = locked;
    row.append(drag, name, status, save, remove);
    row._nameInput = name;
    row.dataset.active = String(Boolean(major.active));
    return row;
  });
  adminEls.majorEditor.replaceChildren(...rows);
}

function renderGroupEditor(groups, locked) {
  const rows = groups.map((group) => {
    const row = document.createElement("div");
    row.className = "entity-row entity-row--group";
    row.dataset.id = String(group.id);
    const drag = document.createElement("span");
    drag.className = "entity-row__drag";
    drag.textContent = "⋮⋮";
    const name = document.createElement("input");
    name.value = group.name;
    name.maxLength = 80;
    name.disabled = locked;
    name.setAttribute("aria-label", "教学组名称");
    const capacityWrap = document.createElement("label");
    capacityWrap.className = "entity-row__capacity";
    const capacity = document.createElement("input");
    capacity.type = "number";
    capacity.min = "0";
    capacity.max = "1000";
    capacity.value = String(group.total_capacity);
    capacity.disabled = locked;
    capacity.setAttribute("aria-label", "教学组总容量");
    capacityWrap.append(capacity);
    const status = makeEntityStatus(group.active, locked, "toggle-group-status");
    const save = makeIconButton("save-group", "✓", "保存教学组");
    const remove = makeIconButton("delete-group", "×", "删除教学组", true);
    save.disabled = locked;
    remove.disabled = locked;
    row.append(drag, name, capacityWrap, status, save, remove);
    row._nameInput = name;
    row._capacityInput = capacity;
    row.dataset.active = String(Boolean(group.active));
    return row;
  });
  adminEls.groupEditor.replaceChildren(...rows);
}

function renderQuotaMatrix(data, locked) {
  const table = document.createElement("table");
  table.className = "quota-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.textContent = "专业 / 教学组";
  headRow.append(corner);
  for (const group of data.groups) {
    const th = document.createElement("th");
    th.textContent = `${group.name}（总 ${group.total_capacity}）`;
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  const quotaMap = new Map(data.quotas.map((quota) => [`${quota.major_id}:${quota.group_id}`, quota]));
  for (const major of data.majors) {
    const row = document.createElement("tr");
    const majorCell = document.createElement("td");
    majorCell.textContent = major.name;
    row.append(majorCell);
    for (const group of data.groups) {
      const cell = document.createElement("td");
      const quota = quotaMap.get(`${major.id}:${group.id}`) || { capacity: 0, selected_count: 0 };
      const wrapper = document.createElement("div");
      wrapper.className = "quota-cell";
      const selected = document.createElement("span");
      selected.textContent = String(quota.selected_count);
      const slash = document.createTextNode("/");
      const input = document.createElement("input");
      input.type = "number";
      input.min = "0";
      input.max = "1000";
      input.value = String(quota.capacity);
      input.disabled = locked || !major.active || !group.active;
      input.dataset.majorId = String(major.id);
      input.dataset.groupId = String(group.id);
      input.dataset.original = String(quota.capacity);
      input.setAttribute("aria-label", `${major.name}分配到${group.name}的配额`);
      wrapper.append(selected, slash, input);
      cell.append(wrapper);
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  adminEls.quotaMatrix.replaceChildren(table);
}

function renderStructure(data, locked) {
  adminEls.majorEditor.dataset.activityId = String(data.settings.activity_id);
  adminEls.groupEditor.dataset.activityId = String(data.settings.activity_id);
  adminEls.quotaMatrix.dataset.activityId = String(data.settings.activity_id);
  adminEls.majorCount.textContent = `${data.majors.length} 个专业`;
  adminEls.groupCount.textContent = `${data.groups.length} 个教学组`;
  adminEls.structureLock.textContent = locked ? "抢选开放中 · 已锁定" : "当前可编辑数量和名称";
  adminEls.structureLock.classList.toggle("is-locked", locked);
  document.querySelectorAll("#add-major-form input, #add-major-form button, #add-group-form input, #add-group-form button").forEach((element) => { element.disabled = locked; });
  renderMajorEditor(data.majors, locked);
  renderGroupEditor(data.groups, locked);
  renderQuotaMatrix(data, locked);
}

function quotaRemainingFor(student, group, data) {
  const major = data.majors.find((item) => item.name === student.major_name);
  const quota = data.quotas.find((item) => item.major_id === major?.id && item.group_id === group.id);
  const majorRemaining = quota ? quota.capacity - quota.selected_count : 0;
  const groupRemaining = group.total_capacity - group.selected_count;
  return Math.max(0, Math.min(majorRemaining, groupRemaining));
}

function renderAssignmentTable(data) {
  if (!data.unselected_students.length) {
    const row = document.createElement("tr");
    const cell = createCell("所有学生都已完成选择");
    cell.colSpan = 5;
    cell.className = "empty-state";
    row.append(cell);
    adminEls.assignmentBody.replaceChildren(row);
    return;
  }
  const rows = data.unselected_students.map((student) => {
    const row = document.createElement("tr");
    row.dataset.studentId = String(student.id);
    row.append(createCell(student.student_no), createCell(student.name), createCell(student.major_name));
    const selectCell = document.createElement("td");
    const select = document.createElement("select");
    select.className = "assign-select";
    select.setAttribute("aria-label", `为${student.name}选择教学组`);
    const placeholder = document.createElement("option");
    placeholder.value = "";
    placeholder.textContent = "选择教学组";
    select.append(placeholder);
    for (const group of data.groups.filter((item) => item.active)) {
      const remaining = quotaRemainingFor(student, group, data);
      const option = document.createElement("option");
      option.value = String(group.id);
      option.textContent = `${group.name}（余 ${remaining}）`;
      option.disabled = remaining <= 0;
      select.append(option);
    }
    selectCell.append(select);
    const actionCell = document.createElement("td");
    const assign = document.createElement("button");
    assign.type = "button";
    assign.className = "button button--quiet";
    assign.dataset.action = "assign-student";
    assign.textContent = "补位";
    actionCell.append(assign);
    row.append(selectCell, actionCell);
    row._groupSelect = select;
    return row;
  });
  adminEls.assignmentBody.replaceChildren(...rows);
}

function filteredRosterStudents(students) {
  const query = adminEls.rosterSearch.value.trim().toLowerCase();
  if (!query) return students;
  return students.filter((student) => [
    student.student_no,
    student.name,
    student.major_name,
    student.group_name || "未选择",
    student.active ? "有效" : "已停用",
  ].some((value) => String(value).toLowerCase().includes(query)));
}

function revealedCodeKey(studentId) {
  return `${adminState.dashboard?.settings.activity_id || "current"}:${studentId}`;
}

function clearRevealedActivationCode(studentId) {
  const key = revealedCodeKey(studentId);
  adminState.revealedActivationCodes.delete(key);
  clearTimeout(adminState.activationHideTimers.get(key));
  adminState.activationHideTimers.delete(key);
}

function scrubRevealedActivationCodeDom() {
  adminEls.rosterBody.querySelectorAll(".activation-code-value.is-revealed").forEach((value) => {
    value.textContent = "••••••";
    value.classList.remove("is-revealed");
  });
  adminEls.rosterBody.querySelectorAll("button[data-action=hide-activation-code]").forEach((button) => {
    button.dataset.action = "reveal-activation-code";
    button.textContent = "显示明文";
    button.title = "仅本页显示，60 秒后自动隐藏";
  });
}

function rememberRevealedActivationCode(studentId, code) {
  const key = revealedCodeKey(studentId);
  clearTimeout(adminState.activationHideTimers.get(key));
  adminState.revealedActivationCodes.set(key, code);
  adminState.activationHideTimers.set(key, setTimeout(() => {
    adminState.revealedActivationCodes.delete(key);
    adminState.activationHideTimers.delete(key);
    scrubRevealedActivationCodeDom();
    if (adminState.currentView === "students") renderStudentRoster();
  }, 60_000));
}

function activationCodeFromResponse(result) {
  return result?.activation_code || result?.code || result?.credential?.activation_code || null;
}

function renderStudentRoster(data = adminState.dashboard) {
  const students = Array.isArray(data?.students) ? data.students : [];
  const filtered = filteredRosterStudents(students);
  adminEls.rosterCount.textContent = filtered.length === students.length
    ? `${students.length} 人`
    : `显示 ${filtered.length} / ${students.length} 人`;
  if (!filtered.length) {
    const row = document.createElement("tr");
    const cell = createCell(students.length ? "没有匹配的学生" : "尚未导入学生名单");
    cell.colSpan = 6;
    cell.className = "empty-state";
    row.append(cell);
    adminEls.rosterBody.replaceChildren(row);
    return;
  }
  const rows = filtered.map((student) => {
    const row = document.createElement("tr");
    row.dataset.studentId = String(student.id);
    row.classList.toggle("is-inactive", !student.active);
    row.append(createCell(student.student_no), createCell(student.name), createCell(student.major_name));

    const statusCell = document.createElement("td");
    const status = document.createElement("span");
    status.className = `roster-status ${student.active ? "is-active" : "is-inactive"}`;
    status.textContent = student.active ? "有效" : "已停用";
    statusCell.append(status);

    const selectionCell = document.createElement("td");
    if (student.group_name) {
      const group = document.createElement("strong");
      group.textContent = student.group_name;
      selectionCell.append(group);
      if (student.selected_at) {
        const time = document.createElement("small");
        time.textContent = formatAdminTime(student.selected_at);
        selectionCell.append(document.createElement("br"), time);
      }
    } else {
      selectionCell.textContent = "未选择";
      selectionCell.className = "roster-selection--empty";
    }

    const credentialCell = document.createElement("td");
    const credentialControl = document.createElement("div");
    credentialControl.className = "activation-code-control";
    const value = document.createElement("code");
    value.className = "activation-code-value";
    const key = revealedCodeKey(student.id);
    const revealedCode = adminState.revealedActivationCodes.get(key);
    const revealable = student.activation_code_revealable
      ?? student.activation_code_available
      ?? student.has_recoverable_activation_code
      ?? true;
    value.textContent = revealedCode || (revealable ? "••••••" : "历史码不可显示");
    value.classList.toggle("is-revealed", Boolean(revealedCode));
    const reveal = document.createElement("button");
    reveal.type = "button";
    reveal.className = "button button--quiet";
    reveal.dataset.action = revealedCode ? "hide-activation-code" : "reveal-activation-code";
    reveal.dataset.studentName = student.name;
    reveal.textContent = revealedCode ? "隐藏" : "显示明文";
    reveal.disabled = !revealable;
    reveal.title = revealable
      ? revealedCode ? "立即从页面隐藏" : "仅本页显示，60 秒后自动隐藏"
      : "请在关闭抢选后，重新导入包含证件号的该生名单";
    credentialControl.append(value, reveal);
    credentialCell.append(credentialControl);
    row.append(statusCell, selectionCell, credentialCell);
    return row;
  });
  adminEls.rosterBody.replaceChildren(...rows);
}

function fillSettingsForm(settings) {
  for (const key of ["public_base_url"]) {
    const field = adminEls.settingsForm.elements.namedItem(key);
    if (field && document.activeElement !== field) field.value = settings[key] || "";
  }
}

function switchAdminView(viewName) {
  adminState.currentView = viewName;
  document.querySelectorAll(".admin-nav__item").forEach((button) => button.classList.toggle("is-active", button.dataset.view === viewName));
  document.querySelectorAll(".admin-view").forEach((view) => view.classList.add("is-hidden"));
  document.querySelector(`#view-${viewName}`).classList.remove("is-hidden");
  if (viewName !== "overview") {
    stopRosterAutoScroll();
    stopLiveFeedAutoScroll();
    loadDashboard({ quiet: true });
  } else {
    renderUnselectedList({ force: true });
    renderLiveSelectionFeed(adminState.dashboard?.recent_selections || [], { force: true });
  }
}

document.querySelectorAll(".admin-nav__item").forEach((button) => button.addEventListener("click", () => switchAdminView(button.dataset.view)));

adminEls.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  adminEls.loginError.textContent = "";
  const submit = adminEls.loginForm.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.textContent = "正在登录…";
  try {
    const form = new FormData(adminEls.loginForm);
    const data = await adminApi("/api/admin/login", { method: "POST", body: JSON.stringify(Object.fromEntries(form.entries())) });
    adminState.csrf = data.csrf_token;
    showAdminApp();
    await loadDashboard();
    startAdminPolling();
  } catch (error) {
    adminEls.loginError.textContent = error.message;
  } finally {
    submit.disabled = false;
    submit.textContent = "进入管理平台";
  }
});

document.querySelector("#admin-logout").addEventListener("click", async () => {
  try { await adminApi("/api/admin/logout", { method: "POST", body: JSON.stringify({}) }); } catch (_) { /* clear local view anyway */ }
  adminState.csrf = "";
  showAdminLogin();
});

async function handleSelectionPhaseAction() {
  if (adminState.phaseActionPending || !adminState.dashboard) return;
  const phase = dashboardPhase();
  if (phase === "countdown") return;
  const activityId = adminState.dashboard?.settings.activity_id;
  const readiness = normalizeReadiness(adminState.dashboard?.readiness);
  if (phase !== "open" && !readiness.ready) {
    adminEls.readinessPanel.scrollIntoView({ behavior: "smooth", block: "center" });
    showAdminToast(`暂不能开始：${readiness.blockers.join("；")}`, "error");
    return;
  }
  const readinessMessage = readiness.warnings.length
    ? `就绪检查已通过。仍有提醒：${readiness.warnings.join("；")}。`
    : "就绪检查已通过。";
  const presence = normalizedPresence();
  const absentStudents = presence.absentStudents || [];
  const absentDetail = absentStudents.map((student) => `${student.name}（${student.major_name}）`).join("、");
  const startMessage = presence.absent > 0
    ? `${readinessMessage}\n\n还有 ${presence.absent} 名同学未进入候场：\n${absentDetail || "名单正在同步，请以右侧实时名单为准"}\n\n仍可继续开始。确认后，全体学生端将同步进入 10 秒倒计时，倒计时结束后同时开放提交。`
    : `${readinessMessage}全部 ${presence.online} 名同学均已进入候场。确认后，全体学生端将同步进入 10 秒倒计时，倒计时结束后同时开放提交。`;
  const confirmed = await confirmDanger(
    phase === "open" ? "关闭学生抢选" : "开始全体 10 秒倒计时",
    phase === "open"
      ? "关闭后学生无法继续提交，管理员仍可补位和撤销。"
      : startMessage,
  );
  if (!confirmed) return;
  adminState.phaseActionPending = true;
  adminEls.statusButton.disabled = true;
  adminEls.boardStart.disabled = true;
  try {
    if (phase === "open") {
      await adminApi("/api/admin/status", {
        method: "POST",
        body: JSON.stringify({ status: "closed" }),
        activityId,
      });
    } else {
      await adminApi("/api/admin/countdown", {
        method: "POST",
        body: JSON.stringify({}),
        activityId,
      });
    }
    showAdminToast(phase === "open" ? "抢选已关闭" : "10 秒同步倒计时已开始", "success");
    await loadDashboard();
  } catch (error) {
    showAdminToast(error.message, "error");
  } finally {
    adminState.phaseActionPending = false;
    if (adminState.dashboard) renderBoardStage(adminState.dashboard, dashboardPhase(), normalizedPresence());
  }
}

adminEls.statusButton.addEventListener("click", handleSelectionPhaseAction);
adminEls.boardStart.addEventListener("click", handleSelectionPhaseAction);

adminEls.unselectedSearch.addEventListener("input", renderUnselectedList);
adminEls.rosterSearch.addEventListener("input", () => renderStudentRoster());

const liveBoard = document.querySelector("#live-board");
const fullscreenButton = document.querySelector("#fullscreen-board");
const reducedMotionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
reducedMotionPreference.addEventListener?.("change", () => {
  if (adminState.dashboard && adminState.currentView === "overview") {
    renderUnselectedList({ force: true });
    renderLiveSelectionFeed(adminState.dashboard.recent_selections || [], { force: true });
  }
});

function leavePresentationMode() {
  liveBoard.classList.remove("is-presentation");
  document.body.classList.remove("is-presentation");
  stopRosterAutoScroll();
  stopLiveFeedAutoScroll();
}

function updateFullscreenButton() {
  fullscreenButton.textContent = document.fullscreenElement || liveBoard.classList.contains("is-presentation") ? "退出全屏" : "⛶ 全屏展示";
  if (adminState.dashboard) {
    renderGroupProgress(adminState.dashboard.groups || []);
    renderLiveSelectionFeed(adminState.dashboard.recent_selections || [], { force: true });
    renderUnselectedList({ force: true });
  }
}

async function exitBoardFullscreen() {
  if (document.fullscreenElement) await document.exitFullscreen();
  else leavePresentationMode();
  updateFullscreenButton();
}

fullscreenButton.addEventListener("click", async () => {
  try {
    if (document.fullscreenElement) {
      await document.exitFullscreen();
    } else if (liveBoard.classList.contains("is-presentation")) {
      leavePresentationMode();
    } else {
      await liveBoard.requestFullscreen();
    }
  } catch (_) {
    liveBoard.classList.add("is-presentation");
    document.body.classList.add("is-presentation");
    showAdminToast("浏览器未授予原生全屏，已切换为页面大屏模式", "success");
  }
  updateFullscreenButton();
});

document.addEventListener("fullscreenchange", () => {
  if (document.fullscreenElement) leavePresentationMode();
  updateFullscreenButton();
});

adminEls.boardExitFullscreen.addEventListener("click", () => {
  exitBoardFullscreen().catch(() => leavePresentationMode());
});

document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && liveBoard.classList.contains("is-presentation")) {
    leavePresentationMode();
    updateFullscreenButton();
  }
});

for (const form of document.querySelectorAll(
  "#add-major-form, #add-group-form, #settings-form, #new-activity-form, #student-import-form",
)) {
  form.addEventListener("focusin", () => {
    if (!form.dataset.activityId && adminState.dashboard?.settings.activity_id) {
      form.dataset.activityId = String(adminState.dashboard.settings.activity_id);
    }
  });
}

document.querySelector("#add-major-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const input = event.currentTarget.elements.namedItem("name");
  const activityId = Number(form.dataset.activityId || adminState.dashboard.settings.activity_id);
  try {
    await adminApi("/api/admin/majors", {
      method: "POST",
      body: JSON.stringify({ name: input.value }),
      activityId,
    });
    input.value = "";
    delete form.dataset.activityId;
    showAdminToast("专业已新增，配额矩阵已自动扩展", "success");
    await loadDashboard();
  } catch (error) { showAdminToast(error.message, "error"); }
});

document.querySelector("#add-group-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const activityId = Number(form.dataset.activityId || adminState.dashboard.settings.activity_id);
  try {
    await adminApi("/api/admin/groups", {
      method: "POST",
      body: JSON.stringify({ name: form.elements.namedItem("name").value, total_capacity: Number(form.elements.namedItem("capacity").value) }),
      activityId,
    });
    form.elements.namedItem("name").value = "";
    delete form.dataset.activityId;
    showAdminToast("教学组已新增，所有专业已自动补齐零配额", "success");
    await loadDashboard();
  } catch (error) { showAdminToast(error.message, "error"); }
});

adminEls.majorEditor.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest(".entity-row");
  const id = Number(row.dataset.id);
  const activityId = Number(adminEls.majorEditor.dataset.activityId);
  try {
    if (button.dataset.action === "save-major") {
      await adminApi(`/api/admin/majors/${id}`, { method: "PATCH", body: JSON.stringify({ name: row._nameInput.value }), activityId });
      showAdminToast("专业名称已保存", "success");
    } else if (button.dataset.action === "toggle-major-status") {
      const nextActive = button.dataset.nextActive === "true";
      const actionName = nextActive ? "重新启用专业" : "停用专业";
      const actionMessage = nextActive
        ? `确认重新启用“${row._nameInput.value}”？启用后请检查该专业在各教学组的配额。`
        : `确认停用“${row._nameInput.value}”？历史记录不会删除，但该专业将不再参与本场抢选；有在册学生时系统会阻止操作。`;
      if (!await confirmDanger(actionName, actionMessage)) return;
      button.disabled = true;
      await adminApi(`/api/admin/majors/${id}`, { method: "PATCH", body: JSON.stringify({ active: nextActive }), activityId });
      showAdminToast(nextActive ? "专业已重新启用" : "专业已停用，历史记录仍保留", "success");
    } else if (button.dataset.action === "delete-major") {
      if (!await confirmDanger("删除专业", `确认删除“${row._nameInput.value}”？已有学生时系统会阻止删除。`)) return;
      await adminApi(`/api/admin/majors/${id}`, { method: "DELETE", body: JSON.stringify({}), activityId });
      showAdminToast("专业已删除，配额矩阵已同步缩减", "success");
    }
    await loadDashboard();
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

adminEls.groupEditor.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest(".entity-row");
  const id = Number(row.dataset.id);
  const activityId = Number(adminEls.groupEditor.dataset.activityId);
  try {
    if (button.dataset.action === "save-group") {
      const result = await adminApi(`/api/admin/groups/${id}`, { method: "PATCH", body: JSON.stringify({ name: row._nameInput.value, total_capacity: Number(row._capacityInput.value) }), activityId });
      showAdminToast(
        result?.quotas_adjusted || result?.quota_adjustments?.length
          ? "教学组容量已保存，专业配额已按已选下限自动重算"
          : "教学组设置已保存，配额矩阵已同步复核",
        "success",
      );
    } else if (button.dataset.action === "toggle-group-status") {
      const nextActive = button.dataset.nextActive === "true";
      const actionName = nextActive ? "重新启用教学组" : "停用教学组";
      const actionMessage = nextActive
        ? `确认重新启用“${row._nameInput.value}”？启用后请复核总容量和各专业配额。`
        : `确认停用“${row._nameInput.value}”？历史记录不会删除；若已有学生选择该组，系统会阻止操作。`;
      if (!await confirmDanger(actionName, actionMessage)) return;
      button.disabled = true;
      await adminApi(`/api/admin/groups/${id}`, { method: "PATCH", body: JSON.stringify({ active: nextActive }), activityId });
      showAdminToast(nextActive ? "教学组已重新启用" : "教学组已停用，历史记录仍保留", "success");
    } else if (button.dataset.action === "delete-group") {
      if (!await confirmDanger("删除教学组", `确认删除“${row._nameInput.value}”？有历史选择时系统会阻止删除。`)) return;
      await adminApi(`/api/admin/groups/${id}`, { method: "DELETE", body: JSON.stringify({}), activityId });
      showAdminToast("教学组已删除，配额矩阵已同步缩减", "success");
    }
    await loadDashboard();
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

adminEls.quotaMatrix.addEventListener("change", async (event) => {
  const input = event.target.closest("input[data-major-id]");
  if (!input) return;
  const activityId = Number(adminEls.quotaMatrix.dataset.activityId);
  try {
    await adminApi(`/api/admin/quotas/${input.dataset.majorId}/${input.dataset.groupId}`, { method: "PUT", body: JSON.stringify({ capacity: Number(input.value) }), activityId });
    input.dataset.original = input.value;
    showAdminToast("配额已保存", "success");
    await loadDashboard();
  } catch (error) {
    input.value = input.dataset.original;
    showAdminToast(error.message, "error");
  }
});

adminEls.settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(adminEls.settingsForm).entries());
  const activityId = Number(adminEls.settingsForm.dataset.activityId || adminState.dashboard.settings.activity_id);
  try {
    await adminApi("/api/admin/settings", { method: "PATCH", body: JSON.stringify(values), activityId });
    delete adminEls.settingsForm.dataset.activityId;
    showAdminToast("学生端访问地址已保存", "success");
    await loadDashboard();
  } catch (error) { showAdminToast(error.message, "error"); }
});

adminEls.newActivityForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const title = form.elements.namedItem("title").value.trim();
  const code = form.elements.namedItem("code").value.trim();
  const copyStructure = form.elements.namedItem("copy_structure").checked;
  const previousActivityId = Number(form.dataset.activityId || adminState.dashboard.settings.activity_id);
  const confirmed = await confirmDanger(
    "归档并新建活动",
    `确认封存“${adminState.dashboard?.settings.activity_title}”并创建“${title}”？旧结果可下载查看，但不能再修改。`,
  );
  if (!confirmed) return;
  const submitButton = form.querySelector('button[type="submit"]');
  submitButton.disabled = true;
  try {
    await adminApi("/api/admin/activities", {
      method: "POST",
      body: JSON.stringify({
        title,
        code: code || null,
        copy_structure: copyStructure,
        previous_activity_id: previousActivityId,
      }),
      activityId: previousActivityId,
    });
    form.reset();
    delete form.dataset.activityId;
    form.elements.namedItem("copy_structure").checked = true;
    showAdminToast("旧活动已归档，新活动已创建", "success");
    await loadDashboard();
  } catch (error) {
    showAdminToast(error.message, "error");
  } finally {
    submitButton.disabled = adminState.dashboard?.settings.status === "open";
  }
});

document.querySelector("#password-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const currentPassword = form.elements.namedItem("current_password").value;
  const newPassword = form.elements.namedItem("new_password").value;
  const confirmation = form.elements.namedItem("confirm_password").value;
  if (newPassword !== confirmation) { showAdminToast("两次输入的新密码不一致", "error"); return; }
  try {
    await adminApi("/api/admin/password", { method: "POST", body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }) });
    form.reset();
    showAdminToast("管理员密码已更新", "success");
  } catch (error) { showAdminToast(error.message, "error"); }
});

adminEls.importFile.addEventListener("change", () => {
  if (!adminEls.importForm.dataset.activityId && adminState.dashboard?.settings.activity_id) {
    adminEls.importForm.dataset.activityId = String(adminState.dashboard.settings.activity_id);
  }
  const files = [...adminEls.importFile.files];
  adminEls.importFileName.textContent = files.length
    ? `${files.length} 个文件：${files.map((file) => file.name).join("、")}`
    : "可多选 CSV / XLS / XLSX";
});

adminEls.importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const files = [...adminEls.importFile.files];
  if (!files.length) {
    showAdminToast("请先选择至少一个 CSV、XLS 或 XLSX 名单文件", "error");
    return;
  }
  const mode = adminEls.importMode.value === "sync" ? "sync" : "merge";
  if (mode === "sync") {
    const confirmed = await confirmDanger(
      "确认同步完整名单",
      "同步模式会停用所有未出现在本次全部文件中的学生；个人激活码仍固定为证件号后 6 位，不会随机生成或批量重置。",
    );
    if (!confirmed) return;
  }
  const body = new FormData();
  for (const file of files) body.append("files", file, file.name);
  const activityId = Number(adminEls.importForm.dataset.activityId || adminState.dashboard.settings.activity_id);
  const query = new URLSearchParams({ mode });
  const submit = adminEls.importForm.querySelector('button[type="submit"]');
  submit.disabled = true;
  submit.textContent = `正在导入 ${files.length} 个文件…`;
  try {
    const result = (await adminApi(`/api/admin/students/import?${query}`, { method: "POST", body, activityId })) || {};
    adminEls.importResult.className = "import-result is-success";
    adminEls.importResult.textContent = `已完成 ${files.length} 个文件：新增 ${result.created || 0} 人，更新 ${result.updated || 0} 人，停用 ${result.deactivated || 0} 人。个人激活码使用证件号后 6 位，未生成或下载随机凭据。`;
    adminEls.importForm.reset();
    delete adminEls.importForm.dataset.activityId;
    adminEls.importFileName.textContent = "可多选 CSV / XLS / XLSX";
    showAdminToast("学生名单导入成功", "success");
    await loadDashboard();
  } catch (error) {
    adminEls.importResult.className = "import-result is-error";
    adminEls.importResult.textContent = `导入失败：${error.message}`;
    showAdminToast(error.message, "error");
  } finally {
    submit.disabled = false;
    submit.textContent = "批量导入学生名单";
  }
});

function downloadText(filename, content) {
  const blob = new Blob(["\ufeff", content], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function exportFilename(response, fallback) {
  const disposition = response.headers.get("content-disposition") || "";
  const utf8Name = disposition.match(/filename\*=UTF-8''([^;]+)/i)?.[1];
  if (utf8Name) {
    try { return decodeURIComponent(utf8Name); } catch (_) { /* use fallback below */ }
  }
  return disposition.match(/filename="?([^";]+)"?/i)?.[1] || fallback;
}

async function downloadAdminExport(anchor, fallbackName, successMessage) {
  if (anchor.dataset.downloading === "true") return;
  anchor.dataset.downloading = "true";
  anchor.setAttribute("aria-busy", "true");
  anchor.classList.add("is-downloading");
  try {
    let response;
    try {
      response = await fetch(anchor.href, { credentials: "same-origin" });
    } catch (_) {
      throw Object.assign(new Error("网络连接失败，导出未完成"), { status: 0 });
    }
    if (!response.ok) {
      let data = null;
      if ((response.headers.get("content-type") || "").includes("application/json")) {
        try { data = await response.json(); } catch (_) { data = null; }
      }
      throw Object.assign(new Error(adminErrorMessage(data, response.status)), { status: response.status });
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const download = document.createElement("a");
    download.href = url;
    download.download = exportFilename(response, fallbackName);
    document.body.append(download);
    download.click();
    download.remove();
    URL.revokeObjectURL(url);
    showAdminToast(successMessage, "success");
  } catch (error) {
    if (error.status === 401) {
      showAdminLogin();
      adminEls.loginError.textContent = "登录已失效，请重新登录后导出";
    } else {
      showAdminToast(`导出失败：${error.message}`, "error");
    }
  } finally {
    delete anchor.dataset.downloading;
    anchor.removeAttribute("aria-busy");
    anchor.classList.remove("is-downloading");
  }
}

function csvEscape(value) {
  let text = String(value ?? "");
  if (/^[\t\r]/.test(text) || /^\s*[=+\-@]/.test(text)) text = `'${text}`;
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

document.querySelector("#download-template").addEventListener("click", () => {
  const rows = [["学号", "姓名", "专业名称", "证件号"]];
  downloadText("学生名单模板.csv", rows.map((row) => row.map(csvEscape).join(",")).join("\n"));
});

for (const [anchor, filename, message] of [
  [adminEls.exportSelections, "选择记录.csv", "选择记录已导出"],
  [adminEls.exportCompleteResults, "本场完整结果.xlsx", "完整名单与抢选结果 Excel 已导出"],
  [adminEls.exportUnselected, "未选学生名单.csv", "未选学生名单已导出"],
]) {
  anchor.addEventListener("click", (event) => {
    event.preventDefault();
    downloadAdminExport(anchor, filename, message);
  });
}

adminEls.assignmentBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action=assign-student]");
  if (!button) return;
  const row = button.closest("tr");
  const groupId = Number(row._groupSelect.value);
  const activityId = Number(adminEls.assignmentBody.dataset.activityId);
  if (!groupId) { showAdminToast("请先选择补位教学组", "error"); return; }
  try {
    await adminApi("/api/admin/selections", { method: "POST", body: JSON.stringify({ student_id: Number(row.dataset.studentId), group_id: groupId }), activityId });
    showAdminToast("补位已写入并记录审计日志", "success");
    await loadDashboard();
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

adminEls.rosterBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest("tr");
  const activityId = Number(adminEls.rosterBody.dataset.activityId);
  const studentId = Number(row.dataset.studentId);

  if (button.dataset.action === "hide-activation-code") {
    clearRevealedActivationCode(studentId);
    renderStudentRoster();
    return;
  }

  if (button.dataset.action === "reveal-activation-code") {
    button.disabled = true;
    button.textContent = "读取中…";
    try {
      const result = await adminApi(`/api/admin/students/${studentId}/activation-code/reveal`, {
        method: "POST",
        body: JSON.stringify({}),
        activityId,
      });
      const activationCode = activationCodeFromResponse(result);
      if (!activationCode) throw new Error("该历史激活码无法显示；请在关闭抢选后，重新导入包含证件号的该生名单");
      rememberRevealedActivationCode(studentId, activationCode);
      renderStudentRoster();
      showAdminToast("激活码明文已显示，60 秒后自动隐藏", "success");
    } catch (error) {
      button.disabled = false;
      button.textContent = "显示明文";
      showAdminToast(error.message, "error");
    }
    return;
  }

});

adminEls.recentBody.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action=revoke-selection]");
  if (!button) return;
  const activityId = Number(adminEls.recentBody.dataset.activityId);
  if (!await confirmDanger("撤销当前选择", `确认撤销 ${button.dataset.studentName} 的当前教学组？名额会立即释放。`)) return;
  try {
    await adminApi("/api/admin/selections/revoke", { method: "POST", body: JSON.stringify({ student_id: Number(button.dataset.studentId), reason: "管理员在管理端撤销" }), activityId });
    showAdminToast("选择已撤销，名额已释放", "success");
    await loadDashboard();
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && adminState.currentView === "overview" && adminState.csrf) {
    adminState.rosterFingerprint = "";
    adminState.liveFeedFingerprint = "";
    loadDashboard({ quiet: true });
  }
});

loadAdminSession();
