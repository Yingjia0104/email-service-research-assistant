# B 组报告：正式图片链路

- HTML 版本：`experiment_report_b_pipeline_with_images.html`

## 运行摘要

```json
{
  "group": "B",
  "mode": "正式图片链路",
  "email_count": 4,
  "total_runtime_seconds": 1090.32,
  "non_llm_runtime_seconds": 0.0,
  "num_llm_calls": 63,
  "llm_runtime_seconds": 1843.905,
  "avg_llm_call_seconds": 29.268,
  "median_llm_call_seconds": 24.853,
  "models_used": [
    "qwen-vl-max-latest",
    "qwen3-max",
    "qwen3-vl-235b-a22b-thinking"
  ],
  "stage_summary": {
    "deep_analysis": {
      "count": 51,
      "duration_seconds": 1463.531,
      "models": [
        "qwen-vl-max-latest",
        "qwen3-vl-235b-a22b-thinking"
      ],
      "multimodal_calls": 51,
      "success_count": 49
    },
    "lightweight_classification": {
      "count": 9,
      "duration_seconds": 57.968,
      "models": [
        "qwen-vl-max-latest"
      ],
      "multimodal_calls": 9,
      "success_count": 9
    },
    "report_generation": {
      "count": 3,
      "duration_seconds": 322.405,
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
  "prescreen_candidate_images": 50,
  "lightweight_classification_count": 32,
  "deep_analysis_count": 31,
  "visual_context_ready_emails": 3,
  "visual_status_distribution": {
    "ready": 3,
    "empty": 1
  },
  "classification_concurrency": 2,
  "deep_analysis_concurrency": 2,
  "lightweight_models": [
    "qwen-vl-max-latest"
  ],
  "deep_analysis_models": [
    "qwen-vl-max-latest",
    "qwen3-vl-235b-a22b-thinking"
  ],
  "image_caps_disabled": {
    "max_multimodal_images": null,
    "max_deep_analysis_images": null
  }
}
```

## 报告正文（纯文本抽取）

AI Morning Brief | 2026-03-26

AI Morning Brief | 2026-03-26

Prepared by: AI Research Assistant | Source: MS + JPM + BofA | Reading time: 8 mins

Executive Summary

市场大背景: AI硬件与模型进展主导短期交易主线，NVDA GTC/OFC会议催化光铜架构分歧；软件板块面临AI转型阵痛，管理层变动与变现效率承压。

关键信号:

META推迟Avocado模型至5月，Gemini授权传闻存疑
NVDA GTC与OFC会议催化：光互联 vs 铜缆架构
ADBE CEO离职与AI对ARR的短期冲击
NVDA GTC关键日程修正与Feynman芯片传闻
NVDA Vera Rubin（Blackwell后继）进展与竞争格局

Key Coverage | 核心事件与市场观点

1. META推迟Avocado模型至5月，Gemini授权传闻存疑

核心事实

Avocado原定3月发布，现推迟至至少5月
内部测试显示Avocado优于Gemini 2.5但弱于Gemini 3.0
曾讨论临时授权Gemini，但未做决定
META官方称重点在于技术演进轨迹而非单点性能

市场怎么看

观点来源立场核心论点
Mark Schilsky (JPM)否定Gemini授权I HIGHLY doubt that META is going to license Gemini
The NY Times事实引述Avocado因内部基准测试表现弱于竞品而推迟

投资启示

观察5月Avocado发布窗口及模型能力披露，短期不博弈Gemini授权叙事

2. NVDA GTC与OFC会议催化：光互联 vs 铜缆架构

核心事实

NVDA在GTC前投资LITE与COHR各20亿美元
NVDA与AVGO CEO均强调铜缆在intra-rack场景仍重要
NVDA计划在multi-rack场景采用光互联，intra-rack维持铜缆（APH保有socket）

市场怎么看

观点来源立场核心论点
Morgan Stanley (Joe Moore, Meta Marshall)结构性分化光模块（LITE/COHR/GLW）与高速连接器（CRDO/APH）存在结构性分化；市场已部分预交易该主题，铜缆股上周出现挤压

投资启示

跟踪GTC/OFC细节验证光铜部署节奏，关注APH/CRDO vs LITE/COHR相对表现

3. ADBE CEO离职与AI对ARR的短期冲击

核心事实

ADBE CEO在任职18年后宣布离职，将转任董事会主席
Q1财报显示Firefly ARR环比增长75%，但Adobe Stock因GenAI替代导致收入下滑超预期
免费用户快速增长压制短期ARR

市场怎么看

观点来源立场核心论点
BofA TMT / Morgan Stanley Tech负面短期软件板块面临AI转型阵痛，AI freemium模式侵蚀变现效率

投资启示

规避短期ARR波动风险，等待管理层交接清晰化及付费转化路径验证

4. NVDA GTC关键日程修正与Feynman芯片传闻

核心事实

NVDA GTC主题演讲定于3月16日14:00 ET，财报问答会移至3月17日12:00 ET
TrendForce报道称NVDA或在GTC展示1nm Feynman产品，预计2028年量产

市场怎么看

投资启示

确认GTC日程安排，关注Feynman路线图是否披露

5. NVDA Vera Rubin（Blackwell后继）进展与竞争格局

