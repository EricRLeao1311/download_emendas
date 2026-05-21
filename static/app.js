const bootstrap = window.__APP_BOOTSTRAP__;
const AUTO_PREVIEW_DELAY_MS = 250;

const state = {
  datasetKey: Object.keys(bootstrap.datasets)[0],
  selectedColumns: [],
  activeFilters: [],
  filterValues: {},
  filterMetadata: {},
  filterSearchTerms: {},
  filterMetadataPending: {},
  lastQuery: null,
  queryStale: false,
  openFilter: null,
  sortBy: "",
  sortDesc: true,
  previewTimer: null,
  previewAbortController: null,
  requestSerial: 0,
  dragColumn: null,
};

const elements = {
  datasetButtons: document.getElementById("dataset-buttons"),
  limitRows: document.getElementById("limit-rows"),
  limitColumns: document.getElementById("limit-columns"),
  limitPreview: document.getElementById("limit-preview"),
  heroTitle: document.getElementById("hero-title"),
  heroSubtitle: document.getElementById("hero-subtitle"),
  heroStatus: document.getElementById("hero-status"),
  datasetLabel: document.getElementById("dataset-label"),
  datasetDescription: document.getElementById("dataset-description"),
  datasetParquet: document.getElementById("dataset-parquet"),
  datasetSource: document.getElementById("dataset-source"),
  metricRows: document.getElementById("metric-rows"),
  metricColumns: document.getElementById("metric-columns"),
  metricSelectedColumns: document.getElementById("metric-selected-columns"),
  metricFound: document.getElementById("metric-found"),
  metricExport: document.getElementById("metric-export"),
  metricUpdated: document.getElementById("metric-updated"),
  addFilterSelect: document.getElementById("add-filter-select"),
  clearFilters: document.getElementById("clear-filters"),
  filtersContainer: document.getElementById("filters-container"),
  columnSearch: document.getElementById("column-search"),
  restoreDefaultColumns: document.getElementById("restore-default-columns"),
  clearColumns: document.getElementById("clear-columns"),
  selectedColumnsSummary: document.getElementById("selected-columns-summary"),
  selectedColumnsCount: document.getElementById("selected-columns-count"),
  columnChipList: document.getElementById("column-chip-list"),
  sortSelect: document.getElementById("sort-select"),
  sortDesc: document.getElementById("sort-desc"),
  previewButton: document.getElementById("preview-button"),
  downloadCsv: document.getElementById("download-csv"),
  downloadXlsx: document.getElementById("download-xlsx"),
  warningBox: document.getElementById("warning-box"),
  previewTableHead: document.querySelector("#preview-table thead"),
  previewTableBody: document.querySelector("#preview-table tbody"),
};

function currentDataset() {
  return bootstrap.datasets[state.datasetKey];
}

function redirectToLogin() {
  window.location.href = "/login";
}

function filterKind(column) {
  const originalKind = currentDataset().columnKinds[column];
  if (originalKind === "numeric" || originalKind === "date") {
    return originalKind;
  }
  return "options";
}

function defaultActiveFilters(dataset) {
  return [...dataset.featuredFilters];
}

function formatNumber(value) {
  return new Intl.NumberFormat("pt-BR").format(value || 0);
}

function formatDate(value) {
  if (!value) return "Ainda nao registrado";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString("pt-BR");
}

function sanitizeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function truncateText(value, length = 30) {
  if (!value) return "";
  return value.length > length ? `${value.slice(0, length - 1)}…` : value;
}

function valuesEqual(left, right) {
  if (left.length !== right.length) return false;
  return left.every((value, index) => value === right[index]);
}

function clearScheduledPreview() {
  if (state.previewTimer) {
    clearTimeout(state.previewTimer);
    state.previewTimer = null;
  }
}

function cancelPendingPreview() {
  if (!state.previewAbortController) {
    return;
  }
  state.previewAbortController.abort();
  state.previewAbortController = null;
}

function markQueryDirty() {
  state.queryStale = true;
  renderHeaderArea();
  renderPreviewTable(null);
}

function schedulePreview() {
  clearScheduledPreview();
  if (!state.selectedColumns.length) {
    markQueryDirty();
    return;
  }

  markQueryDirty();
  state.previewTimer = window.setTimeout(() => {
    void runPreview();
  }, AUTO_PREVIEW_DELAY_MS);
}

