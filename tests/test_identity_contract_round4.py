from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.database import connect, utc_now
from server.main import StudentLogin
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


@pytest.mark.parametrize(
    ("student_no", "name", "expected_message"),
    [
        ("ABC", "正常姓名", "学号不能少于 4 个字符"),
        ("A" * 33, "正常姓名", "学号不能超过 32 个字符"),
        ("2026/001", "正常姓名", "学号只能包含"),
        ("\t20260001", "正常姓名", "学号不能包含控制字符"),
        ("20260001", "姓名🙂", "姓名包含不支持的字符"),
        ("20260001", "正常\x07姓名", "姓名不能包含控制字符"),
        ("20260001", "A" * 81, "姓名不能超过 80 个字符"),
    ],
)
def test_roster_import_rejects_identity_that_student_login_would_reject(
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
            "file": (
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
    detail = response.json()["detail"]
    assert "第 1 个文件" in detail
    assert "第 2 行" in detail
    assert expected_message in detail
    assert client.get("/api/admin/dashboard").json()["students"] == []


def test_invalid_identity_aborts_the_entire_roster_batch(
    client: TestClient, admin_headers: dict[str, str]
):
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    response = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "file": (
                "atomic-invalid.csv",
                roster_csv(
                    [
                        (
                            "20260001",
                            "正常学生",
                            major_name,
                            fictional_document_number("valid-first"),
                        ),
                        (
                            "bad number",
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


def test_roster_and_login_share_canonical_identity_for_real_name_formats(
    app,
    client: TestClient,
    admin_headers: dict[str, str],
):
    major_name = client.get("/api/admin/dashboard").json()["majors"][0]["name"]
    source_rows = [
        ("２０２６０１２３００４５", "欧阳·子涵", "mainland"),
        ("HK＿TW－2026", "Ch'en Wei-Lun", "hong-kong"),
        ("MACAO_2026", "陳・美玲", "macao"),
        ("TW-2026_01", "王小明", "taiwan"),
    ]
    content = roster_csv(
        [
            (student_no, name, major_name, fictional_document_number(seed))
            for student_no, name, seed in source_rows
        ]
    )
    parsed = parse_roster_file(filename="real-formats.csv", content=content, file_index=1)
    expected_numbers = [normalize_student_number(row[0]) for row in source_rows]
    expected_names = [normalize_student_name(row[1]) for row in source_rows]
    assert [row.student_no for row in parsed] == expected_numbers
    assert [row.name for row in parsed] == expected_names

    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={"file": ("real-formats.csv", content, "text/csv")},
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["created"] == len(source_rows)

    students = client.get("/api/admin/dashboard").json()["students"]
    assert [student["student_no"] for student in students] == expected_numbers
    for (source_number, source_name, seed), expected_number, expected_name in zip(
        source_rows, expected_numbers, expected_names, strict=True
    ):
        model = StudentLogin.model_validate(
            {
                "student_no": source_number,
                "name": source_name,
                "activation_code": fictional_document_number(seed)[-6:],
            }
        )
        assert (model.student_no, model.name) == (expected_number, expected_name)
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


@pytest.mark.parametrize(
    ("student_no", "name"),
    [
        ("LEGACY.2026.001", "旧版兼容学生"),
        ("L" * 35, "=Legacy Name"),
    ],
)
def test_exact_legacy_database_identity_can_still_login_without_rekeying(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
    student_no: str,
    name: str,
):
    dashboard = client.get("/api/admin/dashboard").json()
    assert int(dashboard["settings"]["activity_id"]) == int(
        admin_headers["X-Activity-ID"]
    )
    major_id = dashboard["majors"][0]["id"]
    activation_code = "A1B2C3"
    ciphertext = encrypt_activation_code(
        app_config.app_secret, student_no, activation_code
    )
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """
            INSERT INTO students
                (student_no, name, major_id, activation_hash,
                 activation_ciphertext, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                student_no,
                name,
                major_id,
                activation_code_hash(app_config.app_secret, activation_code),
                ciphertext,
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()

    # The strict contract correctly rejects this for every future import.
    with pytest.raises(StudentIdentityError):
        normalize_student_number(student_no)

    with TestClient(app) as student_client:
        login = student_client.post(
            "/api/student/login",
            json={
                "student_no": student_no,
                "name": name,
                "activation_code": activation_code,
            },
        )
        assert login.status_code == 200, login.text
        assert login.json()["student"]["student_no"] == student_no

    # No migration/re-key occurred: the ciphertext remains decryptable under
    # the original student number used as its authenticated associated data.
    connection = connect(app_config.database_path)
    try:
        stored = connection.execute(
            "SELECT student_no, activation_ciphertext FROM students WHERE student_no = ?",
            (student_no,),
        ).fetchone()
    finally:
        connection.close()
    assert stored["student_no"] == student_no
    assert stored["activation_ciphertext"] == ciphertext


def test_exact_raw_legacy_identity_wins_over_canonical_sibling_collision(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_id = dashboard["majors"][0]["id"]
    same_name = "碰撞测试学生"
    ascii_number = "ABCD"
    fullwidth_number = "ＡＢＣＤ"
    ascii_code = "A1B2C3"
    fullwidth_code = "Z9Y8X7"
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        connection.execute("BEGIN IMMEDIATE")
        for student_no, code in (
            (ascii_number, ascii_code),
            (fullwidth_number, fullwidth_code),
        ):
            connection.execute(
                """
                INSERT INTO students
                    (student_no, name, major_id, activation_hash,
                     activation_ciphertext, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, 1, ?, ?)
                """,
                (
                    student_no,
                    same_name,
                    major_id,
                    activation_code_hash(app_config.app_secret, code),
                    encrypt_activation_code(app_config.app_secret, student_no, code),
                    now,
                    now,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    with TestClient(app) as student_client:
        no_canonical_fallback = student_client.post(
            "/api/student/login",
            json={
                "student_no": fullwidth_number,
                "name": same_name,
                "activation_code": ascii_code,
            },
        )
        assert no_canonical_fallback.status_code == 401, no_canonical_fallback.text

        exact_login = student_client.post(
            "/api/student/login",
            json={
                "student_no": fullwidth_number,
                "name": same_name,
                "activation_code": fullwidth_code,
            },
        )
        assert exact_login.status_code == 200, exact_login.text
        assert exact_login.json()["student"]["student_no"] == fullwidth_number


def test_safe_legacy_envelope_does_not_reveal_account_existence(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    major_id = dashboard["majors"][0]["id"]
    active_number = "LEGACY.ACTIVE.2026"
    inactive_number = "LEGACY.INACTIVE.2026"
    correct_name = "=Legacy Student"
    correct_code = "A1B2C3"
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        connection.execute("BEGIN IMMEDIATE")
        for student_no, active in (
            (active_number, 1),
            (inactive_number, 0),
        ):
            connection.execute(
                """
                INSERT INTO students
                    (student_no, name, major_id, activation_hash,
                     activation_ciphertext, active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    student_no,
                    correct_name,
                    major_id,
                    activation_code_hash(app_config.app_secret, correct_code),
                    encrypt_activation_code(
                        app_config.app_secret, student_no, correct_code
                    ),
                    active,
                    now,
                    now,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    attempts = [
        {
            "student_no": active_number,
            "name": correct_name,
            "activation_code": "Z9Y8X7",
        },
        {
            "student_no": "LEGACY.MISSING.2026",
            "name": correct_name,
            "activation_code": correct_code,
        },
        {
            "student_no": active_number,
            "name": "=Wrong Legacy Name",
            "activation_code": correct_code,
        },
        {
            "student_no": inactive_number,
            "name": correct_name,
            "activation_code": correct_code,
        },
    ]
    responses = []
    with TestClient(app) as student_client:
        for payload in attempts:
            response = student_client.post("/api/student/login", json=payload)
            responses.append((response.status_code, response.json()))
    assert responses == [
        (401, {"detail": "学号、姓名或激活码不正确"}) for _ in attempts
    ]


@pytest.mark.parametrize(
    "payload",
    [
        {"student_no": "", "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "L" * 41, "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "20260001", "name": "N" * 81, "activation_code": "A1B2C3"},
        {"student_no": "bad\nnumber", "name": "正常姓名", "activation_code": "A1B2C3"},
        {"student_no": "20260001", "name": "bad\x07name", "activation_code": "A1B2C3"},
        {"student_no": "20260001", "name": "正常姓名", "activation_code": "BAD*12"},
    ],
)
def test_login_request_rejects_only_outside_safe_historical_envelope(
    client: TestClient, payload: dict[str, str]
):
    response = client.post("/api/student/login", json=payload)
    assert response.status_code == 422, response.text


@pytest.mark.parametrize(
    "value",
    ["ABC", "A" * 33, "with space", "2026/001", "bad\nnumber"],
)
def test_shared_student_number_validator_rejects_unusable_values(value: str):
    with pytest.raises(StudentIdentityError):
        normalize_student_number(value)
