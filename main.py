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
import base64
import socket
from asyncio.subprocess import PIPE
from contextlib import asynccontextmanager

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
from email.utils import parseaddr
import json
from datetime import datetime, time, timedelta
from typing import Optional
import pytz
import email_db
from zoneinfo import ZoneInfo

# 加载配置
CONFIG_FILE = os.getenv("EMAIL_SERVICE_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml"))

def load_config():
    try:
        with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning(f"配置文件不存在: {CONFIG_FILE}")
        return {}
    except Exception as e:
        logger.error(f"加载配置失败: {e}")
        return {}

def verify_api_key(api_key: str) -> bool:
    """验证API密钥"""
    if not api_key:
        return False
    stored_key = load_config().get("api_key", "")
    return api_key == stored_key and stored_key != ""

config = load_config()


background_tasks = []
analysis_task_lock = None
IMAGE_EXTENSIONS = ('.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.heic', '.heif')
MAX_MULTIMODAL_IMAGE_BYTES = 4 * 1024 * 1024
MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS = 12000
ATTACHMENT_SIGNATURE_MARKERS = (
    "best regards",
    "kind regards",
    "warm regards",
    "regards",
    "many thanks",
    "thanks,",
    "thanks and regards",
    "thank you,",
    "cheers,",
    "sent from my iphone",
    "sent from my ipad",
    "sent from outlook",
    "sent via outlook",
    "此致",
    "敬礼",
    "祝好",
    "谢谢",
    "--",
)
ATTACHMENT_DISCLAIMER_MARKERS = (
    "免责声明",
    "confidentiality notice",
    "this message and any attachment",
    "this e-mail and any attachments",
    "this email and any attachments",
    "the information contained in this e-mail",
    "the information contained in this email",
    "the contents of this email",
    "privileged and confidential",
    "本邮件及其附件",
    "本电子邮件",
    "重要提示",
    "法律声明",
)


def get_analysis_task_lock() -> asyncio.Lock:
    """延迟创建分析互斥锁，避免模块导入时提前绑定默认 event loop。"""
    global analysis_task_lock
    if analysis_task_lock is None:
        analysis_task_lock = asyncio.Lock()
    return analysis_task_lock


def _extract_attachment_bytes(att):
    """统一提取附件二进制。"""
    if hasattr(att, "payload") and isinstance(att.payload, bytes):
        return att.payload
    if hasattr(att, "data") and isinstance(att.data, bytes):
        return att.data
    return None


def _clean_extracted_attachment_text(text, filename=""):
    """清洗 .msg/.eml/.pdf 等附件提取文本，避免原始转发噪音压垮分析上下文。"""
    if not text:
        return ""

    cleaned = text.replace("\r\n", "\n").replace("\r", "\n")
    cleaned = cleaned.replace("\u200b", " ").replace("\xa0", " ")
    cleaned = re.sub(r"<https?://[^>\s]+>", "[link]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"https?://\S+", "[link]", cleaned, flags=re.IGNORECASE)

    kept_lines = []
    meaningful_chars = 0
    non_empty_lines = 0

    for line in cleaned.split("\n"):
        stripped = line.strip()
        normalized = stripped.lower()

        if stripped:
            non_empty_lines += 1
            meaningful_chars += len(stripped)

        has_enough_content = meaningful_chars >= 80 or non_empty_lines >= 4
        if has_enough_content:
            if any(normalized.startswith(marker) for marker in ATTACHMENT_SIGNATURE_MARKERS) and len(stripped) <= 120:
                break
            if any(marker in normalized for marker in ATTACHMENT_DISCLAIMER_MARKERS):
                break

        kept_lines.append(line)

    cleaned = "\n".join(kept_lines)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned).strip()

    if len(cleaned) > MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS:
        cleaned = cleaned[:MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS].rstrip() + "\n\n[附件内容已截断]"

    return cleaned


