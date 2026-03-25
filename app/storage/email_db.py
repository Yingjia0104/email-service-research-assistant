"""
邮件数据库模块 - SQLite
"""

import sqlite3
import os
import json
from datetime import datetime, timedelta
import pytz

BJT = pytz.timezone('Asia/Shanghai')

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_FILE = os.path.join(PROJECT_ROOT, "emails.db")


def get_db_path():
    """获取数据库路径"""
    return DB_FILE


def _connect():
    """创建数据库连接。"""
    return sqlite3.connect(DB_FILE, timeout=30)


def _column_names(cursor, table_name: str) -> set:
    """获取表字段名集合。"""
    cursor.execute(f"PRAGMA table_info({table_name})")
    return {row[1] for row in cursor.fetchall()}


def _migrate_image_analysis_results_schema(cursor) -> None:
    """将 image_analysis_results 迁移到当前精简字段结构。"""
    columns = _column_names(cursor, "image_analysis_results")
    expected_columns = {
        "id",
        "email_local_id",
        "image_key",
        "core_signal",
        "supporting_details",
        "created_at",
        "updated_at",
    }
    if columns == expected_columns:
        return

    cursor.execute(
        """
        CREATE TABLE image_analysis_results__new (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_local_id INTEGER NOT NULL,
            image_key TEXT NOT NULL,
            core_signal TEXT,
            supporting_details TEXT,
            created_at TEXT,
            updated_at TEXT
        )
        """
    )
    cursor.execute(
        """
        INSERT INTO image_analysis_results__new (
            id, email_local_id, image_key, core_signal,
            supporting_details, created_at, updated_at
        )
        SELECT
            {id_expr},
            {email_local_id_expr},
            {image_key_expr},
            {core_signal_expr},
            {supporting_details_expr},
            {created_at_expr},
            {updated_at_expr}
        FROM image_analysis_results
        """.format(
            id_expr="id" if "id" in columns else "NULL",
            email_local_id_expr="email_local_id" if "email_local_id" in columns else "NULL",
            image_key_expr="image_key" if "image_key" in columns else "''",
            core_signal_expr="core_signal" if "core_signal" in columns else "NULL",
            supporting_details_expr="supporting_details" if "supporting_details" in columns else "'[]'",
            created_at_expr="created_at" if "created_at" in columns else "NULL",
            updated_at_expr="updated_at" if "updated_at" in columns else "NULL",
        )
    )
    cursor.execute("DROP TABLE image_analysis_results")
    cursor.execute("ALTER TABLE image_analysis_results__new RENAME TO image_analysis_results")


