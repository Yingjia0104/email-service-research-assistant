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
import pytz
import re
import logging
import requests
import traceback
from html import unescape
from datetime import datetime
from typing import List, Dict, Optional
from functools import wraps
from io import BytesIO

# ============ 配置 ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")
STATE_FILE = os.path.join(BASE_DIR, ".qclaw_state.json")
REPORT_PREFIX = "report_"
LOG_FILE = os.path.join(BASE_DIR, "qclaw.log")
PENDING_FILE = os.path.join(BASE_DIR, "pending_emails.json")  # 兼容旧的文件交互流程

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
    "model": "moonshot-v1-128k"
}

# 备用 API 配置（当前API余额不足时使用）
KIMI_BACKUP_CONFIG = {
    "api_key": "",
    "base_url": "https://api.moonshot.ai/v1",
    "model": "kimi-k2.5"
}

MAX_EMAIL_BODY_CHARS = 12000
MAX_PROMPT_BODY_CHARS = 40000
MAX_COMPLETION_TOKENS = 12000
BATCH_SPLIT_TRIGGER_CHARS = 26000
MIN_TRUNCATION_CONTENT_CHARS = 40

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
    "短期（1-5天）",
    "中期（1-4周）",
    "长期（1-3月）",
    "Catalysts to Watch",
}

