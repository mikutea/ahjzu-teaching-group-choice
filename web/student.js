"use strict";

const STUDENT_NO_INPUT_LENGTH = 11;
const STUDENT_NAME_MAX_INPUT_LENGTH = 40;
const CONTROL_CHARACTER_PATTERN = /\p{C}/u;
const STUDENT_NO_PATTERN = /^\d{11}$/;
const STUDENT_NAME_PATTERN = /^[A-Za-z\p{Script=Han}]+(?:[ ·•・][A-Za-z\p{Script=Han}]+)*$/u;
const ACTIVATION_CODE_PATTERN = /^[A-Z0-9]{6}$/;

function normalizeCompatibilityText(value) {
  return String(value ?? "").normalize("NFKC");
}

function trimUnicodeSeparators(value) {
  return String(value ?? "").replace(/^\p{Z}+|\p{Z}+$/gu, "");
}

function normalizeStudentLoginPayload(values) {
  return {
    student_no: trimUnicodeSeparators(normalizeCompatibilityText(values.student_no)),
    name: trimUnicodeSeparators(normalizeCompatibilityText(values.name)).replace(/\p{Z}+/gu, " "),
    activation_code: trimUnicodeSeparators(normalizeCompatibilityText(values.activation_code))
      .toUpperCase(),
  };
}

function validateStudentLoginPayload(payload) {
  const errors = {};
  if (!payload.student_no) {
    errors.student_no = "请输入学号";
  } else if (CONTROL_CHARACTER_PATTERN.test(payload.student_no)) {
    errors.student_no = "学号不能包含换行或其他控制字符";
  } else if (!STUDENT_NO_PATTERN.test(payload.student_no)) {
    errors.student_no = "学号必须是 11 位数字";
  }
  if (!payload.name) {
    errors.name = "请输入姓名";
  } else if (CONTROL_CHARACTER_PATTERN.test(payload.name)) {
    errors.name = "姓名不能包含换行或其他控制字符";
  } else if (Array.from(payload.name).length > STUDENT_NAME_MAX_INPUT_LENGTH) {
    errors.name = `姓名不能超过 ${STUDENT_NAME_MAX_INPUT_LENGTH} 个字符`;
  } else if (!STUDENT_NAME_PATTERN.test(payload.name)) {
    errors.name = "姓名只能包含中文或英文字母，各部分之间可使用空格或中点";
  }
  if (!payload.activation_code) {
    errors.activation_code = "请输入个人激活码";
  } else if (CONTROL_CHARACTER_PATTERN.test(payload.activation_code)) {
    errors.activation_code = "个人激活码不能包含控制字符";
  } else if (!ACTIVATION_CODE_PATTERN.test(payload.activation_code)) {
    errors.activation_code = "个人激活码必须是 6 位英文字母或数字";
  }
  return errors;
}

function professionalBadge(majorName) {
  const major = normalizeCompatibilityText(majorName).trim();
  if (/建筑学/.test(major)) return "建筑学";
  if (/(城乡|城市)规划/.test(major)) return "城乡规划";
  if (/风景园林/.test(major)) return "风景园林";
  if (/环境设计/.test(major)) return "环境设计";
  const baseName = major.split(/[（(]/, 1)[0].trim();
  if (!baseName) return "专业";
  const characters = Array.from(baseName);
  return characters.length <= 6 ? baseName : `${characters.slice(0, 6).join("")}…`;
}

const STUDENT_CLOCK_SYNC_PATHS = new Set([
  "/api/public/info",
  "/api/public/status",
  "/api/student/login",
  "/api/student/me",
]);
const studentResponseClockTimings = new WeakMap();

function beginStudentClockRequestTiming(path) {
  if (!STUDENT_CLOCK_SYNC_PATHS.has(path)) return null;
  return {
    requestWallMs: Date.now(),
    requestMonotonicMs: studentMonotonicNow(),
  };
}

function finishStudentClockRequestTiming(timing) {
  if (!timing) return null;
  return {
    ...timing,
    responseWallMs: Date.now(),
    responseMonotonicMs: studentMonotonicNow(),
  };
}

function rememberStudentResponseClockTiming(payload, timing) {
  if (!timing || !payload || typeof payload !== "object") return;
  studentResponseClockTimings.set(payload, timing);
}

const studentState = {
  csrf: "",
  payload: null,
  selectedGroupId: null,
  pollTimer: null,
  heartbeatTimer: null,
  messageTimer: null,
  countdownTimer: null,
  pollInFlight: false,
  lastSelectedSyncAt: 0,
  heartbeatInFlight: false,
  boundaryRefreshPending: false,
  connectionInterrupted: false,
  lastBackgroundErrorAt: 0,
  sessionReloadTimer: null,
  lastPhase: null,
  resultCardInFlight: false,
  resultCardLogoPromise: null,
  resultCardPreviewKey: null,
  resultCardPreviewPendingKey: null,
  resultCardPreviewUrl: null,
  serverClockEpochMs: null,
  serverClockMonotonicMs: null,
  serverClockSynchronized: false,
  serverClockOffsetMs: null,
  serverClockLastSampleRttMs: null,
  clockTimer: null,
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
  displayBadge: document.querySelector("#student-major-badge"),
  waitingName: document.querySelector("#waiting-student-name"),
  waitingMeta: document.querySelector("#waiting-student-meta"),
  waitingBadge: document.querySelector("#waiting-major-badge"),
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
  successBadge: document.querySelector("#success-major-badge"),
  resultCardPreviewImage: document.querySelector("#result-card-preview-image"),
  resultCardPreviewStatus: document.querySelector("#result-card-preview-status"),
  downloadResultCard: document.querySelector("#download-result-card"),
  clock: document.querySelector("#student-clock"),
  clockStatus: document.querySelector("#student-clock-status"),
  clockTime: document.querySelector("#student-server-clock"),
};

const studentLoginFields = {
  student_no: {
    input: document.querySelector("#student-no"),
    error: document.querySelector("#student-no-error"),
  },
  name: {
    input: document.querySelector("#student-name"),
    error: document.querySelector("#student-name-error"),
  },
  activation_code: {
    input: document.querySelector("#activation-code"),
    error: document.querySelector("#activation-code-error"),
  },
};

const studentFieldLabels = {
  student_no: "学号",
  name: "姓名",
  activation_code: "个人激活码",
};

function setStudentFieldError(fieldName, message = "") {
  const field = studentLoginFields[fieldName];
  if (!field) return;
  if (message) field.input.setAttribute("aria-invalid", "true");
  else field.input.removeAttribute("aria-invalid");
  field.error.textContent = message;
  field.error.classList.toggle("is-hidden", !message);
}

function clearStudentFieldErrors() {
  for (const fieldName of Object.keys(studentLoginFields)) setStudentFieldError(fieldName);
}

function focusFirstStudentFieldError(errors) {
  const fieldName = Object.keys(studentLoginFields).find((key) => errors[key]);
  if (!fieldName) return;
  const field = studentLoginFields[fieldName];
  field.input.focus({ preventScroll: true });
  requestAnimationFrame(() => {
    if (document.activeElement === field.input) {
      field.input.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" });
    }
  });
  if (typeof field.input.select === "function") field.input.select();
}

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
  if (type.startsWith("value_error")) {
    const fieldMessages = {
      student_no: "学号必须是名单中的 11 位数字",
      name: "姓名只能包含中文或英文字母，各部分之间可使用空格或中点",
      activation_code: "个人激活码必须是 6 位英文字母或数字",
    };
    return fieldMessages[field] || `${label}内容不符合要求`;
  }
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
  if (typeof detail === "string" && detail.trim()) return { message: detail, field: null };
  const messages = {
    400: "提交内容格式不正确，请检查后重试",
    401: "登录会话已失效，请重新核验身份",
    403: "本场活动当前不可提交，可能尚未开放或已经关闭",
    404: "当前活动或学生信息不存在，请联系老师核对名单",
    409: "该选择已提交，或名额刚刚发生变化，请刷新后确认",
    410: "本场活动已经结束，无法继续提交",
    413: "提交内容过大，请刷新页面后重试",
    422: "填写内容未通过校验，请检查学号、姓名和激活码",
    423: "本场抢选已关闭或暂停，请等待老师通知",
    428: "活动状态已经变化，页面将重新同步，请稍后再试",
    429: "操作过于频繁，请稍后再试",
    500: "服务暂时异常，请稍后重试",
    503: "当前访问人数较多，请稍后重试",
  };
  return { message: messages[status] || `请求未完成（${status}），请稍后重试`, field: null };
}

