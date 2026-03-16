#!/usr/bin/env python3
"""
QClaw 邮件自动处理 - 文件交互版

流程：
1. 定时收取邮件 → 保存到 pending_emails.json
2. 调用 Kimi 大模型分析 → 生成 AI_Morning_Brief_YYYYMMDD.html
3. 检测到报告生成 → 发送邮件
4. 清理已处理的邮件

用法:
    python qclaw_mail_file.py           # 正常模式
    python qclaw_mail_file.py --force   # 强制立即执行
    python qclaw_mail_file.py --check   # 检查状态
    python qclaw_mail_file.py --analyze # 仅分析已存在的 pending_emails.json
"""

import os
import sys
import yaml
import json
import time
import pytz
import logging
import requests
import traceback
from datetime import datetime
from typing import List, Dict, Optional
from functools import wraps
from io import BytesIO

# ============ 配置 ============
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "config.yaml")
STATE_FILE = os.path.join(BASE_DIR, ".qclaw_state.json")
PENDING_FILE = os.path.join(BASE_DIR, "pending_emails.json")
REPORT_PREFIX = "report_"
LOG_FILE = os.path.join(BASE_DIR, "qclaw.log")

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

    logger.info("📬 正在从Gmail收取邮件...")

    resp = session.get(
        f"{EMAIL_API}/api/emails",
        params={"api_key": api_key, "limit": limit},
        timeout=120
    )
    data = resp.json()

    if data.get("success"):
        emails = data["emails"]
        logger.info(f"✅ 成功收取 {len(emails)} 封邮件")
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
        "max_tokens": 64000
    }

    resp = session.post(url, json=payload, headers=headers, timeout=300)
    result = resp.json()

    if "choices" in result and len(result["choices"]) > 0:
        return result["choices"][0]["message"]["content"]
    else:
        error_msg = str(result)
        logger.warning(f"⚠️ API {api_config['base_url']} 返回错误: {error_msg}")
        return None


