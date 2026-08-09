import tempfile
import unittest
from pathlib import Path

from ai_content_agent.settings import load_settings

REQUIRED_ENV = {
    "LOG_LEVEL": "DEBUG",
    "DATABASE_PATH": "agent.db",
    "OPENCODE_COMMAND": "opencode",
    "INSTAGRAM_ENABLED": "false",
    "IMAGE_PROVIDER": "local",
}


class SettingsTests(unittest.TestCase):
    def test_load_settings_from_environment(self):
        env = {
            "LOG_LEVEL": "DEBUG",
            "DATABASE_PATH": "agent.db",
            "OPENCODE_COMMAND": "opencode",
            "INSTAGRAM_ENABLED": "true",
            "IMAGE_PROVIDER": "local",
        }

        settings = load_settings(env=env)

        self.assertEqual(settings.log_level, "DEBUG")
        self.assertEqual(settings.database_path, "agent.db")
        self.assertEqual(settings.opencode_command, "opencode")
        self.assertTrue(settings.instagram_enabled)
        self.assertEqual(settings.image_provider, "local")

    def test_load_settings_from_env_file(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            env_file = Path(temp_dir) / ".env"
            env_file.write_text(
                "LOG_LEVEL=INFO\n"
                "DATABASE_PATH=agent.db\n"
                "OPENCODE_COMMAND=opencode\n"
                "INSTAGRAM_ENABLED=false\n"
                "IMAGE_PROVIDER=local\n"
            )

            settings = load_settings(env_file=env_file)

            self.assertEqual(settings.log_level, "INFO")
            self.assertEqual(settings.database_path, "agent.db")
            self.assertEqual(settings.opencode_command, "opencode")
            self.assertFalse(settings.instagram_enabled)
            self.assertEqual(settings.image_provider, "local")

    def test_load_settings_raises_if_missing_required(self):
        env = {
            "LOG_LEVEL": "DEBUG",
            "DATABASE_PATH": "agent.db",
            "OPENCODE_COMMAND": "opencode",
            "INSTAGRAM_ENABLED": "true",
        }

        with self.assertRaises(ValueError):
            load_settings(env=env)

    def test_load_settings_rejects_invalid_boolean(self):
        env = {
            "LOG_LEVEL": "DEBUG",
            "DATABASE_PATH": "agent.db",
            "OPENCODE_COMMAND": "opencode",
            "INSTAGRAM_ENABLED": "invalid",
            "IMAGE_PROVIDER": "local",
        }

        with self.assertRaises(ValueError):
            load_settings(env=env)

    def test_llm_provider_defaults_to_openai(self):
        settings = load_settings(env=REQUIRED_ENV)
        self.assertEqual(settings.llm_provider, "openai")

    def test_llm_provider_rejects_unknown_value(self):
        with self.assertRaises(ValueError):
            load_settings(env={**REQUIRED_ENV, "LLM_PROVIDER": "claude"})

    def test_gemini_provider_and_defaults(self):
        settings = load_settings(env={**REQUIRED_ENV, "LLM_PROVIDER": "gemini"})
        self.assertEqual(settings.llm_provider, "gemini")
        self.assertEqual(settings.gemini_model, "gemini-2.5-flash")
        self.assertIsNone(settings.gemini_api_key)

    def test_gemini_overrides(self):
        settings = load_settings(
            env={**REQUIRED_ENV, "LLM_PROVIDER": "gemini", "GEMINI_MODEL": "gemini-2.0-flash", "GEMINI_API_KEY": "k"}
        )
        self.assertEqual(settings.gemini_model, "gemini-2.0-flash")
        self.assertEqual(settings.gemini_api_key, "k")


if __name__ == "__main__":
    unittest.main()
