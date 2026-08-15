from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient


ROOT = Path(__file__).resolve().parents[1]


def _web_sources() -> tuple[str, str, str]:
    return (
        (ROOT / "web" / "admin.html").read_text(encoding="utf-8"),
        (ROOT / "web" / "admin.js").read_text(encoding="utf-8"),
        (ROOT / "web" / "app.css").read_text(encoding="utf-8"),
    )


def test_bootstrap_never_persists_the_plaintext_admin_password() -> None:
    script = (ROOT / "deploy" / "bootstrap.sh").read_text(encoding="utf-8")

    assert "rm -f -- /root/teaching-choice-initial-password.txt" in script
    assert "> /root/teaching-choice-initial-password.txt" not in script
    assert "服务器不会保留该明文密码" in script
    assert "sed -i 's/^ADMIN_INITIAL_PASSWORD=.*/ADMIN_INITIAL_PASSWORD=/' .env" in script


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
    assert '/assets/app.css?v=20260816-round7' in html
    assert '/assets/admin.js?v=20260816-round7' in html


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
    assert "width: clamp(210px,14vw,265px)" in css
    assert "width: clamp(205px,16vw,235px)" in css


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
