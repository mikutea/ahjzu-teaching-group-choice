from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

import server.main as main_module
from server.database import connect

from .conftest import (
    fictional_activation_code,
    fictional_document_number,
    open_selection_now,
)


FIXED_ORGANIZATION = "安徽建筑大学 · 建筑与空间规划学院"
FIXED_OWNER = "Mikutea"


def import_roster(
    client: TestClient,
    headers: dict[str, str],
    major_name: str,
    rows: list[tuple[str, str, str]],
):
    csv_rows = ["student_no,name,major,document_number"]
    csv_rows.extend(
        f"{student_no},{name},{major_name},{document_number}"
        for student_no, name, document_number in rows
    )
    return client.post(
        "/api/admin/students/import",
        headers=headers,
        files={
            "files": (
                "students.csv",
                ("\n".join(csv_rows) + "\n").encode("utf-8"),
                "text/csv",
            )
        },
    )


def login_student(
    app,
    *,
    student_no: str,
    name: str,
    activation_code: str,
) -> tuple[TestClient, dict]:
    student = TestClient(app)
    response = student.post(
        "/api/student/login",
        json={
            "student_no": student_no,
            "name": name,
            "activation_code": activation_code,
        },
    )
    assert response.status_code == 200, response.text
    return student, response.json()


def student_headers(payload: dict, activity_id: int) -> dict[str, str]:
    return {
        "X-CSRF-Token": payload["csrf_token"],
        "X-Activity-ID": str(activity_id),
    }


def test_activation_code_is_encrypted_and_revealable(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    document_number = fictional_document_number("VISIBLE9")
    activation_code = document_number[-6:]
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [("20500000001", "Activation Student", document_number)],
    )
    assert imported.status_code == 200, imported.text

    connection = connect(app_config.database_path)
    try:
        columns = {
            row["name"] for row in connection.execute("PRAGMA table_info(students)")
        }
        assert "activation_ciphertext" in columns
        stored = connection.execute(
            """
            SELECT id, activation_hash, activation_ciphertext
            FROM students WHERE student_no = '20500000001'
            """
        ).fetchone()
        assert stored is not None
        student_id = int(stored["id"])
        assert stored["activation_hash"] != activation_code
        assert stored["activation_ciphertext"]
        assert activation_code not in str(stored["activation_ciphertext"])
    finally:
        connection.close()
    assert activation_code.encode("utf-8") not in app_config.database_path.read_bytes()

    student, login = login_student(
        app,
        student_no="20500000001",
        name="Activation Student",
        activation_code=activation_code,
    )
    try:
        assert login["student"]["id"] == student_id
    finally:
        student.close()

    revealed = client.post(
        f"/api/admin/students/{student_id}/activation-code/reveal",
        headers=admin_headers,
    )
    assert revealed.status_code == 200, revealed.text
    assert "no-store" in revealed.headers.get("cache-control", "").lower()
    assert revealed.json()["credential"] == {
        "student_no": "20500000001",
        "name": "Activation Student",
        "major": major_name,
        "activation_code": activation_code,
    }
    audit_actions = [row["action"] for row in client.get("/api/admin/audit").json()]
    assert "student.activation_code.reveal" in audit_actions

    revealed_again = client.post(
        f"/api/admin/students/{student_id}/activation-code/reveal",
        headers=admin_headers,
    )
    assert revealed_again.status_code == 200, revealed_again.text
    assert revealed_again.json()["credential"]["activation_code"] == activation_code

    same_code = TestClient(app)
    try:
        assert same_code.post(
            "/api/student/login",
            json={
                "student_no": "20500000001",
                "name": "Activation Student",
                "activation_code": activation_code,
            },
        ).status_code == 200
    finally:
        same_code.close()


def test_copyright_is_fixed_and_settings_api_cannot_change_it(
    client: TestClient,
    admin_headers: dict[str, str],
):
    public = client.get("/api/public/info").json()["settings"]
    assert public["organization_name"] == FIXED_ORGANIZATION
    assert public["owner_name"] == FIXED_OWNER

    rejected = client.patch(
        "/api/admin/settings",
        headers=admin_headers,
        json={
            "organization_name": "Untrusted College",
            "owner_name": "Untrusted Owner",
        },
    )
    assert rejected.status_code == 422
    after = client.get("/api/admin/dashboard").json()["settings"]
    assert after["organization_name"] == FIXED_ORGANIZATION
    assert after["owner_name"] == FIXED_OWNER

    title_only = client.patch(
        "/api/admin/settings",
        headers=admin_headers,
        json={"activity_title": "2050 Teaching Group Selection"},
    )
    assert title_only.status_code == 200, title_only.text
    assert title_only.json()["organization_name"] == FIXED_ORGANIZATION
    assert title_only.json()["owner_name"] == FIXED_OWNER


