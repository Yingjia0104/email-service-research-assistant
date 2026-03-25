from __future__ import annotations

import glob
import os
import re
from html import escape
from typing import Any, Callable, Dict, Optional


STANDALONE_SUBHEADINGS = {
    "核心事实",
    "市场怎么看",
    "供应链与竞争方观点",
    "投资影响",
    "投资启示",
    "长期（1-3月）",
}

SECTION_SUBHEADINGS = {
    "Catalysts to Watch",
}

TIME_HORIZON_SUBHEADINGS = {
    "短期（1-5天）",
    "中期（1-4周）",
}

SEMANTIC_CALLOUT_RULES = {
    "投资启示": "action-box",
    "投资影响": "action-box",
    "Action": "action-box",
    "为什么重要": "signal-box",
    "信号": "signal-box",
    "原则": "principle-box",
    "规则": "rule-box",
    "底线": "redline-box",
    "提醒": "reminder-box",
}

FIXED_DETAIL_LABELS = {"投资启示", "信号", "为什么重要", "Action"}

SOURCE_LABEL_PATTERNS = [
    ("MS", [r"\bmorgan stanley\b", r"\bms\b", r"摩根士丹利"]),
    ("JPM", [r"\bj\.?\s?p\.?\s?morgan\b", r"\bjpm\b", r"摩根大通"]),
    ("GS", [r"\bgoldman sachs\b", r"\bgs\b", r"高盛"]),
    ("BofA", [r"\bbank of america\b", r"\bbofa\b", r"美银"]),
    ("UBS", [r"\bubs\b", r"瑞银"]),
    ("Citi", [r"\bciti\b", r"\bcitigroup\b", r"花旗"]),
    ("Barclays", [r"\bbarclays\b", r"巴克莱"]),
    ("Bernstein", [r"\bbernstein\b"]),
]

REPORT_OPTIMIZATION_CATEGORIES = {
    "内容筛选": [
        "普通功能升级、版本小更新、一般性运营通知默认降权，不挤占核心版面",
        "核心事实只保留最硬的信息，避免长句和解释性废话",
        "图片内容要与文本一起理解，但不单独占用杂乱版面",
    ],
    "归因纪律": [
        "发件机构不等于观点主体，外部引述必须保留真实主语",
        "带 says / according to / reports suggest / rumored 的内容默认不是核心事实",
        "来源展示优先使用正文和主题里可识别的真实机构标签，如 MS、JPM",
    ],
    "结构模板": [
        "Executive Summary 固定拆为 市场大背景 和 关键信号",
        "核心事件与市场观点 固定按 事件标题 / 核心事实 / 市场怎么看 / 投资启示 展开",
        "Actionable Ideas 固定包含 短期(1-5天) / 中期(1-4周) / Catalysts to Watch / Bottom Line",
        "Actionable Ideas 需要站在全局上二次提炼最有行动价值的交易想法，而不是承接剩余信息",
    ],
    "格式底线": [
        "阅读时间和来源 metadata 固定显示在标题下方，且只出现一次",
        "highlight 不进入标题，只能留在正文",
        "相同语义标签必须映射到相同结构，不允许同一模块今天是表格、明天是散段落",
    ],
}

FIXED_REPORT_TEMPLATE = {
    "executive_summary": ["市场大背景", "关键信号"],
    "core_events_h2": "Key Coverage | 核心事件与市场观点",
    "core_event_labels": ["核心事实", "市场怎么看", "投资启示"],
    "local_news_h2": "Local News | 容易被忽略的信号",
    "local_news_labels": ["信号", "为什么重要", "Action"],
    "peripheral_h2": "Peripheral Intelligence | 外围信息/类比映射",
    "peripheral_subsections": ["非核心公司事件 → 核心洞察", "跨市场信号"],
    "actionable_h2": "Actionable Ideas",
    "actionable_labels": ["短期(1-5天)", "中期(1-4周)", "Catalysts to Watch", "Bottom Line"],
}


