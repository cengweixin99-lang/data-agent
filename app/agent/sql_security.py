import re

# 自定义异常类，当 SQL 违反只读契约时抛出的自定义异常
class SQLSecurityError(ValueError):
    """Raised when generated SQL is outside the read-only query contract."""

# 禁止的关键字集合
_FORBIDDEN_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "REPLACE", "MERGE", "UPSERT",
    "CREATE", "ALTER", "DROP", "TRUNCATE", "GRANT", "REVOKE",
    "CALL", "DO", "SET", "USE", "INTO",
}

# 词法分析器，负责提取 SQL 中的关键字，同时忽略引号的文本和注释。
def _tokens(sql: str) -> list[str]:
    """Return SQL words and semicolons, ignoring quoted text and comments."""
    tokens: list[str] = []  # 存储提取的关键字
    current: list[str] = [] # 当前正在构建的关键字
    index = 0   # 当前字符索引

    def flush() -> None:
        """将 current 缓冲区的内容刷新到 tokens 列表"""
        if current:
            tokens.append("".join(current).upper())
            current.clear()

    while index < len(sql):
        char = sql[index]
        if char in ("'", '"', "`"):
            flush()
            quote = char
            index += 1
            while index < len(sql):
                if sql[index] == "\\":
                    index += 2
                    continue
                if sql[index] == quote:
                    if index + 1 < len(sql) and sql[index + 1] == quote:
                        index += 2
                        continue
                    index += 1
                    break
                index += 1
            continue
        if char == "-" and index + 1 < len(sql) and sql[index + 1] == "-":
            flush()
            index += 2
            while index < len(sql) and sql[index] not in "\r\n":
                index += 1
            continue
        if char == "/" and index + 1 < len(sql) and sql[index + 1] == "*":
            flush()
            end = sql.find("*/", index + 2)
            if end == -1:
                raise SQLSecurityError("SQL comment is not closed")
            index = end + 2
            continue
        if char.isalpha() or char == "_":
            current.append(char)
        else:
            flush()
            if char == ";":
                tokens.append(";")
        index += 1
    flush()
    return tokens


def validate_read_only_sql(sql: str) -> str:
    """Validate and normalize one read-only SELECT statement."""

    # 1. 基础检查
    if not isinstance(sql, str) or not sql.strip():
        raise SQLSecurityError("SQL cannot be empty")

    normalized = sql.strip().lstrip("\ufeff")
    normalized = re.sub(r"^```(?:sql)?\s*|\s*```$", "", normalized, flags=re.IGNORECASE)
    normalized = normalized.strip()

    # 2. 词法分析
    tokens = _tokens(normalized)
    words = [token for token in tokens if token != ";"]

    # 3. 语句类型检查
    if not words or words[0] not in {"SELECT", "WITH"}:
        raise SQLSecurityError("Only SELECT or WITH queries are allowed")

    # 4. 语句数量检查
    semicolon_indexes = [index for index, token in enumerate(tokens) if token == ";"]
    if len(semicolon_indexes) > 1:
        raise SQLSecurityError("Only one SQL statement is allowed")
    if semicolon_indexes and semicolon_indexes[0] != len(tokens) - 1:
        raise SQLSecurityError("Multiple SQL statements are not allowed")

    # 5. 禁止关键字检查
    forbidden = sorted(_FORBIDDEN_KEYWORDS.intersection(words))
    if forbidden:
        raise SQLSecurityError(f"Forbidden SQL operation: {', '.join(forbidden)}")
    if "FOR" in words and "UPDATE" in words:
        raise SQLSecurityError("FOR UPDATE queries are not allowed")

    # 6. 返回规范化的 SQL
    if normalized.endswith(";"):
        normalized = normalized[:-1].rstrip()
    return normalized