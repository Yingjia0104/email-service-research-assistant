from __future__ import annotations

import json
from typing import Any, Callable, Dict, List, Optional


def parse_batch_summary_json(
    text: str,
    *,
    load_json_dict_with_fallbacks_fn: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    """解析子批次结构化摘要。"""
    payload = load_json_dict_with_fallbacks_fn(text)
    topics = payload.get("topics")
    if not isinstance(topics, list):
        raise ValueError("topics missing from batch summary")

    normalized_topics = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        normalized_topics.append(
            {
                "title": topic.get("title", ""),
                "email_ids": topic.get("email_ids", []),
                "coverage_count": topic.get("coverage_count", 0),
                "merge_key": topic.get("merge_key", ""),
                "time_horizon": topic.get("time_horizon", ""),
                "target_slot": topic.get("target_slot", ""),
                "fact_subject": topic.get("fact_subject", ""),
                "opinion_subject": topic.get("opinion_subject", ""),
                "info_type": topic.get("info_type", ""),
                "core_facts": topic.get("core_facts", []),
                "market_takeaways": topic.get("market_takeaways", []),
                "tickers": topic.get("tickers", []),
                "source_evidence": topic.get("source_evidence", []),
            }
        )

    payload["topics"] = normalized_topics
    return payload


def analyze_batch_summary_with_llm(
    batch_emails: List[Dict[str, Any]],
    *,
    total_email_count: int,
    batch_index: int,
    batch_total: int,
    routing_state: Optional[Dict[str, Any]] = None,
    build_emails_text_fn: Callable[[List[Dict[str, Any]], int, int], str],
    build_report_system_prompt_fn: Callable[..., str],
    get_visual_context_prompt_rules_fn: Callable[[], str],
    get_batch_summary_stage_rules_fn: Callable[[], str],
    generate_with_llm_fn: Callable[..., str],
    build_batch_summary_response_format_fn: Callable[[], Dict[str, Any]],
    parse_batch_summary_json_fn: Callable[[str], Dict[str, Any]],
) -> Dict[str, Any]:
    emails_text = build_emails_text_fn(batch_emails, total_email_count, total_body_budget=0)
    batch_email_ids = ", ".join(str(email.get("_analysis_index")) for email in batch_emails)

    system_prompt = build_report_system_prompt_fn(
        f"""{get_visual_context_prompt_rules_fn()}

{get_batch_summary_stage_rules_fn()}

## JSON 结构
{{
  "batch_index": {batch_index},
  "batch_total": {batch_total},
  "email_ids": [{batch_email_ids}],
  "topics": [
    {{
      "title": "主题名称",
      "email_ids": [1, 2],
      "coverage_count": 2,
      "merge_key": "跨批次对齐键，尽量稳定，写成 `对象 | 事件/催化 | 方向`",
      "time_horizon": "短期 / 中期 / 长期 / 未知",
      "target_slot": "core_events / local_news / peripheral_intelligence / actionable_ideas",
      "fact_subject": "谁是客观事实的主体",
      "opinion_subject": "谁提出了观点；如果没有观点可填空字符串",
      "info_type": "事实 / 机构观点 / 外部引述 / 市场传闻",
      "core_facts": ["客观事实1", "客观事实2"],
      "market_takeaways": ["市场含义1", "市场含义2"],
      "tickers": ["NVDA", "MU"],
      "source_evidence": ["保留最关键的原文短句，注明真实主语"]
    }}
  ]
}}

## 补充要求
- 高频主题必须写明覆盖邮件编号和覆盖邮件数
- 每个主题必须明确区分“事实主体”和“观点主体”，不能把转述者默认当作观点提出者
- 如果邮件尾部是签名、免责声明、法律声明，不要纳入摘要
- 只保留对最终 HF Morning Brief 有帮助的信息
"""
    )

    user_prompt = f"""请把下面这批邮件整理成结构化中间摘要，供后续二次合并。

要求：
- 使用简体中文
- 只返回合法 JSON

当前批次: {batch_index}/{batch_total}
批次包含邮件编号: {batch_email_ids}

邮件内容：
{emails_text}
"""

    raw = generate_with_llm_fn(
        system_prompt,
        user_prompt,
        emails=batch_emails,
        routing_state=routing_state,
        response_format=build_batch_summary_response_format_fn(),
    )
    parsed = parse_batch_summary_json_fn(raw)
    parsed["batch_index"] = batch_index
    parsed["batch_total"] = batch_total
    return parsed


def merge_batch_summaries_with_llm(
    batch_summaries: List[Dict[str, Any]],
    *,
    total_email_count: int,
    source_emails: Optional[List[Dict[str, Any]]] = None,
    routing_state: Optional[Dict[str, Any]] = None,
    build_report_system_prompt_fn: Callable[..., str],
    get_merge_stage_rules_fn: Callable[[int], str],
    get_fixed_report_schema_prompt_fn: Callable[[], str],
    generate_with_llm_fn: Callable[..., str],
    build_report_response_format_fn: Callable[[], Dict[str, Any]],
    parse_report_payload_json_fn: Callable[[str], Dict[str, Any]],
    render_report_html_fn: Callable[[Dict[str, Any], Optional[List[Dict[str, Any]]]], str],
) -> str:
    summaries_text = json.dumps(batch_summaries, ensure_ascii=False, indent=2)

    system_prompt = build_report_system_prompt_fn(
        f"""{get_merge_stage_rules_fn(total_email_count)}

{get_fixed_report_schema_prompt_fn()}
"""
    )

    user_prompt = f"""请将以下结构化子批次摘要合并成最终中文晨报 JSON。

要求：
- 使用简体中文
- 只返回合法 JSON

子批次摘要：
{summaries_text}
"""

    raw = generate_with_llm_fn(
        system_prompt,
        user_prompt,
        routing_state=routing_state,
        response_format=build_report_response_format_fn(),
    )
    return render_report_html_fn(parse_report_payload_json_fn(raw), source_emails=source_emails)


def analyze_emails_with_llm(
    emails: List[Dict[str, Any]],
    *,
    choose_visual_analysis_api_config_fn: Callable[[Optional[Dict[str, Any]]], Optional[Dict[str, Any]]],
    split_emails_for_analysis_fn: Callable[[List[Dict[str, Any]], Optional[Dict[str, Any]]], List[List[Dict[str, Any]]]],
    build_emails_text_fn: Callable[[List[Dict[str, Any]], int, int], str],
    build_report_system_prompt_fn: Callable[..., str],
    get_visual_context_prompt_rules_fn: Callable[[], str],
    get_fixed_report_schema_prompt_fn: Callable[[], str],
    generate_with_llm_fn: Callable[..., str],
    build_report_response_format_fn: Callable[[], Dict[str, Any]],
    parse_report_payload_json_fn: Callable[[str], Dict[str, Any]],
    render_report_html_fn: Callable[[Dict[str, Any], Optional[List[Dict[str, Any]]]], str],
    analyze_batch_summary_with_llm_fn: Callable[..., Dict[str, Any]],
    merge_batch_summaries_with_llm_fn: Callable[..., str],
    logger: Any,
) -> Optional[str]:
    """调用主/备大模型分析邮件，生成 HF Morning Brief HTML。"""
    email_count = len(emails)
    routing_state = {"disabled_model_keys": set()}
    visual_api_config = choose_visual_analysis_api_config_fn(routing_state)
    email_batches = split_emails_for_analysis_fn(emails, api_config=visual_api_config)

    if email_count == 1 and len(email_batches) == 1:
        emails_text = build_emails_text_fn(email_batches[0], email_count, total_body_budget=0)
        system_prompt = build_report_system_prompt_fn(
            f"""{get_visual_context_prompt_rules_fn()}

## 视觉输入约束（重要！必须遵循）
- 你不会直接收到原始图片；图片信息只会以邮件正文里的 `[邮件级视觉上下文]` 文本块出现
- 只能使用这些已确认的视觉结论，不能假设还有未展示的图片信息
- 如果正文里出现 `visual_status: empty`，表示图片前置分析确认没有可用视觉证据，不要再补写任何图片结论
- 如果正文里出现 `visual_status: partial`，表示只拿到了部分视觉结果；你只能使用已给出的视觉证据，未覆盖部分一律不要脑补
- 不要把视觉 framing、传播截图、情绪信号写成独立核实后的硬事实

{get_fixed_report_schema_prompt_fn()}
"""
        )

        user_prompt = f"""请分析以下邮件，生成最终晨报 JSON。

要求：
- 使用简体中文输出所有字段内容
- 只返回合法 JSON，不要补充解释

邮件内容：
{emails_text}"""

        raw = generate_with_llm_fn(
            system_prompt,
            user_prompt,
            emails=email_batches[0],
            routing_state=routing_state,
            response_format=build_report_response_format_fn(),
        )
        html_content = render_report_html_fn(parse_report_payload_json_fn(raw), source_emails=emails)
        logger.info("✅ 大模型分析完成")
        return html_content

    logger.info(f"✂️ 上下文较长，拆分为 {len(email_batches)} 个批次进行分析后合并")
    batch_summaries = []
    for idx, batch in enumerate(email_batches, 1):
        logger.info(f"🧩 正在分析子批次 {idx}/{len(email_batches)}（{len(batch)} 封邮件）")
        batch_summaries.append(
            analyze_batch_summary_with_llm_fn(
                batch,
                total_email_count=email_count,
                batch_index=idx,
                batch_total=len(email_batches),
                routing_state=routing_state,
            )
        )

    html_content = merge_batch_summaries_with_llm_fn(
        batch_summaries,
        total_email_count=email_count,
        source_emails=emails,
        routing_state=routing_state,
    )
    logger.info("✅ 大模型分析完成")
    return html_content
