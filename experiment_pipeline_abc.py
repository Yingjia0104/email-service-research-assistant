from __future__ import annotations

import argparse
import json
import logging
import os
import re
import statistics
import subprocess
import tempfile
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from email.utils import parseaddr
from html import unescape
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import extract_msg

from app import config as app_config
from app.llm import client as app_llm_client
from app.llm import prompts as app_llm_prompts
from app.mail import runtime_helpers as app_mail_runtime
from app.pipeline import email_preprocess as app_email_preprocess
from app.pipeline import multimodal_pipeline as app_multimodal_pipeline
from app.pipeline import report_payload as app_report_payload
from app.pipeline import report_pipeline as app_report_pipeline
from app.runtime import qclaw_runtime as app_runtime_qclaw_runtime
from app.runtime import service_analysis as app_service_analysis


ROOT = Path(__file__).resolve().parent
DEFAULT_SAMPLE_DIRS = [
    ROOT / "sample-emails-0313",
    ROOT / "sample-emails-0309",
]
REPORT_SPECS = {
    "a": {
        "name": "A",
        "title": "纯文本基线",
        "stem": "experiment_report_a_text_only",
    },
    "b": {
        "name": "B",
        "title": "正式图片链路",
        "stem": "experiment_report_b_pipeline_with_images",
    },
    "c": {
        "name": "C",
        "title": "文本+原始图片直塞主模型",
        "stem": "experiment_report_c_raw_images",
    },
}
COMPARISON_PATH = ROOT / "experiment_comparison_abc.md"
RUNTIME_SUMMARY_PATH = ROOT / "experiment_runtime_summary_abc.json"

LOGGER = logging.getLogger("experiment_pipeline_abc")


def build_default_config_text() -> str:
    return """llm:
  api_key_env: "DASHSCOPE_API_KEY"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3-max"
  supports_vision: true

llm_backup2:
  api_key_env: "MOONSHOT_API_KEY"
  base_url: "https://api.moonshot.ai/v1"
  model: "kimi-k2.5"
  supports_vision: true

visual_llm:
  api_key_env: "DASHSCOPE_API_KEY"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3-vl-235b-a22b-thinking"
  supports_vision: true

visual_llm_backup:
  api_key_env: "DASHSCOPE_API_KEY"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen-vl-max-latest"
  supports_vision: true

visual_llm_backup2:
  api_key_env: "DASHSCOPE_API_KEY"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen-vl-plus-latest"
  supports_vision: true

visual_llm_fast:
  api_key_env: "DASHSCOPE_API_KEY"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen-vl-max-latest"
  supports_vision: true

visual_llm_fast_backup:
  api_key_env: "DASHSCOPE_API_KEY"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen-vl-plus-latest"
  supports_vision: true

multimodal:
  classification_concurrency: 2
  deep_analysis_concurrency: 2
"""


def ensure_runtime_config(config_path: Optional[str]) -> Path:
    if config_path:
        return Path(config_path).resolve()

    repo_config = ROOT / "config.yaml"
    if repo_config.exists():
        return repo_config

    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".yaml",
        prefix="experiment_pipeline_abc_",
        delete=False,
    )
    handle.write(build_default_config_text())
    handle.flush()
    handle.close()
    LOGGER.info("未发现 config.yaml，已生成临时实验配置: %s", handle.name)
    return Path(handle.name)


def configure_runtime(config_path: Path) -> None:
    app_service_analysis.CONFIG_FILE = str(config_path)
    app_service_analysis._RUNTIME_SETTINGS = None
    app_service_analysis.load_config()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run A/B/C image value experiment on local .msg samples.")
    parser.add_argument(
        "--sample-dir",
        action="append",
        dest="sample_dirs",
        default=None,
        help="Directory containing .msg sample emails. Can be passed multiple times.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        default=None,
        help="Path to config.yaml. If omitted, uses repo config.yaml or a generated temporary config.",
    )
    parser.add_argument(
        "--baseline-commit",
        default="61667bf",
        help="Documented origin/main baseline commit for this experiment.",
    )
    parser.add_argument(
        "--groups",
        default="a,b,c",
        help="Comma-separated groups to run. Supported values: a,b,c.",
    )
    return parser.parse_args()


