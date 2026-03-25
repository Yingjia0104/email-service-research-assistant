from __future__ import annotations

from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import smtplib
import socket
from typing import Any, Callable, Dict, List, Optional

from imap_tools import MailBox


class EmailNotFoundError(LookupError):
    """Raised when the requested email cannot be found in the remote mailbox."""


def resolve_imap_credentials(
    *,
    load_config_fn,
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> tuple[str, str]:
    cfg = load_config_fn()
    if email and password:
        email_addr = email
        email_pass = password
    else:
        imap_cfg = cfg.get("imap", {})
        email_addr = email or imap_cfg.get("email")
        email_pass = password or imap_cfg.get("password")

    if not email_addr or not email_pass:
        raise ValueError("请提供邮箱配置")

    return email_addr, email_pass


def fetch_emails(
    limit: int = 20,
    *,
    load_config_fn,
    parse_received_after_local_fn,
    should_accept_sender_fn,
    get_message_local_datetime_fn,
    build_attachment_records_fn,
    logger,
    email: Optional[str] = None,
    password: Optional[str] = None,
    folder: str = "INBOX",
    source: Optional[str] = None,
) -> List[Dict[str, Any]]:
    email_addr, email_pass = resolve_imap_credentials(
        load_config_fn=load_config_fn,
        email=email,
        password=password,
    )
    cfg = load_config_fn()
    imap_cfg = cfg.get("imap", {})
    host = source or imap_cfg.get("host", "imap.gmail.com")

    logger.info(f"📬 正在从 {host} 收取邮件...")

    local_tz = datetime.now().astimezone().tzinfo
    filters = cfg.get("filters", {})
    allowed_senders = filters.get("allowed_senders", [])
    received_after_local = parse_received_after_local_fn(filters, local_tz)

    if received_after_local:
        logger.info(f"📅 收件起点: {received_after_local.isoformat()} (本地时区: {local_tz})")
    else:
        logger.info(f"📅 收件起点: 不限制 (本地时区: {local_tz})")
    logger.info(f"🔍 发件人过滤: {allowed_senders}")

    emails: List[Dict[str, Any]] = []
    fetch_limit = max(limit * 5, 50)
    with MailBox(host, timeout=30).login(email_addr, email_pass) as mailbox:
        for msg in mailbox.fetch(limit=fetch_limit, reverse=True):
            from_addr = str(msg.from_)
            msg_local_dt = get_message_local_datetime_fn(msg.date, local_tz)

            if received_after_local and msg_local_dt and msg_local_dt < received_after_local:
                continue
            if not should_accept_sender_fn(from_addr, allowed_senders):
                continue

            body = msg.text or msg.html or ""
            attachment_contents, embedded_images, attachment_records = build_attachment_records_fn(msg)

            combined_body = body or ""
            if attachment_contents:
                combined_body += "\n\n--- 附件内容 ---\n"
                for att in attachment_contents:
                    combined_body += f"\n【附件: {att['filename']}】\n{att['content']}\n"

            if embedded_images:
                combined_body += "\n\n--- 附件图片 ---\n"
                for img in embedded_images:
                    vision_status = "将直接送入多模态模型" if img.get("vision_ready") else "仅保留元数据（图片过大）"
                    combined_body += (
                        f"\n【图片附件: {img['filename']}】"
                        f" 类型: {img['content_type']}, 大小: {img['size']} bytes, 处理方式: {vision_status}\n"
                    )

            emails.append(
                {
                    "account_email": email_addr,
                    "folder": folder,
                    "id": msg.uid,
                    "from": from_addr,
                    "from_name": msg.from_values.name if msg.from_values else "",
                    "to": str(msg.to),
                    "subject": msg.subject,
                    "date": str(msg.date) if msg.date else "",
                    "preview": (combined_body or "")[:200],
                    "body": combined_body,
                    "attachments": attachment_records,
                }
            )
            if len(emails) >= limit:
                break

    logger.info(f"✅ 成功收取 {len(emails)} 封邮件")
    return emails


def get_email_by_id(
    *,
    email_id: int,
    source: str,
    load_config_fn,
    email: Optional[str] = None,
    password: Optional[str] = None,
) -> Dict[str, Any]:
    email_addr, email_pass = resolve_imap_credentials(
        load_config_fn=load_config_fn,
        email=email,
        password=password,
    )

    with MailBox(source, timeout=30).login(email_addr, email_pass) as mailbox:
        for msg in mailbox.fetch(limit=100, reverse=True):
            if str(getattr(msg, "uid", "")) == str(email_id):
                return {
                    "id": msg.uid,
                    "from": str(msg.from_),
                    "from_name": msg.from_values.name if msg.from_values else "",
                    "to": str(msg.to),
                    "subject": msg.subject,
                    "date": str(msg.date) if msg.date else "",
                    "body": msg.text or msg.html or "",
                    "read": msg.seen,
                }

    raise EmailNotFoundError(f"邮件未找到: {email_id}")


def fetch_emails_and_persist(
    limit: int = 20,
    *,
    load_config_fn,
    parse_received_after_local_fn,
    should_accept_sender_fn,
    get_message_local_datetime_fn,
    build_attachment_records_fn,
    email_db_module,
    logger,
) -> List[Dict[str, Any]]:
    emails = fetch_emails(
        limit,
        load_config_fn=load_config_fn,
        parse_received_after_local_fn=parse_received_after_local_fn,
        should_accept_sender_fn=should_accept_sender_fn,
        get_message_local_datetime_fn=get_message_local_datetime_fn,
        build_attachment_records_fn=build_attachment_records_fn,
        logger=logger,
    )
    try:
        added = email_db_module.add_emails(emails)
        if added:
            logger.info(f"💾 已新增 {added} 封邮件到 SQLite")
    except Exception as exc:
        logger.warning(f"⚠️ 写入数据库失败（将继续尝试分析本次收取结果）: {exc}")
    return emails


def send_email_sync(
    smtp_host,
    smtp_port,
    use_ssl,
    timeout_seconds,
    from_email,
    password,
    to_email,
    subject,
    body,
    body_type,
    *,
    mime_multipart_cls=MIMEMultipart,
    mime_text_cls=MIMEText,
) -> Dict[str, Any]:
    msg = mime_multipart_cls("alternative")
    msg["Subject"] = subject
    msg["From"] = from_email
    msg["To"] = to_email
    msg.attach(mime_text_cls(body, body_type, "utf-8"))

    use_ssl = use_ssl or smtp_port == 465
    server = None
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout_seconds)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_seconds)
            server.ehlo()
            server.starttls()
            server.ehlo()
        server.login(from_email, password)
        server.send_message(msg)
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

    return {"success": True, "message": "邮件发送成功"}


def classify_smtp_exception(exc: Exception) -> tuple[int, str]:
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 504, f"SMTP连接或发送超时: {exc}"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 502, "SMTP认证失败，请检查邮箱地址、授权码或应用专用密码"
    if isinstance(exc, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionRefusedError, OSError)):
        return 502, f"SMTP连接失败: {exc}"
    return 500, f"发送失败: {exc}"


def send_email(
    *,
    load_config_fn,
    to_email: str,
    subject: str,
    body: str,
    body_type: str = "plain",
) -> Dict[str, Any]:
    smtp_cfg = load_config_fn().get("smtp", {})
    from_email = smtp_cfg.get("email")
    password = smtp_cfg.get("password")
    if not from_email or not password:
        raise ValueError("未配置 SMTP 发件邮箱或密码")

    return send_email_sync(
        smtp_cfg.get("host", "smtp.gmail.com"),
        smtp_cfg.get("port", 587),
        smtp_cfg.get("use_ssl", False),
        smtp_cfg.get("timeout_seconds", 30),
        from_email,
        password,
        to_email,
        subject,
        body,
        body_type,
    )
