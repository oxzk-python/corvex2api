"""请求元信息与响应用量提取, 兼容 OpenAI / Responses / Anthropic."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

_EVENT_BOUNDARY = re.compile(rb"\r?\n\r?\n")


@dataclass
class TokenUsage:
    """归一化后的输入/输出 token 数."""

    input_tokens: int = 0
    output_tokens: int = 0

    @property
    def total_tokens(self) -> int:
        """输入与输出 token 合计."""
        return self.input_tokens + self.output_tokens

    def merge(self, other: "TokenUsage") -> None:
        """取各字段较大值, 适配流式渐进上报的累计用量."""
        self.input_tokens = max(self.input_tokens, other.input_tokens)
        self.output_tokens = max(self.output_tokens, other.output_tokens)


def _as_int(value: object) -> int:
    """把上游可能为字符串或浮点的 token 数归一为非负整数."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        return max(int(value), 0)
    return 0


def _openai_usage(usage: dict) -> TokenUsage:
    """OpenAI Chat 用 prompt/completion, Responses 用 input/output."""
    return TokenUsage(
        input_tokens=_as_int(usage.get("prompt_tokens", usage.get("input_tokens"))),
        output_tokens=_as_int(
            usage.get("completion_tokens", usage.get("output_tokens"))
        ),
    )


def _anthropic_usage(usage: dict) -> TokenUsage:
    """Anthropic 的缓存读写 token 也按输入单价计入."""
    return TokenUsage(
        input_tokens=(
            _as_int(usage.get("input_tokens"))
            + _as_int(usage.get("cache_creation_input_tokens"))
            + _as_int(usage.get("cache_read_input_tokens"))
        ),
        output_tokens=_as_int(usage.get("output_tokens")),
    )


def extract_usage(protocol: str, body: bytes) -> TokenUsage | None:
    """从非流式 JSON 响应中提取用量, 无 usage 字段时返回 None."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        return None
    if protocol == "anthropic":
        return _anthropic_usage(usage)
    return _openai_usage(usage)


def request_model(body: bytes) -> str:
    """尽力从请求体读取 model, 解析失败返回空串."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ""
    if not isinstance(payload, dict):
        return ""
    model = payload.get("model")
    return model.strip() if isinstance(model, str) else ""


def ensure_chat_stream_usage(body: bytes) -> bytes:
    """OpenAI Chat 流式请求强制 include_usage, 保证末尾返回 usage chunk."""
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return body
    if not isinstance(payload, dict) or payload.get("stream") is not True:
        return body
    options = payload.get("stream_options")
    if isinstance(options, dict) and options.get("include_usage") is True:
        return body
    payload["stream_options"] = {
        **(options if isinstance(options, dict) else {}),
        "include_usage": True,
    }
    try:
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        return body


class SSEUsageParser:
    """增量解析 SSE 事件, 汇总 OpenAI / Responses / Anthropic 的用量."""

    def __init__(self, protocol: str) -> None:
        """按协议面选择 usage 字段解释方式."""
        self.protocol = protocol
        self._buffer = b""
        self._usage = TokenUsage()

    def feed(self, chunk: bytes) -> None:
        """接收任意切分的响应字节, 解析出完整事件."""
        self._buffer += chunk
        while match := _EVENT_BOUNDARY.search(self._buffer):
            event = self._buffer[: match.start()]
            self._buffer = self._buffer[match.end() :]
            self._consume(event)

    def finish(self) -> TokenUsage:
        """处理末尾残留事件并返回累计用量."""
        if self._buffer.strip():
            self._consume(self._buffer)
            self._buffer = b""
        return self._usage

    def _consume(self, event: bytes) -> None:
        """解析单个事件的 data 行, 忽略注释与无法识别的负载."""
        try:
            text = event.decode()
        except UnicodeDecodeError:
            return
        data_lines = [
            line[5:].lstrip()
            for line in text.splitlines()
            if line.startswith("data:")
        ]
        if not data_lines:
            return
        data = "\n".join(data_lines)
        if data == "[DONE]":
            return
        try:
            payload = json.loads(data)
        except json.JSONDecodeError:
            return
        if isinstance(payload, dict):
            self._merge_event(payload)

    def _merge_event(self, payload: dict) -> None:
        """从单个事件中提取用量并合并."""
        if self.protocol == "anthropic":
            event_type = payload.get("type")
            if event_type not in ("message_start", "message_delta"):
                return
            message = payload.get("message")
            usage = message.get("usage") if isinstance(message, dict) else None
            if not isinstance(usage, dict):
                usage = payload.get("usage")
            if isinstance(usage, dict):
                self._usage.merge(_anthropic_usage(usage))
            return

        event_type = payload.get("type")
        if event_type in ("response.completed", "response.incomplete"):
            response = payload.get("response")
            usage = response.get("usage") if isinstance(response, dict) else None
            if isinstance(usage, dict):
                self._usage.merge(_openai_usage(usage))
            return
        usage = payload.get("usage")
        if isinstance(usage, dict):
            self._usage.merge(_openai_usage(usage))
