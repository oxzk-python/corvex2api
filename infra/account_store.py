"""Redis 账号存储, 保存账号状态、余额口径与累计用量."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable
from dataclasses import dataclass

from redis.asyncio import Redis

from infra.pool import ACTIVE, Account
from infra.pricing import INITIAL_BALANCE_USD


@dataclass
class UsageStats:
    """账号累计 token、费用与请求数."""

    input_tokens: int = 0
    output_tokens: int = 0
    cost: float = 0.0
    requests: int = 0
    last_used_at: float = 0.0

    @property
    def total_tokens(self) -> int:
        """输入与输出 token 合计."""
        return self.input_tokens + self.output_tokens


def _int_field(value: str | None) -> int:
    """解析非负整数计数, 损坏值按 0."""
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _float_field(value: str | None) -> float:
    """解析非负浮点计数, 损坏值按 0."""
    try:
        return max(float(value or 0.0), 0.0)
    except (TypeError, ValueError):
        return 0.0


def _usage_stats(raw: dict[str, str]) -> UsageStats:
    """把 Hash 原始字段转换为用量对象."""
    return UsageStats(
        input_tokens=_int_field(raw.get("input_tokens")),
        output_tokens=_int_field(raw.get("output_tokens")),
        cost=_float_field(raw.get("cost")),
        requests=_int_field(raw.get("requests")),
        last_used_at=_float_field(raw.get("last_used_at")),
    )


class RedisAccountStore:
    """{prefix}:accounts Hash 存账号, {prefix}:usage:{id} 存用量, models 缓存目录."""

    def __init__(self, client: Redis, prefix: str, models_cache_seconds: int) -> None:
        """保存客户端与键名, 不负责连接生命周期."""
        self._client = client
        self._accounts_key = f"{prefix}:accounts"
        self._usage_prefix = f"{prefix}:usage"
        self._models_key = f"{prefix}:models"
        self._models_cache_seconds = models_cache_seconds

    async def ping(self) -> None:
        """探活 Redis 连接."""
        await self._client.ping()

    async def load_all(self) -> list[Account]:
        """读取全部账号, 损坏记录跳过不抛."""
        raw = await self._client.hgetall(self._accounts_key)
        accounts: list[Account] = []
        for account_id, document in raw.items():
            try:
                doc = json.loads(document)
                accounts.append(
                    Account(
                        id=account_id,
                        key=doc["key"],
                        status=doc.get("status", ACTIVE),
                        until=float(doc.get("until", 0.0)),
                        initial_balance=float(
                            doc.get("initial_balance", INITIAL_BALANCE_USD)
                        ),
                    )
                )
            except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                continue
        return accounts

    async def save(self, account: Account) -> None:
        """整条写入账号, 附带更新时间."""
        document = {
            "account": account.id,
            "key": account.key,
            "status": account.status,
            "until": account.until,
            "initial_balance": account.initial_balance,
            "updated_at": time.time(),
        }
        await self._client.hset(
            self._accounts_key, account.id, json.dumps(document, ensure_ascii=False)
        )

    async def set_status(self, account_id: str, status: str, until: float = 0.0) -> None:
        """只覆盖状态字段, 账号已被删除时静默跳过."""
        raw = await self._client.hget(self._accounts_key, account_id)
        if raw is None:
            return
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError:
            return
        doc["status"] = status
        doc["until"] = until
        doc["updated_at"] = time.time()
        await self._client.hset(
            self._accounts_key, account_id, json.dumps(doc, ensure_ascii=False)
        )

    async def delete(self, account_id: str) -> None:
        """删除账号及其用量记录."""
        pipe = self._client.pipeline(transaction=False)
        pipe.hdel(self._accounts_key, account_id)
        pipe.delete(self._usage_key(account_id))
        await pipe.execute()

    async def exists(self, account_id: str) -> bool:
        """判断账号是否存在."""
        return bool(await self._client.hexists(self._accounts_key, account_id))

    async def add_usage(
        self,
        account_id: str,
        input_tokens: int,
        output_tokens: int,
        cost: float,
    ) -> float:
        """原子累加一次请求用量, 返回累计费用."""
        key = self._usage_key(account_id)
        pipe = self._client.pipeline(transaction=False)
        pipe.hincrby(key, "input_tokens", input_tokens)
        pipe.hincrby(key, "output_tokens", output_tokens)
        pipe.hincrbyfloat(key, "cost", cost)
        pipe.hincrby(key, "requests", 1)
        pipe.hset(key, "last_used_at", time.time())
        results = await pipe.execute()
        return float(results[2])

    async def load_usage(self, account_id: str) -> UsageStats:
        """读取单个账号的累计用量."""
        raw = await self._client.hgetall(self._usage_key(account_id))
        return _usage_stats(raw)

    async def load_usages(self, account_ids: Iterable[str]) -> dict[str, UsageStats]:
        """批量读取账号用量, 返回 account_id 到用量的映射."""
        ids = list(account_ids)
        if not ids:
            return {}
        pipe = self._client.pipeline(transaction=False)
        for account_id in ids:
            pipe.hgetall(self._usage_key(account_id))
        rows = await pipe.execute()
        return {
            account_id: _usage_stats(raw)
            for account_id, raw in zip(ids, rows, strict=True)
        }

    def _usage_key(self, account_id: str) -> str:
        """账号用量 Hash 的键名."""
        return f"{self._usage_prefix}:{account_id}"

    async def cached_models(self) -> str | None:
        """读取模型目录缓存."""
        return await self._client.get(self._models_key)

    async def cache_models(self, payload: str) -> None:
        """按 TTL 写入模型目录缓存."""
        await self._client.set(self._models_key, payload, ex=self._models_cache_seconds)
