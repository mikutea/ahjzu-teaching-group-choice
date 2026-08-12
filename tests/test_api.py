from __future__ import annotations

import hashlib
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from .conftest import admin_login
from server.database import connect, initialize_database
from server.maintenance import (
    check_database,
    create_backup,
    migrate_and_check,
    migration_business_digest,
)


def test_health_and_public_branding(client: TestClient):
    assert client.get("/api/health").json() == {"status": "ok"}
    info = client.get("/api/public/info")
    assert info.status_code == 200
    assert info.json()["settings"]["organization_name"] == "安徽建筑大学 · 建筑与空间规划学院"
    assert info.json()["group_count"] == 6


def test_professional_and_group_counts_are_dynamic(client: TestClient, admin_headers: dict[str, str]):
    initial = client.get("/api/admin/dashboard").json()
    assert len(initial["majors"]) == 3
    assert len(initial["groups"]) == 6
    assert len(initial["quotas"]) == 18

    major = client.post("/api/admin/majors", headers=admin_headers, json={"name": "室内设计"})
    assert major.status_code == 200, major.text
    group = client.post(
        "/api/admin/groups",
        headers=admin_headers,
        json={"name": "数字建造教学组", "total_capacity": 12},
    )
    assert group.status_code == 200, group.text

    expanded = client.get("/api/admin/dashboard").json()
    assert len(expanded["majors"]) == 4
    assert len(expanded["groups"]) == 7
    assert len(expanded["quotas"]) == 28

    major_id = major.json()["id"]
    group_id = group.json()["id"]
    renamed = client.patch(
        f"/api/admin/majors/{major_id}",
        headers=admin_headers,
        json={"name": "环境设计", "active": True},
    )
    assert renamed.status_code == 200, renamed.text
    quota = client.put(
        f"/api/admin/quotas/{major_id}/{group_id}",
        headers=admin_headers,
        json={"capacity": 5},
    )
    assert quota.status_code == 200, quota.text

    assert client.delete(f"/api/admin/groups/{group_id}", headers=admin_headers).status_code == 200
    assert client.delete(f"/api/admin/majors/{major_id}", headers=admin_headers).status_code == 200
    reduced = client.get("/api/admin/dashboard").json()
    assert len(reduced["majors"]) == 3
    assert len(reduced["groups"]) == 6
    assert len(reduced["quotas"]) == 18


