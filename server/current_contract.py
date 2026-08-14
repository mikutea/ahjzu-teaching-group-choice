from __future__ import annotations

import re
import unicodedata
from ipaddress import ip_address
from urllib.parse import urlsplit


ACTIVITY_CODE_PATTERN = re.compile(r"^[A-Za-z0-9_-]{2,48}$")
HOST_LABEL_PATTERN = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")


def clean_text(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("文本必须是字符串")
    if any(unicodedata.category(character).startswith("C") for character in value):
        raise ValueError("文本不能包含控制字符")
    return " ".join(value.strip().split())


def normalize_named_value(
    value: str, *, label: str, minimum: int, maximum: int
) -> str:
    normalized = clean_text(value)
    if len(normalized) < minimum or len(normalized) > maximum:
        raise ValueError(f"{label}长度必须为 {minimum} 至 {maximum} 个字符")
    return normalized


def normalize_activity_code(value: str) -> str:
    normalized = clean_text(value)
    if not ACTIVITY_CODE_PATTERN.fullmatch(normalized):
        raise ValueError("活动编码只能包含英文字母、数字、下划线或连字符")
    return normalized


def normalize_admin_username(value: str) -> str:
    return normalize_named_value(value, label="管理员账号", minimum=1, maximum=80)


def normalize_public_base_url(value: str) -> str:
    normalized = clean_text(value)
    if not normalized:
        return ""
    parsed = urlsplit(normalized)
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise ValueError("访问地址必须是完整的 http 或 https 站点地址")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("访问地址不能包含账号或密码")
    if parsed.query or parsed.fragment or parsed.path not in {"", "/"}:
        raise ValueError("访问地址只能填写站点根地址，不能包含路径、参数或片段")
    host = parsed.hostname
    try:
        parsed_ip = ip_address(host)
    except ValueError:
        host = host.rstrip(".")
        labels = host.split(".")
        if (
            not host
            or len(host) > 253
            or any(not HOST_LABEL_PATTERN.fullmatch(label) for label in labels)
        ):
            raise ValueError("访问地址中的主机名无效")
        host = host.lower()
    else:
        host = f"[{parsed_ip}]" if parsed_ip.version == 6 else str(parsed_ip)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("访问地址中的端口无效") from exc
    port_suffix = f":{port}" if port is not None else ""
    return f"{parsed.scheme.lower()}://{host}{port_suffix}"
