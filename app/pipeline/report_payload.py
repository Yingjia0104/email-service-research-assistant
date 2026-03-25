from __future__ import annotations

import re
from typing import Any, Dict, List, Optional


def repair_report_payload_json(
    raw_text: str,
    *,
    save_malformed_json_snapshot_fn,
    generate_with_llm_fn,
    load_json_dict_with_fallbacks_fn,
    logger,
) -> Dict[str, Any]:
    save_malformed_json_snapshot_fn(raw_text)
    repair_system_prompt = """你是一个严格的 JSON 修复器。

任务：
1. 你会收到一段“接近 JSON 但不合法”的文本
2. 在不发明新事实、不改变原意的前提下，把它修复成合法 JSON
3. 只输出一个合法 JSON 对象，不要解释，不要 Markdown
4. 保留原有字段结构，尤其是 executive_summary / core_events / local_news / peripheral_intelligence / actionable_ideas
"""

    repair_user_prompt = f"""请把下面这段不合法的 JSON 修复成合法 JSON，只输出 JSON：

```text
{raw_text}
```"""

    repaired = generate_with_llm_fn(
        repair_system_prompt,
        repair_user_prompt,
        emails=None,
        response_format={"type": "json_object"},
    )
    payload = load_json_dict_with_fallbacks_fn(repaired)
    logger.info("✅ 模型返回的损坏 JSON 已通过修复流程恢复")
    return payload


def normalize_string_list(items: Any, limit: int = 6) -> List[str]:
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list):
        return []

    result = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def derive_highlight_phrases(text: str, limit: int = 4) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []

    candidates = []
    patterns = [
        r'["“](.{2,40}?)["”]',
        r"(危机公关/注意力转移|生死存亡级冲突|估值折扣创造entry point|唯一全栈AI玩家|硬件护城河变薄|系统性流动性收缩|效率差距扩大是结构性问题)",
        r"([\u4e00-\u9fffA-Za-z0-9/+\-]{4,28}(?:受益者|创造entry point|护城河变薄|全栈AI玩家|流动性收缩|结构性问题|危机公关|注意力转移|冲突|折扣|错杀机会|战略转向|重新定价|趋势|逻辑))",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, raw))

    normalized = []
    seen = set()
    for candidate in candidates:
        phrase = str(candidate).strip(" \"“”'()[]")
        if len(phrase) < 2 or len(phrase) > 40:
            continue
        lowered = phrase.lower()
        if lowered in {"ai", "et", "pm", "am"}:
            continue
        if re.fullmatch(r"[$]?[0-9]+(?:\.[0-9]+)?(?:%|bps|x|亿|万|bn|b|m)?", lowered):
            continue
        if re.fullmatch(r"[A-Z]{2,5}", phrase):
            continue
        if re.fullmatch(r"[A-Z0-9/+\- ]{2,20}", phrase):
            continue
        if not re.search(r"[\u4e00-\u9fff]", phrase):
            continue
        if not re.search(r"(危机|冲突|受益者|折扣|机会|护城河|全栈|流动性|结构性|逻辑|趋势|转向|重估|错杀|信号|判断|定位|催化)", phrase):
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(phrase)
        if len(normalized) >= limit:
            break
    return normalized


def derive_stance_highlight_phrases(text: str, limit: int = 2) -> List[str]:
    raw = str(text or "").strip()
    if not raw:
        return []

    strong_markers = (
        "强烈看多",
        "强烈看空",
        "明确看多",
        "明确看空",
        "坚定看多",
        "坚定看空",
        "极度乐观",
        "极度悲观",
        "显著转向",
        "明显转向",
        "大幅上修",
        "大幅下修",
        "强烈推荐",
        "明确转向",
        "超配",
        "低配",
        "overweight",
        "underweight",
        "strong buy",
        "strong sell",
        "bullish",
        "bearish",
    )

    results = []
    lowered = raw.lower()
    for marker in strong_markers:
        if marker.lower() in lowered:
            results.append(marker if re.search(r"[\u4e00-\u9fff]", marker) else raw)
            break

    if not results:
        return []

    return normalize_string_list(results, limit=limit)


def merge_highlight_phrases(*sources: Any, limit: int = 6) -> List[str]:
    result = []
    seen = set()
    for source in sources:
        for item in normalize_string_list(source, limit=limit):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
            if len(result) >= limit:
                return result
    return result


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def build_priority_sort_key(item: Dict[str, Any]) -> tuple:
    raw_rank = item.get("priority_rank")
    rank = coerce_int(raw_rank, 9999 if raw_rank in (None, "") else 9999)
    coverage = coerce_int(item.get("coverage_count"), 0)
    score = coerce_float(item.get("global_score"), 0.0)
    return (-coverage, -score, rank)


