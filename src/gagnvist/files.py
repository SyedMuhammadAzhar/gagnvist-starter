"""Moving finished files into place, on every operating system.

On Windows, a program that looks at every new file (a virus scanner, the search
indexer, a sync service) can keep it locked for a moment after it was written, and a
rename then fails with "access denied". Waiting a little and trying again is enough.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

WINDOWS = os.name == "nt"
ATTEMPTS = 20
PAUSE = 0.5  # seconds between attempts: at most about 10 s in all


def move_into_place(source: Path, target: Path) -> None:
    """Rename ``source`` (a file or a folder) to ``target``, replacing a file that is
    there; on Windows, try again for a while if another program holds it locked."""
    for attempt in range(1, ATTEMPTS + 1):
        try:
            os.replace(source, target)
            return
        except PermissionError:
            if not WINDOWS or attempt == ATTEMPTS:
                raise
            time.sleep(PAUSE)
