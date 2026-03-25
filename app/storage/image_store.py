import json
import re
import sqlite3
from datetime import datetime

from . import email_db

VISUAL_STATUS_RANK = {
    "": 0,
    "empty": 1,
    "ready": 2,
}

ANALYSIS_STATUS_RANK = {
    "pending": 0,
    "classified": 1,
    "analyzed": 2,
}

LEGACY_IMAGE_KEY_PATTERN = re.compile(r"^(attachment|inline):\d+:(\d+)$")
STABLE_IMAGE_KEY_PATTERN = re.compile(r"^(attachment|inline):(\d+)$")


def _normalize_visual_status(status: str) -> str:
    normalized = str(status or "").strip().lower()
    if normalized == "partial":
        return "ready"
    return normalized if normalized in VISUAL_STATUS_RANK else ""


def _count_visual_items(context: dict) -> int:
    return len(context.get("inline_visual_contexts") or []) + len(context.get("supporting_visual_evidence") or [])


def normalize_image_key(image_key: str, *, kind: str = "", inline_index=None) -> str:
    raw_key = str(image_key or "").strip()
    if not raw_key:
        normalized_kind = str(kind or "").strip().lower()
        if normalized_kind == "inline" and inline_index not in (None, ""):
            try:
                return f"inline:{int(inline_index)}"
            except (TypeError, ValueError):
                return ""
        return ""

    legacy_match = LEGACY_IMAGE_KEY_PATTERN.match(raw_key)
    if legacy_match:
        return f"{legacy_match.group(1)}:{int(legacy_match.group(2))}"

    stable_match = STABLE_IMAGE_KEY_PATTERN.match(raw_key)
    if stable_match:
        return f"{stable_match.group(1)}:{int(stable_match.group(2))}"

    return raw_key


def _merge_unique_strings(values) -> list:
    merged = []
    seen = set()
    for value in values or []:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        merged.append(text)
        seen.add(text)
    return merged


def _parse_json_list(raw_value) -> list:
    if isinstance(raw_value, list):
        return _merge_unique_strings(raw_value)
    try:
        loaded = json.loads(raw_value or "[]")
    except Exception:
        loaded = []
    if not isinstance(loaded, list):
        return []
    return _merge_unique_strings(loaded)


def _pick_first_non_empty(rows: list, field: str, default=""):
    for row in rows:
        value = row.get(field)
        if isinstance(value, str):
            value = value.strip()
        if value not in (None, "", []):
            return value
    return default


def _pick_best_analysis_status(rows: list) -> str:
    best_status = ""
    best_rank = -1
    for row in rows:
        status = str(row.get("analysis_status") or "").strip().lower()
        rank = ANALYSIS_STATUS_RANK.get(status, -1)
        if rank > best_rank:
            best_rank = rank
            best_status = status
    return best_status or "pending"


def _score_email_image_row(row: dict) -> tuple:
    status = str(row.get("analysis_status") or "").strip().lower()
    return (
        1 if str(row.get("image_type") or "").strip() else 0,
        1 if str(row.get("role_in_email") or "").strip() else 0,
        ANALYSIS_STATUS_RANK.get(status, -1),
        1 if str(row.get("sha256") or "").strip() else 0,
        1 if int(row.get("size") or 0) > 0 else 0,
        1 if str(row.get("filename") or "").strip() else 0,
        str(row.get("updated_at") or ""),
        str(row.get("created_at") or ""),
        int(row.get("id") or 0),
    )


def _score_analysis_row(row: dict) -> tuple:
    return (
        1 if str(row.get("core_signal") or "").strip() else 0,
        1 if _parse_json_list(row.get("supporting_details")) else 0,
        str(row.get("updated_at") or ""),
        str(row.get("created_at") or ""),
        int(row.get("id") or 0),
    )


def _non_empty_timestamps(rows: list, field: str) -> list:
    return [str(row.get(field) or "") for row in rows if str(row.get(field) or "")]


