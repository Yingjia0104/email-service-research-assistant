# AI邮件投研助手

[English Version](./README_EN.md)

自动化邮件分析和推送助手，将卖方邮件转化为专业的 HF Morning Brief 投资报告

## 业务流程

邮件接收 → 智能解析 → AI分析 → 观点抽取 → 报告生成 → 交易日推送

## 功能及特性

### 业务功能

- 📧 **邮件收取**：通过IMAP自动过滤出重点关注的卖方邮件
- 📎 **智能解析**：自动解析邮件正文和附件，支持.msg, .pdf, .docx, .txt格式的附件
- 🤖 **AI分析**：调用大模型分析卖方邮件，提炼主线、市场态度与 thesis等
- 📊 **报告生成**：生成专业 AI Morning Brief 格式报告
- 📤 **自动发送**：通过 SMTP 自动发送报告到指定邮箱

### 系统特性

- 🗃️ **SQLite状态管理**：以本地数据库作为去重、待处理、已发送记录的唯一事实来源
- 🧹 **上下文优化与多模态理解**：自动裁掉邮件尾部署名/免责声明，并将图片附件走多模态输入
- 🔀 **容错分析链路**：主模型短重试后自动切备用模型；超长输入会拆批分析后再合并
- 🧠 **角色化研究输出**：支持按不同使用者角色配置研究视角与晨报口径
- ⏰ **自动模式调度**：`main.py` 可按固定频率轮询收件箱，并在盘前窗口内自动触发 `daily / supplement`
- 🪟 **Session 感知的 early run**：只在本轮 briefing session 内白名单 sales 全部到齐、邮件数足够且 quiet period 满足时提前触发 AI 分析
- 🧾 **实时运行日志**：自动收件、触发判断和服务内分析链日志默认输出到 stdout；需要时可重定向到 `main_runtime.log`
- 🔒 **单实例分析保护**：自动模式下避免重复触发多个分析任务，降低并发重入导致的状态冲突
- 🏷️ **机构来源识别**：报告头部 `Source` 优先显示本轮内容里识别到的机构来源（如 `MS + JPM + BofA`），而不是转发邮箱本身

## 报告内容

基于角色指南（Persona）生成高效简练的 HF Morning Brief：详见 [hf_morning_brief_role_guidance候选.md](./docs/hf_morning_brief_role_guidance候选.md)


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
- 关注的板块/公司：支持全局提权配置（迭代中，敬请期待）

## 项目结构

```text
email-service-research-assistant/
├── app/
│   ├── api/                    # FastAPI 路由与 HTTP adapter
│   ├── llm/                    # LLM client / prompts / JSON 解析
│   ├── mail/                   # IMAP / SMTP / mail integration
│   ├── pipeline/               # 预处理、报告、多模态、调度
│   ├── render/                 # HTML 渲染与格式化
│   ├── runtime/                # 服务运行时、分析入口、CLI 支撑、状态/锁
│   └── storage/                # SQLite 存储实现
├── main.py                     # 服务入口
├── qclaw_mail_file.py          # CLI 入口
├── email_db.py                 # 根目录兼容层
├── docs/                       # 设计与内部文档
├── tests/                      # smoke + 回归测试
├── config.yaml.example         # 配置文件模板
├── requirements.txt            # Python 依赖
├── reference_css.txt           # 报告样式
├── reference_body.txt          # 报告结构参考
├── generate_api_key.py         # API 密钥生成工具
├── CLAUDE.md                   # 协作说明
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
# 服务模式：启动 API + 后台轮询 + 自动调度
python main.py

# CLI 模式：手动触发完整流程
python qclaw_mail_file.py
```

## 使用方式

### 自动模式

```bash
# 启动后台自动模式（轮询收件 + 自动触发分析）
python main.py

# 实时查看自动模式日志（如果你把 stdout 重定向到了文件）
tail -f main_runtime.log
```

自动模式下：
- 系统会按 `background.interval_minutes` 轮询收件箱
- 到固定 DDL 时，只要有 `pending` 邮件就会触发 `daily`
- 如果在盘前窗口内，本轮 session 里的白名单 sales 已全部到齐，且最近一段时间没有新邮件，也会提前触发 `daily`
- `daily` 发出后，开盘后窗口内的新白名单邮件会进入 `supplement`

### 命令行选项

```bash
# 完整流程
python qclaw_mail_file.py

# 仅处理当前 SQLite 里已有的 pending 邮件
# 注意：该模式仍会生成并发送报告，只是不会先去收件
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

# 查看单封邮件
curl "http://localhost:8877/api/emails/123?api_key=YOUR_KEY"

# 按默认 SMTP 配置发送邮件
curl -X POST "http://localhost:8877/api/send?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to_email": "dest@example.com", "subject": "Test", "body": "Hello", "body_type": "plain"}'

# 自定义 SMTP 参数发送邮件
curl -X POST "http://localhost:8877/api/send/custom?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"smtp_host": "smtp.gmail.com", "smtp_port": 587, "from_email": "src@example.com", "password": "app-password", "to_email": "dest@example.com", "subject": "Test", "body": "Hello", "body_type": "plain"}'
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

当前默认链路是：
- `Qwen3-Max`
- `国内 Kimi-2.5`
- `海外 Kimi-2.5`
- `GPT-5.4`

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
- 当前主要状态保存在 `emails.db`
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
A: 默认把“美股开盘前 15 分钟”作为当天 `daily` 的收发 DDL。如果本轮 briefing session 里白名单 sales 已全部到齐，且最近一段时间没有新邮件，系统会更早发送 `daily`；如果直到 DDL 仍未到齐，也不会继续等待。`daily` 发出后，若在开盘后 1 小时内收到新的白名单邮件，系统会走 `supplement` 补充分析并单独重试发送。

**Q: 自动模式日志怎么看？**
A: 默认情况下，运行 `python main.py` 后这些日志会直接打印到 stdout。如果你希望同时落到文件，可以这样启动：

```bash
python main.py 2>&1 | tee -a main_runtime.log
```

**Q: 报告里的 `Source` 指什么？**
A: `Source` 优先展示本次邮件内容里识别出来的机构来源标签（如 `MS + JPM + BofA`）。

## 当前架构

- `main.py`：服务入口，负责 FastAPI、后台轮询与自动调度
- `qclaw_mail_file.py`：CLI 入口，负责手动触发与状态查看
- `app/`：统一业务引擎，负责 mail、pipeline、render、storage、runtime

## 当前能力

- 邮件收取、待处理状态、发送记录统一落 SQLite
- 自动模式支持单实例运行、session-aware `daily / supplement` 调度
- 大模型分析前会清理签名、免责声明、内联图片/base64 噪音，并在超长输入时拆批合并
- 多模态链路支持图片预筛、轻分类、深分析、视觉上下文回填和主摘要接线
- SMTP 发送支持 `587 + STARTTLS` 与 `465 + SSL`
- 默认模型链示例为 `Qwen3-Max -> 国内 Kimi-2.5 -> 海外 Kimi-2.5 -> GPT-5.4`

## 当前验证状态

- 全量测试已通过
- 白名单正向收件、分析、生成报告、发送链路已验证
- 非白名单邮件会进入 inbox，但会被系统正确忽略
- 幂等性已验证：没有新 `pending` 时不会重复分析和重复生成报告
- `.txt`、`.pdf`、图片附件链路已验证
- 多级备用模型切换已验证：主模型失败后可继续尝试 `llm_backup` / `llm_backup2` / `llm_backup3`

## 后续优化项

- 接入美股节假日休市日历
- 大批量邮件 / 长附件压力场景验证与优化


## License

MIT License
