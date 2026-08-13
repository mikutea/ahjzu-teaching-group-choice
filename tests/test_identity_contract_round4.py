from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from server.database import connect, utc_now
from server.main import StudentLogin
from server.roster import parse_roster_file
from server.security import (
    activation_code_hash,
    decrypt_activation_code,
    encrypt_activation_code,
)
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
    *, app_config, client: TestClient, student_no: str, name: str, code: str
) -> None:
    major_id = client.get("/api/admin/dashboard").json()["majors"][0]["id"]
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
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
                activation_code_hash(app_config.app_secret, code),
                encrypt_activation_code(app_config.app_secret, student_no, code),
                now,
                now,
            ),
        )
        connection.commit()
    finally:
        connection.close()


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


def test_merge_updates_pre_nfkc_student_without_creating_a_canonical_sibling(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    major = dashboard["majors"][0]
    legacy_number = "ＡＢＣＤ"
    canonical_number = "ABCD"
    old_name = "旧格式迁移学生"
    new_name = "旧格式更名学生"
    old_code = "A1B2C3"
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO students
                (student_no, name, major_id, activation_hash,
                 activation_ciphertext, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                legacy_number,
                old_name,
                major["id"],
                activation_code_hash(app_config.app_secret, old_code),
                encrypt_activation_code(
                    app_config.app_secret, legacy_number, old_code
                ),
                now,
                now,
            ),
        )
        legacy_id = int(cursor.lastrowid)
        connection.commit()
    finally:
        connection.close()

    student_client = TestClient(app)
    try:
        assert student_client.post(
            "/api/student/login",
            json={
                "student_no": legacy_number,
                "name": old_name,
                "activation_code": old_code,
            },
        ).status_code == 200

        document_number = fictional_document_number("pre-nfkc-rekey")
        new_code = document_number[-6:]
        imported = client.post(
            "/api/admin/students/import",
            headers=admin_headers,
            files={
                "file": (
                    "pre-nfkc.csv",
                    roster_csv(
                        [(legacy_number, new_name, major["name"], document_number)]
                    ),
                    "text/csv",
                )
            },
        )
        assert imported.status_code == 200, imported.text
        assert imported.json()["created"] == 0
        assert imported.json()["updated"] == 1
        assert imported.json()["rotated"] == 1
        assert student_client.get("/api/student/me").status_code == 401

        connection = connect(app_config.database_path)
        try:
            rows = connection.execute(
                """
                SELECT id, student_no, name, activation_hash, activation_ciphertext
                FROM students WHERE student_no IN (?, ?)
                """,
                (legacy_number, canonical_number),
            ).fetchall()
        finally:
            connection.close()
        assert len(rows) == 1
        migrated = rows[0]
        assert int(migrated["id"]) == legacy_id
        assert migrated["student_no"] == legacy_number
        assert migrated["name"] == new_name
        assert decrypt_activation_code(
            app_config.app_secret,
            legacy_number,
            migrated["activation_ciphertext"],
        ) == new_code
        assert old_code != new_code

        assert student_client.post(
            "/api/student/login",
            json={
                "student_no": legacy_number,
                "name": old_name,
                "activation_code": old_code,
            },
        ).status_code == 401
        migrated_login = student_client.post(
            "/api/student/login",
            json={
                "student_no": legacy_number,
                "name": new_name,
                "activation_code": new_code,
            },
        )
        assert migrated_login.status_code == 200, migrated_login.text
        assert migrated_login.json()["student"]["student_no"] == legacy_number
    finally:
        student_client.close()


def test_merge_rejects_ambiguous_nfkc_equivalents_atomically(
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    major = client.get("/api/admin/dashboard").json()["majors"][0]
    canonical_number = "ABCD"
    legacy_number = "ＡＢＣＤ"
    third_variant = "𝐀𝐁𝐂𝐃"
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        for student_no, name, code in (
            (canonical_number, "规范记录", "A1B2C3"),
            (legacy_number, "旧格式记录", "Z9Y8X7"),
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
                    name,
                    major["id"],
                    activation_code_hash(app_config.app_secret, code),
                    encrypt_activation_code(app_config.app_secret, student_no, code),
                    now,
                    now,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    rejected = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "file": (
                "ambiguous.csv",
                roster_csv(
                    [
                        (
                            third_variant,
                            "本次更名",
                            major["name"],
                            fictional_document_number("ambiguous-nfkc"),
                        )
                    ]
                ),
                "text/csv",
            )
        },
    )
    assert rejected.status_code == 409, rejected.text
    assert "多条旧格式学生记录" in rejected.json()["detail"]

    connection = connect(app_config.database_path)
    try:
        rows = connection.execute(
            "SELECT student_no, name, activation_hash FROM students ORDER BY id"
        ).fetchall()
    finally:
        connection.close()
    assert [(row["student_no"], row["name"]) for row in rows] == [
        (canonical_number, "规范记录"),
        (legacy_number, "旧格式记录"),
    ]


