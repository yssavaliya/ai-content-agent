import unittest

from ai_content_agent.settings import load_settings


class ExtendedSettingsTests(unittest.TestCase):
    def _env(self, **overrides) -> dict[str, str]:
        env = {
            "LOG_LEVEL": "INFO",
            "DATABASE_PATH": "agent.db",
            "OPENCODE_COMMAND": "opencode",
            "INSTAGRAM_ENABLED": "false",
            "IMAGE_PROVIDER": "local",
        }
        env.update(overrides)
        return env

    def test_defaults(self):
        settings = load_settings(env=self._env())
        self.assertEqual(settings.opencode_timeout_seconds, 60)
        self.assertEqual(settings.notify_channels, ("dryrun",))
        self.assertFalse(settings.instagram_publish_enabled)
        self.assertFalse(settings.instagram_analytics_enabled)
        self.assertEqual(settings.media_host, "none")
        self.assertEqual(settings.scientist_min_sample_size, 10)
        self.assertEqual(settings.scientist_min_effect, 0.15)
        self.assertEqual(settings.scientist_apply_threshold, 0.6)

    def test_parses_notify_channels_csv(self):
        settings = load_settings(
            env=self._env(NOTIFY_CHANNELS="discord, slack, telegram")
        )
        self.assertEqual(settings.notify_channels, ("discord", "slack", "telegram"))

    def test_parses_instagram_publish_settings(self):
        settings = load_settings(
            env=self._env(
                INSTAGRAM_PUBLISH_ENABLED="true",
                INSTAGRAM_ACCESS_TOKEN="tok",
                INSTAGRAM_ACCOUNT_ID="111",
                INSTAGRAM_API_VERSION="19.0",
                MEDIA_HOST="github",
                MEDIA_HOST_REPO="owner/repo",
            )
        )
        self.assertTrue(settings.instagram_publish_enabled)
        self.assertEqual(settings.instagram_access_token, "tok")
        self.assertEqual(settings.instagram_api_version, "19.0")
        self.assertEqual(settings.media_host, "github")

    def test_parses_numeric_settings(self):
        settings = load_settings(
            env=self._env(
                OPENCODE_TIMEOUT_SECONDS="180",
                SCIENTIST_MIN_SAMPLE_SIZE="15",
                SCIENTIST_MIN_EFFECT="0.2",
                SCIENTIST_APPLY_THRESHOLD="0.7",
                SMTP_PORT="465",
            )
        )
        self.assertEqual(settings.opencode_timeout_seconds, 180)
        self.assertEqual(settings.scientist_min_sample_size, 15)
        self.assertEqual(settings.scientist_min_effect, 0.2)
        self.assertEqual(settings.scientist_apply_threshold, 0.7)
        self.assertEqual(settings.smtp_port, 465)

    def test_rejects_invalid_numeric(self):
        with self.assertRaises(ValueError):
            load_settings(env=self._env(SCIENTIST_MIN_SAMPLE_SIZE="many"))

    def test_quoted_env_values_are_unquoted(self):
        settings = load_settings(env=self._env(NOTIFY_CHANNELS='"email"'))
        self.assertEqual(settings.notify_channels, ("email",))


if __name__ == "__main__":
    unittest.main()
