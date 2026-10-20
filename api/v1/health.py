"""公共健康检查接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.deps import get_health

router: APIRouter = APIRouter(tags=["health"])


@router.get("/")
async def root() -> dict[str, Any]:
    """返回服务标识与可用端点。"""
    return {
        "service": "corvex2api",
        "endpoints": [
            "/v1/chat/completions",
            "/v1/responses",
            "/v1/messages",
            "/v1/models",
        ],
    }


@router.get("/healthz")
async def healthz(request: Request) -> dict[str, str]:
    """探测 Redis 连接, 失败由健康服务抛出业务异常。"""
    return await get_health(request).check()