def test_structure_is_locked_while_open(client: TestClient, admin_headers: dict[str, str]):
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "file": (
                "student.csv",
                f"学号,姓名,专业\n20260000,结构锁测试,{major_name}\n".encode("utf-8"),
                "text/csv",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    assert client.post("/api/admin/status", headers=admin_headers, json={"status": "open"}).status_code == 200
    blocked = client.post("/api/admin/majors", headers=admin_headers, json={"name": "不可新增"})
    assert blocked.status_code == 409
    assert "关闭抢选" in blocked.json()["detail"]


def test_csrf_is_required_for_admin_mutation(client: TestClient):
    admin_login(client)
    response = client.post("/api/admin/majors", json={"name": "缺少校验"})
    assert response.status_code == 403


def test_admin_qr_is_generated_from_configured_public_url(
    client: TestClient, admin_headers: dict[str, str]
):
    response = client.get("/api/admin/qr.png")
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_online_backup_passes_integrity_check(app, app_config, tmp_path):
    backup = create_backup(app_config.database_path, tmp_path / "backups", retain=3)
    assert backup.exists()
    assert check_database(backup) == "ok"


def test_new_activity_archives_history_and_resets_roster(
    client: TestClient, admin_headers: dict[str, str], app_config
):
    dashboard = client.get("/api/admin/dashboard").json()
    first_activity = dashboard["settings"]["activity_id"]
    major = dashboard["majors"][0]
    group = dashboard["groups"][0]
    csv_text = f"学号,姓名,专业,激活码\n20260099,归档测试,{major['name']},ARCH1234\n"
    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={"file": ("students.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    old_student_client = TestClient(client.app)
    old_login = old_student_client.post(
        "/api/student/login",
        json={"student_no": "20260099", "name": "归档测试", "activation_code": "ARCH1234"},
    )
    assert old_login.status_code == 200, old_login.text
    student = client.get("/api/admin/dashboard").json()["unselected_students"][0]
    assigned = client.post(
        "/api/admin/selections",
        headers=admin_headers,
        json={"student_id": student["id"], "group_id": group["id"]},
    )
    assert assigned.status_code == 200, assigned.text

    created = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "2027级教学组线上抢选",
            "code": "2027",
            "copy_structure": True,
            "previous_activity_id": first_activity,
        },
    )
    assert created.status_code == 200, created.text
    current = client.get("/api/admin/dashboard").json()
    assert current["settings"]["activity_title"] == "2027级教学组线上抢选"
    assert current["totals"] == {"students": 0, "selected": 0, "unselected": 0}
    assert old_student_client.get("/api/student/me").status_code == 401
    assert len(current["majors"]) == len(dashboard["majors"])
    assert len(current["groups"]) == len(dashboard["groups"])

    archived = next(item for item in current["activities"] if item["id"] == first_activity)
    assert archived["status"] == "archived"
    assert archived["summary"] == {"students": 1, "selected": 1, "unselected": 0}
    archive = client.get(f"/api/admin/activities/{first_activity}/archive.json")
    assert archive.status_code == 200
    archive_data = archive.json()
    assert archive_data["students"][0]["student_no"] == "20260099"
    assert archive_data["selections"][0]["group_name"] == group["name"]
    assert len(archive.headers["X-Archive-SHA256"]) == 64
    assert hashlib.sha256(archive.content).hexdigest() == archive.headers["X-Archive-SHA256"]

    reimported = client.post(
        "/api/admin/students/import",
        headers={
            **admin_headers,
            "X-Activity-ID": str(current["settings"]["activity_id"]),
        },
        files={
            "file": (
                "students.csv",
                f"学号,姓名,专业,激活码\n20260099,新活动同学,{major['name']},NEXT1234\n".encode("utf-8"),
                "text/csv",
            )
        },
    )
    assert reimported.status_code == 200, reimported.text
    assert reimported.json()["created"] == 1
    unchanged_archive = client.get(f"/api/admin/activities/{first_activity}/archive.json").json()
    assert unchanged_archive["students"][0]["name"] == "归档测试"

    tamper = connect(app_config.database_path)
    try:
        tamper.execute(
            "UPDATE activities SET snapshot_json = snapshot_json || ' ' WHERE id = ?",
            (first_activity,),
        )
    finally:
        tamper.close()
    with pytest.raises(RuntimeError, match="SHA-256"):
        check_database(app_config.database_path)


def test_new_activity_requires_current_activity_closed(client: TestClient, admin_headers: dict[str, str]):
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = dashboard["settings"]["activity_id"]
    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "file": (
                "student.csv",
                f"学号,姓名,专业\n20260000,活动状态测试,{dashboard['majors'][0]['name']}\n".encode(
                    "utf-8"
                ),
                "text/csv",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    assert client.post(
        "/api/admin/status", headers=admin_headers, json={"status": "open"}
    ).status_code == 200
    blocked = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "不应创建",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert blocked.status_code == 409


def test_concurrent_new_activity_requests_archive_only_once(app):
    with TestClient(app) as first, TestClient(app) as second:
        csrf = admin_login(first)
        second.cookies.update(first.cookies)
        activity_id = first.get("/api/admin/dashboard").json()["settings"]["activity_id"]
        headers = {
            "X-CSRF-Token": csrf,
            "X-Activity-ID": str(activity_id),
        }
        payload = {
            "title": "并发创建测试",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        }
        barrier = threading.Barrier(2)

        def create(test_client: TestClient):
            barrier.wait(timeout=5)
            return test_client.post(
                "/api/admin/activities",
                headers=headers,
                json=payload,
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(create, (first, second)))

        assert sorted(response.status_code for response in responses) == [200, 409]
        activities = first.get("/api/admin/activities").json()
        assert len(activities) == 2
        assert sum(1 for activity in activities if activity["status"] == "archived") == 1
        assert sum(1 for activity in activities if activity["current"]) == 1


def test_stale_activity_header_cannot_mutate_new_activity(
    client: TestClient, admin_headers: dict[str, str]
):
    old_activity_id = int(admin_headers["X-Activity-ID"])
    created = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "新活动",
            "copy_structure": True,
            "previous_activity_id": old_activity_id,
        },
    )
    assert created.status_code == 200, created.text
    new_activity_id = created.json()["activity_id"]

    stale_status = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "open"},
    )
    assert stale_status.status_code == 409
    stale_major = client.post(
        "/api/admin/majors",
        headers=admin_headers,
        json={"name": "不应写入新活动"},
    )
    assert stale_major.status_code == 409

    dashboard = client.get("/api/admin/dashboard").json()
    assert dashboard["settings"]["activity_id"] == new_activity_id
    assert dashboard["settings"]["status"] == "closed"
    assert all(major["name"] != "不应写入新活动" for major in dashboard["majors"])


