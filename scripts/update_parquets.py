from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any

import duckdb

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from download_emendas.query_service import quote_identifier
from download_emendas.settings import AppSettings, DatasetSettings, load_settings


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Converte os CSVs de emendas/documentos em parquet para uso no sistema."
    )
    parser.add_argument(
        "--config",
        default=str(ROOT_DIR / "config" / "app.toml"),
        help="Arquivo de configuração TOML.",
    )
    parser.add_argument(
        "--only",
        choices=["emendas", "documentos", "all"],
        default="all",
        help="Atualiza apenas um dataset específico.",
    )
    parser.add_argument(
        "--emendas-csv",
        help="Sobrescreve o caminho do CSV de emendas.",
    )
    parser.add_argument(
        "--documentos-csv",
        help="Sobrescreve o caminho do CSV de documentos.",
    )
    parser.add_argument(
        "--output-dir",
        help="Diretório de saída dos parquets.",
    )
    parser.add_argument(
        "--sample-rows",
        type=int,
        default=0,
        help="Processa somente a quantidade informada de linhas para um teste rápido.",
    )
    parser.add_argument(
        "--compression",
        default="zstd",
        help="Compressão do parquet. Ex.: zstd, snappy.",
    )
    parser.add_argument(
        "--threads",
        type=int,
        help="Quantidade de threads usada na conversao. Se omitido, usa um valor conservador para evitar estouro de memoria.",
    )
    return parser.parse_args()


def read_headers(csv_path: Path) -> list[str]:
    with csv_path.open("r", encoding="utf-8", newline="") as csv_file:
        reader = csv.reader(csv_file)
        return next(reader)


def resolve_source_path(dataset_key: str, dataset: DatasetSettings, args: argparse.Namespace) -> Path:
    override = args.emendas_csv if dataset_key == "emendas" else args.documentos_csv
    return Path(override) if override else dataset.source_csv_path


def resolve_output_path(dataset: DatasetSettings, output_dir: str | None) -> Path:
    if not output_dir:
        return dataset.parquet_path
    return Path(output_dir).resolve() / dataset.parquet_path.name


def build_select_sql(headers: list[str], dataset: DatasetSettings) -> str:
    select_parts: list[str] = []
    for column_name in headers:
        column_sql = quote_identifier(column_name)
        trimmed_sql = f"NULLIF(TRIM({column_sql}), '')"

        if column_name in dataset.date_columns:
            expression = f"TRY_CAST({trimmed_sql} AS DATE)"
        elif column_name in dataset.timestamp_columns:
            expression = f"TRY_CAST({trimmed_sql} AS TIMESTAMP)"
        elif column_name in dataset.integer_columns:
            expression = f"TRY_CAST(REPLACE({trimmed_sql}, ',', '.') AS BIGINT)"
        elif column_name in dataset.numeric_columns:
            expression = f"TRY_CAST(REPLACE({trimmed_sql}, ',', '.') AS DOUBLE)"
        else:
            expression = trimmed_sql

        select_parts.append(f"{expression} AS {column_sql}")

    return ", ".join(select_parts)


def build_csv_scan_sql(source_csv_path: Path, headers: list[str]) -> str:
    columns_sql = ", ".join(
        "'" + column_name.replace("'", "''") + "': 'VARCHAR'"
        for column_name in headers
    )
    return f"""
        read_csv(
            '{source_csv_path.as_posix()}',
            header=true,
            auto_detect=false,
            columns={{ {columns_sql} }},
            delim=',',
            quote='\"',
            escape='\"',
            ignore_errors=false
        )
    """


def build_filter_cache(
    connection: duckdb.DuckDBPyConnection,
    output_path: Path,
    dataset: DatasetSettings,
    max_filter_options: int,
) -> dict[str, dict[str, Any]]:
    filter_cache: dict[str, dict[str, Any]] = {}
    parquet_sql = f"read_parquet('{output_path.as_posix()}')"

    for column_name in dataset.featured_filters:
        column_sql = quote_identifier(column_name)
        kind = dataset.column_kind(column_name)

        if kind == "numeric":
            row = connection.execute(
                f"""
                SELECT MIN({column_sql})::DOUBLE, MAX({column_sql})::DOUBLE
                FROM {parquet_sql}
                WHERE {column_sql} IS NOT NULL
                """
            ).fetchone()
            filter_cache[column_name] = {
                "kind": "numeric",
                "min": row[0],
                "max": row[1],
            }
            continue

        if kind == "date":
            row = connection.execute(
                f"""
                SELECT MIN({column_sql})::DATE, MAX({column_sql})::DATE
                FROM {parquet_sql}
                WHERE {column_sql} IS NOT NULL
                """
            ).fetchone()
            filter_cache[column_name] = {
                "kind": "date",
                "start": row[0].isoformat() if row and row[0] else None,
                "end": row[1].isoformat() if row and row[1] else None,
            }
            continue

        rows = connection.execute(
            f"""
            SELECT DISTINCT CAST({column_sql} AS VARCHAR) AS value
            FROM {parquet_sql}
            WHERE {column_sql} IS NOT NULL
              AND TRIM(CAST({column_sql} AS VARCHAR)) <> ''
            ORDER BY value
            LIMIT ?
            """,
            [max_filter_options + 1],
        ).fetchall()
        values = [row[0] for row in rows[:max_filter_options]]
        filter_cache[column_name] = {
            "kind": "options",
            "values": values,
            "limitedTo": max_filter_options,
            "truncated": len(rows) > max_filter_options,
        }

    return filter_cache


