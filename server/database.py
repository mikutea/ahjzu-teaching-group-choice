from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

from .config import Config
from .current_contract import (
    normalize_activity_code,
    normalize_admin_username,
    normalize_named_value,
    normalize_public_base_url,
)
from .security import (
    hash_password,
    validate_password_hash,
    verify_activation_ciphertext,
)
from .student_identity import (
    StudentIdentityError,
    normalize_student_name,
    normalize_student_number,
)


SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('closed', 'open', 'archived')),
    created_at TEXT NOT NULL,
    opened_at TEXT,
    closed_at TEXT,
    archived_at TEXT,
    selection_opens_at TEXT,
    summary_json TEXT,
    snapshot_json TEXT,
    snapshot_sha256 TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS one_live_activity
ON activities((1)) WHERE status <> 'archived';

CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    activity_title TEXT NOT NULL,
    organization_name TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('closed', 'open')),
    public_base_url TEXT NOT NULL DEFAULT '',
    current_activity_id INTEGER REFERENCES activities(id) ON DELETE RESTRICT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TRIGGER IF NOT EXISTS copyright_settings_guard_update
BEFORE UPDATE OF organization_name, owner_name ON settings
WHEN NEW.organization_name <> '安徽建筑大学 · 建筑与空间规划学院'
  OR NEW.owner_name <> 'Mikutea'
BEGIN
    SELECT RAISE(ABORT, 'copyright settings are fixed');
END;
CREATE TRIGGER IF NOT EXISTS copyright_settings_guard_insert
BEFORE INSERT ON settings
WHEN NEW.organization_name <> '安徽建筑大学 · 建筑与空间规划学院'
  OR NEW.owner_name <> 'Mikutea'
BEGIN
    SELECT RAISE(ABORT, 'copyright settings are fixed');
END;

