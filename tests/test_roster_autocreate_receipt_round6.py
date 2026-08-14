from __future__ import annotations

import base64
import csv
import hashlib
import hmac
import io
import json

from fastapi.testclient import TestClient

import server.main as server_main
from server.database import connect

from .conftest import fictional_activation_code, fictional_document_number, open_selection_now


def signed_receipt_token(secret: str, claims: dict[str, object]) -> str:
    encoded_claims = base64.urlsafe_b64encode(
        json.dumps(
            claims,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"),
        b"selection-receipt-v1\0" + encoded_claims.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    return f"v1.{encoded_claims}.{encoded_signature}"


def roster_csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(["学号", "姓名", "专业名称", "证件号"])
    writer.writerows(rows)
    return output.getvalue().encode("utf-8-sig")


def import_rosters(
    client: TestClient,
    headers: dict[str, str],
    files: list[tuple[str, list[tuple[str, str, str, str]]]],
):
    return client.post(
        "/api/admin/students/import",
        headers=headers,
        files=[
            ("files", (filename, roster_csv(rows), "text/csv"))
            for filename, rows in files
        ],
    )


def test_import_auto_creates_missing_majors_once_across_files(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    response = import_rosters(
        client,
        admin_headers,
        [
            (
                "one.csv",
                [
                    (
                        "20268000001",
                        "自动专业甲",
                        "城乡规划实验班",
                        fictional_document_number("auto-major-1"),
                    ),
                    (
                        "20268000002",
                        "自动专业乙",
                        "城市设计",
                        fictional_document_number("auto-major-2"),
                    ),
                ],
            ),
            (
                "two.csv",
                [
                    (
                        "20268000003",
                        "自动专业丙",
                        "城乡规划实验班",
                        fictional_document_number("auto-major-3"),
                    )
                ],
            ),
        ],
    )
    assert response.status_code == 200, response.text
    assert response.json()["created"] == 3
    assert response.json()["majors_created"] == ["城乡规划实验班", "城市设计"]
    assert response.json()["majors_reactivated"] == []

    dashboard = client.get("/api/admin/dashboard").json()
    imported_majors = {
        major["name"]: major
        for major in dashboard["majors"]
        if major["name"] in {"城乡规划实验班", "城市设计"}
    }
    assert set(imported_majors) == {"城乡规划实验班", "城市设计"}
    assert all(major["active"] for major in imported_majors.values())
    assert {
        student["major_name"] for student in dashboard["students"]
    } >= {"城乡规划实验班", "城市设计"}
    blockers = dashboard["readiness"]["blockers"]
    assert any("城乡规划实验班配额合计 0" in blocker for blocker in blockers)
    assert any("城市设计配额合计 0" in blocker for blocker in blockers)

    connection = connect(app_config.database_path)
    try:
        for major in imported_majors.values():
            quota_count = connection.execute(
                "SELECT COUNT(*) FROM quotas WHERE major_id = ?",
                (major["id"],),
            ).fetchone()[0]
            assert quota_count == len(dashboard["groups"])
        actions = [
            row[0]
            for row in connection.execute(
                "SELECT action FROM audit_logs ORDER BY id"
            ).fetchall()
        ]
    finally:
        connection.close()
    assert actions.count("major.create.import") == 2
    assert actions.count("students.import") == 1


def test_import_rejects_control_char_major_names_without_partial_writes(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    connection = connect(app_config.database_path)
    try:
        counts_before = tuple(
            int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in ("majors", "students", "audit_logs")
        )
    finally:
        connection.close()

    rejected = import_rosters(
        client,
        admin_headers,
        [
            (
                "control-character-major.csv",
                [
                    (
                        "20268000020",
                        "合法对照学生",
                        "合法待创建专业",
                        fictional_document_number("control-major-valid"),
                    ),
                    (
                        "20268000021",
                        "欺骗专业学生",
                        "城乡规划\u202e实验班",
                        fictional_document_number("control-major-invalid"),
                    ),
                ],
            )
        ],
    )

    assert rejected.status_code == 400, rejected.text
    assert rejected.json()["detail"] == (
        "第 1 个文件第 3 行的专业名称无效：文本不能包含控制字符"
    )
    connection = connect(app_config.database_path)
    try:
        counts_after = tuple(
            int(
                connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            )
            for table in ("majors", "students", "audit_logs")
        )
        assert connection.execute(
            "SELECT 1 FROM majors WHERE name IN (?, ?)",
            ("合法待创建专业", "城乡规划\u202e实验班"),
        ).fetchone() is None
    finally:
        connection.close()
    assert counts_after == counts_before


def test_import_reactivates_same_named_inactive_major_with_audit(
    client: TestClient,
    admin_headers: dict[str, str],
):
    created = client.post(
        "/api/admin/majors",
        headers=admin_headers,
        json={"name": "自动恢复专业"},
    )
    assert created.status_code == 200, created.text
    major_id = int(created.json()["id"])
    disabled = client.patch(
        f"/api/admin/majors/{major_id}",
        headers=admin_headers,
        json={"active": False},
    )
    assert disabled.status_code == 200, disabled.text

    imported = import_rosters(
        client,
        admin_headers,
        [
            (
                "reactivate.csv",
                [
                    (
                        "20268000004",
                        "自动恢复学生",
                        "自动恢复专业",
                        fictional_document_number("auto-major-reactivate"),
                    )
                ],
            )
        ],
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["majors_created"] == []
    assert imported.json()["majors_reactivated"] == ["自动恢复专业"]
    major = next(
        row
        for row in client.get("/api/admin/dashboard").json()["majors"]
        if row["id"] == major_id
    )
    assert bool(major["active"]) is True
    actions = [row["action"] for row in client.get("/api/admin/audit").json()]
    assert actions.count("major.reactivate.import") == 1


def test_import_failure_rolls_back_auto_created_majors_students_and_audits(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    dashboard = client.get("/api/admin/dashboard").json()
    original_major = dashboard["majors"][0]
    group = dashboard["groups"][0]
    selected_number = "20268000005"
    selected_document = fictional_document_number("auto-major-rollback-selected")
    seeded = import_rosters(
        client,
        admin_headers,
        [
            (
                "seed.csv",
                [
                    (
                        selected_number,
                        "已有选择学生",
                        original_major["name"],
                        selected_document,
                    )
                ],
            )
        ],
    )
    assert seeded.status_code == 200, seeded.text
    selected_student = client.get("/api/admin/dashboard").json()["students"][0]
    assigned = client.post(
        "/api/admin/selections",
        headers=admin_headers,
        json={"student_id": selected_student["id"], "group_id": group["id"]},
    )
    assert assigned.status_code == 200, assigned.text

    connection = connect(app_config.database_path)
    try:
        audit_count_before = int(
            connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0]
        )
    finally:
        connection.close()

    rejected = import_rosters(
        client,
        admin_headers,
        [
            (
                "rollback.csv",
                [
                    (
                        "20268000006",
                        "应回滚学生",
                        "应回滚专业甲",
                        fictional_document_number("auto-major-rollback-new"),
                    ),
                    (
                        selected_number,
                        "已有选择学生",
                        "应回滚专业乙",
                        selected_document,
                    ),
                ],
            )
        ],
    )
    assert rejected.status_code == 409, rejected.text
    assert "已有选择" in rejected.json()["detail"]

    connection = connect(app_config.database_path)
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM majors WHERE name LIKE '应回滚专业%'"
        ).fetchone()[0] == 0
        assert connection.execute(
            "SELECT COUNT(*) FROM students WHERE student_no = '20268000006'"
        ).fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM audit_logs").fetchone()[0] == audit_count_before
    finally:
        connection.close()


def test_stale_activity_import_cannot_create_major_in_new_activity(
    client: TestClient,
    admin_headers: dict[str, str],
):
    old_activity_id = int(admin_headers["X-Activity-ID"])
    rolled = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "自动专业活动切换",
            "code": "auto-major-rollover",
            "copy_structure": False,
            "previous_activity_id": old_activity_id,
        },
    )
    assert rolled.status_code == 200, rolled.text

    stale = import_rosters(
        client,
        admin_headers,
        [
            (
                "stale.csv",
                [
                    (
                        "20268000007",
                        "过期活动学生",
                        "不应创建专业",
                        fictional_document_number("auto-major-stale"),
                    )
                ],
            )
        ],
    )
    assert stale.status_code == 409, stale.text
    assert "活动已经变化" in stale.json()["detail"]
    dashboard = client.get("/api/admin/dashboard").json()
    assert all(major["name"] != "不应创建专业" for major in dashboard["majors"])
    assert dashboard["students"] == []


def select_one_student(
    client: TestClient,
    admin_headers: dict[str, str],
    *,
    student_no: str,
    student_name: str,
):
    dashboard = client.get("/api/admin/dashboard").json()
    major = dashboard["majors"][0]
    group = dashboard["groups"][0]
    document_number = fictional_document_number(student_no)
    imported = import_rosters(
        client,
        admin_headers,
        [
            (
                "receipt.csv",
                [(student_no, student_name, major["name"], document_number)],
            )
        ],
    )
    assert imported.status_code == 200, imported.text
    quota = client.put(
        f"/api/admin/quotas/{major['id']}/{group['id']}",
        headers=admin_headers,
        json={"capacity": 1},
    )
    assert quota.status_code == 200, quota.text
    open_selection_now(client, admin_headers)

    login = client.post(
        "/api/student/login",
        json={
            "student_no": student_no,
            "name": student_name,
            "activation_code": fictional_activation_code(student_no),
        },
    )
    assert login.status_code == 200, login.text
    student_headers = {
        "X-CSRF-Token": login.json()["csrf_token"],
        "X-Activity-ID": admin_headers["X-Activity-ID"],
    }
    selected = client.post(
        "/api/student/select",
        headers=student_headers,
        json={"group_id": group["id"]},
    )
    assert selected.status_code == 200, selected.text
    return selected.json(), group


def test_signed_receipt_verifies_and_tampering_or_revocation_invalidates_it(
    client: TestClient,
    admin_headers: dict[str, str],
):
    selected, group = select_one_student(
        client,
        admin_headers,
        student_no="20268000008",
        student_name="凭证核验学生",
    )
    receipt = selected["receipt"]
    assert receipt["version"] == "v1"
    assert receipt["verify_url"].startswith(
        "http://127.0.0.1:8765/receipt#token="
    )
    assert receipt["qr_image_url"] == (
        "http://127.0.0.1:8765/api/student/receipt/qr.png"
    )
    assert receipt["token"] not in receipt["qr_image_url"]
    assert len(receipt["verification_code"].split("-")) == 3

    receipt_page = client.get("/receipt")
    assert receipt_page.status_code == 200, receipt_page.text
    assert receipt_page.headers["cache-control"] == "no-store"
    assert receipt_page.headers["referrer-policy"] == "no-referrer"
    assert receipt_page.headers["x-frame-options"] == "DENY"
    assert receipt["token"] not in receipt_page.text
    assert client.get("/assets/receipt.js").status_code == 200
    assert client.get("/assets/receipt.css").status_code == 200

    student_me = client.get("/api/student/me")
    assert student_me.status_code == 200, student_me.text
    qr_headers = {
        "X-CSRF-Token": student_me.json()["csrf_token"],
        "X-Activity-ID": admin_headers["X-Activity-ID"],
    }
    assert client.get("/api/student/receipt/qr.png").status_code == 405
    missing_csrf = client.post(
        "/api/student/receipt/qr.png", json={"token": receipt["token"]}
    )
    assert missing_csrf.status_code == 403
    qr_image = client.post(
        "/api/student/receipt/qr.png",
        headers=qr_headers,
        json={"token": receipt["token"]},
    )
    assert qr_image.status_code == 200, qr_image.text
    assert qr_image.headers["content-type"] == "image/png"
    assert qr_image.headers["cache-control"] == "no-store"
    assert qr_image.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert receipt["token"] not in str(qr_image.request.url)
    assert qr_image.request.url.path == "/api/student/receipt/qr.png"
    assert not qr_image.request.url.query
    encoded_claims = receipt["token"].split(".")[1]
    claims = json.loads(
        base64.urlsafe_b64decode(encoded_claims + "=" * (-len(encoded_claims) % 4))
    )
    claims["student_id"] += 1
    other_student_receipt = signed_receipt_token(
        client.app.state.config.app_secret, claims
    )
    wrong_student = client.post(
        "/api/student/receipt/qr.png",
        headers=qr_headers,
        json={"token": other_student_receipt},
    )
    assert wrong_student.status_code == 403
    with TestClient(client.app) as anonymous_client:
        anonymous_qr = anonymous_client.post(
            "/api/student/receipt/qr.png", json={"token": receipt["token"]}
        )
    assert anonymous_qr.status_code == 401
    assert client.get("/api/public/receipts/verify").status_code == 405

    verified = client.post(
        "/api/public/receipts/verify", json={"token": receipt["token"]}
    )
    assert verified.status_code == 200, verified.text
    assert verified.headers["cache-control"] == "no-store"
    assert receipt["token"] not in str(verified.request.url)
    assert verified.request.url.path == "/api/public/receipts/verify"
    assert not verified.request.url.query
    assert verified.json() == {
        "valid": True,
        "revoked": False,
        "verification_code": receipt["verification_code"],
        "activity": {
            "code": selected["settings"]["activity_code"],
            "title": selected["settings"]["activity_title"],
        },
        "student": {
            "student_no_masked": "*******0008",
            "name": "凭证核验学生",
            "major_name": selected["student"]["major_name"],
        },
        "group": {"name": group["name"]},
        "selected_at": selected["selection"]["selected_at"],
    }

    token = receipt["token"]
    replacement = "A" if token[-1] != "A" else "B"
    tampered_qr = client.post(
        "/api/student/receipt/qr.png",
        headers=qr_headers,
        json={"token": token[:-1] + replacement},
    )
    assert tampered_qr.status_code == 400
    tampered = client.post(
        "/api/public/receipts/verify", json={"token": token[:-1] + replacement}
    )
    assert tampered.status_code == 400
    assert tampered.json()["detail"] == "凭证无效或已损坏"
    assert client.get("/api/public/receipts/qr.png").status_code == 404

    revoked = client.post(
        "/api/admin/selections/revoke",
        headers=admin_headers,
        json={"student_id": selected["student"]["id"], "reason": "核验撤销回归"},
    )
    assert revoked.status_code == 200, revoked.text
    after_revoke = client.post(
        "/api/public/receipts/verify", json={"token": receipt["token"]}
    )
    assert after_revoke.status_code == 200, after_revoke.text
    assert after_revoke.json()["valid"] is False
    assert after_revoke.json()["revoked"] is True


def test_receipt_qr_is_bound_to_rendered_token_during_revoke_reselect_race(
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    selected_a, group = select_one_student(
        client,
        admin_headers,
        student_no="20268000015",
        student_name="竞态凭证学生",
    )
    receipt_a = selected_a["receipt"]
    student_me = client.get("/api/student/me")
    assert student_me.status_code == 200, student_me.text
    student_headers = {
        "X-CSRF-Token": student_me.json()["csrf_token"],
        "X-Activity-ID": admin_headers["X-Activity-ID"],
    }

    revoked = client.post(
        "/api/admin/selections/revoke",
        headers=admin_headers,
        json={"student_id": selected_a["student"]["id"], "reason": "构造结果卡竞态"},
    )
    assert revoked.status_code == 200, revoked.text
    selected_b = client.post(
        "/api/student/select",
        headers=student_headers,
        json={"group_id": group["id"]},
    )
    assert selected_b.status_code == 200, selected_b.text
    receipt_b = selected_b.json()["receipt"]
    assert receipt_b["token"] != receipt_a["token"]

    encoded_values: list[str] = []
    original_qr_code = server_main.qrcode.QRCode

    class CapturingQrCode(original_qr_code):
        def add_data(self, data, *args, **kwargs):
            encoded_values.append(str(data))
            return super().add_data(data, *args, **kwargs)

    monkeypatch.setattr(server_main.qrcode, "QRCode", CapturingQrCode)
    qr_image = client.post(
        "/api/student/receipt/qr.png",
        headers=student_headers,
        json={"token": receipt_a["token"]},
    )

    assert qr_image.status_code == 200, qr_image.text
    assert qr_image.headers["content-type"] == "image/png"
    assert qr_image.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert qr_image.request.url.path == "/api/student/receipt/qr.png"
    assert not qr_image.request.url.query
    assert receipt_a["token"] not in str(qr_image.request.url)
    assert encoded_values == [receipt_a["verify_url"]]
    assert receipt_b["verify_url"] not in encoded_values

    old_receipt_status = client.post(
        "/api/public/receipts/verify", json={"token": receipt_a["token"]}
    )
    assert old_receipt_status.status_code == 200, old_receipt_status.text
    assert old_receipt_status.json()["valid"] is False
    assert old_receipt_status.json()["revoked"] is True


def test_signed_receipt_remains_verifiable_from_integrity_checked_archive(
    client: TestClient,
    admin_headers: dict[str, str],
):
    selected, _ = select_one_student(
        client,
        admin_headers,
        student_no="20268000009",
        student_name="归档凭证学生",
    )
    receipt = selected["receipt"]
    closed = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "closed"},
    )
    assert closed.status_code == 200, closed.text
    activity_id = int(admin_headers["X-Activity-ID"])
    archived = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "凭证归档后续活动",
            "code": "receipt-archive-next",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert archived.status_code == 200, archived.text

    verified = client.post(
        "/api/public/receipts/verify", json={"token": receipt["token"]}
    )
    assert verified.status_code == 200, verified.text
    assert verified.json()["valid"] is True
    assert verified.json()["revoked"] is False
    assert verified.json()["student"]["student_no_masked"] == "*******0009"


def test_archived_receipt_verification_rejects_every_outer_archive_mismatch(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    selected, _ = select_one_student(
        client,
        admin_headers,
        student_no="20268000022",
        student_name="归档绑定核验学生",
    )
    receipt = selected["receipt"]
    closed = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "closed"},
    )
    assert closed.status_code == 200, closed.text
    activity_id = int(admin_headers["X-Activity-ID"])
    archived = client.post(
        "/api/admin/activities",
        headers=admin_headers,
        json={
            "title": "归档绑定核验后续活动",
            "code": "receipt-archive-binding-next",
            "copy_structure": True,
            "previous_activity_id": activity_id,
        },
    )
    assert archived.status_code == 200, archived.text

    intact = client.post(
        "/api/public/receipts/verify", json={"token": receipt["token"]}
    )
    assert intact.status_code == 200, intact.text
    assert intact.json()["valid"] is True

    connection = connect(app_config.database_path)
    try:
        original = dict(
            connection.execute(
                """
                SELECT code, title, created_at, opened_at, closed_at,
                       archived_at, summary_json
                FROM activities WHERE id = ?
                """,
                (activity_id,),
            ).fetchone()
        )
    finally:
        connection.close()

    corruptions = {
        "code": "tampered-archive-code",
        "title": "已篡改归档标题",
        "created_at": "2040-01-02T03:04:05+00:00",
        "opened_at": "2040-01-02T03:04:06+00:00",
        "closed_at": "2040-01-02T03:04:07+00:00",
        "archived_at": "2040-01-02T03:04:08+00:00",
        "summary_json": '{"students":999,"selected":0,"unselected":999}',
    }
    for column, tampered_value in corruptions.items():
        connection = connect(app_config.database_path)
        try:
            connection.execute(
                f"UPDATE activities SET {column} = ? WHERE id = ?",
                (tampered_value, activity_id),
            )
            connection.commit()
        finally:
            connection.close()

        rejected = client.post(
            "/api/public/receipts/verify", json={"token": receipt["token"]}
        )
        assert rejected.status_code == 503, (column, rejected.text)
        assert rejected.json()["detail"] == "凭证核验数据暂不可用，请联系管理员"
        archive_download = client.get(
            f"/api/admin/activities/{activity_id}/archive.json"
        )
        assert archive_download.status_code == 500, (column, archive_download.text)

        connection = connect(app_config.database_path)
        try:
            connection.execute(
                f"UPDATE activities SET {column} = ? WHERE id = ?",
                (original[column], activity_id),
            )
            connection.commit()
        finally:
            connection.close()

    restored = client.post(
        "/api/public/receipts/verify", json={"token": receipt["token"]}
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["valid"] is True


def test_receipt_verification_rate_limits_exact_tokens_without_exhausting_classroom_nat(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    selected, _ = select_one_student(
        client,
        admin_headers,
        student_no="20268000010",
        student_name="共享网络核验学生",
    )
    selected_at = selected["selection"]["selected_at"]
    activity_id = int(admin_headers["X-Activity-ID"])

    def token_for(index: int) -> str:
        return signed_receipt_token(
            app_config.app_secret,
            {
                "activity_id": activity_id,
                "selection_id": 100_000 + index,
                "student_id": 200_000 + index,
                "group_id": 300_000 + index,
                "selected_at": selected_at,
            },
        )

    # Invalid signatures are rejected before the shared classroom-IP bucket.
    for index in range(500):
        rejected = client.post(
            "/api/public/receipts/verify",
            json={"token": f"v1.invalid-{index}.invalid-signature"},
        )
        assert rejected.status_code == 400

    # Repeated scans consume only their exact-token bucket, not the shared NAT budget.
    repeated_tokens = [token_for(index) for index in range(20)]
    for token in repeated_tokens:
        for _ in range(30):
            response = client.post(
                "/api/public/receipts/verify",
                json={"token": token},
            )
            assert response.status_code == 200, response.text
    limited = client.post(
        "/api/public/receipts/verify",
        json={"token": repeated_tokens[0]},
    )
    assert limited.status_code == 429
    assert limited.headers["retry-after"] == "300"

    # A whole class can independently verify signed receipts behind one public IP.
    for index in range(1_000, 1_150):
        response = client.post(
            "/api/public/receipts/verify",
            json={"token": token_for(index)},
        )
        assert response.status_code == 200, (index, response.text)


def test_receipt_verification_rejects_non_ascii_claim_segment_as_invalid(
    client: TestClient,
):
    malformed = "v1.\N{LATIN SMALL LETTER E WITH ACUTE}." + ("A" * 43)
    with TestClient(client.app, raise_server_exceptions=False) as isolated_client:
        response = isolated_client.post(
            "/api/public/receipts/verify",
            json={"token": malformed},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "凭证无效或已损坏"
    assert response.request.url.path == "/api/public/receipts/verify"
    assert not response.request.url.query