def test_major_and_group_can_only_be_disabled_when_safe(
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    occupied_major = dashboard["majors"][0]
    occupied_group = dashboard["groups"][0]
    imported = import_roster(
        client,
        admin_headers,
        occupied_major["name"],
        [("20510000001", "Assigned Student", fictional_document_number("ASSIGNED1"))],
    )
    assert imported.status_code == 200, imported.text
    student_id = next(
        row["id"]
        for row in client.get("/api/admin/dashboard").json()["students"]
        if row["student_no"] == "20510000001"
    )

    major_blocked = client.patch(
        f"/api/admin/majors/{occupied_major['id']}",
        headers=admin_headers,
        json={"active": False},
    )
    assert major_blocked.status_code == 409

    assigned = client.post(
        "/api/admin/selections",
        headers=admin_headers,
        json={"student_id": student_id, "group_id": occupied_group["id"]},
    )
    assert assigned.status_code == 200, assigned.text
    group_blocked = client.patch(
        f"/api/admin/groups/{occupied_group['id']}",
        headers=admin_headers,
        json={"active": False},
    )
    assert group_blocked.status_code == 409

    safe_major = client.post(
        "/api/admin/majors",
        headers=admin_headers,
        json={"name": "Safe Toggle Major"},
    )
    assert safe_major.status_code == 200, safe_major.text
    safe_major_id = safe_major.json()["id"]
    assert client.patch(
        f"/api/admin/majors/{safe_major_id}",
        headers=admin_headers,
        json={"active": False},
    ).status_code == 200
    assert client.patch(
        f"/api/admin/majors/{safe_major_id}",
        headers=admin_headers,
        json={"active": True},
    ).status_code == 200

    safe_group = client.post(
        "/api/admin/groups",
        headers=admin_headers,
        json={"name": "Safe Toggle Group", "total_capacity": 0},
    )
    assert safe_group.status_code == 200, safe_group.text
    safe_group_id = safe_group.json()["id"]
    assert client.patch(
        f"/api/admin/groups/{safe_group_id}",
        headers=admin_headers,
        json={"active": False},
    ).status_code == 200
    assert client.patch(
        f"/api/admin/groups/{safe_group_id}",
        headers=admin_headers,
        json={"active": True},
    ).status_code == 200


def test_waiting_room_presence_heartbeat_and_absent_roster(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    major_name = dashboard["majors"][0]["name"]
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [
            ("20520000001", "Entered Student", fictional_document_number("ENTERED1")),
            ("20520000002", "Absent Student", fictional_document_number("ABSENT22")),
            ("20520000003", "Also Absent", fictional_document_number("ABSENT33")),
        ],
    )
    assert imported.status_code == 200, imported.text

    student, login = login_student(
        app,
        student_no="20520000001",
        name="Entered Student",
        activation_code=fictional_activation_code("ENTERED1"),
    )
    try:
        waiting = client.get("/api/admin/dashboard").json()
        assert waiting["phase"] == "waiting"
        assert waiting["presence"]["total"] == 3
        assert waiting["presence"]["online_count"] == 1
        assert waiting["presence"]["absent_count"] == 2
        assert [row["student_no"] for row in waiting["entered_students"]] == [
            "20520000001"
        ]
        assert {row["student_no"] for row in waiting["absent_students"]} == {
            "20520000002",
            "20520000003",
        }

        connection = connect(app_config.database_path)
        try:
            connection.execute(
                """
                UPDATE sessions SET last_seen_at = '2000-01-01T00:00:00+00:00'
                WHERE role = 'student' AND subject_id = ?
                """,
                (login["student"]["id"],),
            )
        finally:
            connection.close()
        stale = client.get("/api/admin/dashboard").json()
        assert stale["presence"]["total"] == 3
        assert stale["presence"]["online_count"] == 0
        assert stale["presence"]["absent_count"] == 3

        heartbeat = student.post(
            "/api/student/heartbeat",
            headers=student_headers(login, activity_id),
        )
        assert heartbeat.status_code == 200, heartbeat.text
        assert "server_now" in heartbeat.json()
        assert heartbeat.json()["has_selection"] is False
        refreshed = client.get("/api/admin/dashboard").json()
        assert refreshed["presence"]["total"] == 3
        assert refreshed["presence"]["online_count"] == 1
        assert refreshed["presence"]["absent_count"] == 2

        group_id = refreshed["groups"][0]["id"]
        assigned = client.post(
            "/api/admin/selections",
            headers=admin_headers,
            json={"student_id": login["student"]["id"], "group_id": group_id},
        )
        assert assigned.status_code == 200, assigned.text
        selected_heartbeat = student.post(
            "/api/student/heartbeat",
            headers=student_headers(login, activity_id),
        )
        assert selected_heartbeat.status_code == 200, selected_heartbeat.text
        assert selected_heartbeat.json()["has_selection"] is True

        no_csrf = student.post(
            "/api/student/heartbeat",
            headers={"X-Activity-ID": str(activity_id)},
        )
        assert no_csrf.status_code == 403
    finally:
        student.close()


def test_same_student_overlapping_logins_acknowledge_only_one_session(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
    monkeypatch,
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    student_no = "20520000004"
    student_name = "Concurrent Login Student"
    activation_seed = "SAMELOGIN"
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [
            (
                student_no,
                student_name,
                fictional_document_number(activation_seed),
            )
        ],
    )
    assert imported.status_code == 200, imported.text

    projection_threads: list[str] = []
    original_connect = main_module.connect

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            if "SELECT G.ID, G.NAME, G.TOTAL_CAPACITY" in " ".join(
                sql.upper().split()
            ):
                projection_threads.append(threading.current_thread().name)
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        main_module,
        "connect",
        lambda path: ConnectionProxy(original_connect(path)),
    )
    read_time = datetime.now(UTC).replace(microsecond=0)
    write_time = read_time + timedelta(seconds=40)

    class ControlledDateTime(datetime):
        @classmethod
        def now(cls, tz=None):
            current = (
                write_time
                if threading.current_thread().name == "sqlite-batch-writer"
                else read_time
            )
            return current if tz is not None else current.replace(tzinfo=None)

    monkeypatch.setattr(main_module, "datetime", ControlledDateTime)
    writer = app.state.sqlite_writer
    original_batch_size = writer._batch_size
    original_batch_window = writer._batch_window_seconds
    writer._batch_size = 2
    writer._batch_window_seconds = 0.01
    students = [TestClient(app), TestClient(app)]
    barrier = threading.Barrier(2)
    payload = {
        "student_no": student_no,
        "name": student_name,
        "activation_code": fictional_activation_code(activation_seed),
    }

    def login(student: TestClient):
        barrier.wait(timeout=10)
        return student.post("/api/student/login", json=payload)

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(login, students))
        assert sorted(response.status_code for response in responses) == [200, 409]
        winner_index = next(
            index for index, response in enumerate(responses) if response.status_code == 200
        )
        loser_index = 1 - winner_index
        assert "正在登录" in responses[loser_index].json()["detail"]
        assert students[winner_index].get("/api/student/me").status_code == 200
        assert students[loser_index].cookies.get(main_module.STUDENT_COOKIE) is None
        assert projection_threads
        assert all("asyncio-portal" not in name for name in projection_threads)
        connection = connect(app_config.database_path)
        try:
            sessions = connection.execute(
                """
                SELECT created_at FROM sessions
                WHERE role = 'student'
                """
            ).fetchall()
            assert len(sessions) == 1
            assert sessions[0]["created_at"] == write_time.isoformat(
                timespec="seconds"
            )
        finally:
            connection.close()
    finally:
        writer._batch_size = original_batch_size
        writer._batch_window_seconds = original_batch_window
        for student in students:
            student.close()