核心事实

Vera Rubin预计2026下半年发布，将升级至HBM4
两大ASIC用户及潜在AMD客户预计2026年对NVDA采购增长超80%

市场怎么看

观点来源立场核心论点
Joe Moore (MSR)正面中期尽管架构多元化趋势存在，NVDA在头部客户中的份额仍在扩张；技术代际领先仍是护城河核心

投资启示

中期持有NVDA，跟踪头部云厂商资本开支指引及Rubin订单能见度

6. NVDA或推SRAM-based LPU芯片，是否冲击MU？

核心事实

报道称NVDA可能在GTC推出基于大容量片上SRAM的LPU推理芯片
SRAM用于低延迟decode推理，HBM用于高上下文pre-fill任务

市场怎么看

观点来源立场核心论点
Shawn Kim (MSR)互补非替代SRAM是HBM的互补而非替代，对MU的HBM业务短期无直接威胁

投资启示

无需担忧MU HBM需求，区分AI工作负载内存架构差异

Local News | 容易被忽略的信号

1. OpenAI转向Agentic Shopping导流模式

信号

OpenAI调整策略，从直接结账转为导流至零售商/OTA自有App或网站；佣金率个位数%，显著低于Google付费搜索获客成本

为什么重要

若AI流量具增量性且成本更低，可改善零售/OTA单位经济；垂直AI代理或比通用助手更快捕获商业价值

Action

跟踪AMZN/WMT/BKNG/DASH/EBAY流量与转化数据变化

2. BESI获LRCX/AMAT收购兴趣

信号

Reuters及市场消息称BESI吸引LRCX与AMAT收购兴趣，因先进封装需求飙升

为什么重要

反映CoWoS等先进封装产能紧缺，设备厂商整合预期升温；BESI作为贴片机龙头战略价值凸显

Action

监控并购传闻进展及先进封装订单能见度

3. CMCSA延长院线窗口期至5-7个周末

信号

Universal立即实施5个周末独家上映，2027年1月起增至7个周末；结束疫情期间3个周末政策

为什么重要

利好AMC/CNK/IMAX等影院股，流媒体窗口压力暂缓

Action

上调影院股短期评级，跟踪内容排片与票房表现

4. AMZN将Prime Day从7月移至6月

信号

Prime Day将从7月移至6月下旬，计划尚未公开

为什么重要

需调整电商、广告、物流相关公司Q2收入模型

Action

更新AMZN及供应链Q2收入预测

5. AAPL中国App Store佣金降至25%

信号

AAPL自3月15日起将中国区App Store佣金从30%下调至25%，系与中国监管机构协商结果

为什么重要

对AAPL整体收入影响有限，但体现地缘合规灵活性，或缓解中国开发者压力

Action

小幅上调中国生态稳定性预期，不影响核心估值

6. NVDA Kyber机柜高压供电架构升级

信号

Kyber机柜为Rubin Ultra设计，功耗达600kW–1MW；内部供电电压提升至约800V DC

为什么重要

高压供电方案利好IFX、ON、NVTS、VRT等功率半导体厂商

Action

纳入功率半导体中期跟踪清单

Peripheral Intelligence | 外围信息/类比映射

非核心公司事件 → 核心洞察

外围事件相关公司对Key Coverage的映射
UBER采用AV+人类司机混合运营模式UBERAV集中部署高密度区域，人类司机覆盖边缘场景，优化资产利用率；优于纯AV运营商的资产闲置问题
中东冲突推升半导体材料成本，InP基板持续短缺LITE/COHR/II-VI钨、钽、钼价格翻倍，镓价飙升；磷化铟（InP）基板因供需失衡及出口管制持续短缺，影响光通信扩产节奏
NemoClaw（OpenClaw）生态爆发NET/AKAM/DOCN/FSLY/INTC/ARM/OKTA/SAILOpenClaw三周下载量超Linux，Agents消耗token量达1M倍；边缘推理、API流量、身份安全等环节公司受益

跨市场信号

“Agent-first”软件基础设施成中期主线

MS推荐SNOW/AKAM/DDOG/FROG/MDB为AI Agent基础设施核心标的
逻辑：AI Agent数量将超越人类员工，驱动对数据、可观测性、边缘推理、存储治理的需求
近期订单验证：AKAM获2亿美元AI推理合同，DDOG签八位数模型厂商订单

Actionable Ideas

短期(1-5天)

做多APH/CRDO vs 做空LITE/COHR（光铜分化套利）
规避ADBE短期ARR波动，等待管理层交接明朗

中期(1-4周)

超配“Agent-first”软件基础设施：SNOW/AKAM/DDOG/FROG/MDB
持有NVDA，跟踪Rubin订单及头部云厂商资本开支
超配NFLX：高FCF、无AI资本开支、定价权稳固

Catalysts to Watch

Catalyst时间影响标的
NVDA GTC大会（3月16日）2024-03-16披露光铜架构细节、SRAM LPU、NemoClaw、Feynman路线图
META Avocado模型发布（5月）2024-05验证META大模型竞争力，影响AI竞赛格局预期

Bottom Line: 聚焦NVDA GTC催化下的光铜分化与Agent基础设施主线，规避软件ARR转型阵痛，中期布局高FCF稀缺资产。