def test_sync_keeps_resolved_pre_nfkc_student_active(
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    major = client.get("/api/admin/dashboard").json()["majors"][0]
    legacy_number = "ＳＹＮＣ２０２６"
    name = "同步旧格式学生"
    old_code = "A1B2C3"
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO students
                (student_no, name, major_id, activation_hash,
                 activation_ciphertext, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                legacy_number,
                name,
                major["id"],
                activation_code_hash(app_config.app_secret, old_code),
                encrypt_activation_code(
                    app_config.app_secret, legacy_number, old_code
                ),
                now,
                now,
            ),
        )
        student_id = int(cursor.lastrowid)
        connection.commit()
    finally:
        connection.close()

    document_number = fictional_document_number("sync-pre-nfkc")
    imported = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        params={"mode": "sync"},
        files={
            "file": (
                "sync-pre-nfkc.csv",
                roster_csv(
                    [(legacy_number, name, major["name"], document_number)]
                ),
                "text/csv",
            )
        },
    )
    assert imported.status_code == 200, imported.text
    assert imported.json()["updated"] == 1
    assert imported.json()["deactivated"] == 0

    connection = connect(app_config.database_path)
    try:
        stored = connection.execute(
            "SELECT id, student_no, active FROM students"
        ).fetchall()
    finally:
        connection.close()
    assert [(int(row["id"]), row["student_no"], int(row["active"])) for row in stored] == [
        (student_id, legacy_number, 1)
    ]


