from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from app import config as app_config
from app.llm import client as app_llm_client
from app.pipeline import email_preprocess as app_email_preprocess
from app.pipeline import multimodal_pipeline as app_multimodal_pipeline


def load_runtime_settings(config_file: str, logger) -> Dict[str, Any]:
    config = app_config.load_config(config_file, logger)
    return {
        "config": config,
        "image_settings": app_config.build_image_pipeline_settings(config),
        "llm_router_settings": app_config.build_llm_router_settings(config),
    }


def apply_legacy_runtime_globals(module_globals: Dict[str, Any], runtime_settings: Dict[str, Any]) -> None:
    image_settings = runtime_settings.get("image_settings") or {}
    llm_router_settings = runtime_settings.get("llm_router_settings") or {}

    module_globals["MAX_VISUAL_PIPELINE_IMAGES"] = int(image_settings["max_visual_pipeline_images"])
    module_globals["MAX_DEEP_ANALYSIS_IMAGES"] = (
        int(image_settings["max_deep_analysis_images"])
        if image_settings["max_deep_analysis_images"] is not None
        else None
    )
    module_globals["LIGHTWEIGHT_CLASSIFICATION_CONCURRENCY"] = int(image_settings["classification_concurrency"])
    module_globals["DEEP_ANALYSIS_CONCURRENCY"] = int(image_settings["deep_analysis_concurrency"])

    for legacy_name, key in (
        ("LLM_CONFIG", "primary"),
        ("LLM_BACKUP_CONFIG", "backup1"),
        ("LLM_BACKUP2_CONFIG", "backup2"),
        ("LLM_BACKUP3_CONFIG", "backup3"),
        ("VISUAL_LLM_CONFIG", "visual_llm"),
        ("VISUAL_LLM_BACKUP_CONFIG", "visual_llm_backup"),
        ("VISUAL_LLM_BACKUP2_CONFIG", "visual_llm_backup2"),
        ("VISUAL_FAST_LLM_CONFIG", "visual_fast_llm"),
        ("VISUAL_FAST_LLM_BACKUP_CONFIG", "visual_fast_llm_backup"),
    ):
        if legacy_name not in module_globals:
            continue
        target = module_globals[legacy_name]
        target.clear()
        if key in llm_router_settings:
            target.update(llm_router_settings[key])
        elif key in image_settings:
            target.update(image_settings[key])


def build_llm_chain(
    primary_cfg: Dict[str, Any],
    *,
    backup_configs: List[Dict[str, Any]],
) -> List[Tuple[str, str, Dict[str, Any]]]:
    return app_llm_client.build_llm_chain(primary_cfg, backup_configs=backup_configs)


def get_ordered_llm_chain(
    primary_cfg: Dict[str, Any],
    *,
    backup_configs: List[Dict[str, Any]],
    routing_state: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    return app_llm_client.get_ordered_llm_chain(
        primary_cfg,
        backup_configs=backup_configs,
        routing_state=routing_state,
    )


def build_email_visual_context_map_for_analysis(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]],
    load_config_fn: Callable[[], Dict[str, Any]],
    build_image_pipeline_settings_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    load_visual_fast_llm_config_fn: Callable[[], Dict[str, Any]],
    load_visual_llm_config_fn: Callable[[], Dict[str, Any]],
    model_supports_vision_fn,
    classify_images_fn,
    deep_analyze_images_fn,
    get_email_visual_context_fn,
    get_email_visual_contexts_fn,
    get_email_image_analysis_records_fn,
    get_email_image_analysis_records_map_fn,
    upsert_email_images_fn,
    upsert_email_images_batch_fn,
    update_image_classifications_fn,
    update_image_classifications_batch_fn,
    upsert_image_analysis_results_fn,
    upsert_image_analysis_results_batch_fn,
    save_email_visual_context_fn,
    save_email_visual_contexts_batch_fn,
    logger,
) -> Dict[int, Dict[str, Any]]:
    return app_multimodal_pipeline.build_email_visual_context_map_for_analysis_with_settings(
        emails,
        api_config=api_config,
        load_config_fn=load_config_fn,
        build_image_pipeline_settings_fn=build_image_pipeline_settings_fn,
        load_visual_fast_llm_config_fn=load_visual_fast_llm_config_fn,
        load_visual_llm_config_fn=load_visual_llm_config_fn,
        model_supports_vision_fn=model_supports_vision_fn,
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
        logger=logger,
    )


def prepare_emails_for_analysis(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]],
    sanitize_email_body_fn,
    build_email_visual_context_map_for_analysis_fn,
    render_email_visual_context_text_fn,
) -> List[Dict[str, Any]]:
    return app_email_preprocess.prepare_emails_for_analysis_with_visual_context(
        emails,
        api_config=api_config,
        sanitize_email_body_fn=sanitize_email_body_fn,
        build_email_visual_context_map_for_analysis_fn=build_email_visual_context_map_for_analysis_fn,
        render_email_visual_context_text_fn=render_email_visual_context_text_fn,
    )


def split_emails_for_analysis(
    emails: List[Dict[str, Any]],
    *,
    api_config: Optional[Dict[str, Any]],
    prepare_emails_for_analysis_with_visual_context_fn,
) -> List[List[Dict[str, Any]]]:
    return app_email_preprocess.split_emails_for_analysis_with_visual_context(
        emails,
        api_config=api_config,
        prepare_emails_for_analysis_with_visual_context_fn=prepare_emails_for_analysis_with_visual_context_fn,
    )


def generate_with_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    emails: Optional[List[Dict[str, Any]]],
    routing_state: Optional[Dict[str, Any]],
    response_format: Optional[Dict[str, Any]],
    load_llm_config_fn,
    get_ordered_llm_chain_fn,
    call_llm_api_with_retries_fn,
    build_user_content_blocks_fn,
    logger,
) -> str:
    return app_llm_client.generate_with_llm(
        system_prompt,
        user_prompt,
        emails=emails,
        routing_state=routing_state,
        response_format=response_format,
        load_llm_config_fn=load_llm_config_fn,
        get_ordered_llm_chain_fn=get_ordered_llm_chain_fn,
        call_llm_api_with_retries_fn=call_llm_api_with_retries_fn,
        build_user_content_blocks_fn=build_user_content_blocks_fn,
        logger=logger,
    )