function setSortDefaults(dataset) {
  state.sortBy = dataset.defaultSort && dataset.defaultColumns.includes(dataset.defaultSort)
    ? dataset.defaultSort
    : dataset.defaultColumns[0] || "";
  state.sortDesc = dataset.defaultSortDesc;
}

async function setDataset(datasetKey) {
  cancelPendingPreview();
  clearScheduledPreview();
  state.datasetKey = datasetKey;
  state.selectedColumns = [...currentDataset().defaultColumns];
  state.activeFilters = defaultActiveFilters(currentDataset());
  state.filterValues = {};
  state.filterSearchTerms = {};
  state.lastQuery = null;
  state.queryStale = true;
  state.openFilter = null;
  elements.columnSearch.value = "";
  setSortDefaults(currentDataset());
  await render();
}

function renderHeaderArea() {
  const dataset = currentDataset();
  const query = state.lastQuery && !state.queryStale ? state.lastQuery : null;

  elements.limitRows.textContent = formatNumber(bootstrap.downloads.maxRows);
  elements.limitColumns.textContent = formatNumber(bootstrap.downloads.maxColumns);
  elements.limitPreview.textContent = `${formatNumber(bootstrap.downloads.previewRows)} linhas`;

  elements.datasetButtons.innerHTML = Object.values(bootstrap.datasets)
    .map((entry) => {
      const activeClass = entry.key === state.datasetKey ? "is-active" : "";
      return `<button class="dataset-button ${activeClass}" data-dataset="${entry.key}" type="button">${sanitizeHtml(entry.label)}</button>`;
    })
    .join("");

  elements.heroTitle.textContent = bootstrap.title;
  elements.heroSubtitle.textContent = bootstrap.subtitle;
  elements.heroStatus.textContent = dataset.sampleRows
    ? `Amostra ativa: ${formatNumber(dataset.sampleRows)} linhas`
    : "Parquet completo carregado";

  elements.datasetLabel.textContent = dataset.label;
  elements.datasetDescription.textContent = dataset.description;
  elements.datasetParquet.textContent = dataset.parquetPath;
  elements.datasetSource.textContent = dataset.sourceCsvPath;

  elements.metricRows.textContent = formatNumber(dataset.rowCount);
  elements.metricColumns.textContent = formatNumber(dataset.columnCount);
  elements.metricSelectedColumns.textContent = formatNumber(state.selectedColumns.length);
  elements.metricFound.textContent = query ? formatNumber(query.totalRows) : "--";
  elements.metricExport.textContent = query ? formatNumber(query.exportRows) : "--";
  elements.metricUpdated.textContent = formatDate(dataset.generatedAtUtc);
}

function renderAddFilterSelect() {
  const remainingFilters = currentDataset().filterColumns.filter((column) => !state.activeFilters.includes(column));
  elements.addFilterSelect.innerHTML = [
    '<option value="">Adicionar filtro</option>',
    ...remainingFilters.map((column) => `<option value="${sanitizeHtml(column)}">${sanitizeHtml(column)}</option>`),
  ].join("");
}

function ensureValidSortSelection() {
  if (!state.selectedColumns.length) {
    state.sortBy = "";
    return;
  }

  if (!state.sortBy || !state.selectedColumns.includes(state.sortBy)) {
    state.sortBy = state.selectedColumns[0];
  }
}

function renderSortControls() {
  ensureValidSortSelection();
  if (!state.selectedColumns.length) {
    elements.sortSelect.innerHTML = '<option value="">Selecione uma coluna</option>';
    elements.sortSelect.disabled = true;
    elements.sortDesc.disabled = true;
    return;
  }

  elements.sortSelect.disabled = false;
  elements.sortDesc.disabled = false;
  elements.sortSelect.innerHTML = state.selectedColumns
    .map((column) => {
      const selected = column === state.sortBy ? "selected" : "";
      return `<option value="${sanitizeHtml(column)}" ${selected}>${sanitizeHtml(column)}</option>`;
    })
    .join("");
  elements.sortDesc.checked = state.sortDesc;
}

