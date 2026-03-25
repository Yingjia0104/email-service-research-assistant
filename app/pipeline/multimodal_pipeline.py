import base64
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import re
import struct
from typing import Any, Callable, Dict, List, Optional, Tuple

MAX_MULTIMODAL_IMAGE_BYTES = 4 * 1024 * 1024
MIN_MULTIMODAL_IMAGE_EDGE = 90
MIN_MULTIMODAL_IMAGE_AREA = 25000
MAX_MULTIMODAL_BANNER_ASPECT_RATIO = 8.0
LOW_VALUE_IMAGE_NAME_PATTERN = re.compile(r"(logo|header|footer|spacer|divider|banner|signature|icon)", re.IGNORECASE)
INLINE_VISUAL_TYPES = {"editorial_framing_visual", "social_signal_visual"}
SUPPORTING_VISUAL_TYPES = {"research_framework_chart", "market_data_chart"}
ROLE_IN_EMAIL_BY_IMAGE_TYPE = {
    "research_framework_chart": "supporting_evidence",
    "market_data_chart": "supporting_evidence",
    "social_signal_visual": "market_signal",
    "editorial_framing_visual": "main_narrative",
    "low_value_visual": "decorative",
}
ROLE_PRIORITY_RANK = {
    "market_signal": 0,
    "main_narrative": 1,
    "supporting_evidence": 2,
    "decorative": 3,
}
IMG_TAG_RE = re.compile(r"(?is)<img\b[^>]*>")
VISUAL_STATUS_READY = "ready"
VISUAL_STATUS_EMPTY = "empty"
LOCKED_VISUAL_STATUSES = {VISUAL_STATUS_READY, VISUAL_STATUS_EMPTY}
CACHEABLE_VISUAL_STATUSES = {VISUAL_STATUS_READY, VISUAL_STATUS_EMPTY}
PRESCREEN_PRIORITY_RANK = {
    "candidate": 0,
    "low_priority": 1,
}
DEEP_ANALYSIS_IMAGE_TYPE_RANK = {
    "social_signal_visual": 0,
    "market_data_chart": 1,
    "research_framework_chart": 2,
    "editorial_framing_visual": 3,
}


def normalize_concurrency(value: Optional[int]) -> int:
    try:
        normalized = int(value or 1)
    except (TypeError, ValueError):
        return 1
    return max(1, normalized)


def map_image_type_to_role_in_email(image_type: str) -> str:
    normalized = str(image_type or "").strip()
    return ROLE_IN_EMAIL_BY_IMAGE_TYPE.get(normalized, "supporting_evidence")


