# Build guide — Parts Catalog Parser

## Prerequisites

1. **Windows machine** — the build produces a Windows executable and the
   Playwright Chromium download step is OS-specific.
2. **Python 3.12+** and **uv** — install uv from
   <https://docs.astral.sh/uv/getting-started/installation/>.
3. Dependencies installed (`uv sync`) — `pyinstaller` and `playwright` must
   be present in the project's dev dependencies.

## Build command

From the repo root on a Windows machine:

```
uv run python scripts/build.py
```

The script does three things in order:

1. Runs `playwright install chromium` with `PLAYWRIGHT_BROWSERS_PATH=0` so
   Chromium lands inside the playwright package directory and travels with the
   bundle.
2. Runs PyInstaller using `build/PartsCatalogParser.spec` (one-folder build).
3. Zips the output folder into `dist/PartsCatalogParser-<version>-windows.zip`.

## Output locations

| Path | Contents |
|---|---|
| `dist/PartsCatalogParser/` | One-folder bundle (the live app directory) |
| `dist/PartsCatalogParser/Parts Catalog Parser.exe` | Launch executable |
| `dist/PartsCatalogParser-<version>-windows.zip` | Distributable archive |

The `dist/` directory is not committed to the repo.

## CI build

The `build.yml` workflow runs automatically on `v*` version tags and on
manual trigger (`workflow_dispatch`). It runs on `windows-latest`, executes
`uv run python scripts/build.py`, and uploads
`PartsCatalogParser-<version>-windows.zip` as a build artifact.

CI proves the build succeeds on GitHub's Windows runner. It does **not** prove
the app works correctly — smoke-test the artifact on a real machine before
any hand-off.

## Manual smoke checklist

Perform this on a real Windows machine with the extracted zip.

- [ ] **Launch** — double-click `Parts Catalog Parser.exe`; the main window
      opens within a few seconds with no error dialog or console window.
- [ ] **Settings persist** — open Settings, enter an API key, close and
      re-open the app; the key is still shown.
- [ ] **PDF run** — drag a catalog PDF onto the window and click Run; the
      progress bar moves and an output workbook appears in the expected
      location.
- [ ] **Web run** — enter a supported website URL and click Run; Chromium
      launches inside the bundle (no "browser not found" error) and an
      output workbook is created.
- [ ] **No console window** — no extra terminal window appears while the app
      is running.

## Troubleshooting

**Web run fails with "browser not found" in the frozen build.**
The `PLAYWRIGHT_BROWSERS_PATH=0` contract must hold on both sides:
- The frozen app sets it in `src/parts_parser/__main__.py` before any
  Playwright import.
- The build script installs Chromium with the same env var so the browser is
  in `playwright/driver/package/.local-browsers/` and gets bundled by the
  spec.
If one side drifts, the browser won't be where Playwright expects it.
