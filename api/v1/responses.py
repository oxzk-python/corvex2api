"""OpenAI Responses 接口, 业务编排委托应用服务。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from api.deps import get_proxy

router: APIRouter = APIRouter(tags=["responses"])


@router.post("/v1/responses")
async def responses(request: Request) -> Response:
    """透传请求, 剔除与换号由账号池服务负责。"""
    return await get_proxy(request).forward_response(
        protocol="openai",
        path="/v1/responses",
        body=await request.body(),
        accept=request.headers.get("accept"),
    )
