import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class ReportPayloadTests(SmokeTestHelpers, unittest.TestCase):
    test_parse_report_payload_json_uses_yaml_fallback_for_near_json = (
        LegacySmokeMixin.test_parse_report_payload_json_uses_yaml_fallback_for_near_json
    )
    test_parse_report_payload_json_sorts_core_events_after_normalization = (
        LegacySmokeMixin.test_parse_report_payload_json_sorts_core_events_after_normalization
    )
    test_parse_report_payload_json_sorts_actionable_ideas_and_catalysts = (
        LegacySmokeMixin.test_parse_report_payload_json_sorts_actionable_ideas_and_catalysts
    )
    test_parse_report_payload_json_preserves_local_news_model_order = (
        LegacySmokeMixin.test_parse_report_payload_json_preserves_local_news_model_order
    )
    test_parse_report_payload_json_derives_key_signals_from_core_events_first = (
        LegacySmokeMixin.test_parse_report_payload_json_derives_key_signals_from_core_events_first
    )
    test_parse_report_payload_json_preserves_model_market_background = (
        LegacySmokeMixin.test_parse_report_payload_json_preserves_model_market_background
    )
    test_parse_report_payload_json_links_actionable_items_to_core_events = (
        LegacySmokeMixin.test_parse_report_payload_json_links_actionable_items_to_core_events
    )
    test_parse_report_payload_json_dedupes_short_and_medium_term_ideas = (
        LegacySmokeMixin.test_parse_report_payload_json_dedupes_short_and_medium_term_ideas
    )
    test_build_priority_debug_summary_uses_headline_mapping = (
        LegacySmokeMixin.test_build_priority_debug_summary_uses_headline_mapping
    )
    test_parse_report_payload_json_sorts_before_limiting_results = (
        LegacySmokeMixin.test_parse_report_payload_json_sorts_before_limiting_results
    )
    test_parse_report_payload_separates_core_fact_and_action_highlights = (
        LegacySmokeMixin.test_parse_report_payload_separates_core_fact_and_action_highlights
    )
    test_parse_report_payload_separates_local_news_highlights = (
        LegacySmokeMixin.test_parse_report_payload_separates_local_news_highlights
    )
    test_parse_report_payload_splits_market_view_highlights = (
        LegacySmokeMixin.test_parse_report_payload_splits_market_view_highlights
    )
    test_parse_report_payload_splits_cross_market_signal_highlights = (
        LegacySmokeMixin.test_parse_report_payload_splits_cross_market_signal_highlights
    )
