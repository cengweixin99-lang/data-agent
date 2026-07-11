import asyncio

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.column_info import ColumnInfo
from app.prompt.load_prompt import load_prompt

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

MIN_KEYWORDS_FOR_DIRECT_RECALL = 3


def normalize_keywords(keywords: list[str]) -> set[str]:
    return {
        keyword.strip()
        for keyword in keywords
        if isinstance(keyword, str) and keyword.strip()
    }


async def recall_column(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回字段信息", "status": "running"})

    try:
        keywords = state["keywords"]
        query = state["query"]
        column_qdrant_repository = runtime.context["column_qdrant_repository"]
        embedding_client = runtime.context["embedding_client"]

        keywords = normalize_keywords(keywords)
        if len(keywords) < MIN_KEYWORDS_FOR_DIRECT_RECALL:
            prompt = PromptTemplate(
                template=load_prompt("extend_keywords_for_column_recall"),
                input_variables=["query"],
            )
            output_parser = JsonOutputParser()
            chain = prompt | llm | output_parser
            result = await chain.ainvoke({"query": query})
            keywords.update(normalize_keywords(result))
        else:
            logger.info(f"Skip column keyword extension: {list(keywords)}")

        column_infos_map: dict[str, ColumnInfo] = {}
        keyword_list = list(keywords)
        if not keyword_list:
            writer({"type": "progress", "step": "召回字段信息", "status": "success"})
            return {"retrieved_column_infos": []}

        embeddings = await embedding_client.aembed_documents(keyword_list)
        search_results = await asyncio.gather(
            *(column_qdrant_repository.search(embedding=embedding) for embedding in embeddings)
        )
        for current_column_infos in search_results:
            for column_info in current_column_infos:
                if column_info.id not in column_infos_map:
                    column_infos_map[column_info.id] = column_info

        retrieved_column_infos = list(column_infos_map.values())
        logger.info(f"Retrieved column infos: {list(column_infos_map.keys())}")
        writer({"type": "progress", "step": "召回字段信息", "status": "success"})
        return {"retrieved_column_infos": retrieved_column_infos}
    except Exception as e:
        logger.error(f"Recall column info failed: {e}")
        writer({"type": "progress", "step": "召回字段信息", "status": "error"})
        raise
