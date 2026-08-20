from __future__ import annotations

import asyncio
import base64
import csv
from dataclasses import replace
import hashlib
import hmac
import io
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from fastapi.testclient import TestClient

import server.main as server_main
from server.database import connect

from .conftest import (
    TEST_ADMIN_PASSWORD,
    fictional_activation_code,
    fictional_document_number,
    open_selection_now,
)


def test_concurrent_receipt_qr_cache_misses_share_one_render(
    client: TestClient, monkeypatch
) -> None:
    cache = client.app.state.receipt_qr_cache
    renderer = client.app.state.receipt_qr_renderer
    cache.cache_clear()
    original_make_image = server_main.qrcode.QRCode.make_image
    render_count = 0
    render_lock = threading.Lock()
    start = threading.Barrier(9)

    def slow_make_image(qr, *args, **kwargs):
        nonlocal render_count
        with render_lock:
            render_count += 1
        time.sleep(0.05)
        return original_make_image(qr, *args, **kwargs)

    monkeypatch.setattr(server_main.qrcode.QRCode, "make_image", slow_make_image)
    verify_url = "https://choice.example.com/receipt#token=single-flight-test"

    def render() -> bytes:
        start.wait(timeout=10)
        return renderer(verify_url)

    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(render) for _ in range(8)]
        start.wait(timeout=10)
        outputs = [future.result(timeout=10) for future in futures]

    assert render_count == 1
    assert len(set(outputs)) == 1


def test_distinct_receipt_qr_renders_are_bounded_outside_the_sync_pool() -> None:
    active = 0
    max_active = 0
    render_lock = threading.Lock()

    def render(verify_url: str) -> bytes:
        nonlocal active, max_active
        with render_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.03)
            return verify_url.encode("ascii")
        finally:
            with render_lock:
                active -= 1

    async def exercise() -> list[bytes]:
        with ThreadPoolExecutor(
            max_workers=server_main.RECEIPT_QR_RENDER_PARALLELISM
        ) as executor:
            return await asyncio.gather(
                *(
                    server_main.render_receipt_qr_limited(
                        executor,
                        render,
                        f"https://choice.example.com/receipt#token={index}",
                    )
                    for index in range(20)
                )
            )

    outputs = asyncio.run(exercise())
    assert len(outputs) == 20
    assert max_active == server_main.RECEIPT_QR_RENDER_PARALLELISM


def test_cancelled_receipt_qr_requests_keep_running_work_charged() -> None:
    active = 0
    max_active = 0
    started = threading.Event()
    release = threading.Event()
    render_lock = threading.Lock()

    def render(verify_url: str) -> bytes:
        nonlocal active, max_active
        with render_lock:
            active += 1
            max_active = max(max_active, active)
            if active == 2:
                started.set()
        try:
            assert release.wait(timeout=10)
            return verify_url.encode("ascii")
        finally:
            with render_lock:
                active -= 1

    async def exercise(executor: ThreadPoolExecutor) -> list[bytes]:
        cancelled = [
            asyncio.create_task(
                server_main.render_receipt_qr_limited(
                    executor,
                    render,
                    f"https://choice.example.com/receipt#token=cancel-{index}",
                )
            )
            for index in range(2)
        ]
        assert await asyncio.to_thread(started.wait, 10)
        for task in cancelled:
            task.cancel()
        await asyncio.gather(*cancelled, return_exceptions=True)
        queued = [
            asyncio.create_task(
                server_main.render_receipt_qr_limited(
                    executor,
                    render,
                    f"https://choice.example.com/receipt#token=queued-{index}",
                )
            )
            for index in range(2)
        ]
        await asyncio.sleep(0.05)
        with render_lock:
            assert active == 2
            assert max_active == 2
        release.set()
        return await asyncio.gather(*queued)

    executor = ThreadPoolExecutor(max_workers=2)
    try:
        outputs = asyncio.run(exercise(executor))
    finally:
        release.set()
        executor.shutdown(wait=True, cancel_futures=True)
    assert len(outputs) == 2
    assert max_active == 2


