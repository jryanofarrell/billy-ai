"""Build script: install Playwright Chromium then produce the PartsCatalogParser bundle + zip."""

import os
import subprocess
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DIST = ROOT / "dist"
BUILD_WORK = ROOT / "build" / "_work"
SPEC = ROOT / "build" / "PartsCatalogParser.spec"
BUNDLE_NAME = "PartsCatalogParser"


def get_version() -> str:
    pyproject = ROOT / "pyproject.toml"
    if not pyproject.exists():
        return "0.1.0"
    try:
        import tomllib
    except ImportError:
        try:
            import tomli as tomllib  # type: ignore[no-redef]
        except ImportError:
            return "0.1.0"
    with open(pyproject, "rb") as f:
        data = tomllib.load(f)
    return data.get("project", {}).get("version", "0.1.0")


def install_chromium() -> None:
    # PLAYWRIGHT_BROWSERS_PATH=0 stores Chromium next to the playwright package
    # so the spec file can find and bundle it, and the frozen app can locate it.
    env = {**os.environ, "PLAYWRIGHT_BROWSERS_PATH": "0"}
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        env=env,
    )


def run_pyinstaller() -> None:
    subprocess.run(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            str(SPEC),
            "--distpath",
            str(DIST),
            "--workpath",
            str(BUILD_WORK),
            "--noconfirm",
        ],
        check=True,
        cwd=ROOT,
    )


def zip_bundle(version: str) -> Path:
    bundle_dir = DIST / BUNDLE_NAME
    zip_path = DIST / f"{BUNDLE_NAME}-{version}-windows.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in bundle_dir.rglob("*"):
            if file_path.is_file():
                zf.write(file_path, file_path.relative_to(DIST))
    return zip_path


def main() -> None:
    version = get_version()
    print(f"Building Parts Catalog Parser v{version}")
    print("Installing Playwright Chromium into package dir (PLAYWRIGHT_BROWSERS_PATH=0)...")
    install_chromium()
    print("Running PyInstaller...")
    run_pyinstaller()
    print("Creating zip...")
    zip_path = zip_bundle(version)
    print(f"Bundle: {DIST / BUNDLE_NAME}")
    print(f"Zip:    {zip_path}")


if __name__ == "__main__":
    main()
