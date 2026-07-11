import asyncio

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.core.log import logger
from app.entities.value_info import ValueInfo
from app.prompt.load_prompt import load_prompt

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

GROUP_QUERY_MARKERS = ("各", "每", "不同", "分别", "排行", "排名", "分布", "趋势")
VALUE_HINTS = (
    "华北", "华东", "华南", "华中", "东北", "西北", "西南",
    "男", "女", "普通", "银牌", "金牌", "钻石",
    "电子", "服饰", "食品", "家电", "图书", "运动",
)


def explicit_value_hints(query: str) -> list[str]:
    return [value for value in VALUE_HINTS if value in query]


def should_skip_value_recall(query: str) -> bool:
    if explicit_value_hints(query):
        return False
    return any(marker in query for marker in GROUP_QUERY_MARKERS)


def normalize_keywords(keywords: list[str]) -> set[str]:
    return {
        keyword.strip()
        for keyword in keywords
        if isinstance(keyword, str) and keyword.strip()
    }


async def recall_value(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "召回字段取值", "status": "running"})
    try:
        query = state["query"]
        keywords = state["keywords"]
        value_es_repository = runtime.context["value_es_repository"]

        if should_skip_value_recall(query):
            reason = "分组/排行类问题无明确枚举过滤值，跳过字段取值召回"
            logger.info(reason)
            writer({"type": "progress", "step": "召回字段取值", "status": "success"})
            return {"retrieved_value_infos": [], "skip_reason": reason}

        value_keywords = explicit_value_hints(query)
        if value_keywords:
            logger.info(f"Use explicit value hints for value recall: {value_keywords}")
        else:
            prompt = PromptTemplate(
                template=load_prompt("extend_keywords_for_value_recall"),
                input_variables=["query"],
            )
            out_parser = JsonOutputParser()
            chain = prompt | llm | out_parser
            result = await chain.ainvoke({"query": query})
            value_keywords = list(normalize_keywords(keywords).union(normalize_keywords(result)))

        value_infos_map: dict[str, ValueInfo] = {}
        search_results = await asyncio.gather(
            *(value_es_repository.search(keyword) for keyword in value_keywords)
        )
        for current_value_infos in search_results:
            for current_value_info in current_value_infos:
                if current_value_info.id not in value_infos_map:
                    value_infos_map[current_value_info.id] = current_value_info

        retrieved_value_infos: list[ValueInfo] = list(value_infos_map.values())
        logger.info(f"Retrieved value infos: {list(value_infos_map.keys())}")
        writer({"type": "progress", "step": "召回字段取值", "status": "success"})
        return {"retrieved_value_infos": retrieved_value_infos}
    except Exception as e:
        logger.error(f"Recall value info failed: {e}")
        writer({"type": "progress", "step": "召回字段取值", "status": "error"})
        raise