def validate_html(html_content: str) -> tuple[bool, str]:
    """验证 HTML 内容完整性。"""
    if not html_content or len(html_content.strip()) < 100:
        return False, "内容过短，可能不完整"

    required_tags = ["<html", "<head", "<body", "</html>"]
    for tag in required_tags:
        if tag.lower() not in html_content.lower():
            return False, f"缺少必需标签: {tag}"

    if html_content.count("<html") != html_content.count("</html>"):
        return False, "html标签未正确闭合"

    return True, ""


def estimate_read_minutes_from_html(body_content: str) -> int:
    """根据正文长度粗略估算阅读时间。"""
    text = re.sub(r"<[^>]+>", " ", body_content or "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return 1
    return max(1, min(8, round(len(text) / 320)))


def escape_with_highlights(text: str, highlights: Optional[list[str]] = None) -> str:
    """先做 HTML 转义，再把结构化 highlight 短语渲染成统一样式。"""
    escaped_text = escape(str(text or ""))
    phrases: list[str] = []
    seen = set()
    for item in highlights or []:
        phrase = str(item or "").strip()
        if not phrase:
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        phrases.append(phrase)
        if len(phrases) >= 8:
            break

    if not phrases:
        return escaped_text

    placeholders = {}
    replaced_text = escaped_text
    for idx, phrase in enumerate(sorted(phrases, key=len, reverse=True), 1):
        escaped_phrase = escape(phrase)
        token = f"__HIGHLIGHT_{idx}__"
        if escaped_phrase and escaped_phrase in replaced_text:
            replaced_text = replaced_text.replace(escaped_phrase, token)
            placeholders[token] = f'<span class="highlight">{escaped_phrase}</span>'

    for token, html in placeholders.items():
        replaced_text = replaced_text.replace(token, html)
    return replaced_text


def extract_recognized_source_label_from_email(
    email: Dict[str, Any],
    *,
    source_label_patterns: list[tuple[str, list[str]]],
) -> str:
    """优先从邮件主题/正文中提取更真实的机构来源标签。"""
    prioritized_fields = [
        str(email.get("subject") or ""),
        str(email.get("from_name") or ""),
        str(email.get("body") or "")[:2000],
    ]

    for field_text in prioritized_fields:
        if not field_text:
            continue
        for label, patterns in source_label_patterns:
            for pattern in patterns:
                if re.search(pattern, field_text, flags=re.IGNORECASE):
                    return label

    return ""


def build_report_meta_html(
    source_emails: Optional[list[Dict[str, Any]]],
    body_content: str,
    *,
    extract_source_label_fn: Callable[[Dict[str, Any]], str],
) -> str:
    """在标题下方展示阅读时长和来源。"""
    read_minutes = estimate_read_minutes_from_html(body_content)
    labels = []
    seen = set()
    for email in source_emails or []:
        label = extract_source_label_fn(email)
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
    source_text = " + ".join(labels[:4]) if labels else "Whitelisted source emails"
    return f'<div class="meta">Prepared by: AI Research Assistant | Source: {escape(source_text)} | Reading time: {read_minutes} mins</div>'


def strip_emojis_from_html_content(body_content: str, *, emoji_pattern: Any) -> str:
    """本地禁用 emoji，避免视觉风格漂移和模型偶发装饰性输出。"""
    if not body_content:
        return body_content
    return emoji_pattern.sub("", body_content)


def normalize_legacy_label_boxes(body_content: str, *, supported_labels: set[str]) -> str:
    """把旧版 action-box/signal-box 渲染收敛成当前固定标签结构。"""
    if not body_content:
        return body_content

    pattern = (
        r'<div\s+class="(?:action-box|signal-box)">\s*'
        r'<div\s+class="callout-title">\s*(.*?)\s*</div>\s*'
        r'((?:<p\b[^>]*>.*?</p>\s*|<ul\b[^>]*>.*?</ul>\s*|<ol\b[^>]*>.*?</ol>\s*|'
        r'<table\b[^>]*>.*?</table>\s*|<blockquote\b[^>]*>.*?</blockquote>\s*)+)'
        r'</div>'
    )

    def replace_box(match: re.Match[str]) -> str:
        label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        content = (match.group(2) or "").strip()
        if label not in supported_labels or not content:
            return match.group(0)
        return f'<h4 class="detail-label">{label}</h4>\n{content}'

    previous = None
    normalized = body_content
    while previous != normalized:
        previous = normalized
        normalized = re.sub(
            pattern,
            replace_box,
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return normalized


def normalize_subsection_headings(body_content: str, *, section_subheadings: set[str]) -> str:
    """只把白名单里的真正 subsection 提升标题。"""
    if not body_content:
        return body_content

    def replace_heading(match: re.Match[str]) -> str:
        raw_heading = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if not raw_heading or len(raw_heading) > 80:
            return match.group(0)

        normalized = raw_heading.rstrip(":：").strip()
        if not normalized or normalized not in section_subheadings:
            return match.group(0)
        return f"<h2>{normalized}</h2>"

    return re.sub(
        r"<p>\s*<strong>(.*?)</strong>\s*</p>",
        replace_heading,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def strip_highlight_inside_headings(body_content: str) -> str:
    """标题里不保留 highlight。"""
    if not body_content:
        return body_content

    def replace_heading(match: re.Match[str]) -> str:
        tag = match.group(1)
        attrs = match.group(2) or ""
        inner = match.group(3)
        cleaned_inner = re.sub(
            r'<span\s+class="highlight">(.*?)</span>',
            r"\1",
            inner,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return f"<{tag}{attrs}>{cleaned_inner}</{tag}>"

    return re.sub(
        r"<(h[1-4])([^>]*)>(.*?)</\1>",
        replace_heading,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def normalize_standalone_labels(
    body_content: str,
    *,
    section_subheadings: set[str],
    time_horizon_subheadings: set[str],
    standalone_subheadings: set[str],
    fixed_detail_labels: set[str],
) -> str:
    """把常见的独立粗体标签提升成稳定的小节标题。"""
    if not body_content:
        return body_content

    def replace_label(match: re.Match[str]) -> str:
        raw_label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        normalized = raw_label.rstrip(":：").strip()
        if normalized in section_subheadings:
            return f"<h2>{normalized}</h2>"
        if normalized in time_horizon_subheadings:
            return f'<h3 class="horizon-heading">{normalized}</h3>'
        if normalized in standalone_subheadings or normalized in fixed_detail_labels:
            return f"<h4>{normalized}</h4>"
        return match.group(0)

    return re.sub(
        r"<p>\s*<strong>(.*?)</strong>\s*</p>",
        replace_label,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def normalize_existing_heading_tags(
    body_content: str,
    *,
    section_subheadings: set[str],
    time_horizon_subheadings: set[str],
    standalone_subheadings: set[str],
    semantic_callout_rules: Dict[str, str],
) -> str:
    """把模型直接生成的 h3/h4 标签也收敛到硬规则语义。"""
    if not body_content:
        return body_content

    def replace_heading(match: re.Match[str]) -> str:
        tag = match.group(1).lower()
        raw_label = re.sub(r"<[^>]+>", "", match.group(3)).strip()
        normalized = raw_label.rstrip(":：").strip()

        if normalized in section_subheadings:
            return f"<h2>{normalized}</h2>"
        if normalized in time_horizon_subheadings:
            return f'<h3 class="horizon-heading">{normalized}</h3>'
        if normalized in standalone_subheadings or normalized in semantic_callout_rules:
            return f"<h4>{normalized}</h4>"
        if tag == "h3" and normalized != raw_label:
            return f"<h3>{normalized}</h3>"
        return match.group(0)

    return re.sub(
        r"<(h[3-4])([^>]*)>(.*?)</\1>",
        replace_heading,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def build_semantic_callout(
    label: str,
    content_html: str,
    *,
    semantic_callout_rules: Dict[str, str],
) -> Optional[str]:
    """按硬规则把特定标签渲染成固定样式的提示框。"""
    css_class = semantic_callout_rules.get(label)
    if not css_class:
        return None

    content = (content_html or "").strip()
    if not content:
        return None

    if not re.match(r"^<(p|ul|ol|table|div|blockquote)\b", content, flags=re.IGNORECASE):
        content = f"<p>{content}</p>"

    return f'<div class="{css_class}"><div class="callout-title">{label}</div>{content}</div>'


def normalize_semantic_callout_blocks(
    body_content: str,
    *,
    semantic_callout_rules: Dict[str, str],
    fixed_detail_labels: set[str],
    build_semantic_callout_fn: Callable[[str, str], Optional[str]],
) -> str:
    """把独立标签标题 + 紧随内容，收敛成固定样式的提示框。"""
    if not body_content:
        return body_content

    labels_pattern = "|".join(re.escape(label) for label in sorted(semantic_callout_rules, key=len, reverse=True))
    block_pattern = (
        rf"<h4>\s*({labels_pattern})\s*</h4>\s*"
        rf"((?:<p\b[^>]*>.*?</p>|<ul\b[^>]*>.*?</ul>|<ol\b[^>]*>.*?</ol>|<table\b[^>]*>.*?</table>|<div\b[^>]*>.*?</div>))"
    )

    def replace_block(match: re.Match[str]) -> str:
        label = match.group(1).strip()
        content = match.group(2).strip()
        if label in fixed_detail_labels:
            return f'<h4 class="detail-label">{label}</h4>\n{content}'
        return build_semantic_callout_fn(label, content) or match.group(0)

    previous = None
    normalized = body_content
    while previous != normalized:
        previous = normalized
        normalized = re.sub(
            block_pattern,
            replace_block,
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return normalized


def normalize_inline_labeled_paragraphs(
    body_content: str,
    *,
    fixed_detail_labels: set[str],
    build_semantic_callout_fn: Callable[[str, str], Optional[str]],
) -> str:
    """规范行内标签段落。"""
    if not body_content:
        return body_content

    def replace_inline(match: re.Match[str]) -> str:
        raw_label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        label = raw_label.rstrip(":：").strip()
        content = match.group(2).strip()

        if not content:
            return match.group(0)

        if label in fixed_detail_labels:
            return f'<h4 class="detail-label">{label}</h4>\n<p class="detail-copy">{content}</p>'

        semantic_callout = build_semantic_callout_fn(label, content)
        if semantic_callout:
            return semantic_callout

        return f'<p class="label-line"><strong>{label}：</strong>{content}</p>'

    return re.sub(
        r"<p>\s*<strong>([^<]{1,40})</strong>\s*[:：]?\s*(.*?)</p>",
        replace_inline,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def normalize_report_body_content(
    body_content: str,
    *,
    normalize_legacy_label_boxes_fn: Callable[[str], str],
    normalize_subsection_headings_fn: Callable[[str], str],
    normalize_standalone_labels_fn: Callable[[str], str],
    normalize_existing_heading_tags_fn: Callable[[str], str],
    normalize_semantic_callout_blocks_fn: Callable[[str], str],
    normalize_inline_labeled_paragraphs_fn: Callable[[str], str],
    strip_emojis_from_html_content_fn: Callable[[str], str],
    strip_highlight_inside_headings_fn: Callable[[str], str],
) -> str:
    """报告正文规范化单入口。"""
    normalized = body_content or ""
    normalized = re.sub(r'<(?:p|div)\s+class="meta">.*?</(?:p|div)>', "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r"<p>\s*阅读时间[^<]*</p>", "", normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = normalize_legacy_label_boxes_fn(normalized)
    normalized = normalize_subsection_headings_fn(normalized)
    normalized = normalize_standalone_labels_fn(normalized)
    normalized = normalize_existing_heading_tags_fn(normalized)
    normalized = normalize_semantic_callout_blocks_fn(normalized)
    normalized = normalize_inline_labeled_paragraphs_fn(normalized)
    normalized = strip_emojis_from_html_content_fn(normalized)
    normalized = strip_highlight_inside_headings_fn(normalized)
    return normalized


def format_html_report(
    html_content: str,
    *,
    source_emails: Optional[list[Dict[str, Any]]] = None,
    normalize_body: bool = True,
    base_dir: str,
    now_fn: Callable[[], Any],
    build_report_meta_html_fn: Callable[[Optional[list[Dict[str, Any]]], str], str],
    normalize_report_body_content_fn: Callable[[str], str],
) -> str:
    """将模型生成的 HTML 格式化为标准格式。"""
    css_file = os.path.join(base_dir, "reference_css.txt")
    reference_css = ""
    if os.path.exists(css_file):
        with open(css_file, "r", encoding="utf-8") as handle:
            reference_css = handle.read()

    body_match = re.search(r"<body>(.*?)</body>", html_content, re.DOTALL)
    body_content = body_match.group(1) if body_match else html_content
    if normalize_body:
        body_content = normalize_report_body_content_fn(body_content)

    today_str = now_fn().strftime("%Y-%m-%d")
    standardized_title = f"AI Morning Brief | {today_str}"

    if re.search(r"<h1\b[^>]*>.*?</h1>", body_content, re.IGNORECASE | re.DOTALL):
        body_content = re.sub(
            r"<h1\b[^>]*>.*?</h1>",
            f"<h1>{standardized_title}</h1>",
            body_content,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        body_content = f"<h1>{standardized_title}</h1>\n{body_content}"

    meta_html = build_report_meta_html_fn(source_emails, body_content)
    body_content = re.sub(
        r"(<h1\b[^>]*>.*?</h1>)",
        r"\1" + "\n" + meta_html,
        body_content,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    return f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{standardized_title}</title>
    <style>
{reference_css}
    </style>
</head>
<body>
    <div class="container">
{body_content}
    </div>
</body>
</html>"""


def render_list_html(
    items: list[Any],
    *,
    highlights: Optional[list[str]] = None,
    escape_with_highlights_fn: Callable[[str, Optional[list[str]]], str],
) -> str:
    if not items:
        return ""

    rendered_items = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("idea") or item.get("text") or item.get("title") or ""
            item_highlights = item.get("highlight_phrases") or highlights
        else:
            text = item
            item_highlights = highlights
        rendered_items.append(f"<li>{escape_with_highlights_fn(text, item_highlights)}</li>")

    return f"<ul>{''.join(rendered_items)}</ul>"


def render_detail_label(label: str) -> str:
    return f'<h4 class="detail-label">{escape(label)}</h4>'


def render_detail_copy(
    text: str,
    *,
    highlights: Optional[list[str]] = None,
    escape_with_highlights_fn: Callable[[str, Optional[list[str]]], str],
) -> str:
    return f'<p class="detail-copy">{escape_with_highlights_fn(text, highlights)}</p>'


def render_detail_list_html(
    items: list[Any],
    *,
    highlights: Optional[list[str]] = None,
    render_list_html_fn: Callable[[list[Any], Optional[list[str]]], str],
) -> str:
    html = render_list_html_fn(items, highlights)
    return re.sub(r"<(ul|ol)\b", r'<\1 class="detail-list"', html, count=1)


def render_market_views_table(
    rows: list[Dict[str, str]],
    *,
    escape_with_highlights_fn: Callable[[str, Optional[list[str]]], str],
) -> str:
    if not rows:
        return ""

    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td><strong>{escape(row.get('source', ''))}</strong></td>"
            f"<td>{escape_with_highlights_fn(row.get('stance', ''), row.get('stance_highlight_phrases'))}</td>"
            f"<td>{escape_with_highlights_fn(row.get('thesis', ''), row.get('thesis_highlight_phrases'))}</td>"
            "</tr>"
        )

    return (
        "<table>"
        "<tr><th>观点来源</th><th>立场</th><th>核心论点</th></tr>"
        + "".join(body_rows)
        + "</table>"
    )


def render_peripheral_table(rows: list[Dict[str, str]]) -> str:
    if not rows:
        return ""

    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td>{escape(row.get('event', ''))}</td>"
            f"<td>{escape(row.get('related_company', ''))}</td>"
            f"<td>{escape(row.get('mapping', ''))}</td>"
            "</tr>"
        )

    return (
        "<table>"
        "<tr><th>外围事件</th><th>相关公司</th><th>对Key Coverage的映射</th></tr>"
        + "".join(body_rows)
        + "</table>"
    )


def render_catalysts_table(rows: list[Dict[str, str]]) -> str:
    if not rows:
        return ""

    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td>{escape(row.get('catalyst', ''))}</td>"
            f"<td>{escape(row.get('time', ''))}</td>"
            f"<td>{escape(row.get('impact', ''))}</td>"
            "</tr>"
        )

    return (
        "<table>"
        "<tr><th>Catalyst</th><th>时间</th><th>影响标的</th></tr>"
        + "".join(body_rows)
        + "</table>"
    )


def build_priority_debug_summary(payload: Dict[str, Any]) -> str:
    core_event_map = {
        item.get("core_event_id"): item.get("headline", "")
        for item in payload.get("core_events", [])
        if item.get("core_event_id")
    }

    lines = ["排序与映射摘要:"]
    if payload.get("core_events"):
        lines.append("  Key Coverage:")
        for item in payload["core_events"]:
            lines.append(
                "    - {id} | rank={rank} | coverage={coverage} | score={score} | {headline}".format(
                    id=item.get("core_event_id", "-"),
                    rank=item.get("priority_rank", "-"),
                    coverage=item.get("coverage_count", 0),
                    score=item.get("global_score", 0.0),
                    headline=item.get("headline", ""),
                )
            )

    actionable = payload.get("actionable_ideas", {})
    for section_key, section_label in [("short_term", "短期想法"), ("medium_term", "中期想法")]:
        section_items = actionable.get(section_key) or []
        if not section_items:
            continue
        lines.append(f"  {section_label}:")
        for item in section_items:
            linked = [
                core_event_map.get(core_event_id, core_event_id)
                for core_event_id in (item.get("linked_core_event_ids") or [])
            ]
            lines.append(
                "    - rank={rank} | coverage={coverage} | score={score} | linked={linked} | {idea}".format(
                    rank=item.get("priority_rank", "-"),
                    coverage=item.get("coverage_count", 0),
                    score=item.get("global_score", 0.0),
                    linked=", ".join(linked) if linked else "[]",
                    idea=item.get("idea", ""),
                )
            )

    catalysts = actionable.get("catalysts") or []
    if catalysts:
        lines.append("  Catalysts:")
        for item in catalysts:
            linked = [
                core_event_map.get(core_event_id, core_event_id)
                for core_event_id in (item.get("linked_core_event_ids") or [])
            ]
            lines.append(
                "    - rank={rank} | coverage={coverage} | score={score} | linked={linked} | {catalyst}".format(
                    rank=item.get("priority_rank", "-"),
                    coverage=item.get("coverage_count", 0),
                    score=item.get("global_score", 0.0),
                    linked=", ".join(linked) if linked else "[]",
                    catalyst=item.get("catalyst", ""),
                )
            )

    return "\n".join(lines)


def render_report_html(
    report_payload: Dict[str, Any],
    *,
    source_emails: Optional[list[Dict[str, Any]]] = None,
    normalize_report_payload_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
    logger: Any,
    fixed_report_template: Dict[str, Any],
    render_list_html_fn: Callable[[list[Any], Optional[list[str]]], str],
    render_detail_label_fn: Callable[[str], str],
    render_detail_copy_fn: Callable[[str, Optional[list[str]]], str],
    render_detail_list_html_fn: Callable[[list[Any], Optional[list[str]]], str],
    render_market_views_table_fn: Callable[[list[Dict[str, str]]], str],
    render_peripheral_table_fn: Callable[[list[Dict[str, str]]], str],
    render_catalysts_table_fn: Callable[[list[Dict[str, str]]], str],
    build_priority_debug_summary_fn: Callable[[Dict[str, Any]], str],
    format_html_report_fn: Callable[..., str],
) -> str:
    payload = normalize_report_payload_fn(report_payload)
    logger.info("\n" + build_priority_debug_summary_fn(payload))

    body_parts = [
        "<h2>Executive Summary</h2>",
        f'<p><strong>{fixed_report_template["executive_summary"][0]}:</strong> {escape(payload["executive_summary"]["market_background"])}</p>',
        f'<p><strong>{fixed_report_template["executive_summary"][1]}:</strong></p>',
        render_list_html_fn(payload["executive_summary"]["key_signals"], None),
        '<div class="divider"></div>',
        f'<h2>{fixed_report_template["core_events_h2"]}</h2>',
    ]

    for index, coverage in enumerate(payload["core_events"], 1):
        body_parts.append(f"<h3>{index}. {escape(coverage['headline'])}</h3>")
        if coverage["core_facts"]:
            body_parts.append(render_detail_label_fn("核心事实"))
            body_parts.append(render_detail_list_html_fn(coverage["core_facts"], coverage.get("core_fact_highlight_phrases")))
        body_parts.append(render_detail_label_fn("市场怎么看"))
        if coverage["market_views"]:
            body_parts.append(render_market_views_table_fn(coverage["market_views"]))
        elif coverage["market_take"]:
            body_parts.append(render_detail_list_html_fn(coverage["market_take"], coverage["highlight_phrases"]))
        if coverage["action"]:
            body_parts.append(render_detail_label_fn("投资启示"))
            body_parts.append(render_detail_copy_fn(coverage["action"], coverage.get("action_highlight_phrases")))

    body_parts.append('<div class="divider"></div>')
    body_parts.append(f'<h2>{fixed_report_template["local_news_h2"]}</h2>')
    for index, item in enumerate(payload["local_news"], 1):
        body_parts.append(f"<h3>{index}. {escape(item['headline'])}</h3>")
        body_parts.append(render_detail_label_fn("信号"))
        body_parts.append(render_detail_copy_fn(item["signal"], item.get("signal_highlight_phrases")))
        body_parts.append(render_detail_label_fn("为什么重要"))
        body_parts.append(render_detail_copy_fn(item["importance"], item.get("importance_highlight_phrases")))
        body_parts.append(render_detail_label_fn("Action"))
        body_parts.append(render_detail_copy_fn(item["action"], item.get("action_highlight_phrases")))

    body_parts.append(f'<h2>{fixed_report_template["peripheral_h2"]}</h2>')
    body_parts.append(f'<h3>{fixed_report_template["peripheral_subsections"][0]}</h3>')
    body_parts.append(render_peripheral_table_fn(payload["peripheral_intelligence"]["mapped_events"]))
    body_parts.append(f'<h3>{fixed_report_template["peripheral_subsections"][1]}</h3>')
    for item in payload["peripheral_intelligence"]["cross_market_signals"]:
        if item["headline"]:
            body_parts.append(f'<p><strong>{escape(item["headline"])}</strong></p>')
        body_parts.append(render_list_html_fn(item["bullets"], item.get("bullet_highlight_phrases")))

    body_parts.append(f'<h2>{fixed_report_template["actionable_h2"]}</h2>')
    body_parts.append(f'<h3>{fixed_report_template["actionable_labels"][0]}</h3>')
    body_parts.append(render_list_html_fn(payload["actionable_ideas"]["short_term"], None))
    body_parts.append(f'<h3>{fixed_report_template["actionable_labels"][1]}</h3>')
    body_parts.append(render_list_html_fn(payload["actionable_ideas"]["medium_term"], None))
    body_parts.append(f'<h2>{fixed_report_template["actionable_labels"][2]}</h2>')
    body_parts.append(render_catalysts_table_fn(payload["actionable_ideas"]["catalysts"]))
    body_parts.append(
        f'<p><strong>{fixed_report_template["actionable_labels"][3]}:</strong> {escape(payload["actionable_ideas"]["bottom_line"])}</p>'
    )

    return format_html_report_fn(
        "\n".join(part for part in body_parts if part),
        source_emails=source_emails,
        normalize_body=False,
    )


def save_report(
    html_content: str,
    *,
    source_emails: Optional[list[Dict[str, Any]]] = None,
    validate_html_fn: Callable[[str], tuple[bool, str]],
    format_html_report_fn: Callable[..., str],
    logger: Any,
    base_dir: str,
    now_fn: Callable[[], Any],
) -> Optional[str]:
    """保存 HTML 报告到文件。"""
    if not html_content:
        return None

    if html_content.strip().startswith("```html"):
        html_content = html_content.strip()[7:]
    if html_content.strip().startswith("```"):
        html_content = html_content.strip()[3:]
    if html_content.strip().endswith("```"):
        html_content = html_content.strip()[:-3]

    is_valid, error_msg = validate_html_fn(html_content)
    if not is_valid:
        logger.warning(f"⚠️ HTML验证未通过: {error_msg}，尝试自动包裹为完整HTML")
        html_content = format_html_report_fn(html_content, source_emails=source_emails)
        is_valid, error_msg = validate_html_fn(html_content)
        if not is_valid:
            logger.error(f"❌ HTML验证失败: {error_msg}")
            return None
    else:
        html_content = format_html_report_fn(html_content, source_emails=source_emails)

    logger.info("✅ 格式校准完成")

    now_dt = now_fn()
    today_str = now_dt.strftime("%Y%m%d")
    timestamp_str = now_dt.strftime("%H%M%S")
    archived_report_file = os.path.join(base_dir, f"AI_Morning_Brief_{today_str}_{timestamp_str}.html")
    report_file = os.path.join(base_dir, f"AI_Morning_Brief_{today_str}.html")

    try:
        with open(archived_report_file, "w", encoding="utf-8") as handle:
            handle.write(html_content)
        with open(report_file, "w", encoding="utf-8") as handle:
            handle.write(html_content)
        logger.info(
            "💾 已保存报告: %s（稳定产物），并留档: %s (%s bytes)",
            report_file,
            archived_report_file,
            len(html_content),
        )
        return report_file
    except Exception as exc:
        logger.error(f"❌ 保存报告失败: {exc}")
        return None


def check_for_report(*, base_dir: str, now_fn: Callable[[], Any], report_prefix: str) -> Optional[str]:
    """检查是否生成了报告文件。"""
    today_str = now_fn().strftime("%Y%m%d")

    report_file = os.path.join(base_dir, f"AI_Morning_Brief_{today_str}.html")
    if os.path.exists(report_file):
        return report_file

    timestamped_reports = sorted(
        glob.glob(os.path.join(base_dir, f"AI_Morning_Brief_{today_str}_*.html")),
        key=os.path.getmtime,
        reverse=True,
    )
    if timestamped_reports:
        return timestamped_reports[0]

    report_file = os.path.join(base_dir, f"{report_prefix}{today_str}.html")
    if os.path.exists(report_file):
        return report_file

    return None


def get_report_preview(report_file: str, max_lines: int = 10) -> str:
    """获取报告预览。"""
    try:
        with open(report_file, "r", encoding="utf-8") as handle:
            content = handle.read()
            titles = re.findall(r"<h[1-3][^>]*>([^<]+)</h[1-3]>", content, re.IGNORECASE)
            if titles:
                return " | ".join(titles[:max_lines])
            return content[:200] + "..."
    except Exception as exc:
        return f"读取失败: {exc}"