def test_overlapping_student_login_cannot_publish_a_superseded_cookie(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    dashboard = client.get("/api/admin/dashboard").json()
    student_no = "20520000006"
    student_name = "Response Ordered Login"
    activation_seed = "RESPORDER"
    imported = import_roster(
        client,
        admin_headers,
        dashboard["majors"][0]["name"],
        [
            (
                student_no,
                student_name,
                fictional_document_number(activation_seed),
            )
        ],
    )
    assert imported.status_code == 200, imported.text

    first_reached_cookie_boundary = threading.Event()
    allow_first_response = threading.Event()
    clear_lock = threading.Lock()
    clear_calls = 0
    original_clear = main_module.RateLimiter.clear

    def controlled_clear(limiter, key):
        nonlocal clear_calls
        original_clear(limiter, key)
        with clear_lock:
            clear_calls += 1
            call_number = clear_calls
        if call_number == 1:
            first_reached_cookie_boundary.set()
            assert allow_first_response.wait(timeout=10)

    monkeypatch.setattr(main_module.RateLimiter, "clear", controlled_clear)
    writer = app.state.sqlite_writer
    original_batch_size = writer._batch_size
    original_batch_window = writer._batch_window_seconds
    writer._batch_size = 1
    writer._batch_window_seconds = 0
    first_student = TestClient(app)
    second_student = TestClient(app)
    payload = {
        "student_no": student_no,
        "name": student_name,
        "activation_code": fictional_activation_code(activation_seed),
    }

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(
                first_student.post, "/api/student/login", json=payload
            )
            assert first_reached_cookie_boundary.wait(timeout=10)
            second_future = pool.submit(
                second_student.post, "/api/student/login", json=payload
            )
            second_response = second_future.result(timeout=10)
            assert second_response.status_code == 409, second_response.text
            assert second_student.cookies.get(main_module.STUDENT_COOKIE) is None
            allow_first_response.set()
            first_response = first_future.result(timeout=10)

        assert first_response.status_code == 200, first_response.text
        assert first_student.get("/api/student/me").status_code == 200
        assert clear_calls == 1
    finally:
        allow_first_response.set()
        writer._batch_size = original_batch_size
        writer._batch_window_seconds = original_batch_window
        first_student.close()
        second_student.close()


@pytest.mark.parametrize("fail_send", [False, True])
def test_login_response_gate_releases_only_after_outer_asgi_send(app, fail_send: bool):
    async def exercise() -> None:
        gate = main_module.PrincipalResponseGate()
        release = gate.try_acquire(42)
        assert release is not None
        body_send_started = asyncio.Event()
        allow_body_send = asyncio.Event()

        async def inner(scope, receive, send):
            scope[main_module.RESPONSE_FINALIZER_SCOPE_KEY] = release
            await send(
                {
                    "type": "http.response.start",
                    "status": 200,
                    "headers": [],
                }
            )
            await send(
                {
                    "type": "http.response.body",
                    "body": b'{"ok":true}',
                }
            )

        middleware = main_module.ResponseFinalizerMiddleware(inner)

        async def receive():
            return {"type": "http.disconnect"}

        async def send(message):
            if message["type"] != "http.response.body":
                return
            body_send_started.set()
            await allow_body_send.wait()
            if fail_send:
                raise RuntimeError("simulated client disconnect")

        response_task = asyncio.create_task(
            middleware({"type": "http"}, receive, send)
        )
        await asyncio.wait_for(body_send_started.wait(), timeout=2)
        assert gate.try_acquire(42) is None
        allow_body_send.set()
        if fail_send:
            with pytest.raises(RuntimeError, match="simulated client disconnect"):
                await response_task
        else:
            await response_task
        next_release = gate.try_acquire(42)
        assert next_release is not None
        next_release()

    assert app.user_middleware[0].cls is main_module.ResponseFinalizerMiddleware
    asyncio.run(exercise())


def test_heartbeat_sqlite_reads_run_off_the_event_loop(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    student_no = "20520000007"
    student_name = "Async Heartbeat Reads"
    activation_seed = "ASYNCREAD"
    imported = import_roster(
        client,
        admin_headers,
        dashboard["majors"][0]["name"],
        [
            (
                student_no,
                student_name,
                fictional_document_number(activation_seed),
            )
        ],
    )
    assert imported.status_code == 200, imported.text
    student, login_payload = login_student(
        app,
        student_no=student_no,
        name=student_name,
        activation_code=fictional_activation_code(activation_seed),
    )

    read_threads: list[str] = []
    original_connect = main_module.connect

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            normalized = " ".join(sql.upper().split())
            if any(
                marker in normalized
                for marker in (
                    "SELECT ROLE, SUBJECT_ID, CSRF_TOKEN",
                    "SELECT LAST_SEEN_AT FROM SESSIONS",
                    "SELECT EXISTS( SELECT 1 FROM SELECTIONS",
                    "SELECT S.*, A.ID AS ACTIVITY_ID",
                )
            ):
                read_threads.append(threading.current_thread().name)
            return self._connection.execute(sql, parameters)

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        main_module,
        "connect",
        lambda path: ConnectionProxy(original_connect(path)),
    )
    try:
        heartbeat = student.post(
            "/api/student/heartbeat",
            headers=student_headers(login_payload, activity_id),
        )
        assert heartbeat.status_code == 200, heartbeat.text
        assert read_threads
        assert all("asyncio-portal" not in name for name in read_threads)
    finally:
        student.close()


def test_queued_heartbeat_uses_writer_execution_time(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
    monkeypatch,
):
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    major_name = dashboard["majors"][0]["name"]
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [
            (
                "20520000005",
                "Delayed Heartbeat Student",
                fictional_document_number("LATEHEART"),
            )
        ],
    )
    assert imported.status_code == 200, imported.text
    student, login_payload = login_student(
        app,
        student_no="20520000005",
        name="Delayed Heartbeat Student",
        activation_code=fictional_activation_code("LATEHEART"),
    )
    student_id = int(login_payload["student"]["id"])
    connection = connect(app_config.database_path)
    try:
        connection.execute(
            """
            UPDATE sessions SET last_seen_at = '2000-01-01T00:00:00+00:00'
            WHERE role = 'student' AND subject_id = ?
            """,
            (student_id,),
        )
    finally:
        connection.close()

    write_time = datetime.now(UTC).replace(microsecond=0)
    read_time = write_time - timedelta(
        seconds=main_module.PRESENCE_FRESH_SECONDS + 5
    )

    def controlled_utc_now() -> str:
        current = (
            write_time
            if threading.current_thread().name == "sqlite-batch-writer"
            else read_time
        )
        return current.isoformat(timespec="seconds")

    monkeypatch.setattr(main_module, "utc_now", controlled_utc_now)
    try:
        heartbeat = student.post(
            "/api/student/heartbeat",
            headers=student_headers(login_payload, activity_id),
        )
        assert heartbeat.status_code == 200, heartbeat.text
        connection = connect(app_config.database_path)
        try:
            last_seen_at = connection.execute(
                """
                SELECT last_seen_at FROM sessions
                WHERE role = 'student' AND subject_id = ?
                """,
                (student_id,),
            ).fetchone()[0]
        finally:
            connection.close()
        assert last_seen_at == write_time.isoformat(timespec="seconds")
    finally:
        student.close()


