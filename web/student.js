"use strict";

const STUDENT_NO_PATTERN = /^[A-Za-z0-9_-]{4,32}$/;
const STUDENT_NAME_PATTERN = /^[\p{Script=Han}\p{Script=Latin} ·•・'’\-‐‑]{1,80}$/u;
const ACTIVATION_CODE_PATTERN = /^[A-Z0-9]{6}$/;

function normalizeCompatibilityText(value) {
  return String(value ?? "").normalize("NFKC");
}

function normalizeStudentLoginPayload(values) {
  return {
    student_no: normalizeCompatibilityText(values.student_no).trim(),
    name: normalizeCompatibilityText(values.name).trim().replace(/\s+/gu, " "),
    activation_code: normalizeCompatibilityText(values.activation_code).trim().toUpperCase(),
  };
}

function validateStudentLoginPayload(payload) {
  const errors = {};
  if (!payload.student_no) {
    errors.student_no = "请输入学号";
  } else if (!STUDENT_NO_PATTERN.test(payload.student_no)) {
    errors.student_no = "学号须为 4–32 位字母、数字、短横线或下划线";
  }
  if (!payload.name) {
    errors.name = "请输入姓名";
  } else if (!STUDENT_NAME_PATTERN.test(payload.name)) {
    errors.name = "姓名只能包含中文、拉丁字母、空格、间隔点、撇号或连字符";
  }
  if (!payload.activation_code) {
    errors.activation_code = "请输入个人激活码";
  } else if (!ACTIVATION_CODE_PATTERN.test(payload.activation_code)) {
    errors.activation_code = "个人激活码须为证件号后 6 位字母或数字";
  }
  return errors;
}

function professionalBadge(majorName) {
  const major = normalizeCompatibilityText(majorName).trim();
  if (major.includes("建筑学")) return "建";
  if (major.includes("城乡规划")) return "规";
  if (major.includes("风景园林")) return "景";
  const firstMeaningful = Array.from(major).find((character) => /[\p{Script=Han}\p{Script=Latin}]/u.test(character));
  return firstMeaningful ? firstMeaningful.toLocaleUpperCase("zh-CN") : "专";
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
  heartbeatInFlight: false,
  boundaryRefreshPending: false,
  serverClockOffset: 0,
  connectionInterrupted: false,
  lastBackgroundErrorAt: 0,
  sessionReloadTimer: null,
  lastPhase: null,
  resultCardInFlight: false,
  resultCardLogoPromise: null,
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
  downloadResultCard: document.querySelector("#download-result-card"),
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
  field.input.focus({ preventScroll: false });
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
      student_no: "学号须为 4–32 位字母、数字、短横线或下划线",
      name: "姓名只能包含中文、拉丁字母、空格、间隔点、撇号或连字符",
      activation_code: "个人激活码须为证件号后 6 位字母或数字",
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
  try {
    response = await fetch(path, { ...options, headers, credentials: "same-origin" });
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
  showStudentMessage(error.status === 0 ? "网络连接中断，页面会自动重试" : `${error.message}；页面会自动重试`, "error");
}

function markStudentConnectionHealthy() {
  if (!studentState.connectionInterrupted) return;
  studentState.connectionInterrupted = false;
  showStudentMessage("连接已恢复，名额和活动状态已同步", "success");
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

async function createResultCardBlob(payload) {
  if (!payload?.selection || !payload?.student || !payload?.settings) {
    throw new Error("尚未读取到完整选择结果，请刷新页面后重试");
  }
  if (document.fonts?.ready) await document.fonts.ready;
  const logo = await loadResultCardLogo();
  const canvas = document.createElement("canvas");
  canvas.width = 1080;
  canvas.height = 1440;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("当前浏览器无法创建结果卡，请更换浏览器后重试");

  context.fillStyle = "#f3eded";
  context.fillRect(0, 0, canvas.width, canvas.height);
  context.strokeStyle = "rgba(127, 41, 47, .055)";
  context.lineWidth = 1;
  for (let coordinate = 0; coordinate <= 1440; coordinate += 36) {
    context.beginPath();
    context.moveTo(coordinate, 0);
    context.lineTo(coordinate, 1440);
    context.stroke();
    context.beginPath();
    context.moveTo(0, coordinate);
    context.lineTo(1080, coordinate);
    context.stroke();
  }

  context.save();
  context.shadowColor = "rgba(72, 24, 29, .16)";
  context.shadowBlur = 34;
  context.shadowOffsetY = 14;
  roundedRectangle(context, 54, 48, 972, 1344, 34);
  context.fillStyle = "#fffdfc";
  context.fill();
  context.restore();

  roundedRectangle(context, 54, 48, 972, 18, 9);
  context.fillStyle = "#7f292f";
  context.fill();

  // The official college wordmark is white artwork. Give it a full brand
  // field so every stroke remains visible in the downloaded card.
  context.fillStyle = "#7f292f";
  context.fillRect(54, 66, 972, 250);

  // The source asset contains transparent margins; crop to its official visible artwork.
  context.drawImage(logo, 328, 152, 3808, 909, 96, 98, 888, 212);

  context.fillStyle = "#7f292f";
  context.font = '800 24px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.letterSpacing = "3px";
  context.fillText("TEACHING GROUP SELECTION", 96, 364);
  context.letterSpacing = "0px";
  context.fillStyle = "#2f292a";
  context.font = '900 58px "Microsoft YaHei", "PingFang SC", sans-serif';
  const titleBottom = drawWrappedCardText(context, payload.settings.activity_title, 96, 434, 888, 72, 2);

  const statusY = Math.max(540, titleBottom + 5);
  roundedRectangle(context, 96, statusY, 888, 92, 18);
  context.fillStyle = "#eaf4f0";
  context.fill();
  context.fillStyle = "#2f7560";
  context.font = '900 33px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText("✓  服务器已确认选择成功", 132, statusY + 58);

  const detailsY = statusY + 116;
  roundedRectangle(context, 96, detailsY, 888, 400, 24);
  context.fillStyle = "#f8f3f3";
  context.fill();
  context.strokeStyle = "#c9aaad";
  context.lineWidth = 2;
  context.stroke();

  const labelFont = '700 23px "Microsoft YaHei", "PingFang SC", sans-serif';
  const valueFont = '900 34px "Microsoft YaHei", "PingFang SC", sans-serif';
  const detailRows = [
    ["学生", payload.student.name, 150, detailsY + 48],
    ["学号", payload.student.student_no, 150, detailsY + 170],
    ["专业", payload.student.major_name, 570, detailsY + 48],
    ["教学组", payload.selection.group_name, 570, detailsY + 170],
  ];
  for (const [label, value, x, y] of detailRows) {
    context.fillStyle = "#766d6e";
    context.font = labelFont;
    context.fillText(label, x, y);
    context.fillStyle = "#2f292a";
    context.font = valueFont;
    drawWrappedCardText(context, value, x, y + 40, x < 500 ? 350 : 340, 40, 2);
  }
  context.strokeStyle = "#e4d7d8";
  context.beginPath();
  context.moveTo(126, detailsY + 280);
  context.lineTo(954, detailsY + 280);
  context.stroke();
  context.fillStyle = "#766d6e";
  context.font = labelFont;
  context.fillText("系统记录时间", 150, detailsY + 320);
  context.fillStyle = "#7f292f";
  context.font = '900 34px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText(formatStudentTime(payload.selection.selected_at), 150, detailsY + 366);

  const verificationY = detailsY + 440;
  context.fillStyle = "#7f292f";
  context.font = '900 27px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.fillText("结果核验说明", 96, verificationY);
  context.fillStyle = "#766d6e";
  context.font = '500 24px "Microsoft YaHei", "PingFang SC", sans-serif';
  drawWrappedCardText(
    context,
    "本卡片由系统按统一尺寸生成，仅作为学生本人提交凭据；最终教学组安排以学院正式发布结果为准。",
    96,
    verificationY + 48,
    888,
    40,
    3,
  );

  context.strokeStyle = "#c9aaad";
  context.setLineDash([8, 8]);
  context.beginPath();
  context.moveTo(96, 1301);
  context.lineTo(984, 1301);
  context.stroke();
  context.setLineDash([]);
  context.fillStyle = "#766d6e";
  context.font = '600 20px "Microsoft YaHei", "PingFang SC", sans-serif';
  context.textAlign = "center";
  context.fillText("安徽建筑大学 · 建筑与空间规划学院  制作：Mikutea", 540, 1348);
  context.textAlign = "start";

  return resultCardBlob(canvas);
}

async function downloadStudentResultCard() {
  if (studentState.resultCardInFlight) return;
  studentState.resultCardInFlight = true;
  studentEls.downloadResultCard.disabled = true;
  studentEls.downloadResultCard.textContent = "正在生成 1080 × 1440 结果卡…";
  try {
    const blob = await createResultCardBlob(studentState.payload);
    const objectUrl = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    const safeStudentNo = String(studentState.payload.student.student_no).replace(/[^A-Za-z0-9_-]/g, "_");
    anchor.href = objectUrl;
    anchor.download = `教学组选择结果-${safeStudentNo}.png`;
    document.body.append(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(objectUrl), 1500);
    showStudentMessage("统一结果卡已生成，请在浏览器下载记录中查看", "success");
  } catch (error) {
    showStudentMessage(error.message || "结果卡下载失败，请稍后重试", "error");
  } finally {
    studentState.resultCardInFlight = false;
    studentEls.downloadResultCard.disabled = false;
    studentEls.downloadResultCard.textContent = "下载统一结果卡";
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
  const accessibleLabel = `${majorName || "当前"}专业标识：${badge}`;
  for (const element of [studentEls.displayBadge, studentEls.waitingBadge]) {
    element.textContent = badge;
    element.title = accessibleLabel;
    element.setAttribute("aria-label", accessibleLabel);
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
    clearInterval(studentState.pollTimer);
    clearInterval(studentState.heartbeatTimer);
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
      markStudentConnectionHealthy();
      const selectedStillAvailable = data.groups.some((group) => group.id === studentState.selectedGroupId && !group.full);
      if (!selectedStillAvailable) studentState.selectedGroupId = null;
      renderStudentPayload(data);
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
  if (event.target.name === "activation_code") {
    const normalized = normalizeCompatibilityText(event.target.value).toUpperCase().replace(/[^A-Z0-9]/g, "").slice(0, 6);
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

document.querySelector("#student-logout").addEventListener("click", studentLogout);
document.querySelector("#waiting-logout").addEventListener("click", studentLogout);
document.querySelector("#success-logout").addEventListener("click", studentLogout);
studentEls.downloadResultCard.addEventListener("click", downloadStudentResultCard);

studentState.countdownTimer = setInterval(tickStudentCountdown, 200);
loadPublicInfo();
loadStudentSession();
