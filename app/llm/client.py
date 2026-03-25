from __future__ import annotations

import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests


def llm_should_bypass_proxy(api_config: Dict[str, Any]) -> bool:
    """按提供方选择网络策略。"""
    host = (urlparse(str((api_config or {}).get("base_url", "") or "")).hostname or "").lower()
    return host.endswith("moonshot.cn") or host.endswith("dashscope.aliyuncs.com")


def get_llm_http_session(
    api_config: Dict[str, Any],
    *,
    direct_session: requests.Session,
    proxy_session: requests.Session,
) -> requests.Session:
    """返回当前 LLM 请求应使用的 HTTP session。"""
    return direct_session if llm_should_bypass_proxy(api_config) else proxy_session


def model_supports_vision(api_config: Dict[str, Any]) -> bool:
    """判断当前模型是否支持多模态图片输入。"""
    if "supports_vision" in (api_config or {}):
        return bool(api_config.get("supports_vision"))

    model_name = str((api_config or {}).get("model", "")).lower()
    return any(token in model_name for token in ("thinking-preview", "vision", "vl", "gpt-4.1", "gpt-4o", "gpt-5"))


def is_openai_chat_api(api_config: Dict[str, Any]) -> bool:
    """判断当前配置是否指向 OpenAI 兼容官方入口。"""
    base_url = str((api_config or {}).get("base_url", "") or "").lower()
    return "api.openai.com" in base_url


def is_openai_gpt5_family(api_config: Dict[str, Any]) -> bool:
    """判断是否为 OpenAI GPT-5 系列模型。"""
    model_name = str((api_config or {}).get("model", "") or "").lower()
    return model_name.startswith("gpt-5")


def supports_native_response_format(api_config: Dict[str, Any]) -> bool:
    """仅在已知支持的 OpenAI 官方模型上启用原生 JSON Schema 输出。"""
    return is_openai_chat_api(api_config) and is_openai_gpt5_family(api_config)


def build_llm_chain(
    primary_cfg: Dict[str, Any],
    *,
    backup_configs: List[Dict[str, Any]],
) -> List[Tuple[str, str, Dict[str, Any]]]:
    labels = [
        ("primary", "主API"),
        ("backup1", "备用API"),
        ("backup2", "备用API2"),
        ("backup3", "备用API3"),
    ]
    chain = [(labels[0][0], labels[0][1], primary_cfg)]
    for idx, cfg in enumerate(backup_configs[:3], start=1):
        key, label = labels[idx]
        chain.append((key, label, cfg))
    return chain


def build_named_config_chain(
    primary_cfg: Dict[str, Any],
    *,
    primary_key: str,
    primary_label: str,
    backup_configs: List[Dict[str, Any]],
    backup_key_prefix: str,
    backup_label_prefix: str,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    chain = [(primary_key, primary_label, primary_cfg)]
    for idx, cfg in enumerate(backup_configs, start=1):
        chain.append((f"{backup_key_prefix}{idx}", f"{backup_label_prefix}{idx}", cfg))
    return chain


def get_ordered_llm_chain(
    primary_cfg: Dict[str, Any],
    *,
    backup_configs: List[Dict[str, Any]],
    routing_state: Optional[Dict[str, Any]] = None,
) -> List[Tuple[str, str, Dict[str, Any]]]:
    if not bool(primary_cfg.get("allow_fallbacks", False)):
        return [("primary", "主API", primary_cfg)]

    chain = build_llm_chain(primary_cfg, backup_configs=backup_configs)
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
    *,
    load_llm_config_fn: Callable[[], Dict[str, Any]],
    get_ordered_llm_chain_fn: Callable[[Dict[str, Any], Optional[Dict[str, Any]]], List[Tuple[str, str, Dict[str, Any]]]],
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
) -> Optional[Dict[str, Any]]:
    """挑选一个可用于图片轻分类/深分析的视觉模型配置。"""
    primary_cfg = load_llm_config_fn()
    for _, _, api_cfg in get_ordered_llm_chain_fn(primary_cfg, routing_state):
        if model_supports_vision_fn(api_cfg) and str(api_cfg.get("api_key", "") or "").strip():
            return api_cfg
    return None


