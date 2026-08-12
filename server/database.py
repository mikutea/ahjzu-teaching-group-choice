from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Config
from .security import hash_password


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
    activation_ciphertext TEXT,
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


DEFAULT_MAJORS = ["建筑学", "城乡规划", "风景园林"]
SCHEMA_VERSION = 3
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


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row["name"]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _ensure_activity_schema(connection: sqlite3.Connection, now: str) -> int:
    connection.execute(
        "CREATE INDEX IF NOT EXISTS audit_logs_activity_time "
        "ON audit_logs(activity_id, occurred_at DESC)"
    )

    settings = connection.execute(
        """
        SELECT activity_title, status, current_activity_id, created_at, updated_at
        FROM settings WHERE id = 1
        """
    ).fetchone()
    if not settings:
        raise RuntimeError("系统设置尚未初始化")

    activity_id = settings["current_activity_id"]
    activity = None
    if activity_id is not None:
        activity = connection.execute(
            "SELECT id FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
    if not activity:
        cursor = connection.execute(
            """
            INSERT INTO activities
                (code, title, status, created_at, opened_at, closed_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "activity-1",
                settings["activity_title"],
                settings["status"],
                settings["created_at"] or now,
                (settings["updated_at"] or now) if settings["status"] == "open" else None,
                (settings["updated_at"] or now) if settings["status"] == "closed" else None,
            ),
        )
        activity_id = int(cursor.lastrowid)
        connection.execute(
            "UPDATE settings SET current_activity_id = ? WHERE id = 1", (activity_id,)
        )
    connection.execute(
        "UPDATE audit_logs SET activity_id = ? WHERE activity_id IS NULL",
        (activity_id,),
    )

    if int(connection.execute("PRAGMA user_version").fetchone()[0]) < SCHEMA_VERSION:
        connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    return int(activity_id)


def initialize_database(config: Config) -> None:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(config.database_path)
    try:
        database_version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if database_version > SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库版本 {database_version} 高于应用支持版本 {SCHEMA_VERSION}"
            )
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        existing_tables = {
            str(row["name"])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        alterations: list[str] = []
        if "settings" in existing_tables and "current_activity_id" not in _columns(
            connection, "settings"
        ):
            alterations.append(
                "ALTER TABLE settings ADD COLUMN current_activity_id "
                "INTEGER REFERENCES activities(id);"
            )
        if "audit_logs" in existing_tables and "activity_id" not in _columns(
            connection, "audit_logs"
        ):
            alterations.append(
                "ALTER TABLE audit_logs ADD COLUMN activity_id "
                "INTEGER REFERENCES activities(id);"
            )
        if "activities" in existing_tables and "selection_opens_at" not in _columns(
            connection, "activities"
        ):
            alterations.append(
                "ALTER TABLE activities ADD COLUMN selection_opens_at TEXT;"
            )
        if "students" in existing_tables and "activation_ciphertext" not in _columns(
            connection, "students"
        ):
            alterations.append(
                "ALTER TABLE students ADD COLUMN activation_ciphertext TEXT;"
            )
        if "sessions" in existing_tables and "last_seen_at" not in _columns(
            connection, "sessions"
        ):
            alterations.append("ALTER TABLE sessions ADD COLUMN last_seen_at TEXT;")
        trigger_marker = "CREATE TRIGGER IF NOT EXISTS copyright_settings_guard_update"
        migration_steps = alterations + [
            "UPDATE settings SET "
            "organization_name = '安徽建筑大学 · 建筑与空间规划学院', "
            "owner_name = 'Mikutea' WHERE id = 1;",
            "UPDATE activities SET selection_opens_at = COALESCE(opened_at, created_at) "
            "WHERE status = 'open' AND selection_opens_at IS NULL;",
        ]
        migration_schema = SCHEMA.replace(
            trigger_marker,
            "\n".join(migration_steps + [trigger_marker]),
            1,
        )
        connection.executescript("BEGIN IMMEDIATE;\n" + migration_schema)
        now = utc_now()
        setting_insert = connection.execute(
            """
            INSERT OR IGNORE INTO settings
                (id, activity_title, organization_name, owner_name, status,
                 public_base_url, created_at, updated_at)
            VALUES (1, ?, ?, ?, 'closed', ?, ?, ?)
            """,
            (
                "2026级教学组线上抢选",
                "安徽建筑大学 · 建筑与空间规划学院",
                "Mikutea",
                config.public_base_url,
                now,
                now,
            ),
        )
        _ensure_activity_schema(connection, now)

        admin_count = connection.execute(
            "SELECT COUNT(*) AS count FROM admin_users"
        ).fetchone()["count"]
        if admin_count == 0:
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
                    config.admin_username,
                    hash_password(config.admin_initial_password),
                    now,
                    now,
                ),
            )

        connection.commit()

        major_count = connection.execute(
            "SELECT COUNT(*) AS count FROM majors"
        ).fetchone()["count"]
        if config.seed_demo_structure and setting_insert.rowcount == 1 and major_count == 0:
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
