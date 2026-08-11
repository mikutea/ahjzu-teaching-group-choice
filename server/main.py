from __future__ import annotations

import csv
import io
import json
import secrets
import sqlite3
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated, Any, Literal

import qrcode
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

from .config import Config, PROJECT_ROOT
from .database import audit, connect, initialize_database, utc_now
from .security import (
    activation_code_hash,
    hash_password,
    new_activation_code,
    new_csrf_token,
    new_session_token,
    session_token_hash,
    verify_activation_code,
    verify_password,
)


WEB_ROOT = PROJECT_ROOT / "web"
BRAND_ROOT = PROJECT_ROOT / "assets" / "brand"
ADMIN_COOKIE = "tg_admin_session"
STUDENT_COOKIE = "tg_student_session"


def clean_text(value: str) -> str:
    return " ".join(value.strip().split())


class StrictModel(BaseModel):
    model_config = {"extra": "forbid"}


class AdminLogin(StrictModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=256)


class StudentLogin(StrictModel):
    student_no: str = Field(min_length=1, max_length=40)
    name: str = Field(min_length=1, max_length=80)
    activation_code: str = Field(min_length=4, max_length=64)

    @field_validator("student_no", "name", "activation_code")
    @classmethod
    def strip_values(cls, value: str) -> str:
        return clean_text(value)


class StatusUpdate(StrictModel):
    status: Literal["closed", "open"]


class SettingsUpdate(StrictModel):
    activity_title: str | None = Field(default=None, min_length=2, max_length=120)
    organization_name: str | None = Field(default=None, min_length=2, max_length=160)
    owner_name: str | None = Field(default=None, min_length=1, max_length=80)
    public_base_url: str | None = Field(default=None, max_length=300)

    @field_validator("activity_title", "organization_name", "owner_name")
    @classmethod
    def normalize_names(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value)

    @field_validator("public_base_url")
    @classmethod
    def validate_base_url(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip().rstrip("/")
        if value and not value.startswith(("http://", "https://")):
            raise ValueError("访问地址必须以 http:// 或 https:// 开头")
        return value


class MajorCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return clean_text(value)


class MajorUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value)


