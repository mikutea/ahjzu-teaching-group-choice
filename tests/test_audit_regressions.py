from __future__ import annotations

import asyncio
import csv
import io
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from time import sleep

import pytest
from fastapi.testclient import TestClient

import server.main as main_module
from server.config import Config
from server.database import SCHEMA, connect, initialize_database
from server.maintenance import check_database

from .conftest import fictional_activation_code, fictional_document_number


def import_students(
    client: TestClient,
    headers: dict[str, str],
    csv_text: str,
    *,
    mode: str = "merge",
):
    return client.post(
        "/api/admin/students/import",
        headers=headers,
        params={"mode": mode},
        files={"files": ("students.csv", csv_text.encode("utf-8"), "text/csv")},
    )


def login_student(client: TestClient, *, student_no: str, name: str):
    return client.post(
        "/api/student/login",
        json={
            "student_no": student_no,
            "name": name,
            "activation_code": fictional_activation_code(student_no),
        },
    )


def test_sixty_students_behind_one_ip_can_all_log_in(
    app, client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    rows = ["student_no,name,major,document_number"]
    for index in range(60):
        student_no = f"2031000{index:04d}"
        rows.append(
            f"{student_no},同网学生,{major_name},{fictional_document_number(student_no)}"
        )
    imported = import_students(client, admin_headers, "\n".join(rows) + "\n")
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == 60

    students = [TestClient(app, client=("192.0.2.10", 40000 + index)) for index in range(60)]
    barrier = threading.Barrier(len(students))

    def login(index: int):
        barrier.wait(timeout=15)
        return login_student(
            students[index],
            student_no=f"2031000{index:04d}",
            name="同网学生",
        )

    try:
        with ThreadPoolExecutor(max_workers=len(students)) as pool:
            responses = list(pool.map(login, range(len(students))))
    finally:
        for student in students:
            student.close()

    failures = [(response.status_code, response.text) for response in responses if response.status_code != 200]
    assert not failures


def test_reimport_with_same_document_keeps_existing_credential(
    app, client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    document_number = fictional_document_number("20320000002")
    first = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n"
        f"20320000002,批量轮换,{major_name},{document_number}\n",
    )
    assert first.status_code == 200, first.text

    student = TestClient(app)
    try:
        assert login_student(
            student,
            student_no="20320000002",
            name="批量轮换",
        ).status_code == 200

        rotated = import_students(
            client,
            admin_headers,
            "student_no,name,major,document_number\n"
            f"20320000002,批量轮换,{major_name},{document_number}\n",
            mode="merge",
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["rotated"] == 0
        assert "credentials" not in rotated.json()
        assert '"activation_code":' not in rotated.text
        assert student.get("/api/student/me").status_code == 200
    finally:
        student.close()


def test_sync_import_deactivates_omitted_student_and_invalidates_session(
    app, client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    retained_document = fictional_document_number("20320000003")
    omitted_document = fictional_document_number("20320000004")
    initial = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n"
        f"20320000003,保留学生,{major_name},{retained_document}\n"
        f"20320000004,遗漏学生,{major_name},{omitted_document}\n",
    )
    assert initial.status_code == 200, initial.text

    omitted = TestClient(app)
    try:
        assert login_student(
            omitted,
            student_no="20320000004",
            name="遗漏学生",
        ).status_code == 200

        synchronized = import_students(
            client,
            admin_headers,
            "student_no,name,major,document_number\n"
            f"20320000003,保留学生,{major_name},{retained_document}\n",
            mode="sync",
        )
        assert synchronized.status_code == 200, synchronized.text
        assert omitted.get("/api/student/me").status_code == 401
        assert login_student(
            omitted,
            student_no="20320000004",
            name="遗漏学生",
        ).status_code == 401

        students = {
            row["student_no"]: row
            for row in client.get("/api/admin/dashboard").json()["students"]
        }
        assert students["20320000003"]["active"] == 1
        assert students["20320000004"]["active"] == 0
    finally:
        omitted.close()


def test_roster_rejects_formula_like_student_names_atomically(
    client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    group_id = dashboard["groups"][0]["id"]
    formula_name = "=HYPERLINK(\"x\",\"y\")"
    rows = [
        ["student_no", "name", "major", "document_number"],
        [
            "20330000001",
            formula_name,
            major_name,
            fictional_document_number("20330000001"),
        ],
        [
            "20330000002",
            "@SUM(1,1)",
            major_name,
            fictional_document_number("20330000002"),
        ],
    ]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    imported = import_students(client, admin_headers, buffer.getvalue())
    assert imported.status_code == 400, imported.text
    assert "姓名只能包含中文或英文字母" in imported.json()["detail"]
    assert client.get("/api/admin/dashboard").json()["students"] == []


def test_opening_is_blocked_until_readiness_passes(
    client: TestClient, admin_headers: dict[str, str]
):
    empty = client.get("/api/admin/dashboard").json()
    assert empty["students"] == []
    assert empty["readiness"]["ready"] is False
    assert empty["readiness"]["blockers"]
    assert isinstance(empty["readiness"]["warnings"], list)

    blocked = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "open"},
    )
    assert blocked.status_code == 409
    assert client.get("/api/admin/dashboard").json()["settings"]["status"] == "closed"

    major_name = empty["majors"][0]["name"]
    imported = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n"
        f"20340000001,就绪学生,{major_name},"
        f"{fictional_document_number('20340000001')}\n",
    )
    assert imported.status_code == 200, imported.text
    ready = client.get("/api/admin/dashboard").json()["readiness"]
    assert ready["ready"] is True, ready
    assert ready["blockers"] == []

    opened = client.post("/api/admin/countdown", headers=admin_headers)
    assert opened.status_code == 200, opened.text


