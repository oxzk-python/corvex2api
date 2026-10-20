"""账号池同步边界。"""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from core.logger import logger
from infra.account_store import RedisAccountStore
from infra.pool import AccountPool


class GatewayMiddleware(BaseHTTPMiddleware):
    """每请求从 Redis 刷新账号池, 保持多实例状态一致。

    这里是 deps 类型化取件之外的唯一动态取件点: 中间件运行在路由解析之前,
    拿不到 Depends 机制, 只能直接读 app.state, 属有意为之。
    端点鉴权已由路由级 Depends(require_api_key) 承担, 不在此处理。
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        store: RedisAccountStore | None = getattr(request.app.state, "store", None)
        if store is not None:
            pool: AccountPool = request.app.state.pool
            try:
                pool.reload(await store.load_all())
            except Exception as exc:
                logger.warning("account pool reload failed: %s", exc)
        return await call_next(request)
