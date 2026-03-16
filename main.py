"""
邮件服务 API
功能：
- IMAP 收取邮件
- SMTP 发送邮件

使用：
    pip install -r requirements.txt
    python main.py
"""

import yaml
import os
import re
import asyncio
import logging

# 配置日志
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

# 禁用代理，确保 IMAP/SMTP 连接不受代理影响
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(key, None)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from imap_tools import MailBox
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import json

# 加载配置
CONFIG_FILE = os.path.join(os.path.dirname(__file__), "config.yaml")

def load_config():
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def verify_api_key(api_key: str) -> bool:
    """验证API密钥"""
    if not api_key:
        return False
    stored_key = config.get("api_key", "")
    return api_key == stored_key and stored_key != ""

config = load_config()

app = FastAPI(
    title="邮件服务 API",
    description="IMAP收取 + SMTP发送",
    version="1.0.0"
)

# ============ 数据模型 ============

class EmailConfig(BaseModel):
    address: str
    password: str

class SendEmailRequest(BaseModel):
    to_email: str
    subject: str
    body: str
    body_type: str = "plain"  # plain 或 html

class SendEmailWithConfigRequest(BaseModel):
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    from_email: str
    password: str
    to_email: str
    subject: str
    body: str
    body_type: str = "plain"

# ============ 邮件收取 (IMAP) ============