def test_dashboard_exposes_students_for_sync_review(
    client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    imported = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n"
        f"20350000001,名单甲,{major_name},"
        f"{fictional_document_number('20350000001')}\n"
        f"20350000002,名单乙,{major_name},"
        f"{fictional_document_number('20350000002')}\n",
    )
    assert imported.status_code == 200, imported.text

    refreshed = client.get("/api/admin/dashboard").json()
    by_number = {student["student_no"]: student for student in refreshed["students"]}
    assert {"20350000001", "20350000002"} <= by_number.keys()
    for student_no in ("20350000001", "20350000002"):
        assert {
            "id",
            "student_no",
            "name",
            "major_name",
            "active",
        } <= by_number[student_no].keys()


def test_dashboard_remains_one_snapshot_while_activity_changes(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    before = client.get("/api/admin/dashboard").json()
    old_activity_id = before["settings"]["activity_id"]
    old_major_ids = [major["id"] for major in before["majors"]]
    old_group_ids = [group["id"] for group in before["groups"]]

    armed = threading.Event()
    paused = threading.Event()
    release = threading.Event()
    claim = threading.Lock()
    original_connect = main_module.connect

    class CursorProxy:
        def __init__(self, cursor, intercept: bool):
            self._cursor = cursor
            self._intercept = intercept

        def fetchone(self):
            row = self._cursor.fetchone()
            if self._intercept and armed.is_set():
                with claim:
                    should_pause = armed.is_set()
                    if should_pause:
                        armed.clear()
                if should_pause:
                    paused.set()
                    if not release.wait(timeout=10):
                        raise RuntimeError("dashboard snapshot test timed out")
            return row

        def __iter__(self):
            return iter(self._cursor)

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, *args, **kwargs):
            cursor = self._connection.execute(sql, *args, **kwargs)
            intercept = "SELECT s.*, a.id AS activity_id" in sql
            return CursorProxy(cursor, intercept) if intercept else cursor

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def controlled_connect(path):
        return ConnectionProxy(original_connect(path))

    rollover_client = TestClient(app)
    rollover_client.cookies.update(client.cookies)
    monkeypatch.setattr(main_module, "connect", controlled_connect)
    armed.set()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            dashboard_future = pool.submit(client.get, "/api/admin/dashboard")
            assert paused.wait(timeout=10)
            rollover_future = pool.submit(
                rollover_client.post,
                "/api/admin/activities",
                headers=admin_headers,
                json={
                    "title": "快照竞态下一场",
                    "code": "snapshot-race-next",
                    "copy_structure": False,
                    "previous_activity_id": old_activity_id,
                },
            )
            sleep(0.2)
            release.set()
            raced_dashboard = dashboard_future.result(timeout=10)
            rollover = rollover_future.result(timeout=10)
    finally:
        release.set()
        rollover_client.close()

    assert raced_dashboard.status_code == 200, raced_dashboard.text
    assert rollover.status_code == 200, rollover.text
    raced = raced_dashboard.json()
    assert raced["settings"]["activity_id"] == old_activity_id
    assert [major["id"] for major in raced["majors"]] == old_major_ids
    assert [group["id"] for group in raced["groups"]] == old_group_ids
    assert [activity["id"] for activity in raced["activities"] if activity["current"]] == [
        old_activity_id
    ]

    after = client.get("/api/admin/dashboard").json()
    assert after["settings"]["activity_id"] == rollover.json()["activity_id"]
    assert after["majors"] == []
    assert after["groups"] == []


