# HF Multimodal Image Deep Analysis Prompts

这份文档只记录当前第三步深分析的真实口径。

主链路是：

1. Step 1 `collect + prescreen`
2. Step 2 `lightweight classification`
3. Step 3 `deep analysis`
4. 聚合成邮件级 `Visual Context / Visual Evidence`

---

## 目标

第三步的任务很简单：

- 把高价值图片转成结构化文本信息
- 告诉后续链路“这张图说了什么”
- 不替正文做判断，不补邮件主线，不脑补图外事实

---

## 当前输入

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

---

## 当前输出

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
  除了核心结论外，这张图还额外补充了什么

当前已经移除：

- 旧的“支持正文 claim”字段
- 旧的“不确定性”字段
- 旧的“置信度”字段

---

## 当前 Prompt 结构

### Shared System Prompt

```text
你负责把图片转成结构化文本信息，告诉我这张图说了什么。
```

### Shared User Contract

```text
只根据图片本身输出 JSON，顶层固定为 {"images": [...]}。
字段固定为：image_key / core_signal / supporting_details。
不能新增字段；无内容时返回空字符串或 []。
```

---

## 类型化 User Prompt

### `research_framework_chart`

```text
逐张分析这些 research framework chart。
- 先看图片本身，只写图里能直接看到或稳妥推出的内容
- 信息不够就留空，不要补写
- 重点看框架、排序维度、bucket、关键对象的位置关系
- 如果图片是二维定位矩阵、象限图、仓位情绪图或 positioning map，按这个顺序读图：
  1. 先识别横轴和纵轴分别代表什么
  2. 再识别四个象限各自代表什么立场、情绪或仓位
  3. 再提取每个关键象限里的代表性对象或 ticker
  4. 如果图里有 consensus long、consensus short、battleground、hedge fund hotel 一类显式标签，要直接写出来
  5. 如果图里有箭头，优先解释它表示的方向变化、情绪迁移或边际改善/恶化
- 不要机械罗列全部 ticker，只提最能代表各区域的对象
- 不要把机构框架图写成独立核实的客观事实
- `core_signal` 直接写这张图最重要的结论；遇到象限图时，优先用 1-2 句写清楚市场最强共识在哪里、最大分歧在哪里、哪些票在边际改善或恶化，不要先解释坐标轴和读图方法
- `supporting_details` 写补充信息；遇到象限图时，再补充轴含义、象限标签、代表性 ticker、拥挤区、战场区和箭头变化
```

### `market_data_chart`

```text
逐张分析这些 market data chart。
- 先看图片本身，只写图里能直接看到或稳妥推出的内容
- 信息不够就留空，不要补写
- 先在内部识别：
  1. 图在比较什么对象
  2. 主要方向是走强、走弱、分化还是收敛
  3. 哪个对象相对更强、哪个对象相对更弱
  4. 有没有明显拐点、放量、回撤、修复或趋势变化
- 不要把相关性写成因果；幅度不清楚时只写方向
- `core_signal` 直接写这张图最重要的市场结论，优先回答谁更强、谁更弱、分化有没有扩大或收敛，不要先解释图表类型
- `supporting_details` 再补比较对象、时间段、方向性细节、相对表现和可见数字
```

### `social_signal_visual`

```text
逐张分析这些 social signal visual。
- 先看图片本身，只写图里能直接看到或由可见线索支持的最小解释
- 信息不够就留空，不要补写
- 先在内部识别：
  1. 这是哪个平台、哪类账号、什么传播场景
  2. 核心传播内容是什么
  3. 传播 framing 偏什么方向
  4. 有没有浏览量、点赞、转发、时间戳、截图 UI 这类可见线索
- 社交截图反映的是传播和 framing，不等于独立核实后的事实
- 不要把“有人在传播”写成“事实已经成立”
- `core_signal` 直接写这张图最重要的传播结论，优先回答谁在传、在传什么、市场会从这张图感受到什么信号，不要先解释平台界面
- `supporting_details` 再补平台、账号、互动量、时间戳、截图里额外出现的直接证据
```

### `editorial_framing_visual`

```text
逐张分析这些 editorial framing visual。
- 先看图片本身，只写图里能直接看到或由可见线索支持的最小解释
- 信息不够就留空，不要补写
- 先在内部识别：
  1. 标题、封面、版式、人物或视觉主体是什么
  2. 主题被包装成什么叙事
  3. 图面强调的是冲突、机会、风险还是情绪
  4. 哪些元素在推动这种 framing
- editorial framing 不等于客观事实，不要从弱视觉信号推出过强结论
- `core_signal` 直接写这张图最重要的 framing 结论，优先回答它把主题包装成了什么故事或市场情绪，不要先复述版面结构
- `supporting_details` 再补标题措辞、封面元素、排版重点、视觉对比和附带文字信息
```

---

## 聚合口径

深分析结果会回填到统一图片对象，再进入邮件级聚合。

- 偏主叙事的图片进入 `Visual Context`
- 偏支撑证据的图片进入 `Visual Evidence`
- 聚合时只使用：
  - `core_signal`
  - `supporting_details`

如果 `core_signal` 为空，这张图不会进入邮件级视觉上下文。

---

## 当前设计取舍

当前第三步故意做得很克制：

- 不让模型联读正文
- 不让模型猜“支持正文哪条 claim”
- 不单独输出“不确定性字段”
- 让输出尽量聚焦在“这张图到底说了什么”

这样做的目的，是先把第三步收成一个更容易被模型理解、也更容易验收的最小任务。
