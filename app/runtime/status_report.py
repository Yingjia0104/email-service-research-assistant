from __future__ import annotations

import os
from typing import Any, Callable, Dict, List


def build_status_report(
    *,
    load_state_fn,
    email_db_module,
    check_for_report_fn,
    get_report_preview_fn,
    log_file: str,
) -> str:
    lines: List[str] = []
    lines.append("=" * 60)
    lines.append("🔍 状态检查")
    lines.append("=" * 60)

    state = load_state_fn()
    lines.append("")
    lines.append("📋 执行状态:")
    lines.append(f"   上次处理日期: {state.get('last_processed_date', '从未执行')}")
    lines.append(f"   上次检查时间: {state.get('last_check_time', 'N/A')}")
    if state.get("last_error"):
        lines.append(f"   ⚠️  上次错误: {state.get('last_error')}")

    lines.append("")
    lines.append("📧 待处理邮件:")
    db_status = email_db_module.get_status()
    lines.append(
        f"   📊 数据库: 总计 {db_status['total']}, 待处理 {db_status['pending']}, 已处理 {db_status['processed']}, 今日 {db_status['today']}"
    )
    pending_emails = email_db_module.get_pending_emails(limit=20)
    if pending_emails:
        lines.append(f"   ✅ 当前待处理 {len(pending_emails)} 封（显示最近 {min(len(pending_emails), 20)} 封）")
        sources: Dict[str, int] = {}
        for email in pending_emails:
            from_addr = email.get("from", "Unknown")
            if "@" in from_addr:
                domain = from_addr.split("@")[1].split(">")[0]
                sources[domain] = sources.get(domain, 0) + 1
        if sources:
            lines.append(f"   📮 来源分布: {', '.join([f'{k}({v})' for k, v in sources.items()])}")
        for email in pending_emails[:5]:
            lines.append(f"   - [{email.get('id')}] {email.get('subject', '(无主题)')} | {email.get('from', 'Unknown')}")
    else:
        lines.append("   📭 没有待处理的邮件")

    lines.append("")
    lines.append("📊 报告文件:")
    report = check_for_report_fn()
    if report:
        file_size = os.path.getsize(report)
        preview = get_report_preview_fn(report)
        lines.append("   ✅ 报告已生成")
        lines.append(f"   📁 {report}")
        lines.append(f"   📏 大小: {file_size:,} bytes")
        lines.append(f"   👁️ 预览: {preview}")
    else:
        lines.append("   📭 没有生成的报告")

    lines.append("")
    lines.append("📝 日志:")
    if os.path.exists(log_file):
        file_size = os.path.getsize(log_file)
        with open(log_file, "r", encoding="utf-8") as handle:
            lines_in_file = handle.readlines()
            last_lines = lines_in_file[-5:] if len(lines_in_file) > 5 else lines_in_file
        lines.append(f"   ✅ 日志文件存在: {log_file} ({file_size:,} bytes)")
        lines.append("   最近日志:")
        for line in last_lines:
            lines.append(f"      {line.strip()}")
    else:
        lines.append("   📭 没有日志文件")

    lines.append("")
    return "\n".join(lines)