def test_import_rejects_unrecognized_document_number_atomically(
    client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    rejected = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "files": (
                "students.csv",
                (
                    "student_no,name,major,document_number\n"
                    f"20360000001,无效证件学生,{major_name},ABC\n"
                ).encode("utf-8"),
                "text/csv",
            )
        },
    )
    assert rejected.status_code == 400
    assert "证件号格式无法识别" in rejected.json()["detail"]
    assert client.get("/api/admin/dashboard").json()["students"] == []


def test_import_body_limit_runs_before_multipart_authentication(client: TestClient):
    oversized = client.post(
        "/api/admin/students/import",
        files={"files": ("oversized.csv", b"x" * 1_300_000, "text/csv")},
    )
    assert oversized.status_code == 413
    assert "1.25 MB" in oversized.json()["detail"]


def test_import_body_limit_returns_413_for_chunked_body_without_content_length():
    downstream_called = False
    sent: list[dict] = []
    messages = [
        {"type": "http.request", "body": b"x" * 700_000, "more_body": True},
        {"type": "http.request", "body": b"y" * 600_001, "more_body": False},
    ]

    async def downstream(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True

    async def receive():
        return messages.pop(0)

    async def send(message):
        sent.append(message)

    middleware = main_module.ImportBodyLimitMiddleware(downstream)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/admin/students/import",
                "headers": [],
            },
            receive,
            send,
        )
    )
    assert downstream_called is False
    assert sent[0]["status"] == 413


def test_import_body_gate_bounds_concurrent_slow_uploads(monkeypatch):
    downstream_called = False
    release = asyncio.Event()
    started = 0
    started_lock = asyncio.Lock()

    async def downstream(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True

    async def slow_receive():
        nonlocal started
        async with started_lock:
            started += 1
        await release.wait()
        return {"type": "http.disconnect"}

    def request_scope():
        return {
            "type": "http",
            "method": "POST",
            "path": "/api/admin/students/import",
            "headers": [],
        }

    async def scenario():
        middleware = main_module.ImportBodyLimitMiddleware(downstream)
        captured: list[list[dict]] = [[] for _ in range(5)]

        async def run(index):
            async def send(message):
                captured[index].append(message)

            await middleware(request_scope(), slow_receive, send)

        holders = [asyncio.create_task(run(index)) for index in range(4)]
        for _ in range(100):
            if started == 4:
                break
            await asyncio.sleep(0.001)
        assert started == 4
        fifth = asyncio.create_task(run(4))
        await asyncio.wait_for(fifth, timeout=1)
        assert captured[4][0]["status"] == 429
        release.set()
        await asyncio.gather(*holders)
        return captured

    captured = asyncio.run(scenario())
    assert downstream_called is False
    assert captured[4][0]["status"] == 429


def test_import_body_read_has_total_timeout(monkeypatch):
    downstream_called = False
    sent: list[dict] = []
    never = asyncio.Event()

    async def downstream(scope, receive, send):
        nonlocal downstream_called
        downstream_called = True

    async def receive():
        await never.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        sent.append(message)

    monkeypatch.setattr(main_module, "IMPORT_BODY_TIMEOUT_SECONDS", 0.01)
    middleware = main_module.ImportBodyLimitMiddleware(downstream)
    asyncio.run(
        middleware(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/admin/students/import",
                "headers": [],
            },
            receive,
            send,
        )
    )
    assert downstream_called is False
    assert sent[0]["status"] == 408


