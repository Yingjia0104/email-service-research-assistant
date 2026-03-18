# AI邮件投研助手

[English Version](./README_EN.md)

自动化邮件分析和推送助手，将卖方邮件转化为专业的 HF Morning Brief 投资报告。

## 业务流程

邮件接收 → 智能解析 → AI分析 → 观点抽取 → 报告生成 → 交易日推送

## 功能及特性

### 业务功能

- 📧 **邮件收取**：通过 IMAP 自动过滤出重点关注的卖方邮件
- 📎 **智能解析**：自动解析邮件正文和附件，支持.msg, .pdf, .docx, .txt格式的附件
- 🤖 **AI分析**：调用大模型分析卖方邮件，提炼主线、市场态度与 thesis
- 📊 **报告生成**：生成专业 HF Morning Brief 格式报告
- 📤 **自动发送**：通过 SMTP 自动发送报告到指定邮箱

### 系统特性

- 🗃️ **SQLite状态管理**：以本地数据库作为去重、待处理、已发送记录的唯一事实来源
- 🧹 **上下文优化与多模态理解**：自动裁掉邮件尾部署名/免责声明，并将图片附件走多模态输入
- 🔀 **容错分析链路**：主模型短重试后自动切备用模型；超长输入会拆批分析后再合并
- 🧠 **角色化研究输出**：支持按不同使用者角色配置研究视角与晨报口径

## 报告内容

基于角色指南（Persona）生成高效简炼的高效简炼：详见 [HF_Morning_Brief_role_guidance候选.md](./HF_Morning_Brief_role_guidance候选.md)


##### 报告结构 #####

| 章节 | 内容 |
|------|------|
| Executive Summary | 市场大背景 + 关键信号 |
| Key Coverage | 核心事件与市场观点 |
| Local News | 容易被忽略的信号 |
| Peripheral Intelligence | 外围信息映射 |
| Actionable Ideas | 可执行建议 |


## 可配选项

面向投研使用者：
- 关注的投行/分析师列表：支持后缀匹配（`@morganstanley.com`）或精确匹配（`analyst@gs.com`）
- 关注的板块/公司：迭代中，敬请期待

## 项目结构

```
email-service/
├── main.py                      # FastAPI 服务入口
├── qclaw_mail_file.py          # 核心处理逻辑
├── email_db.py                 # SQLite 状态与发送记录
├── config.yaml.example          # 配置文件模板
├── requirements.txt             # Python 依赖
├── generate_api_key.py         # API 密钥生成工具
├── reference_css.txt           # 报告格式 CSS
├── reference_body.txt          # 报告结构参考
├── HF_Morning_Brief_role_guidance候选.md # 角色指南候选
├── tests/test_smoke.py         # 关键烟测与回归测试
├── CLAUDE.md                   # AI 助手指南
└── .gitignore                  # Git 忽略配置
```

## 快速开始

### 安装

```bash
git clone https://github.com/Yingjia0104/email-service-research-assistant.git
cd email-service-research-assistant
pip install -r requirements.txt
```

### 配置

复制并编辑配置文件：

```bash
cp config.yaml.example config.yaml
# 编辑 config.yaml，填入你的 API 密钥和邮箱配置
```

**最小配置（仅收信 + 分析，不自动发回报告）：**
- `api_key`: API 访问密钥
- `llm.api_key` / `llm.api_key_env`: 主模型 API 密钥或环境变量名
- `llm_backup.api_key`: 第一备用模型密钥（可选但强烈建议）
- `llm_backup2.api_key` / `llm_backup2.api_key_env`: 第二备用模型密钥（可选）
- `llm_backup3.api_key` / `llm_backup3.api_key_env`: 第三备用模型密钥（可选）
- `imap.email` / `imap.password`: 收件邮箱和应用专用密码

**完整闭环（收信 + 分析 + 自动发送报告）时额外配置：**
- `smtp.email` / `smtp.password`: 发件邮箱和应用专用密码
- `smtp.timeout_seconds`: SMTP 超时秒数（建议保留默认值 30）
- `target.email`: 报告发送目标邮箱

> 多数实际场景下，只需要同一个邮箱同时具备 IMAP 和 SMTP 能力即可：
> - 它既作为系统监控的收件箱
> - 也作为系统发送最终报告的邮箱
> - `target.email` 也可以直接填这个同一个邮箱地址

