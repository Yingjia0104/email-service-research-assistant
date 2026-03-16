import asyncio
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
        format_spec = "spec"
        real_cfg = {"api_key": "backup-key", "base_url": "https://backup.example/v1", "model": "backup-model"}
        calls = []

        def fake_load():
            qclaw_mail_file.KIMI_BACKUP_CONFIG.update(real_cfg)
            return {"api_key": "primary-key", "base_url": "https://primary.example/v1", "model": "primary-model"}

        def fake_call(api_config, system_prompt, user_prompt):
            calls.append(api_config["base_url"])
            if api_config["base_url"] == "https://primary.example/v1":
                raise RuntimeError("network down")
            return "<html><head></head><body>ok</body></html>"

        with patch.object(qclaw_mail_file, "load_kimi_config", side_effect=fake_load):
            with patch.object(qclaw_mail_file, "call_kimi_api", side_effect=fake_call):
                with patch.object(qclaw_mail_file.time, "sleep", return_value=None):
                    result = qclaw_mail_file.analyze_emails_with_kimi(emails, format_spec)

        self.assertIn("ok", result)
        self.assertEqual(
            calls,
            [
                "https://primary.example/v1",
                "https://primary.example/v1",
                "https://backup.example/v1",
            ],
        )

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
            return "<html><head></head><body>ok</body></html>"

        with patch.object(
            qclaw_mail_file,
            "load_kimi_config",
            return_value={"api_key": "primary-key", "base_url": "https://primary.example/v1", "model": "primary-model"},
        ):
            with patch.object(qclaw_mail_file, "call_kimi_api_with_retries", side_effect=lambda *args, **kwargs: fake_call(*args[:3])):
                result = qclaw_mail_file.analyze_emails_with_kimi(emails, "spec")

        self.assertIn("ok", result)
        self.assertIn("[图片附件已省略", prompts["user_prompt"])
        self.assertNotIn("data:image/png;base64", prompts["user_prompt"])

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

        html = "<html><body><h1>AI Morning Brief | March 17, 2026</h1><h2>Executive Summary</h2></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<title>AI Morning Brief | 2026-03-16</title>", formatted)
        self.assertIn("<h1>AI Morning Brief | 2026-03-16</h1>", formatted)
        self.assertNotIn("March 17, 2026", formatted)

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

        self.assertIn('<div class="action-box"><strong>投资启示：</strong>关注NVDA与MU。</div>', formatted)
        self.assertNotIn("<p><strong>投资启示</strong>：关注NVDA与MU。</p>", formatted)

    def test_format_html_report_promotes_time_horizon_label_to_h4(self):
        import qclaw_mail_file

        html = "<html><body><p><strong>短期（1-5天）</strong></p><ul><li>A</li></ul></body></html>"
        formatted = qclaw_mail_file.format_html_report(html)

        self.assertIn("<h4>短期（1-5天）</h4>", formatted)
        self.assertNotIn("<p><strong>短期（1-5天）</strong></p>", formatted)

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

        def fake_generate(system_prompt, user_prompt):
            prompts["system"] = system_prompt
            prompts["user"] = user_prompt
            return "<html><head></head><body>ok</body></html>"

        with patch.object(qclaw_mail_file, "generate_with_kimi", side_effect=fake_generate):
            result = qclaw_mail_file.analyze_emails_with_kimi(emails, "spec")

        self.assertIn("ok", result)
        self.assertIn("Shawn Kim says", prompts["user"])
        self.assertIn("不能改写成 `MS认为...`", prompts["system"])
        self.assertIn("不要把第三方被引述的观点错误写成发件机构观点", prompts["user"])

    def test_batch_summary_prompt_requests_structured_attribution_fields(self):
        import qclaw_mail_file

        prompts = {}

        def fake_generate(system_prompt, user_prompt):
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

        with patch.object(qclaw_mail_file, "generate_with_kimi", side_effect=fake_generate):
            parsed = qclaw_mail_file.analyze_batch_summary_with_kimi(emails, total_email_count=1, batch_index=1, batch_total=1)

        self.assertEqual(parsed["batch_index"], 1)
        self.assertIn('"fact_subject"', prompts["system"])
        self.assertIn('"opinion_subject"', prompts["system"])
        self.assertIn('"source_evidence"', prompts["system"])
        self.assertIn("不要把引述来的第三方观点升级成发件机构观点", prompts["user"])


if __name__ == "__main__":
    unittest.main()
