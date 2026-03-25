# HF Multimodal Image Pipeline

这份文档用于记录当前图片链路的真实实现、字段设计和规则。

当前正式主链路是：

1. `collect + prescreen`
2. `lightweight classification`
3. `deep analysis`
4. 聚合成邮件级 `Visual Context / Visual Evidence`

本文重点记录前三步，因为它们决定了图片如何从原图变成结构化视觉证据。

---

## 1. 总体原则

当前图片链路遵守 5 个原则：

- 只保留一条正式主路径，不允许后续阶段绕过前置图片结果再直传原图
- 图片轻分类和深分析都尽量只基于图片本身，不联读正文上下文
- 尽量减少上下文污染，只保留真正有价值的信息；弱元数据默认不进模型，除非已经证明能稳定提升效果
- 先把单张图变成结构化证据，再进入邮件级聚合
- 空结果和弱结果不能覆盖已有更强的视觉结果

---

## 1.1 参数与 Cutoff 总表

这部分只记录“当前真实会生效的参数和截断点”，方便排查行为时快速定位。

### 主入口 Wrapper

服务分析入口和 CLI 入口当前都对齐成这两组 wrapper：

- 轻分类 wrapper
  - `images, api_config=None, classification_concurrency=None`
  - 服务入口见 [`app/runtime/service_analysis.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/runtime/service_analysis.py#L363)
  - CLI 入口见 [`qclaw_mail_file.py`](/Users/yyukichen/Desktop/email-service-research-assistant/qclaw_mail_file.py#L526)
- 深分析 wrapper
  - `image_objects, api_config=None, max_deep_analysis_images=None, deep_analysis_concurrency=None`
  - 服务入口见 [`app/runtime/service_analysis.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/runtime/service_analysis.py#L382)
  - CLI 入口见 [`qclaw_mail_file.py`](/Users/yyukichen/Desktop/email-service-research-assistant/qclaw_mail_file.py#L544)

### 配置项、默认值和当前值

这些值统一从 [`app/config.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/config.py#L73) 的 `DEFAULT_IMAGE_PIPELINE_SETTINGS` 和 `build_image_pipeline_settings()` 解析出来。

| 配置项 | 默认值 | 当前值 | 生效位置 | 说明 |
| --- | --- | --- | --- | --- |
| `multimodal.max_images` | `50` | `50` | [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L664) | Step 1 收图总量上限；超过后按优先级截断 |
| `multimodal.max_deep_analysis_images` | `15` | `0 -> None` | [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L1044) | 当前配置 `0` 会被归一成“不限量” |
| `multimodal.classification_concurrency` | `2` | `2` | [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L998) | 轻分类并发数 |
| `multimodal.deep_analysis_concurrency` | `2` | `2` | [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L1210) | 深分析并发数 |
| `multimodal.max_inline_visual_contexts` | `None` | `None` | [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L794) | 邮件级 inline visual context 数量上限；当前不截断 |
| `multimodal.max_supporting_visual_evidence` | `None` | `None` | [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L817) | 邮件级 supporting evidence 数量上限；当前不截断 |
| `multimodal.stop_new_deep_analysis_before_daily_minutes` | `None` | `3` | [`app/config.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/config.py#L248) | 当前只完成配置解析，尚未接入执行逻辑 |

### 运行时额外上限

除了 `multimodal.*` 配置外，还有一个只作用于主 LLM 直连多模态入口的运行时上限：

- [`app/runtime/service_analysis.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/runtime/service_analysis.py#L40) 的 `MAX_MULTIMODAL_IMAGES = 20`
- 它控制的是 `build_multimodal_user_blocks()` 最多往主 LLM 的 `user_content_blocks` 放多少张图，见 [`app/runtime/service_analysis.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/runtime/service_analysis.py#L264)
- 这个上限和视觉上下文 pipeline 的 `multimodal.max_images=50` 不是同一个概念

### 各层 Cutoff

按链路顺序看，当前真实会生效的 cutoff 如下：

1. 收图前置过滤
   - 单图体积超过 `4MB` 直接跳过，见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L579)
   - 同一封邮件内按 `data_url` 去重，见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L574)
2. 本地 prescreen cutoff
   - 最短边 `< 90`
   - 面积 `< 25000`
   - 长宽比 `>= 8.0`
   - 文件名命中 `logo/header/footer/spacer/divider/banner/signature/icon`
   - 规则定义见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L9) 和 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L159)
