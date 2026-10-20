"""账号池状态接口。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.deps import get_accounts, get_pool

router: APIRouter = APIRouter(tags=["status"])


@router.get("/status")
async def status(request: Request) -> dict[str, Any]:
    """输出账号池状态计数与余额、token 汇总。"""
    summary = await get_accounts(request).summary()
    return {
        **get_pool(request).snapshot(),
        **summary,
        "service": "corvex2api",
    }
