from __future__ import annotations

import asyncio
from datetime import date, datetime
import json
import math
from pathlib import Path
import sys
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from download_emendas.auth import AccessTokenStore
from download_emendas.export_service import dataframe_to_csv_bytes, dataframe_to_excel_bytes
from download_emendas.query_service import ParquetQueryService
from download_emendas.settings import AppSettings, DatasetSettings, load_settings


templates = Jinja2Templates(directory=str(ROOT_DIR / "templates"))
settings = load_settings(ROOT_DIR)
token_store = AccessTokenStore(settings.auth.tokens_path)
services = {
    dataset_key: ParquetQueryService(dataset, threads=settings.engine.threads)
    for dataset_key, dataset in settings.datasets.items()
}
metadata_cache: dict[str, tuple[int | None, dict[str, Any]]] = {}


def normalize_value(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float) and not math.isfinite(value):
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    if isinstance(value, datetime):
        return value.isoformat(sep=" ")
    if isinstance(value, date):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return normalize_value(value.item())
        except Exception:
            return str(value)
    return value


def get_dataset(dataset_key: str) -> DatasetSettings:
    if dataset_key not in settings.datasets:
        raise KeyError(f"Dataset inválido: {dataset_key}")
    return settings.datasets[dataset_key]


def get_service(dataset_key: str) -> ParquetQueryService:
    return services[dataset_key]


def load_dataset_metadata(dataset_key: str) -> dict[str, Any]:
    service = get_service(dataset_key)
    metadata_path = service.metadata_path()
    if metadata_path.exists():
        metadata_version = metadata_path.stat().st_mtime_ns
        cached = metadata_cache.get(dataset_key)
        if cached and cached[0] == metadata_version:
            return cached[1]

        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        metadata_cache[dataset_key] = (metadata_version, metadata)
        return metadata

    dataset = get_dataset(dataset_key)
    columns = [
        {"name": column.name, "duckdb_type": column.duckdb_type}
        for column in service.describe_columns()
    ]
    metadata = {
        "dataset": dataset_key,
        "label": dataset.label,
        "parquet_path": str(dataset.parquet_path),
        "source_csv_path": str(dataset.source_csv_path),
        "row_count": service.total_rows(),
        "column_count": len(columns),
        "columns": columns,
        "featured_filter_cache": {},
        "generated_at_utc": None,
        "sample_rows": None,
    }
    metadata_cache[dataset_key] = (None, metadata)
    return metadata


def available_columns(dataset_key: str) -> list[str]:
    return [column["name"] for column in load_dataset_metadata(dataset_key)["columns"]]


def is_authorized(request: Request) -> bool:
    if not settings.auth.enabled:
        return True
    return token_store.verify(request.cookies.get(settings.auth.cookie_name))


def unauthorized_page_response() -> RedirectResponse:
    return RedirectResponse("/login", status_code=303)


def unauthorized_api_response() -> JSONResponse:
    return JSONResponse({"error": "Sessao expirada ou token invalido.", "redirect": "/login"}, status_code=401)


def build_bootstrap_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "title": settings.title,
        "subtitle": settings.subtitle,
        "authEnabled": settings.auth.enabled,
        "downloads": {
            "maxRows": settings.downloads.max_rows,
            "maxColumns": settings.downloads.max_columns,
            "previewRows": settings.downloads.preview_rows,
            "maxFilterOptions": settings.downloads.max_filter_options,
        },
        "datasets": {},
    }

    for dataset_key, dataset in settings.datasets.items():
        metadata = load_dataset_metadata(dataset_key)
        columns = [column["name"] for column in metadata["columns"]]
        payload["datasets"][dataset_key] = {
            "key": dataset_key,
            "label": dataset.label,
            "description": dataset.description,
            "parquetPath": str(dataset.parquet_path),
            "sourceCsvPath": str(dataset.source_csv_path),
            "rowCount": metadata["row_count"],
            "columnCount": metadata["column_count"],
            "generatedAtUtc": metadata.get("generated_at_utc"),
            "sampleRows": metadata.get("sample_rows"),
            "columns": columns,
            "defaultColumns": [column for column in dataset.default_columns if column in columns],
            "featuredFilters": [column for column in dataset.featured_filters if column in columns],
            "filterColumns": [column for column in dataset.filter_columns if column in columns],
            "defaultSort": dataset.default_sort if dataset.default_sort in columns else "",
            "defaultSortDesc": dataset.default_sort_desc,
            "columnKinds": {column: dataset.column_kind(column) for column in dataset.filter_columns if column in columns},
        }
    return payload


