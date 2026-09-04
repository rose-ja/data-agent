"""查询接口请求体定义"""

from pydantic import BaseModel, ConfigDict, Field, field_validator


class QuerySchema(BaseModel):
    """POST /api/query 的请求体"""

    # 限制输入规模，避免空问题或超长问题进入模型和检索链路。
    query: str = Field(..., min_length=1, max_length=2000)

    # 请求体只允许声明接口已知字段，避免客户端悄悄传入未处理参数。
    model_config = ConfigDict(extra="forbid")

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        """去除首尾空白，并拒绝看似有值但实际为空的输入。"""

        normalized = value.strip()
        if not normalized:
            raise ValueError("query 不能是空字符串或仅包含空白字符")
        return normalized
