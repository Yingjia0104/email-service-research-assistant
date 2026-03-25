import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class StorageTests(SmokeTestHelpers, unittest.TestCase):
    test_mark_processed_marks_only_given_uids = (
        LegacySmokeMixin.test_mark_processed_marks_only_given_uids
    )
    test_add_emails_allows_same_uid_in_different_mailboxes = (
        LegacySmokeMixin.test_add_emails_allows_same_uid_in_different_mailboxes
    )
    test_normalize_email_image_keys_collapses_legacy_runtime_index_variants = (
        LegacySmokeMixin.test_normalize_email_image_keys_collapses_legacy_runtime_index_variants
    )
    test_finalize_report_success_is_atomic_for_log_and_processed = (
        LegacySmokeMixin.test_finalize_report_success_is_atomic_for_log_and_processed
    )
