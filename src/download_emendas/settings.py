from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import tomllib


@dataclass(frozen=True)
class DownloadSettings:
    max_rows: int
    max_columns: int
    preview_rows: int
    max_filter_options: int


@dataclass(frozen=True)
class EngineSettings:
    threads: int


@dataclass(frozen=True)
class AuthSettings:
    enabled: bool
    cookie_name: str
    tokens_path: Path


@dataclass(frozen=True)
class DatasetSettings:
    key: str
    label: str
    description: str
    parquet_path: Path
    source_csv_path: Path
    default_sort: str
    default_sort_desc: bool
    default_columns: tuple[str, ...]
    featured_filters: tuple[str, ...]
    categorical_filters: tuple[str, ...]
    search_filters: tuple[str, ...]
    numeric_filters: tuple[str, ...]
    integer_columns: frozenset[str]
    numeric_columns: frozenset[str]
    date_columns: frozenset[str]
    timestamp_columns: frozenset[str]

    @property
    def filter_columns(self) -> tuple[str, ...]:
        ordered: list[str] = []
        for column in (
            *self.featured_filters,
            *self.categorical_filters,
            *self.search_filters,
            *self.numeric_filters,
            *sorted(self.date_columns),
        ):
            if column not in ordered:
                ordered.append(column)
        return tuple(ordered)

    def column_kind(self, column_name: str) -> str:
        if column_name in self.date_columns or column_name in self.timestamp_columns:
            return "date"
        if column_name in self.numeric_filters:
            return "numeric"
        if column_name in self.categorical_filters:
            return "categorical"
        if column_name in self.search_filters:
            return "search"
        return "search"


@dataclass(frozen=True)
class AppSettings:
    root_dir: Path
    title: str
    subtitle: str
    downloads: DownloadSettings
    engine: EngineSettings
    auth: AuthSettings
    datasets: dict[str, DatasetSettings]


def _resolve_path(root_dir: Path, raw_value: str) -> Path:
    candidate = Path(raw_value)
    if candidate.is_absolute():
        return candidate
    return (root_dir / candidate).resolve()


def load_settings(root_dir: Path) -> AppSettings:
    config_path = root_dir / "config" / "app.toml"
    with config_path.open("rb") as config_file:
        config = tomllib.load(config_file)

    auth_config = config.get("auth", {})

    datasets: dict[str, DatasetSettings] = {}
    for key, dataset_config in config["datasets"].items():
        datasets[key] = DatasetSettings(
            key=key,
            label=dataset_config["label"],
            description=dataset_config["description"],
            parquet_path=_resolve_path(root_dir, dataset_config["parquet_path"]),
            source_csv_path=_resolve_path(root_dir, dataset_config["source_csv_path"]),
            default_sort=dataset_config["default_sort"],
            default_sort_desc=dataset_config["default_sort_desc"],
            default_columns=tuple(dataset_config["default_columns"]),
            featured_filters=tuple(dataset_config["featured_filters"]),
            categorical_filters=tuple(dataset_config["categorical_filters"]),
            search_filters=tuple(dataset_config["search_filters"]),
            numeric_filters=tuple(dataset_config["numeric_filters"]),
            integer_columns=frozenset(dataset_config["integer_columns"]),
            numeric_columns=frozenset(dataset_config["numeric_columns"]),
            date_columns=frozenset(dataset_config["date_columns"]),
            timestamp_columns=frozenset(dataset_config["timestamp_columns"]),
        )

    return AppSettings(
        root_dir=root_dir,
        title=config["ui"]["title"],
        subtitle=config["ui"]["subtitle"],
        downloads=DownloadSettings(**config["downloads"]),
        engine=EngineSettings(**config["engine"]),
        auth=AuthSettings(
            enabled=bool(auth_config.get("enabled", False)),
            cookie_name=str(auth_config.get("cookie_name", "emendas_access_token")),
            tokens_path=_resolve_path(root_dir, str(auth_config.get("tokens_path", "config/access_tokens.json"))),
        ),
        datasets=datasets,
    )