def parse_model_boolean(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    normalized = str(value or "").strip().lower()
    return normalized in {"1", "true", "yes", "y", "是"}


def derive_role_in_email_from_classification(image_type: str, direct_market_signal: bool) -> str:
    normalized = str(image_type or "").strip()
    if normalized in {"research_framework_chart", "market_data_chart"}:
        return "market_signal" if direct_market_signal else "supporting_evidence"
    return map_image_type_to_role_in_email(normalized)


def parse_attachment_list(raw_attachments: Any) -> List[Dict]:
    """兼容 attachments 字段的 JSON 字符串或列表结构。"""
    if not raw_attachments:
        return []
    if isinstance(raw_attachments, list):
        return [item for item in raw_attachments if isinstance(item, dict)]
    if isinstance(raw_attachments, str):
        try:
            parsed = json.loads(raw_attachments)
        except Exception:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def estimate_data_url_image_bytes(data_url: str) -> int:
    """粗略估算 data URL 图片体积，用于过滤过大的正文内嵌图片。"""
    if not data_url or "," not in data_url:
        return 0
    encoded = data_url.split(",", 1)[1]
    compact = re.sub(r"\s+", "", encoded)
    padding = compact.count("=")
    return max(0, (len(compact) * 3) // 4 - padding)


def decode_data_url_image_bytes(data_url: str) -> bytes:
    """解析 data URL 图片字节，失败时返回空字节串。"""
    if not data_url or "," not in data_url:
        return b""
    try:
        encoded = data_url.split(",", 1)[1]
        compact = re.sub(r"\s+", "", encoded)
        return base64.b64decode(compact)
    except Exception:
        return b""


def build_data_url_sha256(data_url: str) -> str:
    raw_bytes = decode_data_url_image_bytes(data_url)
    if not raw_bytes:
        return ""
    return hashlib.sha256(raw_bytes).hexdigest()


def detect_image_dimensions(raw_bytes: bytes) -> Tuple[Optional[int], Optional[int]]:
    """从常见图片头部提取宽高，避免引入额外依赖。"""
    if len(raw_bytes) >= 24 and raw_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        try:
            width, height = struct.unpack(">II", raw_bytes[16:24])
            return int(width), int(height)
        except Exception:
            return None, None

    if len(raw_bytes) >= 10 and raw_bytes[:6] in (b"GIF87a", b"GIF89a"):
        try:
            width, height = struct.unpack("<HH", raw_bytes[6:10])
            return int(width), int(height)
        except Exception:
            return None, None

    if len(raw_bytes) >= 4 and raw_bytes[:2] == b"\xff\xd8":
        offset = 2
        while offset + 9 < len(raw_bytes):
            if raw_bytes[offset] != 0xFF:
                offset += 1
                continue
            marker = raw_bytes[offset + 1]
            offset += 2
            if marker in (0xD8, 0xD9):
                continue
            if offset + 2 > len(raw_bytes):
                break
            segment_length = struct.unpack(">H", raw_bytes[offset:offset + 2])[0]
            if segment_length < 2 or offset + segment_length > len(raw_bytes):
                break
            if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                if offset + 7 <= len(raw_bytes):
                    height, width = struct.unpack(">HH", raw_bytes[offset + 3:offset + 7])
                    return int(width), int(height)
                break
            offset += segment_length

    return None, None


def prescreen_multimodal_image(
    *,
    filename: str,
    data_url: str,
    declared_size: int = 0,
) -> Tuple[str, List[str]]:
    """本地轻量预筛图片，只过滤明显低价值或异常图片。"""
    reasons: List[str] = []
    raw_bytes = decode_data_url_image_bytes(data_url)
    width, height = detect_image_dimensions(raw_bytes)
    effective_size = int(declared_size or len(raw_bytes) or 0)

    if LOW_VALUE_IMAGE_NAME_PATTERN.search(filename or ""):
        reasons.append("low_value_name_pattern")

    if width and height:
        if min(width, height) < MIN_MULTIMODAL_IMAGE_EDGE:
            reasons.append("tiny_edge")
        if width * height < MIN_MULTIMODAL_IMAGE_AREA:
            reasons.append("very_small_area")
        aspect = max(width / height, height / width)
        if aspect >= MAX_MULTIMODAL_BANNER_ASPECT_RATIO:
            reasons.append("extreme_banner_aspect")

    if effective_size and effective_size < 1024:
        reasons.append("tiny_file")

    if "low_value_name_pattern" in reasons:
        return "drop", reasons
    if "tiny_file" in reasons and ("very_small_area" in reasons or "tiny_edge" in reasons):
        return "drop", reasons
    if "extreme_banner_aspect" in reasons and ("very_small_area" in reasons or "tiny_edge" in reasons):
        return "drop", reasons
    if sum(
        1 for reason in reasons if reason in {"tiny_file", "very_small_area", "tiny_edge", "extreme_banner_aspect"}
    ) >= 2:
        return "low_priority", reasons
    return "candidate", reasons


def extract_inline_body_image_data_urls(body: str) -> List[str]:
    """从 HTML 正文里提取 data:image 内嵌图片。"""
    return [item["data_url"] for item in extract_inline_body_images(body)]


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


def is_data_image_src(src: str) -> bool:
    return bool(src) and src.strip().lower().startswith("data:image/")


def extract_inline_body_images(body: str) -> List[Dict[str, Any]]:
    """按正文 <img> 顺序提取 data:image 内嵌图片，并保留稳定的 inline_index。"""
    if not body:
        return []

    images: List[Dict[str, Any]] = []
    seen = set()
    inline_index = 0

    for match in IMG_TAG_RE.finditer(body):
        src = extract_img_src_from_tag(match.group(0))
        if not is_data_image_src(src):
            continue
        compact = re.sub(r"\s+", "", src)
        if compact in seen:
            continue
        inline_index += 1
        seen.add(compact)
        images.append({
            "data_url": compact,
            "inline_index": inline_index,
        })

    if images:
        return images

    # 回退到旧的纯 data:image 扫描，兼容极端异常 HTML。
    fallback_matches = re.findall(
        r"data:image/[^;'\"]+;base64,[A-Za-z0-9+/=\s]+",
        body,
        flags=re.IGNORECASE,
    )
    for match in fallback_matches:
        compact = re.sub(r"\s+", "", match)
        if compact in seen:
            continue
        inline_index += 1
        seen.add(compact)
        images.append({
            "data_url": compact,
            "inline_index": inline_index,
        })
    return images


def extract_image_dimensions_from_data_url(data_url: str) -> Tuple[Optional[int], Optional[int]]:
    return detect_image_dimensions(decode_data_url_image_bytes(data_url))


def build_multimodal_user_blocks(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    max_multimodal_images: Optional[int],
    logger: Any,
) -> List[Dict[str, Any]]:
    if any(
        email.get("_analysis_visual_context_applied")
        or str(email.get("_visual_status") or "").strip().lower() in {"ready", "empty"}
        for email in (emails or [])
    ):
        return []
    if not model_supports_vision_fn(api_config or {}):
        return []

    collected = collect_multimodal_images(
        emails,
        api_config=api_config,
        model_supports_vision_fn=model_supports_vision_fn,
        max_multimodal_images=max_multimodal_images,
        logger=logger,
    )
    selected_images = list(collected.get("selected_images") or [])
    blocks: List[Dict[str, Any]] = []

    for image in selected_images:
        email_index = int(image.get("email_index") or 0)
        subject = str(image.get("subject") or "(无主题)")
        if str(image.get("kind") or "") == "inline":
            label = f"下面是一张直接内嵌在邮件 {email_index}《{subject}》正文中的图片。请结合该邮件的上下文理解图片内容。"
        else:
            filename = str(image.get("filename") or "image")
            label = (
                f"下面是一张来自邮件 {email_index}《{subject}》的图片附件：{filename}。"
                "请结合对应邮件正文一起理解，不要脱离邮件上下文单独脑补。"
            )
        blocks.append({"type": "text", "text": label})
        blocks.append({"type": "image_url", "image_url": {"url": image["data_url"]}})

    total_images = int(collected.get("total_images") or 0)
    if total_images:
        logger.info(
            f"🖼️ 本轮共识别到 {total_images} 张可用图片；按当前上限送入其中 {len(selected_images)} 张进入多模态分析"
        )
    return blocks


def collect_multimodal_images_for_analysis(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    load_visual_fast_llm_config_fn: Callable[[], Dict[str, Any]],
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    max_multimodal_images: Optional[int],
    logger: Any,
) -> Dict[str, Any]:
    selected_api_config = api_config or load_visual_fast_llm_config_fn()
    return collect_multimodal_images(
        emails,
        api_config=selected_api_config,
        model_supports_vision_fn=model_supports_vision_fn,
        max_multimodal_images=max_multimodal_images,
        logger=logger,
    )


def derive_narrative_priority(image_type: str, role_in_email: str) -> str:
    image_type = str(image_type or "").strip()
    role_in_email = str(role_in_email or "").strip()
    if image_type == "low_value_visual" or role_in_email == "decorative":
        return "skip"
    if image_type in INLINE_VISUAL_TYPES or role_in_email in {"main_narrative", "market_signal"}:
        return "core"
    return "supporting"


def normalize_visual_status(status: Any) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "partial":
        return VISUAL_STATUS_READY
    return normalized if normalized in LOCKED_VISUAL_STATUSES else ""


def build_selected_image_lookup(selected_images: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    return {
        str(image.get("image_key") or "").strip(): image
        for image in selected_images
        if str(image.get("image_key") or "").strip()
    }


def build_collection_priority(image: Dict[str, Any]) -> Tuple[int, int, int]:
    prescreen_result = str(image.get("prescreen_result") or "").strip().lower()
    email_index = int(image.get("email_index") or 0)
    discovery_order = int(image.get("_discovery_order") or 0)
    return (
        PRESCREEN_PRIORITY_RANK.get(prescreen_result, 0),
        email_index,
        discovery_order,
    )


def build_deep_analysis_priority(image: Dict[str, Any], fallback_order: int) -> Tuple[int, int, int]:
    image_type = str(image.get("image_type") or "").strip()
    role_in_email = str(image.get("role_in_email") or "").strip()
    email_index = int(image.get("email_index") or 0)
    return (
        DEEP_ANALYSIS_IMAGE_TYPE_RANK.get(image_type, len(DEEP_ANALYSIS_IMAGE_TYPE_RANK)),
        ROLE_PRIORITY_RANK.get(role_in_email, len(ROLE_PRIORITY_RANK)),
        -int(image.get("size") or 0),
        email_index,
        fallback_order,
    )


def merge_deep_analysis_into_image_objects(
    image_objects: List[Dict[str, Any]],
    deep_analysis: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    deep_analysis = deep_analysis or {}
    merged: List[Dict[str, Any]] = []
    for image in image_objects:
        analysis = deep_analysis.get(str(image.get("image_key") or "").strip(), {})
        merged.append(
            {
                **image,
                "core_signal": str(analysis.get("core_signal") or image.get("core_signal") or "").strip(),
                "supporting_details": [
                    str(item).strip()
                    for item in (analysis.get("supporting_details") or image.get("supporting_details") or [])
                    if str(item).strip()
                ],
            }
        )
    return merged


def group_records_by_local_id(
    records_by_image_key: Dict[str, Dict[str, Any]],
    *,
    selected_images_by_key: Dict[str, Dict[str, Any]],
    local_id_by_index: Dict[int, int],
) -> Dict[int, Dict[str, Dict[str, Any]]]:
    grouped: Dict[int, Dict[str, Dict[str, Any]]] = {}
    for image_key, record in records_by_image_key.items():
        image = selected_images_by_key.get(image_key, {})
        local_id = local_id_by_index.get(int(image.get("email_index") or 0))
        if local_id:
            grouped.setdefault(local_id, {})[image_key] = record
    return grouped


def derive_visual_status_for_email(
    image_objects: List[Dict[str, Any]],
    *,
    candidate_images: int,
    selected_images_count: int,
    skipped_due_to_cap: int,
) -> str:
    high_value_images = [
        item for item in image_objects
        if item.get("narrative_priority") != "skip"
    ]
    if not high_value_images:
        return VISUAL_STATUS_EMPTY

    analyzed_total = sum(
        1 for item in high_value_images
        if str(item.get("core_signal") or "").strip()
    )
    if analyzed_total > 0:
        return VISUAL_STATUS_READY
    return VISUAL_STATUS_EMPTY


def build_visual_status_note(status: str) -> str:
    status = normalize_visual_status(status)
    if status == VISUAL_STATUS_EMPTY:
        return "图片前置分析已完成，但没有产出可用视觉证据；后续阶段不要根据图片补写结论。"
    return ""


def run_multimodal_image_analysis_session(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    classification_api_config: Optional[Dict[str, Any]] = None,
    deep_analysis_api_config: Optional[Dict[str, Any]] = None,
    collect_multimodal_images_fn,
    build_image_objects_fn,
    classify_images_fn,
    deep_analyze_images_fn,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    max_multimodal_images: Optional[int],
    max_deep_analysis_images: Optional[int],
    classification_concurrency: int,
    deep_analysis_concurrency: int,
    logger,
) -> Dict[str, Any]:
    classification_api_config = classification_api_config or api_config
    deep_analysis_api_config = deep_analysis_api_config or api_config
    collected = collect_multimodal_images_fn(
        emails,
        api_config=classification_api_config,
        model_supports_vision_fn=model_supports_vision_fn,
        max_multimodal_images=max_multimodal_images,
        logger=logger,
    )
    selected_images = list(collected.get("selected_images") or [])
    email_stats_by_index = {
        int(key): value
        for key, value in (collected.get("email_stats_by_index") or {}).items()
    }

    classifications: Dict[str, Dict[str, str]] = {}
    if selected_images:
        try:
            try:
                classifications = classify_images_fn(
                    selected_images,
                    classification_api_config,
                    classification_concurrency=classification_concurrency,
                ) or {}
            except TypeError as exc:
                if "classification_concurrency" not in str(exc):
                    raise
                classifications = classify_images_fn(selected_images, classification_api_config) or {}
        except Exception as exc:
            logger.warning(f"⚠️ 图片轻分类阶段失败，回退为未分类图片: {exc}")
    preliminary_objects = build_image_objects_fn(selected_images, classifications=classifications)
    deep_analysis: Dict[str, Dict[str, Any]] = {}
    if preliminary_objects:
        try:
            try:
                deep_analysis = deep_analyze_images_fn(
                    preliminary_objects,
                    deep_analysis_api_config,
                    max_deep_analysis_images=max_deep_analysis_images,
                    deep_analysis_concurrency=deep_analysis_concurrency,
                ) or {}
            except TypeError as exc:
                if "deep_analysis_concurrency" not in str(exc):
                    raise
                deep_analysis = deep_analyze_images_fn(
                    preliminary_objects,
                    deep_analysis_api_config,
                    max_deep_analysis_images=max_deep_analysis_images,
                ) or {}
        except Exception as exc:
            logger.warning(f"⚠️ 图片深分析阶段失败，回退为无视觉证据: {exc}")
    image_objects = merge_deep_analysis_into_image_objects(preliminary_objects, deep_analysis=deep_analysis)

    return {
        "collected": collected,
        "selected_images": selected_images,
        "selected_images_by_key": build_selected_image_lookup(selected_images),
        "email_stats_by_index": email_stats_by_index,
        "classifications": classifications,
        "deep_analysis": deep_analysis,
        "image_objects": image_objects,
    }


def collect_multimodal_images(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    max_multimodal_images: Optional[int],
    logger,
) -> Dict[str, Any]:
    """从邮件里抽取通过本地预筛的候选图片。"""
    candidate_images: List[Dict[str, Any]] = []
    total_images = 0
    dropped_images = 0
    deprioritized_images = 0
    email_stats_by_index: Dict[int, Dict[str, int]] = {}
    discovery_order = 0

    for fallback_index, email in enumerate(emails, 1):
        email_index = email.get("_analysis_index", fallback_index)
        subject = email.get("subject", "") or "(无主题)"
        body = email.get("body", "") or ""
        attachments = parse_attachment_list(email.get("attachments"))
        email_stats = email_stats_by_index.setdefault(
            int(email_index),
            {
                "total_images": 0,
                "candidate_images": 0,
                "dropped_images": 0,
                "deprioritized_images": 0,
                "selected_images": 0,
                "skipped_due_to_cap": 0,
            },
        )
        attachment_image_index = 0
        email_seen_urls = set()

        for attachment in attachments:
            if attachment.get("kind") != "image":
                continue
            attachment_image_index += 1

            content_type = attachment.get("content_type", "") or "image/*"
            data_url = attachment.get("data_url")
            size = int(attachment.get("size") or 0)
            if not content_type.startswith("image/") or not data_url:
                continue
            if size and size > MAX_MULTIMODAL_IMAGE_BYTES:
                continue
            compact_url = re.sub(r"\s+", "", data_url)
            if compact_url in email_seen_urls:
                continue
            total_images += 1
            email_stats["total_images"] += 1
            prescreen_result, prescreen_reasons = prescreen_multimodal_image(
                filename=attachment.get("filename", "image"),
                data_url=compact_url,
                declared_size=size,
            )
            if prescreen_result == "drop":
                dropped_images += 1
                email_stats["dropped_images"] += 1
                email_seen_urls.add(compact_url)
                continue
            email_stats["candidate_images"] += 1
            if prescreen_result == "low_priority":
                deprioritized_images += 1
                email_stats["deprioritized_images"] += 1
            filename = attachment.get("filename", "image")
            discovery_order += 1
            candidate_images.append({
                "image_key": f"attachment:{attachment_image_index}",
                "email_index": email_index,
                "subject": subject,
                "filename": filename,
                "data_url": compact_url,
                "kind": "attachment",
                "source_location": "attachment",
                "content_type": content_type,
                "size": size,
                "prescreen_result": prescreen_result,
                "prescreen_reasons": prescreen_reasons,
                "sha256": build_data_url_sha256(compact_url),
                "_discovery_order": discovery_order,
            })
            email_seen_urls.add(compact_url)

        for inline_image in extract_inline_body_images(body):
            inline_index = int(inline_image["inline_index"])
            compact_url = re.sub(r"\s+", "", inline_image["data_url"])
            if compact_url in email_seen_urls:
                continue

            estimated_size = estimate_data_url_image_bytes(compact_url)
            if estimated_size and estimated_size > MAX_MULTIMODAL_IMAGE_BYTES:
                continue
            total_images += 1
            email_stats["total_images"] += 1
            prescreen_result, prescreen_reasons = prescreen_multimodal_image(
                filename=f"inline_image_{inline_index}.png",
                data_url=compact_url,
                declared_size=estimated_size,
            )
            if prescreen_result == "drop":
                dropped_images += 1
                email_stats["dropped_images"] += 1
                email_seen_urls.add(compact_url)
                continue
            email_stats["candidate_images"] += 1
            if prescreen_result == "low_priority":
                deprioritized_images += 1
                email_stats["deprioritized_images"] += 1
            discovery_order += 1
            candidate_images.append({
                "image_key": f"inline:{inline_index}",
                "email_index": email_index,
                "subject": subject,
                "filename": f"inline_image_{inline_index}.png",
                "data_url": compact_url,
                "kind": "inline",
                "inline_index": inline_index,
                "source_location": "inline",
                "content_type": "image/*",
                "size": estimated_size,
                "prescreen_result": prescreen_result,
                "prescreen_reasons": prescreen_reasons,
                "sha256": build_data_url_sha256(compact_url),
                "_discovery_order": discovery_order,
            })
            email_seen_urls.add(compact_url)

    prioritized_candidates = sorted(candidate_images, key=build_collection_priority)
    if max_multimodal_images is None:
        selected_images = prioritized_candidates
    else:
        selected_images = prioritized_candidates[:max_multimodal_images]

    selected_keys = {str(image.get("image_key") or "").strip() for image in selected_images}
    image_count = len(selected_images)
    for image in candidate_images:
        email_index = int(image.get("email_index") or 0)
        stats = email_stats_by_index[email_index]
        image_key = str(image.get("image_key") or "").strip()
        if image_key in selected_keys:
            stats["selected_images"] += 1
        elif max_multimodal_images is not None:
            stats["skipped_due_to_cap"] += 1

    return {
        "selected_images": selected_images,
        "total_images": total_images,
        "dropped_images": dropped_images,
        "deprioritized_images": deprioritized_images,
        "sent_images": image_count,
        "email_stats_by_index": email_stats_by_index,
    }


def build_image_objects(
    selected_images: List[Dict[str, Any]],
    classifications: Optional[Dict[str, Dict[str, str]]] = None,
    deep_analysis: Optional[Dict[str, Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """把预筛图片、轻分类和深分析结果合并成统一的中间对象。"""
    classifications = classifications or {}
    deep_analysis = deep_analysis or {}
    image_objects: List[Dict[str, Any]] = []

    for image in selected_images:
        classification = classifications.get(image["image_key"], {})
        analysis = deep_analysis.get(image["image_key"], {})
        image_type = str(classification.get("image_type") or "").strip()
        role_in_email = str(classification.get("role_in_email") or "").strip() or map_image_type_to_role_in_email(image_type)
        image_objects.append({
            "image_key": image["image_key"],
            "email_index": image["email_index"],
            "kind": image.get("kind", "attachment"),
            "inline_index": image.get("inline_index"),
            "filename": image.get("filename", ""),
            "subject": image.get("subject", ""),
            "size": int(image.get("size") or 0),
            "data_url": image.get("data_url", ""),
            "image_type": image_type,
            "role_in_email": role_in_email,
            "narrative_priority": derive_narrative_priority(image_type, role_in_email),
            "core_signal": str(analysis.get("core_signal") or "").strip(),
            "supporting_details": [
                str(item).strip() for item in analysis.get("supporting_details", []) if str(item).strip()
            ],
        })
    return image_objects


def build_stored_image_objects(email_index: int, image_rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    image_objects: List[Dict[str, Any]] = []
    for row in image_rows or []:
        image_type = str(row.get("image_type") or "").strip()
        role_in_email = str(row.get("role_in_email") or "").strip() or map_image_type_to_role_in_email(image_type)
        core_signal = str(row.get("core_signal") or "").strip()
        supporting_details = [
            str(item).strip() for item in (row.get("supporting_details") or []) if str(item).strip()
        ]
        image_objects.append({
            "image_key": str(row.get("image_key") or "").strip(),
            "email_index": email_index,
            "kind": row.get("kind", "attachment"),
            "inline_index": row.get("inline_index"),
            "filename": row.get("filename", ""),
            "subject": row.get("subject", ""),
            "size": int(row.get("size") or 0),
            "data_url": "",
            "image_type": image_type,
            "role_in_email": role_in_email,
            "narrative_priority": derive_narrative_priority(image_type, role_in_email),
            "core_signal": core_signal,
            "supporting_details": supporting_details,
        })
    return image_objects


def build_email_visual_context_map(
    image_objects: List[Dict[str, Any]],
    *,
    max_inline_visual_contexts: Optional[int] = None,
    max_supporting_visual_evidence: Optional[int] = None,
) -> Dict[int, Dict[str, List[str]]]:
    """把图片中间对象聚合成邮件级视觉上下文。"""
    context_map: Dict[int, Dict[str, List[str]]] = {}

    for image in image_objects:
        if image.get("narrative_priority") == "skip":
            continue
        email_index = int(image.get("email_index") or 0)
        if email_index <= 0:
            continue
        bucket = context_map.setdefault(
            email_index,
            {
                "inline_visual_contexts": [],
                "supporting_visual_evidence": [],
                "inline_visual_context_records": [],
                "supporting_visual_evidence_records": [],
            },
        )

        core_signal = str(image.get("core_signal") or "").strip()
        if not core_signal:
            continue

        image_type = str(image.get("image_type") or "").strip()
        role_in_email = str(image.get("role_in_email") or "").strip()
        supporting_details = [str(item).strip() for item in image.get("supporting_details", []) if str(item).strip()]

        if image_type in INLINE_VISUAL_TYPES or role_in_email in {"main_narrative", "market_signal"}:
            lines = [
                f"type: {image_type or 'unknown'}",
                f"role: {role_in_email or 'unknown'}",
                f"core_signal: {core_signal}",
            ]
            if supporting_details:
                lines.append("supporting_details: " + " | ".join(supporting_details[:2]))
            block_text = "[Visual Context]\n" + "\n".join(lines)
            if max_inline_visual_contexts is None or len(bucket["inline_visual_contexts"]) < max_inline_visual_contexts:
                bucket["inline_visual_contexts"].append(block_text)
                bucket["inline_visual_context_records"].append({
                    "image_key": str(image.get("image_key") or "").strip(),
                    "kind": str(image.get("kind") or "").strip(),
                    "inline_index": image.get("inline_index"),
                    "filename": str(image.get("filename") or "").strip(),
                    "image_type": image_type,
                    "role_in_email": role_in_email,
                    "core_signal": core_signal,
                    "supporting_details": supporting_details[:2],
                    "block_text": block_text,
                })
        else:
            lines = [
                f"type: {image_type or 'unknown'}",
                f"role: {role_in_email or 'unknown'}",
                f"core_view: {core_signal}",
            ]
            if supporting_details:
                lines.append("supporting_details: " + " | ".join(supporting_details[:2]))
            block_text = "[Visual Evidence]\n" + "\n".join(lines)
            if (
                max_supporting_visual_evidence is None
                or len(bucket["supporting_visual_evidence"]) < max_supporting_visual_evidence
            ):
                bucket["supporting_visual_evidence"].append(block_text)
                bucket["supporting_visual_evidence_records"].append({
                    "image_key": str(image.get("image_key") or "").strip(),
                    "kind": str(image.get("kind") or "").strip(),
                    "inline_index": image.get("inline_index"),
                    "filename": str(image.get("filename") or "").strip(),
                    "image_type": image_type,
                    "role_in_email": role_in_email,
                    "core_signal": core_signal,
                    "supporting_details": supporting_details[:2],
                    "block_text": block_text,
                })

    return context_map


def render_email_visual_context_text(context: Dict[str, List[str]]) -> str:
    """把邮件级视觉上下文渲染成可拼接进摘要输入的文本块。"""
    inline_items = list(context.get("inline_visual_contexts") or [])
    evidence_items = list(context.get("supporting_visual_evidence") or [])
    visual_status = normalize_visual_status(context.get("visual_status"))
    status_note = build_visual_status_note(visual_status)
    if not inline_items and not evidence_items and not status_note:
        return ""

    parts = ["[邮件级视觉上下文]"]
    if visual_status:
        parts.append(f"visual_status: {visual_status}")
    if status_note:
        parts.append(f"note: {status_note}")
    if inline_items:
        parts.append("## Inline Visual Contexts")
        parts.extend(inline_items)
    if evidence_items:
        parts.append("## Supporting Visual Evidence")
        parts.extend(evidence_items)
    return "\n".join(parts).strip()


def classify_multimodal_images_lightweight(
    images: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    classification_concurrency: int = 1,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    call_llm_api_with_retries_fn,
    load_json_dict_with_fallbacks_fn,
    logger,
) -> Dict[str, Dict[str, str]]:
    """对已通过本地预筛的图片做轻量分类，先忠实读图再给出 image_type。"""
    api_config = api_config or {}
    if not images or not model_supports_vision_fn(api_config):
        return {}
    if not api_config.get("api_key"):
        return {}

    system_prompt = """你负责给图片做轻分类。只根据图片本身判断，只输出 JSON。

可选 `image_type` 只有：
- editorial_framing_visual
- social_signal_visual
- research_framework_chart
- market_data_chart
- low_value_visual

同时返回 `direct_market_signal`：
- true: 图片本身直接传达明确市场信号
- false: 其他情况；如果不确定，一律 false

输出要求：
- 只输出合法 JSON
- 顶层结构固定为 {\"images\": [...]}
- 每张图返回 `image_key`、`image_type`、`direct_market_signal`
"""

    valid_image_types = {
        "editorial_framing_visual",
        "social_signal_visual",
        "research_framework_chart",
        "market_data_chart",
        "low_value_visual",
    }
    batch_size = 6
    max_workers = min(normalize_concurrency(classification_concurrency), max(1, (len(images) + batch_size - 1) // batch_size))
    batches = [
        (batch_start // batch_size + 1, images[batch_start:batch_start + batch_size])
        for batch_start in range(0, len(images), batch_size)
    ]

    def classify_batch(batch_number: int, batch_images: List[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
        user_prompt = """请只根据图片本身判定每张图片的 image_type 和 direct_market_signal，并输出 JSON。"""
        user_content_blocks = []
        for image in batch_images:
            user_content_blocks.extend(
                [
                    {
                        "type": "text",
                        "text": (
                            f"image_key: {image['image_key']}\n"
                            "请先忠实读图，再返回 image_type 和 direct_market_signal。"
                        ),
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": image["data_url"]},
                    },
                ]
            )

        raw = call_llm_api_with_retries_fn(
            api_config,
            system_prompt,
            user_prompt,
            label=f"图片轻分类-批次{batch_number}",
            max_retries=0,
            user_content_blocks=user_content_blocks,
            response_format={"type": "json_object"},
        )
        if not raw:
            return {}

        try:
            payload = load_json_dict_with_fallbacks_fn(raw)
        except Exception as exc:
            batch_keys = ", ".join(str(image.get("image_key") or "") for image in batch_images)
            logger.warning(f"⚠️ 图片轻分类 JSON 解析失败（{batch_keys}），回退为无标签提示: {exc}")
            return {}

        items = payload.get("images")
        if not isinstance(items, list):
            return {}

        batch_result: Dict[str, Dict[str, str]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            image_key = str(item.get("image_key") or "").strip()
            image_type = str(item.get("image_type") or "").strip()
            if not image_key or image_type not in valid_image_types:
                continue
            direct_market_signal = parse_model_boolean(item.get("direct_market_signal"))
            batch_result[image_key] = {
                "image_type": image_type,
                "role_in_email": derive_role_in_email_from_classification(image_type, direct_market_signal),
                "direct_market_signal": "true" if direct_market_signal else "false",
            }
        return batch_result

    result: Dict[str, Dict[str, str]] = {}
    if max_workers <= 1 or len(batches) <= 1:
        for batch_number, batch_images in batches:
            result.update(classify_batch(batch_number, batch_images))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for batch_result in executor.map(lambda item: classify_batch(*item), batches):
                result.update(batch_result)

    if result:
        logger.info(f"🧭 图片轻分类已返回 {len(result)} 个标签结果")
    return result


def classify_multimodal_images_lightweight_for_pipeline(
    images: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    load_visual_fast_llm_config_fn: Callable[[], Dict[str, Any]],
    classification_concurrency: Optional[int],
    default_classification_concurrency: int,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    call_llm_api_with_retries_fn,
    load_json_dict_with_fallbacks_fn,
    logger,
) -> Dict[str, Dict[str, str]]:
    primary_cfg = api_config or load_visual_fast_llm_config_fn()
    return classify_multimodal_images_lightweight(
        images,
        api_config=primary_cfg,
        classification_concurrency=max(
            1,
            int(classification_concurrency or default_classification_concurrency or 1),
        ),
        model_supports_vision_fn=model_supports_vision_fn,
        call_llm_api_with_retries_fn=call_llm_api_with_retries_fn,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks_fn,
        logger=logger,
    )


def deep_analyze_multimodal_images(
    image_objects: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    max_deep_analysis_images: Optional[int] = None,
    deep_analysis_concurrency: int = 1,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    call_llm_api_with_retries_fn,
    load_json_dict_with_fallbacks_fn,
    normalize_string_list_fn,
    logger,
) -> Dict[str, Dict[str, Any]]:
    """对高价值图片做独立深分析，产出可回填到邮件正文的图片证据。"""
    api_config = api_config or {}
    if not image_objects or not model_supports_vision_fn(api_config):
        return {}
    if not api_config.get("api_key"):
        return {}

    high_value_images = [
        image for image in image_objects
        if image.get("narrative_priority") != "skip"
        and image.get("image_type") not in {"", "low_value_visual"}
        and image.get("role_in_email") != "decorative"
    ]
    if not high_value_images:
        return {}

    prioritized_images = [
        image
        for _, image in sorted(
            enumerate(high_value_images),
            key=lambda pair: build_deep_analysis_priority(pair[1], pair[0]),
        )
    ]
    if max_deep_analysis_images is not None:
        high_value_images = prioritized_images[:max_deep_analysis_images]
        skipped_count = max(0, len(prioritized_images) - len(high_value_images))
        if skipped_count:
            logger.info(
                f"⏱️ 图片深分析预算生效：本轮仅分析 {len(high_value_images)} 张高价值图片，跳过 {skipped_count} 张"
            )
    else:
        high_value_images = prioritized_images

    def build_system_prompt_for_image_type(image_type: str) -> str:
        return "你负责把图片转成结构化文本信息，告诉我这张图说了什么。"

    def build_user_prompt_for_image_type(image_type: str) -> str:
        shared_output_contract = """只根据图片本身输出 JSON，顶层固定为 {\"images\": [...]}。
字段固定为：image_key / core_signal / supporting_details。
不能新增字段；无内容时返回空字符串或 []。"""

        prompts = {
            "research_framework_chart": """逐张分析这些 research framework chart。
- 先看图片本身，只写图里能直接看到或稳妥推出的内容
- 信息不够就留空，不要补写
- 重点看框架、排序维度、bucket、关键对象的位置关系
- 如果图片是二维定位矩阵、象限图、仓位情绪图或 positioning map，按这个顺序读图：
  1. 先识别横轴和纵轴分别代表什么
  2. 再识别四个象限各自代表什么立场、情绪或仓位
  3. 再提取每个关键象限里的代表性对象或 ticker
  4. 如果图里有 consensus long、consensus short、battleground、hedge fund hotel 一类显式标签，要直接写出来
  5. 如果图里有箭头，优先解释它表示的方向变化、情绪迁移或边际改善/恶化
- 不要机械罗列全部 ticker，只提最能代表各区域的对象
- 不要把机构框架图写成独立核实的客观事实
- `core_signal` 直接写这张图最重要的结论；遇到象限图时，优先用 1-2 句写清楚市场最强共识在哪里、最大分歧在哪里、哪些票在边际改善或恶化，不要先解释坐标轴和读图方法
- `supporting_details` 写补充信息；遇到象限图时，再补充轴含义、象限标签、代表性 ticker、拥挤区、战场区和箭头变化""",
            "market_data_chart": """逐张分析这些 market data chart。
- 先看图片本身，只写图里能直接看到或稳妥推出的内容
- 信息不够就留空，不要补写
- 先在内部识别：
  1. 图在比较什么对象
  2. 主要方向是走强、走弱、分化还是收敛
  3. 哪个对象相对更强、哪个对象相对更弱
  4. 有没有明显拐点、放量、回撤、修复或趋势变化
- 不要把相关性写成因果；幅度不清楚时只写方向
- `core_signal` 直接写这张图最重要的市场结论，优先回答谁更强、谁更弱、分化有没有扩大或收敛，不要先解释图表类型
- `supporting_details` 再补比较对象、时间段、方向性细节、相对表现和可见数字""",
            "social_signal_visual": """逐张分析这些 social signal visual。
- 先看图片本身，只写图里能直接看到或由可见线索支持的最小解释
- 信息不够就留空，不要补写
- 先在内部识别：
  1. 这是哪个平台、哪类账号、什么传播场景
  2. 核心传播内容是什么
  3. 传播 framing 偏什么方向
  4. 有没有浏览量、点赞、转发、时间戳、截图 UI 这类可见线索
- 社交截图反映的是传播和 framing，不等于独立核实后的事实
- 不要把“有人在传播”写成“事实已经成立”
- `core_signal` 直接写这张图最重要的传播结论，优先回答谁在传、在传什么、市场会从这张图感受到什么信号，不要先解释平台界面
- `supporting_details` 再补平台、账号、互动量、时间戳、截图里额外出现的直接证据""",
            "editorial_framing_visual": """逐张分析这些 editorial framing visual。
- 先看图片本身，只写图里能直接看到或由可见线索支持的最小解释
- 信息不够就留空，不要补写
- 先在内部识别：
  1. 标题、封面、版式、人物或视觉主体是什么
  2. 主题被包装成什么叙事
  3. 图面强调的是冲突、机会、风险还是情绪
  4. 哪些元素在推动这种 framing
- editorial framing 不等于客观事实，不要从弱视觉信号推出过强结论
- `core_signal` 直接写这张图最重要的 framing 结论，优先回答它把主题包装成了什么故事或市场情绪，不要先复述版面结构
- `supporting_details` 再补标题措辞、封面元素、排版重点、视觉对比和附带文字信息""",
        }
        specific_prompt = prompts.get(image_type, "")
        return f"{shared_output_contract}\n\n{specific_prompt}".strip()

    def analyze_single_image(image: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
        image_type = str(image.get("image_type") or "").strip()
        user_content_blocks = [
            {
                "type": "text",
                "text": (
                    f"image_key: {image['image_key']}\n"
                    f"image_type: {image.get('image_type', '')}\n"
                    f"role_in_email: {image.get('role_in_email', '')}\n"
                    "请只根据图片本身返回这张图的结构化视觉证据，不要联读邮件正文。"
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": image["data_url"]},
            },
        ]

        raw = call_llm_api_with_retries_fn(
            api_config,
            build_system_prompt_for_image_type(image_type),
            build_user_prompt_for_image_type(image_type),
            label=f"图片深分析-{image_type}-{image['image_key']}",
            max_retries=0,
            user_content_blocks=user_content_blocks,
            response_format={"type": "json_object"},
        )
        if not raw:
            return {}

        try:
            payload = load_json_dict_with_fallbacks_fn(raw)
        except Exception as exc:
            logger.warning(f"⚠️ 图片深分析 JSON 解析失败（{image_type}/{image['image_key']}），回退为空视觉证据: {exc}")
            return {}

        items = payload.get("images")
        if not isinstance(items, list):
            if any(key in payload for key in {"core_signal", "supporting_details"}):
                items = [{**payload, "image_key": image["image_key"]}]
            else:
                return {}

        image_result: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                continue
            image_key = str(item.get("image_key") or "").strip()
            if not image_key:
                continue
            image_result[image_key] = {
                "core_signal": str(item.get("core_signal") or "").strip(),
                "supporting_details": normalize_string_list_fn(item.get("supporting_details"), limit=3),
            }
        return image_result

    result: Dict[str, Dict[str, Any]] = {}
    max_workers = min(normalize_concurrency(deep_analysis_concurrency), len(high_value_images))
    if max_workers <= 1 or len(high_value_images) <= 1:
        for image in high_value_images:
            result.update(analyze_single_image(image))
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for image_result in executor.map(analyze_single_image, high_value_images):
                result.update(image_result)

    if result:
        logger.info(f"🔎 图片深分析已返回 {len(result)} 条视觉证据")
    return result


def deep_analyze_multimodal_images_for_pipeline(
    image_objects: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    load_visual_llm_config_fn: Callable[[], Dict[str, Any]],
    max_deep_analysis_images: Optional[int],
    default_max_deep_analysis_images: Optional[int],
    deep_analysis_concurrency: Optional[int],
    default_deep_analysis_concurrency: int,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    call_llm_api_with_retries_fn,
    load_json_dict_with_fallbacks_fn,
    normalize_string_list_fn,
    logger,
) -> Dict[str, Dict[str, Any]]:
    primary_cfg = api_config or load_visual_llm_config_fn()
    return deep_analyze_multimodal_images(
        image_objects,
        api_config=primary_cfg,
        max_deep_analysis_images=(
            max_deep_analysis_images
            if max_deep_analysis_images is not None
            else default_max_deep_analysis_images
        ),
        deep_analysis_concurrency=max(
            1,
            int(deep_analysis_concurrency or default_deep_analysis_concurrency or 1),
        ),
        model_supports_vision_fn=model_supports_vision_fn,
        call_llm_api_with_retries_fn=call_llm_api_with_retries_fn,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks_fn,
        normalize_string_list_fn=normalize_string_list_fn,
        logger=logger,
    )


def build_email_visual_context_map_for_analysis(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    classification_api_config: Optional[Dict[str, Any]] = None,
    deep_analysis_api_config: Optional[Dict[str, Any]] = None,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    collect_multimodal_images_fn,
    build_image_objects_fn,
    build_email_visual_context_map_fn,
    render_email_visual_context_text_fn,
    classify_images_fn,
    deep_analyze_images_fn,
    get_email_visual_context_fn,
    get_email_visual_contexts_fn=None,
    get_email_image_analysis_records_fn,
    get_email_image_analysis_records_map_fn=None,
    upsert_email_images_fn,
    upsert_email_images_batch_fn=None,
    update_image_classifications_fn,
    update_image_classifications_batch_fn=None,
    upsert_image_analysis_results_fn,
    upsert_image_analysis_results_batch_fn=None,
    save_email_visual_context_fn,
    save_email_visual_contexts_batch_fn=None,
    max_multimodal_images: Optional[int],
    max_deep_analysis_images: Optional[int],
    classification_concurrency: int,
    deep_analysis_concurrency: int,
    max_inline_visual_contexts: Optional[int],
    max_supporting_visual_evidence: Optional[int],
    logger,
) -> Dict[int, Dict[str, Any]]:
    """为每封邮件构建可回填的视觉上下文。"""
    api_config = api_config or {}
    if not emails:
        return {}

    context_map: Dict[int, Dict[str, Any]] = {}
    emails_to_process: List[Dict[str, Any]] = []
    local_ids = [int(email.get("local_id")) for email in emails if email.get("local_id") is not None]
    cached_contexts_by_local_id = (
        get_email_visual_contexts_fn(local_ids)
        if get_email_visual_contexts_fn and local_ids
        else {local_id: get_email_visual_context_fn(local_id) for local_id in local_ids}
    )
    cached_records_by_local_id = (
        get_email_image_analysis_records_map_fn(local_ids)
        if get_email_image_analysis_records_map_fn and local_ids
        else {
            local_id: (get_email_image_analysis_records_fn(local_id) if get_email_image_analysis_records_fn else [])
            for local_id in local_ids
        }
    )

    for idx, original_email in enumerate(emails, 1):
        email = dict(original_email)
        email.setdefault("_analysis_index", idx)
        local_id = email.get("local_id")
        if local_id:
            cached = cached_contexts_by_local_id.get(int(local_id), {})
            if cached and normalize_visual_status(cached.get("visual_status")) in CACHEABLE_VISUAL_STATUSES:
                cached_records_context: Dict[str, Any] = {}
                stored_records = cached_records_by_local_id.get(int(local_id), [])
                if stored_records:
                    cached_records_context = build_email_visual_context_map_fn(
                        build_stored_image_objects(idx, stored_records),
                        max_inline_visual_contexts=max_inline_visual_contexts,
                        max_supporting_visual_evidence=max_supporting_visual_evidence,
                    ).get(idx, {})
                context_map[idx] = {
                    "inline_visual_contexts": list(
                        cached_records_context.get("inline_visual_contexts")
                        or cached.get("inline_visual_contexts")
                        or []
                    ),
                    "supporting_visual_evidence": list(
                        cached_records_context.get("supporting_visual_evidence")
                        or cached.get("supporting_visual_evidence")
                        or []
                    ),
                    "inline_visual_context_records": list(cached_records_context.get("inline_visual_context_records") or []),
                    "supporting_visual_evidence_records": list(
                        cached_records_context.get("supporting_visual_evidence_records") or []
                    ),
                    "enriched_body": cached.get("enriched_body") or "",
                    "visual_status": normalize_visual_status(cached.get("visual_status")) or VISUAL_STATUS_READY,
                    "updated_at": cached.get("updated_at") or "",
                }
                continue
        emails_to_process.append(email)

    if not emails_to_process:
        return context_map

    session = run_multimodal_image_analysis_session(
        emails_to_process,
        api_config=api_config,
        classification_api_config=classification_api_config,
        deep_analysis_api_config=deep_analysis_api_config,
        collect_multimodal_images_fn=collect_multimodal_images_fn,
        build_image_objects_fn=build_image_objects_fn,
        classify_images_fn=classify_images_fn,
        deep_analyze_images_fn=deep_analyze_images_fn,
        model_supports_vision_fn=model_supports_vision_fn,
        max_multimodal_images=max_multimodal_images,
        max_deep_analysis_images=max_deep_analysis_images,
        classification_concurrency=classification_concurrency,
        deep_analysis_concurrency=deep_analysis_concurrency,
        logger=logger,
    )
    selected_images = session["selected_images"]
    selected_images_by_key = session["selected_images_by_key"]
    email_image_stats = session["email_stats_by_index"]
    classifications = session["classifications"]
    deep_analysis = session["deep_analysis"]
    image_objects = session["image_objects"]

    local_id_by_index = {
        int(email.get("_analysis_index") or 0): int(email.get("local_id"))
        for email in emails_to_process
        if email.get("local_id") is not None
    }
    images_by_local_id: Dict[int, List[Dict[str, Any]]] = {}
    for image in selected_images:
        local_id = local_id_by_index.get(int(image.get("email_index") or 0))
        if local_id:
            images_by_local_id.setdefault(local_id, []).append(image)
    if upsert_email_images_batch_fn:
        upsert_email_images_batch_fn(images_by_local_id)
    else:
        for local_id, image_records in images_by_local_id.items():
            upsert_email_images_fn(local_id, image_records)

    if not selected_images:
        contexts_to_save: Dict[int, Dict[str, Any]] = {}
        for email in emails_to_process:
            local_id = email.get("local_id")
            email_index = int(email.get("_analysis_index") or 0)
            visual_status = VISUAL_STATUS_EMPTY
            context_entry = {
                "inline_visual_contexts": [],
                "supporting_visual_evidence": [],
                "inline_visual_context_records": [],
                "supporting_visual_evidence_records": [],
                "enriched_body": render_email_visual_context_text_fn({"visual_status": visual_status}),
                "visual_status": visual_status,
            }
            if local_id:
                contexts_to_save[int(local_id)] = {
                    "visual_status": visual_status,
                    "inline_visual_contexts": [],
                    "supporting_visual_evidence": [],
                    "enriched_body": context_entry["enriched_body"],
                }
            context_map[email_index] = context_entry
        if save_email_visual_contexts_batch_fn:
            save_email_visual_contexts_batch_fn(contexts_to_save)
        else:
            for local_id, context in contexts_to_save.items():
                save_email_visual_context_fn(
                    local_id,
                    visual_status=context["visual_status"],
                    inline_visual_contexts=context["inline_visual_contexts"],
                    supporting_visual_evidence=context["supporting_visual_evidence"],
                    enriched_body=context["enriched_body"],
                )
        return context_map

    classifications_by_local_id = group_records_by_local_id(
        classifications,
        selected_images_by_key=selected_images_by_key,
        local_id_by_index=local_id_by_index,
    )
    if update_image_classifications_batch_fn:
        update_image_classifications_batch_fn(classifications_by_local_id)
    else:
        for local_id, scoped in classifications_by_local_id.items():
            update_image_classifications_fn(local_id, scoped)

    analysis_by_local_id = group_records_by_local_id(
        deep_analysis,
        selected_images_by_key=selected_images_by_key,
        local_id_by_index=local_id_by_index,
    )
    if upsert_image_analysis_results_batch_fn:
        upsert_image_analysis_results_batch_fn(analysis_by_local_id)
    else:
        for local_id, scoped in analysis_by_local_id.items():
            upsert_image_analysis_results_fn(local_id, scoped)

    computed_map = build_email_visual_context_map_fn(
        image_objects,
        max_inline_visual_contexts=max_inline_visual_contexts,
        max_supporting_visual_evidence=max_supporting_visual_evidence,
    )
    image_objects_by_index: Dict[int, List[Dict[str, Any]]] = {}
    for image_object in image_objects:
        image_objects_by_index.setdefault(int(image_object.get("email_index") or 0), []).append(image_object)

    contexts_to_save: Dict[int, Dict[str, Any]] = {}
    for email in emails_to_process:
        email_index = int(email.get("_analysis_index") or 0)
        local_id = email.get("local_id")
        scoped_context = computed_map.get(
            email_index,
            {
                "inline_visual_contexts": [],
                "supporting_visual_evidence": [],
                "inline_visual_context_records": [],
                "supporting_visual_evidence_records": [],
            },
        )
        rendered = render_email_visual_context_text_fn(scoped_context)
        stats = email_image_stats.get(email_index, {})
        selected_images_count = int(stats.get("selected_images") or 0)
        skipped_due_to_cap = int(stats.get("skipped_due_to_cap") or 0)
        candidate_images = int(stats.get("candidate_images") or 0)
        visual_status = derive_visual_status_for_email(
            image_objects_by_index.get(email_index, []),
            candidate_images=candidate_images,
            selected_images_count=selected_images_count,
            skipped_due_to_cap=skipped_due_to_cap,
        )
        context_entry = {
            "inline_visual_contexts": list(scoped_context.get("inline_visual_contexts") or []),
            "supporting_visual_evidence": list(scoped_context.get("supporting_visual_evidence") or []),
            "inline_visual_context_records": list(scoped_context.get("inline_visual_context_records") or []),
            "supporting_visual_evidence_records": list(scoped_context.get("supporting_visual_evidence_records") or []),
            "enriched_body": rendered or render_email_visual_context_text_fn({"visual_status": visual_status}),
            "visual_status": visual_status,
        }
        context_map[email_index] = context_entry
        if local_id:
            contexts_to_save[int(local_id)] = {
                "visual_status": visual_status,
                "inline_visual_contexts": context_entry["inline_visual_contexts"],
                "supporting_visual_evidence": context_entry["supporting_visual_evidence"],
                "enriched_body": rendered,
            }

    if save_email_visual_contexts_batch_fn:
        save_email_visual_contexts_batch_fn(contexts_to_save)
    else:
        for local_id, context in contexts_to_save.items():
            save_email_visual_context_fn(
                local_id,
                visual_status=context["visual_status"],
                inline_visual_contexts=context["inline_visual_contexts"],
                supporting_visual_evidence=context["supporting_visual_evidence"],
                enriched_body=context["enriched_body"],
            )

    if context_map:
        logger.info(f"🧩 已为 {len(context_map)} 封邮件构建视觉上下文")
    return context_map


def build_email_visual_context_map_for_analysis_with_settings(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]] = None,
    load_config_fn: Callable[[], Dict[str, Any]],
    build_image_pipeline_settings_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    load_visual_fast_llm_config_fn: Callable[[], Dict[str, Any]],
    load_visual_llm_config_fn: Callable[[], Dict[str, Any]],
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    classify_images_fn,
    deep_analyze_images_fn,
    get_email_visual_context_fn,
    get_email_visual_contexts_fn=None,
    get_email_image_analysis_records_fn,
    get_email_image_analysis_records_map_fn=None,
    upsert_email_images_fn,
    upsert_email_images_batch_fn=None,
    update_image_classifications_fn,
    update_image_classifications_batch_fn=None,
    upsert_image_analysis_results_fn,
    upsert_image_analysis_results_batch_fn=None,
    save_email_visual_context_fn,
    save_email_visual_contexts_batch_fn=None,
    logger,
) -> Dict[int, Dict[str, Any]]:
    image_settings = build_image_pipeline_settings_fn(load_config_fn())
    return build_email_visual_context_map_for_analysis(
        emails,
        api_config=api_config,
        classification_api_config=load_visual_fast_llm_config_fn(),
        deep_analysis_api_config=load_visual_llm_config_fn(),
        model_supports_vision_fn=model_supports_vision_fn,
        collect_multimodal_images_fn=collect_multimodal_images,
        build_image_objects_fn=build_image_objects,
        build_email_visual_context_map_fn=build_email_visual_context_map,
        render_email_visual_context_text_fn=render_email_visual_context_text,
        classify_images_fn=classify_images_fn,
        deep_analyze_images_fn=deep_analyze_images_fn,
        get_email_visual_context_fn=get_email_visual_context_fn,
        get_email_visual_contexts_fn=get_email_visual_contexts_fn,
        get_email_image_analysis_records_fn=get_email_image_analysis_records_fn,
        get_email_image_analysis_records_map_fn=get_email_image_analysis_records_map_fn,
        upsert_email_images_fn=upsert_email_images_fn,
        upsert_email_images_batch_fn=upsert_email_images_batch_fn,
        update_image_classifications_fn=update_image_classifications_fn,
        update_image_classifications_batch_fn=update_image_classifications_batch_fn,
        upsert_image_analysis_results_fn=upsert_image_analysis_results_fn,
        upsert_image_analysis_results_batch_fn=upsert_image_analysis_results_batch_fn,
        save_email_visual_context_fn=save_email_visual_context_fn,
        save_email_visual_contexts_batch_fn=save_email_visual_contexts_batch_fn,
        max_multimodal_images=image_settings["max_visual_pipeline_images"],
        max_deep_analysis_images=image_settings["max_deep_analysis_images"],
        classification_concurrency=image_settings["classification_concurrency"],
        deep_analysis_concurrency=image_settings["deep_analysis_concurrency"],
        max_inline_visual_contexts=image_settings["max_inline_visual_contexts"],
        max_supporting_visual_evidence=image_settings["max_supporting_visual_evidence"],
        logger=logger,
    )