def test_archive_download_and_database_check_fail_closed_after_tamper(
    client: TestClient, admin_headers: dict[str, str], app_config
):
    activity_id = int(admin_headers["X-Activity-ID"])
    created = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "归档校验下一场",
            "code": "archive-check-next",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert created.status_code == 200, created.text

    connection = sqlite3.connect(app_config.database_path)
    try:
        connection.execute(
            "UPDATE activities SET snapshot_json = snapshot_json || ' ' WHERE id = ?",
            (activity_id,),
        )
        connection.commit()
    finally:
        connection.close()

    download = client.get(f"/api/admin/activities/{activity_id}/archive.json")
    assert download.status_code == 500
    assert "归档校验失败" in download.json()["detail"]
    with pytest.raises(RuntimeError, match="SHA-256"):
        check_database(app_config.database_path, app_config.app_secret)


def test_database_check_rejects_archive_summary_tamper(
    client: TestClient, admin_headers: dict[str, str], app_config
):
    activity_id = int(admin_headers["X-Activity-ID"])
    created = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "汇总校验下一场",
            "code": "summary-check-next",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert created.status_code == 200, created.text
    connection = sqlite3.connect(app_config.database_path)
    try:
        connection.execute(
            """
            UPDATE activities
            SET summary_json = '{"students":999,"selected":0,"unselected":999}'
            WHERE id = ?
            """,
            (activity_id,),
        )
        connection.commit()
    finally:
        connection.close()
    with pytest.raises(RuntimeError, match="汇总与快照不一致"):
        check_database(app_config.database_path, app_config.app_secret)
    assert client.get(f"/api/admin/activities/{activity_id}/archive.json").status_code == 500


