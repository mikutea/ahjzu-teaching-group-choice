from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Config
from .security import hash_password


SCHEMA = """
CREATE TABLE IF NOT EXISTS settings (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    activity_title TEXT NOT NULL,
    organization_name TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('closed', 'open')),
    public_base_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

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

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_no TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    major_id INTEGER NOT NULL REFERENCES majors(id) ON DELETE RESTRICT,
    activation_hash TEXT NOT NULL,
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
    details_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS audit_logs_time ON audit_logs(occurred_at DESC);
"""


DEFAULT_MAJORS = ["建筑学", "城乡规划", "风景园林"]
DEFAULT_GROUPS = [f"第{i}教学组" for i in range(1, 7)]
DEFAULT_QUOTAS = {
    "建筑学": [10, 10, 10, 10, 10, 10],
    "城乡规划": [9, 9, 8, 8, 8, 8],
    "风景园林": [6, 6, 6, 6, 6, 5],
}


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(
        str(database_path), timeout=10, isolation_level=None, check_same_thread=False
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 10000")
    return connection


def initialize_database(config: Config) -> None:
    config.database_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect(config.database_path)
    try:
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA synchronous = NORMAL")
        connection.executescript(SCHEMA)
        now = utc_now()
        connection.execute(
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

        major_count = connection.execute(
            "SELECT COUNT(*) AS count FROM majors"
        ).fetchone()["count"]
        if config.seed_demo_structure and major_count == 0:
            _seed_structure(connection, now)
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
) -> None:
    connection.execute(
        """
        INSERT INTO audit_logs
            (occurred_at, actor_type, actor_id, action, entity_type, entity_id, details_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            utc_now(),
            actor_type,
            str(actor_id),
            action,
            entity_type,
            str(entity_id),
            json.dumps(details or {}, ensure_ascii=False, separators=(",", ":")),
        ),
    )