def test_receipt_qr_executor_is_safe_across_event_loops() -> None:
    active = 0
    max_active = 0
    render_lock = threading.Lock()

    def render(verify_url: str) -> bytes:
        nonlocal active, max_active
        with render_lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.02)
            return verify_url.encode("ascii")
        finally:
            with render_lock:
                active -= 1

    executor = ThreadPoolExecutor(max_workers=4)

    def run_loop(prefix: str) -> list[bytes]:
        async def exercise() -> list[bytes]:
            return await asyncio.gather(
                *(
                    server_main.render_receipt_qr_limited(
                        executor,
                        render,
                        f"https://choice.example.com/receipt#token={prefix}-{index}",
                    )
                    for index in range(8)
                )
            )

        return asyncio.run(exercise())

    try:
        with ThreadPoolExecutor(max_workers=2) as loops:
            outputs = list(loops.map(run_loop, ("first", "second")))
    finally:
        executor.shutdown(wait=True, cancel_futures=True)
    assert [len(group) for group in outputs] == [8, 8]
    assert max_active == 4


def signed_receipt_token(secret: str, claims: dict[str, object]) -> str:
    complete_claims = {
        "snapshot_version": 1,
        "snapshot_hmac_sha256": "0" * 64,
        **claims,
    }
    encoded_claims = base64.urlsafe_b64encode(
        json.dumps(
            complete_claims,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).decode("ascii").rstrip("=")
    signature = hmac.new(
        secret.encode("utf-8"),
        b"selection-receipt-v2\0" + encoded_claims.encode("ascii"),
        hashlib.sha256,
    ).digest()
    encoded_signature = (
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    )
    return f"v2.{encoded_claims}.{encoded_signature}"


def legacy_signed_receipt_token(secret: str, claims: dict[str, object]) -> str:
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
    encoded_signature = (
        base64.urlsafe_b64encode(signature).decode("ascii").rstrip("=")
    )
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
    assert receipt["version"] == "v2"
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
    cache_before = client.app.state.receipt_qr_cache.cache_info()
    repeated_qr = client.post(
        "/api/student/receipt/qr.png",
        headers=qr_headers,
        json={"token": receipt["token"]},
    )
    cache_after = client.app.state.receipt_qr_cache.cache_info()
    assert repeated_qr.status_code == 200
    assert repeated_qr.content == qr_image.content
    assert cache_after.hits == cache_before.hits + 1
    encoded_claims = receipt["token"].split(".")[1]
    claims = json.loads(
        base64.urlsafe_b64decode(encoded_claims + "=" * (-len(encoded_claims) % 4))
    )
    assert set(claims) == {
        "activity_id",
        "selection_id",
        "student_id",
        "group_id",
        "selected_at",
        "snapshot_version",
        "snapshot_hmac_sha256",
    }
    assert claims["snapshot_version"] == 1
    assert len(claims["snapshot_hmac_sha256"]) == 64
    assert "student_name" not in claims
    assert "student_no" not in claims
    assert len(encoded_claims) <= 384
    assert len(receipt["token"]) <= 512

    def encoded_snapshot(candidate_student_no: str) -> bytes:
        return json.dumps(
            {
                "version": 1,
                "activity_code": selected["settings"]["activity_code"],
                "activity_title": selected["settings"]["activity_title"],
                "student_no": candidate_student_no,
                "student_name": "凭证核验学生",
                "major_name": selected["student"]["major_name"],
                "group_name": group["name"],
                "selected_at": selected["selection"]["selected_at"],
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    raw_sha256_dictionary = {
        hashlib.sha256(
            b"selection-receipt-snapshot-v1\0"
            + encoded_snapshot(f"202{candidate:04d}0008")
        ).hexdigest()
        for candidate in range(6500, 7500)
    }
    assert claims["snapshot_hmac_sha256"] not in raw_sha256_dictionary
    expected_snapshot_hmac = hmac.new(
        client.app.state.config.app_secret.encode("utf-8"),
        b"selection-receipt-snapshot-v1\0" + encoded_snapshot("20268000008"),
        hashlib.sha256,
    ).hexdigest()
    assert hmac.compare_digest(
        claims["snapshot_hmac_sha256"], expected_snapshot_hmac
    )
    assert "20268000008" not in receipt["token"]
    assert "凭证核验学生" not in receipt["token"]

    legacy_receipt = legacy_signed_receipt_token(
        client.app.state.config.app_secret,
        {
            key: claims[key]
            for key in (
                "activity_id",
                "selection_id",
                "student_id",
                "group_id",
                "selected_at",
            )
        },
    )
    legacy_rejected = client.post(
        "/api/public/receipts/verify", json={"token": legacy_receipt}
    )
    assert legacy_rejected.status_code == 400
    assert legacy_rejected.json()["detail"] == "凭证无效或已损坏"

    mismatched_snapshot_claims = dict(claims)
    mismatched_snapshot_claims["snapshot_hmac_sha256"] = "0" * 64
    mismatched_snapshot_receipt = signed_receipt_token(
        client.app.state.config.app_secret,
        mismatched_snapshot_claims,
    )
    mismatched_snapshot = client.post(
        "/api/public/receipts/verify",
        json={"token": mismatched_snapshot_receipt},
    )
    assert mismatched_snapshot.status_code == 200, mismatched_snapshot.text
    assert mismatched_snapshot.json()["valid"] is False

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


def test_current_receipt_signature_binds_every_rendered_mutable_field(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    selected, group = select_one_student(
        client,
        admin_headers,
        student_no="20268000031",
        student_name="字段绑定学生",
    )
    receipt = selected["receipt"]
    closed = client.post(
        "/api/admin/status",
        headers=admin_headers,
        json={"status": "closed"},
    )
    assert closed.status_code == 200, closed.text

    baseline = client.post(
        "/api/public/receipts/verify", json={"token": receipt["token"]}
    )
    assert baseline.status_code == 200, baseline.text
    assert baseline.json()["valid"] is True

    activity_id = int(admin_headers["X-Activity-ID"])
    student_id = int(selected["student"]["id"])
    major_id = int(selected["student"]["major_id"])
    group_id = int(group["id"])
    mutations = [
        ("activities", "title", activity_id, "已修改活动标题"),
        ("activities", "code", activity_id, "receipt-mutated-code"),
        ("students", "name", student_id, "已修改学生姓名"),
        ("students", "student_no", student_id, "20268000032"),
        ("majors", "name", major_id, "已修改专业名称"),
        ("teaching_groups", "name", group_id, "已修改教学组名称"),
    ]
    for table, column, record_id, replacement in mutations:
        connection = connect(app_config.database_path)
        try:
            original = connection.execute(
                f"SELECT {column} FROM {table} WHERE id = ?", (record_id,)
            ).fetchone()[0]
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE id = ?",
                (replacement, record_id),
            )
            connection.commit()
        finally:
            connection.close()

        changed = client.post(
            "/api/public/receipts/verify", json={"token": receipt["token"]}
        )
        assert changed.status_code == 200, (table, column, changed.text)
        assert changed.json()["valid"] is False, (table, column, changed.json())

        refreshed = client.get("/api/student/me")
        assert refreshed.status_code == 200, (table, column, refreshed.text)
        refreshed_receipt = refreshed.json()["receipt"]
        assert refreshed_receipt["token"] != receipt["token"]
        refreshed_verified = client.post(
            "/api/public/receipts/verify",
            json={"token": refreshed_receipt["token"]},
        )
        assert refreshed_verified.status_code == 200, (
            table,
            column,
            refreshed_verified.text,
        )
        assert refreshed_verified.json()["valid"] is True

        connection = connect(app_config.database_path)
        try:
            connection.execute(
                f"UPDATE {table} SET {column} = ? WHERE id = ?",
                (original, record_id),
            )
            connection.commit()
        finally:
            connection.close()

        restored = client.post(
            "/api/public/receipts/verify", json={"token": receipt["token"]}
        )
        assert restored.status_code == 200, (table, column, restored.text)
        assert restored.json()["valid"] is True, (table, column, restored.json())


def test_receipt_generation_and_qr_require_a_trusted_absolute_public_origin(
    app_config,
    tmp_path,
):
    isolated_config = replace(
        app_config,
        database_path=tmp_path / "receipt-origin.db",
        public_base_url="",
    )
    isolated_app = server_main.create_app(isolated_config)

    with TestClient(isolated_app, base_url="http://request-host.invalid") as isolated:
        login = isolated.post(
            "/api/admin/login",
            json={"username": "admin", "password": TEST_ADMIN_PASSWORD},
        )
        assert login.status_code == 200, login.text
        dashboard = isolated.get("/api/admin/dashboard").json()
        activity_id = int(dashboard["settings"]["activity_id"])
        admin_headers = {
            "X-CSRF-Token": login.json()["csrf_token"],
            "X-Activity-ID": str(activity_id),
        }
        assert dashboard["readiness"]["ready"] is False
        assert "尚未设置学生端访问地址" in dashboard["readiness"]["blockers"]

        major = dashboard["majors"][0]
        group = dashboard["groups"][0]
        student_no = "20268000022"
        student_name = "缺少站点地址学生"
        imported = import_rosters(
            isolated,
            admin_headers,
            [
                (
                    "missing-origin.csv",
                    [
                        (
                            student_no,
                            student_name,
                            major["name"],
                            fictional_document_number("missing-receipt-origin"),
                        )
                    ],
                )
            ],
        )
        assert imported.status_code == 200, imported.text
        quota = isolated.put(
            f"/api/admin/quotas/{major['id']}/{group['id']}",
            headers=admin_headers,
            json={"capacity": 1},
        )
        assert quota.status_code == 200, quota.text

        student_login = isolated.post(
            "/api/student/login",
            json={
                "student_no": student_no,
                "name": student_name,
                "activation_code": fictional_activation_code(
                    "missing-receipt-origin"
                ),
            },
        )
        assert student_login.status_code == 200, student_login.text
        student = student_login.json()["student"]
        student_headers = {
            "X-CSRF-Token": student_login.json()["csrf_token"],
            "X-Activity-ID": str(activity_id),
            "Host": "attacker-controlled.invalid",
            "X-Forwarded-Host": "also-attacker-controlled.invalid",
        }
        receipt_token = signed_receipt_token(
            isolated_config.app_secret,
            {
                "activity_id": activity_id,
                "selection_id": 1,
                "student_id": int(student["id"]),
                "group_id": int(group["id"]),
                "selected_at": "2026-08-14T00:00:00+00:00",
            },
        )

        qr = isolated.post(
            "/api/student/receipt/qr.png",
            headers=student_headers,
            json={"token": receipt_token},
        )
        assert qr.status_code == 409, qr.text
        assert qr.json()["detail"] == "请先在系统设置中填写学生端访问地址"

        assigned = isolated.post(
            "/api/admin/selections",
            headers=admin_headers,
            json={"student_id": student["id"], "group_id": group["id"]},
        )
        assert assigned.status_code == 409, assigned.text
        assert assigned.json()["detail"] == "请先在系统设置中填写学生端访问地址"

        connection = connect(isolated_config.database_path)
        try:
            assert connection.execute("SELECT COUNT(*) FROM selections").fetchone()[0] == 0
        finally:
            connection.close()


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
    app_config,
):
    selected, group = select_one_student(
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

    archived_payload = verified.json()
    connection = connect(app_config.database_path)
    try:
        connection.execute(
            "UPDATE students SET name = ? WHERE id = ?",
            ("新活动学生姓名", selected["student"]["id"]),
        )
        connection.execute(
            "UPDATE majors SET name = ? WHERE id = ?",
            ("新活动专业名称", selected["student"]["major_id"]),
        )
        connection.execute(
            "UPDATE teaching_groups SET name = ? WHERE id = ?",
            ("新活动教学组名称", group["id"]),
        )
        connection.commit()
    finally:
        connection.close()

    after_live_structure_changes = client.post(
        "/api/public/receipts/verify", json={"token": receipt["token"]}
    )
    assert after_live_structure_changes.status_code == 200
    assert after_live_structure_changes.json() == archived_payload


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
            json={"token": f"v2.invalid-{index}.invalid-signature"},
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
    malformed = "v2.\N{LATIN SMALL LETTER E WITH ACUTE}." + ("A" * 43)
    with TestClient(client.app, raise_server_exceptions=False) as isolated_client:
        response = isolated_client.post(
            "/api/public/receipts/verify",
            json={"token": malformed},
        )
    assert response.status_code == 400
    assert response.json()["detail"] == "凭证无效或已损坏"
    assert response.request.url.path == "/api/public/receipts/verify"
    assert not response.request.url.query