class GroupCreate(StrictModel):
    name: str = Field(min_length=1, max_length=80)
    total_capacity: int = Field(default=30, ge=0, le=1000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        return clean_text(value)


class GroupUpdate(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    total_capacity: int | None = Field(default=None, ge=0, le=1000)
    active: bool | None = None
    sort_order: int | None = Field(default=None, ge=0, le=100_000)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        return None if value is None else clean_text(value)


class QuotaUpdate(StrictModel):
    capacity: int = Field(ge=0, le=1000)


class StudentSelect(StrictModel):
    group_id: int = Field(gt=0)


class AdminAssign(StrictModel):
    student_id: int = Field(gt=0)
    group_id: int = Field(gt=0)


class RevokeSelection(StrictModel):
    student_id: int = Field(gt=0)
    reason: str = Field(default="管理员撤销", min_length=2, max_length=200)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        return clean_text(value)


class PasswordChange(StrictModel):
    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=12, max_length=256)


@dataclass(frozen=True)
class Identity:
    role: Literal["student", "admin"]
    subject_id: int
    csrf_token: str
    token_hash: str


class RateLimiter:
    def __init__(self) -> None:
        self._events: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def check(self, key: str, *, limit: int, window_seconds: int) -> None:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            events = [event for event in self._events.get(key, []) if event >= cutoff]
            if len(events) >= limit:
                raise HTTPException(status_code=429, detail="尝试次数过多，请稍后再试")
            events.append(now)
            self._events[key] = events

    def clear(self, key: str) -> None:
        with self._lock:
            self._events.pop(key, None)


def create_app(config: Config | None = None) -> FastAPI:
    config = config or Config.from_env()
    initialize_database(config)
    limiter = RateLimiter()
    app = FastAPI(
        title="教学组抢选系统",
        docs_url=None if config.environment == "production" else "/api/docs",
        redoc_url=None,
        openapi_url=None if config.environment == "production" else "/api/openapi.json",
    )
    app.state.config = config

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; "
            "base-uri 'self'; form-action 'self'"
        )
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(sqlite3.IntegrityError)
    async def sqlite_integrity_error(_: Request, exc: sqlite3.IntegrityError):
        message = str(exc).lower()
        if "unique" in message:
            detail = "名称或编号已存在"
        else:
            detail = "数据约束校验失败"
        return JSONResponse(status_code=409, content={"detail": detail})

    def client_key(request: Request, namespace: str) -> str:
        host = request.client.host if request.client else "unknown"
        return f"{namespace}:{host}"

    def require_session(
        request: Request,
        role: Literal["student", "admin"],
        *,
        csrf: bool = False,
    ) -> Identity:
        cookie_name = ADMIN_COOKIE if role == "admin" else STUDENT_COOKIE
        token = request.cookies.get(cookie_name, "")
        if not token:
            raise HTTPException(status_code=401, detail="请先登录")
        token_hash = session_token_hash(token)
        now = utc_now()
        connection = connect(config.database_path)
        try:
            row = connection.execute(
                """
                SELECT role, subject_id, csrf_token
                FROM sessions
                WHERE token_hash = ? AND expires_at > ?
                """,
                (token_hash, now),
            ).fetchone()
        finally:
            connection.close()
        if not row or row["role"] != role:
            raise HTTPException(status_code=401, detail="登录已失效，请重新登录")
        if csrf:
            provided = request.headers.get("X-CSRF-Token", "")
            if not secrets.compare_digest(provided, row["csrf_token"]):
                raise HTTPException(status_code=403, detail="请求校验失败，请刷新页面后重试")
        return Identity(
            role=role,
            subject_id=int(row["subject_id"]),
            csrf_token=row["csrf_token"],
            token_hash=token_hash,
        )

    def create_session(
        response: Response,
        *,
        role: Literal["student", "admin"],
        subject_id: int,
    ) -> str:
        token = new_session_token()
        csrf_token = new_csrf_token()
        now_dt = datetime.now(UTC)
        expires = now_dt + timedelta(hours=config.session_hours)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (utc_now(),))
            connection.execute(
                "DELETE FROM sessions WHERE role = ? AND subject_id = ?",
                (role, subject_id),
            )
            connection.execute(
                """
                INSERT INTO sessions
                    (token_hash, role, subject_id, csrf_token, created_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    session_token_hash(token),
                    role,
                    subject_id,
                    csrf_token,
                    now_dt.isoformat(timespec="seconds"),
                    expires.isoformat(timespec="seconds"),
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

        cookie_name = ADMIN_COOKIE if role == "admin" else STUDENT_COOKIE
        response.set_cookie(
            cookie_name,
            token,
            max_age=config.session_hours * 3600,
            httponly=True,
            secure=config.cookie_secure,
            samesite="strict",
            path="/",
        )
        return csrf_token

    def ensure_closed(connection: sqlite3.Connection) -> None:
        status = connection.execute("SELECT status FROM settings WHERE id = 1").fetchone()[
            "status"
        ]
        if status != "closed":
            raise HTTPException(status_code=409, detail="请先关闭抢选再修改结构或配额")

    def setting_dict(connection: sqlite3.Connection) -> dict[str, Any]:
        row = connection.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        return {
            "activity_title": row["activity_title"],
            "organization_name": row["organization_name"],
            "owner_name": row["owner_name"],
            "status": row["status"],
            "public_base_url": row["public_base_url"],
            "updated_at": row["updated_at"],
        }

    def current_student_payload(student_id: int) -> dict[str, Any]:
        connection = connect(config.database_path)
        try:
            student = connection.execute(
                """
                SELECT s.id, s.student_no, s.name, s.active, s.major_id,
                       m.name AS major_name, m.active AS major_active
                FROM students s JOIN majors m ON m.id = s.major_id
                WHERE s.id = ?
                """,
                (student_id,),
            ).fetchone()
            if not student or not student["active"]:
                raise HTTPException(status_code=403, detail="学生账号已停用")
            selection = connection.execute(
                """
                SELECT se.group_id, se.selected_at, g.name AS group_name
                FROM selections se
                JOIN teaching_groups g ON g.id = se.group_id
                WHERE se.student_id = ? AND se.revoked_at IS NULL
                """,
                (student_id,),
            ).fetchone()
            groups = connection.execute(
                """
                SELECT g.id, g.name, g.total_capacity,
                       q.capacity,
                       (SELECT COUNT(*) FROM selections sx
                        JOIN students stx ON stx.id = sx.student_id
                        WHERE sx.group_id = g.id AND stx.major_id = ?
                          AND sx.revoked_at IS NULL) AS major_selected,
                       (SELECT COUNT(*) FROM selections sx
                        WHERE sx.group_id = g.id AND sx.revoked_at IS NULL) AS total_selected
                FROM teaching_groups g
                JOIN quotas q ON q.group_id = g.id AND q.major_id = ?
                WHERE g.active = 1
                ORDER BY g.sort_order, g.id
                """,
                (student["major_id"], student["major_id"]),
            ).fetchall()
            settings = setting_dict(connection)
            return {
                "student": {
                    "id": student["id"],
                    "student_no": student["student_no"],
                    "name": student["name"],
                    "major_id": student["major_id"],
                    "major_name": student["major_name"],
                },
                "selection": dict(selection) if selection else None,
                "groups": [
                    {
                        "id": row["id"],
                        "name": row["name"],
                        "capacity": row["capacity"],
                        "selected": row["major_selected"],
                        "remaining": max(
                            0,
                            min(
                                row["capacity"] - row["major_selected"],
                                row["total_capacity"] - row["total_selected"],
                            ),
                        ),
                        "full": row["major_selected"] >= row["capacity"]
                        or row["total_selected"] >= row["total_capacity"],
                    }
                    for row in groups
                ],
                "settings": settings,
            }
        finally:
            connection.close()

    def choose_group(
        *,
        student_id: int,
        group_id: int,
        source: Literal["student", "admin"],
        operator: str,
        require_open: bool,
    ) -> None:
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            settings = connection.execute(
                "SELECT status FROM settings WHERE id = 1"
            ).fetchone()
            if require_open and settings["status"] != "open":
                raise HTTPException(status_code=409, detail="抢选尚未开放或已经结束")
            student = connection.execute(
                """
                SELECT s.id, s.major_id, s.active, m.active AS major_active
                FROM students s JOIN majors m ON m.id = s.major_id
                WHERE s.id = ?
                """,
                (student_id,),
            ).fetchone()
            if not student or not student["active"] or not student["major_active"]:
                raise HTTPException(status_code=403, detail="学生或所属专业已停用")
            existing = connection.execute(
                "SELECT 1 FROM selections WHERE student_id = ? AND revoked_at IS NULL",
                (student_id,),
            ).fetchone()
            if existing:
                raise HTTPException(status_code=409, detail="你已经完成选择，不能重复提交")
            group = connection.execute(
                "SELECT id, active, total_capacity FROM teaching_groups WHERE id = ?",
                (group_id,),
            ).fetchone()
            if not group or not group["active"]:
                raise HTTPException(status_code=404, detail="教学组不存在或已停用")
            quota = connection.execute(
                "SELECT capacity FROM quotas WHERE major_id = ? AND group_id = ?",
                (student["major_id"], group_id),
            ).fetchone()
            if not quota:
                raise HTTPException(status_code=409, detail="该专业尚未配置此教学组配额")
            major_selected = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM selections se JOIN students s ON s.id = se.student_id
                WHERE se.group_id = ? AND s.major_id = ? AND se.revoked_at IS NULL
                """,
                (group_id, student["major_id"]),
            ).fetchone()["count"]
            total_selected = connection.execute(
                """
                SELECT COUNT(*) AS count FROM selections
                WHERE group_id = ? AND revoked_at IS NULL
                """,
                (group_id,),
            ).fetchone()["count"]
            if major_selected >= quota["capacity"] or total_selected >= group["total_capacity"]:
                raise HTTPException(status_code=409, detail="该教学组名额刚刚已满，请选择其他教学组")
            now = utc_now()
            selection = connection.execute(
                """
                INSERT INTO selections
                    (student_id, group_id, selected_at, source, operator)
                VALUES (?, ?, ?, ?, ?)
                """,
                (student_id, group_id, now, source, operator),
            )
            audit(
                connection,
                actor_type=source,
                actor_id=operator,
                action="selection.create",
                entity_type="selection",
                entity_id=selection.lastrowid,
                details={"student_id": student_id, "group_id": group_id},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @app.get("/api/health")
    def health() -> dict[str, str]:
        connection = connect(config.database_path)
        try:
            connection.execute("SELECT 1").fetchone()
        finally:
            connection.close()
        return {"status": "ok"}

    @app.get("/api/public/info")
    def public_info() -> dict[str, Any]:
        connection = connect(config.database_path)
        try:
            settings = setting_dict(connection)
            groups = connection.execute(
                """
                SELECT id, name FROM teaching_groups
                WHERE active = 1 ORDER BY sort_order, id
                """
            ).fetchall()
            return {"settings": settings, "group_count": len(groups)}
        finally:
            connection.close()

    @app.post("/api/student/login")
    def student_login(payload: StudentLogin, request: Request, response: Response):
        key = client_key(request, "student-login")
        limiter.check(key, limit=20, window_seconds=300)
        connection = connect(config.database_path)
        try:
            row = connection.execute(
                """
                SELECT id, name, activation_hash, active
                FROM students WHERE student_no = ?
                """,
                (payload.student_no,),
            ).fetchone()
            valid = (
                row
                and row["active"]
                and clean_text(row["name"]) == payload.name
                and verify_activation_code(
                    config.app_secret, payload.activation_code, row["activation_hash"]
                )
            )
            if not valid:
                raise HTTPException(status_code=401, detail="学号、姓名或激活码不正确")
            student_id = int(row["id"])
        finally:
            connection.close()
        limiter.clear(key)
        csrf_token = create_session(response, role="student", subject_id=student_id)
        return {"csrf_token": csrf_token, **current_student_payload(student_id)}

    @app.get("/api/student/me")
    def student_me(request: Request):
        identity = require_session(request, "student")
        return {"csrf_token": identity.csrf_token, **current_student_payload(identity.subject_id)}

    @app.post("/api/student/select")
    def student_select(payload: StudentSelect, request: Request):
        identity = require_session(request, "student", csrf=True)
        choose_group(
            student_id=identity.subject_id,
            group_id=payload.group_id,
            source="student",
            operator=str(identity.subject_id),
            require_open=True,
        )
        return {"ok": True, **current_student_payload(identity.subject_id)}

    @app.post("/api/student/logout")
    def student_logout(request: Request, response: Response):
        identity = require_session(request, "student", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (identity.token_hash,))
        finally:
            connection.close()
        response.delete_cookie(STUDENT_COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/admin/login")
    def admin_login(payload: AdminLogin, request: Request, response: Response):
        key = client_key(request, "admin-login")
        limiter.check(key, limit=10, window_seconds=300)
        connection = connect(config.database_path)
        try:
            row = connection.execute(
                "SELECT id, password_hash FROM admin_users WHERE username = ?",
                (payload.username.strip(),),
            ).fetchone()
            if not row or not verify_password(payload.password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="管理员账号或密码不正确")
            admin_id = int(row["id"])
        finally:
            connection.close()
        limiter.clear(key)
        csrf_token = create_session(response, role="admin", subject_id=admin_id)
        return {"csrf_token": csrf_token, "username": payload.username.strip()}

    @app.get("/api/admin/me")
    def admin_me(request: Request):
        identity = require_session(request, "admin")
        connection = connect(config.database_path)
        try:
            row = connection.execute(
                "SELECT username FROM admin_users WHERE id = ?", (identity.subject_id,)
            ).fetchone()
        finally:
            connection.close()
        if not row:
            raise HTTPException(status_code=401, detail="管理员账号不存在")
        return {"csrf_token": identity.csrf_token, "username": row["username"]}

    @app.post("/api/admin/logout")
    def admin_logout(request: Request, response: Response):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (identity.token_hash,))
        finally:
            connection.close()
        response.delete_cookie(ADMIN_COOKIE, path="/")
        return {"ok": True}

    @app.post("/api/admin/password")
    def change_admin_password(payload: PasswordChange, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT username, password_hash FROM admin_users WHERE id = ?",
                (identity.subject_id,),
            ).fetchone()
            if not row or not verify_password(payload.current_password, row["password_hash"]):
                raise HTTPException(status_code=401, detail="当前密码不正确")
            connection.execute(
                "UPDATE admin_users SET password_hash = ?, updated_at = ? WHERE id = ?",
                (hash_password(payload.new_password), utc_now(), identity.subject_id),
            )
            connection.execute(
                "DELETE FROM sessions WHERE role = 'admin' AND token_hash <> ?",
                (identity.token_hash,),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=row["username"],
                action="admin.password.change",
                entity_type="admin_user",
                entity_id=identity.subject_id,
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"ok": True}

    @app.get("/api/admin/dashboard")
    def admin_dashboard(request: Request):
        require_session(request, "admin")
        connection = connect(config.database_path)
        try:
            settings = setting_dict(connection)
            majors = connection.execute(
                """
                SELECT m.*,
                       (SELECT COUNT(*) FROM students s
                        WHERE s.major_id = m.id AND s.active = 1) AS student_count,
                       (SELECT COUNT(*) FROM selections se
                        JOIN students s ON s.id = se.student_id
                        WHERE s.major_id = m.id AND s.active = 1
                          AND se.revoked_at IS NULL) AS selected_count
                FROM majors m ORDER BY m.sort_order, m.id
                """
            ).fetchall()
            groups = connection.execute(
                """
                SELECT g.*,
                       (SELECT COUNT(*) FROM selections se
                        WHERE se.group_id = g.id AND se.revoked_at IS NULL) AS selected_count
                FROM teaching_groups g ORDER BY g.sort_order, g.id
                """
            ).fetchall()
            quotas = connection.execute(
                """
                SELECT q.major_id, q.group_id, q.capacity,
                       (SELECT COUNT(*) FROM selections se
                        JOIN students s ON s.id = se.student_id
                        WHERE s.major_id = q.major_id AND se.group_id = q.group_id
                          AND se.revoked_at IS NULL) AS selected_count
                FROM quotas q
                """
            ).fetchall()
            totals = connection.execute(
                """
                SELECT
                    (SELECT COUNT(*) FROM students WHERE active = 1) AS students,
                    (SELECT COUNT(*) FROM selections se JOIN students s ON s.id = se.student_id
                     WHERE se.revoked_at IS NULL AND s.active = 1) AS selected
                """
            ).fetchone()
            unselected = connection.execute(
                """
                SELECT s.id, s.student_no, s.name, m.name AS major_name
                FROM students s
                JOIN majors m ON m.id = s.major_id
                LEFT JOIN selections se ON se.student_id = s.id AND se.revoked_at IS NULL
                WHERE s.active = 1 AND se.id IS NULL
                ORDER BY m.sort_order, s.student_no
                """
            ).fetchall()
            recent = connection.execute(
                """
                SELECT s.id AS student_id, s.student_no, s.name, m.name AS major_name,
                       g.name AS group_name, se.selected_at, se.source
                FROM selections se
                JOIN students s ON s.id = se.student_id
                JOIN majors m ON m.id = s.major_id
                JOIN teaching_groups g ON g.id = se.group_id
                WHERE se.revoked_at IS NULL
                ORDER BY se.selected_at DESC LIMIT 20
                """
            ).fetchall()
            return {
                "settings": settings,
                "totals": {
                    "students": totals["students"],
                    "selected": totals["selected"],
                    "unselected": totals["students"] - totals["selected"],
                },
                "majors": [dict(row) for row in majors],
                "groups": [dict(row) for row in groups],
                "quotas": [dict(row) for row in quotas],
                "unselected_students": [dict(row) for row in unselected],
                "recent_selections": [dict(row) for row in recent],
            }
        finally:
            connection.close()

    @app.patch("/api/admin/settings")
    def update_settings(payload: SettingsUpdate, request: Request):
        identity = require_session(request, "admin", csrf=True)
        values = payload.model_dump(exclude_none=True)
        if not values:
            raise HTTPException(status_code=400, detail="没有需要保存的设置")
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            before = setting_dict(connection)
            assignments = ", ".join(f"{column} = ?" for column in values)
            connection.execute(
                f"UPDATE settings SET {assignments}, updated_at = ? WHERE id = 1",
                (*values.values(), utc_now()),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="settings.update",
                entity_type="settings",
                entity_id=1,
                details={"before": before, "changed": values},
            )
            connection.commit()
            return setting_dict(connection)
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @app.post("/api/admin/status")
    def update_status(payload: StatusUpdate, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            old = connection.execute("SELECT status FROM settings WHERE id = 1").fetchone()[
                "status"
            ]
            connection.execute(
                "UPDATE settings SET status = ?, updated_at = ? WHERE id = 1",
                (payload.status, utc_now()),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action=f"activity.{payload.status}",
                entity_type="settings",
                entity_id=1,
                details={"from": old, "to": payload.status},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"status": payload.status}

    @app.post("/api/admin/majors")
    def create_major(payload: MajorCreate, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            max_sort = connection.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS value FROM majors"
            ).fetchone()["value"]
            now = utc_now()
            cursor = connection.execute(
                """
                INSERT INTO majors (code, name, active, sort_order, created_at, updated_at)
                VALUES (?, ?, 1, ?, ?, ?)
                """,
                (f"major-{secrets.token_hex(4)}", payload.name, max_sort + 10, now, now),
            )
            major_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO quotas (major_id, group_id, capacity, updated_at)
                SELECT ?, id, 0, ? FROM teaching_groups
                """,
                (major_id, now),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="major.create",
                entity_type="major",
                entity_id=major_id,
                details={"name": payload.name},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"id": major_id, "name": payload.name}

    @app.patch("/api/admin/majors/{major_id}")
    def update_major(major_id: int, payload: MajorUpdate, request: Request):
        identity = require_session(request, "admin", csrf=True)
        values = payload.model_dump(exclude_none=True)
        if "active" in values:
            values["active"] = int(values["active"])
        if not values:
            raise HTTPException(status_code=400, detail="没有需要保存的内容")
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            before = connection.execute("SELECT * FROM majors WHERE id = ?", (major_id,)).fetchone()
            if not before:
                raise HTTPException(status_code=404, detail="专业不存在")
            assignments = ", ".join(f"{column} = ?" for column in values)
            connection.execute(
                f"UPDATE majors SET {assignments}, updated_at = ? WHERE id = ?",
                (*values.values(), utc_now(), major_id),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="major.update",
                entity_type="major",
                entity_id=major_id,
                details={"before": dict(before), "changed": values},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"ok": True}

    @app.delete("/api/admin/majors/{major_id}")
    def delete_major(major_id: int, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            row = connection.execute("SELECT name FROM majors WHERE id = ?", (major_id,)).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="专业不存在")
            students = connection.execute(
                "SELECT COUNT(*) AS count FROM students WHERE major_id = ?", (major_id,)
            ).fetchone()["count"]
            if students:
                raise HTTPException(status_code=409, detail="该专业已有学生，不能删除；可改为停用")
            connection.execute("DELETE FROM majors WHERE id = ?", (major_id,))
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="major.delete",
                entity_type="major",
                entity_id=major_id,
                details={"name": row["name"]},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"ok": True}

    @app.post("/api/admin/groups")
    def create_group(payload: GroupCreate, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            max_sort = connection.execute(
                "SELECT COALESCE(MAX(sort_order), 0) AS value FROM teaching_groups"
            ).fetchone()["value"]
            now = utc_now()
            cursor = connection.execute(
                """
                INSERT INTO teaching_groups
                    (code, name, total_capacity, active, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, 1, ?, ?, ?)
                """,
                (
                    f"group-{secrets.token_hex(4)}",
                    payload.name,
                    payload.total_capacity,
                    max_sort + 10,
                    now,
                    now,
                ),
            )
            group_id = int(cursor.lastrowid)
            connection.execute(
                """
                INSERT INTO quotas (major_id, group_id, capacity, updated_at)
                SELECT id, ?, 0, ? FROM majors
                """,
                (group_id, now),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="group.create",
                entity_type="teaching_group",
                entity_id=group_id,
                details={"name": payload.name, "total_capacity": payload.total_capacity},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"id": group_id, "name": payload.name}

    @app.patch("/api/admin/groups/{group_id}")
    def update_group(group_id: int, payload: GroupUpdate, request: Request):
        identity = require_session(request, "admin", csrf=True)
        values = payload.model_dump(exclude_none=True)
        if "active" in values:
            values["active"] = int(values["active"])
        if not values:
            raise HTTPException(status_code=400, detail="没有需要保存的内容")
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            before = connection.execute(
                "SELECT * FROM teaching_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if not before:
                raise HTTPException(status_code=404, detail="教学组不存在")
            selected = connection.execute(
                "SELECT COUNT(*) AS count FROM selections WHERE group_id = ? AND revoked_at IS NULL",
                (group_id,),
            ).fetchone()["count"]
            quota_sum = connection.execute(
                "SELECT COALESCE(SUM(capacity), 0) AS total FROM quotas WHERE group_id = ?",
                (group_id,),
            ).fetchone()["total"]
            if "total_capacity" in values and values["total_capacity"] < max(selected, quota_sum):
                raise HTTPException(
                    status_code=409,
                    detail=f"总容量不能小于当前配额合计 {quota_sum} 或已选人数 {selected}",
                )
            if values.get("active") == 0 and selected:
                raise HTTPException(status_code=409, detail="该教学组已有选择，不能直接停用")
            assignments = ", ".join(f"{column} = ?" for column in values)
            connection.execute(
                f"UPDATE teaching_groups SET {assignments}, updated_at = ? WHERE id = ?",
                (*values.values(), utc_now(), group_id),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="group.update",
                entity_type="teaching_group",
                entity_id=group_id,
                details={"before": dict(before), "changed": values},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"ok": True}

    @app.delete("/api/admin/groups/{group_id}")
    def delete_group(group_id: int, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            row = connection.execute(
                "SELECT name FROM teaching_groups WHERE id = ?", (group_id,)
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="教学组不存在")
            selections = connection.execute(
                "SELECT COUNT(*) AS count FROM selections WHERE group_id = ?", (group_id,)
            ).fetchone()["count"]
            if selections:
                raise HTTPException(status_code=409, detail="该教学组已有历史选择，不能删除；可改为停用")
            connection.execute("DELETE FROM teaching_groups WHERE id = ?", (group_id,))
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="group.delete",
                entity_type="teaching_group",
                entity_id=group_id,
                details={"name": row["name"]},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"ok": True}

    @app.put("/api/admin/quotas/{major_id}/{group_id}")
    def update_quota(major_id: int, group_id: int, payload: QuotaUpdate, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            current = connection.execute(
                "SELECT capacity FROM quotas WHERE major_id = ? AND group_id = ?",
                (major_id, group_id),
            ).fetchone()
            if not current:
                raise HTTPException(status_code=404, detail="配额单元不存在")
            selected = connection.execute(
                """
                SELECT COUNT(*) AS count
                FROM selections se JOIN students s ON s.id = se.student_id
                WHERE s.major_id = ? AND se.group_id = ? AND se.revoked_at IS NULL
                """,
                (major_id, group_id),
            ).fetchone()["count"]
            if payload.capacity < selected:
                raise HTTPException(status_code=409, detail=f"配额不能小于当前已选人数 {selected}")
            other_sum = connection.execute(
                """
                SELECT COALESCE(SUM(capacity), 0) AS total FROM quotas
                WHERE group_id = ? AND major_id <> ?
                """,
                (group_id, major_id),
            ).fetchone()["total"]
            total_capacity = connection.execute(
                "SELECT total_capacity FROM teaching_groups WHERE id = ?", (group_id,)
            ).fetchone()["total_capacity"]
            if other_sum + payload.capacity > total_capacity:
                raise HTTPException(
                    status_code=409,
                    detail=f"各专业配额合计不能超过教学组总容量 {total_capacity}",
                )
            connection.execute(
                """
                UPDATE quotas SET capacity = ?, updated_at = ?
                WHERE major_id = ? AND group_id = ?
                """,
                (payload.capacity, utc_now(), major_id, group_id),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="quota.update",
                entity_type="quota",
                entity_id=f"{major_id}:{group_id}",
                details={"from": current["capacity"], "to": payload.capacity},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"ok": True}

    @app.post("/api/admin/students/import")
    async def import_students(
        request: Request,
        file: Annotated[UploadFile, File(description="UTF-8 或 GB18030 CSV")],
    ):
        identity = require_session(request, "admin", csrf=True)
        content = await file.read(1_048_577)
        if len(content) > 1_048_576:
            raise HTTPException(status_code=413, detail="CSV 文件不能超过 1 MB")
        text: str
        try:
            text = content.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                text = content.decode("gb18030")
            except UnicodeDecodeError as exc:
                raise HTTPException(status_code=400, detail="CSV 编码需为 UTF-8 或 GB18030") from exc
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise HTTPException(status_code=400, detail="CSV 缺少表头")
        aliases = {
            "student_no": ("student_no", "学号"),
            "name": ("name", "姓名"),
            "major": ("major", "专业"),
            "activation_code": ("activation_code", "激活码"),
        }

        def pick(row: dict[str, str | None], key: str) -> str:
            for alias in aliases[key]:
                if alias in row and row[alias] is not None:
                    return clean_text(row[alias] or "")
            return ""

        rows = list(reader)
        if not rows:
            raise HTTPException(status_code=400, detail="CSV 没有学生记录")
        connection = connect(config.database_path)
        generated: list[dict[str, str]] = []
        created = 0
        updated = 0
        try:
            connection.execute("BEGIN IMMEDIATE")
            ensure_closed(connection)
            major_map = {
                row["name"]: int(row["id"])
                for row in connection.execute("SELECT id, name FROM majors").fetchall()
            }
            seen_numbers: set[str] = set()
            for line_number, row in enumerate(rows, start=2):
                student_no = pick(row, "student_no")
                name = pick(row, "name")
                major_name = pick(row, "major")
                supplied_code = pick(row, "activation_code")
                if not student_no or not name or not major_name:
                    raise HTTPException(
                        status_code=400,
                        detail=f"第 {line_number} 行必须填写学号、姓名和专业",
                    )
                if student_no in seen_numbers:
                    raise HTTPException(status_code=400, detail=f"学号 {student_no} 在文件中重复")
                seen_numbers.add(student_no)
                if major_name not in major_map:
                    raise HTTPException(
                        status_code=400,
                        detail=f"第 {line_number} 行的专业“{major_name}”不存在",
                    )
                existing = connection.execute(
                    "SELECT id, major_id FROM students WHERE student_no = ?", (student_no,)
                ).fetchone()
                code = supplied_code or (new_activation_code() if not existing else "")
                if existing:
                    active_selection = connection.execute(
                        "SELECT 1 FROM selections WHERE student_id = ? AND revoked_at IS NULL",
                        (existing["id"],),
                    ).fetchone()
                    if active_selection and existing["major_id"] != major_map[major_name]:
                        raise HTTPException(
                            status_code=409,
                            detail=f"学号 {student_no} 已有选择，不能更改所属专业",
                        )
                    if code:
                        connection.execute(
                            """
                            UPDATE students SET name = ?, major_id = ?, activation_hash = ?,
                                                active = 1, updated_at = ?
                            WHERE id = ?
                            """,
                            (
                                name,
                                major_map[major_name],
                                activation_code_hash(config.app_secret, code),
                                utc_now(),
                                existing["id"],
                            ),
                        )
                    else:
                        connection.execute(
                            """
                            UPDATE students SET name = ?, major_id = ?, active = 1, updated_at = ?
                            WHERE id = ?
                            """,
                            (name, major_map[major_name], utc_now(), existing["id"]),
                        )
                    updated += 1
                else:
                    now = utc_now()
                    connection.execute(
                        """
                        INSERT INTO students
                            (student_no, name, major_id, activation_hash, active, created_at, updated_at)
                        VALUES (?, ?, ?, ?, 1, ?, ?)
                        """,
                        (
                            student_no,
                            name,
                            major_map[major_name],
                            activation_code_hash(config.app_secret, code),
                            now,
                            now,
                        ),
                    )
                    created += 1
                if code:
                    generated.append(
                        {
                            "student_no": student_no,
                            "name": name,
                            "major": major_name,
                            "activation_code": code,
                        }
                    )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="students.import",
                entity_type="student",
                entity_id="batch",
                details={"created": created, "updated": updated, "credential_rows": len(generated)},
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"created": created, "updated": updated, "credentials": generated}

    @app.post("/api/admin/selections")
    def admin_assign(payload: AdminAssign, request: Request):
        identity = require_session(request, "admin", csrf=True)
        choose_group(
            student_id=payload.student_id,
            group_id=payload.group_id,
            source="admin",
            operator=str(identity.subject_id),
            require_open=False,
        )
        return {"ok": True}

    @app.post("/api/admin/selections/revoke")
    def revoke_selection(payload: RevokeSelection, request: Request):
        identity = require_session(request, "admin", csrf=True)
        connection = connect(config.database_path)
        try:
            connection.execute("BEGIN IMMEDIATE")
            selection = connection.execute(
                """
                SELECT id, group_id FROM selections
                WHERE student_id = ? AND revoked_at IS NULL
                """,
                (payload.student_id,),
            ).fetchone()
            if not selection:
                raise HTTPException(status_code=404, detail="该学生没有可撤销的当前选择")
            now = utc_now()
            connection.execute(
                "UPDATE selections SET revoked_at = ?, revoked_by = ? WHERE id = ?",
                (now, str(identity.subject_id), selection["id"]),
            )
            audit(
                connection,
                actor_type="admin",
                actor_id=identity.subject_id,
                action="selection.revoke",
                entity_type="selection",
                entity_id=selection["id"],
                details={
                    "student_id": payload.student_id,
                    "group_id": selection["group_id"],
                    "reason": payload.reason,
                },
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        return {"ok": True}

    def csv_response(filename: str, headers: list[str], rows: list[list[Any]]):
        buffer = io.StringIO()
        writer = csv.writer(buffer, lineterminator="\n")
        writer.writerow(headers)
        writer.writerows(rows)
        content = "\ufeff" + buffer.getvalue()
        return StreamingResponse(
            iter([content.encode("utf-8")]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )

    @app.get("/api/admin/export/selections.csv")
    def export_selections(request: Request):
        require_session(request, "admin")
        connection = connect(config.database_path)
        try:
            rows = connection.execute(
                """
                SELECT s.student_no, s.name, m.name AS major_name,
                       g.name AS group_name, se.selected_at, se.source
                FROM selections se
                JOIN students s ON s.id = se.student_id
                JOIN majors m ON m.id = s.major_id
                JOIN teaching_groups g ON g.id = se.group_id
                WHERE se.revoked_at IS NULL
                ORDER BY m.sort_order, g.sort_order, s.student_no
                """
            ).fetchall()
        finally:
            connection.close()
        return csv_response(
            "selections.csv",
            ["学号", "姓名", "专业", "教学组", "选择时间", "来源"],
            [[row[key] for key in row.keys()] for row in rows],
        )

    @app.get("/api/admin/export/unselected.csv")
    def export_unselected(request: Request):
        require_session(request, "admin")
        connection = connect(config.database_path)
        try:
            rows = connection.execute(
                """
                SELECT s.student_no, s.name, m.name AS major_name
                FROM students s JOIN majors m ON m.id = s.major_id
                LEFT JOIN selections se ON se.student_id = s.id AND se.revoked_at IS NULL
                WHERE s.active = 1 AND se.id IS NULL
                ORDER BY m.sort_order, s.student_no
                """
            ).fetchall()
        finally:
            connection.close()
        return csv_response(
            "unselected.csv",
            ["学号", "姓名", "专业"],
            [[row["student_no"], row["name"], row["major_name"]] for row in rows],
        )

    @app.get("/api/admin/audit")
    def audit_log(request: Request, limit: int = 100):
        require_session(request, "admin")
        limit = min(max(limit, 1), 500)
        connection = connect(config.database_path)
        try:
            rows = connection.execute(
                """
                SELECT id, occurred_at, actor_type, actor_id, action,
                       entity_type, entity_id, details_json
                FROM audit_logs ORDER BY id DESC LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [
                {
                    **{key: row[key] for key in row.keys() if key != "details_json"},
                    "details": json.loads(row["details_json"]),
                }
                for row in rows
            ]
        finally:
            connection.close()

    @app.get("/api/admin/qr.png")
    def qr_code(request: Request):
        require_session(request, "admin")
        connection = connect(config.database_path)
        try:
            settings = setting_dict(connection)
        finally:
            connection.close()
        base_url = settings["public_base_url"] or config.public_base_url
        if not base_url:
            raise HTTPException(status_code=409, detail="请先在系统设置中填写学生端访问地址")
        qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=12, border=4)
        qr.add_data(base_url.rstrip("/") + "/")
        qr.make(fit=True)
        image = qr.make_image(fill_color="#2b2223", back_color="#ffffff")
        output = io.BytesIO()
        image.save(output, format="PNG")
        output.seek(0)
        return StreamingResponse(output, media_type="image/png", headers={"Cache-Control": "no-store"})

    @app.get("/brand/college-wordmark-official.png", include_in_schema=False)
    def brand_asset():
        return FileResponse(
            BRAND_ROOT / "college-wordmark-official.png",
            media_type="image/png",
            headers={"Cache-Control": "public, max-age=86400"},
        )

    @app.get("/assets/app.css", include_in_schema=False)
    def css_asset():
        return FileResponse(WEB_ROOT / "app.css", media_type="text/css")

    @app.get("/assets/student.js", include_in_schema=False)
    def student_script():
        return FileResponse(WEB_ROOT / "student.js", media_type="text/javascript")

    @app.get("/assets/admin.js", include_in_schema=False)
    def admin_script():
        return FileResponse(WEB_ROOT / "admin.js", media_type="text/javascript")

    @app.get("/admin", include_in_schema=False)
    def admin_page():
        return FileResponse(WEB_ROOT / "admin.html", media_type="text/html")

    @app.get("/", include_in_schema=False)
    def student_page():
        return FileResponse(WEB_ROOT / "index.html", media_type="text/html")

    return app
