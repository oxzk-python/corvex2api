"""模型目录透传与缓存的业务编排。"""

from __future__ import annotations

import httpx
from fastapi.responses import Response

from core.exceptions import GatewayUnavailableError
from core.logger import logger
from infra.account_store import RedisAccountStore
from infra.upstream import Upstream
from services.relay import to_fastapi_response


class ModelsService:
    """读取上游公开模型目录, 结果短暂缓存在 Redis。"""

    def __init__(self, store: RedisAccountStore, upstream: Upstream) -> None:
        """注入 Redis 存储与上游客户端。"""
        self.store = store
        self.upstream = upstream

    async def list_models(self) -> Response:
        """命中缓存直接返回, 否则请求上游并按 TTL 回填。"""
        cached = await self.store.cached_models()
        if cached is not None:
            return Response(content=cached, status_code=200, media_type="application/json")
        try:
            response = await self.upstream.fetch_models()
        except httpx.RequestError as exc:
            raise GatewayUnavailableError(
                "upstream_unreachable", f"cannot reach upstream: {exc}", status=502
            ) from exc
        if response.status_code == 200:
            await self.store.cache_models(response.text)
        else:
            logger.warning("upstream models fetch failed: %s", response.status_code)
        return await to_fastapi_response(response, "openai")