CREATE TABLE IF NOT EXISTS majors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS teaching_groups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL UNIQUE,
    total_capacity INTEGER NOT NULL DEFAULT 30 CHECK (total_capacity >= 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS quotas (
    major_id INTEGER NOT NULL REFERENCES majors(id) ON DELETE CASCADE,
    group_id INTEGER NOT NULL REFERENCES teaching_groups(id) ON DELETE CASCADE,
    capacity INTEGER NOT NULL DEFAULT 0 CHECK (capacity >= 0),
    updated_at TEXT NOT NULL,
    PRIMARY KEY (major_id, group_id)
);
CREATE TRIGGER IF NOT EXISTS quota_group_capacity_guard_insert
BEFORE INSERT ON quotas
WHEN NEW.capacity + COALESCE((
    SELECT SUM(capacity) FROM quotas WHERE group_id = NEW.group_id
), 0) > COALESCE((
    SELECT total_capacity FROM teaching_groups WHERE id = NEW.group_id
), -1)
BEGIN
    SELECT RAISE(ABORT, 'group quota sum exceeds total capacity');
END;
CREATE TRIGGER IF NOT EXISTS quota_group_capacity_guard_update
BEFORE UPDATE OF major_id, group_id, capacity ON quotas
WHEN NEW.capacity + COALESCE((
    SELECT SUM(capacity) FROM quotas
    WHERE group_id = NEW.group_id
      AND NOT (major_id = OLD.major_id AND group_id = OLD.group_id)
), 0) > COALESCE((
    SELECT total_capacity FROM teaching_groups WHERE id = NEW.group_id
), -1)
BEGIN
    SELECT RAISE(ABORT, 'group quota sum exceeds total capacity');
END;
CREATE TRIGGER IF NOT EXISTS group_total_capacity_guard_update
BEFORE UPDATE OF total_capacity ON teaching_groups
WHEN NEW.total_capacity < COALESCE((
    SELECT SUM(capacity) FROM quotas WHERE group_id = OLD.id
), 0)
BEGIN
    SELECT RAISE(ABORT, 'group total capacity below quota sum');
END;

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_no TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    major_id INTEGER NOT NULL REFERENCES majors(id) ON DELETE RESTRICT,
    activation_hash TEXT NOT NULL,
    activation_ciphertext TEXT NOT NULL
        CHECK (length(trim(activation_ciphertext)) > 0),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS selections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id) ON DELETE RESTRICT,
    group_id INTEGER NOT NULL REFERENCES teaching_groups(id) ON DELETE RESTRICT,
    selected_at TEXT NOT NULL,
    source TEXT NOT NULL CHECK (source IN ('student', 'admin')),
    operator TEXT NOT NULL,
    revoked_at TEXT,
    revoked_by TEXT
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_selection_per_student
ON selections(student_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS selections_active_group
ON selections(group_id, revoked_at);
CREATE INDEX IF NOT EXISTS students_major
ON students(major_id, active);
CREATE TRIGGER IF NOT EXISTS student_activation_ciphertext_guard_insert
BEFORE INSERT ON students
WHEN NEW.activation_ciphertext IS NULL
     OR length(trim(NEW.activation_ciphertext)) = 0
BEGIN
    SELECT RAISE(ABORT, 'student activation ciphertext required');
END;
CREATE TRIGGER IF NOT EXISTS student_activation_ciphertext_guard_update
BEFORE UPDATE OF activation_ciphertext ON students
WHEN NEW.activation_ciphertext IS NULL
     OR length(trim(NEW.activation_ciphertext)) = 0
BEGIN
    SELECT RAISE(ABORT, 'student activation ciphertext required');
END;
CREATE TRIGGER IF NOT EXISTS selection_capacity_guard
BEFORE INSERT ON selections
WHEN NEW.revoked_at IS NULL
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM students s
        JOIN quotas q ON q.major_id = s.major_id AND q.group_id = NEW.group_id
        WHERE s.id = NEW.student_id
    ) THEN RAISE(ABORT, 'selection quota missing') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM selections
        WHERE group_id = NEW.group_id AND revoked_at IS NULL
    ) >= (
        SELECT total_capacity FROM teaching_groups WHERE id = NEW.group_id
    ) THEN RAISE(ABORT, 'teaching group capacity exceeded') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM selections se
        JOIN students selected_student ON selected_student.id = se.student_id
        WHERE se.group_id = NEW.group_id AND se.revoked_at IS NULL
          AND selected_student.major_id = (
              SELECT major_id FROM students WHERE id = NEW.student_id
          )
    ) >= (
        SELECT q.capacity FROM quotas q
        JOIN students choosing_student ON choosing_student.major_id = q.major_id
        WHERE choosing_student.id = NEW.student_id AND q.group_id = NEW.group_id
    ) THEN RAISE(ABORT, 'major quota exceeded') END;
END;
CREATE TRIGGER IF NOT EXISTS selection_capacity_guard_update
BEFORE UPDATE OF student_id, group_id, revoked_at ON selections
WHEN NEW.revoked_at IS NULL AND (
    OLD.revoked_at IS NOT NULL
    OR NEW.student_id <> OLD.student_id
    OR NEW.group_id <> OLD.group_id
)
BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM students s
        JOIN quotas q ON q.major_id = s.major_id AND q.group_id = NEW.group_id
        WHERE s.id = NEW.student_id
    ) THEN RAISE(ABORT, 'selection quota missing') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM selections
        WHERE group_id = NEW.group_id AND revoked_at IS NULL AND id <> OLD.id
    ) >= (
        SELECT total_capacity FROM teaching_groups WHERE id = NEW.group_id
    ) THEN RAISE(ABORT, 'teaching group capacity exceeded') END;
    SELECT CASE WHEN (
        SELECT COUNT(*) FROM selections se
        JOIN students selected_student ON selected_student.id = se.student_id
        WHERE se.group_id = NEW.group_id AND se.revoked_at IS NULL
          AND se.id <> OLD.id
          AND selected_student.major_id = (
              SELECT major_id FROM students WHERE id = NEW.student_id
          )
    ) >= (
        SELECT q.capacity FROM quotas q
        JOIN students choosing_student ON choosing_student.major_id = q.major_id
        WHERE choosing_student.id = NEW.student_id AND q.group_id = NEW.group_id
    ) THEN RAISE(ABORT, 'major quota exceeded') END;
