from __future__ import annotations

from html.parser import HTMLParser
import json
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]


class _StudentDomParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.by_id: dict[str, dict[str, str]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        element_id = attributes.get("id")
        if element_id:
            self.by_id[element_id] = {"tag": tag, **attributes}


def _student_sources() -> tuple[_StudentDomParser, str, str]:
    html = (ROOT / "web" / "index.html").read_text(encoding="utf-8")
    javascript = (ROOT / "web" / "student.js").read_text(encoding="utf-8")
    parser = _StudentDomParser()
    parser.feed(html)
    return parser, html, javascript


def _run_node(script: str) -> dict[str, object]:
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "student.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert execution.returncode == 0, execution.stderr
    return json.loads(execution.stdout)


def test_student_login_contract_is_explicit_and_mobile_friendly() -> None:
    parser, html, _ = _student_sources()

    student_no = parser.by_id["student-no"]
    assert student_no["inputmode"] == "numeric"
    assert student_no["minlength"] == student_no["maxlength"] == "11"
    assert student_no["pattern"] == "[0-9]{11}"
    assert "student-no-help" in student_no["aria-describedby"]
    assert "11 位数字" in html

    name = parser.by_id["student-name"]
    assert name["maxlength"] == "40"
    assert "A-Za-z" in name["pattern"]
    assert "·•・" in name["pattern"]
    assert "student-name-help" in name["aria-describedby"]
    assert "中文、英文字母、空格或姓名中点" in html

    activation = parser.by_id["activation-code"]
    assert activation["minlength"] == activation["maxlength"] == "6"
    assert activation["pattern"] == "[A-Za-z0-9]{6}"


def test_student_login_normalization_and_validation_execute_in_node() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8").split("const studentState =", 1)[0];
eval(source + `
  const normalized = normalizeStudentLoginPayload({
    student_no: " ２０２６１２３４５６７ ",
    name: " 张 三·Alice ",
    activation_code: " ａ1ｂ2ｃ3 ",
  });
  const codeWithInnerSpace = normalizeStudentLoginPayload({
    student_no: "20261234567", name: "张三", activation_code: " A1 B2C ",
  });
  process.stdout.write(JSON.stringify({
    normalized,
    codeWithInnerSpace: codeWithInnerSpace.activation_code,
    codeWithInnerSpaceErrors: validateStudentLoginPayload(codeWithInnerSpace),
    valid: validateStudentLoginPayload(normalized),
    badStudentNumbers: ["2026123456", "202612345678", "20261A34567"].map((student_no) =>
      validateStudentLoginPayload({student_no, name: "张三", activation_code: "A1B2C3"})
    ),
    badNames: ["张三2", "张三🙂", "O'Connor", "张\\u0007三"].map((name) =>
      validateStudentLoginPayload({student_no: "20261234567", name, activation_code: "A1B2C3"})
    ),
    badCodes: ["12345", "1234567", "12*456", "A1 B2C"].map((activation_code) =>
      validateStudentLoginPayload({student_no: "20261234567", name: "张三", activation_code})
    ),
    badges: [
      professionalBadge("建筑学（五年制）"),
      professionalBadge("城乡规划"),
      professionalBadge("风景园林"),
      professionalBadge("环境设计"),
      professionalBadge("室内空间设计实验班"),
    ],
  }));
`);
"""
    result = _run_node(script)
    assert result["normalized"] == {
        "student_no": "20261234567",
        "name": "张 三·Alice",
        "activation_code": "A1B2C3",
    }
    assert result["valid"] == {}
    assert result["codeWithInnerSpace"] == "A1 B2C"
    assert set(result["codeWithInnerSpaceErrors"]) == {"activation_code"}
    assert all(set(item) == {"student_no"} for item in result["badStudentNumbers"])
    assert all(set(item) == {"name"} for item in result["badNames"])
    assert all(set(item) == {"activation_code"} for item in result["badCodes"])
    assert result["badges"] == ["建筑学", "城乡规划", "风景园林", "环境设计", "室内空间设计…"]


def test_server_clock_uses_server_epoch_and_local_monotonic_elapsed_time() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const stateBody = source.match(/const studentState = (\{[\s\S]*?[\r\n]+\});[\r\n]+const studentEls/);
if (!stateBody) throw new Error("studentState block not found");
const timingBlock = "const STUDENT_CLOCK_SYNC_PATHS" + source.split("const STUDENT_CLOCK_SYNC_PATHS", 2)[1].split("const studentState =", 1)[0];
const clockBlock = "function studentField" + source.split("function studentField", 2)[1].split("function studentPhase", 1)[0];
let monotonic = 1000;
Object.defineProperty(globalThis, "performance", {value: {now: () => monotonic}, configurable: true});
const element = () => ({dataset: {}, textContent: "", title: "", removeAttribute() {}, setAttribute(key, value) { this[key] = value; }});
eval(`
  ${timingBlock}
  const studentState = ${stateBody[1]};
  const studentEls = {clock: element(), clockStatus: element(), clockTime: element()};
  ${clockBlock}
  synchronizeStudentClock({server_now: "2026-08-14T06:00:00+00:00"});
  const atSync = currentStudentServerTimeMs();
  monotonic = 3500;
  renderStudentServerClock();
  const after = currentStudentServerTimeMs();
  studentState.connectionInterrupted = true;
  renderStudentServerClock();
  process.stdout.write(JSON.stringify({
    atSync,
    after,
    text: studentEls.clockTime.textContent,
    syncStatus: studentEls.clock.dataset.syncStatus,
    statusText: studentEls.clockStatus.textContent,
  }));
`);
"""
    result = _run_node(script)
    assert result["after"] - result["atSync"] == 2500
    assert result["text"] == "14:00:02"
    assert result["syncStatus"] == "interrupted"
    assert result["statusText"] == "同步中断"


def test_server_clock_compensates_800ms_rtt_and_never_moves_backward() -> None:
    _, _, javascript = _student_sources()
    api_block = javascript.split("async function studentApi", 1)[1].split(
        "function showStudentMessage", 1
    )[0]
    assert "beginStudentClockRequestTiming(path)" in api_block
    assert "finishStudentClockRequestTiming(clockRequestTiming)" in api_block
    assert "rememberStudentResponseClockTiming(data, clockResponseTiming)" in api_block

    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const stateBody = source.match(/const studentState = (\{[\s\S]*?[\r\n]+\});[\r\n]+const studentEls/);
if (!stateBody) throw new Error("studentState block not found");
const timingBlock = "const STUDENT_CLOCK_SYNC_PATHS" + source.split("const STUDENT_CLOCK_SYNC_PATHS", 2)[1].split("const studentState =", 1)[0];
const clockBlock = "function studentField" + source.split("function studentField", 2)[1].split("function studentPhase", 1)[0];
const baseServerMs = Date.parse("2026-08-14T06:00:00.000Z");
let monotonic = 0;
let wall = Date.parse("2026-08-14T05:59:58.000Z");
Object.defineProperty(globalThis, "performance", {value: {now: () => monotonic}, configurable: true});
Date.now = () => wall;
const element = () => ({dataset: {}, textContent: "", title: "", removeAttribute() {}, setAttribute(key, value) { this[key] = value; }});
eval(`
  ${timingBlock}
  const studentState = ${stateBody[1]};
  const studentEls = {clock: element(), clockStatus: element(), clockTime: element()};
  ${clockBlock}
  const request = beginStudentClockRequestTiming("/api/student/me");
  monotonic = 800;
  wall += 800;
  const response = finishStudentClockRequestTiming(request);
  const payload = {server_now: new Date(baseServerMs).toISOString()};
  rememberStudentResponseClockTiming(payload, response);
  synchronizeStudentClock(payload);
  const compensatedAtResponse = currentStudentServerTimeMs();

  monotonic = 1600;
  wall += 800;
  const afterElapsed = currentStudentServerTimeMs();

  const staleRequest = beginStudentClockRequestTiming("/api/public/info");
  monotonic = 2400;
  wall += 800;
  const staleResponse = finishStudentClockRequestTiming(staleRequest);
  const stalePayload = {server_now: new Date(baseServerMs + 500).toISOString()};
  rememberStudentResponseClockTiming(stalePayload, staleResponse);
  const beforeStaleSync = currentStudentServerTimeMs();
  synchronizeStudentClock(stalePayload);
  const afterStaleSync = currentStudentServerTimeMs();
  process.stdout.write(JSON.stringify({
    compensatedMs: compensatedAtResponse - baseServerMs,
    elapsedMs: afterElapsed - compensatedAtResponse,
    rttMs: studentState.serverClockLastSampleRttMs,
    monotonicAfterStale: afterStaleSync >= beforeStaleSync,
    paths: [...STUDENT_CLOCK_SYNC_PATHS],
  }));
`);
"""
    result = _run_node(script)
    assert result["compensatedMs"] == 400
    assert result["elapsedMs"] == 800
    assert result["rttMs"] == 800
    assert result["monotonicAfterStale"] is True
    assert result["paths"] == [
        "/api/public/info",
        "/api/public/status",
        "/api/student/login",
        "/api/student/me",
    ]


def test_keyboard_sized_visual_viewport_uses_internal_form_scroll_only() -> None:
    parser, _, javascript = _student_sources()
    css = (ROOT / "web" / "app.css").read_text(encoding="utf-8")
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const viewportBlock = "function syncStudentViewportHeight" + source.split("function syncStudentViewportHeight", 2)[1].split('window.addEventListener("offline"', 1)[0];
const classes = new Set();
let visualHeight = 844;
let focused = false;
global.window = {innerHeight: 844, visualViewport: {get height() { return visualHeight; }}};
global.document = {
  activeElement: {closest: () => focused ? {} : null},
  documentElement: {clientHeight: 844, style: {value: "", setProperty(name, value) { if (name === "--student-app-height") this.value = value; }}},
  body: {classList: {toggle(name, enabled) { if (enabled) classes.add(name); else classes.delete(name); }}},
};
eval(`${viewportBlock}
  syncStudentViewportHeight();
  const normal = {height: document.documentElement.style.value, keyboard: classes.has("student-keyboard-open")};
  visualHeight = 360;
  focused = true;
  syncStudentViewportHeight();
  const keyboard = {height: document.documentElement.style.value, keyboard: classes.has("student-keyboard-open")};
  process.stdout.write(JSON.stringify({normal, keyboard}));
`);
"""
    result = _run_node(script)

    assert parser.by_id["login-view"]["tag"] == "section"
    assert parser.by_id["student-login-form"]["tag"] == "form"
    assert result["normal"] == {"height": "844px", "keyboard": False}
    assert result["keyboard"] == {"height": "360px", "keyboard": True}
    assert ".student-body.student-keyboard-open #student-login-form" in css
    keyboard_css = css.split(
        ".student-body.student-keyboard-open #student-login-form {", 1
    )[1].split("}", 1)[0]
    assert "overflow-y: auto" in keyboard_css
    assert "overscroll-behavior: contain" in keyboard_css
    assert ".student-body.student-keyboard-open .student-hero" in css
    assert ".student-body.student-keyboard-open .site-footer--student" in css
    assert ".student-body.student-keyboard-open" in css and "overflow: hidden" in css
    error_focus = javascript.split("function focusFirstStudentFieldError", 1)[1].split(
        "function validationField", 1
    )[0]
    assert 'field.input.focus({ preventScroll: true })' in error_focus
    assert "document.activeElement === field.input" in error_focus
    assert 'field.input.scrollIntoView({ block: "center", inline: "nearest", behavior: "auto" })' in error_focus


def test_result_receipt_and_professional_labels_are_clear_and_secret_free() -> None:
    parser, html, javascript = _student_sources()

    assert parser.by_id["student-clock"]["data-sync-status"] == "syncing"
    assert parser.by_id["student-server-clock"]["tag"] == "time"
    assert parser.by_id["success-major-badge"]["role"] == "img"
    assert "下载抢选结果凭证" in html
    assert "请下载并妥善保存「抢选结果凭证」" in html

    card_source = javascript.split("async function createResultCardBlob", 1)[1].split(
        "async function downloadStudentResultCard", 1
    )[0]
    assert "canvas.width = 1080" in card_source
    assert "canvas.height = 1920" in card_source
    assert "抢选结果凭证" in card_source
    assert "在线核验" in card_source
    assert "核验编号" in card_source
    assert "payload.settings.activity_title" in card_source
    assert "payload.student.name" in card_source
    assert "payload.student.student_no" in card_source
    assert "payload.student.major_name" in card_source
    assert "payload.selection.group_name" in card_source
    assert 'label === "姓名" || label === "专业"' in card_source
    assert "drawFittedCardText(context, payload.selection.group_name" in card_source
    assert "payload.selection.selected_at" in card_source
    assert "receipt.verification_code" in card_source
    assert "receipt.verify_url" in card_source
    assert "verificationQr" in card_source
    assert '"/brand/college-wordmark-official.png"' in javascript
    assert "activation_code" not in card_source
    assert "个人激活码" not in card_source
    assert "--student-app-height" in javascript


@pytest.mark.parametrize(
    ("length", "max_width", "max_font_size"),
    [(40, 360, 33), (80, 360, 33), (80, 800, 42)],
)
def test_result_receipt_preserves_full_boundary_text_in_two_lines(
    length: int, max_width: int, max_font_size: int
) -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const helperBlock = "function fittedCardTextLines" + source.split("function fittedCardTextLines", 2)[1].split("function loadResultCardLogo", 1)[0];
const drawn = [];
let currentFontSize = 0;
const context = {
  set font(value) {
    this._font = value;
    currentFontSize = Number(value.match(/(\d+)px/)[1]);
  },
  get font() { return this._font; },
  measureText(value) { return {width: Array.from(value).length * currentFontSize}; },
  fillText(value, x, y) { drawn.push({value, x, y}); },
};
eval(`${helperBlock}
  const name = "超".repeat(__LENGTH__);
  const result = drawFittedCardText(context, name, 132, 900, __MAX_WIDTH__, __MAX_FONT_SIZE__, 2);
  process.stdout.write(JSON.stringify({name, drawn, result}));
`);
"""
    script = (
        script.replace("__LENGTH__", str(length))
        .replace("__MAX_WIDTH__", str(max_width))
        .replace("__MAX_FONT_SIZE__", str(max_font_size))
    )
    result = _run_node(script)

    assert "".join(line["value"] for line in result["drawn"]) == result["name"]
    assert result["result"]["lineCount"] == 2
    assert result["result"]["fontSize"] >= 1
    assert all("…" not in line["value"] for line in result["drawn"])


def test_success_view_keeps_syncing_for_administrator_revocation() -> None:
    _, _, javascript = _student_sources()
    render_block = javascript.split("function renderStudentPayload", 1)[1].split(
        "async function loadPublicInfo", 1
    )[0]
    polling_block = javascript.split("function startStudentPolling", 1)[1].split(
        "function tickStudentCountdown", 1
    )[0]

    assert "clearInterval(studentState.pollTimer)" not in render_block
    assert "if (studentState.payload?.selection) return" not in polling_block
    assert "const hadSelection = Boolean(studentState.payload?.selection)" in polling_block
    assert (
        "pollStartedAt - studentState.lastSelectedSyncAt < "
        "STUDENT_SELECTED_SYNC_INTERVAL_MS"
    ) in polling_block
    assert "const STUDENT_WAITING_POLL_INTERVAL_MS = 2500" in javascript
    assert "const STUDENT_SELECTED_SYNC_INTERVAL_MS = 10000" in javascript
    assert "const STUDENT_HEARTBEAT_INTERVAL_MS = 15000" in javascript
    assert "}, STUDENT_WAITING_POLL_INTERVAL_MS);" in polling_block
    assert "}, STUDENT_HEARTBEAT_INTERVAL_MS);" in polling_block
    assert "hadSelection && !data.selection" in polling_block
    assert "原选择已被管理员撤销" in polling_block


def test_waiting_poll_uses_lightweight_public_status_until_selection_opens() -> None:
    _, _, javascript = _student_sources()
    merge_block = javascript.split(
        "function mergePublicStatusIntoStudentPayload", 1
    )[1].split("async function loadPublicInfo", 1)[0]
    polling_block = javascript.split("function startStudentPolling", 1)[1].split(
        "function tickStudentCountdown", 1
    )[0]

    assert 'studentApi("/api/public/status")' in polling_block
    assert 'studentApi("/api/student/me")' in polling_block
    assert "mergePublicStatusIntoStudentPayload" in polling_block
    assert "activity_id" in merge_block
    assert "selection_opens_at" in merge_block

    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const mergeBlock = "function mergePublicStatusIntoStudentPayload" + source
  .split("function mergePublicStatusIntoStudentPayload", 2)[1]
  .split("async function loadPublicInfo", 1)[0];
const pollingBlock = "function startStudentPolling" + source
  .split("function startStudentPolling", 2)[1]
  .split("function tickStudentCountdown", 1)[0];
const calls = [];
const renders = [];
const renderedTimingTags = [];
const synchronizedTimingTags = [];
const studentResponseClockTimings = new WeakMap();
const STUDENT_WAITING_POLL_INTERVAL_MS = 2500;
const STUDENT_SELECTED_SYNC_INTERVAL_MS = 10000;
const STUDENT_HEARTBEAT_INTERVAL_MS = 15000;
let intervalCallback = null;
let now = 1000;
const studentState = {
  pollTimer: null,
  heartbeatTimer: null,
  pollInFlight: false,
  heartbeatInFlight: false,
  lastSelectedSyncAt: 0,
  preparedCountdownKey: null,
  selectedGroupId: null,
  csrf: "csrf",
  payload: {
    phase: "waiting",
    selection_opens_at: null,
    selection: null,
    groups: [{id: 1, name: "登录时旧教学组", full: false}],
    student: {id: 1},
    settings: {activity_id: 7, activity_title: "压力测试", status: "closed"},
  },
};
global.clearInterval = () => {};
global.setInterval = (callback, delay) => {
  if (delay === STUDENT_WAITING_POLL_INTERVAL_MS) intervalCallback = callback;
  return delay;
};
function studentMonotonicNow() { return now; }
function studentPhase(payload) { return payload.phase; }
function rememberStudentResponseClockTiming(payload, timing) {
  if (timing) studentResponseClockTimings.set(payload, timing);
}
function synchronizeStudentClock(payload) {
  synchronizedTimingTags.push(studentResponseClockTimings.get(payload)?.tag || null);
}
function markStudentConnectionHealthy() {}
function handleStudentSessionExpired() { throw new Error("unexpected expiry"); }
function reportStudentConnectionIssue(error) { throw error; }
function renderStudentPayload(payload) {
  studentState.payload = payload;
  renders.push(`${payload.phase}:${payload.groups?.[0]?.name || "no-groups"}`);
  renderedTimingTags.push(studentResponseClockTimings.get(payload)?.tag || null);
}
const waitingStatus = {activity_id: 7, status: "closed", phase: "waiting", server_now: "2026-08-15T00:00:00Z", selection_opens_at: null, student_login_allowed: true, status_message: "waiting"};
const countdownStatus = {activity_id: 7, status: "open", phase: "countdown", server_now: "2026-08-15T00:00:01Z", selection_opens_at: "2026-08-15T00:00:10Z", student_login_allowed: true, status_message: "countdown"};
const openStatus = {activity_id: 7, status: "open", phase: "open", server_now: "2026-08-15T00:00:11Z", selection_opens_at: "2026-08-15T00:00:10Z", student_login_allowed: true, status_message: "open"};
studentResponseClockTimings.set(waitingStatus, {tag: "waiting-rtt"});
studentResponseClockTimings.set(countdownStatus, {tag: "countdown-rtt"});
studentResponseClockTimings.set(openStatus, {tag: "open-rtt"});
const responses = [
  waitingStatus,
  countdownStatus,
  {csrf_token: "csrf", phase: "countdown", selection_opens_at: "2026-08-15T00:00:10Z", selection: null, groups: [{id: 1, name: "当前教学组", full: false}], student: {id: 1}, settings: {activity_id: 7, activity_title: "压力测试", status: "open"}},
  openStatus,
  {csrf_token: "csrf", phase: "open", selection_opens_at: "2026-08-15T00:00:10Z", selection: null, groups: [{id: 1, name: "当前教学组", full: false}], student: {id: 1}, settings: {activity_id: 7, activity_title: "压力测试", status: "open"}},
];
async function studentApi(path) { calls.push(path); return responses.shift(); }
eval(mergeBlock + pollingBlock);
(async () => {
  startStudentPolling();
  await intervalCallback();
  await intervalCallback();
  await intervalCallback();
  now = 2000;
  await intervalCallback();
  process.stdout.write(JSON.stringify({calls, renders, renderedTimingTags, synchronizedTimingTags, phase: studentState.payload.phase}));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    result = _run_node(script)

    assert result["calls"] == [
        "/api/public/status",
        "/api/public/status",
        "/api/student/me",
        "/api/public/status",
        "/api/student/me",
    ]
    assert result["renders"] == [
        "waiting:登录时旧教学组",
        "countdown:当前教学组",
        "open:当前教学组",
        "open:当前教学组",
    ]
    assert result["renderedTimingTags"][0] == "waiting-rtt"
    assert "countdown-rtt" in result["synchronizedTimingTags"]
    assert "open-rtt" in result["synchronizedTimingTags"]
    assert result["phase"] == "open"


def test_waiting_heartbeat_refreshes_private_state_after_admin_backfill() -> None:
    _, _, javascript = _student_sources()
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const pollingBlock = "function startStudentPolling" + source
  .split("function startStudentPolling", 2)[1]
  .split("function tickStudentCountdown", 1)[0];
const calls = [];
const renders = [];
const STUDENT_WAITING_POLL_INTERVAL_MS = 2500;
const STUDENT_SELECTED_SYNC_INTERVAL_MS = 10000;
const STUDENT_HEARTBEAT_INTERVAL_MS = 15000;
let heartbeatCallback = null;
const studentState = {
  csrf: "csrf",
  payload: {
    phase: "waiting",
    selection: null,
    groups: [{id: 1, name: "第一教学组", full: false}],
    student: {id: 11},
    settings: {activity_id: 7, status: "closed"},
  },
  selectedGroupId: null,
  pollTimer: null,
  heartbeatTimer: null,
  pollInFlight: false,
  heartbeatInFlight: false,
  lastSelectedSyncAt: 0,
};
global.clearInterval = () => {};
global.setInterval = (callback, delay) => {
  if (delay === STUDENT_HEARTBEAT_INTERVAL_MS) heartbeatCallback = callback;
  return delay;
};
function studentMonotonicNow() { return 1000; }
function studentPhase(payload) { return payload.phase; }
function synchronizeStudentClock() {}
function markStudentConnectionHealthy() {}
function handleStudentSessionExpired() { throw new Error("unexpected expiry"); }
function reportStudentConnectionIssue(error) { throw error; }
function showStudentMessage() {}
function mergePublicStatusIntoStudentPayload(payload) { return payload; }
function renderStudentPayload(payload) {
  studentState.payload = payload;
  renders.push(payload.selection?.group_name || null);
}
const responses = [
  {ok: true, has_selection: true, phase: "waiting"},
  {
    csrf_token: "next-csrf",
    phase: "waiting",
    selection: {group_id: 3, group_name: "管理员补录教学组", selected_at: "2026-08-15T15:00:00Z"},
    groups: [{id: 3, name: "管理员补录教学组", full: false}],
    student: {id: 11},
    settings: {activity_id: 7, status: "closed"},
  },
];
async function studentApi(path) {
  calls.push(path);
  return responses.shift();
}
eval(pollingBlock);
(async () => {
  startStudentPolling();
  await heartbeatCallback();
  process.stdout.write(JSON.stringify({calls, renders, csrf: studentState.csrf, selection: studentState.payload.selection}));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    result = _run_node(script)

    assert result["calls"] == ["/api/student/heartbeat", "/api/student/me"]
    assert result["renders"] == ["管理员补录教学组"]
    assert result["csrf"] == "next-csrf"
    assert result["selection"]["group_id"] == 3


def test_countdown_boundary_reuses_prepared_snapshot_without_refetch() -> None:
    _, _, javascript = _student_sources()
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const countdownBlock = "function tickStudentCountdown" + source
  .split("function tickStudentCountdown", 2)[1]
  .split('studentEls.loginForm.addEventListener', 1)[0];
const renders = [];
const calls = [];
const selectionOpensAt = "2026-08-15T00:00:10Z";
const studentState = {
  payload: {
    phase: "open",
    selection_opens_at: selectionOpensAt,
    groups: [{name: "倒计时期间准备的教学组"}],
    selection: null,
    settings: {activity_id: 7, selection_opens_at: selectionOpensAt},
  },
  preparedCountdownKey: `7:${selectionOpensAt}`,
  boundaryRefreshPending: false,
  pollInFlight: false,
};
const studentEls = {
  waitingView: {classList: {contains: () => false}},
};
function studentPhase() { return "open"; }
function renderStudentPayload(payload) { renders.push(payload.groups[0].name); }
function studentApi(path) { calls.push(path); throw new Error("prepared snapshot must avoid refetch"); }
eval(countdownBlock);
tickStudentCountdown();
process.stdout.write(JSON.stringify({calls, renders}));
"""
    result = _run_node(script)

    assert result["calls"] == []
    assert result["renders"] == ["倒计时期间准备的教学组"]


def test_countdown_boundary_fetches_when_no_snapshot_was_prepared() -> None:
    _, _, javascript = _student_sources()
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const countdownBlock = "function tickStudentCountdown" + source
  .split("function tickStudentCountdown", 2)[1]
  .split('studentEls.loginForm.addEventListener', 1)[0];
const renders = [];
const calls = [];
let resolvePrivateSnapshot;
const studentState = {
  payload: {phase: "open", groups: [{name: "登录时旧教学组"}], selection: null},
  preparedCountdownKey: null,
  boundaryRefreshPending: false,
  pollInFlight: false,
};
const studentEls = {
  waitingView: {classList: {contains: () => false}},
};
function studentPhase() { return "open"; }
function renderStudentPayload(payload) { renders.push(payload.groups[0].name); }
function studentApi(path) {
  calls.push(path);
  return new Promise((resolve) => { resolvePrivateSnapshot = resolve; });
}
eval(countdownBlock);
(async () => {
  tickStudentCountdown();
  const beforePrivateSnapshot = [...renders];
  resolvePrivateSnapshot({phase: "open", groups: [{name: "当前教学组"}], selection: null});
  await new Promise((resolve) => setImmediate(resolve));
  process.stdout.write(JSON.stringify({calls, beforePrivateSnapshot, renders}));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    result = _run_node(script)

    assert result["calls"] == ["/api/student/me"]
    assert result["beforePrivateSnapshot"] == []
    assert result["renders"] == ["当前教学组"]
