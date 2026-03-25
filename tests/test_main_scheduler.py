import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class MainSchedulerTests(SmokeTestHelpers, unittest.TestCase):
    test_smtp_timeout_maps_to_504 = LegacySmokeMixin.test_smtp_timeout_maps_to_504
    test_smtp_auth_failure_maps_to_502 = LegacySmokeMixin.test_smtp_auth_failure_maps_to_502
    test_get_us_market_open_time_uses_real_dst = (
        LegacySmokeMixin.test_get_us_market_open_time_uses_real_dst
    )
    test_get_next_market_trigger_time_skips_weekend = (
        LegacySmokeMixin.test_get_next_market_trigger_time_skips_weekend
    )
    test_is_in_supplement_window_uses_market_session_bounds = (
        LegacySmokeMixin.test_is_in_supplement_window_uses_market_session_bounds
    )
    test_message_local_date_converts_cross_timezone_mail = (
        LegacySmokeMixin.test_message_local_date_converts_cross_timezone_mail
    )
    test_match_allowed_sender_supports_exact_and_suffix = (
        LegacySmokeMixin.test_match_allowed_sender_supports_exact_and_suffix
    )
    test_all_expected_senders_arrived_uses_session_matches = (
        LegacySmokeMixin.test_all_expected_senders_arrived_uses_session_matches
    )
    test_should_trigger_early_daily_reports_missing_sales_and_session_context = (
        LegacySmokeMixin.test_should_trigger_early_daily_reports_missing_sales_and_session_context
    )
    test_should_trigger_early_daily_requires_quiet_period = (
        LegacySmokeMixin.test_should_trigger_early_daily_requires_quiet_period
    )
    test_should_trigger_early_daily_succeeds_when_all_conditions_met = (
        LegacySmokeMixin.test_should_trigger_early_daily_succeeds_when_all_conditions_met
    )
    test_get_briefing_session_start_handles_weekend_rollover = (
        LegacySmokeMixin.test_get_briefing_session_start_handles_weekend_rollover
    )
    test_trigger_supplement_analysis_requires_daily_first = (
        LegacySmokeMixin.test_trigger_supplement_analysis_requires_daily_first
    )
    test_clean_extracted_attachment_text_strips_links_and_disclaimer = (
        LegacySmokeMixin.test_clean_extracted_attachment_text_strips_links_and_disclaimer
    )
    test_clean_extracted_attachment_text_truncates_long_msg_body = (
        LegacySmokeMixin.test_clean_extracted_attachment_text_truncates_long_msg_body
    )
    test_verify_api_key_uses_fresh_config = (
        LegacySmokeMixin.test_verify_api_key_uses_fresh_config
    )