function renderSelectedColumnsSummary() {
  elements.selectedColumnsCount.textContent = `${formatNumber(state.selectedColumns.length)} de ${formatNumber(
    bootstrap.downloads.maxColumns
  )}`;

  if (!state.selectedColumns.length) {
    elements.selectedColumnsSummary.innerHTML =
      '<span class="selected-column-pill--empty">Nenhuma coluna selecionada.</span>';
    return;
  }

  elements.selectedColumnsSummary.innerHTML = state.selectedColumns
    .map(
      (column) => `
        <div class="selected-column-pill" draggable="true" data-selected-column="${column}">
          <span class="selected-column-pill__handle" title="Arraste para mudar a ordem">::</span>
          <span class="selected-column-pill__label">${sanitizeHtml(column)}</span>
          <button type="button" data-remove-column="${column}" aria-label="Remover coluna ${sanitizeHtml(column)}">x</button>
        </div>
      `
    )
    .join("");
}

function renderAvailableColumns() {
  const search = elements.columnSearch.value.trim().toLowerCase();
  const availableColumns = currentDataset().columns.filter((column) => !state.selectedColumns.includes(column));
  const filteredColumns = availableColumns.filter((column) => column.toLowerCase().includes(search));

  if (!filteredColumns.length) {
    elements.columnChipList.innerHTML =
      '<span class="selected-column-pill--empty">Nenhuma coluna disponivel com esse filtro.</span>';
    return;
  }

  const maxReached = state.selectedColumns.length >= bootstrap.downloads.maxColumns;
  elements.columnChipList.innerHTML = filteredColumns
    .map((column) => {
      const disabledClass = maxReached ? "is-disabled" : "";
      return `
        <button class="column-button ${disabledClass}" data-column="${column}" type="button" ${maxReached ? "disabled" : ""}>
          ${sanitizeHtml(column)}
        </button>
      `;
    })
    .join("");
}

function summarizeFilter(column, kind) {
  const value = state.filterValues[column] || {};

  if (kind === "options") {
    const selectedValues = value.values || [];
    if (!selectedValues.length) return "Todos";
    if (selectedValues.length === 1) return truncateText(String(selectedValues[0]), 24);
    return `${selectedValues.length} selecionados`;
  }

  if (kind === "numeric") {
    const hasMin = value.min != null && value.min !== "";
    const hasMax = value.max != null && value.max !== "";
    if (!hasMin && !hasMax) return "Todos";
    return `${hasMin ? value.min : "min"} ate ${hasMax ? value.max : "max"}`;
  }

  if (kind === "date") {
    if (!value.start && !value.end) return "Todos";
    return `${value.start || "inicio"} ate ${value.end || "fim"}`;
  }

  return "Todos";
}

async function fetchFilterMetadata(column) {
  state.filterMetadata[state.datasetKey] ||= {};
  if (state.filterMetadata[state.datasetKey][column]) {
    return state.filterMetadata[state.datasetKey][column];
  }

  state.filterMetadataPending[state.datasetKey] ||= {};
  if (state.filterMetadataPending[state.datasetKey][column]) {
    return state.filterMetadataPending[state.datasetKey][column];
  }

  state.filterMetadataPending[state.datasetKey][column] = fetch(
    `/api/datasets/${state.datasetKey}/filters/${column}`
  )
    .then(async (response) => {
      const payload = await response.json();
      if (response.status === 401) {
        redirectToLogin();
        throw new Error("unauthorized");
      }
      return payload;
    })
    .then((payload) => {
      state.filterMetadata[state.datasetKey][column] = payload;
      return payload;
    })
    .finally(() => {
      delete state.filterMetadataPending[state.datasetKey][column];
    });

  return state.filterMetadataPending[state.datasetKey][column];
}

function getFilteredOptionValues(column, meta) {
  const term = (state.filterSearchTerms[column] || "").trim().toLowerCase();
  const values = meta.values || [];
  if (!term) return values;
  return values.filter((value) => String(value).toLowerCase().includes(term));
}

