"""统一 API 错误响应和业务异常模型。"""

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.api.errors.error_codes import ErrorCode


class ErrorResponse(BaseModel):
    """HTTP 和 SSE 共用的错误负载结构。"""

    model_config = ConfigDict(use_enum_values=True)

    code: ErrorCode
    message: str
    request_id: str
    retryable: bool = False
    stage: str | None = None
    terminal: bool = True
    details: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class AppError(Exception):
    """业务层可主动抛出的、可被 API 层稳定转换的异常。"""

    code: ErrorCode
    message: str
    status_code: int = 500
    retryable: bool = False
    stage: str | None = None
    details: dict[str, Any] | None = None

    def __post_init__(self) -> None:
        if not self.message.strip():
            raise ValueError("业务错误 message 不能为空")
        if not 400 <= self.status_code <= 599:
            raise ValueError("业务错误 status_code 必须位于 400-599")
        Exception.__init__(self, self.message)

    def to_response(self, request_id: str) -> ErrorResponse:
        """把内部异常转换成不暴露实现细节的对外响应。"""

        if not request_id.strip():
            raise ValueError("request_id 不能为空")
        return ErrorResponse(
            code=self.code,
            message=self.message,
            request_id=request_id,
            retryable=self.retryable,
            stage=self.stage,
            details=self.details,
        )
