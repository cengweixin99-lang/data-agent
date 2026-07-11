from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.sql_security import validate_read_only_sql
from app.agent.state import DataAgentState
from app.core.log import logger


async def validate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "校验SQL", "status": "running"})

    try:
        normalized_sql = validate_read_only_sql(state["sql"])
        dw_mysql_repository = runtime.context["dw_mysql_repository"]
        await dw_mysql_repository.validate_sql(normalized_sql)
        logger.info("SQL validation succeeded")
        writer({"type": "progress", "step": "校验SQL", "status": "success"})
        return {"sql": normalized_sql, "error": None}
    except Exception as error:
        logger.error(f"SQL validation failed: {error}")
        writer({"type": "progress", "step": "校验SQL", "status": "error"})
        return {"error": str(error)}