import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class LlmClientTests(SmokeTestHelpers, unittest.TestCase):
    test_parse_batch_summary_json_from_code_fence = (
        LegacySmokeMixin.test_parse_batch_summary_json_from_code_fence
    )
    test_primary_network_failure_falls_back_to_backup = (
        LegacySmokeMixin.test_primary_network_failure_falls_back_to_backup
    )
    test_missing_primary_key_skips_to_backup = (
        LegacySmokeMixin.test_missing_primary_key_skips_to_backup
    )
    test_missing_primary_and_backup1_skips_to_backup2 = (
        LegacySmokeMixin.test_missing_primary_and_backup1_skips_to_backup2
    )
    test_missing_primary_backup1_backup2_skips_to_backup3 = (
        LegacySmokeMixin.test_missing_primary_backup1_backup2_skips_to_backup3
    )
    test_generate_with_llm_pins_to_successful_backup_within_same_run = (
        LegacySmokeMixin.test_generate_with_llm_pins_to_successful_backup_within_same_run
    )
    test_analyze_sanitizes_inline_image_payloads = (
        LegacySmokeMixin.test_analyze_sanitizes_inline_image_payloads
    )
    test_call_llm_api_sends_multimodal_payload = (
        LegacySmokeMixin.test_call_llm_api_sends_multimodal_payload
    )
    test_call_llm_api_uses_openai_gpt5_chat_options = (
        LegacySmokeMixin.test_call_llm_api_uses_openai_gpt5_chat_options
    )
    test_call_llm_api_uses_openai_json_schema_response_format_when_available = (
        LegacySmokeMixin.test_call_llm_api_uses_openai_json_schema_response_format_when_available
    )
    test_call_llm_api_ignores_json_schema_response_format_for_non_openai_provider = (
        LegacySmokeMixin.test_call_llm_api_ignores_json_schema_response_format_for_non_openai_provider
    )
    test_moonshot_cn_uses_direct_session = LegacySmokeMixin.test_moonshot_cn_uses_direct_session
    test_dashscope_uses_direct_session = LegacySmokeMixin.test_dashscope_uses_direct_session
    test_gpt_backup_uses_proxy_session = LegacySmokeMixin.test_gpt_backup_uses_proxy_session