async function studentApi(path, options = {}) {
  const clockRequestTiming = beginStudentClockRequestTiming(path);
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
  let response;
  let clockResponseTiming = null;
  try {
    response = await fetch(path, { ...options, headers, credentials: "same-origin" });
    clockResponseTiming = finishStudentClockRequestTiming(clockRequestTiming);
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
    const details = apiErrorDetails(data, response.status);
    const error = new Error(details.message);
    error.status = response.status;
    error.field = details.field;
    throw error;
  }
  rememberStudentResponseClockTiming(data, clockResponseTiming);
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

function reportStudentConnectionIssue(error) {
  const now = Date.now();
  if (studentState.connectionInterrupted && now - studentState.lastBackgroundErrorAt < 10_000) return;
  studentState.connectionInterrupted = true;
  studentState.lastBackgroundErrorAt = now;
  renderStudentServerClock();
  showStudentMessage(error.status === 0 ? "网络连接中断，页面会自动重试" : `${error.message}；页面会自动重试`, "error");
}

function markStudentConnectionHealthy() {
  const recovered = studentState.connectionInterrupted;
  studentState.connectionInterrupted = false;
  renderStudentServerClock();
  if (recovered) showStudentMessage("连接已恢复，名额和活动状态已同步", "success");
}

function handleStudentSessionExpired() {
  if (studentState.sessionReloadTimer) return;
  clearInterval(studentState.pollTimer);
  clearInterval(studentState.heartbeatTimer);
  studentState.csrf = "";
  showStudentMessage("登录会话已失效，即将返回身份核验页", "error");
  studentState.sessionReloadTimer = setTimeout(() => window.location.reload(), 1200);
}

function studentField(payload, key) {
  return payload?.[key] ?? payload?.settings?.[key] ?? null;
}

function studentMonotonicNow() {
  return typeof globalThis.performance?.now === "function" ? globalThis.performance.now() : Date.now();
}

function currentStudentServerTimeMs() {
  if (!studentState.serverClockSynchronized) return Date.now();
  const elapsed = Math.max(0, studentMonotonicNow() - studentState.serverClockMonotonicMs);
  return studentState.serverClockEpochMs + elapsed;
}

function synchronizeStudentClock(payload) {
  const parsed = Date.parse(studentField(payload, "server_now") || "");
  if (!Number.isFinite(parsed)) return;
  const synchronizedMonotonicMs = studentMonotonicNow();
  const timing = payload && typeof payload === "object"
    ? studentResponseClockTimings.get(payload)
    : null;
  let estimatedServerNowMs = parsed;
  let sampledOffsetMs = parsed - Date.now();
  let sampledRoundTripMs = 0;
  if (timing) {
    const requestMonotonicMs = Number(timing.requestMonotonicMs);
    const responseMonotonicMs = Number(timing.responseMonotonicMs);
    const requestWallMs = Number(timing.requestWallMs);
    const responseWallMs = Number(timing.responseWallMs);
    if (
      Number.isFinite(requestMonotonicMs)
      && Number.isFinite(responseMonotonicMs)
      && responseMonotonicMs >= requestMonotonicMs
    ) {
      sampledRoundTripMs = responseMonotonicMs - requestMonotonicMs;
      const monotonicMidpointMs = (requestMonotonicMs + responseMonotonicMs) / 2;
      estimatedServerNowMs = parsed + Math.max(0, synchronizedMonotonicMs - monotonicMidpointMs);
    }
    if (Number.isFinite(requestWallMs) && Number.isFinite(responseWallMs)) {
      const wallMidpointMs = (requestWallMs + responseWallMs) / 2;
      sampledOffsetMs = parsed - wallMidpointMs;
    }
  }
  const previousServerNowMs = studentState.serverClockSynchronized
    ? studentState.serverClockEpochMs
      + Math.max(0, synchronizedMonotonicMs - studentState.serverClockMonotonicMs)
    : null;
  if (Number.isFinite(previousServerNowMs)) {
    estimatedServerNowMs = Math.max(estimatedServerNowMs, previousServerNowMs);
  }
  studentState.serverClockEpochMs = estimatedServerNowMs;
  studentState.serverClockMonotonicMs = synchronizedMonotonicMs;
  studentState.serverClockOffsetMs = sampledOffsetMs;
  studentState.serverClockLastSampleRttMs = sampledRoundTripMs;
  studentState.serverClockSynchronized = true;
  renderStudentServerClock();
}

function renderStudentServerClock() {
  const browserOffline = typeof navigator !== "undefined" && navigator.onLine === false;
  const interrupted = studentState.connectionInterrupted || browserOffline;
  const status = !studentState.serverClockSynchronized
    ? (interrupted ? "未同步" : "正在同步")
    : (interrupted ? "同步中断" : "服务器时间");
  const syncStatus = !studentState.serverClockSynchronized ? "syncing" : interrupted ? "interrupted" : "synced";
  studentEls.clock.dataset.syncStatus = syncStatus;
  studentEls.clockStatus.textContent = status;
  if (!studentState.serverClockSynchronized) {
    studentEls.clockTime.textContent = "--:--:--";
    studentEls.clockTime.removeAttribute("datetime");
    studentEls.clock.setAttribute("aria-label", `${status}，尚未取得服务器时间`);
    return;
  }
  const now = new Date(currentStudentServerTimeMs());
  const fullText = now.toLocaleString("zh-CN", { hour12: false, timeZone: "Asia/Shanghai" });
  studentEls.clockTime.textContent = now.toLocaleTimeString("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
    timeZone: "Asia/Shanghai",
  });
  studentEls.clockTime.dateTime = now.toISOString();
  studentEls.clock.title = `${status}：${fullText}`;
  studentEls.clock.setAttribute("aria-label", `${status} ${fullText}`);
}

