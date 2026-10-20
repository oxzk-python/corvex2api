"""FastAPI 应用创建与资源组装入口。"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncGenerator

import redis.asyncio as aioredis
from fastapi import FastAPI

from api import api_router
from api.exception_handlers import register_exception_handlers
from api.middleware import GatewayMiddleware
from core.config import Settings, settings
from services.accounts import AccountsService
from services.health import HealthService
from services.models import ModelsService
from services.proxy import ProxyService
from infra.account_store import RedisAccountStore
from infra.pool import AccountPool
from infra.upstream import Upstream



def create_app(app_settings: Settings | None = None) -> FastAPI:
    """创建 FastAPI 应用实例。"""
    selected_settings: Settings = app_settings or settings

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """连接 Redis 并组装账号池与全部服务, 退出时释放资源。"""
        client = aioredis.from_url(selected_settings.redis_url, decode_responses=True)
        try:
            await client.ping()
        except aioredis.RedisError as exc:
            await client.aclose()
            raise RuntimeError(
                f"cannot connect to redis at {selected_settings.redis_url}: {exc}"
            ) from exc
        store = RedisAccountStore(
            client, selected_settings.redis_prefix, selected_settings.models_cache_seconds
        )
        pool = AccountPool()
        pool.reload(await store.load_all())
        upstream = Upstream(selected_settings)
        app.state.settings = selected_settings
        app.state.pool = pool
        app.state.store = store
        app.state.proxy = ProxyService(selected_settings, pool, store, upstream)
        app.state.accounts = AccountsService(pool, store)
        app.state.models = ModelsService(store, upstream)
        app.state.health = HealthService(store)
        try:
            yield
        finally:
            await upstream.aclose()
            await client.aclose()

    app: FastAPI = FastAPI(
        title="corvex2api",
        version="1.0.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.settings = selected_settings
    app.add_middleware(GatewayMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    return app


app: FastAPI = create_app()
