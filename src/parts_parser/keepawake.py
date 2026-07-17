"""Best-effort system sleep prevention for long-running parser jobs."""

import ctypes
import subprocess
import sys
from collections.abc import Iterator
from contextlib import contextmanager

_ES_CONTINUOUS = 0x80000000
_ES_SYSTEM_REQUIRED = 0x00000001


@contextmanager
def keep_awake() -> Iterator[None]:
    """Prevent system sleep for the duration of the block.

    Acquisition is best-effort: power management failures are silently
    ignored so they can never break a run. Display sleep remains enabled.
    """
    if sys.platform == "darwin":
        try:
            proc = subprocess.Popen(["caffeinate", "-i", "-m"])
        except Exception:
            yield
            return

        try:
            yield
        finally:
            try:
                proc.terminate()
            except Exception:
                pass
        return

    if sys.platform == "win32":
        try:
            ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
                _ES_CONTINUOUS | _ES_SYSTEM_REQUIRED
            )
        except Exception:
            yield
            return

        try:
            yield
        finally:
            try:
                ctypes.windll.kernel32.SetThreadExecutionState(  # type: ignore[attr-defined]
                    _ES_CONTINUOUS
                )
            except Exception:
                pass
        return

    yield
