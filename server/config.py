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
    seed_demo_structure: bool

    @classmethod
    def from_env(cls) -> "Config":
        environment = os.getenv("ENVIRONMENT", "production").strip().lower()
        data_dir = Path(os.getenv("DATA_DIR", str(PROJECT_ROOT / "data"))).resolve()
        database_path = Path(
            os.getenv("DATABASE_PATH", str(data_dir / "teaching-choice.db"))
        ).resolve()
        app_secret = os.getenv("APP_SECRET", "")
        admin_initial_password = os.getenv("ADMIN_INITIAL_PASSWORD", "")

        if environment == "production" and len(app_secret) < 32:
            raise RuntimeError("生产环境 APP_SECRET 必须至少 32 个字符")
        if not app_secret:
            app_secret = "development-only-secret-change-before-production"

        return cls(
            environment=environment,
            database_path=database_path,
            app_secret=app_secret,
            admin_username=os.getenv("ADMIN_USERNAME", "admin").strip() or "admin",
            admin_initial_password=admin_initial_password,
            cookie_secure=_as_bool(os.getenv("COOKIE_SECURE"), False),
            session_hours=max(1, int(os.getenv("SESSION_HOURS", "12"))),
            public_base_url=os.getenv("PUBLIC_BASE_URL", "").strip().rstrip("/"),
            seed_demo_structure=_as_bool(os.getenv("SEED_DEMO_STRUCTURE"), True),
        )

