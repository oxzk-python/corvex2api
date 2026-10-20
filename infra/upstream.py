"""Corvex Token Factory 上游客户端."""

from __future__ import annotations

import httpx

from core.config import Settings

DEFAULT_ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_ACCEPT = "application/json, text/event-stream"
USER_AGENT = "corvex2api/1.0"


class Upstream:
    """OpenAI 面用 Bearer, Anthropic 面用 x-api-key, 连接池由应用入口统一关闭."""

    def __init__(self, settings: Settings) -> None:
        """按配置创建带连接池的异步客户端."""
        self._client = httpx.AsyncClient(
            base_url=settings.upstream_base.rstrip("/"),
            timeout=httpx.Timeout(
                connect=10.0, read=settings.timeout_seconds, write=30.0, pool=10.0
            ),
            proxy=settings.proxy or None,
            trust_env=False,
            limits=httpx.Limits(max_connections=100, max_keepalive_connections=20),
        )

    async def aclose(self) -> None:
        """关闭底层连接池."""
        await self._client.aclose()

    def build_request(
        self,
        key: str,
        path: str,
        body: bytes,
        *,
        protocol: str,
        accept: str | None = None,
        anthropic_headers: dict[str, str] | None = None,
    ) -> httpx.Request:
        """按协议面选择认证头并组装请求."""
        headers = {
            "Content-Type": "application/json",
            "Accept": accept or DEFAULT_ACCEPT,
            "User-Agent": USER_AGENT,
        }
        if protocol == "anthropic":
            headers["x-api-key"] = key
            for name, value in (anthropic_headers or {}).items():
                headers[name] = value
            headers.setdefault("anthropic-version", DEFAULT_ANTHROPIC_VERSION)
        else:
            headers["Authorization"] = f"Bearer {key}"
        return self._client.build_request("POST", path, content=body, headers=headers)

    async def send(self, request: httpx.Request) -> httpx.Response:
        """以流模式发送, 读完或关闭由调用方负责."""
        return await self._client.send(request, stream=True)

    async def fetch_models(self) -> httpx.Response:
        """请求公开模型目录, 无需账号 key."""
        return await self._client.get(
            "/v1/models",
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
        )