def _build_attachment_records(msg):
    """提取附件记录；图片默认保留 data URL 供多模态模型直接使用。"""
    attachment_contents = []
    embedded_images = []
    attachment_records = []

    if not msg.attachments:
        return attachment_contents, embedded_images, attachment_records

    for att in msg.attachments:
        if not att.filename:
            continue

        filename = att.filename
        lower_filename = filename.lower()
        content_type = getattr(att, "content_type", "") or "application/octet-stream"

        try:
            att_data = _extract_attachment_bytes(att)
            if not att_data:
                continue

            is_image = content_type.startswith("image/") or any(lower_filename.endswith(ext) for ext in IMAGE_EXTENSIONS)
            attachment_record = {
                "filename": filename,
                "content_type": content_type,
                "size": len(att_data),
                "kind": "image" if is_image else "file",
            }

            if is_image:
                if len(att_data) <= MAX_MULTIMODAL_IMAGE_BYTES:
                    attachment_record["data_url"] = (
                        f"data:{content_type};base64,{base64.b64encode(att_data).decode('ascii')}"
                    )
                    attachment_record["vision_ready"] = True
                else:
                    attachment_record["vision_ready"] = False
                    attachment_record["vision_skip_reason"] = (
                        f"image_too_large>{MAX_MULTIMODAL_IMAGE_BYTES}"
                    )

                embedded_images.append({
                    "filename": filename,
                    "content_type": content_type,
                    "size": len(att_data),
                    "vision_ready": attachment_record.get("vision_ready", False),
                })
                attachment_records.append(attachment_record)
                continue

            att_text = ""
            if lower_filename.endswith('.msg'):
                import extract_msg
                from io import BytesIO
                msg_file = extract_msg.Message(BytesIO(att_data))
                att_text = msg_file.body or ""

            elif lower_filename.endswith('.pdf'):
                try:
                    import PyPDF2
                    from io import BytesIO
                    pdf_reader = PyPDF2.PdfReader(BytesIO(att_data))
                    for page in pdf_reader.pages:
                        att_text += page.extract_text() or ""
                except Exception as e:
                    logger.warning(f"PDF解析失败 {filename}: {e}")

            elif lower_filename.endswith(('.docx', '.doc')):
                try:
                    import docx
                    from io import BytesIO
                    doc = docx.Document(BytesIO(att_data))
                    for para in doc.paragraphs:
                        att_text += para.text + "\n"
                except Exception as e:
                    logger.warning(f"Word解析失败 {filename}: {e}")

            elif lower_filename.endswith('.txt'):
                try:
                    att_text = att_data.decode('utf-8', errors='ignore')
                except Exception:
                    att_text = ""

            elif lower_filename.endswith('.eml'):
                try:
                    from email import policy
                    from email.parser import BytesParser
                    nested_msg = BytesParser(policy=policy.default).parsebytes(att_data)
                    att_text = nested_msg.body or ""
                except Exception as e:
                    logger.warning(f"EML解析失败 {filename}: {e}")

            att_text = _clean_extracted_attachment_text(att_text, filename=filename)

            if att_text and att_text.strip():
                attachment_contents.append({
                    "filename": filename,
                    "content": att_text.strip()
                })
                attachment_record["extracted_text"] = att_text.strip()

            attachment_records.append(attachment_record)
        except Exception as e:
            logger.warning(f"附件解析失败 {filename}: {e}")
            continue

    return attachment_contents, embedded_images, attachment_records


def get_message_local_date(msg_datetime, local_tz):
    """将邮件时间统一转换到本地时区后再取日期，避免跨时区邮件被误过滤。"""
    if not msg_datetime:
        return None
    if msg_datetime.tzinfo is None:
        return msg_datetime.date()
    return msg_datetime.astimezone(local_tz).date()


def get_message_local_datetime(msg_datetime, local_tz):
    """将邮件时间统一转换到本地时区。"""
    if not msg_datetime:
        return None
    if msg_datetime.tzinfo is None:
        if hasattr(local_tz, "localize"):
            return local_tz.localize(msg_datetime)
        return msg_datetime.replace(tzinfo=local_tz)
    return msg_datetime.astimezone(local_tz)


def parse_received_after_local(filters: dict, local_tz):
    """解析可选的本地时间阈值，用于联调时忽略历史邮件。"""
    raw_value = (filters or {}).get("received_after_local")
    if not raw_value:
        return None
    try:
        parsed = datetime.fromisoformat(str(raw_value))
        if parsed.tzinfo is None:
            if hasattr(local_tz, "localize"):
                return local_tz.localize(parsed)
            return parsed.replace(tzinfo=local_tz)
        return parsed.astimezone(local_tz)
    except Exception:
        logger.warning(f"无效的 received_after_local 配置: {raw_value}")
        return None


def extract_sender_email(from_addr: str) -> str:
    """从发件人字段中提取纯邮箱地址。"""
    if not from_addr:
        return ""
    _, email_addr = parseaddr(from_addr)
    return (email_addr or from_addr).strip().lower()


def match_allowed_sender(email_addr: str, allowed_senders: list) -> Optional[str]:
    """返回命中的白名单项（精确邮箱或后缀），未命中则返回 None。"""
    normalized_email = (email_addr or "").strip().lower()
    for sender in allowed_senders or []:
        sender_key = (sender or "").strip().lower()
        if not sender_key:
            continue
        if sender_key.startswith("@"):
            if normalized_email.endswith(sender_key):
                return sender_key
        elif normalized_email == sender_key:
            return sender_key
    return None


