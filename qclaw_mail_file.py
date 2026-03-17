#!/usr/bin/env python3
"""
QClaw 邮件自动处理 - 文件交互版

流程：
1. 通过 API / IMAP 收取邮件 → 落 SQLite
2. 从 SQLite 读取 pending 邮件并调用大模型分析
3. 生成 AI_Morning_Brief_YYYYMMDD.html
4. 发送报告并更新 SQLite 状态

用法:
    python qclaw_mail_file.py           # 正常模式
    python qclaw_mail_file.py --force   # 强制立即执行
    python qclaw_mail_file.py --check   # 检查状态
    python qclaw_mail_file.py --analyze # 仅分析 SQLite 中已存在的 pending 邮件
"""

import os
import sys
import yaml
import json
import time
import glob
import pytz
import re
import logging
import requests
import traceback
import fcntl
from html import escape, unescape
from datetime import datetime
from typing import Any, List, Dict, Optional
from functools import wraps
from io import BytesIO

# ============ 配置 ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")
STATE_FILE = os.path.join(BASE_DIR, ".qclaw_state.json")
REPORT_PREFIX = "report_"
LOG_FILE = os.path.join(BASE_DIR, "qclaw.log")
PENDING_FILE = os.path.join(BASE_DIR, "pending_emails.json")  # 兼容旧的文件交互流程
ANALYSIS_LOCK_FILE = os.path.join(BASE_DIR, ".analysis.lock")

# 导入数据库模块
import sys
sys.path.insert(0, BASE_DIR)
import email_db

# 时区
BJT = pytz.timezone('Asia/Shanghai')

# 邮件服务API
EMAIL_API = "http://127.0.0.1:8877"

# Kimi (Moonshot AI) API 配置
KIMI_CONFIG = {
    "api_key": "",
    "base_url": "https://api.moonshot.cn/v1",
    "model": "kimi-k2.5",
    "supports_vision": True,
}

# 备用 API 配置（当前API余额不足时使用）
KIMI_BACKUP_CONFIG = {
    "api_key": "",
    "base_url": "https://api.moonshot.cn/v1",
    "model": "kimi-k2.5",
    "supports_vision": True,
}

MAX_EMAIL_BODY_CHARS = 12000
MAX_PROMPT_BODY_CHARS = 40000
MAX_COMPLETION_TOKENS = 12000
BATCH_SPLIT_TRIGGER_CHARS = 26000
MIN_TRUNCATION_CONTENT_CHARS = 40
MAX_MULTIMODAL_IMAGES = 6
MAX_MULTIMODAL_IMAGE_BYTES = 4 * 1024 * 1024