def test_countdown_uses_server_clock_and_opens_atomically_without_sleeping(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    # Keep the controlled clock inside the already-created admin session's
    # validity window while still avoiding a real ten-second sleep.
    base = datetime.now(UTC).replace(microsecond=0)
    clock = {"now": base}

    def controlled_utc_now() -> str:
        return clock["now"].isoformat(timespec="seconds")

    monkeypatch.setattr(main_module, "utc_now", controlled_utc_now)
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    major_name = dashboard["majors"][0]["name"]
    group_id = int(dashboard["groups"][0]["id"])
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [("20530000001", "Countdown Student", fictional_document_number("COUNTDWN"))],
    )
    assert imported.status_code == 200, imported.text
    student, login = login_student(
        app,
        student_no="20530000001",
        name="Countdown Student",
        activation_code=fictional_activation_code("COUNTDWN"),
    )
    try:
        assert login["phase"] == "waiting"
        assert login["server_now"] == controlled_utc_now()
        assert login["selection_opens_at"] is None

        started = client.post("/api/admin/countdown", headers=admin_headers)
        assert started.status_code == 200, started.text
        opens_at = (base + timedelta(seconds=10)).isoformat(timespec="seconds")
        assert started.json()["selection_opens_at"] == opens_at
        countdown = student.get("/api/student/me").json()
        assert countdown["phase"] == "countdown"
        assert countdown["server_now"] == controlled_utc_now()
        assert countdown["selection_opens_at"] == opens_at

        early = student.post(
            "/api/student/select",
            headers=student_headers(login, activity_id),
            json={"group_id": group_id},
        )
        assert early.status_code == 409
        assert client.get("/api/admin/dashboard").json()["totals"]["selected"] == 0

        clock["now"] = base + timedelta(seconds=9)
        assert student.get("/api/student/me").json()["phase"] == "countdown"
        clock["now"] = base + timedelta(seconds=10)
        opened = student.get("/api/student/me").json()
        assert opened["phase"] == "open"
        selected = student.post(
            "/api/student/select",
            headers=student_headers(login, activity_id),
            json={"group_id": group_id},
        )
        assert selected.status_code == 200, selected.text

        closed = client.post(
            "/api/admin/status",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert closed.status_code == 200, closed.text
        after_close = client.get("/api/admin/dashboard").json()
        assert after_close["phase"] == "closed"
        assert after_close["selection_opens_at"] is None
    finally:
        student.close()


def test_selection_returns_committed_payload_without_post_commit_projection(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    major_name = dashboard["majors"][0]["name"]
    group_id = int(dashboard["groups"][0]["id"])
    document_number = fictional_document_number("ROLLBACK-RESPONSE")
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [("20530000011", "Projection Failure", document_number)],
    )
    assert imported.status_code == 200, imported.text
    open_selection_now(client, admin_headers)

    with TestClient(app, raise_server_exceptions=False) as student:
        login = student.post(
            "/api/student/login",
            json={
                "student_no": "20530000011",
                "name": "Projection Failure",
                "activation_code": document_number[-6:],
            },
        )
        assert login.status_code == 200, login.text
        login_payload = login.json()
        original_connect = main_module.connect
        projection_failure_triggered = False

        class ProjectionFailingConnection:
            def __init__(self, database_path):
                self._connection = original_connect(database_path)
                self._write_committed = False

            def execute(self, sql, *args, **kwargs):
                nonlocal projection_failure_triggered
                normalized = " ".join(str(sql).upper().split())
                if (
                    self._write_committed
                    and "SELECT G.ID, G.NAME, G.TOTAL_CAPACITY" in normalized
                ):
                    projection_failure_triggered = True
                    raise RuntimeError("synthetic post-commit projection failure")
                return self._connection.execute(sql, *args, **kwargs)

            def commit(self):
                self._connection.commit()
                self._write_committed = True

            def rollback(self):
                return self._connection.rollback()

            def close(self):
                return self._connection.close()

            def __getattr__(self, name):
                return getattr(self._connection, name)

        monkeypatch.setattr(main_module, "connect", ProjectionFailingConnection)
        selected = student.post(
            "/api/student/select",
            headers=student_headers(login_payload, activity_id),
            json={"group_id": group_id},
        )
        assert selected.status_code == 200, selected.text
        payload = selected.json()
        assert projection_failure_triggered is False
        assert payload["selection"]["group_id"] == group_id
        assert payload["receipt"]["token"]
        assert payload["groups"] == []
        verified = student.post(
            "/api/public/receipts/verify",
            json={"token": payload["receipt"]["token"]},
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["valid"] is True

    connection = connect(app_config.database_path)
    try:
        student_id = int(
            connection.execute(
                "SELECT id FROM students WHERE student_no = ?", ("20530000011",)
            ).fetchone()["id"]
        )
        assert connection.execute(
            "SELECT COUNT(*) FROM selections WHERE student_id = ?", (student_id,)
        ).fetchone()[0] == 1
        assert connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE action = 'selection.create' AND entity_type = 'selection'"
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_countdown_freezes_admin_assignment_and_revocation(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
) -> None:
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    group_id = int(dashboard["groups"][0]["id"])
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [
            ("20530000012", "Assigned Before Countdown", fictional_document_number("ASSIGN-BEFORE")),
            ("20530000013", "Blocked During Countdown", fictional_document_number("ASSIGN-DURING")),
        ],
    )
    assert imported.status_code == 200, imported.text
    connection = connect(app_config.database_path)
    try:
        rows = connection.execute(
            "SELECT id, student_no FROM students WHERE student_no IN (?, ?)",
            ("20530000012", "20530000013"),
        ).fetchall()
        ids = {row["student_no"]: int(row["id"]) for row in rows}
    finally:
        connection.close()

    assigned = client.post(
        "/api/admin/selections",
        headers=admin_headers,
        json={"student_id": ids["20530000012"], "group_id": group_id},
    )
    assert assigned.status_code == 200, assigned.text
    started = client.post("/api/admin/countdown", headers=admin_headers)
    assert started.status_code == 200, started.text
    assert started.json()["phase"] == "countdown"

    blocked_assign = client.post(
        "/api/admin/selections",
        headers=admin_headers,
        json={"student_id": ids["20530000013"], "group_id": group_id},
    )
    assert blocked_assign.status_code == 409
    assert "倒计时" in blocked_assign.json()["detail"]
    blocked_revoke = client.post(
        "/api/admin/selections/revoke",
        headers=admin_headers,
        json={"student_id": ids["20530000012"], "reason": "synthetic countdown guard"},
    )
    assert blocked_revoke.status_code == 409
    assert "倒计时" in blocked_revoke.json()["detail"]

    connection = connect(app_config.database_path)
    try:
        active = connection.execute(
            "SELECT student_id FROM selections WHERE revoked_at IS NULL ORDER BY student_id"
        ).fetchall()
        assert [int(row["student_id"]) for row in active] == [ids["20530000012"]]
    finally:
        connection.close()


def test_cancelling_countdown_returns_to_waiting_and_clears_schedule(
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    imported = import_roster(
        client,
        admin_headers,
        dashboard["majors"][0]["name"],
        [("20530000002", "Cancelled Countdown", fictional_document_number("CANCEL10"))],
    )
    assert imported.status_code == 200, imported.text
    started = client.post("/api/admin/countdown", headers=admin_headers)
    assert started.status_code == 200, started.text
    assert started.json()["phase"] == "countdown"

    cancelled = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "closed"},
    )
    assert cancelled.status_code == 200, cancelled.text
    waiting = client.get("/api/admin/dashboard").json()
    assert waiting["phase"] == "waiting"
    assert waiting["selection_opens_at"] is None