> **提示**
> - **Gmail**: 
>   - 若只做收信分析，启用 IMAP 即可；若要完整闭环，则同一个邮箱还需具备 SMTP 发信能力并配置[应用专用密码](https://support.google.com/accounts/answer/185833)
>   - IMAP/SMTP 配置：`imap.gmail.com` (IMAP: 993, SMTP: 587)
> - **Outlook/Exchange**:
>   - 个人账户：微软将于 2025-2026 年停用基本身份验证，建议迁移至 OAuth 2.0
>   - 企业账户：需管理员在 Azure AD 中启用「允许应用密码」或配置 OAuth 2.0
>   - IMAP/SMTP 配置：`outlook.office365.com` (IMAP: 993, SMTP: 587)
> - **QQ 邮箱**:
>   - 建议 SMTP 使用 `465 + SSL`
>   - 收件和发信都应使用授权码，不要直接用登录密码
>   - IMAP/SMTP 配置：`imap.qq.com` (993), `smtp.qq.com` (465 / SSL)

### 运行

```bash
# 1. 启动 API 服务（后台运行）
python main.py

# 2. 运行处理流程
python qclaw_mail_file.py
```

## 使用方式

### 命令行选项

```bash
# 完整流程
python qclaw_mail_file.py

# 仅分析（不发送）
python qclaw_mail_file.py --analyze

# 强制运行（跳过每日一次限制）
python qclaw_mail_file.py --force

# 检查状态
python qclaw_mail_file.py --check
```

### API 调用

```bash
# 收取邮件
curl "http://localhost:8877/api/emails?api_key=YOUR_KEY&limit=10"

# 发送邮件
curl -X POST "http://localhost:8877/api/send?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to_email": "dest@example.com", "subject": "Test", "body": "Hello", "body_type": "plain"}'
```

## 技术栈

- **语言**: Python 3.9+
- **Web 框架**: FastAPI
- **邮件**: imap-tools, smtplib
- **大语言模型**: 通用 LLM（支持 Moonshot / OpenAI / MiniMax / MiMo / Sonnet 等兼容接口）
- **文档解析**: extract-msg, PyPDF2, python-docx

## LLM

当前默认示例是 `Qwen3-Max` 作为主模型，另配 `国内 Kimi + 海外 Kimi + GPT-5.4` 三级备用：

- **主模型示例**：`qwen3-max + supports_vision: true`
- **第一备用模型示例**：`kimi-k2.5 + supports_vision: true`
- **第二备用模型示例**：`kimi-k2.5 + supports_vision: true`
- **第三备用模型示例**：`gpt-5.4 + supports_vision: true + reasoning_effort: medium`
- **切换策略**：主模型未配置可用 key 或调用失败时，系统会自动尝试 `llm_backup`、`llm_backup2`，再尝试 `llm_backup3`

## 安全注意事项

### 1. API 密钥保护
- **不要** 将 `config.yaml` 上传到 Git
- `.gitignore` 已配置自动忽略该文件
- 如发现密钥泄露，请立即在对应平台重新生成密钥

### 2. 本地运行
- 默认 API 服务仅监听 `localhost`
- 如需远程访问，请配置防火墙或使用 VPN
- 建议不要将服务暴露在公网

### 3. 邮件数据
- 邮件内容仅保存在本地
- 当前主要状态保存在 `emails.db`；`pending_emails.json` 仅为兼容旧流程保留
- 敏感邮件建议在虚拟机或隔离环境中处理

### 4. 第三方服务
- 仅使用官方渠道注册的服务（Gmail、OpenAI、Moonshot 等）
- 定期检查账户安全设置
- 启用双因素认证（2FA）

## 常见问题

**Q: 解析 .msg 附件失败？**
A: 确保安装了 `extract-msg` 库

**Q: 邮箱登录失败？**
A: 需要开启"应用专用密码"，不要使用邮箱登录密码

**Q: LLM API 报错？**
A: 检查 API 密钥是否正确，账户是否有足够配额

**Q: 为什么有时报告格式不稳定？**
A: 这是大模型 HTML 输出结构漂移导致的。当前 `save_report()` 已内建标题日期统一、伪小标题提升、提示框/标签标准化等后处理，但仍建议保留 smoke test 与人工 review。

**Q: 系统的收发 DDL 和补发逻辑是怎样的？**
A: 默认把“美股开盘前 15 分钟”作为当天 `daily` 的收发 DDL。如果白名单分析师邮件提前全部到齐，系统会更早发送 `daily`；如果直到 DDL 仍未到齐，也不会继续等待。`daily` 发出后，若在开盘后 1 小时内收到新的白名单邮件，系统会走 `supplement` 补充分析并单独重试发送。

## 最新进展

### 今日已完成的优化

- 服务端鉴权与白名单配置已改为按请求读取最新配置，便于联调时热更新 `allowed_senders`
- 邮件收取、待处理状态、已发送记录统一落 SQLite，避免“分析对象”和“标记对象”错位
- 数据库已补作用域唯一键与原子状态更新，减少并发去重和“已发出但仍 pending”的状态撕裂
- 大模型分析前会清理尾部署名、免责声明、内联图片/base64 长串，并限制单封与整批上下文长度
- 当上下文仍然偏长时，系统会先拆成两个子批次生成结构化 JSON 摘要，再做二次合并生成最终晨报
- 中间摘要新增 `fact_subject / opinion_subject / info_type / source_evidence`，用于约束“事实/观点分离”和“真实主语归因”
- SMTP 发送支持 `587 + STARTTLS` 和 `465 + SSL`，并新增显式 timeout 与错误分类
- 定时分析与补充分析窗口改为按真实 `America/New_York` 时区计算，并自动跳过周末
- 当天白名单分析师邮件如果已全部到齐，会提前触发 daily；否则继续等到盘前 15 分钟 DDL

### 今日已验证的流程

- 白名单正向邮件收取、分析、生成报告、自动发送
- 非白名单邮件会进入 inbox，但被系统正确忽略
- 幂等性成立：没有新 `pending` 时不会重复分析和重复生成报告
- `.txt`、`.pdf`、图片附件已完成真实联调
- Gmail / Outlook 两个白名单发件人都已完成真实联调
- `qwen3-max + supports_vision: true` 与 `qwen-vl-max + supports_vision: true` 已完成真实多模态联调：图片附件与正文内嵌图片都能被提取成多模态输入并成功生成/发送报告
- 多级备用模型切换已验证：主模型失败后可继续尝试 `llm_backup` / `llm_backup2` / `llm_backup3`
- `early daily` 已验证：白名单分析师全部到齐后，会在 DDL 前提前发送 `daily`
- `supplement` 已验证：`daily` 提前发送后，新增白名单邮件会先保持 `pending`，进入 supplement window 后再单独发送 `supplement`

### 待优化项

- 接入美股节假日休市日历
- 大批量邮件 / 长附件压力场景验证与优化
- 长上下文拆批时，图片信息目前只在子批次阶段做多模态理解，合并阶段可能出现图像 insight 衰减；后续可考虑补充更显式的 image insights / image evidence 保留机制


## License

MIT License
