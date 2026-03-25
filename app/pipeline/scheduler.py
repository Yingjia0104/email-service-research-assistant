from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional


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
    cfg = load_config_fn()
    bg_cfg = cfg.get("background", {})
    if not bg_cfg.get("enabled", False):
        return

    limit = bg_cfg.get("limit", 20)

    now_local = __import__("datetime").datetime.now().astimezone()
    filters = cfg.get("filters", {})
    allowed_senders = filters.get("allowed_senders", [])
    status_before = email_db_module.get_status()

    runtime_print_fn("📬 [后台] 正在收取邮件...")
    runtime_print_fn(f"   🔍 发件人过滤: {allowed_senders}")
    runtime_print_fn(
        f"   📊 数据库状态: 总计 {status_before['total']}, 待处理 {status_before['pending']}, 已处理 {status_before['processed']}"
    )

    try:
        fetched_emails = await asyncio.to_thread(fetch_emails_and_persist_fn, limit)
        status_after = email_db_module.get_status()
        added_count = max(status_after["total"] - status_before["total"], 0)
        runtime_print_fn(f"✅ [后台] 本轮抓取 {len(fetched_emails)} 封，新增入库 {added_count} 封")
        runtime_print_fn(f"   📊 待处理邮件: {status_after['pending']} 封")

        if not has_daily_report_sent_today_fn():
            should_early_run, reason = should_trigger_early_daily_fn(allowed_senders, bg_cfg, now_local)
            if should_early_run:
                runtime_print_fn(f"🚀 [后台] 提前触发 daily 分析：{reason}")
                await trigger_daily_analysis_fn(reason="all_senders_arrived_quiet")
                return
            runtime_print_fn(f"   ⏳ 本轮暂不 early run：{reason}")

        if added_count > 0 and is_in_supplement_window_fn():
            await trigger_supplement_analysis_fn(added_count)
    except Exception as exc:
        runtime_print_fn(f"❌ [后台] 收取邮件失败: {exc}")


async def background_fetch_loop(*, load_config_fn, fetch_and_save_emails_fn, runtime_print_fn):
    bg_cfg = load_config_fn().get("background", {})
    if not bg_cfg.get("enabled", False):
        runtime_print_fn("⚠️ 后台收取已禁用")
        return

    interval = bg_cfg.get("interval_minutes", 15) * 60
    runtime_print_fn(f"⏰ 后台收取已启用，每 {bg_cfg.get('interval_minutes', 15)} 分钟收取一次邮件")

    while True:
        await fetch_and_save_emails_fn()
        await asyncio.sleep(interval)


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
    if new_emails_count == 0:
        return
    if not has_daily_report_sent_today_fn():
        runtime_print_fn("   ⏭️ 今日尚未发送 daily 报告，跳过 supplement")
        return

    lock_handle = try_acquire_analysis_lock_fn()
    if lock_handle is None:
        runtime_print_fn("   ⏭️ 当前已有分析任务运行中，跳过本次 supplement")
        return

    pending_emails = email_db_module.get_pending_emails(limit=50)
    if not pending_emails:
        runtime_print_fn("   📭 没有待处理的邮件，跳过补充分析")
        return

    recent_supplement = email_db_module.get_recent_successful_report(report_type="supplement", within_hours=1)
    if recent_supplement:
        runtime_print_fn("   ⏭️ 1小时内已发送过 supplement，跳过本次补充分析")
        return

    runtime_print_fn("=" * 50)
    runtime_print_fn("📈 检测到开盘期间新邮件，触发补充分析！")
    runtime_print_fn("=" * 50)
    runtime_print_fn(f"   📧 待处理邮件数: {len(pending_emails)}")

    try:
        try:
            exit_code = await run_analysis_job_fn(supplement_mode=True, label="supplement")
            if exit_code != 0:
                runtime_print_fn(f"❌ 补充分析退出码异常: {exit_code}")
        except asyncio.TimeoutError:
            runtime_print_fn("❌ 补充分析超时")
        except Exception as exc:
            runtime_print_fn(f"❌ 补充分析失败: {exc}")
    finally:
        release_analysis_lock_fn(lock_handle)


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
    lock_handle = try_acquire_analysis_lock_fn()
    if lock_handle is None:
        runtime_print_fn(f"   ⏭️ 当前已有分析任务运行中，跳过 daily ({reason})")
        return

    pending = email_db_module.get_pending_emails(limit=1)
    if not pending:
        runtime_print_fn("   📭 没有待处理邮件，跳过 daily 分析")
        return

    runtime_print_fn("=" * 50)
    runtime_print_fn(f"📨 触发 daily 分析 ({reason})")
    runtime_print_fn("=" * 50)

    try:
        if has_daily_report_sent_today_fn():
            runtime_print_fn(f"   ⏭️ 今日已发送 daily 报告，跳过 ({reason})")
            return
        pending = email_db_module.get_pending_emails(limit=1)
        if not pending:
            runtime_print_fn("   📭 没有待处理邮件，跳过 daily 分析")
            return
        try:
            exit_code = await run_analysis_job_fn(supplement_mode=False, label=f"daily/{reason}")
            if exit_code != 0:
                runtime_print_fn(f"❌ daily 分析退出码异常: {exit_code}")
        except asyncio.TimeoutError:
            runtime_print_fn("❌ daily 分析超时")
        except Exception as exc:
            runtime_print_fn(f"❌ daily 分析失败: {exc}")
    finally:
        release_analysis_lock_fn(lock_handle)


async def scheduled_analysis_loop(
    *,
    get_next_market_trigger_time_fn,
    bjt,
    runtime_print_fn,
    has_daily_report_sent_today_fn,
    email_db_module,
    trigger_daily_analysis_fn,
):
    next_trigger = get_next_market_trigger_time_fn()
    runtime_print_fn("⏰ 定时分析已启用")
    runtime_print_fn(f"   📈 收件截止时间: 美股开盘前15分钟（北京时间 {next_trigger.strftime('%Y-%m-%d %H:%M')}）")

    while True:
        now = __import__("datetime").datetime.now(bjt)
        next_trigger = get_next_market_trigger_time_fn(now)
        wait_seconds = (next_trigger - now).total_seconds()
        runtime_print_fn(f"   ⏳ 分析启动时间: {next_trigger.strftime('%Y-%m-%d %H:%M')} ({(wait_seconds/3600):.1f}小时后)")
        await asyncio.sleep(wait_seconds)

        if has_daily_report_sent_today_fn():
            runtime_print_fn("   ⏭️ 今日已发送 daily 报告，跳过")
            continue

        pending = email_db_module.get_pending_emails(limit=1)
        if not pending:
            runtime_print_fn("   ⏭️ 没有待处理邮件，跳过")
            continue

        await trigger_daily_analysis_fn(reason="ddl_reached")