@app.get("/api/emails")
def get_emails(
    api_key: str = None,
    email: str = None,
    password: str = None,
    folder: str = "INBOX",
    limit: int = 20,
    source: str = "imap.gmail.com"
):
    """
    收取邮件

    参数:
    - api_key: API密钥 (必填)
    - email: 邮箱地址 (可选，默认用配置)
    - password: 应用专用密码 (可选)
    - folder: 文件夹，默认INBOX
    - limit: 获取数量，默认10
    - source: IMAP服务器，默认gmail
    """
    # 验证API密钥
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="API密钥无效或未提供")
    # 使用提供的配置或默认配置
    if email and password:
        email_addr = email
        email_pass = password
    else:
        cfg = config.get("imap", {})
        email_addr = cfg.get("email")
        email_pass = cfg.get("password")

    if not email_addr or not email_pass:
        raise HTTPException(status_code=400, detail="请提供邮箱配置")

    try:
        # 获取过滤配置
        filters = config.get("filters", {})
        allowed_senders = filters.get("allowed_senders", [])

        # 日期过滤：获取今天和昨天的邮件（基于系统本地时区）
        from datetime import datetime, timedelta

        # 自动获取系统本地时区
        local_tz = datetime.now().astimezone().tzinfo
        now_local = datetime.now(local_tz)
        today = now_local.date()
        yesterday = today - timedelta(days=1)

        logger.info(f"📅 日期过滤: {yesterday.strftime('%Y-%m-%d')} ~ {today.strftime('%Y-%m-%d')} (本地时区: {local_tz})")
        logger.info(f"🔍 发件人过滤: {allowed_senders}")

        with MailBox(source, timeout=30).login(email_addr, email_pass) as mailbox:
            emails = []

            # 获取更多邮件以便过滤（默认取50封）
            fetch_limit = max(limit * 5, 50)

            for msg in mailbox.fetch(limit=fetch_limit, reverse=True):
                from_addr = str(msg.from_)
                msg_date = msg.date.date() if msg.date else None

                # 日期过滤：只保留今天和昨天的邮件
                if msg_date and msg_date not in [today, yesterday]:
                    continue

                # 发件人过滤：如果配置了允许列表，只保留匹配的邮件
                if allowed_senders:
                    email_match = re.search(r'<(.+?)>|^(.+?)$', from_addr)
                    if email_match:
                        email_addr = email_match.group(1) or email_match.group(2)
                        matched = False
                        for s in allowed_senders:
                            s_lower = s.lower()
                            if s_lower.startswith('@'):
                                if email_addr.lower().endswith(s_lower):
                                    matched = True
                                    break
                            else:
                                if email_addr.lower() == s_lower:
                                    matched = True
                                    break
                        if not matched:
                            continue

                # 获取正文
                body = msg.text or msg.html or ""

                # ============ 附件解析 ============
                attachment_contents = []
                embedded_images = []  # 附件中的图片

                # 支持的图片格式
                IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif')

                if msg.attachments:
                    for att in msg.attachments:
                        if not att.filename:
                            continue

                        filename = att.filename.lower()

                        try:
                            # 获取附件数据
                            att_data = None
                            if hasattr(att, 'payload') and isinstance(att.payload, bytes):
                                att_data = att.payload
                            elif hasattr(att, 'data'):
                                att_data = att.data

                            if not att_data:
                                continue

                            # 检查是否是图片附件
                            is_image = any(filename.endswith(ext) for ext in IMAGE_EXTENSIONS)

                            if is_image:
                                # 保存图片附件（base64编码），让AI理解图片
                                b64_data = base64.b64encode(att_data).decode('utf-8')
                                img_format = filename.split('.')[-1]
                                if img_format == 'jpeg':
                                    img_format = 'jpeg'
                                embedded_images.append({
                                    "filename": att.filename,
                                    "base64": f"data:image/{img_format};base64,{b64_data}"
                                })
                                continue

                            # 文本类附件解析
                            att_text = ""
                            if filename.endswith('.msg'):
                                import extract_msg
                                from io import BytesIO
                                msg_file = extract_msg.Message(BytesIO(att_data))
                                att_text = msg_file.body or ""

                            elif filename.endswith('.pdf'):
                                try:
                                    import PyPDF2
                                    from io import BytesIO
                                    pdf_reader = PyPDF2.PdfReader(BytesIO(att_data))
                                    for page in pdf_reader.pages:
                                        att_text += page.extract_text() or ""
                                except Exception as e:
                                    logger.warning(f"PDF解析失败 {att.filename}: {e}")

                            elif filename.endswith(('.docx', '.doc')):
                                try:
                                    import docx
                                    from io import BytesIO
                                    doc = docx.Document(BytesIO(att_data))
                                    for para in doc.paragraphs:
                                        att_text += para.text + "\n"
                                except Exception as e:
                                    logger.warning(f"Word解析失败 {att.filename}: {e}")

                            elif filename.endswith('.txt'):
                                try:
                                    att_text = att_data.decode('utf-8', errors='ignore')
                                except:
                                    pass

                            elif filename.endswith('.eml'):
                                try:
                                    from email import policy
                                    from email.parser import BytesParser
                                    nested_msg = BytesParser(policy=policy.default).parsebytes(att_data)
                                    att_text = nested_msg.body or ""
                                except Exception as e:
                                    logger.warning(f"EML解析失败 {att.filename}: {e}")

                            if att_text and att_text.strip():
                                attachment_contents.append({
                                    "filename": att.filename,
                                    "content": att_text.strip()
                                })

                        except Exception as e:
                            logger.warning(f"附件解析失败 {att.filename}: {e}")
                            continue

                # 合并正文和附件内容
                combined_body = body or ""
                if attachment_contents:
                    combined_body += "\n\n--- 附件内容 ---\n"
                    for att in attachment_contents:
                        combined_body += f"\n【附件: {att['filename']}】\n{att['content']}\n"

                # 将图片嵌入HTML，让AI理解图片内容
                if embedded_images:
                    combined_body += "\n\n--- 附件图片 ---\n"
                    for img in embedded_images:
                        combined_body += f"\n<img src='{img['base64']}' alt='{img['filename']}'>\n"

                emails.append({
                    "id": msg.uid,
                    "from": from_addr,
                    "from_name": msg.from_values.name if msg.from_values else "",
                    "to": str(msg.to),
                    "subject": msg.subject,
                    "date": str(msg.date) if msg.date else "",
                    "preview": (combined_body or "")[:200],
                    "body": combined_body
                })
            return {"success": True, "emails": emails, "total": len(emails)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"收取邮件失败: {str(e)}")