def run_git_command(args: List[str]) -> str:
    try:
        return subprocess.check_output(args, cwd=ROOT, text=True).strip()
    except Exception:
        return ""


def load_sample_emails(sample_dirs: Iterable[Path]) -> List[Dict[str, Any]]:
    emails: List[Dict[str, Any]] = []
    for sample_dir in sample_dirs:
        for msg_path in sorted(sample_dir.glob("*.msg")):
            emails.append(load_msg_email(msg_path))
    return emails


def load_msg_email(msg_path: Path) -> Dict[str, Any]:
    msg = extract_msg.Message(str(msg_path))
    attachment_contents, embedded_images, attachment_records = app_mail_runtime.build_attachment_records(
        msg,
        logger=LOGGER,
    )
    sender = str(getattr(msg, "sender", "") or "")
    _, sender_email = parseaddr(sender)
    body = str(getattr(msg, "body", "") or "")
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

    return {
        "id": msg_path.stem,
        "from": sender,
        "from_name": (getattr(msg, "sender", "") or "").split("<", 1)[0].strip(),
        "email_from": sender_email or sender,
        "to": str(getattr(msg, "to", "") or ""),
        "subject": str(getattr(msg, "subject", "") or msg_path.stem),
        "date": str(getattr(msg, "date", "") or ""),
        "preview": combined_body[:200],
        "body": combined_body,
        "attachments": attachment_records,
        "_sample_path": str(msg_path),
    }


def collect_uncapped_images(emails: List[Dict[str, Any]]) -> Dict[str, Any]:
    return app_multimodal_pipeline.collect_multimodal_images(
        emails,
        api_config=app_service_analysis.load_visual_fast_llm_config(),
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        max_multimodal_images=None,
        logger=LOGGER,
    )


def prepare_text_only_emails(
    emails: List[Dict[str, Any]],
    *,
    suppress_raw_images: bool,
) -> List[Dict[str, Any]]:
    prepared: List[Dict[str, Any]] = []
    for idx, email in enumerate(emails, 1):
        item = dict(email)
        body = app_service_analysis.sanitize_email_body(email.get("body", ""))
        item["_analysis_index"] = idx
        item["_analysis_body"] = body
        item["_analysis_body_len"] = len(body)
        item["_inline_visual_contexts"] = []
        item["_supporting_visual_evidence"] = []
        item["_visual_context_text"] = ""
        item["_visual_status"] = "disabled" if suppress_raw_images else ""
        item["_visual_context_ready"] = False
        item["_visual_input_locked"] = bool(suppress_raw_images)
        if suppress_raw_images:
            item["_analysis_visual_context_applied"] = True
        prepared.append(item)
    return prepared


def classify_images_uncapped(
    images: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
    *,
    classification_concurrency: int = 1,
) -> Dict[str, Dict[str, str]]:
    return app_multimodal_pipeline.classify_multimodal_images_lightweight(
        images,
        api_config=api_config or app_service_analysis.load_visual_fast_llm_config(),
        classification_concurrency=classification_concurrency,
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        call_llm_api_with_retries_fn=app_service_analysis._call_visual_fast_llm_for_pipeline,
        load_json_dict_with_fallbacks_fn=app_service_analysis.load_json_dict_with_fallbacks,
        logger=LOGGER,
    )


def deep_analyze_images_uncapped(
    image_objects: List[Dict[str, Any]],
    api_config: Optional[Dict[str, Any]] = None,
    *,
    max_deep_analysis_images: Optional[int] = None,
    deep_analysis_concurrency: int = 1,
) -> Dict[str, Dict[str, Any]]:
    del max_deep_analysis_images
    return app_multimodal_pipeline.deep_analyze_multimodal_images(
        image_objects,
        api_config=api_config or app_service_analysis.load_visual_llm_config(),
        max_deep_analysis_images=None,
        deep_analysis_concurrency=deep_analysis_concurrency,
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        call_llm_api_with_retries_fn=app_service_analysis._call_visual_deep_llm_for_pipeline,
        load_json_dict_with_fallbacks_fn=app_service_analysis.load_json_dict_with_fallbacks,
        normalize_string_list_fn=app_report_payload.normalize_string_list,
        logger=LOGGER,
    )