def init_db():
    """初始化数据库"""
    conn = _connect()
    cursor = conn.cursor()

    # 创建邮件表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS emails (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            account_email TEXT NOT NULL DEFAULT '',
            folder TEXT NOT NULL DEFAULT 'INBOX',
            uid TEXT NOT NULL,
            email_from TEXT,
            from_name TEXT,
            to_addr TEXT,
            subject TEXT,
            date TEXT,
            body TEXT,
            attachments TEXT,
            status TEXT DEFAULT 'pending',  -- pending, processed
            created_at TEXT,
            processed_at TEXT
        )
    """)

    email_columns = _column_names(cursor, "emails")
    if "account_email" not in email_columns:
        cursor.execute("ALTER TABLE emails ADD COLUMN account_email TEXT NOT NULL DEFAULT ''")
    if "folder" not in email_columns:
        cursor.execute("ALTER TABLE emails ADD COLUMN folder TEXT NOT NULL DEFAULT 'INBOX'")
    cursor.execute("UPDATE emails SET account_email = '' WHERE account_email IS NULL")
    cursor.execute("UPDATE emails SET folder = 'INBOX' WHERE folder IS NULL OR folder = ''")

    # 创建索引
    cursor.execute("DROP INDEX IF EXISTS idx_uid")
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_scope_uid ON emails(account_email, folder, uid)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_status ON emails(status)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_date ON emails(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_created_at ON emails(created_at)")

    # 创建发送记录表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sent_reports (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_local_ids TEXT,       -- 发送的邮件本地ID列表（JSON）
            email_uids TEXT,           -- 发送的邮件服务器UID列表（JSON）
            report_type TEXT,          -- 报告类型: daily / supplement
            subject TEXT,               -- 邮件主题
            recipient TEXT,            -- 收件人
            sent_at TEXT,              -- 发送时间
            status TEXT DEFAULT 'success'  -- 发送状态: success / failed
        )
    """)

    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sent_at ON sent_reports(sent_at)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sent_status_type ON sent_reports(status, report_type, sent_at)")

    cursor.execute(
        """
        CREATE TABLE IF NOT EXISTS runtime_state (
            state_key TEXT PRIMARY KEY,
            state_value TEXT,
            updated_at TEXT
        )
        """
    )
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_runtime_state_updated_at ON runtime_state(updated_at)")

    # 创建图片处理链路表
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_local_id INTEGER NOT NULL,
            image_key TEXT NOT NULL,
            kind TEXT,
            source_location TEXT,
            inline_index INTEGER,
            filename TEXT,
            content_type TEXT,
            size INTEGER DEFAULT 0,
            sha256 TEXT,
            prescreen_status TEXT DEFAULT 'pending',
            prescreen_reasons TEXT,
            image_type TEXT,
            role_in_email TEXT,
            analysis_status TEXT DEFAULT 'pending',
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_images_scope_key ON email_images(email_local_id, image_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_images_local_id ON email_images(email_local_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_images_analysis_status ON email_images(analysis_status)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS image_analysis_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_local_id INTEGER NOT NULL,
            image_key TEXT NOT NULL,
            core_signal TEXT,
            supporting_details TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    _migrate_image_analysis_results_schema(cursor)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_image_analysis_scope_key ON image_analysis_results(email_local_id, image_key)")

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS email_visual_contexts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email_local_id INTEGER NOT NULL,
            visual_status TEXT DEFAULT 'empty',
            inline_visual_contexts TEXT,
            supporting_visual_evidence TEXT,
            enriched_body TEXT,
            created_at TEXT,
            updated_at TEXT
        )
    """)
    cursor.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_email_visual_context_local_id ON email_visual_contexts(email_local_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_email_visual_context_status ON email_visual_contexts(visual_status)")
    cursor.execute(
        """
        UPDATE email_visual_contexts
        SET visual_status = 'empty'
        WHERE visual_status IS NULL OR visual_status = ''
        """
    )
    cursor.execute(
        """
        UPDATE email_visual_contexts
        SET visual_status = CASE
            WHEN COALESCE(NULLIF(TRIM(inline_visual_contexts), ''), '[]') != '[]'
              OR COALESCE(NULLIF(TRIM(supporting_visual_evidence), ''), '[]') != '[]'
            THEN 'ready'
            ELSE 'empty'
        END
        WHERE LOWER(COALESCE(visual_status, '')) = 'partial'
        """
    )

    conn.commit()
    conn.close()


def add_emails(emails: list):
    """批量添加邮件（去重）"""
    if not emails:
        return 0

    conn = _connect()
    cursor = conn.cursor()

    count = 0
    for email in emails:
        uid = email.get("id")
        if not uid:
            continue

        cursor.execute("""
            INSERT OR IGNORE INTO emails (
                account_email, folder, uid, email_from, from_name, to_addr, subject, date, body, attachments, status, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?)
        """, (
            (email.get("account_email") or "").strip().lower(),
            (email.get("folder") or "INBOX").strip() or "INBOX",
            uid,
            email.get("from"),
            email.get("from_name"),
            email.get("to"),
            email.get("subject"),
            email.get("date"),
            email.get("body"),
            email.get("attachments"),
            datetime.now(BJT).isoformat()
        ))
        count += cursor.rowcount

    conn.commit()
    conn.close()
    return count


def get_pending_emails(limit: int = 20) -> list:
    """获取待处理的邮件"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT id, account_email, folder, uid, email_from, from_name, to_addr, subject, date, body, attachments
        FROM emails
        WHERE status = 'pending'
        ORDER BY COALESCE(date, created_at) DESC, id DESC
        LIMIT ?
    """, (limit,))

    emails = []
    for row in cursor.fetchall():
        emails.append({
            "local_id": row["id"],   # 本地自增ID
            "account_email": row["account_email"],
            "folder": row["folder"],
            "id": row["uid"],         # 邮箱服务器UID
            "from": row["email_from"],
            "from_name": row["from_name"],
            "to": row["to_addr"],
            "subject": row["subject"],
            "date": row["date"],
            "body": row["body"],
            "attachments": row["attachments"]
        })

    conn.close()
    return emails


def upsert_email_images(email_local_id: int, image_records: list) -> int:
    from . import image_store

    return image_store.upsert_email_images(email_local_id, image_records)


def upsert_email_images_batch(records_by_local_id: dict[int, list]) -> int:
    from . import image_store

    return image_store.upsert_email_images_batch(records_by_local_id)


def update_image_classifications(email_local_id: int, image_classifications: dict) -> int:
    from . import image_store

    return image_store.update_image_classifications(email_local_id, image_classifications)


def update_image_classifications_batch(classifications_by_local_id: dict[int, dict]) -> int:
    from . import image_store

    return image_store.update_image_classifications_batch(classifications_by_local_id)


def upsert_image_analysis_results(email_local_id: int, analysis_results: dict) -> int:
    from . import image_store

    return image_store.upsert_image_analysis_results(email_local_id, analysis_results)


def upsert_image_analysis_results_batch(results_by_local_id: dict[int, dict]) -> int:
    from . import image_store

    return image_store.upsert_image_analysis_results_batch(results_by_local_id)


def save_email_visual_context(
    email_local_id: int,
    *,
    visual_status: str,
    inline_visual_contexts: list,
    supporting_visual_evidence: list,
    enriched_body: str,
) -> None:
    from . import image_store

    image_store.save_email_visual_context(
        email_local_id,
        visual_status=visual_status,
        inline_visual_contexts=inline_visual_contexts,
        supporting_visual_evidence=supporting_visual_evidence,
        enriched_body=enriched_body,
    )


def save_email_visual_contexts_batch(contexts_by_local_id: dict[int, dict]) -> int:
    from . import image_store

    return image_store.save_email_visual_contexts_batch(contexts_by_local_id)


def get_email_visual_context(email_local_id: int) -> dict:
    from . import image_store

    return image_store.get_email_visual_context(email_local_id)


def get_email_visual_contexts(email_local_ids: list[int]) -> dict[int, dict]:
    from . import image_store

    return image_store.get_email_visual_contexts(email_local_ids)


def get_email_image_analysis_records(email_local_id: int) -> list:
    from . import image_store

    return image_store.get_email_image_analysis_records(email_local_id)


def get_email_image_analysis_records_map(email_local_ids: list[int]) -> dict[int, list]:
    from . import image_store

    return image_store.get_email_image_analysis_records_map(email_local_ids)


def normalize_email_image_keys(email_local_id: int) -> int:
    from . import image_store

    return image_store.normalize_email_image_keys(email_local_id)


def mark_processed(uids: list):
    """标记邮件为已处理"""
    if not uids:
        return

    conn = _connect()
    cursor = conn.cursor()

    placeholders = ",".join(["?"] * len(uids))
    cursor.execute(
        f"""
        UPDATE emails
        SET status = 'processed', processed_at = ?
        WHERE uid IN ({placeholders})
        """,
        (datetime.now(BJT).isoformat(), *uids),
    )

    conn.commit()
    conn.close()


def mark_processed_scoped(uids: list, account_email: str = None, folder: str = None):
    """按 UID + 可选邮箱作用域标记邮件为已处理。"""
    if not uids:
        return

    conn = _connect()
    cursor = conn.cursor()

    placeholders = ",".join(["?"] * len(uids))
    query = f"""
        UPDATE emails
        SET status = 'processed', processed_at = ?
        WHERE uid IN ({placeholders})
    """
    params = [datetime.now(BJT).isoformat(), *uids]

    if account_email is not None:
        query += " AND account_email = ?"
        params.append(account_email.strip().lower())
    if folder is not None:
        query += " AND folder = ?"
        params.append((folder or "INBOX").strip() or "INBOX")

    cursor.execute(query, tuple(params))
    conn.commit()
    conn.close()


def mark_processed_by_local_ids(local_ids: list):
    """按本地 ID 标记邮件为已处理。"""
    local_ids = [local_id for local_id in (local_ids or []) if local_id is not None]
    if not local_ids:
        return

    conn = _connect()
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(local_ids))
    cursor.execute(
        f"""
        UPDATE emails
        SET status = 'processed', processed_at = ?
        WHERE id IN ({placeholders})
        """,
        (datetime.now(BJT).isoformat(), *local_ids),
    )

    conn.commit()
    conn.close()


def get_local_ids_by_uids(uids: list, account_email: str = None, folder: str = None) -> dict:
    """根据 UID 列表获取本地自增 ID 映射"""
    if not uids:
        return {}

    conn = _connect()
    cursor = conn.cursor()

    placeholders = ",".join(["?"] * len(uids))
    query = f"SELECT id, uid FROM emails WHERE uid IN ({placeholders})"
    params = list(uids)
    if account_email is not None:
        query += " AND account_email = ?"
        params.append(account_email.strip().lower())
    if folder is not None:
        query += " AND folder = ?"
        params.append((folder or "INBOX").strip() or "INBOX")
    cursor.execute(query, tuple(params))

    mapping = {row[1]: row[0] for row in cursor.fetchall() if row[1] is not None}
    conn.close()
    return mapping


def get_today_processed_uids() -> set:
    """获取今天已处理的邮件UID"""
    conn = _connect()
    cursor = conn.cursor()
    today_str = datetime.now(BJT).strftime("%Y-%m-%d")

    cursor.execute("""
        SELECT uid FROM emails
        WHERE status = 'processed'
        AND substr(processed_at, 1, 10) = ?
    """, (today_str,))

    uids = {row[0] for row in cursor.fetchall() if row[0]}
    conn.close()
    return uids


def get_today_processed_uids_scoped(account_email: str = None, folder: str = None) -> set:
    """获取今天已处理的邮件 UID，可按邮箱作用域过滤。"""
    conn = _connect()
    cursor = conn.cursor()
    today_str = datetime.now(BJT).strftime("%Y-%m-%d")

    query = """
        SELECT uid FROM emails
        WHERE status = 'processed'
        AND substr(processed_at, 1, 10) = ?
    """
    params = [today_str]
    if account_email is not None:
        query += " AND account_email = ?"
        params.append(account_email.strip().lower())
    if folder is not None:
        query += " AND folder = ?"
        params.append((folder or "INBOX").strip() or "INBOX")

    cursor.execute(query, tuple(params))
    uids = {row[0] for row in cursor.fetchall() if row[0]}
    conn.close()
    return uids


def get_status():
    """获取状态统计"""
    conn = _connect()
    cursor = conn.cursor()
    today_str = datetime.now(BJT).strftime("%Y-%m-%d")

    cursor.execute("SELECT status, COUNT(*) FROM emails GROUP BY status")
    stats = dict(cursor.fetchall())

    cursor.execute("SELECT COUNT(*) FROM emails WHERE substr(created_at, 1, 10) = ?", (today_str,))
    today_count = cursor.fetchone()[0]

    conn.close()

    return {
        "total": sum(stats.values()),
        "pending": stats.get("pending", 0),
        "processed": stats.get("processed", 0),
        "today": today_count
    }


def log_sent_report(email_local_ids: list, email_uids: list, report_type: str, subject: str, recipient: str, status: str = "success"):
    """记录发送报告

    Args:
        email_local_ids: 邮件本地ID列表
        email_uids: 邮件服务器UID列表
        report_type: 报告类型
        subject: 邮件主题
        recipient: 收件人
        status: 发送状态
    """
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO sent_reports (email_local_ids, email_uids, report_type, subject, recipient, sent_at, status)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        json.dumps(email_local_ids),
        json.dumps(email_uids),
        report_type,
        subject,
        recipient,
        datetime.now(BJT).isoformat(),
        status
    ))

    conn.commit()
    conn.close()


def finalize_report_success(
    email_local_ids: list,
    email_uids: list,
    report_type: str,
    subject: str,
    recipient: str,
    account_email: str = None,
    folder: str = None,
) -> int:
    """在同一事务内记录发送成功并标记邮件为已处理。"""
    conn = _connect()
    cursor = conn.cursor()

    normalized_local_ids = [local_id for local_id in (email_local_ids or []) if local_id is not None]
    normalized_uids = [uid for uid in (email_uids or []) if uid]
    timestamp = datetime.now(BJT).isoformat()

    cursor.execute("""
        INSERT INTO sent_reports (email_local_ids, email_uids, report_type, subject, recipient, sent_at, status)
        VALUES (?, ?, ?, ?, ?, ?, 'success')
    """, (
        json.dumps(normalized_local_ids),
        json.dumps(normalized_uids),
        report_type,
        subject,
        recipient,
        timestamp,
    ))

    processed_count = 0
    if normalized_local_ids:
        placeholders = ",".join(["?"] * len(normalized_local_ids))
        cursor.execute(
            f"""
            UPDATE emails
            SET status = 'processed', processed_at = ?
            WHERE id IN ({placeholders})
            """,
            (timestamp, *normalized_local_ids),
        )
        processed_count = cursor.rowcount
    elif normalized_uids:
        placeholders = ",".join(["?"] * len(normalized_uids))
        query = f"""
            UPDATE emails
            SET status = 'processed', processed_at = ?
            WHERE uid IN ({placeholders})
        """
        params = [timestamp, *normalized_uids]
        if account_email is not None:
            query += " AND account_email = ?"
            params.append(account_email.strip().lower())
        if folder is not None:
            query += " AND folder = ?"
            params.append((folder or "INBOX").strip() or "INBOX")
        if account_email is not None or folder is not None:
            cursor.execute(query, tuple(params))
            processed_count = cursor.rowcount

    conn.commit()
    conn.close()
    return processed_count


def get_sent_reports(limit: int = 10) -> list:
    """获取发送记录"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM sent_reports
        ORDER BY sent_at DESC
        LIMIT ?
    """, (limit,))

    results = []
    for row in cursor.fetchall():
        results.append({
            "id": row["id"],
            "email_local_ids": row["email_local_ids"],
            "email_uids": row["email_uids"],
            "report_type": row["report_type"],
            "subject": row["subject"],
            "recipient": row["recipient"],
            "sent_at": row["sent_at"],
            "status": row["status"]
        })

    conn.close()
    return results


def get_runtime_state() -> dict:
    defaults = {
        "last_processed_date": None,
        "last_check_time": None,
        "last_error": None,
    }

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT state_key, state_value
        FROM runtime_state
        """
    )
    for key, value in cursor.fetchall():
        if key in defaults:
            defaults[key] = value
    conn.close()
    return defaults


