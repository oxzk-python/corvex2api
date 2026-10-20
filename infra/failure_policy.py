"""上游错误分类与退避解析."""

from __future__ import annotations

import json
import time
from email.utils import parsedate_to_datetime

# 对账号的处理动作
ACTION_RELAY = "relay"            # 与账号无关, 错误原样透传给客户端
ACTION_DISABLE = "disable"        # 永久剔除（exhausted）
ACTION_RATE_LIMIT = "rate_limit"  # 标记冷却, 到期自动恢复
ACTION_SKIP = "skip"              # 仅本次请求跳过, 不改账号状态


def extract_error(body: bytes) -> dict[str, str]:
    """解析 OpenAI/Anthropic 两种错误信封共有的 error.code/type/message."""
    try:
        doc = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return {}
    if not isinstance(doc, dict):
        return {}
    error = doc.get("error")
    if not isinstance(error, dict):
        return {}
    extracted: dict[str, str] = {}
    for field in ("code", "type", "message"):
        value = error.get(field)
        if isinstance(value, str) and value:
            extracted[field] = value
    return extracted


def classify(status: int, code: str) -> str:
    """按状态码与错误码决定账号处理动作."""
    if status in (401, 402):
        # 402 insufficient_credits / 401 invalid_api_key: key 已不可用
        return ACTION_DISABLE
    if status == 403:
        return ACTION_DISABLE if code == "virtual_key_blocked" else ACTION_SKIP
    if status == 429:
        return ACTION_RATE_LIMIT
    return ACTION_RELAY


def parse_retry_after(value: str | None) -> float | None:
    """解析 Retry-After 的秒数或 HTTP 日期, 不可解析时返回 None."""
    if not value:
        return None
    value = value.strip()
    try:
        return max(1.0, float(value))
    except ValueError:
        pass
    try:
        when = parsedate_to_datetime(value)
        return max(1.0, when.timestamp() - time.time())
    except (TypeError, ValueError):
        return None
