"""Anthropic 消息接口, 业务编排委托应用服务。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from api.deps import get_proxy

router: APIRouter = APIRouter(tags=["messages"])


def _anthropic_headers(request: Request) -> dict[str, str]:
    """提取需转发的 anthropic-* 请求头（anthropic-version / anthropic-beta 等）。"""
    return {
        name: value
        for name, value in request.headers.items()
        if name.lower().startswith("anthropic-")
    }


@router.post("/v1/messages")
async def messages(request: Request) -> Response:
    """透传消息请求, 上游改用账号 key 走 x-api-key 认证。"""
    return await get_proxy(request).forward_response(
        protocol="anthropic",
        path="/v1/messages",
        body=await request.body(),
        accept=request.headers.get("accept"),
        anthropic_headers=_anthropic_headers(request),
    )


@router.post("/v1/messages/count_tokens")
async def count_tokens(request: Request) -> Response:
    """透传 token 计数请求, 错误处理与消息接口一致。"""
    return await get_proxy(request).forward_response(
        protocol="anthropic",
        path="/v1/messages/count_tokens",
        body=await request.body(),
        accept=request.headers.get("accept"),
        anthropic_headers=_anthropic_headers(request),
    )
