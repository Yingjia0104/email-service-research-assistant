import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class MultimodalPipelineTests(SmokeTestHelpers, unittest.TestCase):
    test_lightweight_image_classification_uses_fast_model = (
        LegacySmokeMixin.test_lightweight_image_classification_uses_fast_model
    )
    test_lightweight_image_classification_upgrades_market_chart_with_direct_signal = (
        LegacySmokeMixin.test_lightweight_image_classification_upgrades_market_chart_with_direct_signal
    )
    test_deep_image_analysis_prioritizes_social_signal_with_strong_model = (
        LegacySmokeMixin.test_deep_image_analysis_prioritizes_social_signal_with_strong_model
    )
    test_prepare_emails_for_analysis_appends_visual_context = (
        LegacySmokeMixin.test_prepare_emails_for_analysis_appends_visual_context
    )
    test_prepare_emails_for_analysis_inserts_visual_context_at_image_positions = (
        LegacySmokeMixin.test_prepare_emails_for_analysis_inserts_visual_context_at_image_positions
    )
    test_normalize_email_image_keys_collapses_legacy_runtime_index_variants = (
        LegacySmokeMixin.test_normalize_email_image_keys_collapses_legacy_runtime_index_variants
    )
