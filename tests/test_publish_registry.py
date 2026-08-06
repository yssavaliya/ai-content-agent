import unittest

from ai_content_agent.publish.instagram import InstagramPublisher
from ai_content_agent.publish.providers.dry_run import DryRunPublisher
from ai_content_agent.publish.registry import PublishRegistry
from ai_content_agent.settings import Settings


def make_settings(**overrides) -> Settings:
    base = {
        "log_level": "INFO",
        "database_path": "agent.db",
        "opencode_command": "opencode",
        "instagram_enabled": False,
        "image_provider": "local",
    }
    base.update(overrides)
    return Settings(**base)


class PublishRegistryTests(unittest.TestCase):
    def test_returns_dry_run_when_not_enabled(self):
        publisher = PublishRegistry.build_publisher(make_settings())
        self.assertIsInstance(publisher, DryRunPublisher)

    def test_returns_instagram_when_configured(self):
        publisher = PublishRegistry.build_publisher(
            make_settings(
                instagram_publish_enabled=True,
                instagram_access_token="tok",
                instagram_account_id="111",
            )
        )
        self.assertIsInstance(publisher, InstagramPublisher)

    def test_falls_back_to_dry_run_when_misconfigured(self):
        publisher = PublishRegistry.build_publisher(
            make_settings(
                instagram_publish_enabled=True,
                instagram_access_token=None,
                instagram_account_id=None,
            )
        )
        self.assertIsInstance(publisher, DryRunPublisher)


if __name__ == "__main__":
    unittest.main()