END;

CREATE TABLE IF NOT EXISTS admin_users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    role TEXT NOT NULL CHECK (role IN ('student', 'admin')),
    subject_id INTEGER NOT NULL,
    csrf_token TEXT NOT NULL,
    created_at TEXT NOT NULL,
    last_seen_at TEXT,
    expires_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS sessions_expiry ON sessions(expires_at);

CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at TEXT NOT NULL,
    actor_type TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    action TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    details_json TEXT NOT NULL,
    activity_id INTEGER REFERENCES activities(id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS audit_logs_time ON audit_logs(occurred_at DESC);
CREATE INDEX IF NOT EXISTS audit_logs_activity_time
ON audit_logs(activity_id, occurred_at DESC);
CREATE TRIGGER IF NOT EXISTS sync_activity_title_to_settings
AFTER UPDATE OF title ON activities
WHEN NEW.id = (SELECT current_activity_id FROM settings WHERE id = 1)
     AND (SELECT activity_title FROM settings WHERE id = 1) IS NOT NEW.title
BEGIN
    UPDATE settings SET activity_title = NEW.title WHERE id = 1;
END;
CREATE TRIGGER IF NOT EXISTS sync_activity_status_to_settings
AFTER UPDATE OF status ON activities
WHEN NEW.id = (SELECT current_activity_id FROM settings WHERE id = 1)
     AND NEW.status IN ('closed', 'open')
     AND (SELECT status FROM settings WHERE id = 1) IS NOT NEW.status
BEGIN
    UPDATE settings SET status = NEW.status WHERE id = 1;
END;
CREATE TRIGGER IF NOT EXISTS sync_settings_title_to_activity
AFTER UPDATE OF activity_title ON settings
WHEN NEW.current_activity_id IS NOT NULL
     AND (SELECT title FROM activities WHERE id = NEW.current_activity_id)
         IS NOT NEW.activity_title
BEGIN
    UPDATE activities SET title = NEW.activity_title WHERE id = NEW.current_activity_id;
END;
CREATE TRIGGER IF NOT EXISTS sync_settings_status_to_activity
AFTER UPDATE OF status ON settings
WHEN NEW.current_activity_id IS NOT NULL
     AND (SELECT status FROM activities WHERE id = NEW.current_activity_id)
         IS NOT NEW.status
BEGIN
    UPDATE activities
    SET status = NEW.status,
        opened_at = CASE
            WHEN NEW.status = 'open' THEN COALESCE(opened_at, NEW.updated_at)
            ELSE opened_at
        END,
        closed_at = CASE
            WHEN NEW.status = 'closed' THEN NEW.updated_at
            ELSE closed_at
        END
    WHERE id = NEW.current_activity_id;
END;
CREATE TRIGGER IF NOT EXISTS assign_current_activity_to_audit
AFTER INSERT ON audit_logs
WHEN NEW.activity_id IS NULL
BEGIN
    UPDATE audit_logs
    SET activity_id = (SELECT current_activity_id FROM settings WHERE id = 1)
    WHERE id = NEW.id;
END;
"""


_SCHEMA_OBJECT_TYPES = ("table", "index", "trigger", "view")


def _schema_object_catalog(
    connection: sqlite3.Connection,
) -> dict[tuple[str, str], str]:
    """Return every application-owned schema object and its stored DDL.

    SQLite's own ``sqlite_*`` tables and automatic indexes are deliberately
    outside the application contract.  Everything else must be created by the
    current ``SCHEMA`` verbatim; accepting only object names would let a stale
    or replaced trigger/index pass the release gate.
    """

    placeholders = ", ".join("?" for _ in _SCHEMA_OBJECT_TYPES)
    rows = connection.execute(
        f"""
        SELECT type, name, sql
        FROM sqlite_master
        WHERE type IN ({placeholders})
          AND name NOT LIKE 'sqlite_%'
        ORDER BY type, name
        """,
        _SCHEMA_OBJECT_TYPES,
    ).fetchall()
    return {
        (str(row[0]), str(row[1])): str(row[2] or "").strip()
        for row in rows
    }


def _build_current_schema_catalog() -> dict[tuple[str, str], str]:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(SCHEMA)
        return _schema_object_catalog(connection)
    finally:
        connection.close()


CURRENT_SCHEMA_CATALOG = _build_current_schema_catalog()


DEFAULT_MAJORS = ["建筑学", "城乡规划", "风景园林"]
SCHEMA_VERSION = 3
FIXED_ORGANIZATION_NAME = "安徽建筑大学 · 建筑与空间规划学院"
FIXED_OWNER_NAME = "Mikutea"
REQUIRED_CURRENT_TRIGGERS = frozenset(
    {
        "selection_capacity_guard",
        "selection_capacity_guard_update",
        "quota_group_capacity_guard_insert",
        "quota_group_capacity_guard_update",
        "group_total_capacity_guard_update",
        "sync_activity_title_to_settings",
        "sync_activity_status_to_settings",
        "sync_settings_title_to_activity",
        "sync_settings_status_to_activity",
        "assign_current_activity_to_audit",
        "copyright_settings_guard_update",
        "copyright_settings_guard_insert",
        "student_activation_ciphertext_guard_insert",
        "student_activation_ciphertext_guard_update",
    }
)
REQUIRED_CURRENT_INDEXES = frozenset(
    {
        "one_live_activity",
        "one_active_selection_per_student",
        "selections_active_group",
        "students_major",
        "sessions_expiry",
        "audit_logs_time",
        "audit_logs_activity_time",
    }
)
DEFAULT_GROUPS = [f"第{i}教学组" for i in range(1, 7)]
DEFAULT_QUOTAS = {
    "建筑学": [10, 10, 10, 10, 10, 10],
    "城乡规划": [9, 9, 8, 8, 8, 8],
    "风景园林": [6, 6, 6, 6, 6, 5],
}


def utc_now() -> str:
    # Millisecond precision prevents a nominal ten-second countdown from being
    # shortened by truncating both ends to whole seconds.
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(database_path), timeout=10, isolation_level=None, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def _create_initial_activity(connection: sqlite3.Connection, now: str) -> int:
    settings = connection.execute(
        """
        SELECT activity_title, status, current_activity_id, created_at, updated_at
        FROM settings WHERE id = 1
        """
    ).fetchone()
    if not settings:
        raise RuntimeError("系统设置尚未初始化")
    if settings["current_activity_id"] is not None:
        raise RuntimeError("全新数据库不能预先指向活动")
    if connection.execute("SELECT 1 FROM activities LIMIT 1").fetchone():
        raise RuntimeError("全新数据库不能包含既有活动")
    cursor = connection.execute(
        """
        INSERT INTO activities
            (code, title, status, created_at, opened_at, closed_at)
        VALUES (?, ?, 'closed', ?, NULL, ?)
        """,
        (
            "activity-1",
            settings["activity_title"],
            settings["created_at"] or now,
            settings["updated_at"] or now,
        ),
    )
    activity_id = int(cursor.lastrowid)
    connection.execute(
        "UPDATE settings SET current_activity_id = ? WHERE id = 1", (activity_id,)
    )
    return int(activity_id)


def validate_current_schema_fingerprint(connection: sqlite3.Connection) -> None:
    """Reject every non-current application schema object, fail closed."""

    actual = _schema_object_catalog(connection)
    expected_keys = set(CURRENT_SCHEMA_CATALOG)
    actual_keys = set(actual)

    unexpected = sorted(actual_keys - expected_keys)
    if unexpected:
        labels = "、".join(f"{object_type} {name}" for object_type, name in unexpected)
        raise RuntimeError(f"当前数据库包含 SCHEMA 未定义的结构对象：{labels}")

    missing = sorted(expected_keys - actual_keys)
    if missing:
        labels = "、".join(f"{object_type} {name}" for object_type, name in missing)
        raise RuntimeError(f"当前数据库缺少 SCHEMA 定义的结构对象：{labels}")

    mismatched = sorted(
        key
        for key in expected_keys
        if actual[key] != CURRENT_SCHEMA_CATALOG[key]
    )
    if mismatched:
        labels = "、".join(f"{object_type} {name}" for object_type, name in mismatched)
        raise RuntimeError(f"当前数据库结构对象定义与 SCHEMA 不一致：{labels}")


def _is_canonical_stored_text(
    value: object, normalizer: Callable[[str], str]
) -> bool:
    if not isinstance(value, str):
        return False
    try:
        return normalizer(value) == value
    except (TypeError, ValueError, StudentIdentityError):
        return False


def _parse_aware_iso_timestamp(value: object, *, label: str) -> datetime:
    if not isinstance(value, str):
        raise RuntimeError(f"当前数据库{label}格式不正确")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise RuntimeError(f"当前数据库{label}格式不正确") from exc
    if parsed.utcoffset() is None:
        raise RuntimeError(f"当前数据库{label}缺少时区")
    return parsed


def validate_current_business_values(connection: sqlite3.Connection) -> None:
    """Validate that stored business values equal the current input contract."""

    for student_no, name in connection.execute(
        "SELECT student_no, name FROM students"
    ).fetchall():
        if not _is_canonical_stored_text(student_no, normalize_student_number) or not (
            _is_canonical_stored_text(name, normalize_student_name)
        ):
            raise RuntimeError("当前数据库学生学号或姓名不符合当前规范")

    admin_rows = connection.execute(
        "SELECT username, password_hash FROM admin_users"
    ).fetchall()
    if not admin_rows:
        raise RuntimeError("当前数据库缺少管理员账号")
    for username, password_hash in admin_rows:
        if not _is_canonical_stored_text(username, normalize_admin_username):
            raise RuntimeError("当前数据库管理员账号不符合当前规范")
        if not validate_password_hash(password_hash):
            raise RuntimeError("当前数据库管理员密码摘要不符合当前 PBKDF2 格式")

    settings = connection.execute(
        "SELECT activity_title, public_base_url FROM settings WHERE id = 1"
    ).fetchone()
    if not settings:
        raise RuntimeError("当前数据库缺少系统设置")
    if not _is_canonical_stored_text(
        settings[0],
        lambda value: normalize_named_value(
            value, label="活动标题", minimum=2, maximum=120
        ),
    ):
        raise RuntimeError("当前数据库活动标题不符合当前规范")
    if not _is_canonical_stored_text(settings[1], normalize_public_base_url):
        raise RuntimeError("当前数据库访问地址不符合当前规范")

    for code, title, status, opened_at, selection_opens_at in connection.execute(
        """
        SELECT code, title, status, opened_at, selection_opens_at
        FROM activities
        """
    ).fetchall():
        if not _is_canonical_stored_text(code, normalize_activity_code):
            raise RuntimeError("当前数据库活动编码不符合当前规范")
        if not _is_canonical_stored_text(
            title,
            lambda value: normalize_named_value(
                value, label="活动标题", minimum=2, maximum=120
            ),
        ):
            raise RuntimeError("当前数据库活动标题不符合当前规范")
        if selection_opens_at is not None:
            _parse_aware_iso_timestamp(selection_opens_at, label="开抢时间")
        if opened_at is not None:
            _parse_aware_iso_timestamp(opened_at, label="活动开放时间")
        if status == "open":
            if selection_opens_at is None:
                raise RuntimeError("当前数据库开放活动缺少开抢时间")
            if opened_at is None or opened_at != selection_opens_at:
                raise RuntimeError("当前数据库开放活动的开放时间与开抢时间不一致")
        elif selection_opens_at is not None:
            raise RuntimeError("当前数据库非开放活动仍保留开抢时间")

    named_tables = (
        ("majors", "专业", 1, 80),
        ("teaching_groups", "教学组", 1, 80),
    )
    for table, label, minimum, maximum in named_tables:
        for (name,) in connection.execute(f"SELECT name FROM {table}").fetchall():
            if not _is_canonical_stored_text(
                name,
                lambda value, *, _label=label, _minimum=minimum, _maximum=maximum: normalize_named_value(
                    value,
                    label=_label,
                    minimum=_minimum,
                    maximum=_maximum,
                ),
            ):
                raise RuntimeError(f"当前数据库{label}名称不符合当前规范")


def _validate_existing_current_database(
    connection: sqlite3.Connection, app_secret: str
) -> None:
    required_columns = {
        "activities": {"id", "title", "status", "selection_opens_at"},
        "settings": {
            "id",
            "activity_title",
            "organization_name",
            "owner_name",
            "status",
            "current_activity_id",
        },
        "majors": {"id"},
        "teaching_groups": {"id"},
        "quotas": {"major_id", "group_id", "capacity"},
        "students": {"id", "activation_ciphertext"},
        "selections": {"id"},
        "admin_users": {"id"},
        "sessions": {"token_hash", "last_seen_at"},
        "audit_logs": {"id", "activity_id"},
    }
    tables = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    missing_tables = sorted(required_columns.keys() - tables)
    if missing_tables:
        raise RuntimeError(
            "当前数据库缺少关键表：" + "、".join(missing_tables)
        )
    for table, expected_columns in required_columns.items():
        table_columns = connection.execute(f"PRAGMA table_info({table})").fetchall()
        actual_columns = {str(row["name"]) for row in table_columns}
        if not expected_columns <= actual_columns:
            raise RuntimeError(f"当前数据库表 {table} 缺少当前版本字段")
        if table == "students":
            ciphertext_column = next(
                row
                for row in table_columns
                if str(row["name"]) == "activation_ciphertext"
            )
            if int(ciphertext_column["notnull"]) != 1:
                raise RuntimeError("当前数据库学生激活码密文字段缺少 NOT NULL 约束")

    students_sql_row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'students'"
    ).fetchone()
    normalized_students_sql = "".join(str(students_sql_row["sql"]).lower().split())
    if "check(length(trim(activation_ciphertext))>0)" not in normalized_students_sql:
        raise RuntimeError("当前数据库学生激活码密文字段缺少非空检查约束")

    settings = connection.execute(
        """
        SELECT activity_title, organization_name, owner_name, status,
               current_activity_id
        FROM settings WHERE id = 1
        """
    ).fetchone()
    if not settings:
        raise RuntimeError("当前数据库缺少系统设置")
    if (
        settings["organization_name"] != FIXED_ORGANIZATION_NAME
        or settings["owner_name"] != FIXED_OWNER_NAME
    ):
        raise RuntimeError("当前数据库版权信息与固定发布信息不一致")
    if settings["current_activity_id"] is None:
        raise RuntimeError("当前数据库未指向当前活动")

    live_activities = connection.execute(
        """
        SELECT id, title, status, selection_opens_at
        FROM activities WHERE status <> 'archived'
        """
    ).fetchall()
    if len(live_activities) != 1:
        raise RuntimeError("当前数据库必须且只能有一个当前活动")
    activity = live_activities[0]
    if int(settings["current_activity_id"]) != int(activity["id"]):
        raise RuntimeError("当前数据库系统设置指向的活动不正确")
    if (
        settings["activity_title"] != activity["title"]
        or settings["status"] != activity["status"]
    ):
        raise RuntimeError("当前数据库活动与系统设置不同步")
    if activity["status"] == "open" and not activity["selection_opens_at"]:
        raise RuntimeError("当前数据库开放活动缺少开抢时间")
    if activity["selection_opens_at"] is not None:
        try:
            selection_opens_at = datetime.fromisoformat(
                str(activity["selection_opens_at"])
            )
        except ValueError as exc:
            raise RuntimeError("当前数据库开抢时间格式不正确") from exc
        if selection_opens_at.utcoffset() is None:
            raise RuntimeError("当前数据库开抢时间缺少时区")
    if activity["status"] == "closed" and activity["selection_opens_at"] is not None:
        raise RuntimeError("当前数据库关闭活动仍保留开抢时间")

    unassigned_audits = int(
        connection.execute(
            "SELECT COUNT(*) FROM audit_logs WHERE activity_id IS NULL"
        ).fetchone()[0]
    )
    if unassigned_audits:
        raise RuntimeError(
            f"当前数据库有 {unassigned_audits} 条审计日志未归属活动"
        )
    incomplete_credentials = int(
        connection.execute(
            """
            SELECT COUNT(*) FROM students
            WHERE activation_ciphertext IS NULL
               OR length(trim(activation_ciphertext)) = 0
            """
        ).fetchone()[0]
    )
    if incomplete_credentials:
        raise RuntimeError(
            f"当前数据库有 {incomplete_credentials} 名学生缺少激活码密文；"
            "请使用当前规范名单重新建立数据库"
        )
    invalid_credentials = [
        str(row["student_no"])
        for row in connection.execute(
            """
            SELECT student_no, activation_hash, activation_ciphertext
            FROM students
            """
        ).fetchall()
        if not verify_activation_ciphertext(
            app_secret,
            str(row["student_no"]),
            str(row["activation_ciphertext"]),
            str(row["activation_hash"]),
        )
    ]
    if invalid_credentials:
        raise RuntimeError(
            f"当前数据库有 {len(invalid_credentials)} 名学生的激活码密文无效或与摘要不一致；"
            "请使用当前规范名单重新建立数据库"
        )
    if not connection.execute("SELECT 1 FROM admin_users LIMIT 1").fetchone():
        raise RuntimeError("当前数据库缺少管理员账号")
    validate_current_business_values(connection)

    triggers = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    missing_triggers = sorted(REQUIRED_CURRENT_TRIGGERS - triggers)
    if missing_triggers:
        raise RuntimeError(
            "当前数据库缺少关键约束触发器：" + "、".join(missing_triggers)
        )
    indexes = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    missing_indexes = sorted(REQUIRED_CURRENT_INDEXES - indexes)
    if missing_indexes:
        raise RuntimeError(
            "当前数据库缺少关键索引：" + "、".join(missing_indexes)
        )
    validate_current_schema_fingerprint(connection)


def initialize_database(config: Config) -> None:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(config.database_path)
    try:
        database_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if database_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库版本 {database_version} 高于应用支持版本 {SCHEMA_VERSION}"
            )
        existing_tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        is_new_database = not existing_tables
        if existing_tables and database_version < SCHEMA_VERSION:
            raise RuntimeError(
                f"不再支持旧数据库版本 {database_version}；"
                f"请使用当前版本 {SCHEMA_VERSION} 的空库或已验证备份"
            )
        if not is_new_database:
            _validate_existing_current_database(connection, config.app_secret)

        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.executescript("BEGIN IMMEDIATE;\n" + SCHEMA)
        now = utc_now()
        if is_new_database:
            initial_public_base_url = normalize_public_base_url(config.public_base_url)
            initial_admin_username = normalize_admin_username(config.admin_username)
            connection.execute(
                """
                INSERT INTO settings
                    (id, activity_title, organization_name, owner_name, status,
                     public_base_url, created_at, updated_at)
                VALUES (1, ?, ?, ?, 'closed', ?, ?, ?)
                """,
                (
                    "2026级教学组线上抢选",
                    FIXED_ORGANIZATION_NAME,
                    FIXED_OWNER_NAME,
                    initial_public_base_url,
                    now,
                    now,
                ),
            )
            _create_initial_activity(connection, now)
            if not config.admin_initial_password:
                raise RuntimeError(
                    "首次启动必须提供 ADMIN_INITIAL_PASSWORD，初始化后可移除该变量"
                )
            connection.execute(
                """
                INSERT INTO admin_users (username, password_hash, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                """,
                (
                    initial_admin_username,
                    hash_password(config.admin_initial_password),
                    now,
                    now,
                ),
            )
            connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

        connection.commit()

        if config.seed_demo_structure and is_new_database:
            _seed_structure(connection, now)
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _seed_structure(connection: sqlite3.Connection, now: str) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        major_ids: dict[str, int] = {}
        for index, name in enumerate(DEFAULT_MAJORS, start=1):
            cursor = connection.execute(
                """
                INSERT INTO majors (code, name, active, sort_order, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?, ?)
                """,
                (f"major-{index}", name, index * 10, now, now),
            )
            major_ids[name] = int(cursor.lastrowid)

        group_ids: list[int] = []
        for index, name in enumerate(DEFAULT_GROUPS, start=1):
            cursor = connection.execute(
                """
                INSERT INTO teaching_groups
                    (code, name, total_capacity, active, sort_order, created_at, updated_at)
                VALUES (?, ?, 30, 1, ?, ?, ?)
                """,
                (f"group-{index}", name, index * 10, now, now),
            )
            group_ids.append(int(cursor.lastrowid))

        for major_name, capacities in DEFAULT_QUOTAS.items():
            for group_id, capacity in zip(group_ids, capacities, strict=True):
                connection.execute(
                    """
                    INSERT INTO quotas (major_id, group_id, capacity, updated_at)
                    VALUES (?, ?, ?, ?)
                    """,
                    (major_ids[major_name], group_id, capacity, now),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def audit(
    connection: sqlite3.Connection,
    *,
    actor_type: str,
    actor_id: str | int,
    action: str,
    entity_type: str,
    entity_id: str | int,
    details: dict[str, Any] | None = None,
    activity_id: int | None = None,
) -> None:
    if activity_id is None:
        settings = connection.execute(
            "SELECT current_activity_id FROM settings WHERE id = 1"
        ).fetchone()
        activity_id = int(settings["current_activity_id"]) if settings else None
    connection.execute(
        """
        INSERT INTO audit_logs
            (occurred_at, actor_type, actor_id, action, entity_type, entity_id,
             details_json, activity_id)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now(),
            actor_type,
            str(actor_id),
            action,
            entity_type,
            str(entity_id),
            json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
            activity_id,
        ),
    )


