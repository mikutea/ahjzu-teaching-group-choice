from html.parser import HTMLParser
import json
from pathlib import Path
import re
import subprocess


ROOT = Path(__file__).resolve().parents[1]


class _Ids(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: dict[str, dict[str, str | None]] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if element_id := values.get("id"):
            self.ids[element_id] = {"tag": tag, **values}


def _sources() -> tuple[str, str, str]:
    return (
        (ROOT / "web" / "admin.html").read_text(encoding="utf-8"),
        (ROOT / "web" / "admin.js").read_text(encoding="utf-8"),
        (ROOT / "web" / "app.css").read_text(encoding="utf-8"),
    )


def test_absent_roster_dialog_is_grouped_and_never_exposes_credentials() -> None:
    html, javascript, css = _sources()
    parser = _Ids()
    parser.feed(html)

    assert parser.ids["danger-dialog-roster"]["tag"] == "section"
    assert parser.ids["danger-dialog-roster-groups"]["tag"] == "div"
    assert "renderConfirmationRoster" in javascript
    assert "const grouped = new Map()" in javascript
    assert 'left.localeCompare(right, "zh-CN")' in javascript
    action = javascript.split("async function handleSelectionPhaseAction", 1)[1].split(
        "adminEls.statusButton.addEventListener", 1
    )[0]
    assert "absentRoster" in action
    assert "仍可继续开始" in action
    assert "student_no" not in action
    assert "activation_code" not in action
    assert ".confirm-roster__name-grid" in css


def test_countdown_uses_one_raf_ticker_and_single_shot_number_animation() -> None:
    _, javascript, css = _sources()
    ticker = javascript.split("function startCountdownTicker", 1)[1].split(
        "function dashboardPhase", 1
    )[0]
    number = javascript.split("function setCountdownNumber", 1)[1].split(
        "function startCountdownTicker", 1
    )[0]

    assert "serverSynchronizedDate" in ticker
    assert "requestStartedAt + sample.responseReceivedAt" in javascript
    assert "requestAnimationFrame(tick)" in ticker
    assert "countdownLastSecond === seconds" in number
    assert 'classList.add("is-ticking")' in number
    assert ".countdown-content strong.is-ticking" in css
    assert "countdown-number .92s" not in css
    assert "countdown-number" in css and "infinite" not in css.split(
        ".countdown-content strong.is-ticking", 1
    )[1].split(".countdown-content h2", 1)[0]
    assert "transition: opacity .38s ease" in css
    assert "prefers-reduced-motion: reduce" in css


def test_live_lists_loop_only_on_overflow_and_resume_after_visibility_change() -> None:
    _, javascript, css = _sources()

    assert javascript.count("list.scrollHeight > list.clientHeight + 4") >= 2
    assert "list.scrollTop % loopHeight" in javascript
    assert 'document.addEventListener("visibilitychange"' in javascript
    assert 'renderUnselectedList({ force: true })' in javascript
    assert 'renderLiveSelectionFeed(adminState.dashboard.recent_selections || [], { force: true })' in javascript
    assert "grid-auto-rows: max-content" in css
    assert "will-change: scroll-position" in css


def test_completion_progress_and_excel_exports_are_projection_ready() -> None:
    html, javascript, css = _sources()
    parser = _Ids()
    parser.feed(html)

    track = parser.ids["metric-rate-track"]
    assert track["role"] == "progressbar"
    assert track["aria-valuemin"] == "0"
    assert track["aria-valuemax"] == "100"
    assert parser.ids["export-selections"]["href"] == "/api/admin/export/selections.xlsx"
    assert parser.ids["export-unselected"]["href"] == "/api/admin/export/unselected.xlsx"
    assert "/api/admin/export/selections.xlsx?" in javascript
    assert "/api/admin/export/unselected.xlsx?" in javascript
    assert '[adminEls.exportSelections, "选择记录.xlsx"' in javascript
    assert '[adminEls.exportUnselected, "未选学生名单.xlsx"' in javascript
    assert re.search(r"/api/admin/export/[^\"'`\s]+\.csv", html + javascript) is None
    assert "rateCount.textContent" in javascript
    assert 'setAttribute("aria-valuetext"' in javascript
    assert ".completion-progress__scale" in css
    assert "repeating-linear-gradient" in css


def test_phone_admin_has_only_two_primary_entries_and_card_roster() -> None:
    html, javascript, css = _sources()

    overview = html.split('data-view="overview"', 1)[1].split("</button>", 1)[0]
    students = html.split('data-view="students"', 1)[1].split("</button>", 1)[0]
    assert 'data-mobile-label="实时大屏"' in overview
    assert 'data-mobile-label="激活码查询"' in students
    assert '.admin-nav__item[data-view="structure"]' in css
    assert '.admin-nav__item[data-view="settings"]' in css
    assert "grid-template-columns: minmax(0,1fr) minmax(104px,116px)" in css
    assert "overflow-x: hidden" in css
    assert ".admin-authenticated #view-overview .live-board.is-presentation" in css
    assert "grid-template-columns: 1fr;" in css
    assert "shouldUsePresentationFallback" in javascript
    assert 'window.matchMedia("(max-width: 700px)").matches' in javascript
    assert "mobileLookupWaiting" not in javascript
    assert "const filtered = filteredRosterStudents(students)" in javascript
    assert "enterPresentationFallback" in javascript


def test_phone_admin_keeps_a_visible_safe_logout_and_a_fixed_login_viewport() -> None:
    html, _, css = _sources()
    parser = _Ids()
    parser.feed(html)

    assert parser.ids["admin-logout"]["tag"] == "button"
    assert parser.ids["admin-logout"]["type"] == "button"
    phone_console_css = css.split("/* Phone admin:", 1)[1].split(
        "@media (max-width: 500px)", 1
    )[0]
    assert "grid-template-columns: minmax(92px,32vw) minmax(0,1fr) 48px" in phone_console_css
    assert ".admin-authenticated .admin-sidebar__footer { display: block" in phone_console_css
    assert ".admin-authenticated .admin-sidebar__footer #admin-logout" in phone_console_css
    assert "width: 48px" in phone_console_css

    phone_css = css.split("@media (max-width: 700px)", 1)[1].split(
        "/* Phone admin:", 1
    )[0]
    assert ".admin-body:not(.admin-authenticated)" in phone_css
    assert "height: 100dvh" in phone_css
    assert "overflow: hidden" in phone_css
    assert "grid-template-rows: minmax(146px,19dvh) minmax(0,1fr)" in phone_css
    assert ".admin-login-card" in phone_css and "overflow-y: auto" in phone_css


def test_native_fullscreen_three_column_stage_fits_tablet_and_small_projector_widths() -> None:
    _, _, css = _sources()
    responsive = css.split(
        "@media (min-width: 701px) and (max-width: 1223px)", 1
    )[1].split("@media (max-width: 980px)", 1)[0]

    assert ".live-board:fullscreen" in responsive
    assert ".live-board.is-presentation" in responsive
    assert "grid-template-columns: minmax(0,.96fr) minmax(0,1.28fr) minmax(0,1fr)" in responsive
    assert "grid-template-columns: minmax(0,1fr) auto auto auto" in responsive
    assert ".board-presentation-footer" in responsive and "margin: 0 -12px" in responsive
    assert ".board-presentation-sync" in responsive and "display: none" in responsive
    assert "width: clamp(205px,28vw,310px)" in responsive
    assert "aspect-ratio: 3808 / 909" in css


def test_quota_inputs_save_after_idle_then_refresh_latest_dashboard() -> None:
    _, javascript, _ = _sources()
    persist = javascript.split("async function persistQuotaInput", 1)[1].split(
        "function scheduleQuotaSave", 1
    )[0]

    assert "Number.isInteger(nextValue)" in persist
    assert 'setAttribute("aria-busy", "true")' in persist
    assert "await adminApi" in persist
    assert "await loadDashboard({ quiet: true, afterMutation: true })" in persist
    assert "scheduleQuotaSave(input, 0)" in javascript
    assert 'adminEls.quotaMatrix.addEventListener("input"' in javascript
    assert "structureFingerprint" in javascript
    assert "adminState.quotaSaveTimers.size > 0" in javascript
    assert 'adminEls.quotaMatrix.querySelector(\'input[data-saving="true"]\')' in javascript
    assert 'document.activeElement?.closest?.("#major-editor, #group-editor, #quota-matrix")' in javascript


def test_non_overview_admin_views_poll_only_public_phase_status() -> None:
    _, javascript, _ = _sources()
    status_sync = javascript.split("async function loadDashboardStatusSnapshot", 1)[1].split(
        "function startAdminPolling", 1
    )[0]
    status_merge = javascript.split("function mergeDashboardStatusSnapshot", 1)[1].split(
        "async function loadDashboardStatusSnapshot", 1
    )[0]
    polling = javascript.split("function startAdminPolling", 1)[1].split(
        "function renderDashboard", 1
    )[0]

    assert 'adminApi("/api/public/status")' in status_sync
    assert 'adminState.currentView === "overview"' in status_sync
    assert 'adminState.currentView !== "students"' not in status_sync
    assert "mergeDashboardStatusSnapshot" in status_sync
    assert "clearAllRevealedActivationCodes()" in status_merge
    assert "renderDashboardPhaseStatus" in status_sync
    assert "/api/admin/dashboard" not in status_sync
    assert "renderStudentRoster" not in status_sync
    assert "renderAssignmentTable" not in status_sync
    assert "activation_code" not in status_sync
    assert 'else loadDashboardStatusSnapshot({ quiet: true });' in polling
    assert "loadDashboardStatusSnapshot({ quiet: true })" in polling
    assert 'adminState.currentView === "overview"' in polling


def test_mobile_activity_switch_scrubs_old_roster_and_reloads_dashboard_once() -> None:
    _, javascript, _ = _sources()
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const statusFunctions = "function mergeDashboardStatusSnapshot" + source
  .split("function mergeDashboardStatusSnapshot", 2)[1]
  .split("function startAdminPolling", 1)[0];
let publicLoads = 0;
let dashboardLoads = 0;
let clearCalls = 0;
let phaseRenders = 0;
let observedBeforeReload = null;
const adminState = {
  csrf: "qa",
  currentView: "students",
  dashboard: {
    status: "waiting",
    phase: "waiting",
    settings: {activity_id: 41, status: "waiting", phase: "waiting"},
    students: [{id: 11, name: "旧名单学生"}],
    unselected_students: [{id: 11, name: "旧名单学生"}],
    recent_selections: [{student_id: 11}],
    absent_students: [{id: 11}],
    presence: {absent_students: [{id: 11}]},
  },
  dashboardClockSample: null,
  statusSyncLoading: false,
  loading: false,
  revealedActivationCodes: new Map([["41:11", "A1B2C3"]]),
  activationHideTimers: new Map([["41:11", 1234]]),
  connectionInterrupted: false,
  lastBackgroundErrorAt: 0,
};
const adminEls = {
  assignmentBody: {
    dataset: {activityId: "41"},
    replaceChildren() { this.cleared = true; },
  },
  rosterBody: {
    dataset: {activityId: "41"},
    replaceChildren() { this.cleared = true; },
  },
  rosterCount: {textContent: "1 人"},
  statusBadge: {className: "", textContent: ""},
  statusButton: {textContent: "", disabled: false, title: ""},
  lastRefresh: {textContent: ""},
};
const mobileAdminQuery = {matches: true};
const document = {hidden: false};
const synchronizeServerClock = () => {};
const renderDashboardPhaseStatus = () => { phaseRenders += 1; };
const showAdminToast = () => {};
const clearAllRevealedActivationCodes = () => {
  clearCalls += 1;
  adminState.revealedActivationCodes.clear();
  adminState.activationHideTimers.clear();
};
async function adminApi(path) {
  if (path !== "/api/public/status") throw new Error(`unexpected API ${path}`);
  publicLoads += 1;
  return {activity_id: 42, status: "waiting", phase: "waiting", server_now: "2026-08-14T12:00:00+08:00"};
}
async function loadDashboard() {
  dashboardLoads += 1;
  observedBeforeReload = {
    students: adminState.dashboard.students.length,
    unselected: adminState.dashboard.unselected_students.length,
    recent: adminState.dashboard.recent_selections.length,
    absent: adminState.dashboard.absent_students.length,
    presenceAbsent: adminState.dashboard.presence.absent_students.length,
    assignmentCleared: adminEls.assignmentBody.cleared === true,
    rosterCleared: adminEls.rosterBody.cleared === true,
    assignmentHasActivityId: Object.hasOwn(adminEls.assignmentBody.dataset, "activityId"),
    rosterHasActivityId: Object.hasOwn(adminEls.rosterBody.dataset, "activityId"),
    revealedCodes: adminState.revealedActivationCodes.size,
  };
  adminState.dashboard = {
    status: "waiting",
    phase: "waiting",
    settings: {activity_id: 42, status: "waiting", phase: "waiting"},
    students: [{id: 22, name: "新名单学生"}],
    unselected_students: [{id: 22, name: "新名单学生"}],
    recent_selections: [],
    absent_students: [],
    presence: {absent_students: []},
  };
}
eval(`
  (async () => {
    ${statusFunctions}
    await loadDashboardStatusSnapshot({quiet: true});
    await loadDashboardStatusSnapshot({quiet: true});
    process.stdout.write(JSON.stringify({
      publicLoads,
      dashboardLoads,
      clearCalls,
      phaseRenders,
      observedBeforeReload,
      currentActivityId: adminState.dashboard.settings.activity_id,
    }));
  })().catch((error) => { console.error(error); process.exitCode = 1; });
`);
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert execution.returncode == 0, execution.stderr
    assert json.loads(execution.stdout) == {
        "publicLoads": 2,
        "dashboardLoads": 1,
        "clearCalls": 1,
        "phaseRenders": 1,
        "observedBeforeReload": {
            "students": 0,
            "unselected": 0,
            "recent": 0,
            "absent": 0,
            "presenceAbsent": 0,
            "assignmentCleared": True,
            "rosterCleared": True,
            "assignmentHasActivityId": False,
            "rosterHasActivityId": False,
            "revealedCodes": 0,
        },
        "currentActivityId": 42,
    }


def test_backgrounding_admin_scrubs_activation_codes_immediately() -> None:
    _, javascript, _ = _sources()
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const credentialFunctions = "function scrubRevealedActivationCodeDom" + source.split("function scrubRevealedActivationCodeDom", 2)[1].split("function rememberRevealedActivationCode", 1)[0];
const visibilityHandler = 'document.addEventListener("visibilitychange"' + source.split('document.addEventListener("visibilitychange"', 2)[1].split("loadAdminSession();", 1)[0];
const valueClasses = new Set(["activation-code-value", "is-revealed"]);
const value = {textContent: "A1B2C3", classList: {remove(name) { valueClasses.delete(name); }}};
const button = {dataset: {action: "hide-activation-code"}, textContent: "隐藏", title: ""};
let handler = null;
const clearedTimers = [];
global.clearTimeout = (timer) => clearedTimers.push(timer);
global.document = {
  hidden: true,
  addEventListener(name, callback) { if (name === "visibilitychange") handler = callback; },
};
eval(`
  const adminState = {
    csrf: "qa",
    currentView: "students",
    activationHideTimers: new Map([["77:1", 1234], ["77:2", 5678]]),
    revealedActivationCodes: new Map([["77:1", "A1B2C3"], ["77:2", "D4E5F6"]]),
  };
  const adminEls = {rosterBody: {querySelectorAll(selector) {
    if (selector === ".activation-code-value.is-revealed") return [value];
    if (selector === "button[data-action=hide-activation-code]") return [button];
    return [];
  }}};
  ${credentialFunctions}
  ${visibilityHandler}
  if (!handler) throw new Error("visibilitychange handler not registered");
  handler();
  process.stdout.write(JSON.stringify({
    timers: adminState.activationHideTimers.size,
    codes: adminState.revealedActivationCodes.size,
    clearedTimers,
    value: value.textContent,
    revealedClass: valueClasses.has("is-revealed"),
    action: button.dataset.action,
    buttonText: button.textContent,
  }));
`);
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert execution.returncode == 0, execution.stderr
    result = json.loads(execution.stdout)

    assert result == {
        "timers": 0,
        "codes": 0,
        "clearedTimers": [1234, 5678],
        "value": "••••••",
        "revealedClass": False,
        "action": "reveal-activation-code",
        "buttonText": "显示明文",
    }


def test_leaving_student_lookup_scrubs_revealed_codes_immediately() -> None:
    _, javascript, _ = _sources()
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const switchBlock = "function switchAdminView" + source.split("function switchAdminView", 2)[1].split('document.querySelectorAll(".admin-nav__item").forEach((button) => button.addEventListener', 1)[0];
let clearCalls = 0;
global.window = {matchMedia: () => ({matches: false})};
global.document = {
  querySelectorAll(selector) {
    if (selector === ".admin-nav__item") return [{dataset: {view: "overview"}, classList: {toggle() {}}}];
    if (selector === ".admin-view") return [{classList: {add() {}}}];
    return [];
  },
  querySelector() { return {classList: {remove() {}}}; },
};
eval(`
  const adminState = {currentView: "students", dashboard: {recent_selections: []}};
  const clearAllRevealedActivationCodes = () => { clearCalls += 1; };
  const stopRosterAutoScroll = () => {};
  const stopLiveFeedAutoScroll = () => {};
  const stopWaitingFeedAutoScroll = () => {};
  const loadDashboard = () => {};
  const renderUnselectedList = () => {};
  const renderLiveSelectionFeed = () => {};
  const renderWaitingStudentFeed = () => {};
  ${switchBlock}
  switchAdminView("overview");
  switchAdminView("students");
  process.stdout.write(JSON.stringify({clearCalls, currentView: adminState.currentView}));
`);
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert execution.returncode == 0, execution.stderr
    assert json.loads(execution.stdout) == {"clearCalls": 1, "currentView": "students"}


def test_activation_reveal_accepts_only_current_identity_contract() -> None:
    _, javascript, _ = _sources()
    response_parser = javascript.split("function activationCodeFromResponse", 1)[1].split(
        "function renderStudentRoster", 1
    )[0]
    roster = javascript.split("function renderStudentRoster", 1)[1].split(
        "function fillSettingsForm", 1
    )[0]

    assert "result?.credential?.activation_code" in response_parser
    assert "result?.activation_code" not in response_parser
    assert "result?.code" not in response_parser
    assert "student.activation_code_revealable === true" in roster
    assert "activation_code_available" not in javascript
    assert "has_recoverable_activation_code" not in javascript
    assert "当前名单需重导入" not in javascript
    assert "重新导入当前规范名单" not in javascript
