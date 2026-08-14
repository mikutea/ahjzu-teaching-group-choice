import json
import subprocess
from html.parser import HTMLParser
from pathlib import Path


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


def test_topbar_is_a_board_entry_and_phase_control_stays_inside_board() -> None:
    html, javascript, _ = _sources()
    parser = _Ids()
    parser.feed(html)

    assert "toggle-status" not in parser.ids
    assert parser.ids["open-live-board"]["tag"] == "button"
    assert "进入实时大屏" in html
    assert parser.ids["board-start-countdown"]["tag"] == "button"
    assert 'adminEls.statusButton.addEventListener("click", enterBoardFullscreen)' in javascript
    assert 'adminEls.boardStart.addEventListener("click", handleSelectionPhaseAction)' in javascript
    phase_render = javascript.split("function renderBoardStage", 1)[1].split(
        "function normalizeReadiness", 1
    )[0]
    assert "adminEls.statusButton.textContent" not in phase_render


def test_entity_names_autosave_with_ime_guard_and_capacity_only_on_commit() -> None:
    _, javascript, _ = _sources()
    major = javascript.split("function renderMajorEditor", 1)[1].split(
        "function renderGroupEditor", 1
    )[0]
    group = javascript.split("function renderGroupEditor", 1)[1].split(
        "function renderQuotaMatrix", 1
    )[0]
    wiring = javascript.split("function wireEntityAutosave", 1)[1].split(
        "wireEntityAutosave(adminEls.majorEditor)", 1
    )[0]

    assert "save-major" not in major
    assert "save-group" not in group
    assert "makeEntitySaveState" in major and "makeEntitySaveState" in group
    assert 'addEventListener("compositionstart"' in wiring
    assert 'addEventListener("compositionend"' in wiring
    assert "event.isComposing" in wiring
    assert "scheduleEntityRowSave(row)" in wiring
    assert "离开输入框后保存容量" in wiring
    assert "includeCapacity = event.target === row._capacityInput" in wiring
    assert "delay = 360" in javascript
    assert "saveQueued" in javascript
    assert "保存失败 · 已还原" in javascript


def test_entity_autosave_keeps_the_latest_queued_edit_across_dashboard_refresh() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const dashboardFunctions = source.slice(
  source.indexOf("function structureEditorAutosaveBusy"),
  source.indexOf("function renderDashboardPhaseStatus"),
);
const saveFunctions = "function entityRowSaveKey" + source.split("function entityRowSaveKey", 2)[1].split(
  "function wireEntityAutosave", 1,
)[0];

const row = {
  dataset: {
    entityKind: "group",
    id: "3",
    originalName: "原教学组",
    originalCapacity: "10",
  },
  isConnected: true,
  _nameInput: {
    value: "第一版教学组",
    setCustomValidity() {},
    reportValidity() {},
  },
  _capacityInput: {
    value: "11",
    setCustomValidity() {},
    reportValidity() {},
  },
  _saveState: {className: "", textContent: ""},
  setAttribute() {},
  removeAttribute() {},
};
const makeElement = () => ({
  textContent: "",
  href: "",
  style: {},
  classList: {toggle() {}},
  setAttribute() {},
});
const majorEditor = {
  dataset: {activityId: "7"},
  querySelector() { return null; },
};
const groupEditor = {
  dataset: {activityId: "7"},
  querySelector(selector) {
    return row.isConnected && row.dataset.saving === "true" && selector.includes('data-saving="true"')
      ? row
      : null;
  },
};
const quotaMatrix = {querySelector() { return null; }};
const adminEls = new Proxy({majorEditor, groupEditor, quotaMatrix}, {
  get(target, property) {
    if (!(property in target)) target[property] = makeElement();
    return target[property];
  },
});
const adminState = {
  currentView: "structure",
  dashboard: null,
  entitySaveTimers: new Map(),
  quotaSaveTimers: new Map(),
  lastActivityId: 7,
  structureFingerprint: JSON.stringify([false, [3, "原教学组", true, 10, 1]]),
};
const document = {activeElement: null};
const liveBoard = {dataset: {}, classList: {toggle() {}}};
const synchronizeServerClock = () => {};
const dashboardPhase = () => "waiting";
const boardDisplayMode = () => "waiting";
const normalizedPresence = () => ({online: 0, absent: 0});
const clearAllRevealedActivationCodes = () => {};
const stopRosterAutoScroll = () => {};
const stopLiveFeedAutoScroll = () => {};
const stopWaitingFeedAutoScroll = () => {};
const renderBoardClock = () => {};
const renderReadiness = () => {};
const renderDashboardPhaseStatus = () => {};
const renderGroupProgress = () => {};
const renderLiveSelectionFeed = () => {};
const renderWaitingStudentFeed = () => {};
const renderQr = () => {};
const renderUnselectedList = () => {};
const renderRecentSelections = () => {};
const renderAssignmentTable = () => {};
const renderStudentRoster = () => {};
const renderActivities = () => {};
const fillSettingsForm = () => {};
const showAdminToast = () => {};
let structureRenders = 0;
const renderStructure = () => {
  structureRenders += 1;
  row.isConnected = false;
};