def test_activity_mutation_requires_valid_activity_header(client: TestClient):
    csrf = admin_login(client)
    missing = client.post(
        "/api/admin/status",
        headers={"X-CSRF-Token": csrf},
        json={"status": "open"},
    )
    assert missing.status_code == 428
    malformed = client.post(
        "/api/admin/status",
        headers={"X-CSRF-Token": csrf, "X-Activity-ID": "not-an-id"},
        json={"status": "open"},
    )
    assert malformed.status_code == 400
    assert client.get("/api/admin/dashboard").json()["settings"]["status"] == "closed"


def test_check_database_rejects_missing_or_empty_database(tmp_path):
    missing = tmp_path / "missing.db"
    with pytest.raises(RuntimeError, match="不存在或为空"):
        check_database(missing)
    assert not missing.exists()

    empty = tmp_path / "empty.db"
    empty.touch()
    with pytest.raises(RuntimeError, match="不存在或为空"):
        check_database(empty)


def test_existing_single_activity_database_migrates_without_losing_settings(app_config):
    database_path = app_config.database_path
    connection = sqlite3.connect(database_path)
    connection.executescript(
        """
        CREATE TABLE settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            activity_title TEXT NOT NULL,
            organization_name TEXT NOT NULL,
            owner_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (status IN ('closed', 'open')),
            public_base_url TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE audit_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            occurred_at TEXT NOT NULL,
            actor_type TEXT NOT NULL,
            actor_id TEXT NOT NULL,
            action TEXT NOT NULL,
            entity_type TEXT NOT NULL,
            entity_id TEXT NOT NULL,
            details_json TEXT NOT NULL
        );
        INSERT INTO settings VALUES (
            1, '旧版活动', '安徽建筑大学 · 建筑与空间规划学院', 'Mikutea',
            'closed', 'https://choice.example.com', '2026-01-01T00:00:00+00:00',
            '2026-01-01T00:00:00+00:00'
        );
        INSERT INTO audit_logs
            (occurred_at, actor_type, actor_id, action, entity_type, entity_id, details_json)
        VALUES ('2026-01-01T00:00:00+00:00', 'admin', '1', 'legacy.event', 'settings', '1', '{}');
        """
    )
    connection.close()

    initialize_database(app_config)
    migrated = connect(database_path)
    try:
        activity = migrated.execute(
            """
            SELECT a.id, a.title, a.status, a.created_at, a.closed_at FROM activities a
            JOIN settings s ON s.current_activity_id = a.id WHERE s.id = 1
            """
        ).fetchone()
        assert dict(activity) == {
            "id": 1,
            "title": "旧版活动",
            "status": "closed",
            "created_at": "2026-01-01T00:00:00+00:00",
            "closed_at": "2026-01-01T00:00:00+00:00",
        }
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 2
        assert migrated.execute(
            "SELECT activity_id FROM audit_logs WHERE action = 'legacy.event'"
        ).fetchone()[0] == 1
        assert migrated.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    finally:
        migrated.close()


