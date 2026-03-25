from __future__ import annotations

import re
from html import unescape
from typing import Any, Callable, Dict, List, Optional, Tuple

TARGET_ANALYSIS_BATCH_BODY_CHARS = 30000
MAX_ANALYSIS_BATCHES = 5
IMG_TAG_RE = re.compile(r"(?is)<img\b[^>]*>")
IMAGE_INLINE_PLACEHOLDER_RE = re.compile(r"\[图片位置:inline:(\d+)\]")
IMAGE_CID_PLACEHOLDER_RE = re.compile(r"\[图片位置:cid:([^\]]+)\]")
GENERIC_IMAGE_PLACEHOLDER = "[图片引用已省略]"
LEADING_NOISE_MARKERS = (
    "sales commentary -- not a product of",
    "not a product of ms research",
    "for institutional distribution only",
)
DISCLAIMER_TAIL_MARKERS = (
    "if you have received this communication in error",
    "general disclaimers",
    "privacy policies",
    "this email and any files attached may be sensitive",
    "this email and any files attached may be confidential",
    "country specific disclosures",
    "this message is subject to terms at",
    "www.jpmm.com/#mardisclosures",
    "www.jpmorgan.com/salesandtradingdisclaimer",
)


def is_prepared_email(email: Dict[str, Any]) -> bool:
    """判断邮件是否已经完成过分析前预处理。"""
    if not isinstance(email, dict):
        return False
    return "_analysis_body" in email and "_analysis_index" in email


def normalize_marker_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def extract_img_src_from_tag(tag: str) -> str:
    if not tag:
        return ""
    match = re.search(
        r"""(?is)\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^'"\s>]+))""",
        tag,
    )
    if not match:
        return ""
    return (match.group(1) or match.group(2) or match.group(3) or "").strip()


def normalize_cid_token(src: str) -> str:
    normalized = str(src or "").strip()
    if normalized.lower().startswith("cid:"):
        normalized = normalized[4:]
    normalized = normalized.strip("<>").strip()
    if "@" in normalized:
        normalized = normalized.split("@", 1)[0]
    return normalized.strip().lower()


def replace_img_tags_with_position_placeholders(body: str) -> str:
    if not body:
        return ""

    seen_data_urls = set()
    inline_index = 0

    def replace(match: re.Match) -> str:
        nonlocal inline_index
        tag = match.group(0)
        src = extract_img_src_from_tag(tag)
        normalized_src = re.sub(r"\s+", "", src)
        lower_src = normalized_src.lower()
        if lower_src.startswith("data:image/"):
            if normalized_src in seen_data_urls:
                return GENERIC_IMAGE_PLACEHOLDER
            inline_index += 1
            seen_data_urls.add(normalized_src)
            return f"[图片位置:inline:{inline_index}]"
        if lower_src.startswith("cid:"):
            cid_token = normalize_cid_token(normalized_src)
            if cid_token:
                return f"[图片位置:cid:{cid_token}]"
        return GENERIC_IMAGE_PLACEHOLDER

    return IMG_TAG_RE.sub(replace, body)


