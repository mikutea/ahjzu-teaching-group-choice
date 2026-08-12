"use strict";

const studentState = {
  csrf: "",
  payload: null,
  selectedGroupId: null,
  pollTimer: null,
  heartbeatTimer: null,
  messageTimer: null,
  countdownTimer: null,
  pollInFlight: false,
  heartbeatInFlight: false,
  boundaryRefreshPending: false,
  serverClockOffset: 0,
};

const studentEls = {
  activityTitle: document.querySelector("#activity-title"),
  organizationName: document.querySelector("#organization-name"),
  publicStatus: document.querySelector("#public-status"),
  loginView: document.querySelector("#login-view"),
  choiceView: document.querySelector("#choice-view"),
  waitingView: document.querySelector("#waiting-view"),
  successView: document.querySelector("#success-view"),
  loginForm: document.querySelector("#student-login-form"),
  groupList: document.querySelector("#group-list"),
  submitChoice: document.querySelector("#submit-choice"),
  choiceHint: document.querySelector("#choice-hint"),
  displayName: document.querySelector("#student-display-name"),
  displayMeta: document.querySelector("#student-display-meta"),
  waitingName: document.querySelector("#waiting-student-name"),
  waitingMeta: document.querySelector("#waiting-student-meta"),
  waitingVisual: document.querySelector("#waiting-visual"),
  waitingTitle: document.querySelector("#waiting-title"),
  waitingMessage: document.querySelector("#waiting-message"),
  waitingLiveNote: document.querySelector("#waiting-live-note"),
  countdownValue: document.querySelector("#student-countdown-value"),
  message: document.querySelector("#student-message"),
  confirmDialog: document.querySelector("#confirm-dialog"),
  confirmGroupName: document.querySelector("#confirm-group-name"),
  successMessage: document.querySelector("#success-message"),
  successTime: document.querySelector("#success-time"),
};

const studentFieldLabels = {
  student_no: "学号",
  name: "姓名",
  activation_code: "个人激活码",
};

function validationField(issue) {
  const locations = Array.isArray(issue?.loc) ? issue.loc : [];
  for (let index = locations.length - 1; index >= 0; index -= 1) {
    if (studentFieldLabels[locations[index]]) return locations[index];
  }
  return null;
}

function translateValidationIssue(issue) {
  const field = validationField(issue);
  const label = studentFieldLabels[field] || "提交内容";
  const type = String(issue?.type || "");
  if (type === "missing") return `请填写${label}`;
  if (type === "string_too_short") {
    const minimum = Number(issue?.ctx?.min_length);
    return Number.isFinite(minimum) ? `${label}至少需要 ${minimum} 个字符` : `${label}长度太短`;
  }
  if (type === "string_too_long") {
    const maximum = Number(issue?.ctx?.max_length);
    return Number.isFinite(maximum) ? `${label}不能超过 ${maximum} 个字符` : `${label}长度超过限制`;
  }
  if (["string_type", "int_type", "int_parsing"].includes(type)) return `${label}格式不正确`;
  if (type === "extra_forbidden") return "提交内容包含无效字段，请刷新页面后重试";
  if (type === "json_invalid") return "提交内容无法识别，请刷新页面后重试";
  if (type.startsWith("value_error")) return `${label}内容不符合要求`;
  return `${label}填写不正确`;
}

function apiErrorDetails(data, status) {
  const detail = data?.detail;
  if (status === 422 && Array.isArray(detail)) {
    const messages = [...new Set(detail.map(translateValidationIssue))];
    return {
      message: messages.join("；") || "请检查填写内容",
      field: detail.map(validationField).find(Boolean) || null,
    };
  }
  return {
    message: typeof detail === "string" ? detail : `请求失败（${status}）`,
    field: null,
  };
}

