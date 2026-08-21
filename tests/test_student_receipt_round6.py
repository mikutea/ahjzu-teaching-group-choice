from __future__ import annotations

import subprocess
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ReceiptMarkupParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}
        self.meta: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.by_id[values["id"]] = {"tag": tag, **values}
        if tag == "meta":
            self.meta.append(values)


def test_student_result_receipt_is_mobile_portrait_and_never_contains_login_secret() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    parser = ReceiptMarkupParser()
    parser.feed(html)

    preview = parser.by_id["result-card-preview-image"]
    assert preview["width"] == "1080"
    assert preview["height"] == "1920"
    assert preview["alt"] == "抢选结果凭证预览"
    assert "9:16 手机竖版预览" in html
    assert "请下载并妥善保存「抢选结果凭证」，以便后续核对。" in html
    assert "请注意：最终安排以学院正式发布结果为准。" in html

    card_source = javascript.split("async function createResultCardBlob", 1)[1].split(
        "function resultCardPreviewKey", 1
    )[0]
    assert "canvas.width = 1080" in card_source
    assert "canvas.height = 1920" in card_source
    assert "receipt.verification_code" in card_source
    assert "receipt.verify_url" in card_source
    assert "receipt?.qr_image_url" in javascript
    assert "url.origin === window.location.origin" in javascript
    assert 'typeof currentQr.close === "function"' in card_source
    assert "扫码可核对服务端原始记录" in card_source
    assert "在线核验暂不可用" in card_source
    assert 'context.fillText("核"' not in card_source
    assert "activation_code" not in card_source
    assert "身份证" not in card_source
    assert "证件号" not in card_source


def test_receipt_generation_exposes_progress_and_blocks_early_exit() -> None:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    parser = ReceiptMarkupParser()
    parser.feed(html)

    progress = parser.by_id["result-card-progress"]
    assert progress["role"] == "progressbar"
    assert progress["aria-valuemin"] == "0"
    assert progress["aria-valuemax"] == "100"
    assert progress["aria-valuenow"] == "0"
    assert "disabled" in parser.by_id["download-result-card"]
    assert "disabled" in parser.by_id["success-logout"]
    assert parser.by_id["receipt-exit-dialog"]["tag"] == "dialog"
    assert parser.by_id["confirm-receipt-exit"]["value"] == "confirm"
    assert "setStudentResultCardProgress(100" in javascript
    assert "resultCardDownloadedKey" in javascript
    assert "studentState.allowReceiptUnload = true" in javascript
    assert "studentState.resultCardPreviewError" in javascript
    assert "receiptExitDialog.showModal()" in javascript
    assert "void performStudentLogout()" in javascript
    assert 'window.addEventListener("beforeunload"' in javascript
    assert "studentState.allowReceiptUnload" in javascript
    assert "请先下载并保存抢选结果凭证，再安全退出" in javascript
    assert "正在获取防伪二维码" in javascript
    assert "正在编码高清图片" in javascript
    assert ".result-card-progress__track" in css
    assert '.result-card-progress[data-state="ready"]' in css