function millisecondsUntilStudentOpen(payload = studentState.payload) {
  const target = Date.parse(studentField(payload, "selection_opens_at") || "");
  if (!Number.isFinite(target)) return null;
  return target - currentStudentServerTimeMs();
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

function roundedRectangle(context, x, y, width, height, radius) {
  const safeRadius = Math.min(radius, width / 2, height / 2);
  context.beginPath();
  context.moveTo(x + safeRadius, y);
  context.arcTo(x + width, y, x + width, y + height, safeRadius);
  context.arcTo(x + width, y + height, x, y + height, safeRadius);
  context.arcTo(x, y + height, x, y, safeRadius);
  context.arcTo(x, y, x + width, y, safeRadius);
  context.closePath();
}

function drawWrappedCardText(context, text, x, y, maxWidth, lineHeight, maxLines = 2) {
  const characters = Array.from(String(text || "—"));
  const lines = [];
  let line = "";
  for (const character of characters) {
    const candidate = line + character;
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = character;
      if (lines.length === maxLines) break;
    } else {
      line = candidate;
    }
  }
  if (lines.length < maxLines && line) lines.push(line);
  if (lines.join("").length < characters.length && lines.length) {
    let last = lines.length - 1;
    while (lines[last] && context.measureText(`${lines[last]}…`).width > maxWidth) {
      lines[last] = Array.from(lines[last]).slice(0, -1).join("");
    }
    lines[last] = `${lines[last]}…`;
  }
  lines.forEach((currentLine, index) => context.fillText(currentLine, x, y + index * lineHeight));
  return y + Math.max(1, lines.length) * lineHeight;
}

function fittedCardTextLines(context, text, maxWidth) {
  const characters = Array.from(String(text || "—"));
  const lines = [];
  let line = "";
  for (const character of characters) {
    const candidate = line + character;
    if (line && context.measureText(candidate).width > maxWidth) {
      lines.push(line);
      line = character;
    } else {
      line = candidate;
    }
  }
  if (line || !lines.length) lines.push(line || "—");
  return lines;
}

function drawFittedCardText(context, text, x, y, maxWidth, maxFontSize = 42, maxLines = 2) {
  let fontSize = maxFontSize;
  let lines = [];
  while (fontSize >= 1) {
    context.font = `900 ${fontSize}px "Microsoft YaHei", "PingFang SC", sans-serif`;
    lines = fittedCardTextLines(context, text, maxWidth);
    if (lines.length <= maxLines) break;
    fontSize -= 1;
  }
  const lineHeight = Math.max(fontSize + 5, Math.round(fontSize * 1.16));
  lines.forEach((line, index) => context.fillText(line, x, y + index * lineHeight));
  return { fontSize, lineCount: lines.length, bottom: y + lines.length * lineHeight };
}

function loadResultCardLogo() {
  if (studentState.resultCardLogoPromise) return studentState.resultCardLogoPromise;
  studentState.resultCardLogoPromise = new Promise((resolve, reject) => {
    const logo = new Image();
    logo.decoding = "async";
    logo.onload = () => resolve(logo);
    logo.onerror = () => reject(new Error("学院标识加载失败，请检查网络后重试"));
    logo.src = "/brand/college-wordmark-official.png";
  }).catch((error) => {
    studentState.resultCardLogoPromise = null;
    throw error;
  });
  return studentState.resultCardLogoPromise;
}

function resultCardSameOriginImageUrl(value) {
  if (!value) return null;
  try {
    const url = new URL(String(value), window.location.href);
    return url.origin === window.location.origin ? url.href : null;
  } catch (_error) {
    return null;
  }
}

