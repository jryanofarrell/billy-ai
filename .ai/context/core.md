# Core package context

The initial `parts_parser` package scaffold provides configuration, one
provider-agnostic LLM boundary, and local persistent run state.

## Modules

| Module | Purpose |
|---|---|
| `src/parts_parser/config.py` | Loads and saves user settings and resolves the OS app-data directory. |
| `src/parts_parser/llm.py` | Defines the provider-agnostic LLM interface and the configured OpenAI implementation. |
| `src/parts_parser/models.py` | Defines the shared `PartRecord` output model. |
| `src/parts_parser/output/filtering.py` | Loads part-number filter workbooks, normalizes keys for matching, and reports exact, normalized, collision, and unmatched results. |
| `src/parts_parser/output/excel.py` | Writes PDF- and web-mode parts workbooks and optional match-report sheets. |
| `src/parts_parser/store.py` | Persists site configs, PDF results, and run history, and computes file hashes. |
| `src/parts_parser/pdf/extract.py` | Extracts per-page text from a PDF via `pypdf`; classifies pages as digital or scanned. |
| `src/parts_parser/pdf/toc.py` | Detects TOC pages by dotted-leader density and parses them into ordered sections via one `complete_json` call. Prompt lives here. |
| `src/parts_parser/pdf/pages.py` | Sends the per-page extraction prompt and returns parts/subcategory/skip for each page. Prompt lives here. |
| `src/parts_parser/pdf/validate.py` | Drops parts whose number isn't found in the page text, deduplicates, assigns sequence, and reports totals/drops/dupes. |
| `src/parts_parser/pdf/pipeline.py` | Orchestrates the full PDF run: cache lookup, extraction, TOC parse, per-page AI calls, validation, filter matching, and `record_run`. |
| `src/parts_parser/web/` | Provides the throttled Playwright browser session, Insite/Optimizely API adapter, and filter-or-crawl web pipeline. |
| `src/parts_parser/web/site_config.py` | Defines the provider-neutral `SiteConfig` schema, dict serialization, and generic-config schema validation. |
| `src/parts_parser/web/generic.py` | Deterministically enumerates and parses non-Insite sites from a `SiteConfig`, including sitemap, bounded crawl, and search-template paths. |
| `src/parts_parser/web/discovery.py` | Uses two structure-discovery LLM calls to derive a generic site config, then validates it against sampled product pages. |
| `src/parts_parser/gui/` | Provides the PySide6 desktop UI: source and optional-filter drop zones, saved settings dialog, main-window pipeline controls, and background worker wiring for web and PDF runs. |
| `src/parts_parser/keepawake.py` | Best-effort context manager that prevents system sleep while a worker run is active. |
| `src/parts_parser/__main__.py` | Creates the Qt application and opens the `Parts Catalog Parser` window; launch it with `python -m parts_parser`. |

## Insite endpoint facts

- `GET /api/v1/websites/current?expand=languages%2Ccurrencies` detects an
  Insite site from an object containing `id` or `websiteId`.
- `GET /api/v1/categories/?maxDepth=3&includeStartCategory=false` returns the
  category tree.
- `GET /api/v2/products?categoryId=<id>&page=<n>&pageSize=48&expand=attributes`
  lists one leaf category; follow `pagination.numberOfPages`.
- `GET /api/v2/products?search=<term>&expand=attributes&pageSize=48` searches
  products for filter mode.
- `GET /api/v2/products/<guid>?expand=attributes` returns a product directly
  at the top level, not inside a `products` collection; it is also the cached
  site-config probe.
- `GET /api/v1/catalogpages?path=%2Fproduct%2F<url-segment>` returns
  `breadCrumbs` for filter-mode category fields; discard the `Home` crumb.
- Products attach to leaf categories. Intermediate category IDs can return no
  products because those pages are navigation tile fan-outs, so crawl the tree
  and request products only for nodes without `subCategories`.

## App-data layout

Runtime state lives in the OS app-data directory for `PartsParser`, not in the
repository or beside the executable:

```text
PartsParser/
├── settings.json
├── site_configs/
├── pdf_cache/
└── runs.jsonl
```

- `settings.json` stores the local API key and model setting. A non-empty
  `OPENAI_API_KEY` environment variable takes precedence when settings load.
- `site_configs/` stores one JSON file per normalized domain.
- `pdf_cache/` stores parsed results in JSON files keyed by the source PDF's
  SHA-256 hash. Each cache file has the shape
  `{"parts": [...], "validation": {...}, "complete": <bool>}` where `parts`
  is the list of raw `PartRecord`-compatible dicts and `validation` holds the
  summary counts (totals, skipped pages, drops, duplicates). Only entries with
  `complete: true` are cache hits. A stopped-early parse is persisted with
  `complete: false` for partial-state visibility but is never served as cached
  output; a later run reparses the file.