def test_receipt_failure_allows_confirmed_logout_and_session_expiry_bypasses_unload_guard() -> None:
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    expiry_source = "function handleStudentSessionExpired" + javascript.split(
        "function handleStudentSessionExpired", 1
    )[1].split("function studentField", 1)[0]
    logout_source = "async function performStudentLogout" + javascript.split(
        "async function performStudentLogout", 1
    )[1].split("function syncStudentViewportHeight", 1)[0]
    unload_source = 'window.addEventListener("beforeunload"' + javascript.split(
        'window.addEventListener("beforeunload"', 1
    )[1].split('window.addEventListener("resize"', 1)[0]
    harness = rf"""
const assert = require("node:assert/strict");
const scheduled = [];
let reloads = 0;
let logoutCalls = 0;
let logoutFailure = null;
let delayedLogoutReject = null;
let riskPrompts = 0;
let closeHandler = null;
const listeners = {{}};
const window = {{
  location: {{ reload() {{ reloads += 1; }} }},
  addEventListener(name, handler) {{ listeners[name] = handler; }},
}};
const studentState = {{
  sessionReloadTimer: null,
  studentLogoutInFlight: false,
  pollTimer: 1,
  heartbeatTimer: 2,
  csrf: "csrf",
  allowReceiptUnload: false,
  payload: {{ selection: {{ group_id: 1 }} }},
  resultCardPreviewError: new Error("qr failed"),
  resultCardDownloadedKey: null,
}};
const studentEls = {{
  receiptExitDialog: {{
    returnValue: "",
    showModal() {{ assert.equal(this.returnValue, ""); riskPrompts += 1; }},
    addEventListener(name, handler) {{ assert.equal(name, "close"); closeHandler = handler; }},
  }},
}};
function clearInterval() {{}}
function setTimeout(handler, delay) {{ scheduled.push({{handler, delay}}); return scheduled.length; }}
function clearStudentResultCardPreviewSchedule() {{}}
function showStudentMessage() {{}}
function resultCardPreviewKey() {{ return "receipt-key"; }}
function studentResultCardIsReady() {{ return false; }}
async function studentApi(path) {{
  assert.equal(path, "/api/student/logout");
  logoutCalls += 1;
  if (logoutFailure === "delayed") return new Promise((_, reject) => {{ delayedLogoutReject = reject; }});
  if (logoutFailure) throw logoutFailure;
}}

{expiry_source}
{logout_source}
{unload_source}

(async () => {{
  await studentLogout();
  assert.equal(riskPrompts, 1, "a failed receipt must offer an explicit risk confirmation");
  assert.equal(logoutCalls, 0, "opening the confirmation must not log out yet");
  studentEls.receiptExitDialog.returnValue = "confirm";
  closeHandler();
  await Promise.resolve();
  await Promise.resolve();
  assert.equal(logoutCalls, 1);
  assert.equal(studentState.allowReceiptUnload, true);

  studentState.allowReceiptUnload = false;
  logoutFailure = Object.assign(new Error("offline"), {{status: 0}});
  const scheduledBeforeFailure = scheduled.length;
  const failedLogout = await performStudentLogout();
  assert.equal(failedLogout, false);
  assert.equal(studentState.allowReceiptUnload, false, "failed server logout must restore the unload guard");
  assert.equal(scheduled.length, scheduledBeforeFailure, "failed server logout must not reload the page");
  logoutFailure = null;

  studentState.allowReceiptUnload = false;
  studentState.sessionReloadTimer = null;
  logoutFailure = "delayed";
  const firstOverlappingLogout = performStudentLogout();
  await Promise.resolve();
  const secondOverlappingLogout = await performStudentLogout();
  assert.equal(secondOverlappingLogout, false);
  assert.equal(logoutCalls, 3, "overlapping attempts must use only one server request");
  studentState.allowReceiptUnload = true;
  delayedLogoutReject(Object.assign(new Error("older request failed"), {{status: 0}}));
  assert.equal(await firstOverlappingLogout, false);
  assert.equal(studentState.allowReceiptUnload, true, "a late failure must preserve a newer unload permission");
  logoutFailure = null;

  studentEls.receiptExitDialog.returnValue = "confirm";
  await studentLogout();
  assert.equal(studentEls.receiptExitDialog.returnValue, "", "the dialog result must reset before reopening");

  studentState.allowReceiptUnload = false;
  studentState.sessionReloadTimer = null;
  logoutFailure = "delayed";
  const racingLogout = performStudentLogout();
  await Promise.resolve();
  handleStudentSessionExpired();
  assert.equal(studentState.allowReceiptUnload, true);
  delayedLogoutReject(Object.assign(new Error("offline after expiry"), {{status: 0}}));
  assert.equal(await racingLogout, false);
  assert.equal(
    studentState.allowReceiptUnload,
    true,
    "a late logout failure must not reverse the session-expiry reload bypass",
  );
  logoutFailure = null;

  studentState.allowReceiptUnload = false;
  studentState.sessionReloadTimer = null;
  handleStudentSessionExpired();
  assert.equal(studentState.allowReceiptUnload, true, "expiry recovery must bypass the receipt unload warning");
  assert.equal(studentState.csrf, "");

  studentState.allowReceiptUnload = false;
  const blocked = {{ prevented: false, returnValue: null, preventDefault() {{ this.prevented = true; }} }};
  listeners.beforeunload(blocked);
  assert.equal(blocked.prevented, true);
  studentState.allowReceiptUnload = true;
  const allowed = {{ prevented: false, returnValue: null, preventDefault() {{ this.prevented = true; }} }};
  listeners.beforeunload(allowed);
  assert.equal(allowed.prevented, false);
}})().catch((error) => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_result_preview_is_cached_and_uses_csp_compatible_data_url() -> None:
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    preview_source = javascript.split("function resultCardPreviewKey", 1)[1].split(
        "async function downloadStudentResultCard", 1
    )[0]

    assert "resultCardPreviewPendingKey" in preview_source
    assert "resultCardPreviewPromise" in preview_source
    assert "resultCardPreviewBlob" in preview_source
    assert "key === studentState.resultCardPreviewKey" in preview_source
    assert "key === studentState.resultCardPreviewPendingKey" in preview_source
    assert "resultCardDataUrl(blob)" in preview_source
    assert "URL.createObjectURL" not in preview_source
    assert "scheduleStudentResultCardPreview(payload)" in javascript
    assert "RESULT_CARD_PREVIEW_SPREAD_MS = 15000" in preview_source
    assert "clearStudentResultCardPreviewSchedule()" in javascript
    assert ".result-card-preview__frame" in css
    assert "aspect-ratio: 9 / 16" in css
    assert "object-fit: contain" in css
    assert '.student-body[data-student-view="success"] .student-hero { display: none; }' in css
    assert '.student-body[data-student-view="success"] .result-card-preview { width: min(34vw, 120px);' in css
    assert '.student-body[data-student-view="success"] .success-card__actions { grid-template-columns: 1fr 1fr;' in css


def test_manual_download_reuses_an_inflight_preview_generation() -> None:
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    result_flow_source = "function resultCardPreviewKey" + javascript.split(
        "function resultCardPreviewKey", 1
    )[1].split("function createGroupOption", 1)[0]
    harness = rf"""