@app.get("/api/emails/{email_id}")
def get_email_by_id(
    email_id: int,
    email: str = None,
    password: str = None,
    source: str = "imap.gmail.com"
):
    """根据ID获取单封邮件详情"""
    if email and password:
        email_addr = email
        email_pass = password
    else:
        cfg = config.get("default_email", {})
        email_addr = cfg.get("address")
        email_pass = cfg.get("password")

    try:
        with MailBox(source, timeout=30).login(email_addr, email_pass) as mailbox:
            for msg in mailbox.fetch(limit=100, reverse=True):
                if msg.uid == email_id:
                    return {
                        "success": True,
                        "email": {
                            "id": msg.uid,
                            "from": str(msg.from_),
                            "from_name": msg.from_values.name if msg.from_values else "",
                            "to": str(msg.to),
                            "subject": msg.subject,
                            "date": str(msg.date) if msg.date else "",
                            "body": msg.text or msg.html or "",
                            "read": msg.seen
                        }
                    }
            raise HTTPException(status_code=404, detail="邮件未找到")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ============ 邮件发送 (SMTP) ============

@app.post("/api/send")
async def send_email(
    api_key: str = None,
    request: SendEmailRequest = None
):
    """发送邮件 (使用默认配置) - 需要API密钥"""
    print(f"[DEBUG] 收到发送请求: api_key={api_key}, request={request}")
    
    # 验证API密钥
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="API密钥无效或未提供")
    
    if request is None:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    # 使用配置文件中的IMAP配置（作为发送方）
    imap_cfg = config.get("imap", {})
    smtp_cfg = config.get("smtp", {})

    return await send_email_smtp(
        smtp_host=smtp_cfg.get("host", "smtp.gmail.com"),
        smtp_port=smtp_cfg.get("port", 587),
        from_email=smtp_cfg.get("email"),
        password=smtp_cfg.get("password"),
        to_email=request.to_email,
        subject=request.subject,
        body=request.body,
        body_type=request.body_type
    )


@app.post("/api/send/custom")
async def send_email_custom(request: SendEmailWithConfigRequest):
    """发送邮件 (自定义配置)"""
    return await send_email_smtp(
        smtp_host=request.smtp_host,
        smtp_port=request.smtp_port,
        from_email=request.from_email,
        password=request.password,
        to_email=request.to_email,
        subject=request.subject,
        body=request.body,
        body_type=request.body_type
    )


def _send_email_sync(smtp_host, smtp_port, from_email, password, to_email, subject, body, body_type):
    """同步发送邮件（在线程池中运行）"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email

    # 添加正文
    msg.attach(MIMEText(body, body_type, 'utf-8'))

    # 发送
    server = smtplib.SMTP(smtp_host, smtp_port)
    server.starttls()
    server.login(from_email, password)
    server.send_message(msg)
    server.quit()

    return {"success": True, "message": "邮件发送成功"}


async def send_email_smtp(smtp_host, smtp_port, from_email, password, to_email, subject, body, body_type):
    """SMTP发送邮件的核心逻辑（异步包装）"""
    try:
        # 使用线程池执行同步的SMTP操作
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(
            None,
            _send_email_sync,
            smtp_host, smtp_port, from_email, password, 
            to_email, subject, body, body_type
        )
        return result
    except Exception as e:
        import traceback
        print(f"[ERROR] SMTP发送失败: {e}")
        print(traceback.format_exc())
        raise HTTPException(status_code=500, detail=f"发送失败: {str(e)}")


# ============ 状态检查 ============

@app.get("/")
async def root():
    return {"service": "邮件服务 API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "ok"}


# ============ 启动 ============

if __name__ == "__main__":
    import uvicorn
    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "0.0.0.0")
    port = server_cfg.get("port", 8765)
    print(f"🚀 邮件服务 API 启动中...")
    print(f"   地址: http://{host}:{port}")
    print(f"   健康检查: http://{host}:{port}/health")
    uvicorn.run(
        app,
        host=host,
        port=port
    )
