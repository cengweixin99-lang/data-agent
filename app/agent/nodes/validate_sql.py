from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.state import DataAgentState
from app.core.log import logger

async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "校验SQL", "status": "running"})

    try:
        sql = state["sql"]
        dw_mysql_repository = runtime.context["dw_mysql_repository"]
        try:
            await dw_mysql_repository.validate_sql(sql)
            logger.info("SQL语法正确")
            writer({"type": "progress", "step": "校验SQL", "status": "success"})
            return {"error": None}
        except Exception as e:
            logger.error(f"SQL语法错误: {e}")
            writer({"type": "progress", "step": "校验SQL", "status": "success"})
            return {"error": str(e)}
    except Exception as e:
        logger.error(f"SQL语法错误: {e}")
        writer({"type": "progress", "step": "校验SQL", "status": "error"})
        raise