def test_activity_rollover_clears_countdown_and_revokes_old_student_session(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    old_activity_id = int(dashboard["settings"]["activity_id"])
    major_name = dashboard["majors"][0]["name"]
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [("20540000001", "Rollover Student", fictional_document_number("ROLLOVER"))],
    )
    assert imported.status_code == 200, imported.text
    student, _ = login_student(
        app,
        student_no="20540000001",
        name="Rollover Student",
        activation_code=fictional_activation_code("ROLLOVER"),
    )
    try:
        started = client.post("/api/admin/countdown", headers=admin_headers)
        assert started.status_code == 200, started.text
        assert started.json()["selection_opens_at"]
        closed = client.post(
            "/api/admin/status",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert closed.status_code == 200, closed.text
        created = client.post(
            "/api/admin/activities",
            headers=admin_headers,
            json={
                "title": "Next Waiting Flow Activity",
                "code": "next-waiting-flow",
                "copy_structure": True,
                "previous_activity_id": old_activity_id,
            },
        )
        assert created.status_code == 200, created.text
        next_dashboard = client.get("/api/admin/dashboard").json()
        assert next_dashboard["settings"]["activity_id"] == created.json()["activity_id"]
        assert next_dashboard["phase"] == "waiting"
        assert next_dashboard["selection_opens_at"] is None
        assert next_dashboard["presence"]["total"] == 0
        assert next_dashboard["presence"]["online_count"] == 0
        assert next_dashboard["presence"]["absent_count"] == 0
        assert student.get("/api/student/me").status_code == 401

        archive = client.get(f"/api/admin/activities/{old_activity_id}/archive.json")
        assert archive.status_code == 200, archive.text
        serialized = archive.content
        assert b"ROLLOVER" not in serialized
        assert b"activation_ciphertext" not in serialized
    finally:
        student.close()


def test_one_hundred_fifty_students_after_countdown_never_oversell(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    """The staged start must preserve the same atomic seat boundary as direct open."""
    base = datetime.now(UTC).replace(microsecond=0)
    clock = {"now": base}

    def controlled_utc_now() -> str:
        return clock["now"].isoformat(timespec="seconds")

    monkeypatch.setattr(main_module, "utc_now", controlled_utc_now)
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    major = dashboard["majors"][0]
    group = dashboard["groups"][0]

    for quota in dashboard["quotas"]:
        if quota["major_id"] != major["id"]:
            assert client.put(
                f"/api/admin/quotas/{quota['major_id']}/{quota['group_id']}",
                headers=admin_headers,
                json={"capacity": 0},
            ).status_code == 200
    for quota in dashboard["quotas"]:
        if quota["major_id"] == major["id"]:
            assert client.put(
                f"/api/admin/quotas/{quota['major_id']}/{quota['group_id']}",
                headers=admin_headers,
                json={"capacity": 30},
            ).status_code == 200

    rows = [
        (
            f"2055000{index:04d}",
            f"CountdownLoad{chr(65 + (index // 26) // 26)}{chr(65 + (index // 26) % 26)}{chr(65 + index % 26)}",
            fictional_document_number(f"FLOW{index:04d}"),
        )
        for index in range(150)
    ]
    imported = import_roster(client, admin_headers, major["name"], rows)
    assert imported.status_code == 200, imported.text

    clients: list[TestClient] = []
    payloads: list[dict] = []
    try:
        for student_no, name, document_number in rows:
            student, payload = login_student(
                app,
                student_no=student_no,
                name=name,
                activation_code=document_number[-6:],
            )
            clients.append(student)
            payloads.append(payload)

        started = client.post("/api/admin/countdown", headers=admin_headers)
        assert started.status_code == 200, started.text

        early = clients[0].post(
            "/api/student/select",
            headers=student_headers(payloads[0], activity_id),
            json={"group_id": group["id"]},
        )
        assert early.status_code == 409

        clock["now"] = base + timedelta(seconds=10)
        barrier = threading.Barrier(150)
        writer_before = app.state.sqlite_writer.stats()

        def submit(index: int):
            barrier.wait(timeout=20)
            return clients[index].post(
                "/api/student/select",
                headers=student_headers(payloads[index], activity_id),
                json={"group_id": group["id"]},
            )

        with ThreadPoolExecutor(max_workers=150) as pool:
            responses = list(pool.map(submit, range(150)))

        writer_after = app.state.sqlite_writer.stats()
        assert writer_after["commits"] - writer_before["commits"] < 150
        assert writer_after["max_batch_size"] > 1

        statuses = [response.status_code for response in responses]
        assert statuses.count(200) == 30
        assert statuses.count(409) == 120
        assert not [status for status in statuses if status >= 500]
        non_conflicts = [
            (response.status_code, response.text)
            for response in responses
            if response.status_code not in {200, 409}
        ]
        assert not non_conflicts
        conflict_details = [
            response.json().get("detail", "")
            for response in responses
            if response.status_code == 409
        ]
        assert all(detail for detail in conflict_details)
        assert all("名额" in detail or "已满" in detail for detail in conflict_details)
        final = client.get("/api/admin/dashboard").json()
        cell = next(
            quota
            for quota in final["quotas"]
            if quota["major_id"] == major["id"]
            and quota["group_id"] == group["id"]
        )
        assert cell["selected_count"] == 30
        assert final["totals"] == {
            "students": 150,
            "selected": 30,
            "unselected": 120,
        }
    finally:
        for student in clients:
            student.close()


def test_same_student_same_group_retry_is_idempotent_after_commit(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    major_name = dashboard["majors"][0]["name"]
    group = dashboard["groups"][0]
    document_number = fictional_document_number("IDEMPOTENT-SELECTION")
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [("20550000999", "Idempotent Student", document_number)],
    )
    assert imported.status_code == 200, imported.text
    open_selection_now(client, admin_headers)
    student, login = login_student(
        app,
        student_no="20550000999",
        name="Idempotent Student",
        activation_code=document_number[-6:],
    )
    try:
        headers = student_headers(login, activity_id)
        first = student.post(
            "/api/student/select",
            headers=headers,
            json={"group_id": group["id"]},
        )
        assert first.status_code == 200, first.text
        closed = client.post(
            "/api/admin/status",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert closed.status_code == 200, closed.text
        traces: list[tuple[str, list[str]]] = []
        original_connect = main_module.connect

        def traced_connect(database_path):
            connection = original_connect(database_path)
            statements: list[str] = []
            traces.append((threading.current_thread().name, statements))
            connection.set_trace_callback(statements.append)
            return connection

        monkeypatch.setattr(main_module, "connect", traced_connect)
        replay_committed = threading.Event()
        allow_replay_response = threading.Event()
        original_submit_async = app.state.sqlite_writer.submit_async

        async def gated_submit_async(callback, *, priority=0):
            result = await original_submit_async(callback, priority=priority)
            replay_committed.set()
            allowed = await asyncio.to_thread(
                allow_replay_response.wait, 10
            )
            assert allowed
            return result

        monkeypatch.setattr(
            app.state.sqlite_writer, "submit_async", gated_submit_async
        )
        try:
            with ThreadPoolExecutor(max_workers=1) as pool:
                replay_future = pool.submit(
                    student.post,
                    "/api/student/select",
                    headers=headers,
                    json={"group_id": group["id"]},
                )
                assert replay_committed.wait(timeout=10)
                revoked = client.post(
                    "/api/admin/selections/revoke",
                    headers=admin_headers,
                    json={
                        "student_id": first.json()["student"]["id"],
                        "reason": "synthetic replay response race",
                    },
                )
                assert revoked.status_code == 200, revoked.text
                allow_replay_response.set()
                replay = replay_future.result(timeout=10)
        finally:
            allow_replay_response.set()
        assert replay.status_code == 200, replay.text
        assert replay.json()["phase"] == "closed"
        assert replay.json()["selection"] == first.json()["selection"]
        assert replay.json()["receipt"]["token"] == first.json()["receipt"]["token"]
        writer_statements = next(
            statements for thread_name, statements in traces if thread_name == "sqlite-batch-writer"
        )
        assert not any(
            "SELECT G.ID, G.NAME, G.TOTAL_CAPACITY"
            in " ".join(statement.upper().split())
            for statement in writer_statements
        )
        assert not any(
            "SELECT G.ID, G.NAME, G.TOTAL_CAPACITY"
            in " ".join(statement.upper().split())
            for _, statements in traces
            for statement in statements
        )
        connection = connect(client.app.state.config.database_path)
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM selections"
            ).fetchone()[0] == 1
            assert connection.execute(
                "SELECT COUNT(*) FROM audit_logs WHERE action = 'selection.create'"
            ).fetchone()[0] == 1
        finally:
            connection.close()
    finally:
        student.close()


def test_three_hundred_simultaneous_valid_choices_commit_without_busy_errors(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    major = dashboard["majors"][0]
    group = dashboard["groups"][0]
    connection = connect(client.app.state.config.database_path)
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute("UPDATE quotas SET capacity = 0")
        connection.execute(
            "UPDATE teaching_groups SET total_capacity = 300 WHERE id = ?",
            (group["id"],),
        )
        connection.execute(
            "UPDATE quotas SET capacity = 300 WHERE major_id = ? AND group_id = ?",
            (major["id"], group["id"]),
        )
        connection.commit()
    finally:
        connection.close()

    rows = [
        (
            f"2060000{index:04d}",
            f"BatchStudent{chr(65 + (index // 26) // 26)}{chr(65 + (index // 26) % 26)}{chr(65 + index % 26)}",
            fictional_document_number(f"BATCH-300-{index:04d}"),
        )
        for index in range(300)
    ]
    imported = import_roster(client, admin_headers, major["name"], rows)
    assert imported.status_code == 200, imported.text
    open_selection_now(client, admin_headers)

    clients: list[TestClient] = []
    payloads: list[dict] = []
    try:
        for student_no, name, document_number in rows:
            student, payload = login_student(
                app,
                student_no=student_no,
                name=name,
                activation_code=document_number[-6:],
            )
            clients.append(student)
            payloads.append(payload)

        barrier = threading.Barrier(300)
        before = app.state.sqlite_writer.stats()

        def submit(index: int):
            barrier.wait(timeout=30)
            return clients[index].post(
                "/api/student/select",
                headers=student_headers(payloads[index], activity_id),
                json={"group_id": group["id"]},
            )

        with ThreadPoolExecutor(max_workers=300) as pool:
            responses = list(pool.map(submit, range(300)))

        assert [response.status_code for response in responses] == [200] * 300
        after = app.state.sqlite_writer.stats()
        assert after["commits"] - before["commits"] <= 20
        assert after["max_batch_size"] >= 16
        connection = connect(client.app.state.config.database_path)
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM selections WHERE revoked_at IS NULL"
            ).fetchone()[0] == 300
        finally:
            connection.close()
    finally:
        for student in clients:
            student.close()


def test_activity_rollover_cannot_race_heartbeat_into_old_activity(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    imported = import_roster(
        client,
        admin_headers,
        dashboard["majors"][0]["name"],
        [("20560000002", "Heartbeat Rollover Race", fictional_document_number("HEARTROL"))],
    )
    assert imported.status_code == 200, imported.text
    student, login = login_student(
        app,
        student_no="20560000002",
        name="Heartbeat Rollover Race",
        activation_code=fictional_activation_code("HEARTROL"),
    )
    student_id = int(login["student"]["id"])
    original_connect = main_module.connect
    connection = original_connect(client.app.state.config.database_path)
    try:
        connection.execute(
            """
            UPDATE sessions SET last_seen_at = '2000-01-01T00:00:00+00:00'
            WHERE role = 'student' AND subject_id = ?
            """,
            (student_id,),
        )
    finally:
        connection.close()
    heartbeat_waiting = threading.Event()
    allow_heartbeat = threading.Event()
    initial_read_closed = threading.Event()
    read_closed_before_writer_wait: list[bool] = []
    pause_lock = threading.Lock()
    paused_once = False

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection
            self._saw_begin = False

        def execute(self, sql, parameters=()):
            nonlocal paused_once
            should_pause = False
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                self._saw_begin = True
                with pause_lock:
                    if not paused_once:
                        paused_once = True
                        should_pause = True
            if should_pause:
                read_closed_before_writer_wait.append(initial_read_closed.is_set())
                heartbeat_waiting.set()
                assert allow_heartbeat.wait(timeout=10)
            return self._connection.execute(sql, parameters)

        def close(self):
            if not self._saw_begin:
                initial_read_closed.set()
            return self._connection.close()

        def __getattr__(self, name):
            return getattr(self._connection, name)

    monkeypatch.setattr(
        main_module,
        "connect",
        lambda path: ConnectionProxy(original_connect(path)),
    )
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            heartbeat_future = pool.submit(
                student.post,
                "/api/student/heartbeat",
                headers=student_headers(login, activity_id),
            )
            assert heartbeat_waiting.wait(timeout=10)
            assert read_closed_before_writer_wait == [True]
            rollover = client.post(
                "/api/admin/activities",
                headers=admin_headers,
                json={
                    "title": "Heartbeat Race Next Activity",
                    "code": "heartbeat-race-next",
                    "copy_structure": True,
                    "previous_activity_id": activity_id,
                },
            )
            assert rollover.status_code == 200, rollover.text
            allow_heartbeat.set()
            stale = heartbeat_future.result(timeout=10)
        assert stale.status_code == 401, stale.text
        connection = original_connect(client.app.state.config.database_path)
        try:
            assert connection.execute(
                "SELECT COUNT(*) FROM sessions WHERE role = 'student' AND subject_id = ?",
                (student_id,),
            ).fetchone()[0] == 0
        finally:
            connection.close()
    finally:
        allow_heartbeat.set()
        student.close()
