from contextvars import ContextVar
from functools import wraps
from itertools import count
from time import perf_counter
from typing import Any, Awaitable, Callable

_current_trace_id: ContextVar[str | None] = ContextVar("current_trace_id", default=None)
_current_node_name: ContextVar[str | None] = ContextVar("current_node_name", default=None)
_trace_counter = count(1)

_NODE_TITLES = {
    "extract_keywords": "抽取关键词",
    "recall_column": "召回字段信息",
    "recall_value": "召回字段取值",
    "recall_metric": "召回指标信息",
    "merge_retrieved_info": "合并召回信息",
    "filter_metric": "过滤指标信息",
    "filter_table": "过滤表信息",
    "add_extra_context": "补充上下文",
    "generate_sql": "生成 SQL",
    "validate_sql": "校验 SQL",
    "correct_sql": "修正 SQL",
    "run_sql": "执行 SQL",
    "explain_result": "解读结果",
    "sql_failure": "SQL 验证失败",
}


def node_title(name: str) -> str:
    return _NODE_TITLES.get(name, name)


def current_trace_id() -> str | None:
    return _current_trace_id.get()


def current_node_name() -> str | None:
    return _current_node_name.get()


def summarize_update(update: dict[str, Any] | None) -> dict[str, int]:
    if not update:
        return {}

    summary: dict[str, int] = {}
    list_fields = {
        "retrieved_column_infos": "retrieved_columns",
        "retrieved_value_infos": "retrieved_values",
        "retrieved_metric_infos": "retrieved_metrics",
        "table_infos": "tables",
        "metric_infos": "metrics",
        "keywords": "keywords",
    }
    for field, name in list_fields.items():
        value = update.get(field)
        if isinstance(value, list):
            summary[name] = len(value)

    if isinstance(update.get("correction_attempts"), int):
        summary["correction_attempts"] = update["correction_attempts"]
    if update.get("skip_reason"):
        summary["skipped"] = 1
    return summary


def _name_of(item: Any) -> str | None:
    if isinstance(item, dict):
        return item.get("name") or item.get("id")
    return getattr(item, "name", None) or getattr(item, "id", None)


def _preview_names(items: list[Any], limit: int = 6) -> str:
    names = [name for item in items if (name := _name_of(item))]
    if not names:
        return ""
    preview = "、".join(names[:limit])
    if len(names) > limit:
        preview += f" 等 {len(names)} 个"
    return preview


def summarize_trace_content(update: dict[str, Any] | None) -> str:
    if not update:
        return "节点执行完成。"

    lines: list[str] = []
    if update.get("skip_reason"):
        lines.append(f"跳过：{update['skip_reason']}")
    if keywords := update.get("keywords"):
        lines.append(f"关键词：{'、'.join(map(str, keywords[:8]))}")
    if columns := update.get("retrieved_column_infos"):
        lines.append(f"召回字段：{len(columns)} 个 {_preview_names(columns)}".strip())
    if values := update.get("retrieved_value_infos"):
        lines.append(f"召回取值：{len(values)} 个 {_preview_names(values)}".strip())
    if metrics := update.get("retrieved_metric_infos"):
        lines.append(f"召回指标：{len(metrics)} 个 {_preview_names(metrics)}".strip())
    if tables := update.get("table_infos"):
        lines.append(f"候选表：{len(tables)} 张 {_preview_names(tables)}".strip())
    if metric_infos := update.get("metric_infos"):
        lines.append(f"候选指标：{len(metric_infos)} 个 {_preview_names(metric_infos)}".strip())
    if sql := update.get("sql"):
        lines.append(f"SQL：{sql}")
    if update.get("error"):
        lines.append(f"错误：{update['error']}")
    if update.get("result_rows") is not None:
        lines.append(f"查询结果：{len(update['result_rows'])} 行")
    if update.get("result_analysis"):
        lines.append(str(update["result_analysis"]))
    if update.get("date_info"):
        lines.append("已补充日期上下文。")
    if update.get("db_info"):
        lines.append("已补充数据库上下文。")

    return "\n".join(lines) if lines else "节点执行完成。"


def _write_trace(runtime: Any, payload: dict[str, Any]) -> None:
    runtime.stream_writer({"type": "trace", **payload})


def instrument_node(name: str, node: Callable[..., Awaitable[dict[str, Any]]]):
    @wraps(node)
    async def wrapped(state: dict[str, Any], runtime: Any):
        trace_id = f"{name}-{next(_trace_counter)}"
        title = node_title(name)
        token_id = _current_trace_id.set(trace_id)
        token_node = _current_node_name.set(name)

        runtime.stream_writer({
            "type": "telemetry",
            "node": name,
            "status": "running",
            "phase": "start",
            "metrics": {},
        })
        _write_trace(runtime, {
            "event": "node_start",
            "id": trace_id,
            "node": name,
            "title": title,
            "status": "running",
            "content": f"开始{title}",
            "metrics": {},
        })

        started = perf_counter()
        try:
            update = await node(state, runtime)
            duration_ms = round((perf_counter() - started) * 1000, 2)
            metrics = summarize_update(update)
            content = summarize_trace_content(update)
            runtime.stream_writer({
                "type": "telemetry",
                "node": name,
                "status": "success",
                "phase": "end",
                "duration_ms": duration_ms,
                "metrics": metrics,
            })
            _write_trace(runtime, {
                "event": "node_end",
                "id": trace_id,
                "node": name,
                "title": title,
                "status": "success",
                "duration_ms": duration_ms,
                "metrics": metrics,
                "content": content,
            })
            return update
        except Exception as exc:
            duration_ms = round((perf_counter() - started) * 1000, 2)
            runtime.stream_writer({
                "type": "telemetry",
                "node": name,
                "status": "error",
                "phase": "end",
                "duration_ms": duration_ms,
                "metrics": {},
            })
            _write_trace(runtime, {
                "event": "node_error",
                "id": trace_id,
                "node": name,
                "title": title,
                "status": "error",
                "duration_ms": duration_ms,
                "metrics": {},
                "content": str(exc),
            })
            raise
        finally:
            _current_trace_id.reset(token_id)
            _current_node_name.reset(token_node)

    return wrapped
