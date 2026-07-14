# Building the Windows application

## Prerequisites

- Install [uv](https://docs.astral.sh/uv/).
- Run the build on Windows to produce a Windows executable. If you do not have a
  Windows build machine, run the GitHub Actions `build` workflow and download its
  `PartsCatalogParser-windows` artifact instead.

From the repository root, run:

```powershell
uv run python scripts/build.py
```

The build creates:

- `dist/PartsCatalogParser/Parts Catalog Parser.exe`
- `dist/PartsCatalogParser-<version>-windows.zip`

Distribute the zip file, which contains the executable and all required support
files, including Chromium.

## Manual smoke test

Extract the zip, then verify all of the following on Windows:

1. Launch `Parts Catalog Parser.exe`.
2. Open **Settings**, paste an API key, and save it. Quit and relaunch the app,
   then confirm that the key persisted.
3. Drag a PDF into the app and start the run. Confirm that the run completes and
   the generated workbook opens.
4. Enter a website URL, attach a small filter sheet, and start the run. Confirm
   that the run completes.

Windows SmartScreen may warn about the unsigned executable. Choose **More info**
and then **Run anyway** to continue. Code signing is deliberately deferred for
this release.
