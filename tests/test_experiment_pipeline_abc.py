import unittest

from tests.test_smoke import SmokeTestHelpers


class ExperimentPipelineABCTests(SmokeTestHelpers, unittest.TestCase):
    def test_prepare_text_only_emails_suppresses_raw_images(self):
        import experiment_pipeline_abc as experiment

        prepared = experiment.prepare_text_only_emails(
            [
                {
                    "subject": "sample",
                    "body": "Hello\n\n[Image #1]\nWorld",
                    "attachments": [],
                }
            ],
            suppress_raw_images=True,
        )

        self.assertEqual(len(prepared), 1)
        self.assertTrue(prepared[0]["_analysis_visual_context_applied"])
        self.assertEqual(prepared[0]["_visual_status"], "disabled")
        self.assertIn("Hello", prepared[0]["_analysis_body"])

    def test_build_uncapped_raw_image_blocks_keeps_all_images(self):
        import experiment_pipeline_abc as experiment
        emails = [
            {
                "subject": "sample",
                "body": "",
                "attachments": [
                    {
                        "filename": f"chart_{idx}.png",
                        "content_type": "image/png",
                        "size": 1024,
                        "kind": "image",
                        "data_url": self.make_png_data_url(width=200 + idx, height=200 + idx),
                    }
                    for idx in range(9)
                ],
            }
        ]

        blocks = experiment.build_uncapped_raw_image_blocks(
            emails,
            api_config={"model": "gpt-4.1", "supports_vision": True},
        )

        self.assertEqual(len(blocks), 18)
