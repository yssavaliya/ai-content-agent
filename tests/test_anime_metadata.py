import unittest
from unittest.mock import MagicMock

import requests

from ai_content_agent.anime.metadata import (
    _FALLBACK_ANIME_RECORDS,
    AnimeCharacter,
    AnimeMetadataClient,
    AnimeMetadataError,
    AnimeRecord,
)


class AnimeMetadataTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = AnimeMetadataClient(timeout_seconds=5, max_retries=2, allow_fallback=True)

    def test_anime_record_dataclass_fields(self) -> None:
        rec = AnimeRecord(
            id="101",
            title="Steins;Gate",
            japanese_title="シュタインズ・ゲート",
            synopsis="Self-proclaimed mad scientist Rintaro Okabe accidentally invents a time machine.",
            genres=["Sci-Fi", "Thriller"],
            episode_count=24,
            status="finished",
            start_date="2011-04-06",
            rating="PG-13",
            average_rating=91.4,
            poster_image_url="https://media.kitsu.io/poster.jpg",
        )
        self.assertEqual(rec.id, "101")
        self.assertEqual(rec.title, "Steins;Gate")
        self.assertEqual(rec.episode_count, 24)
        self.assertEqual(rec.source_api, "kitsu")

    def test_anime_character_dataclass_fields(self) -> None:
        char = AnimeCharacter(
            id="c42",
            name="Rintaro Okabe",
            japanese_name="岡部 倫太郎",
            description="Founder of the Future Gadget Laboratory.",
            role="Main",
        )
        self.assertEqual(char.name, "Rintaro Okabe")
        self.assertEqual(char.role, "Main")

    def test_get_trending_returns_valid_records(self) -> None:
        records = self.client.get_trending(limit=3)
        self.assertIsInstance(records, list)
        self.assertGreater(len(records), 0)
        first = records[0]
        self.assertIsInstance(first, AnimeRecord)
        self.assertTrue(bool(first.title))
        self.assertTrue(bool(first.synopsis))

    def test_search_with_valid_query(self) -> None:
        results = self.client.search("Titan", limit=2)
        self.assertIsInstance(results, list)
        self.assertGreater(len(results), 0)
        self.assertTrue(any("Titan" in r.title for r in results))

    def test_search_empty_query_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.client.search("   ")

    def test_get_characters_empty_id_raises_value_error(self) -> None:
        with self.assertRaises(ValueError):
            self.client.get_characters("")

    def test_fallback_activated_on_connection_error(self) -> None:
        bad_session = MagicMock(spec=requests.Session)
        bad_session.headers = {}
        bad_session.get.side_effect = requests.ConnectionError("Network down")
        client = AnimeMetadataClient(session=bad_session, allow_fallback=True)

        fallback = client.get_trending(limit=2)
        self.assertEqual(len(fallback), 2)
        self.assertEqual(fallback[0].title, _FALLBACK_ANIME_RECORDS[0].title)
        self.assertEqual(fallback[0].source_api, "fallback")

    def test_error_raised_when_fallback_disabled(self) -> None:
        bad_session = MagicMock(spec=requests.Session)
        bad_session.headers = {}
        bad_session.get.side_effect = requests.ConnectionError("Network down")
        client = AnimeMetadataClient(session=bad_session, allow_fallback=False)

        with self.assertRaises(AnimeMetadataError):
            client.get_trending(limit=2)



if __name__ == "__main__":
    unittest.main()
