from typing import Any, Dict, List


def build_json_schema_response_format(name: str, schema: Dict[str, Any], strict: bool = True) -> Dict[str, Any]:
    return {
        "type": "json_schema",
        "json_schema": {
            "name": name,
            "strict": strict,
            "schema": schema,
        },
    }


def build_batch_summary_response_format() -> Dict[str, Any]:
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["batch_index", "batch_total", "email_ids", "topics"],
        "properties": {
            "batch_index": {"type": "integer"},
            "batch_total": {"type": "integer"},
            "email_ids": {"type": "array", "items": {"type": "integer"}},
            "topics": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "title",
                        "email_ids",
                        "coverage_count",
                        "merge_key",
                        "time_horizon",
                        "target_slot",
                        "fact_subject",
                        "opinion_subject",
                        "info_type",
                        "core_facts",
                        "market_takeaways",
                        "tickers",
                        "source_evidence",
                    ],
                    "properties": {
                        "title": {"type": "string"},
                        "email_ids": {"type": "array", "items": {"type": "integer"}},
                        "coverage_count": {"type": "integer"},
                        "merge_key": {"type": "string"},
                        "time_horizon": {"type": "string"},
                        "target_slot": {
                            "type": "string",
                            "enum": [
                                "core_events",
                                "local_news",
                                "peripheral_intelligence",
                                "actionable_ideas",
                            ],
                        },
                        "fact_subject": {"type": "string"},
                        "opinion_subject": {"type": "string"},
                        "info_type": {"type": "string"},
                        "core_facts": {"type": "array", "items": {"type": "string"}},
                        "market_takeaways": {"type": "array", "items": {"type": "string"}},
                        "tickers": {"type": "array", "items": {"type": "string"}},
                        "source_evidence": {"type": "array", "items": {"type": "string"}},
                    },
                },
            },
        },
    }
    return build_json_schema_response_format("hf_batch_summary", schema)


def build_report_response_format() -> Dict[str, Any]:
    market_view_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["source", "stance", "thesis"],
        "properties": {
            "source": {"type": "string"},
            "stance": {"type": "string"},
            "thesis": {"type": "string"},
            "stance_highlight_phrases": {"type": "array", "items": {"type": "string"}},
            "thesis_highlight_phrases": {"type": "array", "items": {"type": "string"}},
        },
    }
    core_event_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "headline",
            "priority_rank",
            "coverage_count",
            "global_score",
            "source_topics",
            "core_facts",
            "market_views",
            "action",
            "attribution_note",
            "source_evidence",
        ],
        "properties": {
            "headline": {"type": "string"},
            "priority_rank": {"type": "integer"},
            "coverage_count": {"type": "integer"},
            "global_score": {"type": "number"},
            "source_topics": {"type": "array", "items": {"type": "string"}},
            "core_facts": {"type": "array", "items": {"type": "string"}},
            "market_views": {"type": "array", "items": market_view_schema},
            "action": {"type": "string"},
            "highlight_phrases": {"type": "array", "items": {"type": "string"}},
            "attribution_note": {"type": "string"},
            "source_evidence": {"type": "array", "items": {"type": "string"}},
        },
    }
    local_news_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["headline", "priority_rank", "signal", "importance", "action"],
        "properties": {
            "headline": {"type": "string"},
            "priority_rank": {"type": "integer"},
            "signal": {"type": "string"},
            "importance": {"type": "string"},
            "action": {"type": "string"},
            "highlight_phrases": {"type": "array", "items": {"type": "string"}},
        },
    }
    mapped_event_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["event", "related_company", "mapping"],
        "properties": {
            "event": {"type": "string"},
            "related_company": {"type": "string"},
            "mapping": {"type": "string"},
        },
    }
    cross_market_signal_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": ["headline", "priority_rank", "bullets"],
        "properties": {
            "headline": {"type": "string"},
            "priority_rank": {"type": "integer"},
            "bullets": {"type": "array", "items": {"type": "string"}},
            "highlight_phrases": {"type": "array", "items": {"type": "string"}},
        },
    }
    actionable_item_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "idea",
            "priority_rank",
            "coverage_count",
            "global_score",
            "source_topics",
            "linked_core_event_headlines",
        ],
        "properties": {
            "idea": {"type": "string"},
            "priority_rank": {"type": "integer"},
            "coverage_count": {"type": "integer"},
            "global_score": {"type": "number"},
            "source_topics": {"type": "array", "items": {"type": "string"}},
            "linked_core_event_headlines": {"type": "array", "items": {"type": "string"}},
        },
    }
    catalyst_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "catalyst",
            "time",
            "impact",
            "priority_rank",
            "coverage_count",
            "global_score",
            "source_topics",
            "linked_core_event_headlines",
        ],
        "properties": {
            "catalyst": {"type": "string"},
            "time": {"type": "string"},
            "impact": {"type": "string"},
            "priority_rank": {"type": "integer"},
            "coverage_count": {"type": "integer"},
            "global_score": {"type": "number"},
            "source_topics": {"type": "array", "items": {"type": "string"}},
            "linked_core_event_headlines": {"type": "array", "items": {"type": "string"}},
        },
    }
    schema = {
        "type": "object",
        "additionalProperties": False,
        "required": [
            "executive_summary",
            "core_events",
            "local_news",
            "peripheral_intelligence",
            "actionable_ideas",
        ],
        "properties": {
            "executive_summary": {
                "type": "object",
                "additionalProperties": False,
                "required": ["market_background", "key_signals"],
                "properties": {
                    "market_background": {"type": "string"},
                    "key_signals": {"type": "array", "items": {"type": "string"}},
                },
            },
            "core_events": {"type": "array", "items": core_event_schema},
            "local_news": {"type": "array", "items": local_news_schema},
            "peripheral_intelligence": {
                "type": "object",
                "additionalProperties": False,
                "required": ["mapped_events", "cross_market_signals"],
                "properties": {
                    "mapped_events": {"type": "array", "items": mapped_event_schema},
                    "cross_market_signals": {"type": "array", "items": cross_market_signal_schema},
                },
            },
            "actionable_ideas": {
                "type": "object",
                "additionalProperties": False,
                "required": ["short_term", "medium_term", "catalysts", "bottom_line"],
                "properties": {
                    "short_term": {"type": "array", "items": actionable_item_schema},
                    "medium_term": {"type": "array", "items": actionable_item_schema},
                    "catalysts": {"type": "array", "items": catalyst_schema},
                    "bottom_line": {"type": "string"},
                },
            },
        },
    }
    return build_json_schema_response_format("hf_morning_brief_report", schema)


