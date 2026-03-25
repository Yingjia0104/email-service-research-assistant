from __future__ import annotations

from typing import Any, Dict, List, Optional


def mark_emails_processed(
    email_uids: List[str],
    *,
    email_local_ids: Optional[List[int]] = None,
    source_emails: Optional[List[Dict[str, Any]]] = None,
    derive_email_scope_fn,
    get_local_ids_by_uids_fn,
    mark_processed_by_local_ids_fn,
    logger,
) -> None:
    uids = [uid for uid in (email_uids or []) if uid]
    if not uids:
        return

    local_ids = [lid for lid in (email_local_ids or []) if lid is not None]
    if not local_ids and source_emails:
        local_ids = [
            int(item.get("local_id"))
            for item in source_emails
            if item.get("local_id") is not None
        ]
    if not local_ids:
        account_email, folder = derive_email_scope_fn(source_emails)
        local_id_map = get_local_ids_by_uids_fn(
            uids,
            account_email=account_email,
            folder=folder,
        )
        local_ids = [local_id_map.get(uid) for uid in uids if local_id_map.get(uid) is not None]
    if local_ids:
        mark_processed_by_local_ids_fn(local_ids)
        logger.info(f"✅ 已标记 {len(uids)} 封邮件为已处理 (local_id: {min(local_ids)}-{max(local_ids)})")
    else:
        logger.warning(f"⚠️ 未找到可安全更新的 local_id，跳过 {len(uids)} 封邮件的 processed 标记")


def log_failed_report_attempt(
    *,
    email_uids: List[str],
    email_local_ids: Optional[List[int]] = None,
    is_supplement: bool = False,
    load_config_fn,
    log_sent_report_fn,
    now_fn,
) -> None:
    target_email = load_config_fn().get("target", {}).get("email", "")
    subject_prefix = "补充分析 " if is_supplement else ""
    subject = f"AI Morning Brief | {subject_prefix}{now_fn().strftime('%Y-%m-%d %H:%M')}"
    log_sent_report_fn(
        email_local_ids=email_local_ids or [],
        email_uids=email_uids or [],
        report_type="supplement" if is_supplement else "daily",
        subject=subject,
        recipient=target_email,
        status="failed",
    )


def send_report(
    report_file: str,
    email_uids: List[str],
    *,
    email_local_ids: Optional[List[int]] = None,
    source_emails: Optional[List[Dict[str, Any]]] = None,
    is_supplement: bool = False,
    load_config_fn,
    send_email_fn,
    now_fn,
    derive_email_scope_fn,
    get_local_ids_by_uids_fn,
    finalize_report_success_fn,
    logger,
) -> bool:
    config = load_config_fn()
    api_key = config.get("api_key", "")
    target_email = config.get("target", {}).get("email")

    if not target_email:
        logger.error("❌ 未配置目标邮箱")
        return False

    with open(report_file, "r", encoding="utf-8") as handle:
        html_content = handle.read()

    if is_supplement:
        supplement_note = """
        <div style="background-color: #fff3cd; border: 1px solid #ffc107; padding: 15px; margin-bottom: 20px; border-radius: 5px;">
            <strong>⚠️ 补充分析通知</strong><br>
            此报告为美股交易时段内的补充分析，可能包含延迟收到的市场信息，请注意时效性。
        </div>
        """
        html_content = html_content.replace("<body>", "<body>" + supplement_note)

    subject_prefix = "补充分析 " if is_supplement else ""
    subject = f"AI Morning Brief | {subject_prefix}{now_fn().strftime('%Y-%m-%d %H:%M')}"
    logger.info(f"📤 正在发送报告到 {target_email}...")
    del api_key

    result = send_email_fn(
        to_email=target_email,
        subject=subject,
        body=html_content,
        body_type="html",
    )
    if not result.get("success"):
        error_msg = result.get("detail", result.get("message", "未知错误"))
        logger.error(f"❌ 发送失败: {error_msg}")
        raise Exception(error_msg)

    logger.info("✅ 报告发送成功")

    uids = [uid for uid in (email_uids or []) if uid]
    local_ids = [lid for lid in (email_local_ids or []) if lid is not None]
    scope_account, scope_folder = derive_email_scope_fn(source_emails)
    if not local_ids and uids:
        local_id_map = get_local_ids_by_uids_fn(
            uids,
            account_email=scope_account,
            folder=scope_folder,
        )
        local_ids = [local_id_map.get(uid) for uid in uids if local_id_map.get(uid) is not None]

    processed_count = finalize_report_success_fn(
        email_local_ids=local_ids,
        email_uids=uids,
        report_type="supplement" if is_supplement else "daily",
        subject=subject,
        recipient=target_email,
        account_email=scope_account,
        folder=scope_folder,
    )
    logger.info(f"✅ 数据库状态已更新：{processed_count} 封邮件已标记为 processed")
    return True