function buildOptionsPopover(column, meta) {
  const selectedValues = new Set((state.filterValues[column]?.values || []).map(String));
  const filteredValues = getFilteredOptionValues(column, meta);
  const optionRows = filteredValues.length
    ? filteredValues
        .map((value) => {
          const raw = String(value);
          const checked = selectedValues.has(raw) ? "checked" : "";
          const checkedClass = checked ? "is-checked" : "";
          return `
            <label class="option-item ${checkedClass}" data-option-row="${column}">
              <input type="checkbox" data-filter-input="${column}" data-kind="options" value="${sanitizeHtml(raw)}" ${checked} />
              <span>${sanitizeHtml(raw)}</span>
            </label>
          `;
        })
        .join("")
    : '<div class="option-empty">Nenhum valor encontrado.</div>';

  return `
    <div class="filter-popover" data-filter-popover="${column}">
      <div class="filter-popover__head">
        <strong>${sanitizeHtml(column)}</strong>
        <button class="ghost-button ghost-button--small" type="button" data-remove-filter="${column}">Remover</button>
      </div>
      <input
        type="search"
        data-option-search="${column}"
        value="${sanitizeHtml(state.filterSearchTerms[column] || "")}"
        placeholder="Pesquisar valor"
      />
      <div class="filter-popover__meta">${selectedValues.size} selecionado(s)</div>
      <div class="option-list">${optionRows}</div>
      <div class="filter-popover__actions">
        <button class="ghost-button ghost-button--small" type="button" data-filter-clear="${column}">Limpar</button>
      </div>
    </div>
  `;
}

function buildNumericPopover(column, meta) {
  const savedValue = state.filterValues[column] || {};
  return `
    <div class="filter-popover" data-filter-popover="${column}">
      <div class="filter-popover__head">
        <strong>${sanitizeHtml(column)}</strong>
        <button class="ghost-button ghost-button--small" type="button" data-remove-filter="${column}">Remover</button>
      </div>
      <div class="popover-range">
        <label class="control-field">
          <span>Minimo</span>
          <input type="number" step="any" data-filter-input="${column}" data-kind="numeric" data-boundary="min" value="${savedValue.min ?? meta.min ?? ""}" />
        </label>
        <label class="control-field">
          <span>Maximo</span>
          <input type="number" step="any" data-filter-input="${column}" data-kind="numeric" data-boundary="max" value="${savedValue.max ?? meta.max ?? ""}" />
        </label>
      </div>
      <div class="filter-popover__actions">
        <button class="ghost-button ghost-button--small" type="button" data-filter-clear="${column}">Limpar</button>
      </div>
    </div>
  `;
}

function buildDatePopover(column, meta) {
  const savedValue = state.filterValues[column] || {};
  return `
    <div class="filter-popover" data-filter-popover="${column}">
      <div class="filter-popover__head">
        <strong>${sanitizeHtml(column)}</strong>
        <button class="ghost-button ghost-button--small" type="button" data-remove-filter="${column}">Remover</button>
      </div>
      <div class="popover-range">
        <label class="control-field">
          <span>De</span>
          <input type="date" data-filter-input="${column}" data-kind="date" data-boundary="start" value="${savedValue.start ?? meta.start ?? ""}" />
        </label>
        <label class="control-field">
          <span>Ate</span>
          <input type="date" data-filter-input="${column}" data-kind="date" data-boundary="end" value="${savedValue.end ?? meta.end ?? ""}" />
        </label>
      </div>
      <div class="filter-popover__actions">
        <button class="ghost-button ghost-button--small" type="button" data-filter-clear="${column}">Limpar</button>
      </div>
    </div>
  `;
}

async function renderFilterTiles() {
  const tiles = await Promise.all(
    state.activeFilters.map(async (column) => {
      const kind = filterKind(column);
      let popover = "";
      if (state.openFilter === column) {
        const meta = await fetchFilterMetadata(column);
        if (kind === "options") {
          popover = buildOptionsPopover(column, meta);
        } else if (kind === "numeric") {
          popover = buildNumericPopover(column, meta);
        } else if (kind === "date") {
          popover = buildDatePopover(column, meta);
        }
      }

      return `
        <div class="filter-tile ${state.openFilter === column ? "is-open" : ""}">
          <button class="filter-trigger" type="button" data-filter-trigger="${column}">
            <span class="filter-trigger__label">${sanitizeHtml(column)}</span>
            <span class="filter-trigger__value">${sanitizeHtml(summarizeFilter(column, kind))}</span>
            <span class="filter-trigger__arrow">${state.openFilter === column ? "▲" : "▼"}</span>
          </button>
          ${popover}
        </div>
      `;
    })
  );

  elements.filtersContainer.innerHTML = tiles.join("");
}

