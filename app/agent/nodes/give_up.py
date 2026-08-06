"""SQL 多次修正仍失败后的放弃节点"""

from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState


async def give_up(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    """输出结构化错误消息并结束流程"""
    runtime.stream_writer(
        {"type": "error", "message": "SQL 多次修正仍无法通过校验，请换一种问法"}
    )
    return {}