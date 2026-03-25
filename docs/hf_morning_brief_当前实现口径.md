# HF Morning Brief 当前实现口径

这份文档用于说明当前代码里的真实实现口径，方便后续 review `prompt / schema / 文本构造 / 排序逻辑 / 渲染模板` 时快速对照。

说明：
- 这不是对外产品介绍。
- 这份文档描述的是“当前代码如何工作”。
- 如果 README、角色文档与代码有冲突，以代码实现和本说明为准，再决定是否同步更新其他文档。

## 1. 文件信息

- 最终产物文件名：`AI_Morning_Brief_YYYYMMDD.html`
- 内部会额外保留一份带时间戳的归档文件：`AI_Morning_Brief_YYYYMMDD_HHMMSS.html`
- 报告最终格式：HTML
- 阅读时间显示保留，当前口径按 `8 分钟上限`

## 2. 内容架构

### 2.1 固定模板骨架

- `Executive Summary`
- `Key Coverage | 核心事件与市场观点`
- `Local News | 容易被忽略的信号`
- `Peripheral Intelligence | 外围信息/类比映射`
- `Actionable Ideas`

### 2.2 Key Coverage

单条结构固定为：
- `核心事实`
- `市场怎么看`
- `投资启示`

当前口径：
- 不强制每条都三维完整
- 不为了模板完整性硬凑内容

### 2.3 Local News

单条结构固定为：
- `信号`
- `为什么重要`
- `Action`

当前口径：
- 不强制必须包含股价表现
- 如果股价表现有助于理解，可由模型自行纳入

### 2.4 Peripheral Intelligence

结构固定为两块：
- `非核心公司事件 -> 核心洞察`
- `跨市场信号`

这部分更强调映射价值，不强制每条都显式落成投资结论。

### 2.5 Actionable Ideas

结构固定为：
- `短期（1-5天）`
- `中期（1-4周）`
- `Catalysts to Watch`
- `Bottom Line`

当前口径：
- 要求更具体
- 但先只通过 prompt 强化
- 不做本地硬校验，不做本地自动改写

## 3. 图片链路与正文回填

### 3.1 当前图片链路

当前不是“文本和图片在同一个请求里联合理解”，而是分成独立链路：
1. 图片收集
2. 轻分类
3. 深分析
4. 将图片分析结果回填进正文
5. 文本模型只消费回填后的正文，不再直接看原图

### 3.2 轻分类与深分析

- 轻分类固定走快模型
- 深分析固定走强模型
- 轻分类输出：
  - `image_type`
  - 中间信号判断字段（用于 role 映射）
- 深分析输出：
  - `core_signal`
  - `supporting_details`

### 3.3 正文回填口径

当前正文回填只使用图片深分析里的 `core_signal`：
- `supporting_details` 不回填进正文
- 没命中的图片不再写“图文已省略”之类占位文案
- 回填目标是让送给文本模型的正文尽量高信息密度

### 3.4 回填位置

- inline / `cid:` 图片优先按原正文位置回填
- 找不到稳定位置的图片，会作为 residual 文本追加到正文尾部
- 最终送给文本模型的是 `_analysis_body`

## 4. 文本分析输入构造

### 4.1 正文清洗

在进入文本分析前，会先做：
- 去掉 HTML 标签
- 去掉脚本、样式、长 base64 编码
- 去掉头部噪音
- 去掉尾部签名、免责声明、法律声明
- 把原图标签替换成可回填的位置标记

### 4.2 Final Analysis Body

`Final Analysis Body` 是文本模型真实消费的正文输入：
- 先清洗正文
- 再把可用图片 `core_signal` 回填回去
- 再去掉残留图片占位

验收时应该优先看 `Final Analysis Body`，而不是只看中间调试字段。

### 4.3 分批逻辑

- 单封邮件内部不再做文本切段
- 多封邮件按 `_analysis_body_len` 做均衡分桶
- 不再有“邮件数 <= 2 直接不分批”的豁免
- 只有 `<= 1` 封邮件时才固定单批

### 4.4 Batch / Merge 两阶段

当上下文过长时，文本分析分两轮：
1. `batch_summary`
   - 每个 batch 各调一次文本模型
   - 输出结构化中间摘要 `topics`
2. `merge`
   - 再调一次文本模型
   - 输入各 batch 的中间摘要
   - 输出最终晨报 JSON

## 5. Prompt 装配口径

### 5.1 单封邮件最终报告

单封邮件、无需拆批时：
- 仍然走完整版 `build_report_system_prompt()`
- 更适合保留完整共享规则

### 5.2 Batch Prompt

当前 `batch` 阶段已经改成瘦身装配器：
- 运行时直接使用 `build_batch_system_prompt()`
- 不再额外拼 `get_batch_summary_stage_rules()`
- 完整共享 prompt 不再直接进入 batch 运行时 prompt

当前 batch prompt 关注：
- 中间摘要任务定义
- 归因纪律
- 主题切分与归槽
- `batch_summary` JSON 结构

### 5.3 Merge Prompt