function restoreOpenFilterSearchFocus() {
  if (!state.openFilter) {
    return;
  }

  const searchInput = elements.filtersContainer.querySelector(
    `[data-option-search="${CSS.escape(state.openFilter)}"]`
  );
  if (!searchInput) {
    return;
  }

  const caretPosition = searchInput.value.length;
  searchInput.focus({ preventScroll: true });
  searchInput.setSelectionRange(caretPosition, caretPosition);
}

function updateOpenFilterPlacement() {
  if (!state.openFilter) {
    return;
  }

  const tile = elements.filtersContainer.querySelector(`[data-filter-trigger="${CSS.escape(state.openFilter)}"]`)?.closest(".filter-tile");
  if (!tile) {
    return;
  }

  const shouldAlignRight = tile.getBoundingClientRect().left + 360 > window.innerWidth - 32;
  tile.classList.toggle("is-popover-right", shouldAlignRight);
}

function updateQueryPreviewColumnsOnly() {
  if (!state.lastQuery || state.queryStale) {
    return;
  }
  state.lastQuery.selectedColumns = [...state.selectedColumns];
  renderSortControls();
  renderHeaderArea();
  renderPreviewTable(state.lastQuery);
}

function clearWarnings() {
  elements.warningBox.hidden = true;
  elements.warningBox.innerHTML = "";
}

function showWarnings(messages) {
  if (!messages || messages.length === 0) {
    clearWarnings();
    return;
  }
  elements.warningBox.hidden = false;
  elements.warningBox.innerHTML = `<ul>${messages.map((message) => `<li>${sanitizeHtml(message)}</li>`).join("")}</ul>`;
}

function buildTableHeader(columns) {
  return `<tr>${columns
    .map((column) => {
      const isSorted = state.sortBy === column;
      const arrow = isSorted ? (state.sortDesc ? " ▼" : " ▲") : "";
      return `<th class="sortable-header" data-sort-column="${column}">${sanitizeHtml(column)}${arrow}</th>`;
    })
    .join("")}</tr>`;
}

function renderPreviewTable(result) {
  if (!result) {
    const colspan = Math.max(state.selectedColumns.length, 1);
    elements.previewTableHead.innerHTML = state.selectedColumns.length ? buildTableHeader(state.selectedColumns) : "";
    elements.previewTableBody.innerHTML = `<tr><td class="empty-table" colspan="${colspan}">Aguardando atualizacao automatica da previa.</td></tr>`;
    return;
  }

  if (!result.rows || result.rows.length === 0) {
    const colspan = Math.max(result.selectedColumns.length, 1);
    elements.previewTableHead.innerHTML = buildTableHeader(result.selectedColumns);
    elements.previewTableBody.innerHTML = `<tr><td class="empty-table" colspan="${colspan}">Nenhum dado encontrado com os filtros atuais.</td></tr>`;
    return;
  }

  const columns = result.selectedColumns;
  elements.previewTableHead.innerHTML = buildTableHeader(columns);
  elements.previewTableBody.innerHTML = result.rows
    .map(
      (row) =>
        `<tr>${columns
          .map((column) => `<td title="${sanitizeHtml(row[column] ?? "")}">${sanitizeHtml(row[column] ?? "")}</td>`)
          .join("")}</tr>`
    )
    .join("");
}

function syncFilterValuesFromDom() {
  const nextValues = {};

  document.querySelectorAll("[data-filter-input]").forEach((input) => {
    const column = input.dataset.filterInput;
    const kind = input.dataset.kind;
    nextValues[column] ||= {};

    if (kind === "options") {
      nextValues[column].values ||= [];
      if (input.checked) {
        nextValues[column].values.push(input.value);
      }
      return;
    }

    if (kind === "numeric") {
      const rawValue = input.value.trim();
      nextValues[column][input.dataset.boundary] = rawValue === "" ? null : Number(rawValue);
      return;
    }

    if (kind === "date") {
      nextValues[column][input.dataset.boundary] = input.value || null;
    }
  });

  state.filterValues = { ...state.filterValues, ...nextValues };
}

