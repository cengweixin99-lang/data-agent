from typing import Any

from app.agent.observability import current_node_name, current_trace_id, node_title


def _chunk_to_text(chunk: Any) -> str:
    if isinstance(chunk, str):
        return chunk

    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "".join(parts)

    return ""


async def stream_text_chain(chain: Any, inputs: dict[str, Any], runtime: Any) -> str:
    trace_id = current_trace_id()
    node = current_node_name()
    writer = runtime.stream_writer
    chunks: list[str] = []

    try:
        async for chunk in chain.astream(inputs):
            text = _chunk_to_text(chunk)
            if not text:
                continue
            chunks.append(text)
            if trace_id and node:
                writer({
                    "type": "trace",
                    "event": "content_delta",
                    "id": trace_id,
                    "node": node,
                    "title": node_title(node),
                    "status": "running",
                    "delta": text,
                })
    except NotImplementedError:
        result = await chain.ainvoke(inputs)
        text = _chunk_to_text(result) or str(result)
        chunks.append(text)
        if trace_id and node:
            writer({
                "type": "trace",
                "event": "content_delta",
                "id": trace_id,
                "node": node,
                "title": node_title(node),
                "status": "running",
                "delta": text,
            })

    return "".join(chunks).strip()
