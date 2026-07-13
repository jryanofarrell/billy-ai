import os
import sys

if getattr(sys, "frozen", False):
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"

from parts_parser.app import main  # noqa: E402

main()
