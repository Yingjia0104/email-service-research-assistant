"""
邮件服务 API
功能：
- IMAP 收取邮件
- SMTP 发送邮件

使用：
    pip install -r requirements.txt
    python main.py
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager

# 配置日志
logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from typing import Optional
import pytz
from zoneinfo import ZoneInfo
from app import config as app_config
from app.api import server as app_api_server
from app.mail import service as app_mail_service
from app.mail import runtime_helpers as app_mail_runtime
from app.pipeline import briefing_policy as app_briefing_policy
from app.pipeline import scheduler as app_scheduler
from app.pipeline import scheduler_utils as app_scheduler_utils
from app.runtime import analysis_lock as app_analysis_lock
from app.runtime import logging_utils as app_logging_utils
from app.runtime import service_runtime as app_service_runtime
from app.runtime import service_bootstrap as app_service_bootstrap
from app.storage import email_db

app_service_bootstrap.prepare_service_environment()

# 加载配置
CONFIG_FILE = os.getenv("EMAIL_SERVICE_CONFIG", os.path.join(os.path.dirname(__file__), "config.yaml"))

def load_config():
    return app_config.load_config(CONFIG_FILE, logger)

def verify_api_key(api_key: str) -> bool:
    """验证API密钥"""
    return app_config.verify_api_key(api_key, load_config_fn=load_config)

config = load_config()


background_tasks = []
IMAGE_EXTENSIONS = app_mail_runtime.IMAGE_EXTENSIONS
MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS = app_mail_runtime.MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS
ANALYSIS_LOCK_FILE = os.path.join(os.path.dirname(__file__), ".analysis.lock")
ATTACHMENT_SIGNATURE_MARKERS = app_mail_runtime.ATTACHMENT_SIGNATURE_MARKERS
ATTACHMENT_DISCLAIMER_MARKERS = app_mail_runtime.ATTACHMENT_DISCLAIMER_MARKERS
get_message_local_date = app_mail_runtime.get_message_local_date
get_message_local_datetime = app_mail_runtime.get_message_local_datetime
extract_sender_email = app_mail_runtime.extract_sender_email
match_allowed_sender = app_mail_runtime.match_allowed_sender
get_expected_senders = app_mail_runtime.get_expected_senders
classify_smtp_exception = app_api_server.classify_smtp_exception
runtime_timestamp = app_logging_utils.runtime_timestamp
runtime_print = app_logging_utils.runtime_print

def try_acquire_analysis_lock():
    return app_analysis_lock.try_acquire_analysis_lock(ANALYSIS_LOCK_FILE)


def release_analysis_lock(lock_handle) -> None:
    app_analysis_lock.release_analysis_lock(lock_handle)


def _extract_attachment_bytes(att):
    """统一提取附件二进制。"""
    return app_mail_runtime.extract_attachment_bytes(att)


def _clean_extracted_attachment_text(text, filename=""):
    """清洗 .msg/.eml/.pdf 等附件提取文本，避免原始转发噪音压垮分析上下文。"""
    return app_mail_runtime.clean_extracted_attachment_text(text, filename=filename)


def _build_attachment_records(msg):
    """提取附件记录；图片默认保留 data URL 供多模态模型直接使用。"""
    return app_mail_runtime.build_attachment_records(msg, logger=logger)


def parse_received_after_local(filters: dict, local_tz):
    """解析可选的本地时间阈值，用于联调时忽略历史邮件。"""
    return app_mail_runtime.parse_received_after_local(filters, local_tz, logger=logger)


def should_accept_sender(from_addr: str, allowed_senders: list) -> bool:
    """统一发件人过滤逻辑。"""
    return app_mail_runtime.should_accept_sender(from_addr, allowed_senders)


def get_received_sender_matches_for_today(allowed_senders: list, reference_time: Optional[datetime] = None) -> set:
    """返回当天自然日内已收到并命中的白名单 sales 集合。"""
    return app_briefing_policy.get_received_sender_matches_for_today(
        allowed_senders,
        reference_time,
        ensure_bjt_fn=_ensure_bjt,
        get_sender_addresses_for_created_date_fn=email_db.get_sender_addresses_for_created_date,
        extract_sender_email_fn=extract_sender_email,
        match_allowed_sender_fn=match_allowed_sender,
    )


def get_briefing_session_start(reference_time: Optional[datetime] = None) -> datetime:
    """定义一轮盘前 briefing 的起点：最近一个美股交易日收盘（16:00 ET）后的北京时间。"""
    return app_briefing_policy.get_briefing_session_start(
        reference_time,
        ensure_bjt_fn=_ensure_bjt,
        bjt=BJT,
        us_et=US_ET,
    )


def get_received_sender_matches_for_session(allowed_senders: list, reference_time: Optional[datetime] = None) -> set:
    """返回当前 briefing session 内已收到并命中的白名单 sales 集合。"""
    return app_briefing_policy.get_received_sender_matches_for_session(
        allowed_senders,
        reference_time,
        get_briefing_session_start_fn=get_briefing_session_start,
        get_sender_addresses_created_since_fn=email_db.get_sender_addresses_created_since,
        extract_sender_email_fn=extract_sender_email,
        match_allowed_sender_fn=match_allowed_sender,
    )


def all_expected_senders_arrived_for_session(allowed_senders: list, reference_time: Optional[datetime] = None) -> bool:
    """判断当前 briefing session 内是否已经收齐全部白名单 sales 邮件。"""
    return app_briefing_policy.all_expected_senders_arrived_for_session(
        allowed_senders,
        reference_time,
        get_received_sender_matches_for_session_fn=get_received_sender_matches_for_session,
    )


def should_trigger_early_daily(allowed_senders: list, bg_cfg: dict, reference_time: Optional[datetime] = None) -> tuple[bool, str]:
    """盘前提前触发规则：白名单全到齐 + session 内邮件够多 + 最近 N 分钟无新邮件。"""
    return app_briefing_policy.should_trigger_early_daily(
        allowed_senders,
        bg_cfg,
        reference_time,
        ensure_bjt_fn=_ensure_bjt,
        get_briefing_session_start_fn=get_briefing_session_start,
        get_received_sender_matches_for_session_fn=get_received_sender_matches_for_session,
        count_emails_created_since_fn=email_db.count_emails_created_since,
        has_new_email_within_minutes_fn=email_db.has_new_email_within_minutes,
    )


def all_expected_senders_arrived(allowed_senders: list, reference_time: Optional[datetime] = None) -> bool:
    """按当前 briefing session 口径判断是否已收齐白名单 sales。"""
    return app_briefing_policy.all_expected_senders_arrived(
        allowed_senders,
        reference_time,
        all_expected_senders_arrived_for_session_fn=all_expected_senders_arrived_for_session,
    )


def has_daily_report_sent_today(reference_time: Optional[datetime] = None) -> bool:
    """判断今天是否已经成功发送过 daily 报告。"""
    return app_briefing_policy.has_daily_report_sent_today(
        reference_time,
        ensure_bjt_fn=_ensure_bjt,
        has_successful_report_on_date_fn=email_db.has_successful_report_on_date,
    )


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
    return app_api_server.get_emails(
        api_key=api_key,
        email=email,
        password=password,
        folder=folder,
        limit=limit,
        source=source,
        verify_api_key_fn=verify_api_key,
        load_config_fn=load_config,
        parse_received_after_local_fn=parse_received_after_local,
        should_accept_sender_fn=should_accept_sender,
        get_message_local_datetime_fn=get_message_local_datetime,
        build_attachment_records_fn=_build_attachment_records,
        logger=logger,
        http_exception_cls=HTTPException,
    )


@app.get("/api/emails/{email_id}")
def get_email_by_id(
    email_id: int,
    api_key: str = None,
    email: str = None,
    password: str = None,
    source: str = "imap.gmail.com"
):
    return app_api_server.get_email_by_id(
        email_id=email_id,
        api_key=api_key,
        email=email,
        password=password,
        source=source,
        verify_api_key_fn=verify_api_key,
        load_config_fn=load_config,
        http_exception_cls=HTTPException,
    )

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
    return app_api_server.send_email_sync(
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
        mime_multipart_cls=MIMEMultipart,
        mime_text_cls=MIMEText,
    )


async def send_email_smtp(smtp_host, smtp_port, from_email, password, to_email, subject, body, body_type, use_ssl=False, timeout_seconds=30):
    """SMTP发送邮件的核心逻辑（异步包装）"""
    return await app_api_server.send_email_smtp(
        smtp_host,
        smtp_port,
        from_email,
        password,
        to_email,
        subject,
        body,
        body_type,
        use_ssl=use_ssl,
        timeout_seconds=timeout_seconds,
        send_email_sync_fn=_send_email_sync,
        classify_smtp_exception_fn=classify_smtp_exception,
        http_exception_cls=HTTPException,
    )


# ============ 状态检查 ============

@app.get("/")
async def root():
    return app_api_server.root_payload()

@app.get("/health")
async def health():
    return app_api_server.health_payload()


# ============ 后台定时收取邮件 ============

BJT = pytz.timezone('Asia/Shanghai')
US_ET = ZoneInfo("America/New_York")


def _fetch_emails_and_persist(limit: int):
    """后台收件统一走 mail service，scheduler 只负责编排时机。"""
    return app_service_runtime.fetch_emails_and_persist(
        limit,
        load_config_fn=load_config,
        parse_received_after_local_fn=parse_received_after_local,
        should_accept_sender_fn=should_accept_sender,
        get_message_local_datetime_fn=get_message_local_datetime,
        build_attachment_records_fn=_build_attachment_records,
        email_db_module=email_db,
        logger=logger,
    )


async def fetch_and_save_emails():
    """后台任务：收取邮件并保存到数据库"""
    await app_service_runtime.fetch_and_save_emails(
        load_config_fn=load_config,
        email_db_module=email_db,
        runtime_print_fn=runtime_print,
        has_daily_report_sent_today_fn=has_daily_report_sent_today,
        should_trigger_early_daily_fn=should_trigger_early_daily,
        trigger_daily_analysis_fn=trigger_daily_analysis,
        is_in_supplement_window_fn=is_in_supplement_window,
        trigger_supplement_analysis_fn=trigger_supplement_analysis,
        fetch_emails_and_persist_fn=_fetch_emails_and_persist,
    )


async def background_fetch_loop():
    """后台循环：定期收取邮件"""
    await app_service_runtime.background_fetch_loop(
        load_config_fn=load_config,
        fetch_and_save_emails_fn=fetch_and_save_emails,
        runtime_print_fn=runtime_print,
    )


def _ensure_bjt(dt_value: Optional[datetime] = None) -> datetime:
    """将时间标准化到北京时间 aware datetime。"""
    return app_scheduler_utils.ensure_bjt(dt_value, bjt=BJT)


def get_next_market_trigger_time(reference_time: Optional[datetime] = None) -> datetime:
    """获取下一个美股开盘前 15 分钟触发点（北京时间，自动跳过周末）。"""
    return app_scheduler_utils.get_next_market_trigger_time(reference_time, bjt=BJT, us_et=US_ET)


def get_us_market_open_time(reference_time: Optional[datetime] = None):
    """返回下一个美股开盘前 15 分钟触发点的北京时间小时和分钟。"""
    return app_scheduler_utils.get_us_market_open_time(reference_time, bjt=BJT, us_et=US_ET)


def is_in_supplement_window(reference_time: Optional[datetime] = None):
    """检查当前是否在补充分析时间窗口内（开盘前15分钟到开盘后1小时）"""
    return app_scheduler_utils.is_in_supplement_window(reference_time, bjt=BJT, us_et=US_ET)


async def trigger_supplement_analysis(new_emails_count: int):
    """触发补充分析（针对延迟邮件）"""
    await app_service_runtime.trigger_supplement_analysis(
        new_emails_count,
        has_daily_report_sent_today_fn=has_daily_report_sent_today,
        try_acquire_analysis_lock_fn=try_acquire_analysis_lock,
        release_analysis_lock_fn=release_analysis_lock,
        email_db_module=email_db,
        runtime_print_fn=runtime_print,
        run_analysis_job_fn=_run_analysis_job_in_process,
    )


async def trigger_daily_analysis(reason: str):
    """触发 daily 分析。"""
    await app_service_runtime.trigger_daily_analysis(
        reason,
        try_acquire_analysis_lock_fn=try_acquire_analysis_lock,
        release_analysis_lock_fn=release_analysis_lock,
        email_db_module=email_db,
        runtime_print_fn=runtime_print,
        has_daily_report_sent_today_fn=has_daily_report_sent_today,
        run_analysis_job_fn=_run_analysis_job_in_process,
    )


async def scheduled_analysis_loop():
    """定时分析循环：每天美股开盘前15分钟触发分析"""
    await app_service_runtime.scheduled_analysis_loop(
        get_next_market_trigger_time_fn=get_next_market_trigger_time,
        bjt=BJT,
        runtime_print_fn=runtime_print,
        has_daily_report_sent_today_fn=has_daily_report_sent_today,
        email_db_module=email_db,
        trigger_daily_analysis_fn=trigger_daily_analysis,
    )


async def _run_analysis_job_in_process(*, supplement_mode: bool, label: str, timeout: int = 900) -> int:
    """直接在当前进程里执行分析入口，不再通过子进程拉起 qclaw CLI。"""
    return await app_service_runtime.run_analysis_job_in_process(
        supplement_mode=supplement_mode,
        label=label,
        runtime_print_fn=runtime_print,
        timeout=timeout,
    )


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
