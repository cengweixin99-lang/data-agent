import re

_CN_NUMBERS = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _extract_top_n(query: str) -> int | None:
    digit_match = re.search(r"前\s*(\d+)\s*(?:个|名)?", query)
    if digit_match:
        return int(digit_match.group(1))

    cn_match = re.search(r"前\s*([一二两三四五六七八九十])\s*(?:个|名)?", query)
    if cn_match:
        return _CN_NUMBERS.get(cn_match.group(1))
    return None


def _is_topn_product_query(query: str) -> bool:
    has_product = "商品" in query or "产品" in query
    has_topn = _extract_top_n(query) is not None or any(word in query for word in ("排行", "排名", "最高"))
    return has_product and has_topn


def _measure_for_query(query: str) -> tuple[str, str] | None:
    if any(word in query for word in ("销量", "销售量", "购买数量", "数量")):
        return "order_quantity", "销量"
    if any(word in query for word in ("销售额", "成交额", "GMV", "金额")):
        return "order_amount", "销售额"
    return None


def try_generate_template_sql(query: str) -> str | None:
    if not _is_topn_product_query(query):
        return None

    top_n = _extract_top_n(query) or 3
    measure = _measure_for_query(query)
    if measure is None:
        return None
    measure_column, measure_alias = measure

    if "地区" in query:
        return f"""WITH ranked_products AS (
    SELECT
        r.region_name AS 地区,
        p.product_name AS 商品名称,
        SUM(f.{measure_column}) AS {measure_alias},
        ROW_NUMBER() OVER (PARTITION BY r.region_id, r.region_name ORDER BY SUM(f.{measure_column}) DESC) AS 排名
    FROM fact_order f
    INNER JOIN dim_region r ON f.region_id = r.region_id
    INNER JOIN dim_product p ON f.product_id = p.product_id
    GROUP BY r.region_id, r.region_name, p.product_id, p.product_name
)
SELECT 地区 AS 地区, 商品名称 AS 商品名称, {measure_alias} AS {measure_alias}
FROM ranked_products
WHERE 排名 <= {top_n}
ORDER BY 地区, 排名"""

    return f"""SELECT
    p.product_name AS 商品名称,
    SUM(f.{measure_column}) AS {measure_alias}
FROM fact_order f
INNER JOIN dim_product p ON f.product_id = p.product_id
GROUP BY p.product_id, p.product_name
ORDER BY {measure_alias} DESC
LIMIT {top_n}"""