def build_prompt_category_block(title: str, items: List[str]) -> str:
    lines = [f"## {title}"]
    lines.extend(f"- {item}" for item in items if item and item.strip())
    return "\n".join(lines)


def get_report_prompt_governance() -> str:
    principles = [
        "优先做内容筛选和语义归因，再做摘要表达。",
        "结构稳定优先于文采，宁可朴素也不要漂移。",
        "输入中的正文可能已经过清洗、裁剪，并把可用视觉结论回填成短句；要把这些回填句子和正文放在同一判断框架下理解。",
    ]
    bottom_lines = [
        "不能把外部引述、媒体报道、市场传闻误写成发件机构 house view。",
        "不能把普通功能小升级、版本小更新、一般性运营通知硬塞进核心版面。",
        "不能把观点判断、推测或带 says / suggests / reportedly 色彩的内容直接写成核心事实。",
        "不能为了显得完整而重复同一个逻辑，不能把一句话能说清的内容扩成一段。",
    ]
    reminders = [
        "核心事实每条尽量一句话；能短就不要写成长句。",
        "关键信号、投资启示、Bottom Line 都优先写成短句，避免背景解释和同义反复。",
        "来源展示优先保留真实主语；只有原文明确属于发件机构判断时，才写成 MS、JPM 等 house view。",
        "版式由本地固定模板渲染，模型只需要把内容填进正确槽位。",
    ]
    return "\n\n".join(
        [
            build_prompt_category_block("原则", principles),
            build_prompt_category_block("底线", bottom_lines),
            build_prompt_category_block("提醒", reminders),
        ]
    )


