# billy-ai

AI tooling for Central Components (plumbing distributor, Epicor P21). Product #1 is the
**parts-catalog parser**: a local desktop app that parses plumbing-parts **websites** and
**catalog PDFs** into Excel workbooks, optionally filtered to the part numbers in a
user-supplied Excel sheet. Managed by ai_factory.

Design doc: [`docs/PARSER_PLAN.md`](docs/PARSER_PLAN.md) · Building the Windows exe:
[`docs/BUILD.md`](docs/BUILD.md)

## Running the parser locally

```bash
uv sync                              # install dependencies (Python 3.12+, uv)
uv run playwright install chromium   # one-time, for website runs
uv run python -m parts_parser        # opens the GUI
```

In the window: pick Website or PDF catalog, provide the address or drop the PDF,
optionally drop an Excel part list to filter by, and hit Run. The output workbook
lands in `~/Downloads` and contains a `Parts` sheet plus a `Match Report` sheet when
a filter was supplied.

**API key:** PDF parsing calls an LLM (~$1–2 per catalog, once — results are cached by
file hash). Set `OPENAI_API_KEY` or paste a key into Settings. Website runs against
supported platforms use **no AI at all**.

## What's supported today

| Source | Works? | AI used |
|---|---|---|
| Websites on the Insite/Optimizely B2B commerce platform (e.g. midlandindustries.com — detection is automatic) | ✅ | none — the platform's JSON API is read directly |
| Any other website | ❌ "isn't supported yet" | — (planned: one-time AI structure discovery that saves a reusable site config; see plan §4.3/§11) |
| Digital-text catalog PDFs (e.g. Fairview master catalog) | ✅ | one LLM call per page, once per unique file |
| Scanned/image PDFs | ❌ detected and declined | — |

Repeat runs on a known source hit the local run store (site configs, PDF cache, run
history in the OS app-data dir) and make **zero** AI calls.

## Structure

```
src/parts_parser/
  config.py        settings + app-data paths (env override: PARTS_PARSER_DATA_DIR)
  llm.py           provider-agnostic LLM client (the only file that imports an AI SDK)
  store.py         run store: site configs, PDF parts cache, run history
  models.py        PartRecord — the shape both pipelines emit
  output/          filter loading/matching (verbatim part numbers, normalized matching)
                   + Excel writer (Parts + Match Report sheets)
  web/             Playwright session (Cloudflare-capable) + Insite adapter + pipeline
  pdf/             text extraction, TOC parse, per-page AI extraction, validation, cache
  gui/             PySide6 window, drop zones, settings dialog, worker thread
```

Conventions and constraints live in [`.ai/rules/core.md`](.ai/rules/core.md) (read it
before writing code); per-area snapshots in `.ai/context/`.

## Development

```bash
uv run pytest          # test suite (no network, no real browser)
uv run ruff check .    # lint
```

Windows distributable: `uv run python scripts/build.py` on Windows, or the `build`
GitHub Actions workflow — see [`docs/BUILD.md`](docs/BUILD.md).
