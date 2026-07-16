"""Build and archive the Parts Catalog Parser desktop application."""

from __future__ import annotations

import importlib.util
import logging
import os
import platform
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
DIST_DIR = ROOT / "dist"
APP_DIR = DIST_DIR / "PartsCatalogParser"


def run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    """Run and log a build command, raising immediately if it fails."""
    logger.info("Running: %s", " ".join(command))
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def project_version() -> str:
    """Read the application version from pyproject.toml."""
    with (ROOT / "pyproject.toml").open("rb") as pyproject_file:
        pyproject = tomllib.load(pyproject_file)
    return str(pyproject["project"]["version"])


def platform_name() -> str:
    """Return the platform label used in release archive names."""
    return {
        "Darwin": "macos",
        "Linux": "linux",
        "Windows": "windows",
    }.get(platform.system(), platform.system().lower())


def assert_pyinstaller_available() -> None:
    """Fail with an actionable hint when build dependencies are missing."""
    if importlib.util.find_spec("PyInstaller") is None:
        raise RuntimeError(
            "PyInstaller is not installed. Run `uv sync --group build`, then try again."
        )


def assert_bundled_chromium() -> None:
    """Verify that PyInstaller copied Playwright's local browser installation."""
    browser_directories = [path for path in APP_DIR.rglob(".local-browsers") if path.is_dir()]
    if not any(any(path.iterdir()) for path in browser_directories):
        raise RuntimeError(
            "Chromium was not included in the packaged application. "
            "Run `uv sync --group build` and rebuild."
        )


def build() -> Path:
    """Install dependencies, freeze the application, and create its zip archive."""
    run(["uv", "sync"])
    assert_pyinstaller_available()

    browser_env = os.environ.copy()
    browser_env["PLAYWRIGHT_BROWSERS_PATH"] = "0"
    run(["playwright", "install", "chromium"], env=browser_env)
    run(
        [
            "pyinstaller",
            "build/parts_parser.spec",
            "--noconfirm",
            "--distpath",
            "dist",
        ]
    )
    assert_bundled_chromium()

    archive_base = DIST_DIR / (f"PartsCatalogParser-{project_version()}-{platform_name()}")
    archive_path = Path(
        shutil.make_archive(
            str(archive_base),
            "zip",
            root_dir=DIST_DIR,
            base_dir=APP_DIR.name,
        )
    )
    logger.info("Created: %s", archive_path)
    return archive_path


def main() -> int:
    """Run the build and return a process exit status."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    try:
        build()
    except (OSError, RuntimeError, subprocess.CalledProcessError) as error:
        logger.error("Build failed: %s", error)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