@pytest.mark.parametrize("tampered_value", [None, "2030-01-02T03:04:05+00:00"])
def test_archive_time_is_bound_to_snapshot(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
    tampered_value: str | None,
):
    activity_id = int(admin_headers["X-Activity-ID"])
    created = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "归档时间校验下一场",
            "code": "archive-time-check-next",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert created.status_code == 200, created.text
    connection = sqlite3.connect(app_config.database_path)
    try:
        connection.execute(
            "UPDATE activities SET archived_at = ? WHERE id = ?",
            (tampered_value, activity_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="缺少快照|归档时间"):
        check_database(app_config.database_path, app_config.app_secret)
    assert client.get(f"/api/admin/activities/{activity_id}/archive.json").status_code == 500


def test_current_exports_require_matching_activity_version(
    client: TestClient, admin_headers: dict[str, str]
):
    activity_id = int(admin_headers["X-Activity-ID"])
    assert client.get("/api/admin/export/selections.xlsx").status_code == 422
    stale = client.get(
        "/api/admin/export/selections.xlsx", params={"activity_id": activity_id + 999}
    )
    assert stale.status_code == 409


def test_https_configuration_emits_hsts(app_config):
    secure_config = replace(
        app_config,
        database_path=app_config.database_path.with_name("secure.db"),
        cookie_secure=True,
        public_base_url="https://class.example.invalid",
    )
    with TestClient(main_module.create_app(secure_config)) as secure_client:
        response = secure_client.get("/api/health")
    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == "max-age=31536000"


def test_environment_loader_rejects_missing_secret(monkeypatch, tmp_path):
    monkeypatch.setenv("ENVIRONMENT", "development")
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.delenv("APP_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="APP_SECRET"):
        Config.from_env()


def test_profile_change_invalidates_existing_student_session(
    app, client: TestClient, admin_headers: dict[str, str]
):
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    document_number = fictional_document_number("20400000001")
    imported = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n20400000001,原姓名,"
        f"{major_name},{document_number}\n",
    )
    assert imported.status_code == 200, imported.text
    student = TestClient(app)
    try:
        assert login_student(
            student, student_no="20400000001", name="原姓名"
        ).status_code == 200
        changed = import_students(
            client,
            admin_headers,
            "student_no,name,major,document_number\n"
            f"20400000001,新姓名,{major_name},{document_number}\n",
        )
        assert changed.status_code == 200, changed.text
        assert "credentials" not in changed.json()
        assert '"activation_code":' not in changed.text
        assert student.get("/api/student/me").status_code == 401
        assert login_student(
            student, student_no="20400000001", name="新姓名"
        ).status_code == 200
    finally:
        student.close()


def test_database_check_binds_archive_snapshot_to_outer_activity(
    client: TestClient, admin_headers: dict[str, str], app_config
):
    first_activity_id = int(admin_headers["X-Activity-ID"])
    second = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "第二场归档归属测试",
            "code": "archive-owner-second",
            "copy_structure": True,
            "previous_activity_id": first_activity_id,
        },
    )
    assert second.status_code == 200, second.text
    second_activity_id = int(second.json()["activity_id"])
    second_headers = {**admin_headers, "X-Activity-ID": str(second_activity_id)}
    third = client.post(
        "/api/admin/activities",
        headers=second_headers,
        json={
            "title": "第三场归档归属测试",
            "code": "archive-owner-third",
            "copy_structure": True,
            "previous_activity_id": second_activity_id,
        },
    )
    assert third.status_code == 200, third.text

    connection = sqlite3.connect(app_config.database_path)
    try:
        first_archive = connection.execute(
            "SELECT summary_json, snapshot_json, snapshot_sha256 FROM activities WHERE id = ?",
            (first_activity_id,),
        ).fetchone()
        second_archive = connection.execute(
            "SELECT summary_json, snapshot_json, snapshot_sha256 FROM activities WHERE id = ?",
            (second_activity_id,),
        ).fetchone()
        connection.execute(
            """
            UPDATE activities
            SET summary_json = ?, snapshot_json = ?, snapshot_sha256 = ?
            WHERE id = ?
            """,
            (*second_archive, first_activity_id),
        )
        connection.execute(
            """
            UPDATE activities
            SET summary_json = ?, snapshot_json = ?, snapshot_sha256 = ?
            WHERE id = ?
            """,
            (*first_archive, second_activity_id),
        )
        connection.commit()
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="快照归属"):
        check_database(app_config.database_path, app_config.app_secret)
    download = client.get(f"/api/admin/activities/{first_activity_id}/archive.json")
    assert download.status_code == 500


@pytest.mark.parametrize(
    ("path", "payload"),
    [
        ("/api/admin/settings", {"activity_title": "   "}),
        ("/api/admin/majors", {"name": "   "}),
        ("/api/admin/groups", {"name": "   ", "total_capacity": 10}),
    ],
)
def test_activity_names_reject_whitespace_only_values(
    client: TestClient,
    admin_headers: dict[str, str],
    path: str,
    payload: dict[str, object],
):
    method = "PATCH" if path.endswith("settings") else "POST"
    response = client.request(method, path, headers=admin_headers, json=payload)
    assert response.status_code == 422


def test_activity_title_rejects_whitespace_only_value(
    client: TestClient, admin_headers: dict[str, str]
):
    activity_id = int(admin_headers["X-Activity-ID"])
    response = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "   ",
            "code": "blank-title",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert response.status_code == 422


