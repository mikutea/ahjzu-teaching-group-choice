from __future__ import annotations

import csv
import io
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from server.database import connect
from server.maintenance import check_database

from .conftest import fictional_document_number


ROSTER_PATH = (
    Path(__file__).resolve().parents[1]
    / "examples"
    / "fictional-students-180.csv"
)
SHARED_STUDENT_IP = "198.51.100.23"
CONCURRENCY = 60


def load_fictional_roster() -> tuple[bytes, list[dict[str, str]]]:
    content = ROSTER_PATH.read_bytes()
    reader = csv.DictReader(io.StringIO(content.decode("utf-8-sig")))
    assert reader.fieldnames == ["学号", "姓名", "专业"]
    rows = list(reader)
    assert len(rows) == 180
    assert [row["学号"] for row in rows] == [
        f"TEST2026{index:04d}" for index in range(1, 181)
    ]
    assert [row["姓名"] for row in rows] == [
        f"虚构学生{index:03d}" for index in range(1, 181)
    ]
    assert Counter(row["专业"] for row in rows) == {
        "建筑学": 60,
        "城乡规划": 60,
        "风景园林": 60,
    }
    # The checked-in fixture intentionally carries no identity number.  Add only
    # deterministic H-prefixed synthetic values in memory for API validation.
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=["学号", "姓名", "专业", "证件号"])
    writer.writeheader()
    enriched_rows: list[dict[str, str]] = []
    for row in rows:
        enriched = {
            **row,
            "证件号": fictional_document_number(row["学号"]),
        }
        enriched_rows.append(enriched)
        writer.writerow(enriched)
    return output.getvalue().encode("utf-8-sig"), enriched_rows


def assert_all_ok(label: str, responses) -> None:
    server_errors = [
        (index, response.status_code, response.text)
        for index, response in enumerate(responses)
        if response.status_code >= 500
    ]
    assert not server_errors, f"{label} returned 5xx: {server_errors[:5]}"
    failures = [
        (index, response.status_code, response.text)
        for index, response in enumerate(responses)
        if response.status_code != 200
    ]
    assert not failures, f"{label} failed: {failures[:5]}"


def assert_activation_codes_are_not_plaintext(database_path: Path, codes: set[str]) -> None:
    connection = connect(database_path)
    try:
        hashes = [
            str(row["activation_hash"])
            for row in connection.execute(
                "SELECT activation_hash FROM students ORDER BY student_no"
            ).fetchall()
        ]
        logical_dump = "\n".join(connection.iterdump())
    finally:
        connection.close()

    assert len(hashes) == 180
    assert len(set(hashes)) == 180
    assert all(re.fullmatch(r"[0-9a-f]{64}", value) for value in hashes)
    assert codes.isdisjoint(hashes)
    assert not [code for code in codes if code in logical_dump]


