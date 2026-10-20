"""统一业务异常, 请求校验和未知错误响应, 按端点面选择信封。"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from core.exceptions import (
    AppException,
    GatewayUnavailableError,
    anthropic_error_body,
    anthropic_type,
    openai_error_body,
)
from core.logger import logger

# AppException 只带 code 与状态码, HTTP 状态到 OpenAI 风格 type 的稳定映射
_TYPE_BY_STATUS = {
    400: "invalid_request_error",
    401: "authentication_error",
    404: "not_found_error",
    500: "server_error",
    502: "service_unavailable",
    503: "service_unavailable",
}


def _is_anthropic_path(path: str) -> bool:
    """判断端点是否属于 Anthropic 协议面。"""
    return path == "/v1/messages" or path.startswith("/v1/messages/")


def openai_error(
    status: int, code: str, message: str, err_type: str, param: str | None = None
) -> JSONResponse:
    """构造 OpenAI 风格错误响应。"""
    return JSONResponse(
        status_code=status, content=openai_error_body(code, message, err_type, param)
    )


def anthropic_error(status: int, err_type: str, message: str) -> JSONResponse:
    """构造 Anthropic 风格错误响应。"""
    return JSONResponse(status_code=status, content=anthropic_error_body(err_type, message))


def error_for_path(
    path: str, status: int, code: str, message: str, err_type: str
) -> JSONResponse:
    """仅在错误响应边界构造信封, 协议面由请求路径决定。"""
    if _is_anthropic_path(path):
        return anthropic_error(status, anthropic_type(err_type), message)
    return openai_error(status, code, message, err_type)


async def app_error(request: Request, exception: Exception) -> JSONResponse:
    """将已声明业务错误映射到稳定 HTTP 状态。"""
    assert isinstance(exception, AppException)
    return error_for_path(
        request.url.path,
        exception.status_code,
        exception.code,
        exception.message,
        _TYPE_BY_STATUS.get(exception.status_code, "server_error"),
    )


async def validation_error(request: Request, exception: Exception) -> JSONResponse:
    """不返回原始输入值, 避免账号 key 进入参数校验响应。"""
    assert isinstance(exception, RequestValidationError)
    return error_for_path(
        request.url.path, 400, "bad_request", "request body is invalid", "invalid_request_error"
    )


async def http_error(request: Request, exception: Exception) -> JSONResponse:
    """统一处理未匹配路由和不允许的 HTTP 方法。"""
    assert isinstance(exception, HTTPException)
    if exception.status_code == 404:
        return error_for_path(
            request.url.path, 404, "not_found", str(exception.detail), "not_found_error"
        )
    code = "method_not_allowed" if exception.status_code == 405 else "bad_request"
    return error_for_path(
        request.url.path,
        exception.status_code,
        code,
        str(exception.detail),
        "invalid_request_error",
    )


async def internal_error(request: Request, exception: Exception) -> JSONResponse:
    """记录完整服务端调用栈, 客户端只接收固定消息。"""
    logger.exception("unhandled error on %s", request.url.path)
    return error_for_path(
        request.url.path, 500, "internal_error", "internal server error", "server_error"
    )


def register_exception_handlers(application: FastAPI) -> None:
    """在启动边界注册全部异常处理。"""
    application.add_exception_handler(AppException, app_error)
    application.add_exception_handler(GatewayUnavailableError, app_error)
    application.add_exception_handler(RequestValidationError, validation_error)
    application.add_exception_handler(HTTPException, http_error)
    application.add_exception_handler(Exception, internal_error)