const assert = require("node:assert/strict");
const payload = {{
  student: {{ id: 17, student_no: "20260000017", name: "测试学生", major_name: "建筑学" }},
  selection: {{ group_id: 1, group_name: "第一教学组", selected_at: "2026-08-20T10:00:00+00:00" }},
  receipt: {{ verification_code: "ABCD-EFGH-IJKL", qr_image_url: "/api/student/receipt/qr.png" }},
  settings: {{ activity_id: 1, activity_title: "并发测试" }},
}};
const studentState = {{
  payload,
  resultCardInFlight: false,
  resultCardPreviewKey: null,
  resultCardPreviewBlob: null,
  resultCardPreviewError: null,
  resultCardPreviewPendingKey: null,
  resultCardPreviewPromise: null,
  resultCardPreviewScheduledKey: null,
  resultCardPreviewTimer: null,
  resultCardProgressTimer: null,
  resultCardPreviewUrl: null,
  resultCardDownloadedKey: null,
}};
const studentEls = {{
  downloadResultCard: {{ disabled: false, textContent: "下载抢选结果凭证" }},
  resultCardPreviewImage: {{ hidden: false, src: "" }},
  resultCardPreviewStatus: {{ hidden: true, textContent: "" }},
  resultCardProgress: {{ dataset: {{}}, setAttribute(name, value) {{ this[name] = value; }} }},
  resultCardProgressFill: {{ style: {{ width: "" }} }},
  resultCardProgressLabel: {{ textContent: "" }},
  resultCardProgressPercent: {{ textContent: "" }},
  successLogout: {{ disabled: false, textContent: "安全退出" }},
}};
let generationCalls = 0;
let releaseGeneration;
const generatedBlob = {{ kind: "receipt-png" }};
function createResultCardBlob() {{
  generationCalls += 1;
  return new Promise((resolve) => {{ releaseGeneration = () => resolve(generatedBlob); }});
}}
async function resultCardDataUrl(blob) {{
  assert.equal(blob, generatedBlob);
  return "data:image/png;base64,preview";
}}
let objectUrlCreates = 0;
const URL = {{
  createObjectURL(blob) {{ assert.equal(blob, generatedBlob); objectUrlCreates += 1; return "blob:download"; }},
  revokeObjectURL() {{}},
}};
let downloadClicks = 0;
const document = {{
  createElement(tag) {{
    assert.equal(tag, "a");
    return {{ href: "", download: "", click() {{ downloadClicks += 1; }}, remove() {{}} }};
  }},
  body: {{ append() {{}} }},
}};
function showStudentMessage() {{}}

{result_flow_source}

