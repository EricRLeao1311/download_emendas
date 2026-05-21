from __future__ import annotations

import atexit
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
import threading
from typing import Any

import duckdb
import pandas as pd

from download_emendas.settings import DatasetSettings


@dataclass(frozen=True)
class ColumnProfile:
    name: str
    duckdb_type: str


def quote_identifier(identifier: str) -> str:
    return f'"{identifier.replace("\"", "\"\"")}"'


def _normalize_filter_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    return value


class ParquetQueryService:
    def __init__(self, dataset: DatasetSettings, threads: int = 4) -> None:
        self.dataset = dataset
        self.threads = threads
        self._local = threading.local()
        self._connections: list[duckdb.DuckDBPyConnection] = []
        self._connections_lock = threading.Lock()
        self._column_profiles: list[ColumnProfile] | None = None
        atexit.register(self.close)

    def _scan_sql(self) -> str:
        return f"read_parquet('{self.dataset.parquet_path.as_posix()}')"

    def _connect(self) -> duckdb.DuckDBPyConnection:
        connection = getattr(self._local, "connection", None)
        if connection is not None:
            return connection

        temp_dir = self.dataset.parquet_path.parent / "_duckdb_tmp" / self.dataset.key
        temp_dir.mkdir(parents=True, exist_ok=True)
        connection = duckdb.connect(database=":memory:")
        connection.execute(f"PRAGMA threads={max(1, self.threads)}")
        connection.execute("PRAGMA preserve_insertion_order=false")
        connection.execute("PRAGMA enable_object_cache=true")
        connection.execute(f"PRAGMA temp_directory='{temp_dir.as_posix()}'")
        self._local.connection = connection
        with self._connections_lock:
            self._connections.append(connection)
        return connection

    def parquet_exists(self) -> bool:
        return self.dataset.parquet_path.exists()

    def metadata_path(self) -> Path:
        return self.dataset.parquet_path.with_suffix(".metadata.json")

    def describe_columns(self) -> list[ColumnProfile]:
        if self._column_profiles is not None:
            return self._column_profiles

        sql = f"DESCRIBE SELECT * FROM {self._scan_sql()}"
        rows = self._connect().execute(sql).fetchall()
        self._column_profiles = [ColumnProfile(name=row[0], duckdb_type=row[1]) for row in rows]
        return self._column_profiles

    def total_rows(self) -> int:
        return self.count_rows({})

    def count_rows(self, filters: dict[str, dict[str, Any]]) -> int:
        where_sql, params = self._build_where_clause(filters)
        sql = f"""
            SELECT COUNT(*)::BIGINT
            FROM {self._scan_sql()}
            {where_sql}
        """
        return int(self._connect().execute(sql, params).fetchone()[0])

    def get_distinct_values(self, column_name: str, limit: int) -> list[Any]:
        column_sql = quote_identifier(column_name)
        sql = f"""
            SELECT DISTINCT {column_sql} AS value
            FROM {self._scan_sql()}
            WHERE {column_sql} IS NOT NULL
              AND TRIM(CAST({column_sql} AS VARCHAR)) <> ''
            ORDER BY value
            LIMIT ?
        """
        rows = self._connect().execute(sql, [limit]).fetchall()
        return [row[0] for row in rows]

    def get_numeric_bounds(self, column_name: str) -> tuple[float | None, float | None]:
        column_sql = quote_identifier(column_name)
        sql = f"""
            SELECT MIN({column_sql})::DOUBLE, MAX({column_sql})::DOUBLE
            FROM {self._scan_sql()}
            WHERE {column_sql} IS NOT NULL
        """
        row = self._connect().execute(sql).fetchone()
        return row[0], row[1]

    def get_date_bounds(self, column_name: str) -> tuple[date | None, date | None]:
        column_sql = quote_identifier(column_name)
        sql = f"""
            SELECT MIN({column_sql})::DATE, MAX({column_sql})::DATE
            FROM {self._scan_sql()}
            WHERE {column_sql} IS NOT NULL
        """
        row = self._connect().execute(sql).fetchone()
        return row[0], row[1]

    def fetch_frame(
        self,
        selected_columns: list[str],
        filters: dict[str, dict[str, Any]],
        row_limit: int,
        sort_column: str | None,
        sort_desc: bool,
    ) -> pd.DataFrame:
        columns_sql = ", ".join(quote_identifier(column_name) for column_name in selected_columns)
        where_sql, params = self._build_where_clause(filters)
        order_sql = ""
        if sort_column and sort_column in selected_columns:
            direction = "DESC" if sort_desc else "ASC"
            order_sql = f"ORDER BY {quote_identifier(sort_column)} {direction} NULLS LAST"
        sql = f"""
            SELECT {columns_sql}
            FROM {self._scan_sql()}
            {where_sql}
            {order_sql}
            LIMIT ?
        """
        return self._connect().execute(sql, [*params, row_limit]).fetchdf()

    def fetch_preview_frame(
        self,
        selected_columns: list[str],
        filters: dict[str, dict[str, Any]],
        row_limit: int,
        sort_column: str | None,
        sort_desc: bool,
    ) -> tuple[pd.DataFrame, int]:
        dataframe = self.fetch_frame(selected_columns, filters, row_limit, sort_column, sort_desc)
        return dataframe, self.count_rows(filters)

    def close(self) -> None:
        with self._connections_lock:
            for connection in self._connections:
                try:
                    connection.close()
                except Exception:
                    continue
            self._connections.clear()

    def _build_where_clause(self, filters: dict[str, dict[str, Any]]) -> tuple[str, list[Any]]:
        clauses: list[str] = []
        params: list[Any] = []

        for column_name, payload in filters.items():
            if not payload:
                continue

            column_sql = quote_identifier(column_name)
            kind = payload.get("kind")

            if kind == "categorical":
                values = payload.get("values") or []
                if values:
                    placeholders = ", ".join("?" for _ in values)
                    clauses.append(f"CAST({column_sql} AS VARCHAR) IN ({placeholders})")
                    params.extend(str(_normalize_filter_value(value)) for value in values)

            elif kind == "search":
                term = str(payload.get("value", "")).strip()
                if term:
                    clauses.append(f"CAST({column_sql} AS VARCHAR) ILIKE ?")
                    params.append(f"%{term}%")

            elif kind == "numeric":
                minimum = payload.get("min")
                maximum = payload.get("max")
                if minimum is not None:
                    clauses.append(f"{column_sql} >= ?")
                    params.append(minimum)
                if maximum is not None:
                    clauses.append(f"{column_sql} <= ?")
                    params.append(maximum)

            elif kind == "date":
                start_value = payload.get("start")
                end_value = payload.get("end")
                if start_value is not None:
                    clauses.append(f"{column_sql} >= ?")
                    params.append(_normalize_filter_value(start_value))
                if end_value is not None:
                    clauses.append(f"{column_sql} <= ?")
                    params.append(_normalize_filter_value(end_value))

        if not clauses:
            return "", []
        return "WHERE " + " AND ".join(clauses), params