async function studentApi(path, options = {}) {
  const headers = new Headers(options.headers || {});
  const method = (options.method || "GET").toUpperCase();
  if (options.body && !(options.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  if (studentState.csrf && !["GET", "HEAD"].includes(method)) {
    headers.set("X-CSRF-Token", studentState.csrf);
  }
  if (
    path.startsWith("/api/student/")
    && !["GET", "HEAD"].includes(method)
    && !["/api/student/login", "/api/student/logout"].includes(path)
    && studentState.payload?.settings.activity_id
    && !headers.has("X-Activity-ID")
  ) {
    headers.set("X-Activity-ID", String(studentState.payload.settings.activity_id));
  }
  const response = await fetch(path, { ...options, headers, credentials: "same-origin" });
  const type = response.headers.get("content-type") || "";
  const data = type.includes("application/json") ? await response.json() : null;
  if (!response.ok) {
    const details = apiErrorDetails(data, response.status);
    const error = new Error(details.message);
    error.status = response.status;
    error.field = details.field;
    throw error;
  }
  return data;
}

function showStudentMessage(text, kind = "info") {
  clearTimeout(studentState.messageTimer);
  studentEls.message.textContent = text;
  studentEls.message.className = `toast is-visible${kind === "error" ? " is-error" : kind === "success" ? " is-success" : ""}`;
  studentState.messageTimer = setTimeout(() => {
    studentEls.message.classList.remove("is-visible");
  }, 3300);
}

function studentField(payload, key) {
  return payload?.[key] ?? payload?.settings?.[key] ?? null;
}

function synchronizeStudentClock(payload) {
  const parsed = Date.parse(studentField(payload, "server_now") || "");
  if (Number.isFinite(parsed)) studentState.serverClockOffset = parsed - Date.now();
}

function millisecondsUntilStudentOpen(payload = studentState.payload) {
  const target = Date.parse(studentField(payload, "selection_opens_at") || "");
  if (!Number.isFinite(target)) return null;
  return target - (Date.now() + studentState.serverClockOffset);
}

function studentPhase(payload = studentState.payload) {
  const raw = String(studentField(payload, "phase") || "").toLowerCase();
  const status = String(payload?.settings?.status || payload?.status || "closed").toLowerCase();
  const remaining = millisecondsUntilStudentOpen(payload);
  if (["archived", "finished", "closed", "paused", "ended"].includes(raw) || status === "archived") return raw === "archived" ? "closed" : raw;
  if ((raw === "countdown" || ["countdown", "open"].includes(status)) && remaining !== null && remaining > 0) return "countdown";
  if (raw === "countdown" && (remaining === null || remaining <= 0)) return "open";
  if (["open", "selecting", "active"].includes(raw) || status === "open") return "open";
  return "waiting";
}

function renderStudentSettings(settings, payload = { settings }) {
  document.title = `${settings.activity_title} · 建筑与空间规划学院`;
  studentEls.activityTitle.textContent = settings.activity_title;
  studentEls.organizationName.textContent = "安徽建筑大学 · 建筑与空间规划学院";
  const phase = studentPhase(payload);
  studentEls.publicStatus.className = `status-ribbon status-ribbon--${phase}`;
  const remaining = millisecondsUntilStudentOpen(payload);
  const seconds = remaining === null ? 10 : Math.max(0, Math.ceil(remaining / 1000));
  const labels = {
    waiting: "候场中 · 登录后请保持页面打开",
    countdown: `统一倒计时 ${seconds} 秒 · 即将同时开抢`,
    open: "抢选进行中 · 名额实时更新",
    closed: "本场抢选已关闭",
    paused: "本场抢选已暂停",
    ended: "本场抢选已结束",
  };
  studentEls.publicStatus.lastElementChild.textContent = labels[phase] || labels.waiting;
}

function formatStudentTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function createGroupOption(group, payload) {
  const label = document.createElement("label");
  const unavailable = group.full || studentPhase(payload) !== "open";
  label.className = `group-option${unavailable ? " is-full" : ""}${studentState.selectedGroupId === group.id ? " is-selected" : ""}`;

  const details = document.createElement("div");
  const name = document.createElement("span");
  name.className = "group-option__name";
  name.textContent = group.name;
  const progress = document.createElement("div");
  progress.className = "group-option__progress";
  const progressFill = document.createElement("span");
  const rate = group.capacity > 0 ? Math.min(100, Math.round((group.selected / group.capacity) * 100)) : 100;
  progressFill.style.width = `${rate}%`;
  progress.append(progressFill);
  details.append(name, progress);

  const count = document.createElement("div");
  count.className = "group-option__count";
  const remaining = document.createElement("strong");
  remaining.textContent = unavailable && group.full ? "已满" : `${group.remaining}`;
  count.append(remaining, document.createTextNode(group.full ? `${group.selected}/${group.capacity}` : "剩余名额"));

  const radio = document.createElement("input");
  radio.className = "group-option__radio";
  radio.type = "radio";
  radio.name = "teaching_group";
  radio.value = String(group.id);
  radio.disabled = unavailable;
  radio.checked = studentState.selectedGroupId === group.id;
  radio.addEventListener("change", () => {
    studentState.selectedGroupId = group.id;
    renderStudentPayload(studentState.payload);
  });

  label.append(details, count, radio);
  return label;
}

function renderStudentPayload(payload) {
  studentState.payload = payload;
  synchronizeStudentClock(payload);
  renderStudentSettings(payload.settings, payload);
  studentEls.loginView.classList.add("is-hidden");
  studentEls.displayName.textContent = `${payload.student.name} 同学`;
  studentEls.displayMeta.textContent = `${payload.student.student_no} · ${payload.student.major_name}`;
  studentEls.waitingName.textContent = `${payload.student.name} 同学`;
  studentEls.waitingMeta.textContent = `${payload.student.student_no} · ${payload.student.major_name}`;

  if (payload.selection) {
    studentEls.choiceView.classList.add("is-hidden");
    studentEls.waitingView.classList.add("is-hidden");
    studentEls.successView.classList.remove("is-hidden");
    studentEls.successMessage.textContent = `已成功选择「${payload.selection.group_name}」`;
    studentEls.successTime.textContent = formatStudentTime(payload.selection.selected_at);
    clearInterval(studentState.pollTimer);
    clearInterval(studentState.heartbeatTimer);
    return;
  }

  studentEls.successView.classList.add("is-hidden");
  const phase = studentPhase(payload);
  if (phase !== "open") {
    studentEls.choiceView.classList.add("is-hidden");
    studentEls.waitingView.classList.remove("is-hidden");
    studentEls.waitingView.classList.toggle("is-countdown", phase === "countdown");
    const remaining = millisecondsUntilStudentOpen(payload);
    const seconds = remaining === null ? 10 : Math.max(0, Math.ceil(remaining / 1000));
    if (phase === "countdown") {
      studentEls.countdownValue.textContent = String(seconds);
      studentEls.waitingTitle.textContent = "全体同步倒计时";
      studentEls.waitingMessage.textContent = "倒计时结束后将自动进入选组页面，请不要退出或锁屏。";
      studentEls.waitingLiveNote.textContent = "时间以服务器为准，所有同学同时开抢";
    } else if (["closed", "ended", "paused"].includes(phase)) {
      studentEls.countdownValue.textContent = "END";
      studentEls.waitingTitle.textContent = phase === "paused" ? "抢选已暂停" : "本场抢选已关闭";
      studentEls.waitingMessage.textContent = "当前无法提交，请等待老师后续通知。";
      studentEls.waitingLiveNote.textContent = "页面会继续自动同步活动状态";
    } else {
      studentEls.countdownValue.textContent = "READY";
      studentEls.waitingTitle.textContent = "已进入抢选候场";
      studentEls.waitingMessage.textContent = "请保持页面打开，等待老师开始统一倒计时。";
      studentEls.waitingLiveNote.textContent = "候场状态每秒自动同步";
    }
    return;
  }

  studentState.boundaryRefreshPending = false;
  studentEls.waitingView.classList.add("is-hidden");
  studentEls.choiceView.classList.remove("is-hidden");
  studentEls.groupList.replaceChildren(...payload.groups.map((group) => createGroupOption(group, payload)));
  const selected = payload.groups.find((group) => group.id === studentState.selectedGroupId && !group.full);
  studentEls.submitChoice.disabled = !selected;
  studentEls.choiceHint.textContent = selected
    ? `将选择：${selected.name}，当前剩余 ${selected.remaining} 个名额`
    : "请选择一个仍有名额的教学组";
}

async function loadPublicInfo() {
  try {
    const data = await studentApi("/api/public/info");
    synchronizeStudentClock(data);
    renderStudentSettings(data.settings, data);
  } catch (error) {
    showStudentMessage(error.message, "error");
  }
}

async function loadStudentSession() {
  try {
    const data = await studentApi("/api/student/me");
    studentState.csrf = data.csrf_token;
    renderStudentPayload(data);
    startStudentPolling();
  } catch (error) {
    if (error.status !== 401) showStudentMessage(error.message, "error");
  }
}

function startStudentPolling() {
  clearInterval(studentState.pollTimer);
  clearInterval(studentState.heartbeatTimer);
  if (studentState.payload?.selection) return;
  studentState.pollTimer = setInterval(async () => {
    if (studentState.pollInFlight) return;
    studentState.pollInFlight = true;
    try {
      const data = await studentApi("/api/student/me");
      const selectedStillAvailable = data.groups.some((group) => group.id === studentState.selectedGroupId && !group.full);
      if (!selectedStillAvailable) studentState.selectedGroupId = null;
      renderStudentPayload(data);
    } catch (error) {
      if (error.status === 401) {
        clearInterval(studentState.pollTimer);
        clearInterval(studentState.heartbeatTimer);
        window.location.reload();
      }
    } finally {
      studentState.pollInFlight = false;
    }
  }, 1000);
  studentState.heartbeatTimer = setInterval(async () => {
    if (studentState.heartbeatInFlight || !studentState.payload || studentState.payload.selection) return;
    studentState.heartbeatInFlight = true;
    try {
      await studentApi("/api/student/heartbeat", { method: "POST", body: JSON.stringify({}) });
    } catch (error) {
      if (error.status === 401) window.location.reload();
    } finally {
      studentState.heartbeatInFlight = false;
    }
  }, 5000);
}

function tickStudentCountdown() {
  const payload = studentState.payload;
  if (!payload || payload.selection) return;
  const phase = studentPhase(payload);
  if (phase === "countdown") {
    const seconds = Math.max(0, Math.ceil((millisecondsUntilStudentOpen(payload) || 0) / 1000));
    studentEls.countdownValue.textContent = String(seconds);
    studentEls.publicStatus.lastElementChild.textContent = `统一倒计时 ${seconds} 秒 · 即将同时开抢`;
    return;
  }
  if (phase === "open" && !studentEls.waitingView.classList.contains("is-hidden")) {
    renderStudentPayload(payload);
    if (studentState.boundaryRefreshPending) return;
    studentState.boundaryRefreshPending = true;
    studentApi("/api/student/me")
      .then((latest) => renderStudentPayload(latest))
      .catch(() => { /* the one-second poll will retry */ })
      .finally(() => { studentState.boundaryRefreshPending = false; });
  }
}

studentEls.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const submit = studentEls.loginForm.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.textContent = "正在核验…";
  try {
    const form = new FormData(studentEls.loginForm);
    const data = await studentApi("/api/student/login", {
      method: "POST",
      body: JSON.stringify(Object.fromEntries(form.entries())),
    });
    studentState.csrf = data.csrf_token;
    studentState.selectedGroupId = null;
    renderStudentPayload(data);
    startStudentPolling();
    showStudentMessage("身份核验成功", "success");
  } catch (error) {
    showStudentMessage(error.message, "error");
    if (error.status === 422 && error.field) {
      const field = studentEls.loginForm.elements.namedItem(error.field);
      if (field instanceof HTMLElement) {
        field.setAttribute("aria-invalid", "true");
        field.focus();
        if (typeof field.select === "function") field.select();
      }
    }
  } finally {
    submit.disabled = false;
    submit.innerHTML = "核验并进入 <span aria-hidden=\"true\">→</span>";
  }
});