def should_accept_sender(from_addr: str, allowed_senders: list) -> bool:
    """统一发件人过滤逻辑。"""
    if not allowed_senders:
        return True
    return match_allowed_sender(extract_sender_email(from_addr), allowed_senders) is not None


def get_expected_senders(cfg: dict) -> list:
    """获取当前自动触发逻辑中要等待的全部白名单 sales 名单。"""
    filters = cfg.get("filters", {})
    return [(sender or "").strip().lower() for sender in filters.get("allowed_senders", []) if sender]


def get_received_sender_matches_for_today(allowed_senders: list, reference_time: Optional[datetime] = None) -> set:
    """返回当天自然日内已收到并命中的白名单 sales 集合。"""
    if not allowed_senders:
        return set()

    today_str = _ensure_bjt(reference_time).strftime("%Y-%m-%d")
    matches = set()
    for raw_sender in email_db.get_sender_addresses_for_created_date(today_str):
        matched = match_allowed_sender(extract_sender_email(raw_sender), allowed_senders)
        if matched:
            matches.add(matched)
    return matches


def get_briefing_session_start(reference_time: Optional[datetime] = None) -> datetime:
    """定义一轮盘前 briefing 的起点：最近一个美股交易日收盘（16:00 ET）后的北京时间。"""
    now_bjt = _ensure_bjt(reference_time)

    for day_offset in range(0, 8):
        candidate_date_et = now_bjt.astimezone(US_ET).date() - timedelta(days=day_offset)
        if candidate_date_et.weekday() >= 5:
            continue

        market_close_et = datetime.combine(candidate_date_et, time(16, 0), tzinfo=US_ET)
        market_close_bjt = market_close_et.astimezone(BJT)
        if market_close_bjt < now_bjt:
            return market_close_bjt

    raise RuntimeError("无法计算最近一个 briefing session 的起点")


def get_received_sender_matches_for_session(allowed_senders: list, reference_time: Optional[datetime] = None) -> set:
    """返回当前 briefing session 内已收到并命中的白名单 sales 集合。"""
    if not allowed_senders:
        return set()

    session_start = get_briefing_session_start(reference_time).isoformat()
    matches = set()
    for raw_sender in email_db.get_sender_addresses_created_since(session_start):
        matched = match_allowed_sender(extract_sender_email(raw_sender), allowed_senders)
        if matched:
            matches.add(matched)
    return matches


def all_expected_senders_arrived_for_session(allowed_senders: list, reference_time: Optional[datetime] = None) -> bool:
    """判断当前 briefing session 内是否已经收齐全部白名单 sales 邮件。"""
    expected = {(sender or "").strip().lower() for sender in allowed_senders or [] if sender}
    if not expected:
        return False
    received = get_received_sender_matches_for_session(list(expected), reference_time)
    return expected.issubset(received)


def should_trigger_early_daily(allowed_senders: list, bg_cfg: dict, reference_time: Optional[datetime] = None) -> tuple[bool, str]:
    """盘前提前触发规则：白名单全到齐 + session 内邮件够多 + 最近 N 分钟无新邮件。"""
    now_bjt = _ensure_bjt(reference_time)
    quiet_minutes = int(bg_cfg.get("early_quiet_minutes", 10) or 10)
    min_new_emails = int(bg_cfg.get("early_min_new_emails", max(2, len(allowed_senders) or 0)) or max(2, len(allowed_senders) or 0))
    session_start = get_briefing_session_start(now_bjt)
    expected = {(sender or "").strip().lower() for sender in allowed_senders or [] if sender}
    received = get_received_sender_matches_for_session(list(expected), now_bjt)
    missing = sorted(expected - received)

    if expected and not expected.issubset(received):
        return False, (
            f"白名单 sales 尚未在本轮 session 内全部到齐；"
            f"session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, "
            f"已到齐={sorted(received)}, 缺失={missing}"
        )

    session_email_count = email_db.count_emails_created_since(session_start.isoformat())
    if session_email_count < min_new_emails:
        return False, (
            f"本轮 session 邮件数不足（{session_email_count}/{min_new_emails}）；"
            f"session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, 已到齐={sorted(received)}"
        )

    if email_db.has_new_email_within_minutes(quiet_minutes, now_bjt):
        return False, (
            f"最近 {quiet_minutes} 分钟仍有新邮件，继续等待；"
            f"session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, 已到齐={sorted(received)}, "
            f"session邮件数={session_email_count}"
        )

    return True, (
        f"满足 early run 条件：session_start={session_start.strftime('%Y-%m-%d %H:%M:%S')}, "
        f"已到齐={sorted(received)}, 邮件数={session_email_count}, quiet={quiet_minutes}m"
    )


