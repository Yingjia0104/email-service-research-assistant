# C 组报告：文本+原始图片直塞主模型

- HTML 版本：`experiment_report_c_raw_images.html`

## 运行摘要

```json
{
  "group": "C",
  "mode": "文本+原始图片直塞主模型",
  "email_count": 4,
  "total_runtime_seconds": 312.826,
  "non_llm_runtime_seconds": 0.606,
  "num_llm_calls": 3,
  "llm_runtime_seconds": 312.22,
  "avg_llm_call_seconds": 104.073,
  "median_llm_call_seconds": 99.924,
  "models_used": [
    "qwen3-max"
  ],
  "stage_summary": {
    "report_generation": {
      "count": 3,
      "duration_seconds": 312.22,
      "models": [
        "qwen3-max"
      ],
      "multimodal_calls": 2,
      "success_count": 3
    }
  },
  "image_summary": {
    "total_images": 53,
    "dropped_images": 3,
    "deprioritized_images": 0,
    "sent_images": 50
  },
  "sent_images_to_main_model": 50,
  "main_model_call_count": 3,
  "main_models": [
    "qwen3-max"
  ],
  "multimodal_fallback_to_text": false,
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

市场大背景: 市场聚焦GTC/OFC会议催化与AI基础设施路径分化，同时关注模型发布延迟、软件生态演进及地缘对材料成本的影响。

关键信号:

META推迟Avocado模型至5月，Gemini授权传闻被否认
ADBE CEO离职及AI对ARR的短期冲击
NVDA GTC与OFC会议催化：光学vs铜缆路径分化
OpenAI转向Agentic Shopping导流模式，利好主流零售与OTA平台
NVDA或推SRAM-based LPU，非HBM替代而是互补

Key Coverage | 核心事件与市场观点

1. META推迟Avocado模型至5月，Gemini授权传闻被否认

核心事实

Avocado模型因性能未达内部预期（弱于Gemini 3.0）推迟至5月发布
Meta曾讨论临时授权Gemini，但未做决定
据NYT报道，内部基准测试显示性能弱于竞品

市场怎么看

观点来源立场核心论点
JPMorgan (Mark Schilsky)中性偏谨慎市场对3月发布本无强预期，延迟影响有限；高度怀疑Meta会授权Gemini作为临时方案

投资启示

短期无需过度反应，但需跟踪5月模型性能验证

2. ADBE CEO离职及AI对ARR的短期冲击

核心事实

ADBE CEO在任职18年后将转任董事长，属意外变动
Q1财报显示Firefly ARR环比增长75%，但Adobe Stock图片收入因GenAI替代加速下滑
免费用户MAU增长50%，但拖累整体ARR

市场怎么看

投资启示

短期回避，观察管理层交接与ARR企稳信号

3. NVDA GTC与OFC会议催化：光学vs铜缆路径分化

核心事实

NVDA将在GTC和OFC会议期间披露下一代AI基础设施细节
NVDA已向LITE和COHR各投资20亿美元
NVDA与AVGO CEO均强调铜缆在intra-rack场景仍具重要性

市场怎么看

观点来源立场核心论点
Morgan Stanley (Joe Moore, Meta Marshall)正面光学用于multi-rack互联，铜缆保留intra-rack连接，APH维持socket地位；市场此前过度交易光学替代逻辑，铜缆标的（CRDO、APH）获得支撑

投资启示

关注CRDO、APH等铜缆供应链标的短期修复机会

4. OpenAI转向Agentic Shopping导流模式，利好主流零售与OTA平台

核心事实

OpenAI将ChatGPT购物策略从直接结账转为导流至零售商App/网站
AMZN、WMT、BKNG、DASH、EBAY等成为主要受益者
ChatGPT佣金率（个位数%）远低于传统搜索广告获客成本

市场怎么看

观点来源立场核心论点
Morgan Stanley (Brian Nowak & Simeon Gutman)正面垂直AI代理比通用助手更易变现；零售商可获得高性价比增量流量，改善AI时代用户获取经济性

投资启示

关注AMZN、WMT、BKNG等导流受益标的中期催化

5. NVDA或推SRAM-based LPU，非HBM替代而是互补

核心事实

市场传闻NVDA将在GTC发布基于大容量片上SRAM的LPU推理芯片

市场怎么看

观点来源立场核心论点
Shawn Kim (MSR)中性SRAM用于低延迟decode阶段，HBM仍用于高context pre-fill，二者互补；对美光HBM需求短期无实质替代威胁

投资启示

维持MU持仓，无需因LPU传闻调整HBM需求预期

Local News | 容易被忽略的信号

1. BESI获LRCX与AMAT收购兴趣

信号

BESI股价在欧洲上涨8%，因路透报道称其吸引LRCX与AMAT收购兴趣

为什么重要

先进封装需求激增推动设备厂商整合预期，若属实将加速后道设备集中度提升

Action

跟踪并购传闻进展及BESI基本面验证

2. CMCSA延长院线窗口至5-7周，利好影院运营商

信号

Universal立即实施5个周末独家院线窗口，2026年起增至7个周末

为什么重要

逆转疫情期缩短窗口策略，强化影院排他性，AMC称‘极度有利’

Action

关注AMC、CNK、IMAX短期情绪催化

3. AAPL中国App Store佣金下调至25%

信号

AAPL将于3月15日起将中国App Store佣金从30%降至25%

为什么重要

体现公司在华合规姿态，小幅改善开发者生态，对整体收入影响有限

Action

视为轻微正面信号，无需大幅调整估值

4. AMZN将Prime Day从7月提前至6月下旬

信号

Amazon将年度Prime Day促销从7月移至6月下旬

为什么重要

需调整电商相关公司Q2/Q3收入与现金流模型

Action

更新AMZN及电商生态链季节性假设

5. NVDA与INTC合作 speculation：先进封装或x86 CPU

信号

市场猜测合作方向为：(1) INTC EMIB先进封装 vs Foundry前道；(2) NVDA+INTC联合开发x86 CPU

为什么重要

若属实将重塑CPU与封装格局，但目前仅为speculation

Action

保持观察，等待官方确认

6. NVDA Kyber机柜推高电压架构，利好高压功率器件厂商

信号

Kyber机柜功耗达600kW–1MW，配电电压升至约800V DC

为什么重要

高压架构将拉动IFX、ON、NVTS、VRT等功率半导体需求

Action

中期跟踪功率器件厂商订单验证

Peripheral Intelligence | 外围信息/类比映射

非核心公司事件 → 核心洞察

外围事件相关公司对Key Coverage的映射
中东冲突推升半导体材料成本NVDA, MU, KLAC, LRCX地缘冲突导致钨、钽、镓、InP衬底涨价，氦库存受监控，可能压制存储与光通信厂商利润率
UBER AV战略优势：混合模式提升资产利用率UBER, GOOGL, LYFT, TSLAUBER采用人类司机+AV混合网络，可动态分配AV至高密度区域，相比纯AV运营商更具运营弹性
NVDA Vera Rubin（Blackwell继任者）性能升级，HBM4迁移NVDA, AMD, AVGOVera Rubin预计2026下半年发布，采用HBM4；尽管护城河略侵蚀，但两大ASIC用户计划2026年对NVDA采购增长超80%
NVDA GTC关键日程修正与Feynman芯片前瞻NVDAGTC主题演讲3月16日2ET，财报问答3月17日12ET；TrendForce称或展示Feynman 1nm产品（2028量产）
NemoClaw/OpenClaw软件生态引爆API流量，边缘推理受益NET, AKAM, DOCN, FSLY, INTC, ARM, AMD, OKTA, SAIL, PANW, CRWD, EQIX, AAPLOpenClaw三周下载超Linux，Agent token消耗达100万倍；API流量激增利好CDN、边缘计算、安全及硬件厂商

跨市场信号

“Agent-first”软件投资主线显现

AI代理数量将超人类员工，驱动数据基础设施需求
SNOW/AKAM/DDOG/FROG/MDB处于AI代理消费层核心位置
SNOW FY27指引超预期，AKAM签2亿美元AI推理合同，DDOG获八位数订单

Actionable Ideas

短期(1-5天)

短期回避ADBE，等待ARR企稳与新CEO战略清晰化
做多铜缆供应链（CRDO、APH），做空过度交易的纯光学替代逻辑

中期(1-4周)

布局“Agent-first”基础设施组合：SNOW/AKAM/DDOG/FROG/MDB
增持零售与OTA平台（AMZN/WMT/BKNG/DASH/EBAY）作为AI购物导流受益者
持有NFLX作为非AI资本开支压力下的稀缺有机增长标的

Catalysts to Watch

Catalyst时间影响标的
NVDA GTC大会（3月16-17日）2025年3月16-17日将披露Blackwell Ultra、Vera Rubin路线图、Kyber机柜、NemoClaw及LPU等关键信息，验证AI基础设施分层架构
META Avocado模型5月发布2025年5月若性能达标将缓解AI进度担忧，否则可能加剧市场对其竞争力疑虑

Bottom Line: GTC会议是短期核心焦点，NVDA分层架构缓解替代恐慌；中期看好Agent-first基础设施与AI导流受益平台。