(async () => {{
  const automaticPreview = ensureStudentResultCardPreview(payload);
  await Promise.resolve();
  assert.equal(studentEls.downloadResultCard.disabled, true);
  assert.equal(studentEls.successLogout.disabled, true);
  const manualDownload = downloadStudentResultCard();
  await Promise.resolve();
  assert.equal(generationCalls, 1, "download must join the in-flight preview render");
  releaseGeneration();
  const [previewBlob] = await Promise.all([automaticPreview, manualDownload]);
  assert.equal(previewBlob, generatedBlob);
  assert.equal(studentState.resultCardPreviewBlob, generatedBlob);
  assert.equal(objectUrlCreates, 1);
  assert.equal(downloadClicks, 1);
  assert.equal(studentState.resultCardDownloadedKey, resultCardPreviewKey(payload));
  assert.equal(studentEls.resultCardProgress["aria-valuenow"], "100");
  assert.equal(studentEls.resultCardProgressPercent.textContent, "100%");
  assert.equal(studentEls.resultCardProgressLabel.textContent, "凭证已下载，可安全退出；建议同时备份到相册或文件");
  assert.equal(studentEls.downloadResultCard.disabled, false);
  assert.equal(studentEls.downloadResultCard.textContent, "再次下载抢选结果凭证");
  assert.equal(studentEls.successLogout.disabled, false);
  assert.equal(studentEls.successLogout.textContent, "安全退出");
  assert.equal(studentState.resultCardPreviewPendingKey, null);
  assert.equal(studentState.resultCardPreviewPromise, null);
}})().catch((error) => {{ console.error(error); process.exit(1); }});
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_signed_receipt_qr_uses_csp_compatible_decode_and_fails_closed() -> None:
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    qr_loader_source = "function resultCardSameOriginImageUrl" + javascript.split(
        "function resultCardSameOriginImageUrl", 1
    )[1].split("function resultCardBlob", 1)[0]
    result_flow_source = "function resultCardPreviewKey" + javascript.split(
        "function resultCardPreviewKey", 1
    )[1].split("function createGroupOption", 1)[0]

    assert "createImageBitmap(qrBlob)" in qr_loader_source
    assert "URL.createObjectURL" not in qr_loader_source

    harness = r"""
const assert = require("node:assert/strict");
const window = {
  location: {
    href: "https://class.example/student",
    origin: "https://class.example",
  },
};
let bitmapShouldDecode = true;
let bitmapDecodeCalls = 0;
const decodedBitmap = { kind: "verification-qr-bitmap" };
async function createImageBitmap(blob) {
  bitmapDecodeCalls += 1;
  assert.equal(blob.type, "image/png");
  if (!bitmapShouldDecode) throw new Error("bitmap decode failed");
  return decodedBitmap;
}
let imageRequests = 0;
let fallbackImageShouldLoad = true;
class Image {
  set src(value) {
    imageRequests += 1;
    assert.match(value, /^data:image\/png;base64,/);
    queueMicrotask(() => fallbackImageShouldLoad
      ? this.onload()
      : this.onerror(new Error("data URL decode failed")));
  }
}
let fallbackDataUrlReads = 0;
class FileReader {
  readAsDataURL(blob) {
    fallbackDataUrlReads += 1;
    assert.equal(blob.type, "image/png");
    this.result = "data:image/png;base64,iVBORw0KGgo=";
    queueMicrotask(() => this.onload());
  }
}

const payload = {
  settings: { activity_id: 9, activity_title: "测试活动" },
  student: { student_no: "20268000008", name: "凭证学生", major_name: "城乡规划" },
  selection: { group_id: 3, group_name: "第三教学组", selected_at: "2026-08-14T12:00:00Z" },
  receipt: {
    token: "v2.signed.receipt-token",
    verification_code: "ABC-DEF-GHI",
    verify_url: "https://class.example/receipt#token=signed",
    qr_image_url: "https://class.example/api/student/receipt/qr.png",
  },
};
const studentState = {
  payload,
  csrf: "student-csrf-token",
  resultCardInFlight: false,
  resultCardPreviewKey: null,
  resultCardPreviewPendingKey: null,
  resultCardPreviewUrl: null,
};
const studentEls = {
  resultCardPreviewImage: { hidden: false, src: "" },
  resultCardPreviewStatus: { hidden: true, textContent: "" },
  downloadResultCard: { disabled: false, textContent: "下载抢选结果凭证" },
};
let dataUrlCalls = 0;
const fetchCalls = [];
let apiShouldSucceed = true;
let objectUrlCalls = 0;
let revokedObjectUrls = 0;
let anchorClicks = 0;
let lastMessage = null;
async function fetch(url, options) {
  fetchCalls.push({url, options});
  if (!apiShouldSucceed) {
    return {
      ok: false,
      status: 503,
      headers: {get(name) { return name.toLowerCase() === "content-type" ? "application/json" : null; }},
      async json() { return {detail: "二维码服务暂不可用"}; },
    };
  }
  return {
    ok: true,
    status: 200,
    headers: {get(name) { return name.toLowerCase() === "content-type" ? "image/png" : null; }},
    async blob() { return {type: "image/png"}; },
  };
}
function apiErrorDetails(data, status) {
  return {message: data?.detail || `request failed: ${status}`};
}
async function createResultCardBlob(value) {
  await loadResultCardVerificationQr(value);
  return { type: "image/png" };
}
async function resultCardDataUrl(_blob) {
  dataUrlCalls += 1;
  return "data:image/png;base64,unexpected";
}
function showStudentMessage(message, kind) {
  lastMessage = { message, kind };
}
URL.createObjectURL = () => {
  objectUrlCalls += 1;
  throw new Error("CSP-incompatible blob URL must not be created");
};
URL.revokeObjectURL = () => { revokedObjectUrls += 1; };
const document = {
  createElement(tag) {
    assert.equal(tag, "a");
    return {
      click() { anchorClicks += 1; },
      remove() {},
    };
  },
  body: { append() {} },
};

(async () => {
  for (const incompleteReceipt of [
    null,
    {...payload.receipt, verification_code: ""},
    {...payload.receipt, verify_url: "https://outside.example/receipt#token=signed"},
    {...payload.receipt, qr_image_url: "https://outside.example/qr.png"},
  ]) {
    await assert.rejects(
      loadResultCardVerificationQr({...payload, receipt: incompleteReceipt}),
      /防伪核验信息不完整.*重试/,
    );
  }
  assert.equal(fetchCalls.length, 0, "核验信息缺失或非同源时不应请求二维码");
  assert.equal(imageRequests, 0);
  assert.equal(bitmapDecodeCalls, 0);

  const validQr = await loadResultCardVerificationQr(payload);
  assert.equal(validQr, decodedBitmap, "完整同源核验信息应由 createImageBitmap 解码");
  assert.equal(fetchCalls.length, 1);
  assert.equal(fetchCalls[0].url, payload.receipt.qr_image_url);
  assert.equal(fetchCalls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(fetchCalls[0].options.body), {token: payload.receipt.token});
  assert.equal(fetchCalls[0].options.headers.get("X-CSRF-Token"), "student-csrf-token");
  assert.equal(fetchCalls[0].options.headers.get("X-Activity-ID"), "9");
  assert.equal(bitmapDecodeCalls, 1);
  assert.equal(imageRequests, 0, "正常路径不应依赖 Image 加载 blob URL");
  assert.equal(fallbackDataUrlReads, 0);
  assert.equal(objectUrlCalls, 0);
  assert.equal(revokedObjectUrls, 0);

  const availableBitmapDecoder = createImageBitmap;
  createImageBitmap = undefined;
  const fallbackQr = await loadResultCardVerificationQr(payload);
  assert.ok(fallbackQr instanceof Image, "无 createImageBitmap 时应使用 CSP 允许的 data URL 解码");
  assert.equal(bitmapDecodeCalls, 1);
  assert.equal(fallbackDataUrlReads, 1);
  assert.equal(imageRequests, 1);
  assert.equal(objectUrlCalls, 0);
  createImageBitmap = availableBitmapDecoder;

  apiShouldSucceed = false;
  await assert.rejects(
    loadResultCardVerificationQr(payload),
    /二维码服务暂不可用/,
  );
  assert.equal(bitmapDecodeCalls, 1, "API 失败时不应尝试解码响应");
  assert.equal(imageRequests, 1);
  assert.equal(objectUrlCalls, 0);

  apiShouldSucceed = true;
  bitmapShouldDecode = false;
  fallbackImageShouldLoad = false;
  await assert.rejects(
    loadResultCardVerificationQr(payload),
    /防伪二维码加载失败.*重试/,
  );
  assert.equal(bitmapDecodeCalls, 2);
  assert.equal(fallbackDataUrlReads, 2, "位图解码失败时仅回退到 CSP 允许的 data URL");
  assert.equal(imageRequests, 2);
  assert.equal(objectUrlCalls, 0);

  await ensureStudentResultCardPreview(payload);
  assert.equal(studentState.resultCardPreviewKey, null, "二维码失败不能写入预览缓存键");
  assert.equal(studentState.resultCardPreviewUrl, null, "二维码失败不能写入预览缓存内容");
  assert.equal(studentState.resultCardPreviewPendingKey, null, "失败后必须释放 pending 状态以便重试");
  assert.equal(dataUrlCalls, 0, "二维码失败不能继续生成可缓存 Data URL");
  assert.equal(studentEls.resultCardPreviewImage.hidden, true);
  assert.match(studentEls.resultCardPreviewStatus.textContent, /防伪二维码.*重试/);

  await downloadStudentResultCard();
  assert.equal(bitmapDecodeCalls, 4);
  assert.equal(fallbackDataUrlReads, 4);
  assert.equal(imageRequests, 4);
  assert.equal(objectUrlCalls, 0, "防伪二维码解码不得创建 CSP 禁止的 blob URL");
  assert.equal(revokedObjectUrls, 0);
  assert.equal(anchorClicks, 0, "二维码失败不能触发缺少防伪二维码的下载");
  assert.deepEqual(lastMessage, {
    message: "防伪二维码加载失败，请检查网络后重试",
    kind: "error",
  });
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        ["node", "-e", "\n".join((qr_loader_source, result_flow_source, harness))],
        cwd=ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_result_card_always_releases_decoded_qr_bitmap_exactly_once() -> None:
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    card_source = "async function createResultCardBlob" + javascript.split(
        "async function createResultCardBlob", 1
    )[1].split("function resultCardPreviewKey", 1)[0]

    harness = r"""