def get_hf_role_guidance() -> str:
    identity = [
        "你是一位每天会收到非常多邮件的对冲基金高级研究员，需要在每天盘前高效阅读卖方 sales 发来的内容。",
        "你的输入是已经筛选、清洗并裁剪过的高价值卖方邮件文本；其中可能已把可用图片结论回填成短句。",
        "你的职责不是机械复述邮件，而是帮助你自己快速看清：今天最集中的关注点、市场对这些主题的主流态度和 thesis、以及哪些信息最可能影响预期修正和交易决策。",
    ]
    editorial_style = [
        "你已经知道大部分基础事实，你的价值在于提炼主线、统一归因、压缩噪音，并把最值得进入晨会讨论的内容放到最前面。",
        "在做盘前邮件信息总结时，首页先给市场背景，再给关键信号，让人快速抓住关键点。",
        "市场背景优先写宏观或者行业层面的主线，或者近期的重点事件。",
        "核心区优先保留共识最强、可交易性最强、最可能影响预期修正的主题。",
        "句子尽量短，解释尽量少；一句话能讲清，就不要拆成三句。",
        "非常重要的内容需要高亮。",
    ]
    judgment_style = [
        "对谁真正提出观点保持高度敏感；发件机构不自动拥有正文里的所有观点，外部人物、媒体、管理层、市场传闻必须保留真实主语。",
        "默认先看哪些主题被重复提到、哪些判断正在形成共识，再决定排序和首页信号。",
        "正文中由图片回填的视觉短句，默认视为邻近主题的辅助证据；只有它本身构成独立、可交易的市场信号时，才单独成主题。",
        "不要因为同一封邮件里连续出现多条视觉结论，就把它们拆成多个相近 topic；先判断它们是否只是同一主题的补充证据。",
        "不要为了填版面硬塞 trivial 更新、普通功能升级或没有交易含义的边角信息。",
        "不要把 Actionable Ideas 写成待办清单；它更像你会放进晨会和盘前讨论里的交易想法与催化清单。",
        "Actionable Ideas 要短、狠、可执行；优先保留最核心的对象、逻辑和催化，不要写成解释型小作文。",
        "Local News 不是次要垃圾桶，而是捕捉暂时不属于核心覆盖、但可能预示预期变化或相对收益机会的边缘信号。",
        "Peripheral Intelligence 需要把非核心公司事件、跨市场变化和外围信息映射回当前最重要的投资主线。",
    ]
    return "\n\n".join(
        [
            build_prompt_category_block("角色", identity),
            build_prompt_category_block("写法", editorial_style),
            build_prompt_category_block("判断", judgment_style),
        ]
    )


def get_visual_context_prompt_rules() -> str:
    return """## 邮件级视觉上下文使用规则
- 邮件正文中可能已经包含 `[邮件级视觉上下文]`、`[Visual Context]`、`[Visual Evidence]` 结构块，这代表图片已被单独预处理和结构化
- `Visual Context` 更偏主叙事 framing / social signal，应优先作为正文理解的一部分
- `Visual Evidence` 更偏图表、研究框架、市场数据证据，应作为 supporting evidence 使用
- 视觉上下文可以强化事实与市场观点，但不能把 editorial framing、社交传播截图直接写成已独立核实的硬事实
- 最终摘要不得超出视觉上下文里已经明确给出的结论和补充信息
"""


def get_shared_fact_attribution_rules() -> str:
    return """## 事实与归因规则
- 先区分事实、观点、传闻，再做摘要
- 主语归因优先于表面语气词
- “发件人/券商机构”不等于“正文里每一句话的观点主体”
- 如果正文出现 `X says`、`according to X`、`reports suggest`、`媒体称`、`市场传闻`、`management said` 之类表述，必须把观点归给 X、媒体、市场或管理层，而不是默认归给发件机构
- 带有“认为 / 预计 / 可能 / 或 / suggests / reportedly / rumor”色彩的内容，默认不是核心事实，除非邮件里给出了可验证的客观证据
- 例如 `Shawn Kim says SRAM is a complement to HBM` 应写成 `Shawn Kim 认为...` 或 `邮件转述 Shawn Kim 的观点...`，不能写成 `MS认为...`，除非原文明确写的是 Morgan Stanley 的判断
"""


def get_report_output_contract() -> str:
    return """## 输出契约
- 只输出合法 JSON，不要 HTML，不要 Markdown，不要解释文字
- 必须使用简体中文；ticker、公司英文名和必要英文缩写可保留原文
- 无内容时：数组返回 `[]`，字符串返回 `\"\"`；不要返回 `null`、`None`、`N/A`、`未知`、`待定`
- 不得新增 schema 未定义字段、额外顶层模块或说明性文字
- 不得补写邮件中未出现、也无法从输入直接推出的机构观点、时间点、催化、数字、引述对象
- 如果信息不足，宁可留空、降级或省略该条，也不要为了显得完整而硬写
"""


