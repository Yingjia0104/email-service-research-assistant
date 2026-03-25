# AI Email Research Assistant

[中文版](./README.md)

An automated email research system that converts sell-side emails into professional HF Morning Brief investment reports.

## Features

Email Reception → Smart Parsing → AI Analysis → Insight Extraction → Report Generation → Everyday Push

Business Functions:

- 📧 **Email Receiving**: IMAP-based filtering of targeted sell-side emails
- 📎 **Smart Parsing**: Auto-parse email body and attachments (.msg, .pdf, .docx, .txt)
- 🤖 **AI Analysis**: Use an LLM to extract the key market narrative, stance, thesis, and core takeaways from sell-side emails
- 📊 **Report Generation**: Generate professional AI Morning Brief format reports
- 📤 **Auto Send**: Auto-send reports via SMTP to designated email

System Traits:

- 🗃️ **SQLite State Management**: SQLite is the single source of truth for dedupe, pending emails, and sent-report history
- 🧹 **Context Optimization**: Automatically trims signatures/disclaimers, strips inline image/base64 noise, and sends image attachments through multimodal input
- 🔀 **Fault-Tolerant Analysis**: Primary model short-retries, then falls back to backup model; long batches are split and merged
- 🧠 **Persona-Based Research Output**: Supports configurable research personas for different end users and briefing styles
- ⏰ **Automatic Scheduling**: `main.py` can poll the inbox on a fixed interval and trigger `daily / supplement` automatically in the pre-market window
- 🪟 **Session-Aware Early Run**: Supports early triggering after whitelisted sales emails in the current briefing session have fully arrived
- 🧾 **Real-Time Runtime Logs**: inbox polling, trigger decisions, and in-process service analysis logs go to stdout by default; redirect them to `main_runtime.log` when needed
- 🔒 **Single-Instance Analysis Protection**: Automatic mode prevents duplicate analysis jobs from running at the same time
- 🏷️ **Institution-First Source Labels**: The report header prefers institution labels recognized from the content itself (for example `MS + JPM + BofA`) rather than just the forwarding mailbox

## Report Content

Generated reports follow an efficient format:

| Section | Content |
|---------|---------|
| Executive Summary | Market background + Key signals |
| Key Coverage | Core events & market views |
| Local News | Easily overlooked signals |
| Peripheral Intelligence | Peripheral information mapping |
| Actionable Ideas | Actionable suggestions |

## Configurable Options

For investment users:

- Target investment banks/analysts list: Supports suffix matching (`@morganstanley.com`) or exact matching (`analyst@gs.com`)
- Sector/company focus: reserved for future global-priority configuration
- Persona guidance: see [hf_morning_brief_role_guidance候选.md](./docs/hf_morning_brief_role_guidance候选.md)

For product / system setup:

- Multi-level LLM fallback via `llm_backup` / `llm_backup2`

## Project Structure

```text
email-service-research-assistant/
├── app/
│   ├── api/                    # FastAPI routes and HTTP adapters
│   ├── llm/                    # LLM client / prompts / JSON parsing
│   ├── mail/                   # IMAP / SMTP / mail integration
│   ├── pipeline/               # preprocessing, report, multimodal, scheduling
│   ├── render/                 # HTML rendering and formatting
│   ├── runtime/                # service runtime, analysis entry, CLI support, state/locks
│   └── storage/                # SQLite storage implementation
├── main.py                     # service entry
├── qclaw_mail_file.py          # CLI entry
├── email_db.py                 # root-level compatibility layer
├── docs/                       # design and internal docs
├── tests/                      # smoke + regression tests
├── config.yaml.example         # config template
├── requirements.txt            # Python dependencies
├── reference_css.txt           # report styles
├── reference_body.txt          # report structure reference
├── generate_api_key.py         # API key generator
├── CLAUDE.md                   # collaboration notes
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

**Minimum setup (receive + analyze only, without auto-sending reports):**
- `api_key`: API access key
- `llm.api_key` / `llm.api_key_env`: Primary model API key or environment variable name
- `llm_backup.api_key`: First backup model key (optional but strongly recommended)
- `llm_backup2.api_key` / `llm_backup2.api_key_env`: Second backup model key (optional)
- `llm_backup3.api_key` / `llm_backup3.api_key_env`: Third backup model key (optional)
- `imap.email` / `imap.password`: Receiver email and app password

**Full closed loop (receive + analyze + auto-send reports) adds:**
- `smtp.email` / `smtp.password`: Sender email and app password
- `smtp.timeout_seconds`: SMTP timeout in seconds (keep the default `30` unless you have a reason not to)
- `target.email`: Report destination email

> In most real deployments, a single mailbox with both IMAP and SMTP capability is enough:
> - it is the inbox the system monitors
> - it is also the mailbox used to send the final report
> - `target.email` can be this same mailbox address as well

> **Notes**
> - **Gmail**: If you only need receiving + analysis, IMAP is enough; for the full closed loop, the same mailbox also needs SMTP sending capability and an [App Password](https://support.google.com/accounts/answer/185833)
> - **Outlook/Exchange**:
>   - Personal: Microsoft will disable Basic Auth in 2025-2026, recommend OAuth 2.0 migration
>   - Enterprise: Admin needs to enable "Allow App Passwords" in Azure AD or configure OAuth 2.0
>   - IMAP/SMTP: `outlook.office365.com` (IMAP: 993, SMTP: 587)
> - **QQ Mail**:
>   - Prefer SMTP `465 + SSL`
>   - Use authorization codes rather than the mailbox login password for both receiving and sending
>   - IMAP/SMTP: `imap.qq.com` (993), `smtp.qq.com` (465 / SSL)

### Running

```bash
# Service mode: start API + background polling + automatic scheduling
python main.py

