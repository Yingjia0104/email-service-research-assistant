# A 组报告：纯文本基线

- HTML 版本：`experiment_report_a_text_only.html`

## 运行摘要

```json
{
  "group": "A",
  "mode": "纯文本基线",
  "email_count": 4,
  "total_runtime_seconds": 299.433,
  "non_llm_runtime_seconds": 0.037,
  "num_llm_calls": 3,
  "llm_runtime_seconds": 299.396,
  "avg_llm_call_seconds": 99.799,
  "median_llm_call_seconds": 86.959,
  "models_used": [
    "qwen3-max"
  ],
  "stage_summary": {
    "report_generation": {
      "count": 3,
      "duration_seconds": 299.396,
      "models": [
        "qwen3-max"
      ],
      "multimodal_calls": 0,
      "success_count": 3
    }
  },
  "image_summary": {
    "total_images": 53,
    "dropped_images": 3,
    "deprioritized_images": 0,
    "sent_images": 50
  },
  "actual_skipped_images": 53
}
```

## 报告正文（纯文本抽取）

AI Morning Brief | 2026-03-26

AI Morning Brief | 2026-03-26

Prepared by: AI Research Assistant | Source: MS + JPM + BofA | Reading time: 8 mins

Executive Summary

市场大背景: GTC/OFC会议临近，AI硬件与软件生态进入密集验证期；多条技术路径（光/铜、SRAM/HBM）分化显现，市场聚焦可交易信号。

关键信号:

NVDA GTC/OFC前瞻：光铜路径分化 + Blackwell大规模部署 + Feynman路线图
META Avocado延期至5月，Gemini授权可能性极低
BESI获LRCX/AMAT收购兴趣，先进封装需求激增
ADBE CEO离职叠加AI freemium拖累ARR，短期承压
NVDA Vera Rubin HBM4升级，头部客户采购2026年增长超80%

Key Coverage | 核心事件与市场观点

1. NVDA GTC/OFC前瞻：光铜路径分化 + Blackwell大规模部署 + Feynman路线图

核心事实

NVDA向LITE和COHR各投资20亿美元
NVDA计划在multi-rack场景采用光互联，intra-rack维持铜缆
字节跳动通过Aolani Cloud在马来西亚部署500套Blackwell系统（含约36,000颗B200芯片），投资超25亿美元
TrendForce称NVDA或在GTC展示Feynman 1nm产品，预计2028年上市

市场怎么看

观点来源立场核心论点
Morgan Stanley (Joe Moore, Meta Marshall)中性偏多光模块（LITE/COHR/GLW）与高速连接器（CRDO/APH）存在路径分化交易机会；市场已部分预交易该主题
Morgan Stanley (Shawn Kim)澄清误读SRAM与HBM为互补关系，MU等HBM供应商需求逻辑未受根本冲击

投资启示

关注GTC keynote（3/16 14:00 ET）及财报问答会（3/17 12:00 ET）；区分光/铜、SRAM/HBM供应链标的

2. META Avocado延期至5月，Gemini授权可能性极低

核心事实

Avocado因性能未达Gemini 3.0水平而推迟至5月发布
内部测试显示其优于Gemini 2.5但不及3.0
曾讨论临时授权Gemini但无决定
据NYT报道，延期因内部基准测试弱于竞品

市场怎么看

观点来源立场核心论点
JPMorgan (Mark Schilsky)否定传闻I HIGHLY doubt that META is going to license Gemini

投资启示

短期情绪扰动有限，但需跟踪AI资本效率叙事变化

3. BESI获LRCX/AMAT收购兴趣，先进封装需求激增

核心事实

Reuters报道称BESI吸引收购兴趣，股价欧洲盘中上涨8%
消息源指LRCX与AMAT为潜在买家，因先进芯片封装需求激增

市场怎么看

观点来源立场核心论点
Reuters / Morgan Stanley sources正面催化反映半导体后道设备在AI算力扩张周期中的战略价值提升

投资启示

跟踪并购传闻进展，关注先进封装设备板块重估机会

4. ADBE CEO离职叠加AI freemium拖累ARR，短期承压

核心事实

ADBE CEO在任职18年后将转任董事长
公司承认GenAI导致Adobe Stock图片使用加速下滑，freemium用户增长压制短期ARR
Firefly ARR环比+75%，但整体ARR短期承压致股价下跌7%