def get_report_slot_boundary_rules() -> str:
    return """## 槽位边界
- `executive_summary` 只负责市场大背景和当日最重要信号，不承担细节堆砌
- `core_events` 只放最高优先级、最可能影响预期修正或交易决策的核心主题；同一主题应围绕同一个主要对象、事件/催化和预期变化
- `local_news` 放没有进入核心区、但仍可能预示预期变化、情绪变化或相对收益机会的边缘信号；不要重复 `core_events`，也不要收留 trivial 噪音
- `peripheral_intelligence` 只放能够映射回当前核心主线的外围事件、跨市场变化和类比信号；如果不能清楚映射，就不要硬写
- `actionable_ideas` 是基于全局信息重新提炼出的交易想法与催化剂，不是剩余信息区，也不是对事实的机械改写
"""


def build_report_system_prompt(*extra_sections: str) -> str:
    sections = [
        "你是一位每天会收到非常多邮件的对冲基金高级研究员，需要在每天盘前高效阅读卖方 sales 发来的内容。",
        get_hf_role_guidance(),
        get_report_prompt_governance(),
        get_shared_fact_attribution_rules(),
        get_report_output_contract(),
        get_report_slot_boundary_rules(),
        *extra_sections,
    ]
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def get_batch_prompt_shared_brief() -> str:
    return """## 子批次工作方式
- 你在做的是中间摘要，不是最终晨报；目标是为后续 merge 提供稳定、可对齐、可归槽的 topics
- 输入是已经筛选、清洗并裁剪过的高价值邮件正文；正文里可能已自然混入图片提炼出的证据短句
- 优先保留最可能影响预期修正、市场共识和交易决策的信息；句子尽量短，结构稳定优先于文采

## 归因纪律
- 先区分事实、观点、传闻，再做摘要
- 主语归因优先；发件机构不自动拥有正文里的所有观点
- 出现 `X says`、`according to X`、`reports suggest`、`媒体称`、`市场传闻`、`management said` 等表述时，必须保留真实主语，不能默认写成发件机构 house view
- 带有“认为 / 预计 / 可能 / suggests / reportedly / rumor”色彩的内容，默认不是核心事实，除非正文给出了可验证证据

## 输出纪律
- 只保留后续合并、排序和归槽真正需要的信息，不要为了完整硬塞 trivial 内容
- 只输出合法 JSON，不要 HTML、Markdown 或解释文字
- 必须使用简体中文；ticker、公司英文名和必要英文缩写可保留原文
- 不得补写正文中未出现、也无法直接推出的观点、时间点、催化、数字或引述对象
 
## 主题切分与归槽
- 同一对象如果对应不同催化、不同时间框架或不同预期方向，不要合并成一个 topic
- 实质相同的主题在同一批次内尽量使用稳定标题，避免后续 merge 漂移
- 如果你不确定两个点是否属于同一主题，优先分开写，并保留各自证据
- 每个 topic 都要预判最终更可能进入哪个槽位，并写入 `target_slot`
- 每个 topic 都要写 `time_horizon`，帮助后续区分短期交易驱动和中期主线
- `core_events` 只放最高优先级、最可能影响预期修正或交易决策的核心主题
- `local_news` 放未进入核心区、但仍可能预示预期变化或相对收益机会的边缘信号
- `peripheral_intelligence` 只放能够映射回当前核心主线的外围事件、跨市场变化和类比信号
- `actionable_ideas` 是基于全局信息重新提炼出的交易想法与催化剂，不是剩余信息区，也不是事实改写区
"""


