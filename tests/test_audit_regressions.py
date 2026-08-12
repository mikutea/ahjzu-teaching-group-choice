from __future__ import annotations

import csv
import io
import threading
from concurrent.futures import ThreadPoolExecutor
from time import sleep

from fastapi.testclient import TestClient

import server.main as main_module


def import_students(
    client: TestClient,
    headers: dict[str, str],
    csv_text: str,
    *,
    mode: str = "merge",
    regenerate_existing: bool = False,
):
    return client.post(
        "/api/admin/students/import",
        headers=headers,
        params={
            "mode": mode,
            "regenerate_existing": str(regenerate_existing).lower(),
        },
        files={"file": ("students.csv", csv_text.encode("utf-8"), "text/csv")},
    )


def login_student(client: TestClient, *, student_no: str, name: str, code: str):
    return client.post(
        "/api/student/login",
        json={"student_no": student_no, "name": name, "activation_code": code},
    )


def decode_csv(response) -> list[list[str]]:
    assert response.status_code == 200, response.text
    return list(csv.reader(io.StringIO(response.content.decode("utf-8-sig"))))


def test_sixty_students_behind_one_ip_can_all_log_in(
    app, client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    rows = ["student_no,name,major,activation_code"]
    rows.extend(
        f"2031{index:04d},同网学生{index:02d},{major_name},NAT{index:05d}"
        for index in range(60)
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
            student_no=f"2031{index:04d}",
            name=f"同网学生{index:02d}",
            code=f"NAT{index:05d}",
        )

    try:
        with ThreadPoolExecutor(max_workers=len(students)) as pool:
            responses = list(pool.map(login, range(len(students))))
    finally:
        for student in students:
            student.close()

    failures = [(response.status_code, response.text) for response in responses if response.status_code != 200]
    assert not failures


def test_activation_code_rotation_invalidates_old_session_and_old_code(
    app, client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    imported = import_students(
        client,
        admin_headers,
        "student_no,name,major,activation_code\n"
        f"20320001,轮换学生,{major_name},OLD20001\n",
    )
    assert imported.status_code == 200, imported.text

    student = TestClient(app)
    try:
        login = login_student(
            student,
            student_no="20320001",
            name="轮换学生",
            code="OLD20001",
        )
        assert login.status_code == 200, login.text
        student_id = login.json()["student"]["id"]

        reset = client.post(
            f"/api/admin/students/{student_id}/activation-code",
            headers=admin_headers,
        )
        assert reset.status_code == 200, reset.text
        assert reset.json().keys() == {"credential"}
        credential = reset.json()["credential"]
        assert credential.keys() == {"student_no", "name", "major", "activation_code"}
        assert credential["student_no"] == "20320001"
        assert credential["name"] == "轮换学生"
        assert credential["major"] == major_name
        assert credential["activation_code"] != "OLD20001"

        assert student.get("/api/student/me").status_code == 401
        old_code_client = TestClient(app)
        try:
            old_code_login = login_student(
                old_code_client,
                student_no="20320001",
                name="轮换学生",
                code="OLD20001",
            )
            assert old_code_login.status_code == 401
        finally:
            old_code_client.close()

        replacement = TestClient(app)
        try:
            new_code_login = login_student(
                replacement,
                student_no="20320001",
                name="轮换学生",
                code=credential["activation_code"],
            )
            assert new_code_login.status_code == 200, new_code_login.text
        finally:
            replacement.close()
    finally:
        student.close()


def test_regenerate_existing_import_invalidates_session_and_returns_new_credential(
    app, client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    first = import_students(
        client,
        admin_headers,
        "student_no,name,major,activation_code\n"
        f"20320002,批量轮换,{major_name},OLD20002\n",
    )
    assert first.status_code == 200, first.text

    student = TestClient(app)
    try:
        assert login_student(
            student,
            student_no="20320002",
            name="批量轮换",
            code="OLD20002",
        ).status_code == 200

        rotated = import_students(
            client,
            admin_headers,
            "student_no,name,major,activation_code\n"
            f"20320002,批量轮换,{major_name},\n",
            mode="merge",
            regenerate_existing=True,
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["updated"] == 1
        assert len(rotated.json()["credentials"]) == 1
        new_code = rotated.json()["credentials"][0]["activation_code"]
        assert new_code and new_code != "OLD20002"
        assert student.get("/api/student/me").status_code == 401
        old_code_client = TestClient(app)
        try:
            assert login_student(
                old_code_client,
                student_no="20320002",
                name="批量轮换",
                code="OLD20002",
            ).status_code == 401
        finally:
            old_code_client.close()
    finally:
        student.close()


def test_sync_import_deactivates_omitted_student_and_invalidates_session(
    app, client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    initial = import_students(
        client,
        admin_headers,
        "student_no,name,major,activation_code\n"
        f"20320003,保留学生,{major_name},SYNC2003\n"
        f"20320004,遗漏学生,{major_name},SYNC2004\n",
    )
    assert initial.status_code == 200, initial.text

    omitted = TestClient(app)
    try:
        assert login_student(
            omitted,
            student_no="20320004",
            name="遗漏学生",
            code="SYNC2004",
        ).status_code == 200

        synchronized = import_students(
            client,
            admin_headers,
            "student_no,name,major,activation_code\n"
            f"20320003,保留学生,{major_name},\n",
            mode="sync",
        )
        assert synchronized.status_code == 200, synchronized.text
        assert omitted.get("/api/student/me").status_code == 401
        assert login_student(
            omitted,
            student_no="20320004",
            name="遗漏学生",
            code="SYNC2004",
        ).status_code == 401

        students = {
            row["student_no"]: row
            for row in client.get("/api/admin/dashboard").json()["students"]
        }
        assert students["20320003"]["active"] == 1
        assert students["20320004"]["active"] == 0
    finally:
        omitted.close()


def test_csv_exports_neutralize_formula_cells(
    client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    group_id = dashboard["groups"][0]["id"]
    formula_name = "=HYPERLINK(\"https://example.invalid\",\"打开\")"
    rows = [
        ["student_no", "name", "major", "activation_code"],
        ["+20330001", formula_name, major_name, "FORMULA1"],
        ["-20330002", "@SUM(1,1)", major_name, "FORMULA2"],
    ]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    imported = import_students(client, admin_headers, buffer.getvalue())
    assert imported.status_code == 200, imported.text

    imported_students = {
        row["student_no"]: row for row in client.get("/api/admin/dashboard").json()["unselected_students"]
    }
    assigned = client.post(
        "/api/admin/selections",
        headers=admin_headers,
        json={"student_id": imported_students["+20330001"]["id"], "group_id": group_id},
    )
    assert assigned.status_code == 200, assigned.text

    activity_params = {"activity_id": dashboard["settings"]["activity_id"]}
    selection_rows = decode_csv(
        client.get("/api/admin/export/selections.csv", params=activity_params)
    )
    unselected_rows = decode_csv(
        client.get("/api/admin/export/unselected.csv", params=activity_params)
    )
    assert selection_rows[1][0] == "'+20330001"
    assert selection_rows[1][1] == "'" + formula_name
    assert unselected_rows[1][0] == "'-20330002"
    assert unselected_rows[1][1] == "'@SUM(1,1)"


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
        "student_no,name,major,activation_code\n"
        f"20340001,就绪学生,{major_name},READY001\n",
    )
    assert imported.status_code == 200, imported.text
    ready = client.get("/api/admin/dashboard").json()["readiness"]
    assert ready["ready"] is True, ready
    assert ready["blockers"] == []

    opened = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "open"},
    )
    assert opened.status_code == 200, opened.text


def test_dashboard_exposes_students_for_sync_review(
    client: TestClient, admin_headers: dict[str, str]
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_name = dashboard["majors"][0]["name"]
    imported = import_students(
        client,
        admin_headers,
        "student_no,name,major,activation_code\n"
        f"20350001,名单甲,{major_name},SYNC0001\n"
        f"20350002,名单乙,{major_name},SYNC0002\n",
    )
    assert imported.status_code == 200, imported.text

    refreshed = client.get("/api/admin/dashboard").json()
    by_number = {student["student_no"]: student for student in refreshed["students"]}
    assert {"20350001", "20350002"} <= by_number.keys()
    for student_no in ("20350001", "20350002"):
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
