from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

import pytz
import yaml

from app import config as app_config
from app.llm import client as app_llm_client
from app.llm import json_utils as app_llm_json_utils
from app.llm import prompts as app_llm_prompts
from app.mail import runtime_helpers as app_mail_runtime
from app.mail import service as app_mail_service
from app.pipeline import email_preprocess as app_email_preprocess
from app.pipeline import multimodal_pipeline as app_multimodal_pipeline
from app.pipeline import report_payload as app_report_payload
from app.pipeline import report_pipeline as app_report_pipeline
from app.render import report_renderer as app_report_renderer
from app.runtime import qclaw_runtime as app_runtime_qclaw_runtime
from app.runtime import qclaw_support as app_runtime_qclaw_support
from app.runtime import report_delivery as app_runtime_report_delivery
from app.runtime import state as app_runtime_state
from app.storage import email_db


PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CONFIG_FILE = os.getenv("EMAIL_SERVICE_CONFIG", os.path.join(PROJECT_ROOT, "config.yaml"))
BASE_DIR = PROJECT_ROOT
BJT = pytz.timezone("Asia/Shanghai")
REPORT_PREFIX = "report_"
MAX_EMAIL_BODY_CHARS = 12000
MAX_PROMPT_BODY_CHARS = 40000
MAX_COMPLETION_TOKENS = 12000
MIN_TRUNCATION_CONTENT_CHARS = 40
MAX_MULTIMODAL_IMAGES = 8

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
)

logger = logging.getLogger(__name__)
session = None
proxy_session = None
_RUNTIME_SETTINGS: Optional[Dict[str, Any]] = None


def _ensure_llm_sessions():
    global session
    global proxy_session

    if session is None or proxy_session is None:
        session, proxy_session = app_runtime_qclaw_support.build_llm_sessions()
    return session, proxy_session


def load_config() -> Dict[str, Any]:
    global _RUNTIME_SETTINGS
    _RUNTIME_SETTINGS = app_runtime_qclaw_runtime.load_runtime_settings(CONFIG_FILE, logger)
    return dict(_RUNTIME_SETTINGS["config"])


def _get_runtime_settings(refresh: bool = False) -> Dict[str, Any]:
    global _RUNTIME_SETTINGS
    if refresh or _RUNTIME_SETTINGS is None:
        load_config()
    return _RUNTIME_SETTINGS or {}


def load_llm_config() -> Dict[str, Any]:
    return dict((_get_runtime_settings().get("llm_router_settings") or {}).get("primary") or {})


def load_visual_llm_config() -> Dict[str, Any]:
    return dict((_get_runtime_settings().get("image_settings") or {}).get("visual_llm") or {})


def load_visual_fast_llm_config() -> Dict[str, Any]:
    return dict((_get_runtime_settings().get("image_settings") or {}).get("visual_fast_llm") or {})


