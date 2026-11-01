import unittest
from unittest.mock import MagicMock, patch

from ai_content_agent.analytics.buffer import BufferAnalyticsClient
from ai_content_agent.analytics.registry import AnalyticsRegistry
from ai_content_agent.settings import Settings


class BufferAnalyticsQueryTests(unittest.TestCase):
    def test_query_declares_the_id_variable_with_the_schema_type(self) -> None:
        # Buffer rejected `$id: String!` with: Variable "$id" of type "String!" used in position expecting
        # type "PostId!" (seen in the Actions log of the 1 Nov daily run), so every metrics call failed.
        from ai_content_agent.analytics.buffer import GET_POST_METRICS_QUERY

        self.assertIn("$id: PostId!", GET_POST_METRICS_QUERY)
        self.assertNotIn("String!", GET_POST_METRICS_QUERY)


class MissingMetricsAreNotZeroTests(unittest.TestCase):
    def fetch(self, metrics):
        with patch("ai_content_agent.analytics.buffer.requests.post") as mock_post:
            mock_post.return_value = MagicMock(status_code=200)
            mock_post.return_value.json.return_value = {"data": {"post": {"id": "p", "metrics": metrics}}}
            return BufferAnalyticsClient("tok").fetch_post_metrics("p")

    def test_a_post_with_no_metrics_has_no_data_not_zeros(self) -> None:
        metrics = self.fetch([])
        self.assertFalse(metrics.has_data())
        self.assertEqual(
            (metrics.likes, metrics.comments, metrics.shares, metrics.saves, metrics.engagement, metrics.engagement_rate),
            (None, None, None, None, None, None),
        )

    def test_only_returned_metrics_are_filled_in(self) -> None:
        metrics = self.fetch([{"type": "impressions", "value": 400}, {"type": "reactions", "value": 20}])
        self.assertTrue(metrics.has_data())
        self.assertEqual((metrics.likes, metrics.comments, metrics.shares, metrics.saves), (20, None, None, None))
        self.assertEqual(metrics.engagement, 20)
        self.assertEqual(metrics.engagement_rate, 0.05)

    def test_a_real_zero_is_kept(self) -> None:
        metrics = self.fetch([{"type": "impressions", "value": 300}, {"type": "reactions", "value": 0}])
        self.assertEqual((metrics.likes, metrics.engagement, metrics.engagement_rate), (0, 0, 0.0))


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