def clamp_selected_columns(dataset_key: str, selected_columns: list[str]) -> list[str]:
    known_columns = set(available_columns(dataset_key))
    cleaned = [column for column in selected_columns if column in known_columns]
    return cleaned[: settings.downloads.max_columns]


def normalize_filters(dataset_key: str, raw_filters: dict[str, Any]) -> dict[str, dict[str, Any]]:
    dataset = get_dataset(dataset_key)
    known_columns = set(available_columns(dataset_key))
    normalized: dict[str, dict[str, Any]] = {}

    for column_name, payload in raw_filters.items():
        if column_name not in known_columns or not isinstance(payload, dict):
            continue

        if "values" in payload:
            values = payload.get("values") or []
            normalized[column_name] = {"kind": "categorical", "values": values}
            continue

        kind = dataset.column_kind(column_name)
        if kind == "search":
            value = str(payload.get("value", "")).strip()
            normalized[column_name] = {"kind": "search", "value": value}
        elif kind == "numeric":
            normalized[column_name] = {
                "kind": "numeric",
                "min": payload.get("min"),
                "max": payload.get("max"),
            }
        elif kind == "date":
            normalized[column_name] = {
                "kind": "date",
                "start": payload.get("start"),
                "end": payload.get("end"),
            }
    return normalized


def serialize_frame(dataframe) -> list[dict[str, Any]]:
    rows = dataframe.to_dict(orient="records")
    return [{key: normalize_value(value) for key, value in row.items()} for row in rows]


async def homepage(request: Request) -> HTMLResponse:
    if not is_authorized(request):
        return unauthorized_page_response()

    return templates.TemplateResponse(
        request,
        "index.html",
        {
            "request": request,
            "bootstrap_json": json.dumps(build_bootstrap_payload(), ensure_ascii=False),
            "auth_enabled": settings.auth.enabled,
        },
    )


async def healthcheck(_: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def login_page(request: Request) -> HTMLResponse | RedirectResponse:
    if not settings.auth.enabled:
        return RedirectResponse("/", status_code=303)
    if is_authorized(request):
        return RedirectResponse("/", status_code=303)

    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "request": request,
            "title": settings.title,
            "subtitle": settings.subtitle,
            "error": request.query_params.get("error", ""),
        },
    )


async def login_submit(request: Request) -> RedirectResponse:
    if not settings.auth.enabled:
        return RedirectResponse("/", status_code=303)

    form = await request.form()
    raw_token = str(form.get("token", "")).strip()
    if not token_store.verify(raw_token):
        return RedirectResponse("/login?error=token", status_code=303)

    response = RedirectResponse("/", status_code=303)
    response.set_cookie(
        settings.auth.cookie_name,
        raw_token,
        httponly=True,
        samesite="lax",
        secure=request.url.scheme == "https",
        max_age=60 * 60 * 24 * 30,
    )
    return response


async def logout(request: Request) -> RedirectResponse:
    response = RedirectResponse("/login", status_code=303)
    response.delete_cookie(settings.auth.cookie_name)
    return response


async def filter_metadata(request: Request) -> JSONResponse:
    if not is_authorized(request):
        return unauthorized_api_response()

    dataset_key = request.path_params["dataset_key"]
    column_name = request.path_params["column_name"]
    dataset = get_dataset(dataset_key)
    service = get_service(dataset_key)
    kind = dataset.column_kind(column_name)
    metadata = load_dataset_metadata(dataset_key)
    cached_filter = metadata.get("featured_filter_cache", {}).get(column_name)

    if cached_filter:
        return JSONResponse(cached_filter)

    if kind in {"categorical", "search"}:
        values = await asyncio.to_thread(
            service.get_distinct_values,
            column_name,
            settings.downloads.max_filter_options,
        )
        return JSONResponse(
            {
                "kind": "options",
                "originalKind": kind,
                "values": [normalize_value(value) for value in values],
                "limitedTo": settings.downloads.max_filter_options,
            }
        )
    if kind == "numeric":
        minimum, maximum = await asyncio.to_thread(service.get_numeric_bounds, column_name)
        return JSONResponse({"kind": kind, "min": minimum, "max": maximum})
    if kind == "date":
        start, end = await asyncio.to_thread(service.get_date_bounds, column_name)
        return JSONResponse(
            {
                "kind": kind,
                "start": normalize_value(start),
                "end": normalize_value(end),
            }
        )
    return JSONResponse({"kind": kind})


