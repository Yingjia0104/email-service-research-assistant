from __future__ import annotations

from typing import Any


def record_run_error(error_message: str, *, load_state_fn, save_state_fn) -> None:
    state = load_state_fn()
    state["last_error"] = error_message
    save_state_fn(state)


def record_run_success(*, now_fn, load_state_fn, save_state_fn) -> None:
    now_dt = now_fn()
    state = load_state_fn()
    state["last_processed_date"] = now_dt.strftime("%Y-%m-%d")
    state["last_check_time"] = now_dt.isoformat()
    state["last_error"] = None
    save_state_fn(state)