function collectFilters() {
  syncFilterValuesFromDom();
  const filters = {};

  Object.entries(state.filterValues).forEach(([column, value]) => {
    if (!state.activeFilters.includes(column)) {
      return;
    }

    if (Array.isArray(value.values)) {
      if (value.values.length) {
        filters[column] = { values: value.values };
      }
      return;
    }

    if (Object.prototype.hasOwnProperty.call(value, "min") || Object.prototype.hasOwnProperty.call(value, "max")) {
      if (value.min != null || value.max != null) {
        filters[column] = { min: value.min, max: value.max };
      }
      return;
    }

    if (value.start || value.end) {
      filters[column] = { start: value.start, end: value.end };
    }
  });

  return filters;
}

function buildPayload() {
  ensureValidSortSelection();
  return {
    dataset: state.datasetKey,
    selectedColumns: state.selectedColumns,
    filters: collectFilters(),
    sortBy: state.sortBy,
    sortDesc: state.sortDesc,
  };
}

async function runPreview() {
  if (!state.selectedColumns.length) {
    showWarnings(["Selecione pelo menos uma coluna."]);
    return;
  }

  clearScheduledPreview();
  clearWarnings();

  const requestId = ++state.requestSerial;
  cancelPendingPreview();
  const abortController = new AbortController();
  state.previewAbortController = abortController;
  elements.previewButton.disabled = true;
  elements.previewButton.textContent = "Atualizando...";

  let response;
  let result;

  try {
    response = await fetch("/api/query", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(buildPayload()),
      signal: abortController.signal,
    });
    result = await response.json();
  } catch (error) {
    if (requestId !== state.requestSerial || error.name === "AbortError") {
      return;
    }

    showWarnings(["Nao foi possivel gerar a previa."]);
    return;
  } finally {
    if (state.previewAbortController === abortController) {
      state.previewAbortController = null;
    }
    if (requestId === state.requestSerial) {
      elements.previewButton.disabled = false;
      elements.previewButton.textContent = "Atualizar agora";
    }
  }

  if (requestId !== state.requestSerial) {
    return;
  }

  if (!response.ok) {
    if (response.status === 401) {
      redirectToLogin();
      return;
    }
    showWarnings([result.error || "Nao foi possivel gerar a previa."]);
    return;
  }

  state.lastQuery = result;
  state.queryStale = false;
  renderHeaderArea();
  renderSortControls();
  showWarnings(result.warnings);
  renderPreviewTable(result);
}