def test_selected_legacy_student_major_change_rolls_back_entire_reimport(
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    dashboard = client.get("/api/admin/dashboard").json()
    old_major, new_major = dashboard["majors"][:2]
    group = dashboard["groups"][0]
    legacy_number = "ＳＥＬ２０２６"
    old_name = "已选旧格式学生"
    old_code = "A1B2C3"
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        cursor = connection.execute(
            """
            INSERT INTO students
                (student_no, name, major_id, activation_hash,
                 activation_ciphertext, active, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (
                legacy_number,
                old_name,
                old_major["id"],
                activation_code_hash(app_config.app_secret, old_code),
                encrypt_activation_code(
                    app_config.app_secret, legacy_number, old_code
                ),
                now,
                now,
            ),
        )
        student_id = int(cursor.lastrowid)
        connection.execute(
            """
            INSERT INTO selections
                (student_id, group_id, selected_at, source, operator)
            VALUES (?, ?, ?, 'admin', 'legacy-regression')
            """,
            (student_id, group["id"], now),
        )
        before = tuple(
            connection.execute(
                """
                SELECT student_no, name, major_id, activation_hash,
                       activation_ciphertext, active
                FROM students WHERE id = ?
                """,
                (student_id,),
            ).fetchone()
        )
        connection.commit()
    finally:
        connection.close()

    rejected = client.post(
        "/api/admin/students/import",
        headers=admin_headers,
        files={
            "file": (
                "selected-legacy.csv",
                roster_csv(
                    [
                        (
                            legacy_number,
                            "试图更名学生",
                            new_major["name"],
                            fictional_document_number("selected-legacy-change"),
                        )
                    ]
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
                """
                SELECT student_no, name, major_id, activation_hash,
                       activation_ciphertext, active
                FROM students WHERE id = ?
                """,
                (student_id,),
            ).fetchone()
        )
        active_selection = connection.execute(
            """
            SELECT COUNT(*) FROM selections
            WHERE student_id = ? AND revoked_at IS NULL
            """,
            (student_id,),
        ).fetchone()[0]
    finally:
        connection.close()
    assert after == before
    assert active_selection == 1


def test_colliding_raw_and_canonical_students_have_independent_login_limits(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
):
    major_id = client.get("/api/admin/dashboard").json()["majors"][0]["id"]
    canonical_number = "ABCD"
    legacy_number = "ＡＢＣＤ"
    name = "限流隔离学生"
    canonical_code = "A1B2C3"
    legacy_code = "Z9Y8X7"
    connection = connect(app_config.database_path)
    try:
        now = utc_now()
        for student_no, activation_code in (
            (canonical_number, canonical_code),
            (legacy_number, legacy_code),
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
                    name,
                    major_id,
                    activation_code_hash(app_config.app_secret, activation_code),
                    encrypt_activation_code(
                        app_config.app_secret, student_no, activation_code
                    ),
                    now,
                    now,
                ),
            )
        connection.commit()
    finally:
        connection.close()

    with TestClient(app) as student_client:
        for _ in range(9):
            rejected = student_client.post(
                "/api/student/login",
                json={
                    "student_no": legacy_number,
                    "name": name,
                    "activation_code": "Q1W2E3",
                },
            )
            assert rejected.status_code == 401, rejected.text

        canonical_login = student_client.post(
            "/api/student/login",
            json={
                "student_no": canonical_number,
                "name": name,
                "activation_code": canonical_code,
            },
        )
        assert canonical_login.status_code == 200, canonical_login.text

        tenth_legacy_attempt = student_client.post(
            "/api/student/login",
            json={
                "student_no": legacy_number,
                "name": name,
                "activation_code": "Q1W2E3",
            },
        )
        assert tenth_legacy_attempt.status_code == 401, tenth_legacy_attempt.text

        still_limited = student_client.post(
            "/api/student/login",
            json={
                "student_no": legacy_number,
                "name": name,
                "activation_code": legacy_code,
            },
        )
        assert still_limited.status_code == 429, still_limited.text


@pytest.mark.parametrize("reverse_direction", [False, True])
@pytest.mark.parametrize("account_exists", [False, True])
def test_unresolved_nfkc_aliases_cannot_reveal_account_existence_via_rate_limit(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
    account_exists: bool,
    reverse_direction: bool,
):
    canonical_number = "ENUM2026"
    nfkc_alias = "ＥＮＵＭ２０２６"
    name = "枚举保护学生"
    correct_code = "A1B2C3"
    if account_exists:
        insert_login_identity(
            app_config=app_config,
            client=client,
            student_no=canonical_number,
            name=name,
            code=correct_code,
        )
    first_number, probe_number = (
        (nfkc_alias, canonical_number)
        if reverse_direction
        else (canonical_number, nfkc_alias)
    )

    with TestClient(app) as student_client:
        for _ in range(10):
            rejected = student_client.post(
                "/api/student/login",
                json={
                    "student_no": first_number,
                    "name": name,
                    "activation_code": "Q1W2E3",
                },
            )
            assert rejected.status_code == 401, rejected.text

        nfkc_probe = student_client.post(
            "/api/student/login",
            json={
                "student_no": probe_number,
                "name": name,
                "activation_code": correct_code,
            },
        )
        assert nfkc_probe.status_code == 429, nfkc_probe.text


@pytest.mark.parametrize("account_exists", [False, True])
def test_case_sensitive_unresolved_buckets_do_not_reveal_account_existence(
    app,
    app_config,
    client: TestClient,
    admin_headers: dict[str, str],
    account_exists: bool,
):
    stored_number = "CASE2026"
    distinct_number = "case2026"
    name = "大小写枚举保护学生"
    correct_code = "A1B2C3"
    if account_exists:
        insert_login_identity(
            app_config=app_config,
            client=client,
            student_no=stored_number,
            name=name,
            code=correct_code,
        )

    with TestClient(app) as student_client:
        for _ in range(10):
            rejected = student_client.post(
                "/api/student/login",
                json={
                    "student_no": stored_number,
                    "name": name,
                    "activation_code": "Q1W2E3",
                },
            )
            assert rejected.status_code == 401, rejected.text

        case_probe = student_client.post(
            "/api/student/login",
            json={
                "student_no": distinct_number,
                "name": name,
                "activation_code": correct_code,
            },
        )
        assert case_probe.status_code == 401, case_probe.text


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
