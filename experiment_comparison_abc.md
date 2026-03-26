# A/B/C 实验对比

## 总结

三组报告均围绕 2026 年 3 月 26 日的 AI 市场动态展开，结构高度一致（Executive Summary、Key Coverage、Local News、Peripheral Intelligence、Actionable Ideas、Catalysts to Watch、Bottom Line），内容主题重合度高，包括：NVDA GTC/OFC 会议前瞻、META Avocado 延期、ADBE CEO 变动、BESI 并购传闻、OpenAI 购物导流、Kyber 高压架构等。

- **A 组**（纯文本基线）：内容完整，覆盖所有核心事件，但未包含部分细节（如 SRAM LPU、INTC 合作猜测等）。
- **B 组**（正式图片链路）：在 A 的基础上增加了若干新条目（如第 6 条“NVDA或推SRAM-based LPU芯片”），并对部分事件描述更细致（如 Local News 中明确提到 InP 基板短缺、中东冲突影响材料成本）。
- **C 组**（文本+原始图片直塞主模型）：内容介于 A 与 B 之间，包含 SRAM LPU 条目和 INTC 合作 speculation，但未提 B 组中某些细节（如铜缆股“上周出现挤压”）。

## 信息增量

### B 相对 A 是否有新增信息？
**是**。  
B 组相比 A 组明确新增以下信息：
- Key Coverage 第 6 条：“NVDA或推SRAM-based LPU芯片，是否冲击MU？”（A 组无此条目）
- Local News 中增加对“中东冲突推升半导体材料成本”的详细说明（提及钨、钽、钼、镓、InP 基板短缺），A 组无此内容
- Peripheral Intelligence 中明确列出更多受益公司（如 FROG、PANW、CRWD、EQIX、AAPL 等），A 组未包含
- Actionable Ideas 中明确加入“规避ADBE短期ARR波动”等更具体的建议

### C 相对 A 是否有新增信息？
**是**。  
C 组相比 A 组新增：
- Key Coverage 第 5 条：“NVDA或推SRAM-based LPU，非HBM替代而是互补”（A 组无此独立条目，仅在 NVDA Vera Rubin 条目末尾简略提及）
- Local News 第 5 条：“NVDA与INTC合作 speculation”（A 组完全未提）
- Peripheral Intelligence 中补充了中东材料成本、UBER 混合模式细节、Vera Rubin 性能升级整合等更细颗粒度信息

> 注意：虽然 A 组在“NVDA Vera Rubin”条目中有一句“SRAM与HBM为互补关系”，但未展开为独立事件，也未提及 LPU 芯片概念，因此 C 和 B 的 SRAM/LPU 内容构成信息增量。

## 结构与可控性

- **结构一致性**：三组报告结构完全一致，章节划分、标题命名、格式排版无差异，说明 pipeline 对输出结构有强控制。
- **内容可控性**：
  - A 组为纯文本基线，仅依赖主模型生成，未引入多模态分析流程。
  - B 组启用了“正式图片链路”，包含 lightweight_classification（9 次）和 deep_analysis（51 次）阶段，理论上可从图片中提取额外上下文。但实际报告显示，其新增信息（如材料成本、LPU 芯片）未必直接来自图片——因这些属于文本性市场传闻或分析师观点，可能由多轮 LLM 推理补充。
  - C 组将全部 50 张图片直塞主模型（multimodal_calls: 2），但主模型仍为 qwen3-max（非 VL 模型），可能无法有效解析图像内容。其新增信息更可能源于提示词调整或上下文扩展，而非图片理解。

> 关键疑问：B 组的 deep_analysis 使用了 qwen-vl-max-latest 和 qwen3-vl-235b-a22b-thinking，具备多模态能力，但最终报告中的新增信息是否**可归因于图片分析**？从内容看，新增点均为文本性财经信息（如并购传闻、芯片架构、佣金率），**无法确认是否源自图片**。因此，不能断定 B 的信息增量来自图像理解。

## 耗时

- **A 组**：总耗时 299.4 秒（约 5 分钟），3 次 LLM 调用，平均每次 ~100 秒
- **B 组**：总耗时 1090.3 秒（约 18.2 分钟），63 次 LLM 调用，其中 51 次为 deep_analysis
- **C 组**：总耗时 312.8 秒（约 5.2 分钟），3 次 LLM 调用，平均每次 ~104 秒

耗时对比：
- B 比 A 多 **790.9 秒**（+264%）
- C 比 A 多 **13.4 秒**（+4.5%）

## 最终判断

- **B 相对 A 有新增信息**：✅ 是  
- **C 相对 A 有新增信息**：✅ 是  
- **B 与 C 谁更值得保留**：**不确定**

理由：  
- B 组信息最全（含 LPU 条目、材料成本细节、更多股票代码），但耗时极高（18 分钟 vs 5 分钟），且**无法确认其增量信息是否依赖图片分析**。若这些信息可通过纯文本 prompt 工程实现，则 B 的复杂 pipeline 不必要。
- C 组以极低时间成本（仅比 A 多 13 秒）实现了接近 B 的信息覆盖（含 LPU 和 INTC speculation），但缺少 B 中部分细节（如 InP 短缺、铜缆挤压等）。
- 由于**无法验证 B 的信息增量是否真正源于多模态分析**（而非更强的提示或更多推理轮次），且 C 在效率上显著优于 B，**在缺乏归因证据的情况下，无法断定 B 更值得保留**。

> 结论：若目标是**信息密度最大化**，选 B；若追求**性价比与可控性**，C 更优。但基于当前数据，**无法确定 B 的额外耗时带来了不可替代的价值**，故回答“不确定”。
