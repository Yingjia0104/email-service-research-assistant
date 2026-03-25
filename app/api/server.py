from __future__ import annotations

import asyncio
import json
from typing import Any, Callable, Dict, Optional

from app.mail import service as app_mail_service


def root_payload() -> Dict[str, str]:
    return {"service": "邮件服务 API", "version": "1.0.0"}


def health_payload() -> Dict[str, str]:
    return {"status": "ok"}


def get_emails(
    *,
    api_key: Optional[str],
    email: Optional[str],
    password: Optional[str],
    folder: str,
    limit: int,
    source: str,
    verify_api_key_fn: Callable[[str], bool],
    load_config_fn: Callable[[], Dict[str, Any]],
    parse_received_after_local_fn,
    should_accept_sender_fn,
    get_message_local_datetime_fn,
    build_attachment_records_fn,
    logger: Any,
    http_exception_cls,
) -> Dict[str, Any]:
    if not verify_api_key_fn(api_key):
        raise http_exception_cls(status_code=401, detail="API密钥无效或未提供")

    try:
        email_addr, email_pass = app_mail_service.resolve_imap_credentials(
            load_config_fn=load_config_fn,
            email=email,
            password=password,
        )
        emails = app_mail_service.fetch_emails(
            limit=limit,
            load_config_fn=load_config_fn,
            parse_received_after_local_fn=parse_received_after_local_fn,
            should_accept_sender_fn=should_accept_sender_fn,
            get_message_local_datetime_fn=get_message_local_datetime_fn,
            build_attachment_records_fn=build_attachment_records_fn,
            logger=logger,
            email=email_addr,
            password=email_pass,
            folder=folder,
            source=source,
        )
        normalized_emails = []
        for item in emails:
            normalized = dict(item)
            attachments = normalized.get("attachments")
            if isinstance(attachments, list):
                normalized["attachments"] = json.dumps(attachments, ensure_ascii=False)
            normalized_emails.append(normalized)
        return {"success": True, "emails": normalized_emails, "total": len(normalized_emails)}
    except ValueError as exc:
        raise http_exception_cls(status_code=400, detail=str(exc))
    except Exception as exc:
        raise http_exception_cls(status_code=500, detail=f"收取邮件失败: {str(exc)}")


def get_email_by_id(
    *,
    email_id: int,
    api_key: Optional[str],
    email: Optional[str],
    password: Optional[str],
    source: str,
    verify_api_key_fn: Callable[[str], bool],
    load_config_fn: Callable[[], Dict[str, Any]],
    http_exception_cls,
) -> Dict[str, Any]:
    if not verify_api_key_fn(api_key):
        raise http_exception_cls(status_code=401, detail="API密钥无效或未提供")

    try:
        email_record = app_mail_service.get_email_by_id(
            email_id=email_id,
            source=source,
            load_config_fn=load_config_fn,
            email=email,
            password=password,
        )
        return {"success": True, "email": email_record}
    except ValueError as exc:
        raise http_exception_cls(status_code=400, detail=str(exc))
    except app_mail_service.EmailNotFoundError:
        raise http_exception_cls(status_code=404, detail="邮件未找到")
    except Exception as exc:
        raise http_exception_cls(status_code=500, detail=str(exc))


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
    mime_multipart_cls,
    mime_text_cls,
) -> Dict[str, Any]:
    return app_mail_service.send_email_sync(
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
        mime_multipart_cls=mime_multipart_cls,
        mime_text_cls=mime_text_cls,
    )


def classify_smtp_exception(exc: Exception) -> tuple[int, str]:
    return app_mail_service.classify_smtp_exception(exc)


async def send_email_smtp(
    smtp_host,
    smtp_port,
    from_email,
    password,
    to_email,
    subject,
    body,
    body_type,
    *,
    use_ssl=False,
    timeout_seconds=30,
    send_email_sync_fn,
    classify_smtp_exception_fn,
    http_exception_cls,
):
    try:
        return await asyncio.to_thread(
            send_email_sync_fn,
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
        )
    except Exception as exc:
        status_code, detail = classify_smtp_exception_fn(exc)
        raise http_exception_cls(status_code=status_code, detail=detail)
