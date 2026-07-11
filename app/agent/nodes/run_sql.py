from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.sql_security import validate_read_only_sql
from app.agent.state import DataAgentState
from app.core.log import logger


async def run_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "执行SQL", "status": "running"})

    try:
        sql = validate_read_only_sql(state["sql"])
        dw_mysql_repository = runtime.context["dw_mysql_repository"]
        result = await dw_mysql_repository.run_sql(sql)

        logger.info(f"SQL execution result: {result}")
        writer({"type": "progress", "step": "执行SQL", "status": "success"})
        writer({
            "type": "result",
            "data": result,
            "sql": sql,
            "correction_attempts": state.get("correction_attempts", 0),
            "meta": {"row_count": len(result)},
        })
        return {"result_rows": result}
    except Exception as error:
        logger.error(f"SQL execution failed: {error}")
        writer({"type": "progress", "step": "执行SQL", "status": "error"})
        raise