from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Config:
    environment: str
    database_path: Path
    app_secret: str
    admin_username: str
    admin_initial_password: str
    cookie_secure: bool
    session_hours: int
    public_base_url: str
    trusted_proxy_ips: tuple[str, ...]
    seed_demo_structure: bool
    sqlite_write_batch_size: int = 64
    sqlite_write_queue_limit: int = 4_096
    sqlite_write_batch_window_ms: int = 4

    @classmethod
    def from_env(cls) -> "Config":
        environment = os.getenv("ENVIRONMENT", "production").strip().lower()
        data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
        database_path = Path(
            os.getenv("DATABASE_PATH", str(data_dir / "teaching-choice.db"))
        ).resolve()
        app_secret = os.getenv("APP_SECRET", "")
        admin_initial_password = os.getenv("ADMIN_INITIAL_PASSWORD", "")

        if len(app_secret) < 32:
            raise RuntimeError("APP_SECRET 必须至少 32 个字符")

        write_batch_size = max(
            1, min(256, int(os.getenv("SQLITE_WRITE_BATCH_SIZE", "64")))
        )
        write_queue_limit = max(
            write_batch_size * 2,
            min(16_384, int(os.getenv("SQLITE_WRITE_QUEUE_LIMIT", "4096"))),
        )
        write_batch_window_ms = max(
            0, min(100, int(os.getenv("SQLITE_WRITE_BATCH_WINDOW_MS", "4")))
        )

        return cls(
            environment=environment,
            database_path=database_path,
            app_secret=app_secret,
            admin_username=os.getenv("ADMIN_USERNAME", "admin").strip() or "admin",
            admin_initial_password=admin_initial_password,
            cookie_secure=_as_bool(os.getenv("COOKIE_SECURE"), False),
            session_hours=max(1, int(os.getenv("SESSION_HOURS", "12"))),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"),
            trusted_proxy_ips=tuple(
                value.strip()
                for value in os.getenv("TRUSTED_PROXY_IPS", "").split(",")
                if value.strip()
            ),
            seed_demo_structure=_as_bool(os.getenv("SEED_DEMO_STRUCTURE"), False),
            sqlite_write_batch_size=write_batch_size,
            sqlite_write_queue_limit=write_queue_limit,
            sqlite_write_batch_window_ms=write_batch_window_ms,
        )