def build_llm_chain(primary_cfg: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    settings = _get_runtime_settings().get("llm_router_settings") or {}
    return app_llm_client.build_llm_chain(
        primary_cfg,
        backup_configs=[
            dict(settings.get("backup1") or {}),
            dict(settings.get("backup2") or {}),
            dict(settings.get("backup3") or {}),
        ],
    )


def get_ordered_llm_chain(
    primary_cfg: Dict[str, Any],
    routing_state: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    settings = _get_runtime_settings().get("llm_router_settings") or {}
    return app_llm_client.get_ordered_llm_chain(
        primary_cfg,
        backup_configs=[
            dict(settings.get("backup1") or {}),
            dict(settings.get("backup2") or {}),
            dict(settings.get("backup3") or {}),
        ],
        routing_state=routing_state,
    )


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
        model_supports_vision_fn=app_llm_client.model_supports_vision,
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


def get_llm_http_session(api_config: Dict[str, Any]):
    direct_session, proxied_session = _ensure_llm_sessions()
    return app_llm_client.get_llm_http_session(
        api_config,
        direct_session=direct_session,
        proxy_session=proxied_session,
    )


def call_llm_api(
    api_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
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
    api_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    *,
    label: str,
    max_retries: int = 1,
    delay: float = 5.0,
    backoff: float = 2.0,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
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


def build_multimodal_user_blocks(
    emails: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    return app_multimodal_pipeline.build_multimodal_user_blocks(
        emails,
        api_config=api_config,
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        max_multimodal_images=MAX_MULTIMODAL_IMAGES,
        logger=logger,
    )


def build_visual_llm_chain(primary_cfg: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    settings = _get_runtime_settings().get("image_settings") or {}
    return app_llm_client.build_named_config_chain(
        primary_cfg,
        primary_key="visual_primary",
        primary_label="视觉主模型",
        backup_configs=[
            dict(settings.get("visual_llm_backup") or {}),
            dict(settings.get("visual_llm_backup2") or {}),
        ],
        backup_key_prefix="visual_backup",
        backup_label_prefix="视觉备用模型",
    )


def build_visual_fast_llm_chain(primary_cfg: Dict[str, Any]) -> List[Tuple[str, str, Dict[str, Any]]]:
    settings = _get_runtime_settings().get("image_settings") or {}
    return app_llm_client.build_named_config_chain(
        primary_cfg,
        primary_key="visual_fast_primary",
        primary_label="视觉快模型",
        backup_configs=[dict(settings.get("visual_fast_llm_backup") or {})],
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
        model_supports_vision_fn=app_llm_client.model_supports_vision,
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
) -> Dict[str, Dict[str, str]]:
    image_settings = _get_runtime_settings().get("image_settings") or {}
    return app_multimodal_pipeline.classify_multimodal_images_lightweight_for_pipeline(
        images,
        api_config=api_config,
        load_visual_fast_llm_config_fn=load_visual_fast_llm_config,
        classification_concurrency=None,
        default_classification_concurrency=int(image_settings.get("classification_concurrency") or 2),
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        call_llm_api_with_retries_fn=_call_visual_fast_llm_for_pipeline,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        logger=logger,
    )


def _deep_analyze_multimodal_images(
    image_objects: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Dict[str, Any]]:
    image_settings = _get_runtime_settings().get("image_settings") or {}
    return app_multimodal_pipeline.deep_analyze_multimodal_images_for_pipeline(
        image_objects,
        api_config=api_config,
        load_visual_llm_config_fn=load_visual_llm_config,
        max_deep_analysis_images=None,
        default_max_deep_analysis_images=image_settings.get("max_deep_analysis_images"),
        deep_analysis_concurrency=None,
        default_deep_analysis_concurrency=int(image_settings.get("deep_analysis_concurrency") or 2),
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        call_llm_api_with_retries_fn=_call_visual_deep_llm_for_pipeline,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        normalize_string_list_fn=app_report_payload.normalize_string_list,
        logger=logger,
    )


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
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        classify_images_fn=_classify_multimodal_images_lightweight,
        deep_analyze_images_fn=_deep_analyze_multimodal_images,
        get_email_visual_context_fn=email_db.get_email_visual_context,
        get_email_visual_contexts_fn=email_db.get_email_visual_contexts,
        get_email_image_analysis_records_fn=email_db.get_email_image_analysis_records,
        get_email_image_analysis_records_map_fn=email_db.get_email_image_analysis_records_map,
        upsert_email_images_fn=email_db.upsert_email_images,
        upsert_email_images_batch_fn=email_db.upsert_email_images_batch,
        update_image_classifications_fn=email_db.update_image_classifications,
        update_image_classifications_batch_fn=email_db.update_image_classifications_batch,
        upsert_image_analysis_results_fn=email_db.upsert_image_analysis_results,
        upsert_image_analysis_results_batch_fn=email_db.upsert_image_analysis_results_batch,
        save_email_visual_context_fn=email_db.save_email_visual_context,
        save_email_visual_contexts_batch_fn=email_db.save_email_visual_contexts_batch,
        logger=logger,
    )


def prepare_emails_for_analysis(
    emails: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    return app_runtime_qclaw_runtime.prepare_emails_for_analysis(
        emails,
        api_config=api_config,
        sanitize_email_body_fn=sanitize_email_body,
        build_email_visual_context_map_for_analysis_fn=build_email_visual_context_map_for_analysis,
        render_email_visual_context_text_fn=app_multimodal_pipeline.render_email_visual_context_text,
    )


def split_emails_for_analysis(
    emails: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
) -> List[List[Dict[str, Any]]]:
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


def build_emails_text(emails: List[Dict[str, Any]], total_email_count: int, total_body_budget: int) -> str:
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
    emails: Optional[List[Dict[str, Any]]] = None,
    routing_state: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
) -> str:
    return app_runtime_qclaw_runtime.generate_with_llm(
        system_prompt,
        user_prompt,
        emails=emails,
        routing_state=routing_state,
        response_format=response_format,
        load_llm_config_fn=load_llm_config,
        get_ordered_llm_chain_fn=get_ordered_llm_chain,
        call_llm_api_with_retries_fn=call_llm_api_with_retries,
        build_user_content_blocks_fn=build_multimodal_user_blocks,
        logger=logger,
    )


def save_malformed_json_snapshot(raw_text: str, prefix: str = "malformed_report_payload") -> Optional[str]:
    try:
        timestamp = datetime.now(BJT).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(BASE_DIR, f"{prefix}_{timestamp}.txt")
        with open(path, "w", encoding="utf-8") as handle:
            handle.write(raw_text or "")
        logger.warning(f"⚠️ 已保存损坏 JSON 快照: {path}")
        return path
    except Exception as exc:
        logger.warning(f"⚠️ 保存损坏 JSON 快照失败: {exc}")
        return None


def load_json_dict_with_fallbacks(raw_text: str) -> Dict[str, Any]:
    return app_llm_json_utils.load_json_dict_with_fallbacks(raw_text)


def repair_report_payload_json(raw_text: str) -> Dict[str, Any]:
    return app_report_payload.repair_report_payload_json(
        raw_text,
        save_malformed_json_snapshot_fn=save_malformed_json_snapshot,
        generate_with_llm_fn=generate_with_llm,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        logger=logger,
    )


def parse_batch_summary_json(text: str) -> Dict[str, Any]:
    return app_report_pipeline.parse_batch_summary_json(
        text,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
    )


def parse_report_payload_json(text: str) -> Dict[str, Any]:
    return app_report_payload.parse_report_payload_json(
        text,
        load_json_dict_with_fallbacks_fn=load_json_dict_with_fallbacks,
        repair_report_payload_json_fn=repair_report_payload_json,
        normalize_report_payload_fn=app_report_payload.normalize_report_payload,
        logger=logger,
    )


def validate_html(html_content: str) -> tuple[bool, str]:
    return app_report_renderer.validate_html(html_content)


def extract_recognized_source_label_from_email(email: Dict[str, Any]) -> str:
    return app_report_renderer.extract_recognized_source_label_from_email(
        email,
        source_label_patterns=app_report_renderer.SOURCE_LABEL_PATTERNS,
    )


def build_report_meta_html(source_emails: Optional[List[Dict[str, Any]]], body_content: str) -> str:
    return app_report_renderer.build_report_meta_html(
        source_emails,
        body_content,
        extract_source_label_fn=extract_recognized_source_label_from_email,
    )


def strip_emojis_from_html_content(body_content: str) -> str:
    return app_report_renderer.strip_emojis_from_html_content(
        body_content,
        emoji_pattern=EMOJI_PATTERN,
    )


def normalize_legacy_label_boxes(body_content: str) -> str:
    return app_report_renderer.normalize_legacy_label_boxes(
        body_content,
        supported_labels=app_report_renderer.FIXED_DETAIL_LABELS,
    )


def normalize_subsection_headings(body_content: str) -> str:
    return app_report_renderer.normalize_subsection_headings(
        body_content,
        section_subheadings=app_report_renderer.SECTION_SUBHEADINGS,
    )


def normalize_standalone_labels(body_content: str) -> str:
    return app_report_renderer.normalize_standalone_labels(
        body_content,
        section_subheadings=app_report_renderer.SECTION_SUBHEADINGS,
        time_horizon_subheadings=app_report_renderer.TIME_HORIZON_SUBHEADINGS,
        standalone_subheadings=app_report_renderer.STANDALONE_SUBHEADINGS,
        fixed_detail_labels=app_report_renderer.FIXED_DETAIL_LABELS,
    )


def normalize_existing_heading_tags(body_content: str) -> str:
    return app_report_renderer.normalize_existing_heading_tags(
        body_content,
        section_subheadings=app_report_renderer.SECTION_SUBHEADINGS,
        time_horizon_subheadings=app_report_renderer.TIME_HORIZON_SUBHEADINGS,
        standalone_subheadings=app_report_renderer.STANDALONE_SUBHEADINGS,
        semantic_callout_rules=app_report_renderer.SEMANTIC_CALLOUT_RULES,
    )


def build_semantic_callout(label: str, content_html: str) -> Optional[str]:
    return app_report_renderer.build_semantic_callout(
        label,
        content_html,
        semantic_callout_rules=app_report_renderer.SEMANTIC_CALLOUT_RULES,
    )


def normalize_semantic_callout_blocks(body_content: str) -> str:
    return app_report_renderer.normalize_semantic_callout_blocks(
        body_content,
        semantic_callout_rules=app_report_renderer.SEMANTIC_CALLOUT_RULES,
        fixed_detail_labels=app_report_renderer.FIXED_DETAIL_LABELS,
        build_semantic_callout_fn=build_semantic_callout,
    )


def normalize_inline_labeled_paragraphs(body_content: str) -> str:
    return app_report_renderer.normalize_inline_labeled_paragraphs(
        body_content,
        fixed_detail_labels=app_report_renderer.FIXED_DETAIL_LABELS,
        build_semantic_callout_fn=build_semantic_callout,
    )


def normalize_report_body_content(body_content: str) -> str:
    return app_report_renderer.normalize_report_body_content(
        body_content,
        normalize_legacy_label_boxes_fn=normalize_legacy_label_boxes,
        normalize_subsection_headings_fn=normalize_subsection_headings,
        normalize_standalone_labels_fn=normalize_standalone_labels,
        normalize_existing_heading_tags_fn=normalize_existing_heading_tags,
        normalize_semantic_callout_blocks_fn=normalize_semantic_callout_blocks,
        normalize_inline_labeled_paragraphs_fn=normalize_inline_labeled_paragraphs,
        strip_emojis_from_html_content_fn=strip_emojis_from_html_content,
        strip_highlight_inside_headings_fn=app_report_renderer.strip_highlight_inside_headings,
    )


def format_html_report(
    html_content: str,
    source_emails: Optional[List[Dict[str, Any]]] = None,
    normalize_body: bool = True,
) -> str:
    return app_report_renderer.format_html_report(
        html_content,
        source_emails=source_emails,
        normalize_body=normalize_body,
        base_dir=BASE_DIR,
        now_fn=lambda: datetime.now(BJT),
        build_report_meta_html_fn=build_report_meta_html,
        normalize_report_body_content_fn=normalize_report_body_content,
    )


def render_list_html(items: List[Any], highlights: Optional[List[str]] = None) -> str:
    return app_report_renderer.render_list_html(
        items,
        highlights=highlights,
        escape_with_highlights_fn=app_report_renderer.escape_with_highlights,
    )


def render_detail_list_html(items: List[Any], highlights: Optional[List[str]] = None) -> str:
    return app_report_renderer.render_detail_list_html(
        items,
        highlights=highlights,
        render_list_html_fn=lambda current_items, current_highlights=None: render_list_html(
            current_items,
            current_highlights,
        ),
    )


def render_report_html(report_payload: Dict[str, Any], source_emails: Optional[List[Dict[str, Any]]] = None) -> str:
    return app_report_renderer.render_report_html(
        report_payload,
        source_emails=source_emails,
        normalize_report_payload_fn=app_report_payload.normalize_report_payload,
        logger=logger,
        fixed_report_template=app_report_renderer.FIXED_REPORT_TEMPLATE,
        render_list_html_fn=lambda items, highlights=None: render_list_html(items, highlights),
        render_detail_label_fn=app_report_renderer.render_detail_label,
        render_detail_copy_fn=lambda text, highlights=None: app_report_renderer.render_detail_copy(
            text,
            highlights=highlights,
            escape_with_highlights_fn=app_report_renderer.escape_with_highlights,
        ),
        render_detail_list_html_fn=lambda items, highlights=None: render_detail_list_html(items, highlights),
        render_market_views_table_fn=lambda rows: app_report_renderer.render_market_views_table(
            rows,
            escape_with_highlights_fn=app_report_renderer.escape_with_highlights,
        ),
        render_peripheral_table_fn=app_report_renderer.render_peripheral_table,
        render_catalysts_table_fn=app_report_renderer.render_catalysts_table,
        build_priority_debug_summary_fn=app_report_renderer.build_priority_debug_summary,
        format_html_report_fn=format_html_report,
    )


def save_report(html_content: str, source_emails: Optional[List[Dict[str, Any]]] = None) -> Optional[str]:
    return app_report_renderer.save_report(
        html_content,
        source_emails=source_emails,
        validate_html_fn=validate_html,
        format_html_report_fn=format_html_report,
        logger=logger,
        base_dir=BASE_DIR,
        now_fn=lambda: datetime.now(BJT),
    )


def analyze_batch_summary_with_llm(
    batch_emails: List[Dict[str, Any]],
    total_email_count: int,
    batch_index: int,
    batch_total: int,
    routing_state: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
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
        build_report_system_prompt_fn=app_llm_prompts.build_batch_system_prompt,
        get_visual_context_prompt_rules_fn=lambda: "",
        get_batch_summary_stage_rules_fn=lambda: "",
        generate_with_llm_fn=generate_with_llm,
        build_batch_summary_response_format_fn=app_llm_prompts.build_batch_summary_response_format,
        parse_batch_summary_json_fn=parse_batch_summary_json,
    )


def merge_batch_summaries_with_llm(
    batch_summaries: List[Dict[str, Any]],
    total_email_count: int,
    source_emails: Optional[List[Dict[str, Any]]] = None,
    routing_state: Optional[Dict[str, Any]] = None,
) -> str:
    return app_report_pipeline.merge_batch_summaries_with_llm(
        batch_summaries,
        total_email_count=total_email_count,
        source_emails=source_emails,
        routing_state=routing_state,
        build_report_system_prompt_fn=app_llm_prompts.build_merge_system_prompt,
        get_merge_stage_rules_fn=lambda _count: "",
        get_fixed_report_schema_prompt_fn=app_llm_prompts.get_fixed_report_schema_prompt,
        generate_with_llm_fn=generate_with_llm,
        build_report_response_format_fn=app_llm_prompts.build_report_response_format,
        parse_report_payload_json_fn=parse_report_payload_json,
        render_report_html_fn=render_report_html,
    )


def analyze_emails_with_llm(emails: List[Dict[str, Any]]) -> Optional[str]:
    return app_report_pipeline.analyze_emails_with_llm(
        emails,
        choose_visual_analysis_api_config_fn=choose_visual_analysis_api_config,
        split_emails_for_analysis_fn=split_emails_for_analysis,
        build_emails_text_fn=lambda batch_emails, total_email_count, total_body_budget: build_emails_text(
            batch_emails,
            total_email_count,
            total_body_budget=MAX_PROMPT_BODY_CHARS if total_body_budget <= 0 else total_body_budget,
        ),
        build_report_system_prompt_fn=app_llm_prompts.build_report_system_prompt,
        get_visual_context_prompt_rules_fn=app_llm_prompts.get_visual_context_prompt_rules,
        get_fixed_report_schema_prompt_fn=app_llm_prompts.get_fixed_report_schema_prompt,
        generate_with_llm_fn=generate_with_llm,
        build_report_response_format_fn=app_llm_prompts.build_report_response_format,
        parse_report_payload_json_fn=parse_report_payload_json,
        render_report_html_fn=render_report_html,
        analyze_batch_summary_with_llm_fn=analyze_batch_summary_with_llm,
        merge_batch_summaries_with_llm_fn=merge_batch_summaries_with_llm,
        logger=logger,
    )


def load_state() -> Dict[str, Any]:
    return email_db.get_runtime_state()


def save_state(state: Dict[str, Any]) -> None:
    email_db.save_runtime_state(state)


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


def send_report(
    report_file: str,
    email_uids: List[str],
    email_local_ids: Optional[List[int]] = None,
    source_emails: Optional[List[Dict[str, Any]]] = None,
    is_supplement: bool = False,
) -> bool:
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


def run_analysis_job(*, supplement_mode: bool = False) -> int:
    emails = email_db.get_pending_emails(limit=20)
    if not emails:
        logger.warning("📭 没有待分析的邮件")
        return 0

    try:
        html_content = analyze_emails_with_llm(emails)
    except Exception as exc:
        logger.error(f"❌ 大模型分析失败: {exc}")
        app_runtime_state.record_run_error(
            f"分析失败: {str(exc)[:100]}",
            load_state_fn=load_state,
            save_state_fn=save_state,
        )
        return 1

    if not html_content:
        logger.error("❌ 大模型分析失败")
        return 1

    report_file = save_report(html_content, source_emails=emails)
    if not report_file:
        logger.error("❌ 保存报告失败")
        return 1

    email_uids = [item.get("id") for item in emails if item.get("id")]
    email_local_ids = [item.get("local_id") for item in emails if item.get("local_id") is not None]
    try:
        send_success = send_report(
            report_file,
            email_uids=email_uids,
            email_local_ids=email_local_ids,
            source_emails=emails,
            is_supplement=supplement_mode,
        )
    except Exception as exc:
        logger.error(f"❌ 发送报告失败: {exc}")
        try:
            log_failed_report_attempt(
                email_uids=email_uids,
                email_local_ids=email_local_ids,
                is_supplement=supplement_mode,
            )
        except Exception:
            pass
        app_runtime_state.record_run_error(
            f"发送失败: {str(exc)[:100]}",
            load_state_fn=load_state,
            save_state_fn=save_state,
        )
        return 1

    if not send_success:
        logger.warning("⚠️ 发送失败，邮件保留为待处理状态")
        app_runtime_state.record_run_error(
            "发送失败",
            load_state_fn=load_state,
            save_state_fn=save_state,
        )
        return 1

    logger.info("✅ 邮件已完成发送与状态落库")
    if supplement_mode:
        logger.info("✅ 补充分析完成，已单独推送")
    return 0
