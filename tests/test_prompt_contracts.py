import unittest

from tests.test_smoke import LegacySmokeMixin, SmokeTestHelpers


class PromptContractTests(SmokeTestHelpers, unittest.TestCase):
    test_single_stage_prompt_enforces_attribution = (
        LegacySmokeMixin.test_single_stage_prompt_enforces_attribution
    )
    test_batch_summary_prompt_requests_structured_attribution_fields = (
        LegacySmokeMixin.test_batch_summary_prompt_requests_structured_attribution_fields
    )
    test_single_stage_analysis_requests_report_response_format = (
        LegacySmokeMixin.test_single_stage_analysis_requests_report_response_format
    )
    test_merge_prompt_discourages_trivial_updates = (
        LegacySmokeMixin.test_merge_prompt_discourages_trivial_updates
    )