const assert = require("node:assert/strict");

const payload = {
  settings: { activity_id: 9, activity_title: "测试活动" },
  student: { student_no: "20268000008", name: "凭证学生", major_name: "城乡规划" },
  selection: { group_id: 3, group_name: "第三教学组", selected_at: "2026-08-14T12:00:00Z" },
  receipt: {
    token: "v2.signed.receipt-token",
    verification_code: "ABC-DEF-GHI",
    verify_url: "https://class.example/receipt#token=signed",
    qr_image_url: "https://class.example/api/student/receipt/qr.png",
  },
};

let scenario = null;
let bitmapSequence = 0;
function bitmap(label = `bitmap-${++bitmapSequence}`) {
  return {
    label,
    closeCalls: 0,
    drawCalls: 0,
    close() { this.closeCalls += 1; },
  };
}
function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolveValue, rejectValue) => {
    resolve = resolveValue;
    reject = rejectValue;
  });
  return { promise, resolve, reject };
}
async function pollUntil(predicate) {
  for (let attempt = 0; attempt < 20; attempt += 1) {
    if (predicate()) return;
    await new Promise((resolve) => setImmediate(resolve));
  }
  assert.fail("timed out waiting for decoded bitmap cleanup");
}

function drawingContext() {
  const context = {
    createLinearGradient() { return { addColorStop() {} }; },
    measureText(value) { return { width: String(value).length * 10 }; },
    drawImage(image) {
      if (image && typeof image.drawCalls === "number") image.drawCalls += 1;
      if (scenario.qrDrawFails && image?.label?.startsWith("qr-draw-failure")) {
        throw new Error("QR drawing failed");
      }
    },
  };
  return new Proxy(context, {
    get(target, property) {
      if (property in target) return target[property];
      return () => {};
    },
    set(target, property, value) {
      target[property] = value;
      return true;
    },
  });
}