function resultCardVerificationQrDataUrl(qrBlob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = String(reader.result || "");
      if (dataUrl.startsWith("data:image/png")) resolve(dataUrl);
      else reject(new Error("防伪二维码加载失败，请检查网络后重试"));
    };
    reader.onerror = () => reject(new Error("防伪二维码加载失败，请检查网络后重试"));
    reader.onabort = reader.onerror;
    reader.readAsDataURL(qrBlob);
  });
}

async function decodeResultCardVerificationQr(qrBlob) {
  if (typeof createImageBitmap === "function") {
    try {
      return await createImageBitmap(qrBlob);
    } catch (_error) {
      // Older WebKit versions can expose createImageBitmap but reject PNG blobs.
    }
  }

  const dataUrl = await resultCardVerificationQrDataUrl(qrBlob);
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.decoding = "async";
    image.onload = () => resolve(image);
    image.onerror = () => reject(new Error("防伪二维码加载失败，请检查网络后重试"));
    image.src = dataUrl;
  });
}

async function loadResultCardVerificationQr(payload) {
  const receipt = payload?.receipt;
  const token = String(receipt?.token || "").trim();
  const verificationCode = String(receipt?.verification_code || "").trim();
  const verifyUrl = resultCardSameOriginImageUrl(receipt?.verify_url);
  const qrImageUrl = resultCardSameOriginImageUrl(receipt?.qr_image_url);
  if (!receipt || !token || !verificationCode || !verifyUrl || !qrImageUrl || !studentState.csrf) {
    throw new Error("防伪核验信息不完整，请刷新页面后重试");
  }

  const headers = new Headers({
    "Content-Type": "application/json",
    "X-CSRF-Token": studentState.csrf,
  });
  if (payload?.settings?.activity_id) {
    headers.set("X-Activity-ID", String(payload.settings.activity_id));
  }
  let response;
  try {
    response = await fetch(qrImageUrl, {
      method: "POST",
      headers,
      body: JSON.stringify({ token }),
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (_error) {
    throw new Error("防伪二维码加载失败，请检查网络后重试");
  }
  if (!response.ok) {
    let data = null;
    if ((response.headers.get("content-type") || "").includes("application/json")) {
      try { data = await response.json(); } catch (_error) { data = null; }
    }
    throw new Error(apiErrorDetails(data, response.status).message);
  }
  if (!(response.headers.get("content-type") || "").includes("image/png")) {
    throw new Error("防伪二维码响应格式异常，请刷新页面后重试");
  }
  let qrBlob;
  try {
    qrBlob = await response.blob();
  } catch (_error) {
    throw new Error("防伪二维码加载失败，请检查网络后重试");
  }
  return decodeResultCardVerificationQr(qrBlob);
}

function resultCardBlob(canvas) {
  return new Promise((resolve, reject) => {
    if (typeof canvas.toBlob !== "function") {
      reject(new Error("当前浏览器不支持生成结果卡，请更换浏览器后重试"));
      return;
    }
    canvas.toBlob((blob) => {
      if (blob) resolve(blob);
      else reject(new Error("结果卡生成失败，请释放设备存储空间后重试"));
    }, "image/png");
  });
}

function resultCardDataUrl(blob) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result || ""));
    reader.onerror = () => reject(new Error("凭证预览生成失败，可直接下载高清凭证"));
    reader.readAsDataURL(blob);
  });
}

