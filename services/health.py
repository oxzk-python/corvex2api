"""公开健康检查的业务编排."""

from __future__ import annotations

from core.exceptions import HealthCheckError
from infra.account_store import RedisAccountStore


class HealthService:
    """验证 Redis 连接与账号存储可用."""

    def __init__(self, store: RedisAccountStore) -> None:
        """注入共享 Redis 存储, 不单独创建连接."""
        self.store = store

    async def check(self) -> dict[str, str]:
        """ping Redis, 失败时抛出健康检查错误."""
        try:
            await self.store.ping()
        except Exception as exc:
            raise HealthCheckError("redis unavailable") from exc
        return {"status": "ok", "redis": "ok"}