# CLI mode: manually trigger the full processing flow
python qclaw_mail_file.py
```

## Usage

### Automatic Mode

```bash
# Start background automatic mode (poll inbox + auto-trigger analysis)
python main.py

# Watch automatic-mode logs in real time
# if you redirected stdout into a file
tail -f main_runtime.log
```

In automatic mode:
- the system polls the inbox according to `background.interval_minutes`
- at the fixed DDL, any `pending` mail triggers `daily`
- during the pre-market window, `daily` can trigger early if all whitelisted sales in the current session have arrived and no new email has landed during the recent quiet period
- after `daily` is sent, new whitelisted mail in the post-open window flows into `supplement`

### Command Line Options

```bash
# Full pipeline
python qclaw_mail_file.py

# Process only the pending emails already stored in SQLite
# Note: this mode still generates and sends the report; it just skips inbox fetching first
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

# Fetch one email by id
curl "http://localhost:8877/api/emails/123?api_key=YOUR_KEY"

# Send email with default SMTP config
curl -X POST "http://localhost:8877/api/send?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"to_email": "dest@example.com", "subject": "Test", "body": "Hello", "body_type": "plain"}'

# Send email with custom SMTP config
curl -X POST "http://localhost:8877/api/send/custom?api_key=YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"smtp_host": "smtp.gmail.com", "smtp_port": 587, "from_email": "src@example.com", "password": "app-password", "to_email": "dest@example.com", "subject": "Test", "body": "Hello", "body_type": "plain"}'
```

## Tech Stack

- **Language**: Python 3.9+
- **Web Framework**: FastAPI
- **Email**: imap-tools, smtplib
- **LLM**: Generic LLM routing across Moonshot / OpenAI / MiniMax / MiMo / Sonnet style providers
- **Document Parsing**: extract-msg, PyPDF2, python-docx

## LLM

The default example now uses `Qwen3-Max` as the primary model, with `domestic Kimi + overseas Kimi + GPT-5.4` as three backup layers:

- **Primary model example**: `qwen3-max + supports_vision: true`
- **First backup example**: `kimi-k2.5 + supports_vision: true`
- **Second backup example**: `kimi-k2.5 + supports_vision: true`
- **Third backup example**: `gpt-5.4 + supports_vision: true + reasoning_effort: medium`
- **Fallback behavior**: if the primary model has no usable key or fails at runtime, the system automatically tries `llm_backup`, then `llm_backup2`, then `llm_backup3`

The current default chain is:
- `Qwen3-Max`
- `Domestic Kimi-2.5`
- `Overseas Kimi-2.5`
- `GPT-5.4`

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
- Core state lives in `emails.db`
- Consider using VM or isolated environment for sensitive emails

### 4. Third-Party Services
- Only use official channels (Gmail, OpenAI, Moonshot, etc.)
- Regularly review account security settings
- Enable Two-Factor Authentication (2FA)

## FAQ

**Q: .msg attachment parsing fails?**
A: Ensure `extract-msg` library is installed

**Q: Gmail login fails?**
A: Need to enable "App Password", do not use email login password

**Q: LLM API error?**
A: Check API key correctness and account quota

**Q: Why can the report format still look slightly unstable sometimes?**
A: Because the raw HTML still comes from an LLM. The project now includes HTML normalization for title dates, pseudo-headings, and action boxes, but smoke tests and manual review are still recommended.

**Q: How do the `daily` deadline and retry rules work?**
A: By default, the system treats “15 minutes before the US market opens” as the `daily` send/receive DDL. During the current briefing session, if all whitelisted sales have already arrived and the recent quiet period has been satisfied, it can send `daily` before that point; if they have not all arrived by the DDL, it stops waiting and sends anyway. After `daily` has been sent, any new whitelist email received within 1 hour after the market opens is handled through `supplement`, which retries analysis and sends a separate supplemental brief.

**Q: How do I watch automatic-mode logs?**
A: By default, running `python main.py` prints these logs to stdout. If you want them persisted to a file as well, start it like this:

```bash
python main.py 2>&1 | tee -a main_runtime.log
```

**Q: What does `Source` mean in the report header?**
A: `Source` tries to show the institution labels recognized from the actual content in this run (for example `MS + JPM + BofA`), not just the mailbox that forwarded or triggered the run. It only falls back to a generic source label when no institution can be confidently recognized.

## Current Architecture

- `main.py`: service entry for FastAPI, background polling, and automatic scheduling
- `qclaw_mail_file.py`: CLI entry for manual triggering and status inspection
- `app/`: unified business engine for mail, pipeline, render, storage, and runtime

## Current Capabilities

- Email ingestion, pending state, and sent-report history are unified in SQLite
- Automatic mode supports single-instance execution and session-aware `daily / supplement` scheduling
- Prompt construction trims signatures, disclaimers, inline image noise, and split-merges oversized inputs
- The multimodal pipeline supports image prescreening, lightweight classification, deep analysis, cached visual context, and summary-stage wiring
- SMTP supports both `587 + STARTTLS` and `465 + SSL`
- The default example chain is `Qwen3-Max -> Domestic Kimi-2.5 -> Overseas Kimi-2.5 -> GPT-5.4`

## Current Validation Status

- The full test suite passes
- The whitelist-positive flow has been validated: receive, analyze, generate, and send
- Non-whitelisted mail is ignored correctly
- Idempotency is validated: no duplicate analysis/report when there is no new pending mail
- `.txt`, `.pdf`, and image attachment flows are covered
- Multi-level fallback has been validated across `llm_backup` / `llm_backup2` / `llm_backup3`

## Future Optimization Items

- Add a US market holiday calendar
- Validate and optimize large-batch / long-attachment pressure scenarios
- Improve asynchronous multimodal processing

## License

MIT License