def test_fictional_roster_full_concurrent_multi_activity_flow(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    roster_bytes, roster = load_fictional_roster()
    dashboard = client.get("/api/admin/dashboard").json()
    activity_id = int(dashboard["settings"]["activity_id"])
    assert int(admin_headers["X-Activity-ID"]) == activity_id
    assert len(dashboard["majors"]) == 3
    assert len(dashboard["groups"]) == 6
    assert {major["name"] for major in dashboard["majors"]} == {
        row["专业"] for row in roster
    }

    groups = sorted(dashboard["groups"], key=lambda row: (row["sort_order"], row["id"]))
    for group in groups:
        configured = client.patch(
            f"/api/admin/groups/{group['id']}",
            headers=admin_headers,
            json={"total_capacity": 30},
        )
        assert configured.status_code == 200, configured.text
    for quota in dashboard["quotas"]:
        configured = client.put(
            f"/api/admin/quotas/{quota['major_id']}/{quota['group_id']}",
            headers=admin_headers,
            json={"capacity": 10},
        )
        assert configured.status_code == 200, configured.text

    configured_dashboard = client.get("/api/admin/dashboard").json()
    assert all(group["total_capacity"] == 30 for group in configured_dashboard["groups"])
    assert len(configured_dashboard["quotas"]) == 18
    assert all(quota["capacity"] == 10 for quota in configured_dashboard["quotas"])

    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        params={"mode": "merge"},
        files={
            "file": (
                ROSTER_PATH.name,
                roster_bytes,
                "text/csv",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    result = imported.json()
    assert result["created"] == 180
    assert result["updated"] == 0
    assert result["deactivated"] == 0
    assert "credentials" not in result
    assert '"activation_code":' not in imported.text
    assert not any(row["证件号"] in imported.text for row in roster)

    codes = {row["证件号"][-6:] for row in roster}
    assert len(codes) == 180
    assert codes == {row["证件号"][-6:] for row in roster}
    assert all(re.fullmatch(r"\d{6}", code) for code in codes)
    assert_activation_codes_are_not_plaintext(app_config.database_path, codes)

    ready_dashboard = client.get("/api/admin/dashboard").json()
    assert ready_dashboard["totals"] == {
        "students": 180,
        "selected": 0,
        "unselected": 180,
    }
    assert ready_dashboard["readiness"]["ready"] is True
    assert ready_dashboard["readiness"]["blockers"] == []
    opened = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "open"},
    )
    assert opened.status_code == 200, opened.text

    student_clients = [
        TestClient(app, client=(SHARED_STUDENT_IP, 40000 + index))
        for index in range(180)
    ]
    try:
        def login(index: int):
            row = roster[index]
            return student_clients[index].post(
                "/api/student/login",
                json={
                    "student_no": row["学号"],
                    "name": row["姓名"],
                    "activation_code": row["证件号"][-6:],
                },
            )

        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            login_responses = list(pool.map(login, range(180)))
        assert_all_ok("student login", login_responses)
        login_payloads = [response.json() for response in login_responses]
        for index, payload in enumerate(login_payloads):
            assert payload["student"]["student_no"] == roster[index]["学号"]
            assert payload["student"]["major_name"] == roster[index]["专业"]

        target_group_by_index = {
            index: groups[(index % 60) // 10]["id"]
            for index in range(180)
        }

        def select(index: int):
            return student_clients[index].post(
                "/api/student/select",
                headers={
                    "X-CSRF-Token": login_payloads[index]["csrf_token"],
                    "X-Activity-ID": str(activity_id),
                },
                json={"group_id": target_group_by_index[index]},
            )

        interleaved_order = [
            major_index * 60 + local_index
            for local_index in range(60)
            for major_index in range(3)
        ]
        with ThreadPoolExecutor(max_workers=CONCURRENCY) as pool:
            selection_responses = list(pool.map(select, interleaved_order))
        assert_all_ok("student selection", selection_responses)

        selected_dashboard = client.get("/api/admin/dashboard").json()
        assert selected_dashboard["totals"] == {
            "students": 180,
            "selected": 180,
            "unselected": 0,
        }
        assert all(major["selected_count"] == 60 for major in selected_dashboard["majors"])
        assert all(group["selected_count"] == 30 for group in selected_dashboard["groups"])
        assert len(selected_dashboard["quotas"]) == 18
        assert all(
            quota["capacity"] == 10 and quota["selected_count"] == 10
            for quota in selected_dashboard["quotas"]
        )

        exported = client.get(
            "/api/admin/export/selections.csv",
            params={"activity_id": activity_id},
        )
        assert exported.status_code == 200, exported.text
        exported_rows = list(
            csv.DictReader(io.StringIO(exported.content.decode("utf-8-sig")))
        )
        assert len(exported_rows) == 180
        assert {row["学号"] for row in exported_rows} == {
            row["学号"] for row in roster
        }

        unselected_export = client.get(
            "/api/admin/export/unselected.csv",
            params={"activity_id": activity_id},
        )
        assert unselected_export.status_code == 200, unselected_export.text
        assert len(
            list(csv.reader(io.StringIO(unselected_export.content.decode("utf-8-sig"))))
        ) == 1

        closed = client.post(
            "/api/admin/status",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert closed.status_code == 200, closed.text
        rolled = client.post(
            "/api/admin/activities",
            headers=admin_headers,
            json={
                "title": "下一轮虚构学生并发验收",
                "code": "fictional-flow-next",
                "copy_structure": True,
                "previous_activity_id": activity_id,
            },
        )
        assert rolled.status_code == 200, rolled.text
        new_activity_id = int(rolled.json()["activity_id"])
        assert new_activity_id != activity_id

        assert student_clients[0].get("/api/student/me").status_code == 401
        stale_activity = client.post(
            "/api/admin/status",
            headers=admin_headers,
            json={"status": "closed"},
        )
        assert stale_activity.status_code == 409, stale_activity.text

        archive_response = client.get(
            f"/api/admin/activities/{activity_id}/archive.json"
        )
        assert archive_response.status_code == 200, archive_response.text
        archive = archive_response.json()
        assert len(archive["students"]) == 180
        assert len(archive["selections"]) == 180
        assert all(row["revoked_at"] is None for row in archive["selections"])

        next_dashboard = client.get("/api/admin/dashboard").json()
        assert next_dashboard["settings"]["activity_id"] == new_activity_id
        assert next_dashboard["totals"] == {
            "students": 0,
            "selected": 0,
            "unselected": 0,
        }
        assert len(next_dashboard["majors"]) == 3
        assert len(next_dashboard["groups"]) == 6
        assert check_database(app_config.database_path) == "ok"
    finally:
        for student_client in student_clients:
            student_client.close()
