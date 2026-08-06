import unittest

from ai_content_agent.database.connection import DatabaseConnection
from ai_content_agent.science.experiments import (
    ExperimentRepository,
    compute_experiment_result,
)


class ExperimentRepositoryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.db = DatabaseConnection(db_path=":memory:")

    def tearDown(self) -> None:
        self.db.close()

    def _seed_post(self, external_id: str) -> int:
        cursor = self.db.execute(
            "INSERT INTO posts(external_id, caption, image_description, hashtags, created_at) VALUES (?, ?, ?, ?, ?)",
            (external_id, "caption", "desc", "[]", "2026-08-01T00:00:00Z"),
        )
        return cursor.lastrowid

    def _seed_metrics(self, post_id: int, rate: float) -> None:
        self.db.execute(
            "INSERT INTO post_metrics(post_id, media_id, engagement_rate, collected_at, raw_payload) VALUES (?, ?, ?, ?, ?)",
            (post_id, f"media-{post_id}", rate, "2026-08-06T00:00:00Z", "{}"),
        )

    def test_create_and_list_active(self):
        repository = ExperimentRepository(self.db)
        experiment_id = repository.create(
            name="caption-test",
            description="Testing captions",
            hypothesis="Short captions win",
            variable="caption-length",
        )
        self.assertGreater(experiment_id, 0)

        active = repository.list_active()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0].variable, "caption-length")

    def test_assign_post_validates_arm(self):
        repository = ExperimentRepository(self.db)
        experiment_id = repository.create(name="x", description="x")
        post_id = self._seed_post("m1")
        repository.assign_post(experiment_id, post_id, "variant")

        with self.assertRaises(ValueError):
            repository.assign_post(experiment_id, post_id, "unknown")

        self.assertEqual(repository.posts_for_arm(experiment_id, "variant"), [post_id])

    def test_complete_experiment(self):
        repository = ExperimentRepository(self.db)
        experiment_id = repository.create(name="x", description="x")
        repository.complete(experiment_id)
        self.assertEqual(repository.list_active(), [])

    def test_compute_result_requires_sample_size(self):
        repository = ExperimentRepository(self.db)
        experiment_id = repository.create(name="x", description="x", variable="approach")

        for index in range(2):
            control_post = self._seed_post(f"c{index}")
            variant_post = self._seed_post(f"v{index}")
            repository.assign_post(experiment_id, control_post, "control")
            repository.assign_post(experiment_id, variant_post, "variant")
            self._seed_metrics(control_post, 0.01)
            self._seed_metrics(variant_post, 0.02)

        result = compute_experiment_result(experiment_id, self.db, min_sample_size=10, min_effect=0.15)
        self.assertEqual(result.n_control, 2)
        self.assertEqual(result.n_variant, 2)
        self.assertFalse(result.sample_size_met)
        self.assertEqual(result.winner, "inconclusive")

    def test_compute_result_detects_variant_winner(self):
        repository = ExperimentRepository(self.db)
        experiment_id = repository.create(name="x", description="x", variable="approach")

        for index in range(2):
            control_post = self._seed_post(f"c{index}")
            variant_post = self._seed_post(f"v{index}")
            repository.assign_post(experiment_id, control_post, "control")
            repository.assign_post(experiment_id, variant_post, "variant")
            self._seed_metrics(control_post, 0.01 + index * 0.01)
            self._seed_metrics(variant_post, 0.20 + index * 0.01)

        result = compute_experiment_result(experiment_id, self.db, min_sample_size=2, min_effect=0.15)
        self.assertTrue(result.sample_size_met)
        self.assertTrue(result.significant)
        self.assertGreater(result.cohens_d, 0)
        self.assertEqual(result.winner, "variant")


if __name__ == "__main__":
    unittest.main()
