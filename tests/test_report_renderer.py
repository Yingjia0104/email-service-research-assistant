import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class ReportRendererTests(SmokeTestHelpers, unittest.TestCase):
    test_format_html_report_uses_local_date_title = (
        LegacySmokeMixin.test_format_html_report_uses_local_date_title
    )
    test_format_html_report_injects_meta_with_sources = (
        LegacySmokeMixin.test_format_html_report_injects_meta_with_sources
    )
    test_save_report_returns_stable_filename_and_keeps_timestamped_archive = (
        LegacySmokeMixin.test_save_report_returns_stable_filename_and_keeps_timestamped_archive
    )
    test_format_html_report_removes_existing_model_meta_block = (
        LegacySmokeMixin.test_format_html_report_removes_existing_model_meta_block
    )
    test_format_html_report_promotes_bold_paragraph_heading_to_h3 = (
        LegacySmokeMixin.test_format_html_report_promotes_bold_paragraph_heading_to_h3
    )
    test_format_html_report_promotes_short_english_bold_heading_without_colon = (
        LegacySmokeMixin.test_format_html_report_promotes_short_english_bold_heading_without_colon
    )
    test_format_html_report_does_not_promote_executive_or_action_labels_to_h2 = (
        LegacySmokeMixin.test_format_html_report_does_not_promote_executive_or_action_labels_to_h2
    )
    test_format_html_report_promotes_standalone_core_fact_label_to_h4 = (
        LegacySmokeMixin.test_format_html_report_promotes_standalone_core_fact_label_to_h4
    )
    test_format_html_report_wraps_inline_action_label = (
        LegacySmokeMixin.test_format_html_report_wraps_inline_action_label
    )
    test_format_html_report_wraps_standalone_action_label_block = (
        LegacySmokeMixin.test_format_html_report_wraps_standalone_action_label_block
    )
    test_format_html_report_wraps_signal_block = (
        LegacySmokeMixin.test_format_html_report_wraps_signal_block
    )
    test_format_html_report_rewrites_legacy_callout_boxes_to_fixed_labels = (
        LegacySmokeMixin.test_format_html_report_rewrites_legacy_callout_boxes_to_fixed_labels
    )
    test_format_html_report_distinguishes_principle_rule_redline_reminder = (
        LegacySmokeMixin.test_format_html_report_distinguishes_principle_rule_redline_reminder
    )
    test_format_html_report_promotes_time_horizon_label_to_h4 = (
        LegacySmokeMixin.test_format_html_report_promotes_time_horizon_label_to_h4
    )
    test_format_html_report_promotes_medium_term_label_to_horizon_heading = (
        LegacySmokeMixin.test_format_html_report_promotes_medium_term_label_to_horizon_heading
    )
    test_format_html_report_normalizes_existing_h3_horizon_heading = (
        LegacySmokeMixin.test_format_html_report_normalizes_existing_h3_horizon_heading
    )
    test_format_html_report_strips_highlight_inside_heading = (
        LegacySmokeMixin.test_format_html_report_strips_highlight_inside_heading
    )
    test_format_html_report_strips_emojis_locally = (
        LegacySmokeMixin.test_format_html_report_strips_emojis_locally
    )
    test_render_report_html_uses_fact_specific_highlights = (
        LegacySmokeMixin.test_render_report_html_uses_fact_specific_highlights
    )
    test_render_report_html_uses_local_news_specific_highlights = (
        LegacySmokeMixin.test_render_report_html_uses_local_news_specific_highlights
    )
    test_render_market_views_table_does_not_highlight_source = (
        LegacySmokeMixin.test_render_market_views_table_does_not_highlight_source
    )
    test_render_report_html_does_not_highlight_cross_market_headline = (
        LegacySmokeMixin.test_render_report_html_does_not_highlight_cross_market_headline
    )
    test_derive_highlight_phrases_prefers_judgment_over_numbers = (
        LegacySmokeMixin.test_derive_highlight_phrases_prefers_judgment_over_numbers
    )
    test_escape_with_highlights_avoids_nested_spans = (
        LegacySmokeMixin.test_escape_with_highlights_avoids_nested_spans
    )
