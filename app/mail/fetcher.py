from __future__ import annotations

import base64
import mimetypes
import re
from datetime import datetime
from email.utils import parseaddr
from typing import Any, Dict, List, Optional, Tuple


def extract_attachment_bytes(att: Any) -> Optional[bytes]:
    """统一提取附件二进制。"""
    if hasattr(att, "payload") and isinstance(att.payload, bytes):
        return att.payload
    if hasattr(att, "data") and isinstance(att.data, bytes):
        return att.data
    return None


def clean_extracted_attachment_text(
    text: str,
    *,
    filename: str = "",
    max_extracted_attachment_text_chars: int,
    attachment_signature_markers: Tuple[str, ...],
    attachment_disclaimer_markers: Tuple[str, ...],
) -> str:
    """清洗 .msg/.eml/.pdf 等附件提取文本。"""
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\u200b", " ").replace("\xa0", " ")
    cleaned = re.sub(r"<https?://[^>\s]+>", "[link]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"https?://\S+", "[link]", cleaned, flags=re.IGNORECASE)

    kept_lines = []
    meaningful_chars = 0
    non_empty_lines = 0

    for line in cleaned.split("\n"):
        stripped = line.strip()
        normalized = stripped.lower()

        if stripped:
            non_empty_lines += 1
            meaningful_chars += len(stripped)

        has_enough_content = meaningful_chars >= 80 or non_empty_lines >= 4
        if has_enough_content:
            if any(normalized.startswith(marker) for marker in attachment_signature_markers) and len(stripped) <= 120:
                break
            if any(marker in normalized for marker in attachment_disclaimer_markers):
                break

        kept_lines.append(line)

    cleaned = "\n".join(kept_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    if len(cleaned) > max_extracted_attachment_text_chars:
        cleaned = cleaned[:max_extracted_attachment_text_chars].rstrip() + "\n\n[附件内容已截断]"

    return cleaned


def build_attachment_records(
    msg: Any,
    *,
    image_extensions: Tuple[str, ...],
    max_multimodal_image_bytes: int,
    extract_attachment_bytes_fn,
    clean_extracted_attachment_text_fn,
    logger: Any,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]], List[Dict[str, Any]]]:
    """提取附件记录；图片默认保留 data URL 供多模态模型直接使用。"""
    attachment_contents = []
    embedded_images = []
    attachment_records = []

    if not msg.attachments:
        return attachment_contents, embedded_images, attachment_records

    for att in msg.attachments:
        filename = resolve_attachment_filename(att)
        if not filename:
            continue

        lower_filename = filename.lower()
        content_type = getattr(att, "content_type", "") or mimetypes.guess_type(filename)[0] or "application/octet-stream"

        try:
            att_data = extract_attachment_bytes_fn(att)
            if not att_data:
                continue

            is_image = content_type.startswith("image/") or any(lower_filename.endswith(ext) for ext in image_extensions)
            attachment_record = {
                "filename": filename,
                "content_type": content_type,
                "size": len(att_data),
                "kind": "image" if is_image else "file",
            }

            if is_image:
                if len(att_data) <= max_multimodal_image_bytes:
                    attachment_record["data_url"] = f"data:{content_type};base64,{base64.b64encode(att_data).decode('ascii')}"
                    attachment_record["vision_ready"] = True
                else:
                    attachment_record["vision_ready"] = False
                    attachment_record["vision_skip_reason"] = f"image_too_large>{max_multimodal_image_bytes}"

                embedded_images.append(
                    {
                        "filename": filename,
                        "content_type": content_type,
                        "size": len(att_data),
                        "vision_ready": attachment_record.get("vision_ready", False),
                    }
                )
                attachment_records.append(attachment_record)
                continue

            att_text = ""
            if lower_filename.endswith(".msg"):
                import extract_msg
                from io import BytesIO

                msg_file = extract_msg.Message(BytesIO(att_data))
                att_text = msg_file.body or ""

            elif lower_filename.endswith(".pdf"):
                try:
                    import PyPDF2
                    from io import BytesIO

                    pdf_reader = PyPDF2.PdfReader(BytesIO(att_data))
                    for page in pdf_reader.pages:
                        att_text += page.extract_text() or ""
                except Exception as exc:
                    logger.warning(f"PDF解析失败 {filename}: {exc}")

            elif lower_filename.endswith((".docx", ".doc")):
                try:
                    import docx
                    from io import BytesIO

                    doc = docx.Document(BytesIO(att_data))
                    for para in doc.paragraphs:
                        att_text += para.text + "\n"
                except Exception as exc:
                    logger.warning(f"Word解析失败 {filename}: {exc}")

            elif lower_filename.endswith(".txt"):
                try:
                    att_text = att_data.decode("utf-8", errors="ignore")
                except Exception:
                    att_text = ""

            elif lower_filename.endswith(".eml"):
                try:
                    from email import policy
                    from email.parser import BytesParser

                    nested_msg = BytesParser(policy=policy.default).parsebytes(att_data)
                    att_text = nested_msg.body or ""
                except Exception as exc:
                    logger.warning(f"EML解析失败 {filename}: {exc}")

            att_text = clean_extracted_attachment_text_fn(att_text, filename=filename)

            if att_text and att_text.strip():
                attachment_contents.append({"filename": filename, "content": att_text.strip()})
                attachment_record["extracted_text"] = att_text.strip()

            attachment_records.append(attachment_record)
        except Exception as exc:
            logger.warning(f"附件解析失败 {filename}: {exc}")
            continue

    return attachment_contents, embedded_images, attachment_records


