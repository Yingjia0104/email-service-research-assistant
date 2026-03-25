#!/usr/bin/env python3
"""
QClaw 邮件自动处理 - 文件交互版

流程：
1. 通过 API / IMAP 收取邮件 → 落 SQLite
2. 从 SQLite 读取 pending 邮件并调用大模型分析
3. 生成 AI_Morning_Brief_YYYYMMDD.html
4. 发送报告并更新 SQLite 状态

用法:
    python qclaw_mail_file.py           # 正常模式
    python qclaw_mail_file.py --force   # 强制立即执行
    python qclaw_mail_file.py --check   # 检查状态
    python qclaw_mail_file.py --analyze # 仅分析 SQLite 中已存在的 pending 邮件
"""

import os
import sys
import atexit
import base64
import yaml
import json
import time
import glob
import pytz
import re
import struct
import logging
import traceback
from html import escape, unescape
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, List, Dict, Optional, Tuple
from io import BytesIO
from urllib.parse import urlparse

# ============ 配置 ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")
REPORT_PREFIX = "report_"
LOG_FILE = os.path.join(BASE_DIR, "qclaw.log")
ANALYSIS_LOCK_FILE = os.path.join(BASE_DIR, ".analysis.lock")

from app import config as app_config
from app.llm import client as app_llm_client
from app.llm import json_utils as app_llm_json_utils
from app.llm import prompts as app_llm_prompts
from app.mail import fetcher as app_mail_fetcher
from app.mail import service as app_mail_service
from app.pipeline import email_preprocess as app_email_preprocess
from app.pipeline import multimodal_pipeline as app_multimodal_pipeline
from app.pipeline import report_payload as app_report_payload
from app.pipeline import report_pipeline as app_report_pipeline
from app.runtime import qclaw_runner as app_runtime_qclaw_runner
from app.runtime import analysis_lock as app_analysis_lock
from app.runtime import qclaw_runtime as app_runtime_qclaw_runtime
from app.runtime import qclaw_support as app_runtime_qclaw_support
from app.runtime import report_delivery as app_runtime_report_delivery
from app.runtime import service_analysis as app_runtime_service_analysis
from app.runtime import state as app_runtime_state
from app.runtime import status_report as app_runtime_status_report
from app.render import report_renderer as app_report_renderer
from app.storage import email_db as app_storage_email_db
email_db = app_storage_email_db

# 时区
BJT = pytz.timezone('Asia/Shanghai')

LLM_CONFIG = app_config.DEFAULT_LLM_CONFIG.copy()
LLM_BACKUP_CONFIG = app_config.DEFAULT_LLM_BACKUP_CONFIG.copy()
LLM_BACKUP2_CONFIG = app_config.DEFAULT_LLM_BACKUP2_CONFIG.copy()
LLM_BACKUP3_CONFIG = app_config.DEFAULT_LLM_BACKUP3_CONFIG.copy()

VISUAL_LLM_CONFIG = app_config.DEFAULT_VISUAL_LLM_CONFIG.copy()
VISUAL_LLM_BACKUP_CONFIG = app_config.DEFAULT_VISUAL_LLM_BACKUP_CONFIG.copy()
VISUAL_LLM_BACKUP2_CONFIG = app_config.DEFAULT_VISUAL_LLM_BACKUP2_CONFIG.copy()
VISUAL_FAST_LLM_CONFIG = app_config.DEFAULT_VISUAL_FAST_LLM_CONFIG.copy()
VISUAL_FAST_LLM_BACKUP_CONFIG = app_config.DEFAULT_VISUAL_FAST_LLM_BACKUP_CONFIG.copy()

MAX_EMAIL_BODY_CHARS = 12000
MAX_PROMPT_BODY_CHARS = 40000
MAX_COMPLETION_TOKENS = 12000
BATCH_SPLIT_TRIGGER_CHARS = 26000
MIN_TRUNCATION_CONTENT_CHARS = 40
MAX_MULTIMODAL_IMAGE_BYTES = 4 * 1024 * 1024
MAX_MULTIMODAL_IMAGES = 8
MAX_VISUAL_PIPELINE_IMAGES = 50
MAX_DEEP_ANALYSIS_IMAGES = 15
LIGHTWEIGHT_CLASSIFICATION_CONCURRENCY = 2
DEEP_ANALYSIS_CONCURRENCY = 2
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif')
MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS = 12000

EMOJI_PATTERN = re.compile(
    "["
    "\U0001F000-\U0001F02F"
    "\U0001F0A0-\U0001F0FF"
    "\U0001F100-\U0001F64F"
    "\U0001F680-\U0001F6FF"
    "\U0001F700-\U0001F77F"
    "\U0001F780-\U0001F7FF"
    "\U0001F800-\U0001F8FF"
    "\U0001F900-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002700-\U000027BF"
    "\U00002600-\U000026FF"
    "\uFE0F"
    "\u20E3"
    "]+",
    flags=re.UNICODE,
)

SIGNATURE_LINE_MARKERS = (
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
    "managing director",
    "executive director",
    "vice president",
    "tech sector specialists:",
    "us tech trading:",
    "--",
)

DISCLAIMER_LINE_MARKERS = (
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
    "disclaimers:",
    "for institutional & professional clients only",
    "not intended for retail customer use",
    "this communication is intended for institutional & professional clients only",
    "you are receiving this email because you are a client of j.p. morgan",
    "if you would like to stop receiving",
    "this material has been prepared by j.p. morgan sales and trading personnel",
    "this material is provided for informational purposes only",
    "this material is a “solicitation” of derivatives business only",
)

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

STANDALONE_SUBHEADINGS = app_report_renderer.STANDALONE_SUBHEADINGS
SECTION_SUBHEADINGS = app_report_renderer.SECTION_SUBHEADINGS
TIME_HORIZON_SUBHEADINGS = app_report_renderer.TIME_HORIZON_SUBHEADINGS
SEMANTIC_CALLOUT_RULES = app_report_renderer.SEMANTIC_CALLOUT_RULES
FIXED_DETAIL_LABELS = app_report_renderer.FIXED_DETAIL_LABELS
SOURCE_LABEL_PATTERNS = app_report_renderer.SOURCE_LABEL_PATTERNS
REPORT_OPTIMIZATION_CATEGORIES = app_report_renderer.REPORT_OPTIMIZATION_CATEGORIES
FIXED_REPORT_TEMPLATE = app_report_renderer.FIXED_REPORT_TEMPLATE

logger = app_runtime_qclaw_support.setup_file_logger(LOG_FILE, stream=sys.stdout)
atexit.register(logging.shutdown)
session = None
proxy_session = None
_RUNTIME_SETTINGS = None


