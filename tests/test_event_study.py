import unittest

from src.event_study import run_event_study


class EventStudyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.result = run_event_study()

    def test_expected_targets_and_windows_are_present(self):
        keys = {
            (row["target"], row["window_start"], row["window_end"])
            for row in self.result["rows"]
        }
        expected = {
            (symbol, lower, upper)
            for symbol in ("AMZN", "NVDA", "PLTR")
            for lower, upper in ((-1, 1), (-5, 5))
        }
        self.assertEqual(keys, expected)

    def test_space_x_stress_vector_matches_frozen_snapshot(self):
        shock = self.result["shock_vectors"]["spacex_ipo"]
        self.assertAlmostEqual(shock["AMZN"], -0.0633959703, places=8)
        self.assertAlmostEqual(shock["NVDA"], -0.0522444195, places=8)
        self.assertAlmostEqual(shock["PLTR"], -0.0527920083, places=8)


if __name__ == "__main__":
    unittest.main()
