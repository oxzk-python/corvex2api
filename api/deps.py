"""HTTP 路由的类型化取件与鉴权依赖。"""

from __future__ import annotations

import secrets

from fastapi import Request

from core.config import Settings
from core.exceptions import AuthenticationError
from infra.pool import AccountPool
from services.accounts import AccountsService
from services.health import HealthService
from services.models import ModelsService
from services.proxy import ProxyService


def get_proxy(request: Request) -> ProxyService:
    """获取应用生命周期创建的换号透传服务。"""
    service: ProxyService = request.app.state.proxy
    return service


def get_accounts(request: Request) -> AccountsService:
    """获取账号管理服务。"""
    service: AccountsService = request.app.state.accounts
    return service


def get_models(request: Request) -> ModelsService:
    """获取模型目录服务。"""
    service: ModelsService = request.app.state.models
    return service


def get_health(request: Request) -> HealthService:
    """获取健康检查服务。"""
    service: HealthService = request.app.state.health
    return service


def get_pool(request: Request) -> AccountPool:
    """获取本次请求快照使用的账号池。"""
    pool: AccountPool = request.app.state.pool
    return pool


def _extract_key(request: Request) -> str | None:
    """兼容 Authorization: Bearer 与 x-api-key 两种鉴权头。"""
    authorization = request.headers.get("authorization")
    if authorization and authorization.lower().startswith("bearer "):
        return authorization[7:].strip()
    return request.headers.get("x-api-key")


def require_api_key(request: Request) -> None:
    """受保护端点的网关鉴权, 失败抛业务异常由全局边界按协议面渲染。"""
    settings: Settings = request.app.state.settings
    expected = settings.api_key
    if not expected:
        return
    if not secrets.compare_digest(_extract_key(request) or "", expected):
        raise AuthenticationError("Invalid gateway API key")
