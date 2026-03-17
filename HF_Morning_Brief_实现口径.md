# HF Morning Brief 当前实现口径

这份文档用于说明当前代码里的真实实现口径，方便后续 review `prompt / schema / 渲染模板 / 排序逻辑` 时快速对照。

说明：
- 这不是对外产品介绍。
- 这份文档描述的是“当前代码如何工作”。
- 如果 README、角色文档与代码有冲突，以代码实现和本说明为准，再决定是否同步更新其他文档。

## 1. 文件信息

- 最终产物文件名：`AI_Morning_Brief_YYYYMMDD.html`
- 内部会额外保留一份带时间戳的归档文件：`AI_Morning_Brief_YYYYMMDD_HHMMSS.html`
- 报告最终格式：HTML
- 阅读时间显示保留，当前口径按 `8 分钟上限`

## 2. 全局排序原则

### 2.1 本地排序的模块

- `Key Coverage`
- `Actionable Ideas`

当前默认排序键：
1. `coverage_count` 降序
2. `global_score` 降序
3. `priority_rank` 升序

解释：
- `coverage_count` 代表共识强度/覆盖频率
- `global_score` 代表模型给出的重要性强度分
- `priority_rank` 代表模型主观排序位次，目前只作为后置微调项

### 2.2 不做人为重排的模块

- `Local News`
- `Peripheral Intelligence`
  - `mapped_events`
  - `cross_market_signals`

这些模块默认尊重模型原始顺序，不做本地二次排序。

### 2.3 Executive Summary 的排序来源

- `Executive Summary.market_background`
  - 主要信模型输出
  - 本地只做空值兜底
- `Executive Summary.key_signals`
  - 主要来自排序靠前的 `Key Coverage`
  - 再补少量特别强的 `Local News / Peripheral`
  - 最后才用模型原始 `key_signals` 填空

### 2.4 未来预留口子

后续如做人工标注、模型评测，或允许分析师配置关注板块/主题：
- `Executive Summary`
- `Key Coverage`

可重新评估是否让主观排序信号更强。

## 3. 内容架构

### 3.1 固定模板骨架

- `Executive Summary`
- `Key Coverage | 核心事件与市场观点`
- `Local News | 容易被忽略的信号`
- `Peripheral Intelligence | 外围信息/类比映射`
- `Actionable Ideas`

### 3.2 Key Coverage

单条结构固定为：
- `核心事实`
- `市场怎么看`
- `投资启示`

当前口径：
- 不强制每条都三维完整
- 不为了模板完整性硬凑内容

### 3.3 Local News

单条结构固定为：
- `信号`
- `为什么重要`
- `Action`

当前口径：
- 不强制必须包含股价表现
- 如果股价表现有助于理解，可由模型自行纳入

### 3.4 Peripheral Intelligence

结构固定为两块：
- `非核心公司事件 -> 核心洞察`
- `跨市场信号`

这部分更强调映射价值，不强制每条都显式落成投资结论。

### 3.5 Actionable Ideas

结构固定为：
- `短期（1-5天）`
- `中期（1-4周）`
- `Catalysts to Watch`
- `Bottom Line`

当前口径：
- 要求更具体
- 但先只通过 prompt 强化
- 不做本地硬校验，不做本地自动改写

## 4. 图片处理

### 4.1 当前实现

- 附件图片会走多模态
- 正文内嵌图片也会走多模态
- 文本和图片在同一个请求里联合理解
- 最终报告不展示原图，只展示提炼后的 insight

### 4.2 解读原则

- 图表类图片：提炼数据/图表结论
- 非图表类图片：允许做深度解读
  - 可从场合、人物、时机、公关策略、信号强度等角度理解

### 4.3 已知待优化点

- 长上下文拆批时，图片目前只在子批次阶段做多模态理解
- 最终合并阶段可能出现图像 insight 衰减
- 后续可考虑显式保留 `image_insights / image_evidence`

## 5. 视觉格式

### 5.1 已本地硬编码的部分

- 顶部 meta：
  - `Prepared by: AI Research Assistant`
  - `Source: ...`
  - `Reading time: ...`
- 标题日期统一为系统本地日期
- `Catalysts to Watch` 统一为标题
- `短期 / 中期` 统一为同层级标题
- `投资启示 / 信号 / 为什么重要 / Action` 统一为独立加粗标签
- 标题里不允许 `highlight`

### 5.2 颜色口径

样式真源在 `reference_css.txt`，当前关键颜色包括：
- 框架主色：`#146785`
- highlight：`#31A8C4`
- 正文：`#1a1a1a`
- meta：`#666`

### 5.3 emoji

- emoji 已做本地禁用
- 最终 HTML 会统一清除 emoji，避免视觉风格漂移

## 6. 写作风格

### 6.1 简洁原则

当前主要交给模型，通过 `role guidance + governance` 强化：
- 读者已经知道大部分基础事实
- 价值在于提炼主线、统一归因、压缩噪音
- `核心事实` 尽量一句话
- trivial 内容默认降权

本地不做句子级自动压缩器。

### 6.2 结构化表达

结构化表达主要由本地模板保证，不再依赖模型自由发挥 HTML。

### 6.3 Actionable 的具体性

当前口径：
- 通过 prompt 要求尽量写清对象、逻辑、催化/时间点
- 不做本地硬校验
- 不做本地自动改写

### 6.4 完整性

当前不做以下强制完整性要求：
- 每个 `Key Coverage` 都必须三维完整
- 每条 `Local News` 都必须字段齐全

目的是避免为了模板完整而灌水。

## 7. 质量检查清单

### 7.1 适合做硬规则的

- 文件名规范
- 无 emoji
- highlight 不滥用纯数字
- 颜色与模板样式正确
- `Actionable Ideas` 区分短期/中期

### 7.2 不适合做硬规则的

- 每个核心事件都三维完整
- 每条 `Local News` 都字段齐全
- 阅读时间 3 分钟内

这些更适合作为：
- 设计目标
- prompt 约束
- 人工 review checklist

## 8. 关键注意事项

- 核心事实和观点必须分离
- 归因必须保留真实主语
- trivial 内容默认降权
- 排序只在该排序的层级执行
- 卖方 comments 尽量提炼成：
  - `source`
  - `stance`
  - `thesis`

## 9. Prompt 分工

### 9.1 `get_hf_role_guidance()`

负责：
- 像谁
- 怎么想
- 怎么写

当前采用的角色口径是：
- `Persona A`
- 面向重点覆盖 `2-3` 个板块分析师的对冲基金盘前晨报编辑

### 9.2 `get_report_prompt_governance()`

负责：
- 原则
- 底线
- 提醒

例如：
- 事实/观点分离
- 归因纪律
- trivial 内容降权

### 9.3 `get_fixed_report_schema_prompt()`

负责：
- 输出结构
- 字段定义
- 模块边界
- 排序字段
- highlight 字段

### 9.4 `user_prompt`

负责：
- 本次任务
- 本次输入内容

不再重复长期稳定规则。

## 10. 当前实现哲学

当前整体分工是：
- 模型负责：
  - 内容筛选
  - 主次排序
  - 归因判断
  - 高亮短语选择
  - 结构化 JSON 输出
- 本地代码负责：
  - 固定模板渲染
  - 结构校验
  - 少量兜底
  - 防止明显越界

目标不是让本地代码成为“第二个编辑部”，而是让它成为稳定的护栏和模板真源。
