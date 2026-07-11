from typing import Any


def _compact_values(values: list[Any] | None, limit: int = 5) -> str:
    if not values:
        return ""
    compacted = [str(value).strip() for value in values if value is not None and str(value).strip()]
    if not compacted:
        return ""
    head = compacted[:limit]
    suffix = f", ...(+{len(compacted) - limit})" if len(compacted) > limit else ""
    return ", ".join(head) + suffix


def _format_column(column: dict[str, Any]) -> str:
    name = column.get("name", "")
    details = _compact_values([column.get("type"), column.get("role")], limit=2)
    line = f"  - {name}"
    if details:
        line += f" ({details})"

    extras: list[str] = []
    if description := column.get("description"):
        extras.append(str(description))
    if alias := _compact_values(column.get("alias"), limit=4):
        extras.append(f"alias: {alias}")
    if examples := _compact_values(column.get("examples"), limit=3):
        extras.append(f"examples: {examples}")
    if extras:
        line += ": " + "; ".join(extras)
    return line


def format_table_context(table_infos: list[dict[str, Any]]) -> str:
    if not table_infos:
        return "No candidate tables."

    lines: list[str] = []
    for table in table_infos:
        header = f"Table {table.get('name', '')}"
        table_details = _compact_values([table.get("role"), table.get("description")], limit=2)
        if table_details:
            header += f": {table_details}"
        lines.append(header)
        for column in table.get("columns", []):
            lines.append(_format_column(column))
    return "\n".join(lines)


def format_metric_context(metric_infos: list[dict[str, Any]]) -> str:
    if not metric_infos:
        return "No candidate metrics."

    lines: list[str] = []
    for metric in metric_infos:
        line = f"- {metric.get('name', '')}"
        extras: list[str] = []
        if description := metric.get("description"):
            extras.append(str(description))
        if relevant_columns := _compact_values(metric.get("relevant_columns"), limit=8):
            extras.append(f"columns: {relevant_columns}")
        if alias := _compact_values(metric.get("alias"), limit=5):
            extras.append(f"alias: {alias}")
        if extras:
            line += ": " + "; ".join(extras)
        lines.append(line)
    return "\n".join(lines)


def format_extra_context(date_info: dict[str, Any], db_info: dict[str, Any]) -> tuple[str, str]:
    date_text = ", ".join(f"{key}: {value}" for key, value in date_info.items()) if date_info else ""
    db_text = ", ".join(f"{key}: {value}" for key, value in db_info.items()) if db_info else ""
    return date_text, db_text