async function downloadFile(format) {
  if (!state.selectedColumns.length) {
    showWarnings(["Selecione pelo menos uma coluna antes de baixar."]);
    return;
  }

  const button = format === "csv" ? elements.downloadCsv : elements.downloadXlsx;
  button.disabled = true;
  button.textContent = format === "csv" ? "Gerando CSV..." : "Gerando Excel...";

  const response = await fetch(`/api/export/${format}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(buildPayload()),
  });

  button.disabled = false;
  button.textContent = format === "csv" ? "Baixar CSV" : "Baixar Excel";

  if (!response.ok) {
    const payload = await response.json();
    if (response.status === 401) {
      redirectToLogin();
      return;
    }
    showWarnings([payload.error || "Nao foi possivel gerar o arquivo."]);
    return;
  }

  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename=\"([^\"]+)\"/);
  const filename = match ? match[1] : `download.${format}`;
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function addColumn(column) {
  if (state.selectedColumns.includes(column)) {
    return;
  }
  if (state.selectedColumns.length >= bootstrap.downloads.maxColumns) {
    showWarnings([`O limite atual e de ${bootstrap.downloads.maxColumns} colunas.`]);
    return;
  }
  state.selectedColumns = [...state.selectedColumns, column];
  renderColumnsAndSort();
  schedulePreview();
}

function removeColumn(column) {
  state.selectedColumns = state.selectedColumns.filter((item) => item !== column);
  renderColumnsAndSort();
  schedulePreview();
}

function moveColumn(column, targetColumn) {
  if (!column || !targetColumn || column === targetColumn) {
    return;
  }

  const nextColumns = [...state.selectedColumns];
  const fromIndex = nextColumns.indexOf(column);
  const toIndex = nextColumns.indexOf(targetColumn);
  if (fromIndex === -1 || toIndex === -1) {
    return;
  }

  nextColumns.splice(fromIndex, 1);
  nextColumns.splice(toIndex, 0, column);
  state.selectedColumns = nextColumns;
  renderSelectedColumnsSummary();
  renderSortControls();
  updateQueryPreviewColumnsOnly();
}

function addFilter(column) {
  if (!column || state.activeFilters.includes(column)) {
    return;
  }
  state.activeFilters = [...state.activeFilters, column];
  state.openFilter = column;
  void renderFilters();
}

function removeFilter(column) {
  syncFilterValuesFromDom();
  state.activeFilters = state.activeFilters.filter((item) => item !== column);
  delete state.filterValues[column];
  delete state.filterSearchTerms[column];
  if (state.openFilter === column) {
    state.openFilter = null;
  }
  void renderFilters();
  schedulePreview();
}

function clearFilterValue(column) {
  delete state.filterValues[column];
  delete state.filterSearchTerms[column];
  void renderFilters();
  schedulePreview();
}

function updateOptionsFilter(column, value, checked) {
  const values = new Set((state.filterValues[column]?.values || []).map(String));
  if (checked) {
    values.add(value);
  } else {
    values.delete(value);
  }
  state.filterValues[column] = { values: [...values] };
}

function handleFilterSearch(column, term) {
  state.filterSearchTerms[column] = term;
  void renderFilters({ preserveSearchFocus: true });
}

function handleTableSort(column) {
  if (state.sortBy === column) {
    state.sortDesc = !state.sortDesc;
  } else {
    state.sortBy = column;
    state.sortDesc = false;
  }
  renderSortControls();
  schedulePreview();
}

function renderColumnsAndSort() {
  renderSelectedColumnsSummary();
  renderAvailableColumns();
  renderSortControls();
  renderHeaderArea();
}

async function renderFilters({ preserveSearchFocus = false } = {}) {
  renderAddFilterSelect();
  await renderFilterTiles();
  updateOpenFilterPlacement();
  if (preserveSearchFocus) {
    restoreOpenFilterSearchFocus();
  }
}

function bindGlobalClickClose() {
  document.addEventListener("click", (event) => {
    if (!state.openFilter) return;
    const insideFilters = event.target.closest(".filter-tile");
    if (insideFilters) return;
    state.openFilter = null;
    void renderFilters();
  });
}

function bindEvents() {
  elements.datasetButtons.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-dataset]");
    if (!button) return;
    await setDataset(button.dataset.dataset);
    await runPreview();
  });

  elements.addFilterSelect.addEventListener("change", (event) => {
    addFilter(event.target.value);
    event.target.value = "";
  });

  elements.clearFilters.addEventListener("click", () => {
    state.activeFilters = [];
    state.filterValues = {};
    state.filterSearchTerms = {};
    state.openFilter = null;
    void renderFilters();
    schedulePreview();
  });

  elements.filtersContainer.addEventListener("click", (event) => {
    const trigger = event.target.closest("[data-filter-trigger]");
    if (trigger) {
      const column = trigger.dataset.filterTrigger;
      state.openFilter = state.openFilter === column ? null : column;
      void renderFilters();
      return;
    }

    const removeButton = event.target.closest("[data-remove-filter]");
    if (removeButton) {
      removeFilter(removeButton.dataset.removeFilter);
      return;
    }

    const clearButton = event.target.closest("[data-filter-clear]");
    if (clearButton) {
      clearFilterValue(clearButton.dataset.filterClear);
    }
  });

  elements.filtersContainer.addEventListener("input", (event) => {
    const searchInput = event.target.closest("[data-option-search]");
    if (searchInput) {
      handleFilterSearch(searchInput.dataset.optionSearch, searchInput.value);
      return;
    }

    const filterInput = event.target.closest("[data-filter-input]");
    if (!filterInput) return;

    const column = filterInput.dataset.filterInput;
    if (filterInput.dataset.kind === "options") {
      return;
    }

    state.filterValues[column] ||= {};
    state.filterValues[column][filterInput.dataset.boundary] =
      filterInput.value === "" ? null : filterInput.value;
    if (filterInput.dataset.kind === "numeric" && filterInput.value !== "") {
      state.filterValues[column][filterInput.dataset.boundary] = Number(filterInput.value);
    }
    schedulePreview();
  });

  elements.filtersContainer.addEventListener("change", (event) => {
    const filterInput = event.target.closest("[data-filter-input]");
    if (!filterInput) return;

    const column = filterInput.dataset.filterInput;
    if (filterInput.dataset.kind === "options") {
      updateOptionsFilter(column, filterInput.value, filterInput.checked);
      void renderFilters({ preserveSearchFocus: true });
      schedulePreview();
      return;
    }

    state.filterValues[column] ||= {};
    state.filterValues[column][filterInput.dataset.boundary] =
      filterInput.value === "" ? null : filterInput.value;
    if (filterInput.dataset.kind === "numeric" && filterInput.value !== "") {
      state.filterValues[column][filterInput.dataset.boundary] = Number(filterInput.value);
    }
    schedulePreview();
  });

  elements.columnSearch.addEventListener("input", renderAvailableColumns);

  elements.restoreDefaultColumns.addEventListener("click", () => {
    state.selectedColumns = [...currentDataset().defaultColumns];
    setSortDefaults(currentDataset());
    renderColumnsAndSort();
    schedulePreview();
  });

  elements.clearColumns.addEventListener("click", () => {
    state.selectedColumns = [];
    renderColumnsAndSort();
    schedulePreview();
  });

  elements.selectedColumnsSummary.addEventListener("click", (event) => {
    const button = event.target.closest("[data-remove-column]");
    if (!button) return;
    removeColumn(button.dataset.removeColumn);
  });

  elements.selectedColumnsSummary.addEventListener("dragstart", (event) => {
    const item = event.target.closest("[data-selected-column]");
    if (!item) return;
    state.dragColumn = item.dataset.selectedColumn;
    item.classList.add("is-dragging");
  });

  elements.selectedColumnsSummary.addEventListener("dragend", (event) => {
    const item = event.target.closest("[data-selected-column]");
    if (item) {
      item.classList.remove("is-dragging");
    }
    state.dragColumn = null;
  });

  elements.selectedColumnsSummary.addEventListener("dragover", (event) => {
    const item = event.target.closest("[data-selected-column]");
    if (!item || !state.dragColumn) return;
    event.preventDefault();
  });

  elements.selectedColumnsSummary.addEventListener("drop", (event) => {
    const item = event.target.closest("[data-selected-column]");
    if (!item || !state.dragColumn) return;
    event.preventDefault();
    moveColumn(state.dragColumn, item.dataset.selectedColumn);
    state.dragColumn = null;
  });

  elements.columnChipList.addEventListener("click", (event) => {
    const button = event.target.closest("[data-column]");
    if (!button || button.disabled) return;
    addColumn(button.dataset.column);
  });

  elements.sortSelect.addEventListener("change", (event) => {
    state.sortBy = event.target.value;
    schedulePreview();
  });

  elements.sortDesc.addEventListener("change", (event) => {
    state.sortDesc = event.target.checked;
    schedulePreview();
  });

  elements.previewButton.addEventListener("click", runPreview);
  elements.downloadCsv.addEventListener("click", () => downloadFile("csv"));
  elements.downloadXlsx.addEventListener("click", () => downloadFile("xlsx"));

  elements.previewTableHead.addEventListener("click", (event) => {
    const header = event.target.closest("[data-sort-column]");
    if (!header) return;
    handleTableSort(header.dataset.sortColumn);
  });

  bindGlobalClickClose();
  window.addEventListener("resize", updateOpenFilterPlacement);
}

async function render() {
  renderHeaderArea();
  renderColumnsAndSort();
  await renderFilters();
  clearWarnings();
  renderPreviewTable(state.lastQuery && !state.queryStale ? state.lastQuery : null);
}

async function main() {
  bindEvents();
  await setDataset(state.datasetKey);
  await runPreview();
}

main();
