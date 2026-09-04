"""FastAPI 异常到统一 API 错误响应的转换。"""

from typing import Any

from fastapi import HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.errors.error_codes import ErrorCode
from app.api.errors.error_response import AppError, ErrorResponse
from app.core.context import request_id_ctx_var


def _request_id() -> str:
    """读取当前请求 ID；异常处理本身不能因为上下文缺失而再次失败。"""

    return str(request_id_ctx_var.get())


def _json_response(error: ErrorResponse, status_code: int) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error.model_dump(mode="json"))


def _validation_details(exc: RequestValidationError) -> list[dict[str, Any]]:
    """保留字段定位和错误类型，避免把原始输入值回传给客户端。"""

    return [
        {
            "location": list(item.get("loc", ())),
            "type": item.get("type", "validation_error"),
            "message": item.get("msg", "请求参数不合法"),
        }
        for item in exc.errors()
    ]


async def request_validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """把 FastAPI 默认 422 错误转换为项目错误协议。"""

    error = ErrorResponse(
        code=ErrorCode.REQUEST_BODY_INVALID,
        message="请求参数不合法",
        request_id=_request_id(),
        retryable=False,
        stage="request_validation",
        details={"errors": _validation_details(exc)},
    )
    return _json_response(error, status_code=422)


async def app_error_exception_handler(request: Request, exc: AppError) -> JSONResponse:
    """把业务层主动抛出的 AppError 转成统一 HTTP 响应。"""

    return _json_response(exc.to_response(_request_id()), status_code=exc.status_code)


async def http_exception_handler(request: Request, exc: HTTPException) -> JSONResponse:
    """兼容 FastAPI/Starlette 异常，同时保持错误字段稳定。"""

    detail = exc.detail if isinstance(exc.detail, str) else "请求处理失败"
    error = ErrorResponse(
        code=ErrorCode.HTTP_ERROR,
        message=detail,
        request_id=_request_id(),
        retryable=500 <= exc.status_code < 600,
        stage="http",
    )
    return _json_response(error, status_code=exc.status_code)


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """兜底返回安全文案，内部异常详情只应写入服务端日志。"""

    error = ErrorResponse(
        code=ErrorCode.INTERNAL_ERROR,
        message="服务器内部错误",
        request_id=_request_id(),
        retryable=True,
        stage="internal",
    )
    return _json_response(error, status_code=500)