def resolve_attachment_filename(att: Any) -> str:
    """兼容 extract_msg 附件只暴露 longFilename/displayName 的情况。"""
    for attr in ("filename", "longFilename", "shortFilename", "displayName", "name"):
        value = getattr(att, attr, None)
        if value:
            return str(value).strip()
    return ""


def get_message_local_date(msg_datetime, local_tz):
    """将邮件时间统一转换到本地时区后再取日期。"""
    if not msg_datetime:
        return None
    if msg_datetime.tzinfo is None:
        return msg_datetime.date()
    return msg_datetime.astimezone(local_tz).date()


def get_message_local_datetime(msg_datetime, local_tz):
    """将邮件时间统一转换到本地时区。"""
    if not msg_datetime:
        return None
    if msg_datetime.tzinfo is None:
        if hasattr(local_tz, "localize"):
            return local_tz.localize(msg_datetime)
        return msg_datetime.replace(tzinfo=local_tz)
    return msg_datetime.astimezone(local_tz)


def parse_received_after_local(filters: dict, local_tz, logger: Any):
    """解析可选的本地时间阈值。"""
    raw_value = (filters or {}).get("received_after_local")
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value))
        if parsed.tzinfo is None:
            if hasattr(local_tz, "localize"):
                return local_tz.localize(parsed)
            return parsed.replace(tzinfo=local_tz)
        return parsed.astimezone(local_tz)
    except Exception:
        logger.warning(f"无效的 received_after_local 配置: {raw_value}")
        return None


def extract_sender_email(from_addr: str) -> str:
    """从发件人字段中提取纯邮箱地址。"""
    if not from_addr:
        return ""
    _, email_addr = parseaddr(from_addr)
    return (email_addr or from_addr).strip().lower()


def match_allowed_sender(email_addr: str, allowed_senders: list) -> Optional[str]:
    """返回命中的白名单项。"""
    normalized_email = (email_addr or "").strip().lower()
    for sender in allowed_senders or []:
        sender_key = (sender or "").strip().lower()
        if not sender_key:
            continue
        if sender_key.startswith("@"):
            if normalized_email.endswith(sender_key):
                return sender_key
        elif normalized_email == sender_key:
            return sender_key
    return None


def should_accept_sender(from_addr: str, allowed_senders: list, *, extract_sender_email_fn, match_allowed_sender_fn) -> bool:
    """统一发件人过滤逻辑。"""
    if not allowed_senders:
        return True
    return match_allowed_sender_fn(extract_sender_email_fn(from_addr), allowed_senders) is not None


def get_expected_senders(cfg: dict) -> list:
    """获取当前自动触发逻辑中要等待的全部白名单 sales 名单。"""
    filters = cfg.get("filters", {})
    return [(sender or "").strip().lower() for sender in filters.get("allowed_senders", []) if sender]
