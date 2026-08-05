"""查询接口请求体定义"""

from pydantic import BaseModel


class QuerySchema(BaseModel):
    """POST /api/query 的请求体"""

    query: str  # 用户自然语言问题