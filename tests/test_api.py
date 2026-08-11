from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

from .conftest import admin_login
from server.maintenance import check_database, create_backup


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


def test_two_students_competing_for_last_seat_yields_one_success(app):
    with TestClient(app) as admin_client:
        admin_headers = {"X-CSRF-Token": admin_login(admin_client)}
        dashboard = admin_client.get("/api/admin/dashboard").json()
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
                headers={"X-CSRF-Token": csrf},
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
