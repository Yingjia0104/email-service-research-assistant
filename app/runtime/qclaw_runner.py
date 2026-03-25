from __future__ import annotations

from typing import Any, Dict, List


def run_analysis_mode(
    *,
    email_db_module,
    analyze_emails_with_llm_fn,
    save_report_fn,
    send_report_fn,
    log_failed_report_attempt_fn,
    record_run_error_fn,
    logger,
    supplement_mode: bool = False,
) -> None:
    logger.info("📊 分析模式：调用当前 LLM 链路分析已存在的邮件")

    emails = email_db_module.get_pending_emails(limit=20)
    if not emails:
        logger.warning("📭 没有待分析的邮件")
        return

    logger.info(f"📧 待分析邮件数: {len(emails)}")

    try:
        html_content = analyze_emails_with_llm_fn(emails)
    except Exception as exc:
        logger.error(f"❌ 大模型分析失败: {exc}")
        record_run_error_fn(f"分析失败: {str(exc)[:100]}")
        return

    if not html_content:
        logger.error("❌ 大模型分析失败")
        return

    report_file = save_report_fn(html_content, source_emails=emails)
    if not report_file:
        logger.error("❌ 保存报告失败")
        return

    logger.info("✅ 分析完成！报告已生成")
    logger.info("📤 发送报告...")

    email_uids = [item.get("id") for item in emails if item.get("id")]
    email_local_ids = [item.get("local_id") for item in emails if item.get("local_id") is not None]
    try:
        send_success = send_report_fn(
            report_file,
            email_uids=email_uids,
            email_local_ids=email_local_ids,
            source_emails=emails,
            is_supplement=supplement_mode,
        )
    except Exception as exc:
        logger.error(f"❌ 发送报告失败: {exc}")
        try:
            log_failed_report_attempt_fn(
                email_uids=email_uids,
                email_local_ids=email_local_ids,
                is_supplement=supplement_mode,
            )
        except Exception:
            pass
        return

    if send_success:
        logger.info("✅ 邮件已完成发送与状态落库")
    else:
        logger.warning("⚠️ 发送失败，邮件保留为待处理状态")

    if supplement_mode:
        logger.info("✅ 补充分析完成，已单独推送")


def run_normal_mode(
    *,
    force_mode: bool,
    should_trigger_fn,
    fetch_emails_fn,
    email_db_module,
    analyze_emails_with_llm_fn,
    save_report_fn,
    send_report_fn,
    cleanup_fn,
    log_failed_report_attempt_fn,
    record_run_error_fn,
    record_run_success_fn,
    logger,
    supplement_mode: bool = False,
) -> None:
    if force_mode:
        logger.warning("⚠️ 强制模式（忽略时间检查）")
    elif not should_trigger_fn():
        logger.info("⏰ 今天已经处理过，跳过")
        print("提示: 使用 --force 强制运行，或 --check 检查状态")
        return

    logger.info("【步骤 1/4】收取邮件...")
    try:
        fetch_emails_fn(limit=20)
    except Exception as exc:
        logger.error(f"❌ 收取邮件失败: {exc}")
        record_run_error_fn(f"收取邮件失败: {str(exc)[:100]}")
        return

    emails = email_db_module.get_pending_emails(limit=20)
    if not emails:
        logger.warning("📭 没有待处理的邮件")
        return
    logger.info(f"📭 待处理邮件数: {len(emails)}")

    logger.info("【步骤 2/4】LLM / 备用链路分析...")
    try:
        html_content = analyze_emails_with_llm_fn(emails)
    except Exception as exc:
        logger.error(f"❌ 大模型分析失败: {exc}")
        record_run_error_fn(f"AI分析失败: {str(exc)[:100]}")
        return

    if not html_content:
        logger.error("❌ 大模型分析失败，跳过后续步骤")
        return

    report_file = save_report_fn(html_content, source_emails=emails)
    if not report_file:
        logger.error("❌ 保存报告失败，跳过后续步骤")
        return

    logger.info("【步骤 3/4】发送报告...")
    email_uids = [item.get("id") for item in emails if item.get("id")]
    email_local_ids = [item.get("local_id") for item in emails if item.get("local_id") is not None]
    try:
        send_success = send_report_fn(
            report_file,
            email_uids=email_uids,
            email_local_ids=email_local_ids,
            source_emails=emails,
            is_supplement=supplement_mode,
        )
    except Exception as exc:
        logger.error(f"❌ 发送报告失败: {exc}")
        try:
            log_failed_report_attempt_fn(
                email_uids=email_uids,
                email_local_ids=email_local_ids,
                is_supplement=supplement_mode,
            )
        except Exception:
            pass
        record_run_error_fn(f"发送失败: {str(exc)[:100]}")
        print("   ⚠️ 发送失败，保留文件待重试")
        return

    if send_success:
        record_run_success_fn()
        logger.info("✅ 邮件已完成发送与状态落库")
    else:
        try:
            log_failed_report_attempt_fn(
                email_uids=email_uids,
                email_local_ids=email_local_ids,
                is_supplement=supplement_mode,
            )
        except Exception:
            pass
        record_run_error_fn("发送失败")
        print("   ⚠️ 发送失败，保留文件待重试")
        return

    cleanup_fn()
    logger.info("✅ 流程完成")
    print("\n✅ 流程完成")
