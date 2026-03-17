# CLAUDE.md - AI 邮件研究助手

## 项目概述

这是一个自动化邮件研究系统，可以：
- 通过 IMAP 收取 Gmail 邮件
- 自动解析邮件附件（.msg, .pdf, .docx 等）
- 调用通用 LLM（如 Moonshot / OpenAI）分析卖方邮件
- 生成专业 HF Morning Brief 格式的投资报告
- 通过 SMTP 发送报告到指定邮箱
- 使用 SQLite 管理邮件去重、待处理状态与发送记录

## 核心文件

```
├── main.py              # FastAPI 服务，提供邮件收取/发送 API
├── qclaw_mail_file.py  # 核心处理脚本：收取→分析→生成报告→发送
├── email_db.py         # SQLite 去重、pending/processed、发送记录
├── config.yaml          # 配置文件（API密钥、邮箱配置等）
├── requirements.txt     # Python 依赖
├── reference_css.txt   # 报告格式校准用 CSS
├── reference_body.txt  # 报告结构参考
├── tests/test_smoke.py # 关键 smoke test / 回归测试
└── generate_api_key.py # API 密钥生成工具
```

## 快速开始

### 1. 配置

编辑 `config.yaml`：
```yaml
api_key: "your-secret-key"
llm:
  api_key: "your-primary-llm-api-key"
  base_url: "https://api.moonshot.cn/v1"
  model: "kimi-k2.5"
llm_backup:
  api_key: "your-backup-api-key"
  base_url: "https://api.moonshot.ai/v1"
  model: "kimi-k2.5"
smtp:
  host: "smtp.gmail.com"
  port: 587
  timeout_seconds: 30
  email: "your-email@gmail.com"
  password: "your-app-password"
imap:
  host: "imap.gmail.com"
  port: 993
  email: "your-email@gmail.com"
  password: "your-app-password"
target:
  email: "destination@example.com"
filters:
  allowed_senders:
    - "@goldmansachs.com"
    - "@morganstanley.com"
server:
  # 安全起见默认仅监听本机；如需局域网访问请自行改为 0.0.0.0 并配防火墙/VPN
  host: "127.0.0.1"
  port: 8877
```

说明：
- `llm_backup` 为强烈建议项，但必须使用真实可用的独立凭证；不要假设任意兼容接口都接受同一组 key
- QQ 邮箱建议 SMTP 使用 `465 + SSL`

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 启动服务

```bash
# 启动 API 服务
python main.py

# 另一终端：运行处理流程
python qclaw_mail_file.py
```

## 使用方式

### 方式一：完整流程

```bash
python qclaw_mail_file.py
```

流程：收取邮件 → LLM 分析 → 生成报告 → 发送邮件

### 方式二：仅分析模式

```bash
python qclaw_mail_file.py --analyze
```

### 其他选项

```bash
--force   # 强制运行（忽略每日一次限制）
--check   # 检查状态
```

## API 接口

### 收取邮件
```bash
GET http://localhost:8877/api/emails?api_key=YOUR_KEY&limit=10
```

### 发送邮件
```bash
POST http://localhost:8877/api/send?api_key=YOUR_KEY
{
  "to_email": "dest@example.com",
  "subject": "标题",
  "body": "正文",
  "body_type": "html"
}
```

## 报告格式

生成的报告遵循 HF Morning Brief 格式：
- Executive Summary（关键信号）
- Key Coverage（核心事件与市场观点）
- Local News（容易被忽略的信号）
- Peripheral Intelligence（外围信息映射）
- Actionable Ideas（可执行建议）

## 2026-03-16 关键迭代

1. 状态流转改为以 `emails.db` 为唯一事实来源，解决了“分析对象”和“标记 processed 对象”可能错位的问题
2. 服务端鉴权、白名单等配置按请求读取，联调期间修改 `config.yaml` 不必重启 API 才生效
3. 分析前新增上下文清洗：尾部署名/免责声明裁剪、图片元数据替代 base64、长内容截断
4. 超长分析改为“两阶段”：先拆成两个子批次，生成结构化 JSON 摘要，再合并生成最终 HTML
5. 中间摘要显式包含 `fact_subject / opinion_subject / info_type / source_evidence`，用于稳定事实/观点分离与主语归因
6. `save_report()` 增加本地日期标题统一、伪小标题提升、独立粗体标签与提示框样式规范化
7. SMTP 发送同时支持 `587 + STARTTLS` 与 `465 + SSL`
8. 已补 smoke tests 覆盖配置热加载、fallback、上下文清洗、结构化摘要解析、HTML 规范化等关键路径
9. SMTP 发送新增显式 timeout 与异常分类，便于区分超时 / 认证失败 / 连接失败
10. 定时分析与补充分析窗口改为按真实 `America/New_York` 时区计算，并自动跳过周末
11. 后台收信新增“全员到齐即提前触发 daily”的逻辑；若未到齐，则继续等待盘前 15 分钟 DDL
12. 已完成一轮真实联调：Gmail + Outlook 两个白名单发件人全部到齐后，系统会在 DDL 前直接发送 `daily`
13. `daily` 提前发送后，后续新增白名单邮件会先保持 `pending`，并在 supplement window 内单独发送 `supplement`

## 注意事项

1. **Gmail 配置**：需要开启"应用专用密码"
2. **LLM API**：不同提供方额度和限速策略不同，注意监控调用频率
3. **过滤器**：`config.yaml` 中的 `allowed_senders` 可限制处理特定发件人
4. **时区**：系统使用北京时间 (Asia/Shanghai)
5. **定时逻辑**：当前已完成一轮 early daily / supplement 联调，但美股节假日休市日历等边界仍值得继续优化

## 常见问题

**Q: 邮件附件解析失败？**
A: 确保安装了 `extract-msg` 库，用于解析 .msg 文件

**Q: LLM API 超时？**
A: 检查网络连接，或调整 `qclaw_mail_file.py` 中的超时设置

**Q: 如何生成新的 API 密钥？**
A: 运行 `python generate_api_key.py`