def save_runtime_state(state: dict) -> None:
    normalized = {
        "last_processed_date": state.get("last_processed_date"),
        "last_check_time": state.get("last_check_time"),
        "last_error": state.get("last_error"),
    }
    timestamp = datetime.now(BJT).isoformat()

    conn = _connect()
    cursor = conn.cursor()
    for key, value in normalized.items():
        cursor.execute(
            """
            INSERT INTO runtime_state (state_key, state_value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(state_key) DO UPDATE SET
                state_value = excluded.state_value,
                updated_at = excluded.updated_at
            """,
            (key, value, timestamp),
        )
    conn.commit()
    conn.close()


def get_recent_successful_report(report_type: str = None, within_hours: int = None) -> dict:
    """获取最近一条成功发送记录，可按类型和时间窗口过滤。"""
    conn = _connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    query = """
        SELECT *
        FROM sent_reports
        WHERE status = 'success'
    """
    params = []

    if report_type:
        query += " AND report_type = ?"
        params.append(report_type)

    if within_hours is not None:
        threshold = datetime.now(BJT) - timedelta(hours=within_hours)
        query += " AND sent_at >= ?"
        params.append(threshold.isoformat())

    query += " ORDER BY sent_at DESC LIMIT 1"
    cursor.execute(query, tuple(params))
    row = cursor.fetchone()
    conn.close()

    if not row:
        return None

    return {
        "id": row["id"],
        "email_local_ids": row["email_local_ids"],
        "email_uids": row["email_uids"],
        "report_type": row["report_type"],
        "subject": row["subject"],
        "recipient": row["recipient"],
        "sent_at": row["sent_at"],
        "status": row["status"],
    }


