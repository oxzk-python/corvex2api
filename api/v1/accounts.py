"""账号管理接口, 业务编排委托应用服务。"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request

from api.deps import get_accounts

router: APIRouter = APIRouter(tags=["accounts"])


@router.post("/accounts")
async def add_accounts(request: Request) -> dict[str, Any]:
    """导入账号, 支持 {email, api_key} 单条/数组与 autara result.json 格式。"""
    return await get_accounts(request).add(await request.body())


@router.get("/accounts")
async def list_accounts(request: Request) -> dict[str, Any]:
    """列出全部账号与状态, 不包含 key。"""
    return await get_accounts(request).list_accounts()


@router.delete("/accounts/{account_id}")
async def delete_account(account_id: str, request: Request) -> dict[str, str]:
    """删除指定账号。"""
    return await get_accounts(request).delete(account_id)