INLINE_ACTION_LABELS = {
    "投资启示",
    "投资影响",
    "为什么重要",
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
    KIMI_CONFIG["model"] = kimi_cfg.get("model", "moonshot-v1-128k")

    # 加载备用 API 配置
    backup_cfg = config.get("kimi_backup", {})
    KIMI_BACKUP_CONFIG["api_key"] = backup_cfg.get("api_key", "")
    KIMI_BACKUP_CONFIG["base_url"] = backup_cfg.get("base_url", "https://api.moonshot.ai/v1")
    KIMI_BACKUP_CONFIG["model"] = backup_cfg.get("model", "kimi-k2.5")

    return KIMI_CONFIG


def load_format_spec():
    """加载 HF Morning Brief 格式规范"""
    format_spec_file = os.path.join(BASE_DIR, "HF_Morning_Brief_格式规范.md")
    if os.path.exists(format_spec_file):
        with open(format_spec_file, 'r', encoding='utf-8') as f:
            return f.read()
    return ""


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
        "[图片附件已省略：原始图片数据未直接送入模型]",
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


def generate_with_kimi(system_prompt: str, user_prompt: str) -> str:
    """统一封装主/备模型的短重试与切换逻辑。"""
    kimi_cfg = load_kimi_config()
    api_key = kimi_cfg.get("api_key", "")

    if not api_key:
        logger.error("❌ 未配置 Kimi API Key，请在 config.yaml 中配置 kimi.api_key")
        raise Exception("missing kimi api key")

    result = call_kimi_api_with_retries(
        kimi_cfg,
        system_prompt,
        user_prompt,
        label="主API",
        max_retries=1,
        delay=5.0,
        backoff=2.0,
    )

    if result:
        return result

    backup_cfg = KIMI_BACKUP_CONFIG
    if backup_cfg.get("api_key"):
        logger.warning(f"⚠️ 主 API 不可用，切换备用 API: {backup_cfg['base_url']} (模型: {backup_cfg['model']})")
        result = call_kimi_api_with_retries(
            backup_cfg,
            system_prompt,
            user_prompt,
            label="备用API",
            max_retries=1,
            delay=3.0,
            backoff=2.0,
        )
        if result:
            logger.info("✅ 备用 API 分析完成")
            return result

    logger.error("❌ 主 API 失败，且未配置备用 API")
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


def parse_batch_summary_json(text: str) -> Dict:
    """解析子批次结构化摘要，失败时直接抛错让上层重试/切换。"""
    payload = json.loads(extract_json_block(text))
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


def analyze_batch_summary_with_kimi(batch_emails: List[Dict], total_email_count: int, batch_index: int, batch_total: int) -> Dict:
    emails_text = build_emails_text(batch_emails, total_email_count, total_body_budget=MAX_PROMPT_BODY_CHARS // 2)
    batch_email_ids = ", ".join(str(email.get("_analysis_index")) for email in batch_emails)

    system_prompt = f"""你是一位卖方邮件研究助理。你当前的任务不是直接写最终晨报，而是先把一个子批次邮件压缩成便于二次合并的结构化 JSON 摘要。

## 输出规则
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

## 注意
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

    raw = generate_with_kimi(system_prompt, user_prompt)
    parsed = parse_batch_summary_json(raw)
    parsed["batch_index"] = batch_index
    parsed["batch_total"] = batch_total
    return parsed


def merge_batch_summaries_with_kimi(batch_summaries: List[Dict], format_spec: str, total_email_count: int) -> str:
    summaries_text = json.dumps(batch_summaries, ensure_ascii=False, indent=2)

    system_prompt = f"""你是一位专业的对冲基金研究分析师，擅长把多个子批次摘要合并成一份 HF Morning Brief 风格的 HTML 报告。

## 任务
你会收到若干份子批次摘要，这些摘要来自同一天的同一组 {total_email_count} 封卖方邮件。请完成以下工作：
1. 合并表达不同但实质相同的主题
2. 按合并后的覆盖邮件数进行排序
3. 如果主题出现在多个批次中，合并其覆盖邮件数和观点
4. 最终报告中不要显示覆盖数字，但排序必须体现覆盖频率
5. 合并时必须保留观点归因，不能把外部引述、媒体消息或市场传闻改写成券商自身判断

## 重要风格要求（必须严格遵循）
1. 简洁精炼，控制在3分钟内读完
2. 核心事实和观点严格分离
3. 不要大段复制批次摘要原文
4. 低频但重要的信号放到 Local News 或 Actionable Ideas

## 归因规则（非常重要）
1. “发件机构”与“观点主体”必须分开判断
2. 如果子批次摘要里写明 `观点主体: Shawn Kim`、`信息类型: 外部引述`，最终报告必须保留这种归因，不能改写成 `MS认为`
3. 只有客观、可验证、非判断性的内容才能进入“核心事实”
4. 带 `认为 / 预计 / 可能 / says / suggests / reportedly / rumor` 的内容，除非有独立客观佐证，否则归入“观点”或“市场含义”，并保留主语
5. 如果主语不明确，宁可写成“邮件转述市场观点”或“市场传闻称”，也不要强行归给券商机构

## HTML结构指引（本地会应用标准CSS样式）
- 使用 <h1> 作为主标题
- 使用 <h2> 作为章节标题
- 使用 <h3> 作为事件标题
- 使用 <table> 呈现多观点对比
- 使用 .highlight 类标记重点
- 使用 .divider 分割章节

## 格式规范（必须严格遵循）
{format_spec}

## 输出要求
1. 必须使用简体中文输出
2. 只生成 HTML 内容
3. 排序按合并后的覆盖频率，但不要显示数字
"""

    user_prompt = f"""请将以下结构化子批次摘要合并成最终中文 HTML 晨报。

{summaries_text}

请特别检查每个主题：
- 核心事实里是否混入了观点判断
- 观点主语是否被误写成发件机构
- 外部引述是否被错误升级为券商判断
"""

    return generate_with_kimi(system_prompt, user_prompt)




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

def call_kimi_api(api_config: dict, system_prompt: str, user_prompt: str) -> Optional[str]:
    """
    调用 Kimi API，返回 HTML 内容或 None
    """
    url = f"{api_config['base_url']}/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_config['api_key']}"
    }

    payload = {
        "model": api_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
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
) -> Optional[str]:
    """对单个模型做有限重试，失败后交由上层切换备用模型。"""
    current_delay = delay
    last_error = None

    for attempt in range(max_retries + 1):
        try:
            logger.info(f"🤖 正在调用 Kimi 大模型分析... ({label}: {api_config['base_url']})")
            html_content = call_kimi_api(api_config, system_prompt, user_prompt)
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

    if len(email_batches) == 1:
        emails_text = build_emails_text(email_batches[0], email_count, total_body_budget=MAX_PROMPT_BODY_CHARS)
        system_prompt = f"""你是一位专业的对冲基金研究分析师，擅长将卖方邮件转化为简洁专业的盘前简报。

## 重要风格要求（必须严格遵循）
1. **简洁精炼**：去掉冗余连接词，bullet point直接陈述事实
2. **阅读时间**：控制在3分钟内
3. **不要大段复制邮件原文**，要提炼关键观点
4. **核心事实和观点严格分离**
5. **按邮件覆盖频率排序**：3/3 > 2/3 > 1/3

## 归因规则（非常重要）
1. 发件人/券商机构不等于正文里每一句话的观点主体
2. 如果正文出现 `X says`、`according to X`、`reports suggest`、`management said`、`媒体称`、`市场传闻` 等表述，必须识别真实主语并保留归因
3. 带有 `认为 / 预计 / 可能 / suggests / reportedly / rumor` 的内容默认属于观点、判断或传闻，不应直接写进“核心事实”
4. 只有客观、可验证、非判断性的内容才能写进“核心事实”
5. 如果原文是 `Shawn Kim says ...`，应写成 `Shawn Kim 认为...` 或 `邮件转述 Shawn Kim 的观点...`，不能改写成 `MS认为...`，除非原文明确写的是 Morgan Stanley 的 house view

## HTML结构指引（本地会应用标准CSS样式）
- 使用 <h1> 作为主标题
- 使用 <h2> 作为章节标题（如 Executive Summary, Key Coverage 等）
- 使用 <h3> 作为事件标题
- 使用 <table> 呈现多观点对比
- 使用 .highlight 类标记重点
- 使用 .divider 分割章节

## 格式规范（必须严格遵循）
{format_spec}

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

## 输出要求
1. **语言：必须使用简体中文（中文），包括所有标题、正文、术语**
2. 文件名格式: AI_Morning_Brief_{{日期}}.html
3. 必须严格按照格式规范生成 HTML
4. 排序必须按邮件覆盖频率（3/3 > 2/3 > 1/3），但**不要在报告中显示频率数字**
5. 核心事实和观点必须严格分离
6. 只生成 HTML 内容，不要 markdown 格式
"""

        user_prompt = f"""请分析以下邮件，生成 HF Morning Brief HTML 报告。

**重要：请使用简体中文（中文）输出所有内容，包括标题、正文、观点和术语。**

邮件内容：
{emails_text}

请严格按照格式规范生成中文 HTML 报告。

**注意：排序按邮件覆盖频率，但不要在报告中显示频率数字（如"3/3"、"2/3"）。**
**额外注意：不要把第三方被引述的观点错误写成发件机构观点；不要把观点判断错误写进核心事实。**"""

        html_content = generate_with_kimi(system_prompt, user_prompt)
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

    html_content = merge_batch_summaries_with_kimi(batch_summaries, format_spec, total_email_count=email_count)
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


def format_html_report(html_content: str) -> str:
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
    body_content = normalize_subsection_headings(body_content)
    body_content = normalize_standalone_labels(body_content)
    body_content = normalize_inline_labeled_paragraphs(body_content)

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


def normalize_standalone_labels(body_content: str) -> str:
    """把常见的独立粗体标签提升成稳定的小节标题。"""
    if not body_content:
        return body_content

    def replace_label(match):
        raw_label = re.sub(r"<[^>]+>", "", match.group(1)).strip()
        normalized = raw_label.rstrip(":：").strip()
        if normalized in STANDALONE_SUBHEADINGS:
            return f"<h4>{normalized}</h4>"
        return match.group(0)

    return re.sub(
        r"<p>\s*<strong>(.*?)</strong>\s*</p>",
        replace_label,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


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

        if label in INLINE_ACTION_LABELS:
            return f'<div class="action-box"><strong>{label}：</strong>{content}</div>'

        return f'<p class="label-line"><strong>{label}：</strong>{content}</p>'

    return re.sub(
        r"<p>\s*<strong>([^<]{1,40})</strong>\s*[:：]?\s*(.*?)</p>",
        replace_inline,
        body_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


def save_report(html_content: str) -> Optional[str]:
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
        html_content = format_html_report(html_content)
        is_valid, error_msg = validate_html(html_content)
        if not is_valid:
            logger.error(f"❌ HTML验证失败: {error_msg}")
            return None
    else:
        # 格式校准 - 应用参考文件的CSS样式
        html_content = format_html_report(html_content)

    logger.info("✅ 格式校准完成")

    # 生成文件名
    today_str = datetime.now(BJT).strftime("%Y%m%d")
    report_file = os.path.join(BASE_DIR, f"AI_Morning_Brief_{today_str}.html")

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

    # 检查新格式
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
            report_file = save_report(html_content)
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

    report_file = save_report(html_content)
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
        except:
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
