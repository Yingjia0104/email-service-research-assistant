from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Callable, Optional, Set, Tuple


def get_received_sender_matches_for_today(
    allowed_senders: list,
    reference_time: Optional[datetime] = None,
    *,
    ensure_bjt_fn,
    get_sender_addresses_for_created_date_fn,
    extract_sender_email_fn,
    match_allowed_sender_fn,
) -> Set[str]:
    if not allowed_senders:
        return set()

    today_str = ensure_bjt_fn(reference_time).strftime("%Y-%m-%d")
    matches = set()
    for raw_sender in get_sender_addresses_for_created_date_fn(today_str):
        matched = match_allowed_sender_fn(extract_sender_email_fn(raw_sender), allowed_senders)
        if matched:
            matches.add(matched)
    return matches


def get_briefing_session_start(
    reference_time: Optional[datetime] = None,
    *,
    ensure_bjt_fn,
    bjt,
    us_et,
) -> datetime:
    now_bjt = ensure_bjt_fn(reference_time)

    for day_offset in range(0, 8):
        candidate_date_et = now_bjt.astimezone(us_et).date() - timedelta(days=day_offset)
        if candidate_date_et.weekday() >= 5:
            continue

        market_close_et = datetime.combine(candidate_date_et, time(16, 0), tzinfo=us_et)
        market_close_bjt = market_close_et.astimezone(bjt)
        if market_close_bjt < now_bjt:
            return market_close_bjt

    raise RuntimeError("无法计算最近一个 briefing session 的起点")


def get_received_sender_matches_for_session(
    allowed_senders: list,
    reference_time: Optional[datetime] = None,
    *,
    get_briefing_session_start_fn,
    get_sender_addresses_created_since_fn,
    extract_sender_email_fn,
    match_allowed_sender_fn,
) -> Set[str]:
    if not allowed_senders:
        return set()

    session_start = get_briefing_session_start_fn(reference_time).isoformat()
    matches = set()
    for raw_sender in get_sender_addresses_created_since_fn(session_start):
        matched = match_allowed_sender_fn(extract_sender_email_fn(raw_sender), allowed_senders)
        if matched:
            matches.add(matched)
    return matches


def all_expected_senders_arrived_for_session(
    allowed_senders: list,
    reference_time: Optional[datetime] = None,
    *,
    get_received_sender_matches_for_session_fn,
) -> bool:
    expected = {(sender or "").strip().lower() for sender in allowed_senders or [] if sender}
    if not expected:
        return False
    received = get_received_sender_matches_for_session_fn(list(expected), reference_time)
    return expected.issubset(received)


def should_trigger_early_daily(
    allowed_senders: list,
    bg_cfg: dict,
    reference_time: Optional[datetime] = None,
    *,
    ensure_bjt_fn,
    get_briefing_session_start_fn,
    get_received_sender_matches_for_session_fn,
    count_emails_created_since_fn,
    has_new_email_within_minutes_fn,
) -> Tuple[bool, str]:
    now_bjt = ensure_bjt_fn(reference_time)
    quiet_minutes = int(bg_cfg.get("early_quiet_minutes", 10) or 10)
    ignore_quiet_for_demo = bool(bg_cfg.get("ignore_early_quiet_for_demo", False))
    min_new_emails = int(
        bg_cfg.get("early_min_new_emails", max(2, len(allowed_senders) or 0))
        or max(2, len(allowed_senders) or 0)
    )
    session_start = get_briefing_session_start_fn(now_bjt)
    expected = {(sender or "").strip().lower() for sender in allowed_senders or [] if sender}
    received = get_received_sender_matches_for_session_fn(list(expected), now_bjt)
    missing = sorted(expected - received)

    if expected and not expected.issubset(received):
        return False, (
            f"白名单 sales 尚未在本轮 session 内全部到齐；"
            f"session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"已到齐={sorted(received)}, 缺失={missing}"
        )

    session_email_count = count_emails_created_since_fn(session_start.isoformat())
    if session_email_count < min_new_emails:
        return False, (
            f"本轮 session 邮件数不足（{session_email_count}/{min_new_emails}）；"
            f"session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, 已到齐={sorted(received)}"
        )

    if not ignore_quiet_for_demo and has_new_email_within_minutes_fn(quiet_minutes, now_bjt):
        return False, (
            f"最近 {quiet_minutes} 分钟仍有新邮件，继续等待；"
            f"session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, 已到齐={sorted(received)}, "
            f"session邮件数={session_email_count}"
        )

    return True, (
        f"满足 early run 条件：session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, "
        f"已到齐={sorted(received)}, 邮件数={session_email_count}, quiet={quiet_minutes}m"
    )


def all_expected_senders_arrived(
    allowed_senders: list,
    reference_time: Optional[datetime] = None,
    *,
    all_expected_senders_arrived_for_session_fn,
) -> bool:
    return all_expected_senders_arrived_for_session_fn(allowed_senders, reference_time)


def has_daily_report_sent_today(
    reference_time: Optional[datetime] = None,
    *,
    ensure_bjt_fn,
    has_successful_report_on_date_fn,
) -> bool:
    today_str = ensure_bjt_fn(reference_time).strftime("%Y-%m-%d")
    return has_successful_report_on_date_fn(today_str, report_type="daily")