let serverGroup = {id: 3, name: "原教学组", active: true, total_capacity: 10, sort_order: 1, selected_count: 0};
const payloads = [];
const pendingResponses = [];
let activeRequests = 0;
let maxConcurrentRequests = 0;
async function adminApi(path, options) {
  if (path !== "/api/admin/groups/3") throw new Error(`unexpected API ${path}`);
  const payload = JSON.parse(options.body);
  payloads.push(payload);
  activeRequests += 1;
  maxConcurrentRequests = Math.max(maxConcurrentRequests, activeRequests);
  return new Promise((resolve) => pendingResponses.push(() => {
    if (Object.hasOwn(payload, "name")) serverGroup.name = payload.name;
    if (Object.hasOwn(payload, "total_capacity")) serverGroup.total_capacity = payload.total_capacity;
    activeRequests -= 1;
    resolve({});
  }));
}
function dashboardData() {
  return {
    settings: {activity_id: 7, activity_title: "回归测试", status: "waiting", phase: "waiting", public_base_url: ""},
    totals: {students: 0, selected: 0, unselected: 0},
    readiness: {},
    majors: [],
    groups: [{...serverGroup}],
    quotas: [],
    activities: [],
  };
}
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));

eval(`
  (async () => {
    ${dashboardFunctions}
    ${saveFunctions}
    async function loadDashboard() {
      const data = dashboardData();
      adminState.dashboard = data;
      renderDashboard(data);
    }
    const firstSave = persistEntityRow(row, {refreshAfter: true, includeCapacity: true});
    await tick();
    row._nameInput.value = "最终教学组";
    row._capacityInput.value = "12";
    await persistEntityRow(row, {refreshAfter: true, includeCapacity: true});
    pendingResponses.shift()();
    await firstSave;
    for (let attempt = 0; attempt < 20 && pendingResponses.length === 0; attempt += 1) await tick();
    if (pendingResponses.length) pendingResponses.shift()();
    for (let attempt = 0; attempt < 20 && (row.dataset.saving === "true" || adminState.entitySaveTimers.size); attempt += 1) await tick();
    const structureRendersAfterAutosaves = structureRenders;
    const rowConnectedAfterAutosaves = row.isConnected;
    await loadDashboard();
    process.stdout.write(JSON.stringify({
      payloads,
      maxConcurrentRequests,
      structureRendersAfterAutosaves,
      rowConnectedAfterAutosaves,
      structureRenders,
      rowConnected: row.isConnected,
      timers: adminState.entitySaveTimers.size,
      saving: row.dataset.saving === "true",
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
        "payloads": [
            {"name": "第一版教学组", "total_capacity": 11},
            {"name": "最终教学组", "total_capacity": 12},
        ],
        "maxConcurrentRequests": 1,
        "structureRendersAfterAutosaves": 1,
        "rowConnectedAfterAutosaves": False,
        "structureRenders": 1,
        "rowConnected": False,
        "timers": 0,
        "saving": False,
    }


def test_quota_autosave_defers_structure_rerender_until_put_finishes() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const dashboardFunctions = source.slice(
  source.indexOf("function structureEditorAutosaveBusy"),
  source.indexOf("function renderDashboardPhaseStatus"),
);
const quotaFunctions = source.slice(
  source.indexOf("function quotaInputKey"),
  source.indexOf('adminEls.quotaMatrix.addEventListener("input"'),
);

const makeElement = () => ({
  textContent: "",
  href: "",
  style: {},
  classList: {toggle() {}},
  setAttribute() {},
});
const majorEditor = {querySelector() { return null; }};
const groupEditor = {querySelector() { return null; }};
let activeQuotaInput = null;
const quotaMatrix = {
  dataset: {activityId: "7"},
  querySelector(selector) {
    return activeQuotaInput?.isConnected
      && activeQuotaInput.dataset.saving === "true"
      && selector.includes('data-saving="true"')
      ? activeQuotaInput
      : null;
  },
};
const adminEls = new Proxy({majorEditor, groupEditor, quotaMatrix}, {
  get(target, property) {
    if (!(property in target)) target[property] = makeElement();
    return target[property];
  },
});
const adminState = {
  currentView: "structure",
  dashboard: null,
  entitySaveTimers: new Map(),
  quotaSaveTimers: new Map(),
  lastActivityId: 7,
  structureFingerprint: JSON.stringify([false, [1, 2, 3, 0]]),
};
const document = {activeElement: null};
const liveBoard = {dataset: {}, classList: {toggle() {}}};
const synchronizeServerClock = () => {};
const dashboardPhase = () => "waiting";
const boardDisplayMode = () => "waiting";
const normalizedPresence = () => ({online: 0, absent: 0});
const clearAllRevealedActivationCodes = () => {};
const stopRosterAutoScroll = () => {};
const stopLiveFeedAutoScroll = () => {};
const stopWaitingFeedAutoScroll = () => {};
const renderBoardClock = () => {};
const renderReadiness = () => {};
const renderDashboardPhaseStatus = () => {};
const renderGroupProgress = () => {};
const renderLiveSelectionFeed = () => {};
const renderWaitingStudentFeed = () => {};
const renderQr = () => {};
const renderUnselectedList = () => {};
const renderRecentSelections = () => {};
const renderAssignmentTable = () => {};
const renderStudentRoster = () => {};
const renderActivities = () => {};
const fillSettingsForm = () => {};
const toasts = [];
const showAdminToast = (message, kind) => toasts.push([message, kind]);
const renderedCapacities = [];
const renderStructure = (data) => renderedCapacities.push(data.quotas[0].capacity);

let timerId = 0;
const scheduledTimers = new Map();
const setTimeout = (callback) => {
  timerId += 1;
  scheduledTimers.set(timerId, callback);
  return timerId;
};
const clearTimeout = (id) => scheduledTimers.delete(id);
const runNextTimer = () => {
  const [id, callback] = scheduledTimers.entries().next().value;
  scheduledTimers.delete(id);
  callback();
};

const makeQuotaInput = ({groupId, original, value}) => ({
  value: String(value),
  isConnected: true,
  dataset: {majorId: "1", groupId: String(groupId), original: String(original)},
  title: "",
  setCustomValidity() {},
  reportValidity() {},
  setAttribute() {},
  removeAttribute() {},
});
let serverCapacity = 3;
const requests = [];
let resolveSuccessfulPut;
async function adminApi(path, options) {
  requests.push({path, activityId: options.activityId, payload: JSON.parse(options.body)});
  if (path.endsWith("/12")) throw Object.assign(new Error("配额不能小于当前已选人数 3"), {status: 409});
  return new Promise((resolve) => {
    resolveSuccessfulPut = () => {
      serverCapacity = JSON.parse(options.body).capacity;
      resolve({});
    };
  });
}
function dashboardData(capacity = serverCapacity, activityId = 7) {
  return {
    settings: {activity_id: activityId, activity_title: "回归测试", status: "waiting", phase: "waiting", public_base_url: ""},
    totals: {students: 0, selected: 0, unselected: 0},
    readiness: {},
    majors: [{id: 1, name: "建筑学", active: true, sort_order: 1}],
    groups: [{id: 2, name: "第一教学组", active: true, total_capacity: 10, sort_order: 1, selected_count: 0}],
    quotas: [{major_id: 1, group_id: 2, capacity, selected_count: 0}],
    activities: [],
  };
}
let dashboardRefreshes = 0;
let renderDashboardForHarness;
async function loadDashboard() {
  dashboardRefreshes += 1;
  adminState.dashboard = dashboardData();
  renderDashboardForHarness(adminState.dashboard);
}
const tick = () => Promise.resolve();

eval(`
  (async () => {
    ${dashboardFunctions}
    ${quotaFunctions}
    renderDashboardForHarness = renderDashboard;
    const input = makeQuotaInput({groupId: 2, original: 3, value: 8});
    activeQuotaInput = input;
    scheduleQuotaSave(input, 650);
    adminState.dashboard = dashboardData(4);
    renderDashboard(adminState.dashboard);
    const rendersWhileQueued = renderedCapacities.length;

    runNextTimer();
    await tick();
    adminState.dashboard = dashboardData(5);
    renderDashboard(adminState.dashboard);
    const rendersWhilePutInFlight = renderedCapacities.length;
    resolveSuccessfulPut();
    for (let attempt = 0; attempt < 20 && input.dataset.saving === "true"; attempt += 1) await tick();

    const failedInput = makeQuotaInput({groupId: 12, original: 2, value: 9});
    activeQuotaInput = failedInput;
    adminState.dashboard.settings.activity_id = 99;
    await persistQuotaInput(failedInput);

    process.stdout.write(JSON.stringify({
      rendersWhileQueued,
      rendersWhilePutInFlight,
      renderedCapacities,
      dashboardRefreshes,
      requests,
      savedOriginal: input.dataset.original,
      savedValue: input.value,
      savedBusy: input.dataset.saving === "true",
      failedOriginal: failedInput.dataset.original,
      failedValue: failedInput.value,
      failedBusy: failedInput.dataset.saving === "true",
      timers: adminState.quotaSaveTimers.size,
      lastToast: toasts.at(-1),
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
        "rendersWhileQueued": 0,
        "rendersWhilePutInFlight": 0,
        "renderedCapacities": [8, 8],
        "dashboardRefreshes": 1,
        "requests": [
            {
                "path": "/api/admin/quotas/1/2",
                "activityId": 7,
                "payload": {"capacity": 8},
            },
            {
                "path": "/api/admin/quotas/1/12",
                "activityId": 7,
                "payload": {"capacity": 9},
            },
        ],
        "savedOriginal": "8",
        "savedValue": "8",
        "savedBusy": False,
        "failedOriginal": "2",
        "failedValue": "2",
        "failedBusy": False,
        "timers": 0,
        "lastToast": ["配额不能小于当前已选人数 3", "error"],
    }


def test_quota_autosave_serializes_latest_value_and_stops_on_activity_cas() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const quotaFunctions = source.slice(
  source.indexOf("function quotaInputKey"),
  source.indexOf('adminEls.quotaMatrix.addEventListener("input"'),
);

const adminState = {
  currentView: "structure",
  dashboard: {settings: {activity_id: 7}},
  quotaSaveTimers: new Map(),
};
const adminEls = {quotaMatrix: {dataset: {activityId: "7"}}};
const renderLatestStructureAfterAutosave = () => {};
const toasts = [];
const showAdminToast = (message, kind) => toasts.push([message, kind]);

let timerId = 0;
const scheduledTimers = new Map();
const setTimeout = (callback) => {
  timerId += 1;
  scheduledTimers.set(timerId, callback);
  return timerId;
};
const clearTimeout = (id) => scheduledTimers.delete(id);
const runNextTimer = () => {
  const next = scheduledTimers.entries().next().value;
  if (!next) throw new Error("expected a queued quota save timer");
  const [id, callback] = next;
  scheduledTimers.delete(id);
  callback();
};
const tick = () => Promise.resolve();
const settle = async (input) => {
  for (let attempt = 0; attempt < 30; attempt += 1) {
    await tick();
    if (input.dataset.saving !== "true" && adminState.quotaSaveTimers.size === 0) return;
  }
  throw new Error("quota save did not settle");
};

const makeInput = () => ({
  value: "8",
  isConnected: true,
  dataset: {majorId: "1", groupId: "2", original: "3", pending: "true"},
  title: "按回车或离开输入框保存配额",
  setCustomValidity() {},
  reportValidity() {},
  setAttribute() {},
  removeAttribute() {},
});

let serverCapacity;
let requests;
let pendingPuts;
let activeRequests;
let maxConcurrentRequests;
let dashboardRefreshes;
function resetScenario() {
  for (const timer of adminState.quotaSaveTimers.values()) clearTimeout(timer);
  adminState.quotaSaveTimers.clear();
  scheduledTimers.clear();
  adminState.dashboard.settings.activity_id = 7;
  adminEls.quotaMatrix.dataset.activityId = "7";
  serverCapacity = 3;
  requests = [];
  pendingPuts = [];
  activeRequests = 0;
  maxConcurrentRequests = 0;
  dashboardRefreshes = 0;
  toasts.length = 0;
}
async function adminApi(path, options) {
  const capacity = JSON.parse(options.body).capacity;
  requests.push({capacity, activityId: options.activityId});
  activeRequests += 1;
  maxConcurrentRequests = Math.max(maxConcurrentRequests, activeRequests);
  return new Promise((resolve, reject) => pendingPuts.push({
    capacity,
    succeed() {
      serverCapacity = capacity;
      activeRequests -= 1;
      resolve({});
    },
    fail(error) {
      activeRequests -= 1;
      reject(error);
    },
  }));
}
async function loadDashboard() {
  dashboardRefreshes += 1;
}
const snapshot = (input) => ({
  requests: requests.map((request) => request.capacity),
  activityIds: requests.map((request) => request.activityId),
  maxConcurrentRequests,
  serverCapacity,
  original: input.dataset.original,
  value: input.value,
  pending: input.dataset.pending === "true",
  queued: input.dataset.saveQueued === "true",
  saving: input.dataset.saving === "true",
  timers: adminState.quotaSaveTimers.size,
  dashboardRefreshes,
});

eval(`
  (async () => {
    ${quotaFunctions}

    resetScenario();
    const successInput = makeInput();
    const firstSuccess = persistQuotaInput(successInput);
    await tick();
    successInput.value = "9";
    successInput.dataset.pending = "true";
    const queuedSuccess = persistQuotaInput(successInput);
    await tick();
    if (pendingPuts.length > 1) {
      pendingPuts[1].succeed();
      await queuedSuccess;
      pendingPuts[0].succeed();
      await firstSuccess;
    } else {
      pendingPuts[0].succeed();
      await firstSuccess;
      runNextTimer();
      await tick();
      pendingPuts[1].succeed();
      await settle(successInput);
    }
    const success = snapshot(successInput);

    resetScenario();
    const failureInput = makeInput();
    const firstFailure = persistQuotaInput(failureInput);
    await tick();
    failureInput.value = "9";
    failureInput.dataset.pending = "true";
    const queuedAfterFailure = persistQuotaInput(failureInput);
    await tick();
    pendingPuts[0].fail(Object.assign(new Error("临时保存失败"), {status: 500}));
    await firstFailure;
    if (pendingPuts.length === 1) {
      runNextTimer();
      await tick();
    }
    pendingPuts[1].succeed();
    await queuedAfterFailure;
    await settle(failureInput);
    const failureThenLatest = snapshot(failureInput);

    resetScenario();
    const casInput = makeInput();
    const firstCas = persistQuotaInput(casInput);
    await tick();
    casInput.value = "9";
    casInput.dataset.pending = "true";
    const queuedBeforeCas = persistQuotaInput(casInput);
    await tick();
    adminState.dashboard.settings.activity_id = 8;
    pendingPuts[0].fail(Object.assign(new Error("当前活动已经变化，请刷新页面后重试"), {status: 409}));
    await firstCas;
    if (pendingPuts.length > 1) {
      pendingPuts[1].succeed();
      await queuedBeforeCas;
    }
    await settle(casInput);
    const activityCas = snapshot(casInput);

    process.stdout.write(JSON.stringify({success, failureThenLatest, activityCas}));
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
        "success": {
            "requests": [8, 9],
            "activityIds": [7, 7],
            "maxConcurrentRequests": 1,
            "serverCapacity": 9,
            "original": "9",
            "value": "9",
            "pending": False,
            "queued": False,
            "saving": False,
            "timers": 0,
            "dashboardRefreshes": 2,
        },
        "failureThenLatest": {
            "requests": [8, 9],
            "activityIds": [7, 7],
            "maxConcurrentRequests": 1,
            "serverCapacity": 9,
            "original": "9",
            "value": "9",
            "pending": False,
            "queued": False,
            "saving": False,
            "timers": 0,
            "dashboardRefreshes": 1,
        },
        "activityCas": {
            "requests": [8],
            "activityIds": [7],
            "maxConcurrentRequests": 1,
            "serverCapacity": 3,
            "original": "3",
            "value": "3",
            "pending": False,
            "queued": False,
            "saving": False,
            "timers": 0,
            "dashboardRefreshes": 1,
        },
    }


def test_mutation_refresh_waits_for_an_inflight_poll_and_add_forms_force_refresh() -> None:
    _, javascript, _ = _sources()
    loader = javascript.split("async function loadDashboard", 1)[1].split(
        "function mergeDashboardStatusSnapshot", 1
    )[0]
    add_major = javascript.split(
        'document.querySelector("#add-major-form").addEventListener', 1
    )[1].split(
        'document.querySelector("#add-group-form").addEventListener', 1
    )[0]
    add_group = javascript.split(
        'document.querySelector("#add-group-form").addEventListener', 1
    )[1].split("function entityRowSaveKey", 1)[0]

    assert "afterMutation" in loader
    assert "await adminState.dashboardLoadPromise" in loader
    assert "return loadDashboard({ quiet, afterMutation: false })" in loader
    assert "loadDashboard({ afterMutation: true })" in add_major
    assert "loadDashboard({ afterMutation: true })" in add_group
    assert '#major-editor, #group-editor, #quota-matrix' in javascript


def test_waiting_and_unselected_lists_are_continuous_without_poll_reset() -> None:
    html, javascript, css = _sources()
    parser = _Ids()
    parser.feed(html)

    assert parser.ids["waiting-student-feed"]["tag"] == "div"
    assert parser.ids["waiting-feed-state"]["tag"] == "span"
    waiting = javascript.split("function setupWaitingFeedLoop", 1)[1].split(
        "function renderQr", 1
    )[0]
    assert "list.scrollHeight > list.clientHeight + 4" in waiting
    assert 'clone.dataset.waitingClone = "true"' in waiting
    assert "waitingFeedFingerprint" in waiting
    assert "student.last_seen_at" not in waiting
    assert "setupRosterLoop(previousScrollRatio)" in javascript
    assert "rosterFingerprint" in javascript
    assert "waitingFeedScrollPosition + elapsed" in javascript
    assert "rosterScrollPosition + elapsed" in javascript
    assert "liveFeedScrollPosition + elapsed" in javascript
    unselected_render = javascript.split("function renderUnselectedList", 1)[1].split(
        "function renderRecentSelections", 1
    )[0]
    fingerprint_guard = unselected_render.index("adminState.rosterFingerprint === fingerprint")
    assert 'unselectedPage.textContent = visibleStudents.length ? "实时更新"' not in unselected_render[:fingerprint_guard]
    assert ".waiting-student-feed" in css and "will-change: scroll-position" in css
    assert ".unselected-list" in css and "will-change: scroll-position" in css


def test_phone_roster_defaults_to_all_and_qr_portal_is_larger_and_structured() -> None:
    html, javascript, css = _sources()
    parser = _Ids()
    parser.feed(html)

    roster = javascript.split("function renderStudentRoster", 1)[1].split(
        "function fillSettingsForm", 1
    )[0]
    assert "mobileLookupWaiting" not in roster
    assert "filteredRosterStudents(students)" in roster
    assert "输入姓名、11 位学号或专业快速查找" in html
    assert 'class="qr-portal"' in html
    assert 'class="qr-portal__instruction"' in html
    assert "width: min(48vh, 100%, 560px)" in css
    assert ".completion-progress + .panel-title-row" in css
    assert "margin-top: 25px" in css


def test_roster_import_feedback_names_autocreated_majors_and_next_step() -> None:
    html, javascript, _ = _sources()

    assert "自动补充本场专业" in html
    assert "result.majors_created" in javascript
    assert "result.majors_reactivated" in javascript
    assert "新专业配额默认为 0" in javascript
    assert "请设置配额" in javascript
    assert 'adminState.structureFingerprint = ""' in javascript


def test_short_desktop_projection_compacts_qr_before_hiding_countdown_action() -> None:
    _, _, css = _sources()
    compact = css.split("@media (max-height: 820px) and (min-width: 1000px)", 1)[1].split(
        "@media (prefers-reduced-motion: reduce)", 1
    )[0]

    assert "width: min(38vh, 100%, 450px)" in compact
    assert ".qr-heading h2" in compact and "margin-bottom: 8px" in compact
    assert ".board-stage" in compact and "margin-top: 4px" in compact
    assert "min-height: 48px" in compact