async def preview_query(request: Request) -> JSONResponse:
    if not is_authorized(request):
        return unauthorized_api_response()

    payload = await request.json()
    dataset_key = payload["dataset"]
    selected_columns = clamp_selected_columns(dataset_key, payload.get("selectedColumns", []))
    if not selected_columns:
        return JSONResponse({"error": "Selecione ao menos uma coluna."}, status_code=400)

    filters = normalize_filters(dataset_key, payload.get("filters", {}))
    sort_by = payload.get("sortBy") or None
    sort_desc = bool(payload.get("sortDesc", True))
    service = get_service(dataset_key)

    preview_rows = min(settings.downloads.max_rows, settings.downloads.preview_rows)
    dataframe, total_rows = await asyncio.gather(
        asyncio.to_thread(
            service.fetch_frame,
            selected_columns,
            filters,
            preview_rows,
            sort_by,
            sort_desc,
        ),
        asyncio.to_thread(service.count_rows, filters),
    )
    export_rows = min(total_rows, settings.downloads.max_rows)

    warnings: list[str] = []
    if len(payload.get("selectedColumns", [])) > settings.downloads.max_columns:
        warnings.append(
            f"O limite atual é de {settings.downloads.max_columns} colunas. "
            "A extração vai usar apenas as primeiras colunas selecionadas."
        )
    if total_rows > settings.downloads.max_rows:
        warnings.append(
            f"Foram encontrados {total_rows} registros, mas o download está limitado "
            f"a {settings.downloads.max_rows} linhas."
        )

    return JSONResponse(
        {
            "dataset": dataset_key,
            "selectedColumns": selected_columns,
            "totalRows": total_rows,
            "exportRows": export_rows,
            "previewRows": len(dataframe),
            "warnings": warnings,
            "rows": serialize_frame(dataframe),
        }
    )


async def export_file(request: Request) -> Response:
    if not is_authorized(request):
        return unauthorized_api_response()

    payload = await request.json()
    dataset_key = payload["dataset"]
    selected_columns = clamp_selected_columns(dataset_key, payload.get("selectedColumns", []))
    if not selected_columns:
        return JSONResponse({"error": "Selecione ao menos uma coluna."}, status_code=400)

    filters = normalize_filters(dataset_key, payload.get("filters", {}))
    sort_by = payload.get("sortBy") or None
    sort_desc = bool(payload.get("sortDesc", True))
    service = get_service(dataset_key)
    dataframe = await asyncio.to_thread(
        service.fetch_frame,
        selected_columns,
        filters,
        settings.downloads.max_rows,
        sort_by,
        sort_desc,
    )

    timestamp = datetime.now().strftime("%Y%m%d_%H%M")
    export_format = request.path_params["export_format"]
    if export_format == "csv":
        content = await asyncio.to_thread(dataframe_to_csv_bytes, dataframe)
        media_type = "text/csv"
        file_name = f"{dataset_key}_{timestamp}.csv"
    else:
        content = await asyncio.to_thread(dataframe_to_excel_bytes, dataframe)
        media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        file_name = f"{dataset_key}_{timestamp}.xlsx"

    return Response(
        content,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{file_name}"'},
    )


routes = [
    Route("/", homepage),
    Route("/api/health", healthcheck),
    Route("/login", login_page, methods=["GET"]),
    Route("/login", login_submit, methods=["POST"]),
    Route("/logout", logout, methods=["POST"]),
    Route("/api/datasets/{dataset_key}/filters/{column_name}", filter_metadata),
    Route("/api/query", preview_query, methods=["POST"]),
    Route("/api/export/{export_format}", export_file, methods=["POST"]),
    Mount("/static", app=StaticFiles(directory=str(ROOT_DIR / "static")), name="static"),
]

app = Starlette(debug=True, routes=routes)
