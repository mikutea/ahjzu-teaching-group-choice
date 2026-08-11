from __future__ import annotations

import argparse
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from .config import Config


def create_backup(database_path: Path, backup_dir: Path, retain: int = 30) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    target = backup_dir / f"teaching-choice-{stamp}.db"
    source_connection = sqlite3.connect(str(database_path), timeout=15)
    target_connection = sqlite3.connect(str(target))
    try:
        source_connection.backup(target_connection)
        result = target_connection.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise RuntimeError(f"备份完整性检查失败：{result}")
    finally:
        target_connection.close()
        source_connection.close()

    backups = sorted(backup_dir.glob("teaching-choice-*.db"), reverse=True)
    for old_backup in backups[max(1, retain):]:
        old_backup.unlink()
    return target


def check_database(database_path: Path) -> str:
    connection = sqlite3.connect(str(database_path), timeout=15)
    try:
        return str(connection.execute("PRAGMA integrity_check").fetchone()[0])
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="教学组抢选数据库维护")
    subparsers = parser.add_subparsers(dest="command", required=True)
    backup = subparsers.add_parser("backup")
    backup.add_argument("--retain", type=int, default=30)
    subparsers.add_parser("check")
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


if __name__ == "__main__":
    main()

