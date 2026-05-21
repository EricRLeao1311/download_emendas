from __future__ import annotations

import csv
from pathlib import Path
import sys
import tempfile
import unittest

import duckdb

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from download_emendas.query_service import ParquetQueryService
from download_emendas.settings import DatasetSettings
from scripts.update_parquets import build_select_sql, read_headers


class PipelineTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.base_path = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _dataset(self, parquet_name: str) -> DatasetSettings:
        return DatasetSettings(
            key="documentos",
            label="Documentos",
            description="Teste",
            parquet_path=self.base_path / parquet_name,
            source_csv_path=self.base_path / "fonte.csv",
            default_sort="data_movimento",
            default_sort_desc=True,
            default_columns=("documento", "fase"),
            featured_filters=("fase",),
            categorical_filters=("fase",),
            search_filters=("documento",),
            numeric_filters=("valor_pago",),
            integer_columns=frozenset({"ano"}),
            numeric_columns=frozenset({"valor_pago"}),
            date_columns=frozenset({"data_movimento"}),
            timestamp_columns=frozenset({"data_carga"}),
        )

    def test_build_select_sql_casts_expected_types(self) -> None:
        dataset = self._dataset("saida.parquet")
        select_sql = build_select_sql(
            ["documento", "data_movimento", "valor_pago", "data_carga"],
            dataset,
        )
        self.assertIn('TRY_CAST(NULLIF(TRIM("data_movimento"), \'\') AS DATE)', select_sql)
        self.assertIn('TRY_CAST(REPLACE(NULLIF(TRIM("ano"), \'\'), \',\', \'.\') AS BIGINT)', build_select_sql(["ano"], dataset))
        self.assertIn('TRY_CAST(REPLACE(NULLIF(TRIM("valor_pago"), \'\'), \',\', \'.\') AS DOUBLE)', select_sql)
        self.assertIn('TRY_CAST(NULLIF(TRIM("data_carga"), \'\') AS TIMESTAMP)', select_sql)

    def test_query_service_filters_data(self) -> None:
        csv_path = self.base_path / "fonte.csv"
        parquet_path = self.base_path / "saida.parquet"
        with csv_path.open("w", encoding="utf-8", newline="") as csv_file:
            writer = csv.writer(csv_file)
            writer.writerow(["documento", "fase", "valor_pago", "data_movimento", "data_carga", "ano"])
            writer.writerow(["DOC1", "PAGAMENTO", "10.5", "2024-01-01", "2024-01-01 10:00:00", "2024"])
            writer.writerow(["DOC2", "EMPENHO", "25.0", "2024-01-10", "2024-01-10 10:00:00", "2024"])

        dataset = self._dataset("saida.parquet")
        headers = read_headers(csv_path)
        select_sql = build_select_sql(headers, dataset)
        connection = duckdb.connect(database=":memory:")
        connection.execute(
            f"""
            COPY (
                SELECT {select_sql}
                FROM read_csv_auto('{csv_path.as_posix()}', header=true, all_varchar=true)
            )
            TO '{parquet_path.as_posix()}'
            (FORMAT PARQUET)
            """
        )
        connection.close()

        service = ParquetQueryService(dataset)
        count = service.count_rows({"fase": {"kind": "categorical", "values": ["PAGAMENTO"]}})
        self.assertEqual(count, 1)

        dataframe = service.fetch_frame(
            selected_columns=["documento", "valor_pago"],
            filters={"documento": {"kind": "search", "value": "DOC"}},
            row_limit=10,
            sort_column="valor_pago",
            sort_desc=True,
        )
        self.assertEqual(list(dataframe["documento"]), ["DOC2", "DOC1"])


if __name__ == "__main__":
    unittest.main()
