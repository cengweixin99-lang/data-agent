from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.sql_context import format_extra_context, format_metric_context, format_table_context
from app.agent.state import DataAgentState
from app.agent.streaming import stream_text_chain
from app.core.log import logger
from app.prompt.load_prompt import load_prompt

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime


async def correct_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "校正SQL", "status": "running"})

    try:
        table_infos = state["table_infos"]
        metric_infos = state["metric_infos"]
        date_info = state["date_info"]
        db_info = state["db_info"]
        query = state["query"]
        sql = state["sql"]
        error = state["error"]
        date_text, db_text = format_extra_context(date_info, db_info)

        prompt = PromptTemplate(
            template=load_prompt("correct_sql"),
            input_variables=["table_infos", "metric_infos", "date_info", "db_info", "query", "sql", "error"],
        )
        output_parser = StrOutputParser()
        chain = prompt | llm | output_parser

        result = await stream_text_chain(
            chain,
            {
                "table_infos": format_table_context(table_infos),
                "metric_infos": format_metric_context(metric_infos),
                "date_info": date_text,
                "db_info": db_text,
                "query": query,
                "sql": sql,
                "error": error,
            },
            runtime,
        )

        logger.info(f"Corrected SQL: {result}")
        writer({"type": "progress", "step": "校正SQL", "status": "success"})
        return {"sql": result, "correction_attempts": state.get("correction_attempts", 0) + 1}
    except Exception as e:
        logger.error(f"Correct SQL failed: {e}")
        writer({"type": "progress", "step": "校正SQL", "status": "error"})
        raise
