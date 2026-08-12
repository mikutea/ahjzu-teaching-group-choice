from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

import server.main as main_module
from server.database import connect


FIXED_ORGANIZATION = "安徽建筑大学 · 建筑与空间规划学院"
FIXED_OWNER = "Mikutea"


def import_roster(
    client: TestClient,
    headers: dict[str, str],
    major_name: str,
    rows: list[tuple[str, str, str]],
):
    csv_rows = ["student_no,name,major,activation_code"]
    csv_rows.extend(
        f"{student_no},{name},{major_name},{activation_code}"
        for student_no, name, activation_code in rows
    )
    return client.post(
        "/api/admin/students/import",
        headers=headers,
        files={
            "file": (
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


def test_activation_code_is_encrypted_revealable_rotatable_and_audited(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    activation_code = "VISIBLE9"
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [("20500001", "Activation Student", activation_code)],
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
            FROM students WHERE student_no = '20500001'
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
        student_no="20500001",
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
        "student_no": "20500001",
        "name": "Activation Student",
        "major": major_name,
        "activation_code": activation_code,
    }
    audit_actions = [row["action"] for row in client.get("/api/admin/audit").json()]
    assert "student.activation_code.reveal" in audit_actions

    reset = client.post(
        f"/api/admin/students/{student_id}/activation-code",
        headers=admin_headers,
    )
    assert reset.status_code == 200, reset.text
    replacement = reset.json()["credential"]["activation_code"]
    assert replacement != activation_code
    revealed_again = client.post(
        f"/api/admin/students/{student_id}/activation-code/reveal",
        headers=admin_headers,
    )
    assert revealed_again.status_code == 200, revealed_again.text
    assert revealed_again.json()["credential"]["activation_code"] == replacement

    old_code = TestClient(app)
    new_code = TestClient(app)
    try:
        assert old_code.post(
            "/api/student/login",
            json={
                "student_no": "20500001",
                "name": "Activation Student",
                "activation_code": activation_code,
            },
        ).status_code == 401
        assert new_code.post(
            "/api/student/login",
            json={
                "student_no": "20500001",
                "name": "Activation Student",
                "activation_code": replacement,
            },
        ).status_code == 200
    finally:
        old_code.close()
        new_code.close()


def test_legacy_hash_only_activation_code_requires_reset_before_reveal(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    imported = import_roster(
        client,
        admin_headers,
        major_name,
        [("20500002", "Legacy Student", "LEGACY99")],
    )
    assert imported.status_code == 200, imported.text
    student_id = next(
        row["id"]
        for row in client.get("/api/admin/dashboard").json()["students"]
        if row["student_no"] == "20500002"
    )

    connection = connect(app_config.database_path)
    try:
        connection.execute(
            "UPDATE students SET activation_ciphertext = NULL WHERE id = ?",
            (student_id,),
        )
    finally:
        connection.close()

    unavailable = client.post(
        f"/api/admin/students/{student_id}/activation-code/reveal",
        headers=admin_headers,
    )
    assert unavailable.status_code == 409
    assert "重置" in unavailable.json()["detail"]
    reset = client.post(
        f"/api/admin/students/{student_id}/activation-code",
        headers=admin_headers,
    )
    assert reset.status_code == 200, reset.text
    revealed = client.post(
        f"/api/admin/students/{student_id}/activation-code/reveal",
        headers=admin_headers,
    )
    assert revealed.status_code == 200, revealed.text
    assert (
        revealed.json()["credential"]["activation_code"]
        == reset.json()["credential"]["activation_code"]
    )


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
        [("20510001", "Assigned Student", "ASSIGNED1")],
    )
    assert imported.status_code == 200, imported.text
    student_id = next(
        row["id"]
        for row in client.get("/api/admin/dashboard").json()["students"]
        if row["student_no"] == "20510001"
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
            ("20520001", "Entered Student", "ENTERED1"),
            ("20520002", "Absent Student", "ABSENT22"),
            ("20520003", "Also Absent", "ABSENT33"),
        ],
    )
    assert imported.status_code == 200, imported.text

    student, login = login_student(
        app,
        student_no="20520001",
        name="Entered Student",
        activation_code="ENTERED1",
    )
    try:
        waiting = client.get("/api/admin/dashboard").json()
        assert waiting["phase"] == "waiting"
        assert waiting["presence"]["total"] == 3
        assert waiting["presence"]["online_count"] == 1
        assert waiting["presence"]["absent_count"] == 2
        assert [row["student_no"] for row in waiting["entered_students"]] == [
            "20520001"
        ]
        assert {row["student_no"] for row in waiting["absent_students"]} == {
            "20520002",
            "20520003",
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
        refreshed = client.get("/api/admin/dashboard").json()
        assert refreshed["presence"]["total"] == 3
        assert refreshed["presence"]["online_count"] == 1
        assert refreshed["presence"]["absent_count"] == 2

        no_csrf = student.post(
            "/api/student/heartbeat",
            headers={"X-Activity-ID": str(activity_id)},
        )
        assert no_csrf.status_code == 403
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
        [("20530001", "Countdown Student", "COUNTDWN")],
    )
    assert imported.status_code == 200, imported.text
    student, login = login_student(
        app,
        student_no="20530001",
        name="Countdown Student",
        activation_code="COUNTDWN",
    )
    try:
        assert login["phase"] == "waiting"
        assert login["server_now"] == controlled_utc_now()
        assert login["selection_opens_at"] is None

        started = client.post("/api/admin/start-countdown", headers=admin_headers)
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


def test_cancelling_countdown_returns_to_waiting_and_clears_schedule(
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    imported = import_roster(
        client,
        admin_headers,
        dashboard["majors"][0]["name"],
        [("20530002", "Cancelled Countdown", "CANCEL10")],
    )
    assert imported.status_code == 200, imported.text
    started = client.post("/api/admin/start-countdown", headers=admin_headers)
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
        [("20540001", "Rollover Student", "ROLLOVER")],
    )
    assert imported.status_code == 200, imported.text
    student, _ = login_student(
        app,
        student_no="20540001",
        name="Rollover Student",
        activation_code="ROLLOVER",
    )
    try:
        started = client.post("/api/admin/start-countdown", headers=admin_headers)
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
        (f"2055{index:04d}", f"Countdown Load {index:03d}", f"FLOW{index:04d}")
        for index in range(150)
    ]
    imported = import_roster(client, admin_headers, major["name"], rows)
    assert imported.status_code == 200, imported.text

    clients: list[TestClient] = []
    payloads: list[dict] = []
    try:
        for student_no, name, code in rows:
            student, payload = login_student(
                app,
                student_no=student_no,
                name=name,
                activation_code=code,
            )
            clients.append(student)
            payloads.append(payload)

        started = client.post("/api/admin/start-countdown", headers=admin_headers)
        assert started.status_code == 200, started.text

        early = clients[0].post(
            "/api/student/select",
            headers=student_headers(payloads[0], activity_id),
            json={"group_id": group["id"]},
        )
        assert early.status_code == 409

        clock["now"] = base + timedelta(seconds=10)
        barrier = threading.Barrier(150)

        def submit(index: int):
            barrier.wait(timeout=20)
            return clients[index].post(
                "/api/student/select",
                headers=student_headers(payloads[index], activity_id),
                json={"group_id": group["id"]},
            )

        with ThreadPoolExecutor(max_workers=150) as pool:
            responses = list(pool.map(submit, range(150)))

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


def test_activation_reset_cannot_race_heartbeat_into_reviving_old_session(
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
        [("20560001", "Heartbeat Reset Race", "HEARTRST")],
    )
    assert imported.status_code == 200, imported.text
    student, login = login_student(
        app,
        student_no="20560001",
        name="Heartbeat Reset Race",
        activation_code="HEARTRST",
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
    pause_lock = threading.Lock()
    paused_once = False

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            nonlocal paused_once
            should_pause = False
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                with pause_lock:
                    if not paused_once:
                        paused_once = True
                        should_pause = True
            if should_pause:
                heartbeat_waiting.set()
                assert allow_heartbeat.wait(timeout=10)
            return self._connection.execute(sql, parameters)

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
            reset = client.post(
                f"/api/admin/students/{student_id}/activation-code",
                headers=admin_headers,
            )
            assert reset.status_code == 200, reset.text
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
        [("20560002", "Heartbeat Rollover Race", "HEARTROL")],
    )
    assert imported.status_code == 200, imported.text
    student, login = login_student(
        app,
        student_no="20560002",
        name="Heartbeat Rollover Race",
        activation_code="HEARTROL",
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
    pause_lock = threading.Lock()
    paused_once = False

    class ConnectionProxy:
        def __init__(self, connection):
            self._connection = connection

        def execute(self, sql, parameters=()):
            nonlocal paused_once
            should_pause = False
            if sql.strip().upper() == "BEGIN IMMEDIATE":
                with pause_lock:
                    if not paused_once:
                        paused_once = True
                        should_pause = True
            if should_pause:
                heartbeat_waiting.set()
                assert allow_heartbeat.wait(timeout=10)
            return self._connection.execute(sql, parameters)

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


def test_migrated_hash_only_rows_are_maintenance_compatible(app_config):
    """A v0 fixture is covered elsewhere; this pins nullable ciphertext semantics."""
    from server.database import initialize_database
    from server.maintenance import check_database, migrate_and_check
    from server.security import activation_code_hash

    initialize_database(app_config)
    connection = connect(app_config.database_path)
    try:
        major_id = int(connection.execute("SELECT id FROM majors ORDER BY id LIMIT 1").fetchone()[0])
        now = "2026-01-01T00:00:00+00:00"
        connection.execute(
            """
            INSERT INTO students
                (student_no, name, major_id, activation_hash, activation_ciphertext,
                 active, created_at, updated_at)
            VALUES ('legacy-hash-only', 'Legacy Hash Only', ?, ?, NULL, 1, ?, ?)
            """,
            (
                major_id,
                activation_code_hash(app_config.app_secret, "HASHONLY"),
                now,
                now,
            ),
        )
    finally:
        connection.close()

    assert check_database(app_config.database_path) == "ok"
    assert migrate_and_check(app_config) == "MIGRATION_CHECK_OK"
    connection = sqlite3.connect(app_config.database_path)
    try:
        assert connection.execute(
            "SELECT activation_ciphertext FROM students WHERE student_no = 'legacy-hash-only'"
        ).fetchone()[0] is None
    finally:
        connection.close()