async function createResultCardBlob(payload) {
  if (!payload?.selection || !payload?.student || !payload?.settings) {
    throw new Error("尚未读取到完整抢选结果，请刷新页面后重试");
  }
  if (document.fonts?.ready) await document.fonts.ready;
  let verificationQr = null;
  let verificationQrReleaseRequested = false;
  const releaseVerificationQr = () => {
    if (!verificationQr) return;
    const currentQr = verificationQr;
    verificationQr = null;
    if (typeof currentQr.close === "function") currentQr.close();
  };
  try {
  const logoPromise = Promise.resolve().then(() => loadResultCardLogo());
  const verificationQrPromise = Promise.resolve()
    .then(() => loadResultCardVerificationQr(payload))
    .then((decodedQr) => {
      verificationQr = decodedQr;
      if (verificationQrReleaseRequested) releaseVerificationQr();
      return decodedQr;
    });
  const [logo] = await Promise.all([logoPromise, verificationQrPromise]);
  const receipt = payload.receipt || {};
  const verificationCode = String(receipt.verification_code || "").trim();
  const hasOnlineVerification = Boolean(verificationCode && receipt.verify_url);
  const canScanVerify = hasOnlineVerification && Boolean(verificationQr);
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1920;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("当前浏览器无法创建抢选结果凭证，请更换浏览器后重试");

  const pageGradient = context.createLinearGradient(0, 0, 1080, 1920);
  pageGradient.addColorStop(0, "#6f2028");
  pageGradient.addColorStop(0.56, "#8b3037");
  pageGradient.addColorStop(1, "#4e171d");
  context.fillStyle = pageGradient;
  context.fillRect(0, 0, canvas.width, canvas.height);

  context.strokeStyle = "rgba(255, 255, 255, .08)";
  context.lineWidth = 2;
  for (let coordinate = -960; coordinate <= 2040; coordinate += 68) {
    context.beginPath();
    context.moveTo(coordinate, 0);
    context.lineTo(coordinate + 960, 1920);
    context.stroke();
  }

  context.save();
  context.shadowColor = "rgba(25, 4, 8, .34)";
  context.shadowBlur = 44;
  context.shadowOffsetY = 22;
  roundedRectangle(context, 52, 42, 976, 1836, 42);
  context.fillStyle = "#fffdfc";
  context.fill();
  context.restore();

  roundedRectangle(context, 52, 42, 976, 1836, 42);
  context.strokeStyle = "rgba(255, 255, 255, .42)";
  context.lineWidth = 2;
  context.stroke();

  context.save();
  roundedRectangle(context, 52, 42, 976, 336, 42);
  context.clip();
  const headerGradient = context.createLinearGradient(52, 42, 1028, 378);
  headerGradient.addColorStop(0, "#7a252d");
  headerGradient.addColorStop(1, "#4f171d");
  context.fillStyle = headerGradient;
  context.fillRect(52, 42, 976, 336);
  context.strokeStyle = "rgba(255, 255, 255, .12)";
  context.lineWidth = 2;
  for (let x = -160; x < 1240; x += 112) {
    context.beginPath();
    context.moveTo(x, 378);
    context.lineTo(x + 280, 42);
    context.stroke();
  }
  context.restore();

  roundedRectangle(context, 52, 42, 976, 14, 7);
  context.fillStyle = "#c9a363";
  context.fill();

  // Crop only the transparent margins around the official college wordmark.
  context.drawImage(logo, 328, 152, 3808, 909, 96, 88, 888, 212);

  context.fillStyle = "#7f292f";
  context.font = '800 23px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText("TEACHING GROUP SELECTION · RESULT RECEIPT", 100, 438);
  context.fillStyle = "#282123";
  context.font = '900 64px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText("抢选结果凭证", 100, 516);
  context.fillStyle = "#6f6466";
  context.font = '700 27px "Microsoft YaHei", "PingFang SC", sans-serif';
  const activityBottom = drawWrappedCardText(context, payload.settings.activity_title, 100, 568, 880, 38, 2);

  const statusY = Math.max(634, activityBottom + 22);
  roundedRectangle(context, 100, statusY, 880, 86, 22);
  context.fillStyle = "#eaf4f0";
  context.fill();
  context.strokeStyle = "#bdd8ce";
  context.lineWidth = 2;
  context.stroke();
  context.fillStyle = "#2f7560";
  context.font = '900 30px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText("✓  服务器已确认本次抢选记录", 138, statusY + 55);

  const detailsY = statusY + 118;
  roundedRectangle(context, 100, detailsY, 880, 574, 28);
  context.fillStyle = "#f8f3f3";
  context.fill();
  context.strokeStyle = "#c9aaad";
  context.lineWidth = 2;
  context.stroke();

  const labelFont = '700 22px "Microsoft YaHei", "PingFang SC", sans-serif';
  const valueFont = '900 35px "Microsoft YaHei", "PingFang SC", sans-serif';
  const detailRows = [
    ["姓名", payload.student.name, 140, detailsY + 60, 344],
    ["学号", payload.student.student_no, 554, detailsY + 60, 370],
    ["专业", payload.student.major_name, 140, detailsY + 208, 344],
    ["系统记录时间", formatStudentTime(payload.selection.selected_at), 554, detailsY + 208, 370],
  ];
  for (const [label, value, x, y, maxWidth] of detailRows) {
    context.fillStyle = "#766d6e";
    context.font = labelFont;
    context.fillText(label, x, y);
    context.fillStyle = "#2f292a";
    context.font = valueFont;
    if (label === "姓名" || label === "专业") {
      drawFittedCardText(context, value, x, y + 46, maxWidth, 35, 2);
    } else {
      drawWrappedCardText(context, value, x, y + 46, maxWidth, 42, 2);
    }
  }
  context.strokeStyle = "#e4d7d8";
  context.beginPath();
  context.moveTo(132, detailsY + 354);
  context.lineTo(948, detailsY + 354);
  context.stroke();
  context.fillStyle = "#766d6e";
  context.font = labelFont;
  context.fillText("已选教学组", 140, detailsY + 410);
  context.fillStyle = "#7f292f";
  drawFittedCardText(context, payload.selection.group_name, 140, detailsY + 470, 780, 48, 2);

  const verificationY = detailsY + 608;
  roundedRectangle(context, 100, verificationY, 880, 286, 28);
  context.fillStyle = "#fff8eb";
  context.fill();
  context.strokeStyle = "#ead1ac";
  context.lineWidth = 2;
  context.stroke();
  context.fillStyle = "#7f292f";
  context.font = '900 27px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText(hasOnlineVerification ? "在线核验" : "记录核对", 138, verificationY + 54);
  context.fillStyle = "#766d6e";
  context.font = '700 21px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText("核验编号", 138, verificationY + 100);
  context.fillStyle = "#2f292a";
  context.font = '900 33px ui-monospace, "SFMono-Regular", Consolas, monospace';
  context.fillText(verificationCode || "以系统导出记录为准", 138, verificationY + 143);
  context.fillStyle = "#766d6e";
  context.font = '600 21px "Microsoft YaHei", "PingFang SC", sans-serif';
  drawWrappedCardText(
    context,
    canScanVerify
      ? "扫码可核对服务端原始记录。请勿修改凭证图片，任何差异均以在线核验和学院导出结果为准。"
      : hasOnlineVerification
        ? "在线核验暂不可用，请保留核验编号，并以学院系统导出记录为准。"
        : "请勿修改凭证图片；核对时以学院导出的系统原始记录为准。",
    138,
    verificationY + 188,
    verificationQr ? 550 : 790,
    32,
    3,
  );

  const watermarkText = verificationCode || `${payload.settings.activity_id || "CURRENT"} · SYSTEM RECORD`;
  context.save();
  roundedRectangle(context, 100, verificationY, 880, 286, 28);
  context.clip();
  context.translate(70, verificationY + 40);
  context.rotate(-Math.PI / 12);
  context.fillStyle = "rgba(127, 41, 47, .045)";
  context.font = '800 17px ui-monospace, "SFMono-Regular", Consolas, monospace';
  for (let row = -2; row < 8; row += 1) {
    for (let column = -2; column < 7; column += 1) {
      context.fillText(`AHJZU · ${watermarkText}`, column * 240, row * 48);
    }
  }
  context.restore();

  if (verificationQr) {
    roundedRectangle(context, 734, verificationY + 34, 210, 210, 18);
    context.fillStyle = "#ffffff";
    context.fill();
    context.strokeStyle = "#d8bba0";
    context.lineWidth = 2;
    context.stroke();
    context.imageSmoothingEnabled = false;
    try {
      context.drawImage(verificationQr, 747, verificationY + 47, 184, 184);
    } finally {
      context.imageSmoothingEnabled = true;
    }
  }

  context.strokeStyle = "#c9aaad";
  context.setLineDash([8, 8]);
  context.beginPath();
  context.moveTo(100, 1792);
  context.lineTo(980, 1792);
  context.stroke();
  context.setLineDash([]);
  context.fillStyle = "#766d6e";
  context.font = '600 21px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.textAlign = "center";
  context.fillText("安徽建筑大学 · 建筑与空间规划学院", 540, 1830);
  context.font = '600 18px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText("制作：Mikutea  ·  最终安排以学院正式发布结果为准", 540, 1861);
  context.textAlign = "start";

  return await resultCardBlob(canvas);
  } finally {
    verificationQrReleaseRequested = true;
    releaseVerificationQr();
  }
}

