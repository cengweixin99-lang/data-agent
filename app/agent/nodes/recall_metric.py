import asyncio

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.metric_info import MetricInfo
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


async def recall_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回指标信息", "status": "running"})

    try:
        query = state["query"]
        keywords = state["keywords"]
        embedding_client = runtime.context["embedding_client"]
        metric_qdrant_repository = runtime.context["metric_qdrant_repository"]

        keywords = normalize_keywords(keywords)
        if len(keywords) < MIN_KEYWORDS_FOR_DIRECT_RECALL:
            prompt = PromptTemplate(
                template=load_prompt("extend_keywords_for_metric_recall"),
                input_variables=["query"],
            )
            output_parser = JsonOutputParser()
            chain = prompt | llm | output_parser
            result = await chain.ainvoke({"query": query})
            keywords.update(normalize_keywords(result))
        else:
            logger.info(f"Skip metric keyword extension: {list(keywords)}")

        metric_infos_map: dict[str, MetricInfo] = {}
        keyword_list = list(keywords)
        if not keyword_list:
            writer({"type": "progress", "step": "召回指标信息", "status": "success"})
            return {"retrieved_metric_infos": []}

        embeddings = await embedding_client.aembed_documents(keyword_list)
        search_results = await asyncio.gather(
            *(metric_qdrant_repository.search(embedding=embedding) for embedding in embeddings)
        )
        for current_metric_infos in search_results:
            for metric_info in current_metric_infos:
                if metric_info.id not in metric_infos_map:
                    metric_infos_map[metric_info.id] = metric_info

        retrieved_metric_infos = list(metric_infos_map.values())
        logger.info(f"Retrieved metric infos: {list(metric_infos_map.keys())}")
        writer({"type": "progress", "step": "召回指标信息", "status": "success"})
        return {"retrieved_metric_infos": retrieved_metric_infos}
    except Exception as e:
        logger.error(f"Recall metric info failed: {e}")
        writer({"type": "progress", "step": "召回指标信息", "status": "error"})
        raise
