from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.sql_context import format_extra_context, format_metric_context, format_table_context
from app.agent.state import DataAgentState
from app.agent.streaming import stream_text_chain
from app.agent.sql_templates import try_generate_template_sql
from app.core.log import logger
from app.prompt.load_prompt import load_prompt

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime


async def generate_sql(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "生成SQL语句", "status": "running"})

    try:
        table_infos = state["table_infos"]
        metric_infos = state["metric_infos"]
        date_info = state["date_info"]
        db_info = state["db_info"]
        query = state["query"]

        template_sql = try_generate_template_sql(query)
        if template_sql:
            logger.info(f"Generated SQL from template: {template_sql}")
            writer({"type": "progress", "step": "生成SQL语句", "status": "success"})
            return {"sql": template_sql}
        date_text, db_text = format_extra_context(date_info, db_info)

        prompt = PromptTemplate(
            template=load_prompt("generate_sql"),
            input_variables=["table_infos", "metric_infos", "date_info", "db_info", "query"],
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
            },
            runtime,
        )

        logger.info(f"Generated SQL: {result}")
        writer({"type": "progress", "step": "生成SQL语句", "status": "success"})
        return {"sql": result}
    except Exception as e:
        logger.error(f"Generate SQL failed: {e}")
        writer({"type": "progress", "step": "生成SQL语句", "status": "error"})
        raise
