"use strict";

const adminState = {
  csrf: "",
  dashboard: null,
  currentView: "overview",
  pollTimer: null,
  messageTimer: null,
  loading: false,
  dashboardLoadPromise: null,
  boardPageTimer: null,
  boardLayoutTimer: null,
  groupProgressScrollFrame: null,
  groupProgressScrollLastTime: 0,
  groupProgressScrollPosition: 0,
  groupProgressLoopSetupFrame: null,
  rosterScrollFrame: null,
  rosterScrollLastTime: 0,
  rosterScrollPosition: 0,
  rosterFingerprint: "",
  rosterLoopSetupFrame: null,
  liveFeedFingerprint: "",
  groupProgressFingerprint: "",
  structureFingerprint: "",
  liveFeedScrollFrame: null,
  liveFeedScrollLastTime: 0,
  liveFeedScrollPosition: 0,
  liveFeedLoopSetupFrame: null,
  waitingFeedFingerprint: "",
  waitingFeedScrollFrame: null,
  waitingFeedScrollLastTime: 0,
  waitingFeedScrollPosition: 0,
  waitingFeedLoopSetupFrame: null,
  revealedActivationCodes: new Map(),
  activationHideTimers: new Map(),
  phaseActionPending: false,
  serverClockOffset: 0,
  serverClockSynchronized: false,
  dashboardClockSample: null,
  statusSyncLoading: false,
  recentRenderedAt: 0,
  lastActivityId: null,
  connectionInterrupted: false,
  lastBackgroundErrorAt: 0,
  countdownFrame: null,
  countdownTargetMs: null,
  countdownLastSecond: null,
  countdownFinishedTarget: null,
  quotaSaveTimers: new Map(),
  entitySaveTimers: new Map(),
};

const adminEls = {
  loginView: document.querySelector("#admin-login-view"),
  loginForm: document.querySelector("#admin-login-form"),
  loginError: document.querySelector("#admin-login-error"),
  app: document.querySelector("#admin-app"),
  title: document.querySelector("#admin-title"),
  statusBadge: document.querySelector("#admin-status-badge"),
  statusButton: document.querySelector("#open-live-board"),
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
  waitingRateCount: document.querySelector("#waiting-rate-count"),
  waitingRateBar: document.querySelector("#waiting-rate-bar"),
  rate: document.querySelector("#metric-rate"),
  rateBar: document.querySelector("#metric-rate-bar"),
  rateTrack: document.querySelector("#metric-rate-track"),
  rateCount: document.querySelector("#metric-progress-count"),
  groupProgress: document.querySelector("#group-progress"),
  groupProgressPage: document.querySelector("#group-progress-page"),
  liveSelectionFeed: document.querySelector("#live-selection-feed"),
  liveFeedState: document.querySelector("#live-feed-state"),
  waitingStudentFeed: document.querySelector("#waiting-student-feed"),
  waitingFeedState: document.querySelector("#waiting-feed-state"),
  qr: document.querySelector("#student-qr"),
  qrPlaceholder: document.querySelector("#qr-placeholder"),
  publicUrl: document.querySelector("#public-url-label"),
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
  structureSaveSummary: document.querySelector("#structure-save-summary"),
  majorSearch: document.querySelector("#structure-major-search"),
  groupSearch: document.querySelector("#structure-group-search"),
  majorVisibleCount: document.querySelector("#major-visible-count"),
  groupVisibleCount: document.querySelector("#group-visible-count"),
  quotaBatchForm: document.querySelector("#quota-batch-form"),
  quotaBatchValue: document.querySelector("#quota-batch-value"),
  quotaBatchCount: document.querySelector("#quota-batch-count"),
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
  dangerDialogMessage: document.querySelector("#danger-dialog-message"),
  dangerDialogRoster: document.querySelector("#danger-dialog-roster"),
  dangerDialogRosterCount: document.querySelector("#danger-dialog-roster-count"),
  dangerDialogRosterGroups: document.querySelector("#danger-dialog-roster-groups"),
  dangerDialogConfirm: document.querySelector("#danger-dialog-confirm"),
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

function renderConfirmationRoster(students = []) {
  adminEls.dangerDialogRoster.classList.toggle("is-hidden", students.length === 0);
  adminEls.dangerDialog.classList.toggle("confirm-dialog--roster", students.length > 0);
  adminEls.dangerDialogConfirm.textContent = students.length > 0 ? "仍然开始倒计时" : "确认";
  adminEls.dangerDialogRosterCount.textContent = `${students.length} 人`;
  if (!students.length) {
    adminEls.dangerDialogRosterGroups.replaceChildren();
    return;
  }
  const grouped = new Map();
  for (const student of students) {
    const majorName = String(student.major_name || "未注明专业").trim() || "未注明专业";
    if (!grouped.has(majorName)) grouped.set(majorName, []);
    grouped.get(majorName).push(String(student.name || "姓名待同步"));
  }
  const sections = [...grouped.entries()]
    .sort(([left], [right]) => left.localeCompare(right, "zh-CN"))
    .map(([majorName, names]) => {
      const section = document.createElement("section");
      section.className = "confirm-roster__group";
      const heading = document.createElement("div");
      heading.className = "confirm-roster__group-heading";
      const title = document.createElement("strong");
      title.textContent = majorName;
      const count = document.createElement("span");
      count.textContent = `${names.length} 人`;
      heading.append(title, count);
      const grid = document.createElement("div");
      grid.className = "confirm-roster__name-grid";
      const sortedNames = names.sort((left, right) => left.localeCompare(right, "zh-CN"));
      grid.append(...sortedNames.map((name) => {
        const item = document.createElement("span");
        item.textContent = name;
        return item;
      }));
      section.append(heading, grid);
      return section;
    });
  adminEls.dangerDialogRosterGroups.replaceChildren(...sections);
}

function confirmDanger(title, message, { roster = [] } = {}) {
  const originalParent = adminEls.dangerDialog.parentElement;
  const fullscreenHost = document.fullscreenElement;
  if (fullscreenHost && !fullscreenHost.contains(adminEls.dangerDialog)) {
    fullscreenHost.append(adminEls.dangerDialog);
  }
  document.querySelector("#danger-dialog-title").textContent = title;
  adminEls.dangerDialogMessage.textContent = message;
  renderConfirmationRoster(roster);
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
      renderConfirmationRoster([]);
      resolve(confirmed);
    }, { once: true });
  });
}

function showAdminApp() {
  adminEls.loginView.classList.add("is-hidden");
  adminEls.app.classList.remove("is-hidden");
  document.body.classList.add("admin-authenticated");
}

function showAdminLogin() {
  adminEls.app.classList.add("is-hidden");
  adminEls.loginView.classList.remove("is-hidden");
  document.body.classList.remove("admin-authenticated");
  clearInterval(adminState.pollTimer);
  clearInterval(adminState.boardPageTimer);
  clearAllRevealedActivationCodes();
  stopRosterAutoScroll();
  stopLiveFeedAutoScroll();
  stopWaitingFeedAutoScroll();
  stopGroupProgressAutoScroll();
  stopCountdownTicker();
  for (const timer of adminState.quotaSaveTimers.values()) clearTimeout(timer);
  adminState.quotaSaveTimers.clear();
  for (const timer of adminState.entitySaveTimers.values()) clearTimeout(timer);
  adminState.entitySaveTimers.clear();
  adminState.serverClockOffset = 0;
  adminState.serverClockSynchronized = false;
  adminState.dashboardClockSample = null;
  adminState.statusSyncLoading = false;
  adminState.rosterFingerprint = "";
  adminState.liveFeedFingerprint = "";
  adminState.waitingFeedFingerprint = "";
  adminState.groupProgressFingerprint = "";
  adminState.structureFingerprint = "";
}

function dashboardField(data, key) {
  return data?.[key] ?? data?.settings?.[key] ?? null;
}

function synchronizeServerClock(data) {
  const serverNow = dashboardField(data, "server_now");
  const parsed = Date.parse(serverNow || "");
  if (!Number.isFinite(parsed)) return;
  const sample = adminState.dashboardClockSample;
  const clientReference = sample
    ? (sample.requestStartedAt + sample.responseReceivedAt) / 2
    : Date.now();
  const sampledOffset = parsed - clientReference;
  if (!adminState.serverClockSynchronized || Math.abs(sampledOffset - adminState.serverClockOffset) > 10_000) {
    adminState.serverClockOffset = sampledOffset;
    adminState.serverClockSynchronized = true;
    return;
  }
  adminState.serverClockOffset = (adminState.serverClockOffset * 0.75) + (sampledOffset * 0.25);
}

function millisecondsUntilSelection(data = adminState.dashboard) {
  const opensAt = dashboardField(data, "selection_opens_at");
  const target = Date.parse(opensAt || "");
  if (!Number.isFinite(target)) return null;
  return target - (Date.now() + adminState.serverClockOffset);
}

function serverSynchronizedDate() {
  return new Date(Date.now() + adminState.serverClockOffset);
}

function renderBoardClock() {
  adminEls.boardClock.textContent = serverSynchronizedDate().toLocaleTimeString("zh-CN", { hour12: false });
}

function stopCountdownTicker({ preserveTarget = false } = {}) {
  if (adminState.countdownFrame) cancelAnimationFrame(adminState.countdownFrame);
  adminState.countdownFrame = null;
  adminState.countdownLastSecond = null;
  if (!preserveTarget) adminState.countdownTargetMs = null;
}

function setCountdownNumber(seconds) {
  if (adminState.countdownLastSecond === seconds) return;
  adminState.countdownLastSecond = seconds;
  const countdownElements = [adminEls.boardCountdown, adminEls.boardOverlayCountdown];
  for (const element of countdownElements) {
    element.textContent = String(seconds);
    element.classList.remove("is-ticking");
  }
  void adminEls.boardOverlayCountdown.offsetWidth;
  for (const element of countdownElements) element.classList.add("is-ticking");
  adminEls.boardStart.textContent = `倒计时 ${seconds} 秒`;
}

