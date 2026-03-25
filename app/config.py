from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional, Tuple

import yaml


DEFAULT_VISUAL_LLM_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen3-vl-235b-a22b-thinking",
    "supports_vision": True,
}

DEFAULT_VISUAL_LLM_BACKUP_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-vl-max-latest",
    "supports_vision": True,
}

DEFAULT_VISUAL_LLM_BACKUP2_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-vl-plus-latest",
    "supports_vision": True,
}

DEFAULT_VISUAL_FAST_LLM_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-vl-max-latest",
    "supports_vision": True,
}

DEFAULT_VISUAL_FAST_LLM_BACKUP_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-vl-plus-latest",
    "supports_vision": True,
}

DEFAULT_LLM_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen3-max",
    "supports_vision": True,
}

DEFAULT_LLM_BACKUP_CONFIG = {
    "api_key": "",
    "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
    "model": "qwen-vl-max",
    "supports_vision": True,
}

DEFAULT_LLM_BACKUP2_CONFIG = {
    "api_key": "",
    "base_url": "https://api.moonshot.ai/v1",
    "model": "kimi-k2.5",
    "supports_vision": True,
}

DEFAULT_LLM_BACKUP3_CONFIG = {
    "api_key": "",
    "api_key_env": "OPENAI_API_KEY",
    "base_url": "https://api.openai.com/v1",
    "model": "gpt-5.4",
    "supports_vision": True,
    "reasoning_effort": "medium",
}

DEFAULT_IMAGE_PIPELINE_SETTINGS = {
    "max_visual_pipeline_images": 50,
    "max_deep_analysis_images": 15,
    "classification_concurrency": 2,
    "deep_analysis_concurrency": 2,
    "max_inline_visual_contexts": None,
    "max_supporting_visual_evidence": None,
    "stop_new_deep_analysis_before_daily_minutes": None,
}


def load_config(config_file: str, logger: Any) -> Dict[str, Any]:
    try:
        with open(config_file, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle) or {}
    except FileNotFoundError:
        logger.warning(f"配置文件不存在: {config_file}")
        return {}
    except Exception as exc:
        logger.error(f"加载配置失败: {exc}")
        return {}


def verify_api_key(api_key: str, *, load_config_fn: Callable[[], Dict[str, Any]]) -> bool:
    if not api_key:
        return False
    stored_key = load_config_fn().get("api_key", "")
    return api_key == stored_key and stored_key != ""


def _normalize_positive_int(value: Any) -> Optional[int]:
    if value in (None, "", False):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return None
    return normalized if normalized > 0 else None


def _normalize_optional_limit(value: Any, *, default: Optional[int]) -> Optional[int]:
    if value in (None, "", False):
        return None
    try:
        normalized = int(value)
    except (TypeError, ValueError):
        return default
    if normalized <= 0:
        return None
    return normalized


def _supports_vision_from_model_name(model_name: str) -> bool:
    normalized = str(model_name or "").lower()
    return any(token in normalized for token in ("thinking-preview", "vision", "vl", "gpt-4.1", "gpt-4o", "gpt-5"))


def _resolve_api_key(section_cfg: Dict[str, Any], default_cfg: Optional[Dict[str, Any]] = None) -> Tuple[str, str]:
    default_cfg = default_cfg or {}
    api_key_env = str(section_cfg.get("api_key_env", default_cfg.get("api_key_env", "")) or "").strip()
    api_key = str(section_cfg.get("api_key", "") or "").strip()
    if not api_key and api_key_env:
        api_key = str(os.getenv(api_key_env, "") or "").strip()
    if not api_key:
        api_key = str(default_cfg.get("api_key", "") or "").strip()
    return api_key, api_key_env