def convert_dataset(
    dataset_key: str,
    dataset: DatasetSettings,
    args: argparse.Namespace,
    app_settings: AppSettings,
) -> dict[str, Any]:
    source_csv_path = resolve_source_path(dataset_key, dataset, args)
    output_path = resolve_output_path(dataset, args.output_dir)

    if not source_csv_path.exists():
        raise FileNotFoundError(f"CSV não encontrado: {source_csv_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    headers = read_headers(source_csv_path)
    select_sql = build_select_sql(headers, dataset)

    limit_sql = f"LIMIT {args.sample_rows}" if args.sample_rows and args.sample_rows > 0 else ""
    csv_scan_sql = build_csv_scan_sql(source_csv_path, headers)
    copy_sql = f"""
        COPY (
            SELECT {select_sql}
            FROM {csv_scan_sql}
            {limit_sql}
        )
        TO '{output_path.as_posix()}'
        (FORMAT PARQUET, COMPRESSION {args.compression.upper()})
    """

    temp_dir = ROOT_DIR / "data" / "tmp" / dataset_key
    temp_dir.mkdir(parents=True, exist_ok=True)
    connection = duckdb.connect(database=":memory:")
    thread_count = args.threads if args.threads is not None else max(1, min(2, app_settings.engine.threads))
    connection.execute(f"PRAGMA threads={thread_count}")
    connection.execute("PRAGMA preserve_insertion_order=false")
    connection.execute("PRAGMA enable_object_cache=true")
    connection.execute(f"PRAGMA temp_directory='{temp_dir.as_posix()}'")
    connection.execute(copy_sql)

    row_count = int(
        connection.execute(
            f"SELECT COUNT(*)::BIGINT FROM read_parquet('{output_path.as_posix()}')"
        ).fetchone()[0]
    )
    schema_rows = connection.execute(
        f"DESCRIBE SELECT * FROM read_parquet('{output_path.as_posix()}')"
    ).fetchall()
    featured_filter_cache = build_filter_cache(
        connection=connection,
        output_path=output_path,
        dataset=dataset,
        max_filter_options=app_settings.downloads.max_filter_options,
    )
    connection.close()

    metadata = {
        "dataset": dataset_key,
        "label": dataset.label,
        "source_csv_path": str(source_csv_path),
        "parquet_path": str(output_path),
        "row_count": row_count,
        "column_count": len(schema_rows),
        "columns": [{"name": row[0], "duckdb_type": row[1]} for row in schema_rows],
        "featured_filter_cache": featured_filter_cache,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "sample_rows": args.sample_rows if args.sample_rows else None,
    }
    metadata_path = output_path.with_suffix(".metadata.json")
    metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    return metadata


def choose_datasets(app_settings: AppSettings, only: str) -> list[tuple[str, DatasetSettings]]:
    if only == "all":
        return list(app_settings.datasets.items())
    return [(only, app_settings.datasets[only])]


def main() -> int:
    args = parse_args()
    config_root = Path(args.config).resolve().parents[1]
    app_settings = load_settings(config_root)

    selected_datasets = choose_datasets(app_settings, args.only)
    print(f"Atualizando {len(selected_datasets)} dataset(s)...")

    for dataset_key, dataset in selected_datasets:
        print(f"[{dataset_key}] lendo {resolve_source_path(dataset_key, dataset, args)}")
        metadata = convert_dataset(dataset_key, dataset, args, app_settings)
        print(
            f"[{dataset_key}] parquet criado em {metadata['parquet_path']} "
            f"com {metadata['row_count']} linhas e {metadata['column_count']} colunas."
        )

    print("Processo concluído.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