def _merge_email_image_rows(normalized_key: str, rows: list) -> dict:
    ordered = sorted(rows, key=_score_email_image_row, reverse=True)
    base = dict(ordered[0])
    kind = str(_pick_first_non_empty(ordered, "kind", base.get("kind") or "") or "").strip().lower()
    source_location = str(
        _pick_first_non_empty(ordered, "source_location", base.get("source_location") or kind or "") or ""
    ).strip().lower()
    inline_index = _pick_first_non_empty(ordered, "inline_index")
    created_times = _non_empty_timestamps(ordered, "created_at")
    updated_times = _non_empty_timestamps(ordered, "updated_at")

    return {
        "email_local_id": int(base.get("email_local_id") or 0),
        "image_key": normalized_key,
        "kind": kind or source_location or "attachment",
        "source_location": source_location or kind or "attachment",
        "inline_index": inline_index if inline_index not in ("", None) else None,
        "filename": str(_pick_first_non_empty(ordered, "filename", base.get("filename") or "") or ""),
        "content_type": str(_pick_first_non_empty(ordered, "content_type", base.get("content_type") or "") or ""),
        "size": max(int(row.get("size") or 0) for row in ordered),
        "sha256": str(_pick_first_non_empty(ordered, "sha256", base.get("sha256") or "") or ""),
        "prescreen_status": str(
            _pick_first_non_empty(ordered, "prescreen_status", base.get("prescreen_status") or "candidate")
            or "candidate"
        ),
        "prescreen_reasons": _merge_unique_strings(
            item for row in ordered for item in _parse_json_list(row.get("prescreen_reasons"))
        ),
        "image_type": str(_pick_first_non_empty(ordered, "image_type", base.get("image_type") or "") or ""),
        "role_in_email": str(_pick_first_non_empty(ordered, "role_in_email", base.get("role_in_email") or "") or ""),
        "analysis_status": _pick_best_analysis_status(ordered),
        "created_at": min(created_times) if created_times else None,
        "updated_at": max(updated_times) if updated_times else None,
    }


def _merge_image_analysis_rows(normalized_key: str, rows: list) -> dict:
    ordered = sorted(rows, key=_score_analysis_row, reverse=True)
    base = dict(ordered[0])
    created_times = _non_empty_timestamps(ordered, "created_at")
    updated_times = _non_empty_timestamps(ordered, "updated_at")
    return {
        "email_local_id": int(base.get("email_local_id") or 0),
        "image_key": normalized_key,
        "core_signal": str(_pick_first_non_empty(ordered, "core_signal", base.get("core_signal") or "") or ""),
        "supporting_details": _merge_unique_strings(
            item for row in ordered for item in _parse_json_list(row.get("supporting_details"))
        ),
        "created_at": min(created_times) if created_times else None,
        "updated_at": max(updated_times) if updated_times else None,
    }


def _group_rows_by_normalized_key(rows: list, *, kind_field: str = "kind", inline_index_field: str = "inline_index") -> dict:
    grouped = {}
    for row in rows:
        normalized_key = normalize_image_key(
            row.get("image_key"),
            kind=row.get(kind_field) or row.get("source_location") or "",
            inline_index=row.get(inline_index_field),
        )
        if not normalized_key:
            normalized_key = str(row.get("image_key") or "").strip()
        grouped.setdefault(normalized_key, []).append(row)
    return grouped


