from __future__ import annotations

import re

MAX_SQL_LENGTH = 5000

DENIED_PATTERN = re.compile(
    r"\b("
    r"insert|update|delete|replace|upsert|merge|"
    r"drop|alter|create|truncate|"
    r"attach|detach|pragma|vacuum|reindex|analyze|"
    r"begin|commit|rollback|savepoint|release|"
    r"grant|revoke|"
    r"load_extension|readfile|writefile|fts3_tokenizer|"
    r"sqlite_master|sqlite_schema|sqlite_temp_master"
    r")\b",
    re.IGNORECASE,
)
START_PATTERN = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
SELECT_PATTERN = re.compile(r"\bselect\b", re.IGNORECASE)


class SQLValidationError(ValueError):
    pass


def _strip_literals_and_comments(sql: str) -> str:
    output: list[str] = []
    index = 0
    length = len(sql)
    state = "normal"
    while index < length:
        character = sql[index]
        following = sql[index + 1] if index + 1 < length else ""
        if state == "normal":
            if character == "'":
                state = "single"
                output.append(" ")
            elif character == '"':
                state = "double"
                output.append(" ")
            elif character == "`":
                state = "backtick"
                output.append(" ")
            elif character == "[":
                state = "bracket"
                output.append(" ")
            elif character == "-" and following == "-":
                state = "line_comment"
                index += 1
                output.append(" ")
            elif character == "/" and following == "*":
                state = "block_comment"
                index += 1
                output.append(" ")
            else:
                output.append(character)
        elif state == "single":
            if character == "'" and following == "'":
                index += 1
            elif character == "'":
                state = "normal"
                output.append(" ")
        elif state == "double":
            if character == '"' and following == '"':
                index += 1
            elif character == '"':
                state = "normal"
                output.append(" ")
        elif state == "backtick":
            if character == "`":
                state = "normal"
                output.append(" ")
        elif state == "bracket":
            if character == "]" and following == "]":
                index += 1
            elif character == "]":
                state = "normal"
                output.append(" ")
        elif state == "line_comment":
            if character in "\r\n":
                state = "normal"
                output.append("\n")
        elif state == "block_comment" and character == "*" and following == "/":
            state = "normal"
            index += 1
            output.append(" ")
        index += 1
    if state in {"single", "double", "backtick", "bracket", "block_comment"}:
        raise SQLValidationError("SQL contains an unterminated string, identifier, or comment.")
    return "".join(output)


def _strip_comments_only(sql: str) -> str:
    output: list[str] = []
    index = 0
    length = len(sql)
    state = "normal"
    while index < length:
        character = sql[index]
        following = sql[index + 1] if index + 1 < length else ""
        if state == "normal":
            if character in {"'", '"', "`", "["}:
                state = {"'": "single", '"': "double", "`": "backtick", "[": "bracket"}[character]
                output.append(character)
            elif character == "-" and following == "-":
                state = "line_comment"
                index += 1
                output.append(" ")
            elif character == "/" and following == "*":
                state = "block_comment"
                index += 1
                output.append(" ")
            else:
                output.append(character)
        elif state in {"single", "double"}:
            quote = "'" if state == "single" else '"'
            output.append(character)
            if character == quote and following == quote:
                output.append(following)
                index += 1
            elif character == quote:
                state = "normal"
        elif state == "backtick":
            output.append(character)
            if character == "`":
                state = "normal"
        elif state == "bracket":
            output.append(character)
            if character == "]" and following == "]":
                output.append(following)
                index += 1
            elif character == "]":
                state = "normal"
        elif state == "line_comment":
            if character in "\r\n":
                state = "normal"
                output.append("\n")
        elif state == "block_comment" and character == "*" and following == "/":
            state = "normal"
            index += 1
            output.append(" ")
        index += 1
    if state in {"single", "double", "backtick", "bracket", "block_comment"}:
        raise SQLValidationError("SQL contains an unterminated string, identifier, or comment.")
    return "".join(output)


def validate_sql(sql: str) -> str:
    if not isinstance(sql, str) or not sql.strip():
        raise SQLValidationError("SQL must be a non-empty string.")
    if len(sql) > MAX_SQL_LENGTH:
        raise SQLValidationError(f"SQL is longer than the {MAX_SQL_LENGTH}-character limit.")
    if "\x00" in sql:
        raise SQLValidationError("SQL must not contain NUL characters.")
    stripped = _strip_literals_and_comments(sql).strip()
    if not stripped:
        raise SQLValidationError("SQL does not contain a statement.")
    if stripped.endswith(";"):
        stripped = stripped[:-1].rstrip()
    if ";" in stripped:
        raise SQLValidationError("Only one SQL statement is allowed.")
    if not START_PATTERN.match(stripped):
        raise SQLValidationError("Only SELECT queries and WITH ... SELECT queries are allowed.")
    if stripped.lstrip().lower().startswith("with") and not SELECT_PATTERN.search(stripped):
        raise SQLValidationError("A WITH clause must end in a SELECT query.")
    denied = DENIED_PATTERN.search(stripped)
    if denied:
        raise SQLValidationError(f"The keyword '{denied.group(1).lower()}' is not allowed.")
    if not SELECT_PATTERN.search(stripped):
        raise SQLValidationError("Only SELECT queries are allowed.")
    execution = _strip_comments_only(sql).strip()
    if execution.endswith(";"):
        execution = execution[:-1].rstrip()
    if not execution:
        raise SQLValidationError("SQL does not contain a statement.")
    return execution