def get_merge_prompt_shared_brief() -> str:
    return """## 合并阶段工作方式
- 你在做的是最终晨报整合，需要把各批次中间摘要统一归因、去重、排序，并填入固定槽位
- 优先保留最高优先级、最可交易、最可能影响预期修正的主题；结构稳定优先于文采，句子尽量短

## 归因纪律
- 先区分事实、观点、传闻，再做整合
- 主语归因优先；发件机构不自动拥有被引述观点
- 外部引述、媒体报道、市场传闻不能误写成 house view；若提示和证据冲突，以事实归因和原文证据为准

## 合并纪律
- 只在“同一主要对象 + 同一底层事件/催化 + 同一主要预期方向 + 同一时间框架”成立时才合并主题
- 同一公司若对应不同催化、不同时间框架或不同价格驱动，必须拆成不同主题，不要硬并
- 如果基础事实相同但市场观点有分歧，可以放在同一个 `core_events` 下保留分歧，不要伪造一致共识
- 可以参考 batch 中的 `target_slot`、`time_horizon`、`merge_key` 做对齐，但若提示和证据冲突，以事实归因和原文证据为准
- 按合并后的覆盖邮件数排序，但不要在输出中显示覆盖数字
- 普通功能升级、一般性产品更新、没有交易含义的 trivial 变化默认忽略或显著降权
- `executive_summary` 必须明确拆成“市场大背景”和“关键信号”
- `actionable_ideas` 必须基于合并后的全局图景二次提炼，不能只是复制批次 topic 标题

## 输出纪律
- 版式由固定模板渲染，模型只负责把内容填进正确槽位
- 只输出合法 JSON，不要 HTML、Markdown 或解释文字
- 必须使用简体中文；ticker、公司英文名和必要英文缩写可保留原文
- 不得补写输入中未出现、也无法直接推出的观点、时间点、催化、数字或引述对象
"""


def build_batch_system_prompt(*extra_sections: str) -> str:
    sections = [
        "你是一位每天会收到非常多邮件的对冲基金高级研究员，需要在每天盘前高效阅读卖方 sales 发来的内容。",
        get_batch_prompt_shared_brief(),
        *extra_sections,
    ]
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def build_merge_system_prompt(*extra_sections: str) -> str:
    sections = [
        "你是一位每天会收到非常多邮件的对冲基金高级研究员，需要在每天盘前高效阅读卖方 sales 发来的内容。",
        get_merge_prompt_shared_brief(),
        *extra_sections,
    ]
    return "\n\n".join(section.strip() for section in sections if section and section.strip())


def get_batch_summary_stage_rules() -> str:
    return """## 子批次任务
- 当前任务不是直接写最终晨报，而是把一批已经清洗、裁剪过的邮件正文整理成稳定、可对齐、可归槽的中间摘要，供后续 merge 使用
- 输入文本可能包含由图片提炼出的短句证据，请与周围正文一起理解，不要把它们机械当成独立主题

## 核心要求
- 先做内容筛选和语义归因，再做摘要表达
- 优先保留最可能影响预期修正、市场共识和交易决策的信息
- 句子尽量短，解释尽量少，结构稳定优先于文采
- 只保留后续合并、排序和归槽真正需要的信息，不要为了完整硬塞 trivial 内容

## 归因与证据纪律
- 先区分事实、观点、传闻，再做摘要
- 主语归因优先于表面语气词；发件机构不自动拥有正文里的所有观点
- 如果正文出现 `X says`、`according to X`、`reports suggest`、`媒体称`、`市场传闻`、`management said` 等表述，必须保留真实主语，不能默认写成发件机构 house view
- 带有“认为 / 预计 / 可能 / suggests / reportedly / rumor”色彩的内容，默认不是核心事实，除非邮件里给出了可验证的客观证据

## 主题切分纪律
- 同一对象如果对应不同催化、不同时间框架或不同预期方向，不要合并成一个 topic
- 实质相同的主题在同一批次内尽量使用稳定标题，避免后续 merge 漂移
- 如果你不确定两个点是否属于同一主题，优先分开写，并保留各自证据
- 每个 topic 都要预判最终更可能进入哪个槽位，并写入 `target_slot`
- 每个 topic 都要写 `time_horizon`，帮助后续区分短期交易驱动和中期主线

## 槽位边界
- `core_events` 只放最高优先级、最可能影响预期修正或交易决策的核心主题
- `local_news` 放未进入核心区、但仍可能预示预期变化或相对收益机会的边缘信号
- `peripheral_intelligence` 只放能够映射回当前核心主线的外围事件、跨市场变化和类比信号
- `actionable_ideas` 是基于全局信息重新提炼出的交易想法与催化剂，不是剩余信息区，也不是事实改写区

## 输出要求
- 只输出合法 JSON，不要 HTML、Markdown 或解释文字
- 必须使用简体中文；ticker、公司英文名和必要英文缩写可保留原文
- 无内容时数组返回 `[]`，字符串返回 `""`；不要返回 `null`、`None`、`N/A`
- 不得新增 schema 未定义字段，不得补写邮件中未出现、也无法直接推出的观点、时间点、催化、数字或引述对象
"""