def all_expected_senders_arrived(allowed_senders: list, reference_time: Optional[datetime] = None) -> bool:
    """兼容旧调用：按当前 briefing session 口径判断是否已收齐白名单 sales。"""
    return all_expected_senders_arrived_for_session(allowed_senders, reference_time)


def has_daily_report_sent_today(reference_time: Optional[datetime] = None) -> bool:
    """判断今天是否已经成功发送过 daily 报告。"""
    today_str = _ensure_bjt(reference_time).strftime("%Y-%m-%d")
    return email_db.has_successful_report_on_date(today_str, report_type="daily")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan：在运行循环内启动/回收后台任务。"""
    global config
    config = load_config()

    bg_cfg = config.get("background", {})
    if bg_cfg.get("enabled", False):
        background_tasks.append(asyncio.create_task(background_fetch_loop()))
    if bg_cfg.get("analysis_enabled", False):
        background_tasks.append(asyncio.create_task(scheduled_analysis_loop()))

    try:
        yield
    finally:
        for task in background_tasks:
            task.cancel()
        if background_tasks:
            await asyncio.gather(*background_tasks, return_exceptions=True)
        background_tasks.clear()


app = FastAPI(
    title="邮件服务 API",
    description="IMAP收取 + SMTP发送",
    version="1.0.0",
    lifespan=lifespan,
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
    use_ssl: bool = False
    timeout_seconds: int = 30
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
    cfg = load_config()

    if email and password:
        email_addr = email
        email_pass = password
    else:
        imap_cfg = cfg.get("imap", {})
        email_addr = imap_cfg.get("email")
        email_pass = imap_cfg.get("password")

    if not email_addr or not email_pass:
        raise HTTPException(status_code=400, detail="请提供邮箱配置")

    try:
        # 自动获取系统本地时区
        local_tz = datetime.now().astimezone().tzinfo

        # 获取过滤配置
        filters = cfg.get("filters", {})
        allowed_senders = filters.get("allowed_senders", [])
        received_after_local = parse_received_after_local(filters, local_tz)

        if received_after_local:
            logger.info(f"📅 收件起点: {received_after_local.isoformat()} (本地时区: {local_tz})")
        else:
            logger.info(f"📅 收件起点: 不限制 (本地时区: {local_tz})")
        logger.info(f"🔍 发件人过滤: {allowed_senders}")

        with MailBox(source, timeout=30).login(email_addr, email_pass) as mailbox:
            emails = []

            # 获取更多邮件以便过滤（默认取50封）
            fetch_limit = max(limit * 5, 50)

            for msg in mailbox.fetch(limit=fetch_limit, reverse=True):
                from_addr = str(msg.from_)
                msg_local_dt = get_message_local_datetime(msg.date, local_tz)

                # 可选联调过滤：忽略某个本地时间点之前的历史邮件
                if received_after_local and msg_local_dt and msg_local_dt < received_after_local:
                    continue

                # 发件人过滤：如果配置了允许列表，只保留匹配的邮件
                if not should_accept_sender(from_addr, allowed_senders):
                    continue

                # 获取正文
                body = msg.text or msg.html or ""

                # ============ 附件解析 ============
                attachment_contents, embedded_images, attachment_records = _build_attachment_records(msg)

                # 合并正文和附件内容
                combined_body = body or ""
                if attachment_contents:
                    combined_body += "\n\n--- 附件内容 ---\n"
                    for att in attachment_contents:
                        combined_body += f"\n【附件: {att['filename']}】\n{att['content']}\n"

                # 图片附件元数据仍保留在正文中，真实图片会通过 attachments 走多模态分析链路
                if embedded_images:
                    combined_body += "\n\n--- 附件图片 ---\n"
                    for img in embedded_images:
                        vision_status = "将直接送入多模态模型" if img.get("vision_ready") else "仅保留元数据（图片过大）"
                        combined_body += (
                            f"\n【图片附件: {img['filename']}】"
                            f" 类型: {img['content_type']}, 大小: {img['size']} bytes, 处理方式: {vision_status}\n"
                        )

                emails.append({
                    "account_email": email_addr,
                    "folder": folder,
                    "id": msg.uid,
                    "from": from_addr,
                    "from_name": msg.from_values.name if msg.from_values else "",
                    "to": str(msg.to),
                    "subject": msg.subject,
                    "date": str(msg.date) if msg.date else "",
                    "preview": (combined_body or "")[:200],
                    "body": combined_body,
                    "attachments": json.dumps(attachment_records, ensure_ascii=False) if attachment_records else None,
                })
            return {"success": True, "emails": emails, "total": len(emails)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"收取邮件失败: {str(e)}")


@app.get("/api/emails/{email_id}")
def get_email_by_id(
    email_id: int,
    api_key: str = None,
    email: str = None,
    password: str = None,
    source: str = "imap.gmail.com"
):
    """根据ID获取单封邮件详情"""
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="API密钥无效或未提供")

    cfg = load_config()

    if email and password:
        email_addr = email
        email_pass = password
    else:
        imap_cfg = cfg.get("imap", {})
        email_addr = imap_cfg.get("email")
        email_pass = imap_cfg.get("password")

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
    # 验证API密钥
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="API密钥无效或未提供")
    
    if request is None:
        raise HTTPException(status_code=400, detail="请求体不能为空")

    smtp_cfg = load_config().get("smtp", {})

    return await send_email_smtp(
        smtp_host=smtp_cfg.get("host", "smtp.gmail.com"),
        smtp_port=smtp_cfg.get("port", 587),
        use_ssl=smtp_cfg.get("use_ssl", False),
        timeout_seconds=smtp_cfg.get("timeout_seconds", 30),
        from_email=smtp_cfg.get("email"),
        password=smtp_cfg.get("password"),
        to_email=request.to_email,
        subject=request.subject,
        body=request.body,
        body_type=request.body_type
    )


@app.post("/api/send/custom")
async def send_email_custom(api_key: str = None, request: SendEmailWithConfigRequest = None):
    """发送邮件 (自定义配置)"""
    if not verify_api_key(api_key):
        raise HTTPException(status_code=401, detail="API密钥无效或未提供")
    if request is None:
        raise HTTPException(status_code=400, detail="请求体不能为空")
    return await send_email_smtp(
        smtp_host=request.smtp_host,
        smtp_port=request.smtp_port,
        use_ssl=request.use_ssl,
        timeout_seconds=request.timeout_seconds,
        from_email=request.from_email,
        password=request.password,
        to_email=request.to_email,
        subject=request.subject,
        body=request.body,
        body_type=request.body_type
    )


def _send_email_sync(smtp_host, smtp_port, use_ssl, timeout_seconds, from_email, password, to_email, subject, body, body_type):
    """同步发送邮件（在线程池中运行）"""
    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = from_email
    msg['To'] = to_email

    # 添加正文
    msg.attach(MIMEText(body, body_type, 'utf-8'))

    # 发送
    use_ssl = use_ssl or smtp_port == 465
    server = None
    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout_seconds)
        else:
            server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout_seconds)
            server.ehlo()
            server.starttls()
            server.ehlo()
        server.login(from_email, password)
        server.send_message(msg)
    finally:
        if server is not None:
            try:
                server.quit()
            except Exception:
                pass

    return {"success": True, "message": "邮件发送成功"}


def classify_smtp_exception(exc: Exception) -> tuple[int, str]:
    """将 SMTP 异常映射为更清晰的 HTTP 状态码与错误信息。"""
    if isinstance(exc, (socket.timeout, TimeoutError)):
        return 504, f"SMTP连接或发送超时: {exc}"
    if isinstance(exc, smtplib.SMTPAuthenticationError):
        return 502, "SMTP认证失败，请检查邮箱地址、授权码或应用专用密码"
    if isinstance(exc, (smtplib.SMTPConnectError, smtplib.SMTPServerDisconnected, ConnectionRefusedError, OSError)):
        return 502, f"SMTP连接失败: {exc}"
    return 500, f"发送失败: {exc}"


async def send_email_smtp(smtp_host, smtp_port, from_email, password, to_email, subject, body, body_type, use_ssl=False, timeout_seconds=30):
    """SMTP发送邮件的核心逻辑（异步包装）"""
    try:
        return await asyncio.to_thread(
            _send_email_sync,
            smtp_host,
            smtp_port,
            use_ssl,
            timeout_seconds,
            from_email,
            password,
            to_email,
            subject,
            body,
            body_type,
        )
    except Exception as e:
        status_code, detail = classify_smtp_exception(e)
        raise HTTPException(status_code=status_code, detail=detail)


# ============ 状态检查 ============

@app.get("/")
async def root():
    return {"service": "邮件服务 API", "version": "1.0.0"}

@app.get("/health")
async def health():
    return {"status": "ok"}


# ============ 后台定时收取邮件 ============

BJT = pytz.timezone('Asia/Shanghai')
US_ET = ZoneInfo("America/New_York")
background_task = None


def runtime_timestamp() -> str:
    """统一的运行时日志时间戳，方便录屏时观察轮询/触发节奏。"""
    return datetime.now().astimezone().strftime("%H:%M:%S")


def runtime_print(message: str) -> None:
    print(f"[{runtime_timestamp()}] {message}")


def _fetch_emails_for_db_sync(host: str, email_addr: str, email_pass: str, allowed_senders: list, local_tz, received_after_local, limit: int, folder: str = "INBOX"):
    """同步收取邮件（供 asyncio.to_thread 调用）"""
    emails = []
    fetch_limit = max(limit * 5, 50)

    with MailBox(host, timeout=30).login(email_addr, email_pass) as mailbox:
        for msg in mailbox.fetch(limit=fetch_limit, reverse=True):
            from_addr = str(msg.from_)
            msg_local_dt = get_message_local_datetime(msg.date, local_tz)

            if received_after_local and msg_local_dt and msg_local_dt < received_after_local:
                continue

            if not should_accept_sender(from_addr, allowed_senders):
                continue

            attachment_contents, embedded_images, attachment_records = _build_attachment_records(msg)

            combined_body = msg.html or msg.text or ""
            if attachment_contents:
                combined_body += "\n\n--- 附件内容 ---\n"
                for att in attachment_contents:
                    combined_body += f"\n【附件: {att['filename']}】\n{att['content']}\n"

            if embedded_images:
                combined_body += "\n\n--- 附件图片 ---\n"
                for img in embedded_images:
                    vision_status = "将直接送入多模态模型" if img.get("vision_ready") else "仅保留元数据（图片过大）"
                    combined_body += (
                        f"\n【图片附件: {img['filename']}】"
                        f" 类型: {img['content_type']}, 大小: {img['size']} bytes, 处理方式: {vision_status}\n"
                    )

            emails.append({
                "account_email": email_addr,
                "folder": folder,
                "id": msg.uid,
                "from": from_addr,
                "from_name": msg.from_values.name if msg.from_values else "",
                "to": str(msg.to),
                "subject": msg.subject,
                "date": msg.date.isoformat() if msg.date else "",
                "body": combined_body,
                "attachments": json.dumps(attachment_records, ensure_ascii=False) if attachment_records else None,
            })

            if len(emails) >= limit:
                break

    return emails


async def fetch_and_save_emails():
    """后台任务：收取邮件并保存到数据库"""
    cfg = load_config()
    bg_cfg = cfg.get("background", {})
    if not bg_cfg.get("enabled", False):
        return

    imap_cfg = cfg.get("imap", {})
    email_addr = imap_cfg.get("email")
    email_pass = imap_cfg.get("password")
    host = imap_cfg.get("host", "imap.gmail.com")
    limit = bg_cfg.get("limit", 20)

    local_tz = datetime.now().astimezone().tzinfo
    now_local = datetime.now(local_tz)

    # 获取过滤配置
    filters = cfg.get("filters", {})
    allowed_senders = filters.get("allowed_senders", [])
    received_after_local = parse_received_after_local(filters, local_tz)

    # 获取数据库状态
    status = email_db.get_status()

    runtime_print(f"📬 [后台] 正在收取邮件...")
    if received_after_local:
        runtime_print(f"   📅 收件起点: {received_after_local.strftime('%Y-%m-%d %H:%M:%S %z')}")
    else:
        runtime_print("   📅 收件起点: 不限制（按邮箱最新邮件顺序回溯）")
    runtime_print(f"   🔍 发件人过滤: {allowed_senders}")
    runtime_print(f"   📊 数据库状态: 总计 {status['total']}, 待处理 {status['pending']}, 已处理 {status['processed']}")

    try:
        emails = await asyncio.to_thread(
            _fetch_emails_for_db_sync,
            host,
            email_addr,
            email_pass,
            allowed_senders,
            local_tz,
            received_after_local,
            limit,
        )

        # 保存到数据库（自动去重）
        added_count = email_db.add_emails(emails)

        runtime_print(f"✅ [后台] 新邮件: {added_count} 封，已存入数据库")
        runtime_print(f"   📊 待处理邮件: {email_db.get_status()['pending']} 封")

        # 早触发：只有当本轮 session 内白名单 sales 全部到齐、邮件数量足够且最近一段时间安静时，才提前跑 daily。
        if not has_daily_report_sent_today():
            should_early_run, reason = should_trigger_early_daily(allowed_senders, bg_cfg, now_local)
            if should_early_run:
                runtime_print(f"🚀 [后台] 提前触发 daily 分析：{reason}")
                await trigger_daily_analysis(reason="all_senders_arrived_quiet")
                return
            runtime_print(f"   ⏳ 本轮暂不 early run：{reason}")

        # 检查是否在补充分析时间窗口内
        if added_count > 0 and is_in_supplement_window():
            # 触发补充分析
            await trigger_supplement_analysis(added_count)
    except Exception as e:
        runtime_print(f"❌ [后台] 收取邮件失败: {e}")


async def background_fetch_loop():
    """后台循环：定期收取邮件"""
    bg_cfg = load_config().get("background", {})
    if not bg_cfg.get("enabled", False):
        runtime_print("⚠️ 后台收取已禁用")
        return

    interval = bg_cfg.get("interval_minutes", 15) * 60
    runtime_print(f"⏰ 后台收取已启用，每 {bg_cfg.get('interval_minutes', 15)} 分钟收取一次邮件")

    while True:
        await fetch_and_save_emails()
        await asyncio.sleep(interval)


def _ensure_bjt(dt_value: Optional[datetime] = None) -> datetime:
    """将时间标准化到北京时间 aware datetime。"""
    dt_value = dt_value or datetime.now(BJT)
    if dt_value.tzinfo is None:
        return BJT.localize(dt_value)
    return dt_value.astimezone(BJT)


def _market_session_bounds_bjt(reference_time: Optional[datetime] = None) -> tuple[datetime, datetime, datetime]:
    """返回当前美东日期对应的 trigger/open/window_end 的北京时间。"""
    now_bjt = _ensure_bjt(reference_time)
    now_et = now_bjt.astimezone(US_ET)

    # 周末没有美股常规交易时段，直接映射到当天美东日期对应的时间点，由调用方决定是否跳过。
    session_date_et = now_et.date()
    market_open_et = datetime.combine(session_date_et, time(9, 30), tzinfo=US_ET)
    trigger_et = market_open_et - timedelta(minutes=15)
    window_end_et = market_open_et + timedelta(hours=1)

    return (
        trigger_et.astimezone(BJT),
        market_open_et.astimezone(BJT),
        window_end_et.astimezone(BJT),
    )


def get_next_market_trigger_time(reference_time: Optional[datetime] = None) -> datetime:
    """获取下一个美股开盘前 15 分钟触发点（北京时间，自动跳过周末）。"""
    now_bjt = _ensure_bjt(reference_time)
    session_time_et = now_bjt.astimezone(US_ET)
    session_date_et = session_time_et.date()

    for day_offset in range(8):
        candidate_date = session_date_et + timedelta(days=day_offset)
        if candidate_date.weekday() >= 5:
            continue

        trigger_et = datetime.combine(candidate_date, time(9, 15), tzinfo=US_ET)
        trigger_bjt = trigger_et.astimezone(BJT)
        if trigger_bjt > now_bjt:
            return trigger_bjt

    raise RuntimeError("无法计算下一个美股开盘触发时间")


def get_us_market_open_time(reference_time: Optional[datetime] = None):
    """返回下一个美股开盘前 15 分钟触发点的北京时间小时和分钟。"""
    next_trigger = get_next_market_trigger_time(reference_time)
    return next_trigger.hour, next_trigger.minute


def is_in_supplement_window(reference_time: Optional[datetime] = None):
    """检查当前是否在补充分析时间窗口内（开盘前15分钟到开盘后1小时）"""
    now_bjt = _ensure_bjt(reference_time)
    now_et = now_bjt.astimezone(US_ET)
    if now_et.weekday() >= 5:
        return False

    window_start, _, window_end = _market_session_bounds_bjt(now_bjt)
    return window_start <= now_bjt <= window_end


async def trigger_supplement_analysis(new_emails_count: int):
    """触发补充分析（针对延迟邮件）"""
    if new_emails_count == 0:
        return

    if not has_daily_report_sent_today():
        runtime_print("   ⏭️ 今日尚未发送 daily 报告，跳过 supplement")
        return

    analysis_lock = get_analysis_task_lock()
    if analysis_lock.locked():
        runtime_print("   ⏭️ 当前已有分析任务运行中，跳过本次 supplement")
        return

    # 检查是否有待处理邮件
    pending_emails = email_db.get_pending_emails(limit=50)
    if not pending_emails:
        runtime_print("   📭 没有待处理的邮件，跳过补充分析")
        return

    # 只对 supplement 自己做节流，避免刚发完 daily 就把应发的补充报告也拦掉
    recent_supplement = email_db.get_recent_successful_report(report_type="supplement", within_hours=1)
    if recent_supplement:
        runtime_print("   ⏭️ 1小时内已发送过 supplement，跳过本次补充分析")
        return

    runtime_print("="*50)
    runtime_print("📈 检测到开盘期间新邮件，触发补充分析！")
    runtime_print("="*50)
    runtime_print(f"   📧 待处理邮件数: {len(pending_emails)}")

    async with analysis_lock:
        try:
            exit_code = await _run_qclaw_and_stream_logs(["--analyze", "--supplement"], label="supplement")
            if exit_code != 0:
                runtime_print(f"❌ 补充分析退出码异常: {exit_code}")
        except asyncio.TimeoutError:
            runtime_print("❌ 补充分析超时")
        except Exception as e:
            runtime_print(f"❌ 补充分析失败: {e}")


async def trigger_daily_analysis(reason: str):
    """触发 daily 分析。"""
    analysis_lock = get_analysis_task_lock()
    if analysis_lock.locked():
        runtime_print(f"   ⏭️ 当前已有分析任务运行中，跳过 daily ({reason})")
        return

    pending = email_db.get_pending_emails(limit=1)
    if not pending:
        runtime_print("   📭 没有待处理邮件，跳过 daily 分析")
        return

    runtime_print("=" * 50)
    runtime_print(f"📨 触发 daily 分析 ({reason})")
    runtime_print("=" * 50)

    async with analysis_lock:
        if has_daily_report_sent_today():
            runtime_print(f"   ⏭️ 今日已发送 daily 报告，跳过 ({reason})")
            return
        pending = email_db.get_pending_emails(limit=1)
        if not pending:
            runtime_print("   📭 没有待处理邮件，跳过 daily 分析")
            return
        try:
            exit_code = await _run_qclaw_and_stream_logs(["--analyze"], label=f"daily/{reason}")
            if exit_code != 0:
                runtime_print(f"❌ daily 分析退出码异常: {exit_code}")
        except asyncio.TimeoutError:
            runtime_print("❌ daily 分析超时")
        except Exception as e:
            runtime_print(f"❌ daily 分析失败: {e}")


async def scheduled_analysis_loop():
    """定时分析循环：每天美股开盘前15分钟触发分析"""
    next_trigger = get_next_market_trigger_time()
    runtime_print(f"⏰ 定时分析已启用")
    runtime_print(f"   📈 收件截止时间: 美股开盘前15分钟（北京时间 {next_trigger.strftime('%Y-%m-%d %H:%M')}）")

    while True:
        now = datetime.now(BJT)
        next_trigger = get_next_market_trigger_time(now)

        # 等待直到触发时间
        wait_seconds = (next_trigger - now).total_seconds()
        runtime_print(f"   ⏳ 分析启动时间: {next_trigger.strftime('%Y-%m-%d %H:%M')} ({(wait_seconds/3600):.1f}小时后)")
        await asyncio.sleep(wait_seconds)

        # 检查今天是否已发送过报告
        if has_daily_report_sent_today():
            runtime_print(f"   ⏭️ 今日已发送 daily 报告，跳过")
            continue

        # 检查是否有待处理邮件
        pending = email_db.get_pending_emails(limit=1)
        if not pending:
            runtime_print(f"   ⏭️ 没有待处理邮件，跳过")
            continue

        await trigger_daily_analysis(reason="ddl_reached")


async def _stream_subprocess_pipe(pipe, prefix: str):
    """实时转发子进程 stdout/stderr，方便录屏时看到完整链路。"""
    if pipe is None:
        return

    while True:
        line = await pipe.readline()
        if not line:
            break
        text = line.decode("utf-8", errors="replace").rstrip()
        if text:
            runtime_print(f"{prefix}{text}")


async def _run_qclaw_and_stream_logs(args: list[str], label: str, timeout: int = 900) -> int:
    """启动 qclaw_mail_file 并实时打印完整日志，而不是在结束后一次性输出。"""
    script_path = os.path.join(os.path.dirname(__file__), "qclaw_mail_file.py")
    cmd = ["python3", "-u", script_path, *args]
    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"

    runtime_print(f"   ▶️ 启动分析子进程 ({label}): {' '.join(cmd)}")
    process = await asyncio.create_subprocess_exec(
        *cmd,
        cwd=os.path.dirname(__file__),
        stdout=PIPE,
        stderr=PIPE,
        env=env,
    )

    stdout_task = asyncio.create_task(_stream_subprocess_pipe(process.stdout, "   │ "))
    stderr_task = asyncio.create_task(_stream_subprocess_pipe(process.stderr, "   ! "))

    try:
        await asyncio.wait_for(process.wait(), timeout=timeout)
    except asyncio.TimeoutError:
        process.kill()
        await process.wait()
        raise
    finally:
        await asyncio.gather(stdout_task, stderr_task, return_exceptions=True)

    runtime_print(f"   ✅ 分析子进程结束 ({label})，退出码: {process.returncode}")
    return process.returncode


# ============ 启动 ============

if __name__ == "__main__":
    import uvicorn
    server_cfg = config.get("server", {})
    host = server_cfg.get("host", "127.0.0.1")
    port = server_cfg.get("port", 8877)
    runtime_print(f"🚀 邮件服务 API 启动中...")
    runtime_print(f"   地址: http://{host}:{port}")
    runtime_print(f"   健康检查: http://{host}:{port}/health")

    uvicorn.run(
        app,
        host=host,
        port=port
    )