def strip_leading_noise(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    cut_index = 0
    while cut_index < len(lines):
        stripped = lines[cut_index].strip()
        normalized = normalize_marker_text(stripped)
        if not stripped:
            cut_index += 1
            continue
        if stripped == GENERIC_IMAGE_PLACEHOLDER:
            cut_index += 1
            continue
        if any(marker in normalized for marker in LEADING_NOISE_MARKERS):
            cut_index += 1
            continue
        break
    return "\n".join(lines[cut_index:]).strip()


def strip_trailing_disclaimer_blocks(text: str) -> str:
    if not text:
        return ""
    lines = text.split("\n")
    for idx, line in enumerate(lines):
        normalized = normalize_marker_text(line)
        if any(marker in normalized for marker in DISCLAIMER_TAIL_MARKERS):
            return "\n".join(lines[:idx]).strip()
    return text.strip()


def strip_image_placeholders(text: str) -> str:
    if not text:
        return ""
    lines = []
    for line in str(text).split("\n"):
        stripped = line.strip()
        if not stripped:
            lines.append(line)
            continue
        if stripped == GENERIC_IMAGE_PLACEHOLDER:
            continue
        if IMAGE_INLINE_PLACEHOLDER_RE.fullmatch(stripped):
            continue
        if IMAGE_CID_PLACEHOLDER_RE.fullmatch(stripped):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def build_visual_context_insertion_text(block_text: str) -> str:
    if isinstance(block_text, dict):
        core_signal = str(block_text.get("core_signal") or "").strip()
        return core_signal
    return str(block_text or "").strip()


def normalize_merged_body(text: str) -> str:
    normalized = str(text or "")
    normalized = re.sub(r"[ \t]+\n", "\n", normalized)
    normalized = re.sub(r"\n[ \t]+", "\n", normalized)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip()


def merge_visual_context_into_body(
    body: str,
    *,
    visual_context: Dict[str, Any],
    render_email_visual_context_text_fn: Callable[[Dict[str, Any]], str],
) -> Tuple[str, str]:
    working_body = str(body or "").strip()
    body_without_internal_placeholders = strip_image_placeholders(
        strip_leading_noise(
            IMAGE_INLINE_PLACEHOLDER_RE.sub(
                GENERIC_IMAGE_PLACEHOLDER,
                IMAGE_CID_PLACEHOLDER_RE.sub(GENERIC_IMAGE_PLACEHOLDER, working_body),
            )
        )
    )
    if not visual_context:
        return normalize_merged_body(body_without_internal_placeholders), ""

    inline_records = list(visual_context.get("inline_visual_context_records") or [])
    supporting_records = list(visual_context.get("supporting_visual_evidence_records") or [])
    visual_status = str(visual_context.get("visual_status") or "").strip()
    if not inline_records and not supporting_records:
        visual_status = str(visual_context.get("visual_status") or "").strip().lower()
        fallback_text = str(visual_context.get("enriched_body") or "").strip()
        if visual_status == "empty":
            fallback_text = ""
        if not fallback_text and visual_context and visual_status != "empty":
            fallback_text = render_email_visual_context_text_fn(visual_context)
        if fallback_text:
            merged = (
                f"{body_without_internal_placeholders}\n\n{fallback_text}".strip()
                if body_without_internal_placeholders
                else fallback_text
            )
            return normalize_merged_body(merged), fallback_text
        return normalize_merged_body(body_without_internal_placeholders), ""

    inserted_keys = set()
    inline_by_index = {
        int(record.get("inline_index") or 0): record
        for record in inline_records
        if int(record.get("inline_index") or 0) > 0 and build_visual_context_insertion_text(record)
    }
    attachment_by_filename = {}
    for record in inline_records + supporting_records:
        filename = str(record.get("filename") or "").strip().lower()
        if filename and build_visual_context_insertion_text(record):
            attachment_by_filename.setdefault(filename, record)

    def replace_inline(match: re.Match) -> str:
        inline_index = int(match.group(1))
        record = inline_by_index.get(inline_index)
        if not record:
            return ""
        inserted_keys.add(str(record.get("image_key") or ""))
        return build_visual_context_insertion_text(record)

    def replace_cid(match: re.Match) -> str:
        cid_token = normalize_cid_token(match.group(1))
        record = attachment_by_filename.get(cid_token)
        if not record:
            return ""
        inserted_keys.add(str(record.get("image_key") or ""))
        return build_visual_context_insertion_text(record)

    merged_body = IMAGE_INLINE_PLACEHOLDER_RE.sub(replace_inline, working_body)
    merged_body = IMAGE_CID_PLACEHOLDER_RE.sub(replace_cid, merged_body)
    merged_body = strip_image_placeholders(merged_body)

    residual_inline = []
    residual_supporting = []
    for record in inline_records:
        if str(record.get("image_key") or "") in inserted_keys:
            continue
        block_text = build_visual_context_insertion_text(record)
        if block_text:
            residual_inline.append(block_text)
    for record in supporting_records:
        if str(record.get("image_key") or "") in inserted_keys:
            continue
        block_text = build_visual_context_insertion_text(record)
        if block_text:
            residual_supporting.append(block_text)

    residual_items = residual_inline + residual_supporting
    residual_text = "\n\n".join(item for item in residual_items if item).strip()
    if residual_text:
        merged_body = f"{merged_body}\n\n{residual_text}".strip() if merged_body else residual_text
    return normalize_merged_body(merged_body), residual_text


def strip_signature_and_disclaimer(
    body: str,
    *,
    min_truncation_content_chars: int,
    signature_line_markers: tuple[str, ...],
    disclaimer_line_markers: tuple[str, ...],
    normalize_marker_text_fn: Callable[[str], str],
) -> str:
    """裁掉邮件尾部的署名、免责声明和设备签名。"""
    if not body:
        return ""

    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cut_index = None
    meaningful_chars = 0
    non_empty_lines = 0

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        normalized = normalize_marker_text_fn(stripped)
        has_enough_content = meaningful_chars >= min_truncation_content_chars or non_empty_lines >= 3

        if has_enough_content:
            signature_hit = any(normalized.startswith(marker) for marker in signature_line_markers)
            if (
                not signature_hit
                and len(stripped) <= 120
                and any(marker in normalized for marker in signature_line_markers if marker != "--")
                and any(token in stripped for token in {",", "|", "@", ":"})
            ):
                signature_hit = True
            if signature_hit and len(stripped) <= 120:
                cut_index = idx
                break
            if any(marker in normalized for marker in disclaimer_line_markers):
                cut_index = idx
                break

        meaningful_chars += len(stripped)
        non_empty_lines += 1

    if cut_index is not None:
        return "\n".join(lines[:cut_index]).strip()
    return text.strip()


def sanitize_email_body(
    body: str,
    *,
    strip_signature_and_disclaimer_fn: Callable[[str], str],
) -> str:
    """清理超大/无效的嵌入内容。"""
    if not body:
        return ""

    sanitized = body.replace("\r\n", "\n").replace("\r", "\n")
    sanitized = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", sanitized)
    sanitized = re.sub(r"(?i)<br\s*/?>", "\n", sanitized)
    sanitized = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", sanitized)
    sanitized = re.sub(r"(?is)<li[^>]*>", "• ", sanitized)
    sanitized = replace_img_tags_with_position_placeholders(sanitized)
    sanitized = re.sub(
        r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+",
        "[图片数据已省略]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"[A-Za-z0-9+/=]{500,}", "[长编码内容已省略]", sanitized)
    sanitized = re.sub(r"(?is)<[^>]+>", " ", sanitized)
    sanitized = unescape(sanitized)
    sanitized = sanitized.replace("\xa0", " ").replace("\u200b", " ").replace("\ufeff", " ")
    sanitized = strip_signature_and_disclaimer_fn(sanitized)
    sanitized = strip_trailing_disclaimer_blocks(sanitized)
    sanitized = strip_leading_noise(sanitized)
    sanitized = re.sub(r"[ \t]+\n", "\n", sanitized)
    sanitized = re.sub(r"\n[ \t]+", "\n", sanitized)
    sanitized = re.sub(r"[ \t]{2,}", " ", sanitized)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    return sanitized.strip()


def prepare_emails_for_analysis(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    sanitize_email_body_fn: Callable[[str], str],
    build_email_visual_context_map_for_analysis_fn: Callable[[List[Dict[str, Any]], Optional[Dict[str, Any]]], Dict[int, Dict[str, Any]]],
    render_email_visual_context_text_fn: Callable[[Dict[str, Any]], str],
) -> List[Dict[str, Any]]:
    if emails and all(is_prepared_email(email) for email in emails):
        return [dict(email) for email in emails]

    visual_context_map = build_email_visual_context_map_for_analysis_fn(emails, api_config=api_config)
    prepared = []
    for idx, email in enumerate(emails, 1):
        item = dict(email)
        body = sanitize_email_body_fn(email.get("body", ""))
        visual_context = visual_context_map.get(idx, {})
        body, visual_context_text = merge_visual_context_into_body(
            body,
            visual_context=visual_context,
            render_email_visual_context_text_fn=render_email_visual_context_text_fn,
        )
        visual_status = str(visual_context.get("visual_status") or "").strip()
        if not visual_status and visual_context_text:
            visual_status = "ready"
        item["_analysis_index"] = idx
        item["_analysis_body"] = body
        item["_analysis_body_len"] = len(body)
        item["_inline_visual_contexts"] = list(visual_context.get("inline_visual_contexts") or [])
        item["_supporting_visual_evidence"] = list(visual_context.get("supporting_visual_evidence") or [])
        item["_visual_context_text"] = visual_context_text
        item["_visual_status"] = visual_status
        item["_visual_context_ready"] = item["_visual_status"] in {"ready", "empty"}
        item["_visual_input_locked"] = bool(item["_visual_status"])
        prepared.append(item)
    return prepared


def prepare_emails_for_analysis_with_visual_context(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    sanitize_email_body_fn: Callable[[str], str],
    build_email_visual_context_map_for_analysis_fn: Callable[[List[Dict[str, Any]], Optional[Dict[str, Any]]], Dict[int, Dict[str, Any]]],
    render_email_visual_context_text_fn: Callable[[Dict[str, Any]], str],
) -> List[Dict[str, Any]]:
    def build_visual_context_map_adapter(
        items: List[Dict[str, Any]],
        api_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[int, Dict[str, Any]]:
        raw_map = build_email_visual_context_map_for_analysis_fn(items, api_config=api_config)
        normalized_map: Dict[int, Dict[str, Any]] = {}
        for email_index, context in (raw_map or {}).items():
            normalized = dict(context)
            if not str(normalized.get("enriched_body") or "").strip() and normalized.get("rendered_text"):
                normalized["enriched_body"] = normalized.get("rendered_text")
            normalized_map[email_index] = normalized
        return normalized_map

    prepared = prepare_emails_for_analysis(
        emails,
        api_config=api_config,
        sanitize_email_body_fn=sanitize_email_body_fn,
        build_email_visual_context_map_for_analysis_fn=build_visual_context_map_adapter,
        render_email_visual_context_text_fn=render_email_visual_context_text_fn,
    )
    normalized_prepared = []
    for item in prepared:
        normalized = dict(item)
        visual_status = str(normalized.get("_visual_status") or "").strip().lower()
        if normalized.get("_visual_context_text") or visual_status in {"ready", "empty"}:
            normalized["_analysis_visual_context_applied"] = True
        normalized_prepared.append(normalized)
    return normalized_prepared

def derive_email_scope(source_emails: Optional[List[Dict[str, Any]]]) -> Tuple[Optional[str], Optional[str]]:
    """从一组邮件里提炼唯一的邮箱作用域。"""
    if not source_emails:
        return None, None

    account_values = {
        str(item.get("account_email") or "").strip().lower()
        for item in source_emails
        if str(item.get("account_email") or "").strip()
    }
    folder_values = {
        (str(item.get("folder") or "INBOX").strip() or "INBOX")
        for item in source_emails
    }
    account_email = next(iter(account_values)) if len(account_values) == 1 else None
    folder = next(iter(folder_values)) if len(folder_values) == 1 else None
    return account_email, folder


def get_analysis_body_len(email: Dict[str, Any]) -> int:
    try:
        body_len = int(email.get("_analysis_body_len") or 0)
    except (TypeError, ValueError):
        body_len = 0
    if body_len > 0:
        return body_len
    return len(str(email.get("_analysis_body") or email.get("body") or ""))


def choose_analysis_batch_count(prepared: List[Dict[str, Any]]) -> int:
    if len(prepared) <= 1:
        return 1

    total_body_chars = sum(max(1, get_analysis_body_len(email)) for email in prepared)
    estimated_batches = (total_body_chars + TARGET_ANALYSIS_BATCH_BODY_CHARS - 1) // TARGET_ANALYSIS_BATCH_BODY_CHARS
    return max(1, min(len(prepared), MAX_ANALYSIS_BATCHES, estimated_batches))


def balance_emails_into_batches(prepared: List[Dict[str, Any]], batch_count: int) -> List[List[Dict[str, Any]]]:
    if batch_count <= 1:
        return [list(prepared)]

    buckets: List[List[Dict[str, Any]]] = [[] for _ in range(batch_count)]
    bucket_loads = [0] * batch_count
    ordered_emails = sorted(
        (dict(email) for email in prepared),
        key=lambda email: (-get_analysis_body_len(email), int(email.get("_analysis_index") or 0)),
    )

    for email in ordered_emails:
        bucket_idx = min(
            range(batch_count),
            key=lambda idx: (bucket_loads[idx], len(buckets[idx]), idx),
        )
        buckets[bucket_idx].append(email)
        bucket_loads[bucket_idx] += max(1, get_analysis_body_len(email))

    normalized = []
    for bucket in buckets:
        if not bucket:
            continue
        normalized.append(
            sorted(bucket, key=lambda email: int(email.get("_analysis_index") or 0))
        )

    normalized.sort(key=lambda bucket: min(int(email.get("_analysis_index") or 0) for email in bucket))
    return normalized

def split_emails_for_analysis(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    prepare_emails_for_analysis_fn: Callable[[List[Dict[str, Any]], Optional[Dict[str, Any]]], List[Dict[str, Any]]],
) -> List[List[Dict[str, Any]]]:
    """多封邮件按 `_analysis_body_len` 做均衡分桶；单封邮件内部不再分段。"""
    if emails and all(is_prepared_email(email) for email in emails):
        prepared = [dict(email) for email in emails]
    else:
        prepared = prepare_emails_for_analysis_fn(emails, api_config=api_config)
    if len(prepared) <= 1:
        return [prepared]
    batch_count = choose_analysis_batch_count(prepared)
    return balance_emails_into_batches(prepared, batch_count)


def split_emails_for_analysis_with_visual_context(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    prepare_emails_for_analysis_with_visual_context_fn: Callable[[List[Dict[str, Any]], Optional[Dict[str, Any]]], List[Dict[str, Any]]],
) -> List[List[Dict[str, Any]]]:
    return split_emails_for_analysis(
        emails,
        api_config=api_config,
        prepare_emails_for_analysis_fn=prepare_emails_for_analysis_with_visual_context_fn,
    )


def truncate_analysis_body_preserving_visual_context(
    body: str,
    *,
    body_budget: int,
    original_len: int,
) -> str:
    if len(body) <= body_budget:
        return body

    truncation_note = (
        f"\n\n【内容已截断：原始长度 {original_len} 字符，为控制模型输入长度仅保留前 {body_budget} 字符】"
    )
    visual_marker = "[邮件级视觉上下文]"
    visual_index = body.find(visual_marker)
    if visual_index < 0:
        return body[:body_budget] + truncation_note

    visual_block = body[visual_index:].strip()
    reserved = len(truncation_note) + len(visual_block) + 2
    prefix_budget = body_budget - reserved
    if prefix_budget > 0:
        prefix = body[:prefix_budget].rstrip()
        return f"{prefix}{truncation_note}\n\n{visual_block}".strip()

    visual_budget = max(body_budget - len(truncation_note) - 2, 0)
    if visual_budget <= 0:
        return truncation_note.strip()
    trimmed_visual = visual_block[:visual_budget].rstrip()
    return (
        "【正文前部已省略：为保留邮件级视觉上下文，优先保留视觉结果】"
        f"{truncation_note}\n\n{trimmed_visual}"
    ).strip()


def build_emails_text(
    emails: List[Dict[str, Any]],
    total_email_count: int,
    total_body_budget: int,
    *,
    sanitize_email_body_fn: Callable[[str], str],
) -> str:
    emails_summary = []

    for fallback_index, email in enumerate(emails, 1):
        subject = email.get("subject", "")
        from_name = email.get("from_name", "")
        from_addr = email.get("from", "")
        date = email.get("date", "")
        body = email.get("_analysis_body", sanitize_email_body_fn(email.get("body", "")))
        email_index = email.get("_analysis_index", fallback_index)

        emails_summary.append(f"""
--- 邮件 {email_index}/{total_email_count} ---
发件人: {from_name} <{from_addr}>
时间: {date}
主题: {subject}
正文:
{body}
""")

    return "\n".join(emails_summary)


def build_emails_text_with_budget(
    emails: List[Dict[str, Any]],
    total_email_count: int,
    total_body_budget: int,
    *,
    sanitize_email_body_fn: Callable[[str], str],
    max_email_body_chars: int,
    truncate_analysis_body_preserving_visual_context_fn: Callable[..., str],
) -> str:
    emails_summary = []
    total_body_chars = 0

    for fallback_index, email in enumerate(emails, 1):
        subject = email.get("subject", "")
        from_name = email.get("from_name", "")
        from_addr = email.get("from", "")
        date = email.get("date", "")
        body = email.get("_analysis_body", sanitize_email_body_fn(email.get("body", "")))
        original_len = len(body)
        email_index = email.get("_analysis_index", fallback_index)

        remaining = max(total_body_budget - total_body_chars, 0)
        if remaining <= 0:
            body = "【内容已省略：本轮邮件总长度超出模型输入预算】"
        else:
            body_budget = min(max_email_body_chars, remaining)
            if len(body) > body_budget:
                body = truncate_analysis_body_preserving_visual_context_fn(
                    body,
                    body_budget=body_budget,
                    original_len=original_len,
                )
        total_body_chars += len(body)

        emails_summary.append(f"""
--- 邮件 {email_index}/{total_email_count} ---
发件人: {from_name} <{from_addr}>
时间: {date}
主题: {subject}
正文:
{body}
""")

    return "\n".join(emails_summary)
