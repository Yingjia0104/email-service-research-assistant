from __future__ import annotations

from datetime import datetime


def runtime_timestamp() -> str:
    """统一的运行时日志时间戳。"""
    return datetime.now().astimezone().strftime("%H:%M:%S")


def runtime_print(message: str) -> None:
    print(f"[{runtime_timestamp()}] {message}")