当前 `merge` 阶段也改成瘦身装配器：
- 运行时直接使用 `build_merge_system_prompt()`
- 不再额外拼 `get_merge_stage_rules()`
- 完整共享 prompt 不再直接进入 merge 运行时 prompt

当前 merge prompt 关注：
- 最终整合任务定义
- 归因纪律
- 合并纪律
- 最终晨报 schema

### 5.4 共享规则的角色

原有共享规则函数仍然保留，但更偏向：
- 总规则库
- 单封邮件最终报告 prompt
- 设计参考

不再默认直接进入 batch / merge 运行时 prompt。

## 6. 全局排序原则

### 6.1 图片链路排序

图片链路里存在两层优先级：
- 图片收集阶段排序
  - 决定哪些图片先进入图片链
- 深分析阶段排序
  - 决定哪些图片更优先送强模型

会综合参考：
- `image_type`
- `role_in_email`
- `narrative_priority`
- 图片大小
- 发现顺序

### 6.2 文本分批排序

分批阶段不是内容排序，而是长度均衡：
- 长邮件优先分配到当前最短 bucket
- batch 内再按 `_analysis_index` 排回稳定顺序

### 6.3 最终报告本地排序模块

当前本地显式排序的模块主要是：
- `Key Coverage`
- `Actionable Ideas`

当前默认排序键：
1. `coverage_count` 降序
2. `global_score` 降序
3. `priority_rank` 升序

解释：
- `coverage_count` 代表共识强度 / 覆盖频率
- `global_score` 代表模型给出的重要性强度分
- `priority_rank` 代表模型主观排序位次，目前只作为后置微调项

### 6.4 不做人为重排的模块

- `Local News`
- `Peripheral Intelligence`
  - `mapped_events`
  - `cross_market_signals`

这些模块默认尊重模型原始顺序，不做本地二次排序。

### 6.5 排序字段来源

`batch_summary` 中间结果主要提供：
- `coverage_count`
- `merge_key`
- `time_horizon`
- `target_slot`

最终 `merge` 结果主要提供：
- `priority_rank`
- `coverage_count`
- `global_score`

本地排序主要消费的是最终 `merge` 结果里的排序字段。

### 6.6 Executive Summary 的排序来源

- `Executive Summary.market_background`
  - 主要信模型输出
  - 本地只做空值兜底
- `Executive Summary.key_signals`
  - 主要来自排序靠前的 `Key Coverage`
  - 再补少量特别强的 `Local News / Peripheral`
  - 最后才用模型原始 `key_signals` 填空

## 7. 视觉格式

### 7.1 已本地硬编码的部分

- 顶部 meta：
  - `Prepared by: AI Research Assistant`
  - `Source: ...`
  - `Reading time: ...`
- 标题日期统一为系统本地日期
- `Catalysts to Watch` 统一为标题
- `短期 / 中期` 统一为同层级标题
- `投资启示 / 信号 / 为什么重要 / Action` 统一为独立加粗标签
- 标题里不允许 `highlight`

### 7.2 颜色口径

样式真源在 `reference_css.txt`，当前关键颜色包括：
- 框架主色：`#146785`
- highlight：`#31A8C4`
- 正文：`#1a1a1a`
- meta：`#666`

### 7.3 emoji

- emoji 已做本地禁用
- 最终 HTML 会统一清除 emoji，避免视觉风格漂移

## 8. 写作风格

### 8.1 简洁原则

当前主要交给模型，通过 prompt 强化：
- 读者已经知道大部分基础事实
- 价值在于提炼主线、统一归因、压缩噪音
- `核心事实` 尽量一句话
- trivial 内容默认降权

本地不做句子级自动压缩器。

### 8.2 结构化表达

结构化表达主要由本地模板保证，不再依赖模型自由发挥 HTML。

### 8.3 Actionable 的具体性

当前口径：
- 通过 prompt 要求尽量写清对象、逻辑、催化 / 时间点
- 不做本地硬校验
- 不做本地自动改写

### 8.4 完整性

当前不做以下强制完整性要求：
- 每个 `Key Coverage` 都必须三维完整
- 每条 `Local News` 都必须字段齐全

目的是避免为了模板完整而灌水。

## 9. 质量检查清单

### 9.1 适合做硬规则的

- 文件名规范
- 无 emoji
- highlight 不滥用纯数字
- 颜色与模板样式正确
- `Actionable Ideas` 区分短期 / 中期

### 9.2 不适合做硬规则的

- 每个核心事件都三维完整
- 每条 `Local News` 都字段齐全
- 阅读时间 3 分钟内

这些更适合作为：
- 设计目标
- prompt 约束
- 人工 review checklist

## 10. 当前实现哲学

当前整体分工是：
- 模型负责：
  - 内容筛选
  - 主次排序
  - 归因判断
  - 高亮短语选择
  - 结构化 JSON 输出
- 本地代码负责：
  - 正文清洗
  - 图片回填
  - 分批
  - 固定模板渲染
  - 结构校验
  - 少量兜底
  - 防止明显越界

目标不是让本地代码成为“第二个编辑部”，而是让它成为稳定的护栏和模板真源。