def _ensure_llm_sessions():
    global session
    global proxy_session

    if session is None or proxy_session is None:
        session, proxy_session = app_runtime_qclaw_support.build_llm_sessions()
    return session, proxy_session


def llm_should_bypass_proxy(api_config: Dict[str, Any]) -> bool:
    return app_llm_client.llm_should_bypass_proxy(api_config)


def get_llm_http_session(api_config: Dict[str, Any]):
    """返回当前 LLM 请求应使用的 HTTP session。"""
    direct_session, proxied_session = _ensure_llm_sessions()
    return app_llm_client.get_llm_http_session(
        api_config,
        direct_session=direct_session,
        proxy_session=proxied_session,
    )


def load_config():
    """加载配置文件"""
    global _RUNTIME_SETTINGS
    _RUNTIME_SETTINGS = app_runtime_qclaw_runtime.load_runtime_settings(CONFIG_FILE, logger)
    app_runtime_qclaw_runtime.apply_legacy_runtime_globals(globals(), _RUNTIME_SETTINGS)
    return dict(_RUNTIME_SETTINGS["config"])


def _get_runtime_settings(refresh: bool = False) -> Dict[str, Any]:
    global _RUNTIME_SETTINGS
    if refresh or _RUNTIME_SETTINGS is None:
        load_config()
    return _RUNTIME_SETTINGS or {}


def _resolve_runtime_settings_for_compat() -> Dict[str, Any]:
    config = load_config()
    return {
        "config": config,
        "image_settings": app_config.build_image_pipeline_settings(config),
        "llm_router_settings": app_config.build_llm_router_settings(config),
    }


def load_llm_config():
    """加载主/备 LLM API 配置。"""
    app_runtime_qclaw_runtime.apply_legacy_runtime_globals(
        globals(),
        _resolve_runtime_settings_for_compat(),
    )
    return LLM_CONFIG


def load_visual_llm_config() -> Dict[str, Any]:
    """加载图片深分析强模型配置。图片配置解析逻辑收口到 app.config。"""
    app_runtime_qclaw_runtime.apply_legacy_runtime_globals(globals(), _resolve_runtime_settings_for_compat())
    return VISUAL_LLM_CONFIG


def load_visual_fast_llm_config() -> Dict[str, Any]:
    """加载图片轻分类快模型配置。图片配置解析逻辑收口到 app.config。"""
    app_runtime_qclaw_runtime.apply_legacy_runtime_globals(globals(), _resolve_runtime_settings_for_compat())
    return VISUAL_FAST_LLM_CONFIG


def try_acquire_analysis_lock():
    """获取分析流程互斥锁，避免并发重复发送。"""
    return app_analysis_lock.try_acquire_analysis_lock(ANALYSIS_LOCK_FILE)


def release_analysis_lock(lock_handle) -> None:
    app_analysis_lock.release_analysis_lock(lock_handle)


def model_supports_vision(api_config: Dict[str, Any]) -> bool:
    return app_llm_client.model_supports_vision(api_config)


def is_openai_chat_api(api_config: Dict[str, Any]) -> bool:
    return app_llm_client.is_openai_chat_api(api_config)


def is_openai_gpt5_family(api_config: Dict[str, Any]) -> bool:
    return app_llm_client.is_openai_gpt5_family(api_config)


def supports_openai_json_schema_response_format(api_config: Dict[str, Any]) -> bool:
    """仅在已知支持的 OpenAI 官方模型上启用原生 JSON Schema 输出。"""
    return app_llm_client.supports_native_response_format(api_config)


def build_json_schema_response_format(name: str, schema: Dict[str, Any], strict: bool = True) -> Dict[str, Any]:
    return app_llm_prompts.build_json_schema_response_format(name, schema, strict=strict)


def build_batch_summary_response_format() -> Dict[str, Any]:
    return app_llm_prompts.build_batch_summary_response_format()


def build_report_response_format() -> Dict[str, Any]:
    return app_llm_prompts.build_report_response_format()


def parse_attachment_list(raw_attachments: Any) -> List[Dict]:
    return app_multimodal_pipeline.parse_attachment_list(raw_attachments)


def _extract_attachment_bytes(att):
    return app_mail_fetcher.extract_attachment_bytes(att)


def _clean_extracted_attachment_text(text, filename=""):
    return app_mail_fetcher.clean_extracted_attachment_text(
        text,
        filename=filename,
        max_extracted_attachment_text_chars=MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS,
        attachment_signature_markers=ATTACHMENT_SIGNATURE_MARKERS,
        attachment_disclaimer_markers=ATTACHMENT_DISCLAIMER_MARKERS,
    )


def _build_attachment_records(msg):
    return app_mail_fetcher.build_attachment_records(
        msg,
        image_extensions=IMAGE_EXTENSIONS,
        max_multimodal_image_bytes=MAX_MULTIMODAL_IMAGE_BYTES,
        extract_attachment_bytes_fn=_extract_attachment_bytes,
        clean_extracted_attachment_text_fn=_clean_extracted_attachment_text,
        logger=logger,
    )


def get_message_local_datetime(msg_datetime, local_tz):
    return app_mail_fetcher.get_message_local_datetime(msg_datetime, local_tz)


def should_accept_sender(from_addr: str, allowed_senders: list) -> bool:
    return app_mail_fetcher.should_accept_sender(
        from_addr,
        allowed_senders,
        extract_sender_email_fn=app_mail_fetcher.extract_sender_email,
        match_allowed_sender_fn=app_mail_fetcher.match_allowed_sender,
    )


def parse_received_after_local(filters: dict, local_tz):
    return app_mail_fetcher.parse_received_after_local(filters, local_tz, logger)


def estimate_data_url_image_bytes(data_url: str) -> int:
    return app_multimodal_pipeline.estimate_data_url_image_bytes(data_url)


def extract_inline_body_image_data_urls(body: str) -> List[str]:
    return app_multimodal_pipeline.extract_inline_body_image_data_urls(body)


