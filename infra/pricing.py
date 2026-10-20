"""模型单价与余额口径, 价格来源 https://docs.corvex.cloud/pricing."""

from __future__ import annotations

from dataclasses import dataclass

INITIAL_BALANCE_USD = 6.0
_TOKENS_PER_MILLION = 1_000_000


@dataclass(frozen=True)
class ModelPrice:
    """模型单价, 单位 USD / 1M tokens."""

    input: float
    output: float


PRICES: dict[str, ModelPrice] = {
    "zai-org/glm-5.3": ModelPrice(input=1.40, output=4.40),
    "deepseek-ai/deepseek-v4-flash-0731": ModelPrice(input=0.14, output=0.28),
}

ALIASES: dict[str, str] = {
    "glm 5.3": "zai-org/glm-5.3",
    "glm-5.3": "zai-org/glm-5.3",
    "deepseek v4 flash": "deepseek-ai/deepseek-v4-flash-0731",
    "deepseek v4 flash 0731": "deepseek-ai/deepseek-v4-flash-0731",
    "deepseek-v4-flash-0731": "deepseek-ai/deepseek-v4-flash-0731",
}


def _normalize(model: str) -> str:
    """统一大小写、下划线与空白, 便于匹配模型 ID 和文档名称."""
    return " ".join(model.strip().lower().replace("_", "-").split())


def price_for(model: str) -> ModelPrice | None:
    """按模型 ID 或别名查价, 未知模型返回 None."""
    normalized = _normalize(model)
    canonical = ALIASES.get(normalized)
    if canonical is not None:
        return PRICES[canonical]
    return PRICES.get(normalized)


def cost_usd(model: str, input_tokens: int, output_tokens: int) -> float | None:
    """按模型单价计算一次请求费用, 未知模型返回 None."""
    price = price_for(model)
    if price is None:
        return None
    return (
        input_tokens * price.input + output_tokens * price.output
    ) / _TOKENS_PER_MILLION