def call_llm_api(
    api_config: Dict[str, Any],
    system_prompt: str,
    user_prompt: str,
    *,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    response_format: Optional[Dict[str, Any]] = None,
    max_completion_tokens: int,
    direct_session: requests.Session,
    proxy_session: requests.Session,
    get_llm_http_session_fn: Optional[Callable[..., requests.Session]] = None,
    logger: Any,
) -> Optional[str]:
    """调用兼容 chat/completions 的大模型 API。"""
    url = f"{api_config['base_url']}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_config['api_key']}",
    }

    if user_content_blocks:
        user_message_content: Any = [{"type": "text", "text": user_prompt}, *user_content_blocks]
    else:
        user_message_content = user_prompt

    payload = {
        "model": api_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content},
        ],
    }

    if response_format and supports_native_response_format(api_config):
        payload["response_format"] = response_format

    if is_openai_chat_api(api_config) and is_openai_gpt5_family(api_config):
        payload["max_completion_tokens"] = max_completion_tokens
        reasoning_effort = str(api_config.get("reasoning_effort", "") or "").strip()
        if reasoning_effort:
            payload["reasoning_effort"] = reasoning_effort
        else:
            payload["temperature"] = 1.0
    else:
        payload["temperature"] = 1.0
        payload["max_tokens"] = max_completion_tokens

    session_getter = get_llm_http_session_fn or get_llm_http_session
    llm_session = session_getter(
        api_config,
        direct_session=direct_session,
        proxy_session=proxy_session,
    )
    resp = llm_session.post(url, json=payload, headers=headers, timeout=300)
    try:
        resp.raise_for_status()
    except Exception:
        logger.warning(f"⚠️ API {api_config['base_url']} HTTP错误: {resp.status_code} {resp.text[:200]}")
        return None

    try:
        result = resp.json()
    except Exception:
        logger.warning(f"⚠️ API {api_config['base_url']} 返回非JSON: {resp.text[:200]}")
        return None

    if "choices" in result and len(result["choices"]) > 0:
        return result["choices"][0]["message"]["content"]

    logger.warning(f"⚠️ API {api_config['base_url']} 返回错误: {str(result)}")
    return None


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
    call_llm_api_fn: Callable[..., Optional[str]],
    logger: Any,
) -> Optional[str]:
    """对单个模型做有限重试，失败后交由上层切换备用模型。"""
    current_delay = delay
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"🤖 正在调用主/备大模型分析... ({label}: {api_config['base_url']})")
            html_content = call_llm_api_fn(
                api_config,
                system_prompt,
                user_prompt,
                user_content_blocks=user_content_blocks,
                response_format=response_format,
            )
            if html_content:
                if attempt > 0:
                    logger.info(f"✅ {label} 第 {attempt + 1} 次尝试成功")
                return html_content

            last_error = Exception("empty response")
            logger.warning(f"⚠️ {label} 返回空结果")
        except Exception as exc:
            last_error = exc
            logger.warning(f"⚠️ {label} 调用失败: {exc}")

        if attempt < max_retries:
            logger.warning(f"⚠️ {label} 将在 {current_delay:.1f} 秒后重试...")
            time.sleep(current_delay)
            current_delay *= backoff

    if last_error:
        logger.warning(f"⚠️ {label} 最终失败: {last_error}")
    return None


def call_llm_with_config_chain(
    chain: List[Tuple[str, str, Dict[str, Any]]],
    system_prompt: str,
    user_prompt: str,
    *,
    label: str,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
    model_supports_vision_fn: Callable[[Dict[str, Any]], bool],
    call_llm_api_with_retries_fn: Callable[..., Optional[str]],
    logger: Any,
) -> Optional[str]:
    for index, (_, _, api_cfg) in enumerate(chain):
        if not model_supports_vision_fn(api_cfg):
            continue
        if not str(api_cfg.get("api_key", "") or "").strip():
            continue
        result = call_llm_api_with_retries_fn(
            api_cfg,
            system_prompt,
            user_prompt,
            label=label if index == 0 else f"{label}-备用视觉模型{index}",
            max_retries=0,
            delay=2.0,
            backoff=2.0,
            user_content_blocks=user_content_blocks,
        )
        if result:
            return result
        if index < len(chain) - 1:
            logger.warning(
                "⚠️ %s 在视觉模型 %s 失败，切换到 %s",
                label,
                api_cfg.get("model", "(unknown)"),
                chain[index + 1][2].get("model", "(unknown)"),
            )
    return None


def generate_with_llm(
    system_prompt: str,
    user_prompt: str,
    *,
    emails: Optional[List[Dict[str, Any]]] = None,
    routing_state: Optional[Dict[str, Any]] = None,
    response_format: Optional[Dict[str, Any]] = None,
    load_llm_config_fn: Callable[[], Dict[str, Any]],
    get_ordered_llm_chain_fn: Callable[[Dict[str, Any], Optional[Dict[str, Any]]], List[Tuple[str, str, Dict[str, Any]]]],
    call_llm_api_with_retries_fn: Callable[..., Optional[str]],
    build_user_content_blocks_fn: Optional[Callable[[List[Dict[str, Any]], Dict[str, Any]], List[Dict[str, Any]]]] = None,
    logger: Any,
) -> str:
    """统一封装主/备模型的短重试与切换逻辑。"""
    llm_cfg = load_llm_config_fn()
    if routing_state is not None:
        routing_state.setdefault("disabled_model_keys", set())

    ordered_chain = get_ordered_llm_chain_fn(llm_cfg, routing_state)
    for model_key, label, api_cfg in ordered_chain:
        api_key = api_cfg.get("api_key", "")
        user_content_blocks = (
            build_user_content_blocks_fn(emails or [], api_cfg)
            if build_user_content_blocks_fn and emails
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

        result = call_llm_api_with_retries_fn(
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
            result = call_llm_api_with_retries_fn(
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
