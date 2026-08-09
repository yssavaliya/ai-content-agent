import os


def base_env(**overrides) -> dict[str, str]:
    env = {
        "LOG_LEVEL": "DEBUG",
        "DATABASE_PATH": ":memory:",
        "OPENCODE_COMMAND": "opencode",
        "INSTAGRAM_ENABLED": "false",
        "IMAGE_PROVIDER": "local",
    }
    env.update(overrides)
    return env


class EnvTestCaseMixin:
    """Sets a known environment for tests that read settings."""

    def setUp(self) -> None:
        self._original_env = dict(os.environ)
        os.environ.update(base_env(**getattr(self, "env_overrides", {})))

    def tearDown(self) -> None:
        os.environ.clear()
        os.environ.update(self._original_env)
