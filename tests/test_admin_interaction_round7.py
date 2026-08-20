from __future__ import annotations

import json
import sqlite3
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def _web_sources() -> tuple[str, str, str]:
    return (
        (ROOT / "web" / "admin.html").read_text(encoding="utf-8"),
        (ROOT / "web" / "admin.js").read_text(encoding="utf-8"),
        (ROOT / "web" / "app.css").read_text(encoding="utf-8"),
    )


def test_container_has_explicit_open_file_headroom_for_peak_login_bursts() -> None:
    compose = (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    env_example = (ROOT / ".env.example").read_text(encoding="utf-8")
    bootstrap = (ROOT / "deploy" / "bootstrap.sh").read_text(encoding="utf-8")
    deployment = (ROOT / "docs" / "deployment.md").read_text(encoding="utf-8")

    assert "ulimits:" in compose
    assert "nofile:" in compose
    assert "soft: ${APP_NOFILE_LIMIT:-8192}" in compose
    assert "hard: ${APP_NOFILE_LIMIT:-8192}" in compose
    assert "APP_NOFILE_LIMIT=8192" in env_example
    assert 'APP_NOFILE_LIMIT_VALUE="${APP_NOFILE_LIMIT:-8192}"' in bootstrap
    assert 'echo "APP_NOFILE_LIMIT=${APP_NOFILE_LIMIT_VALUE}"' in bootstrap
    assert "APP_NOFILE_LIMIT=8192" in deployment
    assert "SQLITE_WRITE_BATCH_SIZE=64" in env_example
    assert 'SQLITE_WRITE_BATCH_SIZE_VALUE="${SQLITE_WRITE_BATCH_SIZE:-64}"' in bootstrap
    assert 'echo "SQLITE_WRITE_BATCH_SIZE=${SQLITE_WRITE_BATCH_SIZE_VALUE}"' in bootstrap
    assert "SQLITE_WRITE_QUEUE_LIMIT=4096" in env_example
    assert "SQLITE_WRITE_BATCH_WINDOW_MS=4" in env_example


def test_origin_keep_alive_outlives_cloudflare_tunnel_idle_pool() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    assert '"--timeout-keep-alive", "95"' in dockerfile


def test_bootstrap_never_persists_the_plaintext_admin_password() -> None:
    script = (ROOT / "deploy" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "rm -f -- /root/teaching-choice-initial-password.txt" in script
    assert "> /root/teaching-choice-initial-password.txt" not in script
    assert "服务器不会保留该明文密码" in script
    assert "sed -i 's/^ADMIN_INITIAL_PASSWORD=.*/ADMIN_INITIAL_PASSWORD=/' .env" in script
    assert "trap bootstrap_exit EXIT" in script
    assert 'docker compose rm -sf app' in script
    assert "database_bootstrap_state()" in script
    assert "sqlite3 -readonly -batch -noheader" in script
    assert "PRAGMA user_version" in script
    assert "SELECT COUNT(*) FROM admin_users" in script
    assert 'CURRENT_SCHEMA_VERSION="$(awk' in script
    assert '"${schema_version}" == "${CURRENT_SCHEMA_VERSION}"' in script
    assert 'elif [[ "${DATABASE_BOOTSTRAP_STATE}" == "empty" ]]' in script
    assert 'elif [[ ! -s data/teaching-choice.db ]]' not in script
    assert 'docker compose up -d --force-recreate --wait --wait-timeout 180 app' in script
    assert 'sed -i "s|^ADMIN_INITIAL_PASSWORD=.*|ADMIN_INITIAL_PASSWORD=${ADMIN_PASSWORD_VALUE}|"' not in script
    assert "write_initial_password_without_argv()" in script
    handoff_index = script.index("首次登录密码")
    first_compose_index = script.index("docker compose up -d --build")
    assert handoff_index < first_compose_index


def test_bootstrap_treats_a_nonempty_wal_shell_as_uninitialized(tmp_path: Path) -> None:
    database_path = tmp_path / "wal-shell.db"
    with sqlite3.connect(database_path) as connection:
        connection.execute("PRAGMA journal_mode = WAL")

    assert database_path.stat().st_size > 0
    with sqlite3.connect(f"file:{database_path}?mode=ro", uri=True) as connection:
        schema_version = connection.execute("PRAGMA user_version").fetchone()[0]
        application_tables = connection.execute(
            "SELECT COUNT(*) FROM sqlite_master "
            "WHERE type = 'table' AND name NOT LIKE 'sqlite_%'"
        ).fetchone()[0]
    assert schema_version == 0
    assert application_tables == 0

    script = (ROOT / "deploy" / "bootstrap.sh").read_text(encoding="utf-8")
    assert '"${schema_version}" == "0" && "${application_tables}" == "0"' in script
    assert "printf 'empty\\n'" in script


def test_structure_editor_has_one_save_summary_and_large_matrix_tools() -> None:
    html, javascript, css = _web_sources()

    assert html.count('id="structure-save-summary"') == 1
    assert 'id="structure-lock-hint"' not in html
    assert 'id="structure-major-search"' in html
    assert 'id="structure-group-search"' in html
    assert 'id="quota-batch-form"' in html
    assert 'id="quota-batch-value"' in html
    assert 'id="quota-batch-count"' in html
    assert "当前筛选结果" in html
    assert "粘贴 Excel" in html
    assert "makeEntitySaveState" not in javascript
    assert "entity-save-state" not in css
    assert "renderStructureSaveSummary" in javascript
    assert 'adminEls.quotaMatrix.addEventListener("paste"' in javascript
    assert 'adminApi("/api/admin/quotas/batch"' in javascript
    assert '/assets/app.css?v=20260816-round8' in html
    assert '/assets/admin.js?v=20260816-round8' in html


def test_board_groups_and_waiting_students_use_continuous_loops() -> None:
    html, javascript, css = _web_sources()

    assert 'id="group-progress"' in html
    assert "boardPage(" not in javascript
    assert "groupProgressScrollPosition + elapsed" in javascript
    assert 'clone.dataset.groupProgressClone = "true"' in javascript
    assert 'adminEls.groupProgressPage.textContent = canLoop' in javascript
    assert ".group-progress" in css and "will-change: scroll-position" in css
    assert ".waiting-overview" in css and "grid-template-rows" in css
    assert ".waiting-feed-shell" in css and "minmax(0,1fr)" in css
    assert ".live-board:fullscreen .college-wordmark--board" in css
    assert "width: clamp(180px,11vw,225px)" in css
    assert "width: clamp(165px,19vw,205px)" in css
    assert "width: clamp(175px,13vw,205px)" in css
    assert "width: 118px" in css
    assert "width: 112px" in css


def test_board_qr_uses_one_compact_stage_and_reduced_motion_stays_reachable() -> None:
    html, javascript, css = _web_sources()
    portal = html.split('class="qr-portal"', 1)[1].split("</section>", 1)[0]
    stage = portal.split('id="board-stage"', 1)[1].split("</div>", 2)[0]
    reduced_motion = css.split("@media (prefers-reduced-motion: reduce)", 1)[1]

    assert 'class="board-stage__summary"' in stage
    assert 'class="status-dot"' in stage
    assert portal.count('class="status-dot"') == 1
    assert portal.index('id="board-stage"') < portal.index('class="qr-frame"')
    assert portal.index('class="qr-frame"') < portal.index('id="board-stage-detail"')
    assert portal.index('id="board-stage-detail"') < portal.index('id="board-start-countdown"')
    assert 'id="board-stage-detail" role="status" aria-live="polite" aria-atomic="true"' in portal
    assert 'class="qr-portal__action button button--primary button--wide"' in portal
    assert 'adminEls.boardStage.className = `qr-portal__status board-stage--${phase}`' in javascript
    assert javascript.count('adminEls.boardStart.className = "qr-portal__action button') == 3
    assert "qr-notice" not in html
    assert "qr-notice" not in css
    assert "boardNotice" not in javascript
    assert "boardLiveNote" not in javascript
    assert ".group-progress" in reduced_motion
    assert ".waiting-student-feed" in reduced_motion
    assert "overflow-y: auto" in reduced_motion
    assert "\n  .group-progress," in reduced_motion
    assert "\n  .waiting-student-feed," in reduced_motion
    assert ".live-board:fullscreen .group-progress" not in reduced_motion
    assert ".live-board.is-presentation .waiting-student-feed" not in reduced_motion


def test_overview_return_and_visibility_restore_restart_group_scrolling() -> None:
    _, javascript, _ = _web_sources()
    switch_view = javascript.split("function switchAdminView", 1)[1].split(
        'document.querySelectorAll(".admin-nav__item").forEach((button) => button.addEventListener', 1
    )[0]
    visibility = javascript.split('document.addEventListener("visibilitychange"', 1)[1]

    assert 'renderGroupProgress(adminState.dashboard?.groups || [], { force: true })' in switch_view
    assert 'adminState.groupProgressFingerprint = ""' in visibility


def test_entity_name_reschedule_keeps_dirty_group_capacity() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const scheduleSource = "function scheduleEntityRowSave" + source
  .split("function scheduleEntityRowSave", 2)[1]
  .split("function wireEntityAutosave", 1)[0];
const adminState = {entitySaveTimers: new Map()};
let scheduledCallback = null;
const cleared = [];
const persisted = [];
function entityRowSaveKey(row) { return `${row.dataset.entityKind}:${row.dataset.id}`; }
function clearTimeout(handle) { if (handle) cleared.push(handle); }
function setTimeout(callback, delay) { scheduledCallback = callback; return {delay}; }
function persistEntityRow(row, options) { persisted.push(options); }
eval(scheduleSource);

const row = {
  dataset: {entityKind: "group", id: "9", originalCapacity: "10"},
  _capacityInput: {value: "12"},
};
scheduleEntityRowSave(row, 650, {refreshAfter: true, includeCapacity: true});
scheduleEntityRowSave(row, 360);
scheduledCallback();

row._capacityInput.value = "10";
scheduleEntityRowSave(row, 360);
scheduledCallback();
console.log(JSON.stringify({persisted, cleared: cleared.length, dataset: row.dataset}));
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(execution.stdout)

    assert result["persisted"] == [
        {"refreshAfter": True, "includeCapacity": True},
        {"refreshAfter": False, "includeCapacity": False},
    ]
    assert result["cleared"] == 1
    assert "saveScheduledCapacity" not in result["dataset"]
    assert "saveScheduledRefresh" not in result["dataset"]


def test_equivalent_capacity_is_canonicalized_without_resave_loop() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const saveFunctions = "function entityRowSaveKey" + source
  .split("function entityRowSaveKey", 2)[1]
  .split("function wireEntityAutosave", 1)[0];
const scheduled = [];
const requests = [];
const adminState = {
  dashboard: {settings: {activity_id: 7}},
  entitySaveTimers: new Map(),
};
const adminEls = {
  majorEditor: {dataset: {activityId: "7"}},
  groupEditor: {dataset: {activityId: "7"}},
};
const row = {
  dataset: {
    entityKind: "group",
    id: "3",
    originalName: "第一教学组",
    originalCapacity: "10",
  },
  isConnected: true,
  _nameInput: {value: "第一教学组", setCustomValidity() {}, reportValidity() {}},
  _capacityInput: {value: "010", setCustomValidity() {}, reportValidity() {}},
  setAttribute() {},
  removeAttribute() {},
};
function clearTimeout() {}
function setTimeout(callback) { scheduled.push(callback); return callback; }
async function adminApi(path, options) {
  requests.push({path, payload: JSON.parse(options.body)});
  return {};
}
async function loadDashboard() {}
function renderLatestStructureAfterAutosave() {}
function showAdminToast() {}
function renderDashboard() {}
eval(saveFunctions);
(async () => {
  await persistEntityRow(row, {includeCapacity: true});
  process.stdout.write(JSON.stringify({
    requests,
    scheduled: scheduled.length,
    value: row._capacityInput.value,
    original: row.dataset.originalCapacity,
    saving: row.dataset.saving === "true",
  }));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(execution.stdout)

    assert result == {
        "requests": [
            {
                "path": "/api/admin/groups/3",
                "payload": {"total_capacity": 10},
            }
        ],
        "scheduled": 0,
        "value": "10",
        "original": "10",
        "saving": False,
    }


def test_equivalent_quota_clears_pending_without_request() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const quotaFunctions = "function quotaInputKey" + source
  .split("function quotaInputKey", 2)[1]
  .split("function quotaMatrixInputAt", 1)[0];
const requests = [];
const adminState = {quotaSaveTimers: new Map()};
const adminEls = {
  structureSaveSummary: null,
  quotaMatrix: {dataset: {activityId: "7"}},
};
const document = {querySelector() { return null; }};
const input = {
  dataset: {
    majorId: "2",
    groupId: "3",
    original: "10",
    pending: "true",
    saveState: "pending",
  },
  value: "010",
  title: "按回车或离开输入框保存配额",
  isConnected: true,
  setCustomValidity() {},
  reportValidity() {},
  setAttribute() {},
  removeAttribute() {},
};
function clearTimeout() {}
function setTimeout() { throw new Error("equivalent value must not be rescheduled"); }
async function adminApi(path, options) { requests.push({path, options}); return {}; }
async function loadDashboard() {}
function renderStructureSaveSummary() {}
function renderLatestStructureAfterAutosave() {}
function showAdminToast() {}
eval(quotaFunctions);
(async () => {
  await persistQuotaInput(input);
  process.stdout.write(JSON.stringify({
    requests: requests.length,
    value: input.value,
    original: input.dataset.original,
    pending: input.dataset.pending === "true",
    saveState: input.dataset.saveState,
    title: input.title,
    timers: adminState.quotaSaveTimers.size,
  }));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert json.loads(execution.stdout) == {
        "requests": 0,
        "value": "10",
        "original": "10",
        "pending": False,
        "saveState": "saved",
        "title": "",
        "timers": 0,
    }


def test_empty_numeric_autosaves_never_submit_zero() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const entityFunctions = "function entityRowSaveKey" + source
  .split("function entityRowSaveKey", 2)[1]
  .split("function wireEntityAutosave", 1)[0];
const quotaFunctions = "function quotaInputKey" + source
  .split("function quotaInputKey", 2)[1]
  .split("function quotaMatrixInputAt", 1)[0];
const requests = [];
const adminState = {
  dashboard: {settings: {activity_id: 7}},
  entitySaveTimers: new Map(),
  quotaSaveTimers: new Map(),
};
const adminEls = {
  structureSaveSummary: null,
  majorEditor: {dataset: {activityId: "7"}},
  groupEditor: {dataset: {activityId: "7"}},
  quotaMatrix: {dataset: {activityId: "7"}},
};
const document = {querySelector() { return null; }};
let entityValidity = "";
let quotaValidity = "";
const row = {
  dataset: {entityKind: "group", id: "3", originalName: "第一教学组", originalCapacity: "10"},
  isConnected: true,
  _nameInput: {value: "第一教学组", setCustomValidity() {}, reportValidity() {}},
  _capacityInput: {
    value: "",
    setCustomValidity(value) { entityValidity = value; },
    reportValidity() {},
  },
  setAttribute() {},
  removeAttribute() {},
};
const quotaInput = {
  dataset: {majorId: "2", groupId: "3", original: "10", pending: "true"},
  value: "",
  title: "",
  isConnected: true,
  setCustomValidity(value) { quotaValidity = value; },
  reportValidity() {},
  setAttribute() {},
  removeAttribute() {},
};
function clearTimeout() {}
function setTimeout() { throw new Error("empty value must not be rescheduled"); }
async function adminApi(path, options) { requests.push({path, options}); return {}; }
async function loadDashboard() {}
function renderDashboard() {}
function renderStructureSaveSummary() {}
function renderLatestStructureAfterAutosave() {}
function showAdminToast() {}
eval(entityFunctions + quotaFunctions);
(async () => {
  await persistEntityRow(row, {includeCapacity: true});
  await persistQuotaInput(quotaInput);
  process.stdout.write(JSON.stringify({
    requests: requests.length,
    entityValidity,
    quotaValidity,
    entityValue: row._capacityInput.value,
    entityOriginal: row.dataset.originalCapacity,
    quotaValue: quotaInput.value,
    quotaOriginal: quotaInput.dataset.original,
  }));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    result = json.loads(execution.stdout)
    assert result["requests"] == 0
    assert "不能为空" in result["entityValidity"]
    assert "不能为空" in result["quotaValidity"]
    assert result["entityValue"] == ""
    assert result["entityOriginal"] == "10"
    assert result["quotaValue"] == ""
    assert result["quotaOriginal"] == "10"


def test_quota_clipboard_preserves_edge_cells_and_rejects_empty_values() -> None:
    _, javascript, _ = _web_sources()
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const parserSource = "function quotaClipboardRows" + source
  .split("function quotaClipboardRows", 2)[1]
  .split('adminEls.quotaMatrix.addEventListener("paste"', 1)[0];
eval(parserSource);
console.log(JSON.stringify({
  leading: quotaClipboardRows("\t5\r\n"),
  trailing: quotaClipboardRows("5\t\r\n"),
  trailingEmptyRow: quotaClipboardRows("5\r\n\r\n"),
  matrix: quotaClipboardRows("1\t2\r\n3\t4\r\n"),
}));
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    parsed = json.loads(execution.stdout)

    assert parsed["leading"] == [["", "5"]]
    assert parsed["trailing"] == [["5", ""]]
    assert parsed["trailingEmptyRow"] == [["5"], [""]]
    assert parsed["matrix"] == [["1", "2"], ["3", "4"]]
    paste_handler = javascript.split('adminEls.quotaMatrix.addEventListener("paste"', 1)[1].split(
        'adminEls.quotaBatchForm.addEventListener("submit"', 1
    )[0]
    assert "clipboard.trim()" not in paste_handler
    assert "!normalizedValue" in paste_handler
    assert "包含空单元格" in paste_handler


def test_countdown_response_starts_the_overlay_before_dashboard_refresh() -> None:
    _, javascript, _ = _web_sources()
    action = javascript.split("async function handleSelectionPhaseAction", 1)[1].split(
        "adminEls.boardStart.addEventListener", 1
    )[0]

    response_index = action.index('adminApi("/api/admin/countdown"')
    immediate_render_index = action.index("renderDashboard(countdownDashboard)")
    refresh_index = action.index("await loadDashboard({ afterMutation: true })")
    assert response_index < immediate_render_index < refresh_index


def test_countdown_forces_every_admin_into_the_presentation_surface() -> None:
    _, javascript, _ = _web_sources()
    action = javascript.split("async function handleSelectionPhaseAction", 1)[1].split(
        "adminEls.boardStart.addEventListener", 1
    )[0]

    assert "enterCountdownPresentation()" in action
    assert "function enforceCountdownPresentation" in javascript
    assert "enforceCountdownPresentation(phase)" in javascript
    assert javascript.index("enforceCountdownPresentation(phase)") < javascript.index(
        "renderBoardStage(data, phase, presence)"
    )


def test_every_non_overview_admin_view_polls_the_countdown_phase() -> None:
    _, javascript, _ = _web_sources()
    snapshot_loader = javascript.split("async function loadDashboardStatusSnapshot", 1)[1].split(
        "function startAdminPolling", 1
    )[0]
    polling = javascript.split("function startAdminPolling", 1)[1].split(
        "function structureEditorAutosaveBusy", 1
    )[0]

    assert 'adminState.currentView === "overview"' in snapshot_loader
    assert 'adminState.currentView !== "students"' not in snapshot_loader
    assert 'if (adminState.currentView === "overview") loadDashboard({ quiet: true });' in polling
    assert 'else loadDashboardStatusSnapshot({ quiet: true });' in polling


def test_unified_structure_status_settles_after_entity_request_finishes() -> None:
    _, javascript, _ = _web_sources()
    persist = javascript.split("async function persistEntityRow", 1)[1].split(
        "function scheduleEntityRowSave", 1
    )[0]
    finally_block = persist.split("} finally {", 1)[1]

    clear_index = finally_block.index("delete row.dataset.saving")
    notify_index = finally_block.index("notifyEntityStructureSaveSummary()")
    render_index = finally_block.index("renderLatestStructureAfterAutosave")
    assert clear_index < notify_index < render_index


def test_quota_batch_is_atomic_and_checks_final_group_totals(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    dashboard = client.get("/api/admin/dashboard").json()
    group = dashboard["groups"][0]
    majors = dashboard["majors"][:2]
    cells = [
        next(
            quota
            for quota in dashboard["quotas"]
            if quota["major_id"] == major["id"] and quota["group_id"] == group["id"]
        )
        for major in majors
    ]

    saved = client.put(
        "/api/admin/quotas/batch",
        headers=admin_headers,
        json={
            "quotas": [
                {"major_id": majors[0]["id"], "group_id": group["id"], "capacity": 4},
                {"major_id": majors[1]["id"], "group_id": group["id"], "capacity": 5},
            ]
        },
    )
    assert saved.status_code == 200, saved.text
    assert saved.json() == {"ok": True, "updated_count": 2}

    after_save = client.get("/api/admin/dashboard").json()
    saved_map = {
        (quota["major_id"], quota["group_id"]): quota["capacity"]
        for quota in after_save["quotas"]
    }
    assert saved_map[(majors[0]["id"], group["id"])] == 4
    assert saved_map[(majors[1]["id"], group["id"])] == 5

    rejected = client.put(
        "/api/admin/quotas/batch",
        headers=admin_headers,
        json={
            "quotas": [
                {
                    "major_id": majors[0]["id"],
                    "group_id": group["id"],
                    "capacity": group["total_capacity"],
                },
                {
                    "major_id": majors[1]["id"],
                    "group_id": group["id"],
                    "capacity": group["total_capacity"],
                },
            ]
        },
    )
    assert rejected.status_code == 409
    assert "配额合计" in rejected.json()["detail"]

    after_reject = client.get("/api/admin/dashboard").json()
    rejected_map = {
        (quota["major_id"], quota["group_id"]): quota["capacity"]
        for quota in after_reject["quotas"]
    }
    assert rejected_map[(majors[0]["id"], group["id"])] == 4
    assert rejected_map[(majors[1]["id"], group["id"])] == 5
    assert cells[0]["capacity"] != 4 or cells[1]["capacity"] != 5


def test_quota_batch_applies_decreases_before_increases(
    client: TestClient,
    admin_headers: dict[str, str],
) -> None:
    dashboard = client.get("/api/admin/dashboard").json()
    group = dashboard["groups"][0]
    group_quotas = [
        quota for quota in dashboard["quotas"] if quota["group_id"] == group["id"]
    ]
    donor = next(quota for quota in group_quotas if quota["capacity"] > 0)
    recipient = next(quota for quota in group_quotas if quota["major_id"] != donor["major_id"])
    current_total = sum(quota["capacity"] for quota in group_quotas)
    slack = group["total_capacity"] - current_total

    # The increase is deliberately listed first. The final state is valid,
    # but applying it first would temporarily exceed the group capacity.
    response = client.put(
        "/api/admin/quotas/batch",
        headers=admin_headers,
        json={
            "quotas": [
                {
                    "major_id": recipient["major_id"],
                    "group_id": group["id"],
                    "capacity": recipient["capacity"] + slack + 1,
                },
                {
                    "major_id": donor["major_id"],
                    "group_id": group["id"],
                    "capacity": donor["capacity"] - 1,
                },
            ]
        },
    )
    assert response.status_code == 200, response.text

    saved = client.get("/api/admin/dashboard").json()
    saved_group_quotas = [
        quota for quota in saved["quotas"] if quota["group_id"] == group["id"]
    ]
    saved_map = {quota["major_id"]: quota["capacity"] for quota in saved_group_quotas}
    assert saved_map[recipient["major_id"]] == recipient["capacity"] + slack + 1
    assert saved_map[donor["major_id"]] == donor["capacity"] - 1
    assert sum(saved_map.values()) == group["total_capacity"]


def test_quota_batch_failure_preserves_pending_manual_edits() -> None:
    script = r"""
const fs = require("fs");
const source = fs.readFileSync(process.argv[1], "utf8");
const applySource = "async function applyQuotaBatch" + source
  .split("async function applyQuotaBatch", 2)[1]
  .split('adminEls.quotaMatrix.addEventListener("input"', 1)[0];

const adminState = {quotaSaveTimers: new Map()};
const adminEls = {quotaMatrix: {dataset: {activityId: "7"}}};
const scheduled = [];
const renders = [];
const toasts = [];
let dashboardLoads = 0;
let adminApi;
function quotaInputKey(input) { return `${input.dataset.majorId}:${input.dataset.groupId}`; }
function clearTimeout() {}
function notifyQuotaStructureSaveSummary() {}
function scheduleQuotaSave(input, delay) { scheduled.push({value: input.value, delay}); }
function showAdminToast(message, kind) { toasts.push({message, kind}); }
async function loadDashboard() { dashboardLoads += 1; }
function renderLatestStructureAfterAutosave(options = {}) { renders.push(options); }
function makeInput(value = "7") {
  return {
    value,
    isConnected: true,
    dataset: {majorId: "1", groupId: "2", original: "5", pending: "true"},
    setAttribute() {},
    removeAttribute() {},
  };
}
eval(applySource);

(async () => {
  const retryInput = makeInput();
  adminApi = async () => { throw Object.assign(new Error("temporary"), {status: 500}); };
  await applyQuotaBatch(new Map([[retryInput, 9]]), "批量配额");
  const retry = {
    value: retryInput.value,
    original: retryInput.dataset.original,
    pending: retryInput.dataset.pending,
    saveState: retryInput.dataset.saveState,
    scheduled: [...scheduled],
    dashboardLoads,
  };

  scheduled.length = 0;
  dashboardLoads = 0;
  const casInput = makeInput();
  adminApi = async () => {
    throw Object.assign(new Error("当前活动已经变化，请刷新后重试"), {status: 409});
  };
  await applyQuotaBatch(new Map([[casInput, 9]]), "批量配额");
  const cas = {
    value: casInput.value,
    original: casInput.dataset.original,
    pending: casInput.dataset.pending || null,
    scheduled: [...scheduled],
    dashboardLoads,
    forceStructure: renders.at(-1)?.forceStructure === true,
  };

  scheduled.length = 0;
  dashboardLoads = 0;
  const duringRequestInput = makeInput("5");
  let resolveRequest;
  adminApi = () => new Promise((resolve) => { resolveRequest = resolve; });
  const request = applyQuotaBatch(new Map([[duringRequestInput, 9]]), "批量配额");
  await Promise.resolve();
  duringRequestInput.value = "11";
  resolveRequest({ok: true});
  await request;
  const duringRequest = {
    value: duringRequestInput.value,
    original: duringRequestInput.dataset.original,
    pending: duringRequestInput.dataset.pending,
    scheduled: [...scheduled],
  };
  console.log(JSON.stringify({retry, cas, duringRequest}));
})().catch((error) => { console.error(error); process.exit(1); });
"""
    execution = subprocess.run(
        ["node", "-e", script, str(ROOT / "web" / "admin.js")],
        check=True,
        capture_output=True,
        text=True,
    )
    result = json.loads(execution.stdout)

    assert result["retry"] == {
        "value": "7",
        "original": "5",
        "pending": "true",
        "saveState": "pending",
        "scheduled": [{"value": "7", "delay": 0}],
        "dashboardLoads": 0,
    }
    assert result["cas"] == {
        "value": "5",
        "original": "5",
        "pending": None,
        "scheduled": [],
        "dashboardLoads": 1,
        "forceStructure": True,
    }
    assert result["duringRequest"] == {
        "value": "11",
        "original": "9",
        "pending": "true",
        "scheduled": [{"value": "11", "delay": 0}],
    }
