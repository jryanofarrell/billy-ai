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
a filter was supplied. On the first run against a new website, review the sample
parts preview and confirm that they look right before the full parse continues.

**API key:** PDF table parsing is deterministic first: regular pages are processed
instantly and for free, with AI used only for pages that do not fit the table rules
(plus a catalog TOC call when one is present). Results are cached by file hash. Set
`OPENAI_API_KEY` or paste a key into Settings. Website runs against known sites use
**no AI at all**; an unknown site's first run uses a few calls to learn its structure.

## What's supported today

| Source | Works? | AI used |
|---|---|---|
| Websites on the Insite/Optimizely B2B commerce platform (e.g. midlandindustries.com — detection is automatic) | ✅ | none — the platform's JSON API is read directly |
| Any other website | ✅ | one-time AI structure discovery (a few LLM calls, once per site); deterministic thereafter; first run shows a preview to confirm |
| Digital-text catalog PDFs (e.g. Fairview master catalog) | ✅ | deterministic table parsing; AI fallback only for pages that do not fit the table rules |
| Scanned/image PDFs | ❌ detected and declined | — |

Repeat runs on a known source hit the local run store (site configs, PDF cache, run
history in the OS app-data dir) and make **zero** AI calls.

**Saved website data:** After a website crawl, its data is kept locally. The next
run offers to use the saved data or re-download it, with an estimated download
time. A crawl that stopped early is saved too and clearly labeled as partial.
Saved data also makes filtered runs instant and able to work offline.

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
  pdf/             text extraction, TOC parse, deterministic tables with per-page AI fallback, validation, cache
  gui/             PySide6 window, drop zones, settings dialog, worker thread
```

Conventions and constraints live in [`.ai/rules/core.md`](.ai/rules/core.md) (read it
before writing code); per-area snapshots in `.ai/context/`.

## Development

```bash
uv run pytest          # test suite (no network, no real browser)
uv run ruff check .    # lint
```

Live-reload while working on the GUI — launches the app immediately, then
restarts it whenever a file under `src/` is saved, so it replaces
`uv run python -m parts_parser` during development. Ctrl-C stops both the
watcher and the app. (Development only; end users get the frozen build.)

```bash
uv run --with watchfiles watchfiles 'python -m parts_parser' src
```

Windows distributable: `uv run python scripts/build.py` on Windows, or the `build`
GitHub Actions workflow — see [`docs/BUILD.md`](docs/BUILD.md).
