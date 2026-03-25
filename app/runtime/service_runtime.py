from __future__ import annotations

import asyncio

from app.mail import service as app_mail_service
from app.pipeline import scheduler as app_scheduler
from app.runtime import service_analysis as app_service_analysis


def fetch_emails_and_persist(
    limit: int,
    *,
    load_config_fn,
    parse_received_after_local_fn,
    should_accept_sender_fn,
    get_message_local_datetime_fn,
    build_attachment_records_fn,
    email_db_module,
    logger,
):
    return app_mail_service.fetch_emails_and_persist(
        limit,
        load_config_fn=load_config_fn,
        parse_received_after_local_fn=parse_received_after_local_fn,
        should_accept_sender_fn=should_accept_sender_fn,
        get_message_local_datetime_fn=get_message_local_datetime_fn,
        build_attachment_records_fn=build_attachment_records_fn,
        email_db_module=email_db_module,
        logger=logger,
    )


async def fetch_and_save_emails(
    *,
    load_config_fn,
    email_db_module,
    runtime_print_fn,
    has_daily_report_sent_today_fn,
    should_trigger_early_daily_fn,
    trigger_daily_analysis_fn,
    is_in_supplement_window_fn,
    trigger_supplement_analysis_fn,
    fetch_emails_and_persist_fn,
):
    await app_scheduler.fetch_and_save_emails(
        load_config_fn=load_config_fn,
        email_db_module=email_db_module,
        runtime_print_fn=runtime_print_fn,
        has_daily_report_sent_today_fn=has_daily_report_sent_today_fn,
        should_trigger_early_daily_fn=should_trigger_early_daily_fn,
        trigger_daily_analysis_fn=trigger_daily_analysis_fn,
        is_in_supplement_window_fn=is_in_supplement_window_fn,
        trigger_supplement_analysis_fn=trigger_supplement_analysis_fn,
        fetch_emails_and_persist_fn=fetch_emails_and_persist_fn,
    )


async def background_fetch_loop(*, load_config_fn, fetch_and_save_emails_fn, runtime_print_fn):
    await app_scheduler.background_fetch_loop(
        load_config_fn=load_config_fn,
        fetch_and_save_emails_fn=fetch_and_save_emails_fn,
        runtime_print_fn=runtime_print_fn,
    )


async def trigger_supplement_analysis(
    new_emails_count: int,
    *,
    has_daily_report_sent_today_fn,
    try_acquire_analysis_lock_fn,
    release_analysis_lock_fn,
    email_db_module,
    runtime_print_fn,
    run_analysis_job_fn,
):
    await app_scheduler.trigger_supplement_analysis(
        new_emails_count,
        has_daily_report_sent_today_fn=has_daily_report_sent_today_fn,
        try_acquire_analysis_lock_fn=try_acquire_analysis_lock_fn,
        release_analysis_lock_fn=release_analysis_lock_fn,
        email_db_module=email_db_module,
        runtime_print_fn=runtime_print_fn,
        run_analysis_job_fn=run_analysis_job_fn,
    )


async def trigger_daily_analysis(
    reason: str,
    *,
    try_acquire_analysis_lock_fn,
    release_analysis_lock_fn,
    email_db_module,
    runtime_print_fn,
    has_daily_report_sent_today_fn,
    run_analysis_job_fn,
):
    await app_scheduler.trigger_daily_analysis(
        reason,
        try_acquire_analysis_lock_fn=try_acquire_analysis_lock_fn,
        release_analysis_lock_fn=release_analysis_lock_fn,
        email_db_module=email_db_module,
        runtime_print_fn=runtime_print_fn,
        has_daily_report_sent_today_fn=has_daily_report_sent_today_fn,
        run_analysis_job_fn=run_analysis_job_fn,
    )


async def scheduled_analysis_loop(
    *,
    get_next_market_trigger_time_fn,
    bjt,
    runtime_print_fn,
    has_daily_report_sent_today_fn,
    email_db_module,
    trigger_daily_analysis_fn,
):
    await app_scheduler.scheduled_analysis_loop(
        get_next_market_trigger_time_fn=get_next_market_trigger_time_fn,
        bjt=bjt,
        runtime_print_fn=runtime_print_fn,
        has_daily_report_sent_today_fn=has_daily_report_sent_today_fn,
        email_db_module=email_db_module,
        trigger_daily_analysis_fn=trigger_daily_analysis_fn,
    )


async def run_analysis_job_in_process(
    *,
    supplement_mode: bool,
    label: str,
    runtime_print_fn,
    timeout: int = 900,
) -> int:
    def run_job() -> int:
        return app_service_analysis.run_analysis_job(supplement_mode=supplement_mode)

    runtime_print_fn(f"   ▶️ 启动进程内分析任务 ({label})")
    result = await asyncio.wait_for(asyncio.to_thread(run_job), timeout=timeout)
    runtime_print_fn(f"   ✅ 进程内分析任务结束 ({label})，退出码: {result}")
    return result
