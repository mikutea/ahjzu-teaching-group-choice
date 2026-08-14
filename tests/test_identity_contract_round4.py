from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from server import main as main_module
from server.database import connect, utc_now
from server.main import RateLimiter
from server.roster import parse_roster_file
from server.security import activation_code_hash, encrypt_activation_code
from server.student_identity import (
    StudentIdentityError,
    normalize_student_name,
    normalize_student_number,
)

from .conftest import fictional_document_number


def roster_csv(rows: list[tuple[str, str, str, str]]) -> bytes:
    lines = ["学号,姓名,专业,证件号"]
    lines.extend(",".join(row) for row in rows)
    return ("\n".join(lines) + "\n").encode("utf-8")


def insert_login_identity(
    *,
    app_config,
    client: TestClient,
    student_no: str,
    name: str,
    code: str,
    active: bool = True,
) -> None:
    assert normalize_student_number(student_no) == student_no
    assert normalize_student_name(name) == name
    major_id = client.get("/api/admin/dashboard").json()["majors"][0]["id"]
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        connection.execute(
            """
            INSERT INTO students
                (student_no, name, major_id, activation_hash,
                 activation_ciphertext, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                student_no,
                name,
                major_id,
                activation_code_hash(app_config.app_secret, code),
                encrypt_activation_code(app_config.app_secret, student_no, code),
                int(active),
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()


def endpoint_closure_value(app, path: str, name: str):
    endpoint = next(route.endpoint for route in app.routes if route.path == path)
    closure = dict(
        zip(endpoint.__code__.co_freevars, endpoint.__closure__ or (), strict=True)
    )
    return closure[name].cell_contents


@pytest.mark.parametrize(
    ("student_no", "name", "expected_message"),
    [
        ("2026123456", "正常姓名", "学号必须是 11 位数字"),
        ("202612345678", "正常姓名", "学号必须是 11 位数字"),
        ("20261A34567", "正常姓名", "学号必须是 11 位数字"),
        ("\t20261234567", "正常姓名", "学号不能包含控制字符"),
        ("20261234567", "姓名🙂", "姓名只能包含中文或英文字母"),
        ("20261234567", "正常\x07姓名", "姓名不能包含控制字符"),
        ("20261234567", "A" * 41, "姓名不能超过 40 个字符"),
    ],
)
def test_roster_import_rejects_invalid_current_identity(
    client: TestClient,
    admin_headers: dict[str, str],
    student_no: str,
    name: str,
    expected_message: str,
):
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    response = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "files": (
                "invalid-identity.csv",
                roster_csv(
                    [
                        (
                            student_no,
                            name,
                            major_name,
                            fictional_document_number("invalid-identity"),
                        )
                    ]
                ),
                "text/csv",
            )
        },
    )
    assert response.status_code == 400, response.text
    assert "第 1 个文件" in response.json()["detail"]
    assert "第 2 行" in response.json()["detail"]
    assert expected_message in response.json()["detail"]
    assert client.get("/api/admin/dashboard").json()["students"] == []


def test_invalid_identity_aborts_the_entire_roster_batch(
    client: TestClient, admin_headers: dict[str, str]
):
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    response = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "files": (
                "atomic-invalid.csv",
                roster_csv(
                    [
                        (
                            "20261234001",
                            "正常学生",
                            major_name,
                            fictional_document_number("valid-first"),
                        ),
                        (
                            "20261234A02",
                            "异常学生",
                            major_name,
                            fictional_document_number("invalid-second"),
                        ),
                    ]
                ),
                "text/csv",
            )
        },
    )
    assert response.status_code == 400, response.text
    assert "第 3 行" in response.json()["detail"]
    assert client.get("/api/admin/dashboard").json()["students"] == []


def test_roster_and_login_share_current_canonical_identity(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
):
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    source_rows = [
        ("２０２６１２３００４５", "欧阳·子涵", "mainland"),
        ("２０２６１２３００４６", "Chen Wei Lun", "hong-kong"),
        ("20261230047", "陳・美玲", "macao"),
        ("20261230048", "王小明", "taiwan"),
    ]
    content = roster_csv(
        [
            (student_no, name, major_name, fictional_document_number(seed))
            for student_no, name, seed in source_rows
        ]
    )
    parsed = parse_roster_file(filename="current-formats.csv", content=content, file_index=1)
    expected_numbers = [normalize_student_number(row[0]) for row in source_rows]
    expected_names = [normalize_student_name(row[1]) for row in source_rows]
    assert [row.student_no for row in parsed] == expected_numbers
    assert [row.name for row in parsed] == expected_names
    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={"files": ("current-formats.csv", content, "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    for (source_number, source_name, seed), expected_number in zip(
        source_rows, expected_numbers, strict=True
    ):
        with TestClient(app) as student_client:
            login = student_client.post(
                "/api/student/login",
                json={
                    "student_no": source_number,
                    "name": source_name,
                    "activation_code": fictional_document_number(seed)[-6:],
                },
            )
        assert login.status_code == 200, login.text
        assert login.json()["student"]["student_no"] == expected_number


def test_selected_student_major_change_rolls_back_entire_reimport(
    client: TestClient,
    admin_headers: dict[str, str],
    app_config,
):
    dashboard = client.get("/api/admin/dashboard").json()
    old_major, new_major = dashboard["majors"][:2]
    group = dashboard["groups"][0]
    student_no = "20261235001"
    document_number = fictional_document_number("selected-major-change")
    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "files": (
                "selected.csv",
                roster_csv(
                    [(student_no, "已选学生", old_major["name"], document_number)]
                ),
                "text/csv",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    student = client.get("/api/admin/dashboard").json()["students"][0]
    assigned = client.post(
        "/api/admin/selections",
        headers=admin_headers,
        json={"student_id": student["id"], "group_id": group["id"]},
    )
    assert assigned.status_code == 200, assigned.text
    connection = connect(app_config.database_path)
    try:
        before = tuple(
            connection.execute(
                "SELECT student_no, name, major_id, activation_hash, active "
                "FROM students WHERE id = ?",
                (student["id"],),
            ).fetchone()
        )
    finally:
        connection.close()
    rejected = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "files": (
                "selected-changed.csv",
                roster_csv(
                    [(student_no, "试图更名学生", new_major["name"], document_number)]
                ),
                "text/csv",
            )
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert "已有选择" in rejected.json()["detail"]
    connection = connect(app_config.database_path)
    try:
        after = tuple(
            connection.execute(
                "SELECT student_no, name, major_id, activation_hash, active "
                "FROM students WHERE id = ?",
                (student["id"],),
            ).fetchone()
        )
        selection_count = connection.execute(
            "SELECT COUNT(*) FROM selections "
            "WHERE student_id = ? AND revoked_at IS NULL",
            (student["id"],),
        ).fetchone()[0]
    finally:
        connection.close()
    assert after == before
    assert selection_count == 1


def test_current_accounts_have_independent_login_limits(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    name = "限流隔离学生"
    accounts = (("20261236001", "A1B2C3"), ("20261236002", "Z9Y8X7"))
    for student_no, code in accounts:
        insert_login_identity(
            app_config=app_config,
            client=client,
            student_no=student_no,
            name=name,
            code=code,
        )
    with TestClient(app) as student_client:
        for _ in range(10):
            rejected = student_client.post(
                "/api/student/login",
                json={
                    "student_no": accounts[0][0],
                    "name": name,
                    "activation_code": "Q1W2E3",
                },
            )
            assert rejected.status_code == 401, rejected.text
        second_login = student_client.post(
            "/api/student/login",
            json={
                "student_no": accounts[1][0],
                "name": name,
                "activation_code": accounts[1][1],
            },
        )
        assert second_login.status_code == 200, second_login.text
        first_blocked = student_client.post(
            "/api/student/login",
            json={
                "student_no": accounts[0][0],
                "name": name,
                "activation_code": accounts[0][1],
            },
        )
        assert first_blocked.status_code == 429, first_blocked.text


def test_failure_recording_is_atomic_at_the_tenth_eleventh_boundary():
    limiter = RateLimiter()

    def record_attempt() -> bool:
        return limiter.record_failure("student-family", limit=10, window_seconds=300)

    with ThreadPoolExecutor(max_workers=20) as executor:
        states = list(executor.map(lambda _: record_attempt(), range(20)))
    assert states.count(False) == 10
    assert states.count(True) == 10


def test_no_evict_capacity_preserves_existing_identity_lock():
    limiter = RateLimiter(max_keys=1, evict_oldest=False)
    assert limiter.record_failure("protected", limit=1, window_seconds=300) is False
    assert limiter.record_failure("new-key", limit=10, window_seconds=300) is True
    assert limiter.is_limited("protected", limit=1, window_seconds=300)
    assert limiter.is_limited("new-key", limit=10, window_seconds=300)


def test_no_evict_capacity_recovers_after_failure_window(monkeypatch):
    now = [1_000.0]
    monkeypatch.setattr(main_module.time, "monotonic", lambda: now[0])
    limiter = RateLimiter(max_keys=1, evict_oldest=False)
    assert limiter.record_failure("expired", limit=10, window_seconds=300) is False
    assert limiter.record_failure("blocked", limit=10, window_seconds=300) is True
    now[0] += 301
    assert limiter.record_failure("fresh", limit=10, window_seconds=300) is False


def test_rate_limit_namespaces_do_not_evict_or_block_each_other():
    student_ip = RateLimiter(max_keys=1)
    protected = (
        (RateLimiter(max_keys=1), "admin-ip"),
        (RateLimiter(max_keys=1), "admin-account"),
        (RateLimiter(max_keys=1), "admin-id"),
    )
    for limiter, key in protected:
        assert limiter.record_failure(key, limit=1, window_seconds=300) is False
    assert student_ip.record_failure("student-ip-one", limit=1, window_seconds=300) is False
    assert student_ip.record_failure("student-ip-two", limit=1, window_seconds=300) is False
    for limiter, key in protected:
        assert limiter.is_limited(key, limit=1, window_seconds=300)


def test_identity_capacity_skips_verification_without_evicting_locks(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
    monkeypatch,
):
    student_no = "20261237002"
    name = "身份容量保护学生"
    correct_code = "A1B2C3"
    insert_login_identity(
        app_config=app_config,
        client=client,
        student_no=student_no,
        name=name,
        code=correct_code,
    )
    identity_limiter = endpoint_closure_value(
        app, "/api/student/login", "student_id_limiter"
    )
    protected_key = "protected-student-id"
    for _ in range(10):
        identity_limiter.record_failure(protected_key, limit=10, window_seconds=300)
    for index in range(4_095):
        assert identity_limiter.record_failure(
            f"other-student-id-{index}", limit=10, window_seconds=300
        ) is False
    monkeypatch.setattr(
        main_module,
        "verify_activation_ciphertext",
        lambda *_args, **_kwargs: pytest.fail("capacity lock reached credential check"),
    )
    response = client.post(
        "/api/student/login",
        json={
            "student_no": student_no,
            "name": name,
            "activation_code": correct_code,
        },
    )
    assert response.status_code == 401, response.text
    assert identity_limiter.is_limited(protected_key, limit=10, window_seconds=300)


def test_success_does_not_count_or_clear_account_failures(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    student_no = "20261238001"
    name = "成功路径保护学生"
    correct_code = "A1B2C3"
    insert_login_identity(
        app_config=app_config,
        client=client,
        student_no=student_no,
        name=name,
        code=correct_code,
    )
    with TestClient(app) as student_client:
        for _ in range(9):
            rejected = student_client.post(
                "/api/student/login",
                json={
                    "student_no": student_no,
                    "name": name,
                    "activation_code": "Q1W2E3",
                },
            )
            assert rejected.status_code == 401, rejected.text
        success = student_client.post(
            "/api/student/login",
            json={
                "student_no": student_no,
                "name": name,
                "activation_code": correct_code,
            },
        )
        assert success.status_code == 200, success.text
        tenth_failure = student_client.post(
            "/api/student/login",
            json={
                "student_no": student_no,
                "name": name,
                "activation_code": "Q1W2E3",
            },
        )
        assert tenth_failure.status_code == 401, tenth_failure.text
        success_after_limit = student_client.post(
            "/api/student/login",
            json={
                "student_no": student_no,
                "name": name,
                "activation_code": correct_code,
            },
        )
        assert success_after_limit.status_code == 200, success_after_limit.text
        limited_failure = student_client.post(
            "/api/student/login",
            json={
                "student_no": student_no,
                "name": name,
                "activation_code": "Q1W2E3",
            },
        )
        assert limited_failure.status_code == 429, limited_failure.text


def test_current_identity_failures_do_not_reveal_account_existence(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    active_number = "20261239002"
    inactive_number = "20261239003"
    missing_number = "20261239004"
    name = "枚举保护学生"
    code = "A1B2C3"
    insert_login_identity(
        app_config=app_config,
        client=client,
        student_no=active_number,
        name=name,
        code=code,
    )
    insert_login_identity(
        app_config=app_config,
        client=client,
        student_no=inactive_number,
        name=name,
        code=code,
        active=False,
    )
    attempts = [
        {"student_no": active_number, "name": name, "activation_code": "Z9Y8X7"},
        {"student_no": missing_number, "name": name, "activation_code": code},
        {"student_no": active_number, "name": "错误姓名", "activation_code": code},
        {"student_no": inactive_number, "name": name, "activation_code": code},
    ]
    with TestClient(app) as student_client:
        responses = [
            student_client.post("/api/student/login", json=payload)
            for payload in attempts
        ]
    assert [response.status_code for response in responses] == [401] * len(attempts)
    assert [response.json() for response in responses] == [
        {"detail": "学号、姓名或激活码不正确"} for _ in attempts
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"student_no": "", "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "2026123456", "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "202612345678", "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "20261A34567", "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "20261234567", "name": "N" * 81, "activation_code": "A1B2C3"},
        {"student_no": "bad\nnumber", "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "20261234567", "name": "bad\x07name", "activation_code": "A1B2C3"},
        {"student_no": "20261234567", "name": "正常姓名", "activation_code": "BAD*12"},
    ],
)
def test_login_request_rejects_invalid_current_contract(
    client: TestClient, payload: dict[str, str]
):
    response = client.post("/api/student/login", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "value",
    ["2026123456", "202612345678", "20261A34567", "with space", "bad\nnumber"],
)
def test_shared_student_number_validator_rejects_unusable_values(value: str):
    with pytest.raises(StudentIdentityError):
        normalize_student_number(value)