@retry_on_error(max_retries=3, delay=5.0, backoff=2.0)
def analyze_emails_with_kimi(emails: List[Dict], format_spec: str) -> Optional[str]:
    """
    调用 Kimi 大模型分析邮件，生成 HF Morning Brief HTML
    支持主 API 失败时自动切换到备用 API
    """
    kimi_cfg = load_kimi_config()
    api_key = kimi_cfg.get("api_key", "")

    if not api_key:
        logger.error("❌ 未配置 Kimi API Key，请在 config.yaml 中配置 kimi.api_key")
        return None

    # 构建 prompt
    email_count = len(emails)
    emails_summary = []

    for i, email in enumerate(emails, 1):
        subject = email.get("subject", "")
        from_name = email.get("from_name", "")
        from_addr = email.get("from", "")
        date = email.get("date", "")
        body = email.get("body", "")  # 完整内容发送给Kimi

        emails_summary.append(f"""
--- 邮件 {i}/{email_count} ---
发件人: {from_name} <{from_addr}>
时间: {date}
主题: {subject}
正文:
{body}
""")

    emails_text = "\n".join(emails_summary)

    system_prompt = f"""你是一位专业的对冲基金研究分析师，擅长将卖方邮件转化为简洁专业的盘前简报。

## 任务
分析以下{email_count}封卖方邮件，生成一份 HF Morning Brief 风格的 HTML 报告。

## 重要风格要求（必须严格遵循）
1. **简洁精炼**：去掉冗余连接词，bullet point直接陈述事实
2. **阅读时间**：控制在3分钟内
3. **不要大段复制邮件原文**，要提炼关键观点
4. **核心事实和观点严格分离**
5. **按邮件覆盖频率排序**：3/3 > 2/3 > 1/3

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

**注意：排序按邮件覆盖频率，但不要在报告中显示频率数字（如"3/3"、"2/3"）。**"""

    # 尝试主 API
    logger.info(f"🤖 正在调用 Kimi 大模型分析... (主API: {kimi_cfg['base_url']})")
    html_content = call_kimi_api(kimi_cfg, system_prompt, user_prompt)

    # 如果主 API 失败，尝试备用 API
    if not html_content:
        backup_cfg = KIMI_BACKUP_CONFIG
        if backup_cfg.get("api_key"):
            logger.warning(f"⚠️ 主 API 失败，尝试备用 API: {backup_cfg['base_url']} (模型: {backup_cfg['model']})")
            html_content = call_kimi_api(backup_cfg, system_prompt, user_prompt)
            if html_content:
                logger.info("✅ 备用 API 分析完成")
        else:
            logger.error("❌ 主 API 失败，且未配置备用 API")
            raise Exception("Kimi API error: 主 API 和备用 API 均失败")

    if html_content:
        logger.info("✅ Kimi 分析完成")
        return html_content
    else:
        raise Exception("Kimi API error: 未能获取有效响应")


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

    if not reference_css:
        return html_content

    # 提取body内容
    body_match = re.search(r'<body>(.*?)</body>', html_content, re.DOTALL)
    body_content = body_match.group(1) if body_match else html_content

    # 构建标准化HTML
    today_str = datetime.now(BJT).strftime('%Y-%m-%d')

    formatted_html = f'''<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>HF Morning Brief | {today_str}</title>
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

    # 验证HTML内容
    is_valid, error_msg = validate_html(html_content)
    if not is_valid:
        logger.error(f"❌ HTML验证失败: {error_msg}")
        return None

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
def send_report(report_file: str) -> bool:
    """发送报告到指定邮箱 - HTML正文"""
    config = load_config()
    api_key = config.get("api_key", "")
    target_email = config.get("target", {}).get("email")

    if not target_email:
        logger.error("❌ 未配置目标邮箱")
        return False

    # 读取HTML报告
    with open(report_file, 'r', encoding='utf-8') as f:
        html_content = f.read()

    # 直接使用HTML作为邮件正文
    body_html = html_content

    logger.info(f"📤 正在发送报告到 {target_email}...")

    resp = session.post(
        f"{EMAIL_API}/api/send",
        json={
            "api_key": api_key,
            "to_email": target_email,
            "subject": f"AI Morning Brief | {datetime.now(BJT).strftime('%Y-%m-%d')}",
            "body": body_html,
            "body_type": "html"
        },
        timeout=60
    )

    result = resp.json()
    if result.get("success"):
        logger.info("✅ 报告发送成功")
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
    if os.path.exists(PENDING_FILE):
        with open(PENDING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            count = data.get('count', 0)
            timestamp = data.get('timestamp', 'N/A')
            print(f"   ✅ 存在 {count} 封邮件")
            print(f"   📅 收取时间: {timestamp}")

            # 显示邮件来源
            emails = data.get('emails', [])
            sources = {}
            for email in emails:
                from_addr = email.get('from', 'Unknown')
                # 提取域名
                if '@' in from_addr:
                    domain = from_addr.split('@')[1].split('>')[0]
                    sources[domain] = sources.get(domain, 0) + 1

            if sources:
                print(f"   📮 来源分布: {', '.join([f'{k}({v})' for k, v in sources.items()])}")
    else:
        print(f"   📭 没有待处理的邮件")

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

    # 状态检查模式
    if check_mode:
        print_status()
        return

    # 分析模式
    if analyze_mode:
        logger.info("📊 分析模式：调用 Kimi 大模型分析已存在的邮件")

        if not os.path.exists(PENDING_FILE):
            logger.error("❌ 没有找到 pending_emails.json，请先运行正常模式收取邮件")
            return

        with open(PENDING_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            emails = data.get("emails", [])

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
        emails = fetch_emails(limit=20)
    except Exception as e:
        logger.error(f"❌ 收取邮件失败: {e}")
        state = load_state()
        state["last_error"] = f"收取邮件失败: {str(e)[:100]}"
        save_state(state)
        return

    if not emails:
        logger.warning("📭 没有新邮件")
        if not os.path.exists(PENDING_FILE):
            return
        logger.info("发现之前的待处理邮件，继续处理...")
    else:
        save_pending_emails(emails)

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
        send_report(report_file)
    except Exception as e:
        logger.error(f"❌ 发送报告失败: {e}")
        state = load_state()
        state["last_error"] = f"发送失败: {str(e)[:100]}"
        save_state(state)
        print("   ⚠️ 发送失败，保留文件待重试")
        return

    # 成功，更新状态
    state = load_state()
    state["last_processed_date"] = datetime.now(BJT).strftime("%Y-%m-%d")
    state["last_check_time"] = datetime.now(BJT).isoformat()
    state["last_error"] = None
    save_state(state)

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