function resultCardPreviewKey(payload) {
  if (!payload?.selection || !payload?.student || !payload?.settings) return null;
  return JSON.stringify([
    payload.settings.activity_id,
    payload.settings.activity_title,
    payload.student.student_no,
    payload.student.name,
    payload.student.major_name,
    payload.selection.group_id,
    payload.selection.group_name,
    payload.selection.selected_at,
    payload.receipt?.verification_code || "",
    payload.receipt?.qr_image_url || "",
  ]);
}

async function ensureStudentResultCardPreview(payload) {
  const key = resultCardPreviewKey(payload);
  if (!key || key === studentState.resultCardPreviewKey || key === studentState.resultCardPreviewPendingKey) return;
  studentState.resultCardPreviewPendingKey = key;
  studentEls.resultCardPreviewImage.hidden = true;
  studentEls.resultCardPreviewStatus.hidden = false;
  studentEls.resultCardPreviewStatus.textContent = "正在生成 9:16 凭证预览…";
  try {
    const blob = await createResultCardBlob(payload);
    if (key !== resultCardPreviewKey(studentState.payload)) return;
    const nextUrl = await resultCardDataUrl(blob);
    if (key !== resultCardPreviewKey(studentState.payload)) return;
    studentState.resultCardPreviewUrl = nextUrl;
    studentState.resultCardPreviewKey = key;
    studentEls.resultCardPreviewImage.src = nextUrl;
    studentEls.resultCardPreviewImage.hidden = false;
    studentEls.resultCardPreviewStatus.hidden = true;
  } catch (error) {
    if (key !== resultCardPreviewKey(studentState.payload)) return;
    studentEls.resultCardPreviewImage.hidden = true;
    studentEls.resultCardPreviewStatus.hidden = false;
    studentEls.resultCardPreviewStatus.textContent = error.message || "凭证预览生成失败，可点击下方按钮重试下载";
  } finally {
    if (studentState.resultCardPreviewPendingKey === key) studentState.resultCardPreviewPendingKey = null;
  }
}

