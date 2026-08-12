from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from .config import Config
from .database import SCHEMA_VERSION, connect, initialize_database


MIGRATION_DIGEST_QUERIES = {
    "settings": (
        "SELECT id, activity_title, organization_name, owner_name, status, "
        "public_base_url, created_at, updated_at FROM settings ORDER BY id"
    ),
    "majors": "SELECT * FROM majors ORDER BY id",
    "teaching_groups": "SELECT * FROM teaching_groups ORDER BY id",
    "quotas": "SELECT * FROM quotas ORDER BY major_id, group_id",
    "students": "SELECT * FROM students ORDER BY id",
    "selections": "SELECT * FROM selections ORDER BY id",
    "admin_users": "SELECT * FROM admin_users ORDER BY id",
    "sessions": "SELECT * FROM sessions ORDER BY token_hash",
    "audit_logs": (
        "SELECT id, occurred_at, actor_type, actor_id, action, entity_type, "
        "entity_id, details_json FROM audit_logs ORDER BY id"
    ),
}


def migration_business_digest(database_path: Path) -> dict[str, str]:
    connection = connect(database_path)
    try:
        digests: dict[str, str] = {}
        for name, query in MIGRATION_DIGEST_QUERIES.items():
            rows = [dict(row) for row in connection.execute(query).fetchall()]
            encoded = json.dumps(
                rows,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
            digests[name] = hashlib.sha256(encoded).hexdigest()
        return digests
    finally:
        connection.close()


def migrate_and_check(config: Config) -> str:
    before = migration_business_digest(config.database_path)
    initialize_database(config)
    after = migration_business_digest(config.database_path)
    if before != after:
        changed = sorted(name for name in before if before[name] != after[name])
        raise RuntimeError(f"迁移改变了旧版业务数据：{', '.join(changed)}")
    result = check_database(config.database_path)
    if result != "ok":
        raise RuntimeError(f"迁移后数据库检查失败：{result}")
    return "MIGRATION_CHECK_OK"


def create_backup(database_path: Path, backup_dir: Path, retain: int = 30) -> Path:
    if not database_path.is_file() or database_path.stat().st_size == 0:
        raise RuntimeError(f"数据库不存在或为空：{database_path}")
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"teaching-choice-{stamp}.db"
    partial = backup_dir / f".{target.name}.{uuid4().hex}.partial"
    source_uri = f"{database_path.resolve().as_uri()}?mode=ro"
    source_connection: sqlite3.Connection | None = None
    target_connection: sqlite3.Connection | None = None
    try:
        source_connection = sqlite3.connect(source_uri, timeout=15, uri=True)
        target_connection = sqlite3.connect(str(partial))
        try:
            source_connection.backup(target_connection)
            result = target_connection.execute("PRAGMA integrity_check").fetchone()[0]
            if result != "ok":
                raise RuntimeError(f"备份完整性检查失败：{result}")
        finally:
            target_connection.close()
            source_connection.close()
            target_connection = None
            source_connection = None

        result = check_database(partial)
        if result != "ok":
            raise RuntimeError(f"备份深度检查失败：{result}")
        os.replace(partial, target)
    finally:
        if target_connection is not None:
            target_connection.close()
        if source_connection is not None:
            source_connection.close()
        partial.unlink(missing_ok=True)

    backups = sorted(backup_dir.glob("teaching-choice-*.db"), reverse=True)
    for old_backup in backups[max(1, retain):]:
        old_backup.unlink()
    return target


def check_database(database_path: Path) -> str:
    if not database_path.is_file() or database_path.stat().st_size == 0:
        raise RuntimeError(f"数据库不存在或为空：{database_path}")
    connection = sqlite3.connect(str(database_path), timeout=15)
    try:
        required = {
            "settings",
            "activities",
            "majors",
            "teaching_groups",
            "quotas",
            "students",
            "selections",
            "admin_users",
            "sessions",
            "audit_logs",
        }
        tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        missing = sorted(required - tables)
        if missing:
            raise RuntimeError(f"数据库缺少关键表：{', '.join(missing)}")
        version = int(connection.execute("PRAGMA user_version").fetchone()[0])
        if version != SCHEMA_VERSION:
            raise RuntimeError(
                f"数据库版本不受支持：{version}（应用要求 {SCHEMA_VERSION}）"
            )
        triggers = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            ).fetchall()
        }
        required_triggers = {
            "selection_capacity_guard",
            "selection_capacity_guard_update",
            "sync_activity_title_to_settings",
            "sync_activity_status_to_settings",
            "sync_settings_title_to_activity",
            "sync_settings_status_to_activity",
            "assign_current_activity_to_audit",
        }
        if not required_triggers <= triggers:
            raise RuntimeError("数据库缺少名额约束触发器")
        live_activities = connection.execute(
            "SELECT id FROM activities WHERE status <> 'archived'"
        ).fetchall()
        if len(live_activities) != 1:
            raise RuntimeError("数据库必须且只能有一个当前活动")
        current = connection.execute(
            "SELECT current_activity_id FROM settings WHERE id = 1"
        ).fetchone()
        if not current or int(current[0]) != int(live_activities[0][0]):
            raise RuntimeError("系统设置指向的当前活动不正确")
        for row in connection.execute(
            """
            SELECT id, summary_json, snapshot_json, snapshot_sha256
            FROM activities WHERE status = 'archived'
            """
        ).fetchall():
            if not row[1] or not row[2] or not row[3]:
                raise RuntimeError(f"归档活动 {row[0]} 缺少快照或校验值")
            try:
                summary = json.loads(row[1])
                snapshot = json.loads(row[2])
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"归档活动 {row[0]} JSON 无法解析") from exc
            if not {"students", "selected", "unselected"} <= summary.keys():
                raise RuntimeError(f"归档活动 {row[0]} 汇总字段不完整")
            required_snapshot_keys = {
                "activity",
                "majors",
                "teaching_groups",
                "quotas",
                "students",
                "selections",
                "audit_logs",
            }
            if not required_snapshot_keys <= snapshot.keys():
                raise RuntimeError(f"归档活动 {row[0]} 快照字段不完整")
            digest = hashlib.sha256(str(row[2]).encode("utf-8")).hexdigest()
            if not hmac.compare_digest(digest, str(row[3])):
                raise RuntimeError(f"归档活动 {row[0]} SHA-256 校验失败")
        total_overages = connection.execute(
            """
            SELECT g.id FROM teaching_groups g
            WHERE (SELECT COUNT(*) FROM selections se
                   WHERE se.group_id = g.id AND se.revoked_at IS NULL) > g.total_capacity
            """
        ).fetchall()
        major_overages = connection.execute(
            """
            SELECT q.major_id, q.group_id FROM quotas q
            WHERE (SELECT COUNT(*) FROM selections se
                   JOIN students s ON s.id = se.student_id
                   WHERE se.group_id = q.group_id AND s.major_id = q.major_id
                     AND se.revoked_at IS NULL) > q.capacity
            """
        ).fetchall()
        if total_overages or major_overages:
            raise RuntimeError("数据库存在超过当前容量的有效选择")
        foreign_key_errors = connection.execute("PRAGMA foreign_key_check").fetchall()
        if foreign_key_errors:
            raise RuntimeError(f"数据库外键检查失败：{foreign_key_errors[:3]}")
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="教学组抢选数据库维护")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--retain", type=int, default=30)
    subparsers.add_parser("check")
    subparsers.add_parser("migrate-check")
    args = parser.parse_args()
    config = Config.from_env()

    if args.command == "backup":
        target = create_backup(config.database_path, config.database_path.parent / "backups", args.retain)
        print(target)
    elif args.command == "check":
        result = check_database(config.database_path)
        print(result)
        if result != "ok":
            raise SystemExit(1)
    elif args.command == "migrate-check":
        print(migrate_and_check(config))


if __name__ == "__main__":
    main()
