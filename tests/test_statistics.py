import unittest

from ai_content_agent.science import statistics


class StatisticsTests(unittest.TestCase):
    def test_mean(self):
        self.assertEqual(statistics.mean([1, 2, 3]), 2.0)
        self.assertEqual(statistics.mean([]), 0.0)

    def test_sample_stddev(self):
        self.assertEqual(statistics.sample_stddev([5, 5, 5]), 0.0)
        self.assertGreater(statistics.sample_stddev([1, 2, 3, 4, 5]), 0.0)

    def test_cohens_d_positive_when_variant_larger(self):
        control = [1, 2, 3, 4, 5]
        variant = [6, 7, 8, 9, 10]
        d = statistics.cohens_d(control, variant)
        self.assertGreater(d, 0)

    def test_cohens_d_symmetry(self):
        control = [1, 2, 3, 4, 5]
        variant = [3, 4, 5, 6, 7]
        d = statistics.cohens_d(control, variant)
        self.assertAlmostEqual(d, -statistics.cohens_d(variant, control))

    def test_two_sample_p_value_identical_groups(self):
        p = statistics.two_sample_p_value([1, 2, 3], [1, 2, 3])
        self.assertAlmostEqual(p, 1.0, places=6)

    def test_two_sample_p_value_large_separation(self):
        control = list(range(1, 30))
        variant = [value + 20 for value in control]
        p = statistics.two_sample_p_value(control, variant)
        self.assertLess(p, 0.01)

    def test_two_sample_p_value_small_samples(self):
        self.assertEqual(statistics.two_sample_p_value([1], [2]), 1.0)

    def test_students_t_cdf_median(self):
        self.assertAlmostEqual(statistics.students_t_cdf(0.0, 10), 0.5, places=6)

    def test_normal_cdf_known_values(self):
        self.assertAlmostEqual(statistics.normal_cdf(0.0), 0.5, places=6)
        self.assertAlmostEqual(statistics.normal_cdf(1.96), 0.975, places=3)


if __name__ == "__main__":
    unittest.main()
