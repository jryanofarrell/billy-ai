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
  `{"parts": [...], "validation": {...}}` where `parts` is the list of raw
  `PartRecord`-compatible dicts and `validation` holds the summary counts
  (totals, skipped pages, drops, duplicates).
- `runs.jsonl` is append-only run history; each record receives an ID and UTC
  timestamp.

Tests can set `PARTS_PARSER_DATA_DIR` to redirect all default app-data access
to a temporary directory.

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

## Design references

See `docs/PARSER_PLAN.md` §3 for the package boundaries, §6 for the run-store
design, and §7 for the provider-agnostic LLM client.