SIGNATURE_LINE_MARKERS = (
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

DISCLAIMER_LINE_MARKERS = (
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

STANDALONE_SUBHEADINGS = {
    "核心事实",
    "市场怎么看",
    "供应链与竞争方观点",
    "投资影响",
    "投资启示",
    "长期（1-3月）",
}

SECTION_SUBHEADINGS = {
    "Catalysts to Watch",
}

TIME_HORIZON_SUBHEADINGS = {
    "短期（1-5天）",
    "中期（1-4周）",
}

SEMANTIC_CALLOUT_RULES = {
    "投资启示": "action-box",
    "投资影响": "action-box",
    "Action": "action-box",
    "为什么重要": "signal-box",
    "信号": "signal-box",
    "原则": "principle-box",
    "规则": "rule-box",
    "底线": "redline-box",
    "提醒": "reminder-box",
}

FIXED_DETAIL_LABELS = {"投资启示", "信号", "为什么重要", "Action"}

# 报告格式治理说明
# 原则：结构语义优先于模型原始标签；同一语义必须收敛到同一视觉组件。
# 规则：标题层级、提示框、时间催化标题全部走确定性映射，不依赖模型“刚好写对”。
# 底线：不得让同一个标签在不同报告里一会儿是普通段落、一会儿是底色框。
# 提醒：prompt 只能尽量约束；最终稳定性必须由本地格式化规则兜底。

SOURCE_LABEL_PATTERNS = [
    ("MS", [r"\bmorgan stanley\b", r"\bms\b", r"摩根士丹利"]),
    ("JPM", [r"\bj\.?\s?p\.?\s?morgan\b", r"\bjpm\b", r"摩根大通"]),
    ("GS", [r"\bgoldman sachs\b", r"\bgs\b", r"高盛"]),
    ("BofA", [r"\bbank of america\b", r"\bbofa\b", r"美银"]),
    ("UBS", [r"\bubs\b", r"瑞银"]),
    ("Citi", [r"\bciti\b", r"\bcitigroup\b", r"花旗"]),
    ("Barclays", [r"\bbarclays\b", r"巴克莱"]),
    ("Bernstein", [r"\bbernstein\b"]),
]

REPORT_OPTIMIZATION_CATEGORIES = {
    "内容筛选": [
        "普通功能升级、版本小更新、一般性运营通知默认降权，不挤占核心版面",
        "核心事实只保留最硬的信息，避免长句和解释性废话",
        "图片内容要与文本一起理解，但不单独占用杂乱版面",
    ],
    "归因纪律": [
        "发件机构不等于观点主体，外部引述必须保留真实主语",
        "带 says / according to / reports suggest / rumored 的内容默认不是核心事实",
        "来源展示优先使用正文和主题里可识别的真实机构标签，如 MS、JPM",
    ],
    "结构模板": [
        "Executive Summary 固定拆为 市场大背景 和 关键信号",
        "核心事件与市场观点 固定按 事件标题 / 核心事实 / 市场怎么看 / 投资启示 展开",
        "Actionable Ideas 固定包含 短期(1-5天) / 中期(1-4周) / Catalysts to Watch / Bottom Line",
        "Actionable Ideas 需要站在全局上二次提炼最有行动价值的交易想法，而不是承接剩余信息",
    ],
    "格式底线": [
        "阅读时间和来源 metadata 固定显示在标题下方，且只出现一次",
        "highlight 不进入标题，只能留在正文",
        "相同语义标签必须映射到相同结构，不允许同一模块今天是表格、明天是散段落",
    ],
}

FIXED_REPORT_TEMPLATE = {
    "executive_summary": ["市场大背景", "关键信号"],
    "core_events_h2": "Key Coverage | 核心事件与市场观点",
    "core_event_labels": ["核心事实", "市场怎么看", "投资启示"],
    "local_news_h2": "Local News | 容易被忽略的信号",
    "local_news_labels": ["信号", "为什么重要", "Action"],
    "peripheral_h2": "Peripheral Intelligence | 外围信息/类比映射",
    "peripheral_subsections": ["非核心公司事件 → 核心洞察", "跨市场信号"],
    "actionable_h2": "Actionable Ideas",
    "actionable_labels": ["短期(1-5天)", "中期(1-4周)", "Catalysts to Watch", "Bottom Line"],
}

# ============ 日志系统 ============
def setup_logging():
    """设置日志系统"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=[
            logging.FileHandler(LOG_FILE, encoding='utf-8'),
            logging.StreamHandler(sys.stdout)
        ]
    )
    return logging.getLogger(__name__)

logger = setup_logging()

# ============ 代理设置 ============
# 移除系统代理环境变量（本地服务不需要代理）
for key in ['http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY', 'ALL_PROXY']:
    os.environ.pop(key, None)

# 设置 NO_PROXY 绕过本地地址
os.environ['NO_PROXY'] = '127.0.0.1,localhost,0.0.0.0'

session = requests.Session()
session.trust_env = False

# 明确配置适配器，禁用代理
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# 为HTTP和HTTPS配置不使用代理的adapter
adapter = HTTPAdapter(
    max_retries=3,
    pool_connections=10,
    pool_maxsize=10,
)
session.mount('http://', adapter)
session.mount('https://', adapter)


# ============ 重试装饰器 ============
def retry_on_error(max_retries: int = 3, delay: float = 2.0, backoff: float = 2.0):
    """
    重试装饰器

    参数:
        max_retries: 最大重试次数
        delay: 初始延迟（秒）
        backoff: 退避系数
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            current_delay = delay
            last_exception = None

            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries:
                        logger.warning(f"第 {attempt + 1} 次尝试失败: {e}, {current_delay:.1f}秒后重试...")
                        time.sleep(current_delay)
                        current_delay *= backoff
                    else:
                        logger.error(f"已达到最大重试次数 ({max_retries + 1}), 最终错误: {e}")

            raise last_exception
        return wrapper
    return decorator


# ============ 配置加载 ============
def load_config():
    """加载配置文件"""
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def load_kimi_config():
    """加载 Kimi API 配置"""
    config = load_config()
    kimi_cfg = config.get("kimi", {})

    KIMI_CONFIG["api_key"] = kimi_cfg.get("api_key", "")
    KIMI_CONFIG["base_url"] = kimi_cfg.get("base_url", "https://api.moonshot.cn/v1")
    KIMI_CONFIG["model"] = kimi_cfg.get("model", "kimi-k2.5")
    if "supports_vision" in kimi_cfg:
        KIMI_CONFIG["supports_vision"] = bool(kimi_cfg.get("supports_vision"))
    else:
        KIMI_CONFIG["supports_vision"] = any(
            token in KIMI_CONFIG["model"].lower() for token in ("thinking-preview", "vision", "vl")
        )

    # 加载备用 API 配置
    backup_cfg = config.get("kimi_backup", {})
    KIMI_BACKUP_CONFIG["api_key"] = backup_cfg.get("api_key", "")
    KIMI_BACKUP_CONFIG["base_url"] = backup_cfg.get("base_url", "https://api.moonshot.cn/v1")
    KIMI_BACKUP_CONFIG["model"] = backup_cfg.get("model", "kimi-k2.5")
    if "supports_vision" in backup_cfg:
        KIMI_BACKUP_CONFIG["supports_vision"] = bool(backup_cfg.get("supports_vision"))
    else:
        KIMI_BACKUP_CONFIG["supports_vision"] = any(
            token in KIMI_BACKUP_CONFIG["model"].lower() for token in ("thinking-preview", "vision", "vl")
        )

    return KIMI_CONFIG


def load_format_spec():
    """加载 HF Morning Brief 格式规范"""
    format_spec_file = os.path.join(BASE_DIR, "HF_Morning_Brief_格式规范.md")
    if os.path.exists(format_spec_file):
        with open(format_spec_file, 'r', encoding='utf-8') as f:
            return f.read()
    return ""


def build_format_spec_guidance(format_spec: str, max_chars: int = 2200) -> str:
    """把格式规范压缩成适合 prompt 的参考块。"""
    raw = (format_spec or "").strip()
    if not raw:
        return ""
    compact = re.sub(r"\n{3,}", "\n\n", raw)
    compact = compact.strip()
    if len(compact) > max_chars:
        compact = compact[:max_chars].rstrip() + "\n..."
    return compact


def try_acquire_analysis_lock():
    """获取分析流程互斥锁，避免并发重复发送。"""
    lock_handle = open(ANALYSIS_LOCK_FILE, "w", encoding="utf-8")
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        lock_handle.close()
        return None

    lock_handle.seek(0)
    lock_handle.truncate()
    lock_handle.write(str(os.getpid()))
    lock_handle.flush()
    return lock_handle


def release_analysis_lock(lock_handle) -> None:
    if not lock_handle:
        return
    try:
        fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
    except Exception:
        pass
    try:
        lock_handle.close()
    except Exception:
        pass


def model_supports_vision(api_config: Dict[str, Any]) -> bool:
    """判断当前模型是否支持多模态图片输入。"""
    if "supports_vision" in (api_config or {}):
        return bool(api_config.get("supports_vision"))

    model_name = str((api_config or {}).get("model", "")).lower()
    return any(token in model_name for token in ("thinking-preview", "vision", "vl"))


def parse_attachment_list(raw_attachments: Any) -> List[Dict]:
    """兼容 attachments 字段的 JSON 字符串或列表结构。"""
    if not raw_attachments:
        return []
    if isinstance(raw_attachments, list):
        return [item for item in raw_attachments if isinstance(item, dict)]
    if isinstance(raw_attachments, str):
        try:
            parsed = json.loads(raw_attachments)
        except Exception:
            return []
        if isinstance(parsed, list):
            return [item for item in parsed if isinstance(item, dict)]
    return []


def estimate_data_url_image_bytes(data_url: str) -> int:
    """粗略估算 data URL 图片体积，用于过滤过大的正文内嵌图片。"""
    if not data_url or "," not in data_url:
        return 0
    encoded = data_url.split(",", 1)[1]
    compact = re.sub(r"\s+", "", encoded)
    padding = compact.count("=")
    return max(0, (len(compact) * 3) // 4 - padding)


def extract_inline_body_image_data_urls(body: str) -> List[str]:
    """从 HTML 正文里提取 data:image 内嵌图片。"""
    if not body:
        return []

    matches = re.findall(
        r"data:image/[^;'\"]+;base64,[A-Za-z0-9+/=\s]+",
        body,
        flags=re.IGNORECASE,
    )

    data_urls = []
    seen = set()
    for match in matches:
        compact = re.sub(r"\s+", "", match)
        if compact in seen:
            continue
        seen.add(compact)
        data_urls.append(compact)
    return data_urls


def build_multimodal_user_blocks(emails: List[Dict], api_config: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """从邮件附件里提取可直接送入模型的图片块。"""
    if not model_supports_vision(api_config or {}):
        return []

    blocks: List[Dict[str, Any]] = []
    image_count = 0
    seen_urls = set()

    for fallback_index, email in enumerate(emails, 1):
        email_index = email.get("_analysis_index", fallback_index)
        subject = email.get("subject", "") or "(无主题)"
        attachments = parse_attachment_list(email.get("attachments"))

        for attachment in attachments:
            if image_count >= MAX_MULTIMODAL_IMAGES:
                return blocks

            if attachment.get("kind") != "image":
                continue

            content_type = attachment.get("content_type", "") or "image/*"
            data_url = attachment.get("data_url")
            size = int(attachment.get("size") or 0)
            if not content_type.startswith("image/") or not data_url:
                continue
            if size and size > MAX_MULTIMODAL_IMAGE_BYTES:
                continue
            compact_url = re.sub(r"\s+", "", data_url)
            if compact_url in seen_urls:
                continue

            filename = attachment.get("filename", "image")
            blocks.append({
                "type": "text",
                "text": (
                    f"下面是一张来自邮件 {email_index}《{subject}》的图片附件：{filename}。"
                    "请结合对应邮件正文一起理解，不要脱离邮件上下文单独脑补。"
                ),
            })
            blocks.append({
                "type": "image_url",
                "image_url": {"url": compact_url},
            })
            image_count += 1
            seen_urls.add(compact_url)

        for inline_index, data_url in enumerate(extract_inline_body_image_data_urls(email.get("body", "")), 1):
            if image_count >= MAX_MULTIMODAL_IMAGES:
                return blocks

            compact_url = re.sub(r"\s+", "", data_url)
            if compact_url in seen_urls:
                continue

            estimated_size = estimate_data_url_image_bytes(compact_url)
            if estimated_size and estimated_size > MAX_MULTIMODAL_IMAGE_BYTES:
                continue

            blocks.append({
                "type": "text",
                "text": (
                    f"下面是一张直接内嵌在邮件 {email_index}《{subject}》正文中的图片（内嵌图 {inline_index}）。"
                    "请结合该邮件的上下文理解图片内容。"
                ),
            })
            blocks.append({
                "type": "image_url",
                "image_url": {"url": compact_url},
            })
            image_count += 1
            seen_urls.add(compact_url)

    return blocks


def normalize_marker_text(text: str) -> str:
    return " ".join((text or "").strip().lower().split())


def strip_signature_and_disclaimer(body: str) -> str:
    """裁掉邮件尾部的署名、免责声明和设备签名，给模型释放上下文。"""
    if not body:
        return ""

    text = body.replace("\r\n", "\n").replace("\r", "\n")
    lines = text.split("\n")
    cut_index = None
    meaningful_chars = 0
    non_empty_lines = 0

    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue

        normalized = normalize_marker_text(stripped)
        has_enough_content = meaningful_chars >= MIN_TRUNCATION_CONTENT_CHARS or non_empty_lines >= 3

        if has_enough_content:
            if any(normalized.startswith(marker) for marker in SIGNATURE_LINE_MARKERS) and len(stripped) <= 120:
                cut_index = idx
                break
            if any(marker in normalized for marker in DISCLAIMER_LINE_MARKERS):
                cut_index = idx
                break

        meaningful_chars += len(stripped)
        non_empty_lines += 1

    if cut_index is not None:
        return "\n".join(lines[:cut_index]).strip()
    return text.strip()


def sanitize_email_body(body: str) -> str:
    """清理超大/无效的嵌入内容，避免 prompt 被 base64、HTML 和免责声明撑爆。"""
    if not body:
        return ""

    sanitized = body.replace("\r\n", "\n").replace("\r", "\n")
    sanitized = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", sanitized)
    sanitized = re.sub(r"(?i)<br\s*/?>", "\n", sanitized)
    sanitized = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", sanitized)
    sanitized = re.sub(r"(?is)<li[^>]*>", "• ", sanitized)
    sanitized = re.sub(
        r"<img[^>]+src=['\"]data:image/[^'\"]+['\"][^>]*>",
        "[内嵌图片已省略：如为附件图片，将通过多模态链路单独送入模型]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"(?is)<img[^>]*>", "[图片引用已省略]", sanitized)
    sanitized = re.sub(
        r"data:image/[^;]+;base64,[A-Za-z0-9+/=\s]+",
        "[图片数据已省略]",
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"[A-Za-z0-9+/=]{500,}", "[长编码内容已省略]", sanitized)
    sanitized = re.sub(r"(?is)<[^>]+>", " ", sanitized)
    sanitized = unescape(sanitized)
    sanitized = strip_signature_and_disclaimer(sanitized)
    sanitized = re.sub(r"[ \t]+\n", "\n", sanitized)
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)
    return sanitized.strip()


def prepare_emails_for_analysis(emails: List[Dict]) -> List[Dict]:
    prepared = []
    for idx, email in enumerate(emails, 1):
        item = dict(email)
        body = sanitize_email_body(email.get("body", ""))
        item["_analysis_index"] = idx
        item["_analysis_body"] = body
        item["_analysis_body_len"] = len(body)
        prepared.append(item)
    return prepared


def split_emails_for_analysis(emails: List[Dict]) -> List[List[Dict]]:
    """当上下文仍然偏长时，拆成两个批次分析，降低单次模型压力。"""
    prepared = prepare_emails_for_analysis(emails)
    total_chars = sum(min(email["_analysis_body_len"], MAX_EMAIL_BODY_CHARS) for email in prepared)

    if len(prepared) <= 1 or total_chars <= BATCH_SPLIT_TRIGGER_CHARS:
        return [prepared]

    buckets = [[], []]
    bucket_sizes = [0, 0]

    for email in sorted(prepared, key=lambda item: item["_analysis_body_len"], reverse=True):
        target_idx = 0 if bucket_sizes[0] <= bucket_sizes[1] else 1
        buckets[target_idx].append(email)
        bucket_sizes[target_idx] += min(email["_analysis_body_len"], MAX_EMAIL_BODY_CHARS)

    result = []
    for bucket in buckets:
        if bucket:
            result.append(sorted(bucket, key=lambda item: item["_analysis_index"]))
    return result


def build_emails_text(emails: List[Dict], total_email_count: int, total_body_budget: int) -> str:
    emails_summary = []
    total_body_chars = 0

    for fallback_index, email in enumerate(emails, 1):
        subject = email.get("subject", "")
        from_name = email.get("from_name", "")
        from_addr = email.get("from", "")
        date = email.get("date", "")
        body = email.get("_analysis_body", sanitize_email_body(email.get("body", "")))
        original_len = len(body)
        email_index = email.get("_analysis_index", fallback_index)

        remaining = max(total_body_budget - total_body_chars, 0)
        if remaining <= 0:
            body = "【内容已省略：本轮邮件总长度超出模型输入预算】"
        else:
            body_budget = min(MAX_EMAIL_BODY_CHARS, remaining)
            if len(body) > body_budget:
                body = (
                    body[:body_budget]
                    + f"\n\n【内容已截断：原始长度 {original_len} 字符，为控制模型输入长度仅保留前 {body_budget} 字符】"
                )
        total_body_chars += len(body)

        emails_summary.append(f"""
--- 邮件 {email_index}/{total_email_count} ---
发件人: {from_name} <{from_addr}>
时间: {date}
主题: {subject}
正文:
{body}
""")

    return "\n".join(emails_summary)


def generate_with_kimi(system_prompt: str, user_prompt: str, emails: Optional[List[Dict]] = None) -> str:
    """统一封装主/备模型的短重试与切换逻辑。"""
    kimi_cfg = load_kimi_config()
    api_key = kimi_cfg.get("api_key", "")

    if not api_key:
        logger.error("❌ 未配置 Kimi API Key，请在 config.yaml 中配置 kimi.api_key")
        raise Exception("missing kimi api key")

    primary_multimodal_blocks = build_multimodal_user_blocks(emails or [], kimi_cfg)
    if primary_multimodal_blocks:
        logger.info(f"🖼️ 主模型将接收 {len(primary_multimodal_blocks) // 2} 张图片附件进行多模态分析")

    result = call_kimi_api_with_retries(
        kimi_cfg,
        system_prompt,
        user_prompt,
        label="主API",
        max_retries=1,
        delay=5.0,
        backoff=2.0,
        user_content_blocks=primary_multimodal_blocks,
    )

    if result:
        return result

    if primary_multimodal_blocks:
        logger.warning("⚠️ 主模型多模态请求失败，降级为纯文本重试")
        result = call_kimi_api_with_retries(
            kimi_cfg,
            system_prompt,
            user_prompt,
            label="主API-文本降级",
            max_retries=1,
            delay=4.0,
            backoff=2.0,
            user_content_blocks=None,
        )
        if result:
            logger.info("✅ 主模型文本降级成功")
            return result

    backup_cfg = KIMI_BACKUP_CONFIG
    if backup_cfg.get("api_key"):
        logger.warning(f"⚠️ 主 API 不可用，切换备用 API: {backup_cfg['base_url']} (模型: {backup_cfg['model']})")
        backup_multimodal_blocks = build_multimodal_user_blocks(emails or [], backup_cfg)
        if primary_multimodal_blocks and not backup_multimodal_blocks:
            logger.warning("⚠️ 备用模型当前未启用多模态支持，图片附件将仅保留正文元数据提示")
        result = call_kimi_api_with_retries(
            backup_cfg,
            system_prompt,
            user_prompt,
            label="备用API",
            max_retries=1,
            delay=3.0,
            backoff=2.0,
            user_content_blocks=backup_multimodal_blocks,
        )
        if result:
            logger.info("✅ 备用 API 分析完成")
            return result

        if backup_multimodal_blocks:
            logger.warning("⚠️ 备用模型多模态请求失败，降级为纯文本重试")
            result = call_kimi_api_with_retries(
                backup_cfg,
                system_prompt,
                user_prompt,
                label="备用API-文本降级",
                max_retries=1,
                delay=3.0,
                backoff=2.0,
                user_content_blocks=None,
            )
            if result:
                logger.info("✅ 备用模型文本降级成功")
                return result

    logger.error("❌ 主 API 与备用 API 均失败")
    raise Exception("Kimi API error: 主 API 和备用 API 均失败")


def extract_json_block(text: str) -> str:
    """从模型输出中提取 JSON 主体，兼容 ```json 代码块。"""
    if not text:
        raise ValueError("empty json response")

    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, count=1, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned, count=1)
        cleaned = cleaned.strip()

    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("json object not found")
    return cleaned[start:end + 1]


def save_malformed_json_snapshot(raw_text: str, prefix: str = "malformed_report_payload") -> Optional[str]:
    """保存模型返回的损坏 JSON 片段，方便排查。"""
    try:
        timestamp = datetime.now(BJT).strftime("%Y%m%d_%H%M%S")
        path = os.path.join(BASE_DIR, f"{prefix}_{timestamp}.txt")
        with open(path, "w", encoding="utf-8") as f:
            f.write(raw_text or "")
        logger.warning(f"⚠️ 已保存损坏 JSON 快照: {path}")
        return path
    except Exception as exc:
        logger.warning(f"⚠️ 保存损坏 JSON 快照失败: {exc}")
        return None


def load_json_dict_with_fallbacks(raw_text: str) -> Dict[str, Any]:
    """优先严格 JSON，失败时允许用 YAML 宽松解析。"""
    block = extract_json_block(raw_text)
    try:
        payload = json.loads(block)
        if isinstance(payload, dict):
            return payload
    except Exception:
        pass

    try:
        payload = yaml.safe_load(block)
        if isinstance(payload, dict):
            logger.warning("⚠️ JSON 严格解析失败，已用 YAML 宽松解析兜底")
            return payload
    except Exception:
        pass

    raise ValueError("unable to parse json payload")


def repair_report_payload_json(raw_text: str) -> Dict[str, Any]:
    """当模型返回的 JSON 不合法时，尝试做一次短请求修复。"""
    save_malformed_json_snapshot(raw_text)
    repair_system_prompt = """你是一个严格的 JSON 修复器。

任务：
1. 你会收到一段“接近 JSON 但不合法”的文本
2. 在不发明新事实、不改变原意的前提下，把它修复成合法 JSON
3. 只输出一个合法 JSON 对象，不要解释，不要 Markdown
4. 保留原有字段结构，尤其是 executive_summary / core_events / local_news / peripheral_intelligence / actionable_ideas
"""

    repair_user_prompt = f"""请把下面这段不合法的 JSON 修复成合法 JSON，只输出 JSON：

```text
{raw_text}
```"""

    repaired = generate_with_kimi(repair_system_prompt, repair_user_prompt, emails=None)
    payload = load_json_dict_with_fallbacks(repaired)
    logger.info("✅ 模型返回的损坏 JSON 已通过修复流程恢复")
    return payload


def parse_batch_summary_json(text: str) -> Dict:
    """解析子批次结构化摘要，失败时直接抛错让上层重试/切换。"""
    payload = load_json_dict_with_fallbacks(text)
    topics = payload.get("topics")
    if not isinstance(topics, list):
        raise ValueError("topics missing from batch summary")

    normalized_topics = []
    for topic in topics:
        if not isinstance(topic, dict):
            continue
        normalized_topics.append({
            "title": topic.get("title", ""),
            "email_ids": topic.get("email_ids", []),
            "coverage_count": topic.get("coverage_count", 0),
            "fact_subject": topic.get("fact_subject", ""),
            "opinion_subject": topic.get("opinion_subject", ""),
            "info_type": topic.get("info_type", ""),
            "core_facts": topic.get("core_facts", []),
            "market_takeaways": topic.get("market_takeaways", []),
            "tickers": topic.get("tickers", []),
            "source_evidence": topic.get("source_evidence", []),
        })

    payload["topics"] = normalized_topics
    return payload


def normalize_string_list(items: Any, limit: int = 6) -> List[str]:
    """把模型返回的数组字段规整成去重、去空的字符串列表。"""
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list):
        return []

    result = []
    seen = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(text)
        if len(result) >= limit:
            break
    return result


def escape_with_highlights(text: str, highlights: Optional[List[str]] = None) -> str:
    """先做 HTML 转义，再把结构化 highlight 短语渲染成统一样式。"""
    escaped_text = escape(str(text or ""))
    phrases = normalize_string_list(highlights or [], limit=8)
    if not phrases:
        return escaped_text

    placeholders = {}
    replaced_text = escaped_text
    for idx, phrase in enumerate(sorted(phrases, key=len, reverse=True), 1):
        escaped_phrase = escape(phrase)
        token = f"__HIGHLIGHT_{idx}__"
        if escaped_phrase and escaped_phrase in replaced_text:
            replaced_text = replaced_text.replace(
                escaped_phrase,
                token,
            )
            placeholders[token] = f'<span class="highlight">{escaped_phrase}</span>'

    for token, html in placeholders.items():
        replaced_text = replaced_text.replace(token, html)
    return replaced_text


def derive_highlight_phrases(text: str, limit: int = 4) -> List[str]:
    """当模型没有稳定返回 highlight 时，用判断性短语补一层重点高亮。"""
    raw = str(text or "").strip()
    if not raw:
        return []

    candidates = []

    patterns = [
        r'["“](.{2,40}?)["”]',
        r"(危机公关/注意力转移|生死存亡级冲突|估值折扣创造entry point|唯一全栈AI玩家|硬件护城河变薄|系统性流动性收缩|效率差距扩大是结构性问题)",
        r"([\u4e00-\u9fffA-Za-z0-9/+\-]{4,28}(?:受益者|创造entry point|护城河变薄|全栈AI玩家|流动性收缩|结构性问题|危机公关|注意力转移|冲突|折扣|错杀机会|战略转向|重新定价|趋势|逻辑))",
    ]
    for pattern in patterns:
        candidates.extend(re.findall(pattern, raw))

    normalized = []
    seen = set()
    for candidate in candidates:
        phrase = str(candidate).strip(" \"“”'()[]")
        if len(phrase) < 2 or len(phrase) > 40:
            continue
        lowered = phrase.lower()
        if lowered in {"ai", "et", "pm", "am"}:
            continue
        if re.fullmatch(r"[$]?[0-9]+(?:\.[0-9]+)?(?:%|bps|x|亿|万|bn|b|m)?", lowered):
            continue
        if re.fullmatch(r"[A-Z]{2,5}", phrase):
            continue
        if re.fullmatch(r"[A-Z0-9/+\- ]{2,20}", phrase):
            continue
        if not re.search(r"[\u4e00-\u9fff]", phrase):
            continue
        if not re.search(r"(危机|冲突|受益者|折扣|机会|护城河|全栈|流动性|结构性|逻辑|趋势|转向|重估|错杀|信号|判断|定位|催化)", phrase):
            continue
        key = phrase.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(phrase)
        if len(normalized) >= limit:
            break
    return normalized


def merge_highlight_phrases(*sources: Any, limit: int = 6) -> List[str]:
    """优先使用模型给的高亮短语，不足时再用规则补齐。"""
    result = []
    seen = set()
    for source in sources:
        for item in normalize_string_list(source, limit=limit):
            key = item.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
            if len(result) >= limit:
                return result
    return result


def coerce_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def build_priority_sort_key(item: Dict[str, Any]) -> tuple:
    """统一的优先级排序键：先按显式 rank，再按覆盖度，再按全局分数。"""
    raw_rank = item.get("priority_rank")
    rank = coerce_int(raw_rank, 9999 if raw_rank in (None, "") else 9999)
    coverage = coerce_int(item.get("coverage_count"), 0)
    score = coerce_float(item.get("global_score"), 0.0)
    return (rank, -coverage, -score)


def sort_by_priority(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(items, key=build_priority_sort_key)


def normalize_core_event_link_refs(value: Any, limit: int = 5) -> List[str]:
    refs = normalize_string_list(value, limit=limit)
    normalized = []
    seen = set()
    for ref in refs:
        ref = ref.strip()
        if not ref:
            continue
        key = ref.lower()
        if key in seen:
            continue
        seen.add(key)
        normalized.append(ref)
    return normalized


def build_core_event_lookup(core_events: List[Dict[str, Any]]) -> Dict[str, str]:
    lookup: Dict[str, str] = {}
    for item in core_events:
        core_event_id = item.get("core_event_id")
        if not core_event_id:
            continue
        lookup[str(core_event_id).strip().lower()] = core_event_id
        for candidate in [item.get("headline"), *(item.get("source_topics") or [])]:
            if not candidate:
                continue
            lookup[str(candidate).strip().lower()] = core_event_id
    return lookup


def resolve_linked_core_event_ids(
    explicit_refs: Any,
    source_topics: Any,
    core_event_lookup: Dict[str, str],
    limit: int = 5,
) -> List[str]:
    linked_ids = []
    seen = set()
    for ref in [*normalize_core_event_link_refs(explicit_refs, limit=limit), *normalize_string_list(source_topics, limit=limit)]:
        key = str(ref).strip().lower()
        if not key:
            continue
        mapped = core_event_lookup.get(key)
        if not mapped:
            continue
        if mapped in seen:
            continue
        seen.add(mapped)
        linked_ids.append(mapped)
        if len(linked_ids) >= limit:
            break
    return linked_ids


def normalize_actionable_dedupe_key(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip()).lower()


def dedupe_actionable_items(
    items: List[Dict[str, Any]],
    existing_keys: Optional[set] = None,
) -> List[Dict[str, Any]]:
    deduped = []
    seen = set(existing_keys or set())
    for item in items:
        key = normalize_actionable_dedupe_key(item.get("idea", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped


def normalize_actionable_item(item: Any, fallback_text_key: str = "idea") -> Optional[Dict[str, Any]]:
    if isinstance(item, str):
        text = item.strip()
        if not text:
            return None
        return {
            "idea": text,
            "priority_rank": 9999,
            "coverage_count": 0,
            "global_score": 0.0,
            "source_topics": [],
            "linked_core_event_refs": [],
        }

    if not isinstance(item, dict):
        return None

    text = str(
        item.get("idea")
        or item.get("text")
        or item.get("title")
        or item.get(fallback_text_key)
        or ""
    ).strip()
    if not text:
        return None

    return {
        "idea": text,
        "priority_rank": coerce_int(item.get("priority_rank"), 9999),
        "coverage_count": coerce_int(item.get("coverage_count"), 0),
        "global_score": coerce_float(item.get("global_score"), 0.0),
        "source_topics": normalize_string_list(item.get("source_topics"), limit=5),
        "linked_core_event_refs": normalize_core_event_link_refs(
            item.get("linked_core_event_headlines") or item.get("linked_core_event_ids"),
            limit=5,
        ),
    }


def normalize_report_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    """把最终晨报 JSON 规整到固定模板槽位。"""
    executive = payload.get("executive_summary") or payload.get("summary") or {}
    if not isinstance(executive, dict):
        executive = {}

    coverage_items = (
        payload.get("core_events")
        or payload.get("key_coverage")
        or payload.get("coverage")
        or payload.get("topics")
        or []
    )
    if not isinstance(coverage_items, list):
        coverage_items = []

    normalized_coverage = []
    for item in coverage_items:
        if not isinstance(item, dict):
            continue

        headline = str(
            item.get("headline")
            or item.get("title")
            or item.get("topic")
            or ""
        ).strip()
        if not headline:
            continue

        normalized_coverage.append({
            "headline": headline,
            "priority_rank": coerce_int(item.get("priority_rank"), 9999),
            "coverage_count": coerce_int(item.get("coverage_count"), 0),
            "global_score": coerce_float(item.get("global_score"), 0.0),
            "source_topics": normalize_string_list(item.get("source_topics") or item.get("email_ids"), limit=8),
            "core_facts": normalize_string_list(item.get("core_facts") or item.get("facts"), limit=4),
            "market_views": [
                {
                    "source": str(row.get("source") or row.get("观点来源") or "").strip(),
                    "stance": str(row.get("stance") or row.get("立场") or "").strip(),
                    "thesis": str(row.get("thesis") or row.get("core_argument") or row.get("核心论点") or "").strip(),
                    "highlight_phrases": merge_highlight_phrases(
                        row.get("highlight_phrases") or row.get("highlights"),
                        derive_highlight_phrases(row.get("thesis") or row.get("core_argument") or row.get("核心论点") or ""),
                        limit=4,
                    ),
                }
                for row in (item.get("market_views") or item.get("view_table") or [])
                if isinstance(row, dict)
                and (
                    str(row.get("source") or row.get("观点来源") or "").strip()
                    or str(row.get("stance") or row.get("立场") or "").strip()
                    or str(row.get("thesis") or row.get("core_argument") or row.get("核心论点") or "").strip()
                )
            ],
            "market_take": normalize_string_list(item.get("market_take") or item.get("market_takeaways"), limit=4),
            "importance": str(item.get("importance") or item.get("why_it_matters") or "").strip(),
            "action": str(item.get("action") or item.get("investment_takeaway") or item.get("investment_implication") or "").strip(),
            "highlight_phrases": merge_highlight_phrases(
                item.get("highlight_phrases") or item.get("highlights"),
                derive_highlight_phrases(headline, limit=2),
                derive_highlight_phrases(item.get("action") or item.get("investment_takeaway") or item.get("investment_implication") or "", limit=3),
                derive_highlight_phrases(" ".join(item.get("core_facts") or item.get("facts") or []), limit=4),
                limit=6,
            ),
            "attribution_note": str(item.get("attribution_note") or item.get("source_note") or "").strip(),
            "source_evidence": normalize_string_list(item.get("source_evidence"), limit=3),
        })

    normalized_coverage = sort_by_priority(normalized_coverage)[:6]
    for index, item in enumerate(normalized_coverage, 1):
        item["core_event_id"] = f"core_event_{index}"

    core_event_lookup = build_core_event_lookup(normalized_coverage)

    local_news = payload.get("local_news") or []
    if not isinstance(local_news, list):
        local_news = []
    normalized_local_news = []
    for item in local_news:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or item.get("title") or "").strip()
        if not headline:
            continue
        normalized_local_news.append({
            "headline": headline,
            "priority_rank": coerce_int(item.get("priority_rank"), 9999),
            "signal": str(item.get("signal") or "").strip(),
            "importance": str(item.get("importance") or item.get("why_it_matters") or "").strip(),
            "action": str(item.get("action") or "").strip(),
            "highlight_phrases": merge_highlight_phrases(
                item.get("highlight_phrases") or item.get("highlights"),
                derive_highlight_phrases(headline, limit=2),
                derive_highlight_phrases(item.get("signal") or "", limit=3),
                derive_highlight_phrases(item.get("action") or "", limit=3),
                limit=5,
            ),
        })

    normalized_local_news = sorted(
        normalized_local_news,
        key=lambda item: coerce_int(item.get("priority_rank"), 9999),
    )[:6]

    peripheral = payload.get("peripheral_intelligence") or {}
    if not isinstance(peripheral, dict):
        peripheral = {}

    mapped_events = peripheral.get("mapped_events") or payload.get("mapped_events") or []
    if not isinstance(mapped_events, list):
        mapped_events = []
    normalized_mapped_events = []
    for item in mapped_events:
        if not isinstance(item, dict):
            continue
        event = str(item.get("event") or item.get("外围事件") or "").strip()
        related = str(item.get("related_company") or item.get("相关公司") or "").strip()
        mapping = str(item.get("mapping") or item.get("对Key Coverage的映射") or "").strip()
        if not (event or related or mapping):
            continue
        normalized_mapped_events.append({
            "event": event,
            "related_company": related,
            "mapping": mapping,
        })

    cross_market_signals = peripheral.get("cross_market_signals") or payload.get("cross_market_signals") or []
    if not isinstance(cross_market_signals, list):
        cross_market_signals = []
    normalized_cross_market_signals = []
    for item in cross_market_signals:
        if not isinstance(item, dict):
            continue
        headline = str(item.get("headline") or item.get("title") or "").strip()
        bullets = normalize_string_list(item.get("bullets") or item.get("signals") or item.get("insights"), limit=4)
        if not headline and not bullets:
            continue
        normalized_cross_market_signals.append({
            "headline": headline,
            "priority_rank": coerce_int(item.get("priority_rank"), 9999),
            "bullets": bullets,
            "highlight_phrases": merge_highlight_phrases(
                item.get("highlight_phrases") or item.get("highlights"),
                derive_highlight_phrases(headline, limit=2),
                derive_highlight_phrases(" ".join(bullets), limit=4),
                limit=5,
            ),
        })

    normalized_cross_market_signals = sorted(
        normalized_cross_market_signals,
        key=lambda item: coerce_int(item.get("priority_rank"), 9999),
    )[:5]

    actionable = payload.get("actionable_ideas") or {}
    if not isinstance(actionable, dict):
        actionable = {}

    catalysts = actionable.get("catalysts") or payload.get("catalysts_to_watch") or payload.get("catalysts") or []
    if isinstance(catalysts, dict):
        catalysts = catalysts.get("items") or []
    if not isinstance(catalysts, list):
        catalysts = []
    normalized_catalysts = []
    for item in catalysts:
        if not isinstance(item, dict):
            continue
        catalyst = str(item.get("catalyst") or item.get("title") or "").strip()
        timing = str(item.get("time") or item.get("timing") or "").strip()
        impact = str(item.get("impact") or item.get("impact_assets") or item.get("affected_assets") or "").strip()
        if not (catalyst or timing or impact):
            continue
        normalized_catalysts.append({
            "catalyst": catalyst,
            "time": timing,
            "impact": impact,
            "priority_rank": coerce_int(item.get("priority_rank"), 9999),
            "coverage_count": coerce_int(item.get("coverage_count"), 0),
            "global_score": coerce_float(item.get("global_score"), 0.0),
            "source_topics": normalize_string_list(item.get("source_topics"), limit=5),
            "linked_core_event_refs": normalize_core_event_link_refs(
                item.get("linked_core_event_headlines") or item.get("linked_core_event_ids"),
                limit=5,
            ),
        })

    normalized_catalysts = sort_by_priority(normalized_catalysts)[:8]
    for item in normalized_catalysts:
        item["linked_core_event_ids"] = resolve_linked_core_event_ids(
            item.pop("linked_core_event_refs", []),
            item.get("source_topics"),
            core_event_lookup,
        )

    short_term_raw = actionable.get("short_term") or actionable.get("near_term") or []
    medium_term_raw = actionable.get("medium_term") or actionable.get("mid_term") or []
    if not short_term_raw:
        short_term_raw = (payload.get("catalysts_to_watch") or {}).get("short_term") or []
    if not medium_term_raw:
        medium_term_raw = (payload.get("catalysts_to_watch") or {}).get("medium_term") or []

    normalized_short_term = []
    if isinstance(short_term_raw, list):
        for item in short_term_raw:
            normalized_item = normalize_actionable_item(item)
            if normalized_item:
                normalized_short_term.append(normalized_item)
    normalized_short_term = dedupe_actionable_items(sort_by_priority(normalized_short_term))[:5]
    for item in normalized_short_term:
        item["linked_core_event_ids"] = resolve_linked_core_event_ids(
            item.pop("linked_core_event_refs", []),
            item.get("source_topics"),
            core_event_lookup,
        )

    normalized_medium_term = []
    if isinstance(medium_term_raw, list):
        for item in medium_term_raw:
            normalized_item = normalize_actionable_item(item)
            if normalized_item:
                normalized_medium_term.append(normalized_item)
    normalized_medium_term = dedupe_actionable_items(
        sort_by_priority(normalized_medium_term),
        existing_keys={normalize_actionable_dedupe_key(item.get("idea", "")) for item in normalized_short_term},
    )[:5]
    for item in normalized_medium_term:
        item["linked_core_event_ids"] = resolve_linked_core_event_ids(
            item.pop("linked_core_event_refs", []),
            item.get("source_topics"),
            core_event_lookup,
        )

    market_background_items = normalize_string_list(
        executive.get("market_background") or executive.get("background"),
        limit=4,
    )
    normalized = {
        "executive_summary": {
            "market_background": "；".join(market_background_items),
            "key_signals": normalize_string_list(
                executive.get("key_signals") or executive.get("signals"),
                limit=5,
            ),
        },
        "core_events": normalized_coverage,
        "local_news": normalized_local_news,
        "peripheral_intelligence": {
            "mapped_events": normalized_mapped_events,
            "cross_market_signals": normalized_cross_market_signals,
        },
        "actionable_ideas": {
            "short_term": normalized_short_term,
            "medium_term": normalized_medium_term,
            "catalysts": normalized_catalysts,
            "bottom_line": str(actionable.get("bottom_line") or payload.get("bottom_line") or "").strip(),
        },
    }

    if not normalized["executive_summary"]["market_background"]:
        normalized["executive_summary"]["market_background"] = "当日邮件的共同背景尚不充分，建议结合盘前行情一并解读。"
    if not normalized["executive_summary"]["key_signals"]:
        normalized["executive_summary"]["key_signals"] = ["暂无足够强的共识信号，需结合后续白名单邮件继续观察。"]
    if not normalized["local_news"]:
        normalized["local_news"] = [{
            "headline": "暂无额外边缘信号",
            "signal": "目前白名单邮件中的高价值信息主要集中在核心事件。",
            "importance": "避免为了填充版面而加入低质量噪音。",
            "action": "后续如有补充邮件，再更新边缘信号。",
        }]
    if not normalized["actionable_ideas"]["short_term"]:
        normalized["actionable_ideas"]["short_term"] = [normalize_actionable_item("关注盘前新增邮件、管理层发言和数据披露是否改变当前判断。")]
    if not normalized["actionable_ideas"]["medium_term"]:
        normalized["actionable_ideas"]["medium_term"] = [normalize_actionable_item("关注未来 1-4 周内产业链验证、财报与产品节点带来的再定价机会。")]
    if not normalized["actionable_ideas"]["catalysts"]:
        normalized["actionable_ideas"]["catalysts"] = [{
            "catalyst": "后续白名单邮件验证",
            "time": "TBD",
            "impact": "相关主题与标的",
        }]
    if not normalized["actionable_ideas"]["bottom_line"]:
        normalized["actionable_ideas"]["bottom_line"] = "市场仍处于信息快速演化阶段，建议优先跟踪共识最强、验证路径最清晰的主题。"

    return normalized


def parse_report_payload_json(text: str) -> Dict[str, Any]:
    """解析最终晨报 JSON，并做字段归一化。"""
    try:
        payload = load_json_dict_with_fallbacks(text)
    except Exception:
        logger.warning("⚠️ 最终晨报 JSON 解析失败，尝试修复")
        payload = repair_report_payload_json(text)
    return normalize_report_payload(payload)


def build_prompt_category_block(title: str, items: List[str]) -> str:
    lines = [f"## {title}"]
    for idx, item in enumerate(items, 1):
        lines.append(f"{idx}. {item}")
    return "\n".join(lines)


def get_report_prompt_governance() -> str:
    principles = [
        "优先做内容筛选和语义归因，再做摘要表达。",
        "结构稳定优先于文采，宁可朴素也不要漂移。",
        "图片、正文、附件文本需要在同一判断框架下联合理解。",
    ]
    bottom_lines = [
        "不能把外部引述、媒体报道、市场传闻误写成发件机构 house view。",
        "不能把普通功能小升级、版本小更新、一般性运营通知硬塞进核心版面。",
        "不能把观点判断、推测或带 says / suggests / reportedly 色彩的内容直接写成核心事实。",
    ]
    reminders = [
        "Executive Summary 固定只服务于市场背景和关键信号，不写散乱长段。",
        "核心事实每条尽量一句话；投资启示和为什么重要要短而硬。",
        "版式由本地固定模板渲染，模型只需要把内容填进正确槽位。",
    ]
    return "\n\n".join(
        [
            build_prompt_category_block("原则", principles),
            build_prompt_category_block("底线", bottom_lines),
            build_prompt_category_block("提醒", reminders),
        ]
    )


def get_fixed_report_schema_prompt() -> str:
    return f"""## 固定模板槽位
你必须输出合法 JSON，字段结构如下：
{{
  "executive_summary": {{
    "market_background": "1段，概括市场大背景",
    "key_signals": ["3-5条，提炼当日最重要信号"]
  }},
  "core_events": [
    {{
      "headline": "事件标题",
      "priority_rank": 1,
      "coverage_count": 3,
      "global_score": 9.5,
      "source_topics": ["相关主题或邮件编号"],
      "core_facts": ["1-4条，每条尽量一句话，只写硬信息"],
      "market_views": [
        {{
          "source": "观点来源",
          "stance": "立场",
          "thesis": "核心论点",
          "highlight_phrases": ["这一行里最值得高亮的1-3个短语，可选"]
        }}
      ],
      "action": "投资启示，1-2句",
      "highlight_phrases": ["本主题最该高亮的1-4个短语，可选"],
      "attribution_note": "如有外部引述或传闻，明确说明真实主语；没有可留空字符串",
      "source_evidence": ["保留最关键的原文依据，最多3条"]
    }}
  ],
  "local_news": [
    {{
      "headline": "容易被忽略的信号标题",
      "priority_rank": 1,
      "signal": "发生了什么",
      "importance": "为什么重要",
      "action": "怎么交易/如何跟踪",
      "highlight_phrases": ["可选：这一条里最该高亮的短语"]
    }}
  ],
  "peripheral_intelligence": {{
    "mapped_events": [
      {{
        "event": "外围事件",
        "related_company": "相关公司",
        "mapping": "对核心主题的映射"
      }}
    ],
    "cross_market_signals": [
      {{
        "headline": "跨市场信号标题",
        "priority_rank": 1,
        "bullets": ["2-4条"],
        "highlight_phrases": ["可选：跨市场映射里最该高亮的短语"]
      }}
    ]
  }},
  "actionable_ideas": {{
    "short_term": [
      {{
        "idea": "短期(1-5天)交易想法",
        "priority_rank": 1,
        "coverage_count": 3,
        "global_score": 9.0,
        "source_topics": ["来自哪些高优先级主题"],
        "linked_core_event_headlines": ["引用 `core_events.headline` 中的标题，最多3个"]
      }}
    ],
    "medium_term": [
      {{
        "idea": "中期(1-4周)交易想法",
        "priority_rank": 1,
        "coverage_count": 2,
        "global_score": 8.5,
        "source_topics": ["来自哪些高优先级主题"],
        "linked_core_event_headlines": ["引用 `core_events.headline` 中的标题，最多3个"]
      }}
    ],
    "catalysts": [
      {{
        "catalyst": "事件",
        "time": "时间",
        "impact": "影响标的",
        "priority_rank": 1,
        "coverage_count": 2,
        "global_score": 8.0,
        "source_topics": ["关联主题"],
        "linked_core_event_headlines": ["引用 `core_events.headline` 中的标题，最多3个"]
      }}
    ],
    "bottom_line": "1句总结"
  }}
}}

## 固定模板说明
- `Executive Summary` 下面固定只放 `{FIXED_REPORT_TEMPLATE["executive_summary"][0]}` 和 `{FIXED_REPORT_TEMPLATE["executive_summary"][1]}`
- `核心事件与市场观点` 下的每个主题固定只使用 `{ " / ".join(FIXED_REPORT_TEMPLATE["core_event_labels"]) }`
- `Local News` 固定只使用 `{ " / ".join(FIXED_REPORT_TEMPLATE["local_news_labels"]) }`
- `Peripheral Intelligence` 固定拆成 `{ " / ".join(FIXED_REPORT_TEMPLATE["peripheral_subsections"]) }`
- `Actionable Ideas` 固定拆成 `{FIXED_REPORT_TEMPLATE["actionable_labels"][0]}`、`{FIXED_REPORT_TEMPLATE["actionable_labels"][1]}`、`{FIXED_REPORT_TEMPLATE["actionable_labels"][2]}`
- `Local News` 与 `Peripheral Intelligence` 承接不属于最高优先级核心覆盖的内容
- `Actionable Ideas` 不是剩余信息区，而是基于全局信息重新提炼最有行动价值的交易想法与催化剂
- `core_events`、`Actionable Ideas`、`catalysts` 必须显式给出 `priority_rank / coverage_count / global_score`，本地会据此再做一次排序校验
- `Actionable Ideas` 与 `catalysts` 应尽量给出 `linked_core_event_headlines`，引用它们所依赖的 `core_events.headline`，本地会把这些引用映射成可解释的 `linked_core_event_ids`
- `highlight` 属于结构字段：你只需指出哪些短语需要强调，本地模板会统一渲染高亮样式
- 应优先高亮：程度描述、核心结论、独特定位、趋势判断
- 不要高亮：纯数字、普通描述性文字、纯ticker、一般事实名词
- 不要输出 HTML，不要输出 Markdown，不要发明额外顶层模块
"""


def render_list_html(items: List[Any], highlights: Optional[List[str]] = None) -> str:
    if not items:
        return ""
    rendered_items = []
    for item in items:
        if isinstance(item, dict):
            text = item.get("idea") or item.get("text") or item.get("title") or ""
            item_highlights = item.get("highlight_phrases") or highlights
        else:
            text = item
            item_highlights = highlights
        rendered_items.append(f"<li>{escape_with_highlights(text, item_highlights)}</li>")
    li_items = "".join(rendered_items)
    return f"<ul>{li_items}</ul>"


def render_market_views_table(rows: List[Dict[str, str]]) -> str:
    if not rows:
        return ""

    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td><strong>{escape_with_highlights(row.get('source', ''), row.get('highlight_phrases'))}</strong></td>"
            f"<td>{escape_with_highlights(row.get('stance', ''), row.get('highlight_phrases'))}</td>"
            f"<td>{escape_with_highlights(row.get('thesis', ''), row.get('highlight_phrases'))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<tr><th>观点来源</th><th>立场</th><th>核心论点</th></tr>"
        + "".join(body_rows)
        + "</table>"
    )


def render_peripheral_table(rows: List[Dict[str, str]]) -> str:
    if not rows:
        return ""
    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td>{escape(row.get('event', ''))}</td>"
            f"<td>{escape(row.get('related_company', ''))}</td>"
            f"<td>{escape(row.get('mapping', ''))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<tr><th>外围事件</th><th>相关公司</th><th>对Key Coverage的映射</th></tr>"
        + "".join(body_rows)
        + "</table>"
    )


def render_catalysts_table(rows: List[Dict[str, str]]) -> str:
    if not rows:
        return ""
    body_rows = []
    for row in rows:
        body_rows.append(
            "<tr>"
            f"<td>{escape(row.get('catalyst', ''))}</td>"
            f"<td>{escape(row.get('time', ''))}</td>"
            f"<td>{escape(row.get('impact', ''))}</td>"
            "</tr>"
        )
    return (
        "<table>"
        "<tr><th>Catalyst</th><th>时间</th><th>影响标的</th></tr>"
        + "".join(body_rows)
        + "</table>"
    )


def build_priority_debug_summary(payload: Dict[str, Any]) -> str:
    core_event_map = {
        item.get("core_event_id"): item.get("headline", "")
        for item in payload.get("core_events", [])
        if item.get("core_event_id")
    }

    lines = ["排序与映射摘要:"]
    if payload.get("core_events"):
        lines.append("  Key Coverage:")
        for item in payload["core_events"]:
            lines.append(
                "    - {id} | rank={rank} | coverage={coverage} | score={score} | {headline}".format(
                    id=item.get("core_event_id", "-"),
                    rank=item.get("priority_rank", "-"),
                    coverage=item.get("coverage_count", 0),
                    score=item.get("global_score", 0.0),
                    headline=item.get("headline", ""),
                )
            )

    actionable = payload.get("actionable_ideas", {})
    for section_key, section_label in [("short_term", "短期想法"), ("medium_term", "中期想法")]:
        section_items = actionable.get(section_key) or []
        if not section_items:
            continue
        lines.append(f"  {section_label}:")
        for item in section_items:
            linked = [
                core_event_map.get(core_event_id, core_event_id)
                for core_event_id in (item.get("linked_core_event_ids") or [])
            ]
            lines.append(
                "    - rank={rank} | coverage={coverage} | score={score} | linked={linked} | {idea}".format(
                    rank=item.get("priority_rank", "-"),
                    coverage=item.get("coverage_count", 0),
                    score=item.get("global_score", 0.0),
                    linked=", ".join(linked) if linked else "[]",
                    idea=item.get("idea", ""),
                )
            )

    catalysts = actionable.get("catalysts") or []
    if catalysts:
        lines.append("  Catalysts:")
        for item in catalysts:
            linked = [
                core_event_map.get(core_event_id, core_event_id)
                for core_event_id in (item.get("linked_core_event_ids") or [])
            ]
            lines.append(
                "    - rank={rank} | coverage={coverage} | score={score} | linked={linked} | {catalyst}".format(
                    rank=item.get("priority_rank", "-"),
                    coverage=item.get("coverage_count", 0),
                    score=item.get("global_score", 0.0),
                    linked=", ".join(linked) if linked else "[]",
                    catalyst=item.get("catalyst", ""),
                )
            )

    return "\n".join(lines)


def render_report_html(report_payload: Dict[str, Any], source_emails: Optional[List[Dict]] = None) -> str:
    """用固定模板渲染最终 HTML，避免模型直接输出排版。"""
    payload = normalize_report_payload(report_payload)
    logger.info("\n" + build_priority_debug_summary(payload))
    body_parts = [
        "<h2>Executive Summary</h2>",
        f'<p><strong>{FIXED_REPORT_TEMPLATE["executive_summary"][0]}:</strong> {escape(payload["executive_summary"]["market_background"])}</p>',
        f'<p><strong>{FIXED_REPORT_TEMPLATE["executive_summary"][1]}:</strong></p>',
        render_list_html(payload["executive_summary"]["key_signals"]),
        '<div class="divider"></div>',
        f'<h2>{FIXED_REPORT_TEMPLATE["core_events_h2"]}</h2>',
    ]

    for index, coverage in enumerate(payload["core_events"], 1):
        body_parts.append(f"<h3>{index}. {escape(coverage['headline'])}</h3>")
        if coverage["core_facts"]:
            body_parts.append("<p><strong>核心事实</strong></p>")
            body_parts.append(render_list_html(coverage["core_facts"], coverage["highlight_phrases"]))
        body_parts.append("<p><strong>市场怎么看</strong></p>")
        if coverage["market_views"]:
            body_parts.append(render_market_views_table(coverage["market_views"]))
        elif coverage["market_take"]:
            body_parts.append(render_list_html(coverage["market_take"], coverage["highlight_phrases"]))
        if coverage["action"]:
            body_parts.append("<p><strong>投资启示</strong></p>")
            body_parts.append(f'<p>{escape_with_highlights(coverage["action"], coverage["highlight_phrases"])}</p>')

    body_parts.append('<div class="divider"></div>')
    body_parts.append(f'<h2>{FIXED_REPORT_TEMPLATE["local_news_h2"]}</h2>')
    for index, item in enumerate(payload["local_news"], 1):
        body_parts.append(f"<h3>{index}. {escape(item['headline'])}</h3>")
        body_parts.append("<p><strong>信号</strong></p>")
        body_parts.append(f'<p>{escape_with_highlights(item["signal"], item["highlight_phrases"])}</p>')
        body_parts.append("<p><strong>为什么重要</strong></p>")
        body_parts.append(f'<p>{escape_with_highlights(item["importance"], item["highlight_phrases"])}</p>')
        body_parts.append("<p><strong>Action</strong></p>")
        body_parts.append(f'<p>{escape_with_highlights(item["action"], item["highlight_phrases"])}</p>')

    body_parts.append(f'<h2>{FIXED_REPORT_TEMPLATE["peripheral_h2"]}</h2>')
    body_parts.append(f'<h3>{FIXED_REPORT_TEMPLATE["peripheral_subsections"][0]}</h3>')
    body_parts.append(render_peripheral_table(payload["peripheral_intelligence"]["mapped_events"]))
    body_parts.append(f'<h3>{FIXED_REPORT_TEMPLATE["peripheral_subsections"][1]}</h3>')
    for item in payload["peripheral_intelligence"]["cross_market_signals"]:
        if item["headline"]:
            body_parts.append(f'<p><strong>{escape_with_highlights(item["headline"], item["highlight_phrases"])}</strong></p>')
        body_parts.append(render_list_html(item["bullets"], item["highlight_phrases"]))

    body_parts.append(f'<h2>{FIXED_REPORT_TEMPLATE["actionable_h2"]}</h2>')
    body_parts.append(f'<h3>{FIXED_REPORT_TEMPLATE["actionable_labels"][0]}</h3>')
    body_parts.append(render_list_html(payload["actionable_ideas"]["short_term"]))
    body_parts.append(f'<h3>{FIXED_REPORT_TEMPLATE["actionable_labels"][1]}</h3>')
    body_parts.append(render_list_html(payload["actionable_ideas"]["medium_term"]))
    body_parts.append(f'<h3>{FIXED_REPORT_TEMPLATE["actionable_labels"][2]}</h3>')
    body_parts.append(render_catalysts_table(payload["actionable_ideas"]["catalysts"]))
    body_parts.append(f'<p><strong>{FIXED_REPORT_TEMPLATE["actionable_labels"][3]}:</strong> {escape(payload["actionable_ideas"]["bottom_line"])}</p>')
    return format_html_report(
        "\n".join(part for part in body_parts if part),
        source_emails=source_emails,
        normalize_body=False,
    )


def analyze_batch_summary_with_kimi(batch_emails: List[Dict], total_email_count: int, batch_index: int, batch_total: int) -> Dict:
    emails_text = build_emails_text(batch_emails, total_email_count, total_body_budget=MAX_PROMPT_BODY_CHARS // 2)
    batch_email_ids = ", ".join(str(email.get("_analysis_index")) for email in batch_emails)

    system_prompt = f"""你是一位卖方邮件研究助理。你当前的任务不是直接写最终晨报，而是先把一个子批次邮件压缩成便于二次合并的结构化 JSON 摘要。

## 原则
- 先区分事实、观点、传闻，再做摘要
- 主语归因优先于表面语气词
- 结构化信息优先于漂亮表述

## 规则
1. 只输出合法 JSON，不要 HTML，不要 Markdown，不要解释文字
2. 必须使用简体中文
3. 内容要极度精炼，只保留后续合并所需的信息
4. 高频主题必须写明覆盖邮件编号和覆盖邮件数
5. 同一主题下只保留最核心的事实、观点、交易含义
6. 每个主题必须明确区分“事实主体”和“观点主体”，不能把转述者默认当作观点提出者

## JSON 结构
{{
  "batch_index": {batch_index},
  "batch_total": {batch_total},
  "email_ids": [{batch_email_ids}],
  "topics": [
    {{
      "title": "主题名称",
      "email_ids": [1, 2],
      "coverage_count": 2,
      "fact_subject": "谁是客观事实的主体",
      "opinion_subject": "谁提出了观点；如果没有观点可填空字符串",
      "info_type": "事实 / 机构观点 / 外部引述 / 市场传闻",
      "core_facts": ["客观事实1", "客观事实2"],
      "market_takeaways": ["市场含义1", "市场含义2"],
      "tickers": ["NVDA", "MU"],
      "source_evidence": ["保留最关键的原文短句，注明真实主语"]
    }}
  ]
}}

## 底线
- 如果邮件尾部是签名、免责声明、法律声明，不要纳入摘要
- 只保留对最终 HF Morning Brief 有帮助的信息
- “发件人/券商机构”不等于“正文里每一句话的观点主体”
- 如果正文出现 `X says`、`according to X`、`reports suggest`、`媒体称`、`市场传闻`、`management said` 之类表述，必须把观点归给 X、媒体、市场或管理层，而不是默认归给发件机构
- 带有“认为 / 预计 / 可能 / 或 / suggests / reportedly / rumor”色彩的内容，默认不是核心事实，除非邮件里给出了可验证的客观证据
- 例如 `Shawn Kim says SRAM is a complement to HBM` 应写成 `Shawn Kim 认为...` 或 `邮件转述 Shawn Kim 的观点...`，不能写成 `MS认为...`，除非原文明确写的是 Morgan Stanley 的判断
"""

    user_prompt = f"""请把下面这批邮件整理成结构化中间摘要，供后续二次合并。

当前批次: {batch_index}/{batch_total}
批次包含邮件编号: {batch_email_ids}

邮件内容：
{emails_text}

请特别注意：
- 识别每条判断的真实主语
- 不要把引述来的第三方观点升级成发件机构观点
- 不要把带有判断色彩的观点写进“核心事实”
"""

    raw = generate_with_kimi(system_prompt, user_prompt, emails=batch_emails)
    parsed = parse_batch_summary_json(raw)
    parsed["batch_index"] = batch_index
    parsed["batch_total"] = batch_total
    return parsed


def merge_batch_summaries_with_kimi(
    batch_summaries: List[Dict],
    format_spec: str,
    total_email_count: int,
    source_emails: Optional[List[Dict]] = None,
) -> str:
    summaries_text = json.dumps(batch_summaries, ensure_ascii=False, indent=2)

    system_prompt = f"""你是一位专业的对冲基金研究分析师，擅长把多个子批次摘要合并成一份固定模板晨报的结构化 JSON。

{get_report_prompt_governance()}

## 额外参考规范
以下内容来自项目内的晨报规范文档，仅用于帮助你做内容取舍、章节语气和信息密度控制；最终排版仍以固定 JSON 槽位和本地模板为准。
{build_format_spec_guidance(format_spec) or "（无额外参考规范）"}

## 合并任务
你会收到若干份子批次摘要，这些摘要来自同一天的同一组 {total_email_count} 封卖方邮件。请完成以下工作：
1. 合并表达不同但实质相同的主题
2. 按合并后的覆盖邮件数排序，但不要在输出中显示覆盖数字
3. 如果主题出现在多个批次中，合并其事实、观点与邮件覆盖面
4. 外部引述、媒体消息、市场传闻必须保留真实主语和归因提醒
5. 普通功能升级、一般性产品更新、没有交易含义的 trivial 变化默认忽略或显著降权

{get_fixed_report_schema_prompt()}
"""

    user_prompt = f"""请将以下结构化子批次摘要合并成最终中文晨报 JSON。

{summaries_text}

请特别检查每个主题：
- 核心事实里是否混入了观点判断
- 观点主语是否被误写成发件机构
- 外部引述是否被错误升级为券商判断
- 是否把没有明确投资含义的 trivial 功能升级写进了核心版面
- Executive Summary 是否明确包含 `市场背景` 与 `关键信号`
- 核心事实是否仍然过长、过啰嗦
"""

    raw = generate_with_kimi(system_prompt, user_prompt)
    return render_report_html(parse_report_payload_json(raw), source_emails=source_emails)




# ============ 状态管理 ============
def load_state() -> Dict:
    """加载状态文件"""
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    return {
        "last_processed_date": None,
        "last_check_time": None,
        "last_error": None,
    }


def save_state(state: Dict):
    """保存状态文件"""
    with open(STATE_FILE, 'w', encoding='utf-8') as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def should_trigger() -> bool:
    """判断是否应该触发（每天只运行一次）"""
    now_bjt = datetime.now(BJT)
    state = load_state()
    last_processed = state.get("last_processed_date")

    if last_processed == now_bjt.strftime("%Y-%m-%d"):
        return False

    return True


# ============ 邮件收取 ============
@retry_on_error(max_retries=3, delay=3.0, backoff=2.0)
def fetch_emails(limit: int = 20) -> List[Dict]:
    """从Gmail收取邮件"""
    config = load_config()
    api_key = config.get("api_key", "")
    imap_cfg = config.get("imap", {})
    imap_host = imap_cfg.get("host", "imap.gmail.com")

    logger.info(f"📬 正在从 {imap_host} 收取邮件...")

    resp = session.get(
        f"{EMAIL_API}/api/emails",
        params={"api_key": api_key, "limit": limit, "source": imap_host},
        timeout=120
    )
    data = resp.json()

    if data.get("success"):
        emails = data["emails"]
        logger.info(f"✅ 成功收取 {len(emails)} 封邮件")
        # 保存到数据库（去重），作为后续分析/标记的唯一事实来源
        try:
            added = email_db.add_emails(emails)
            if added:
                logger.info(f"💾 已新增 {added} 封邮件到 SQLite")
        except Exception as e:
            logger.warning(f"⚠️ 写入数据库失败（将继续尝试分析本次收取结果）: {e}")
        return emails
    else:
        error_msg = data.get('detail', '未知错误')
        logger.error(f"❌ 收取邮件失败: {error_msg}")
        raise Exception(error_msg)


def save_pending_emails(emails: List[Dict]):
    """保存待处理的邮件到JSON文件"""
    if not emails:
        return

    data = {
        "timestamp": datetime.now(BJT).isoformat(),
        "count": len(emails),
        "emails": emails
    }

    with open(PENDING_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    logger.info(f"💾 已保存 {len(emails)} 封邮件到 {PENDING_FILE}")


def mark_emails_processed(email_uids: List[str]):
    """标记指定邮件 UID 为已处理"""
    uids = [uid for uid in (email_uids or []) if uid]
    if not uids:
        return

    email_db.mark_processed(uids)
    local_id_map = email_db.get_local_ids_by_uids(uids)
    local_ids = [local_id_map.get(uid) for uid in uids if local_id_map.get(uid) is not None]
    if local_ids:
        logger.info(f"✅ 已标记 {len(uids)} 封邮件为已处理 (local_id: {min(local_ids)}-{max(local_ids)})")
    else:
        logger.info(f"✅ 已标记 {len(uids)} 封邮件为已处理")


# ============ AI 分析 ============

def call_kimi_api(
    api_config: dict,
    system_prompt: str,
    user_prompt: str,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """
    调用 Kimi API，返回 HTML 内容或 None
    """
    url = f"{api_config['base_url']}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_config['api_key']}"
    }

    user_message_content: Any
    if user_content_blocks:
        user_message_content = [{"type": "text", "text": user_prompt}, *user_content_blocks]
    else:
        user_message_content = user_prompt

    payload = {
        "model": api_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message_content}
        ],
        "temperature": 1.0,
        "max_tokens": MAX_COMPLETION_TOKENS
    }

    resp = session.post(url, json=payload, headers=headers, timeout=300)
    try:
        resp.raise_for_status()
    except Exception:
        logger.warning(f"⚠️ API {api_config['base_url']} HTTP错误: {resp.status_code} {resp.text[:200]}")
        return None

    try:
        result = resp.json()
    except Exception:
        logger.warning(f"⚠️ API {api_config['base_url']} 返回非JSON: {resp.text[:200]}")
        return None

    if "choices" in result and len(result["choices"]) > 0:
        return result["choices"][0]["message"]["content"]
    else:
        error_msg = str(result)
        logger.warning(f"⚠️ API {api_config['base_url']} 返回错误: {error_msg}")
        return None


def call_kimi_api_with_retries(
    api_config: dict,
    system_prompt: str,
    user_prompt: str,
    label: str,
    max_retries: int = 1,
    delay: float = 5.0,
    backoff: float = 2.0,
    user_content_blocks: Optional[List[Dict[str, Any]]] = None,
) -> Optional[str]:
    """对单个模型做有限重试，失败后交由上层切换备用模型。"""
    current_delay = delay
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"🤖 正在调用 Kimi 大模型分析... ({label}: {api_config['base_url']})")
            html_content = call_kimi_api(
                api_config,
                system_prompt,
                user_prompt,
                user_content_blocks=user_content_blocks,
            )
            if html_content:
                if attempt > 0:
                    logger.info(f"✅ {label} 第 {attempt + 1} 次尝试成功")
                return html_content

            last_error = Exception("empty response")
            logger.warning(f"⚠️ {label} 返回空结果")
        except Exception as e:
            last_error = e
            logger.warning(f"⚠️ {label} 调用失败: {e}")

        if attempt < max_retries:
            logger.warning(f"⚠️ {label} 将在 {current_delay:.1f} 秒后重试...")
            time.sleep(current_delay)
            current_delay *= backoff

    if last_error:
        logger.warning(f"⚠️ {label} 最终失败: {last_error}")
    return None


def analyze_emails_with_kimi(emails: List[Dict], format_spec: str) -> Optional[str]:
    """
    调用 Kimi 大模型分析邮件，生成 HF Morning Brief HTML
    支持尾部清洗、超长上下文拆批分析，以及主/备模型自动切换
    """
    email_count = len(emails)
    email_batches = split_emails_for_analysis(emails)
    format_spec_guidance = build_format_spec_guidance(format_spec)

    if len(email_batches) == 1:
        emails_text = build_emails_text(email_batches[0], email_count, total_body_budget=MAX_PROMPT_BODY_CHARS)
        system_prompt = f"""你是一位专业的对冲基金研究分析师，擅长将卖方邮件转化为固定模板晨报的结构化 JSON。

{get_report_prompt_governance()}

## 额外参考规范
以下内容来自项目内的晨报规范文档，仅用于帮助你做内容取舍、章节语气和信息密度控制；最终排版仍以固定 JSON 槽位和本地模板为准。
{format_spec_guidance or "（无额外参考规范）"}

## 图片理解指引（重要！必须遵循）
邮件中可能包含图片（图表、截图、照片等），请按以下规则理解和处理：

1. **图表类图片**：
   - 提炼图表中的核心数据结论
   - 不要在报告中展示原始图表
   - 将图表传达的关键数据信息转化为文字描述

2. **非图表类图片**（截图、照片）：
   - 深度解读隐含信息，从以下维度分析：
     * 场合：这是什么场景？发布会？财报电话会？活动？
     * 人物：有哪些关键人物？他们的职位和身份？
     * 时机：为什么是现在？有什么特殊时间节点？
     * 公关策略：传达了什么信息？正面还是负面？
     * 信号强度：这个图片传递的信号有多强？

3. **图片融入方式**：
   - 图片信息应作为论据自然融入正文
   - 不要单独标注"图片佐证"
   - 直接写出从图片中解读出的Insight

{get_fixed_report_schema_prompt()}
"""

        user_prompt = f"""请分析以下邮件，生成最终晨报 JSON。

**重要：请使用简体中文（中文）输出所有字段内容。**

邮件内容：
{emails_text}

请严格按照固定模板槽位返回 JSON。

**注意：排序按邮件覆盖频率，但不要在输出中显示频率数字（如"3/3"、"2/3"）。**
**额外注意：不要把第三方被引述的观点错误写成发件机构观点；不要把观点判断错误写进核心事实。**
**如果邮件里只是功能上线、版本升级、界面变化、一般性产品更新，而没有清晰交易含义，请忽略或降权，不要放进核心版面。**"""

        raw = generate_with_kimi(system_prompt, user_prompt, emails=emails)
        html_content = render_report_html(parse_report_payload_json(raw), source_emails=emails)
        logger.info("✅ Kimi 分析完成")
        return html_content

    logger.info(f"✂️ 上下文较长，拆分为 {len(email_batches)} 个批次进行分析后合并")
    batch_summaries = []
    for idx, batch in enumerate(email_batches, 1):
        logger.info(f"🧩 正在分析子批次 {idx}/{len(email_batches)}（{len(batch)} 封邮件）")
        batch_summaries.append(
            analyze_batch_summary_with_kimi(
                batch,
                total_email_count=email_count,
                batch_index=idx,
                batch_total=len(email_batches),
            )
        )

    html_content = merge_batch_summaries_with_kimi(
        batch_summaries,
        format_spec,
        total_email_count=email_count,
        source_emails=emails,
    )
    logger.info("✅ Kimi 分析完成")
    return html_content


# ============ 报告处理 ============
def validate_html(html_content: str) -> tuple[bool, str]:
    """
    验证HTML内容完整性

    返回: (是否有效, 错误信息)
    """
    if not html_content or len(html_content.strip()) < 100:
        return False, "内容过短，可能不完整"

    # 检查必需的HTML标签
    required_tags = ['<html', '<head', '<body', '</html>']
    for tag in required_tags:
        if tag.lower() not in html_content.lower():
            return False, f"缺少必需标签: {tag}"

    # 检查标签是否闭合
    if html_content.count('<html') != html_content.count('</html>'):
        return False, "html标签未正确闭合"

    return True, ""


def estimate_read_minutes_from_html(body_content: str) -> int:
    """根据正文长度粗略估算阅读时间。"""
    text = re.sub(r"<[^>]+>", " ", body_content or "")
    text = re.sub(r"\s+", " ", text).strip()
    if not text:
        return 1
    return max(1, min(8, round(len(text) / 320)))


def extract_source_label_from_email(email: Dict) -> str:
    """优先从邮件主题/正文中提取更真实的来源标签，再回退到发件人。"""
    search_text = " ".join(
        [
            str(email.get("subject") or ""),
            str(email.get("body") or ""),
            str(email.get("from_name") or ""),
        ]
    ).lower()

    for label, patterns in SOURCE_LABEL_PATTERNS:
        for pattern in patterns:
            if re.search(pattern, search_text, flags=re.IGNORECASE):
                return label

    from_name = (email.get("from_name") or "").strip()
    if from_name:
        return from_name
    return (email.get("from") or "").strip()


def build_report_meta_html(source_emails: Optional[List[Dict]], body_content: str) -> str:
    """在标题下方展示阅读时长和来源。"""
    read_minutes = estimate_read_minutes_from_html(body_content)
    labels = []
    seen = set()
    for email in source_emails or []:
        label = extract_source_label_from_email(email)
        if not label:
            continue
        key = label.lower()
        if key in seen:
            continue
        seen.add(key)
        labels.append(label)
    source_text = " + ".join(labels[:4]) if labels else "Whitelisted analyst emails"
    return f'<div class="meta">Prepared by: AI Research Assistant | Source: {escape(source_text)} | Reading time: {read_minutes} mins</div>'


def normalize_report_body_content(body_content: str) -> str:
    """
    报告正文规范化单入口。

    原则：
    - 先收敛语义结构，再收敛视觉样式。
    规则：
    - 同类标签统一映射到固定组件。
    底线：
    - 不允许同一标签在不同报告里呈现出不一致的层级/底色。
    提醒：
    - prompt 只是建议，本地规则才是最终版式真源。
    """
    normalized = body_content or ""
    normalized = re.sub(r'<(?:p|div)\s+class="meta">.*?</(?:p|div)>', '', normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = re.sub(r'<p>\s*阅读时间[^<]*</p>', '', normalized, flags=re.IGNORECASE | re.DOTALL)
    normalized = normalize_legacy_label_boxes(normalized)
    normalized = normalize_subsection_headings(normalized)
    normalized = normalize_standalone_labels(normalized)
    normalized = normalize_existing_heading_tags(normalized)
    normalized = normalize_semantic_callout_blocks(normalized)
    normalized = normalize_inline_labeled_paragraphs(normalized)
    normalized = strip_highlight_inside_headings(normalized)
    return normalized


def normalize_legacy_label_boxes(body_content: str) -> str:
    """把旧版 action-box/signal-box 渲染收敛成当前固定标签结构。"""
    if not body_content:
        return body_content

    supported_labels = {"投资启示", "信号", "为什么重要", "Action"}
    pattern = (
        r'<div\s+class="(?:action-box|signal-box)">\s*'
        r'<div\s+class="callout-title">\s*(.*?)\s*</div>\s*'
        r'((?:<p\b[^>]*>.*?</p>\s*|<ul\b[^>]*>.*?</ul>\s*|<ol\b[^>]*>.*?</ol>\s*|'
        r'<table\b[^>]*>.*?</table>\s*|<blockquote\b[^>]*>.*?</blockquote>\s*)+)'
        r'</div>'
    )

    def replace_box(match):
        label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        content = (match.group(2) or "").strip()
        if label not in supported_labels or not content:
            return match.group(0)
        return f"<p><strong>{label}</strong></p>\n{content}"

    previous = None
    normalized = body_content
    while previous != normalized:
        previous = normalized
        normalized = re.sub(
            pattern,
            replace_box,
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return normalized


def format_html_report(
    html_content: str,
    source_emails: Optional[List[Dict]] = None,
    normalize_body: bool = True,
) -> str:
    """
    格式校准：将Kimi生成的HTML格式化为标准格式
    应用参考文件的CSS样式和结构
    """
    import re

    # 读取参考CSS
    css_file = os.path.join(BASE_DIR, "reference_css.txt")
    reference_css = ""
    if os.path.exists(css_file):
        with open(css_file, 'r', encoding='utf-8') as f:
            reference_css = f.read()

    # 提取body内容
    body_match = re.search(r'<body>(.*?)</body>', html_content, re.DOTALL)
    body_content = body_match.group(1) if body_match else html_content
    if normalize_body:
        body_content = normalize_report_body_content(body_content)

    # 构建标准化HTML
    today_str = datetime.now(BJT).strftime('%Y-%m-%d')
    standardized_title = f"AI Morning Brief | {today_str}"

    if re.search(r'<h1\b[^>]*>.*?</h1>', body_content, re.IGNORECASE | re.DOTALL):
        body_content = re.sub(
            r'<h1\b[^>]*>.*?</h1>',
            f'<h1>{standardized_title}</h1>',
            body_content,
            count=1,
            flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        body_content = f"<h1>{standardized_title}</h1>\n{body_content}"

    meta_html = build_report_meta_html(source_emails, body_content)
    body_content = re.sub(
        r'(<h1\b[^>]*>.*?</h1>)',
        r'\1' + "\n" + meta_html,
        body_content,
        count=1,
        flags=re.IGNORECASE | re.DOTALL,
    )

    formatted_html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{standardized_title}</title>
    <style>
{reference_css}
    </style>
</head>
<body>
    <div class="container">
{body_content}
    </div>
</body>
</html>'''

    return formatted_html


def normalize_subsection_headings(body_content: str) -> str:
    """把模型生成的“粗体段落小标题”提升为 h3，减少样式漂移。"""
    if not body_content:
        return body_content

    def replace_heading(match):
        raw_heading = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        if not raw_heading or len(raw_heading) > 80:
            return match.group(0)

        normalized = raw_heading.rstrip(":：").strip()
        if not normalized:
            return match.group(0)

        has_suffix_punct = raw_heading.endswith((':', '：'))
        is_short_english_heading = bool(re.fullmatch(r"[A-Z][A-Za-z0-9/&,\-()' ]{2,79}", normalized))

        if not has_suffix_punct and not is_short_english_heading:
            return match.group(0)

        return f"<h3>{normalized}</h3>"

    return re.sub(
        r"<p>\s*<strong>(.*?)</strong>\s*</p>",
        replace_heading,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def strip_highlight_inside_headings(body_content: str) -> str:
    """标题里不保留 highlight，避免高亮跑到 heading 上。"""
    if not body_content:
        return body_content

    def replace_heading(match):
        tag = match.group(1)
        attrs = match.group(2) or ""
        inner = match.group(3)
        cleaned_inner = re.sub(
            r'<span\s+class="highlight">(.*?)</span>',
            r'\1',
            inner,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return f"<{tag}{attrs}>{cleaned_inner}</{tag}>"

    return re.sub(
        r"<(h[1-4])([^>]*)>(.*?)</\1>",
        replace_heading,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def normalize_standalone_labels(body_content: str) -> str:
    """把常见的独立粗体标签提升成稳定的小节标题。"""
    if not body_content:
        return body_content

    def replace_label(match):
        raw_label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        normalized = raw_label.rstrip(":：").strip()
        if normalized in SECTION_SUBHEADINGS:
            return f"<h3>{normalized}</h3>"
        if normalized in TIME_HORIZON_SUBHEADINGS:
            return f'<h3 class="horizon-heading">{normalized}</h3>'
        if normalized in STANDALONE_SUBHEADINGS:
            return f"<h4>{normalized}</h4>"
        return match.group(0)

    return re.sub(
        r"<p>\s*<strong>(.*?)</strong>\s*</p>",
        replace_label,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def normalize_existing_heading_tags(body_content: str) -> str:
    """把模型直接生成的 h3/h4 标签也收敛到硬规则语义。"""
    if not body_content:
        return body_content

    def replace_heading(match):
        tag = match.group(1).lower()
        raw_label = re.sub(r"<[^>]+>", "", match.group(3)).strip()
        normalized = raw_label.rstrip(":：").strip()

        if normalized in SECTION_SUBHEADINGS:
            return f"<h3>{normalized}</h3>"
        if normalized in TIME_HORIZON_SUBHEADINGS:
            return f'<h3 class="horizon-heading">{normalized}</h3>'
        if normalized in STANDALONE_SUBHEADINGS or normalized in SEMANTIC_CALLOUT_RULES:
            return f"<h4>{normalized}</h4>"
        if tag == "h3" and normalized != raw_label:
            return f"<h3>{normalized}</h3>"
        return match.group(0)

    return re.sub(
        r"<(h[3-4])([^>]*)>(.*?)</\1>",
        replace_heading,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def build_semantic_callout(label: str, content_html: str) -> Optional[str]:
    """按硬规则把特定标签渲染成固定样式的提示框。"""
    css_class = SEMANTIC_CALLOUT_RULES.get(label)
    if not css_class:
        return None

    content = (content_html or "").strip()
    if not content:
        return None

    if not re.match(r"^<(p|ul|ol|table|div|blockquote)\b", content, flags=re.IGNORECASE):
        content = f"<p>{content}</p>"

    return f'<div class="{css_class}"><div class="callout-title">{label}</div>{content}</div>'


def normalize_semantic_callout_blocks(body_content: str) -> str:
    """把独立标签标题 + 紧随内容，收敛成固定样式的提示框。"""
    if not body_content:
        return body_content

    labels_pattern = "|".join(re.escape(label) for label in sorted(SEMANTIC_CALLOUT_RULES, key=len, reverse=True))
    block_pattern = (
        rf"<h4>\s*({labels_pattern})\s*</h4>\s*"
        rf"((?:<p\b[^>]*>.*?</p>|<ul\b[^>]*>.*?</ul>|<ol\b[^>]*>.*?</ol>|<table\b[^>]*>.*?</table>|<div\b[^>]*>.*?</div>))"
    )

    def replace_block(match):
        label = match.group(1).strip()
        content = match.group(2).strip()
        if label in FIXED_DETAIL_LABELS:
            return f"<p><strong>{label}</strong></p>\n{content}"
        return build_semantic_callout(label, content) or match.group(0)

    previous = None
    normalized = body_content
    while previous != normalized:
        previous = normalized
        normalized = re.sub(
            block_pattern,
            replace_block,
            normalized,
            flags=re.IGNORECASE | re.DOTALL,
        )
    return normalized


def normalize_inline_labeled_paragraphs(body_content: str) -> str:
    """规范行内标签段落，减少同类内容一会儿是正文一会儿是提示框。"""
    if not body_content:
        return body_content

    def replace_inline(match):
        raw_label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        label = raw_label.rstrip(":：").strip()
        content = match.group(2).strip()

        if not content:
            return match.group(0)

        if label in FIXED_DETAIL_LABELS:
            return f"<p><strong>{label}</strong></p>\n<p>{content}</p>"

        semantic_callout = build_semantic_callout(label, content)
        if semantic_callout:
            return semantic_callout

        return f'<p class="label-line"><strong>{label}：</strong>{content}</p>'

    return re.sub(
        r"<p>\s*<strong>([^<]{1,40})</strong>\s*[:：]?\s*(.*?)</p>",
        replace_inline,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def save_report(html_content: str, source_emails: Optional[List[Dict]] = None) -> Optional[str]:
    """保存 HTML 报告到文件"""
    if not html_content:
        return None

    # 清理可能的 markdown 代码块
    if html_content.strip().startswith("```html"):
        html_content = html_content.strip()[7:]
    if html_content.strip().startswith("```"):
        html_content = html_content.strip()[3:]
    if html_content.strip().endswith("```"):
        html_content = html_content.strip()[:-3]

    # 验证HTML内容；如果不是完整HTML，先尝试自动包裹
    is_valid, error_msg = validate_html(html_content)
    if not is_valid:
        logger.warning(f"⚠️ HTML验证未通过: {error_msg}，尝试自动包裹为完整HTML")
        html_content = format_html_report(html_content, source_emails=source_emails)
        is_valid, error_msg = validate_html(html_content)
        if not is_valid:
            logger.error(f"❌ HTML验证失败: {error_msg}")
            return None
    else:
        # 格式校准 - 应用参考文件的CSS样式
        html_content = format_html_report(html_content, source_emails=source_emails)

    logger.info("✅ 格式校准完成")

    # 生成文件名：保留带时间戳的工件，避免 daily / supplement / 重跑互相覆盖
    now_bjt = datetime.now(BJT)
    today_str = now_bjt.strftime("%Y%m%d")
    timestamp_str = now_bjt.strftime("%H%M%S")
    report_file = os.path.join(BASE_DIR, f"AI_Morning_Brief_{today_str}_{timestamp_str}.html")

    try:
        with open(report_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        logger.info(f"💾 已保存报告: {report_file} ({len(html_content)} bytes)")
        return report_file
    except Exception as e:
        logger.error(f"❌ 保存报告失败: {e}")
        return None


def check_for_report() -> Optional[str]:
    """检查是否生成了报告文件"""
    today_str = datetime.now(BJT).strftime("%Y%m%d")

    timestamped_reports = sorted(
        glob.glob(os.path.join(BASE_DIR, f"AI_Morning_Brief_{today_str}_*.html")),
        key=os.path.getmtime,
        reverse=True,
    )
    if timestamped_reports:
        return timestamped_reports[0]

    # 兼容旧格式
    report_file = os.path.join(BASE_DIR, f"AI_Morning_Brief_{today_str}.html")
    if os.path.exists(report_file):
        return report_file

    # 检查旧格式（兼容）
    report_file = os.path.join(BASE_DIR, f"{REPORT_PREFIX}{today_str}.html")
    if os.path.exists(report_file):
        return report_file

    return None


def get_report_preview(report_file: str, max_lines: int = 10) -> str:
    """获取报告预览"""
    try:
        with open(report_file, 'r', encoding='utf-8') as f:
            content = f.read()
            # 提取标题
            import re
            titles = re.findall(r'<h[1-3][^>]*>([^<]+)</h[1-3]>', content, re.IGNORECASE)
            if titles:
                return " | ".join(titles[:5])
            return content[:200] + "..."
    except Exception as e:
        return f"读取失败: {e}"


@retry_on_error(max_retries=2, delay=3.0, backoff=2.0)
def send_report(
    report_file: str,
    email_uids: List[str],
    email_local_ids: Optional[List[int]] = None,
    is_supplement: bool = False,
) -> bool:
    """发送报告到指定邮箱 - HTML正文

    Args:
        report_file: 报告文件路径
        email_uids: 本次报告覆盖的邮件 UID 列表（用于记录/幂等）
        email_local_ids: 本次报告覆盖的邮件本地ID列表（可选）
        is_supplement: 是否为补充分析
    """
    config = load_config()
    api_key = config.get("api_key", "")
    target_email = config.get("target", {}).get("email")

    if not target_email:
        logger.error("❌ 未配置目标邮箱")
        return False

    # 读取HTML报告
    with open(report_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # 如果是补充分析，添加说明
    if is_supplement:
        # 在HTML开头添加补充说明
        supplement_note = '''
        <div style="background-color: #fff3cd; border: 1px solid #ffc107; padding: 15px; margin-bottom: 20px; border-radius: 5px;">
            <strong>⚠️ 补充分析通知</strong><br>
            此报告为美股交易时段内的补充分析，可能包含延迟收到的市场信息，请注意时效性。
        </div>
        '''
        html_content = html_content.replace('<body>', '<body>' + supplement_note)

    # 直接使用HTML作为邮件正文
    body_html = html_content

    # 主题添加标识
    subject_prefix = "补充分析 " if is_supplement else ""
    logger.info(f"📤 正在发送报告到 {target_email}...")

    resp = session.post(
        f"{EMAIL_API}/api/send",
        params={"api_key": api_key},
        json={
            "to_email": target_email,
            "subject": f"AI Morning Brief | {subject_prefix}{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}",
            "body": body_html,
            "body_type": "html"
        },
        timeout=60
    )

    result = resp.json()
    if result.get("success"):
        logger.info("✅ 报告发送成功")

        # 原子完成发送记录与 processed 状态更新，避免“已发送但仍 pending”的撕裂状态
        subject = f"AI Morning Brief | {subject_prefix}{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}"
        uids = [uid for uid in (email_uids or []) if uid]
        local_ids = [lid for lid in (email_local_ids or []) if lid is not None]
        if not local_ids and uids:
            local_id_map = email_db.get_local_ids_by_uids(uids)
            local_ids = [local_id_map.get(uid) for uid in uids if local_id_map.get(uid) is not None]
        processed_count = email_db.finalize_report_success(
            email_local_ids=local_ids,
            email_uids=uids,
            report_type="supplement" if is_supplement else "daily",
            subject=subject,
            recipient=target_email,
        )
        logger.info(f"✅ 数据库状态已更新：{processed_count} 封邮件已标记为 processed")

        return True
    else:
        error_msg = result.get('detail', '未知错误')
        logger.error(f"❌ 发送失败: {error_msg}")
        raise Exception(error_msg)


def cleanup():
    """清理临时文件"""
    if os.path.exists(PENDING_FILE):
        os.remove(PENDING_FILE)
        logger.info(f"🗑️ 已清理 {PENDING_FILE}")


# ============ 主程序 ============
def print_status():
    """打印详细状态信息"""
    print("=" * 60)
    print("🔍 状态检查")
    print("=" * 60)

    # 状态文件
    state = load_state()
    print(f"\n📋 执行状态:")
    print(f"   上次处理日期: {state.get('last_processed_date', '从未执行')}")
    print(f"   上次检查时间: {state.get('last_check_time', 'N/A')}")
    if state.get('last_error'):
        print(f"   ⚠️  上次错误: {state.get('last_error')}")

    # 待处理邮件
    print(f"\n📧 待处理邮件:")
    db_status = email_db.get_status()
    print(f"   📊 数据库: 总计 {db_status['total']}, 待处理 {db_status['pending']}, 已处理 {db_status['processed']}, 今日 {db_status['today']}")
    pending_emails = email_db.get_pending_emails(limit=20)
    if pending_emails:
        print(f"   ✅ 当前待处理 {len(pending_emails)} 封（显示最近 {min(len(pending_emails), 20)} 封）")
        sources = {}
        for email in pending_emails:
            from_addr = email.get('from', 'Unknown')
            if '@' in from_addr:
                domain = from_addr.split('@')[1].split('>')[0]
                sources[domain] = sources.get(domain, 0) + 1
        if sources:
            print(f"   📮 来源分布: {', '.join([f'{k}({v})' for k, v in sources.items()])}")
        for email in pending_emails[:5]:
            print(f"   - [{email.get('id')}] {email.get('subject', '(无主题)')} | {email.get('from', 'Unknown')}")
    else:
        print(f"   📭 没有待处理的邮件")

    if os.path.exists(PENDING_FILE):
        print(f"   ℹ️  兼容文件仍存在: {PENDING_FILE}（状态展示已不再依赖它）")

    # 报告文件
    print(f"\n📊 报告文件:")
    report = check_for_report()
    if report:
        file_size = os.path.getsize(report)
        preview = get_report_preview(report)
        print(f"   ✅ 报告已生成")
        print(f"   📁 {report}")
        print(f"   📏 大小: {file_size:,} bytes")
        print(f"   👁️ 预览: {preview}")
    else:
        print(f"   📭 没有生成的报告")

    # 日志文件
    print(f"\n📝 日志:")
    if os.path.exists(LOG_FILE):
        file_size = os.path.getsize(LOG_FILE)
        # 获取最后几行
        with open(LOG_FILE, 'r', encoding='utf-8') as f:
            lines = f.readlines()
            last_lines = lines[-5:] if len(lines) > 5 else lines
        print(f"   ✅ 日志文件存在: {LOG_FILE} ({file_size:,} bytes)")
        print(f"   最近日志:")
        for line in last_lines:
            print(f"      {line.strip()}")
    else:
        print(f"   📭 没有日志文件")

    print()


def main():
    """主程序"""
    print("=" * 60)
    print("🚀 QClaw 邮件自动处理 - Kimi AI 分析版")
    print("=" * 60)
    print(f"当前时间: {datetime.now(BJT).strftime('%Y-%m-%d %H:%M:%S')} (北京时间)")
    print()

    logger.info("程序启动")

    force_mode = "--force" in sys.argv
    check_mode = "--check" in sys.argv
    analyze_mode = "--analyze" in sys.argv
    supplement_mode = "--supplement" in sys.argv

    # 如果使用 --supplement 但没有 --analyze，自动启用 --analyze
    if supplement_mode and not analyze_mode:
        analyze_mode = True

    # 状态检查模式
    if check_mode:
        print_status()
        return

    analysis_lock = try_acquire_analysis_lock()
    if analysis_lock is None:
        logger.warning("⏭️ 已有分析流程运行中，跳过本次触发")
        print("⏭️ 已有分析流程运行中，跳过本次触发")
        return

    try:
        # 分析模式
        if analyze_mode:
            logger.info("📊 分析模式：调用 Kimi 大模型分析已存在的邮件")

            # 从数据库获取待处理邮件
            emails = email_db.get_pending_emails(limit=20)

            if not emails:
                logger.warning("📭 没有待分析的邮件")
                return

            logger.info(f"📧 待分析邮件数: {len(emails)}")

            # 加载格式规范
            format_spec = load_format_spec()
            if not format_spec:
                logger.error("❌ 未找到 HF_Morning_Brief_格式规范.md")
                return

            # 调用 Kimi 分析
            try:
                html_content = analyze_emails_with_kimi(emails, format_spec)
            except Exception as e:
                logger.error(f"❌ Kimi 分析失败: {e}")
                # 更新错误状态
                state = load_state()
                state["last_error"] = f"分析失败: {str(e)[:100]}"
                save_state(state)
                return

            if html_content:
                report_file = save_report(html_content, source_emails=emails)
                if report_file:
                    logger.info("✅ 分析完成！报告已生成")

                    # 发送报告（支持补充模式）
                    logger.info("📤 发送报告...")
                    email_uids = [e.get("id") for e in emails if e.get("id")]
                    email_local_ids = [e.get("local_id") for e in emails if e.get("local_id") is not None]
                    try:
                        send_success = send_report(
                            report_file,
                            email_uids=email_uids,
                            email_local_ids=email_local_ids,
                            is_supplement=supplement_mode,
                        )
                    except Exception as e:
                        logger.error(f"❌ 发送报告失败: {e}")
                        # 记录失败
                        target_email = load_config().get("target", {}).get("email", "")
                        subject_prefix = "补充分析 " if supplement_mode else ""
                        subject = f"AI Morning Brief | {subject_prefix}{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}"
                        try:
                            email_db.log_sent_report(
                                email_local_ids=email_local_ids,
                                email_uids=email_uids,
                                report_type="supplement" if supplement_mode else "daily",
                                subject=subject,
                                recipient=target_email,
                                status="failed",
                            )
                        except Exception:
                            pass
                        return

                    if send_success:
                        logger.info("✅ 邮件已完成发送与状态落库")
                    else:
                        logger.warning("⚠️ 发送失败，邮件保留为待处理状态")

                    if supplement_mode:
                        logger.info("✅ 补充分析完成，已单独推送")
                else:
                    logger.error("❌ 保存报告失败")
            else:
                logger.error("❌ Kimi 分析失败")
            return

        # 正常模式
        if force_mode:
            logger.warning("⚠️ 强制模式（忽略时间检查）")
        elif not should_trigger():
            logger.info("⏰ 今天已经处理过，跳过")
            print("提示: 使用 --force 强制运行，或 --check 检查状态")
            return

        # 第一步：收取邮件
        logger.info("【步骤 1/4】收取邮件...")
        try:
            fetch_emails(limit=20)
        except Exception as e:
            logger.error(f"❌ 收取邮件失败: {e}")
            state = load_state()
            state["last_error"] = f"收取邮件失败: {str(e)[:100]}"
            save_state(state)
            return

        # 从数据库读取待处理邮件（本次分析的唯一来源）
        emails = email_db.get_pending_emails(limit=20)
        if not emails:
            logger.warning("📭 没有待处理的邮件")
            return
        logger.info(f"📭 待处理邮件数: {len(emails)}")

        # 第二步：AI 分析
        logger.info("【步骤 2/4】Kimi AI 分析...")

        format_spec = load_format_spec()
        if not format_spec:
            logger.error("❌ 未找到 HF_Morning_Brief_格式规范.md")
            return

        try:
            html_content = analyze_emails_with_kimi(emails, format_spec)
        except Exception as e:
            logger.error(f"❌ Kimi 分析失败: {e}")
            state = load_state()
            state["last_error"] = f"AI分析失败: {str(e)[:100]}"
            save_state(state)
            return

        if not html_content:
            logger.error("❌ Kimi 分析失败，跳过后续步骤")
            return

        report_file = save_report(html_content, source_emails=emails)
        if not report_file:
            logger.error("❌ 保存报告失败，跳过后续步骤")
            return

        # 第三步：发送报告
        logger.info("【步骤 3/4】发送报告...")
        try:
            email_uids = [e.get("id") for e in emails if e.get("id")]
            email_local_ids = [e.get("local_id") for e in emails if e.get("local_id") is not None]
            send_success = send_report(
                report_file,
                email_uids=email_uids,
                email_local_ids=email_local_ids,
                is_supplement=supplement_mode,
            )
        except Exception as e:
            logger.error(f"❌ 发送报告失败: {e}")

            # 记录发送失败
            config = load_config()
            target_email = config.get("target", {}).get("email", "")
            subject_prefix = "补充分析 " if supplement_mode else ""
            subject = f"AI Morning Brief | {subject_prefix}{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}"
            try:
                email_db.log_sent_report(
                    email_local_ids=email_local_ids,
                    email_uids=email_uids,
                    report_type="supplement" if supplement_mode else "daily",
                    subject=subject,
                    recipient=target_email,
                    status="failed"
                )
            except Exception:
                pass

            state = load_state()
            state["last_error"] = f"发送失败: {str(e)[:100]}"
            save_state(state)
            print("   ⚠️ 发送失败，保留文件待重试")
            return

        if send_success:
            # 成功，更新状态
            state = load_state()
            state["last_processed_date"] = datetime.now(BJT).strftime("%Y-%m-%d")
            state["last_check_time"] = datetime.now(BJT).isoformat()
            state["last_error"] = None
            save_state(state)
            logger.info("✅ 邮件已完成发送与状态落库")
        else:
            # 理论上不会走到这里（send_report 失败会抛异常）；兜底防止未来行为变化
            config = load_config()
            target_email = config.get("target", {}).get("email", "")
            subject_prefix = "补充分析 " if supplement_mode else ""
            subject = f"AI Morning Brief | {subject_prefix}{datetime.now(BJT).strftime('%Y-%m-%d %H:%M')}"
            try:
                email_db.log_sent_report(
                    email_local_ids=email_local_ids,
                    email_uids=email_uids,
                    report_type="supplement" if supplement_mode else "daily",
                    subject=subject,
                    recipient=target_email,
                    status="failed",
                )
            except Exception:
                pass
            state = load_state()
            state["last_error"] = "发送失败"
            save_state(state)
            print("   ⚠️ 发送失败，保留文件待重试")
            return

        # 清理
        cleanup()
        logger.info("✅ 流程完成")
        print("\n✅ 流程完成")
    finally:
        release_analysis_lock(analysis_lock)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        logger.warning("⚠️ 用户中断")
        print("\n⚠️ 已退出")
    except Exception as e:
        logger.error(f"❌ 未处理的异常: {e}")
        logger.error(traceback.format_exc())
        print(f"\n❌ 发生错误: {e}")
        sys.exit(1)