def test_complete_v0_database_migrates_without_changing_business_rows(app_config):
    database_path = app_config.database_path
    schema_path = Path(__file__).parent / "fixtures" / "schema_v0.sql"
    connection = sqlite3.connect(database_path)
    connection.executescript(schema_path.read_text(encoding="utf-8"))
    connection.executescript(
        """
        INSERT INTO settings VALUES (
            1, '完整旧库', '安徽建筑大学 · 建筑与空间规划学院', 'Mikutea',
            'closed', 'https://choice.example.com', '2026-01-01T00:00:00+00:00',
            '2026-01-01T00:00:00+00:00'
        );
        INSERT INTO majors VALUES (
            1, 'major-1', '建筑学', 1, 10,
            '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
        );
        INSERT INTO teaching_groups VALUES (
            1, 'group-1', '第一教学组', 1, 1, 10,
            '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
        );
        INSERT INTO quotas VALUES (1, 1, 1, '2026-01-01T00:00:00+00:00');
        INSERT INTO students VALUES (
            1, '20260001', '旧库学生', 1, 'activation-hash', 1,
            '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
        );
        INSERT INTO selections VALUES (
            1, 1, 1, '2026-01-01T00:00:00+00:00', 'student', '1', NULL, NULL
        );
        INSERT INTO admin_users VALUES (
            1, 'admin', 'password-hash',
            '2026-01-01T00:00:00+00:00', '2026-01-01T00:00:00+00:00'
        );
        INSERT INTO sessions VALUES (
            'token-hash', 'student', 1, 'csrf',
            '2026-01-01T00:00:00+00:00', '2099-01-01T00:00:00+00:00'
        );
        INSERT INTO audit_logs
            (occurred_at, actor_type, actor_id, action, entity_type, entity_id, details_json)
        VALUES (
            '2026-01-01T00:00:00+00:00', 'student', '1',
            'selection.create', 'selection', '1', '{}'
        );
        """
    )
    connection.close()

    before = migration_business_digest(database_path)
    assert migrate_and_check(app_config) == "MIGRATION_CHECK_OK"
    assert migration_business_digest(database_path) == before
    migrated = connect(database_path)
    try:
        assert migrated.execute("PRAGMA user_version").fetchone()[0] == 2
        assert migrated.execute("SELECT COUNT(*) FROM activities").fetchone()[0] == 1
        assert migrated.execute("SELECT COUNT(*) FROM selections").fetchone()[0] == 1
        assert migrated.execute("SELECT activity_id FROM audit_logs").fetchone()[0] == 1
    finally:
        migrated.close()


def test_legacy_v0_writes_stay_synchronized_after_migration(app_config):
    initialize_database(app_config)
    connection = connect(app_config.database_path)
    try:
        connection.execute(
            """
            UPDATE settings SET activity_title = '旧镜像改名', status = 'open',
                updated_at = '2030-01-02T03:04:05+00:00' WHERE id = 1
            """
        )
        connection.execute(
            """
            INSERT INTO audit_logs
                (occurred_at, actor_type, actor_id, action, entity_type, entity_id, details_json)
            VALUES (
                '2026-08-13T00:00:00+00:00', 'admin', '1', 'legacy.write',
                'settings', '1', '{}'
            )
            """
        )
        activity = connection.execute(
            "SELECT id, title, status, opened_at FROM activities WHERE status <> 'archived'"
        ).fetchone()
        assert activity["title"] == "旧镜像改名"
        assert activity["status"] == "open"
        assert activity["opened_at"] == "2030-01-02T03:04:05+00:00"
        assert connection.execute(
            "SELECT activity_id FROM audit_logs WHERE action = 'legacy.write'"
        ).fetchone()[0] == activity["id"]
    finally:
        connection.close()


def test_future_database_version_is_rejected_without_downgrade(app_config):
    initialize_database(app_config)
    connection = connect(app_config.database_path)
    try:
        connection.execute("PRAGMA user_version = 99")
    finally:
        connection.close()

    with pytest.raises(RuntimeError, match="高于应用支持版本"):
        initialize_database(app_config)
    connection = sqlite3.connect(app_config.database_path)
    try:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 99
    finally:
        connection.close()