def sort_by_priority(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=build_priority_sort_key)


def derive_executive_key_signals(
    normalized_coverage: List[Dict[str, Any]],
    normalized_local_news: List[Dict[str, Any]],
    normalized_cross_market_signals: List[Dict[str, Any]],
    model_key_signals: Any,
    limit: int = 5,
) -> List[str]:
    def add_signal(result: List[str], seen: set, text: str) -> None:
        text = str(text or "").strip()
        if not text:
            return
        key = re.sub(r"\s+", " ", text).strip().lower()
        if not key or key in seen:
            return
        seen.add(key)
        result.append(text)

    def is_standout(item: Dict[str, Any]) -> bool:
        coverage = coerce_int(item.get("coverage_count"), 0)
        score = coerce_float(item.get("global_score"), 0.0)
        rank = coerce_int(item.get("priority_rank"), 9999)
        return coverage >= 2 or score >= 8.0 or rank == 1

    results: List[str] = []
    seen = set()

    for item in normalized_coverage:
        if len(results) >= limit:
            break
        add_signal(results, seen, item.get("headline"))

    for item in normalized_local_news:
        if len(results) >= limit:
            break
        if is_standout(item):
            add_signal(results, seen, item.get("headline") or item.get("signal"))

    for item in normalized_cross_market_signals:
        if len(results) >= limit:
            break
        if is_standout(item):
            add_signal(results, seen, item.get("headline"))

    for item in normalize_string_list(model_key_signals, limit=limit):
        if len(results) >= limit:
            break
        add_signal(results, seen, item)

    return results[:limit]


def normalize_core_event_link_refs(value: Any, limit: int = 5) -> List[str]:
    refs = normalize_string_list(value, limit=limit)
    normalized = []
    seen = set()
    for ref in refs:
        ref = ref.strip()
        if not ref:
            continue
        key = ref.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(ref)
    return normalized