def _normalize_email_image_keys_in_conn(conn, email_local_id: int) -> int:
    if not email_local_id:
        return 0

    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    image_rows = [
        dict(row)
        for row in cursor.execute(
            "SELECT * FROM email_images WHERE email_local_id = ? ORDER BY id",
            (email_local_id,),
        ).fetchall()
    ]
    analysis_rows = [
        dict(row)
        for row in cursor.execute(
            "SELECT * FROM image_analysis_results WHERE email_local_id = ? ORDER BY id",
            (email_local_id,),
        ).fetchall()
    ]

    image_groups = _group_rows_by_normalized_key(image_rows)
    analysis_groups = _group_rows_by_normalized_key(analysis_rows)
    needs_normalization = any(
        normalized_key != str(rows[0].get("image_key") or "").strip() or len(rows) > 1
        for normalized_key, rows in image_groups.items()
    ) or any(
        normalized_key != str(rows[0].get("image_key") or "").strip() or len(rows) > 1
        for normalized_key, rows in analysis_groups.items()
    )
    if not needs_normalization:
        return 0

    merged_image_rows = [
        _merge_email_image_rows(normalized_key, rows)
        for normalized_key, rows in sorted(image_groups.items(), key=lambda item: item[0])
    ]
    merged_analysis_rows = [
        _merge_image_analysis_rows(normalized_key, rows)
        for normalized_key, rows in sorted(analysis_groups.items(), key=lambda item: item[0])
    ]

    cursor.execute("DELETE FROM image_analysis_results WHERE email_local_id = ?", (email_local_id,))
    cursor.execute("DELETE FROM email_images WHERE email_local_id = ?", (email_local_id,))

    for row in merged_image_rows:
        cursor.execute(
            """
            INSERT INTO email_images (
                email_local_id, image_key, kind, source_location, inline_index, filename,
                content_type, size, sha256, prescreen_status, prescreen_reasons,
                image_type, role_in_email, analysis_status, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["email_local_id"],
                row["image_key"],
                row["kind"],
                row["source_location"],
                row["inline_index"],
                row["filename"],
                row["content_type"],
                row["size"],
                row["sha256"],
                row["prescreen_status"],
                json.dumps(row["prescreen_reasons"], ensure_ascii=False),
                row["image_type"],
                row["role_in_email"],
                row["analysis_status"],
                row["created_at"],
                row["updated_at"],
            ),
        )

    for row in merged_analysis_rows:
        cursor.execute(
            """
            INSERT INTO image_analysis_results (
                email_local_id, image_key, core_signal, supporting_details, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                row["email_local_id"],
                row["image_key"],
                row["core_signal"],
                json.dumps(row["supporting_details"], ensure_ascii=False),
                row["created_at"],
                row["updated_at"],
            ),
        )

    return len(merged_image_rows) + len(merged_analysis_rows)


def normalize_email_image_keys(email_local_id: int) -> int:
    if not email_local_id:
        return 0

    conn = email_db._connect()
    try:
        changed = _normalize_email_image_keys_in_conn(conn, email_local_id)
        conn.commit()
        return changed
    finally:
        conn.close()


def _should_keep_existing_visual_context(existing: dict, incoming: dict) -> bool:
    existing_status = _normalize_visual_status(existing.get("visual_status"))
    incoming_status = _normalize_visual_status(incoming.get("visual_status"))
    if VISUAL_STATUS_RANK[existing_status] > VISUAL_STATUS_RANK[incoming_status]:
        return True
    if VISUAL_STATUS_RANK[existing_status] < VISUAL_STATUS_RANK[incoming_status]:
        return False

    existing_items = _count_visual_items(existing)
    incoming_items = _count_visual_items(incoming)
    if existing_items > incoming_items:
        return True
    if existing_items < incoming_items:
        return False

    existing_body = str(existing.get("enriched_body") or "").strip()
    incoming_body = str(incoming.get("enriched_body") or "").strip()
    return len(existing_body) > len(incoming_body)


def _deserialize_email_visual_context_row(row) -> dict:
    if not row:
        return {}

    try:
        inline_items = json.loads(row["inline_visual_contexts"] or "[]")
    except Exception:
        inline_items = []
    try:
        evidence_items = json.loads(row["supporting_visual_evidence"] or "[]")
    except Exception:
        evidence_items = []

    return {
        "visual_status": row["visual_status"] or "",
        "inline_visual_contexts": inline_items if isinstance(inline_items, list) else [],
        "supporting_visual_evidence": evidence_items if isinstance(evidence_items, list) else [],
        "enriched_body": row["enriched_body"] or "",
        "updated_at": row["updated_at"] or "",
    }


def upsert_email_images(email_local_id: int, image_records: list) -> int:
    return upsert_email_images_batch({email_local_id: image_records})