3. Step 1 总量上限
   - `selected_images = prioritized_candidates[:max_multimodal_images]`
   - 当前上限是 `50`
   - 见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L664)
4. 轻分类批次 cutoff
   - 每批 `6` 张图
   - 并发由 `classification_concurrency` 控制
   - 见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L902)
5. 深分析入选 cutoff
   - 只分析 `narrative_priority != "skip"` 的图
   - 过滤空 `image_type`、`low_value_visual` 和 `decorative`
   - 见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L1029)
6. 深分析数量上限
   - `max_deep_analysis_images` 为正整数时，按优先级截到前 N 张
   - 当前值为不限量
   - 见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L1044)
7. 单图深分析输出 cutoff
   - `supporting_details` 最多保留 `3` 条
   - 见 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L1167)
8. 主 LLM 直连多模态 blocks 上限
   - `service_analysis` 当前最多塞 `20` 张图
   - 见 [`app/runtime/service_analysis.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/runtime/service_analysis.py#L40)

---

## 2. 主入口

图片链路主入口在 [`app/pipeline/multimodal_pipeline.py`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py)：

- `collect_multimodal_images_for_analysis()`
- `run_multimodal_image_analysis_session()`
- `classify_multimodal_images_lightweight_for_pipeline()`
- `deep_analyze_multimodal_images_for_pipeline()`
- `build_email_visual_context_map()`

邮件级入口在 [`build_email_visual_context_map_for_analysis()`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L1222)。

完整顺序是：

1. 先收集原始图片并做本地预筛
2. 对留下来的图片做轻分类，得到 `image_type + direct_market_signal`
3. 把高价值图做深分析，得到结构化视觉证据
4. 再聚合成邮件级视觉上下文

---

## 3. Step 1: Collect + Prescreen

### 3.1 入口和职责

入口函数：

- [`collect_multimodal_images_for_analysis()`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L318)

职责：

- 从 `attachments` 收图片
- 从正文 `data:image` 抽内嵌图
- 去重
- 过滤超大图
- 跑本地 `prescreen_multimodal_image()`
- 根据数量上限形成 `selected_images`

需要注意：

- “图片入库”不是先发生，再进入 Step 1
- 真实顺序是先 `collect + prescreen`
- 然后把 Step 1 的输出写入 `email_images`

### 3.2 图片来源

当前会扫描两类来源：

- `attachment`
- `inline`

其中：

- `attachment` 来自邮件 `attachments`
- `inline` 来自正文里的 `data:image/...` 内嵌图

如果正文只是 `cid:` 引用，而图片实际在附件里，那么仍然按 `attachment` 进入链路。

### 3.3 去重和大小限制

同一封邮件内，按 `data_url` 去重。

超过 `MAX_MULTIMODAL_IMAGE_BYTES` 的图不进入后续链路。当前阈值是：

- `4 * 1024 * 1024`
- 即 `4MB`

### 3.4 Step 1 输出字段

`selected_images` 里的正式字段如下：

```json
{
  "image_key": "",
  "email_index": 0,
  "subject": "",
  "filename": "",
  "data_url": "",
  "kind": "attachment|inline",
  "source_location": "attachment|inline",
  "content_type": "",
  "size": 0,
  "prescreen_result": "candidate|low_priority",
  "prescreen_reasons": [],
  "sha256": ""
}
```

字段说明：

- `image_key`
  - 附件图格式：`attachment:{email_index}:{attachment_image_index}`
  - 内嵌图格式：`inline:{email_index}:{inline_index}`
- `prescreen_result`
  - `selected_images` 里只会出现 `candidate` 或 `low_priority`
  - `drop` 的图片不会进入 `selected_images`

### 3.5 邮件级统计字段

`collect_multimodal_images_for_analysis()` 还会按邮件输出统计：

```json
{
  "total_images": 0,
  "candidate_images": 0,
  "dropped_images": 0,
  "deprioritized_images": 0,
  "selected_images": 0,
  "skipped_due_to_cap": 0
}
```

### 3.6 `prescreen_result` 枚举

当前只有 3 种：

- `drop`
- `low_priority`
- `candidate`

语义：

- `drop`
  明显低价值或异常，直接丢弃
- `low_priority`
  价值偏低，但仍可以继续留在候选集合里
- `candidate`
  正常候选图，进入后续链路

### 3.7 `prescreen_reasons` 枚举

当前代码里有 5 个 reason：

- `low_value_name_pattern`
- `tiny_edge`
- `very_small_area`
- `extreme_banner_aspect`
- `tiny_file`

含义如下：

- `low_value_name_pattern`
  文件名命中低价值命名模式，如 `logo / header / footer / banner / icon`
- `tiny_edge`
  宽高中的较小边 `< 90`
- `very_small_area`
  面积 `< 25000`
- `extreme_banner_aspect`
  长宽比极端，`max(width / height, height / width) >= 8.0`
- `tiny_file`
  文件体积 `< 1024 bytes`

### 3.8 `prescreen_result` 判定规则

当前规则是本地硬编码，不依赖模型。

直接 `drop`：

1. 命中 `low_value_name_pattern`
2. 同时满足 `tiny_file` 且 `very_small_area` 或 `tiny_edge`
3. 同时满足 `extreme_banner_aspect` 且 `very_small_area` 或 `tiny_edge`

判为 `low_priority`：

- 在 `tiny_file / very_small_area / tiny_edge / extreme_banner_aspect` 这 4 个 reason 里命中至少 2 个

其余情况：

- 一律为 `candidate`

### 3.9 Step 1 和数据库的关系

Step 1 输出会写入 `email_images`。

也就是说：

- `drop` 的图不会进入 `email_images`
- `candidate` 和 `low_priority` 会进入 `email_images`

这一层还不会写入：

- `image_type`
- `role_in_email`
- 深分析结果

这些要等后续步骤补齐。

---

## 4. Step 2: Lightweight Classification

### 4.1 入口和职责

入口函数：

- [`classify_multimodal_images_lightweight_for_pipeline()`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L982)

职责：

- 只判断图片本身属于什么类型
- 不做深层语义提炼
- 不直接生成邮件级视觉证据

Step 2 不再筛图，只给 Step 1 留下来的 `selected_images` 打标签。

### 4.2 输入

这一步按批次读取 `selected_images`。

当前批次大小：

- `batch_size = 6`

每张图送给模型时当前只提供：

- `image_key`
- 图片本身 `data_url`

不会额外补：

- `filename`
- `kind`
- `email_index`
- `subject`
- `from_name / from_addr`
- `body_context / local_body_context`

也就是说，这一步是 image-only 轻分类。

这里的设计原则是：

- 轻分类 prompt 要尽量减少上下文污染
- 只保留回填结果必需的信息，例如 `image_key`
- 像 `filename`、`kind`、`subject`、`dimensions` 这类弱辅助字段，默认不送给模型；只有在验证能稳定提升效果时才重新引入

### 4.3 输出

轻分类结果是一个按 `image_key` 建索引的字典：

```json
{
  "attachment:1:1": {
    "image_type": "social_signal_visual",
    "direct_market_signal": "true",
    "role_in_email": "market_signal"
  }
}
```

其中：

- `image_type` 来自模型判断
- `direct_market_signal` 来自模型判断，只回答“这张图本身是否直接传达明确市场信号”
- `role_in_email` 由代码根据 `image_type + direct_market_signal` 映射

### 4.4 `image_type` 枚举

当前只有 5 个合法值：

- `editorial_framing_visual`
- `social_signal_visual`
- `research_framework_chart`
- `market_data_chart`
- `low_value_visual`

语义如下：

- `social_signal_visual`
  社交平台帖子、媒体账号或 KOL 截图、互动数据、平台 UI、截图式传播语境
- `market_data_chart`
  柱状图、折线图、价格图、终端图、相对表现图或其他市场数据图
- `research_framework_chart`
  sell-side exhibit、矩阵图、象限图、positioning map、风险比较、机构框架图
- `editorial_framing_visual`
  封面包装、专题 framing、人物或主题视觉塑造
- `low_value_visual`
  信息密度低、重复、装饰性强、后续价值很低

### 4.5 `image_type + direct_market_signal -> role_in_email` 映射规则

当前映射是代码硬编码规则：

```text
research_framework_chart + true -> market_signal
research_framework_chart + false -> supporting_evidence
market_data_chart + true -> market_signal
market_data_chart + false -> supporting_evidence
social_signal_visual -> market_signal
editorial_framing_visual -> main_narrative
low_value_visual -> decorative
```

这一步不会让模型自由输出 `role_in_email`。

设计意图：

- `image_type` 负责回答“这是什么图”
- `direct_market_signal` 负责回答“这张图本身是否直接承载强市场信号”
- `role_in_email` 继续由代码收口，避免让轻分类阶段变成自由叙事判断

### 4.6 Step 2 Prompt

当前轻分类 `system_prompt`：

```text
你负责给图片做轻分类。只根据图片本身判断，只输出 JSON。

可选 `image_type` 只有：
- editorial_framing_visual
- social_signal_visual
- research_framework_chart
- market_data_chart
- low_value_visual

同时返回 `direct_market_signal`：
- true: 图片本身直接传达明确市场信号
- false: 其他情况；如果不确定，一律 false

输出要求：
- 只输出合法 JSON
- 顶层结构固定为 {"images": [...]}
- 每张图返回 `image_key`、`image_type`、`direct_market_signal`
```

当前批次级 `user_prompt`：

```text
请只根据图片本身判定每张图片的 image_type 和 direct_market_signal，并输出 JSON。
```

每张图额外附带：

```text
image_key: ...
请先忠实读图，再返回 image_type 和 direct_market_signal。
```

这里特意保持极简：

- 这一步的核心目标是“快、稳、粗筛”
- 不追求在轻分类阶段完成复杂解释
- 如果分布已经可用，就不要继续拉长 prompt 以换取边际精度

### 4.7 视觉模型链和 fallback

图片轻分类与文本主模型分离，轻分类和深分析也分开用模型。

当前默认模型链：

1. 文本主链：文本主模型配置，独立于图片链
2. 图片轻分类：`qwen-vl-max-latest`
3. 图片轻分类备用：`qwen-vl-plus-latest`
4. 图片深分析：`qwen3-vl-235b-a22b-thinking`
5. 图片深分析备用：`qwen-vl-max-latest` -> `qwen-vl-plus-latest`

规则：

- 轻分类固定优先走快模型
- 深分析保留强模型
- 单个批次先尝试该阶段主模型
- 当前批次失败时再切到该阶段备用模型
- 只影响当前批次，不会把整轮直接判死

### 4.8 异常处理

批次失败：

- 当前批次会按视觉链顺序切到备用模型
- 如果所有视觉模型都失败，这个批次没有分类结果

JSON 解析失败：

- 当前批次视为无标签
- 不生成脏标签

非法 `image_type`：

- 该条结果直接丢弃
- 不进入 `role_in_email` 映射

---

## 5. Step 3: Deep Analysis

### 5.1 入口和职责

入口函数：

- [`deep_analyze_multimodal_images_for_pipeline()`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L1186)

职责：

- 把高价值图片转成结构化文本信息
- 告诉后续链路“这张图说了什么”
- 不替正文做判断，不联读邮件主线，不脑补图外事实

### 5.2 哪些图会进入深分析

当前只分析高价值图：

- `narrative_priority != "skip"`
- `image_type` 不是空，也不是 `low_value_visual`
- `role_in_email != "decorative"`

`narrative_priority` 由 `image_type + role_in_email` 推导：

- `low_value_visual` 或 `decorative` -> `skip`
- `main_narrative` / `market_signal` / inline 主视觉类型 -> `core`
- 其余高价值图 -> `supporting`

### 5.3 当前输入

深分析阶段只给模型最小输入：

```text
image_key: ...
image_type: ...
role_in_email: ...
```

再加上图片本身。

不会再传：

- `email_index`
- `subject`
- `filename`
- `from_name / from_addr`
- `body_context / local_body_context`

### 5.4 当前输出

当前统一输出结构是：

```json
{
  "image_key": "",
  "core_signal": "",
  "supporting_details": []
}
```

字段含义：

- `core_signal`
  这张图最核心在说什么
- `supporting_details`
  用 1 到 3 条补充信息支撑 `core_signal`

当前已经移除：

- 旧的“支持正文 claim”字段
- 旧的“不确定性”字段
- 旧的“置信度”字段

### 5.5 Shared Prompt

当前共享 `system_prompt`：

```text
你负责把图片转成结构化文本信息，告诉我这张图说了什么。
```

当前共享输出约束：

```text
只根据图片本身输出 JSON，顶层固定为 {"images": [...]}。
字段固定为：image_key / core_signal / supporting_details。
不能新增字段；无内容时返回空字符串或 []。
```

### 5.6 类型化引导

当前第三步的 prompt 不是让模型把“读图过程”写出来，而是：

- 模型内部先按步骤识别图面结构
- 最终对外只输出结论和补充信息

#### `research_framework_chart`

重点：

- 框架、排序维度、bucket、对象的位置关系
- 对二维定位矩阵、仓位情绪图、象限图额外识别：
  - 横轴和纵轴
  - 四个象限
  - 代表性 ticker
  - 显式标签
  - 箭头变化

输出要求：

- `core_signal` 直接写最重要的结论
- 对象限图优先写：
  - 最强共识在哪里
  - 最大分歧在哪里
  - 哪些票在边际改善或恶化
- `supporting_details` 再补轴含义、象限标签、代表性 ticker、拥挤区、战场区和箭头变化

#### `market_data_chart`

重点：

- 图在比较什么对象
- 主要方向是走强、走弱、分化还是收敛
- 哪个对象相对更强、哪个对象相对更弱
- 有没有明显拐点、放量、回撤、修复或趋势变化

输出要求：

- `core_signal` 直接写最重要的市场结论
- 优先回答谁更强、谁更弱、分化有没有扩大或收敛
- `supporting_details` 再补比较对象、时间段、方向性细节、相对表现和可见数字

#### `social_signal_visual`

重点：

- 哪个平台、哪类账号、什么传播场景
- 核心传播内容是什么
- 传播 framing 偏什么方向
- 有没有浏览量、点赞、转发、时间戳、截图 UI 这类可见线索

输出要求：

- `core_signal` 直接写最重要的传播结论
- 优先回答谁在传、在传什么、市场会从这张图感受到什么信号
- `supporting_details` 再补平台、账号、互动量、时间戳和截图里的直接证据

#### `editorial_framing_visual`

重点：

- 标题、封面、版式、人物或视觉主体
- 主题被包装成什么叙事
- 图面强调的是冲突、机会、风险还是情绪
- 哪些元素在推动这种 framing

输出要求：

- `core_signal` 直接写最重要的 framing 结论
- 优先回答它把主题包装成了什么故事或市场情绪
- `supporting_details` 再补标题措辞、封面元素、排版重点、视觉对比和附带文字信息

### 5.7 深分析和数据库的关系

深分析结果会写入 `image_analysis_results`。

当前表结构只保留：

- `core_signal`
- `supporting_details`

同时，深分析结果会回填到统一图片对象，供邮件级聚合使用。

---

## 6. Step 4: 聚合成邮件级视觉上下文

虽然本文重点是前三步，但主链路最后还会做一次邮件级收口。

入口函数：

- [`build_email_visual_context_map()`](/Users/yyukichen/Desktop/email-service-research-assistant/app/pipeline/multimodal_pipeline.py#L752)

聚合规则：

- 偏主叙事的图片进入 `Visual Context`
- 偏支撑证据的图片进入 `Visual Evidence`
- 聚合时只使用：
  - `core_signal`
  - `supporting_details`
- 邮件级 `visual_status` 只保留两档：
  - `ready`：已经拿到至少一条可用视觉证据
  - `empty`：没有任何可用视觉证据
- 默认不对 `inline_visual_contexts` 和 `supporting_visual_evidence` 设条数上限
- 如果配置了 `multimodal.max_inline_visual_contexts` 或 `multimodal.max_supporting_visual_evidence`，聚合时才会按配置截断

如果 `core_signal` 为空，这张图不会进入邮件级视觉上下文。

---

## 7. 当前明确移除的能力

当前主链路已经主动移除这些旧路径或旧字段：

- 图片 enrich 上下文
- `from_name / from_addr`
- `body_context / local_body_context`
- 旧的“支持正文 claim”字段
- 旧的“不确定性”字段
- 旧的“置信度”字段

这样做的目的，是把图片链路收成更清晰、更容易验收的最小闭环：

1. 先筛图
2. 再分类型
3. 再把高价值图转成结构化结论
4. 最后才把这些结果喂给邮件级分析
