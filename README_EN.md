# AI Email Research Assistant

[中文版](./README.md)

An automated email research system that converts sell-side emails into professional HF Morning Brief investment reports.

## Features

Email Reception → Smart Parsing → AI Analysis → Insight Extraction → Report Generation → Auto Push

- 📧 **Email Receiving**: IMAP-based filtering of targeted sell-side emails
- 📎 **Smart Parsing**: Auto-parse email body and attachments (.msg, .pdf, .docx, .txt)
- 🤖 **AI Analysis**: Call LLM to analyze sell-side emails and extract key insights
- 📊 **Report Generation**: Generate professional HF Morning Brief format reports
- 📤 **Auto Send**: Auto-send reports via SMTP to designated email

## Report Content

Generated reports follow the efficient HF Morning Brief format:

| Section | Content |
|---------|---------|
| Executive Summary | Market background + Key signals |
| Key Coverage | Core events & market views |
| Local News | Easily overlooked signals |
| Peripheral Intelligence | Peripheral information mapping |
| Actionable Ideas | Actionable suggestions |

See [HF_Morning_Brief_Format_Spec.md](./HF_Morning_Brief_格式规范.md) for details.

## Configurable Options

- **Target investment banks/analysts list**: Supports suffix matching (`@morganstanley.com`) or exact matching (`analyst@gs.com`)
- Target sectors/companies <!-- WIP -->
- Push cutoff time (pre-US market) <!-- WIP -->

## Project Structure

```
email-service/
├── main.py                      # FastAPI service entry
├── qclaw_mail_file.py          # Core processing logic
├── config.yaml.example          # Config file template
├── requirements.txt             # Python dependencies
├── generate_api_key.py         # API key generator
├── reference_css.txt           # Report CSS styles
├── reference_body.txt          # Report structure reference
├── HF_Morning_Brief_Format_Spec.md # Format specification
├── CLAUDE.md                   # AI assistant guide
└── .gitignore                  # Git ignore config
```

## Quick Start

### Installation

```bash
git clone https://github.com/Yingjia0104/email-service-research-assistant.git
cd email-service-research-assistant
pip install -r requirements.txt
```

### Configuration

Copy and edit the config file:

```bash
cp config.yaml.example config.yaml
# Edit config.yaml with your API keys and email settings
```

**Required config fields:**
- `api_key`: API access key
- `kimi.api_key`: Kimi API key
- `smtp.email` / `smtp.password`: Sender email and app password
- `imap.email` / `imap.password`: Receiver email and app password
- `target.email`: Report destination email

> **Notes**
> - **Gmail**: Enable IMAP and generate an [App Password](https://support.google.com/accounts/answer/185833)
> - **Outlook/Exchange**:
>   - Personal: Microsoft will disable Basic Auth in 2025-2026, recommend OAuth 2.0 migration
>   - Enterprise: Admin needs to enable "Allow App Passwords" in Azure AD or configure OAuth 2.0
>   - IMAP/SMTP: `outlook.office365.com` (IMAP: 993, SMTP: 587)

### Running

```bash
# 1. Start API service (run in background)
python main.py

# 2. Run processing pipeline
python qclaw_mail_file.py
```

## Usage

### Command Line Options

```bash
# Full pipeline
python qclaw_mail_file.py

# Analyze only (no sending)
python qclaw_mail_file.py --analyze

# Force run (skip daily limit)
python qclaw_mail_file.py --force

# Check status
python qclaw_mail_file.py --check
```

### API Calls

```bash
# Fetch emails
curl "http://localhost:8877/api/emails?api_key=YOUR_KEY&limit=10"

# Send email
curl -X POST "http://localhost:8877/api/send?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to_email": "dest@example.com", "subject": "Test", "body": "Hello", "body_type": "plain"}'
```

## Tech Stack

- **Language**: Python 3.9+
- **Web Framework**: FastAPI
- **Email**: imap-tools, smtplib
- **LLM**: Kimi (Moonshot AI)
- **Document Parsing**: extract-msg, PyPDF2, python-docx

## Security Notes

### 1. API Key Protection
- **Do NOT** upload `config.yaml` to Git
- `.gitignore` is configured to automatically ignore this file
- If keys are leaked, regenerate immediately on the respective platform

### 2. Local Running
- API service defaults to `localhost` only
- If remote access is needed, configure firewall or use VPN
- Avoid exposing service to public internet

### 3. Email Data
- Email content is stored locally only
- Regularly clean up temporary files like `pending_emails.json`
- Consider using VM or isolated environment for sensitive emails

### 4. Third-Party Services
- Only use official channels (Gmail, Kimi, etc.)
- Regularly review account security settings
- Enable Two-Factor Authentication (2FA)

## FAQ

**Q: .msg attachment parsing fails?**
A: Ensure `extract-msg` library is installed

**Q: Gmail login fails?**
A: Need to enable "App Password", do not use email login password

**Q: LLM API error?**
A: Check API key correctness and account quota

## License

MIT License
