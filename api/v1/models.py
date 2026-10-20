"""模型目录接口, 业务编排委托应用服务。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import Response

from api.deps import get_models

router: APIRouter = APIRouter(tags=["models"])


@router.get("/v1/models")
async def models(request: Request) -> Response:
    """透传模型目录, 缓存由模型服务维护。"""
    return await get_models(request).list_models()
