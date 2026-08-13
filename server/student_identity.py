from __future__ import annotations

import re
import unicodedata
from typing import Any


STUDENT_NUMBER_MIN_LENGTH = 4
STUDENT_NUMBER_MAX_LENGTH = 32
STUDENT_NAME_MIN_LENGTH = 1
STUDENT_NAME_MAX_LENGTH = 80
ACTIVATION_CODE_LENGTH = 6

STUDENT_NUMBER_PATTERN = re.compile(r"^[A-Za-z0-9_-]{4,32}$")
STUDENT_NAME_PATTERN = re.compile(
    r"^[A-Za-z0-9\u00C0-\u024F\u1E00-\u1EFF"
    r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
    r"\U00020000-\U0002FA1F ·•・'’\-‐‑]+$"
)
ACTIVATION_CODE_PATTERN = re.compile(r"^[A-Z0-9]{6}$")


class StudentIdentityError(ValueError):
    """A roster/login identity field cannot produce a usable credential."""


def _require_text(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise StudentIdentityError(f"{label}必须是文本")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise StudentIdentityError(f"{label}不能包含控制字符")
    return value


def normalize_student_number(value: Any) -> str:
    """Return the canonical value accepted by both import and login."""

    text = unicodedata.normalize("NFKC", _require_text(value, "学号")).strip()
    if len(text) < STUDENT_NUMBER_MIN_LENGTH:
        raise StudentIdentityError(
            f"学号不能少于 {STUDENT_NUMBER_MIN_LENGTH} 个字符"
        )
    if len(text) > STUDENT_NUMBER_MAX_LENGTH:
        raise StudentIdentityError(
            f"学号不能超过 {STUDENT_NUMBER_MAX_LENGTH} 个字符"
        )
    if not STUDENT_NUMBER_PATTERN.fullmatch(text):
        raise StudentIdentityError("学号只能包含英文字母、数字、下划线或连字符")
    return text


def normalize_student_name(value: Any) -> str:
    """Normalize spacing while preserving supported mainland/HK/Macao/TW names."""

    text = unicodedata.normalize("NFKC", _require_text(value, "姓名"))
    text = " ".join(text.strip().split())
    if len(text) < STUDENT_NAME_MIN_LENGTH:
        raise StudentIdentityError("姓名不能为空")
    if len(text) > STUDENT_NAME_MAX_LENGTH:
        raise StudentIdentityError(
            f"姓名不能超过 {STUDENT_NAME_MAX_LENGTH} 个字符"
        )
    if not STUDENT_NAME_PATTERN.fullmatch(text):
        raise StudentIdentityError("姓名包含不支持的字符")
    return text


def normalize_activation_code(value: Any) -> str:
    text = _require_text(value, "个人激活码")
    normalized = "".join(unicodedata.normalize("NFKC", text).strip().upper().split())
    if not ACTIVATION_CODE_PATTERN.fullmatch(normalized):
        raise StudentIdentityError(
            f"个人激活码必须是 {ACTIVATION_CODE_LENGTH} 位英文字母或数字"
        )
    return normalized