def upsert_email_images_batch(records_by_local_id: dict[int, list]) -> int:
    """写入或更新某封邮件对应的图片记录。"""
    normalized_batches = {
        int(email_local_id): list(image_records or [])
        for email_local_id, image_records in (records_by_local_id or {}).items()
        if email_local_id and image_records
    }
    if not normalized_batches:
        return 0

    conn = email_db._connect()
    cursor = conn.cursor()
    timestamp = datetime.now(email_db.BJT).isoformat()
    count = 0

    for email_local_id, image_records in normalized_batches.items():
        _normalize_email_image_keys_in_conn(conn, email_local_id)
        for image in image_records:
            normalized_key = normalize_image_key(
                image.get("image_key"),
                kind=image.get("kind") or image.get("source_location") or "",
                inline_index=image.get("inline_index"),
            )
            cursor.execute(
                """
                INSERT INTO email_images (
                    email_local_id, image_key, kind, source_location, inline_index, filename,
                    content_type, size, sha256, prescreen_status, prescreen_reasons,
                    image_type, role_in_email, analysis_status, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(email_local_id, image_key) DO UPDATE SET
                    kind = excluded.kind,
                    source_location = excluded.source_location,
                    inline_index = excluded.inline_index,
                    filename = excluded.filename,
                    content_type = excluded.content_type,
                    size = excluded.size,
                    sha256 = excluded.sha256,
                    prescreen_status = excluded.prescreen_status,
                    prescreen_reasons = excluded.prescreen_reasons,
                    image_type = COALESCE(excluded.image_type, email_images.image_type),
                    role_in_email = COALESCE(excluded.role_in_email, email_images.role_in_email),
                    analysis_status = excluded.analysis_status,
                    updated_at = excluded.updated_at
                """,
                (
                    email_local_id,
                    normalized_key,
                    image.get("kind"),
                    image.get("source_location"),
                    image.get("inline_index"),
                    image.get("filename"),
                    image.get("content_type"),
                    int(image.get("size") or 0),
                    image.get("sha256"),
                    image.get("prescreen_result") or image.get("prescreen_status") or "candidate",
                    json.dumps(image.get("prescreen_reasons") or [], ensure_ascii=False),
                    image.get("image_type"),
                    image.get("role_in_email"),
                    image.get("analysis_status") or "pending",
                    timestamp,
                    timestamp,
                ),
            )
            count += 1

    conn.commit()
    conn.close()
    return count


def update_image_classifications(email_local_id: int, image_classifications: dict) -> int:
    return update_image_classifications_batch({email_local_id: image_classifications})


def update_image_classifications_batch(classifications_by_local_id: dict[int, dict]) -> int:
    """更新图片轻分类结果。"""
    normalized_batches = {
        int(email_local_id): dict(image_classifications or {})
        for email_local_id, image_classifications in (classifications_by_local_id or {}).items()
        if email_local_id and image_classifications
    }
    if not normalized_batches:
        return 0

    conn = email_db._connect()
    cursor = conn.cursor()
    timestamp = datetime.now(email_db.BJT).isoformat()
    count = 0

    for email_local_id, image_classifications in normalized_batches.items():
        _normalize_email_image_keys_in_conn(conn, email_local_id)
        normalized_classifications = {}
        for image_key, classification in image_classifications.items():
            normalized_key = normalize_image_key(
                image_key,
                kind=classification.get("kind") or "",
                inline_index=classification.get("inline_index"),
            )
            if not normalized_key:
                continue
            normalized_classifications[normalized_key] = classification

        for image_key, classification in normalized_classifications.items():
            cursor.execute(
                """
                UPDATE email_images
                SET image_type = ?, role_in_email = ?, analysis_status = 'classified', updated_at = ?
                WHERE email_local_id = ? AND image_key = ?
                """,
                (
                    classification.get("image_type"),
                    classification.get("role_in_email"),
                    timestamp,
                    email_local_id,
                    image_key,
                ),
            )
            count += cursor.rowcount

    conn.commit()
    conn.close()
    return count


def upsert_image_analysis_results(email_local_id: int, analysis_results: dict) -> int:
    return upsert_image_analysis_results_batch({email_local_id: analysis_results})


