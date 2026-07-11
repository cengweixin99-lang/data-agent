from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger


async def sql_failure(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "SQL验证", "status": "running"})

    try:
        error = state.get("error") or "SQL验证失败"
        attempts = state.get("correction_attempts", 0)
        logger.error(f"SQL修正次数达到上限：{attempts}次; 错误：{error}")
        writer({"type": "progress", "step": "SQL验证", "status": "error"})
        writer({
            "type": "error",
            "message": f"SQL验证在{attempts}次修正后仍失败：{error}",
        })
        return {}
    except Exception as e:
        logger.error(f"SQL验证失败：{e}")
        writer({"type": "progress", "step": "SQL验证", "status": "error"})
        raise