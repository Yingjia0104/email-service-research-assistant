# CLAUDE.md - AI 邮件研究助手

## 项目概述

这是一个自动化邮件研究系统，可以：
- 通过 IMAP 收取白名单邮件
- 自动解析邮件附件（.msg, .pdf, .docx 等）
- 调用通用 LLM（如 Moonshot / OpenAI）分析卖方邮件
- 生成专业 HF Morning Brief 格式的投资报告
- 通过 SMTP 发送报告到指定邮箱
- 使用 SQLite 管理邮件去重、待处理状态与发送记录

## 核心文件

```text
├── app/                # 统一业务引擎（api / mail / pipeline / render / runtime / storage）
├── main.py             # 服务入口：FastAPI + 后台轮询 + 自动调度
├── qclaw_mail_file.py  # CLI 入口：手动触发 / 状态查看
├── email_db.py         # 根目录兼容层
├── config.yaml         # 配置文件（API密钥、邮箱配置等）
├── requirements.txt    # Python 依赖
├── reference_css.txt   # 报告格式 CSS
├── reference_body.txt  # 报告结构参考
├── tests/              # smoke / 回归测试
└── generate_api_key.py # API 密钥生成工具
```

## 快速开始

### 1. 配置

编辑 `config.yaml`：
```yaml
api_key: "your-secret-key"
llm:
  api_key: "your-primary-llm-api-key"
  base_url: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  model: "qwen3-max"
  supports_vision: true
llm_backup:
  api_key: "your-backup-api-key"
  base_url: "https://api.moonshot.cn/v1"
  model: "kimi-k2.5"
  supports_vision: true
smtp:
  host: "smtp.gmail.com"
  port: 587
  use_ssl: false
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
# 服务模式：启动 API + 后台轮询 + 自动调度
python main.py

# CLI 模式：手动触发完整流程
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

说明：
- 这个模式只处理 SQLite 里当前已有的 `pending` 邮件
- 它仍然会生成并发送报告，只是不会先去收件

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

### 查看单封邮件
```bash
GET http://localhost:8877/api/emails/123?api_key=YOUR_KEY
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

## 当前架构

1. `main.py` 是服务入口
2. `qclaw_mail_file.py` 是 CLI 入口
3. `app/` 是统一业务引擎 owner
4. SQLite 是状态主存储，`emails.db` 保存邮件、发送记录、图片链路和运行时状态

## 当前能力

1. 自动模式支持单实例轮询、session-aware `daily / supplement` 调度
2. 分析前会清理签名、免责声明、内联图片/base64 噪音，并在超长输入时拆批合并
3. 图片链路支持预筛、轻分类、深分析、视觉上下文回填
4. SMTP 发送支持 `587 + STARTTLS` 与 `465 + SSL`
5. 默认模型链示例为 `Qwen3-Max -> 国内 Kimi-2.5 -> 海外 Kimi-2.5 -> GPT-5.4`

## 注意事项

1. **Gmail 配置**：需要开启"应用专用密码"
2. **LLM API**：不同提供方额度和限速策略不同，注意监控调用频率
3. **过滤器**：`config.yaml` 中的 `allowed_senders` 可限制处理特定发件人
4. **时区**：系统使用北京时间 (Asia/Shanghai)
5. **日志落盘**：运行日志默认打印到 stdout；如果需要写入 `main_runtime.log`，请用 `python main.py 2>&1 | tee -a main_runtime.log`

## 常见问题

**Q: 邮件附件解析失败？**
A: 确保安装了 `extract-msg` 库，用于解析 .msg 文件

**Q: LLM API 超时？**
A: 检查网络连接，或调整 `config.yaml` 里的模型 / SMTP 超时相关配置

**Q: 如何生成新的 API 密钥？**
A: 运行 `python generate_api_key.py`