def get_merge_stage_rules(total_email_count: int) -> str:
    return f"""## 合并任务
你会收到若干份子批次摘要，这些摘要来自同一天的同一组 {total_email_count} 封卖方邮件。请完成以下工作：
1. 只在“同一主要对象 + 同一底层事件/催化 + 同一主要预期方向 + 同一时间框架”成立时才合并主题
2. 如果是同一公司但对应不同催化、不同时间框架或不同价格驱动，必须拆成不同主题，不要硬并
3. 如果基础事实相同但市场观点有分歧，可以放在同一个 `core_events` 下用多条 `market_views` 保留分歧；不要伪造一致共识
4. 合并时把 batch 里的 `target_slot`、`time_horizon`、`merge_key` 当作对齐提示，但不要机械照搬；若提示和证据冲突，以事实归因与原文证据为准
5. 按合并后的覆盖邮件数排序，但不要在输出中显示覆盖数字
6. 普通功能升级、一般性产品更新、没有交易含义的 trivial 变化默认忽略或显著降权
7. Executive Summary 必须明确拆成“市场大背景”和“关键信号”
8. Actionable Ideas 必须基于合并后的全局图景二次提炼，不能只是复制批次 topic 标题
9. 核心事实要尽量短，不要写成长段解释
"""


def get_fixed_report_schema_prompt() -> str:
    return """## 固定模板槽位
你必须输出合法 JSON，字段结构如下：
{
  "executive_summary": {
    "market_background": "1段，概括市场大背景，优先1-2句",
    "key_signals": ["3-5条，提炼当日最重要信号；每条尽量短，不要写成长句"]
  },
  "core_events": [
    {
      "headline": "事件标题",
      "priority_rank": 1,
      "coverage_count": 3,
      "global_score": 9.5,
      "source_topics": ["主题A", "主题B"],
      "core_facts": ["事实1", "事实2"],
      "market_views": [
        {
          "source": "MS",
          "stance": "机构观点",
          "thesis": "机构判断逻辑"
        }
      ],
      "action": "对应交易或跟踪动作",
      "highlight_phrases": ["高亮短语"],
      "attribution_note": "如果需要，说明事实主体和观点主体",
      "source_evidence": ["最关键的原文短句"]
    }
  ],
  "local_news": [
    {
      "headline": "边缘但有意义的信号",
      "priority_rank": 1,
      "signal": "信号本身",
      "importance": "为什么值得注意",
      "action": "该怎么跟踪",
      "highlight_phrases": ["高亮短语"]
    }
  ],
  "peripheral_intelligence": {
    "mapped_events": [
      {
        "event": "外围事件",
        "related_company": "映射公司",
        "mapping": "映射逻辑"
      }
    ],
    "cross_market_signals": [
      {
        "headline": "跨市场信号",
        "priority_rank": 1,
        "bullets": ["要点1", "要点2"],
        "highlight_phrases": ["高亮短语"]
      }
    ]
  },
  "actionable_ideas": {
    "short_term": [
      {
        "idea": "短期交易想法",
        "priority_rank": 1,
        "coverage_count": 2,
        "global_score": 8.8,
        "source_topics": ["主题A"],
        "linked_core_event_headlines": ["事件标题"]
      }
    ],
    "medium_term": [
      {
        "idea": "中期交易想法",
        "priority_rank": 1,
        "coverage_count": 2,
        "global_score": 8.2,
        "source_topics": ["主题B"],
        "linked_core_event_headlines": ["事件标题"]
      }
    ],
    "catalysts": [
      {
        "catalyst": "催化剂",
        "time": "时间",
        "impact": "影响",
        "priority_rank": 1,
        "coverage_count": 2,
        "global_score": 8.0,
        "source_topics": ["主题C"],
        "linked_core_event_headlines": ["事件标题"]
      }
    ],
    "bottom_line": "一句话总结"
  }
}
"""
