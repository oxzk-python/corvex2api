"""版本化 API 路由聚合。"""

from fastapi import APIRouter, Depends

from api.deps import require_api_key
from api.v1.accounts import router as accounts_router
from api.v1.chat import router as chat_router
from api.v1.health import router as health_router
from api.v1.messages import router as messages_router
from api.v1.models import router as models_router
from api.v1.responses import router as responses_router
from api.v1.status import router as status_router

api_router: APIRouter = APIRouter()

# 受保护端点在注册处声明鉴权, 避免维护独立的路径清单; models 与健康检查公开
protected = [Depends(require_api_key)]

api_router.include_router(health_router)
api_router.include_router(models_router)
api_router.include_router(chat_router, dependencies=protected)
api_router.include_router(responses_router, dependencies=protected)
api_router.include_router(messages_router, dependencies=protected)
api_router.include_router(accounts_router, dependencies=protected)
api_router.include_router(status_router, dependencies=protected)

__all__ = ["api_router"]
