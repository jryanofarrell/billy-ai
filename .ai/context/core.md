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
| `src/parts_parser/pdf/tables.py` | Deterministically scans PDF tables into a `PageScan` containing verbatim `RawPart` records, source positions, suspicious lines, header context, and word count. |
| `src/parts_parser/pdf/validate.py` | Drops parts whose number isn't found in the page text, deduplicates, assigns sequence, and reports totals/drops/dupes. |
| `src/parts_parser/pdf/pipeline.py` | Orchestrates the full PDF run: cache lookup, extraction, TOC parse, deterministic per-page table parsing with triggered AI fallback, validation, filter matching, and `record_run`. |
| `src/parts_parser/web/` | Provides the throttled Playwright browser session, Insite/Optimizely API adapter, and filter-or-crawl web pipeline. |
| `src/parts_parser/web/site_config.py` | Defines the provider-neutral `SiteConfig` schema, dict serialization, and generic-config schema validation. |
| `src/parts_parser/web/generic.py` | Deterministically enumerates and parses non-Insite sites from a `SiteConfig`, including sitemap, bounded crawl, and search-template paths. |
| `src/parts_parser/web/discovery.py` | Uses two structure-discovery LLM calls to derive a generic site config, then validates it against sampled product pages. |
| `src/parts_parser/gui/` | Provides the PySide6 desktop UI: source and optional-filter drop zones, saved settings dialog, main-window pipeline controls, and background worker wiring for web and PDF runs. |
| `src/parts_parser/keepawake.py` | Best-effort context manager that prevents system sleep while a worker run is active. |
| `src/parts_parser/__main__.py` | Creates the Qt application and opens the `Parts Catalog Parser` window; launch it with `python -m parts_parser`. |

## Deterministic PDF tables

`pdf/tables.py` applies five description rules in priority order: a
`Description` column is captured as free text, with a trailing numeric `Qty` or
`Quantity` labeled separately; values on both sides of `PART No.` retain labels
from both sides; ordinary columns after `PART No.` become `Label: value` pairs;
tables with all size columns before `PART No.` use those preceding labels; and a
part-only row gets an empty description. Mirrored headers containing two
`PART No.` columns emit both sides of each row.

The ordinary part-code test requires at least one digit and either a hyphen or
a letter, while rejecting values that are entirely simple or mixed-number
fractions. It therefore accepts shapes such as `1460-4`, `S3749-2A`, and
`GO9-72`, but rejects `3/8`, `.122`, and `1-1/4`. Once a `PART No.` header has
established the expected code column, that position also accepts a numeric code
of at least two digits with an optional trailing `*` or `†`; this permits codes
such as `2368*` without treating similarly shaped text elsewhere as a part.
Every accepted part number is stored character-for-character as printed.

`parse_page_tables()` returns a `PageScan`: deterministic parts and their
one-based source line numbers, suspicious lines with their line number, text,
reason, and nearby headings, the most recent part-number header line, and the
page's whitespace-delimited word count. The pipeline makes one of four page
decisions:

- text with fewer than 40 non-whitespace characters is blank and skipped;
- whole-page AI is used when a scan has no parts and at least 40 words, or when
  there are at least three suspicious lines and they are at least 20% of
  `deterministic parts + suspicious lines`;
- otherwise, one or more suspicious lines use a single line-mode AI call while
  retaining deterministic parts;
- every remaining nonblank page uses its deterministic scan result, including
  an empty result for a short page with no recognized parts.

Line mode bundles every suspicious line into one numbered request together
with the page number, category, page title/subcategory, table header, and each
line's nearby headings. AI-recovered parts are associated with the returned
source line number, then merged with deterministic parts in page-line order.
Both whole-page and line-mode extraction calls set
`reasoning_effort="minimal"`; the TOC call does not set reasoning effort.

Each decision is recorded on `PageResult` (`ai_mode` and fallback reasons), and
validation derives `pages_deterministic`, `pages_ai_page`, `pages_ai_lines`, and
`pages_blank` from those results. Pipeline logging, including its end-of-run
page counts, is rendered from `PageResult` and validation-report data rather
than maintained as separate decision state. `logging_setup.setup_logging()`,
called from `__main__`, writes the package logger to a rotating file at
`<app-data>/logs/parts_parser.log`.

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
├── web_cache/
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
- `web_cache/` stores one crawl per normalized domain with the shape
  `{"fetched_at": <UTC ISO timestamp>, "crawl_seconds": <seconds>,
  "complete": <bool>, "parts": [...], "progress": [...]}`. `progress` is present
  only on an incomplete payload and lists the completed crawl unit keys. A later
  full-site collection replaces the prior payload. Completed crawls set
  `complete: true` and omit `progress`; crawls that stop early, including
  enumeration that stops after finding every requested filter entry, retain the
  collected parts with `complete: false` and their completed-unit progress.
- `runs.jsonl` is append-only run history; each record receives an ID and UTC
  timestamp. Partial-run records also include their `stopped_early` reason, and
  web records identify `data_source` as `cache`, `live`, or `cache+resume`.

Tests can set `PARTS_PARSER_DATA_DIR` to redirect all default app-data access
to a temporary directory.

## Website cache behavior

When saved website data exists, the GUI shows its age, part count, completeness,
and estimated re-crawl time, then defaults to using it. Headless runs also reuse
saved data by default. Choosing fresh data performs a live crawl and replaces the
saved payload.

Complete and partial caches have different reuse behavior. Using a complete cache
returns its parts without starting collection. Using a partial cache seeds the run
with its saved parts and resumes collection with `skip_keys = set(progress)`, so
completed units are not fetched again; the GUI describes this as finishing the
remaining work, and the completed run reports that it topped up the saved data.
If the resumed crawl completes, its replacement cache is complete and has no
`progress`. If it stops again, the replacement remains incomplete, its parts
include the prior saved parts, and `progress` is the union of previously and newly
completed unit keys. Choosing fresh ignores either kind of cache, including any
partial progress, and collects every unit again.

Full-site collection is organized into independently resumable units. Insite uses
the leaf category ID as its unit key and yields `(unit_key, records)` after each
leaf category completes. Generic enumeration uses the product URL as its unit key;
`run_generic` accepts `skip_keys` and records each completed URL. Both paths skip
fetching keys supplied in `skip_keys`.

Filter lists of at most 500 entries use per-part search when the site supports it
and do not write a website cache. Larger lists perform full-site enumeration,
cache the collected site data, and match afterward. On a discovered site without
search, enumeration may stop once every filter entry has matched; that cache is
retained but marked `complete: false`.

Refreshing one complete cache with another complete crawl produces a drift notice
when the new crawl contains fewer than 50% of the old part count. It also produces
a notice when attributes existed on more than half of the old parts but are empty
across every new part. These notices are attached to the web result and surfaced
by the GUI after the run.

## Stopped-early results

`WebRunResult` and `PdfRunResult` both expose `stopped_early: str | None`.
`None` means a clean run. A plain-language reason means collection stopped
after usable records were produced, so the result is a success with a warning:
the collected records remain available, filter matching and its match report
are computed against those partial records, and run history records the reason.
Errors before usable collection still raise rather than becoming partial
successes.

`WebRunResult` also exposes `progress: list[str]`, containing the completed crawl
unit keys. A full crawl lists every unit, while a stopped-early crawl lists only
units that completed. On a resumed run this list includes both saved progress and
units completed during the current attempt.

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
