"use strict";

const adminState = {
  csrf: "",
  dashboard: null,
  currentView: "overview",
  pollTimer: null,
  messageTimer: null,
  loading: false,
  generatedCredentials: [],
};

const adminEls = {
  loginView: document.querySelector("#admin-login-view"),
  loginForm: document.querySelector("#admin-login-form"),
  loginError: document.querySelector("#admin-login-error"),
  app: document.querySelector("#admin-app"),
  title: document.querySelector("#admin-title"),
  statusBadge: document.querySelector("#admin-status-badge"),
  statusButton: document.querySelector("#toggle-status"),
  lastRefresh: document.querySelector("#last-refresh"),
  selected: document.querySelector("#metric-selected"),
  unselected: document.querySelector("#metric-unselected"),
  rate: document.querySelector("#metric-rate"),
  rateBar: document.querySelector("#metric-rate-bar"),
  groupProgress: document.querySelector("#group-progress"),
  qr: document.querySelector("#student-qr"),
  qrPlaceholder: document.querySelector("#qr-placeholder"),
  publicUrl: document.querySelector("#public-url-label"),
  boardNotice: document.querySelector(".qr-notice"),
  boardStatus: document.querySelector("#board-status-text"),
  unselectedCount: document.querySelector("#unselected-count"),
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
  settingsForm: document.querySelector("#settings-form"),
  activityList: document.querySelector("#activity-list"),
  activityCount: document.querySelector("#activity-count-label"),
  newActivityForm: document.querySelector("#new-activity-form"),
  importForm: document.querySelector("#student-import-form"),
  importFile: document.querySelector("#student-csv"),
  importFileName: document.querySelector("#import-file-name"),
  importResult: document.querySelector("#import-result"),
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
  const response = await fetch(path, { ...fetchOptions, headers, credentials: "same-origin" });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const error = new Error(data?.detail || `请求失败（${response.status}）`);
    error.status = response.status;
    throw error;
  }
  return data;
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
  document.querySelector("#danger-dialog-title").textContent = title;
  document.querySelector("#danger-dialog-message").textContent = message;
  adminEls.dangerDialog.returnValue = "";
  adminEls.dangerDialog.showModal();
  return new Promise((resolve) => {
    adminEls.dangerDialog.addEventListener("close", () => resolve(adminEls.dangerDialog.returnValue === "confirm"), { once: true });
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
  } catch (error) {
    if (error.status === 401) {
      showAdminLogin();
      if (!quiet) showAdminToast("登录已失效，请重新登录", "error");
    } else if (!quiet) {
      showAdminToast(error.message, "error");
    }
  } finally {
    adminState.loading = false;
  }
}

function startAdminPolling() {
  clearInterval(adminState.pollTimer);
  adminState.pollTimer = setInterval(() => {
    if (adminState.currentView === "overview" && !document.hidden) loadDashboard({ quiet: true });
  }, 3000);
}

function renderDashboard(data) {
  const open = data.settings.status === "open";
  const rate = data.totals.students ? Math.round((data.totals.selected / data.totals.students) * 100) : 0;
  adminEls.title.textContent = data.settings.activity_title;
  document.title = `${data.settings.activity_title} · 管理端`;
  adminEls.selected.textContent = String(data.totals.selected);
  adminEls.unselected.textContent = String(data.totals.unselected);
  adminEls.rate.textContent = `${rate}%`;
  adminEls.rateBar.style.width = `${rate}%`;
  adminEls.statusBadge.className = `status-badge status-badge--${open ? "open" : "closed"}`;
  adminEls.statusBadge.textContent = open ? "进行中" : "已关闭";
  adminEls.statusButton.textContent = open ? "关闭抢选" : "开放抢选";
  adminEls.statusButton.className = `button ${open ? "button--secondary" : "button--primary"}`;
  adminEls.boardNotice.classList.toggle("is-open", open);
  adminEls.boardStatus.textContent = open ? "抢选正在进行" : "当前未开放";
  document.querySelector("#sidebar-owner").textContent = `制作：${data.settings.owner_name}`;
  document.querySelector("#admin-footer-org").textContent = data.settings.organization_name;
  document.querySelector("#admin-footer-owner").textContent = data.settings.owner_name;

  renderGroupProgress(data.groups);
  renderQr(data.settings.public_base_url);
  renderUnselectedList();
  renderRecentSelections(data.recent_selections);
  adminEls.recentBody.dataset.activityId = String(data.settings.activity_id);
  renderStructure(data, open);
  renderAssignmentTable(data);
  adminEls.assignmentBody.dataset.activityId = String(data.settings.activity_id);
  renderActivities(data.activities || []);
  fillSettingsForm(data.settings);
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
      meta.append(download);
    }
    row.append(info, meta);
    return row;
  });
  adminEls.activityList.replaceChildren(...rows);
  const current = activities.find((activity) => activity.current);
  const disabled = current?.status === "open";
  adminEls.newActivityForm.querySelectorAll("input, button").forEach((element) => { element.disabled = disabled; });
}