def get_sender_addresses_for_created_date(date_str: str) -> list:
    """获取某个本地创建日期对应的发件人地址列表。"""
    conn = _connect()
    cursor = conn.cursor()

    cursor.execute(
        """
        SELECT email_from
        FROM emails
        WHERE substr(created_at, 1, 10) = ?
        """,
        (date_str,),
    )

    results = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()
    return results


def get_sender_addresses_created_since(start_at: str) -> list:
    """获取某个时间点之后创建的邮件发件人地址列表。"""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT email_from
        FROM emails
        WHERE created_at >= ?
        """,
        (start_at,),
    )
    results = [row[0] for row in cursor.fetchall() if row[0]]
    conn.close()
    return results


def count_emails_created_since(start_at: str) -> int:
    """统计某个时间点之后创建的邮件数量。"""
    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT COUNT(*)
        FROM emails
        WHERE created_at >= ?
        """,
        (start_at,),
    )
    count = cursor.fetchone()[0]
    conn.close()
    return count


def has_new_email_within_minutes(minutes: int, reference_time: datetime = None) -> bool:
    """判断最近 N 分钟内是否仍有新邮件进入数据库。"""
    now_bjt = (reference_time or datetime.now(BJT)).astimezone(BJT)
    threshold = (now_bjt - timedelta(minutes=minutes)).isoformat()

    conn = _connect()
    cursor = conn.cursor()
    cursor.execute(
        """
        SELECT 1
        FROM emails
        WHERE created_at >= ?
        LIMIT 1
        """,
        (threshold,),
    )
    found = cursor.fetchone() is not None
    conn.close()
    return found


def has_successful_report_on_date(date_str: str, report_type: str = None) -> bool:
    """判断某天是否已经有成功发送的报告。"""
    conn = _connect()
    cursor = conn.cursor()

    if report_type:
        cursor.execute(
            """
            SELECT 1
            FROM sent_reports
            WHERE status = 'success'
              AND report_type = ?
              AND substr(sent_at, 1, 10) = ?
            LIMIT 1
            """,
            (report_type, date_str),
        )
    else:
        cursor.execute(
            """
            SELECT 1
            FROM sent_reports
            WHERE status = 'success'
              AND substr(sent_at, 1, 10) = ?
            LIMIT 1
            """,
            (date_str,),
        )

    found = cursor.fetchone() is not None
    conn.close()
    return found


# 初始化数据库
init_db()
