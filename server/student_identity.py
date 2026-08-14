from __future__ import annotations

import re
import unicodedata
from typing import Any


STUDENT_NUMBER_LENGTH = 11
STUDENT_NUMBER_MIN_LENGTH = STUDENT_NUMBER_LENGTH
STUDENT_NUMBER_MAX_LENGTH = STUDENT_NUMBER_LENGTH
STUDENT_NAME_MIN_LENGTH = 1
STUDENT_NAME_MAX_LENGTH = 40
ACTIVATION_CODE_LENGTH = 6

STUDENT_NUMBER_PATTERN = re.compile(r"^[0-9]{11}$")
_STUDENT_NAME_LETTERS = (
    r"A-Za-z"
    r"\u3400-\u4DBF\u4E00-\u9FFF\uF900-\uFAFF"
    r"\U00020000-\U0002FA1F"
)
STUDENT_NAME_PATTERN = re.compile(
    rf"^[{_STUDENT_NAME_LETTERS}]+(?:[ ·•・][{_STUDENT_NAME_LETTERS}]+)*$"
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
    if not STUDENT_NUMBER_PATTERN.fullmatch(text):
        raise StudentIdentityError(f"学号必须是 {STUDENT_NUMBER_LENGTH} 位数字")
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
        raise StudentIdentityError(
            "姓名只能包含中文或英文字母，姓名各部分之间可使用空格或中点"
        )
    return text


def normalize_activation_code(value: Any) -> str:
    text = _require_text(value, "个人激活码")
    normalized = unicodedata.normalize("NFKC", text).strip().upper()
    if not ACTIVATION_CODE_PATTERN.fullmatch(normalized):
        raise StudentIdentityError(
            f"个人激活码必须是 {ACTIVATION_CODE_LENGTH} 位英文字母或数字"
        )
    return normalized

