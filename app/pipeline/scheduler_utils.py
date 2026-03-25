from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Optional


def ensure_bjt(dt_value: Optional[datetime], *, bjt) -> datetime:
    """将时间标准化到北京时间 aware datetime。"""
    dt_value = dt_value or datetime.now(bjt)
    if dt_value.tzinfo is None:
        return bjt.localize(dt_value)
    return dt_value.astimezone(bjt)


def market_session_bounds_bjt(reference_time: Optional[datetime], *, bjt, us_et):
    """返回当前美东日期对应的 trigger/open/window_end 的北京时间。"""
    now_bjt = ensure_bjt(reference_time, bjt=bjt)
    now_et = now_bjt.astimezone(us_et)

    session_date_et = now_et.date()
    market_open_et = datetime.combine(session_date_et, time(9, 30), tzinfo=us_et)
    trigger_et = market_open_et - timedelta(minutes=15)
    window_end_et = market_open_et + timedelta(hours=1)

    return (
        trigger_et.astimezone(bjt),
        market_open_et.astimezone(bjt),
        window_end_et.astimezone(bjt),
    )


def get_next_market_trigger_time(reference_time: Optional[datetime], *, bjt, us_et) -> datetime:
    """获取下一个美股开盘前 15 分钟触发点。"""
    now_bjt = ensure_bjt(reference_time, bjt=bjt)
    session_time_et = now_bjt.astimezone(us_et)
    session_date_et = session_time_et.date()

    for day_offset in range(8):
        candidate_date = session_date_et + timedelta(days=day_offset)
        if candidate_date.weekday() >= 5:
            continue

        trigger_et = datetime.combine(candidate_date, time(9, 15), tzinfo=us_et)
        trigger_bjt = trigger_et.astimezone(bjt)
        if trigger_bjt > now_bjt:
            return trigger_bjt

    raise RuntimeError("无法计算下一个美股开盘触发时间")


def get_us_market_open_time(reference_time: Optional[datetime], *, bjt, us_et):
    """返回下一个美股开盘前 15 分钟触发点的北京时间小时和分钟。"""
    next_trigger = get_next_market_trigger_time(reference_time, bjt=bjt, us_et=us_et)
    return next_trigger.hour, next_trigger.minute


def is_in_supplement_window(reference_time: Optional[datetime], *, bjt, us_et):
    """检查当前是否在补充分析时间窗口内。"""
    now_bjt = ensure_bjt(reference_time, bjt=bjt)
    now_et = now_bjt.astimezone(us_et)
    if now_et.weekday() >= 5:
        return False

    window_start, _, window_end = market_session_bounds_bjt(now_bjt, bjt=bjt, us_et=us_et)
    return window_start <= now_bjt <= window_end
