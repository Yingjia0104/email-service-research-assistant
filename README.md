# AI 邮件研究助手

自动化邮件研究系统，将卖方邮件转化为专业的 HF Morning Brief 投资报告。

## 功能特性

邮件接收 → 智能解析 → AI 解析 → 观点抽取 → 报告生成 → 自动推送

- 📧 **邮件收取**：通过 IMAP 自动过滤出重点关注的卖方邮件
- 📎 **智能解析**：自动解析邮件正文和附件（.msg, .pdf, .docx, .txt）
- 🤖 **AI 分析**：调用大模型分析卖方邮件，提取要点
- 📊 **报告生成**：生成专业 HF Morning Brief 格式报告
- 📤 **自动发送**：通过 SMTP 自动发送报告到指定邮箱

## 项目结构

```
email-service/
├── main.py                      # FastAPI 服务入口
├── qclaw_mail_file.py          # 核心处理逻辑
├── config.yaml.example          # 配置文件模板
├── requirements.txt             # Python 依赖
├── generate_api_key.py         # API 密钥生成工具
├── reference_css.txt           # 报告格式 CSS
├── reference_body.txt          # 报告结构参考
├── HF_Morning_Brief_格式规范.md # 格式规范文档
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

**config.yaml 必填项：**
- `api_key`: API 访问密钥
- `kimi.api_key`: Kimi API 密钥
- `smtp.email` / `smtp.password`: 发件邮箱和应用专用密码
- `imap.email` / `imap.password`: 收件邮箱和应用专用密码
- `target.email`: 报告发送目标邮箱

> **提示**
> - **Gmail**: 需启用 IMAP 并生成[应用专用密码](https://support.google.com/accounts/answer/185833)
> - **Outlook/Exchange**:
>   - 个人账户：微软将于 2025-2026 年停用基本身份验证，建议迁移至 OAuth 2.0
>   - 企业账户：需管理员在 Azure AD 中启用「允许应用密码」或配置 OAuth 2.0
>   - IMAP/SMTP 配置：`outlook.office365.com` (IMAP: 993, SMTP: 587)

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

## 报告内容

生成的报告遵循高效简炼的 HF Morning Brief 格式：

| 章节 | 内容 |
|------|------|
| Executive Summary | 市场大背景 + 关键信号 |
| Key Coverage | 核心事件与市场观点 |
| Local News | 容易被忽略的信号 |
| Peripheral Intelligence | 外围信息映射 |
| Actionable Ideas | 可执行建议 |

详见 [HF_Morning_Brief_格式规范.md](./HF_Morning_Brief_格式规范.md)

## 可配选项

- 关注的投行列表
- 关注的板块/公司 <!-- 迭代中 -->
- 推送截止时间（美股盘前） <!-- 迭代中 -->

## 技术栈

- **语言**: Python 3.9+
- **Web 框架**: FastAPI
- **邮件**: imap-tools, smtplib
- **LLM**: Kimi (Moonshot AI)
- **文档解析**: extract-msg, PyPDF2, python-docx

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
- 定期清理 `pending_emails.json` 等临时文件
- 敏感邮件建议在虚拟机或隔离环境中处理

### 4. 第三方服务
- 仅使用官方渠道注册的服务（Gmail, Kimi 等）
- 定期检查账户安全设置
- 启用双因素认证（2FA）

## 常见问题

**Q: 解析 .msg 附件失败？**
A: 确保安装了 `extract-msg` 库

**Q: Gmail 登录失败？**
A: 需要开启"应用专用密码"，不要使用邮箱登录密码

**Q: LLM API 报错？**
A: 检查 API 密钥是否正确，账户是否有足够配额

## License

MIT License
