import yaml

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState, MetricInfoState
from app.core.log import logger
from app.prompt.load_prompt import load_prompt

from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

MAX_METRICS_FOR_DIRECT_SQL = 2


async def filter_metric(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "过滤指标信息", "status": "running"})
    try:
        query = state["query"]
        metric_infos: list[MetricInfoState] = state["metric_infos"]
        if len(metric_infos) <= MAX_METRICS_FOR_DIRECT_SQL:
            logger.info(f"Small metric candidate set, skip metric filter: {[metric_info['name'] for metric_info in metric_infos]}")
            writer({"type": "progress", "step": "过滤指标信息", "status": "success"})
            return {"metric_infos": metric_infos}

        prompt = PromptTemplate(
            template=load_prompt("filter_metric_info"),
            input_variables=["query", "metric_infos"],
        )
        output_parser = JsonOutputParser()
        chain = prompt | llm | output_parser

        result = await chain.ainvoke(
            {"query": query, "metric_infos": yaml.dump(metric_infos, allow_unicode=True, sort_keys=False)}
        )
        filtered_metric_infos: list[MetricInfoState] = [
            metric_info for metric_info in metric_infos if metric_info["name"] in result
        ]
        logger.info(f"Filtered metric infos: {[metric_info['name'] for metric_info in filtered_metric_infos]}")
        writer({"type": "progress", "step": "过滤指标信息", "status": "success"})
        return {"metric_infos": filtered_metric_infos}
    except Exception as e:
        logger.error(f"Filter metric info failed: {e}")
        writer({"type": "progress", "step": "过滤指标信息", "status": "error"})
        raise