studentEls.loginForm.addEventListener("input", (event) => {
  if (event.target instanceof HTMLElement) event.target.removeAttribute("aria-invalid");
});

studentEls.submitChoice.addEventListener("click", () => {
  const group = studentState.payload?.groups.find((item) => item.id === studentState.selectedGroupId);
  if (!group) return;
  studentEls.confirmDialog.dataset.activityId = String(studentState.payload.settings.activity_id);
  studentEls.confirmGroupName.textContent = group.name;
  studentEls.confirmDialog.showModal();
});

studentEls.confirmDialog.addEventListener("close", async () => {
  if (studentEls.confirmDialog.returnValue !== "confirm") return;
  const groupId = studentState.selectedGroupId;
  if (!groupId) return;
  studentEls.submitChoice.disabled = true;
  try {
    const data = await studentApi("/api/student/select", {
      method: "POST",
      body: JSON.stringify({ group_id: groupId }),
      headers: { "X-Activity-ID": studentEls.confirmDialog.dataset.activityId },
    });
    renderStudentPayload(data);
    showStudentMessage("选择已由服务器确认", "success");
  } catch (error) {
    studentState.selectedGroupId = null;
    showStudentMessage(error.message, "error");
    try {
      const latest = await studentApi("/api/student/me");
      renderStudentPayload(latest);
    } catch (_) {
      // The original error is more useful to the student.
    }
  }
});

async function studentLogout() {
  clearInterval(studentState.pollTimer);
  clearInterval(studentState.heartbeatTimer);
  try {
    await studentApi("/api/student/logout", { method: "POST", body: JSON.stringify({}) });
  } catch (_) {
    // A stale session can still be cleared by reloading.
  }
  window.location.reload();
}

document.querySelector("#student-logout").addEventListener("click", studentLogout);
document.querySelector("#waiting-logout").addEventListener("click", studentLogout);
document.querySelector("#success-logout").addEventListener("click", studentLogout);

studentState.countdownTimer = setInterval(tickStudentCountdown, 200);
loadPublicInfo();
loadStudentSession();