def build_multimodal_user_blocks(emails: List[Dict], api_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    return app_multimodal_pipeline.build_multimodal_user_blocks(
        emails,
        api_config=api_config,
        model_supports_vision_fn=model_supports_vision,
        max_multimodal_images=MAX_MULTIMODAL_IMAGES,
        logger=logger,
    )


def _decode_image_bytes_from_data_url(data_url: str) -> bytes:
    return app_multimodal_pipeline.decode_data_url_image_bytes(data_url)


def _extract_image_dimensions_from_data_url(data_url: str) -> Tuple[Optional[int], Optional[int]]:
    return app_multimodal_pipeline.extract_image_dimensions_from_data_url(data_url)


def _parse_json_object_relaxed(raw_text: str) -> Dict[str, Any]:
    text = str(raw_text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except Exception:
        pass

    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, count=1, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text, count=1)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return {}
    block = text[start:end + 1]
    try:
        return json.loads(block)
    except Exception:
        pass
    try:
        payload = yaml.safe_load(block)
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def collect_multimodal_images(
    emails: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
    max_multimodal_images: Optional[int] = None,
) -> Dict[str, Any]:
    return app_multimodal_pipeline.collect_multimodal_images_for_analysis(
        emails,
        api_config=api_config,
        load_visual_fast_llm_config_fn=load_visual_fast_llm_config,
        model_supports_vision_fn=model_supports_vision,
        max_multimodal_images=max_multimodal_images,
        logger=logger,
    )


def build_visual_llm_chain(primary_cfg: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    return app_llm_client.build_named_config_chain(
        primary_cfg,
        primary_key="visual_primary",
        primary_label="视觉主模型",
        backup_configs=[VISUAL_LLM_BACKUP_CONFIG, VISUAL_LLM_BACKUP2_CONFIG],
        backup_key_prefix="visual_backup",
        backup_label_prefix="视觉备用模型",
    )


def build_visual_fast_llm_chain(primary_cfg: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    return app_llm_client.build_named_config_chain(
        primary_cfg,
        primary_key="visual_fast_primary",
        primary_label="视觉快模型",
        backup_configs=[VISUAL_FAST_LLM_BACKUP_CONFIG],
        backup_key_prefix="visual_fast_backup",
        backup_label_prefix="视觉快模型备用",
    )


def _call_llm_with_config_chain(
    chain: List[Tuple[str, str, Dict[str, Any]]],
    system_prompt: str,
    user_prompt: str,
    label: str,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    return app_llm_client.call_llm_with_config_chain(
        chain,
        system_prompt,
        user_prompt,
        label=label,
        user_content_blocks=user_content_blocks,
        model_supports_vision_fn=model_supports_vision,
        call_llm_api_with_retries_fn=call_llm_api_with_retries,
        logger=logger,
    )


def _call_visual_fast_llm_for_pipeline(
    api_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    *,
    label: str,
    max_retries: int = 0,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    del max_retries, response_format
    return _call_llm_with_config_chain(
        build_visual_fast_llm_chain(api_config),
        system_prompt,
        user_prompt,
        label=label,
        user_content_blocks=user_content_blocks,
    )


def _call_visual_deep_llm_for_pipeline(
    api_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    *,
    label: str,
    max_retries: int = 0,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    del max_retries, response_format
    return _call_llm_with_config_chain(
        build_visual_llm_chain(api_config),
        system_prompt,
        user_prompt,
        label=label,
        user_content_blocks=user_content_blocks,
    )


def _classify_multimodal_images_lightweight(
    images: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
    classification_concurrency: Optional[int] = None,
) -> Dict[str, Dict[str, str]]:
    return app_multimodal_pipeline.classify_multimodal_images_lightweight_for_pipeline(
        images,
        api_config=api_config,
        load_visual_fast_llm_config_fn=load_visual_fast_llm_config,
        classification_concurrency=classification_concurrency,
        default_classification_concurrency=LIGHTWEIGHT_CLASSIFICATION_CONCURRENCY,
        model_supports_vision_fn=model_supports_vision,
        call_llm_api_with_retries_fn=_call_visual_fast_llm_for_pipeline,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        logger=logger,
    )


def _deep_analyze_multimodal_images(
    image_objects: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
    max_deep_analysis_images: Optional[int] = None,
    deep_analysis_concurrency: Optional[int] = None,
) -> Dict[str, Dict[str, Any]]:
    return app_multimodal_pipeline.deep_analyze_multimodal_images_for_pipeline(
        image_objects,
        api_config=api_config,
        load_visual_llm_config_fn=load_visual_llm_config,
        max_deep_analysis_images=max_deep_analysis_images,
        default_max_deep_analysis_images=MAX_DEEP_ANALYSIS_IMAGES,
        deep_analysis_concurrency=deep_analysis_concurrency,
        default_deep_analysis_concurrency=DEEP_ANALYSIS_CONCURRENCY,
        model_supports_vision_fn=model_supports_vision,
        call_llm_api_with_retries_fn=_call_visual_deep_llm_for_pipeline,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        normalize_string_list_fn=normalize_string_list,
        logger=logger,
    )


def render_email_visual_context_text(context: Dict[str, Any]) -> str:
    return app_multimodal_pipeline.render_email_visual_context_text(context)


def build_email_visual_context_map_for_analysis(
    emails: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
) -> Dict[int, Dict[str, Any]]:
    return app_runtime_qclaw_runtime.build_email_visual_context_map_for_analysis(
        emails,
        api_config=api_config,
        load_config_fn=load_config,
        build_image_pipeline_settings_fn=app_config.build_image_pipeline_settings,
        load_visual_fast_llm_config_fn=load_visual_fast_llm_config,
        load_visual_llm_config_fn=load_visual_llm_config,
        model_supports_vision_fn=model_supports_vision,
        classify_images_fn=_classify_multimodal_images_lightweight,
        deep_analyze_images_fn=_deep_analyze_multimodal_images,
        get_email_visual_context_fn=app_storage_email_db.get_email_visual_context,
        get_email_visual_contexts_fn=app_storage_email_db.get_email_visual_contexts,
        get_email_image_analysis_records_fn=app_storage_email_db.get_email_image_analysis_records,
        get_email_image_analysis_records_map_fn=app_storage_email_db.get_email_image_analysis_records_map,
        upsert_email_images_fn=app_storage_email_db.upsert_email_images,
        upsert_email_images_batch_fn=app_storage_email_db.upsert_email_images_batch,
        update_image_classifications_fn=app_storage_email_db.update_image_classifications,
        update_image_classifications_batch_fn=app_storage_email_db.update_image_classifications_batch,
        upsert_image_analysis_results_fn=app_storage_email_db.upsert_image_analysis_results,
        upsert_image_analysis_results_batch_fn=app_storage_email_db.upsert_image_analysis_results_batch,
        save_email_visual_context_fn=app_storage_email_db.save_email_visual_context,
        save_email_visual_contexts_batch_fn=app_storage_email_db.save_email_visual_contexts_batch,
        logger=logger,
    )


def build_llm_chain(primary_cfg: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    return app_llm_client.build_llm_chain(
        primary_cfg,
        backup_configs=[LLM_BACKUP_CONFIG, LLM_BACKUP2_CONFIG, LLM_BACKUP3_CONFIG],
    )


def get_ordered_llm_chain(
    primary_cfg: Dict[str, Any],
    routing_state: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    chain = build_llm_chain(primary_cfg)
    if not routing_state:
        return chain

    disabled = routing_state.setdefault("disabled_model_keys", set())
    preferred = routing_state.get("preferred_model_key")
    filtered = [item for item in chain if item[0] not in disabled]
    if not preferred:
        return filtered

    preferred_items = [item for item in filtered if item[0] == preferred]
    remaining = [item for item in filtered if item[0] != preferred]
    return preferred_items + remaining


def choose_visual_analysis_api_config(
    routing_state: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    return app_llm_client.choose_visual_analysis_api_config(
        routing_state,
        load_llm_config_fn=load_llm_config,
        get_ordered_llm_chain_fn=lambda primary_cfg, state: get_ordered_llm_chain(
            primary_cfg,
            routing_state=state,
        ),
        model_supports_vision_fn=model_supports_vision,
    )


def normalize_marker_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def strip_signature_and_disclaimer(body: str) -> str:
    return app_email_preprocess.strip_signature_and_disclaimer(
        body,
        min_truncation_content_chars=MIN_TRUNCATION_CONTENT_CHARS,
        signature_line_markers=SIGNATURE_LINE_MARKERS,
        disclaimer_line_markers=DISCLAIMER_LINE_MARKERS,
        normalize_marker_text_fn=normalize_marker_text,
    )


def sanitize_email_body(body: str) -> str:
    return app_email_preprocess.sanitize_email_body(
        body,
        strip_signature_and_disclaimer_fn=strip_signature_and_disclaimer,
    )


def prepare_emails_for_analysis(
    emails: List[Dict],
    api_config: Optional[Dict[str, Any]] = None,
) -> List[Dict]:
    return app_runtime_qclaw_runtime.prepare_emails_for_analysis(
        emails,
        api_config=api_config,
        sanitize_email_body_fn=sanitize_email_body,
        build_email_visual_context_map_for_analysis_fn=build_email_visual_context_map_for_analysis,
        render_email_visual_context_text_fn=render_email_visual_context_text,
    )


def split_emails_for_analysis(
    emails: List[Dict],
    api_config: Optional[Dict[str, Any]] = None,
) -> List[List[Dict]]:
    return app_runtime_qclaw_runtime.split_emails_for_analysis(
        emails,
        api_config=api_config,
        prepare_emails_for_analysis_with_visual_context_fn=prepare_emails_for_analysis,
    )


def truncate_analysis_body_preserving_visual_context(
    body: str,
    *,
    body_budget: int,
    original_len: int,
) -> str:
    return app_email_preprocess.truncate_analysis_body_preserving_visual_context(
        body,
        body_budget=body_budget,
        original_len=original_len,
    )


def build_emails_text(emails: List[Dict], total_email_count: int, total_body_budget: int) -> str:
    return app_email_preprocess.build_emails_text_with_budget(
        emails,
        total_email_count,
        total_body_budget,
        sanitize_email_body_fn=sanitize_email_body,
        max_email_body_chars=MAX_EMAIL_BODY_CHARS,
        truncate_analysis_body_preserving_visual_context_fn=truncate_analysis_body_preserving_visual_context,
    )


def generate_with_llm(
    system_prompt: str,
    user_prompt: str,
    emails: Optional[List[Dict]] = None,
    routing_state: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    """统一封装主/备模型的短重试与切换逻辑。"""
    llm_cfg = load_llm_config()
    if routing_state is not None:
        routing_state.setdefault("disabled_model_keys", set())

    ordered_chain = get_ordered_llm_chain(llm_cfg, routing_state)
    for model_key, label, api_cfg in ordered_chain:
        api_key = api_cfg.get("api_key", "")
        user_content_blocks = (
            build_multimodal_user_blocks(emails or [], api_cfg)
            if emails
            else None
        )
        visual_statuses = {
            str(email.get("_visual_status") or "").strip().lower()
            for email in (emails or [])
            if str(email.get("_visual_status") or "").strip()
        }
        if emails:
            if user_content_blocks:
                logger.info(f"🖼️ {label} 将接收 {len(user_content_blocks) // 2} 张图片进行多模态分析")
            elif visual_statuses & {"ready", "empty"}:
                logger.info(f"🧩 {label} 检测到邮件级视觉上下文，主摘要阶段跳过原图直传")
            else:
                logger.info(f"🧩 {label} 未发现可用视觉上下文，主摘要阶段按纯文本邮件处理")

        if not api_key:
            key_hint = api_cfg.get("api_key_env") or f"{model_key}.api_key"
            logger.warning(f"⚠️ {label} 未配置可用 API Key，跳过（期望来源: {key_hint}）")
            if routing_state is not None:
                routing_state["disabled_model_keys"].add(model_key)
            continue

        if label != "主API":
            logger.warning(f"⚠️ 主 API 不可用，切换{label}: {api_cfg['base_url']} (模型: {api_cfg['model']})")

        result = call_llm_api_with_retries(
            api_cfg,
            system_prompt,
            user_prompt,
            label=label,
            max_retries=1,
            delay=5.0 if label == "主API" else 3.0,
            backoff=2.0,
            user_content_blocks=user_content_blocks,
            response_format=response_format,
        )
        if result:
            if routing_state is not None:
                routing_state["preferred_model_key"] = model_key
            return result

        if user_content_blocks:
            logger.warning(f"⚠️ {label} 多模态请求失败，降级为纯文本重试")
            result = call_llm_api_with_retries(
                api_cfg,
                system_prompt,
                user_prompt,
                label=f"{label}-文本降级",
                max_retries=1,
                delay=4.0 if label == "主API" else 3.0,
                backoff=2.0,
                user_content_blocks=None,
                response_format=response_format,
            )
            if result:
                logger.info(f"✅ {label} 文本降级成功")
                if routing_state is not None:
                    routing_state["preferred_model_key"] = model_key
                return result

        if routing_state is not None:
            routing_state["disabled_model_keys"].add(model_key)

    logger.error("❌ 主 API 与所有备用 API 均失败")
    raise Exception("LLM API error: 主 API 和所有备用 API 均失败")


def extract_json_block(text: str) -> str:
    """从模型输出中提取 JSON 主体，兼容 ```json 代码块。"""
    return app_llm_json_utils.extract_json_block(text)


def save_malformed_json_snapshot(raw_text: str, prefix: str = "malformed_report_payload") -> Optional[str]:
    """保存模型返回的损坏 JSON 片段，方便排查。"""
    try:
        timestamp = datetime.now(BJT).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(BASE_DIR, f"{prefix}_{timestamp}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw_text or "")
        logger.warning(f"⚠️ 已保存损坏 JSON 快照: {path}")
        return path
    except Exception as exc:
        logger.warning(f"⚠️ 保存损坏 JSON 快照失败: {exc}")
        return None


def load_json_dict_with_fallbacks(raw_text: str) -> Dict[str, Any]:
    """优先严格 JSON，失败时允许用 YAML 宽松解析。"""
    return app_llm_json_utils.load_json_dict_with_fallbacks(raw_text)


def repair_report_payload_json(raw_text: str) -> Dict[str, Any]:
    """当模型返回的 JSON 不合法时，尝试做一次短请求修复。"""
    return app_report_payload.repair_report_payload_json(
        raw_text,
        save_malformed_json_snapshot_fn=save_malformed_json_snapshot,
        generate_with_llm_fn=generate_with_llm,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        logger=logger,
    )


def parse_batch_summary_json(text: str) -> Dict:
    """解析子批次结构化摘要，失败时直接抛错让上层重试/切换。"""
    return app_report_pipeline.parse_batch_summary_json(
        text,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
    )


def normalize_string_list(items: Any, limit: int = 6) -> List[str]:
    return app_report_payload.normalize_string_list(items, limit=limit)


def escape_with_highlights(text: str, highlights: Optional[List[str]] = None) -> str:
    return app_report_renderer.escape_with_highlights(text, highlights)


def derive_highlight_phrases(text: str, limit: int = 4) -> List[str]:
    return app_report_payload.derive_highlight_phrases(text, limit=limit)


def derive_stance_highlight_phrases(text: str, limit: int = 2) -> List[str]:
    return app_report_payload.derive_stance_highlight_phrases(text, limit=limit)


def merge_highlight_phrases(*sources: Any, limit: int = 6) -> List[str]:
    return app_report_payload.merge_highlight_phrases(*sources, limit=limit)


def coerce_int(value: Any, default: int = 0) -> int:
    return app_report_payload.coerce_int(value, default=default)


def coerce_float(value: Any, default: float = 0.0) -> float:
    return app_report_payload.coerce_float(value, default=default)


def build_priority_sort_key(item: Dict[str, Any]) -> tuple:
    return app_report_payload.build_priority_sort_key(item)


def sort_by_priority(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return app_report_payload.sort_by_priority(items)


def derive_executive_key_signals(
    normalized_coverage: List[Dict[str, Any]],
    normalized_local_news: List[Dict[str, Any]],
    normalized_cross_market_signals: List[Dict[str, Any]],
    model_key_signals: Any,
    limit: int = 5,
) -> List[str]:
    return app_report_payload.derive_executive_key_signals(
        normalized_coverage,
        normalized_local_news,
        normalized_cross_market_signals,
        model_key_signals,
        limit=limit,
    )


def normalize_core_event_link_refs(value: Any, limit: int = 5) -> List[str]:
    return app_report_payload.normalize_core_event_link_refs(value, limit=limit)


def build_core_event_lookup(core_events: List[Dict[str, Any]]) -> Dict[str, str]:
    return app_report_payload.build_core_event_lookup(core_events)


def resolve_linked_core_event_ids(
    explicit_refs: Any,
    source_topics: Any,
    core_event_lookup: Dict[str, str],
    limit: int = 5,
) -> List[str]:
    return app_report_payload.resolve_linked_core_event_ids(
        explicit_refs,
        source_topics,
        core_event_lookup,
        limit=limit,
    )


def normalize_actionable_dedupe_key(text: str) -> str:
    return app_report_payload.normalize_actionable_dedupe_key(text)


def dedupe_actionable_items(
    items: List[Dict[str, Any]],
    existing_keys: Optional[set] = None,
) -> List[Dict[str, Any]]:
    return app_report_payload.dedupe_actionable_items(items, existing_keys=existing_keys)


def normalize_actionable_item(item: Any, fallback_text_key: str = "idea") -> Optional[Dict[str, Any]]:
    return app_report_payload.normalize_actionable_item(item, fallback_text_key=fallback_text_key)


def normalize_report_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """把最终晨报 JSON 规整到固定模板槽位。"""
    return app_report_payload.normalize_report_payload(payload)


def parse_report_payload_json(text: str) -> Dict[str, Any]:
    """解析最终晨报 JSON，并做字段归一化。"""
    return app_report_payload.parse_report_payload_json(
        text,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        repair_report_payload_json_fn=repair_report_payload_json,
        normalize_report_payload_fn=normalize_report_payload,
        logger=logger,
    )


def build_prompt_category_block(title: str, items: List[str]) -> str:
    return app_llm_prompts.build_prompt_category_block(title, items)


def get_report_prompt_governance() -> str:
    return app_llm_prompts.get_report_prompt_governance()


def get_hf_role_guidance() -> str:
    return app_llm_prompts.get_hf_role_guidance()


def get_shared_fact_attribution_rules() -> str:
    return app_llm_prompts.get_shared_fact_attribution_rules()


def get_report_output_contract() -> str:
    return app_llm_prompts.get_report_output_contract()


def get_report_slot_boundary_rules() -> str:
    return app_llm_prompts.get_report_slot_boundary_rules()


def build_report_system_prompt(*extra_sections: str) -> str:
    return app_llm_prompts.build_report_system_prompt(*extra_sections)


def get_batch_prompt_shared_brief() -> str:
    return app_llm_prompts.get_batch_prompt_shared_brief()


def get_merge_prompt_shared_brief() -> str:
    return app_llm_prompts.get_merge_prompt_shared_brief()


def build_batch_system_prompt(*extra_sections: str) -> str:
    return app_llm_prompts.build_batch_system_prompt(*extra_sections)


def build_merge_system_prompt(*extra_sections: str) -> str:
    return app_llm_prompts.build_merge_system_prompt(*extra_sections)


def get_batch_summary_stage_rules() -> str:
    return app_llm_prompts.get_batch_summary_stage_rules()


def get_merge_stage_rules(total_email_count: int) -> str:
    return app_llm_prompts.get_merge_stage_rules(total_email_count)


def get_fixed_report_schema_prompt() -> str:
    return app_llm_prompts.get_fixed_report_schema_prompt()


def render_list_html(items: List[Any], highlights: Optional[List[str]] = None) -> str:
    return app_report_renderer.render_list_html(
        items,
        highlights=highlights,
        escape_with_highlights_fn=escape_with_highlights,
    )


def render_detail_label(label: str) -> str:
    return app_report_renderer.render_detail_label(label)


def render_detail_copy(text: str, highlights: Optional[List[str]] = None) -> str:
    return app_report_renderer.render_detail_copy(
        text,
        highlights=highlights,
        escape_with_highlights_fn=escape_with_highlights,
    )


def render_detail_list_html(items: List[Any], highlights: Optional[List[str]] = None) -> str:
    return app_report_renderer.render_detail_list_html(
        items,
        highlights=highlights,
        render_list_html_fn=lambda data, current_highlights=None: render_list_html(
            data,
            current_highlights,
        ),
    )


def render_market_views_table(rows: List[Dict[str, str]]) -> str:
    return app_report_renderer.render_market_views_table(
        rows,
        escape_with_highlights_fn=escape_with_highlights,
    )


def render_peripheral_table(rows: List[Dict[str, str]]) -> str:
    return app_report_renderer.render_peripheral_table(rows)


def render_catalysts_table(rows: List[Dict[str, str]]) -> str:
    return app_report_renderer.render_catalysts_table(rows)


def build_priority_debug_summary(payload: Dict[str, Any]) -> str:
    return app_report_renderer.build_priority_debug_summary(payload)


def render_report_html(report_payload: Dict[str, Any], source_emails: Optional[List[Dict]] = None) -> str:
    """用固定模板渲染最终 HTML，避免模型直接输出排版。"""
    return app_report_renderer.render_report_html(
        report_payload,
        source_emails=source_emails,
        normalize_report_payload_fn=normalize_report_payload,
        logger=logger,
        fixed_report_template=FIXED_REPORT_TEMPLATE,
        render_list_html_fn=lambda items, highlights=None: render_list_html(items, highlights),
        render_detail_label_fn=render_detail_label,
        render_detail_copy_fn=lambda text, highlights=None: render_detail_copy(text, highlights),
        render_detail_list_html_fn=lambda items, highlights=None: render_detail_list_html(items, highlights),
        render_market_views_table_fn=render_market_views_table,
        render_peripheral_table_fn=render_peripheral_table,
        render_catalysts_table_fn=render_catalysts_table,
        build_priority_debug_summary_fn=build_priority_debug_summary,
        format_html_report_fn=format_html_report,
    )


def analyze_batch_summary_with_llm(
    batch_emails: List[Dict],
    total_email_count: int,
    batch_index: int,
    batch_total: int,
    routing_state: Optional[Dict[str, Any]] = None,
) -> Dict:
    return app_report_pipeline.analyze_batch_summary_with_llm(
        batch_emails,
        total_email_count=total_email_count,
        batch_index=batch_index,
        batch_total=batch_total,
        routing_state=routing_state,
        build_emails_text_fn=lambda emails, count, total_body_budget: build_emails_text(
            emails,
            count,
            total_body_budget=MAX_PROMPT_BODY_CHARS // 2,
        ),
        build_report_system_prompt_fn=build_batch_system_prompt,
        get_visual_context_prompt_rules_fn=lambda: "",
        get_batch_summary_stage_rules_fn=lambda: "",
        generate_with_llm_fn=generate_with_llm,
        build_batch_summary_response_format_fn=build_batch_summary_response_format,
        parse_batch_summary_json_fn=parse_batch_summary_json,
    )


def merge_batch_summaries_with_llm(
    batch_summaries: List[Dict],
    total_email_count: int,
    source_emails: Optional[List[Dict]] = None,
    routing_state: Optional[Dict[str, Any]] = None,
) -> str:
    return app_report_pipeline.merge_batch_summaries_with_llm(
        batch_summaries,
        total_email_count=total_email_count,
        source_emails=source_emails,
        routing_state=routing_state,
        build_report_system_prompt_fn=build_merge_system_prompt,
        get_merge_stage_rules_fn=lambda _count: "",
        get_fixed_report_schema_prompt_fn=get_fixed_report_schema_prompt,
        generate_with_llm_fn=generate_with_llm,
        build_report_response_format_fn=build_report_response_format,
        parse_report_payload_json_fn=parse_report_payload_json,
        render_report_html_fn=render_report_html,
    )




# ============ 状态管理 ============
def load_state() -> Dict:
    """加载运行时状态。主状态源已统一收敛到 SQLite。"""
    return email_db.get_runtime_state()


def save_state(state: Dict):
    """保存运行时状态。主状态源已统一收敛到 SQLite。"""
    email_db.save_runtime_state(state)


def should_trigger() -> bool:
    """判断今天是否还需要发送 daily 报告。主状态源以数据库发送记录为准。"""
    today = datetime.now(BJT).strftime("%Y-%m-%d")
    return not email_db.has_successful_report_on_date(today, report_type="daily")


# ============ 邮件收取 ============
@app_runtime_qclaw_support.retry_on_error(logger=logger, max_retries=3, delay=3.0, backoff=2.0)
def fetch_emails(limit: int = 20) -> List[Dict]:
    """从Gmail收取邮件"""
    return app_mail_service.fetch_emails_and_persist(
        limit=limit,
        load_config_fn=load_config,
        parse_received_after_local_fn=parse_received_after_local,
        should_accept_sender_fn=should_accept_sender,
        get_message_local_datetime_fn=get_message_local_datetime,
        build_attachment_records_fn=_build_attachment_records,
        email_db_module=email_db,
        logger=logger,
    )


def mark_emails_processed(email_uids: List[str]):
    """标记指定邮件 UID 为已处理"""
    uids = [uid for uid in (email_uids or []) if uid]
    if not uids:
        return

    email_db.mark_processed(uids)
    local_id_map = email_db.get_local_ids_by_uids(uids)
    local_ids = [local_id_map.get(uid) for uid in uids if local_id_map.get(uid) is not None]
    if local_ids:
        logger.info(f"✅ 已标记 {len(uids)} 封邮件为已处理 (local_id: {min(local_ids)}-{max(local_ids)})")
    else:
        logger.info(f"✅ 已标记 {len(uids)} 封邮件为已处理")


# ============ AI 分析 ============

def call_llm_api(
    api_config: dict,
    system_prompt: str,
    user_prompt: str,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """调用兼容 chat/completions 的大模型 API，返回文本结果或 None。"""
    direct_session, proxied_session = _ensure_llm_sessions()
    return app_llm_client.call_llm_api(
        api_config,
        system_prompt,
        user_prompt,
        user_content_blocks=user_content_blocks,
        response_format=response_format,
        max_completion_tokens=MAX_COMPLETION_TOKENS,
        direct_session=direct_session,
        proxy_session=proxied_session,
        get_llm_http_session_fn=get_llm_http_session,
        logger=logger,
    )


def call_llm_api_with_retries(
    api_config: dict,
    system_prompt: str,
    user_prompt: str,
    label: str,
    max_retries: int = 1,
    delay: float = 5.0,
    backoff: float = 2.0,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """对单个模型做有限重试，失败后交由上层切换备用模型。"""
    return app_llm_client.call_llm_api_with_retries(
        api_config,
        system_prompt,
        user_prompt,
        label=label,
        max_retries=max_retries,
        delay=delay,
        backoff=backoff,
        user_content_blocks=user_content_blocks,
        response_format=response_format,
        call_llm_api_fn=call_llm_api,
        logger=logger,
    )


def analyze_emails_with_llm(emails: List[Dict]) -> Optional[str]:
    """
    调用主/备大模型分析邮件，生成 HF Morning Brief HTML
    支持尾部清洗、超长上下文拆批分析，以及主/备模型自动切换
    """
    return app_report_pipeline.analyze_emails_with_llm(
        emails,
        choose_visual_analysis_api_config_fn=choose_visual_analysis_api_config,
        split_emails_for_analysis_fn=split_emails_for_analysis,
        build_emails_text_fn=lambda batch_emails, total_email_count, total_body_budget: build_emails_text(
            batch_emails,
            total_email_count,
            total_body_budget=MAX_PROMPT_BODY_CHARS if total_body_budget <= 0 else total_body_budget,
        ),
        build_report_system_prompt_fn=build_report_system_prompt,
        get_visual_context_prompt_rules_fn=app_llm_prompts.get_visual_context_prompt_rules,
        get_fixed_report_schema_prompt_fn=get_fixed_report_schema_prompt,
        generate_with_llm_fn=generate_with_llm,
        build_report_response_format_fn=build_report_response_format,
        parse_report_payload_json_fn=parse_report_payload_json,
        render_report_html_fn=render_report_html,
        analyze_batch_summary_with_llm_fn=analyze_batch_summary_with_llm,
        merge_batch_summaries_with_llm_fn=merge_batch_summaries_with_llm,
        logger=logger,
    )


# ============ 报告处理 ============
def validate_html(html_content: str) -> tuple[bool, str]:
    """验证HTML内容完整性。"""
    return app_report_renderer.validate_html(html_content)


def estimate_read_minutes_from_html(body_content: str) -> int:
    """根据正文长度粗略估算阅读时间。"""
    text = re.sub(r"<[^>]+>", " ", body_content or "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return 1
    return max(1, min(8, round(len(text) / 320)))


def extract_recognized_source_label_from_email(email: Dict) -> str:
    """优先从邮件主题/正文中提取更真实的机构来源标签。"""
    return app_report_renderer.extract_recognized_source_label_from_email(
        email,
        source_label_patterns=SOURCE_LABEL_PATTERNS,
    )


def build_report_meta_html(source_emails: Optional[List[Dict]], body_content: str) -> str:
    """在标题下方展示阅读时长和来源。"""
    return app_report_renderer.build_report_meta_html(
        source_emails,
        body_content,
        extract_source_label_fn=extract_recognized_source_label_from_email,
    )


def normalize_report_body_content(body_content: str) -> str:
    """
    报告正文规范化单入口。

    原则：
    - 先收敛语义结构，再收敛视觉样式。
    规则：
    - 同类标签统一映射到固定组件。
    底线：
    - 不允许同一标签在不同报告里呈现出不一致的层级/底色。
    提醒：
    - prompt 只是建议，本地规则才是最终版式真源。
    """
    return app_report_renderer.normalize_report_body_content(
        body_content,
        normalize_legacy_label_boxes_fn=normalize_legacy_label_boxes,
        normalize_subsection_headings_fn=normalize_subsection_headings,
        normalize_standalone_labels_fn=normalize_standalone_labels,
        normalize_existing_heading_tags_fn=normalize_existing_heading_tags,
        normalize_semantic_callout_blocks_fn=normalize_semantic_callout_blocks,
        normalize_inline_labeled_paragraphs_fn=normalize_inline_labeled_paragraphs,
        strip_emojis_from_html_content_fn=strip_emojis_from_html_content,
        strip_highlight_inside_headings_fn=strip_highlight_inside_headings,
    )


def strip_emojis_from_html_content(body_content: str) -> str:
    """本地禁用 emoji，避免视觉风格漂移和模型偶发装饰性输出。"""
    return app_report_renderer.strip_emojis_from_html_content(
        body_content,
        emoji_pattern=EMOJI_PATTERN,
    )


def normalize_legacy_label_boxes(body_content: str) -> str:
    """把旧版 action-box/signal-box 渲染收敛成当前固定标签结构。"""
    return app_report_renderer.normalize_legacy_label_boxes(
        body_content,
        supported_labels=FIXED_DETAIL_LABELS,
    )


def format_html_report(
    html_content: str,
    source_emails: Optional[List[Dict]] = None,
    normalize_body: bool = True,
) -> str:
    """将模型生成的 HTML 格式化为标准格式。"""
    return app_report_renderer.format_html_report(
        html_content,
        source_emails=source_emails,
        normalize_body=normalize_body,
        base_dir=BASE_DIR,
        now_fn=lambda: datetime.now(BJT),
        build_report_meta_html_fn=build_report_meta_html,
        normalize_report_body_content_fn=normalize_report_body_content,
    )


def normalize_subsection_headings(body_content: str) -> str:
    """只把白名单里的真正 subsection 提升标题，避免字段标签误升层级。"""
    return app_report_renderer.normalize_subsection_headings(
        body_content,
        section_subheadings=SECTION_SUBHEADINGS,
    )


def strip_highlight_inside_headings(body_content: str) -> str:
    return app_report_renderer.strip_highlight_inside_headings(body_content)


def normalize_standalone_labels(body_content: str) -> str:
    """把常见的独立粗体标签提升成稳定的小节标题。"""
    return app_report_renderer.normalize_standalone_labels(
        body_content,
        section_subheadings=SECTION_SUBHEADINGS,
        time_horizon_subheadings=TIME_HORIZON_SUBHEADINGS,
        standalone_subheadings=STANDALONE_SUBHEADINGS,
        fixed_detail_labels=FIXED_DETAIL_LABELS,
    )


def normalize_existing_heading_tags(body_content: str) -> str:
    """把模型直接生成的 h3/h4 标签也收敛到硬规则语义。"""
    return app_report_renderer.normalize_existing_heading_tags(
        body_content,
        section_subheadings=SECTION_SUBHEADINGS,
        time_horizon_subheadings=TIME_HORIZON_SUBHEADINGS,
        standalone_subheadings=STANDALONE_SUBHEADINGS,
        semantic_callout_rules=SEMANTIC_CALLOUT_RULES,
    )


def build_semantic_callout(label: str, content_html: str) -> Optional[str]:
    """按硬规则把特定标签渲染成固定样式的提示框。"""
    return app_report_renderer.build_semantic_callout(
        label,
        content_html,
        semantic_callout_rules=SEMANTIC_CALLOUT_RULES,
    )


def normalize_semantic_callout_blocks(body_content: str) -> str:
    """把独立标签标题 + 紧随内容，收敛成固定样式的提示框。"""
    return app_report_renderer.normalize_semantic_callout_blocks(
        body_content,
        semantic_callout_rules=SEMANTIC_CALLOUT_RULES,
        fixed_detail_labels=FIXED_DETAIL_LABELS,
        build_semantic_callout_fn=build_semantic_callout,
    )


def normalize_inline_labeled_paragraphs(body_content: str) -> str:
    """规范行内标签段落，减少同类内容一会儿是正文一会儿是提示框。"""
    return app_report_renderer.normalize_inline_labeled_paragraphs(
        body_content,
        fixed_detail_labels=FIXED_DETAIL_LABELS,
        build_semantic_callout_fn=build_semantic_callout,
    )


def save_report(html_content: str, source_emails: Optional[List[Dict]] = None) -> Optional[str]:
    """保存 HTML 报告到文件"""
    return app_report_renderer.save_report(
        html_content,
        source_emails=source_emails,
        validate_html_fn=validate_html,
        format_html_report_fn=format_html_report,
        logger=logger,
        base_dir=BASE_DIR,
        now_fn=lambda: datetime.now(BJT),
    )


def check_for_report() -> Optional[str]:
    """检查是否生成了报告文件"""
    return app_report_renderer.check_for_report(
        base_dir=BASE_DIR,
        now_fn=lambda: datetime.now(BJT),
        report_prefix=REPORT_PREFIX,
    )


def get_report_preview(report_file: str, max_lines: int = 10) -> str:
    """获取报告预览"""
    return app_report_renderer.get_report_preview(report_file, max_lines=max_lines)


@app_runtime_qclaw_support.retry_on_error(logger=logger, max_retries=2, delay=3.0, backoff=2.0)
def send_report(
    report_file: str,
    email_uids: List[str],
    email_local_ids: Optional[List[int]] = None,
    source_emails: Optional[List[Dict[str, Any]]] = None,
    is_supplement: bool = False,
) -> bool:
    """发送报告到指定邮箱 - HTML正文

    Args:
        report_file: 报告文件路径
        email_uids: 本次报告覆盖的邮件 UID 列表（用于记录/幂等）
        email_local_ids: 本次报告覆盖的邮件本地ID列表（可选）
        is_supplement: 是否为补充分析
    """
    return app_runtime_report_delivery.send_report(
        report_file,
        email_uids,
        email_local_ids=email_local_ids,
        source_emails=source_emails,
        is_supplement=is_supplement,
        load_config_fn=load_config,
        send_email_fn=lambda **kwargs: app_mail_service.send_email(
            load_config_fn=load_config,
            **kwargs,
        ),
        now_fn=lambda: datetime.now(BJT),
        derive_email_scope_fn=app_email_preprocess.derive_email_scope,
        get_local_ids_by_uids_fn=email_db.get_local_ids_by_uids,
        finalize_report_success_fn=email_db.finalize_report_success,
        logger=logger,
    )


def cleanup():
    """保留 CLI 生命周期清理钩子。"""
    return None


def log_failed_report_attempt(
    *,
    email_uids: List[str],
    email_local_ids: Optional[List[int]] = None,
    is_supplement: bool = False,
) -> None:
    app_runtime_report_delivery.log_failed_report_attempt(
        email_uids=email_uids,
        email_local_ids=email_local_ids,
        is_supplement=is_supplement,
        load_config_fn=load_config,
        log_sent_report_fn=email_db.log_sent_report,
        now_fn=lambda: datetime.now(BJT),
    )


# ============ 主程序 ============
def print_status():
    """打印详细状态信息"""
    print(
        app_runtime_status_report.build_status_report(
            load_state_fn=load_state,
            email_db_module=email_db,
            check_for_report_fn=check_for_report,
            get_report_preview_fn=get_report_preview,
            log_file=LOG_FILE,
        )
    )


def main():
    """主程序"""
    return run_entrypoint(
        force_mode="--force" in sys.argv,
        check_mode="--check" in sys.argv,
        analyze_mode="--analyze" in sys.argv,
        supplement_mode="--supplement" in sys.argv,
        acquire_analysis_lock_for_run=True,
        print_banner=True,
    )


def run_entrypoint(
    *,
    force_mode: bool = False,
    check_mode: bool = False,
    analyze_mode: bool = False,
    supplement_mode: bool = False,
    acquire_analysis_lock_for_run: bool = True,
    print_banner: bool = True,
) -> int:
    primary_model = load_llm_config().get("model", "unknown")
    if print_banner:
        print("=" * 60)
        print(f"🚀 LLM 邮件自动处理中 - {primary_model}")
        print("=" * 60)
        print(f"当前时间: {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')} (北京时间)")
        print()

    logger.info("程序启动")

    if supplement_mode and not analyze_mode:
        analyze_mode = True

    if check_mode:
        print_status()
        return 0

    analysis_lock = None
    if acquire_analysis_lock_for_run:
        analysis_lock = try_acquire_analysis_lock()
        if analysis_lock is None:
            logger.warning("⏭️ 已有分析流程运行中，跳过本次触发")
            if print_banner:
                print("⏭️ 已有分析流程运行中，跳过本次触发")
            return 0

    try:
        if analyze_mode:
            return app_runtime_service_analysis.run_analysis_job(
                supplement_mode=supplement_mode,
            )

        app_runtime_qclaw_runner.run_normal_mode(
            force_mode=force_mode,
            should_trigger_fn=should_trigger,
            fetch_emails_fn=fetch_emails,
            email_db_module=email_db,
            analyze_emails_with_llm_fn=analyze_emails_with_llm,
            save_report_fn=save_report,
            send_report_fn=send_report,
            cleanup_fn=cleanup,
            log_failed_report_attempt_fn=log_failed_report_attempt,
            record_run_error_fn=lambda message: app_runtime_state.record_run_error(
                message,
                load_state_fn=load_state,
                save_state_fn=save_state,
            ),
            record_run_success_fn=lambda: app_runtime_state.record_run_success(
                now_fn=lambda: datetime.now(BJT),
                load_state_fn=load_state,
                save_state_fn=save_state,
            ),
            logger=logger,
            supplement_mode=supplement_mode,
        )
        return 0
    finally:
        if acquire_analysis_lock_for_run:
            release_analysis_lock(analysis_lock)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("⚠️ 用户中断")
        print("\n⚠️ 已退出")
    except Exception as e:
        logger.error(f"❌ 未处理的异常: {e}")
        logger.error(traceback.format_exc())
        print(f"\n❌ 发生错误: {e}")
        sys.exit(1)