市场怎么看

投资启示

观察SaaS模式在AI转型期的ARR可持续性，短期回避

5. NVDA Vera Rubin HBM4升级，头部客户采购2026年增长超80%

核心事实

Vera Rubin预计2H发布，性能大幅提升并转向HBM4
两大ASIC用户及两大AMD潜在用户预计2026年对NVDA采购增长超80%

市场怎么看

观点来源立场核心论点
Morgan Stanley (Joe Moore)护城河稳固护城河“略有侵蚀”但被夸大，实际订单趋势强劲

投资启示

中期持有，关注HBM4供应链（如MU）及Blackwell successor节奏

Local News | 容易被忽略的信号

1. NVDA Kyber机架推高电压至800V，利好高压功率器件厂商

信号

Kyber机架功率达600kW–1MW，内部配电电压升至800V DC（传统为48–54V）

为什么重要

IFX、ON、NVTS、VRT等高压功率半导体厂商受益于新一代AI机架设计

Action

跟踪AI服务器电源架构演进，评估高压器件渗透率

2. AMZN Prime Day提前至6月下旬，调整电商季节性模型

信号

Prime Day从7月移至6月下旬，计划尚未公开

为什么重要

需调整Q2/Q3电商收入与物流模型

Action

更新AMZN季度收入拆分假设

3. CMCSA延长院线窗口至5-7个周末，影院股受益

信号

Universal立即实施5个周末独家上映，2026年1月起增至7个

为什么重要

院线收入稳定性增强，AMC/CNK/IMAX受益

Action

上调影院股Q2-Q4内容供给预期

4. NFLX被JPM重申超配，强调非AI资本开支且FCF强劲

信号

2025–2028收入CAGR +12%，经营利润CAGR +21%，FCF CAGR +22%

为什么重要

在AI资本开支压制FCF的环境下，NFLX提供稀缺的高质量现金流敞口

Action

作为非AI capex核心持仓，关注回购节奏

5. OpenAI转向Agentic购物链接导流，利好零售商与OTA

信号

OpenAI调整ChatGPT购物策略，从直接结账转为导流至零售商/OTA自有App或网站

为什么重要

AMZN、WMT、BKNG、DASH、EBAY被视为主要受益者；佣金率显著低于Google付费搜索

Action

评估AI流量增量属性及对获客ROI改善潜力

6. AAPL中国App Store佣金降至25%

信号

AAPL将于3月15日起将中国App Store佣金从30%降至25%，称系应监管要求

为什么重要

反映中国监管环境对平台抽成模式的持续压力；对整体收入影响有限

Action

计入地缘合规成本，但无需大幅调整模型

Peripheral Intelligence | 外围信息/类比映射

非核心公司事件 → 核心洞察

外围事件相关公司对Key Coverage的映射
UBER AV混合运营模式提升资产利用率UBER生态系统整合者或胜出，非单一技术最优者；商业化落地节奏或快于TSLA

跨市场信号

NemoClaw/OpenClaw或成GTC软件重点，边缘推理API流量激增

OpenClaw三周内下载量超Linux，成史上最快开源软件
Agents消耗token量达100万倍
Wired报道称NemoClaw将在GTC发布

“Agent-first”软件投资主线确立

MS认为AI代理数量将超人类员工，驱动数据基础设施、可观测性、边缘推理需求
SNOW FY27指引超预期，AKAM签署2亿美元AI推理合同，DDOG获八位数大模型订单
BofA推荐MDB、SNOW为非争议性多头

Actionable Ideas

短期(1-5天)

做多铜缆路径（CRDO/APH）vs 光模块（LITE/COHR）分化交易
布局高压功率半导体（IFX/ON/NVTS/VRT）受益Kyber 800V架构

中期(1-4周)

持有Agent-first软件组合：SNOW/AKAM/DDOG/MDB
持有NFLX作为非AI capex高质量现金流敞口

Catalysts to Watch

Catalyst时间影响标的
NVDA GTC keynote3月16日 14:00 ET验证Feynman路线图、NemoClaw发布、光铜/SRAM-HBM策略
NVDA财报问答会3月17日 12:00 ET更新Blackwell部署进度、HBM4/Vera Rubin时间表

Bottom Line: GTC窗口验证AI硬件路径分化与软件生态扩张，聚焦可交易的供应链错位与Agent基础设施主线。
