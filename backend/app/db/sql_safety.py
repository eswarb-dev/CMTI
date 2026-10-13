"""Read-only SQL safety validation (defensive groundwork, not a feature).

This module prepares for a possible future SQL-assisted investigation path by
validating that a statement is a SINGLE read-only query.  It deliberately does
NOT implement natural-language-to-SQL and there is intentionally no
unrestricted ``execute_sql`` API anywhere in the application.  Repository
templates remain the safest access path.
"""

from __future__ import annotations

import sqlite3

from app.core.exceptions import SqlSafetyError

MAX_QUERY_LENGTH = 10000

ALLOWED_START_KEYWORDS = frozenset({"select", "with"})

#: Keywords that may never appear anywhere outside of quoted literals.
FORBIDDEN_KEYWORDS = frozenset(
    {
        "insert",
        "update",
        "delete",
        "drop",
        "alter",
        "create",
        "replace",
        "attach",
        "detach",
        "vacuum",
        "reindex",
        "analyze",
        "pragma",
        "begin",
        "commit",
        "rollback",
        "savepoint",
        "release",
        "into",
        "truncate",
        "merge",
        "grant",
        "revoke",
        "exec",
        "execute",
        "call",
        "upsert",
        "load",
        "copy",
        "import",
        "export",
    }
)

_TOKEN_WORD = "word"
_TOKEN_STRING = "string"
_TOKEN_PARAM = "param"
_TOKEN_NUMBER = "number"
_TOKEN_PUNCT = "punct"

_OPEN_QUOTES = {"'": "'", '"': '"', "`": "`", "[": "]"}


def _reject(reason: str) -> SqlSafetyError:
    return SqlSafetyError(f"Rejected non-read-only or unsafe SQL: {reason}")


def _tokenize(sql: str) -> list[tuple[str, str]]:
    """Tokenize SQL, treating quoted regions as opaque and rejecting comments."""

    tokens: list[tuple[str, str]] = []
    index = 0
    length = len(sql)
    while index < length:
        char = sql[index]
        if char.isspace():
            index += 1
            continue
        if char == "-" and sql.startswith("--", index):
            raise _reject("SQL comments are not allowed")
        if char == "/" and sql.startswith("/*", index):
            raise _reject("SQL comments are not allowed")
        if char in _OPEN_QUOTES:
            closing = _OPEN_QUOTES[char]
            end = index + 1
            while end < length:
                if sql[end] == closing:
                    if end + 1 < length and sql[end + 1] == closing:
                        end += 2
                        continue
                    break
                end += 1
            if end >= length:
                raise _reject("unterminated quoted literal")
            kind = _TOKEN_STRING if char in {"'", '"'} else _TOKEN_PUNCT
            tokens.append((kind, sql[index : end + 1]))
            index = end + 1
            continue
        if char == ";":
            tokens.append((_TOKEN_PUNCT, ";"))
            index += 1
            continue
        if char == "?":
            end = index + 1
            while end < length and sql[end].isdigit():
                end += 1
            tokens.append((_TOKEN_PARAM, sql[index:end]))
            index = end
            continue
        if char in {":", "@", "$"}:
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] == "_"):
                end += 1
            if end == index + 1:
                tokens.append((_TOKEN_PUNCT, char))
                index += 1
                continue
            tokens.append((_TOKEN_PARAM, sql[index:end]))
            index = end
            continue
        if char.isdigit():
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] in {".", "+", "-"}):
                if sql[end] in "+-" and sql[end - 1] not in {"e", "E"}:
                    break
                end += 1
            tokens.append((_TOKEN_NUMBER, sql[index:end]))
            index = end
            continue
        if char.isalpha() or char == "_":
            end = index + 1
            while end < length and (sql[end].isalnum() or sql[end] in {"_", "$"}):
                end += 1
            tokens.append((_TOKEN_WORD, sql[index:end]))
            index = end
            continue
        tokens.append((_TOKEN_PUNCT, char))
        index += 1
    return tokens


def _check_single_statement(tokens: list[tuple[str, str]]) -> None:
    semicolons = [i for i, (_, text) in enumerate(tokens) if text == ";"]
    if not semicolons:
        return
    if len(semicolons) > 1:
        raise _reject("multiple SQL statements are not allowed")
    if semicolons[0] != len(tokens) - 1:
        raise _reject("multiple SQL statements are not allowed")


def _is_syntax_error(message: str) -> bool:
    lowered = message.lower()
    return "syntax error" in lowered or "incomplete input" in lowered


def _compile_check(sql: str, tokens: list[tuple[str, str]]) -> None:
    """Ask SQLite to compile the statement so syntax errors fail closed.

    Semantic errors (``no such table``/``no such column``) are expected here
    because the validator runs against an empty scratch database; only syntax
    problems reject the statement.
    """

    connection = sqlite3.connect(":memory:")
    try:
        try:
            connection.execute("EXPLAIN QUERY PLAN " + sql)
            return
        except sqlite3.ProgrammingError as exc:
            message = str(exc).lower()
            if "binding" not in message and "parameter" not in message:
                if _is_syntax_error(message):
                    raise _reject(f"statement does not compile: {exc}") from exc
                return
        except sqlite3.Error as exc:
            if _is_syntax_error(str(exc)):
                raise _reject(f"statement does not compile: {exc}") from exc
            return
        binding_count = 0
        for kind, text in tokens:
            if kind != _TOKEN_PARAM:
                continue
            if text.startswith("?"):
                binding_count += 1
                digits = text[1:]
                if digits:
                    binding_count = max(binding_count, int(digits))
            else:
                binding_count += 1
        if binding_count == 0:
            raise _reject("statement does not compile")
        try:
            connection.execute(
                "EXPLAIN QUERY PLAN " + sql, tuple(None for _ in range(binding_count))
            )
        except sqlite3.Error as exc:
            if _is_syntax_error(str(exc)):
                raise _reject(f"statement does not compile: {exc}") from exc
            return
    finally:
        connection.close()


def validate_readonly_query(sql: str) -> str:
    """Validate that ``sql`` is a single read-only query and return it.

    Raises:
        SqlSafetyError: when the statement is not a single read-only query.
    """

    if not isinstance(sql, str):
        raise _reject("query must be a string")
    if "\x00" in sql:
        raise _reject("NUL bytes are not allowed")
    stripped = sql.strip()
    if not stripped:
        raise _reject("query is empty")
    if len(stripped) > MAX_QUERY_LENGTH:
        raise _reject(f"query exceeds {MAX_QUERY_LENGTH} characters")

    tokens = _tokenize(stripped)
    if not tokens:
        raise _reject("query is empty")

    _check_single_statement(tokens)

    words = [(kind, text) for kind, text in tokens if kind == _TOKEN_WORD]
    lowered = [text.lower() for _, text in words]

    first_keyword = lowered[0]
    if first_keyword not in ALLOWED_START_KEYWORDS:
        raise _reject(f"statement must start with SELECT or WITH, got {first_keyword!r}")

    for word in lowered:
        if word in FORBIDDEN_KEYWORDS:
            raise _reject(f"forbidden keyword {word.upper()!r}")

    if first_keyword == "with" and "select" not in lowered[1:]:
        raise _reject("WITH statements must contain a SELECT")

    _compile_check(stripped, tokens)
    return stripped


def is_readonly_query(sql: str) -> bool:
    """Return ``True`` when :func:`validate_readonly_query` accepts the SQL."""

    try:
        validate_readonly_query(sql)
    except SqlSafetyError:
        return False
    return True
