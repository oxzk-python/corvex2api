"""账号导入, 状态与用量查看的业务编排。"""

from __future__ import annotations

import json
from typing import Any

from core.exceptions import NotFoundError, ValidationError
from core.logger import logger
from infra.account_store import RedisAccountStore
from infra.pool import EXHAUSTED, Account, AccountPool
from infra.pricing import INITIAL_BALANCE_USD


def _normalize(item: dict[str, Any]) -> Account | None:
    """归一化账号条目: 首选 api_key 单字符串, 兼容 result.json 的 api_keys 数组（取第一个）。"""
    key = str(item.get("api_key") or "").strip()
    if not key:
        api_keys = item.get("api_keys")
        if isinstance(api_keys, list) and api_keys:
            first = api_keys[0]
            value = first.get("value") if isinstance(first, dict) else first
            key = str(value or "").strip()
    if not key:
        return None
    account_id = str(item.get("email") or "").strip() or key[:16]
    return Account(id=account_id, key=key)


class AccountsService:
    """维护 Redis 账号池数据与累计用量, 对外不返回 key 明文。"""

    def __init__(self, pool: AccountPool, store: RedisAccountStore) -> None:
        """注入共享账号池与 Redis 存储。"""
        self.pool = pool
        self.store = store

    async def add(self, body: bytes) -> dict[str, Any]:
        """解析并导入账号, 兼容单条与数组; 重复 email 视为更新 key 并保留用量。"""
        try:
            payload = json.loads(body)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise ValidationError("request body must be valid JSON") from exc
        items = payload if isinstance(payload, list) else [payload]
        imported: list[str] = []
        updated: list[str] = []
        skipped = 0
        for item in items:
            account = _normalize(item) if isinstance(item, dict) else None
            if account is None:
                skipped += 1
                continue
            existing = self.pool.get(account.id)
            if existing is not None or await self.store.exists(account.id):
                updated.append(account.id)
                if existing is not None:
                    account.initial_balance = existing.initial_balance
                usage = await self.store.load_usage(account.id)
                if account.initial_balance - usage.cost <= 0:
                    account.status = EXHAUSTED
            else:
                account.initial_balance = INITIAL_BALANCE_USD
                imported.append(account.id)
            await self.store.save(account)
            self.pool.upsert(account)
        logger.info(
            "accounts import: %d imported, %d updated, %d skipped",
            len(imported),
            len(updated),
            skipped,
        )
        return {
            "imported": imported,
            "updated": updated,
            "skipped": skipped,
            "total": len(items),
        }

    async def list_accounts(self) -> dict[str, Any]:
        """列出全部账号、状态、余额与用量, 不包含 key。"""
        rows = await self._rows()
        return {"total": len(rows), "accounts": rows}

    async def summary(self) -> dict[str, int | float]:
        """汇总账号池余额与 token 用量。"""
        rows = await self._rows()
        return {
            "total_initial_balance": round(
                sum(row["initial_balance"] for row in rows), 6
            ),
            "total_remaining_balance": round(
                sum(row["remaining_balance"] for row in rows), 6
            ),
            "total_used": round(sum(row["used"] for row in rows), 6),
            "total_input_tokens": sum(row["input_tokens"] for row in rows),
            "total_output_tokens": sum(row["output_tokens"] for row in rows),
            "total_tokens": sum(row["total_tokens"] for row in rows),
            "total_requests": sum(row["requests"] for row in rows),
        }

    async def delete(self, account_id: str) -> dict[str, str]:
        """删除指定账号, 不存在时抛出业务异常。"""
        if not await self.store.exists(account_id):
            raise NotFoundError(f"account {account_id!r} not found")
        await self.store.delete(account_id)
        self.pool.remove(account_id)
        return {"deleted": account_id}

    async def _rows(self) -> list[dict[str, Any]]:
        """合并账号记录与用量, 供列表和汇总共用。"""
        accounts = await self.store.load_all()
        usages = await self.store.load_usages(account.id for account in accounts)
        rows: list[dict[str, Any]] = []
        for account in sorted(accounts, key=lambda item: item.id):
            usage = usages[account.id]
            remaining = max(account.initial_balance - usage.cost, 0.0)
            rows.append(
                {
                    "account": account.id,
                    "status": account.status,
                    "until": account.until,
                    "available": account.healthy(),
                    "initial_balance": round(account.initial_balance, 6),
                    "used": round(usage.cost, 6),
                    "remaining_balance": round(remaining, 6),
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                    "total_tokens": usage.total_tokens,
                    "requests": usage.requests,
                    "last_used_at": usage.last_used_at,
                }
            )
        return rows