def activity_snapshot(
    connection: sqlite3.Connection,
    activity_id: int,
    *,
    archived_at: str | None = None,
) -> tuple[dict[str, Any], str]:
    activity = connection.execute(
        "SELECT id, code, title, status, created_at, opened_at, closed_at FROM activities WHERE id = ?",
        (activity_id,),
    ).fetchone()
    if not activity:
        raise RuntimeError("活动不存在")

    def rows(query: str, parameters: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        return [dict(row) for row in connection.execute(query, parameters).fetchall()]

    snapshot = {
        "schema_version": 1,
        "archived_at": archived_at or utc_now(),
        "activity": dict(activity),
        "majors": rows("SELECT * FROM majors ORDER BY sort_order, id"),
        "teaching_groups": rows("SELECT * FROM teaching_groups ORDER BY sort_order, id"),
        "quotas": rows("SELECT * FROM quotas ORDER BY major_id, group_id"),
        "students": rows(
            """
            SELECT s.id, s.student_no, s.name, s.major_id, s.active,
                   s.created_at, s.updated_at, m.name AS major_name
            FROM students s JOIN majors m ON m.id = s.major_id
            ORDER BY m.sort_order, s.student_no
            """
        ),
        "selections": rows(
            """
            SELECT se.*, s.student_no, s.name AS student_name,
                   m.name AS major_name, g.name AS group_name
            FROM selections se
            JOIN students s ON s.id = se.student_id
            JOIN majors m ON m.id = s.major_id
            JOIN teaching_groups g ON g.id = se.group_id
            ORDER BY se.id
            """
        ),
        "audit_logs": rows(
            """
            SELECT id, occurred_at, actor_type, actor_id, action,
                   entity_type, entity_id, details_json
            FROM audit_logs WHERE activity_id = ? ORDER BY id
            """,
            (activity_id,),
        ),
    }
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return snapshot, hashlib.sha256(encoded.encode("utf-8")).hexdigest()
