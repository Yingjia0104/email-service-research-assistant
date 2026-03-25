from __future__ import annotations

from typing import Any, Optional

from app.mail import fetcher as app_mail_fetcher


IMAGE_EXTENSIONS = (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".heic", ".heif")
MAX_MULTIMODAL_IMAGE_BYTES = 4 * 1024 * 1024
MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS = 12000
ATTACHMENT_SIGNATURE_MARKERS = (
    "best regards",
    "kind regards",
    "warm regards",
    "regards",
    "many thanks",
    "thanks,",
    "thanks and regards",
    "thank you,",
    "cheers,",
    "sent from my iphone",
    "sent from my ipad",
    "sent from outlook",
    "sent via outlook",
    "此致",
    "敬礼",
    "祝好",
    "谢谢",
    "--",
)
ATTACHMENT_DISCLAIMER_MARKERS = (
    "免责声明",
    "confidentiality notice",
    "this message and any attachment",
    "this e-mail and any attachments",
    "this email and any attachments",
    "the information contained in this e-mail",
    "the information contained in this email",
    "the contents of this email",
    "privileged and confidential",
    "本邮件及其附件",
    "本电子邮件",
    "重要提示",
    "法律声明",
)


def extract_attachment_bytes(att):
    """统一提取附件二进制。"""
    return app_mail_fetcher.extract_attachment_bytes(att)


def clean_extracted_attachment_text(text, filename=""):
    """清洗 .msg/.eml/.pdf 等附件提取文本，避免转发噪音压垮分析上下文。"""
    return app_mail_fetcher.clean_extracted_attachment_text(
        text,
        filename=filename,
        max_extracted_attachment_text_chars=MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS,
        attachment_signature_markers=ATTACHMENT_SIGNATURE_MARKERS,
        attachment_disclaimer_markers=ATTACHMENT_DISCLAIMER_MARKERS,
    )


def build_attachment_records(msg, *, logger):
    """提取附件记录；图片默认保留 data URL 供多模态模型直接使用。"""
    return app_mail_fetcher.build_attachment_records(
        msg,
        image_extensions=IMAGE_EXTENSIONS,
        max_multimodal_image_bytes=MAX_MULTIMODAL_IMAGE_BYTES,
        extract_attachment_bytes_fn=extract_attachment_bytes,
        clean_extracted_attachment_text_fn=clean_extracted_attachment_text,
        logger=logger,
    )


def get_message_local_date(msg_datetime, local_tz):
    """将邮件时间统一转换到本地时区后再取日期。"""
    return app_mail_fetcher.get_message_local_date(msg_datetime, local_tz)


def get_message_local_datetime(msg_datetime, local_tz):
    """将邮件时间统一转换到本地时区。"""
    return app_mail_fetcher.get_message_local_datetime(msg_datetime, local_tz)


def parse_received_after_local(filters: dict, local_tz, *, logger: Any):
    """解析可选的本地时间阈值，用于联调时忽略历史邮件。"""
    return app_mail_fetcher.parse_received_after_local(filters, local_tz, logger)


def extract_sender_email(from_addr: str) -> str:
    """从发件人字段中提取纯邮箱地址。"""
    return app_mail_fetcher.extract_sender_email(from_addr)


def match_allowed_sender(email_addr: str, allowed_senders: list) -> Optional[str]:
    """返回命中的白名单项（精确邮箱或后缀），未命中则返回 None。"""
    return app_mail_fetcher.match_allowed_sender(email_addr, allowed_senders)


def should_accept_sender(from_addr: str, allowed_senders: list) -> bool:
    """统一发件人过滤逻辑。"""
    return app_mail_fetcher.should_accept_sender(
        from_addr,
        allowed_senders,
        extract_sender_email_fn=extract_sender_email,
        match_allowed_sender_fn=match_allowed_sender,
    )


def get_expected_senders(cfg: dict) -> list:
    """获取当前自动触发逻辑中要等待的全部白名单 sales 名单。"""
    return app_mail_fetcher.get_expected_senders(cfg)
