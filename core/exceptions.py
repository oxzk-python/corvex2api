"""统一业务异常, 稳定错误码与协议错误信封构造."""

from __future__ import annotations

from typing import Any


class AppException(Exception):
    """携带可公开错误信息的业务异常."""

    code = "application_error"
    status_code = 400

    def __init__(self, message: str) -> None:
        """记录可安全返回给客户端的错误信息."""
        super().__init__(message)
        self.message = message


class ValidationError(AppException):
    """请求内容不符合业务约束."""

    code = "bad_request"
    status_code = 400


class NotFoundError(AppException):
    """请求的资源不存在."""

    code = "not_found"
    status_code = 404


class AuthenticationError(AppException):
    """身份凭证无效或已过期."""

    code = "invalid_api_key"
    status_code = 401


class HealthCheckError(AppException):
    """依赖组件不可用."""

    code = "health_check_failed"
    status_code = 503


class GatewayUnavailableError(AppException):
    """所有账号不可用或上游不可达."""

    status_code = 503

    def __init__(self, code: str, message: str, status: int = 503) -> None:
        """保留原始错误码与 HTTP 状态, 供异常边界渲染."""
        super().__init__(message)
        self.code = code
        self.status_code = status


ANTHROPIC_ERROR_TYPES: dict[str, str] = {
    "server_error": "api_error",
    "service_unavailable": "overloaded_error",
    "rate_limit_error": "rate_limit_error",
    "authentication_error": "authentication_error",
    "invalid_request_error": "invalid_request_error",
    "permission_error": "permission_error",
    "not_found_error": "not_found_error",
}


def anthropic_type(err_type: str) -> str:
    """把 OpenAI 风格错误类型映射为 Anthropic 风格."""
    return ANTHROPIC_ERROR_TYPES.get(err_type, "api_error")


def openai_error_body(
    code: str, message: str, err_type: str, param: str | None = None
) -> dict[str, Any]:
    """构造 OpenAI 风格错误信封, 供 JSON 响应与 SSE 事件共用."""
    error: dict[str, Any] = {"code": code, "message": message, "type": err_type}
    if param:
        error["param"] = param
    return {"error": error}


def anthropic_error_body(err_type: str, message: str) -> dict[str, Any]:
    """构造 Anthropic 风格错误信封, 供 JSON 响应与 SSE 事件共用."""
    return {"type": "error", "error": {"type": err_type, "message": message}}
