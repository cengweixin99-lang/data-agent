import json

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import PromptTemplate
from langgraph.runtime import Runtime

from app.agent.context import DataAgentContext
from app.agent.llm import llm
from app.agent.state import DataAgentState
from app.agent.streaming import stream_text_chain
from app.core.log import logger
from app.prompt.load_prompt import load_prompt


MAX_PREVIEW_ROWS = 20


def _format_rows(rows: list[dict]) -> str:
    preview_rows = rows[:MAX_PREVIEW_ROWS]
    payload = {
        "row_count": len(rows),
        "preview_rows": preview_rows,
    }
    return json.dumps(payload, ensure_ascii=False, default=str)


async def explain_result(state: DataAgentState, runtime: Runtime[DataAgentContext]):
    writer = runtime.stream_writer
    writer({"type": "progress", "step": "解读查询结果", "status": "running"})

    try:
        rows = state.get("result_rows") or []
        if not rows:
            analysis = "本次查询没有返回数据，建议检查筛选条件或扩大查询范围。"
            writer({"type": "progress", "step": "解读查询结果", "status": "success"})
            return {"result_analysis": analysis}

        prompt = PromptTemplate(
            template=load_prompt("explain_result"),
            input_variables=["query", "sql", "result_rows"],
        )
        chain = prompt | llm | StrOutputParser()
        analysis = await stream_text_chain(
            chain,
            {
                "query": state["query"],
                "sql": state.get("sql", ""),
                "result_rows": _format_rows(rows),
            },
            runtime,
        )

        writer({"type": "progress", "step": "解读查询结果", "status": "success"})
        return {"result_analysis": analysis}
    except Exception as error:
        logger.warning(f"Explain result failed: {error}")
        writer({"type": "progress", "step": "解读查询结果", "status": "error"})
        return {"result_analysis": "查询结果已返回，但结果解读生成失败。"}