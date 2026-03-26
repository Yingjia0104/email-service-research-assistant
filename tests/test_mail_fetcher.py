import unittest

from app.mail import fetcher as app_mail_fetcher
from tests.test_smoke import SmokeTestHelpers


class _FakeAttachment:
    def __init__(self, *, long_filename, payload, content_type=""):
        self.longFilename = long_filename
        self.payload = payload
        self.content_type = content_type


class _FakeMessage:
    def __init__(self, attachments):
        self.attachments = attachments


class MailFetcherTests(SmokeTestHelpers, unittest.TestCase):
    def test_build_attachment_records_uses_long_filename_fallback(self):
        raw_bytes = app_mail_fetcher.extract_attachment_bytes(
            _FakeAttachment(long_filename="chart.png", payload=b"png-bytes", content_type="image/png")
        )
        self.assertEqual(raw_bytes, b"png-bytes")

        attachment = _FakeAttachment(long_filename="chart.png", payload=b"png-bytes", content_type="image/png")
        msg = _FakeMessage([attachment])
        _, embedded_images, attachment_records = app_mail_fetcher.build_attachment_records(
            msg,
            image_extensions=(".png", ".jpg"),
            max_multimodal_image_bytes=1024 * 1024,
            extract_attachment_bytes_fn=app_mail_fetcher.extract_attachment_bytes,
            clean_extracted_attachment_text_fn=lambda text, filename="": text,
            logger=None,
        )

        self.assertEqual(len(embedded_images), 1)
        self.assertEqual(embedded_images[0]["filename"], "chart.png")
        self.assertEqual(len(attachment_records), 1)
        self.assertEqual(attachment_records[0]["filename"], "chart.png")