def test_archived_summary_keeps_active_student_semantics_after_sync(
    client: TestClient, admin_headers: dict[str, str]
):
    activity_id = int(admin_headers["X-Activity-ID"])
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    initial = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n"
        f"20410000001,保留学生,{major_name},"
        f"{fictional_document_number('20410000001')}\n"
        f"20410000002,停用学生,{major_name},"
        f"{fictional_document_number('20410000002')}\n",
    )
    assert initial.status_code == 200, initial.text
    synchronized = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n"
        f"20410000001,保留学生,{major_name},"
        f"{fictional_document_number('20410000001')}\n",
        mode="sync",
    )
    assert synchronized.status_code == 200, synchronized.text
    before = client.get("/api/admin/dashboard").json()["totals"]
    assert before == {"students": 1, "selected": 0, "unselected": 1}
    rolled = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "同步口径下一场",
            "code": "sync-summary-next",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert rolled.status_code == 200, rolled.text
    activities = client.get("/api/admin/activities").json()
    archived = next(row for row in activities if row["id"] == activity_id)
    assert archived["summary"] == before


def test_invalid_persisted_quota_total_blocks_check_and_opening(
    client: TestClient, admin_headers: dict[str, str], app_config
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    imported = import_students(
        client,
        admin_headers,
        "student_no,name,major,document_number\n"
        f"20420000001,异常配额学生,{major_name},"
        f"{fictional_document_number('20420000001')}\n",
    )
    assert imported.status_code == 200, imported.text
    quota = dashboard["quotas"][0]

    connection = sqlite3.connect(app_config.database_path)
    try:
        connection.execute("DROP TRIGGER quota_group_capacity_guard_update")
        connection.execute(
            "UPDATE quotas SET capacity = 999 WHERE major_id = ? AND group_id = ?",
            (quota["major_id"], quota["group_id"]),
        )
        connection.commit()
    finally:
        connection.close()

    # The current-version initializer deliberately refuses to repair missing
    # constraints. Restore the deliberately removed guard explicitly so this
    # test can isolate the persisted business invariant violation.
    connection = sqlite3.connect(app_config.database_path)
    try:
        connection.executescript(SCHEMA)
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="配额合计超过教学组总容量"):
        check_database(app_config.database_path, app_config.app_secret)
    readiness = client.get("/api/admin/dashboard").json()["readiness"]
    assert readiness["ready"] is False
    assert any("超过教学组总容量" in blocker for blocker in readiness["blockers"])
    opened = client.post("/api/admin/countdown", headers=admin_headers)
    assert opened.status_code == 409


def test_database_check_uses_one_read_snapshot_during_activity_rollover(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
    monkeypatch,
):
    original_connect = sqlite3.connect
    paused = threading.Event()
    release = threading.Event()

    class CursorProxy:
        def __init__(self, cursor, pause_after_fetch: bool):
            self._cursor = cursor
            self._pause_after_fetch = pause_after_fetch

        def fetchall(self):
            rows = self._cursor.fetchall()
            if self._pause_after_fetch:
                paused.set()
                assert release.wait(timeout=10)
            return rows

        def __getattr__(self, name):
            return getattr(self._cursor, name)

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            cursor = self._connection.execute(sql, parameters)
            return CursorProxy(
                cursor,
                "SELECT id FROM activities WHERE status <> 'archived'" in sql,
            )

        def __getattr__(self, name):
            return getattr(self._connection, name)

    def controlled_connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)
        connection.row_factory = sqlite3.Row
        return ConnectionProxy(connection)

    monkeypatch.setattr(
        "server.maintenance.sqlite3.connect",
        controlled_connect,
    )
    activity_id = int(admin_headers["X-Activity-ID"])
    with ThreadPoolExecutor(max_workers=2) as pool:
        check_future = pool.submit(
            check_database, app_config.database_path, app_config.app_secret
        )
        assert paused.wait(timeout=10)
        rollover = client.post(
            "/api/admin/activities",
            headers=admin_headers,
            json={
                "title": "深检快照下一场",
                "code": "check-snapshot-next",
                "copy_structure": True,
                "previous_activity_id": activity_id,
            },
        )
        assert rollover.status_code == 200, rollover.text
        release.set()
        assert check_future.result(timeout=10) == "ok"