function startCountdownTicker(data) {
  const targetMs = Date.parse(dashboardField(data, "selection_opens_at") || "");
  if (!Number.isFinite(targetMs)) {
    setCountdownNumber(10);
    return;
  }
  if (adminState.countdownTargetMs === targetMs && adminState.countdownFrame) return;
  stopCountdownTicker({ preserveTarget: true });
  adminState.countdownTargetMs = targetMs;
  adminState.countdownFinishedTarget = null;
  const tick = () => {
    const remainingMs = targetMs - serverSynchronizedDate().getTime();
    const remainingSeconds = Math.max(0, Math.ceil(remainingMs / 1000));
    setCountdownNumber(remainingSeconds);
    if (remainingMs <= 0) {
      adminState.countdownFrame = null;
      if (adminState.countdownFinishedTarget !== targetMs) {
        adminState.countdownFinishedTarget = targetMs;
        requestAnimationFrame(() => {
          if (adminState.dashboard && dashboardPhase(adminState.dashboard) !== "countdown") {
            if (adminState.currentView === "overview") renderDashboard(adminState.dashboard);
            else renderDashboardPhaseStatus(adminState.dashboard);
          }
        });
      }
      return;
    }
    adminState.countdownFrame = requestAnimationFrame(tick);
  };
  tick();
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

async function loadAdminSession() {
  try {
    const me = await adminApi("/api/admin/me");
    adminState.csrf = me.csrf_token;
    showAdminApp();
    await loadDashboard({ afterMutation: true });
    startAdminPolling();
  } catch (error) {
    if (error.status !== 401) adminEls.loginError.textContent = error.message;
    showAdminLogin();
  }
}

async function loadDashboard({ quiet = false, afterMutation = false } = {}) {
  if (adminState.loading) {
    if (!afterMutation) return adminState.dashboardLoadPromise;
    try { await adminState.dashboardLoadPromise; } catch (_) { /* the forced refresh below reports its own result */ }
    return loadDashboard({ quiet, afterMutation: false });
  }
  adminState.loading = true;
  const request = (async () => {
    try {
      const requestStartedAt = Date.now();
      const dashboard = await adminApi("/api/admin/dashboard");
      adminState.dashboardClockSample = { requestStartedAt, responseReceivedAt: Date.now() };
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
      adminState.dashboardLoadPromise = null;
    }
  })();
  adminState.dashboardLoadPromise = request;
  return request;
}

function mergeDashboardStatusSnapshot(snapshot) {
  if (!adminState.dashboard?.settings) return null;
  const cachedActivityId = Number(adminState.dashboard.settings.activity_id);
  const snapshotActivityId = Number(snapshot.activity_id);
  if (
    Number.isFinite(cachedActivityId)
    && Number.isFinite(snapshotActivityId)
    && cachedActivityId !== snapshotActivityId
  ) {
    clearAllRevealedActivationCodes();
    const presence = adminState.dashboard.presence;
    adminState.dashboard = {
      ...adminState.dashboard,
      students: [],
      unselected_students: [],
      recent_selections: [],
      absent_students: [],
      presence: presence && typeof presence === "object"
        ? { ...presence, absent_students: [] }
        : presence,
    };
    adminEls.assignmentBody.replaceChildren();
    adminEls.rosterBody.replaceChildren();
    delete adminEls.assignmentBody.dataset.activityId;
    delete adminEls.rosterBody.dataset.activityId;
    adminEls.rosterCount.textContent = "活动已切换，正在同步新名单…";
    adminEls.statusBadge.className = "status-badge status-badge--closed";
    adminEls.statusBadge.textContent = "活动已切换";
    adminEls.statusButton.textContent = "进入实时大屏";
    adminEls.statusButton.disabled = false;
    adminEls.statusButton.title = "活动已切换，进入大屏后会继续同步新名单";
    return null;
  }
  const settings = {
    ...adminState.dashboard.settings,
    status: snapshot.status ?? adminState.dashboard.settings.status,
    phase: snapshot.phase ?? adminState.dashboard.settings.phase,
    server_now: snapshot.server_now ?? adminState.dashboard.settings.server_now,
    selection_opens_at: snapshot.selection_opens_at ?? adminState.dashboard.settings.selection_opens_at,
    student_login_allowed: snapshot.student_login_allowed ?? adminState.dashboard.settings.student_login_allowed,
    status_message: snapshot.status_message ?? adminState.dashboard.settings.status_message,
  };
  return {
    ...adminState.dashboard,
    status: snapshot.status ?? adminState.dashboard.status,
    phase: snapshot.phase ?? adminState.dashboard.phase,
    server_now: snapshot.server_now ?? adminState.dashboard.server_now,
    selection_opens_at: snapshot.selection_opens_at ?? adminState.dashboard.selection_opens_at,
    settings,
  };
}

async function loadDashboardStatusSnapshot({ quiet = false } = {}) {
  if (adminState.statusSyncLoading || adminState.loading || !adminState.dashboard) return;
  adminState.statusSyncLoading = true;
  try {
    const requestStartedAt = Date.now();
    const snapshot = await adminApi("/api/public/status");
    adminState.dashboardClockSample = { requestStartedAt, responseReceivedAt: Date.now() };
    synchronizeServerClock(snapshot);
    if (!adminState.csrf || document.hidden || adminState.currentView === "overview") return;
    const mergedDashboard = mergeDashboardStatusSnapshot(snapshot);
    if (!mergedDashboard) {
      await loadDashboard({ quiet: true });
      return;
    }
    adminState.dashboard = mergedDashboard;
    renderDashboardPhaseStatus(mergedDashboard);
    adminEls.lastRefresh.textContent = `状态同步于 ${new Date().toLocaleTimeString("zh-CN", { hour12: false })}`;
    if (adminState.connectionInterrupted) {
      adminState.connectionInterrupted = false;
      showAdminToast("管理端状态同步已恢复", "success");
    }
  } catch (error) {
    if (!quiet) {
      showAdminToast(error.message, "error");
    } else if (!adminState.connectionInterrupted || Date.now() - adminState.lastBackgroundErrorAt >= 10_000) {
      adminState.connectionInterrupted = true;
      adminState.lastBackgroundErrorAt = Date.now();
      showAdminToast(error.status === 0 ? "抢选状态网络同步中断，系统会自动重试" : `${error.message}；系统会自动重试`, "error");
    }
  } finally {
    adminState.statusSyncLoading = false;
  }
}

function startAdminPolling() {
  clearInterval(adminState.pollTimer);
  adminState.pollTimer = setInterval(() => {
    if (document.hidden) return;
    if (adminState.currentView === "overview") loadDashboard({ quiet: true });
    else loadDashboardStatusSnapshot({ quiet: true });
  }, 1000);
  clearInterval(adminState.boardPageTimer);
  adminState.boardPageTimer = setInterval(() => {
    renderBoardClock();
  }, 1000);
  renderBoardClock();
}

function structureEditorAutosaveBusy() {
  return adminState.entitySaveTimers.size > 0
    || adminState.quotaSaveTimers.size > 0
    || Boolean(document.activeElement?.closest?.("#major-editor, #group-editor, #quota-matrix"))
    || Boolean(adminEls.majorEditor.querySelector('.entity-row[data-saving="true"]'))
    || Boolean(adminEls.groupEditor.querySelector('.entity-row[data-saving="true"]'))
    || Boolean(adminEls.quotaMatrix.querySelector('input[data-saving="true"]'));
}

function renderLatestStructureAfterAutosave({ forceStructure = false } = {}) {
  if (
    adminState.currentView === "structure"
    && adminState.dashboard
    && (forceStructure || !structureEditorAutosaveBusy())
  ) renderDashboard(adminState.dashboard, { forceStructure });
}

function applyBoardDisplayMode(displayMode) {
  liveBoard.dataset.displayMode = displayMode;
  liveBoard.classList.toggle("phase-waiting", displayMode === "waiting");
  liveBoard.classList.toggle("phase-selection", displayMode === "selection");
  liveBoard.classList.toggle("phase-countdown", displayMode === "countdown");
}

function structureSearchValue(input) {
  return input?.value?.trim().toLocaleLowerCase("zh-CN") || "";
}

function renderDashboard(data, { forceStructure = false } = {}) {
  synchronizeServerClock(data);
  const phase = dashboardPhase(data);
  const displayMode = boardDisplayMode(data, phase);
  const structureLocked = phase === "countdown" || phase === "open" || data.settings.status === "open";
  const presence = normalizedPresence(data);
  const activityId = Number(data.settings.activity_id);
  if (adminState.lastActivityId !== null && adminState.lastActivityId !== activityId) {
    clearAllRevealedActivationCodes();
    stopRosterAutoScroll();
    stopLiveFeedAutoScroll();
    stopWaitingFeedAutoScroll();
    stopGroupProgressAutoScroll();
    adminState.rosterFingerprint = "";
    adminState.liveFeedFingerprint = "";
    adminState.waitingFeedFingerprint = "";
    adminState.groupProgressFingerprint = "";
    adminState.structureFingerprint = "";
  }
  adminState.lastActivityId = activityId;
  const rate = data.totals.students ? Math.round((data.totals.selected / data.totals.students) * 100) : 0;
  adminEls.title.textContent = data.settings.activity_title;
  adminEls.boardActivityTitle.textContent = data.settings.activity_title;
  renderBoardClock();
  document.title = `${data.settings.activity_title} · 管理端`;
  adminEls.selected.textContent = String(data.totals.selected);
  adminEls.unselected.textContent = String(data.totals.unselected);
  const waitingRate = data.totals.students ? Math.round((presence.online / data.totals.students) * 100) : 0;
  adminEls.waitingOnline.textContent = String(presence.online);
  adminEls.waitingAbsent.textContent = String(presence.absent);
  adminEls.waitingRate.textContent = `${waitingRate}%`;
  adminEls.waitingRateCount.textContent = `${presence.online} / ${data.totals.students} 人`;
  adminEls.waitingRateBar.style.width = `${waitingRate}%`;
  adminEls.rate.textContent = `${rate}%`;
  adminEls.rateCount.textContent = `${data.totals.selected} / ${data.totals.students}`;
  adminEls.rateBar.style.width = `${rate}%`;
  adminEls.rateTrack.setAttribute("aria-valuenow", String(rate));
  adminEls.rateTrack.setAttribute("aria-valuetext", `已完成 ${data.totals.selected} 人，共 ${data.totals.students} 人，完成率 ${rate}%`);
  renderReadiness(data.readiness, structureLocked);
  renderDashboardPhaseStatus(data, phase, presence);
  applyBoardDisplayMode(displayMode);
  adminEls.statsTitle.textContent = displayMode === "waiting" ? "候场进度" : "各教学组抢选进度";
  adminEls.boardRosterHeading.textContent = displayMode === "waiting" ? "候场学生情况" : "当前抢选进度";

  const activityQuery = `activity_id=${encodeURIComponent(data.settings.activity_id)}`;
  adminEls.exportSelections.href = `/api/admin/export/selections.xlsx?${activityQuery}`;
  adminEls.exportCompleteResults.href = `/api/admin/export/results.xlsx?${activityQuery}`;
  const complete = Number(data.totals.students) > 0 && Number(data.totals.unselected) === 0;
  adminEls.exportCompleteResults.classList.toggle("is-complete", complete);
  adminEls.exportCompleteResults.textContent = complete ? "全部完成 · 导出本场完整结果 Excel" : "导出本场完整结果 Excel";
  adminEls.exportCompletionCallout.classList.toggle("is-hidden", !complete);
  adminEls.exportUnselected.href = `/api/admin/export/unselected.xlsx?${activityQuery}`;
  if (adminState.currentView === "overview") {
    renderGroupProgress(data.groups);
    renderLiveSelectionFeed(data.recent_selections || []);
    renderWaitingStudentFeed(data.entered_students || []);
    renderQr(data.settings.public_base_url);
    renderUnselectedList();
    if (Date.now() - adminState.recentRenderedAt >= 5000) {
      renderRecentSelections(data.recent_selections);
      adminEls.recentBody.dataset.activityId = String(data.settings.activity_id);
      adminState.recentRenderedAt = Date.now();
    }
  } else if (adminState.currentView === "structure") {
    const structureFingerprint = JSON.stringify([
      structureLocked,
      structureSearchValue(adminEls.majorSearch),
      structureSearchValue(adminEls.groupSearch),
      ...data.majors.map((major) => [major.id, major.name, major.active, major.sort_order]),
      ...data.groups.map((group) => [group.id, group.name, group.active, group.total_capacity, group.sort_order]),
      ...data.quotas.map((quota) => [quota.major_id, quota.group_id, quota.capacity, quota.selected_count]),
    ]);
    if ((forceStructure || !structureEditorAutosaveBusy()) && structureFingerprint !== adminState.structureFingerprint) {
      adminState.structureFingerprint = structureFingerprint;
      renderStructure(data, structureLocked);
    }
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

function renderDashboardPhaseStatus(data, phase = dashboardPhase(data), presence = normalizedPresence(data)) {
  const badgeLabels = { waiting: "候场中", countdown: "倒计时", open: "进行中", closed: "已关闭" };
  adminEls.boardHeaderPhase.textContent = badgeLabels[phase];
  adminEls.statusBadge.className = `status-badge status-badge--${phase === "open" ? "open" : phase === "countdown" ? "countdown" : "closed"}`;
  adminEls.statusBadge.textContent = badgeLabels[phase];
  adminEls.statusButton.title = "进入全屏实时大屏，抢选开关位于大屏二维码下方";
  applyBoardDisplayMode(boardDisplayMode(data, phase));
  enforceCountdownPresentation(phase);
  renderBoardStage(data, phase, presence);
  renderBoardClock();
}

function renderBoardStage(data, phase, presence) {
  const total = Number(data.totals?.students || 0);
  const readiness = normalizeReadiness(data.readiness);
  adminEls.boardStage.className = `qr-portal__status board-stage--${phase}`;
  adminEls.boardStart.disabled = adminState.phaseActionPending || phase === "countdown" || ((phase === "waiting" || phase === "closed") && !readiness.ready);

  if (phase === "countdown") {
    adminEls.boardStageLabel.textContent = "全体同步倒计时";
    adminEls.boardStageDetail.textContent = `已进入候场 ${presence.online} / ${total} 人，倒计时结束后同时进入抢选`;
    adminEls.boardStart.className = "qr-portal__action button button--primary button--wide";
    startCountdownTicker(data);
    return;
  }

  stopCountdownTicker();
  adminEls.boardCountdown.classList.remove("is-ticking");
  adminEls.boardOverlayCountdown.classList.remove("is-ticking");

  if (phase === "open") {
    adminEls.boardStageLabel.textContent = "抢选进行中";
    adminEls.boardCountdown.textContent = "LIVE";
    adminEls.boardStageDetail.textContent = `已完成 ${data.totals.selected} / ${total} 人，名额与名单每秒自动同步`;
    adminEls.boardStart.textContent = "关闭抢选";
    adminEls.boardStart.className = "qr-portal__action button button--secondary button--wide";
    return;
  }

  const isClosed = phase === "closed";
  adminEls.boardStageLabel.textContent = isClosed ? "抢选已关闭" : "扫码候场中";
  adminEls.boardCountdown.textContent = "READY";
  adminEls.boardStageDetail.textContent = `已进入候场 ${presence.online} / ${total} 人，尚未进入 ${presence.absent} 人`;
  adminEls.boardStart.textContent = readiness.ready ? "开始 10 秒倒计时" : "就绪检查未通过";
  adminEls.boardStart.className = "qr-portal__action button button--primary button--wide";
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
    await loadDashboard({ afterMutation: true });
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

function captureGroupProgressScrollOffset() {
  const list = adminEls.groupProgress;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  return loopHeight > 0 ? list.scrollTop % loopHeight : Math.max(0, list.scrollTop);
}

function restoreGroupProgressScrollOffset(offset) {
  const list = adminEls.groupProgress;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  const max = loopHeight > 0 ? loopHeight - 1 : Math.max(0, list.scrollHeight - list.clientHeight);
  const restored = Math.min(max, Math.max(0, offset));
  adminState.groupProgressScrollPosition = restored;
  list.scrollTop = restored;
}

function stopGroupProgressAutoScroll() {
  if (adminState.groupProgressScrollFrame) cancelAnimationFrame(adminState.groupProgressScrollFrame);
  if (adminState.groupProgressLoopSetupFrame) cancelAnimationFrame(adminState.groupProgressLoopSetupFrame);
  adminState.groupProgressScrollFrame = null;
  adminState.groupProgressLoopSetupFrame = null;
  adminState.groupProgressScrollLastTime = 0;
}

function startGroupProgressAutoScroll() {
  stopGroupProgressAutoScroll();
  if (reducedMotionPreference.matches) return;
  const list = adminEls.groupProgress;
  if (Number(list.dataset.loopHeight || 0) <= 0) return;
  adminState.groupProgressScrollPosition = Math.max(0, list.scrollTop);
  const tick = (now) => {
    if (document.hidden || adminState.currentView !== "overview") {
      stopGroupProgressAutoScroll();
      return;
    }
    const cycleHeight = Number(list.dataset.loopHeight || 0);
    if (cycleHeight > 0) {
      const elapsed = adminState.groupProgressScrollLastTime
        ? Math.min(80, now - adminState.groupProgressScrollLastTime)
        : 0;
      const domPosition = list.scrollTop % cycleHeight;
      if (Math.abs(domPosition - adminState.groupProgressScrollPosition) > 2) {
        adminState.groupProgressScrollPosition = domPosition;
      }
      adminState.groupProgressScrollPosition = (adminState.groupProgressScrollPosition + elapsed * 0.018) % cycleHeight;
      list.scrollTop = adminState.groupProgressScrollPosition;
    }
    adminState.groupProgressScrollLastTime = now;
    adminState.groupProgressScrollFrame = requestAnimationFrame(tick);
  };
  adminState.groupProgressScrollFrame = requestAnimationFrame(tick);
}

function setupGroupProgressLoop(previousOffset) {
  if (adminState.groupProgressLoopSetupFrame) cancelAnimationFrame(adminState.groupProgressLoopSetupFrame);
  adminState.groupProgressLoopSetupFrame = requestAnimationFrame(() => {
    adminState.groupProgressLoopSetupFrame = null;
    const list = adminEls.groupProgress;
    list.querySelectorAll("[data-group-progress-clone]").forEach((clone) => clone.remove());
    delete list.dataset.loopHeight;
    list.scrollTop = 0;
    const originals = [...list.children];
    const canLoop = originals.length > 1 && list.scrollHeight > list.clientHeight + 4;
    adminEls.groupProgressPage.textContent = canLoop && !reducedMotionPreference.matches
      ? "连续滚动"
      : originals.length ? "实时更新" : "";
    if (!canLoop || reducedMotionPreference.matches) {
      restoreGroupProgressScrollOffset(previousOffset);
      stopGroupProgressAutoScroll();
      return;
    }
    const firstTop = originals[0].offsetTop;
    const clones = originals.map((item) => {
      const clone = item.cloneNode(true);
      clone.dataset.groupProgressClone = "true";
      clone.setAttribute("aria-hidden", "true");
      return clone;
    });
    list.append(...clones);
    const loopHeight = clones[0].offsetTop - firstTop;
    if (loopHeight <= 0) return;
    list.dataset.loopHeight = String(loopHeight);
    restoreGroupProgressScrollOffset(previousOffset);
    startGroupProgressAutoScroll();
  });
}

function renderGroupProgress(groups, { force = false } = {}) {
  const activeGroups = groups.filter((group) => group.active);
  const fingerprint = JSON.stringify([
    boardDisplayMode(),
    ...activeGroups.map((group) => [group.id, group.name, group.selected_count, group.total_capacity]),
  ]);
  if (!force && fingerprint === adminState.groupProgressFingerprint) return;
  const previousOffset = captureGroupProgressScrollOffset();
  adminState.groupProgressFingerprint = fingerprint;
  stopGroupProgressAutoScroll();
  if (!activeGroups.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "尚未启用教学组";
    adminEls.groupProgress.replaceChildren(empty);
    adminEls.groupProgressPage.textContent = "";
    return;
  }
  const elements = activeGroups.map((group) => {
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
  setupGroupProgressLoop(previousOffset);
}

function captureLiveFeedScrollRatio() {
  const list = adminEls.liveSelectionFeed;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  if (loopHeight > 0) return list.scrollTop % loopHeight;
  return Math.max(0, list.scrollTop);
}

function restoreLiveFeedScrollRatio(offset) {
  const list = adminEls.liveSelectionFeed;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  const max = loopHeight > 0 ? loopHeight - 1 : Math.max(0, list.scrollHeight - list.clientHeight);
  const restored = Math.min(max, Math.max(0, offset));
  adminState.liveFeedScrollPosition = restored;
  list.scrollTop = restored;
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
  const list = adminEls.liveSelectionFeed;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  if (loopHeight <= 0) return;
  adminState.liveFeedScrollPosition = Math.max(0, list.scrollTop);
  const tick = (now) => {
    if (document.hidden || adminState.currentView !== "overview") {
      stopLiveFeedAutoScroll();
      return;
    }
    const cycleHeight = Number(list.dataset.loopHeight || 0);
    if (cycleHeight > 0) {
      const elapsed = adminState.liveFeedScrollLastTime ? Math.min(80, now - adminState.liveFeedScrollLastTime) : 0;
      const domPosition = list.scrollTop % cycleHeight;
      if (Math.abs(domPosition - adminState.liveFeedScrollPosition) > 2) {
        adminState.liveFeedScrollPosition = domPosition;
      }
      adminState.liveFeedScrollPosition = (adminState.liveFeedScrollPosition + elapsed * 0.022) % cycleHeight;
      list.scrollTop = adminState.liveFeedScrollPosition;
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

function captureWaitingFeedScrollOffset() {
  const list = adminEls.waitingStudentFeed;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  return loopHeight > 0 ? list.scrollTop % loopHeight : Math.max(0, list.scrollTop);
}

function restoreWaitingFeedScrollOffset(offset) {
  const list = adminEls.waitingStudentFeed;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  const max = loopHeight > 0 ? loopHeight - 1 : Math.max(0, list.scrollHeight - list.clientHeight);
  const restored = Math.min(max, Math.max(0, offset));
  adminState.waitingFeedScrollPosition = restored;
  list.scrollTop = restored;
}

function stopWaitingFeedAutoScroll() {
  if (adminState.waitingFeedScrollFrame) cancelAnimationFrame(adminState.waitingFeedScrollFrame);
  if (adminState.waitingFeedLoopSetupFrame) cancelAnimationFrame(adminState.waitingFeedLoopSetupFrame);
  adminState.waitingFeedScrollFrame = null;
  adminState.waitingFeedLoopSetupFrame = null;
  adminState.waitingFeedScrollLastTime = 0;
}

function startWaitingFeedAutoScroll() {
  stopWaitingFeedAutoScroll();
  if (reducedMotionPreference.matches) return;
  const list = adminEls.waitingStudentFeed;
  if (Number(list.dataset.loopHeight || 0) <= 0) return;
  adminState.waitingFeedScrollPosition = Math.max(0, list.scrollTop);
  const tick = (now) => {
    if (document.hidden || adminState.currentView !== "overview" || boardDisplayMode() !== "waiting") {
      stopWaitingFeedAutoScroll();
      return;
    }
    const cycleHeight = Number(list.dataset.loopHeight || 0);
    if (cycleHeight > 0) {
      const elapsed = adminState.waitingFeedScrollLastTime ? Math.min(80, now - adminState.waitingFeedScrollLastTime) : 0;
      const domPosition = list.scrollTop % cycleHeight;
      if (Math.abs(domPosition - adminState.waitingFeedScrollPosition) > 2) {
        adminState.waitingFeedScrollPosition = domPosition;
      }
      adminState.waitingFeedScrollPosition = (adminState.waitingFeedScrollPosition + elapsed * 0.026) % cycleHeight;
      list.scrollTop = adminState.waitingFeedScrollPosition;
    }
    adminState.waitingFeedScrollLastTime = now;
    adminState.waitingFeedScrollFrame = requestAnimationFrame(tick);
  };
  adminState.waitingFeedScrollFrame = requestAnimationFrame(tick);
}

function setupWaitingFeedLoop(previousOffset) {
  if (adminState.waitingFeedLoopSetupFrame) cancelAnimationFrame(adminState.waitingFeedLoopSetupFrame);
  adminState.waitingFeedLoopSetupFrame = requestAnimationFrame(() => {
    adminState.waitingFeedLoopSetupFrame = null;
    const list = adminEls.waitingStudentFeed;
    list.querySelectorAll("[data-waiting-clone]").forEach((clone) => clone.remove());
    delete list.dataset.loopHeight;
    list.scrollTop = 0;
    const originals = [...list.children];
    const canLoop = originals.length > 1 && list.scrollHeight > list.clientHeight + 4;
    adminEls.waitingFeedState.textContent = canLoop && !reducedMotionPreference.matches
      ? "连续滚动"
      : originals.length ? "实时更新" : "等待进入";
    if (!canLoop || reducedMotionPreference.matches) {
      restoreWaitingFeedScrollOffset(previousOffset);
      stopWaitingFeedAutoScroll();
      return;
    }
    const firstTop = originals[0].offsetTop;
    const clones = originals.map((item) => {
      const clone = item.cloneNode(true);
      clone.dataset.waitingClone = "true";
      clone.setAttribute("aria-hidden", "true");
      return clone;
    });
    list.append(...clones);
    const loopHeight = clones[0].offsetTop - firstTop;
    if (loopHeight <= 0) return;
    list.dataset.loopHeight = String(loopHeight);
    restoreWaitingFeedScrollOffset(previousOffset);
    startWaitingFeedAutoScroll();
  });
}

function renderWaitingStudentFeed(rows, { force = false } = {}) {
  const students = Array.isArray(rows) ? rows : [];
  const fingerprint = JSON.stringify([
    boardDisplayMode(),
    ...students.map((student) => [student.id, student.name, student.major_name]),
  ]);
  if (!force && fingerprint === adminState.waitingFeedFingerprint) return;
  const previousOffset = captureWaitingFeedScrollOffset();
  adminState.waitingFeedFingerprint = fingerprint;
  stopWaitingFeedAutoScroll();
  if (!students.length) {
    const empty = document.createElement("div");
    empty.className = "waiting-feed-empty";
    empty.textContent = "等待学生完成身份核验";
    adminEls.waitingStudentFeed.replaceChildren(empty);
    adminEls.waitingFeedState.textContent = "等待进入";
    return;
  }
  const items = students.map((student) => {
    const item = document.createElement("article");
    item.className = "waiting-feed-item";
    const marker = document.createElement("span");
    marker.className = "waiting-feed-item__marker";
    marker.textContent = "✓";
    const detail = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = student.name;
    const major = document.createElement("small");
    major.textContent = student.major_name || "专业待同步";
    detail.append(name, major);
    item.append(marker, detail);
    return item;
  });
  adminEls.waitingStudentFeed.replaceChildren(...items);
  setupWaitingFeedLoop(previousOffset);
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
  if (loopHeight > 0) return list.scrollTop % loopHeight;
  return Math.max(0, list.scrollTop);
}

function restoreRosterScrollRatio(offset) {
  const list = adminEls.unselectedList;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  if (loopHeight > 0) {
    const restored = Math.min(loopHeight - 1, Math.max(0, offset));
    adminState.rosterScrollPosition = restored;
    list.scrollTop = restored;
    return;
  }
  const max = Math.max(0, list.scrollHeight - list.clientHeight);
  const restored = Math.min(max, Math.max(0, offset));
  adminState.rosterScrollPosition = restored;
  list.scrollTop = restored;
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
  const list = adminEls.unselectedList;
  const loopHeight = Number(list.dataset.loopHeight || 0);
  if (loopHeight <= 0) return;
  adminState.rosterScrollPosition = Math.max(0, list.scrollTop);
  const tick = (now) => {
    if (document.hidden || adminState.currentView !== "overview") {
      stopRosterAutoScroll();
      return;
    }
    const cycleHeight = Number(list.dataset.loopHeight || 0);
    if (cycleHeight > 0) {
      const elapsed = adminState.rosterScrollLastTime ? Math.min(80, now - adminState.rosterScrollLastTime) : 0;
      const domPosition = list.scrollTop % cycleHeight;
      if (Math.abs(domPosition - adminState.rosterScrollPosition) > 2) {
        adminState.rosterScrollPosition = domPosition;
      }
      adminState.rosterScrollPosition = (adminState.rosterScrollPosition + elapsed * 0.018) % cycleHeight;
      list.scrollTop = adminState.rosterScrollPosition;
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
  const fingerprint = JSON.stringify([
    mode,
    adminEls.unselectedSearch.value.trim().toLowerCase(),
    ...visibleStudents.map((student) => [student.id, student.name, student.major_name]),
  ]);
  if (!force && adminState.rosterFingerprint === fingerprint) return;
  adminState.rosterFingerprint = fingerprint;
  stopRosterAutoScroll();
  if (!filtered.length) {
    adminEls.unselectedPage.textContent = "";
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

function renderStructureSaveSummary() {
  const summary = adminEls.structureSaveSummary;
  const locked = summary.dataset.locked === "true";
  const hasError = Boolean(document.querySelector('#view-structure [data-save-state="error"]'));
  const saving = Boolean(document.querySelector('#view-structure [data-saving="true"]'));
  const pending = adminState.entitySaveTimers.size > 0
    || adminState.quotaSaveTimers.size > 0
    || Boolean(document.querySelector('#view-structure [data-save-state="pending"], #quota-matrix input[data-pending="true"]'));
  let state = "saved";
  let text = locked ? "活动进行中 · 结构已锁定" : "已全部保存 · 当前可编辑";
  if (hasError) {
    state = "error";
    text = locked ? "结构已锁定 · 请刷新确认" : "有更改保存失败 · 请重试";
  } else if (saving) {
    state = "saving";
    text = "正在保存更改… · 请稍候";
  } else if (pending) {
    state = "pending";
    text = "有更改待自动保存…";
  }
  summary.className = `structure-save-summary is-${state}`;
  summary.textContent = text;
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
    const remove = makeIconButton("delete-major", "×", "删除专业", true);
    remove.disabled = locked;
    row.append(drag, name, status, remove);
    row._nameInput = name;
    row.dataset.entityKind = "major";
    row.dataset.saveState = "saved";
    row.dataset.originalName = major.name;
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
    capacity.step = "1";
    capacity.inputMode = "numeric";
    capacity.value = String(group.total_capacity);
    capacity.disabled = locked;
    capacity.setAttribute("aria-label", "教学组总容量");
    capacityWrap.append(capacity);
    const status = makeEntityStatus(group.active, locked, "toggle-group-status");
    const remove = makeIconButton("delete-group", "×", "删除教学组", true);
    remove.disabled = locked;
    row.append(drag, name, capacityWrap, status, remove);
    row._nameInput = name;
    row._capacityInput = capacity;
    row.dataset.entityKind = "group";
    row.dataset.saveState = "saved";
    row.dataset.originalName = group.name;
    row.dataset.originalCapacity = String(group.total_capacity);
    row.dataset.active = String(Boolean(group.active));
    return row;
  });
  adminEls.groupEditor.replaceChildren(...rows);
}

function renderQuotaMatrix(data, locked, majors = data.majors, groups = data.groups) {
  if (!majors.length || !groups.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state quota-empty-state";
    empty.textContent = "当前筛选条件下没有可显示的配额单元格";
    adminEls.quotaMatrix.replaceChildren(empty);
    adminEls.quotaBatchCount.textContent = "0 个可编辑单元格";
    return;
  }
  const table = document.createElement("table");
  table.className = "quota-table";
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  const corner = document.createElement("th");
  corner.textContent = "专业 / 教学组";
  headRow.append(corner);
  for (const group of groups) {
    const th = document.createElement("th");
    th.textContent = `${group.name}（总 ${group.total_capacity}）`;
    headRow.append(th);
  }
  head.append(headRow);
  const body = document.createElement("tbody");
  const quotaMap = new Map(data.quotas.map((quota) => [`${quota.major_id}:${quota.group_id}`, quota]));
  for (const [rowIndex, major] of majors.entries()) {
    const row = document.createElement("tr");
    const majorCell = document.createElement("td");
    majorCell.textContent = major.name;
    row.append(majorCell);
    for (const [columnIndex, group] of groups.entries()) {
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
      input.step = "1";
      input.inputMode = "numeric";
      input.value = String(quota.capacity);
      input.disabled = locked || !major.active || !group.active;
      input.dataset.majorId = String(major.id);
      input.dataset.groupId = String(group.id);
      input.dataset.original = String(quota.capacity);
      input.dataset.rowIndex = String(rowIndex);
      input.dataset.columnIndex = String(columnIndex);
      input.dataset.saveState = "saved";
      input.setAttribute("aria-label", `${major.name}分配到${group.name}的配额`);
      wrapper.append(selected, slash, input);
      cell.append(wrapper);
      row.append(cell);
    }
    body.append(row);
  }
  table.append(head, body);
  adminEls.quotaMatrix.replaceChildren(table);
  const editableCount = adminEls.quotaMatrix.querySelectorAll("input[data-major-id]:not(:disabled)").length;
  adminEls.quotaBatchCount.textContent = `${editableCount} 个可编辑单元格`;
}

function filteredStructureEntities(data) {
  const majorQuery = structureSearchValue(adminEls.majorSearch);
  const groupQuery = structureSearchValue(adminEls.groupSearch);
  const majors = majorQuery
    ? data.majors.filter((major) => major.name.toLocaleLowerCase("zh-CN").includes(majorQuery))
    : data.majors;
  const groups = groupQuery
    ? data.groups.filter((group) => group.name.toLocaleLowerCase("zh-CN").includes(groupQuery))
    : data.groups;
  return { majors, groups };
}

function renderStructure(data, locked) {
  adminEls.majorEditor.dataset.activityId = String(data.settings.activity_id);
  adminEls.groupEditor.dataset.activityId = String(data.settings.activity_id);
  adminEls.quotaMatrix.dataset.activityId = String(data.settings.activity_id);
  const filtered = filteredStructureEntities(data);
  adminEls.majorCount.textContent = `${data.majors.length} 个专业`;
  adminEls.groupCount.textContent = `${data.groups.length} 个教学组`;
  adminEls.majorVisibleCount.textContent = filtered.majors.length === data.majors.length
    ? "显示全部"
    : `显示 ${filtered.majors.length} / ${data.majors.length}`;
  adminEls.groupVisibleCount.textContent = filtered.groups.length === data.groups.length
    ? "显示全部"
    : `显示 ${filtered.groups.length} / ${data.groups.length}`;
  adminEls.structureSaveSummary.dataset.locked = String(locked);
  document.querySelectorAll("#add-major-form input, #add-major-form button, #add-group-form input, #add-group-form button").forEach((element) => { element.disabled = locked; });
  renderMajorEditor(filtered.majors, locked);
  renderGroupEditor(filtered.groups, locked);
  renderQuotaMatrix(data, locked, filtered.majors, filtered.groups);
  renderStructureSaveSummary();
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

function clearAllRevealedActivationCodes() {
  for (const timer of adminState.activationHideTimers.values()) clearTimeout(timer);
  adminState.activationHideTimers.clear();
  adminState.revealedActivationCodes.clear();
  scrubRevealedActivationCodeDom();
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
  return result?.credential?.activation_code || null;
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
    const revealable = student.activation_code_revealable === true;
    value.textContent = revealedCode || (revealable ? "••••••" : "不可显示");
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
      : "当前学生没有可显示的个人激活码";
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
  if (window.matchMedia("(max-width: 700px)").matches && !["overview", "students"].includes(viewName)) {
    viewName = "overview";
  }
  if (adminState.currentView === "students" && viewName !== "students") {
    clearAllRevealedActivationCodes();
  }
  adminState.currentView = viewName;
  document.querySelectorAll(".admin-nav__item").forEach((button) => button.classList.toggle("is-active", button.dataset.view === viewName));
  document.querySelectorAll(".admin-view").forEach((view) => view.classList.add("is-hidden"));
  document.querySelector(`#view-${viewName}`).classList.remove("is-hidden");
  if (viewName !== "overview") {
    stopRosterAutoScroll();
    stopLiveFeedAutoScroll();
    stopWaitingFeedAutoScroll();
    loadDashboard({ quiet: true });
  } else {
    renderGroupProgress(adminState.dashboard?.groups || [], { force: true });
    renderUnselectedList({ force: true });
    renderLiveSelectionFeed(adminState.dashboard?.recent_selections || [], { force: true });
    renderWaitingStudentFeed(adminState.dashboard?.entered_students || [], { force: true });
  }
}

document.querySelectorAll(".admin-nav__item").forEach((button) => button.addEventListener("click", () => switchAdminView(button.dataset.view)));

const mobileAdminQuery = window.matchMedia("(max-width: 700px)");
mobileAdminQuery.addEventListener?.("change", (event) => {
  if (event.matches && !["overview", "students"].includes(adminState.currentView)) switchAdminView("overview");
});

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
    await loadDashboard({ afterMutation: true });
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
  const absentRoster = absentStudents.map((student) => ({
    name: student.name,
    major_name: student.major_name,
  }));
  const startMessage = presence.absent > 0
    ? `${readinessMessage}\n\n还有 ${presence.absent} 名同学未进入候场。名单已按专业整理如下；仍可继续开始。确认后，全体学生端将同步进入 10 秒倒计时，倒计时结束后同时开放提交。`
    : `${readinessMessage}全部 ${presence.online} 名同学均已进入候场。确认后，全体学生端将同步进入 10 秒倒计时，倒计时结束后同时开放提交。`;
  const confirmed = await confirmDanger(
    phase === "open" ? "关闭学生抢选" : "开始全体 10 秒倒计时",
    phase === "open"
      ? "关闭后学生无法继续提交，管理员仍可补位和撤销。"
      : startMessage,
    { roster: phase === "open" ? [] : absentRoster },
  );
  if (!confirmed) return;
  let enteredForCountdown = false;
  if (phase !== "open" && !boardIsPresentation()) {
    enteredForCountdown = true;
    enterCountdownPresentation();
  }
  adminState.phaseActionPending = true;
  adminEls.boardStart.disabled = true;
  try {
    if (phase === "open") {
      await adminApi("/api/admin/status", {
        method: "POST",
        body: JSON.stringify({ status: "closed" }),
        activityId,
      });
    } else {
      const requestStartedAt = Date.now();
      const countdownSnapshot = await adminApi("/api/admin/countdown", {
        method: "POST",
        body: JSON.stringify({}),
        activityId,
      });
      adminState.dashboardClockSample = { requestStartedAt, responseReceivedAt: Date.now() };
      synchronizeServerClock(countdownSnapshot);
      const countdownDashboard = mergeDashboardStatusSnapshot(countdownSnapshot);
      if (countdownDashboard) {
        adminState.dashboard = countdownDashboard;
        renderDashboard(countdownDashboard);
      }
    }
    showAdminToast(phase === "open" ? "抢选已关闭" : "10 秒同步倒计时已开始", "success");
    await loadDashboard({ afterMutation: true });
  } catch (error) {
    if (enteredForCountdown) await exitBoardFullscreen().catch(() => leavePresentationMode());
    showAdminToast(error.message, "error");
  } finally {
    adminState.phaseActionPending = false;
    if (adminState.dashboard) renderBoardStage(adminState.dashboard, dashboardPhase(), normalizedPresence());
  }
}

adminEls.boardStart.addEventListener("click", handleSelectionPhaseAction);

adminEls.unselectedSearch.addEventListener("input", renderUnselectedList);
adminEls.rosterSearch.addEventListener("input", () => renderStudentRoster());

const liveBoard = document.querySelector("#live-board");
const fullscreenButton = document.querySelector("#fullscreen-board");
const reducedMotionPreference = window.matchMedia("(prefers-reduced-motion: reduce)");
reducedMotionPreference.addEventListener?.("change", () => {
  if (adminState.dashboard && adminState.currentView === "overview") {
    renderUnselectedList({ force: true });
    renderGroupProgress(adminState.dashboard.groups || [], { force: true });
    renderLiveSelectionFeed(adminState.dashboard.recent_selections || [], { force: true });
    renderWaitingStudentFeed(adminState.dashboard.entered_students || [], { force: true });
  }
});

function leavePresentationMode() {
  liveBoard.classList.remove("is-presentation");
  document.body.classList.remove("is-presentation");
  stopRosterAutoScroll();
  stopLiveFeedAutoScroll();
  stopWaitingFeedAutoScroll();
  stopGroupProgressAutoScroll();
}

function enterPresentationFallback() {
  liveBoard.classList.add("is-presentation");
  document.body.classList.add("is-presentation");
}

function refreshBoardLoopsForLayout() {
  if (!adminState.dashboard || adminState.currentView !== "overview") return;
  renderGroupProgress(adminState.dashboard.groups || [], { force: true });
  renderLiveSelectionFeed(adminState.dashboard.recent_selections || [], { force: true });
  renderWaitingStudentFeed(adminState.dashboard.entered_students || [], { force: true });
  renderUnselectedList({ force: true });
}

function enterCountdownPresentation() {
  if (adminState.currentView !== "overview") switchAdminView("overview");
  if (!boardIsPresentation()) enterPresentationFallback();
  updateFullscreenButton();
}

function enforceCountdownPresentation(phase = dashboardPhase()) {
  if (phase !== "countdown" || boardIsPresentation()) return;
  enterCountdownPresentation();
}

function shouldUsePresentationFallback() {
  return window.matchMedia("(max-width: 700px)").matches || typeof liveBoard.requestFullscreen !== "function";
}

function updateFullscreenButton() {
  fullscreenButton.textContent = document.fullscreenElement || liveBoard.classList.contains("is-presentation") ? "退出全屏" : "⛶ 全屏展示";
  refreshBoardLoopsForLayout();
}

async function exitBoardFullscreen() {
  if (document.fullscreenElement) await document.exitFullscreen();
  else leavePresentationMode();
  updateFullscreenButton();
}

async function enterBoardFullscreen() {
  switchAdminView("overview");
  try {
    if (document.fullscreenElement || liveBoard.classList.contains("is-presentation")) return;
    if (shouldUsePresentationFallback()) {
      enterPresentationFallback();
    } else {
      await liveBoard.requestFullscreen();
    }
  } catch (_) {
    enterPresentationFallback();
    showAdminToast("浏览器未授予原生全屏，已切换为页面大屏模式", "success");
  }
  updateFullscreenButton();
}

fullscreenButton.addEventListener("click", async () => {
  if (document.fullscreenElement || liveBoard.classList.contains("is-presentation")) {
    await exitBoardFullscreen();
    return;
  }
  await enterBoardFullscreen();
});

adminEls.statusButton.addEventListener("click", enterBoardFullscreen);

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
    await loadDashboard({ afterMutation: true });
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
    await loadDashboard({ afterMutation: true });
  } catch (error) { showAdminToast(error.message, "error"); }
});

window.addEventListener("resize", () => {
  clearTimeout(adminState.boardLayoutTimer);
  adminState.boardLayoutTimer = setTimeout(refreshBoardLoopsForLayout, 120);
});

function entityRowSaveKey(row) {
  return `${row.dataset.entityKind}:${row.dataset.id}`;
}

function notifyEntityStructureSaveSummary() {
  if (adminEls.structureSaveSummary && typeof document.querySelector === "function") {
    renderStructureSaveSummary();
  }
}

function setEntitySaveState(row, state, text) {
  if (!row) return;
  row.dataset.saveState = state;
  row.title = state === "error" ? text : "";
  notifyEntityStructureSaveSummary();
}

function entityRowHasChanges(row, { includeCapacity = true } = {}) {
  if (row._nameInput.value.trim() !== row.dataset.originalName) return true;
  return includeCapacity && row.dataset.entityKind === "group"
    && row._capacityInput.value !== row.dataset.originalCapacity;
}

async function persistEntityRow(row, { refreshAfter = false, includeCapacity = false } = {}) {
  if (!row?.isConnected) return;
  const key = entityRowSaveKey(row);
  clearTimeout(adminState.entitySaveTimers.get(key));
  adminState.entitySaveTimers.delete(key);
  if (row.dataset.saving === "true") {
    row.dataset.saveQueued = "true";
    if (includeCapacity) row.dataset.saveQueuedCapacity = "true";
    if (refreshAfter) row.dataset.saveQueuedRefresh = "true";
    return;
  }

  const submittedName = row._nameInput.value.trim();
  const nameChanged = submittedName !== row.dataset.originalName;
  if (nameChanged && !submittedName) {
    row._nameInput.setCustomValidity("名称不能为空");
    row._nameInput.reportValidity();
    setEntitySaveState(row, "error", "名称不能为空");
    return;
  }
  row._nameInput.setCustomValidity("");

  let submittedCapacity = null;
  const capacityChanged = includeCapacity
    && row.dataset.entityKind === "group"
    && row._capacityInput.value !== row.dataset.originalCapacity;
  if (capacityChanged) {
    const rawCapacity = row._capacityInput.value.trim();
    if (!rawCapacity) {
      row._capacityInput.setCustomValidity("教学组容量不能为空");
      row._capacityInput.reportValidity();
      setEntitySaveState(row, "error", "容量不能为空");
      return;
    }
    submittedCapacity = Number(rawCapacity);
    if (!Number.isInteger(submittedCapacity) || submittedCapacity < 0 || submittedCapacity > 1000) {
      row._capacityInput.setCustomValidity("请输入 0 至 1000 的整数");
      row._capacityInput.reportValidity();
      setEntitySaveState(row, "error", "容量格式有误");
      return;
    }
    row._capacityInput.setCustomValidity("");
  }

  if (!nameChanged && !capacityChanged) {
    setEntitySaveState(row, "saved", "已保存");
    if (refreshAfter && adminState.dashboard) {
      adminState.structureFingerprint = "";
      renderDashboard(adminState.dashboard);
    }
    return;
  }

  const id = Number(row.dataset.id);
  const editor = row.dataset.entityKind === "major" ? adminEls.majorEditor : adminEls.groupEditor;
  const activityId = Number(editor.dataset.activityId);
  const uiHasMovedFromRequestActivity = () => {
    const dashboardActivityId = Number(adminState.dashboard?.settings?.activity_id);
    const editorActivityId = Number(editor.dataset.activityId);
    return Number.isInteger(dashboardActivityId)
      && Number.isInteger(editorActivityId)
      && dashboardActivityId !== activityId
      && editorActivityId !== activityId;
  };
  const payload = {};
  if (nameChanged) payload.name = submittedName;
  if (capacityChanged) payload.total_capacity = submittedCapacity;
  let activityCasConflict = false;
  let activityCasRequiresRefresh = false;
  row.dataset.saving = "true";
  row.setAttribute("aria-busy", "true");
  setEntitySaveState(row, "saving", "保存中…");
  try {
    const result = await adminApi(`/api/admin/${row.dataset.entityKind === "major" ? "majors" : "groups"}/${id}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
      activityId,
    });
    if (nameChanged) row.dataset.originalName = submittedName;
    if (capacityChanged) {
      const canonicalCapacity = String(submittedCapacity);
      row.dataset.originalCapacity = canonicalCapacity;
      if (Number(row._capacityInput.value) === submittedCapacity) {
        row._capacityInput.value = canonicalCapacity;
      }
    }
    setEntitySaveState(row, "saved", "已自动保存");
    if (result?.quotas_adjusted || result?.quota_adjustments?.length) {
      showAdminToast("教学组容量已保存，专业配额已按已选下限自动重算", "success");
    }
    await loadDashboard({ quiet: true, afterMutation: true });
  } catch (error) {
    activityCasConflict = error.status === 409 && error.message.includes("当前活动已经变化");
    if (activityCasConflict) {
      activityCasRequiresRefresh = !uiHasMovedFromRequestActivity();
      if (activityCasRequiresRefresh) {
        for (const timer of adminState.entitySaveTimers.values()) clearTimeout(timer);
        adminState.entitySaveTimers.clear();
      }
      delete row.dataset.saveQueued;
      delete row.dataset.saveQueuedCapacity;
      delete row.dataset.saveQueuedRefresh;
      row._nameInput.value = row.dataset.originalName;
      if (row.dataset.entityKind === "group") row._capacityInput.value = row.dataset.originalCapacity;
    } else {
      if (nameChanged && row._nameInput.value.trim() === submittedName) row._nameInput.value = row.dataset.originalName;
      if (
        capacityChanged
        && Number(row._capacityInput.value) === submittedCapacity
      ) row._capacityInput.value = row.dataset.originalCapacity;
    }
    setEntitySaveState(row, "error", "保存失败 · 已还原");
    showAdminToast(`自动保存失败：${error.message}`, "error");
    if (activityCasRequiresRefresh) {
      await loadDashboard({ quiet: true, afterMutation: true });
      if (uiHasMovedFromRequestActivity()) activityCasRequiresRefresh = false;
    }
  } finally {
    delete row.dataset.saving;
    row.removeAttribute("aria-busy");
    const capacityStillDirty = row.dataset.entityKind === "group"
      && row._capacityInput.value !== row.dataset.originalCapacity;
    const queuedCapacity = row.dataset.saveQueuedCapacity === "true" || capacityStillDirty;
    const queued = !activityCasConflict
      && (row.dataset.saveQueued === "true" || entityRowHasChanges(row, { includeCapacity: queuedCapacity }));
    const queuedRefresh = refreshAfter || row.dataset.saveQueuedRefresh === "true";
    delete row.dataset.saveQueued;
    delete row.dataset.saveQueuedCapacity;
    delete row.dataset.saveQueuedRefresh;
    if (queued && row.isConnected) {
      scheduleEntityRowSave(row, 0, { refreshAfter: queuedRefresh, includeCapacity: queuedCapacity });
    }
    notifyEntityStructureSaveSummary();
    if (!activityCasConflict || activityCasRequiresRefresh) {
      renderLatestStructureAfterAutosave({ forceStructure: activityCasRequiresRefresh });
    }
  }
}

function scheduleEntityRowSave(row, delay = 360, { refreshAfter = false, includeCapacity = false } = {}) {
  const key = entityRowSaveKey(row);
  const capacityDirty = row.dataset.entityKind === "group"
    && row._capacityInput.value !== row.dataset.originalCapacity;
  const scheduledCapacity = includeCapacity
    || capacityDirty
    || row.dataset.saveScheduledCapacity === "true";
  const scheduledRefresh = refreshAfter
    || scheduledCapacity
    || row.dataset.saveScheduledRefresh === "true";
  if (scheduledCapacity) row.dataset.saveScheduledCapacity = "true";
  if (scheduledRefresh) row.dataset.saveScheduledRefresh = "true";
  clearTimeout(adminState.entitySaveTimers.get(key));
  adminState.entitySaveTimers.set(key, setTimeout(() => {
    adminState.entitySaveTimers.delete(key);
    const pendingCapacity = row.dataset.saveScheduledCapacity === "true";
    const pendingRefresh = row.dataset.saveScheduledRefresh === "true";
    delete row.dataset.saveScheduledCapacity;
    delete row.dataset.saveScheduledRefresh;
    persistEntityRow(row, { refreshAfter: pendingRefresh, includeCapacity: pendingCapacity });
  }, delay));
}

function wireEntityAutosave(editor) {
  editor.addEventListener("compositionstart", (event) => {
    const input = event.target.closest(".entity-row input");
    if (input === input?.closest(".entity-row")?._nameInput) input.dataset.composing = "true";
  });
  editor.addEventListener("compositionend", (event) => {
    const input = event.target.closest(".entity-row input");
    const row = input?.closest(".entity-row");
    if (!row || input !== row._nameInput) return;
    delete input.dataset.composing;
    setEntitySaveState(row, "pending", "等待自动保存");
    scheduleEntityRowSave(row);
  });
  editor.addEventListener("input", (event) => {
    const input = event.target.closest(".entity-row input");
    const row = input?.closest(".entity-row");
    if (!row) return;
    input.setCustomValidity("");
    if (input === row._nameInput) {
      setEntitySaveState(row, "pending", input.dataset.composing === "true" || event.isComposing ? "正在输入…" : "等待自动保存");
      if (input.dataset.composing !== "true" && !event.isComposing) scheduleEntityRowSave(row);
    } else {
      if (!input.value.trim()) {
        const key = entityRowSaveKey(row);
        clearTimeout(adminState.entitySaveTimers.get(key));
        adminState.entitySaveTimers.delete(key);
        input.setCustomValidity("教学组容量不能为空");
        setEntitySaveState(row, "error", "容量不能为空");
        return;
      }
      setEntitySaveState(row, "pending", "等待自动保存容量");
      scheduleEntityRowSave(row, 650, { refreshAfter: true, includeCapacity: true });
    }
  });
  editor.addEventListener("focusout", (event) => {
    const row = event.target.closest(".entity-row");
    if (!row) return;
    const includeCapacity = event.target === row._capacityInput;
    scheduleEntityRowSave(row, 0, { refreshAfter: true, includeCapacity });
  });
  editor.addEventListener("keydown", (event) => {
    const input = event.target.closest(".entity-row input");
    if (!input || event.key !== "Enter") return;
    event.preventDefault();
    input.blur();
  });
}

wireEntityAutosave(adminEls.majorEditor);
wireEntityAutosave(adminEls.groupEditor);

for (const searchInput of [adminEls.majorSearch, adminEls.groupSearch]) {
  searchInput.addEventListener("input", () => {
    adminState.structureFingerprint = "";
    if (adminState.dashboard && !structureEditorAutosaveBusy()) {
      renderStructure(
        adminState.dashboard,
        dashboardPhase(adminState.dashboard) === "countdown" || dashboardPhase(adminState.dashboard) === "open",
      );
    }
  });
}

adminEls.majorEditor.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest(".entity-row");
  const id = Number(row.dataset.id);
  const activityId = Number(adminEls.majorEditor.dataset.activityId);
  try {
    if (button.dataset.action === "toggle-major-status") {
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
    await loadDashboard({ afterMutation: true });
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
    if (button.dataset.action === "toggle-group-status") {
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
    await loadDashboard({ afterMutation: true });
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

function quotaInputKey(input) {
  return `${input.dataset.majorId}:${input.dataset.groupId}`;
}

function notifyQuotaStructureSaveSummary() {
  if (adminEls.structureSaveSummary && typeof document?.querySelector === "function") {
    renderStructureSaveSummary();
  }
}

async function persistQuotaInput(input) {
  if (!input?.isConnected) return;
  const key = quotaInputKey(input);
  clearTimeout(adminState.quotaSaveTimers.get(key));
  adminState.quotaSaveTimers.delete(key);
  if (input.dataset.saving === "true") {
    input.dataset.saveQueued = "true";
    return;
  }
  const rawValue = input.value.trim();
  if (!rawValue) {
    input.setCustomValidity("配额不能为空");
    input.reportValidity();
    input.dataset.saveState = "error";
    input.dataset.pending = "true";
    input.title = "配额不能为空";
    notifyQuotaStructureSaveSummary();
    return;
  }
  const nextValue = Number(rawValue);
  if (!Number.isInteger(nextValue) || nextValue < 0 || nextValue > 1000) {
    input.setCustomValidity("请输入 0 至 1000 的整数");
    input.reportValidity();
    input.dataset.saveState = "error";
    notifyQuotaStructureSaveSummary();
    return;
  }
  input.setCustomValidity("");
  if (String(nextValue) === input.dataset.original) {
    input.value = String(nextValue);
    delete input.dataset.pending;
    delete input.dataset.saveQueued;
    input.dataset.saveState = "saved";
    input.title = "";
    notifyQuotaStructureSaveSummary();
    return;
  }
  const activityId = Number(adminEls.quotaMatrix.dataset.activityId);
  const submittedValue = String(nextValue);
  let activityCasConflict = false;
  input.dataset.saving = "true";
  input.dataset.saveState = "saving";
  input.setAttribute("aria-busy", "true");
  notifyQuotaStructureSaveSummary();
  try {
    await adminApi(`/api/admin/quotas/${input.dataset.majorId}/${input.dataset.groupId}`, { method: "PUT", body: JSON.stringify({ capacity: nextValue }), activityId });
    input.dataset.original = submittedValue;
    const currentRawValue = input.value.trim();
    if (currentRawValue && Number(currentRawValue) === nextValue) {
      input.value = submittedValue;
      delete input.dataset.pending;
      input.title = "";
    } else {
      input.dataset.pending = "true";
      input.title = "按回车或离开输入框保存配额";
    }
    input.dataset.saveState = "saved";
    showAdminToast("配额已保存", "success");
    await loadDashboard({ quiet: true, afterMutation: true });
  } catch (error) {
    activityCasConflict = error.status === 409 && error.message.includes("当前活动已经变化");
    if (activityCasConflict) {
      for (const timer of adminState.quotaSaveTimers.values()) clearTimeout(timer);
      adminState.quotaSaveTimers.clear();
      delete input.dataset.saveQueued;
      input.value = input.dataset.original;
      delete input.dataset.pending;
      input.title = "";
    } else if (input.value === submittedValue) {
      input.value = input.dataset.original;
      delete input.dataset.pending;
      input.title = "";
    }
    input.dataset.saveState = "error";
    showAdminToast(error.message, "error");
    if (activityCasConflict) await loadDashboard({ quiet: true, afterMutation: true });
  } finally {
    const queued = !activityCasConflict
      && input.dataset.saveQueued === "true"
      && input.value !== input.dataset.original;
    delete input.dataset.saveQueued;
    delete input.dataset.saving;
    input.removeAttribute("aria-busy");
    if (queued && input.isConnected) scheduleQuotaSave(input, 0);
    notifyQuotaStructureSaveSummary();
    renderLatestStructureAfterAutosave({ forceStructure: activityCasConflict });
  }
}

function scheduleQuotaSave(input, delay = 650) {
  const key = quotaInputKey(input);
  clearTimeout(adminState.quotaSaveTimers.get(key));
  adminState.quotaSaveTimers.set(key, setTimeout(() => {
    adminState.quotaSaveTimers.delete(key);
    persistQuotaInput(input);
  }, delay));
}

function quotaMatrixInputAt(rowIndex, columnIndex) {
  return adminEls.quotaMatrix.querySelector(
    `input[data-row-index="${rowIndex}"][data-column-index="${columnIndex}"]`,
  );
}

async function applyQuotaBatch(capacityByInput, label) {
  const entries = [...capacityByInput.entries()];
  if (!entries.length) {
    showAdminToast("当前筛选结果中没有可编辑的配额", "error");
    return;
  }
  if (entries.some(([input]) => input.dataset.saving === "true")) {
    showAdminToast("仍有配额正在保存，请稍候再批量操作", "error");
    return;
  }
  const activityId = Number(adminEls.quotaMatrix.dataset.activityId);
  const snapshots = entries.map(([input]) => ({
    input,
    value: input.value,
    original: input.dataset.original,
    key: quotaInputKey(input),
    submitted: String(capacityByInput.get(input)),
  }));
  const inputsToReschedule = new Set();
  let activityCasConflict = false;
  for (const snapshot of snapshots) {
    clearTimeout(adminState.quotaSaveTimers.get(snapshot.key));
    adminState.quotaSaveTimers.delete(snapshot.key);
  }
  for (const [input, capacity] of entries) {
    input.value = String(capacity);
    input.dataset.pending = "true";
    input.dataset.saving = "true";
    input.dataset.saveState = "saving";
    input.setAttribute("aria-busy", "true");
  }
  notifyQuotaStructureSaveSummary();
  try {
    await adminApi("/api/admin/quotas/batch", {
      method: "PUT",
      body: JSON.stringify({
        quotas: entries.map(([input, capacity]) => ({
          major_id: Number(input.dataset.majorId),
          group_id: Number(input.dataset.groupId),
          capacity,
        })),
      }),
      activityId,
    });
    for (const [input, capacity] of entries) {
      const submitted = String(capacity);
      input.dataset.original = submitted;
      if (input.value === submitted) {
        input.dataset.saveState = "saved";
        delete input.dataset.pending;
        input.title = "";
      } else {
        input.dataset.pending = "true";
        input.dataset.saveState = "pending";
        input.title = "等待自动保存最新配额";
        inputsToReschedule.add(input);
      }
    }
    showAdminToast(`${label}已一次性保存 ${entries.length} 个配额`, "success");
    await loadDashboard({ quiet: true, afterMutation: true });
  } catch (error) {
    activityCasConflict = error.status === 409 && error.message.includes("当前活动已经变化");
    for (const snapshot of snapshots) {
      if (activityCasConflict) {
        snapshot.input.value = snapshot.original;
        snapshot.input.dataset.saveState = "error";
        delete snapshot.input.dataset.pending;
        snapshot.input.title = "活动已切换，未重放旧活动编辑";
        continue;
      }
      const latestValue = snapshot.input.value === snapshot.submitted
        ? snapshot.value
        : snapshot.input.value;
      snapshot.input.value = latestValue;
      if (latestValue !== snapshot.original) {
        snapshot.input.dataset.pending = "true";
        snapshot.input.dataset.saveState = "pending";
        snapshot.input.title = "批量保存失败，等待自动保存原编辑";
        inputsToReschedule.add(snapshot.input);
      } else {
        snapshot.input.dataset.saveState = "error";
        delete snapshot.input.dataset.pending;
        snapshot.input.title = "批量保存失败，未改变原配额";
      }
    }
    showAdminToast(`批量保存失败：${error.message}`, "error");
    if (activityCasConflict) await loadDashboard({ quiet: true, afterMutation: true });
  } finally {
    for (const [input] of entries) {
      delete input.dataset.saving;
      input.removeAttribute("aria-busy");
    }
    for (const input of inputsToReschedule) {
      if (input.isConnected) scheduleQuotaSave(input, 0);
    }
    notifyQuotaStructureSaveSummary();
    renderLatestStructureAfterAutosave({ forceStructure: activityCasConflict });
  }
}

adminEls.quotaMatrix.addEventListener("input", (event) => {
  const input = event.target.closest("input[data-major-id]");
  if (!input) return;
  if (!input.value.trim()) {
    const key = quotaInputKey(input);
    clearTimeout(adminState.quotaSaveTimers.get(key));
    adminState.quotaSaveTimers.delete(key);
    input.setCustomValidity("配额不能为空");
    input.dataset.pending = "true";
    input.dataset.saveState = "error";
    input.title = "配额不能为空";
    notifyQuotaStructureSaveSummary();
    return;
  }
  input.setCustomValidity("");
  input.dataset.pending = String(input.value !== input.dataset.original);
  input.dataset.saveState = input.dataset.pending === "true" ? "pending" : "saved";
  input.title = input.dataset.pending === "true" ? "按回车或离开输入框保存配额" : "";
  notifyQuotaStructureSaveSummary();
  scheduleQuotaSave(input);
});

adminEls.quotaMatrix.addEventListener("change", (event) => {
  const input = event.target.closest("input[data-major-id]");
  if (input) scheduleQuotaSave(input, 0);
});

adminEls.quotaMatrix.addEventListener("focusout", (event) => {
  const input = event.target.closest("input[data-major-id]");
  if (input) scheduleQuotaSave(input, 0);
});

adminEls.quotaMatrix.addEventListener("keydown", (event) => {
  const input = event.target.closest("input[data-major-id]");
  if (!input || event.key !== "Enter") return;
  event.preventDefault();
  scheduleQuotaSave(input, 0);
  const next = quotaMatrixInputAt(
    Number(input.dataset.rowIndex) + (event.shiftKey ? -1 : 1),
    Number(input.dataset.columnIndex),
  );
  next?.focus();
  next?.select();
});

function quotaClipboardRows(clipboard) {
  const withoutTerminalLineEndings = clipboard.replace(/(?:\r\n|\r|\n)$/, "");
  return withoutTerminalLineEndings.split(/\r\n|\r|\n/).map((line) => line.split("\t"));
}

adminEls.quotaMatrix.addEventListener("paste", async (event) => {
  const start = event.target.closest("input[data-major-id]");
  const clipboard = event.clipboardData?.getData("text/plain") || "";
  if (!start || (!clipboard.includes("\t") && !/[\r\n]/.test(clipboard))) return;
  event.preventDefault();
  const rows = quotaClipboardRows(clipboard);
  const capacityByInput = new Map();
  for (const [rowOffset, values] of rows.entries()) {
    for (const [columnOffset, rawValue] of values.entries()) {
      const input = quotaMatrixInputAt(
        Number(start.dataset.rowIndex) + rowOffset,
        Number(start.dataset.columnIndex) + columnOffset,
      );
      const normalizedValue = rawValue.trim();
      const capacity = Number(normalizedValue);
      if (!input || input.disabled || !normalizedValue || !Number.isInteger(capacity) || capacity < 0 || capacity > 1000) {
        showAdminToast("粘贴区域超出当前矩阵，或包含空单元格、0 至 1000 之外的非整数", "error");
        return;
      }
      capacityByInput.set(input, capacity);
    }
  }
  if (!await confirmDanger(
    "批量粘贴配额",
    `将从当前单元格起一次性保存 ${capacityByInput.size} 个配额。系统会整体校验，任一单元格不合法则全部不修改。`,
  )) return;
  await applyQuotaBatch(capacityByInput, "粘贴配额");
});

adminEls.quotaBatchForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const capacity = Number(adminEls.quotaBatchValue.value);
  if (!Number.isInteger(capacity) || capacity < 0 || capacity > 1000) {
    adminEls.quotaBatchValue.setCustomValidity("请输入 0 至 1000 的整数");
    adminEls.quotaBatchValue.reportValidity();
    return;
  }
  adminEls.quotaBatchValue.setCustomValidity("");
  const inputs = [...adminEls.quotaMatrix.querySelectorAll("input[data-major-id]:not(:disabled)")];
  if (!inputs.length) {
    showAdminToast("当前筛选结果中没有可编辑的配额", "error");
    return;
  }
  if (!await confirmDanger(
    "批量设置配额",
    `确认将当前筛选出的 ${inputs.length} 个配额统一设为 ${capacity}？系统会整体校验并一次性保存。`,
  )) return;
  await applyQuotaBatch(new Map(inputs.map((input) => [input, capacity])), "批量配额");
});

adminEls.settingsForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const values = Object.fromEntries(new FormData(adminEls.settingsForm).entries());
  const activityId = Number(adminEls.settingsForm.dataset.activityId || adminState.dashboard.settings.activity_id);
  try {
    await adminApi("/api/admin/settings", { method: "PATCH", body: JSON.stringify(values), activityId });
    delete adminEls.settingsForm.dataset.activityId;
    showAdminToast("学生端访问地址已保存", "success");
    await loadDashboard({ afterMutation: true });
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
    await loadDashboard({ afterMutation: true });
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
    const createdMajors = (result.majors_created || []).map((major) => typeof major === "string" ? major : major?.name).filter(Boolean);
    const reactivatedMajors = (result.majors_reactivated || []).map((major) => typeof major === "string" ? major : major?.name).filter(Boolean);
    const majorNotes = [];
    if (createdMajors.length) majorNotes.push(`已自动新增专业：${createdMajors.join("、")}（新专业配额默认为 0，请前往“专业与教学组”设置配额）`);
    if (reactivatedMajors.length) majorNotes.push(`已重新启用专业：${reactivatedMajors.join("、")}`);
    adminEls.importResult.className = "import-result is-success";
    adminEls.importResult.textContent = `已完成 ${files.length} 个文件：新增 ${result.created || 0} 人，更新 ${result.updated || 0} 人，停用 ${result.deactivated || 0} 人。${majorNotes.length ? `${majorNotes.join("；")}。` : ""}个人激活码使用证件号后 6 位。`;
    adminEls.importForm.reset();
    delete adminEls.importForm.dataset.activityId;
    adminEls.importFileName.textContent = "可多选 CSV / XLS / XLSX";
    adminState.structureFingerprint = "";
    showAdminToast(createdMajors.length ? `名单导入成功，已自动新增 ${createdMajors.length} 个专业，请设置配额` : "学生名单导入成功", "success");
    await loadDashboard({ afterMutation: true });
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
  [adminEls.exportSelections, "选择记录.xlsx", "选择记录 Excel 已导出"],
  [adminEls.exportCompleteResults, "本场完整结果.xlsx", "完整名单与抢选结果 Excel 已导出"],
  [adminEls.exportUnselected, "未选学生名单.xlsx", "未选学生名单 Excel 已导出"],
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
    await loadDashboard({ afterMutation: true });
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
      if (!activationCode) throw new Error("服务未返回可显示的激活码，请刷新后重试");
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
    await loadDashboard({ afterMutation: true });
  } catch (error) {
    button.disabled = false;
    showAdminToast(error.message, "error");
  }
});

document.addEventListener("visibilitychange", () => {
  if (document.hidden) {
    clearAllRevealedActivationCodes();
    return;
  }
  if (!adminState.csrf) return;
  if (adminState.currentView === "overview") {
    adminState.rosterFingerprint = "";
    adminState.liveFeedFingerprint = "";
    adminState.waitingFeedFingerprint = "";
    adminState.groupProgressFingerprint = "";
    loadDashboard({ quiet: true });
  } else if (adminState.currentView === "students" && mobileAdminQuery.matches) {
    loadDashboardStatusSnapshot({ quiet: true });
  }
});

loadAdminSession();
