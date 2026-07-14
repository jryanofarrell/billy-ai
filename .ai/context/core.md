# Core package context

The initial `parts_parser` package scaffold provides configuration, one
provider-agnostic LLM boundary, and local persistent run state.

## Modules

| Module | Purpose |
|---|---|
| `src/parts_parser/config.py` | Loads and saves user settings and resolves the OS app-data directory. |
| `src/parts_parser/llm.py` | Defines the provider-agnostic LLM interface and the configured OpenAI implementation. |
| `src/parts_parser/store.py` | Persists site configs, PDF results, and run history, and computes file hashes. |

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
- `pdf_cache/` stores parsed parts in JSON files keyed by the source PDF's
  SHA-256 hash.
- `runs.jsonl` is append-only run history; each record receives an ID and UTC
  timestamp.

Tests can set `PARTS_PARSER_DATA_DIR` to redirect all default app-data access
to a temporary directory.

## Design references

See `docs/PARSER_PLAN.md` §3 for the package boundaries, §6 for the run-store
design, and §7 for the provider-agnostic LLM client.