const document = {
  fonts: { ready: Promise.resolve() },
  createElement(tag) {
    assert.equal(tag, "canvas");
    return {
      width: 0,
      height: 0,
      getContext() {
        if (scenario.contextMissing) return null;
        const context = drawingContext();
        if (scenario.drawFails) {
          context.fillRect = () => { throw new Error("drawing failed"); };
        }
        return context;
      },
    };
  },
};
function roundedRectangle() {}
function drawWrappedCardText(_context, _value, _x, y) {
  return { fontSize: 20, lineCount: 1, bottom: y + 32 };
}
function drawFittedCardText() {}
function formatStudentTime(value) { return value; }
function loadResultCardLogo() { return scenario.logoPromise; }
function loadResultCardVerificationQr() { return scenario.qrPromise; }
async function resultCardBlob() {
  if (scenario.blobFails) throw new Error("blob failed");
  return { type: "image/png" };
}

async function rejectsWithBitmapReleased(nextScenario, expectedError, qr) {
  scenario = nextScenario;
  await assert.rejects(createResultCardBlob(payload), expectedError);
  await pollUntil(() => qr.closeCalls === 1);
  assert.equal(qr.closeCalls, 1, `${qr.label} must be closed exactly once`);
}

(async () => {
  const decodedBeforeLogoFailure = bitmap("decoded-before-logo-failure");
  const delayedLogo = deferred();
  scenario = {
    logoPromise: delayedLogo.promise,
    qrPromise: Promise.resolve(decodedBeforeLogoFailure),
  };
  const firstAttempt = createResultCardBlob(payload);
  await new Promise((resolve) => setImmediate(resolve));
  delayedLogo.reject(new Error("logo failed"));
  await assert.rejects(firstAttempt, /logo failed/);
  await pollUntil(() => decodedBeforeLogoFailure.closeCalls === 1);
  assert.equal(decodedBeforeLogoFailure.closeCalls, 1);

  const decodedAfterLogoFailure = bitmap("decoded-after-logo-failure");
  const delayedQr = deferred();
  scenario = {
    logoPromise: Promise.reject(new Error("logo failed early")),
    qrPromise: delayedQr.promise,
  };
  const secondAttempt = createResultCardBlob(payload);
  await assert.rejects(secondAttempt, /logo failed early/);
  delayedQr.resolve(decodedAfterLogoFailure);
  await pollUntil(() => decodedAfterLogoFailure.closeCalls === 1);
  assert.equal(decodedAfterLogoFailure.closeCalls, 1);

  const missingContextQr = bitmap("missing-context");
  await rejectsWithBitmapReleased({
    logoPromise: Promise.resolve({ kind: "logo" }),
    qrPromise: Promise.resolve(missingContextQr),
    contextMissing: true,
  }, /无法创建抢选结果凭证/, missingContextQr);

  for (let attempt = 0; attempt < 3; attempt += 1) {
    const drawingFailureQr = bitmap(`drawing-failure-${attempt}`);
    await rejectsWithBitmapReleased({
      logoPromise: Promise.resolve({ kind: "logo" }),
      qrPromise: Promise.resolve(drawingFailureQr),
      drawFails: true,
    }, /drawing failed/, drawingFailureQr);
    assert.equal(drawingFailureQr.drawCalls, 0, "failed pre-QR drawing must not draw the QR");
  }

  const blobFailureQr = bitmap("blob-failure");
  await rejectsWithBitmapReleased({
    logoPromise: Promise.resolve({ kind: "logo" }),
    qrPromise: Promise.resolve(blobFailureQr),
    blobFails: true,
  }, /blob failed/, blobFailureQr);
  assert.equal(blobFailureQr.drawCalls, 1, "Blob failure still follows the normal QR draw path");

  const qrDrawFailure = bitmap("qr-draw-failure");
  await rejectsWithBitmapReleased({
    logoPromise: Promise.resolve({ kind: "logo" }),
    qrPromise: Promise.resolve(qrDrawFailure),
    qrDrawFails: true,
  }, /QR drawing failed/, qrDrawFailure);
  assert.equal(qrDrawFailure.drawCalls, 1, "QR draw failure must not cause a second draw");

  const normalQr = bitmap("normal");
  scenario = {
    logoPromise: Promise.resolve({ kind: "logo" }),
    qrPromise: Promise.resolve(normalQr),
  };
  const blob = await createResultCardBlob(payload);
  assert.equal(blob.type, "image/png");
  assert.equal(normalQr.drawCalls, 1, "normal generation must draw the QR once");
  assert.equal(normalQr.closeCalls, 1, "normal generation must close the QR exactly once");

  const htmlImage = { kind: "html-image", drawCalls: 0 };
  scenario = {
    logoPromise: Promise.resolve({ kind: "logo" }),
    qrPromise: Promise.resolve(htmlImage),
  };
  await createResultCardBlob(payload);
  assert.equal(htmlImage.drawCalls, 1, "HTMLImage fallback must still be drawn");
  assert.equal("close" in htmlImage, false, "HTMLImage fallback must not require close()");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        ["node", "-e", "\n".join((card_source, harness))],
        cwd=ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout


def test_public_receipt_page_does_not_persist_or_leak_the_signed_token() -> None:
    html = (ROOT / "web" / "receipt.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "receipt.js").read_text(encoding="utf-8")
    css = (ROOT / "web" / "receipt.css").read_text(encoding="utf-8")
    parser = ReceiptMarkupParser()
    parser.feed(html)

    assert any(
        meta.get("name") == "referrer" and meta.get("content") == "no-referrer"
        for meta in parser.meta
    )
    assert parser.by_id["verification-message"]["role"] == "status"
    assert "hidden" in parser.by_id["verification-details"]
    assert parser.by_id["verification-retry"]["tag"] == "button"
    assert parser.by_id["verification-retry"]["type"] == "button"
    assert "hidden" in parser.by_id["verification-retry"]
    assert "window.location.hash" in javascript
    assert "history.replaceState" in javascript
    assert 'fetch("/api/public/receipts/verify"' in javascript
    assert 'method: "POST"' in javascript
    assert 'body: JSON.stringify({ token })' in javascript
    assert "/api/public/receipts/verify?" not in javascript
    assert "encodeURIComponent(token)" not in javascript
    assert 'credentials: "omit"' in javascript
    assert 'referrerPolicy: "no-referrer"' in javascript
    assert "localStorage" not in javascript
    assert "sessionStorage" not in javascript
    assert ".innerHTML" not in javascript
    assert "textContent" in javascript
    assert "核验有效" in javascript
    assert "该抢选记录已被撤销" in javascript
    assert "凭证无效或已损坏" in javascript
    assert "aspect-ratio: 3808 / 909" in css
    assert "top: -16.72%" in css
    assert "left: -8.61%" in css
    assert "width: 109.01%" in css
    assert "安徽建筑大学 · 建筑与空间规划学院 制作：Mikutea" in html


def test_public_receipt_retry_keeps_token_in_memory_only_and_reuses_it_explicitly() -> None:
    harness = r"""
const assert = require("node:assert/strict");
const fs = require("node:fs");
const vm = require("node:vm");
const javascript = fs.readFileSync("web/receipt.js", "utf8");
const signedToken = `signed.${"a".repeat(48)}.token`;

class FakeElement {
  constructor() {
    this.hidden = false;
    this.disabled = false;
    this.textContent = "";
    this.listeners = new Map();
  }
  addEventListener(type, listener) {
    this.listeners.set(type, listener);
  }
  click() {
    const listener = this.listeners.get("click");
    if (listener) listener({ currentTarget: this });
  }
}

function response(status, payload) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return payload; },
  };
}

async function flush() {
  await new Promise((resolve) => setImmediate(resolve));
  await new Promise((resolve) => setImmediate(resolve));
}

async function boot(steps, hash = `#token=${signedToken}`) {
  const selectors = [
    "#verification-mark",
    "#verification-eyebrow",
    "#verification-title",
    "#verification-message",
    "#verification-details",
    "#verification-activity",
    "#verification-name",
    "#verification-student-no",
    "#verification-major",
    "#verification-group",
    "#verification-time",
    "#verification-code",
    "#verification-retry",
  ];
  const elements = Object.fromEntries(selectors.map((selector) => [selector, new FakeElement()]));
  elements["#verification-details"].hidden = true;
  elements["#verification-retry"].hidden = true;
  const location = { hash, pathname: "/receipt" };
  const historyCalls = [];
  const fetchCalls = [];
  const queue = [...steps];
  const context = {
    URLSearchParams,
    document: {
      body: { dataset: {} },
      querySelector(selector) { return elements[selector]; },
    },
    window: { location },
    history: {
      replaceState(...args) {
        historyCalls.push(args);
        location.hash = "";
      },
    },
    async fetch(url, options) {
      fetchCalls.push({ url, options });
      const step = queue.shift();
      if (step instanceof Error) throw step;
      return step;
    },
  };
  vm.runInNewContext(javascript, context, { filename: "web/receipt.js" });
  await flush();
  return { elements, fetchCalls, historyCalls, location };
}

(async () => {
  const validPayload = {
    valid: true,
    revoked: false,
    verification_code: "ABC-DEF-GHI",
    activity: { title: "测试活动" },
    student: { name: "测试学生", student_no_masked: "*******0001", major_name: "城乡规划" },
    group: { name: "第一教学组" },
    selected_at: "2026-08-14T12:00:00Z",
  };
  const retryFlow = await boot([
    new Error("offline"),
    response(429, { detail: "请求频繁" }),
    response(503, { detail: "服务暂不可用" }),
    response(200, validPayload),
  ]);
  const retry = retryFlow.elements["#verification-retry"];
  assert.equal(retryFlow.historyCalls.length, 1, "fragment 只应在启动时清理一次");
  assert.equal(retryFlow.location.hash, "", "读取后必须立即从地址栏移除 token");
  assert.equal(retryFlow.fetchCalls.length, 1);
  assert.equal(retry.hidden, false, "网络失败应显示显式重试入口");

  retry.click();
  await flush();
  assert.equal(retryFlow.fetchCalls.length, 2);
  assert.equal(retry.hidden, false, "429 应允许用户稍后重试");

  retry.click();
  await flush();
  assert.equal(retryFlow.fetchCalls.length, 3);
  assert.equal(retry.hidden, false, "5xx 应允许用户重试");

  retry.click();
  await flush();
  assert.equal(retryFlow.fetchCalls.length, 4);
  assert.equal(retry.hidden, true, "核验成功后不应继续显示重试入口");
  assert.equal(retryFlow.elements["#verification-title"].textContent, "核验有效");
  assert.equal(retryFlow.elements["#verification-details"].hidden, false);
  assert.equal(retryFlow.historyCalls.length, 1, "重试不得重新读取或重写 URL");
  for (const call of retryFlow.fetchCalls) {
    assert.equal(call.url, "/api/public/receipts/verify");
    assert.deepEqual(JSON.parse(call.options.body), { token: signedToken });
  }
  for (const element of Object.values(retryFlow.elements)) {
    assert.equal(element.textContent.includes(signedToken), false, "token 不得写入 DOM");
  }

  const invalid = await boot([response(400, { detail: "凭证无效或已损坏" })]);
  assert.equal(invalid.fetchCalls.length, 1);
  assert.equal(invalid.elements["#verification-retry"].hidden, true);
  assert.equal(invalid.elements["#verification-title"].textContent, "凭证无效或已损坏");
  await flush();
  assert.equal(invalid.fetchCalls.length, 1, "确定性无效响应不得自动循环重试");

  const unmatched = await boot([response(200, {
    valid: false,
    revoked: false,
    verification_code: "ABC-DEF-GHI",
  })]);
  assert.equal(unmatched.fetchCalls.length, 1);
  assert.equal(unmatched.elements["#verification-retry"].hidden, true);
  assert.equal(unmatched.elements["#verification-title"].textContent, "未找到匹配的有效记录");

  const revoked = await boot([response(200, { ...validPayload, valid: false, revoked: true })]);
  assert.equal(revoked.fetchCalls.length, 1);
  assert.equal(revoked.elements["#verification-retry"].hidden, true);
  assert.equal(revoked.elements["#verification-title"].textContent, "该抢选记录已被撤销");
  assert.equal(revoked.elements["#verification-details"].hidden, false);

  const refreshed = await boot([], "");
  assert.equal(refreshed.fetchCalls.length, 0, "刷新后不应从持久化位置恢复 token");
  assert.equal(refreshed.elements["#verification-retry"].hidden, true);
  assert.equal(refreshed.elements["#verification-title"].textContent, "凭证链接无效");
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
"""
    completed = subprocess.run(
        ["node", "-e", harness],
        cwd=ROOT,
        capture_output=True,
        check=False,
        encoding="utf-8",
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
