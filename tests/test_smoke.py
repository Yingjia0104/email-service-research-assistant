import asyncio
import json
import os
import sqlite3
import smtplib
import socket
import tempfile
import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from unittest.mock import Mock, patch


class SmokeTests(unittest.TestCase):
    def test_config_example_has_no_real_key(self):
        repo_root = os.path.dirname(os.path.dirname(__file__))
        cfg_path = os.path.join(repo_root, "config.yaml.example")
        with open(cfg_path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("sk-", text)
        self.assertIn('model: "kimi-k2.5"', text)
        self.assertIn('api_key_env: "OPENAI_API_KEY"', text)
        self.assertIn("supports_vision: true", text)

    def test_send_report_uses_query_api_key(self):
        import qclaw_mail_file

        with tempfile.TemporaryDirectory() as td:
            report_path = os.path.join(td, "r.html")
            with open(report_path, "w", encoding="utf-8") as f:
                f.write("<html><head></head><body>ok</body></html>")

            fake_resp = Mock()
            fake_resp.json.return_value = {"success": True}

            with patch.object(qclaw_mail_file, "load_config", return_value={"api_key": "k", "target": {"email": "t@e.com"}}):
                with patch.object(qclaw_mail_file.session, "post", return_value=fake_resp) as post:
                    with patch.object(qclaw_mail_file.email_db, "finalize_report_success", return_value=2) as finalize:
                        ok = qclaw_mail_file.send_report(
                            report_path,
                            email_uids=["1", "2"],
                            email_local_ids=[10, 11],
                            is_supplement=False,
                        )

            self.assertTrue(ok)
            post.assert_called_once()
            finalize.assert_called_once()
            _, kwargs = post.call_args
            self.assertEqual(kwargs.get("params"), {"api_key": "k"})
            self.assertNotIn("api_key", kwargs.get("json", {}))

    def test_mark_processed_marks_only_given_uids(self):
        import qclaw_mail_file

        with patch.object(qclaw_mail_file.email_db, "mark_processed") as mark:
            with patch.object(qclaw_mail_file.email_db, "get_local_ids_by_uids", return_value={"1": 1, "2": 2}):
                qclaw_mail_file.mark_emails_processed(["1", None, "2", ""])

        mark.assert_called_once_with(["1", "2"])

    def test_add_emails_allows_same_uid_in_different_mailboxes(self):
        import email_db

        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "emails.db")
            original_db_file = email_db.DB_FILE
            try:
                email_db.DB_FILE = db_path
                email_db.init_db()

                added = email_db.add_emails([
                    {
                        "account_email": "alpha@example.com",
                        "folder": "INBOX",
                        "id": "100",
                        "from": "a@example.com",
                        "subject": "A",
                        "date": "2026-03-16T09:00:00+08:00",
                    },
                    {
                        "account_email": "beta@example.com",
                        "folder": "INBOX",
                        "id": "100",
                        "from": "b@example.com",
                        "subject": "B",
                        "date": "2026-03-16T09:01:00+08:00",
                    },
                ])

                self.assertEqual(added, 2)

                conn = sqlite3.connect(db_path)
                try:
                    rows = conn.execute(
                        "SELECT account_email, folder, uid FROM emails ORDER BY account_email"
                    ).fetchall()
                finally:
                    conn.close()

                self.assertEqual(
                    rows,
                    [
                        ("alpha@example.com", "INBOX", "100"),
                        ("beta@example.com", "INBOX", "100"),
                    ],
                )
            finally:
                email_db.DB_FILE = original_db_file

    def test_finalize_report_success_is_atomic_for_log_and_processed(self):
        import email_db

        with tempfile.TemporaryDirectory() as td:
            db_path = os.path.join(td, "emails.db")
            original_db_file = email_db.DB_FILE
            try:
                email_db.DB_FILE = db_path
                email_db.init_db()
                email_db.add_emails([
                    {
                        "account_email": "alpha@example.com",
                        "folder": "INBOX",
                        "id": "200",
                        "from": "a@example.com",
                        "subject": "Atomic",
                        "date": "2026-03-16T10:00:00+08:00",
                    }
                ])

                pending = email_db.get_pending_emails(limit=10)
                processed_count = email_db.finalize_report_success(
                    email_local_ids=[pending[0]["local_id"]],
                    email_uids=[pending[0]["id"]],
                    report_type="daily",
                    subject="AI Morning Brief | 2026-03-16 10:01",
                    recipient="target@example.com",
                )

                self.assertEqual(processed_count, 1)

                conn = sqlite3.connect(db_path)
                try:
                    email_row = conn.execute(
                        "SELECT status, processed_at FROM emails WHERE id = ?",
                        (pending[0]["local_id"],),
                    ).fetchone()
                    report_row = conn.execute(
                        "SELECT report_type, status, recipient FROM sent_reports"
                    ).fetchone()
                finally:
                    conn.close()

                self.assertEqual(email_row[0], "processed")
                self.assertTrue(email_row[1])
                self.assertEqual(report_row, ("daily", "success", "target@example.com"))
            finally:
                email_db.DB_FILE = original_db_file

    def test_send_email_smtp_async_wrapper(self):
        import main

        async def run():
            with patch("main._send_email_sync", return_value={"success": True}) as sync_send:
                res = await main.send_email_smtp(
                    smtp_host="smtp.example.com",
                    smtp_port=587,
                    from_email="a@b.com",
                    password="pw",
                    to_email="c@d.com",
                    subject="s",
                    body="b",
                    body_type="plain",
                )
                self.assertEqual(res, {"success": True})
                sync_send.assert_called_once()

        asyncio.run(run())

    def test_smtp_timeout_maps_to_504(self):
        import main

        status_code, detail = main.classify_smtp_exception(socket.timeout("timed out"))

        self.assertEqual(status_code, 504)
        self.assertIn("超时", detail)

    def test_smtp_auth_failure_maps_to_502(self):
        import main

        status_code, detail = main.classify_smtp_exception(smtplib.SMTPAuthenticationError(535, b"auth failed"))

        self.assertEqual(status_code, 502)
        self.assertIn("认证失败", detail)

    def test_get_us_market_open_time_uses_real_dst(self):
        import main

        march = main.BJT.localize(datetime(2026, 3, 16, 10, 0, 0))
        january = main.BJT.localize(datetime(2026, 1, 15, 10, 0, 0))

        self.assertEqual(main.get_us_market_open_time(march), (21, 15))
        self.assertEqual(main.get_us_market_open_time(january), (22, 15))

    def test_get_next_market_trigger_time_skips_weekend(self):
        import main

        sunday_bjt = main.BJT.localize(datetime(2026, 3, 22, 14, 0, 0))
        next_trigger = main.get_next_market_trigger_time(sunday_bjt)

        self.assertEqual(next_trigger.strftime("%Y-%m-%d %H:%M"), "2026-03-23 21:15")

    def test_is_in_supplement_window_uses_market_session_bounds(self):
        import main

        inside_dst = main.BJT.localize(datetime(2026, 3, 16, 21, 20, 0))
        outside_dst = main.BJT.localize(datetime(2026, 3, 16, 20, 59, 0))

        self.assertTrue(main.is_in_supplement_window(inside_dst))
        self.assertFalse(main.is_in_supplement_window(outside_dst))

    def test_message_local_date_converts_cross_timezone_mail(self):
        import main

        sunday_evening_et = datetime(2026, 3, 15, 20, 30, 0, tzinfo=ZoneInfo("America/New_York"))
        local_date = main.get_message_local_date(sunday_evening_et, main.BJT)

        self.assertEqual(local_date.isoformat(), "2026-03-16")

    def test_match_allowed_sender_supports_exact_and_suffix(self):
        import main

        allowed = ["analyst@example.com", "@broker.com"]

        self.assertEqual(main.match_allowed_sender("analyst@example.com", allowed), "analyst@example.com")
        self.assertEqual(main.match_allowed_sender("foo@broker.com", allowed), "@broker.com")
        self.assertIsNone(main.match_allowed_sender("foo@other.com", allowed))

    def test_all_expected_senders_arrived_uses_today_matches(self):
        import main

        allowed = ["analyst@example.com", "@broker.com"]
        with patch.object(main.email_db, "get_sender_addresses_for_created_date", return_value=[
            "Analyst <analyst@example.com>",
            "Other <foo@broker.com>",
        ]):
            arrived = main.all_expected_senders_arrived(allowed, main.BJT.localize(datetime(2026, 3, 16, 18, 0, 0)))

        self.assertTrue(arrived)

    def test_clean_extracted_attachment_text_strips_links_and_disclaimer(self):
        import main

        raw = (
            "Top line view\n"
            "https://example.com/really/long/link\n"
            "Second insight\n"
            "Confidentiality Notice: this email and any attachments are privileged\n"
            "Trailing text that should disappear\n"
        )

        cleaned = main._clean_extracted_attachment_text(raw, filename="note.msg")

        self.assertIn("Top line view", cleaned)
        self.assertIn("Second insight", cleaned)
        self.assertIn("[link]", cleaned)
        self.assertNotIn("https://example.com", cleaned)
        self.assertNotIn("Trailing text that should disappear", cleaned)

    def test_clean_extracted_attachment_text_truncates_long_msg_body(self):
        import main

        raw = ("alpha beta gamma\n" * 4000)
        cleaned = main._clean_extracted_attachment_text(raw, filename="long.msg")

        self.assertIn("[附件内容已截断]", cleaned)
        self.assertLessEqual(len(cleaned), main.MAX_EXTRACTED_ATTACHMENT_TEXT_CHARS + 20)

    def test_verify_api_key_uses_fresh_config(self):
        import main

        with patch.object(main, "load_config", return_value={"api_key": "fresh-key"}):
            self.assertTrue(main.verify_api_key("fresh-key"))
            self.assertFalse(main.verify_api_key("stale-key"))

    def test_strip_signature_and_disclaimer(self):
        import qclaw_mail_file

        body = (
            "核心观点一\n核心观点二\n核心观点三\n\n"
            "Best regards,\nAnalyst Team\n"
            "Confidentiality Notice: for intended recipient only"
        )

        cleaned = qclaw_mail_file.sanitize_email_body(body)

        self.assertIn("核心观点一", cleaned)
        self.assertNotIn("Best regards", cleaned)
        self.assertNotIn("Confidentiality Notice", cleaned)

    def test_parse_batch_summary_json_from_code_fence(self):
        import qclaw_mail_file

        raw = """```json
        {
          "batch_index": 1,
          "batch_total": 2,
          "email_ids": [1, 2],
          "topics": [
            {
              "title": "NVDA 推理芯片",
              "email_ids": [1],
              "coverage_count": 1,
              "fact_subject": "NVDA",
              "opinion_subject": "Shawn Kim",
              "info_type": "外部引述",
              "core_facts": ["讨论 LPU 与 SRAM 路线"],
              "market_takeaways": ["HBM 仍是关键补充"],
              "tickers": ["NVDA", "MU"],
              "source_evidence": ["Shawn Kim says SRAM is a complement to HBM"]
            }
          ]
        }
        ```"""

        parsed = qclaw_mail_file.parse_batch_summary_json(raw)

        self.assertEqual(parsed["topics"][0]["opinion_subject"], "Shawn Kim")
        self.assertEqual(parsed["topics"][0]["info_type"], "外部引述")
        self.assertIn("source_evidence", parsed["topics"][0])

    def test_primary_network_failure_falls_back_to_backup(self):
        import qclaw_mail_file

        emails = [{
            "subject": "s",
            "from_name": "n",
            "from": "a@example.com",
            "date": "2026-03-16 00:00:00+08:00",
            "body": "b",
        }]
        real_cfg = {"api_key": "backup-key", "base_url": "https://backup.example/v1", "model": "backup-model"}
        calls = []

        def fake_load():
            qclaw_mail_file.LLM_BACKUP_CONFIG.update(real_cfg)
            return {"api_key": "primary-key", "base_url": "https://primary.example/v1", "model": "primary-model"}

        def fake_call(api_config, system_prompt, user_prompt, user_content_blocks=None):
            calls.append(api_config["base_url"])
            if api_config["base_url"] == "https://primary.example/v1":
                raise RuntimeError("network down")
            return """{
              "executive_summary": {
                "market_background": "市场情绪偏谨慎",
                "key_signals": ["HBM 需求仍强"]
              },
              "core_events": [
                {
                  "headline": "NVDA 推理链路",
                  "core_facts": ["讨论 LPU 与 SRAM 路线"],
                  "market_views": [
                    {"source": "行业交流", "stance": "积极", "thesis": "HBM 仍是关键补充"}
                  ],
                  "action": "关注 NVDA 与 MU",
                  "attribution_note": "邮件转述 Shawn Kim 观点",
                  "source_evidence": ["Shawn Kim says SRAM is a complement to HBM"]
                }
              ],
              "local_news": [
                {"headline": "边缘信号", "signal": "供应链对 GTC 更乐观", "importance": "情绪改善", "action": "跟踪会后反馈"}
              ],
              "peripheral_intelligence": {
                "mapped_events": [],
                "cross_market_signals": []
              },
              "actionable_ideas": {
                "short_term": ["GTC 期间供应链反馈"],
                "medium_term": ["后续量产验证"],
                "catalysts": [{"catalyst": "GTC", "time": "本周", "impact": "NVDA, MU"}],
                "bottom_line": "关注推理链路进展",
                "next_update": "盘前关键节点"
              }
            }"""

        with patch.object(qclaw_mail_file, "load_llm_config", side_effect=fake_load):
            with patch.object(qclaw_mail_file, "call_llm_api", side_effect=fake_call):
                with patch.object(qclaw_mail_file.time, "sleep", return_value=None):
                    result = qclaw_mail_file.analyze_emails_with_llm(emails)

        self.assertIn("NVDA 推理链路", result)
        self.assertEqual(
            calls,
            [
                "https://primary.example/v1",
                "https://primary.example/v1",
                "https://backup.example/v1",
            ],
        )

    def test_missing_primary_key_skips_to_backup(self):
        import qclaw_mail_file

        emails = [{
            "subject": "s",
            "from_name": "n",
            "from": "a@example.com",
            "date": "2026-03-16 00:00:00+08:00",
            "body": "b",
        }]
        calls = []

        def fake_load():
            qclaw_mail_file.LLM_BACKUP_CONFIG.update({
                "api_key": "backup-key",
                "base_url": "https://backup.example/v1",
                "model": "kimi-k2.5",
            })
            return {
                "api_key": "",
                "api_key_env": "OPENAI_API_KEY",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-5.4",
                "supports_vision": True,
                "reasoning_effort": "medium",
            }

        def fake_call(api_config, system_prompt, user_prompt, user_content_blocks=None):
            calls.append(api_config["base_url"])
            return """{
              "executive_summary": {"market_background": "背景", "key_signals": ["信号"]},
              "core_events": [],
              "local_news": [],
              "peripheral_intelligence": {"mapped_events": [], "cross_market_signals": []},
              "actionable_ideas": {"short_term": [], "medium_term": [], "catalysts": [], "bottom_line": "结论"}
            }"""

        with patch.object(qclaw_mail_file, "load_llm_config", side_effect=fake_load):
            with patch.object(qclaw_mail_file, "call_llm_api", side_effect=fake_call):
                result = qclaw_mail_file.analyze_emails_with_llm(emails)

        self.assertIn("Executive Summary", result)
        self.assertEqual(calls, ["https://backup.example/v1"])

    def test_missing_primary_and_backup1_skips_to_backup2(self):
        import qclaw_mail_file

        emails = [{
            "subject": "s",
            "from_name": "n",
            "from": "a@example.com",
            "date": "2026-03-16 00:00:00+08:00",
            "body": "b",
        }]
        calls = []

        def fake_load():
            qclaw_mail_file.LLM_BACKUP_CONFIG.clear()
            qclaw_mail_file.LLM_BACKUP_CONFIG.update({
                "api_key": "",
                "base_url": "https://backup1.example/v1",
                "model": "backup1-model",
            })
            qclaw_mail_file.LLM_BACKUP2_CONFIG.clear()
            qclaw_mail_file.LLM_BACKUP2_CONFIG.update({
                "api_key": "backup2-key",
                "base_url": "https://backup2.example/v1",
                "model": "gpt-5.4",
                "supports_vision": True,
                "reasoning_effort": "medium",
            })
            return {
                "api_key": "",
                "base_url": "https://primary.example/v1",
                "model": "kimi-k2.5",
                "supports_vision": True,
            }

        def fake_call(api_config, system_prompt, user_prompt, user_content_blocks=None):
            calls.append(api_config["base_url"])
            return """{
              "executive_summary": {"market_background": "背景", "key_signals": ["信号"]},
              "core_events": [],
              "local_news": [],
              "peripheral_intelligence": {"mapped_events": [], "cross_market_signals": []},
              "actionable_ideas": {"short_term": [], "medium_term": [], "catalysts": [], "bottom_line": "结论"}
            }"""

        with patch.object(qclaw_mail_file, "load_llm_config", side_effect=fake_load):
            with patch.object(qclaw_mail_file, "call_llm_api", side_effect=fake_call):
                result = qclaw_mail_file.analyze_emails_with_llm(emails)

        self.assertIn("Executive Summary", result)
        self.assertEqual(calls, ["https://backup2.example/v1"])

    def test_analyze_sanitizes_inline_image_payloads(self):
        import qclaw_mail_file

        emails = [{
            "subject": "img",
            "from_name": "n",
            "from": "a@example.com",
            "date": "2026-03-16 00:00:00+08:00",
            "body": "<p>note</p><img src='data:image/png;base64,AAAAAA'>tail",
        }]
        prompts = {}

        def fake_call(api_config, system_prompt, user_prompt):
            prompts["user_prompt"] = user_prompt
            return """{
              "executive_summary": {
                "market_background": "图表显示行业景气改善",
                "key_signals": ["图片里的数据变化值得关注"]
              },
              "core_events": [],
              "local_news": [
                {"headline": "图表边缘信息", "signal": "图表中的拐点出现", "importance": "可能影响预期", "action": "继续跟踪"}
              ],
              "peripheral_intelligence": {
                "mapped_events": [],
                "cross_market_signals": []
              },
              "actionable_ideas": {
                "short_term": ["盘前新增邮件"],
                "medium_term": ["后续验证节点"],
                "catalysts": [{"catalyst": "业绩", "time": "下周", "impact": "相关板块"}],
                "bottom_line": "先跟踪数据变化",
                "next_update": "盘前关键节点"
              }
            }"""

        with patch.object(
            qclaw_mail_file,
            "load_llm_config",
            return_value={"api_key": "primary-key", "base_url": "https://primary.example/v1", "model": "primary-model"},
        ):
            with patch.object(qclaw_mail_file, "call_llm_api_with_retries", side_effect=lambda *args, **kwargs: fake_call(*args[:3])):
                result = qclaw_mail_file.analyze_emails_with_llm(emails)

        self.assertIn("Executive Summary", result)
        self.assertIn("[内嵌图片已省略", prompts["user_prompt"])
        self.assertNotIn("data:image/png;base64", prompts["user_prompt"])

    def test_build_multimodal_user_blocks_uses_image_attachments(self):
        import qclaw_mail_file

        emails = [{
            "subject": "img",
            "attachments": json.dumps([
                {
                    "filename": "chart.png",
                    "content_type": "image/png",
                    "size": 128,
                    "kind": "image",
                    "data_url": "data:image/png;base64,AAAA",
                }
            ]),
        }]

        blocks = qclaw_mail_file.build_multimodal_user_blocks(
            emails,
            {"model": "kimi-k2.5", "supports_vision": True},
        )

        self.assertEqual(len(blocks), 2)
        self.assertEqual(blocks[0]["type"], "text")
        self.assertIn("chart.png", blocks[0]["text"])
        self.assertEqual(blocks[1]["type"], "image_url")
        self.assertEqual(blocks[1]["image_url"]["url"], "data:image/png;base64,AAAA")

    def test_build_multimodal_user_blocks_uses_inline_body_images(self):
        import qclaw_mail_file

        emails = [{
            "subject": "inline img",
            "body": "<p>chart</p><img src=\"data:image/png;base64,AAAA\">",
        }]

        blocks = qclaw_mail_file.build_multimodal_user_blocks(
            emails,
            {"model": "kimi-k2.5", "supports_vision": True},
        )

        self.assertEqual(len(blocks), 2)
        self.assertIn("正文中的图片", blocks[0]["text"])
        self.assertEqual(blocks[1]["image_url"]["url"], "data:image/png;base64,AAAA")

    def test_build_multimodal_user_blocks_dedupes_attachment_and_inline_image(self):
        import qclaw_mail_file

        emails = [{
            "subject": "dup img",
            "body": "<img src=\"data:image/png;base64,AAAA\">",
            "attachments": json.dumps([
                {
                    "filename": "same.png",
                    "content_type": "image/png",
                    "size": 4,
                    "kind": "image",
                    "data_url": "data:image/png;base64,AAAA",
                }
            ]),
        }]

        blocks = qclaw_mail_file.build_multimodal_user_blocks(
            emails,
            {"model": "kimi-k2.5", "supports_vision": True},
        )

        self.assertEqual(len(blocks), 2)

    def test_call_llm_api_sends_multimodal_payload(self):
        import qclaw_mail_file

        fake_resp = Mock()
        fake_resp.json.return_value = {
            "choices": [{"message": {"content": "<html><body>ok</body></html>"}}]
        }
        fake_resp.raise_for_status.return_value = None

        with patch.object(qclaw_mail_file.session, "post", return_value=fake_resp) as post:
            result = qclaw_mail_file.call_llm_api(
                {"api_key": "k", "base_url": "https://api.moonshot.cn/v1", "model": "kimi-k2.5"},
                "system",
                "user prompt",
                user_content_blocks=[
                    {"type": "text", "text": "image context"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
                ],
            )

        self.assertIn("ok", result)
        _, kwargs = post.call_args
        messages = kwargs["json"]["messages"]
        self.assertIsInstance(messages[1]["content"], list)
        self.assertEqual(messages[1]["content"][0], {"type": "text", "text": "user prompt"})
        self.assertEqual(messages[1]["content"][2]["type"], "image_url")

    def test_call_llm_api_uses_openai_gpt5_chat_options(self):
        import qclaw_mail_file

        fake_resp = Mock()
        fake_resp.json.return_value = {
            "choices": [{"message": {"content": "{\"ok\": true}"}}]
        }
        fake_resp.raise_for_status.return_value = None

        with patch.object(qclaw_mail_file.session, "post", return_value=fake_resp) as post:
            qclaw_mail_file.call_llm_api(
                {
                    "api_key": "k",
                    "base_url": "https://api.openai.com/v1",
                    "model": "gpt-5.4",
                    "supports_vision": True,
                    "reasoning_effort": "medium",
                },
                "system",
                "user prompt",
            )

        _, kwargs = post.call_args
        payload = kwargs["json"]
        self.assertEqual(payload["max_completion_tokens"], qclaw_mail_file.MAX_COMPLETION_TOKENS)
        self.assertEqual(payload["reasoning_effort"], "medium")
        self.assertNotIn("max_tokens", payload)
        self.assertNotIn("temperature", payload)

    def test_split_emails_for_analysis_when_context_too_long(self):
        import qclaw_mail_file

        emails = [
            {"body": ("alpha beta gamma delta\n" * 700), "subject": "1"},
            {"body": ("theta lambda sigma omega\n" * 650), "subject": "2"},
            {"body": ("copper optics power demand\n" * 600), "subject": "3"},
        ]

        batches = qclaw_mail_file.split_emails_for_analysis(emails)

        self.assertEqual(len(batches), 2)
        self.assertEqual(
            sorted(item["_analysis_index"] for batch in batches for item in batch),
            [1, 2, 3],
        )

    def test_format_html_report_uses_local_date_title(self):
        import qclaw_mail_file

        today = datetime.now(qclaw_mail_file.BJT).strftime("%Y-%m-%d")
        html = "<html><body><h1>AI Morning Brief | March 17, 2026</h1><h2>Executive Summary</h2></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn(f"<title>AI Morning Brief | {today}</title>", formatted)
        self.assertIn(f"<h1>AI Morning Brief | {today}</h1>", formatted)
        self.assertNotIn("March 17, 2026", formatted)
        self.assertIn("Prepared by: AI Research Assistant", formatted)
        self.assertIn("Source: Whitelisted analyst emails", formatted)
        self.assertIn("Reading time:", formatted)

    def test_format_html_report_injects_meta_with_sources(self):
        import qclaw_mail_file

        html = "<html><body><h1>AI Morning Brief | 2026-03-16</h1><p>内容内容内容</p></body></html>"
        formatted = qclaw_mail_file.format_html_report(
            html,
            source_emails=[
                {"from_name": "chen yingjia", "from": "a@example.com", "body": "Morgan Stanley analyst Joe Moore preview note"},
                {"from_name": "yingjia chen", "from": "b@example.com", "body": "J.P. Morgan analyst update on media names"},
            ],
        )

        self.assertIn("Source: MS + JPM", formatted)

    def test_save_report_returns_stable_filename_and_keeps_timestamped_archive(self):
        import qclaw_mail_file

        html = "<html><head><title>x</title></head><body><h1>AI Morning Brief | 2026-03-17</h1><p>正文</p></body></html>"

        with tempfile.TemporaryDirectory() as td:
            with patch.object(qclaw_mail_file, "BASE_DIR", td):
                report_file = qclaw_mail_file.save_report(html)
                self.assertIsNotNone(report_file)
                self.assertTrue(report_file.endswith(".html"))

                stable_files = [
                    name for name in os.listdir(td)
                    if name.startswith("AI_Morning_Brief_") and name.endswith(".html")
                ]

                stable_path = report_file
                self.assertTrue(os.path.exists(stable_path))
                self.assertRegex(os.path.basename(stable_path), r"^AI_Morning_Brief_\d{8}\.html$")

                timestamped_paths = [
                    os.path.join(td, name)
                    for name in stable_files
                    if name != os.path.basename(stable_path)
                ]
                self.assertEqual(len(timestamped_paths), 1)
                self.assertRegex(
                    os.path.basename(timestamped_paths[0]),
                    r"^AI_Morning_Brief_\d{8}_\d{6}\.html$",
                )

                latest = qclaw_mail_file.check_for_report()
                self.assertEqual(latest, stable_path)

    def test_format_html_report_removes_existing_model_meta_block(self):
        import qclaw_mail_file

        html = """<html><body>
        <h1>AI Morning Brief | 2026-03-16</h1>
        <div class="meta">阅读时间：约3分钟 | 覆盖周期：盘前关键事件</div>
        <p>正文</p>
        </body></html>"""
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertEqual(formatted.count('class="meta"'), 1)
        self.assertNotIn("覆盖周期：盘前关键事件", formatted)

    def test_format_html_report_promotes_bold_paragraph_heading_to_h3(self):
        import qclaw_mail_file

        html = "<html><body><p><strong>Catalysts to Watch:</strong></p><ul><li>A</li></ul></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<h3>Catalysts to Watch</h3>", formatted)
        self.assertNotIn("<p><strong>Catalysts to Watch:</strong></p>", formatted)

    def test_format_html_report_promotes_short_english_bold_heading_without_colon(self):
        import qclaw_mail_file

        html = "<html><body><p><strong>Catalysts to Watch</strong></p><ul><li>A</li></ul></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<h3>Catalysts to Watch</h3>", formatted)
        self.assertNotIn("<p><strong>Catalysts to Watch</strong></p>", formatted)

    def test_format_html_report_promotes_standalone_core_fact_label_to_h4(self):
        import qclaw_mail_file

        html = "<html><body><p><strong>核心事实</strong></p><ul><li>A</li></ul></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<h4>核心事实</h4>", formatted)
        self.assertNotIn("<p><strong>核心事实</strong></p>", formatted)

    def test_format_html_report_wraps_inline_action_label(self):
        import qclaw_mail_file

        html = "<html><body><p><strong>投资启示</strong>：关注NVDA与MU。</p></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<p><strong>投资启示</strong></p>", formatted)
        self.assertIn("<p>关注NVDA与MU。</p>", formatted)
        self.assertNotIn("<p><strong>投资启示</strong>：关注NVDA与MU。</p>", formatted)

    def test_format_html_report_wraps_standalone_action_label_block(self):
        import qclaw_mail_file

        html = "<html><body><h4>投资启示</h4><p>关注NVDA与MU。</p></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<p><strong>投资启示</strong></p>", formatted)
        self.assertIn("<p>关注NVDA与MU。</p>", formatted)
        self.assertNotIn("<h4>投资启示</h4><p>关注NVDA与MU。</p>", formatted)

    def test_format_html_report_wraps_signal_block(self):
        import qclaw_mail_file

        html = "<html><body><h4>为什么重要</h4><p>这会影响估值锚。</p></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<p><strong>为什么重要</strong></p>", formatted)
        self.assertIn("<p>这会影响估值锚。</p>", formatted)

    def test_format_html_report_rewrites_legacy_callout_boxes_to_fixed_labels(self):
        import qclaw_mail_file

        html = (
            '<html><body>'
            '<div class="action-box"><div class="callout-title">投资启示</div><p>关注估值修复。</p></div>'
            '<div class="signal-box"><div class="callout-title">信号</div><p>成交量回暖。</p></div>'
            '</body></html>'
        )
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<p><strong>投资启示</strong></p>", formatted)
        self.assertIn("<p>关注估值修复。</p>", formatted)
        self.assertIn("<p><strong>信号</strong></p>", formatted)
        self.assertIn("<p>成交量回暖。</p>", formatted)
        self.assertNotIn('class="action-box"', formatted)
        self.assertNotIn('class="signal-box"', formatted)

    def test_format_html_report_distinguishes_principle_rule_redline_reminder(self):
        import qclaw_mail_file

        html = (
            "<html><body>"
            "<p><strong>原则</strong>：先分事实和观点。</p>"
            "<p><strong>规则</strong>：核心事实每条一句。</p>"
            "<p><strong>底线</strong>：不要误归因。</p>"
            "<p><strong>提醒</strong>：关注时效性。</p>"
            "</body></html>"
        )
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn('class="principle-box"', formatted)
        self.assertIn('class="rule-box"', formatted)
        self.assertIn('class="redline-box"', formatted)
        self.assertIn('class="reminder-box"', formatted)

    def test_format_html_report_promotes_time_horizon_label_to_h4(self):
        import qclaw_mail_file

        html = "<html><body><p><strong>短期（1-5天）</strong></p><ul><li>A</li></ul></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn('<h3 class="horizon-heading">短期（1-5天）</h3>', formatted)
        self.assertNotIn("<p><strong>短期（1-5天）</strong></p>", formatted)

    def test_format_html_report_promotes_medium_term_label_to_horizon_heading(self):
        import qclaw_mail_file

        html = "<html><body><p><strong>中期（1-4周）</strong></p><ul><li>A</li></ul></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn('<h3 class="horizon-heading">中期（1-4周）</h3>', formatted)
        self.assertNotIn("<p><strong>中期（1-4周）</strong></p>", formatted)

    def test_format_html_report_normalizes_existing_h3_horizon_heading(self):
        import qclaw_mail_file

        html = "<html><body><h3>短期（1-5天）</h3><ul><li>A</li></ul></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn('<h3 class="horizon-heading">短期（1-5天）</h3>', formatted)

    def test_format_html_report_strips_highlight_inside_heading(self):
        import qclaw_mail_file

        html = '<html><body><h3><span class="highlight">NVDA GTC</span> 前瞻</h3><p>正文</p></body></html>'
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<h3>NVDA GTC 前瞻</h3>", formatted)
        self.assertNotIn('<h3><span class="highlight">', formatted)

    def test_format_html_report_strips_emojis_locally(self):
        import qclaw_mail_file

        html = "<html><body><h2>Executive Summary 🔥</h2><p>市场当前🙂主要围绕 AI 主线展开。</p></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<h2>Executive Summary </h2>", formatted)
        self.assertIn("<p>市场当前主要围绕 AI 主线展开。</p>", formatted)
        self.assertNotIn("🔥", formatted)
        self.assertNotIn("🙂", formatted)

    def test_single_stage_prompt_enforces_attribution(self):
        import qclaw_mail_file

        emails = [{
            "subject": "attr",
            "from_name": "Broker",
            "from": "broker@example.com",
            "date": "2026-03-16 00:00:00+08:00",
            "body": "Shawn Kim says SRAM is a complement to HBM.",
        }]
        prompts = {}

        def fake_generate(system_prompt, user_prompt, emails=None):
            prompts["system"] = system_prompt
            prompts["user"] = user_prompt
            return """{
              "executive_summary": {
                "market_background": "半导体推理链路仍是焦点",
                "key_signals": ["Shawn Kim 观点不能等同于发件机构 house view"]
              },
              "core_events": [
                {
                  "headline": "NVDA / MU 推理链路",
                  "core_facts": ["讨论 LPU 与 SRAM 路线"],
                  "market_views": [
                    {"source": "行业交流", "stance": "积极", "thesis": "HBM 仍是关键补充"}
                  ],
                  "action": "关注 NVDA 与 MU",
                  "attribution_note": "邮件转述 Shawn Kim 的观点，不是发件机构自有判断",
                  "source_evidence": ["Shawn Kim says SRAM is a complement to HBM."]
                }
              ],
              "local_news": [
                {"headline": "边缘信号", "signal": "市场继续关注 HBM", "importance": "影响情绪", "action": "跟踪 GTC"}
              ],
              "peripheral_intelligence": {
                "mapped_events": [],
                "cross_market_signals": []
              },
              "actionable_ideas": {
                "short_term": ["GTC 期间更多验证"],
                "medium_term": ["后续产品节奏"],
                "catalysts": [{"catalyst": "GTC", "time": "本周", "impact": "NVDA"}],
                "bottom_line": "聚焦推理链路",
                "next_update": "盘前关键节点"
              }
            }"""

        with patch.object(qclaw_mail_file, "generate_with_llm", side_effect=fake_generate):
            result = qclaw_mail_file.analyze_emails_with_llm(emails)

        self.assertIn("NVDA / MU 推理链路", result)
        self.assertIn("Shawn Kim says", prompts["user"])
        self.assertIn("你是一位对冲基金盘前晨报编辑，服务于一位重点覆盖 2-3 个板块的分析师", prompts["system"])
        self.assertIn("你的职责不是机械复述邮件，而是帮助分析师快速看清", prompts["system"])
        self.assertIn("市场大背景优先写宏观主线", prompts["system"])
        self.assertIn("语言要像盘前晨报，不像长报告", prompts["system"])
        self.assertIn("不能把外部引述、媒体报道、市场传闻误写成发件机构 house view", prompts["system"])
        self.assertNotIn("额外参考规范", prompts["system"])
        self.assertNotIn("不要把第三方被引述的观点错误写成发件机构观点", prompts["user"])
        self.assertNotIn("功能上线、版本升级、界面变化、一般性产品更新", prompts["user"])
        self.assertIn("`Executive Summary` 下面固定只放 `市场大背景` 和 `关键信号`", prompts["system"])
        self.assertIn("核心事实每条尽量一句话", prompts["system"])
        self.assertIn("关键信号、投资启示、Bottom Line 都优先写成短句", prompts["system"])
        self.assertIn("只返回合法 JSON，不要补充解释", prompts["user"])
        self.assertIn('"executive_summary"', prompts["system"])
        self.assertIn('"core_events"', prompts["system"])
        self.assertIn('"local_news"', prompts["system"])
        self.assertIn('"actionable_ideas"', prompts["system"])
        self.assertIn('"priority_rank"', prompts["system"])
        self.assertIn('"coverage_count"', prompts["system"])
        self.assertIn('"global_score"', prompts["system"])
        self.assertIn('"source_topics"', prompts["system"])
        self.assertIn('"linked_core_event_headlines"', prompts["system"])

    def test_batch_summary_prompt_requests_structured_attribution_fields(self):
        import qclaw_mail_file

        prompts = {}

        def fake_generate(system_prompt, user_prompt, emails=None):
            prompts["system"] = system_prompt
            prompts["user"] = user_prompt
            return """{
              "batch_index": 1,
              "batch_total": 1,
              "email_ids": [1],
              "topics": []
            }"""

        emails = [{
            "subject": "attr",
            "from_name": "Broker",
            "from": "broker@example.com",
            "date": "2026-03-16 00:00:00+08:00",
            "body": "Reports suggest NVDA may introduce an LPU chip. Shawn Kim says SRAM complements HBM.",
            "_analysis_index": 1,
            "_analysis_body": "Reports suggest NVDA may introduce an LPU chip. Shawn Kim says SRAM complements HBM.",
            "_analysis_body_len": 88,
        }]

        with patch.object(qclaw_mail_file, "generate_with_llm", side_effect=fake_generate):
            parsed = qclaw_mail_file.analyze_batch_summary_with_llm(emails, total_email_count=1, batch_index=1, batch_total=1)

        self.assertEqual(parsed["batch_index"], 1)
        self.assertIn("你是一位对冲基金盘前晨报编辑，服务于一位重点覆盖 2-3 个板块的分析师", prompts["system"])
        self.assertIn('"fact_subject"', prompts["system"])
        self.assertIn('"opinion_subject"', prompts["system"])
        self.assertIn('"source_evidence"', prompts["system"])
        self.assertIn("不能把转述者默认当作观点提出者", prompts["system"])
        self.assertIn("只返回合法 JSON", prompts["user"])

    def test_merge_prompt_discourages_trivial_updates(self):
        import qclaw_mail_file

        prompts = {}

        def fake_generate(system_prompt, user_prompt, emails=None):
            prompts["system"] = system_prompt
            prompts["user"] = user_prompt
            return """{
              "executive_summary": {
                "market_background": "市场情绪分化",
                "key_signals": ["功能小升级被显著降权"]
              },
              "core_events": [],
              "local_news": [
                {"headline": "边缘信号", "signal": "小升级被降权", "importance": "不影响核心判断", "action": "忽略"}
              ],
              "peripheral_intelligence": {
                "mapped_events": [],
                "cross_market_signals": []
              },
              "actionable_ideas": {
                "short_term": ["盘前新增验证"],
                "medium_term": ["后续再定价窗口"],
                "catalysts": [{"catalyst": "验证节点", "time": "本周", "impact": "相关板块"}],
                "bottom_line": "聚焦高信号强度主题",
                "next_update": "盘前关键节点"
              }
            }"""

        with patch.object(qclaw_mail_file, "generate_with_llm", side_effect=fake_generate):
            qclaw_mail_file.merge_batch_summaries_with_llm(
                [{"batch_index": 1, "batch_total": 1, "email_ids": [1], "topics": []}],
                total_email_count=1,
            )

        self.assertIn("你是一位对冲基金盘前晨报编辑，服务于一位重点覆盖 2-3 个板块的分析师", prompts["system"])
        self.assertIn("不要把 Actionable Ideas 写成待办清单", prompts["system"])
        self.assertIn("Actionable Ideas 要短、狠、可执行", prompts["system"])
        self.assertIn("Local News 不是次要垃圾桶", prompts["system"])
        self.assertIn("功能小升级", prompts["system"])
        self.assertIn("trivial 变化默认忽略或显著降权", prompts["system"])
        self.assertIn("市场大背景", prompts["system"])
        self.assertIn("关键信号", prompts["system"])
        self.assertIn("核心事实要尽量短", prompts["system"])
        self.assertIn("如果一句话已经表达出判断，就不要再追加第二句做弱信息量复述", prompts["system"])
        self.assertIn("只返回合法 JSON", prompts["user"])
        self.assertIn("Actionable Ideas` 不是剩余信息区", prompts["system"])

    def test_parse_report_payload_json_normalizes_schema(self):
        import qclaw_mail_file

        raw = """```json
        {
          "summary": {
            "background": "市场波动提升",
            "signals": ["HBM 链条仍是核心焦点"]
          },
          "core_events": [
            {
              "headline": "NVDA 供应链",
              "facts": ["供应链反馈仍偏积极"],
              "market_views": [{"source":"行业交流","stance":"积极","thesis":"资金仍偏向核心算力链"}],
              "investment_implication": "继续跟踪 NVDA 与 MU",
              "source_note": "邮件转述 Shawn Kim 的观点"
            }
          ],
          "local_news": [
            {"headline":"边缘信号","signal":"软件板块偏弱","importance":"反映风险偏好下降","action":"控制仓位"}
          ],
          "peripheral_intelligence": {
            "mapped_events": [
              {"event":"外围事件A","related_company":"AAPL","mapping":"映射到核心主题"}
            ],
            "cross_market_signals": [
              {"headline":"跨市场信号A","bullets":["能源与AI风险偏好同步变化"]}
            ]
          },
          "actionable_ideas": {
            "near_term": ["GTC 期间新增发布"],
            "mid_term": ["后续验证节点"],
            "catalysts": [{"catalyst":"GTC","time":"本周","impact":"NVDA"}],
            "bottom_line": "聚焦高质量主题",
            "next_update": "盘前关键节点"
          }
        }
        ```"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(payload["executive_summary"]["market_background"], "市场波动提升")
        self.assertEqual(payload["core_events"][0]["headline"], "NVDA 供应链")
        self.assertEqual(payload["actionable_ideas"]["short_term"][0]["idea"], "GTC 期间新增发布")

    def test_parse_report_payload_json_uses_yaml_fallback_for_near_json(self):
        import qclaw_mail_file

        raw = """
        {
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["HBM 链条仍是核心焦点"]
          },
          "core_events": [
            {
              "headline": "NVDA 供应链",
              "core_facts": ["供应链反馈仍偏积极"]
            }
          ],
          "local_news": [],
          "peripheral_intelligence": {"mapped_events": [], "cross_market_signals": []},
          "actionable_ideas": {
            "short_term": [
              {"idea": "GTC 期间新增发布", "priority_rank": 1}
            ],
            "medium_term": [],
            "catalysts": [],
            "bottom_line": "聚焦高质量主题"
          }
        }
        """

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(payload["core_events"][0]["headline"], "NVDA 供应链")
        self.assertEqual(payload["actionable_ideas"]["short_term"][0]["idea"], "GTC 期间新增发布")

    def test_parse_report_payload_json_sorts_core_events_after_normalization(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["排序测试"]
          },
          "core_events": [
            {
              "headline": "同rank但覆盖更低的主题",
              "priority_rank": 2,
              "coverage_count": 1,
              "global_score": 6.0,
              "core_facts": ["事实 A"]
            },
            {
              "headline": "高覆盖主题",
              "priority_rank": 2,
              "coverage_count": 4,
              "global_score": 8.0,
              "core_facts": ["事实 B"]
            },
            {
              "headline": "最高优先级主题",
              "priority_rank": 1,
              "coverage_count": 2,
              "global_score": 7.0,
              "core_facts": ["事实 C"]
            }
          ]
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(
            [item["headline"] for item in payload["core_events"]],
            ["高覆盖主题", "最高优先级主题", "同rank但覆盖更低的主题"],
        )

    def test_parse_report_payload_json_sorts_actionable_ideas_and_catalysts(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["排序测试"]
          },
          "actionable_ideas": {
            "short_term": [
              {"idea": "低优先级想法", "priority_rank": 4, "coverage_count": 1, "global_score": 6.0},
              {"idea": "高优先级想法", "priority_rank": 1, "coverage_count": 2, "global_score": 8.0}
            ],
            "medium_term": [
              {"idea": "中期低优先级", "priority_rank": 3, "coverage_count": 1, "global_score": 6.5},
              {"idea": "中期高优先级", "priority_rank": 1, "coverage_count": 1, "global_score": 7.5}
            ],
            "catalysts": [
              {"catalyst": "低优先级催化", "time": "T+5", "impact": "A", "priority_rank": 3, "coverage_count": 1, "global_score": 5.0},
              {"catalyst": "高优先级催化", "time": "T+1", "impact": "B", "priority_rank": 1, "coverage_count": 2, "global_score": 8.0}
            ],
            "bottom_line": "聚焦高优先级主题"
          }
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(
            [item["idea"] for item in payload["actionable_ideas"]["short_term"]],
            ["高优先级想法", "低优先级想法"],
        )
        self.assertEqual(
            [item["idea"] for item in payload["actionable_ideas"]["medium_term"]],
            ["中期高优先级", "中期低优先级"],
        )
        self.assertEqual(
            [item["catalyst"] for item in payload["actionable_ideas"]["catalysts"]],
            ["高优先级催化", "低优先级催化"],
        )

    def test_parse_report_payload_json_preserves_local_news_model_order(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["排序测试"]
          },
          "local_news": [
            {
              "headline": "低覆盖但模型主观更高",
              "priority_rank": 1,
              "coverage_count": 1,
              "global_score": 7.0,
              "signal": "信号 A",
              "importance": "重要性 A",
              "action": "动作 A"
            },
            {
              "headline": "高覆盖信号",
              "priority_rank": 3,
              "coverage_count": 3,
              "global_score": 6.5,
              "signal": "信号 B",
              "importance": "重要性 B",
              "action": "动作 B"
            },
            {
              "headline": "同覆盖但分数更高",
              "priority_rank": 2,
              "coverage_count": 1,
              "global_score": 8.0,
              "signal": "信号 C",
              "importance": "重要性 C",
              "action": "动作 C"
            }
          ]
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(
            [item["headline"] for item in payload["local_news"]],
            ["低覆盖但模型主观更高", "高覆盖信号", "同覆盖但分数更高"],
        )

    def test_parse_report_payload_json_derives_key_signals_from_core_events_first(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["模型原始信号A", "模型原始信号B"]
          },
          "core_events": [
            {
              "headline": "高覆盖核心主题",
              "priority_rank": 3,
              "coverage_count": 4,
              "global_score": 8.5,
              "core_facts": ["事实 A"]
            },
            {
              "headline": "次高覆盖核心主题",
              "priority_rank": 1,
              "coverage_count": 2,
              "global_score": 7.8,
              "core_facts": ["事实 B"]
            }
          ],
          "local_news": [
            {
              "headline": "特别值得关注的边缘信号",
              "priority_rank": 1,
              "coverage_count": 0,
              "global_score": 8.2,
              "signal": "信号 C",
              "importance": "重要性 C",
              "action": "动作 C"
            }
          ],
          "peripheral_intelligence": {
            "mapped_events": [],
            "cross_market_signals": [
              {
                "headline": "普通跨市场信号",
                "priority_rank": 3,
                "coverage_count": 0,
                "global_score": 6.0,
                "bullets": ["信号 D"]
              }
            ]
          }
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(
            payload["executive_summary"]["key_signals"][:3],
            ["高覆盖核心主题", "次高覆盖核心主题", "特别值得关注的边缘信号"],
        )
        self.assertNotIn("普通跨市场信号", payload["executive_summary"]["key_signals"][:3])

    def test_parse_report_payload_json_preserves_model_market_background(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场当前主要围绕 AI 竞赛节奏、广告恢复与消费季节性重估三条主线展开博弈。"
          },
          "core_events": [
            {
              "headline": "HBM 与推理链路仍是焦点",
              "priority_rank": 1,
              "coverage_count": 3,
              "global_score": 8.5,
              "core_facts": ["产业链继续围绕 HBM 供需与推理芯片节奏展开"]
            }
          ]
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(
            payload["executive_summary"]["market_background"],
            "市场当前主要围绕 AI 竞赛节奏、广告恢复与消费季节性重估三条主线展开博弈。",
        )

    def test_parse_report_payload_json_links_actionable_items_to_core_events(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["排序测试"]
          },
          "core_events": [
            {
              "headline": "NVDA 推理链路",
              "priority_rank": 1,
              "coverage_count": 3,
              "global_score": 9.0,
              "source_topics": ["NVDA", "推理"],
              "core_facts": ["事实 A"]
            },
            {
              "headline": "传媒广告恢复",
              "priority_rank": 2,
              "coverage_count": 2,
              "global_score": 7.5,
              "source_topics": ["META", "广告"],
              "core_facts": ["事实 B"]
            }
          ],
          "actionable_ideas": {
            "short_term": [
              {
                "idea": "优先跟踪 NVDA 推理链路验证",
                "priority_rank": 1,
                "coverage_count": 3,
                "global_score": 9.0,
                "source_topics": ["NVDA"],
                "linked_core_event_headlines": ["NVDA 推理链路"]
              }
            ],
            "medium_term": [
              {
                "idea": "继续观察广告恢复斜率",
                "priority_rank": 2,
                "coverage_count": 2,
                "global_score": 7.0,
                "source_topics": ["广告"]
              }
            ],
            "catalysts": [
              {
                "catalyst": "GTC",
                "time": "本周",
                "impact": "NVDA",
                "priority_rank": 1,
                "coverage_count": 3,
                "global_score": 8.5,
                "linked_core_event_headlines": ["NVDA 推理链路"]
              }
            ],
            "bottom_line": "聚焦高优先级主题"
          }
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(payload["core_events"][0]["core_event_id"], "core_event_1")
        self.assertEqual(payload["core_events"][1]["core_event_id"], "core_event_2")
        self.assertEqual(
            payload["actionable_ideas"]["short_term"][0]["linked_core_event_ids"],
            ["core_event_1"],
        )
        self.assertEqual(
            payload["actionable_ideas"]["medium_term"][0]["linked_core_event_ids"],
            ["core_event_2"],
        )
        self.assertEqual(
            payload["actionable_ideas"]["catalysts"][0]["linked_core_event_ids"],
            ["core_event_1"],
        )

    def test_parse_report_payload_json_dedupes_short_and_medium_term_ideas(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["去重测试"]
          },
          "actionable_ideas": {
            "short_term": [
              {"idea": "优先跟踪 NVDA 推理链路验证", "priority_rank": 1, "coverage_count": 3, "global_score": 9.0},
              {"idea": "优先跟踪 NVDA 推理链路验证", "priority_rank": 2, "coverage_count": 1, "global_score": 6.0},
              {"idea": "继续观察广告恢复斜率", "priority_rank": 3, "coverage_count": 2, "global_score": 7.0}
            ],
            "medium_term": [
              {"idea": "继续观察广告恢复斜率", "priority_rank": 1, "coverage_count": 3, "global_score": 8.0},
              {"idea": "关注未来 1-4 周内产业链验证", "priority_rank": 2, "coverage_count": 2, "global_score": 7.0}
            ],
            "catalysts": [],
            "bottom_line": "聚焦高优先级主题"
          }
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(
            [item["idea"] for item in payload["actionable_ideas"]["short_term"]],
            ["优先跟踪 NVDA 推理链路验证", "继续观察广告恢复斜率"],
        )
        self.assertEqual(
            [item["idea"] for item in payload["actionable_ideas"]["medium_term"]],
            ["关注未来 1-4 周内产业链验证"],
        )

    def test_build_priority_debug_summary_uses_headline_mapping(self):
        import qclaw_mail_file

        payload = {
            "core_events": [
                {
                    "core_event_id": "core_event_1",
                    "headline": "NVDA 推理链路",
                    "priority_rank": 1,
                    "coverage_count": 3,
                    "global_score": 9.0,
                }
            ],
            "actionable_ideas": {
                "short_term": [
                    {
                        "idea": "优先跟踪 NVDA 推理链路验证",
                        "priority_rank": 1,
                        "coverage_count": 3,
                        "global_score": 9.0,
                        "linked_core_event_ids": ["core_event_1"],
                    }
                ],
                "medium_term": [],
                "catalysts": [
                    {
                        "catalyst": "GTC",
                        "priority_rank": 1,
                        "coverage_count": 3,
                        "global_score": 8.5,
                        "linked_core_event_ids": ["core_event_1"],
                    }
                ],
            },
        }

        summary = qclaw_mail_file.build_priority_debug_summary(payload)

        self.assertIn("Key Coverage:", summary)
        self.assertIn("core_event_1", summary)
        self.assertIn("NVDA 推理链路", summary)
        self.assertIn("短期想法:", summary)
        self.assertIn("linked=NVDA 推理链路", summary)
        self.assertIn("Catalysts:", summary)

    def test_parse_report_payload_json_sorts_before_limiting_results(self):
        import qclaw_mail_file

        core_events = []
        for idx in range(1, 8):
            core_events.append({
                "headline": f"普通主题{idx}",
                "priority_rank": 10 + idx,
                "coverage_count": 1,
                "global_score": 1.0,
                "core_facts": [f"事实 {idx}"],
            })
        core_events.append({
            "headline": "本应被保留的最高优先级主题",
            "priority_rank": 1,
            "coverage_count": 5,
            "global_score": 9.5,
            "core_facts": ["关键事实"],
        })

        raw = json.dumps({
            "executive_summary": {
                "market_background": "市场波动提升",
                "key_signals": ["排序测试"],
            },
            "core_events": core_events,
        }, ensure_ascii=False)

        payload = qclaw_mail_file.parse_report_payload_json(raw)

        self.assertEqual(len(payload["core_events"]), 6)
        self.assertEqual(payload["core_events"][0]["headline"], "本应被保留的最高优先级主题")
        self.assertNotIn("普通主题7", [item["headline"] for item in payload["core_events"]])

    def test_render_report_html_uses_fixed_template(self):
        import qclaw_mail_file

        html = qclaw_mail_file.render_report_html(
            {
                "executive_summary": {
                    "market_background": "市场背景 A",
                    "key_signals": ["关键信号 B"],
                },
                "core_events": [
                    {
                        "headline": "主题一",
                        "core_facts": ["事实 1"],
                        "market_views": [{"source": "Morgan Stanley", "stance": "谨慎乐观", "thesis": "观点 1", "highlight_phrases": ["观点 1"]}],
                        "action": "行动建议",
                        "highlight_phrases": ["行动建议"],
                        "attribution_note": "邮件转述第三方观点",
                        "source_evidence": ["according to X"],
                    }
                ],
                "local_news": [
                    {"headline":"边缘信号一","signal":"信号内容","importance":"重要性说明","action":"动作建议","highlight_phrases":["动作建议"]}
                ],
                "peripheral_intelligence": {
                    "mapped_events": [{"event":"外围事件A","related_company":"AAPL","mapping":"映射说明"}],
                    "cross_market_signals": [{"headline":"跨市场信号A","bullets":["信号一"],"highlight_phrases":["信号一"]}],
                },
                "actionable_ideas": {
                    "short_term": ["短期催化"],
                    "medium_term": ["中期催化"],
                    "catalysts": [{"catalyst":"财报","time":"Mar 20","impact":"NVDA"}],
                    "bottom_line": "总结句",
                    "next_update": "盘前30 mins",
                },
            },
            source_emails=[
                {"subject": "MS note", "body": "Morgan Stanley update", "from_name": "A"},
                {"subject": "JPM note", "body": "J.P. Morgan update", "from_name": "B"},
            ],
        )

        self.assertIn("<h2>Executive Summary</h2>", html)
        self.assertIn("<strong>市场大背景:</strong>", html)
        self.assertIn("市场背景 A", html)
        self.assertIn("<strong>关键信号:</strong>", html)
        self.assertIn("<h2>Key Coverage | 核心事件与市场观点</h2>", html)
        self.assertIn("<th>观点来源</th>", html)
        self.assertIn("<p><strong>投资启示</strong></p>", html)
        self.assertIn("<h2>Local News | 容易被忽略的信号</h2>", html)
        self.assertIn("<p><strong>信号</strong></p>", html)
        self.assertIn("<p>信号内容</p>", html)
        self.assertIn("<p><strong>为什么重要</strong></p>", html)
        self.assertIn("<p><strong>Action</strong></p>", html)
        self.assertIn("<h2>Peripheral Intelligence | 外围信息/类比映射</h2>", html)
        self.assertIn("<th>外围事件</th>", html)
        self.assertIn("<h2>Actionable Ideas</h2>", html)
        self.assertIn("<h3>短期(1-5天)</h3>", html)
        self.assertIn("<th>Catalyst</th>", html)
        self.assertIn("Prepared by: AI Research Assistant", html)
        self.assertIn("Source: MS + JPM", html)
        self.assertIn('<span class="highlight">观点 1</span>', html)
        self.assertIn('<span class="highlight">行动建议</span>', html)
        self.assertIn('<span class="highlight">信号一</span>', html)
        self.assertNotIn("Next Update:", html)
        self.assertNotIn("归因提醒", html)
        self.assertNotIn("来源依据", html)

    def test_parse_report_payload_separates_core_fact_and_action_highlights(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["高亮拆分测试"]
          },
          "core_events": [
            {
              "headline": "普通主题",
              "core_facts": ["公司宣布新版本上线"],
              "action": "估值折扣创造entry point",
              "highlight_phrases": ["估值折扣创造entry point"]
            }
          ]
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)
        event = payload["core_events"][0]

        self.assertEqual(event["core_fact_highlight_phrases"], [])
        self.assertIn("估值折扣创造entry point", event["action_highlight_phrases"])

    def test_render_report_html_uses_fact_specific_highlights(self):
        import qclaw_mail_file

        html = qclaw_mail_file.render_report_html(
            {
                "executive_summary": {
                    "market_background": "市场背景 A",
                    "key_signals": ["关键信号 B"],
                },
                "core_events": [
                    {
                        "headline": "主题一",
                        "core_facts": ["公司宣布新版本上线"],
                        "core_fact_highlight_phrases": [],
                        "market_views": [],
                        "action": "估值折扣创造entry point",
                        "action_highlight_phrases": ["估值折扣创造entry point"],
                        "highlight_phrases": ["估值折扣创造entry point"],
                    }
                ],
                "local_news": [
                    {
                        "headline": "边缘信号一",
                        "signal": "普通信号",
                        "importance": "普通重要性",
                        "action": "普通动作",
                        "highlight_phrases": [],
                    }
                ],
                "peripheral_intelligence": {
                    "mapped_events": [],
                    "cross_market_signals": [],
                },
                "actionable_ideas": {
                    "short_term": [],
                    "medium_term": [],
                    "catalysts": [],
                    "bottom_line": "总结句",
                },
            }
        )

        self.assertIn("<li>公司宣布新版本上线</li>", html)
        self.assertIn('<span class="highlight">估值折扣创造entry point</span>', html)
        self.assertNotIn('<li><span class="highlight">公司宣布新版本上线</span></li>', html)

    def test_parse_report_payload_separates_local_news_highlights(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["拆分测试"]
          },
          "local_news": [
            {
              "headline": "边缘信号一",
              "signal": "只是普通更新",
              "importance": "系统性流动性收缩",
              "action": "估值折扣创造entry point",
              "highlight_phrases": ["估值折扣创造entry point"]
            }
          ]
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)
        item = payload["local_news"][0]

        self.assertEqual(item["signal_highlight_phrases"], [])
        self.assertIn("系统性流动性收缩", item["importance_highlight_phrases"])
        self.assertIn("估值折扣创造entry point", item["action_highlight_phrases"])

    def test_render_report_html_uses_local_news_specific_highlights(self):
        import qclaw_mail_file

        html = qclaw_mail_file.render_report_html(
            {
                "executive_summary": {
                    "market_background": "市场背景 A",
                    "key_signals": ["关键信号 B"],
                },
                "core_events": [],
                "local_news": [
                    {
                        "headline": "边缘信号一",
                        "signal": "只是普通更新",
                        "importance": "系统性流动性收缩",
                        "action": "估值折扣创造entry point",
                        "signal_highlight_phrases": [],
                        "importance_highlight_phrases": ["系统性流动性收缩"],
                        "action_highlight_phrases": ["估值折扣创造entry point"],
                        "highlight_phrases": ["估值折扣创造entry point"],
                    }
                ],
                "peripheral_intelligence": {
                    "mapped_events": [],
                    "cross_market_signals": [],
                },
                "actionable_ideas": {
                    "short_term": [],
                    "medium_term": [],
                    "catalysts": [],
                    "bottom_line": "总结句",
                },
            }
        )

        self.assertIn("<p>只是普通更新</p>", html)
        self.assertIn('<span class="highlight">系统性流动性收缩</span>', html)
        self.assertIn('<span class="highlight">估值折扣创造entry point</span>', html)
        self.assertNotIn('<span class="highlight">只是普通更新</span>', html)

    def test_parse_report_payload_splits_market_view_highlights(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["市场观点拆分测试"]
          },
          "core_events": [
            {
              "headline": "主题一",
              "market_views": [
                {
                  "source": "Morgan Stanley",
                  "stance": "强烈看多",
                  "thesis": "估值折扣创造entry point",
                  "highlight_phrases": ["估值折扣创造entry point"]
                }
              ]
            }
          ]
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)
        row = payload["core_events"][0]["market_views"][0]

        self.assertIn("强烈看多", row["stance_highlight_phrases"])
        self.assertIn("估值折扣创造entry point", row["thesis_highlight_phrases"])
        self.assertNotIn("Morgan Stanley", row["thesis_highlight_phrases"])

    def test_render_market_views_table_does_not_highlight_source(self):
        import qclaw_mail_file

        html = qclaw_mail_file.render_market_views_table([
            {
                "source": "Morgan Stanley",
                "stance": "强烈看多",
                "thesis": "估值折扣创造entry point",
                "stance_highlight_phrases": ["强烈看多"],
                "thesis_highlight_phrases": ["估值折扣创造entry point"],
            }
        ])

        self.assertIn("<strong>Morgan Stanley</strong>", html)
        self.assertIn('<span class="highlight">强烈看多</span>', html)
        self.assertIn('<span class="highlight">估值折扣创造entry point</span>', html)
        self.assertNotIn('<span class="highlight">Morgan Stanley</span>', html)

    def test_parse_report_payload_splits_cross_market_signal_highlights(self):
        import qclaw_mail_file

        raw = """{
          "executive_summary": {
            "market_background": "市场波动提升",
            "key_signals": ["跨市场高亮拆分测试"]
          },
          "peripheral_intelligence": {
            "mapped_events": [],
            "cross_market_signals": [
              {
                "headline": "跨市场信号A",
                "bullets": ["系统性流动性收缩"],
                "highlight_phrases": ["系统性流动性收缩"]
              }
            ]
          }
        }"""

        payload = qclaw_mail_file.parse_report_payload_json(raw)
        item = payload["peripheral_intelligence"]["cross_market_signals"][0]

        self.assertEqual(item["headline"], "跨市场信号A")
        self.assertIn("系统性流动性收缩", item["bullet_highlight_phrases"])

    def test_render_report_html_does_not_highlight_cross_market_headline(self):
        import qclaw_mail_file

        html = qclaw_mail_file.render_report_html(
            {
                "executive_summary": {
                    "market_background": "市场背景 A",
                    "key_signals": ["关键信号 B"],
                },
                "core_events": [],
                "local_news": [],
                "peripheral_intelligence": {
                    "mapped_events": [],
                    "cross_market_signals": [
                        {
                            "headline": "跨市场信号A",
                            "bullets": ["系统性流动性收缩"],
                            "bullet_highlight_phrases": ["系统性流动性收缩"],
                        }
                    ],
                },
                "actionable_ideas": {
                    "short_term": [],
                    "medium_term": [],
                    "catalysts": [],
                    "bottom_line": "总结句",
                },
            }
        )

        self.assertIn("<strong>跨市场信号A</strong>", html)
        self.assertIn('<span class="highlight">系统性流动性收缩</span>', html)
        self.assertNotIn('<span class="highlight">跨市场信号A</span>', html)

    def test_derive_highlight_phrases_prefers_judgment_over_numbers(self):
        import qclaw_mail_file

        text = "这是危机公关/注意力转移，且效率差距扩大是结构性问题；24%、$260亿、NVDA都不该高亮。"
        phrases = qclaw_mail_file.derive_highlight_phrases(text, limit=6)

        self.assertIn("危机公关/注意力转移", phrases)
        self.assertIn("效率差距扩大是结构性问题", phrases)
        self.assertNotIn("24%", phrases)
        self.assertNotIn("$260亿", phrases)
        self.assertNotIn("NVDA", phrases)

    def test_escape_with_highlights_avoids_nested_spans(self):
        import qclaw_mail_file

        html = qclaw_mail_file.escape_with_highlights(
            "Planting Seeds for Growth",
            ["Planting Seeds for Growth", "Planting Seeds", "Growth"],
        )

        self.assertEqual(html.count('class="highlight"'), 1)


if __name__ == "__main__":
    unittest.main()
