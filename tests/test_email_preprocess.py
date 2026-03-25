import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class EmailPreprocessTests(SmokeTestHelpers, unittest.TestCase):
    test_strip_signature_and_disclaimer = (
        LegacySmokeMixin.test_strip_signature_and_disclaimer
    )
    test_sanitize_email_body_strips_leading_header_and_trailing_disclaimer = (
        LegacySmokeMixin.test_sanitize_email_body_strips_leading_header_and_trailing_disclaimer
    )
    test_split_emails_for_analysis_when_context_too_long = (
        LegacySmokeMixin.test_split_emails_for_analysis_when_context_too_long
    )
    test_split_emails_for_analysis_splits_two_long_emails = (
        LegacySmokeMixin.test_split_emails_for_analysis_splits_two_long_emails
    )
    test_build_emails_text_preserves_visual_context_when_truncating = (
        LegacySmokeMixin.test_build_emails_text_preserves_visual_context_when_truncating
    )
    test_prepare_emails_for_analysis_appends_visual_context = (
        LegacySmokeMixin.test_prepare_emails_for_analysis_appends_visual_context
    )
    test_prepare_emails_for_analysis_inserts_visual_context_at_image_positions = (
        LegacySmokeMixin.test_prepare_emails_for_analysis_inserts_visual_context_at_image_positions
    )
