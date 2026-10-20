"""OpenAI Chat 接口, 业务编排委托应用服务。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from api.deps import get_proxy
from services.usage import ensure_chat_stream_usage

router: APIRouter = APIRouter(tags=["chat"])


@router.post("/v1/chat/completions")
async def chat_completions(request: Request) -> Response:
    """透传请求, 流式强制返回 usage, 剔除与换号由账号池服务负责。"""
    body = ensure_chat_stream_usage(await request.body())
    return await get_proxy(request).forward_response(
        protocol="openai",
        path="/v1/chat/completions",
        body=body,
        accept=request.headers.get("accept"),
    )