def upsert_image_analysis_results_batch(results_by_local_id: dict[int, dict]) -> int:
    """写入或更新单封邮件的图片深分析结果。"""
    normalized_batches = {
        int(email_local_id): dict(analysis_results or {})
        for email_local_id, analysis_results in (results_by_local_id or {}).items()
        if email_local_id and analysis_results
    }
    if not normalized_batches:
        return 0

    conn = email_db._connect()
    cursor = conn.cursor()
    timestamp = datetime.now(email_db.BJT).isoformat()
    count = 0

    for email_local_id, analysis_results in normalized_batches.items():
        _normalize_email_image_keys_in_conn(conn, email_local_id)
        normalized_results = {}
        for image_key, result in analysis_results.items():
            normalized_key = normalize_image_key(
                image_key,
                kind=result.get("kind") or "",
                inline_index=result.get("inline_index"),
            )
            if not normalized_key:
                continue
            normalized_results[normalized_key] = result

        for image_key, result in normalized_results.items():
            cursor.execute(
                """
                INSERT INTO image_analysis_results (
                    email_local_id, image_key, core_signal, supporting_details,
                    created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(email_local_id, image_key) DO UPDATE SET
                    core_signal = excluded.core_signal,
                    supporting_details = excluded.supporting_details,
                    updated_at = excluded.updated_at
                """,
                (
                    email_local_id,
                    image_key,
                    result.get("core_signal"),
                    json.dumps(result.get("supporting_details") or [], ensure_ascii=False),
                    timestamp,
                    timestamp,
                ),
            )
            cursor.execute(
                """
                UPDATE email_images
                SET analysis_status = 'analyzed', updated_at = ?
                WHERE email_local_id = ? AND image_key = ?
                """,
                (timestamp, email_local_id, image_key),
            )
            count += 1

    conn.commit()
    conn.close()
    return count


def save_email_visual_context(
    email_local_id: int,
    *,
    visual_status: str,
    inline_visual_contexts: list,
    supporting_visual_evidence: list,
    enriched_body: str,
) -> None:
    save_email_visual_contexts_batch(
        {
            email_local_id: {
                "visual_status": visual_status,
                "inline_visual_contexts": inline_visual_contexts,
                "supporting_visual_evidence": supporting_visual_evidence,
                "enriched_body": enriched_body,
            }
        }
    )


def save_email_visual_contexts_batch(contexts_by_local_id: dict[int, dict]) -> int:
    """保存邮件级视觉上下文与增强正文。"""
    normalized_batches = {
        int(email_local_id): dict(context or {})
        for email_local_id, context in (contexts_by_local_id or {}).items()
        if email_local_id
    }
    if not normalized_batches:
        return 0

    conn = email_db._connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    timestamp = datetime.now(email_db.BJT).isoformat()
    placeholders = ",".join(["?"] * len(normalized_batches))
    cursor.execute(
        f"""
        SELECT email_local_id, visual_status, inline_visual_contexts, supporting_visual_evidence, enriched_body, updated_at
        FROM email_visual_contexts
        WHERE email_local_id IN ({placeholders})
        """,
        tuple(normalized_batches.keys()),
    )
    existing_by_local_id = {
        int(row["email_local_id"]): _deserialize_email_visual_context_row(row)
        for row in cursor.fetchall()
    }

    saved_count = 0
    for email_local_id, context in normalized_batches.items():
        incoming = {
            "visual_status": context.get("visual_status") or "",
            "inline_visual_contexts": list(context.get("inline_visual_contexts") or []),
            "supporting_visual_evidence": list(context.get("supporting_visual_evidence") or []),
            "enriched_body": context.get("enriched_body") or "",
        }
        existing = existing_by_local_id.get(email_local_id) or {}
        if existing and _should_keep_existing_visual_context(existing, incoming):
            continue
        cursor.execute(
            """
            INSERT INTO email_visual_contexts (
                email_local_id, visual_status, inline_visual_contexts,
                supporting_visual_evidence, enriched_body, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(email_local_id) DO UPDATE SET
                visual_status = excluded.visual_status,
                inline_visual_contexts = excluded.inline_visual_contexts,
                supporting_visual_evidence = excluded.supporting_visual_evidence,
                enriched_body = excluded.enriched_body,
                updated_at = excluded.updated_at
            """,
            (
                email_local_id,
                incoming["visual_status"],
                json.dumps(incoming["inline_visual_contexts"], ensure_ascii=False),
                json.dumps(incoming["supporting_visual_evidence"], ensure_ascii=False),
                incoming["enriched_body"],
                timestamp,
                timestamp,
            ),
        )
        saved_count += 1
    conn.commit()
    conn.close()
    return saved_count