- `runs.jsonl` is append-only run history; each record receives an ID and UTC
  timestamp. Partial-run records also include their `stopped_early` reason.

Tests can set `PARTS_PARSER_DATA_DIR` to redirect all default app-data access
to a temporary directory.

## Stopped-early results

`WebRunResult` and `PdfRunResult` both expose `stopped_early: str | None`.
`None` means a clean run. A plain-language reason means collection stopped
after usable records were produced, so the result is a success with a warning:
the collected records remain available, filter matching and its match report
are computed against those partial records, and run history records the reason.
Errors before usable collection still raise rather than becoming partial
successes.

For PDF runs, cancellation or an LLM failure during the page loop validates and
returns parts from completed pages. Such parses are marked `complete: false` in
the PDF cache and are never reused; only a fully completed parse is stored with
`complete: true` and can satisfy a later cache lookup.

The GUI worker treats a stopped-early result containing at least one part as a
successful run: it writes the workbook, reports
`Done — N parts · saved to <path> (stopped early)`, and shows an information
dialog containing the reason. A stopped-early result with no parts is presented
as a failure. Clean-run presentation is unchanged.

## Keep-awake behavior

The worker holds `keep_awake()` around its entire run body. On macOS the context
manager starts `caffeinate -i -m` and terminates it on exit. On Windows it calls
`SetThreadExecutionState(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)` on entry and
resets the state with `ES_CONTINUOUS` on exit. Other platforms are no-ops, and
any acquisition or cleanup failure is silently ignored so power-management
support cannot break a parser run. Display sleep is not prevented.

## Site-config schema

`src/parts_parser/web/site_config.py` is the source of truth for the serialized
`SiteConfig` schema. Every config contains `platform`, `enumeration`, `selectors`,
optional `search_url_template` and `probe` values, and a bounded `page_budget`.
For generic sites, `selectors.part_no` is required. Enumeration uses either a
`sitemap` strategy (`sitemap_url` plus `product_url_pattern`) or a
`category_crawl` strategy (`start_urls` plus `product_link_pattern`, with optional
`category_link_pattern` and `pagination_param`). Selector configs may also include
`breadcrumb` and an `attributes` mapping with `row`, `label`, and `value` CSS
selectors.

The run store saves the config as JSON at
`PartsParser/site_configs/<normalized-domain>.json`. A successful discovery is
cached only after validation and first-run preview confirmation; later runs load
that file and use its probe to check that it is still valid before parsing.

## Output workbook shape

Every output workbook has a `Parts` sheet. PDF mode uses `Part No`, `Category`,
`Subcategory`, `Series`, `Description`, and `Sequence`; web mode uses `Part No`,
`Category`, `Subcategory`, and `Series`, followed by the alphabetized union of
attribute labels across all parts. Missing web attributes are written as blank
cells, and source part numbers are preserved exactly.

When filter matching is requested, the workbook also has a `Match Report`
sheet. Its first row identifies the filter column used, followed by one row per
filter entry under `Filter Value`, `Match Type`, `Matched Part No`, and `Note`.
Match types are exact, normalized, collision, or unmatched; collision rows list
all candidates rather than selecting one.

## Output path convention

All runs write to the user's `Downloads` directory: `<domain>-parts.xlsx` for
web runs, `<pdf-stem>-parts.xlsx` for PDF runs. If the chosen path already
exists, the app preserves it and selects the next available path by adding
` (2)`, ` (3)`, and so on before the `.xlsx` extension. The worksheet column
holding a part's description text is headed "Size" (warehouse vocabulary) in
both modes; internally the field remains `PartRecord.description` because the
PDF cache stores that key.

## Build

- `build/parts_parser.spec` defines the PyInstaller bundle, and
  `scripts/build.py` installs Chromium, runs the spec, verifies that Chromium
  was bundled, and creates the versioned release zip in `dist/`.
- `scripts/build.py` installs Chromium with `PLAYWRIGHT_BROWSERS_PATH=0`, which
  places the browser inside Playwright's package directory for PyInstaller to
  collect. When the frozen application starts, `src/parts_parser/__main__.py`
  must set the same environment variable before importing anything that can
  import Playwright so runtime browser lookup stays inside the bundle.
- Windows release zips are produced by `.github/workflows/build.yml`. Run the
  `build` workflow and download its `PartsCatalogParser-windows` artifact; the
  artifact contains the versioned zip generated by `scripts/build.py`.

## Design references

See `docs/PARSER_PLAN.md` §3 for the package boundaries, §6 for the run-store
design, and §7 for the provider-agnostic LLM client.
