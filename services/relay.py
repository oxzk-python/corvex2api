"""上游响应与 SSE 流的桥接。"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import AsyncGenerator

import anyio
import httpx
from fastapi.responses import Response, StreamingResponse

from core.exceptions import (
    GatewayUnavailableError,
    anthropic_error_body,
    anthropic_type,
    openai_error_body,
)
from core.logger import logger
from services.usage import SSEUsageParser, TokenUsage, extract_usage

SSE_CONTENT_TYPE = "text/event-stream"

UsageSink = Callable[[TokenUsage], Awaitable[None]]


def openai_stream_error_event() -> bytes:
    """构造 OpenAI 流中断错误事件, 以 [DONE] 收尾。"""
    payload = openai_error_body("server_error", "upstream stream interrupted", "server_error")
    return b"data: " + json.dumps(payload).encode() + b"\n\ndata: [DONE]\n\n"


def anthropic_stream_error_event() -> bytes:
    """构造 Anthropic 流中断错误事件。"""
    payload = anthropic_error_body(anthropic_type("server_error"), "upstream stream interrupted")
    return b"event: error\ndata: " + json.dumps(payload).encode() + b"\n\n"


async def relay_stream(
    response: httpx.Response,
    protocol: str,
    usage_sink: UsageSink | None = None,
) -> AsyncGenerator[bytes, None]:
    """原样转发上游字节, 旁路解析用量, 中断时按协议补发错误事件。"""
    parser = SSEUsageParser(protocol) if usage_sink is not None else None
    try:
        async for chunk in response.aiter_bytes():
            if parser is not None:
                parser.feed(chunk)
            yield chunk
    except Exception as exc:
        logger.warning("upstream stream interrupted: %s", exc)
        if protocol == "anthropic":
            yield anthropic_stream_error_event()
        else:
            yield openai_stream_error_event()
    finally:
        usage = parser.finish() if parser is not None else None
        # 客户端断开时任务处于取消状态, 屏蔽取消确保上游连接一定被关闭
        with anyio.CancelScope(shield=True):
            await response.aclose()
        if usage is not None and usage.total_tokens and usage_sink is not None:
            with anyio.CancelScope(shield=True):
                try:
                    await usage_sink(usage)
                except Exception as exc:  # noqa: BLE001 - 记账失败不影响已完成的响应
                    logger.warning("record usage failed: %s", exc)


async def to_fastapi_response(
    response: httpx.Response,
    protocol: str,
    usage_sink: UsageSink | None = None,
) -> Response:
    """上游 200（流式/非流式）与 RELAY 错误统一转 FastAPI 响应, 字节原样透传。"""
    content_type = response.headers.get("content-type", "application/json")
    request_id = response.headers.get("x-request-id")
    if response.status_code == 200 and SSE_CONTENT_TYPE in content_type:
        headers = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
        if request_id:
            headers["x-request-id"] = request_id
        return StreamingResponse(
            relay_stream(response, protocol, usage_sink),
            media_type=SSE_CONTENT_TYPE,
            headers=headers,
        )
    try:
        body = await response.aread()
    except httpx.HTTPError as exc:
        await response.aclose()
        raise GatewayUnavailableError(
            "upstream_stream_error", f"upstream body read failed: {exc}", status=502
        ) from exc
    await response.aclose()
    if response.status_code == 200 and usage_sink is not None:
        usage = extract_usage(protocol, body)
        if usage is not None and usage.total_tokens:
            try:
                await usage_sink(usage)
            except Exception as exc:  # noqa: BLE001 - 记账失败不影响响应
                logger.warning("record usage failed: %s", exc)
    headers = {"content-type": content_type}
    if request_id:
        headers["x-request-id"] = request_id
    return Response(content=body, status_code=response.status_code, headers=headers)