def test_backup_rejects_missing_source_without_creating_files(tmp_path):
    source = tmp_path / "missing.db"
    backup_dir = tmp_path / "backups"
    with pytest.raises(RuntimeError, match="不存在或为空"):
        create_backup(source, backup_dir)
    assert not source.exists()
    assert not backup_dir.exists()


def test_two_students_competing_for_last_seat_yields_one_success(app):
    with TestClient(app) as admin_client:
        csrf = admin_login(admin_client)
        dashboard = admin_client.get("/api/admin/dashboard").json()
        admin_headers = {
            "X-CSRF-Token": csrf,
            "X-Activity-ID": str(dashboard["settings"]["activity_id"]),
        }
        major = dashboard["majors"][0]
        group = dashboard["groups"][0]

        quota = admin_client.put(
            f"/api/admin/quotas/{major['id']}/{group['id']}",
            headers=admin_headers,
            json={"capacity": 1},
        )
        assert quota.status_code == 200, quota.text

        csv_text = (
            "学号,姓名,专业,激活码\n"
            f"20260001,测试甲,{major['name']},AAAA1111\n"
            f"20260002,测试乙,{major['name']},BBBB2222\n"
        )
        imported = admin_client.post(
            "/api/admin/students/import",
            headers=admin_headers,
            files={"file": ("students.csv", csv_text.encode("utf-8"), "text/csv")},
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["created"] == 2
        assert admin_client.post(
            "/api/admin/status", headers=admin_headers, json={"status": "open"}
        ).status_code == 200

        first = TestClient(app)
        second = TestClient(app)
        first_login = first.post(
            "/api/student/login",
            json={"student_no": "20260001", "name": "测试甲", "activation_code": "AAAA1111"},
        )
        second_login = second.post(
            "/api/student/login",
            json={"student_no": "20260002", "name": "测试乙", "activation_code": "BBBB2222"},
        )
        assert first_login.status_code == second_login.status_code == 200
        first_csrf = first_login.json()["csrf_token"]
        second_csrf = second_login.json()["csrf_token"]

        barrier = threading.Barrier(2)

        def submit(test_client: TestClient, csrf: str):
            barrier.wait(timeout=5)
            return test_client.post(
                "/api/student/select",
                headers={
                    "X-CSRF-Token": csrf,
                    "X-Activity-ID": str(dashboard["settings"]["activity_id"]),
                },
                json={"group_id": group["id"]},
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(lambda pair: submit(*pair), [(first, first_csrf), (second, second_csrf)]))

        assert sorted(response.status_code for response in responses) == [200, 409]
        final = admin_client.get("/api/admin/dashboard").json()
        assert final["totals"] == {"students": 2, "selected": 1, "unselected": 1}
        cell = next(
            item for item in final["quotas"]
            if item["major_id"] == major["id"] and item["group_id"] == group["id"]
        )
        assert cell["selected_count"] == 1
        assert len(final["unselected_students"]) == 1


def test_database_trigger_blocks_direct_capacity_bypass(
    client: TestClient, admin_headers: dict[str, str], app_config
):
    dashboard = client.get("/api/admin/dashboard").json()
    major = dashboard["majors"][0]
    group = dashboard["groups"][0]
    assert client.put(
        f"/api/admin/quotas/{major['id']}/{group['id']}",
        headers=admin_headers,
        json={"capacity": 0},
    ).status_code == 200
    csv_text = f"学号,姓名,专业,激活码\n20269999,约束测试,{major['name']},GUARD999\n"
    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={"file": ("students.csv", csv_text.encode("utf-8"), "text/csv")},
    )
    assert imported.status_code == 200, imported.text

    connection = connect(app_config.database_path)
    try:
        student_id = connection.execute(
            "SELECT id FROM students WHERE student_no = '20269999'"
        ).fetchone()["id"]
        with pytest.raises(sqlite3.IntegrityError, match="major quota exceeded"):
            connection.execute(
                """
                INSERT INTO selections
                    (student_id, group_id, selected_at, source, operator)
                VALUES (?, ?, '2026-08-13T00:00:00+00:00', 'admin', 'trigger-test')
                """,
                (student_id, group["id"]),
            )
        assert connection.execute("SELECT COUNT(*) FROM selections").fetchone()[0] == 0

        revoked = connection.execute(
            """
            INSERT INTO selections
                (student_id, group_id, selected_at, source, operator, revoked_at, revoked_by)
            VALUES (?, ?, '2026-08-13T00:00:00+00:00', 'admin', 'trigger-test',
                    '2026-08-13T00:01:00+00:00', 'trigger-test')
            """,
            (student_id, group["id"]),
        )
        with pytest.raises(sqlite3.IntegrityError, match="major quota exceeded"):
            connection.execute(
                "UPDATE selections SET revoked_at = NULL, revoked_by = NULL WHERE id = ?",
                (revoked.lastrowid,),
            )
        assert connection.execute(
            "SELECT COUNT(*) FROM selections WHERE revoked_at IS NULL"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_one_hundred_fifty_students_competing_for_thirty_seats_never_oversells(app):
    with TestClient(app) as admin_client:
        csrf = admin_login(admin_client)
        dashboard = admin_client.get("/api/admin/dashboard").json()
        admin_headers = {
            "X-CSRF-Token": csrf,
            "X-Activity-ID": str(dashboard["settings"]["activity_id"]),
        }
        major = dashboard["majors"][0]
        group = dashboard["groups"][0]
        for quota in dashboard["quotas"]:
            if quota["major_id"] == major["id"]:
                continue
            assert admin_client.put(
                f"/api/admin/quotas/{quota['major_id']}/{quota['group_id']}",
                headers=admin_headers,
                json={"capacity": 0},
            ).status_code == 200
        for quota in dashboard["quotas"]:
            if quota["major_id"] != major["id"]:
                continue
            assert admin_client.put(
                f"/api/admin/quotas/{quota['major_id']}/{quota['group_id']}",
                headers=admin_headers,
                json={"capacity": 30},
            ).status_code == 200
        rows = ["学号,姓名,专业,激活码"]
        for index in range(150):
            rows.append(f"2027{index:04d},并发{index:03d},{major['name']},LOAD{index:04d}")
        imported = admin_client.post(
            "/api/admin/students/import",
            headers=admin_headers,
            files={"file": ("students.csv", ("\n".join(rows) + "\n").encode("utf-8"), "text/csv")},
        )
        assert imported.status_code == 200, imported.text
        assert admin_client.post(
            "/api/admin/status", headers=admin_headers, json={"status": "open"}
        ).status_code == 200

        clients: list[TestClient] = []
        csrf_tokens: list[str] = []
        for index in range(150):
            student_client = TestClient(app)
            login = student_client.post(
                "/api/student/login",
                json={
                    "student_no": f"2027{index:04d}",
                    "name": f"并发{index:03d}",
                    "activation_code": f"LOAD{index:04d}",
                },
            )
            assert login.status_code == 200, login.text
            clients.append(student_client)
            csrf_tokens.append(login.json()["csrf_token"])

        barrier = threading.Barrier(150)

        def submit(index: int):
            barrier.wait(timeout=15)
            return clients[index].post(
                "/api/student/select",
                headers={
                    "X-CSRF-Token": csrf_tokens[index],
                    "X-Activity-ID": str(dashboard["settings"]["activity_id"]),
                },
                json={"group_id": group["id"]},
            )

        with ThreadPoolExecutor(max_workers=150) as pool:
            responses = list(pool.map(submit, range(150)))

        statuses = [response.status_code for response in responses]
        assert statuses.count(200) == 30
        assert statuses.count(409) == 120
        assert not [status for status in statuses if status >= 500]
        final = admin_client.get("/api/admin/dashboard").json()
        cell = next(
            item for item in final["quotas"]
            if item["major_id"] == major["id"] and item["group_id"] == group["id"]
        )
        assert cell["selected_count"] == 30
        assert final["totals"] == {"students": 150, "selected": 30, "unselected": 120}
