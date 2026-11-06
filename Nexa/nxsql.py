"""
Nexa NXsql - schema compiler and SQLite runner (starter implementation)

Example:
    from Nexa.nxsql import curxor, Table, Column, check, CURRENT_TIMESTAMP

    schema = Table.new(
        name="users",
        id=Column("Int", primary_key=True, auto_increment=True),
        username=Column("Str", non_nullable=True, unique=True),
        email=Column("Str", non_nullable=True, unique=True),
        age=Column("Int", check=check(">= 13")),
        created_at=Column("Datetime", default=CURRENT_TIMESTAMP),
    )

    sql = curxor.compile(schema)  # returns ordinary SQL text

    import sqlite3
    conn = sqlite3.connect("main.db")
    conn.cursor().execute(sql)
    conn.commit()

    # Or use the NXsql convenience runner:
    curxor.execute(file="main.db", schema=schema)
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence


# -----------------------------
# SQL expressions / safe helpers
# -----------------------------

@dataclass(frozen=True)
class SQLExpression:
    """A trusted SQL expression emitted by NXsql, not a user value."""
    sql: str


CURRENT_TIMESTAMP = SQLExpression("CURRENT_TIMESTAMP")


@dataclass(frozen=True)
class Check:
    expression: str


def check(expression: str) -> Check:
    """
    Accepts a deliberately small CHECK expression grammar.
    Examples: '>= 13', '< 100', 'IN (1, 2, 3)'.

    This is not a general SQL parser. Do not pass arbitrary untrusted text.
    """
    expression = expression.strip()
    if not expression:
        raise ValueError("check() requires a non-empty expression")

    # Allow a restricted expression form; column name is inserted by compiler.
    allowed = re.fullmatch(
        r"(?:"
        r"(?:>=|<=|<>|!=|=|>|<)\s*-?\d+(?:\.\d+)?"
        r"|(?:IN|NOT IN)\s*\(\s*-?\d+(?:\.\d+)?(?:\s*,\s*-?\d+(?:\.\d+)?)*\s*\)"
        r"|(?:LIKE|NOT LIKE)\s+'[A-Za-z0-9_% -]+'"
        r")",
        expression,
        flags=re.IGNORECASE,
    )
    if not allowed:
        raise ValueError(
            "Unsupported CHECK expression. Supported examples: "
            "'>= 13', '< 100', 'IN (1, 2, 3)', \"LIKE 'abc%'\""
        )
    return Check(expression)


# -----------------------------
# Schema declaration objects
# -----------------------------

SUPPORTED_TYPES = {
    "Int": "INTEGER",
    "Integer": "INTEGER",
    "Str": "TEXT",
    "String": "TEXT",
    "Text": "TEXT",
    "Float": "REAL",
    "Bool": "INTEGER",
    "Boolean": "INTEGER",
    "Blob": "BLOB",
    "Date": "TEXT",
    "Datetime": "TEXT",
    "Decimal": "NUMERIC",
}


@dataclass(frozen=True)
class Reference:
    table: str
    column: str = "id"
    on_delete: str | None = None
    on_update: str | None = None


def references(
    table: str,
    column: str = "id",
    *,
    on_delete: str | None = None,
    on_update: str | None = None,
) -> Reference:
    return Reference(table, column, on_delete, on_update)


@dataclass
class Column:
    type: str
    primary_key: bool = False
    auto_increment: bool = False
    non_nullable: bool = False
    unique: bool = False
    default: Any = None
    check: Check | None = None
    references: Reference | None = None

    def __post_init__(self):
        if self.type not in SUPPORTED_TYPES:
            raise ValueError(
                f"Unsupported NXsql type {self.type!r}. "
                f"Supported: {', '.join(SUPPORTED_TYPES)}"
            )
        if self.auto_increment and not self.primary_key:
            raise ValueError("auto_increment=True requires primary_key=True")
        if self.auto_increment and SUPPORTED_TYPES[self.type] != "INTEGER":
            raise ValueError("SQLite AUTOINCREMENT requires an INTEGER PRIMARY KEY")


@dataclass
class TableSchema:
    name: str
    columns: dict[str, Column]
    schema: str | None = None
    if_not_exists: bool = True
    constraints: list[str] = field(default_factory=list)


class Table:
    @staticmethod
    def new(
        *,
        name: str,
        schema: str | None = None,
        if_not_exists: bool = True,
        constraints: Sequence[str] = (),
        **columns: Column,
    ) -> TableSchema:
        if not columns:
            raise ValueError("Table.new() requires at least one column")
        for column_name, column in columns.items():
            _validate_identifier(column_name)
            if not isinstance(column, Column):
                raise TypeError(
                    f"Column {column_name!r} must be a Column(...), "
                    f"got {type(column).__name__}"
                )
        _validate_identifier(name)
        if schema is not None:
            _validate_identifier(schema)
        return TableSchema(
            name=name,
            columns=dict(columns),
            schema=schema,
            if_not_exists=if_not_exists,
            constraints=list(constraints),
        )


# -----------------------------
# Compiler
# -----------------------------

_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: str) -> None:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise ValueError(f"Invalid SQL identifier: {value!r}")


def _quote_identifier(value: str) -> str:
    _validate_identifier(value)
    return f'"{value}"'


def _qualified_table_name(table: TableSchema) -> str:
    name = _quote_identifier(table.name)
    if table.schema:
        return f"{_quote_identifier(table.schema)}.{name}"
    return name


def _sql_literal(value: Any) -> str:
    if isinstance(value, SQLExpression):
        return value.sql
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return "'" + value.replace("'", "''") + "'"
    raise TypeError(
        "Unsupported default value. Use a string, number, bool, None, "
        "or NXsql SQLExpression such as CURRENT_TIMESTAMP."
    )


def _compile_column(name: str, column: Column) -> str:
    parts = [_quote_identifier(name), SUPPORTED_TYPES[column.type]]

    if column.primary_key:
        parts.append("PRIMARY KEY")
    if column.auto_increment:
        parts.append("AUTOINCREMENT")
    if column.non_nullable:
        parts.append("NOT NULL")
    if column.unique:
        parts.append("UNIQUE")
    if column.default is not None:
        parts.extend(["DEFAULT", _sql_literal(column.default)])
    if column.check is not None:
        parts.append(f"CHECK ({_quote_identifier(name)} {column.check.expression})")
    if column.references is not None:
        ref = column.references
        _validate_identifier(ref.table)
        _validate_identifier(ref.column)
        clause = (
            f"REFERENCES {_quote_identifier(ref.table)}"
            f"({_quote_identifier(ref.column)})"
        )
        for action_name, action in (
            ("ON DELETE", ref.on_delete),
            ("ON UPDATE", ref.on_update),
        ):
            if action is not None:
                action = action.upper()
                if action not in {"CASCADE", "RESTRICT", "SET NULL", "SET DEFAULT", "NO ACTION"}:
                    raise ValueError(f"Unsupported foreign-key action: {action!r}")
                clause += f" {action_name} {action}"
        parts.append(clause)

    return " ".join(parts)


class curxor:
    """
    NXsql public API.

    compile() returns SQL text; it does not execute.
    execute() runs supplied SQL/schema against the SQLite database file.
    """

    @staticmethod
    def compile(source: TableSchema | str) -> str:
        if isinstance(source, TableSchema):
            columns_sql = [
                _compile_column(name, column)
                for name, column in source.columns.items()
            ]
            columns_sql.extend(source.constraints)
            if_not_exists = "IF NOT EXISTS " if source.if_not_exists else ""
            return (
                f"CREATE TABLE {if_not_exists}{_qualified_table_name(source)} "
                f"({', '.join(columns_sql)});"
            )
        if isinstance(source, str):
            # For raw SQL/NXsql query text, compile currently passes through.
            # Query-language transpilation can be added here later.
            return source.strip()
        raise TypeError("compile() expects a TableSchema or source string")

    @staticmethod
    def compile_many(sources: Iterable[TableSchema | str]) -> list[str]:
        return [curxor.compile(source) for source in sources]

    @staticmethod
    def execute(
        *,
        file: str,
        sql: str | None = None,
        schema: TableSchema | None = None,
        params: Sequence[Any] | Mapping[str, Any] = (),
        scripts: Sequence[str] | None = None,
    ):
        """
        Execute compiled SQL against a SQLite database.

        Pass exactly one of sql, schema, or scripts.
        `params` are SQLite bound parameters; never interpolate user values.
        """
        choices = sum(value is not None for value in (sql, schema, scripts))
        if choices != 1:
            raise ValueError("Pass exactly one of sql=, schema=, or scripts=")

        if schema is not None:
            statement = curxor.compile(schema)
            statements = [statement]
        elif sql is not None:
            statements = [sql]
        else:
            statements = list(scripts or [])

        connection = sqlite3.connect(file)
        try:
            cursor = connection.cursor()
            results = []
            for statement in statements:
                if params and len(statements) != 1:
                    raise ValueError("Use params only with a single SQL statement")
                results.append(cursor.execute(statement, params))
            connection.commit()
            return results[0] if len(results) == 1 else results
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    @staticmethod
    def table_exists(file: str, name: str, schema: str = "main") -> bool:
        _validate_identifier(name)
        _validate_identifier(schema)
        connection = sqlite3.connect(file)
        try:
            row = connection.execute(
                f"SELECT 1 FROM {_quote_identifier(schema)}.sqlite_master "
                "WHERE type='table' AND name=? LIMIT 1",
                (name,),
            ).fetchone()
            return row is not None
        finally:
            connection.close()


__all__ = [
    "curxor",
    "Table",
    "TableSchema",
    "Column",
    "Check",
    "check",
    "Reference",
    "references",
    "SQLExpression",
    "CURRENT_TIMESTAMP",
]