async function downloadStudentResultCard() {
  if (studentState.resultCardInFlight) return;
  studentState.resultCardInFlight = true;
  studentEls.downloadResultCard.disabled = true;
  studentEls.downloadResultCard.textContent = "正在生成手机高清凭证…";
  try {
    const blob = await createResultCardBlob(studentState.payload);
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const safeStudentNo = String(studentState.payload.student.student_no).replace(/[^A-Za-z0-9_-]/g, "_");
    anchor.href = objectUrl;
    anchor.download = `抢选结果凭证-${safeStudentNo}.png`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    showStudentMessage("抢选结果凭证已下载，请妥善保存", "success");
  } catch (error) {
    showStudentMessage(error.message || "结果卡下载失败，请稍后重试", "error");
  } finally {
    studentState.resultCardInFlight = false;
    studentEls.downloadResultCard.disabled = false;
    studentEls.downloadResultCard.textContent = "下载抢选结果凭证";
  }
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

function updateProfessionalBadges(majorName) {
  const badge = professionalBadge(majorName);
  const accessibleLabel = `专业：${majorName || badge}`;
  for (const element of [studentEls.displayBadge, studentEls.waitingBadge, studentEls.successBadge]) {
    element.textContent = badge;
    element.title = accessibleLabel;
    element.setAttribute("aria-label", accessibleLabel);
  }
}

function setStudentCountdownDisplay(value) {
  const nextValue = String(value);
  if (studentEls.countdownValue.textContent !== nextValue) {
    studentEls.countdownValue.textContent = nextValue;
  }
}

function announceStudentPhaseTransition(phase) {
  const previous = studentState.lastPhase;
  studentState.lastPhase = phase;
  if (!previous || previous === phase) return;
  const messages = {
    countdown: ["老师已开始抢选，统一倒计时已启动", "info"],
    open: ["抢选现已开放，请立即选择教学组", "success"],
    paused: ["抢选已暂停，请保留页面并等待老师通知", "error"],
    closed: ["本场抢选已关闭，请等待老师后续通知", "error"],
    ended: ["本场抢选已结束", "info"],
    waiting: ["已回到候场状态，请保持页面打开", "info"],
  };
  const message = messages[phase];
  if (message) showStudentMessage(message[0], message[1]);
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
  updateProfessionalBadges(payload.student.major_name);

  if (payload.selection) {
    document.body.dataset.studentView = "success";
    studentEls.choiceView.classList.add("is-hidden");
    studentEls.waitingView.classList.add("is-hidden");
    studentEls.successView.classList.remove("is-hidden");
    studentEls.successMessage.textContent = `已成功选择「${payload.selection.group_name}」`;
    studentEls.successTime.textContent = formatStudentTime(payload.selection.selected_at);
    void ensureStudentResultCardPreview(payload);
    return;
  }

  studentEls.successView.classList.add("is-hidden");
  const phase = studentPhase(payload);
  announceStudentPhaseTransition(phase);
  if (phase !== "open") {
    document.body.dataset.studentView = phase === "countdown" ? "countdown" : "waiting";
    studentEls.choiceView.classList.add("is-hidden");
    studentEls.waitingView.classList.remove("is-hidden");
    studentEls.waitingView.classList.toggle("is-countdown", phase === "countdown");
    const remaining = millisecondsUntilStudentOpen(payload);
    const seconds = remaining === null ? 10 : Math.max(0, Math.ceil(remaining / 1000));
    if (phase === "countdown") {
      setStudentCountdownDisplay(seconds);
      studentEls.waitingTitle.textContent = "全体同步倒计时";
      studentEls.waitingMessage.textContent = "倒计时结束后将自动进入选组页面，请不要退出或锁屏。";
      studentEls.waitingLiveNote.textContent = "时间以服务器为准，所有同学同时开抢";
    } else if (["closed", "ended", "paused"].includes(phase)) {
      setStudentCountdownDisplay("END");
      studentEls.waitingTitle.textContent = phase === "paused" ? "抢选已暂停" : "本场抢选已关闭";
      studentEls.waitingMessage.textContent = "当前无法提交，请等待老师后续通知。";
      studentEls.waitingLiveNote.textContent = "页面会继续自动同步活动状态";
    } else {
      setStudentCountdownDisplay("READY");
      studentEls.waitingTitle.textContent = "已进入抢选候场";
      studentEls.waitingMessage.textContent = "请保持页面打开，等待老师开始统一倒计时。";
      studentEls.waitingLiveNote.textContent = "候场状态每秒自动同步";
    }
    return;
  }

  studentState.boundaryRefreshPending = false;
  document.body.dataset.studentView = "choice";
  studentEls.waitingView.classList.add("is-hidden");
  studentEls.choiceView.classList.remove("is-hidden");
  studentEls.groupList.replaceChildren(...payload.groups.map((group) => createGroupOption(group, payload)));
  const selected = payload.groups.find((group) => group.id === studentState.selectedGroupId && !group.full);
  studentEls.submitChoice.disabled = !selected;
  studentEls.choiceHint.textContent = selected
    ? `将选择：${selected.name}，当前剩余 ${selected.remaining} 个名额`
    : "请选择一个仍有名额的教学组";
}

function mergePublicStatusIntoStudentPayload(payload, status) {
  if (!payload || !status) return payload;
  const settings = {
    ...payload.settings,
    activity_id: status.activity_id,
    status: status.status,
    phase: status.phase,
    server_now: status.server_now,
    selection_opens_at: status.selection_opens_at,
    student_login_allowed: status.student_login_allowed,
    status_message: status.status_message,
  };
  return {
    ...payload,
    status: status.status,
    phase: status.phase,
    server_now: status.server_now,
    selection_opens_at: status.selection_opens_at,
    student_login_allowed: status.student_login_allowed,
    status_message: status.status_message,
    settings,
  };
}

async function loadPublicInfo() {
  try {
    const data = await studentApi("/api/public/info");
    synchronizeStudentClock(data);
    markStudentConnectionHealthy();
    renderStudentSettings(data.settings, data);
  } catch (error) {
    reportStudentConnectionIssue(error);
  }
}

async function loadStudentSession() {
  try {
    const data = await studentApi("/api/student/me");
    studentState.csrf = data.csrf_token;
    markStudentConnectionHealthy();
    renderStudentPayload(data);
    startStudentPolling();
  } catch (error) {
    if (error.status !== 401) showStudentMessage(error.message, "error");
  }
}

function startStudentPolling() {
  clearInterval(studentState.pollTimer);
  clearInterval(studentState.heartbeatTimer);
  studentState.pollTimer = setInterval(async () => {
    if (studentState.pollInFlight) return;
    const pollStartedAt = studentMonotonicNow();
    if (
      studentState.payload?.selection
      && pollStartedAt - studentState.lastSelectedSyncAt < 5000
    ) return;
    if (studentState.payload?.selection) studentState.lastSelectedSyncAt = pollStartedAt;
    studentState.pollInFlight = true;
    try {
      const hadSelection = Boolean(studentState.payload?.selection);
      const phaseBeforePoll = studentPhase(studentState.payload);
      let data;
      if (!hadSelection && phaseBeforePoll !== "open") {
        const publicStatus = await studentApi("/api/public/status");
        const currentActivityId = studentState.payload?.settings?.activity_id;
        if (String(publicStatus.activity_id) !== String(currentActivityId)) {
          data = await studentApi("/api/student/me");
        } else {
          data = mergePublicStatusIntoStudentPayload(studentState.payload, publicStatus);
          renderStudentPayload(data);
          if (studentPhase(data) !== "open") {
            markStudentConnectionHealthy();
            return;
          }
          data = await studentApi("/api/student/me");
        }
      } else {
        data = await studentApi("/api/student/me");
      }
      if (data.csrf_token) studentState.csrf = data.csrf_token;
      markStudentConnectionHealthy();
      const selectedStillAvailable = data.groups.some((group) => group.id === studentState.selectedGroupId && !group.full);
      if (!selectedStillAvailable) studentState.selectedGroupId = null;
      renderStudentPayload(data);
      if (hadSelection && !data.selection) {
        showStudentMessage("原选择已被管理员撤销，请按当前状态重新选择或等待通知", "error");
      }
    } catch (error) {
      if (error.status === 401) {
        handleStudentSessionExpired();
      } else reportStudentConnectionIssue(error);
    } finally {
      studentState.pollInFlight = false;
    }
  }, 1000);
  studentState.heartbeatTimer = setInterval(async () => {
    if (studentState.heartbeatInFlight || !studentState.payload || studentState.payload.selection) return;
    studentState.heartbeatInFlight = true;
    try {
      await studentApi("/api/student/heartbeat", { method: "POST", body: JSON.stringify({}) });
      markStudentConnectionHealthy();
    } catch (error) {
      if (error.status === 401) handleStudentSessionExpired();
      else reportStudentConnectionIssue(error);
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
    setStudentCountdownDisplay(seconds);
    studentEls.publicStatus.lastElementChild.textContent = `统一倒计时 ${seconds} 秒 · 即将同时开抢`;
    return;
  }
  if (phase === "open" && !studentEls.waitingView.classList.contains("is-hidden")) {
    renderStudentPayload(payload);
    if (studentState.boundaryRefreshPending || studentState.pollInFlight) return;
    studentState.boundaryRefreshPending = true;
    studentApi("/api/student/me")
      .then((latest) => renderStudentPayload(latest))
      .catch(() => { /* the one-second poll will retry */ })
      .finally(() => { studentState.boundaryRefreshPending = false; });
  }
}

studentEls.loginForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearStudentFieldErrors();
  const form = new FormData(studentEls.loginForm);
  const loginPayload = normalizeStudentLoginPayload(Object.fromEntries(form.entries()));
  for (const [fieldName, value] of Object.entries(loginPayload)) {
    studentLoginFields[fieldName].input.value = value;
  }
  const validationErrors = validateStudentLoginPayload(loginPayload);
  if (Object.keys(validationErrors).length) {
    for (const [fieldName, message] of Object.entries(validationErrors)) {
      setStudentFieldError(fieldName, message);
    }
    focusFirstStudentFieldError(validationErrors);
    showStudentMessage("请先修正标出的身份信息", "error");
    return;
  }
  const submit = studentEls.loginForm.querySelector("button[type=submit]");
  submit.disabled = true;
  submit.textContent = "正在核验…";
  try {
    const data = await studentApi("/api/student/login", {
      method: "POST",
      body: JSON.stringify(loginPayload),
    });
    studentState.csrf = data.csrf_token;
    studentState.selectedGroupId = null;
    markStudentConnectionHealthy();
    renderStudentPayload(data);
    startStudentPolling();
    showStudentMessage("身份核验成功", "success");
  } catch (error) {
    showStudentMessage(error.message, "error");
    if (error.status === 422 && error.field) {
      setStudentFieldError(error.field, error.message);
      focusFirstStudentFieldError({ [error.field]: error.message });
    }
  } finally {
    submit.disabled = false;
    submit.innerHTML = "核验并进入 <span aria-hidden=\"true\">→</span>";
  }
});

studentEls.loginForm.addEventListener("input", (event) => {
  if (!(event.target instanceof HTMLInputElement)) return;
  if (event.target.name === "student_no") {
    const normalized = normalizeCompatibilityText(event.target.value).replace(/\D/g, "").slice(0, STUDENT_NO_INPUT_LENGTH);
    if (normalized !== event.target.value) event.target.value = normalized;
  } else if (event.target.name === "activation_code") {
    const normalized = Array.from(normalizeCompatibilityText(event.target.value).toUpperCase()).slice(0, 6).join("");
    if (normalized !== event.target.value) event.target.value = normalized;
  }
  setStudentFieldError(event.target.name);
});

studentEls.loginForm.addEventListener("focusout", (event) => {
  if (!(event.target instanceof HTMLInputElement) || !studentLoginFields[event.target.name]) return;
  const normalized = normalizeStudentLoginPayload({
    student_no: studentLoginFields.student_no.input.value,
    name: studentLoginFields.name.input.value,
    activation_code: studentLoginFields.activation_code.input.value,
  });
  event.target.value = normalized[event.target.name];
  const fieldError = validateStudentLoginPayload(normalized)[event.target.name] || "";
  setStudentFieldError(event.target.name, fieldError);
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
    markStudentConnectionHealthy();
    renderStudentPayload(data);
    showStudentMessage("选择已由服务器确认", "success");
  } catch (error) {
    studentState.selectedGroupId = null;
    showStudentMessage(error.message, "error");
    if (error.status === 401) {
      handleStudentSessionExpired();
      return;
    }
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
  let reloadDelay = 0;
  try {
    await studentApi("/api/student/logout", { method: "POST", body: JSON.stringify({}) });
  } catch (error) {
    if (error.status !== 401) {
      reloadDelay = 900;
      showStudentMessage(`${error.message}；本机页面仍将退出`, "error");
    }
  }
  setTimeout(() => window.location.reload(), reloadDelay);
}

function syncStudentViewportHeight() {
  const viewportHeight = Math.round(window.visualViewport?.height || window.innerHeight || 0);
  if (viewportHeight > 0) {
    document.documentElement.style.setProperty("--student-app-height", `${viewportHeight}px`);
  }
  const layoutHeight = Math.round(document.documentElement.clientHeight || window.innerHeight || viewportHeight);
  const keyboardInset = Math.max(0, layoutHeight - viewportHeight);
  const loginFieldFocused = Boolean(document.activeElement?.closest?.("#student-login-form"));
  const keyboardOpen = viewportHeight > 0
    && viewportHeight <= 480
    && (keyboardInset >= 100 || (Boolean(window.visualViewport) && loginFieldFocused));
  document.body.classList.toggle("student-keyboard-open", keyboardOpen);
}

window.addEventListener("offline", () => {
  const error = new Error("网络连接中断，页面会自动重试");
  error.status = 0;
  reportStudentConnectionIssue(error);
});
window.addEventListener("online", () => {
  renderStudentServerClock();
  showStudentMessage("网络已恢复，正在重新同步服务器状态", "info");
});
window.addEventListener("resize", syncStudentViewportHeight, { passive: true });
window.visualViewport?.addEventListener("resize", syncStudentViewportHeight, { passive: true });
studentEls.loginForm.addEventListener("focusin", () => requestAnimationFrame(syncStudentViewportHeight));
studentEls.loginForm.addEventListener("focusout", () => setTimeout(syncStudentViewportHeight, 0));

document.querySelector("#student-logout").addEventListener("click", studentLogout);
document.querySelector("#waiting-logout").addEventListener("click", studentLogout);
document.querySelector("#success-logout").addEventListener("click", studentLogout);
studentEls.downloadResultCard.addEventListener("click", downloadStudentResultCard);

studentState.countdownTimer = setInterval(tickStudentCountdown, 200);
studentState.clockTimer = setInterval(renderStudentServerClock, 1000);
syncStudentViewportHeight();
renderStudentServerClock();
loadPublicInfo();
loadStudentSession();