def build_uncapped_visual_context_map(
    emails: List[Dict[str, Any]],
) -> Tuple[Dict[int, Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    config = app_service_analysis.load_config()
    image_settings = app_config.build_image_pipeline_settings(config)
    session = app_multimodal_pipeline.run_multimodal_image_analysis_session(
        emails,
        classification_api_config=app_service_analysis.load_visual_fast_llm_config(),
        deep_analysis_api_config=app_service_analysis.load_visual_llm_config(),
        collect_multimodal_images_fn=app_multimodal_pipeline.collect_multimodal_images,
        build_image_objects_fn=app_multimodal_pipeline.build_image_objects,
        classify_images_fn=classify_images_uncapped,
        deep_analyze_images_fn=deep_analyze_images_uncapped,
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        max_multimodal_images=None,
        max_deep_analysis_images=None,
        classification_concurrency=int(image_settings.get("classification_concurrency") or 1),
        deep_analysis_concurrency=int(image_settings.get("deep_analysis_concurrency") or 1),
        logger=LOGGER,
    )
    computed_map = app_multimodal_pipeline.build_email_visual_context_map(
        session["image_objects"],
        max_inline_visual_contexts=image_settings.get("max_inline_visual_contexts"),
        max_supporting_visual_evidence=image_settings.get("max_supporting_visual_evidence"),
    )

    image_objects_by_index: Dict[int, List[Dict[str, Any]]] = {}
    for image_object in session["image_objects"]:
        image_objects_by_index.setdefault(int(image_object.get("email_index") or 0), []).append(image_object)

    context_map: Dict[int, Dict[str, Any]] = {}
    for email_index in range(1, len(emails) + 1):
        scoped = dict(
            computed_map.get(
                email_index,
                {
                    "inline_visual_contexts": [],
                    "supporting_visual_evidence": [],
                    "inline_visual_context_records": [],
                    "supporting_visual_evidence_records": [],
                },
            )
        )
        stats = dict((session.get("email_stats_by_index") or {}).get(email_index) or {})
        visual_status = app_multimodal_pipeline.derive_visual_status_for_email(
            image_objects_by_index.get(email_index, []),
            candidate_images=int(stats.get("candidate_images") or 0),
            selected_images_count=int(stats.get("selected_images") or 0),
            skipped_due_to_cap=int(stats.get("skipped_due_to_cap") or 0),
        )
        scoped["visual_status"] = visual_status
        scoped["enriched_body"] = app_multimodal_pipeline.render_email_visual_context_text(scoped)
        context_map[email_index] = scoped

    return context_map, session, image_settings


def prepare_pipeline_emails(
    emails: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
    context_map, session, image_settings = build_uncapped_visual_context_map(emails)
    prepared = app_email_preprocess.prepare_emails_for_analysis(
        emails,
        api_config=None,
        sanitize_email_body_fn=app_service_analysis.sanitize_email_body,
        build_email_visual_context_map_for_analysis_fn=lambda items, api_config=None: context_map,
        render_email_visual_context_text_fn=app_multimodal_pipeline.render_email_visual_context_text,
    )
    return prepared, session, image_settings


def build_uncapped_raw_image_blocks(
    emails: List[Dict[str, Any]],
    api_config: Dict[str, Any],
) -> List[Dict[str, Any]]:
    return app_multimodal_pipeline.build_multimodal_user_blocks(
        emails,
        api_config=api_config,
        model_supports_vision_fn=app_llm_client.model_supports_vision,
        max_multimodal_images=None,
        logger=LOGGER,
    )


def make_group_generate_with_llm(allow_raw_images: bool):
    def generate_with_llm(
        system_prompt: str,
        user_prompt: str,
        emails: Optional[List[Dict[str, Any]]] = None,
        routing_state: Optional[Dict[str, Any]] = None,
        response_format: Optional[Dict[str, Any]] = None,
    ) -> str:
        build_user_blocks = (
            build_uncapped_raw_image_blocks
            if allow_raw_images
            else (lambda current_emails, api_config: [])
        )
        return app_runtime_qclaw_runtime.generate_with_llm(
            system_prompt,
            user_prompt,
            emails=emails,
            routing_state=routing_state,
            response_format=response_format,
            load_llm_config_fn=app_service_analysis.load_llm_config,
            get_ordered_llm_chain_fn=app_service_analysis.get_ordered_llm_chain,
            call_llm_api_with_retries_fn=app_service_analysis.call_llm_api_with_retries,
            build_user_content_blocks_fn=build_user_blocks,
            logger=LOGGER,
        )

    return generate_with_llm


def analyze_group_report(
    prepared_emails: List[Dict[str, Any]],
    *,
    allow_raw_images: bool,
) -> str:
    generate_with_llm = make_group_generate_with_llm(allow_raw_images=allow_raw_images)
    analyze_batch_summary_with_llm = lambda batch_emails, total_email_count, batch_index, batch_total, routing_state=None: app_report_pipeline.analyze_batch_summary_with_llm(
        batch_emails,
        total_email_count=total_email_count,
        batch_index=batch_index,
        batch_total=batch_total,
        routing_state=routing_state,
        build_emails_text_fn=lambda emails, count, total_body_budget: app_service_analysis.build_emails_text(
            emails,
            count,
            total_body_budget=app_service_analysis.MAX_PROMPT_BODY_CHARS // 2,
        ),
        build_report_system_prompt_fn=app_llm_prompts.build_batch_system_prompt,
        get_visual_context_prompt_rules_fn=lambda: "",
        get_batch_summary_stage_rules_fn=lambda: "",
        generate_with_llm_fn=generate_with_llm,
        build_batch_summary_response_format_fn=app_llm_prompts.build_batch_summary_response_format,
        parse_batch_summary_json_fn=app_service_analysis.parse_batch_summary_json,
    )
    merge_batch_summaries_with_llm = lambda batch_summaries, total_email_count, source_emails=None, routing_state=None: app_report_pipeline.merge_batch_summaries_with_llm(
        batch_summaries,
        total_email_count=total_email_count,
        source_emails=source_emails,
        routing_state=routing_state,
        build_report_system_prompt_fn=app_llm_prompts.build_merge_system_prompt,
        get_merge_stage_rules_fn=lambda _count: "",
        get_fixed_report_schema_prompt_fn=app_llm_prompts.get_fixed_report_schema_prompt,
        generate_with_llm_fn=generate_with_llm,
        build_report_response_format_fn=app_llm_prompts.build_report_response_format,
        parse_report_payload_json_fn=app_service_analysis.parse_report_payload_json,
        render_report_html_fn=app_service_analysis.render_report_html,
    )
    return app_report_pipeline.analyze_emails_with_llm(
        prepared_emails,
        choose_visual_analysis_api_config_fn=lambda _routing_state=None: None,
        split_emails_for_analysis_fn=app_service_analysis.split_emails_for_analysis,
        build_emails_text_fn=lambda batch_emails, total_email_count, total_body_budget: app_service_analysis.build_emails_text(
            batch_emails,
            total_email_count,
            total_body_budget=app_service_analysis.MAX_PROMPT_BODY_CHARS
            if total_body_budget <= 0
            else total_body_budget,
        ),
        build_report_system_prompt_fn=app_llm_prompts.build_report_system_prompt,
        get_visual_context_prompt_rules_fn=app_llm_prompts.get_visual_context_prompt_rules,
        get_fixed_report_schema_prompt_fn=app_llm_prompts.get_fixed_report_schema_prompt,
        generate_with_llm_fn=generate_with_llm,
        build_report_response_format_fn=app_llm_prompts.build_report_response_format,
        parse_report_payload_json_fn=app_service_analysis.parse_report_payload_json,
        render_report_html_fn=app_service_analysis.render_report_html,
        analyze_batch_summary_with_llm_fn=analyze_batch_summary_with_llm,
        merge_batch_summaries_with_llm_fn=merge_batch_summaries_with_llm,
        logger=LOGGER,
    )


def html_to_text(html_content: str) -> str:
    text = str(html_content or "")
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|section|article|li|tr|table|thead|tbody|tfoot|h1|h2|h3|h4|h5|h6)>", "\n", text)
    text = re.sub(r"(?is)<style.*?</style>", "", text)
    text = re.sub(r"(?is)<script.*?</script>", "", text)
    text = re.sub(r"(?is)<[^>]+>", "", text)
    text = unescape(text)
    text = text.replace("\xa0", " ")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def write_text(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def render_report_markdown(group_key: str, html_content: str, metrics: Dict[str, Any]) -> str:
    spec = REPORT_SPECS[group_key]
    html_path = ROOT / f"{spec['stem']}.html"
    text_body = html_to_text(html_content)
    metrics_json = json.dumps(metrics, ensure_ascii=False, indent=2)
    return (
        f"# {spec['name']} 组报告：{spec['title']}\n\n"
        f"- HTML 版本：`{html_path.name}`\n\n"
        "## 运行摘要\n\n"
        "```json\n"
        f"{metrics_json}\n"
        "```\n\n"
        "## 报告正文（纯文本抽取）\n\n"
        f"{text_body}\n"
    )


def infer_stage(label: str) -> str:
    if label.startswith("图片轻分类"):
        return "lightweight_classification"
    if label.startswith("图片深分析"):
        return "deep_analysis"
    if label.endswith("文本降级"):
        return "report_text_fallback"
    return "report_generation"


@dataclass
class LLMCallRecord:
    label: str
    model: str
    duration_seconds: float
    success: bool
    used_multimodal: bool
    base_url: str = ""
    stage: str = ""


@dataclass
class LLMCallTracker:
    records: List[LLMCallRecord] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def wrap(self, original):
        def wrapped(
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
            start = time.perf_counter()
            success = False
            try:
                result = original(
                    api_config,
                    system_prompt,
                    user_prompt,
                    label=label,
                    max_retries=max_retries,
                    delay=delay,
                    backoff=backoff,
                    user_content_blocks=user_content_blocks,
                    response_format=response_format,
                )
                success = bool(result)
                return result
            finally:
                record = LLMCallRecord(
                    label=label,
                    model=str((api_config or {}).get("model", "") or ""),
                    duration_seconds=time.perf_counter() - start,
                    success=success,
                    used_multimodal=bool(user_content_blocks),
                    base_url=str((api_config or {}).get("base_url", "") or ""),
                    stage=infer_stage(label),
                )
                with self._lock:
                    self.records.append(record)

        return wrapped


@contextmanager
def track_llm_calls() -> LLMCallTracker:
    tracker = LLMCallTracker()
    original = app_service_analysis.call_llm_api_with_retries
    app_service_analysis.call_llm_api_with_retries = tracker.wrap(original)
    try:
        yield tracker
    finally:
        app_service_analysis.call_llm_api_with_retries = original


def summarize_llm_records(records: List[LLMCallRecord]) -> Dict[str, Any]:
    durations = [record.duration_seconds for record in records]
    stage_summary: Dict[str, Dict[str, Any]] = {}
    for stage in sorted({record.stage for record in records}):
        stage_records = [record for record in records if record.stage == stage]
        stage_summary[stage] = {
            "count": len(stage_records),
            "duration_seconds": round(sum(record.duration_seconds for record in stage_records), 3),
            "models": sorted({record.model for record in stage_records if record.model}),
            "multimodal_calls": sum(1 for record in stage_records if record.used_multimodal),
            "success_count": sum(1 for record in stage_records if record.success),
        }
    return {
        "num_llm_calls": len(records),
        "llm_runtime_seconds": round(sum(durations), 3),
        "avg_llm_call_seconds": round(statistics.mean(durations), 3) if durations else 0.0,
        "median_llm_call_seconds": round(statistics.median(durations), 3) if durations else 0.0,
        "models_used": sorted({record.model for record in records if record.model}),
        "stage_summary": stage_summary,
    }


def build_group_metrics(
    *,
    group_key: str,
    total_runtime_seconds: float,
    tracker: LLMCallTracker,
    image_summary: Dict[str, Any],
    pipeline_session: Optional[Dict[str, Any]] = None,
    image_settings: Optional[Dict[str, Any]] = None,
    prepared_emails: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    llm_summary = summarize_llm_records(tracker.records)
    metrics: Dict[str, Any] = {
        "group": REPORT_SPECS[group_key]["name"],
        "mode": REPORT_SPECS[group_key]["title"],
        "email_count": len(prepared_emails or []),
        "total_runtime_seconds": round(total_runtime_seconds, 3),
        "non_llm_runtime_seconds": round(max(0.0, total_runtime_seconds - llm_summary["llm_runtime_seconds"]), 3),
        **llm_summary,
        "image_summary": {
            "total_images": int(image_summary.get("total_images") or 0),
            "dropped_images": int(image_summary.get("dropped_images") or 0),
            "deprioritized_images": int(image_summary.get("deprioritized_images") or 0),
            "sent_images": int(image_summary.get("sent_images") or 0),
        },
    }

    if group_key == "a":
        metrics["actual_skipped_images"] = int(image_summary.get("total_images") or 0)

    if group_key == "b":
        email_stats = pipeline_session.get("email_stats_by_index") if pipeline_session else {}
        visual_status_distribution: Dict[str, int] = {}
        for email in prepared_emails or []:
            status = str(email.get("_visual_status") or "").strip() or "missing"
            visual_status_distribution[status] = visual_status_distribution.get(status, 0) + 1
        metrics.update(
            {
                "prescreen_candidate_images": sum(int((email_stats or {}).get(i, {}).get("candidate_images") or 0) for i in range(1, len(prepared_emails or []) + 1)),
                "lightweight_classification_count": len((pipeline_session or {}).get("classifications") or {}),
                "deep_analysis_count": len((pipeline_session or {}).get("deep_analysis") or {}),
                "visual_context_ready_emails": sum(
                    1 for email in (prepared_emails or []) if str(email.get("_visual_status") or "").strip() == "ready"
                ),
                "visual_status_distribution": visual_status_distribution,
                "classification_concurrency": int((image_settings or {}).get("classification_concurrency") or 1),
                "deep_analysis_concurrency": int((image_settings or {}).get("deep_analysis_concurrency") or 1),
                "lightweight_models": llm_summary["stage_summary"].get("lightweight_classification", {}).get("models", []),
                "deep_analysis_models": llm_summary["stage_summary"].get("deep_analysis", {}).get("models", []),
                "image_caps_disabled": {
                    "max_multimodal_images": None,
                    "max_deep_analysis_images": None,
                },
            }
        )

    if group_key == "c":
        report_stage = llm_summary["stage_summary"].get("report_generation", {})
        metrics.update(
            {
                "sent_images_to_main_model": int(image_summary.get("sent_images") or 0),
                "main_model_call_count": int(report_stage.get("count") or 0),
                "main_models": report_stage.get("models", []),
                "multimodal_fallback_to_text": "report_text_fallback" in llm_summary["stage_summary"],
                "image_caps_disabled": {
                    "max_multimodal_images": None,
                    "max_deep_analysis_images": None,
                },
            }
        )

    return metrics


def build_comparison_fallback(runtime_summary: Dict[str, Any], report_texts: Dict[str, str]) -> str:
    a_runtime = runtime_summary["groups"]["a"]["total_runtime_seconds"]
    lines = [
        "# A/B/C 实验对比",
        "",
        "## 运行结论",
        "",
        f"- A 组总耗时：{a_runtime} 秒",
        f"- B 组总耗时：{runtime_summary['groups']['b']['total_runtime_seconds']} 秒",
        f"- C 组总耗时：{runtime_summary['groups']['c']['total_runtime_seconds']} 秒",
        "",
        "## 报告摘录",
        "",
    ]
    for group_key in ("a", "b", "c"):
        spec = REPORT_SPECS[group_key]
        snippet = report_texts[group_key][:2000].strip()
        lines.append(f"### {spec['name']} 组：{spec['title']}")
        lines.append("")
        lines.append(snippet or "（无可用文本）")
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def generate_comparison_markdown(runtime_summary: Dict[str, Any], report_texts: Dict[str, str]) -> str:
    system_prompt = (
        "你是一个严谨的实验分析助手。请比较 A/B/C 三组研究报告，"
        "重点判断新增信息、细节颗粒度、结构变化、可归因性，以及耗时取舍。"
        "输出简体中文 Markdown。"
    )
    user_prompt = f"""请基于下面的三组报告文本和运行摘要，输出一份 Markdown 对比文档。

要求：
- 标题固定为 `# A/B/C 实验对比`
- 必须包含这四节：`## 总结`、`## 信息增量`、`## 结构与可控性`、`## 耗时`
- 明确回答：B 相对 A 是否有新增信息，C 相对 A 是否有新增信息，B 与 C 谁更值得保留
- 如果不能确认某个结论，请明确写“不确定”，不要脑补

运行摘要：
```json
{json.dumps(runtime_summary, ensure_ascii=False, indent=2)}
```

A 组报告：
{report_texts['a']}

B 组报告：
{report_texts['b']}

C 组报告：
{report_texts['c']}
"""
    try:
        return make_group_generate_with_llm(allow_raw_images=False)(
            system_prompt,
            user_prompt,
            emails=None,
            routing_state={"disabled_model_keys": set()},
            response_format=None,
        ).strip() + "\n"
    except Exception:
        LOGGER.warning("对比文档生成失败，回退到本地摘要。", exc_info=True)
        return build_comparison_fallback(runtime_summary, report_texts)


def save_group_outputs(group_key: str, html_content: str, metrics: Dict[str, Any]) -> str:
    spec = REPORT_SPECS[group_key]
    html_path = ROOT / f"{spec['stem']}.html"
    md_path = ROOT / f"{spec['stem']}.md"
    write_text(html_path, html_content)
    markdown_content = render_report_markdown(group_key, html_content, metrics)
    write_text(md_path, markdown_content)
    return markdown_content


def load_existing_runtime_summary() -> Dict[str, Any]:
    if not RUNTIME_SUMMARY_PATH.exists():
        return {}
    try:
        return json.loads(RUNTIME_SUMMARY_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def read_existing_report_text(group_key: str) -> str:
    html_path = ROOT / f"{REPORT_SPECS[group_key]['stem']}.html"
    if not html_path.exists():
        return ""
    return html_to_text(html_path.read_text(encoding="utf-8"))


def run_group_a(emails: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any], str]:
    prepared = prepare_text_only_emails(emails, suppress_raw_images=True)
    image_summary = collect_uncapped_images(emails)
    started_at = time.perf_counter()
    with track_llm_calls() as tracker:
        html_content = analyze_group_report(prepared, allow_raw_images=False)
    metrics = build_group_metrics(
        group_key="a",
        total_runtime_seconds=time.perf_counter() - started_at,
        tracker=tracker,
        image_summary=image_summary,
        prepared_emails=prepared,
    )
    markdown_content = save_group_outputs("a", html_content, metrics)
    return html_content, metrics, markdown_content


def run_group_b(emails: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any], str]:
    started_at = time.perf_counter()
    with track_llm_calls() as tracker:
        prepared, session, image_settings = prepare_pipeline_emails(emails)
        html_content = analyze_group_report(prepared, allow_raw_images=False)
    metrics = build_group_metrics(
        group_key="b",
        total_runtime_seconds=time.perf_counter() - started_at,
        tracker=tracker,
        image_summary=session.get("collected") or {},
        pipeline_session=session,
        image_settings=image_settings,
        prepared_emails=prepared,
    )
    markdown_content = save_group_outputs("b", html_content, metrics)
    return html_content, metrics, markdown_content


def run_group_c(emails: List[Dict[str, Any]]) -> Tuple[str, Dict[str, Any], str]:
    prepared = prepare_text_only_emails(emails, suppress_raw_images=False)
    image_summary = collect_uncapped_images(emails)
    started_at = time.perf_counter()
    with track_llm_calls() as tracker:
        html_content = analyze_group_report(prepared, allow_raw_images=True)
    metrics = build_group_metrics(
        group_key="c",
        total_runtime_seconds=time.perf_counter() - started_at,
        tracker=tracker,
        image_summary=image_summary,
        prepared_emails=prepared,
    )
    markdown_content = save_group_outputs("c", html_content, metrics)
    return html_content, metrics, markdown_content


def main() -> int:
    args = parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    config_path = ensure_runtime_config(args.config_path)
    configure_runtime(config_path)
    selected_groups = {
        item.strip().lower()
        for item in str(args.groups or "").split(",")
        if item.strip()
    }
    invalid_groups = selected_groups - {"a", "b", "c"}
    if invalid_groups:
        raise SystemExit(f"不支持的 groups 参数: {sorted(invalid_groups)}")

    sample_dirs = [Path(item).resolve() for item in (args.sample_dirs or DEFAULT_SAMPLE_DIRS)]
    emails = load_sample_emails(sample_dirs)
    if not emails:
        raise SystemExit("未发现任何 .msg 样本，实验无法运行。")

    existing_summary = load_existing_runtime_summary()
    report_texts = {
        "a": read_existing_report_text("a"),
        "b": read_existing_report_text("b"),
        "c": read_existing_report_text("c"),
    }
    group_metrics = dict(existing_summary.get("groups") or {})

    if "a" in selected_groups:
        a_html, a_metrics, _ = run_group_a(emails)
        report_texts["a"] = html_to_text(a_html)
        group_metrics["a"] = a_metrics
    if "b" in selected_groups:
        b_html, b_metrics, _ = run_group_b(emails)
        report_texts["b"] = html_to_text(b_html)
        group_metrics["b"] = b_metrics
    if "c" in selected_groups:
        c_html, c_metrics, _ = run_group_c(emails)
        report_texts["c"] = html_to_text(c_html)
        group_metrics["c"] = c_metrics

    missing_groups = [group_key for group_key in ("a", "b", "c") if group_key not in group_metrics]
    if missing_groups:
        raise SystemExit(f"缺少分组结果，无法生成 comparison/runtime summary: {missing_groups}")

    runtime_summary = {
        "experiment": "pipeline_abc",
        "worktree": str(ROOT),
        "branch": run_git_command(["git", "rev-parse", "--abbrev-ref", "HEAD"]),
        "head_commit": run_git_command(["git", "rev-parse", "HEAD"]),
        "baseline_commit": args.baseline_commit,
        "sample_dirs": [str(path) for path in sample_dirs],
        "sample_count": len(emails),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "config_path": str(config_path),
        "groups": group_metrics,
        "runtime_deltas_vs_a": {
            "b_minus_a_seconds": round(
                group_metrics["b"]["total_runtime_seconds"] - group_metrics["a"]["total_runtime_seconds"],
                3,
            ),
            "c_minus_a_seconds": round(
                group_metrics["c"]["total_runtime_seconds"] - group_metrics["a"]["total_runtime_seconds"],
                3,
            ),
        },
    }
    write_text(RUNTIME_SUMMARY_PATH, json.dumps(runtime_summary, ensure_ascii=False, indent=2) + "\n")

    comparison_markdown = generate_comparison_markdown(runtime_summary, report_texts)
    write_text(COMPARISON_PATH, comparison_markdown)

    print("Generated:")
    print(f"- {ROOT / 'experiment_report_a_text_only.md'}")
    print(f"- {ROOT / 'experiment_report_b_pipeline_with_images.md'}")
    print(f"- {ROOT / 'experiment_report_c_raw_images.md'}")
    print(f"- {COMPARISON_PATH}")
    print(f"- {RUNTIME_SUMMARY_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
