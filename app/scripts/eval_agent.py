import argparse
import asyncio
import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import perf_counter
from typing import Any

import yaml

from app.agent.context import DataAgentContext
from app.agent.graph import graph
from app.agent.state import DataAgentState
from app.clients.embedding_client_manager import embedding_client_manager
from app.clients.es_client_manager import es_client_manager
from app.clients.mysql_client_manager import dw_mysql_client_manager, meta_mysql_client_manager
from app.clients.qdrant_client_manager import qdrant_client_manager
from app.repositories.es.value_es_repository import ValueESRepository
from app.repositories.mysql.dw.dw_mysql_repository import DWMySQLRepository
from app.repositories.mysql.meta.meta_mysql_repository import MetaMySQLRepository
from app.repositories.qdrant.column_qdrant_repository import ColumnQdrantRepository
from app.repositories.qdrant.metric_qdrant_repository import MetricQdrantRepository


@dataclass
class EvalCase:
    id: str
    question: str
    expected_tables: list[str]
    expected_columns: list[str]
    tags: list[str]
    checks: dict[str, Any]


def _load_cases(path: Path) -> list[EvalCase]:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases = []
    for raw in data.get("cases", []):
        cases.append(
            EvalCase(
                id=raw["id"],
                question=raw["question"],
                expected_tables=list(raw.get("expected_tables", [])),
                expected_columns=list(raw.get("expected_columns", [])),
                tags=list(raw.get("tags", [])),
                checks=dict(raw.get("checks", {})),
            )
        )
    return cases


def _contains_all(sql: str, expected: list[str]) -> tuple[bool, list[str], list[str]]:
    normalized = sql.lower()
    hit = [item for item in expected if item.lower() in normalized]
    missing = [item for item in expected if item.lower() not in normalized]
    return len(missing) == 0, hit, missing


def _safe_row_count(rows: Any) -> int:
    return len(rows) if isinstance(rows, list) else 0


def _run_semantic_checks(rows: list[Any], checks: dict[str, Any]) -> tuple[bool, list[dict[str, Any]]]:
    failures: list[dict[str, Any]] = []

    max_rows_per_group = checks.get("max_rows_per_group")
    if max_rows_per_group:
        group_column = max_rows_per_group.get("group_column")
        max_rows = int(max_rows_per_group.get("max_rows", 0))
        counts: dict[Any, int] = {}
        if group_column and max_rows > 0:
            for row in rows:
                if not isinstance(row, dict):
                    continue
                group_value = row.get(group_column)
                counts[group_value] = counts.get(group_value, 0) + 1
            overflow = {
                str(group): count
                for group, count in counts.items()
                if count > max_rows
            }
            if overflow:
                failures.append({
                    "check": "max_rows_per_group",
                    "group_column": group_column,
                    "max_rows": max_rows,
                    "overflow": overflow,
                })

    return len(failures) == 0, failures


def _extract_node_timings(traces: list[dict[str, Any]]) -> tuple[dict[str, float], list[dict[str, Any]], list[dict[str, Any]]]:
    node_timings: dict[str, float] = {}
    node_runs: list[dict[str, Any]] = []

    for trace in traces:
        if trace.get("event") not in {"node_end", "node_error"}:
            continue
        node = trace.get("node")
        duration_ms = trace.get("duration_ms")
        if not node or duration_ms is None:
            continue

        duration = round(float(duration_ms), 2)
        node_timings[node] = round(node_timings.get(node, 0.0) + duration, 2)
        node_runs.append({
            "id": trace.get("id"),
            "node": node,
            "title": trace.get("title") or node,
            "status": trace.get("status"),
            "duration_ms": duration,
            "metrics": trace.get("metrics") or {},
        })

    slowest_nodes = [
        {"node": node, "duration_ms": duration}
        for node, duration in sorted(node_timings.items(), key=lambda item: item[1], reverse=True)
    ]
    return node_timings, node_runs, slowest_nodes


async def _run_case(case: EvalCase, context: DataAgentContext) -> dict[str, Any]:
    started = perf_counter()
    sql = ""
    rows: list[Any] = []
    error = None
    traces: list[dict[str, Any]] = []
    correction_attempts = 0

    async for chunk in graph.astream(
        input=DataAgentState(query=case.question),
        context=context,
        stream_mode="custom",
    ):
        if not isinstance(chunk, dict):
            continue
        event_type = chunk.get("type")
        if event_type == "trace":
            traces.append(chunk)
        elif event_type == "result":
            sql = chunk.get("sql") or ""
            rows = chunk.get("data") or []
            correction_attempts = chunk.get("correction_attempts", 0)
        elif event_type == "error":
            error = chunk.get("message") or chunk.get("error") or "unknown error"

    elapsed_ms = round((perf_counter() - started) * 1000, 2)
    table_ok, hit_tables, missing_tables = _contains_all(sql, case.expected_tables)
    column_ok, hit_columns, missing_columns = _contains_all(sql, case.expected_columns)
    row_count = _safe_row_count(rows)
    semantic_ok, semantic_failures = _run_semantic_checks(rows, case.checks)
    node_timings, node_runs, slowest_nodes = _extract_node_timings(traces)

    return {
        "id": case.id,
        "question": case.question,
        "tags": case.tags,
        "success": error is None and bool(sql) and semantic_ok,
        "error": error,
        "sql": sql,
        "row_count": row_count,
        "non_empty_result": row_count > 0,
        "semantic_check": semantic_ok,
        "semantic_failures": semantic_failures,
        "elapsed_ms": elapsed_ms,
        "correction_attempts": correction_attempts,
        "expected_tables": case.expected_tables,
        "hit_tables": hit_tables,
        "missing_tables": missing_tables,
        "table_hit": table_ok,
        "expected_columns": case.expected_columns,
        "hit_columns": hit_columns,
        "missing_columns": missing_columns,
        "column_hit": column_ok,
        "trace_count": len(traces),
        "node_timings": node_timings,
        "node_runs": node_runs,
        "slowest_nodes": slowest_nodes[:5],
    }


