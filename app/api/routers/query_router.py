"""查询接口路由（第 5 章先演示 SSE，第 23 章接入完整问数服务）"""

import asyncio
import json

from fastapi import APIRouter
from starlette.responses import StreamingResponse

from app.api.schemas.query_schema import QuerySchema

query_router = APIRouter()


@query_router.post("/api/query")
async def query_handler(query: QuerySchema):
    """接收用户问题，先返回一条 SSE 演示流（第 23 章替换为真实问数）"""

    async def fake_stream():
        """演示 SSE 帧：模拟 3 步节点进度 + 一个结果"""
        steps = ["抽取关键词", "召回字段信息", "生成SQL"]
        for step in steps:
            # 每帧格式：data: {json}\n\n
            yield f"data: {json.dumps({'type': 'progress', 'step': step, 'status': 'running'}, ensure_ascii=False)}\n\n"
            await asyncio.sleep(0.5)  # 模拟每个节点耗时
        yield f"data: {json.dumps({'type': 'result', 'data': [{'region': '华北', 'amount': 123456}]}, ensure_ascii=False)}\n\n"

    return StreamingResponse(fake_stream(), media_type="text/event-stream")