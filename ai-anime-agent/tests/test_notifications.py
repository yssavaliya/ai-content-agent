import unittest
from unittest.mock import MagicMock, patch

import requests

from ai_content_agent.notifications.channels import (
    DiscordChannel,
    DryRunChannel,
    NotificationChannel,
    NotificationError,
    SlackChannel,
    TelegramChannel,
    build_channels,
)
from ai_content_agent.notifications.notifier import Notifier
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


class ChannelTests(unittest.TestCase):
    def test_dry_run_channel_does_not_raise(self):
        DryRunChannel().send("subject", "body", {})

    @patch("ai_content_agent.notifications.channels.requests.post")
    def test_discord_channel_posts_webhook(self, mock_post):
        mock_post.return_value = MagicMock(status_code=204)
        DiscordChannel("https://discord.example/hook").send("s", "b", {"color": 123})
        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs["json"]["embeds"][0]["title"], "s")

    @patch("ai_content_agent.notifications.channels.requests.post")
    def test_discord_channel_raises_on_error(self, mock_post):
        mock_post.return_value = MagicMock(status_code=500, text="nope")
        with self.assertRaises(NotificationError):
            DiscordChannel("https://discord.example/hook").send("s", "b", {})

    @patch("ai_content_agent.notifications.channels.requests.post")
    def test_telegram_channel_posts(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        TelegramChannel("token", "chat-1").send("s", "b", {})
        url = mock_post.call_args.args[0]
        self.assertIn("/bottoken/sendMessage", url)

    @patch("ai_content_agent.notifications.channels.requests.post")
    def test_telegram_network_error_does_not_leak_bot_token(self, mock_post):
        mock_post.side_effect = requests.ConnectionError("failed for https://api.telegram.org/botSECRET123/sendMessage")
        with self.assertRaises(NotificationError) as ctx:
            TelegramChannel("SECRET123", "chat-1").send("s", "b", {})
        self.assertNotIn("SECRET123", str(ctx.exception))

    @patch("ai_content_agent.notifications.channels.requests.post")
    def test_slack_channel_posts(self, mock_post):
        mock_post.return_value = MagicMock(status_code=200)
        SlackChannel("https://slack.example/hook").send("s", "b", {})
        _, kwargs = mock_post.call_args
        self.assertIn("s", kwargs["json"]["text"])



class BuildChannelsTests(unittest.TestCase):
    def test_build_channels_defaults_to_dryrun(self):
        settings = make_settings()
        channels = build_channels(settings)
        self.assertEqual([c.name for c in channels], ["dryrun"])

    def test_build_channels_falls_back_to_dryrun_when_nothing_usable(self):
        settings = make_settings(notify_channels=("discord", "telegram", "slack"))
        channels = build_channels(settings)
        self.assertEqual([c.name for c in channels], ["dryrun"])

    def test_removed_email_channel_is_ignored(self):
        settings = make_settings(notify_channels=("email",))
        channels = build_channels(settings)
        self.assertEqual([c.name for c in channels], ["dryrun"])

    def test_build_channels_instantiates_configured(self):
        settings = make_settings(
            notify_channels=("discord", "telegram"),
            discord_webhook_url="https://discord.example/hook",
            telegram_bot_token="tok",
            telegram_chat_id="chat",
        )
        channels = build_channels(settings)
        self.assertEqual([c.name for c in channels], ["discord", "telegram"])


class RaisingChannel(NotificationChannel):
    @property
    def name(self) -> str:
        return "raising"

    def send(self, subject: str, body: str, metadata: dict) -> None:
        raise RuntimeError("boom")


class NotifierTests(unittest.TestCase):
    def test_notify_isolates_channel_failures(self):
        notifier = Notifier([RaisingChannel(), DryRunChannel()])
        results = notifier.notify("test", "s", "b")
        self.assertFalse(results["raising"])
        self.assertTrue(results["dryrun"])

    def test_send_failure_event_name(self):
        notifier = Notifier([DryRunChannel()])
        results = notifier.send_failure("s", "b")
        self.assertTrue(results["dryrun"])


if __name__ == "__main__":
    unittest.main()