def _populate_model_config(
    target_cfg: Dict[str, Any],
    section_cfg: Dict[str, Any],
    *,
    default_cfg: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    default_cfg = default_cfg or {}
    api_key, api_key_env = _resolve_api_key(section_cfg, default_cfg=default_cfg)

    target_cfg["api_key"] = api_key
    if api_key_env:
        target_cfg["api_key_env"] = api_key_env
    else:
        target_cfg.pop("api_key_env", None)

    target_cfg["base_url"] = section_cfg.get("base_url", default_cfg.get("base_url", target_cfg.get("base_url", "")))
    target_cfg["model"] = section_cfg.get("model", default_cfg.get("model", target_cfg.get("model", "")))

    reasoning_effort = str(section_cfg.get("reasoning_effort", default_cfg.get("reasoning_effort", "")) or "").strip()
    if reasoning_effort:
        target_cfg["reasoning_effort"] = reasoning_effort
    else:
        target_cfg.pop("reasoning_effort", None)

    if "supports_vision" in section_cfg:
        target_cfg["supports_vision"] = bool(section_cfg.get("supports_vision"))
    else:
        default_supports_vision = default_cfg.get(
            "supports_vision",
            _supports_vision_from_model_name(target_cfg.get("model", "")),
        )
        target_cfg["supports_vision"] = bool(default_supports_vision)

    return target_cfg


def build_image_pipeline_settings(config: Dict[str, Any]) -> Dict[str, Any]:
    config = config or {}
    llm_cfg = config.get("llm") or {}

    primary_text_defaults = {
        "api_key": "",
        "api_key_env": "",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen3-max",
    }
    primary_api_key, primary_api_key_env = _resolve_api_key(llm_cfg, default_cfg=primary_text_defaults)

    visual_llm = _populate_model_config(
        DEFAULT_VISUAL_LLM_CONFIG.copy(),
        config.get("visual_llm") or {},
        default_cfg={
            **DEFAULT_VISUAL_LLM_CONFIG,
            "api_key": primary_api_key,
            "api_key_env": primary_api_key_env,
        },
    )
    visual_llm_backup = _populate_model_config(
        DEFAULT_VISUAL_LLM_BACKUP_CONFIG.copy(),
        config.get("visual_llm_backup") or {},
        default_cfg={
            **DEFAULT_VISUAL_LLM_BACKUP_CONFIG,
            "api_key": visual_llm.get("api_key", ""),
            "api_key_env": visual_llm.get("api_key_env", ""),
        },
    )
    visual_llm_backup2 = _populate_model_config(
        DEFAULT_VISUAL_LLM_BACKUP2_CONFIG.copy(),
        config.get("visual_llm_backup2") or {},
        default_cfg={
            **DEFAULT_VISUAL_LLM_BACKUP2_CONFIG,
            "api_key": visual_llm.get("api_key", ""),
            "api_key_env": visual_llm.get("api_key_env", ""),
        },
    )
    visual_fast_llm = _populate_model_config(
        DEFAULT_VISUAL_FAST_LLM_CONFIG.copy(),
        config.get("visual_llm_fast") or config.get("visual_llm_classifier") or {},
        default_cfg={
            **DEFAULT_VISUAL_FAST_LLM_CONFIG,
            "api_key": primary_api_key,
            "api_key_env": primary_api_key_env,
        },
    )
    visual_fast_llm_backup = _populate_model_config(
        DEFAULT_VISUAL_FAST_LLM_BACKUP_CONFIG.copy(),
        config.get("visual_llm_fast_backup") or config.get("visual_llm_classifier_backup") or {},
        default_cfg={
            **DEFAULT_VISUAL_FAST_LLM_BACKUP_CONFIG,
            "api_key": visual_fast_llm.get("api_key", ""),
            "api_key_env": visual_fast_llm.get("api_key_env", ""),
        },
    )

    multimodal_cfg = config.get("multimodal") or {}
    settings = dict(DEFAULT_IMAGE_PIPELINE_SETTINGS)
    settings["max_visual_pipeline_images"] = _normalize_positive_int(multimodal_cfg.get("max_images")) or settings["max_visual_pipeline_images"]
    if "max_deep_analysis_images" in multimodal_cfg:
        settings["max_deep_analysis_images"] = _normalize_optional_limit(
            multimodal_cfg.get("max_deep_analysis_images"),
            default=settings["max_deep_analysis_images"],
        )
    settings["classification_concurrency"] = _normalize_positive_int(multimodal_cfg.get("classification_concurrency")) or settings["classification_concurrency"]
    settings["deep_analysis_concurrency"] = _normalize_positive_int(multimodal_cfg.get("deep_analysis_concurrency")) or settings["deep_analysis_concurrency"]
    settings["max_inline_visual_contexts"] = _normalize_positive_int(multimodal_cfg.get("max_inline_visual_contexts"))
    settings["max_supporting_visual_evidence"] = _normalize_positive_int(multimodal_cfg.get("max_supporting_visual_evidence"))
    settings["stop_new_deep_analysis_before_daily_minutes"] = _normalize_positive_int(
        multimodal_cfg.get("stop_new_deep_analysis_before_daily_minutes")
    )

    settings["visual_llm"] = visual_llm
    settings["visual_llm_backup"] = visual_llm_backup
    settings["visual_llm_backup2"] = visual_llm_backup2
    settings["visual_fast_llm"] = visual_fast_llm
    settings["visual_fast_llm_backup"] = visual_fast_llm_backup
    return settings


def build_llm_router_settings(config: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    config = config or {}

    primary = _populate_model_config(
        DEFAULT_LLM_CONFIG.copy(),
        config.get("llm") or {},
        default_cfg=DEFAULT_LLM_CONFIG,
    )
    backup1 = _populate_model_config(
        DEFAULT_LLM_BACKUP_CONFIG.copy(),
        config.get("llm_backup") or {},
        default_cfg=DEFAULT_LLM_BACKUP_CONFIG,
    )
    backup2 = _populate_model_config(
        DEFAULT_LLM_BACKUP2_CONFIG.copy(),
        config.get("llm_backup2") or {},
        default_cfg=DEFAULT_LLM_BACKUP2_CONFIG,
    )
    backup3 = _populate_model_config(
        DEFAULT_LLM_BACKUP3_CONFIG.copy(),
        config.get("llm_backup3") or {},
        default_cfg=DEFAULT_LLM_BACKUP3_CONFIG,
    )

    return {
        "primary": primary,
        "backup1": backup1,
        "backup2": backup2,
        "backup3": backup3,
    }


def load_llm_router_settings(config_file: str, logger: Any) -> Dict[str, Dict[str, Any]]:
    return build_llm_router_settings(load_config(config_file, logger))


def load_image_pipeline_settings(config_file: str, logger: Any) -> Dict[str, Any]:
    return build_image_pipeline_settings(load_config(config_file, logger))


def load_visual_llm_config(config_file: str, logger: Any) -> Dict[str, Any]:
    return dict(load_image_pipeline_settings(config_file, logger).get("visual_llm") or {})


def load_visual_fast_llm_config(config_file: str, logger: Any) -> Dict[str, Any]:
    return dict(load_image_pipeline_settings(config_file, logger).get("visual_fast_llm") or {})