def _summarize(results: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(results)
    if total == 0:
        return {"total": 0}

    def ratio(key: str) -> float:
        return round(sum(1 for item in results if item.get(key)) / total, 4)

    node_totals: dict[str, float] = {}
    for result in results:
        for node, duration in result.get("node_timings", {}).items():
            node_totals[node] = round(node_totals.get(node, 0.0) + float(duration), 2)

    avg_node_timings = {
        node: round(duration / total, 2)
        for node, duration in sorted(node_totals.items(), key=lambda item: item[1], reverse=True)
    }

    return {
        "total": total,
        "success_rate": ratio("success"),
        "non_empty_rate": ratio("non_empty_result"),
        "table_hit_rate": ratio("table_hit"),
        "column_hit_rate": ratio("column_hit"),
        "semantic_check_rate": ratio("semantic_check"),
        "avg_elapsed_ms": round(sum(item["elapsed_ms"] for item in results) / total, 2),
        "avg_correction_attempts": round(sum(item["correction_attempts"] for item in results) / total, 2),
        "avg_node_timings": avg_node_timings,
        "slowest_nodes": [
            {"node": node, "avg_duration_ms": duration}
            for node, duration in list(avg_node_timings.items())[:5]
        ],
    }


async def run_eval(cases_path: Path, output_path: Path, limit: int | None) -> dict[str, Any]:
    cases = _load_cases(cases_path)
    if limit is not None:
        cases = cases[:limit]

    qdrant_client_manager.init()
    embedding_client_manager.init()
    es_client_manager.init()
    meta_mysql_client_manager.init()
    dw_mysql_client_manager.init()

    try:
        async with (
            meta_mysql_client_manager.session_factory() as meta_session,
            dw_mysql_client_manager.session_factory() as dw_session,
        ):
            context = DataAgentContext(
                column_qdrant_repository=ColumnQdrantRepository(qdrant_client_manager.client),
                embedding_client=embedding_client_manager.client,
                metric_qdrant_repository=MetricQdrantRepository(qdrant_client_manager.client),
                value_es_repository=ValueESRepository(es_client_manager.client),
                meta_mysql_repository=MetaMySQLRepository(meta_session),
                dw_mysql_repository=DWMySQLRepository(dw_session),
            )

            results = []
            for index, case in enumerate(cases, start=1):
                print(f"[{index}/{len(cases)}] {case.id}: {case.question}")
                result = await _run_case(case, context)
                results.append(result)
                status = "OK" if result["success"] else "FAIL"
                print(
                    f"  {status} table_hit={result['table_hit']} "
                    f"column_hit={result['column_hit']} rows={result['row_count']} "
                    f"elapsed={result['elapsed_ms']}ms"
                )
                if result["slowest_nodes"]:
                    slowest = ", ".join(
                        f"{item['node']}={item['duration_ms']}ms"
                        for item in result["slowest_nodes"][:3]
                    )
                    print(f"  slowest: {slowest}")
    finally:
        await qdrant_client_manager.close()
        await es_client_manager.close()
        await meta_mysql_client_manager.close()
        await dw_mysql_client_manager.close()

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "cases_path": str(cases_path),
        "summary": _summarize(results),
        "results": results,
    }

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    latest_path = output_path.parent / "latest.json"
    if latest_path != output_path:
        latest_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Data Agent evaluation cases.")
    parser.add_argument("-c", "--cases", default="eval_cases.yaml", help="Path to eval cases yaml.")
    parser.add_argument("-o", "--output", default=None, help="Path to output report json.")
    parser.add_argument("--limit", type=int, default=None, help="Only run the first N cases.")
    args = parser.parse_args()

    cases_path = Path(args.cases)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = Path(args.output) if args.output else Path("eval_reports") / f"eval_{timestamp}.json"

    report = asyncio.run(run_eval(cases_path, output_path, args.limit))
    print("\nSummary:")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"Report saved to: {output_path}")


if __name__ == "__main__":
    main()
