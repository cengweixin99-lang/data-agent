import yaml

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState, TableInfoState
from app.core.log import logger
from app.prompt.load_prompt import load_prompt

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

MAX_TABLES_FOR_DIRECT_SQL = 3


async def filter_table(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "过滤表信息", "status": "running"})

    try:
        query = state["query"]
        table_infos: list[TableInfoState] = state["table_infos"]

        if len(table_infos) <= MAX_TABLES_FOR_DIRECT_SQL:
            logger.info(f"Small table candidate set, skip table filter: {[table_info['name'] for table_info in table_infos]}")
            writer({"type": "progress", "step": "过滤表信息", "status": "success"})
            return {"table_infos": table_infos}

        prompt = PromptTemplate(
            template=load_prompt("filter_table_info"),
            input_variables=["query", "table_infos"],
        )
        output_parser = JsonOutputParser()
        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
            {"query": query, "table_infos": yaml.dump(table_infos, allow_unicode=True, sort_keys=False)}
        )

        filtered_table_infos: list[TableInfoState] = []
        for table_info in table_infos:
            if table_info["name"] in result:
                table_info["columns"] = [
                    column_info
                    for column_info in table_info["columns"]
                    if column_info["name"] in result[table_info["name"]]
                ]
                filtered_table_infos.append(table_info)

        logger.info(f"Filtered table infos: {[table_info['name'] for table_info in filtered_table_infos]}")
        writer({"type": "progress", "step": "过滤表信息", "status": "success"})
        return {"table_infos": filtered_table_infos}
    except Exception as e:
        logger.error(f"Filter table info failed: {e}")
        writer({"type": "progress", "step": "过滤表信息", "status": "error"})
        raise
