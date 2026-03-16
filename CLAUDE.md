# CLAUDE.md - AI 邮件研究助手

## 项目概述

这是一个自动化邮件研究系统，可以：
- 通过 IMAP 收取 Gmail 邮件
- 自动解析邮件附件（.msg, .pdf, .docx 等）
- 调用 Kimi 大模型分析卖方邮件
- 生成专业 HF Morning Brief 格式的投资报告
- 通过 SMTP 发送报告到指定邮箱

## 核心文件

```
├── main.py              # FastAPI 服务，提供邮件收取/发送 API
├── qclaw_mail_file.py  # 核心处理脚本：收取→分析→生成报告→发送
├── config.yaml          # 配置文件（API密钥、邮箱配置等）
├── requirements.txt     # Python 依赖
├── reference_css.txt   # 报告格式校准用 CSS
├── reference_body.txt  # 报告结构参考
├── HF_Morning_Brief_格式规范.md  # 报告格式规范
└── generate_api_key.py # API 密钥生成工具
```

## 快速开始

### 1. 配置

编辑 `config.yaml`：
```yaml
api_key: "your-secret-key"
kimi:
  api_key: "your-kimi-api-key"
  base_url: "https://api.moonshot.cn/v1"
  model: "kimi-k2.5"
smtp:
  host: "smtp.gmail.com"
  port: 587
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
  host: "0.0.0.0"
  port: 8877
```

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

流程：收取邮件 → Kimi AI 分析 → 生成报告 → 发送邮件

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

格式规范详见 `HF_Morning_Brief_格式规范.md`

## 注意事项

1. **Gmail 配置**：需要开启"应用专用密码"
2. **Kimi API**：免费额度有限，注意使用频率
3. **过滤器**：`config.yaml` 中的 `allowed_senders` 可限制处理特定发件人
4. **时区**：系统使用北京时间 (Asia/Shanghai)

## 常见问题

**Q: 邮件附件解析失败？**
A: 确保安装了 `extract-msg` 库，用于解析 .msg 文件

**Q: Kimi API 超时？**
A: 检查网络连接，或调整 `qclaw_mail_file.py` 中的超时设置

**Q: 如何生成新的 API 密钥？**
A: 运行 `python generate_api_key.py`