function renderGroupProgress(groups) {
  const elements = groups.filter((group) => group.active).map((group) => {
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
  const all = adminState.dashboard?.unselected_students || [];
  const query = adminEls.unselectedSearch.value.trim().toLowerCase();
  if (!query) return all;
  return all.filter((student) => [student.student_no, student.name, student.major_name].some((value) => String(value).toLowerCase().includes(query)));
}

function renderUnselectedList() {
  const all = adminState.dashboard?.unselected_students || [];
  const filtered = filteredUnselectedStudents();
  adminEls.unselectedCount.textContent = `${all.length} 人`;
  if (!filtered.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = all.length ? "没有匹配的学生" : "所有学生都已完成选择";
    adminEls.unselectedList.replaceChildren(empty);
    return;
  }
  const items = filtered.map((student) => {
    const item = document.createElement("article");
    item.className = "student-list-item";
    const avatar = document.createElement("span");
    avatar.className = "student-list-item__avatar";
    avatar.textContent = student.name.slice(-1);
    const info = document.createElement("div");
    const name = document.createElement("strong");
    name.textContent = student.name;
    const major = document.createElement("small");
    major.textContent = student.major_name;
    info.append(name, major);
    const number = document.createElement("span");
    number.className = "student-list-item__no";
    number.textContent = student.student_no;
    item.append(avatar, info, number);
    return item;
  });
  adminEls.unselectedList.replaceChildren(...items);
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

function makeSwitch(active, disabled) {
  const label = document.createElement("label");
  label.className = "switch";
  label.title = active ? "已启用" : "已停用";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.checked = Boolean(active);
  input.disabled = disabled;
  const indicator = document.createElement("i");
  label.append(input, indicator);
  return { label, input };
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
    const enabled = makeSwitch(major.active, locked);
    const save = makeIconButton("save-major", "✓", "保存专业");
    const remove = makeIconButton("delete-major", "×", "删除专业", true);
    save.disabled = locked;
    remove.disabled = locked;
    row.append(drag, name, enabled.label, save, remove);
    row._nameInput = name;
    row._activeInput = enabled.input;
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
    const enabled = makeSwitch(group.active, locked);
    const save = makeIconButton("save-group", "✓", "保存教学组");
    const remove = makeIconButton("delete-group", "×", "删除教学组", true);
    save.disabled = locked;
    remove.disabled = locked;
    row.append(drag, name, capacityWrap, enabled.label, save, remove);
    row._nameInput = name;
    row._capacityInput = capacity;
    row._activeInput = enabled.input;
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

function fillSettingsForm(settings) {
  for (const key of ["activity_title", "organization_name", "owner_name", "public_base_url"]) {
    const field = adminEls.settingsForm.elements.namedItem(key);
    if (field && document.activeElement !== field) field.value = settings[key] || "";
  }
}

function switchAdminView(viewName) {
  adminState.currentView = viewName;
  document.querySelectorAll(".admin-nav__item").forEach((button) => button.classList.toggle("is-active", button.dataset.view === viewName));
  document.querySelectorAll(".admin-view").forEach((view) => view.classList.add("is-hidden"));
  document.querySelector(`#view-${viewName}`).classList.remove("is-hidden");
  if (viewName !== "overview") loadDashboard({ quiet: true });
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

adminEls.statusButton.addEventListener("click", async () => {
  const next = adminState.dashboard?.settings.status === "open" ? "closed" : "open";
  const activityId = adminState.dashboard?.settings.activity_id;
  const confirmed = await confirmDanger(
    next === "open" ? "开放学生抢选" : "关闭学生抢选",
    next === "open" ? "开放后专业、教学组数量和配额会被锁定，学生可立即提交。" : "关闭后学生无法继续提交，管理员仍可补位和撤销。",
  );
  if (!confirmed) return;
  try {
    await adminApi("/api/admin/status", {
      method: "POST",
      body: JSON.stringify({ status: next }),
      activityId,
    });
    showAdminToast(next === "open" ? "抢选已开放" : "抢选已关闭", "success");
    await loadDashboard();
  } catch (error) { showAdminToast(error.message, "error"); }
});

adminEls.unselectedSearch.addEventListener("input", renderUnselectedList);

const liveBoard = document.querySelector("#live-board");
const fullscreenButton = document.querySelector("#fullscreen-board");

function leavePresentationMode() {
  liveBoard.classList.remove("is-presentation");
  document.body.classList.remove("is-presentation");
}

function updateFullscreenButton() {
  fullscreenButton.textContent = document.fullscreenElement || liveBoard.classList.contains("is-presentation") ? "退出全屏" : "⛶ 全屏展示";
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
      await adminApi(`/api/admin/majors/${id}`, { method: "PATCH", body: JSON.stringify({ name: row._nameInput.value, active: row._activeInput.checked }), activityId });
      showAdminToast("专业设置已保存", "success");
    } else if (button.dataset.action === "delete-major") {
      if (!await confirmDanger("删除专业", `确认删除“${row._nameInput.value}”？已有学生时系统会阻止删除。`)) return;
      await adminApi(`/api/admin/majors/${id}`, { method: "DELETE", body: JSON.stringify({}), activityId });
      showAdminToast("专业已删除，配额矩阵已同步缩减", "success");
    }
    await loadDashboard();
  } catch (error) { showAdminToast(error.message, "error"); }
});

adminEls.groupEditor.addEventListener("click", async (event) => {
  const button = event.target.closest("button[data-action]");
  if (!button) return;
  const row = button.closest(".entity-row");
  const id = Number(row.dataset.id);
  const activityId = Number(adminEls.groupEditor.dataset.activityId);
  try {
    if (button.dataset.action === "save-group") {
      await adminApi(`/api/admin/groups/${id}`, { method: "PATCH", body: JSON.stringify({ name: row._nameInput.value, total_capacity: Number(row._capacityInput.value), active: row._activeInput.checked }), activityId });
      showAdminToast("教学组设置已保存", "success");
    } else if (button.dataset.action === "delete-group") {
      if (!await confirmDanger("删除教学组", `确认删除“${row._nameInput.value}”？有历史选择时系统会阻止删除。`)) return;
      await adminApi(`/api/admin/groups/${id}`, { method: "DELETE", body: JSON.stringify({}), activityId });
      showAdminToast("教学组已删除，配额矩阵已同步缩减", "success");
    }
    await loadDashboard();
  } catch (error) { showAdminToast(error.message, "error"); }
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
    showAdminToast("活动、访问地址和版权信息已保存", "success");
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
  adminEls.importFileName.textContent = adminEls.importFile.files[0]?.name || "UTF-8 或 GB18030，最大 1 MB";
});

adminEls.importForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!adminEls.importFile.files[0]) return;
  const body = new FormData();
  body.append("file", adminEls.importFile.files[0]);
  const activityId = Number(adminEls.importForm.dataset.activityId || adminState.dashboard.settings.activity_id);
  try {
    const result = await adminApi("/api/admin/students/import", { method: "POST", body, activityId });
    adminState.generatedCredentials = result.credentials;
    adminEls.importResult.className = "import-result is-success";
    adminEls.importResult.textContent = `导入完成：新增 ${result.created} 人，更新 ${result.updated} 人；本次返回 ${result.credentials.length} 条激活码。请立即下载并妥善保管。`;
    adminEls.importForm.reset();
    delete adminEls.importForm.dataset.activityId;
    adminEls.importFileName.textContent = "UTF-8 或 GB18030，最大 1 MB";
    if (result.credentials.length) downloadCredentials(result.credentials);
    await loadDashboard();
  } catch (error) {
    adminEls.importResult.className = "import-result";
    adminEls.importResult.textContent = "";
    showAdminToast(error.message, "error");
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

function csvEscape(value) {
  const text = String(value ?? "");
  return /[",\r\n]/.test(text) ? `"${text.replaceAll('"', '""')}"` : text;
}

function downloadCredentials(credentials) {
  const rows = [["学号", "姓名", "专业", "激活码"], ...credentials.map((row) => [row.student_no, row.name, row.major, row.activation_code])];
  downloadText("学生激活码-请妥善保管.csv", rows.map((row) => row.map(csvEscape).join(",")).join("\n"));
}

document.querySelector("#download-template").addEventListener("click", () => {
  downloadText("学生名单模板.csv", "学号,姓名,专业,激活码\n20260001,示例学生,建筑学,");
});

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
  } catch (error) { showAdminToast(error.message, "error"); }
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
  } catch (error) { showAdminToast(error.message, "error"); }
});

document.addEventListener("visibilitychange", () => {
  if (!document.hidden && adminState.currentView === "overview" && adminState.csrf) loadDashboard({ quiet: true });
});

loadAdminSession();