def get_email_visual_context(email_local_id: int) -> dict:
    return get_email_visual_contexts([email_local_id]).get(int(email_local_id or 0), {})


def get_email_visual_contexts(email_local_ids: list[int]) -> dict[int, dict]:
    """读取单封邮件已缓存的视觉上下文。"""
    normalized_ids = [int(email_local_id) for email_local_id in (email_local_ids or []) if email_local_id]
    if not normalized_ids:
        return {}

    conn = email_db._connect()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(normalized_ids))
    cursor.execute(
        f"""
        SELECT email_local_id, visual_status, inline_visual_contexts, supporting_visual_evidence, enriched_body, updated_at
        FROM email_visual_contexts
        WHERE email_local_id IN ({placeholders})
        """,
        tuple(normalized_ids),
    )
    rows = cursor.fetchall()
    conn.close()
    return {
        int(row["email_local_id"]): _deserialize_email_visual_context_row(row)
        for row in rows
    }


def get_email_image_analysis_records(email_local_id: int) -> list:
    return get_email_image_analysis_records_map([email_local_id]).get(int(email_local_id or 0), [])


def get_email_image_analysis_records_map(email_local_ids: list[int]) -> dict[int, list]:
    """读取单封邮件的图片记录与深分析结果，用于重建位置化视觉上下文。"""
    normalized_ids = [int(email_local_id) for email_local_id in (email_local_ids or []) if email_local_id]
    if not normalized_ids:
        return {}

    conn = email_db._connect()
    conn.row_factory = sqlite3.Row
    for email_local_id in normalized_ids:
        if _normalize_email_image_keys_in_conn(conn, email_local_id):
            conn.commit()
    cursor = conn.cursor()
    placeholders = ",".join(["?"] * len(normalized_ids))
    cursor.execute(
        f"""
        SELECT
            ei.email_local_id,
            ei.image_key,
            ei.kind,
            ei.source_location,
            ei.inline_index,
            ei.filename,
            ei.content_type,
            ei.size,
            ei.image_type,
            ei.role_in_email,
            iar.core_signal,
            iar.supporting_details
        FROM email_images ei
        LEFT JOIN image_analysis_results iar
          ON iar.email_local_id = ei.email_local_id
         AND iar.image_key = ei.image_key
        WHERE ei.email_local_id IN ({placeholders})
        ORDER BY
            ei.email_local_id,
            CASE WHEN COALESCE(ei.inline_index, 0) > 0 THEN 0 ELSE 1 END,
            COALESCE(ei.inline_index, 999999),
            COALESCE(ei.filename, ''),
            COALESCE(ei.image_key, '')
        """,
        tuple(normalized_ids),
    )
    rows = cursor.fetchall()
    conn.close()

    records_by_local_id: dict[int, list] = {email_local_id: [] for email_local_id in normalized_ids}
    for row in rows:
        try:
            supporting_details = json.loads(row["supporting_details"] or "[]")
        except Exception:
            supporting_details = []
        records_by_local_id.setdefault(int(row["email_local_id"]), []).append(
            {
                "image_key": normalize_image_key(
                    row["image_key"] or "",
                    kind=row["kind"] or row["source_location"] or "",
                    inline_index=row["inline_index"],
                ),
                "kind": row["kind"] or row["source_location"] or "attachment",
                "inline_index": row["inline_index"],
                "filename": row["filename"] or "",
                "content_type": row["content_type"] or "",
                "size": int(row["size"] or 0),
                "image_type": row["image_type"] or "",
                "role_in_email": row["role_in_email"] or "",
                "core_signal": row["core_signal"] or "",
                "supporting_details": supporting_details if isinstance(supporting_details, list) else [],
            }
        )
    return records_by_local_id
