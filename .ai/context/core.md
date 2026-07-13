---
name: core
description: Snapshot of the parts-catalog-parser project layout, stack, and build conventions for cold agent sessions.
---

# Core context — parts-catalog-parser

## Stack

- Python 3.12+, managed with `uv`
- PySide6 — GUI toolkit (native drag-and-drop, PyInstaller-compatible)
- Playwright (Chromium) — web scraping
- pypdf — PDF text extraction
- openpyxl — Excel output
- PyInstaller — Windows packaging (one-folder build)
- Ruff — lint and format

## Key directories

| Path | Purpose |
|---|---|
| `src/parts_parser/` | Package root; `__main__.py` is the entry point |
| `build/` | PyInstaller spec (`PartsCatalogParser.spec`) and work cache |
| `scripts/` | Build orchestration (`build.py`) |
| `dist/` | Build output — gitignored, not committed |
| `docs/` | Architecture (`PARSER_PLAN.md`) and build docs (`BUILD.md`) |
| `.github/workflows/` | CI — lint/tests (`ci.yml`), packaging (`build.yml`) |

## Entry point and frozen-app guard

`src/parts_parser/__main__.py` sets `PLAYWRIGHT_BROWSERS_PATH=0` before
importing Playwright, but only when running as a frozen PyInstaller bundle
(`getattr(sys, "frozen", False)`). This tells Playwright to find Chromium
inside the bundle rather than the user's local cache.

## Build conventions

- **Command:** `uv run python scripts/build.py` (Windows only).
- **Bundle style:** one-folder PyInstaller `COLLECT` — not `--onefile`.
- **Chromium bundling:** `scripts/build.py` installs Chromium with
  `PLAYWRIGHT_BROWSERS_PATH=0` so it lands at
  `playwright/driver/package/.local-browsers/`. The spec file finds it
  there and adds it to `datas`.
- **Version source:** `pyproject.toml [project].version`.
- **Zip name:** `dist/PartsCatalogParser-<version>-windows.zip`.
- **CI trigger:** `build.yml` runs on `workflow_dispatch` and `v*` tags,
  uploads the zip as a build artifact.

## Key design decisions

- `PLAYWRIGHT_BROWSERS_PATH=0` is the contract between the build step and
  the frozen app. If a frozen web run can't find a browser, check that both
  sides agree on this value.
- One-folder (not one-file) build keeps Chromium files addressable at known
  relative paths and avoids slow extraction on every launch.
