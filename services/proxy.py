"""多账号换号透传的业务编排。"""

from __future__ import annotations

import time
from dataclasses import dataclass

import httpx
from fastapi.responses import Response

from core.exceptions import GatewayUnavailableError
from core.logger import logger
from infra import pricing
from infra.failure_policy import (
    ACTION_DISABLE,
    ACTION_RATE_LIMIT,
    ACTION_RELAY,
    classify,
    extract_error,
    parse_retry_after,
)
from infra.pool import EXHAUSTED, RATE_LIMITED, Account
from services.relay import to_fastapi_response
from services.usage import TokenUsage, request_model


@dataclass
class ForwardResult:
    """一次上游响应对应的账号."""

    response: httpx.Response
    account: Account


class ProxyService:
    """402/401/403(virtual_key_blocked) 剔除换号, 429 标记冷却, 其余错误原样透传。"""

    def __init__(self, settings, pool, store, upstream) -> None:
        """注入配置, 账号池, 存储与上游客户端, 不自行创建连接。"""
        self.settings = settings
        self.pool = pool
        self.store = store
        self.upstream = upstream

    async def forward_response(
        self,
        *,
        protocol: str,
        path: str,
        body: bytes,
        accept: str | None = None,
        anthropic_headers: dict[str, str] | None = None,
    ) -> Response:
        """转发并把上游 200 与 RELAY 错误转成给客户端的最终响应。"""
        result = await self.forward(
            protocol=protocol,
            path=path,
            body=body,
            accept=accept,
            anthropic_headers=anthropic_headers,
        )
        usage_sink = None
        if result.response.status_code == 200 and not path.endswith("/count_tokens"):
            model = request_model(body)

            async def record(usage: TokenUsage) -> None:
                await self._record_usage(result.account, model, usage)

            usage_sink = record
        return await to_fastapi_response(
            result.response, protocol, usage_sink=usage_sink
        )

    async def forward(
        self,
        *,
        protocol: str,
        path: str,
        body: bytes,
        accept: str | None = None,
        anthropic_headers: dict[str, str] | None = None,
    ) -> ForwardResult:
        """带换号重试地发送请求, 同一请求体重发保证会话上下文不丢。"""
        tried: set[str] = set()
        attempts = 0
        network_errors = 0
        while attempts < self.settings.max_account_retries:
            account = self.pool.pick(tried)
            if account is None:
                break
            attempts += 1
            tried.add(account.id)
            request = self.upstream.build_request(
                account.key,
                path,
                body,
                protocol=protocol,
                accept=accept,
                anthropic_headers=anthropic_headers,
            )
            try:
                response = await self.upstream.send(request)
            except httpx.RequestError as exc:
                network_errors += 1
                logger.warning("account %s network error: %s", account.id, exc)
                continue
            if response.status_code == 200:
                return ForwardResult(response=response, account=account)
            try:
                await response.aread()
            except httpx.HTTPError as exc:
                await response.aclose()
                network_errors += 1
                logger.warning("account %s error body read failed: %s", account.id, exc)
                continue
            error = extract_error(response.content)
            code = error.get("code", "")
            action = classify(response.status_code, code)
            if action == ACTION_RELAY:
                logger.info(
                    "account %s relay %s on %s (%s)",
                    account.id,
                    response.status_code,
                    path,
                    code or "no code",
                )
                return ForwardResult(response=response, account=account)
            if action == ACTION_DISABLE:
                logger.info(
                    "account %s exhausted after %s on %s (%s); switch account",
                    account.id,
                    response.status_code,
                    path,
                    code or "no code",
                )
                await self._mark(account, EXHAUSTED)
            elif action == ACTION_RATE_LIMIT:
                cooldown = parse_retry_after(response.headers.get("retry-after"))
                if cooldown is None:
                    cooldown = self.settings.rate_limit_cooldown
                logger.info(
                    "account %s rate limited, cooldown %.0fs; switch account",
                    account.id,
                    cooldown,
                )
                await self._mark(account, RATE_LIMITED, time.time() + cooldown)
            await response.aclose()
        if attempts == 0:
            raise GatewayUnavailableError("no_accounts_available", "no usable account in pool")
        if attempts == network_errors:
            raise GatewayUnavailableError(
                "upstream_unreachable", "cannot reach upstream", status=502
            )
        raise GatewayUnavailableError(
            "no_accounts_available", "all tried accounts are exhausted or rate limited"
        )

    async def _record_usage(
        self, account: Account, model: str, usage: TokenUsage
    ) -> None:
        """按模型单价结算一次请求, 余额耗尽时剔除账号; 失败不影响客户端."""
        cost = pricing.cost_usd(model, usage.input_tokens, usage.output_tokens)
        if cost is None:
            cost = 0.0
            logger.warning(
                "unknown model %r; record tokens without cost (account %s, in=%d, out=%d)",
                model,
                account.id,
                usage.input_tokens,
                usage.output_tokens,
            )
        try:
            total_cost = await self.store.add_usage(
                account.id, usage.input_tokens, usage.output_tokens, cost
            )
        except Exception as exc:
            logger.warning("persist usage for account %s failed: %s", account.id, exc)
            return
        remaining = account.initial_balance - total_cost
        logger.info(
            "account %s usage: model=%s in=%d out=%d cost=$%.6f remaining=$%.6f",
            account.id,
            model or "unknown",
            usage.input_tokens,
            usage.output_tokens,
            cost,
            max(remaining, 0.0),
        )
        if remaining <= 0 and account.status != EXHAUSTED:
            logger.info("account %s balance exhausted; disable", account.id)
            await self._mark(account, EXHAUSTED)

    async def _mark(self, account: Account, status: str, until: float = 0.0) -> None:
        """同步更新内存池并持久化到 Redis, 失败不影响转发。"""
        self.pool.mark(account.id, status, until)
        try:
            await self.store.set_status(account.id, status, until)
        except Exception as exc:
            logger.warning("persist status for account %s failed: %s", account.id, exc)
