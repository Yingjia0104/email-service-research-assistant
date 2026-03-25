from __future__ import annotations

import fcntl
import os
from typing import Optional, TextIO


def try_acquire_analysis_lock(lock_file: str) -> Optional[TextIO]:
    lock_handle = open(lock_file, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_handle.close()
        return None

    lock_handle.seek(0)
    lock_handle.truncate()
    lock_handle.write(str(os.getpid()))
    lock_handle.flush()
    return lock_handle


def release_analysis_lock(lock_handle: Optional[TextIO]) -> None:
    if not lock_handle:
        return
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        lock_handle.close()
    except Exception:
        pass
