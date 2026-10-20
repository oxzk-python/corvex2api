"""应用配置。"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全部运行参数, 读取环境变量与项目根 .env。"""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    api_key: str = ""
    redis_url: str = "redis://localhost:6379/0"
    redis_prefix: str = "corvex2api"
    upstream_base: str = "https://api.tokenfactory.corvex.cloud"
    proxy: str = ""  # 上游出口代理（http://user:pass@host:port），留空直连
    timeout_seconds: float = Field(default=180.0, gt=0)
    max_account_retries: int = Field(default=3, ge=1)
    rate_limit_cooldown: float = Field(default=60.0, ge=0)
    models_cache_seconds: int = Field(default=3600, ge=0)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """创建并缓存应用统一配置实例。"""
    return Settings()


settings: Settings = get_settings()
