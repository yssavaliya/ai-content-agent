import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_SRC = ROOT / "src" / "ai_content_agent"
ANIME_SRC = ROOT / "ai-anime-agent" / "src" / "ai_content_agent"

# Files that are intentionally different in the ai-anime-agent instance.
INTENTIONAL_DIFFERENCES = {
    "anime/generator.py",
    "anime/metadata.py",
    "prompts/creator.md",
    "prompts/research.md",
}


def _files(base: Path) -> dict[str, Path]:
    return {
        path.relative_to(base).as_posix(): path
        for path in base.rglob("*")
        if path.is_file() and "__pycache__" not in path.parts and path.suffix in {".py", ".md"}
    }


def _text(path: Path) -> str:
    return path.read_bytes().decode("utf-8").replace("\r\n", "\n")


@unittest.skipUnless(ANIME_SRC.exists(), "ai-anime-agent instance not present")
class VariantSyncTests(unittest.TestCase):
    """ai-anime-agent is a copy of the main package. Fail when a fix lands in only one of them."""

    def test_both_instances_ship_the_same_modules(self):
        self.assertEqual(sorted(_files(ROOT_SRC)), sorted(_files(ANIME_SRC)))

    def test_shared_modules_are_identical(self):
        root_files, anime_files = _files(ROOT_SRC), _files(ANIME_SRC)
        drifted = [
            name
            for name in sorted(root_files)
            if name in anime_files
            and name not in INTENTIONAL_DIFFERENCES
            and _text(root_files[name]) != _text(anime_files[name])
        ]
        self.assertEqual(
            drifted,
            [],
            "These files differ between src/ and ai-anime-agent/src/. Copy the fix to both, or add the "
            "file to INTENTIONAL_DIFFERENCES if the difference is deliberate.",
        )


if __name__ == "__main__":
    unittest.main()
