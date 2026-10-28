import unittest
from unittest.mock import MagicMock, patch

from ai_content_agent.analytics.buffer import BufferAnalyticsClient
from ai_content_agent.analytics.registry import AnalyticsRegistry
from ai_content_agent.settings import Settings


class BufferAnalyticsClientTests(unittest.TestCase):
    @patch("ai_content_agent.analytics.buffer.requests.post")
    def test_fetch_post_metrics(self, mock_post: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "data": {
                "post": {
                    "id": "post_123",
                    "metrics": [
                        {"type": "impressions", "value": 1500},
                        {"type": "reach", "value": 1200},
                        {"type": "reactions", "value": 180},
                        {"type": "comments", "value": 24},
                        {"type": "shares", "value": 12},
                        {"type": "saves", "value": 45},
                    ],
                }
            }
        }
        mock_post.return_value = mock_resp

        client = BufferAnalyticsClient(access_token="tok_123")
        metrics = client.fetch_post_metrics("post_123")

        self.assertEqual(metrics.media_id, "post_123")
        self.assertEqual(metrics.impressions, 1500)
        self.assertEqual(metrics.reach, 1200)
        self.assertEqual(metrics.likes, 180)
        self.assertEqual(metrics.comments, 24)
        self.assertEqual(metrics.shares, 12)
        self.assertEqual(metrics.saves, 45)
        self.assertEqual(metrics.engagement, 180 + 24 + 12 + 45)
        self.assertAlmostEqual(metrics.engagement_rate, round((180 + 24 + 12 + 45) / 1200, 4))

    def test_registry_selects_buffer_analytics_when_token_configured(self) -> None:
        settings = MagicMock(spec=Settings)
        settings.buffer_access_token = "tok_buf"
        settings.instagram_analytics_enabled = False

        provider = AnalyticsRegistry.build_provider(settings)
        self.assertIsInstance(provider, BufferAnalyticsClient)
        self.assertEqual(provider.access_token, "tok_buf")