def build_core_event_lookup(core_events: List[Dict[str, Any]]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for item in core_events:
        core_event_id = item.get("core_event_id")
        if not core_event_id:
            continue
        lookup[str(core_event_id).strip().lower()] = core_event_id
        for candidate in [item.get("headline"), *(item.get("source_topics") or [])]:
            if not candidate:
                continue
            lookup[str(candidate).strip().lower()] = core_event_id
    return lookup


def resolve_linked_core_event_ids(
    explicit_refs: Any,
    source_topics: Any,
    core_event_lookup: Dict[str, str],
    limit: int = 5,
) -> List[str]:
    linked_ids = []
    seen = set()
    for ref in [
        *normalize_core_event_link_refs(explicit_refs, limit=limit),
        *normalize_string_list(source_topics, limit=limit),
    ]:
        key = str(ref).strip().lower()
        if not key:
            continue
        mapped = core_event_lookup.get(key)
        if not mapped:
            continue
        if mapped in seen:
            continue
        seen.add(mapped)
        linked_ids.append(mapped)
        if len(linked_ids) >= limit:
            break
    return linked_ids


def normalize_actionable_dedupe_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def dedupe_actionable_items(
    items: List[Dict[str, Any]],
    existing_keys: Optional[set] = None,
) -> List[Dict[str, Any]]:
    deduped = []
    seen = set(existing_keys or set())
    for item in items:
        key = normalize_actionable_dedupe_key(item.get("idea", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def normalize_actionable_item(item: Any, fallback_text_key: str = "idea") -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            "idea": text,
            "priority_rank": 9999,
            "coverage_count": 0,
            "global_score": 0.0,
            "source_topics": [],
            "linked_core_event_refs": [],
        }

    if not isinstance(item, dict):
        return None

    text = str(
        item.get("idea")
        or item.get("text")
        or item.get("title")
        or item.get(fallback_text_key)
        or ""
    ).strip()
    if not text:
        return None

    return {
        "idea": text,
        "priority_rank": coerce_int(item.get("priority_rank"), 9999),
        "coverage_count": coerce_int(item.get("coverage_count"), 0),
        "global_score": coerce_float(item.get("global_score"), 0.0),
        "source_topics": normalize_string_list(item.get("source_topics"), limit=5),
        "linked_core_event_refs": normalize_core_event_link_refs(
            item.get("linked_core_event_headlines") or item.get("linked_core_event_ids"),
            limit=5,
        ),
    }


def normalize_report_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    executive = payload.get("executive_summary") or payload.get("summary") or {}
    if not isinstance(executive, dict):
        executive = {}

    coverage_items = (
        payload.get("core_events")
        or payload.get("key_coverage")
        or payload.get("coverage")
        or payload.get("topics")
        or []
    )
    if not isinstance(coverage_items, list):
        coverage_items = []

    normalized_coverage = []
    for item in coverage_items:
        if not isinstance(item, dict):
            continue

        headline = str(item.get("headline") or item.get("title") or item.get("topic") or "").strip()
        if not headline:
            continue

        core_facts = normalize_string_list(item.get("core_facts") or item.get("facts"), limit=4)
        action_text = str(item.get("action") or item.get("investment_takeaway") or item.get("investment_implication") or "").strip()
        item_highlights = item.get("highlight_phrases") or item.get("highlights")

        normalized_coverage.append(
            {
                "headline": headline,
                "priority_rank": coerce_int(item.get("priority_rank"), 9999),
                "coverage_count": coerce_int(item.get("coverage_count"), 0),
                "global_score": coerce_float(item.get("global_score"), 0.0),
                "source_topics": normalize_string_list(item.get("source_topics") or item.get("email_ids"), limit=8),
                "core_facts": core_facts,
                "market_views": [
                    {
                        "source": str(row.get("source") or row.get("观点来源") or "").strip(),
                        "stance": str(row.get("stance") or row.get("立场") or "").strip(),
                        "thesis": str(row.get("thesis") or row.get("core_argument") or row.get("核心论点") or "").strip(),
                        "stance_highlight_phrases": merge_highlight_phrases(
                            row.get("stance_highlight_phrases"),
                            derive_stance_highlight_phrases(row.get("stance") or row.get("立场") or ""),
                            limit=2,
                        ),
                        "thesis_highlight_phrases": merge_highlight_phrases(
                            row.get("thesis_highlight_phrases"),
                            row.get("highlight_phrases") or row.get("highlights"),
                            derive_highlight_phrases(row.get("thesis") or row.get("core_argument") or row.get("核心论点") or ""),
                            limit=4,
                        ),
                    }
                    for row in (item.get("market_views") or item.get("view_table") or [])
                    if isinstance(row, dict)
                    and (
                        str(row.get("source") or row.get("观点来源") or "").strip()
                        or str(row.get("stance") or row.get("立场") or "").strip()
                        or str(row.get("thesis") or row.get("core_argument") or row.get("核心论点") or "").strip()
                    )
                ],
                "market_take": normalize_string_list(item.get("market_take") or item.get("market_takeaways"), limit=4),
                "importance": str(item.get("importance") or item.get("why_it_matters") or "").strip(),
                "action": action_text,
                "core_fact_highlight_phrases": merge_highlight_phrases(
                    item.get("core_fact_highlight_phrases"),
                    derive_highlight_phrases(" ".join(core_facts), limit=4),
                    limit=4,
                ),
                "action_highlight_phrases": merge_highlight_phrases(
                    item.get("action_highlight_phrases"),
                    item_highlights,
                    derive_highlight_phrases(headline, limit=2),
                    derive_highlight_phrases(action_text, limit=3),
                    limit=6,
                ),
                "highlight_phrases": merge_highlight_phrases(
                    item_highlights,
                    derive_highlight_phrases(headline, limit=2),
                    derive_highlight_phrases(action_text, limit=3),
                    limit=6,
                ),
                "attribution_note": str(item.get("attribution_note") or item.get("source_note") or "").strip(),
                "source_evidence": normalize_string_list(item.get("source_evidence"), limit=3),
            }
        )

    normalized_coverage = sort_by_priority(normalized_coverage)[:6]
    for index, item in enumerate(normalized_coverage, 1):
        item["core_event_id"] = f"core_event_{index}"

    core_event_lookup = build_core_event_lookup(normalized_coverage)

    local_news = payload.get("local_news") or []
    if not isinstance(local_news, list):
        local_news = []
    normalized_local_news = []
    for item in local_news:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or item.get("title") or "").strip()
        if not headline:
            continue
        signal_text = str(item.get("signal") or "").strip()
        importance_text = str(item.get("importance") or item.get("why_it_matters") or "").strip()
        action_text = str(item.get("action") or "").strip()
        item_highlights = item.get("highlight_phrases") or item.get("highlights")
        normalized_local_news.append(
            {
                "headline": headline,
                "priority_rank": coerce_int(item.get("priority_rank"), 9999),
                "coverage_count": coerce_int(item.get("coverage_count"), 0),
                "global_score": coerce_float(item.get("global_score"), 0.0),
                "signal": signal_text,
                "importance": importance_text,
                "action": action_text,
                "signal_highlight_phrases": merge_highlight_phrases(
                    item.get("signal_highlight_phrases"),
                    derive_highlight_phrases(signal_text, limit=3),
                    limit=4,
                ),
                "importance_highlight_phrases": merge_highlight_phrases(
                    item.get("importance_highlight_phrases"),
                    derive_highlight_phrases(importance_text, limit=3),
                    limit=4,
                ),
                "action_highlight_phrases": merge_highlight_phrases(
                    item.get("action_highlight_phrases"),
                    item_highlights,
                    derive_highlight_phrases(action_text, limit=3),
                    limit=4,
                ),
                "highlight_phrases": merge_highlight_phrases(
                    item_highlights,
                    derive_highlight_phrases(headline, limit=2),
                    derive_highlight_phrases(signal_text, limit=3),
                    derive_highlight_phrases(action_text, limit=3),
                    limit=5,
                ),
            }
        )
    normalized_local_news = normalized_local_news[:6]

    peripheral = payload.get("peripheral_intelligence") or {}
    if not isinstance(peripheral, dict):
        peripheral = {}

    mapped_events = peripheral.get("mapped_events") or payload.get("mapped_events") or []
    if not isinstance(mapped_events, list):
        mapped_events = []
    normalized_mapped_events = []
    for item in mapped_events:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event") or item.get("外围事件") or "").strip()
        related = str(item.get("related_company") or item.get("相关公司") or "").strip()
        mapping = str(item.get("mapping") or item.get("对Key Coverage的映射") or "").strip()
        if not (event or related or mapping):
            continue
        normalized_mapped_events.append({"event": event, "related_company": related, "mapping": mapping})

    cross_market_signals = peripheral.get("cross_market_signals") or payload.get("cross_market_signals") or []
    if not isinstance(cross_market_signals, list):
        cross_market_signals = []
    normalized_cross_market_signals = []
    for item in cross_market_signals:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or item.get("title") or "").strip()
        bullets = normalize_string_list(item.get("bullets") or item.get("signals") or item.get("insights"), limit=4)
        if not headline and not bullets:
            continue
        normalized_cross_market_signals.append(
            {
                "headline": headline,
                "priority_rank": coerce_int(item.get("priority_rank"), 9999),
                "coverage_count": coerce_int(item.get("coverage_count"), 0),
                "global_score": coerce_float(item.get("global_score"), 0.0),
                "bullets": bullets,
                "bullet_highlight_phrases": merge_highlight_phrases(
                    item.get("bullet_highlight_phrases"),
                    item.get("highlight_phrases") or item.get("highlights"),
                    derive_highlight_phrases(" ".join(bullets), limit=4),
                    limit=5,
                ),
            }
        )
    normalized_cross_market_signals = normalized_cross_market_signals[:5]

    actionable = payload.get("actionable_ideas") or {}
    if not isinstance(actionable, dict):
        actionable = {}

    catalysts = actionable.get("catalysts") or payload.get("catalysts_to_watch") or payload.get("catalysts") or []
    if isinstance(catalysts, dict):
        catalysts = catalysts.get("items") or []
    if not isinstance(catalysts, list):
        catalysts = []
    normalized_catalysts = []
    for item in catalysts:
        if not isinstance(item, dict):
            continue
        catalyst = str(item.get("catalyst") or item.get("title") or "").strip()
        timing = str(item.get("time") or item.get("timing") or "").strip()
        impact = str(item.get("impact") or item.get("impact_assets") or item.get("affected_assets") or "").strip()
        if not (catalyst or timing or impact):
            continue
        normalized_catalysts.append(
            {
                "catalyst": catalyst,
                "time": timing,
                "impact": impact,
                "priority_rank": coerce_int(item.get("priority_rank"), 9999),
                "coverage_count": coerce_int(item.get("coverage_count"), 0),
                "global_score": coerce_float(item.get("global_score"), 0.0),
                "source_topics": normalize_string_list(item.get("source_topics"), limit=5),
                "linked_core_event_refs": normalize_core_event_link_refs(
                    item.get("linked_core_event_headlines") or item.get("linked_core_event_ids"),
                    limit=5,
                ),
            }
        )

    normalized_catalysts = sort_by_priority(normalized_catalysts)[:8]
    for item in normalized_catalysts:
        item["linked_core_event_ids"] = resolve_linked_core_event_ids(
            item.pop("linked_core_event_refs", []),
            item.get("source_topics"),
            core_event_lookup,
        )

    short_term_raw = actionable.get("short_term") or actionable.get("near_term") or []
    medium_term_raw = actionable.get("medium_term") or actionable.get("mid_term") or []
    if not short_term_raw:
        short_term_raw = (payload.get("catalysts_to_watch") or {}).get("short_term") or []
    if not medium_term_raw:
        medium_term_raw = (payload.get("catalysts_to_watch") or {}).get("medium_term") or []

    normalized_short_term = []
    if isinstance(short_term_raw, list):
        for item in short_term_raw:
            normalized_item = normalize_actionable_item(item)
            if normalized_item:
                normalized_short_term.append(normalized_item)
    normalized_short_term = dedupe_actionable_items(sort_by_priority(normalized_short_term))[:5]
    for item in normalized_short_term:
        item["linked_core_event_ids"] = resolve_linked_core_event_ids(
            item.pop("linked_core_event_refs", []),
            item.get("source_topics"),
            core_event_lookup,
        )

    normalized_medium_term = []
    if isinstance(medium_term_raw, list):
        for item in medium_term_raw:
            normalized_item = normalize_actionable_item(item)
            if normalized_item:
                normalized_medium_term.append(normalized_item)
    normalized_medium_term = dedupe_actionable_items(
        sort_by_priority(normalized_medium_term),
        existing_keys={normalize_actionable_dedupe_key(item.get("idea", "")) for item in normalized_short_term},
    )[:5]
    for item in normalized_medium_term:
        item["linked_core_event_ids"] = resolve_linked_core_event_ids(
            item.pop("linked_core_event_refs", []),
            item.get("source_topics"),
            core_event_lookup,
        )

    market_background_items = normalize_string_list(
        executive.get("market_background") or executive.get("background"),
        limit=4,
    )
    derived_key_signals = derive_executive_key_signals(
        normalized_coverage,
        normalized_local_news,
        normalized_cross_market_signals,
        executive.get("key_signals") or executive.get("signals"),
        limit=5,
    )

    normalized = {
        "executive_summary": {
            "market_background": "；".join(market_background_items),
            "key_signals": derived_key_signals,
        },
        "core_events": normalized_coverage,
        "local_news": normalized_local_news,
        "peripheral_intelligence": {
            "mapped_events": normalized_mapped_events,
            "cross_market_signals": normalized_cross_market_signals,
        },
        "actionable_ideas": {
            "short_term": normalized_short_term,
            "medium_term": normalized_medium_term,
            "catalysts": normalized_catalysts,
            "bottom_line": str(actionable.get("bottom_line") or payload.get("bottom_line") or "").strip(),
        },
    }

    if not normalized["executive_summary"]["market_background"]:
        normalized["executive_summary"]["market_background"] = "当日邮件的共同背景尚不充分，建议结合盘前行情一并解读。"
    if not normalized["executive_summary"]["key_signals"]:
        normalized["executive_summary"]["key_signals"] = ["暂无足够强的共识信号，需结合后续白名单邮件继续观察。"]
    if not normalized["local_news"]:
        normalized["local_news"] = [
            {
                "headline": "暂无额外边缘信号",
                "signal": "目前白名单邮件中的高价值信息主要集中在核心事件。",
                "importance": "避免为了填充版面而加入低质量噪音。",
                "action": "后续如有补充邮件，再更新边缘信号。",
            }
        ]
    if not normalized["actionable_ideas"]["short_term"]:
        normalized["actionable_ideas"]["short_term"] = [
            normalize_actionable_item("关注盘前新增邮件、管理层发言和数据披露是否改变当前判断。")
        ]
    if not normalized["actionable_ideas"]["medium_term"]:
        normalized["actionable_ideas"]["medium_term"] = [
            normalize_actionable_item("关注未来 1-4 周内产业链验证、财报与产品节点带来的再定价机会。")
        ]
    if not normalized["actionable_ideas"]["catalysts"]:
        normalized["actionable_ideas"]["catalysts"] = [
            {
                "catalyst": "后续白名单邮件验证",
                "time": "",
                "impact": "相关主题与标的",
            }
        ]
    if not normalized["actionable_ideas"]["bottom_line"]:
        normalized["actionable_ideas"]["bottom_line"] = "市场仍处于信息快速演化阶段，建议优先跟踪共识最强、验证路径最清晰的主题。"

    return normalized


def parse_report_payload_json(
    text: str,
    *,
    load_json_dict_with_fallbacks_fn,
    repair_report_payload_json_fn,
    normalize_report_payload_fn,
    logger,
) -> Dict[str, Any]:
    try:
        payload = load_json_dict_with_fallbacks_fn(text)
    except Exception:
        logger.warning("⚠️ 最终晨报 JSON 解析失败，尝试修复")
        payload = repair_report_payload_json_fn(text)
    return normalize_report_payload_fn(payload)
